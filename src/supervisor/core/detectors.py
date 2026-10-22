"""Detector contract and registry (WP37, ADR D23). Pure Python: no I/O, no model, no network.

A *detector* looks at the parts of one gate call (``args``, ``tool_results``, ``output``) and
returns *findings*. The gate asks the registry to run every enabled detector whose ``sides``
include the direction of the call, and folds the findings into the verdict (``status``,
``findings``, ``not_executed``, ``coverage``, ``transformed_payload``).

Rules the code keeps:

* R1. A finding is advice. Its ``action_hint`` may be ``report`` or ``transform`` in this
  version; ``pause`` and ``block`` are declared for later packages, and :func:`derive_status`
  clamps them to ``report``. Only the documented rules decide (docs/detectors.md section 4).
* R2. Entities and fragments carry MASKED text only. Offsets point into the masked text, never
  into the raw text. The chain gets hashes (:meth:`Finding.digest`), never text.
* R3. Nothing here opens a socket or loads a model.

Payload shape handed to ``Detector.evaluate``::

    {"args": {...}, "tool_results": [...], "output": "...", "meta": {"tool_name": ..., ...}}

Only the parts that apply to the direction are present: ``args`` and ``tool_results`` for an
``input`` check, ``output`` for an ``output`` check. ``meta`` is always there.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, runtime_checkable

from supervisor.core.canonical import canonical_json

Direction = Literal["input", "output"]
ProtocolName = Literal["llm", "mcp", "a2a", "all"]
ActionHint = Literal["report", "transform", "pause", "block"]
Status = Literal["allow", "report", "transform", "pause", "block", "skip"]
FieldType = Literal["string", "integer", "number", "boolean", "enum", "array", "object"]

DIRECTIONS: tuple[str, ...] = ("input", "output")
PROTOCOLS: tuple[str, ...] = ("llm", "mcp", "a2a", "all")
ACTION_HINTS: tuple[str, ...] = ("report", "transform", "pause", "block")
STATUSES: tuple[str, ...] = ("allow", "report", "transform", "pause", "block", "skip")
FIELD_TYPES: tuple[str, ...] = ("string", "integer", "number", "boolean", "enum", "array", "object")

# Why a detector did not run (or did not finish). A fixed list: the console groups by it.
NOT_EXECUTED_REASONS: tuple[str, ...] = (
    "execution_failed",
    "invalid_config",
    "payload_too_large",
    "content_uninspectable",
    "not_applicable_for_direction",
    "timed_out",
    "budget_exhausted",  # WP-D4: a budgeted detector (judge_moderation) stopped asking
)
# Reasons that mean "we could not look". Fail closed on money, credit and PII-export tools.
FAILURE_REASONS: frozenset[str] = frozenset(NOT_EXECUTED_REASONS) - {"not_applicable_for_direction"}

# Parts of a payload, in the order coverage lists them.
PARTS: tuple[str, ...] = ("args", "tool_results", "output")
PARTS_BY_DIRECTION: dict[str, tuple[str, ...]] = {
    "input": ("args", "tool_results"),
    "output": ("output",),
}

# WP-D1: the part that holds the text of documents and fetched pages ([{name, text}]). It is in the
# payload only when document intake is on and the call carried documents; a detector sees it only
# when its ``parts`` attribute lists it. It is read after the arguments and the tool results.
DOCUMENT_PART = "documents"


def _reads_documents(det: object) -> bool:
    return DOCUMENT_PART in getattr(det, "parts", ())


def parts_for(
    payload: Mapping[str, Any], direction: str, det: object | None = None
) -> tuple[str, ...]:
    """The payload parts a detector reads on this call: the parts of the direction, plus
    ``documents`` when the payload has it and the detector lists it in ``parts``."""
    base = PARTS_BY_DIRECTION[direction]
    if (
        direction == "input"
        and payload.get(DOCUMENT_PART) is not None
        and (det is None or DOCUMENT_PART in getattr(det, "parts", ()))
    ):
        return (*base, DOCUMENT_PART)
    return base


# Verdict precedence. Index = rank; the highest rank wins. ``skip`` is not in the list: it is
# decided by a policy rule before any detector runs (see :func:`derive_status`).
PRECEDENCE: tuple[str, ...] = ("allow", "report", "transform", "pause", "block")

MAX_DEPTH = 12
# D30 / D18 (WP41): the most text one detector scans per call, and the most text all detectors
# together scan per call (the "scan budget"). Both in UTF-8 bytes.
DEFAULT_MAX_SCAN_BYTES = 16_384
DEFAULT_SCAN_BUDGET_BYTES = 65_536
DEFAULT_DOCUMENT_SCAN_BYTES = 262_144  # WP-D1
MAX_FRAGMENTS = 20
FRAGMENT_TEXT_MAX = 120
SCORE_MAX = 10_000

REPORT_ONLY_HINTS: frozenset[str] = frozenset({"pause", "block"})  # clamped to report (R1)

# Detector categories that may never fail closed, whatever the config says (R1: a judge or an
# advisor that cannot answer must not stop a payment). Enforced in ``DetectorRegistry.run``.
ADVISORY_CATEGORIES: frozenset[str] = frozenset({"advisory"})

# Bounded execution: each detector call runs in its own daemon thread and the gate waits at
# most ``RunConfig.timeout_ms``. A hung detector keeps its thread (Python cannot kill one) but
# never the gate worker. At most MAX_DETECTOR_THREADS calls may be in flight; with no free slot
# the call is not started and is reported ``timed_out`` at once (bounded threads, bounded wait).
MAX_DETECTOR_THREADS = 32
_SLOTS = threading.BoundedSemaphore(MAX_DETECTOR_THREADS)


class _NoSlot(Exception):
    """Every detector thread slot is held (hung detectors)."""


def _call_bounded(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run ``fn`` in a daemon thread; wait at most ``timeout_s``. Raises ``TimeoutError`` on a
    deadline miss, ``_NoSlot`` when no thread slot is free, else re-raises ``fn``'s error."""
    if not _SLOTS.acquire(blocking=False):
        raise _NoSlot
    box: dict[str, Any] = {}
    done = threading.Event()

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - handed back to the caller
            box["error"] = exc
        finally:
            _SLOTS.release()
            done.set()

    try:
        threading.Thread(target=target, name="detector", daemon=True).start()
    except BaseException:
        _SLOTS.release()
        raise
    if not done.wait(timeout_s):
        raise TimeoutError
    if "error" in box:
        raise box["error"]
    return box["value"]


# ---------------------------------------------------------------------------- settings schema


@dataclass(frozen=True)
class SettingField:
    """One setting of a detector. ``type`` is one of FIELD_TYPES.

    ``enum`` lists the allowed values of an ``enum`` field (strings). ``items`` is the type of
    the elements of an ``array`` field (and ``item_enum`` their allowed values). ``fields``
    are the nested fields of an ``object`` field. ``minimum``/``maximum`` bound integers and
    numbers; ``max_length`` bounds strings and arrays."""

    key: str
    label: str
    type: FieldType
    required: bool = False
    default: Any = None
    enum: tuple[str, ...] = ()
    items: FieldType | None = None
    item_enum: tuple[str, ...] = ()
    fields: tuple[SettingField, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    max_length: int = 256
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "default": self.default,
        }
        if self.enum:
            out["enum"] = list(self.enum)
        if self.items:
            out["items"] = self.items
        if self.item_enum:
            out["item_enum"] = list(self.item_enum)
        if self.fields:
            out["fields"] = [f.to_dict() for f in self.fields]
        if self.minimum is not None:
            out["minimum"] = self.minimum
        if self.maximum is not None:
            out["maximum"] = self.maximum
        if self.description:
            out["description"] = self.description
        return out


def _is_type(value: Any, typ: str) -> bool:
    if typ == "string":
        return isinstance(value, str)
    if typ == "boolean":
        return isinstance(value, bool)
    if typ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if typ == "enum":
        return isinstance(value, str)
    if typ == "array":
        return isinstance(value, list)
    if typ == "object":
        return isinstance(value, Mapping)
    return False


def _check_field(f: SettingField, value: Any, where: str, errors: list[str]) -> Any:
    if not _is_type(value, f.type):
        errors.append(f"{where}: expected {f.type}")
        return value
    if f.type == "enum" and value not in f.enum:
        errors.append(f"{where}: must be one of {', '.join(f.enum)}")
    elif f.type == "string" and len(value) > f.max_length:
        errors.append(f"{where}: longer than {f.max_length} characters")
    elif f.type in ("integer", "number"):
        if f.minimum is not None and value < f.minimum:
            errors.append(f"{where}: below {f.minimum}")
        if f.maximum is not None and value > f.maximum:
            errors.append(f"{where}: above {f.maximum}")
    elif f.type == "array":
        if len(value) > f.max_length:
            errors.append(f"{where}: more than {f.max_length} items")
        for i, item in enumerate(value):
            if f.items is not None and not _is_type(item, f.items):
                errors.append(f"{where}[{i}]: expected {f.items}")
            elif f.item_enum and item not in f.item_enum:
                errors.append(f"{where}[{i}]: must be one of {', '.join(f.item_enum)}")
    elif f.type == "object" and f.fields:
        return _validate_fields(f.fields, value, where, errors)
    return value


def _validate_fields(
    fields: Sequence[SettingField], values: Mapping[str, Any], where: str, errors: list[str]
) -> dict[str, Any]:
    known = {f.key: f for f in fields}
    for key in values:
        if key not in known:
            errors.append(f"{where}.{key}: unknown setting")
    out: dict[str, Any] = {}
    for f in fields:
        here = f"{where}.{f.key}" if where else f.key
        if f.key in values and values[f.key] is not None:
            out[f.key] = _check_field(f, values[f.key], here, errors)
        elif f.required and f.default is None:
            errors.append(f"{here}: required")
        else:
            out[f.key] = f.default
    return out


@dataclass(frozen=True)
class SettingsSchema:
    """Declarative settings of one detector: a list of fields, validated without code."""

    fields: tuple[SettingField, ...] = ()

    def validate(self, values: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
        """(settings with defaults filled, error list). Unknown keys are errors."""
        errors: list[str] = []
        clean = _validate_fields(self.fields, dict(values or {}), "", errors)
        return clean, errors

    def defaults(self) -> dict[str, Any]:
        return {f.key: f.default for f in self.fields}

    def to_dict(self) -> list[dict[str, Any]]:
        return [f.to_dict() for f in self.fields]


def common_fields(presets: Iterable[str]) -> tuple[SettingField, ...]:
    """Fields every detector has: the named sensitivity preset and an explicit threshold."""
    return (
        SettingField(
            "preset",
            "Sensitivity preset",
            "enum",
            default="balanced",
            enum=tuple(presets),
            description="Named threshold, frozen per version.",
        ),
        SettingField(
            "threshold_bp",
            "Threshold override (bp)",
            "integer",
            default=None,
            minimum=0,
            maximum=SCORE_MAX,
            description="Explicit threshold in basis points; replaces the preset when set.",
        ),
        SettingField(
            "max_scan_bytes",
            "Largest text this detector scans per call (bytes)",
            "integer",
            default=DEFAULT_MAX_SCAN_BYTES,
            minimum=256,
            maximum=1_000_000,
            description=(
                "Text beyond this is not scanned (coverage payload_too_large). Arguments are "
                "scanned first, tool results last."
            ),
        ),
    )


# ---------------------------------------------------------------------------- finding


@dataclass(frozen=True)
class Entity:
    """A detected entity, MASKED: a type and the pseudonym token, never the value."""

    type: str
    token: str | None = None
    count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "token": self.token, "count": self.count}


@dataclass(frozen=True)
class Fragment:
    """A located piece of MASKED text. ``start``/``end`` index ``text``'s parent: the masked
    leaf at ``path`` of ``part``. ``precision`` is ``span`` (exact) or ``leaf`` (the detector
    matched a normalised form and can only point at the whole leaf)."""

    part: str
    path: str
    start: int
    end: int
    text: str
    precision: Literal["span", "leaf"] = "span"

    def to_dict(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "path": self.path,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "precision": self.precision,
        }

    def digest(self) -> str:
        data = f"{self.part}\x1f{self.path}\x1f{self.start}\x1f{self.end}\x1f{self.text}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class Finding:
    """One result of one detector. ``not_executed_reason`` is None when the detector ran.

    ``transformed_payload`` (dlp only) is the payload parts after the transform; it is handed
    to the verdict and is never part of ``to_dict`` or the digest."""

    detector_slug: str
    detector_id: str
    code: str
    score_bp: int = 0
    threshold_bp: int = 0
    entities: tuple[Entity, ...] = ()
    fragments: tuple[Fragment, ...] = ()
    masked_count: int = 0
    action_hint: ActionHint = "report"
    not_executed_reason: str | None = None
    detail: str = ""  # fixed short text (an error class name at most), never input text
    preset: str | None = None
    is_mock: bool = False
    transformed_payload: Mapping[str, Any] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.not_executed_reason is not None and self.not_executed_reason not in (
            NOT_EXECUTED_REASONS
        ):
            raise ValueError(f"unknown not_executed_reason {self.not_executed_reason!r}")
        if self.action_hint not in ACTION_HINTS:
            raise ValueError(f"unknown action_hint {self.action_hint!r}")
        if type(self.score_bp) is not int or not 0 <= self.score_bp <= SCORE_MAX:
            raise ValueError("score_bp must be an integer between 0 and 10000")

    @property
    def fired(self) -> bool:
        # A finding that transformed the payload is always reported: the payload changed.
        return self.not_executed_reason is None and (
            self.score_bp >= self.threshold_bp or self.action_hint == "transform"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_slug": self.detector_slug,
            "detector_id": self.detector_id,
            "code": self.code,
            "score_bp": self.score_bp,
            "threshold_bp": self.threshold_bp,
            "entities": [e.to_dict() for e in self.entities],
            "fragments": [f.to_dict() for f in self.fragments[:MAX_FRAGMENTS]],
            "masked_count": self.masked_count,
            "action_hint": self.action_hint,
            "not_executed_reason": self.not_executed_reason,
            "preset": self.preset,
            "mock": self.is_mock,
        }

    def digest(self) -> str:
        """SHA-256 over the finding without any text: ids, code, integers, token hashes and
        fragment digests. This is what the evidence chain keeps."""
        doc = {
            "slug": self.detector_slug,
            "id": self.detector_id,
            "code": self.code,
            "score_bp": self.score_bp,
            "threshold_bp": self.threshold_bp,
            "masked_count": self.masked_count,
            "action_hint": self.action_hint,
            "reason": self.not_executed_reason,
            "entities": sorted(
                hashlib.sha256(f"{e.type}:{e.token}:{e.count}".encode()).hexdigest()[:16]
                for e in self.entities
            ),
            "fragments": sorted(f.digest() for f in self.fragments[:MAX_FRAGMENTS]),
        }
        return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


def not_executed(
    slug: str, detector_id: str, reason: str, detail: str = "", preset: str | None = None
) -> Finding:
    """A finding for a detector that did not run (score 0, never fires)."""
    return Finding(
        detector_slug=slug,
        detector_id=detector_id,
        code=f"not_executed.{reason}",
        not_executed_reason=reason,
        detail=detail[:80],
        preset=preset,
    )


# ---------------------------------------------------------------------------- the contract


@runtime_checkable
class Detector(Protocol):
    """One detector. Pure: same payload and settings give the same findings.

    ``sides``: directions it runs on. ``protocols``: gate protocols it applies to (``all`` =
    every protocol). ``presets``: named thresholds in basis points, frozen per ``version``.
    ``evaluate`` returns the findings (a fired one carries ``score_bp >= threshold_bp``), may
    return sub-threshold or not-executed findings, and must not raise for bad input; the
    registry still catches an exception and reports ``execution_failed``."""

    slug: str
    name: str
    category: str
    version: str
    sides: tuple[str, ...]
    protocols: tuple[str, ...]
    settings_schema: SettingsSchema
    presets: Mapping[str, int]

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]: ...


def detector_id(det: Detector) -> str:
    return f"{det.slug}@{det.version}"


def threshold_for(det: Detector, settings: Mapping[str, Any]) -> int:
    """Threshold in bp: the explicit ``threshold_bp`` if set, else the preset's value."""
    explicit = settings.get("threshold_bp")
    if isinstance(explicit, int) and not isinstance(explicit, bool):
        return explicit
    return int(det.presets[str(settings.get("preset") or "balanced")])


def full_schema(det: Detector) -> SettingsSchema:
    """The detector's own fields plus the common ones (preset, threshold_bp)."""
    return SettingsSchema(common_fields(det.presets) + tuple(det.settings_schema.fields))


# ---------------------------------------------------------------------------- payload walking


@dataclass(frozen=True)
class Leaf:
    part: str
    path: str
    text: str


_SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _key(k: object) -> str:
    """A dict key as a path segment. A key that is not a plain identifier could hold personal
    data (a name or a number used as a key), so it is shown as ``*`` (R2)."""
    text = str(k)
    return text if _SAFE_KEY.match(text) else "*"


def walk_leaves(
    part: str, value: Any, path: str = "$", depth: int = 0, bad: list[str] | None = None
) -> Iterator[Leaf]:
    """Every string leaf of ``value`` with its JSON-like path. Leaves of another kind that a
    detector cannot read (bytes, objects, a value deeper than MAX_DEPTH) are appended to
    ``bad``. Numbers, booleans and null are skipped silently: they hold no text."""
    if depth > MAX_DEPTH:
        if bad is not None:
            bad.append(path)
        return
    if isinstance(value, str):
        yield Leaf(part, path, value)
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from walk_leaves(part, v, f"{path}.{_key(k)}", depth + 1, bad)
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            yield from walk_leaves(part, v, f"{path}[{i}]", depth + 1, bad)
    elif isinstance(value, bool | int | float) or value is None:
        return
    elif bad is not None:
        bad.append(path)


def map_leaves(value: Any, fn: Callable[[str], str], depth: int = 0) -> Any:
    """Copy of ``value`` with ``fn`` applied to every string leaf (same shape)."""
    if depth > MAX_DEPTH:
        return value
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, Mapping):
        return {k: map_leaves(v, fn, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [map_leaves(v, fn, depth + 1) for v in value]
    return value


def clip(text: str, start: int, end: int) -> str:
    """Excerpt of masked text for a fragment, at most FRAGMENT_TEXT_MAX characters."""
    return text[start:end][:FRAGMENT_TEXT_MAX]


# ---------------------------------------------------------------------------- run


@dataclass(frozen=True)
class DetectorSetting:
    """Resolved setting of one detector for one call: on/off, preset, values, fail mode."""

    enabled: bool = True
    settings: Mapping[str, Any] = field(default_factory=dict)  # includes preset/threshold_bp
    fail_closed: bool = True  # a failure on a money / credit / pii_export tool blocks (D23)


@dataclass(frozen=True)
class RunConfig:
    """Everything the registry needs for one call, resolved by the caller."""

    detectors: Mapping[str, DetectorSetting]
    max_payload_chars: int = 100_000
    timeout_ms: int = 500
    fail_closed_risk_classes: frozenset[str] = frozenset({"money", "credit", "pii_export"})
    scan_budget_bytes: int = DEFAULT_SCAN_BUDGET_BYTES  # WP41: all detectors together, per call
    # WP-D1: documents have their own budget (per detector, per call) and do not count in
    # max_payload_chars or in scan_budget_bytes, so a long document can never switch off the
    # scan of the arguments
    document_max_scan_bytes: int = DEFAULT_DOCUMENT_SCAN_BYTES


@dataclass
class RunResult:
    """What the registry hands back to the gate."""

    findings: list[Finding] = field(default_factory=list)  # fired, in catalogue order
    evaluated: list[str] = field(default_factory=list)  # slugs that ran to the end
    not_executed: list[Finding] = field(default_factory=list)
    transformed_payload: dict[str, Any] | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    latency_us: int = 0
    per_detector_us: dict[str, int] = field(default_factory=dict)
    failed_closed: list[Finding] = field(default_factory=list)  # failures that block here


def _without_parts(f: Finding, parts: set[str]) -> Finding:
    """``f`` with the named parts removed from its transformed payload."""
    if not f.transformed_payload:
        return f
    keep = {k: v for k, v in f.transformed_payload.items() if k not in parts}
    return replace(f, transformed_payload=keep or None)


# WP41 review: the parts whose transformed copy a caller applies (the tool gets the masked
# arguments, the user gets the masked output). A cut tool result is never applied.
APPLIED_PARTS: frozenset[str] = frozenset({"args", "output"})


def _transforms_here(det: Any, settings: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    """True when ``det`` would transform this call (its optional ``transforms_here`` hook)."""
    hook = getattr(det, "transforms_here", None)
    try:
        return bool(hook(settings, meta)) if callable(hook) else False
    except Exception:  # noqa: BLE001 - when in doubt, treat it as a transforming detector
        return True


def _text_chars(part_value: Any) -> int:
    return sum(len(leaf.text) for leaf in walk_leaves("x", part_value))


def _utf8_len(text: str) -> int:
    return len(text) if text.isascii() else len(text.encode("utf-8", "replace"))


def _clip_text(text: str, nbytes: int) -> str:
    if nbytes <= 0:
        return ""
    if text.isascii():
        return text[:nbytes]
    return text.encode("utf-8", "replace")[:nbytes].decode("utf-8", "ignore")


def _clip_value(value: Any, left: list[int], depth: int = 0) -> Any:
    """Copy of ``value`` whose string leaves, in walk order, hold at most ``left[0]`` bytes in
    all. The shape (and so every leaf path) is kept; a leaf past the limit becomes ''."""
    if depth > MAX_DEPTH:
        return value
    if isinstance(value, str):
        out = _clip_text(value, left[0])
        left[0] -= _utf8_len(out)
        return out
    if isinstance(value, Mapping):
        return {k: _clip_value(v, left, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clip_value(v, left, depth + 1) for v in value]
    return value


def clipped_view(
    payload: Mapping[str, Any],
    parts: Sequence[str],
    part_bytes: Mapping[str, int],
    limit: int,
) -> tuple[Mapping[str, Any], dict[str, int], set[str]]:
    """The payload as ONE detector may see it: at most ``limit`` bytes of text, parts in
    ``parts`` order (arguments before tool results). Returns (view, scanned bytes per part,
    clipped parts). The payload itself is returned when everything fits (no copy)."""
    present = [p for p in parts if p in part_bytes]
    if sum(part_bytes[p] for p in present) <= limit:
        return payload, {p: part_bytes[p] for p in present}, set()
    view = dict(payload)
    left = [limit]
    scanned: dict[str, int] = {}
    clipped: set[str] = set()
    for p in present:
        before = left[0]
        view[p] = _clip_value(payload[p], left)
        scanned[p] = before - left[0]
        if scanned[p] < part_bytes[p]:
            clipped.add(p)
    return view, scanned, clipped


class DetectorRegistry:
    """The catalogue (from code) and the runner."""

    def __init__(self, detectors: Iterable[Detector] = ()) -> None:
        self._by_slug: dict[str, Detector] = {}
        for d in detectors:
            self.register(d)

    def register(self, det: Detector) -> None:
        if det.slug in self._by_slug:
            raise ValueError(f"detector {det.slug} is registered twice")
        bad_sides = [s for s in det.sides if s not in DIRECTIONS]
        bad_protocols = [p for p in det.protocols if p not in PROTOCOLS]
        if bad_sides or bad_protocols or not det.sides or not det.protocols:
            raise ValueError(f"detector {det.slug}: bad sides or protocols")
        if "balanced" not in det.presets:
            raise ValueError(f"detector {det.slug}: presets need a 'balanced' entry")
        self._by_slug[det.slug] = det

    def __contains__(self, slug: object) -> bool:
        return slug in self._by_slug

    def get(self, slug: str) -> Detector:
        return self._by_slug[slug]

    @property
    def slugs(self) -> list[str]:
        return list(self._by_slug)

    def _head_scan(
        self,
        res: RunResult,
        det: Any,
        st: DetectorSetting,
        payload: Mapping[str, Any],
        all_part_bytes: Mapping[str, int],
        parts_here: Sequence[str],
        direction: str,
        config: RunConfig,
        clock_ns: Callable[[], int],
    ) -> None:
        """WP-D2: a payload over ``max_payload_chars`` is skipped by every detector, except one
        that declares ``scan_head_when_oversize`` and whose ``head_scan_here(settings)`` is
        true (dlp_vn with secrets.action block). It reads the first ``max_scan_bytes`` of the
        arguments only, never transforms, and only a ``block`` finding counts. The
        ``payload_too_large`` row stays (risky tools still fail closed); a coverage note says
        how much was read. A padded payload must not be a way past the secrets check."""
        hook = getattr(det, "head_scan_here", None)
        if (
            not getattr(det, "scan_head_when_oversize", False)
            or not callable(hook)
            or "args" not in parts_here
            or "args" not in all_part_bytes
        ):
            return
        clean, errors = self.validate_settings(det.slug, st.settings)
        if errors or not hook(clean):
            return
        limit = int(clean.get("max_scan_bytes") or DEFAULT_MAX_SCAN_BYTES)
        view, scanned, _ = clipped_view(payload, ("args",), {"args": all_part_bytes["args"]}, limit)
        head = {"args": view["args"], "meta": payload.get("meta")}
        t0 = clock_ns()
        try:
            found = _call_bounded(
                lambda: det.evaluate(head, clean, direction), config.timeout_ms / 1000
            )
        except Exception:  # noqa: BLE001 - the payload_too_large row already stands
            return
        res.per_detector_us[det.slug] = (clock_ns() - t0) // 1000
        res.evaluated.append(det.slug)
        for f in found:
            if f.action_hint == "block" and f.not_executed_reason is None and f.fired:
                res.findings.append(replace(f, transformed_payload=None))
        res.coverage.setdefault("notes", []).append(
            {
                "detector": det.slug,
                "reason": "head_only",
                "detail": f"head only: {scanned['args']} of {all_part_bytes['args']} bytes",
            }
        )

    def _closes(self, ne: Finding, config: RunConfig) -> bool:
        """True when this not-executed row blocks a risky tool: its detector is set to fail
        closed and may (R1), or, for a row of the whole call (slug ``*``), any enabled one is."""
        if ne.detector_slug == "*":
            return any(
                s.enabled and s.fail_closed and self.may_fail_closed(slug)
                for slug, s in config.detectors.items()
            )
        st = config.detectors.get(ne.detector_slug)
        return st is not None and st.fail_closed and self.may_fail_closed(ne.detector_slug)

    def may_fail_closed(self, slug: str) -> bool:
        """False for an unknown slug and for an advisory detector (R1), whatever the config."""
        det = self._by_slug.get(slug)
        if det is None or det.category in ADVISORY_CATEGORIES:
            return False
        # WP25: a detector may veto fail-closed itself (the classifier needs a named approver)
        veto = getattr(det, "fail_closed_allowed", None)
        return bool(veto()) if callable(veto) else True

    def catalogue(self) -> list[dict[str, Any]]:
        """The catalogue served from code: one entry per detector, schema included."""
        out = []
        for d in self._by_slug.values():
            out.append(
                {
                    "slug": d.slug,
                    "name": d.name,
                    "category": d.category,
                    "version": d.version,
                    "detector_id": detector_id(d),
                    "sides": list(d.sides),
                    "protocols": list(d.protocols),
                    "presets": dict(d.presets),
                    "settings_schema": full_schema(d).to_dict(),
                }
            )
        return out

    def validate_settings(
        self, slug: str, values: Mapping[str, Any] | None
    ) -> tuple[dict[str, Any], list[str]]:
        """(clean settings with defaults, errors) for one detector."""
        return full_schema(self._by_slug[slug]).validate(values)

    # ------------------------------------------------------------------ run

    def run(
        self,
        payload: Mapping[str, Any],
        direction: str,
        config: RunConfig,
        *,
        protocol: str = "llm",
        risk_class: str | None = None,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> RunResult:
        t_start = clock_ns()
        res = RunResult()
        has_docs = direction == "input" and payload.get(DOCUMENT_PART) is not None
        parts_here = parts_for(payload, direction)
        inspected: list[str] = []
        not_inspected: list[dict[str, Any]] = []
        too_large = False
        uninspectable = False
        total = 0
        doc_chars = 0
        part_bytes: dict[str, int] = {}
        for part in (*PARTS, *((DOCUMENT_PART,) if has_docs else ())):
            if part not in parts_here:
                not_inspected.append({"part": part, "reason": "not_applicable_for_direction"})
                continue
            if part not in payload or payload[part] is None:
                not_inspected.append({"part": part, "reason": "not_provided"})
                continue
            bad: list[str] = []
            n = 0
            nb = 0
            for leaf in walk_leaves(part, payload[part], "$", 0, bad):
                n += len(leaf.text)
                nb += _utf8_len(leaf.text)
            if part == DOCUMENT_PART:
                doc_chars = n  # WP-D1: not part of max_payload_chars
            else:
                total += n
            part_bytes[part] = nb
            if bad:
                uninspectable = True
                not_inspected.append(
                    {"part": part, "reason": "content_uninspectable", "paths": bad[:5]}
                )
            else:
                inspected.append(part)
        if total > config.max_payload_chars:
            too_large = True
            not_inspected = [
                *[n for n in not_inspected if n["reason"] != "content_uninspectable"],
                *[{"part": p, "reason": "payload_too_large"} for p in inspected],
            ]
            inspected = []
        res.coverage = {
            "direction": direction,
            "inspected": inspected,
            "not_inspected": not_inspected,
            "chars": total + doc_chars,
        }
        all_part_bytes = dict(part_bytes)  # WP-D2: for the head scan of an oversize payload
        part_bytes = {p: b for p, b in part_bytes.items() if p in inspected}
        budget_left = config.scan_budget_bytes
        scanned_min: dict[str, int] = {}  # per part: the least any detector scanned

        merged: dict[str, Any] = {}
        notes: list[dict[str, str]] = []  # WP-D2: coverage notes, never a failure
        for slug, det in self._by_slug.items():
            st = config.detectors.get(slug)
            if st is None or not st.enabled:
                continue
            did = detector_id(det)
            preset = str(st.settings.get("preset") or "balanced")
            if direction not in det.sides:
                res.not_executed.append(
                    not_executed(slug, did, "not_applicable_for_direction", preset=preset)
                )
                continue
            if protocol not in det.protocols and "all" not in det.protocols:
                continue  # another transport: not a gap, listed nowhere
            if too_large:
                res.not_executed.append(not_executed(slug, did, "payload_too_large", preset=preset))
                self._head_scan(
                    res, det, st, payload, all_part_bytes, parts_here, direction, config, clock_ns
                )
                continue
            clean, errors = self.validate_settings(slug, st.settings)
            if errors:
                res.not_executed.append(
                    not_executed(slug, did, "invalid_config", errors[0], preset=preset)
                )
                continue
            # WP41 (D30, D18): this detector sees at most max_scan_bytes of text, and all
            # detectors together at most the call's scan budget. Arguments first, results last.
            limit = min(int(clean.get("max_scan_bytes") or DEFAULT_MAX_SCAN_BYTES), budget_left)
            det_parts = tuple(p for p in parts_here if p != DOCUMENT_PART)
            reads_docs = DOCUMENT_PART in parts_here and _reads_documents(det)
            if limit <= 0 and sum(b for p, b in part_bytes.items() if p in det_parts) > 0:
                res.not_executed.append(
                    not_executed(slug, did, "payload_too_large", "scan budget", preset=preset)
                )
                continue
            view, scanned, clipped = clipped_view(payload, det_parts, part_bytes, limit)
            budget_left -= sum(scanned.values())  # the documents do not spend this budget
            if reads_docs and DOCUMENT_PART in part_bytes:
                # WP-D1: the documents have their own budget, per detector
                view, doc_scanned, doc_clipped = clipped_view(
                    view,
                    (DOCUMENT_PART,),
                    {DOCUMENT_PART: part_bytes[DOCUMENT_PART]},
                    config.document_max_scan_bytes,
                )
                scanned = {**scanned, **doc_scanned}
                clipped = clipped | doc_clipped
            for p, nb in scanned.items():
                scanned_min[p] = min(scanned_min.get(p, nb), nb)
            cut_applied = sorted(clipped & APPLIED_PARTS)
            if cut_applied and _transforms_here(det, clean, payload.get("meta") or {}):
                # WP41 review: a detector that would transform this call read only part of a
                # part the caller applies (arguments, output). Personal data after the cut would
                # pass unmasked even when the scanned part is clean, so it did not do its job:
                # not executed, and the fail-closed rule applies on a risky tool.
                res.not_executed.append(
                    not_executed(
                        slug, did, "payload_too_large", ",".join(cut_applied), preset=preset
                    )
                )
                continue
            if (
                DOCUMENT_PART in clipped
                and (payload.get("meta") or {}).get("risk_class") == "pii_export"
                and _transforms_here(det, clean, payload.get("meta") or {})
            ):
                # WP-D1: the cut part of a document is not masked, and a pii_export tool must not
                # get it: the failure row is for the cut document; the call is still scored in
                # full (the arguments and the rest are read and transformed as usual)
                res.not_executed.append(
                    not_executed(slug, did, "payload_too_large", "documents", preset=preset)
                )
            t0 = clock_ns()
            # WP-D4: a detector with a `timeout_ms` setting has its own deadline (default: the
            # gate's). A budget-aware detector is told the deadline so it stops asking its model
            # and frees its thread slot before the gate gives up on it.
            own_ms = clean.get("timeout_ms")
            timeout_ms = own_ms if isinstance(own_ms, int) and own_ms > 0 else config.timeout_ms
            run_settings = (
                {**clean, "_budget_ms": timeout_ms}
                if getattr(det, "budget_aware", False)
                else clean
            )
            try:
                found = _call_bounded(
                    lambda det=det, s=run_settings, view=view: det.evaluate(view, s, direction),
                    timeout_ms / 1000,
                )
            except (TimeoutError, _NoSlot) as exc:
                took_us = (clock_ns() - t0) // 1000
                res.per_detector_us[slug] = took_us
                detail = "no free detector slot" if isinstance(exc, _NoSlot) else "deadline"
                res.not_executed.append(not_executed(slug, did, "timed_out", detail, preset=preset))
                continue
            except Exception as exc:  # noqa: BLE001 - a detector must never break the gate
                res.not_executed.append(
                    not_executed(slug, did, "execution_failed", type(exc).__name__, preset=preset)
                )
                res.per_detector_us[slug] = (clock_ns() - t0) // 1000
                continue
            took_us = (clock_ns() - t0) // 1000
            res.per_detector_us[slug] = took_us
            if took_us > timeout_ms * 1000:
                res.not_executed.append(
                    not_executed(slug, did, "timed_out", f"{took_us // 1000} ms", preset=preset)
                )
                continue
            if clipped and any(f.transformed_payload for f in found):
                # A transform of text the detector only saw in part must not go out. If the
                # arguments were cut, the detector did not do its job (fails closed on a risky
                # tool); a cut tool result is not applied by any caller, so that part is dropped.
                if clipped & APPLIED_PARTS:
                    res.not_executed.append(
                        not_executed(slug, did, "payload_too_large", "arguments", preset=preset)
                    )
                    # WP-D2: a block hint (a secret found in the scanned part of the arguments) is
                    # not a transform and survives the cut, without its masked payload. The block
                    # must stand on every tool class, whatever the size of the payload.
                    found = [
                        replace(f, transformed_payload=None)
                        for f in found
                        if f.action_hint == "block" and f.not_executed_reason is None
                    ]
                    if not found:
                        continue
                else:
                    found = [_without_parts(f, clipped) for f in found]
            res.evaluated.append(slug)
            for f in found:
                if f.not_executed_reason is not None:
                    res.not_executed.append(f)
                elif f.code.startswith("coverage_note."):
                    # WP-D2: a detector says it read less than all of a text (a cut). Listed in
                    # coverage.notes; it is not a finding and never fails a call closed.
                    notes.append(
                        {
                            "detector": slug,
                            "reason": f.code.split(".", 1)[1],
                            "detail": f.detail,
                        }
                    )
                elif f.fired:
                    res.findings.append(f)
                    if f.action_hint == "transform" and f.transformed_payload:
                        for part, value in f.transformed_payload.items():
                            merged[part] = value
        if merged:
            res.transformed_payload = merged
        if notes:
            res.coverage.setdefault("notes", []).extend(notes)
        cut = [
            {
                "part": p,
                "reason": "payload_too_large",
                "bytes": part_bytes[p],
                "scanned_bytes": scanned_min[p],
            }
            for p in inspected
            if p in scanned_min and scanned_min[p] < part_bytes[p]
        ]
        if cut:
            res.coverage["inspected"] = [p for p in inspected if p not in {c["part"] for c in cut}]
            res.coverage["not_inspected"] = [*not_inspected, *cut]
            res.coverage["bytes"] = sum(part_bytes.values())
        intake = (payload.get("meta") or {}).get("intake") if has_docs else None
        if isinstance(intake, Mapping) and int(intake.get("unread") or 0) > 0:
            # WP-D1: some documents were not read (image, damaged file, limit, refused URL). The
            # part moves out of ``inspected``: the readable documents were still scanned.
            res.coverage["inspected"] = [p for p in res.coverage["inspected"] if p != DOCUMENT_PART]
            if not any(
                n["part"] == DOCUMENT_PART and n["reason"] == "content_uninspectable"
                for n in res.coverage["not_inspected"]
            ):
                res.coverage["not_inspected"] = [
                    *res.coverage["not_inspected"],
                    {
                        "part": DOCUMENT_PART,
                        "reason": "content_uninspectable",
                        "unread": int(intake["unread"]),
                    },
                ]
        if (
            any(c["part"] == "args" for c in cut)
            and risk_class in config.fail_closed_risk_classes
            and not any(
                n.not_executed_reason == "payload_too_large" and self._closes(n, config)
                for n in res.not_executed
            )
        ):
            # WP41b (D31): the scan budget cut an argument of a money, credit or pii_export call.
            # The rest of it was not looked at, so no detector did the whole job: fail closed,
            # whatever the detector kind (a read_only tool stays coverage-only). A cut row of a
            # detector that is not fail_closed (dlp_vn with fail_closed false) does not stand in
            # for this one (WP41b review).
            res.not_executed.append(
                not_executed("*", "*", "payload_too_large", "arguments cut by scan budget")
            )
        if uninspectable:
            res.not_executed.append(
                Finding(
                    detector_slug="*",
                    detector_id="*",
                    code="not_executed.content_uninspectable",
                    not_executed_reason="content_uninspectable",
                    detail="payload part has content no detector can read",
                )
            )
        # Failures that block on this tool (GATE-DETECTOR-FAILED): a detector that is set to
        # fail closed could not look, and the tool is money, credit or pii_export.
        if risk_class in config.fail_closed_risk_classes:
            for ne in res.not_executed:
                if ne.not_executed_reason not in FAILURE_REASONS:
                    continue
                if self._closes(ne, config):
                    res.failed_closed.append(ne)
        res.latency_us = (clock_ns() - t_start) // 1000
        return res


# ---------------------------------------------------------------------------- status


def derive_status(
    *,
    allow: bool,
    action: str,
    findings: Sequence[Finding],
    has_transform: bool,
    skipped: bool = False,
    matched_actions: Iterable[str] = (),
) -> str:
    """The v2 ``status`` of a verdict. Precedence (highest wins)::

        block > pause > transform > report > allow

    * ``block`` / ``pause``: the deterministic decision (a rule, a built-in block, or
      GATE-DETECTOR-FAILED) denied the call. If any matched rule says ``block`` the status is
      ``block`` even when a ``pause`` rule decided first (the old ``action`` field keeps the
      gate's own order; the agent is still paused). A finding never raises the status to block
      or pause: an ``action_hint`` of pause or block counts as ``report``.
    * ``transform``: the call is allowed and a detector (dlp) produced a transformed payload.
    * ``report``: the call is allowed and something fired: a finding, or a rule whose action is
      ``log`` or ``alert`` (including a rule that failed open).
    * ``skip``: only when a policy rule asked the gate not to run detectors for this call and
      the deterministic decision would not have been a block or a pause. A transform (WP24b
      inline redaction still runs on a skipped call) wins over skip: a changed payload is
      always visible in the status.
    * ``allow``: none of the above.
    """
    if not allow:
        return "block" if action != "pause" or "block" in set(matched_actions) else "pause"
    if has_transform:
        return "transform"
    if skipped:
        return "skip"
    if findings or action in ("log", "alert"):
        return "report"
    return "allow"
