"""``dlp_vn``: Vietnamese personal data (WP37). Wraps the ``vn_regex`` masker as a detector.

The only detector that may *transform*. For each entity type found it returns one finding with
the pseudonym tokens (never the value), the located tokens in the MASKED text, and the number of
values masked. With ``mode=transform`` and a risk class (or tool) that is in scope, the findings
carry the payload after masking; the gate puts it in ``transformed_payload``.

Scores are rule based (illustrative): a value that passes a check digit or has a label is
stronger than a name that matched the lexicon.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from supervisor.core.detectors import (
    DOCUMENT_PART,
    MAX_DEPTH,
    SCORE_MAX,
    Entity,
    Finding,
    Fragment,
    SettingField,
    SettingsSchema,
    clip,
    detector_id,
    map_leaves,
    parts_for,
    threshold_for,
    walk_leaves,
)
from supervisor.core.ports import Masker

_TOKEN = re.compile(r"<([A-Z_]{2,20}):([0-9a-f]{4,64})>")

# Illustrative confidence per entity type (basis points).
SCORE_BY_TYPE: dict[str, int] = {
    "EMAIL": 10_000,
    "CARD_NUMBER": 9_800,
    "PHONE": 9_500,
    "CCCD": 9_500,
    "CMND": 9_000,
    "TAX_CODE": 9_000,
    "BANK_ACCOUNT": 9_000,
    "PERSON": 8_000,
    "ADDRESS": 8_000,
    "AMOUNT": 5_000,
}
DEFAULT_SCORE = 8_000
RISK_CLASSES = ("money", "credit", "pii_export", "read_only")

# Frozen with the version string: change a number, change the version.
PRESETS: dict[str, int] = {"strict": 5_000, "balanced": 8_000, "lenient": 9_500}


# WP41 (D29): typed pseudonyms. With pseudonym_mode "typed" a text value that sits directly under
# an argument whose NAME says what it is gets that class, not the one the masker guesses from
# the digits (a bare 10 digit tax code looks like a bank account). The label goes in front of
# the value for the masker and is cut off again.
_KEY_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|_)(tax|mst|ma_so_thue)(_|$)", re.I), "mã số thuế "),
    (re.compile(r"(^|_)(account|acct|stk|tai_khoan)(_|$)", re.I), "tài khoản "),
)
PSEUDONYM_MODES = ("generic", "typed")
KEEP_ARG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def keep_args_problems(value: Any) -> list[str]:
    """Problems in a ``keep_args`` setting: ``{tool: [argument names]}`` (empty = fine)."""
    if value in (None, {}):
        return []
    if not isinstance(value, Mapping):
        return ["keep_args: expected a mapping of tool name to a list of argument names"]
    problems: list[str] = []
    if len(value) > 64:
        problems.append("keep_args: more than 64 tools")
    for tool, names in value.items():
        if not isinstance(tool, str) or not KEEP_ARG_RE.match(tool):
            problems.append("keep_args: a tool name is not a plain identifier")
        elif (
            not isinstance(names, list)
            or not 0 < len(names) <= 8
            or any(not isinstance(n, str) or not KEEP_ARG_RE.match(n) for n in names)
        ):
            problems.append(f"keep_args.{tool}: 1..8 argument names (letters, digits, _ . -)")
    return problems


def _hint_label(key: str | None) -> str | None:
    if not key:
        return None
    for rx, label in _KEY_HINTS:
        if rx.search(key):
            return label
    return None


def _typed_mask(mask: Any, key: str | None, text: str) -> str:
    label = _hint_label(key)
    if label is None:
        return mask(text)
    out = mask(label + text)
    return out[len(label) :] if out.startswith(label) else mask(text)


def _mask_tree(value: Any, mask: Any, depth: int = 0, typed: bool = False) -> Any:
    """``map_leaves`` that also masks string dict keys: a transformed payload goes on to a
    pii_export tool, and a name used as a key must not reach it in clear (R2)."""
    if isinstance(value, Mapping) and depth <= MAX_DEPTH:
        return {
            (mask(k) if isinstance(k, str) else k): (
                _typed_mask(mask, k, v)
                if typed and isinstance(k, str) and isinstance(v, str)
                else _mask_tree(v, mask, depth + 1, typed)
            )
            for k, v in value.items()
        }
    if isinstance(value, list | tuple) and depth <= MAX_DEPTH:
        return [_mask_tree(v, mask, depth + 1, typed) for v in value]
    return map_leaves(value, mask, depth)


class DlpVnDetector:
    slug = "dlp_vn"
    name = "Vietnamese personal data (DLP)"
    category = "data_protection"
    deterministic = True  # rules and a masker, no model: its findings count in the session monitor
    version = "1.0.0"
    sides = ("input", "output")
    protocols = ("all",)
    # WP-D1: the document text is scanned too; it is masked in the transformed payload only for a
    # pii_export tool (the same rule as the arguments)
    parts = ("args", "tool_results", "output", DOCUMENT_PART)
    presets = PRESETS
    settings_schema = SettingsSchema(
        (
            SettingField(
                "mode",
                "Mode",
                "enum",
                default="transform",
                enum=("report", "transform"),
                description="transform: mask payloads of tools in scope; report: findings only.",
            ),
            SettingField(
                "transform_risk_classes",
                "Transform for risk classes",
                "array",
                default=["pii_export"],
                items="string",
                item_enum=RISK_CLASSES,
                max_length=4,
            ),
            SettingField(
                "transform_tools",
                "Transform for these tools",
                "array",
                default=[],
                items="string",
                max_length=64,
            ),
            SettingField(
                "keep_args",
                "Arguments passed unmasked, per tool",
                "object",
                default={},
                description=(
                    "{tool: [argument names]}. A named top-level argument reaches the tool as "
                    "sent (a lookup key); it is still masked in every record, chain entry, "
                    "finding and SIEM event. The decision lists it as kept_args. Loading one "
                    "writes an audit line."
                ),
            ),
            SettingField(
                "pseudonym_mode",
                "Pseudonym typing",
                "enum",
                default="generic",
                enum=PSEUDONYM_MODES,
                description=(
                    "generic: the masker guesses the class from the value. typed: the argument "
                    "name decides for tax and account values, so a tax code stays TAX_CODE."
                ),
            ),
        )
    )

    def __init__(self, masker: Masker) -> None:
        self.masker = masker

    # -- helpers --------------------------------------------------------------
    def _in_scope(self, settings: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
        if settings.get("mode") != "transform":
            return False
        return meta.get("risk_class") in (settings.get("transform_risk_classes") or ()) or (
            meta.get("tool_name") in (settings.get("transform_tools") or ())
        )

    def transforms_here(self, settings: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
        """WP41 review: the registry asks before a cut scan; a transform of text read only in
        part is never handed out (core.detectors.APPLIED_PARTS)."""
        return self._in_scope(settings, meta)

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        meta = payload.get("meta") or {}
        typed = settings.get("pseudonym_mode") == "typed"
        memo: dict[str, str] = {}

        def mask(text: str) -> str:  # the scan and the transform mask the same text twice
            out = memo.get(text)
            if out is None:
                out = memo[text] = self.masker.mask(text)
            return out

        did = detector_id(self)
        threshold = threshold_for(self, settings)
        preset = str(settings.get("preset") or "balanced")
        counts: Counter[str] = Counter()
        tokens: dict[str, Counter[str]] = {}
        frags: dict[str, list[Fragment]] = {}
        seen_in: dict[str, set[str]] = {}  # entity type -> parts it was found in
        parts = parts_for(payload, direction, self)
        for part in parts:
            if payload.get(part) is None:
                continue
            for leaf in walk_leaves(part, payload[part]):
                masked = (
                    _typed_mask(mask, leaf.path.rsplit(".", 1)[-1], leaf.text)
                    if typed and not leaf.path.endswith("]")
                    else mask(leaf.text)
                )
                if masked == leaf.text:
                    continue
                before = Counter(m.group(0) for m in _TOKEN.finditer(leaf.text))
                for m in _TOKEN.finditer(masked):
                    if before.get(m.group(0), 0) > 0:  # already a token in the input
                        before[m.group(0)] -= 1
                        continue
                    typ = m.group(1)
                    counts[typ] += 1
                    tokens.setdefault(typ, Counter())[m.group(0)] += 1
                    seen_in.setdefault(typ, set()).add(part)
                    frags.setdefault(typ, []).append(
                        Fragment(
                            part, leaf.path, m.start(), m.end(), clip(masked, m.start(), m.end())
                        )
                    )
        if not counts:
            return []
        transform = self._in_scope(settings, meta)
        doc_transform = transform and meta.get("risk_class") == "pii_export"
        out_payload: dict[str, Any] | None = None
        if transform:
            out_payload = {
                part: _mask_tree(payload[part], mask, typed=typed)
                for part in parts
                if payload.get(part) is not None and (part != DOCUMENT_PART or doc_transform)
            }
        findings = []
        for typ in sorted(counts):
            # an entity found only in a document, on a tool that is not pii_export, is reported
            hint = (
                "transform"
                if transform and (seen_in[typ] != {DOCUMENT_PART} or doc_transform)
                else "report"
            )
            findings.append(
                Finding(
                    detector_slug=self.slug,
                    detector_id=did,
                    code=f"pii.{typ.lower()}",
                    score_bp=min(SCORE_MAX, SCORE_BY_TYPE.get(typ, DEFAULT_SCORE)),
                    threshold_bp=threshold,
                    entities=tuple(
                        Entity(typ, tok, n) for tok, n in sorted(tokens[typ].items())[:20]
                    ),
                    fragments=tuple(frags[typ]),
                    masked_count=counts[typ],
                    action_hint=hint,
                    preset=preset,
                    transformed_payload=out_payload if hint == "transform" else None,
                )
            )
        return findings
