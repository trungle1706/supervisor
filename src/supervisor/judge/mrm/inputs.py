"""Input port for extra validation evidence: ``JudgeValidationInput``.

The validation report (``validation.py``) takes extra check results through this
protocol: any object with ``results() -> list[dict]``, a JSON file of rows
(``--packs FILE``), or - the default when the store has them - the WP17 assurance results
in the ``eval_result`` table (:class:`EvalResultPacks`, judge target of this judge).

Row shape (integers only, basis points 0..10000)::

    {"pack_id": str, "metric": str, "value_bp": int, "threshold_bp": int,
     "passed": bool, "op": ">=" | "<=" (optional, default ">="), "source": str (optional)}

``passed`` must agree with ``value_bp op threshold_bp``: a row that claims a pass its own
numbers do not support is rejected (ValueError). A row with ``passed`` False is a failed
check and forces NO_GO.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

_REQUIRED = ("pack_id", "metric", "value_bp", "threshold_bp", "passed")
_ALLOWED = (*_REQUIRED, "op", "source")
OPS = (">=", "<=")


@runtime_checkable
class JudgeValidationInput(Protocol):
    """A source of extra validation check results."""

    def results(self) -> list[dict[str, Any]]: ...


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_pack_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Strict type check. Return normalised copies, raise ValueError on any bad row."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"pack row {i}: expected an object, got {type(row).__name__}")
        missing = [k for k in _REQUIRED if k not in row]
        if missing:
            raise ValueError(f"pack row {i}: missing {', '.join(missing)}")
        extra = sorted(set(row) - set(_ALLOWED))
        if extra:
            raise ValueError(f"pack row {i}: unknown field(s) {', '.join(extra)}")
        for key in ("pack_id", "metric"):
            if not isinstance(row[key], str) or not row[key]:
                raise ValueError(f"pack row {i}: {key} must be a non-empty string")
        for key in ("value_bp", "threshold_bp"):
            v = row[key]
            if isinstance(v, float):
                raise ValueError(f"pack row {i}: {key} is a float; use integer basis points")
            if not _is_int(v) or not 0 <= v <= 10000:
                raise ValueError(f"pack row {i}: {key} must be an int in 0..10000, got {v!r}")
        if not isinstance(row["passed"], bool):
            raise ValueError(f"pack row {i}: passed must be a bool, got {row['passed']!r}")
        if "source" in row and not isinstance(row["source"], str):
            raise ValueError(f"pack row {i}: source must be a string")
        op = row.get("op", ">=")
        if op not in OPS:
            raise ValueError(f"pack row {i}: op must be one of {', '.join(OPS)}, got {op!r}")
        v, t = row["value_bp"], row["threshold_bp"]
        holds = v >= t if op == ">=" else v <= t
        if holds != row["passed"]:
            raise ValueError(
                f"pack row {i}: passed={row['passed']} disagrees with {v} {op} {t} "
                f"({row['pack_id']}:{row['metric']})"
            )
        norm = {k: row[k] for k in _ALLOWED if k in row}
        norm["op"] = op
        out.append(norm)
    return out


class StaticPackResults:
    """List-backed ``JudgeValidationInput``. Rows are validated on creation."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._rows = validate_pack_rows(rows)

    def results(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows]


def load_pack_results(path: Path | str) -> StaticPackResults:
    """Read a JSON file (a list of rows, or ``{"results": [...]}``). Raise ValueError."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot read packs file {p}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"packs file {p} is not valid JSON: {exc}") from exc
    if isinstance(data, dict) and "results" in data:
        data = data["results"]
    if not isinstance(data, list):
        raise ValueError(f"packs file {p}: expected a list of rows")
    return StaticPackResults(data)


def eval_result_pack_rows(tables: Any, router: Any) -> list[dict[str, Any]]:
    """Rows from the newest WP17 ``eval_result`` per pack for this judge's target.

    Pass/fail is the stored per-metric status (``fail`` = failed; ``ok``/``warn`` = pass, as
    in the WP17 judge gate); the threshold is the pack's ``no_go`` and the operator follows
    the metric direction in the manifest. Metrics with no value, or values outside
    0..10000 (counts, ms), are left out. Deterministic order (pack id, metric)."""
    from supervisor.assurance.gates import judge_target_id
    from supervisor.assurance.loader import PACKS_DIR, load_packs
    from supervisor.assurance.results import latest_results

    directions: dict[tuple[str, str], str] = {}
    for pack in load_packs(PACKS_DIR):
        for m in pack.metrics:
            directions[(pack.id, m.name)] = m.direction
    out: list[dict[str, Any]] = []
    for row in latest_results(tables, "judge", judge_target_id(router)):
        pid = str(row["pack_id"])
        metrics = _json(row.get("metrics"))
        status = _json(row.get("metric_status"))
        thresholds = _json(row.get("thresholds"))
        for name in sorted(thresholds):
            value, thr = metrics.get(name), thresholds[name]
            no_go = thr.get("no_go") if isinstance(thr, Mapping) else None
            if not (_is_int(value) and _is_int(no_go) and 0 <= value <= 10000):
                continue
            if not 0 <= no_go <= 10000:
                continue
            higher = directions.get((pid, name), "higher_better") == "higher_better"
            op = ">=" if higher else "<="
            passed = status.get(name) != "fail"
            if passed != (value >= no_go if higher else value <= no_go):
                passed = False  # inconsistent stored status: never a silent pass
            mock = " (mock run)" if _truthy(row.get("is_mock")) else ""
            out.append(
                {
                    "pack_id": pid,
                    "metric": name,
                    "value_bp": value,
                    "threshold_bp": no_go,
                    "op": op,
                    "passed": passed,
                    "source": f"eval_result:{row.get('run_id')}{mock}",
                }
            )
    return out


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    return bool(value)


class EvalResultPacks:
    """``JudgeValidationInput`` over the WP17 ``eval_result`` table (see above)."""

    def __init__(self, tables: Any, router: Any) -> None:
        self._rows = validate_pack_rows(eval_result_pack_rows(tables, router))

    def results(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows]


__all__ = [
    "EvalResultPacks",
    "JudgeValidationInput",
    "StaticPackResults",
    "eval_result_pack_rows",
    "load_pack_results",
    "validate_pack_rows",
]
