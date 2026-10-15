"""Input port for extra validation evidence: ``JudgeValidationInput``.

The validation report (``validation.py``) can take extra check results, for example the
WP17 assurance eval packs (``supervisor.assurance``). WP17 is built in parallel and this
package does NOT import it. Its results plug in later through this protocol: any object
with ``results() -> list[dict]`` works, or a JSON file of rows (``--packs FILE``).

Row shape (integers only, basis points 0..10000)::

    {"pack_id": str, "metric": str, "value_bp": int, "threshold_bp": int,
     "passed": bool, "source": str (optional)}

A row with ``passed`` False is a failed check and forces NO_GO.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

_REQUIRED = ("pack_id", "metric", "value_bp", "threshold_bp", "passed")
_ALLOWED = (*_REQUIRED, "source")


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
        out.append({k: row[k] for k in _ALLOWED if k in row})
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


__all__ = ["JudgeValidationInput", "StaticPackResults", "load_pack_results", "validate_pack_rows"]
