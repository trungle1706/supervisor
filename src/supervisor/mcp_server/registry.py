"""Tool registry of the MCP server (WP-G6): definitions, argument checks and the refusal list.

A tool is a name, a scope, an input schema and a handler. The registry refuses, at registration,
every tool whose name says it would take a decision that belongs to a person: classify, approve,
accept a risk, change a risk level, close an incident, turn a guardian off. The refusal message
points at the console. A test enumerates the registered tools and checks that none of them is in
the refused set (``tests/mcp_server``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from supervisor.mcp_server import SCOPES

# JSON-RPC codes (-32700 .. -32600 are the standard ones; -320xx are ours, server errors).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APP_NOT_APPROVED = -32001
SCOPE_DENIED = -32002
PERMISSION_DENIED = -32003
NOT_FOUND = -32004
AUDIT_UNAVAILABLE = -32010
RESULT_TOO_LARGE = -32011

# Decisions that stay with people (CLAUDE.md product rules). A tool name is refused when it
# equals one of these or contains one of the parts, after lower-casing and turning - into _.
REFUSED_NAMES: frozenset[str] = frozenset(
    {
        "classify",
        "classify_system",
        "apply_classification",
        "approve",
        "approve_stage",
        "decide_approval",
        "sign_off",
        "signoff",
        "accept_risk",
        "set_risk_level",
        "change_risk_level",
        "lower_risk_level",
        "raise_risk_level",
        "close_incident",
        "resolve_incident",
        "transition_incident",
        "disable_guardian",
        "turn_off_guardian",
        "guardian_off",
        "remove_guardian",
        "pause_agent",
        "resume_agent",
        "quarantine_agent",
    }
)
REFUSED_PARTS: tuple[str, ...] = (
    "classify",
    "apply_classif",
    "approve",
    "accept_risk",
    "risk_level",
    "close_incident",
    "resolve_incident",
    "guardian_off",
    "disable_guardian",
    "turn_off",
    "sign_off",
    "waive",
)
REFUSAL_TEXT = (
    "refused: {name} would classify, approve, accept a risk, change a risk level, close an "
    "incident or turn a guardian off. A person does that in the console (/console/systems)."
)
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}\Z")


class RpcError(Exception):
    """A JSON-RPC error answer (HTTP 200 with an ``error`` object, never a 500)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RefusedTool(ValueError):
    """The name of a tool is on the refusal list."""


def _refused_words(w: set[str]) -> bool:
    """The same rule read word by word, so that "risk_accept" and "classification_apply" are caught
    as well as "accept_risk"."""
    return bool(
        w & {"classify", "approve", "approver", "waive", "signoff"}
        or {"sign", "off"} <= w
        or {"turn", "off"} <= w
        or (w & {"apply", "accept"} and w & {"classification", "classify", "risk"})
        or ("level" in w and "risk" in w)
        or (w & {"close", "closure", "resolve", "transition"} and "incident" in w)
        or ("guardian" in w and w & {"off", "disable", "remove", "stop", "bypass"})
        or (w & {"pause", "resume", "quarantine", "release"} and "agent" in w)
    )


def refusal_for(name: str) -> str | None:
    key = name.lower().replace("-", "_")
    if (
        key in REFUSED_NAMES
        or any(part in key for part in REFUSED_PARTS)
        or _refused_words(set(key.split("_")))
    ):
        return REFUSAL_TEXT.format(name=name)
    return None


@dataclass(frozen=True)
class Tool:
    """One tool. ``handler(call, args, apply)``: for a write tool ``apply`` is False until the
    caller sent ``confirm: true``; the handler then validates and returns the planned change and
    writes nothing. ``target(args)`` names the audited row as (kind, id)."""

    name: str
    description: str
    scope: str
    schema: dict[str, Any]
    handler: Callable[[Any, dict[str, Any], bool], dict[str, Any]]
    write: bool = False
    permission: str | None = None  # the console permission a person needs for the same action
    target: Callable[[dict[str, Any]], tuple[str | None, str | None]] | None = None

    def listing(self) -> dict[str, Any]:
        props = dict(self.schema.get("properties", {}))
        required = list(self.schema.get("required", []))
        if self.write:
            props["confirm"] = {
                "type": "boolean",
                "description": "true to write. Without it nothing is written and the "
                "planned change is returned.",
            }
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": not self.write, "destructiveHint": False},
        }


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        refused = refusal_for(tool.name)
        if refused:
            raise RefusedTool(refused)
        if not NAME_RE.match(tool.name):
            raise ValueError(f"bad tool name {tool.name!r}")
        if tool.scope not in SCOPES:
            raise ValueError(f"tool {tool.name}: unknown scope {tool.scope!r}")
        if tool.write and tool.scope != "governance.write":
            raise ValueError(f"tool {tool.name}: a write tool has the scope governance.write")
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} is registered twice")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __iter__(self) -> Iterator[Tool]:
        return iter([self._tools[n] for n in self.names()])

    def __len__(self) -> int:
        return len(self._tools)


# ---------------------------------------------------------------------------- argument checks

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "boolean": (bool,),
    "integer": (int,),
    "object": (dict,),
}
MAX_STRING = 4000


def validate_args(schema: dict[str, Any], args: Any, *, write: bool = False) -> dict[str, Any]:
    """Check ``args`` against the small schema subset the tools use (type, enum, maxLength,
    minimum, maximum, required, no unknown key). Raises ``RpcError(INVALID_PARAMS)``."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "arguments must be a JSON object")
    props: dict[str, Any] = schema.get("properties", {})
    allowed = set(props) | ({"confirm"} if write else set())
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise RpcError(INVALID_PARAMS, f"unknown argument: {', '.join(unknown)}")
    missing = [k for k in schema.get("required", []) if args.get(k) in (None, "")]
    if missing:
        raise RpcError(INVALID_PARAMS, f"required: {', '.join(missing)}")
    if "confirm" in args and not isinstance(args["confirm"], bool):
        raise RpcError(INVALID_PARAMS, "confirm must be true or false")
    for key, spec in props.items():
        if key not in args or args[key] is None:
            continue
        value = args[key]
        kind = spec.get("type", "")
        want = _TYPES.get(kind, ())
        if want and (
            not isinstance(value, want) or (kind == "integer" and isinstance(value, bool))
        ):
            raise RpcError(INVALID_PARAMS, f"{key} must be of type {kind}")
        if isinstance(value, str) and len(value) > spec.get("maxLength", MAX_STRING):
            raise RpcError(INVALID_PARAMS, f"{key} is too long")
        if "enum" in spec and value not in spec["enum"]:
            raise RpcError(INVALID_PARAMS, f"{key} must be one of {', '.join(spec['enum'])}")
        if isinstance(value, int) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                raise RpcError(INVALID_PARAMS, f"{key} must be at least {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                raise RpcError(INVALID_PARAMS, f"{key} must be at most {spec['maximum']}")
    return dict(args)
