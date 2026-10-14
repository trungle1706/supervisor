"""Build judge messages: mask, render, wrap as data, add the canary.

Nothing reaches the model without passing through the ``Masker`` first: every free-text
field of every event is masked here, also fields named ``*_masked`` (masking is
idempotent for the WP4 maskers; a second pass costs little and closes the gap when a
source skipped masking at capture).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from supervisor.core.ports import Masker
from supervisor.judge.prompts import schema, templates

Tier = int
_DELIM = re.compile(r"(<{2,}|>{2,})")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Deterministic pre-scan: phrases in the DATA that talk to a judge or reviewer. Any hit
# floors the suspicion score (judge output can only raise a score, never lower it).
INJECTION_MARKERS: tuple[str, ...] = (
    "suspicion_bp",
    "suspicion score",
    "verdict:",
    '"verdict"',
    "verdict allow",
    "rate this",
    "mark as safe",
    "mark this as safe",
    "label: benign",
    '"label": "benign"',
    "ignore previous",
    "ignore all previous",
    "ignore the above",
    "disregard previous",
    "system prompt",
    "your instructions",
    "hidden instructions",
    "secret token",
    "canary",
    "end_trace_data",
    "end data",
    "</data>",
    "[/inst]",
    "### system",
    "note to reviewer",
    "note to the reviewer",
    "to the judge",
    "to the monitor",
    "dear reviewer",
    "ai reviewer",
    "điểm nghi ngờ",
    "đánh giá an toàn",
    "đánh dấu an toàn",
    "bỏ qua mọi hướng dẫn",
    "bỏ qua các hướng dẫn",
    "bỏ qua hướng dẫn trước",
    "lời nhắn cho người đánh giá",
    "gửi người đánh giá",
    "gửi giám sát viên",
    "mã bí mật",
    "lời nhắc hệ thống",
    "chỉ dẫn ẩn",
)


def new_nonce() -> str:
    return secrets.token_hex(8)


def new_canary() -> str:
    return "CANARY-" + secrets.token_hex(8).upper()


def _field(event: Mapping[str, Any] | BaseModel, name: str) -> Any:
    if isinstance(event, BaseModel):
        return getattr(event, name, None)
    return event.get(name)


def escape_data(text: str) -> str:
    """Neutralise delimiter look-alikes and control characters inside data."""
    text = _CONTROL.sub(" ", text)
    return _DELIM.sub(lambda m: " ".join(m.group(0)), text)


@dataclass(frozen=True)
class RenderedTranscript:
    lines: tuple[str, ...]  # one JSON line per event (masked, escaped)
    masked_texts: tuple[str, ...]  # masked free text per event (for grounding quotes)
    truncated_chars: int
    marker_hits: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def render_transcript(
    events: Sequence[Mapping[str, Any] | BaseModel],
    masker: Masker,
    max_chars: int = 12000,
    max_field_chars: int = 2000,
) -> RenderedTranscript:
    """Mask every free-text field, render one JSON line per event, cap the size.

    When the transcript is longer than ``max_chars`` the middle events are dropped
    (first and last events kept) and the count of dropped characters is reported.
    """
    lines: list[str] = []
    masked_texts: list[str] = []
    for i, ev in enumerate(events):
        args = _field(ev, "args_masked")
        result = _field(ev, "result_masked")
        args_m = masker.mask(str(args))[:max_field_chars] if args is not None else None
        result_m = masker.mask(str(result))[:max_field_chars] if result is not None else None
        ts = _field(ev, "ts")
        record = {
            "index": i,
            "ts": ts.isoformat() if isinstance(ts, datetime) else (str(ts) if ts else None),
            "type": _field(ev, "event_type"),
            "agent": _field(ev, "agent_id"),
            "caller": _field(ev, "caller_agent_id"),
            "tool": _field(ev, "tool_name"),
            "status": _field(ev, "status"),
            "amount_minor": _field(ev, "amount_minor"),
            "currency": _field(ev, "currency"),
            "args": escape_data(args_m) if args_m is not None else None,
            "result": escape_data(result_m) if result_m is not None else None,
        }
        record = {k: v for k, v in record.items() if v is not None}
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=False))
        masked_texts.append(" ".join(x for x in (args_m, result_m) if x))
    truncated = 0
    total = sum(len(x) + 1 for x in lines)
    if total > max_chars and len(lines) > 2:
        head, tail = [lines[0]], [lines[-1]]
        budget = max_chars - len(head[0]) - len(tail[0])
        middle: list[str] = []
        for line in lines[1:-1]:
            if budget - len(line) - 1 < 0:
                break
            middle.append(line)
            budget -= len(line) + 1
        kept = head + middle + tail
        truncated = total - sum(len(x) + 1 for x in kept)
        dropped = len(lines) - len(kept)
        lines = [*head, *middle, json.dumps({"omitted_events": dropped}), *tail]
    if sum(len(x) + 1 for x in lines) > max_chars:  # few but huge events
        before = sum(len(x) + 1 for x in lines)
        per = max(200, max_chars // max(1, len(lines)))
        lines = [x if len(x) <= per else x[:per] + ' ..."}' for x in lines]
        truncated += before - sum(len(x) + 1 for x in lines)
    hits = scan_injection_markers("\n".join(masked_texts))
    return RenderedTranscript(tuple(lines), tuple(masked_texts), max(0, truncated), hits)


def scan_injection_markers(text: str) -> tuple[str, ...]:
    low = text.lower()
    return tuple(m for m in INJECTION_MARKERS if m in low)


def _policies_text() -> str:
    return "\n".join(f"- {pid}: {desc}" for pid, desc in templates.POLICY_CATALOG)


def system_template(tier: Tier) -> str:
    if tier not in (1, 2):
        raise ValueError("judge tier must be 1 or 2")
    return templates.TIER1_SYSTEM if tier == 1 else templates.TIER2_SYSTEM


def prompt_hash(tier: Tier) -> str:
    """SHA-256 of the unfilled templates + schema + version (logged in each verdict)."""
    blob = json.dumps(
        {
            "v": templates.PROMPT_VERSION,
            "system": system_template(tier),
            "user": templates.USER_TEMPLATE,
            "schema": schema.OUTPUT_SCHEMA,
            "policies": templates.POLICY_CATALOG,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class JudgePrompt:
    messages: tuple[Mapping[str, str], ...]
    canary: str
    nonce: str
    transcript: RenderedTranscript
    prompt_hash: str

    @property
    def chars(self) -> int:
        return sum(len(m["content"]) for m in self.messages)


def build_messages(
    tier: Tier,
    events: Sequence[Mapping[str, Any] | BaseModel],
    masker: Masker,
    *,
    agent_id: str,
    agent_version: str | None = None,
    max_chars: int = 12000,
    nonce_factory: Callable[[], str] = new_nonce,
    canary_factory: Callable[[], str] = new_canary,
) -> JudgePrompt:
    """System + user messages for one judge call. The transcript is masked first."""
    transcript = render_transcript(events, masker, max_chars=max_chars)
    nonce = nonce_factory()
    canary = canary_factory()
    system = system_template(tier).format(
        nonce=nonce,
        canary=canary,
        labels=", ".join(schema.LABELS),
        rationale_max=schema.RATIONALE_MAX_CHARS,
        policies=_policies_text(),
    )
    note = (
        f"\nNote: {transcript.truncated_chars} characters were cut from the middle "
        "of this trace to fit; judge what you see."
        if transcript.truncated_chars
        else ""
    )
    user = templates.USER_TEMPLATE.format(
        agent_id=escape_data(masker.mask(agent_id)),
        agent_version=escape_data(agent_version or "unknown"),
        n_events=len(events),
        truncation_note=note,
        nonce=nonce,
        data=transcript.text,
    )
    return JudgePrompt(
        messages=({"role": "system", "content": system}, {"role": "user", "content": user}),
        canary=canary,
        nonce=nonce,
        transcript=transcript,
        prompt_hash=prompt_hash(tier),
    )


def canary_leaked(output: Mapping[str, Any], canary: str) -> bool:
    """True if any part of the canary (the hex part is enough) appears in the output."""
    secret = canary.split("-", 1)[-1].lower()
    blob = json.dumps(output, ensure_ascii=False).lower()
    return secret in blob or canary.lower() in blob


def ground_spans(
    spans: Sequence[Mapping[str, Any]], masked_texts: Sequence[str]
) -> tuple[list[dict[str, Any]], int]:
    """Keep evidence spans whose quote occurs in the masked text of that event."""
    kept: list[dict[str, Any]] = []
    dropped = 0
    norm = [" ".join(t.split()).lower() for t in masked_texts]
    for s in spans:
        idx, quote = int(s["event_index"]), " ".join(str(s["quote"]).split()).lower()
        if 0 <= idx < len(norm) and quote and quote in norm[idx]:
            kept.append({"event_index": idx, "quote": str(s["quote"])})
        else:
            dropped += 1
    return kept, dropped
