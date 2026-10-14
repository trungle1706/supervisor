"""One judge call with all guards: mask, wrap, bounded retries, truncation, timeout,
schema check, canary check, evidence grounding, injection floor.

Failure policy (analysis 02 section 3.3):

* Reply not valid for the schema, or cut off, after the retries -> fail suspicious:
  ``suspicion_bp = 10000``, label ``judge_output_invalid`` (a human looks at it).
* Canary token in the reply -> the judge obeyed the data: reply discarded,
  ``suspicion_bp = 10000``, label ``judge_manipulation``.
* Model unreachable or timed out after the retries -> no score, label
  ``judge_unavailable``: a coverage gap that is logged, never a silent pass.
* Injection markers in the data (deterministic pre-scan) floor the score at
  ``marker_floor_bp``: judge output can raise a score, never lower it below the floor.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from supervisor.adapters.llm.errors import LLMError, LLMOutputError, LLMTimeoutError, TruncatedError
from supervisor.core.ports import Masker
from supervisor.judge.masking import mask_version_of
from supervisor.judge.prompts import (
    OUTPUT_SCHEMA,
    RATIONALE_MAX_CHARS,
    JudgeOutputError,
    build_messages,
    canary_leaked,
    ground_spans,
    validate_output,
)
from supervisor.judge.prompts.build import new_canary, new_nonce
from supervisor.judge.router import JudgeModel

FAIL_SUSPICIOUS_BP = 10000
MIN_INPUT_CHARS = 1000


@dataclass(frozen=True)
class JudgeCall:
    """Result of one judge call. Scores are integer basis points (no floats)."""

    tier: int
    role: str
    checker_id: str
    model_id: str
    model_family: str
    model_version: str
    region: str
    mask_version: str
    prompt_hash: str
    is_mock: bool
    status: str  # ok | invalid_output | truncated | canary_leak | unavailable
    suspicion_bp: int | None
    label: str
    rationale_masked: str
    policy_refs: tuple[str, ...] = ()
    evidence_spans: tuple[Mapping[str, Any], ...] = ()
    marker_hits: tuple[str, ...] = ()
    attempts: int = 0
    latency_ms: int = 0
    tokens_in_est: int = 0
    tokens_out_est: int = 0
    truncated_chars: int = 0
    dropped_spans: int = 0
    floored: bool = False
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def flagged(self, threshold_bp: int) -> bool:
        return self.suspicion_bp is not None and self.suspicion_bp >= threshold_bp


def _code(exc: BaseException) -> str:
    """Fixed error code for evidence: the exception class only, never its message
    (messages can echo model output, the canary or customer text)."""
    return type(exc).__name__


def _raw_leaks(raw: Any, canary: str) -> bool:
    try:
        return canary_leaked(raw if isinstance(raw, Mapping) else {"raw": str(raw)}, canary)
    except (TypeError, ValueError):
        return canary.split("-", 1)[-1].lower() in str(raw).lower()


class TierJudge:
    """Base for :class:`Tier1Judge` and :class:`Tier2Judge`."""

    tier: int = 0

    def __init__(
        self,
        model: JudgeModel,
        masker: Masker,
        *,
        timeout_s: float = 120.0,
        max_retries: int = 1,
        max_input_chars: int = 12000,
        marker_floor_bp: int = 7000,
        nonce_factory: Callable[[], str] = new_nonce,
        canary_factory: Callable[[], str] = new_canary,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if model.tier != self.tier:
            raise ValueError(f"{type(self).__name__} needs a tier {self.tier} model")
        self.model = model
        self.masker = masker
        self.timeout_s = float(timeout_s)
        self.max_retries = max(0, int(max_retries))
        self.max_input_chars = int(max_input_chars)
        self.marker_floor_bp = int(marker_floor_bp)
        self._nonce = nonce_factory
        self._canary = canary_factory
        self._monotonic = monotonic

    def judge(
        self,
        events: Sequence[Mapping[str, Any] | BaseModel],
        *,
        agent_id: str,
        agent_version: str | None = None,
    ) -> JudgeCall:
        m = self.model
        base: dict[str, Any] = {
            "tier": self.tier,
            "role": m.role,
            "checker_id": m.checker_id,
            "model_id": m.model_id,
            "model_family": m.family,
            "model_version": m.model_version,
            "region": m.region,
            "mask_version": mask_version_of(self.masker),
            "is_mock": m.is_mock,
        }
        max_chars = self.max_input_chars
        start = self._monotonic()
        tokens_in = 0
        status, error = "unavailable", "no attempt"
        prompt = None
        attempts = 0
        for attempts in range(1, self.max_retries + 2):  # noqa: B007 - used after the loop
            prompt = build_messages(
                self.tier,
                events,
                self.masker,
                agent_id=agent_id,
                agent_version=agent_version,
                max_chars=max_chars,
                nonce_factory=self._nonce,
                canary_factory=self._canary,
            )
            tokens_in += prompt.chars // 4
            try:
                raw = m.chat.complete_json(prompt.messages, OUTPUT_SCHEMA, self.timeout_s)
            except TruncatedError as exc:
                status, error = "truncated", _code(exc)
                max_chars = max(MIN_INPUT_CHARS, max_chars // 2)  # shorter input next time
                continue
            except LLMTimeoutError as exc:
                status, error = "unavailable", _code(exc)
                continue
            except LLMOutputError as exc:
                status, error = "invalid_output", _code(exc)
                continue
            except LLMError as exc:
                status, error = "unavailable", _code(exc)
                continue
            if _raw_leaks(raw, prompt.canary):
                # Checked before the schema: a fooled model may put the canary anywhere.
                latency = int((self._monotonic() - start) * 1000)
                return self._canary_call(prompt, base, attempts, latency, tokens_in)
            try:
                out = validate_output(raw)
            except JudgeOutputError as exc:
                status, error = "invalid_output", _code(exc)
                continue
            latency = int((self._monotonic() - start) * 1000)
            tokens_out = len(json.dumps(raw, ensure_ascii=False)) // 4
            return self._accept(out, prompt, base, attempts, latency, tokens_in, tokens_out)
        latency = int((self._monotonic() - start) * 1000)
        assert prompt is not None
        common = {
            **base,
            "prompt_hash": prompt.prompt_hash,
            "status": status,
            "marker_hits": prompt.transcript.marker_hits,
            "attempts": attempts,
            "latency_ms": latency,
            "tokens_in_est": tokens_in,
            "truncated_chars": prompt.transcript.truncated_chars,
            "error": error,
        }
        if status == "unavailable":
            return JudgeCall(
                **common,
                suspicion_bp=None,
                label="judge_unavailable",
                rationale_masked="judge did not answer; coverage gap logged",
            )
        return JudgeCall(
            **common,
            suspicion_bp=FAIL_SUSPICIOUS_BP,
            label="judge_output_invalid",
            rationale_masked=f"judge reply rejected ({status}); scored as suspicious",
        )

    def _canary_call(
        self, prompt: Any, base: dict[str, Any], attempts: int, latency: int, tokens_in: int
    ) -> JudgeCall:
        # Never store the leaked reply: it holds the canary and attacker-chosen text.
        return JudgeCall(
            **base,
            prompt_hash=prompt.prompt_hash,
            marker_hits=prompt.transcript.marker_hits,
            attempts=attempts,
            latency_ms=latency,
            tokens_in_est=tokens_in,
            truncated_chars=prompt.transcript.truncated_chars,
            status="canary_leak",
            suspicion_bp=FAIL_SUSPICIOUS_BP,
            label="judge_manipulation",
            rationale_masked="judge reply contained the canary token: it followed "
            "instructions in the data; reply discarded",
            policy_refs=("JDG-01",),
        )

    def _accept(
        self,
        out: dict[str, Any],
        prompt: Any,
        base: dict[str, Any],
        attempts: int,
        latency: int,
        tokens_in: int,
        tokens_out: int,
    ) -> JudgeCall:
        common = {
            **base,
            "prompt_hash": prompt.prompt_hash,
            "marker_hits": prompt.transcript.marker_hits,
            "attempts": attempts,
            "latency_ms": latency,
            "tokens_in_est": tokens_in,
            "tokens_out_est": tokens_out,
            "truncated_chars": prompt.transcript.truncated_chars,
        }
        if canary_leaked(out, prompt.canary):
            return self._canary_call(prompt, base, attempts, latency, tokens_in)
        spans, dropped = ground_spans(out["evidence_spans"], prompt.transcript.masked_texts)
        score, label, floored = out["suspicion_bp"], out["label"], False
        refs = tuple(out["policy_refs"])
        if prompt.transcript.marker_hits and score < self.marker_floor_bp:
            score, floored = self.marker_floor_bp, True
            if label == "benign":
                label = "judge_manipulation"
            if "JDG-01" not in refs:
                refs = (*refs, "JDG-01")[:5]
        rationale = self.masker.mask(out["rationale"])[:RATIONALE_MAX_CHARS]
        return JudgeCall(
            **common,
            status="ok",
            suspicion_bp=int(score),
            label=label,
            rationale_masked=rationale,
            policy_refs=refs,
            evidence_spans=tuple(spans),
            dropped_spans=dropped,
            floored=floored,
        )
