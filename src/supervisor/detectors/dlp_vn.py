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
    MAX_DEPTH,
    PARTS_BY_DIRECTION,
    SCORE_MAX,
    Entity,
    Finding,
    Fragment,
    SettingField,
    SettingsSchema,
    clip,
    detector_id,
    map_leaves,
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


def _mask_tree(value: Any, mask: Any, depth: int = 0) -> Any:
    """``map_leaves`` that also masks string dict keys: a transformed payload goes on to a
    pii_export tool, and a name used as a key must not reach it in clear (R2)."""
    if isinstance(value, Mapping) and depth <= MAX_DEPTH:
        return {
            (mask(k) if isinstance(k, str) else k): _mask_tree(v, mask, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple) and depth <= MAX_DEPTH:
        return [_mask_tree(v, mask, depth + 1) for v in value]
    return map_leaves(value, mask, depth)


class DlpVnDetector:
    slug = "dlp_vn"
    name = "Vietnamese personal data (DLP)"
    category = "data_protection"
    version = "1.0.0"
    sides = ("input", "output")
    protocols = ("all",)
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

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        meta = payload.get("meta") or {}
        did = detector_id(self)
        threshold = threshold_for(self, settings)
        preset = str(settings.get("preset") or "balanced")
        counts: Counter[str] = Counter()
        tokens: dict[str, Counter[str]] = {}
        frags: dict[str, list[Fragment]] = {}
        for part in PARTS_BY_DIRECTION[direction]:
            if payload.get(part) is None:
                continue
            for leaf in walk_leaves(part, payload[part]):
                masked = self.masker.mask(leaf.text)
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
                    frags.setdefault(typ, []).append(
                        Fragment(
                            part, leaf.path, m.start(), m.end(), clip(masked, m.start(), m.end())
                        )
                    )
        if not counts:
            return []
        transform = self._in_scope(settings, meta)
        out_payload: dict[str, Any] | None = None
        if transform:
            out_payload = {
                part: _mask_tree(payload[part], self.masker.mask)
                for part in PARTS_BY_DIRECTION[direction]
                if payload.get(part) is not None
            }
        findings = []
        for typ in sorted(counts):
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
                    action_hint="transform" if transform else "report",
                    preset=preset,
                    transformed_payload=out_payload,
                )
            )
        return findings
