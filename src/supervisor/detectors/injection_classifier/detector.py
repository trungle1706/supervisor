"""``injection_classifier``: a small local classifier for prompt injection, Vietnamese and English.

WP25, ADR D27, docs/injection-classifier.md. Implements the WP37 ``Detector`` protocol.

* Scans tool arguments (code ``injection.direct_injection``), tool results
  (``injection.indirect_injection``) and tool descriptions (``injection.tool_poisoning``). The tool
  description comes from ``context.tool_description``, prior calls of the same trace from
  ``context.prior_calls`` (both reach the detector through ``payload["meta"]``).
* Pure code plus one weight file under ``data/models/injection_vi_en/<version>/``. The detector
  refuses a weight file whose SHA-256 differs from the model card (``ModelIntegrityError``; the
  registry reports ``execution_failed``). No network, no download, no model call (R3).
* R1: the classifier never blocks. Its finding carries ``action_hint = "pause"`` only when the score
  is at or above the frozen pause threshold AND the tool's risk class is in ``pause_tool_classes``
  (default money, credit). The gate (``gateway/detector_gate.py``) turns that hint into
  ``pause`` with rule id ``GATE-CLASSIFIER-PAUSE``; a human resumes with two people as today.
  Everywhere else the finding is a report.
* R2: fragments point into MASKED text (the masker runs on the leaf, never the raw text); the
  features are hashed numbers and leave no text behind.

The detector is registered in ``build_registry`` and listed in ``config/detectors.yaml`` with
``enabled: false``. The ``enabled`` key of that entry is the only switch.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from supervisor.core.detectors import (
    SCORE_MAX,
    Finding,
    Fragment,
    Leaf,
    SettingField,
    SettingsSchema,
    clip,
    detector_id,
    threshold_for,
)
from supervisor.core.ports import Masker
from supervisor.detectors.injection_classifier import features as F
from supervisor.detectors.injection_classifier import units as U
from supervisor.detectors.injection_classifier.model import (
    LinearModel,
    ModelIntegrityError,
    load_model,
)

MODEL_VERSION = "1.0.0"

# Frozen with MODEL_VERSION (a test compares them with the model card). Detection thresholds in
# basis points, chosen on the dev split by false-alarm rate; ILLUSTRATIVE until the bank sets them.
PRESETS: dict[str, int] = {"strict": 5_500, "balanced": 6_000, "lenient": 7_000}
# At or above this score a finding on a pause class tool carries the pause hint. Frozen per model
# version; the setting can only raise it.
PAUSE_THRESHOLD_BP = 8_500
PAUSE_CLASSES_DEFAULT = ["money", "credit"]
PAUSE_CLASSES_ALLOWED = ("money", "credit", "pii_export")  # read_only can never pause

_SENTENCE = re.compile(r"(?<=[.!?;:\n])\s+|(?=<!--)|(?<=-->)")
MAX_CLAUSES = 80
MAX_FRAGMENT_LEAVES = 2
# Bounded work per call (WP25 review): a call with many or long texts must finish well inside the
# gate's per-detector deadline, or a timeout (not fail closed) would silently skip the classifier.
CALL_BUDGET_CHARS = 30_000  # characters scored per call, all units together
MIN_UNIT_CHARS = 1_500  # every unit keeps at least this much (head, cue segments, tail)
MAX_RESULT_UNITS = 16  # tool results beyond this are scored as one joined text
FRAGMENT_RANK_CHARS = 8_000  # characters scored to rank the leaves of a fired unit
CLAUSE_BUDGET_CHARS = 4_000  # characters of clauses scored to place a fragment in one leaf

_MODEL_CACHE: dict[str, LinearModel] = {}


def default_model(version: str = MODEL_VERSION) -> LinearModel:
    """The shipped model, loaded once per process after the integrity check."""
    m = _MODEL_CACHE.get(version)
    if m is None:
        m = _MODEL_CACHE[version] = load_model(version)
    return m


def score_tool_description(text: str) -> int:
    """Poisoning score of one tool description in basis points (0 to 10000).

    The adapter for WP26: ``mcp_lock.register_description_scorer(score_tool_description)`` (or the
    integrator's equivalent) lets the tool-locking gateway score a description at ``tools/list``
    time. Offline and deterministic. Raises ``ModelIntegrityError`` when the weights do not match
    the model card; the caller decides the fail mode (for tool locking: hold the tool for review).
    """
    return default_model().score_bp(text, "tool_description")


class InjectionClassifierDetector:
    slug = "injection_classifier"
    name = "Prompt injection (classifier, Vietnamese and English)"
    category = "content_security"
    version = MODEL_VERSION
    sides = ("input", "output")
    protocols = ("all",)
    presets = PRESETS
    settings_schema = SettingsSchema(
        (
            SettingField(
                "scan_tool_results",
                "Scan tool results",
                "boolean",
                default=True,
                description="Indirect injection: text a tool returned (and the output side).",
            ),
            SettingField(
                "scan_tool_descriptions",
                "Scan tool descriptions",
                "boolean",
                default=True,
                description="Tool poisoning: context.tool_description of the tool being called.",
            ),
            SettingField(
                "pause_tool_classes",
                "Tool classes that may be paused",
                "array",
                default=list(PAUSE_CLASSES_DEFAULT),
                items="string",
                item_enum=PAUSE_CLASSES_ALLOWED,
                max_length=len(PAUSE_CLASSES_ALLOWED),
                description="A finding at or above the pause threshold on one of these classes "
                "carries the pause hint. Empty = the classifier only reports.",
            ),
            SettingField(
                "pause_threshold_bp",
                "Pause threshold (bp)",
                "integer",
                default=PAUSE_THRESHOLD_BP,
                minimum=PAUSE_THRESHOLD_BP,
                maximum=SCORE_MAX,
                description="Frozen per model version; it can be raised, never lowered.",
            ),
            SettingField(
                "max_chars",
                "Characters scanned per text",
                "integer",
                default=12_000,
                minimum=500,
                maximum=F.MAX_UNIT_CHARS,
                description="Longer text keeps its head, its tail and the middle segments with "
                "the most cue words.",
            ),
        )
    )

    def __init__(self, masker: Masker, *, model: LinearModel | None = None) -> None:
        self.masker = masker
        self._model = model

    @property
    def model(self) -> LinearModel:
        if self._model is None:
            self._model = default_model()
        return self._model

    # ------------------------------------------------------------------ evaluate
    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        model = self.model
        threshold = threshold_for(self, settings)
        preset = str(settings.get("preset") or "balanced")
        did = detector_id(self)
        max_chars = int(settings.get("max_chars") or 12_000)
        pause_classes = set(settings.get("pause_tool_classes") or ())
        pause_thr = max(
            PAUSE_THRESHOLD_BP, int(settings.get("pause_threshold_bp") or PAUSE_THRESHOLD_BP)
        )
        meta = payload.get("meta") or {}
        risk = meta.get("risk_class")
        max_chars = min(max_chars, F.MAX_UNIT_CHARS)
        best: dict[str, tuple[int, U.Unit]] = {}
        units = [
            u
            for u in U.collect(payload, direction)
            if not (u.surface == "tool_results" and not settings.get("scan_tool_results", True))
            and not (
                u.surface == "tool_description" and not settings.get("scan_tool_descriptions", True)
            )
        ]
        units = _bounded_units(units)
        per_unit = min(max_chars, max(MIN_UNIT_CHARS, CALL_BUDGET_CHARS // max(1, len(units))))
        for unit in units:
            # head, tail and the cue-richest middle segments (features.clip_unit)
            score = model.score_bp(F.clip_unit(unit.text, per_unit), unit.surface)
            if unit.surface not in best or score > best[unit.surface][0]:
                best[unit.surface] = (score, unit)
        out: list[Finding] = []
        for surface in U.SURFACES:
            if surface not in best:
                continue
            score, unit = best[surface]
            fired = score >= threshold
            frags: tuple[Fragment, ...] = ()
            if fired:
                frags = self._fragments(model, unit, surface, threshold, max_chars)
            hint = "report"
            if fired and direction == "input" and risk in pause_classes and score >= pause_thr:
                hint = "pause"
            out.append(
                Finding(
                    detector_slug=self.slug,
                    detector_id=did,
                    code=U.CODE_BY_SURFACE[surface],
                    score_bp=score,
                    threshold_bp=threshold,
                    fragments=frags,
                    action_hint=hint,  # type: ignore[arg-type]
                    preset=preset,
                )
            )
        return out

    # ------------------------------------------------------------------ fragments
    def _fragments(
        self, model: LinearModel, unit: U.Unit, surface: str, threshold: int, max_chars: int
    ) -> tuple[Fragment, ...]:
        """The best clause of the best leaves, located on MASKED text (R2)."""
        cands: list[tuple[int, Leaf]] = []
        leaves = [x for x in unit.leaves if x.text.strip()]
        if len(leaves) > 40:  # keep the 40 leaves with the most cue words (bounded work)
            order = sorted(
                range(len(leaves)), key=lambda i: (-F.cue_count(leaves[i].text[:2_000]), i)
            )
            leaves = [leaves[i] for i in sorted(order[:40])]
        rank_chars = max(600, FRAGMENT_RANK_CHARS // max(1, len(leaves)))
        for leaf in leaves:
            if len(leaves) == 1:
                sc = 10_000  # the only leaf: no need to score it again
            elif F.usable(leaf.text):
                sc = model.score_bp(F.clip_unit(leaf.text, rank_chars), surface)
            else:
                sc = 0
            cands.append((sc, leaf))
        cands.sort(key=lambda c: -c[0])
        out: list[Fragment] = []
        for _score, leaf in cands[:MAX_FRAGMENT_LEAVES]:
            # R2: the fragment is located on the MASKED head of the leaf (a margin keeps a value
            # cut at the end whole); only the leaves that give a fragment are masked
            masked = self.masker.mask(leaf.text[: max_chars + 200])[:max_chars]
            span = self._best_clause(model, masked, surface, threshold)
            if span is not None:
                s, e = span
                out.append(Fragment(leaf.part, leaf.path, s, e, clip(masked, s, e), "span"))
            else:
                out.append(
                    Fragment(
                        leaf.part, leaf.path, 0, len(masked), clip(masked, 0, len(masked)), "leaf"
                    )
                )
        return tuple(out)

    @staticmethod
    def _best_clause(
        model: LinearModel, masked: str, surface: str, threshold: int
    ) -> tuple[int, int] | None:
        """(start, end) of the highest-scoring clause of ``masked``, or None when no single clause
        reaches the threshold less 2000 bp (the evidence is spread over the leaf)."""
        spans: list[tuple[int, int]] = []
        pos = 0
        for m in _SENTENCE.finditer(masked):
            if m.start() > pos:
                spans.append((pos, m.start()))
            pos = m.end()
        if pos < len(masked):
            spans.append((pos, len(masked)))
        spans = [(s, e) for s, e in spans if masked[s:e].strip()]
        if len(spans) > MAX_CLAUSES:  # merge neighbours so a long document stays cheap
            k = -(-len(spans) // MAX_CLAUSES)
            spans = [
                (spans[i][0], spans[min(i + k, len(spans)) - 1][1]) for i in range(0, len(spans), k)
            ]
        if len(spans) <= 1:
            return None
        if sum(e - s for s, e in spans) > CLAUSE_BUDGET_CHARS:  # score the cue-richest clauses
            order = sorted(spans, key=lambda se: (-F.cue_count(masked[se[0] : se[1]]), se[0]))
            chosen, used = [], 0
            for s, e in order:
                if used and used + (e - s) > CLAUSE_BUDGET_CHARS:
                    continue
                chosen.append((s, e))
                used += e - s
            spans = sorted(chosen)
        best_score, best_span = -1, None
        for s, e in spans:
            sc = model.score_bp(masked[s:e], surface)
            if sc > best_score:
                best_score, best_span = sc, (s, e)
        if best_span is not None and best_score >= threshold - 2_000:
            s, e = best_span
            while s < e and masked[s].isspace():
                s += 1
            return s, e
        return None


def _bounded_units(units: list[U.Unit]) -> list[U.Unit]:
    """At most MAX_RESULT_UNITS tool-result units: the rest are joined into the last one (their
    text is still scored, inside the call budget)."""
    res = [u for u in units if u.surface == "tool_results" and u.part == "tool_results"]
    if len(res) <= MAX_RESULT_UNITS:
        return units
    others = [u for u in units if not (u.surface == "tool_results" and u.part == "tool_results")]
    keep, rest = res[: MAX_RESULT_UNITS - 1], res[MAX_RESULT_UNITS - 1 :]
    joined = U.Unit(
        "tool_results",
        "tool_results",
        "\n".join(u.text for u in rest),
        tuple(x for u in rest for x in u.leaves),
    )
    return [*others, *keep, joined]


__all__ = [
    "MODEL_VERSION",
    "PAUSE_CLASSES_ALLOWED",
    "PAUSE_CLASSES_DEFAULT",
    "PAUSE_THRESHOLD_BP",
    "PRESETS",
    "InjectionClassifierDetector",
    "ModelIntegrityError",
    "default_model",
    "score_tool_description",
]
