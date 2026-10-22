"""Helpers shared by the tool groups (WP-G6): scope checks and plain JSON."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Mapping
from typing import Any

from supervisor.core.errors import NotFoundError
from supervisor.governance.model import check_system_id, ensure_on
from supervisor.governance.systems import ALL

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
LIMIT_SPEC = {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT}


def plain(value: Any) -> Any:
    """JSON-safe copy: timestamps as RFC 3339, sets and tuples as lists."""
    if isinstance(value, dt.datetime):
        return (value if value.tzinfo else value.replace(tzinfo=dt.UTC)).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, set | frozenset):
        return sorted(plain(v) for v in value)
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    return value


def pick(row: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {k: plain(row[k]) for k in keys if k in row}


def limit_of(args: Mapping[str, Any]) -> int:
    return int(args.get("limit") or DEFAULT_LIMIT)


def systems_on(call: Any) -> Any:
    """The system service, after checking that governance is on."""
    ensure_on(call.ctx.settings)
    return call.ctx.systems


def visible_system(call: Any, system_id: str) -> str:
    """The id when the system exists and is in the app's scope; else NotFoundError (the same
    answer for both, so a scoped app cannot probe for names)."""
    svc = systems_on(call)
    check_system_id(system_id)
    if system_id not in svc.scope_for(call.principal):
        raise NotFoundError(f"AI system {system_id} does not exist")
    return system_id


def visible_agent_ids(call: Any) -> set[str]:
    """Lower-case ids of the agents the app may see (linked to a system in scope, or the
    unlinked ones of its team); the same rule as the console."""
    return {str(a["agent_id"]).lower() for a in call.ctx.systems.agents_in_scope(call.principal)}


def visible_agent(call: Any, agent_id: str) -> str:
    """The agent id as the registry spells it, if the app may see it; else NotFoundError."""
    for a in call.ctx.systems.agents_in_scope(call.principal):
        if str(a["agent_id"]).lower() == str(agent_id).lower():
            return str(a["agent_id"])
    raise NotFoundError(f"agent {agent_id} does not exist")


def sees_everything(call: Any) -> bool:
    return call.ctx.systems.scope_for(call.principal) is ALL


def agents_of_system(call: Any, system_id: str) -> list[str]:
    return sorted(
        {
            str(c["ref_id"])
            for c in call.ctx.state.query("system_component", {"system_id": system_id})
            if str(c["active"]).lower() in ("1", "true") and c["ref_kind"] == "agent"
        }
    )


def actor_of(call: Any) -> str:
    """The id written as the author of a change: ``mcp:<app id>``."""
    return str(call.principal.user_id)


# ---------------------------------------------------------------------------- masking (review H1)

_HEX_DIGEST = re.compile(r"^[0-9a-f]{32,}$")


def masker_of(call: Any) -> Any:
    """The repo masker of the process (``MASKER_KIND``); None when it is ``none``. Kept on the
    context so it is built once."""
    ctx = call.ctx
    if not hasattr(ctx, "_mcp_masker"):
        from supervisor.adapters.factory import make_masker

        ctx._mcp_masker = make_masker(ctx.settings)  # noqa: SLF001
    return ctx._mcp_masker  # noqa: SLF001


def mask_text(call: Any, value: Any) -> Any:
    """Free text through the masker, as the classification prefill does. With no masker the
    text is not sent at all: the field comes back empty. A non-text value is left as it is."""
    if not isinstance(value, str) or not value:
        return value
    masker = masker_of(call)
    return "" if masker is None else str(masker.mask(value))


def mask_deep(call: Any, value: Any) -> Any:
    """Every string inside a nested value, except a hex digest (a hash is not text)."""
    if isinstance(value, str):
        return value if _HEX_DIGEST.match(value) else mask_text(call, value)
    if isinstance(value, Mapping):
        return {k: mask_deep(call, v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [mask_deep(call, v) for v in value]
    return value


def mask_row(
    call: Any, row: Mapping[str, Any], text_keys: Iterable[str], deep_keys: Iterable[str] = ()
) -> dict[str, Any]:
    """A copy of ``row`` with the free-text fields masked. ``text_keys`` hold text;
    ``deep_keys`` hold a structure (tags, reports) whose strings are all text."""
    out = dict(row)
    for k in text_keys:
        if k in out:
            out[k] = mask_text(call, out[k])
    for k in deep_keys:
        if k in out:
            out[k] = mask_deep(call, out[k])
    return out
