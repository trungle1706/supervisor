"""``injection_regex``: prompt-injection phrases in Vietnamese and English (WP37).

Wraps the Tier 0b pattern list (``gateway/tier0b.py``) as a detector. Report only: a regex hit is
advice, never a block (R1). It looks at the whole call: the arguments and the tool results that
fed the call (indirect injection). The output side is not covered (an output check has no
instruction to hijack).

Fragments are located on MASKED text. The leaf is masked first, then the patterns run on a
per-character folded copy (lower case, no diacritics, same length), so the offsets index the
masked leaf. A phrase that only matches after Telex decoding, look-alike folding, or on the
unmasked text (the masker swallowed a word of it) cannot be mapped to offsets; it is reported
with ``precision = "leaf"`` and points at the whole masked leaf.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from supervisor.core.detectors import (
    PARTS_BY_DIRECTION,
    SCORE_MAX,
    Finding,
    Fragment,
    SettingField,
    SettingsSchema,
    clip,
    detector_id,
    threshold_for,
    walk_leaves,
)
from supervisor.core.ports import Masker
from supervisor.gateway import tier0b

# Names and base scores for tier0b._INJECTION, by index. A test checks the lengths match, so a
# new pattern in tier0b cannot slip in without a name and a weight.
GROUPS: tuple[tuple[str, int], ...] = (
    ("instruction_override", 9_000),
    ("mode_switch", 9_000),
    ("prompt_leak", 7_000),
    ("policy_override", 8_500),
    ("urgent_transfer", 6_500),
    ("role_tag", 8_000),
)
EXTRA_HIT_BP = 500  # each further hit of the same group

# Frozen with the version string.
PRESETS: dict[str, int] = {"strict": 5_000, "balanced": 7_000, "lenient": 8_500}


def fold_aligned(text: str) -> str:
    """Lower case and strip diacritics character by character, keeping the length."""
    out = []
    for c in text:
        if c.isascii():
            out.append(c.lower())
            continue
        base = "".join(x for x in unicodedata.normalize("NFD", c) if not unicodedata.combining(x))
        base = base.lower().replace("đ", "d")
        out.append(base if len(base) == 1 else (c.lower()[:1] or "?"))
    return "".join(out)


class InjectionRegexDetector:
    slug = "injection_regex"
    name = "Prompt injection (patterns)"
    category = "prompt_security"
    version = "1.0.0"
    sides = ("input",)
    protocols = ("all",)
    presets = PRESETS
    settings_schema = SettingsSchema(
        (
            SettingField(
                "groups",
                "Pattern groups",
                "array",
                default=[],
                items="string",
                item_enum=tuple(n for n, _ in GROUPS),
                max_length=len(GROUPS),
                description="Empty = all groups.",
            ),
            SettingField(
                "max_chars",
                "Characters scanned per text",
                "integer",
                default=20_000,
                minimum=100,
                maximum=200_000,
            ),
        )
    )

    def __init__(self, masker: Masker) -> None:
        if len(tier0b._INJECTION) != len(GROUPS):  # noqa: SLF001 - same package family
            raise RuntimeError("tier0b patterns and injection_regex groups are out of step")
        self.masker = masker
        self._rx = [re.compile(p) for p in tier0b._INJECTION]  # noqa: SLF001

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        did = detector_id(self)
        threshold = threshold_for(self, settings)
        preset = str(settings.get("preset") or "balanced")
        wanted = set(settings.get("groups") or ()) or {n for n, _ in GROUPS}
        max_chars = int(settings.get("max_chars") or 20_000)
        hits: dict[str, int] = {}
        frags: dict[str, list[Fragment]] = {}
        for part in PARTS_BY_DIRECTION[direction]:
            if payload.get(part) is None:
                continue
            for leaf in walk_leaves(part, payload[part]):
                masked = self.masker.mask(leaf.text)[:max_chars]
                aligned = fold_aligned(masked)
                others: list[str] | None = None
                for (name, _w), rx in zip(GROUPS, self._rx, strict=True):
                    if name not in wanted:
                        continue
                    found = list(rx.finditer(aligned))
                    if found:
                        hits[name] = hits.get(name, 0) + len(found)
                        frags.setdefault(name, []).extend(
                            Fragment(
                                part,
                                leaf.path,
                                m.start(),
                                m.end(),
                                clip(masked, m.start(), m.end()),
                            )
                            for m in found
                        )
                        continue
                    if others is None:
                        # Forms with no usable offsets: Telex decoding, look-alike folding, and
                        # the unmasked text (a name before "Ignore" can be swallowed by the
                        # masker). Only counts leave this function, never the raw text.
                        both = (
                            *tier0b.candidates(masked),
                            *tier0b.candidates(leaf.text[:max_chars]),
                        )
                        others = [c for c in dict.fromkeys(both) if c != aligned]
                    n = max((len(rx.findall(c)) for c in others), default=0)
                    if n:
                        hits[name] = hits.get(name, 0) + n
                        frags.setdefault(name, []).append(
                            Fragment(
                                part,
                                leaf.path,
                                0,
                                len(masked),
                                clip(masked, 0, len(masked)),
                                "leaf",
                            )
                        )
        weights = dict(GROUPS)
        out = []
        for name in (n for n, _ in GROUPS if n in hits):
            score = min(SCORE_MAX, weights[name] + EXTRA_HIT_BP * (hits[name] - 1))
            out.append(
                Finding(
                    detector_slug=self.slug,
                    detector_id=did,
                    code=f"injection.{name}",
                    score_bp=score,
                    threshold_bp=threshold,
                    fragments=tuple(frags[name]),
                    action_hint="report",
                    preset=preset,
                )
            )
        return out
