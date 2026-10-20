"""What the classifier scores: the text units of one gate call (WP25).

A *unit* is the text of one payload part on one *surface*. The surface sets the code of a finding
and the bias of the model:

| surface            | where the text comes from                          | code              |
|--------------------|----------------------------------------------------|-------------------|
| ``args``           | string leaves of the tool arguments                | direct_injection  |
| ``tool_results``   | each tool result (input side), or the output       | indirect_injection|
| ``tool_description`` | ``meta.tool_description`` (set by the caller)    | tool_poisoning    |

Split-field reassembly: the leaves of one part are joined in order, so an instruction cut across
two argument fields is scored as one text. Prior-call context: ``meta.prior_calls`` (a list of
strings or JSON-like values the integrator collected from earlier calls of the same trace) is
placed in front of the ``args`` text, so an instruction cut across two calls is scored as one
text. The detector keeps no state itself (the contract says a detector is pure); a per-trace buffer
is WP27's job (BACKLOG).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from supervisor.core.detectors import Leaf, walk_leaves

SURFACES = ("args", "tool_results", "tool_description")
CODE_BY_SURFACE = {
    "args": "injection.direct_injection",
    "tool_results": "injection.indirect_injection",
    "tool_description": "injection.tool_poisoning",
}
MAX_PRIOR_CALLS = 8


@dataclass(frozen=True)
class Unit:
    surface: str
    part: str  # payload part name for fragments: args | tool_results | tool_description
    text: str  # what is scored (leaves joined)
    leaves: tuple[Leaf, ...]  # the leaves of this unit in the payload part (for fragments)
    prior: str = ""  # prior-call text that was put in front (never shown)


def _leaf_text(leaves: list[Leaf]) -> str:
    return "\n".join(x.text for x in leaves if x.text)


def _prior_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    leaves = list(walk_leaves("prior", value))
    return _leaf_text(leaves)


def collect(payload: Mapping[str, Any], direction: str) -> list[Unit]:
    """Units of one payload. ``payload["meta"]`` may carry ``tool_description`` and ``prior_calls``."""
    meta = payload.get("meta") or {}
    units: list[Unit] = []
    if direction == "input":
        if payload.get("args") is not None:
            leaves = list(walk_leaves("args", payload["args"]))
            prior_calls = meta.get("prior_calls")
            prior = ""
            if isinstance(prior_calls, list | tuple):
                prior = "\n".join(_prior_text(p) for p in prior_calls[-MAX_PRIOR_CALLS:])
            elif prior_calls is not None:
                prior = _prior_text(prior_calls)
            text = _leaf_text(leaves)
            if prior:
                text = prior + "\n" + text
            if text.strip():
                units.append(Unit("args", "args", text, tuple(leaves), prior))
        results = payload.get("tool_results")
        if results is not None:
            items = results if isinstance(results, list | tuple) else [results]
            for k, res in enumerate(items):
                leaves = [
                    Leaf("tool_results", f"$[{k}]{x.path[1:]}", x.text)
                    for x in walk_leaves("tool_results", res)
                ]
                if leaves:
                    units.append(Unit("tool_results", "tool_results", _leaf_text(leaves), tuple(leaves)))
        desc = meta.get("tool_description")
        if isinstance(desc, str) and desc.strip():
            units.append(
                Unit("tool_description", "tool_description", desc, (Leaf("tool_description", "$", desc),))
            )
    elif payload.get("output") is not None:
        leaves = list(walk_leaves("output", payload["output"]))
        if leaves:
            units.append(Unit("tool_results", "output", _leaf_text(leaves), tuple(leaves)))
    return units
