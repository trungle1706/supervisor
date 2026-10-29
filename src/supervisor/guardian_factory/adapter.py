"""Adapter (WP-G1): a ``live`` guardian definition becomes a detector of the existing contract
(``supervisor.core.detectors.Detector``), so WP-G3 can attach it through guardian bindings.

WP-G3 mounts it: ``attach.LiveGuardians`` registers a live definition under the slug
``gf:<def_id>@<version>`` and the gate adds ``GATE-GUARDIAN-BLOCK`` for a deterministic block.

* ``regex``: the ``custom_rules`` machinery (``dlp_extras.Extras``), so the same time budget,
  the same hit cap and the same masking as a custom rule in ``config/detectors.yaml``.
* ``keyword_list``: a case-insensitive substring scan with the same replacement rules.
* ``policy``: a small deterministic evaluator (forbid wins, then permit, then the default).
* ``classifier``: delegates to the existing detector named by ``model_ref`` with the threshold
  of the definition; its findings are re-labelled and can only report or ask for approval.
* ``judge_prompt``: one ``complete_json`` call on the masked text; a failure to answer is a
  ``not_executed`` entry, never a pass.

Action mapping to the finding's ``action_hint`` (the gate clamps ``pause`` and ``block`` to
``report`` unless a gate rule says otherwise (R1 of ``core/detectors.py``; WP-G3 adds the block
rule for deterministic types)): ``block`` ->
``block``, ``require_approval`` -> ``pause``, ``redact`` -> ``transform``, ``log`` -> ``report``.
A model type never gets ``block`` or ``transform``: the definition schema refuses it, and the
adapter repeats the check.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Mapping
from typing import Any

from supervisor.core.detectors import (
    Entity,
    Finding,
    Fragment,
    SettingsSchema,
    clip,
    map_leaves,
    not_executed,
    walk_leaves,
)
from supervisor.guardian_factory import caps
from supervisor.guardian_factory.definition import GuardianDefinition, GuardianFactoryError

HINTS = {"block": "block", "require_approval": "pause", "redact": "transform", "log": "report"}
PARTS_BY_STAGE = {
    "preflight": ("args",),
    "input": ("args", "tool_results"),
    "tool_call": ("args",),
    "output": ("output",),
}
APPLIED = ("args", "output")  # parts whose masked copy a caller applies
HIT = 10_000
THRESHOLD = 5_000


def slug_of(def_id: str) -> str:
    return "guardian_" + def_id.replace("-", "_")


class _Base:
    """Fields of the Detector contract, set from the definition."""

    presets: Mapping[str, int] = {"balanced": THRESHOLD}
    protocols = ("all",)
    settings_schema = SettingsSchema()

    def __init__(self, d: GuardianDefinition, today: Callable[[], dt.date] | None = None) -> None:
        self.d = d
        self.slug = slug_of(d.id)
        self.name = d.name
        self.version = f"{d.lifecycle.version}.0.0"
        self.sides = ("output",) if d.stage == "output" else ("input",)
        self.category = "advisory" if d.type in caps.MODEL_TYPES else "guardian"
        self.parts = PARTS_BY_STAGE[d.stage]
        self._today = today or (lambda: dt.datetime.now(dt.UTC).date())
        if d.action_on_fail not in caps.ACTIONS_BY_TYPE[d.type]:
            raise GuardianFactoryError(
                "invalid_definition", "action_on_fail: not allowed for this type"
            )

    def applies(self, meta: Mapping[str, Any]) -> bool:
        """True when the call is in the scope of the guardian and not allow-listed (WP-G3)."""
        return self._applies(meta)

    def fail_closed_allowed(self) -> bool:
        """WP-G3: a guardian that did not run never blocks a risky call (the registry veto)."""
        return False

    @property
    def did(self) -> str:
        return f"{self.slug}@{self.version}"

    @property
    def hint(self) -> str:
        return HINTS[self.d.action_on_fail]

    def _applies(self, meta: Mapping[str, Any]) -> bool:
        """Scope and the allow-list (an entry stops counting at its ``expires`` date)."""
        sc = self.d.scope
        agent = str(meta.get("agent_id") or "")
        tool = str(meta.get("tool_name") or "")
        if sc.agents != "*" and agent not in sc.agents:
            return False
        if sc.tools != "*" and tool not in sc.tools:
            return False
        if sc.data_classes:
            klass = str(meta.get("data_class") or meta.get("risk_class") or "")
            if klass not in sc.data_classes:
                return False
        today = self._today().isoformat()
        return not any(
            e.agent_id == agent and e.expires >= today for e in self.d.lifecycle.allow_list
        )

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        meta = payload.get("meta") or {}
        if not self._applies(meta):
            return []
        try:
            return self._run(payload, meta)
        except Exception as exc:  # noqa: BLE001 - the contract: report, do not raise
            return [not_executed(self.slug, self.did, "execution_failed", type(exc).__name__)]

    def _run(self, payload: Mapping[str, Any], meta: Mapping[str, Any]) -> list[Finding]:
        raise NotImplementedError

    def _finding(
        self,
        code_suffix: str,
        frags: list[Fragment],
        count: int,
        transformed: Mapping[str, Any] | None,
    ) -> Finding:
        return Finding(
            detector_slug=self.slug,
            detector_id=self.did,
            code=f"guardian.{self.d.id}{code_suffix}",
            score_bp=HIT,
            threshold_bp=THRESHOLD,
            entities=(Entity("guardian", self.d.id, count),),
            fragments=tuple(frags[:20]),
            masked_count=count,
            action_hint=self.hint,  # type: ignore[arg-type]
            preset="balanced",
            transformed_payload=transformed if self.d.action_on_fail == "redact" else None,
        )


# ---------------------------------------------------------------------------- text rules


class TextRuleDetector(_Base):
    """regex and keyword_list."""

    def __init__(self, d: GuardianDefinition, today: Callable[[], dt.date] | None = None) -> None:
        super().__init__(d, today)
        self._words = [str(w) for w in d.config.get("words") or []]

    def _scan(self, text: str) -> tuple[str, list[tuple[int, int]]]:
        """The text with each match replaced, and the spans in the new text."""
        cfg = self.d.config
        if self.d.type == "regex":
            from supervisor.detectors.dlp_extras import Extras

            x = Extras(
                {
                    "custom_rules": [
                        {
                            "id": "g",
                            "kind": "regex",
                            "pattern": cfg["pattern"],
                            "mask_token": cfg.get("mask_token"),
                            "preserve_length": cfg.get("preserve_length", False),
                        }
                    ]
                }
            )
            sc = x.scan(text)
            if not sc.hits:
                return text, []
            final, spans = x.resolve(sc, sc.text)
            return final, [(s, e) for s, e, _ in spans]
        return self._keywords(text)

    def _keywords(self, text: str) -> tuple[str, list[tuple[int, int]]]:
        low = text.casefold()
        if len(low) != len(text):  # casefold changed the length: use lower() positions
            low = text.lower()
        spans: list[tuple[int, int]] = []
        for w in self._words:
            lw = w.casefold() if len(w.casefold()) == len(w) else w.lower()
            i = low.find(lw)
            while i >= 0 and len(spans) < 200:
                spans.append((i, i + len(lw)))
                i = low.find(lw, i + len(lw))
        spans.sort()
        merged: list[tuple[int, int]] = []
        for s, e in spans:
            if merged and s < merged[-1][1]:
                merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
            else:
                merged.append((s, e))
        cfg = self.d.config
        out: list[str] = []
        new: list[tuple[int, int]] = []
        last, pos = 0, 0
        for s, e in merged:
            rep = (
                "*" * (e - s)
                if cfg.get("preserve_length")
                else (cfg.get("mask_token") or f"<GUARDIAN:{self.d.id}>")
            )
            out.append(text[last:s])
            pos += s - last
            out.append(rep)
            new.append((pos, pos + len(rep)))
            pos += len(rep)
            last = e
        out.append(text[last:])
        return "".join(out), new

    def _run(self, payload: Mapping[str, Any], meta: Mapping[str, Any]) -> list[Finding]:
        frags: list[Fragment] = []
        count = 0
        transformed: dict[str, Any] = {}
        for part in self.parts:
            if payload.get(part) is None:
                continue
            for leaf in walk_leaves(part, payload[part]):
                final, spans = self._scan(leaf.text)
                if final == leaf.text:
                    continue
                count += max(len(spans), 1)
                for s, e in spans[:5]:
                    frags.append(Fragment(part, leaf.path, s, e, clip(final, s, e)))
            if part in APPLIED and count:
                transformed[part] = map_leaves(payload[part], lambda t: self._scan(t)[0])
        if not count:
            return []
        return [self._finding("", frags, count, transformed or None)]


# ---------------------------------------------------------------------------- policy


def _vals(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else [value]


def _cond_true(c: Any, args: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    if c.kind == "tool":
        return str(meta.get("tool_name") or "") in _vals(c.value)
    if c.kind == "data_class":
        klass = str(meta.get("data_class") or meta.get("risk_class") or "")
        return klass in _vals(c.value)
    present = c.name in args
    if c.kind == "argument":
        if c.op == "present":
            return present
        return present and args[c.name] in _vals(c.value)
    # amount: only a whole number counts; a float, a bool or a text never matches
    got = args.get(c.name)
    if isinstance(got, bool) or not isinstance(got, int):
        return False
    want = int(c.value)  # type: ignore[arg-type]
    return {
        "eq": got == want,
        "gt": got > want,
        "gte": got >= want,
        "lt": got < want,
        "lte": got <= want,
    }[c.op]


def evaluate_policy(
    d: GuardianDefinition, args: Mapping[str, Any], meta: Mapping[str, Any]
) -> tuple[bool, str | None]:
    """(permitted, id of the rule that decided; None when the default decided).
    A matching forbid wins; else a matching permit; else the default."""
    from supervisor.guardian_factory.definition import PolicyConfig

    cfg = PolicyConfig.model_validate(d.config)
    for effect in ("forbid", "permit"):
        for r in cfg.rules:
            if r.then == effect and all(_cond_true(c, args, meta) for c in r.when):
                return effect == "permit", r.id
    return cfg.default == "permit", None


class PolicyDetector(_Base):
    def _run(self, payload: Mapping[str, Any], meta: Mapping[str, Any]) -> list[Finding]:
        args = payload.get("args")
        if not isinstance(args, Mapping):
            return []
        ok, rule_id = evaluate_policy(self.d, args, meta)
        if ok:
            return []
        suffix = f".{rule_id}" if rule_id else ".default"
        return [self._finding(suffix, [], 1, None)]


# ---------------------------------------------------------------------------- model types


class ClassifierDetector(_Base):
    """Delegates to the existing detector ``model_ref`` with the threshold of the definition."""

    def __init__(
        self,
        d: GuardianDefinition,
        delegates: Mapping[str, Any],
        today: Callable[[], dt.date] | None = None,
    ) -> None:
        super().__init__(d, today)
        self.delegate = delegates.get(str(d.config["model_ref"]))
        self.presets = {"balanced": int(d.config["threshold_bp"])}
        self.parts = tuple(getattr(self.delegate, "parts", self.parts)) or self.parts

    def _run(self, payload: Mapping[str, Any], meta: Mapping[str, Any]) -> list[Finding]:
        if self.delegate is None:
            return [not_executed(self.slug, self.did, "execution_failed", "model_ref unavailable")]
        thr = int(self.d.config["threshold_bp"])
        direction = "output" if self.d.stage == "output" else "input"
        out: list[Finding] = []
        for f in self.delegate.evaluate(payload, {"threshold_bp": thr}, direction):
            if f.not_executed_reason is not None:
                out.append(not_executed(self.slug, self.did, f.not_executed_reason, f.detail))
            elif f.score_bp >= thr:
                out.append(
                    Finding(
                        detector_slug=self.slug,
                        detector_id=self.did,
                        code=f"guardian.{self.d.id}",
                        score_bp=f.score_bp,
                        threshold_bp=thr,
                        fragments=f.fragments,
                        action_hint=self.hint,  # type: ignore[arg-type]
                        preset="balanced",
                        is_mock=f.is_mock,
                    )
                )
        return out


class JudgePromptDetector(_Base):
    """One judge call with the prompt of the definition on the masked text."""

    MAX_CHARS = 8_000

    def __init__(
        self,
        d: GuardianDefinition,
        chat: Any = None,
        masker: Any = None,
        today: Callable[[], dt.date] | None = None,
    ) -> None:
        super().__init__(d, today)
        self.chat = chat
        self.masker = masker

    def _run(self, payload: Mapping[str, Any], meta: Mapping[str, Any]) -> list[Finding]:
        if self.chat is None:
            return [not_executed(self.slug, self.did, "execution_failed", "no judge model")]
        cfg = self.d.config
        parts = {p: payload[p] for p in self.parts if payload.get(p) is not None}
        text = json.dumps(parts, ensure_ascii=False, default=str)[: self.MAX_CHARS]
        if self.masker is not None:
            text = self.masker.mask(text)
        schema = {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": list(cfg["verdict_labels"])},
                "score_bp": {"type": "integer", "minimum": 0, "maximum": 10000},
            },
            "required": ["label", "score_bp"],
            "additionalProperties": False,
        }
        messages = [
            {"role": "system", "content": str(cfg["prompt"])},
            {"role": "user", "content": f"<data>{text}</data>\nAnswer with a label and score_bp."},
        ]
        try:
            ans = self.chat.complete_json(messages, schema, 20.0)
            label, score = str(ans["label"]), ans["score_bp"]
            if (
                label not in cfg["verdict_labels"]
                or isinstance(score, bool)
                or not isinstance(score, int)
            ):
                raise ValueError("bad answer")
            score = max(0, min(10_000, score))
        except Exception:  # noqa: BLE001 - a judge that cannot answer is a gap, not a pass
            return [not_executed(self.slug, self.did, "execution_failed", "judge unavailable")]
        if label not in cfg["fail_labels"]:
            return []
        return [
            Finding(
                detector_slug=self.slug,
                detector_id=self.did,
                code=f"guardian.{self.d.id}.{label}",
                score_bp=score,
                threshold_bp=THRESHOLD,
                action_hint=self.hint,  # type: ignore[arg-type]
                preset="balanced",
                is_mock=bool(getattr(self.chat, "is_mock", False)),
            )
        ]


# ---------------------------------------------------------------------------- entry point


def to_detector(
    d: GuardianDefinition,
    *,
    delegates: Mapping[str, Any] | None = None,
    chat: Any = None,
    masker: Any = None,
    today: Callable[[], dt.date] | None = None,
) -> Any:
    """A detector of the existing contract for a ``live`` definition. A definition in another
    state is refused: only a live, immutable version is attached to agents (WP-G3)."""
    if d.lifecycle.state != "live":
        raise GuardianFactoryError(
            "not_live", f"only a live guardian becomes a detector; this one is {d.lifecycle.state}"
        )
    return build(d, delegates=delegates, chat=chat, masker=masker, today=today)


def build(
    d: GuardianDefinition,
    *,
    delegates: Mapping[str, Any] | None = None,
    chat: Any = None,
    masker: Any = None,
    today: Callable[[], dt.date] | None = None,
) -> Any:
    """Like ``to_detector`` without the live check (the benchmark of WP-G2 and the shadow run of
    WP-G3 build detectors from definitions that are not live yet)."""
    if d.type in ("regex", "keyword_list"):
        return TextRuleDetector(d, today)
    if d.type == "policy":
        return PolicyDetector(d, today)
    if d.type == "classifier":
        return ClassifierDetector(d, delegates or {}, today)
    return JudgePromptDetector(d, chat, masker, today)
