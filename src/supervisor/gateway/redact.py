"""Inline redaction of tool arguments at the gate (WP24b).

``redact_args`` walks dicts, lists and strings and runs the masker over every string leaf.
Numbers, booleans and null keep their value and type (a PII value sent as a bare JSON number is
a known gap, see BACKLOG). Keys are never changed.
The result has the same shape as the input, so the SDK can swap it in before the tool runs.

Nothing here logs or returns the original values; the gate records only keyed hashes of the
original and the transformed arguments (see ``Gateway._payload``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.core.ports import Masker

__all__ = ["redact_args"]

MAX_DEPTH = 12


def _walk(value: Any, masker: Masker, depth: int, count: list[int]) -> Any:
    if depth > MAX_DEPTH:
        return value
    if isinstance(value, str):
        out = masker.mask(value)
        if out != value:
            count[0] += 1
        return out
    if isinstance(value, (bool, int, float)) or value is None:
        return value  # numbers keep their type: a money tool must still get an int
    if isinstance(value, Mapping):
        return {k: _walk(v, masker, depth + 1, count) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_walk(v, masker, depth + 1, count) for v in value]
    return value


def redact_args(masker: Masker, args: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """Masked copy of ``args`` and the number of leaves that changed."""
    count = [0]
    out = _walk(dict(args), masker, 0, count)
    return out, count[0]
