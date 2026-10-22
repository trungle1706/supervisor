"""``guard_model``: ML jailbreak and indirect-injection scoring through a configured model (WP-D3).

Implements the WP37 ``Detector`` protocol. Docs: ``docs/detectors.md`` section 3d, decision memo
``docs/guard-model-decision.md``.

What it scores (input side unless noted), and the label each surface starts from:

| surface            | text                                                   | label              |
|--------------------|--------------------------------------------------------|--------------------|
| ``args``           | string leaves of the tool arguments (user text fields) | jailbreak          |
| ``tool_results``   | string leaves of each tool result; the output side     | indirect_injection |
| ``tool_description`` | ``meta.tool_description(s)``                       | indirect_injection |
| ``documents``      | string leaves of ``payload["documents"]`` (WP-D1)      | indirect_injection |

A model that names its own class (jailbreak or indirect_injection) decides the label of a
finding; a model with one attack class (``malicious``) takes the label of the surface.

Rules the code keeps:

* The model sees MASKED text only (the masker runs on every leaf first) and never a system
  prompt: system prompts are not a payload part, and an argument key named ``system_prompt``,
  ``system``, ``developer`` or ``instructions`` is left out as well.
* Text longer than 2,000 characters is cut in overlapping windows (500 characters of overlap) and
  the highest score wins. At most ``max_windows`` windows are sent per call, spread over the text.
* One batch per call: all windows go to the port in one ``score`` call; scores are cached by text
  hash (model id included) so a repeated tool result costs nothing.
* Findings only (R1). The pause hint is set only when ``pause_tool_classes`` names the tool class,
  the score reaches the pause bar of the label, the call is on the input side AND the model card
  carries an approval that names the approver and the model id (the WP25 rule). Never fail closed
  by default: a timeout or an error is a ``timed_out`` / ``execution_failed`` row, and
  ``fail_closed: true`` is honoured only with the same approval and the setting
  ``GUARD_MODEL_FAIL_CLOSED_APPROVED``.
* Nothing here opens a socket: the port does (``supervisor.adapters.guard``).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.core.detectors import (
    SCORE_MAX,
    Finding,
    Fragment,
    SettingField,
    SettingsSchema,
    clip,
    detector_id,
    not_executed,
    walk_leaves,
)
from supervisor.core.errors import GuardModelError
from supervisor.core.ports import GuardModelPort, GuardScore, Masker

VERSION = "1.0.0"
WINDOW_CHARS = 2_000
WINDOW_OVERLAP = 500
WINDOW_STRIDE = WINDOW_CHARS - WINDOW_OVERLAP
DEFAULT_MAX_WINDOWS = 12
CACHE_SIZE = 1_024

LABELS = ("jailbreak", "indirect_injection")
CODE_BY_LABEL = {"jailbreak": "guard.jailbreak", "indirect_injection": "guard.indirect_injection"}

# Detection thresholds in basis points per label, frozen with VERSION (a test compares them with the
# model card template). ILLUSTRATIVE until the bank calibrates them on a real run of the harness.
LABEL_PRESETS: dict[str, dict[str, int]] = {
    "strict": {"jailbreak": 3_500, "indirect_injection": 4_000},
    "balanced": {"jailbreak": 5_500, "indirect_injection": 6_000},
    "permissive": {"jailbreak": 8_000, "indirect_injection": 8_500},
}
PRESET_ALIASES = {"lenient": "permissive"}  # the shared preset vocabulary of config/detectors.yaml
# The catalogue shows one number per preset: the jailbreak threshold.
PRESETS: dict[str, int] = {
    **{k: v["jailbreak"] for k, v in LABEL_PRESETS.items()},
    **{a: LABEL_PRESETS[b]["jailbreak"] for a, b in PRESET_ALIASES.items()},
}

PAUSE_CLASSES_ALLOWED = ("money", "credit", "pii_export")  # read_only can never pause
SYSTEM_KEYS = frozenset(
    {"system", "system_prompt", "developer", "developer_message", "instructions"}
)
SURFACE_LABEL = {
    "args": "jailbreak",
    "tool_results": "indirect_injection",
    "tool_description": "indirect_injection",
    "documents": "indirect_injection",
}
MODEL_CARD = REPO_ROOT / "data" / "models" / "guard_model" / "model_card.json"
APPROVAL_TTL_S = 5.0
_APPROVAL_CACHE: dict[str, tuple[float, bool]] = {}


def reset_approval_cache() -> None:
    """Forget the cached approval (tests; a changed card is seen after the TTL)."""
    _APPROVAL_CACHE.clear()


def label_threshold(settings: Mapping[str, Any], label: str) -> int:
    """Threshold of one label: the explicit ``threshold_bp`` (both labels) or the preset's."""
    explicit = settings.get("threshold_bp")
    if isinstance(explicit, int) and not isinstance(explicit, bool):
        return explicit
    preset = str(settings.get("preset") or "balanced")
    return LABEL_PRESETS[PRESET_ALIASES.get(preset, preset)][label]


def pause_threshold(settings: Mapping[str, Any], label: str) -> int:
    """Pause bar of one label: the high-confidence (permissive) threshold; ``pause_threshold_bp``
    can raise it, never lower it."""
    floor = LABEL_PRESETS["permissive"][label]
    value = settings.get("pause_threshold_bp")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(floor, value)
    return floor


def windows(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` of the 2,000-character windows of ``text``, 500 characters of overlap;
    the last window ends at the end of the text."""
    n = len(text)
    if n <= WINDOW_CHARS:
        return [(0, n)]
    out = []
    start = 0
    while True:
        end = min(n, start + WINDOW_CHARS)
        out.append((start, end))
        if end >= n:
            return out
        start += WINDOW_STRIDE


def spread(items: Sequence[Any], cap: int) -> list[Any]:
    """At most ``cap`` items, evenly spread, first and last kept (when cap >= 2)."""
    if len(items) <= cap:
        return list(items)
    if cap <= 1:
        return [items[0]]
    step = (len(items) - 1) / (cap - 1)
    return [items[round(i * step)] for i in range(cap)]


@dataclass
class _Unit:
    surface: str
    part: str
    leaves: list[tuple[str, str, int]] = field(default_factory=list)  # (path, masked, start)
    text: str = ""

    def add(self, path: str, masked: str) -> None:
        if not masked.strip():
            return
        if self.text:
            self.text += "\n"
        self.leaves.append((path, masked, len(self.text)))
        self.text += masked

    def locate(self, start: int, end: int) -> tuple[str, str, int, int] | None:
        """(path, masked leaf, from, to) of the leaf that holds the start of a window."""
        for path, masked, off in self.leaves:
            if start < off + len(masked):
                lo = max(start, off) - off
                hi = min(end, off + len(masked)) - off
                return path, masked, lo, max(hi, lo)
        return None


def _is_system_path(path: str) -> bool:
    for seg in path.replace("[", ".").split("."):
        if seg.lower() in SYSTEM_KEYS:
            return True
    return False


def _descriptions(meta: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    one = meta.get("tool_description")
    if isinstance(one, str):
        out.append(one)
    many = meta.get("tool_descriptions")
    if isinstance(many, list | tuple):
        for item in many:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("description"), str):
                out.append(item["description"])
    return out


def _approval_matches(card_path: Path, model_id: str) -> bool:
    """The card approval names an approver (not a FILL-ME placeholder) and the id of the model
    it approves, equal to the model the port serves (the WP25 rule, with the model id in place of
    the weights hash: the weights are served elsewhere)."""
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    approval = card.get("approval") or {}
    approver = str(approval.get("approver") or "").strip()
    named = bool(approver) and not approver.upper().startswith("FILL-ME")
    approved = str(approval.get("model_id") or "")
    return (
        named
        and bool(model_id)
        and not model_id.upper().startswith("FILL-ME")
        and approved == str(card.get("model_id") or "") == model_id
    )


class GuardModelDetector:
    slug = "guard_model"
    name = "Jailbreak and indirect injection (guard model)"
    category = "content_security"
    version = VERSION
    sides = ("input", "output")
    protocols = ("llm", "mcp")
    presets = PRESETS
    settings_schema = SettingsSchema(
        (
            SettingField(
                "scan_args",
                "Scan user text in arguments",
                "boolean",
                default=True,
                description="Jailbreak: string values of the tool arguments.",
            ),
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
                description="Tool poisoning: meta.tool_description(s) of the tools in the call.",
            ),
            SettingField(
                "scan_documents",
                "Scan documents",
                "boolean",
                default=True,
                description="Text extracted from uploaded documents and fetched pages (WP-D1).",
            ),
            SettingField(
                "pause_tool_classes",
                "Tool classes that may be paused",
                "array",
                default=[],
                items="string",
                item_enum=PAUSE_CLASSES_ALLOWED,
                max_length=len(PAUSE_CLASSES_ALLOWED),
                description="A finding at or above the pause bar on one of these classes carries "
                "the pause hint, but only when the model card approval names the approver. "
                "Empty = findings only.",
            ),
            SettingField(
                "pause_threshold_bp",
                "Pause bar (bp)",
                "integer",
                default=None,
                minimum=0,
                maximum=SCORE_MAX,
                description="Default: the permissive threshold of the label. It can be raised, "
                "never lowered below that.",
            ),
            SettingField(
                "max_windows",
                "Windows scored per call",
                "integer",
                default=DEFAULT_MAX_WINDOWS,
                minimum=1,
                maximum=64,
                description="Windows are 2,000 characters; more are spread over the text.",
            ),
        )
    )

    def __init__(
        self,
        masker: Masker,
        port: GuardModelPort | None = None,
        *,
        card_path: Path | str | None = None,
    ) -> None:
        self.masker = masker
        self._port = port
        self._card = Path(card_path) if card_path else MODEL_CARD
        self._cache: OrderedDict[tuple[str, str], GuardScore] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def port(self) -> GuardModelPort | None:
        return self._port

    def set_port(self, port: GuardModelPort | None) -> None:
        """Wire the model (start-up). Scores of another model are not reused."""
        self._port = port

    # ------------------------------------------------------------------ approval
    def approved(self) -> bool:
        """True when the card approval names the approver and the model the port serves."""
        port = self._port
        if port is None or port.is_mock:
            return False
        key = f"{self._card}|{port.model_id}"
        now = time.monotonic()
        hit = _APPROVAL_CACHE.get(key)
        if hit is not None and now - hit[0] < APPROVAL_TTL_S:
            return hit[1]
        ok = _approval_matches(self._card, port.model_id)
        _APPROVAL_CACHE[key] = (now, ok)
        return ok

    def fail_closed_allowed(self) -> bool:
        """False unless ``GUARD_MODEL_FAIL_CLOSED_APPROVED=1`` AND the card approval is valid:
        the registry then ignores ``fail_closed: true`` (R1: a model outage must not stop
        payments without a named owner)."""
        try:
            from supervisor.config import load_settings

            flag = bool(load_settings().guard_model_fail_closed_approved)
        except Exception:  # noqa: BLE001 - a settings problem means "not approved"
            flag = False
        return flag and self.approved()

    # ------------------------------------------------------------------ units
    def _units(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[_Unit]:
        meta = payload.get("meta") or {}
        units: list[_Unit] = []

        def mask_into(unit: _Unit, leaves: Any, prefix: str = "") -> None:
            for leaf in leaves:
                if _is_system_path(leaf.path):
                    continue
                unit.add(
                    prefix + leaf.path[1:] if prefix else leaf.path, self.masker.mask(leaf.text)
                )

        if direction == "input":
            if settings.get("scan_args", True) and payload.get("args") is not None:
                u = _Unit("args", "args")
                mask_into(u, walk_leaves("args", payload["args"]))
                units.append(u)
            results = payload.get("tool_results")
            if settings.get("scan_tool_results", True) and results is not None:
                u = _Unit("tool_results", "tool_results")
                items = results if isinstance(results, list | tuple) else [results]
                for k, res in enumerate(items):
                    mask_into(u, walk_leaves("tool_results", res), f"$[{k}]")
                units.append(u)
            if settings.get("scan_tool_descriptions", True):
                descs = _descriptions(meta)
                if descs:
                    u = _Unit("tool_description", "tool_description")
                    for i, d in enumerate(descs):
                        u.add("$" if len(descs) == 1 else f"$[{i}]", self.masker.mask(d))
                    units.append(u)
            if settings.get("scan_documents", True) and payload.get("documents") is not None:
                u = _Unit("documents", "documents")
                mask_into(u, walk_leaves("documents", payload["documents"]))
                units.append(u)
        elif settings.get("scan_tool_results", True) and payload.get("output") is not None:
            u = _Unit("tool_results", "output")
            mask_into(u, walk_leaves("output", payload["output"]))
            units.append(u)
        return [u for u in units if u.text.strip()]

    # ------------------------------------------------------------------ scoring
    def _score_texts(self, port: GuardModelPort, texts: list[str]) -> dict[str, GuardScore]:
        """Score each distinct text once (cache first, then one batch to the port)."""
        out: dict[str, GuardScore] = {}
        todo: list[str] = []
        with self._lock:
            for t in dict.fromkeys(texts):
                key = (port.model_id, hashlib.sha256(t.encode("utf-8", "replace")).hexdigest())
                hit = self._cache.get(key)
                if hit is not None:
                    self._cache.move_to_end(key)
                    out[t] = hit
                else:
                    todo.append(t)
        if todo:
            scores = port.score(todo)
            if len(scores) != len(todo):
                raise GuardModelError("guard model answered the wrong number of scores")
            with self._lock:
                for t, s in zip(todo, scores, strict=True):
                    out[t] = s
                    key = (port.model_id, hashlib.sha256(t.encode("utf-8", "replace")).hexdigest())
                    self._cache[key] = s
                    while len(self._cache) > CACHE_SIZE:
                        self._cache.popitem(last=False)
        return out

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        did = detector_id(self)
        preset = str(settings.get("preset") or "balanced")
        port = self._port
        if port is None:
            return [not_executed(self.slug, did, "execution_failed", "no guard model", preset)]
        try:
            return self._evaluate(port, payload, settings, direction, did, preset)
        except GuardModelError as exc:
            reason = (
                exc.reason
                if exc.reason in ("timed_out", "execution_failed")
                else ("execution_failed")
            )
            return [not_executed(self.slug, did, reason, str(exc)[:80], preset)]
        except Exception as exc:  # noqa: BLE001 - an adapter bug must never reach the gate
            return [not_executed(self.slug, did, "execution_failed", type(exc).__name__, preset)]

    def _evaluate(
        self,
        port: GuardModelPort,
        payload: Mapping[str, Any],
        settings: Mapping[str, Any],
        direction: str,
        did: str,
        preset: str,
    ) -> list[Finding]:
        units = self._units(payload, settings, direction)
        if not units:
            return []
        cap = max(1, int(settings.get("max_windows") or DEFAULT_MAX_WINDOWS))
        per_unit = max(1, cap // len(units))
        plan: list[tuple[_Unit, list[tuple[int, int]]]] = [
            (u, spread(windows(u.text), per_unit)) for u in units
        ]
        texts = [u.text[s:e] for u, wins in plan for s, e in wins]
        scored = self._score_texts(port, texts)
        # the best window of every unit, then the best unit of every label
        best: dict[str, tuple[int, _Unit, tuple[int, int]]] = {}
        for u, wins in plan:
            default = SURFACE_LABEL[u.surface]
            top: tuple[int, str, tuple[int, int]] = (0, default, wins[0])
            for s, e in wins:
                sc = scored[u.text[s:e]]
                if sc["label"] == "benign":
                    continue
                bp = max(0, min(SCORE_MAX, int(sc["score_bp"])))
                label = default if sc["label"] == "malicious" else sc["label"]
                if bp > top[0]:
                    top = (bp, label, (s, e))
            bp, label, win = top
            if label not in best or bp > best[label][0]:
                best[label] = (bp, u, win)
        pause_classes = set(settings.get("pause_tool_classes") or ())
        risk = (payload.get("meta") or {}).get("risk_class")
        may_pause = direction == "input" and risk in pause_classes and self.approved()
        out: list[Finding] = []
        for label in LABELS:
            if label not in best:
                continue
            bp, u, (s, e) = best[label]
            threshold = label_threshold(settings, label)
            fired = bp >= threshold
            frags: tuple[Fragment, ...] = ()
            if fired:
                loc = u.locate(s, e)
                if loc is not None:
                    path, masked, lo, hi = loc
                    frags = (Fragment(u.part, path, lo, hi, clip(masked, lo, hi), "span"),)
            hint = (
                "pause"
                if fired and may_pause and bp >= pause_threshold(settings, label)
                else "report"
            )
            out.append(
                Finding(
                    detector_slug=self.slug,
                    detector_id=did,
                    code=CODE_BY_LABEL[label],
                    score_bp=bp,
                    threshold_bp=threshold,
                    fragments=frags,
                    action_hint=hint,  # type: ignore[arg-type]
                    preset=preset,
                    is_mock=bool(port.is_mock),
                )
            )
        return out


__all__ = [
    "LABEL_PRESETS",
    "PRESETS",
    "GuardModelDetector",
    "label_threshold",
    "pause_threshold",
    "reset_approval_cache",
    "windows",
]
