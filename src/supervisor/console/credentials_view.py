"""Credentials page (WP-UX3, read-only): WP20 agent ingress key metadata and identity map.

Shows, per agent, which keys exist (key id, state, issued, expiry, active or not) and which
Databricks principals may speak for which agents. It NEVER reads or returns a secret value: the
code touches ``AgentKey.key_id``, ``state`` and ``expires_at`` only, and asks ``valid_at()`` for a
yes or no. Principals are shortened (first and last four characters). Issuing and rotating keys
stay on the command line, because the new secret would pass through the browser otherwise.
Last use is not tracked by WP20, so the column shows ``-``."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from supervisor.adapters.auth.agent_creds import AgentKey
from supervisor.adapters.auth.agent_creds_identity import AgentIdentityMap
from supervisor.core.errors import SupervisorError

MAX_AGENTS = 200
_KEY_TS = re.compile(r"^k-(\d{14})$")
ROTATE_CLI = "python -m supervisor.gateway.ingress_auth rotate {agent_id}"


def issued_from_key_id(key_id: str) -> dt.datetime | None:
    """``k-YYYYmmddHHMMSS`` (WP20 key ids) carries the issue time; other ids do not."""
    m = _KEY_TS.match(key_id or "")
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def short_principal(value: str) -> str:
    """Enough to recognise a principal, not enough to reuse it."""
    if len(value) <= 12:
        return value[:2] + "..." if len(value) > 4 else "..."
    return f"{value[:4]}...{value[-4:]}"


def _store(settings: Any) -> Any:
    from supervisor.gateway.ingress_auth import build_key_store

    return build_key_store(settings)


def _keys(store: Any, agent_id: str, now: dt.datetime, all_keys: dict[str, list[AgentKey]] | None):
    if all_keys is not None:
        return all_keys.get(agent_id, [])
    return store.keys_for(agent_id, now)


def page(ctx: Any) -> dict[str, Any]:
    s = ctx.settings
    now = ctx.clock.now()
    agents = sorted(a["agent_id"] for a in ctx.state.query("agent"))[:MAX_AGENTS]
    store_error: str | None = None
    rows: list[dict[str, Any]] = []
    store_name = s.effective_ingress_key_store
    try:
        store = _store(s)
        all_keys = store.read_all() if hasattr(store, "read_all") else None
        names = sorted(set(agents) | set(all_keys or {}))[:MAX_AGENTS]
        for agent_id in names:
            for k in _keys(store, agent_id, now, all_keys):
                active = k.valid_at(now)
                rows.append(
                    {
                        "agent_id": agent_id,
                        "key_id": k.key_id,
                        "state": k.state,
                        "active": active,
                        "issued": issued_from_key_id(k.key_id),
                        "expires_at": k.expires_at,
                        "last_used": None,
                        "registered": agent_id in agents,
                    }
                )
    except SupervisorError as exc:
        store_error = type(exc).__name__  # the class only: the message could name a path
    except Exception as exc:  # noqa: BLE001 - a store outage must not take the page down
        store_error = type(exc).__name__
    ids: list[dict[str, Any]] = []
    id_error: str | None = None
    try:
        amap = AgentIdentityMap.from_file(s.ingress_identities_file)
        for principal, ags in sorted(amap.entries().items()):
            ids.append({"principal": short_principal(principal), "agents": sorted(ags)})
    except Exception as exc:  # noqa: BLE001 - show the class only
        id_error = type(exc).__name__
    with_key = {r["agent_id"] for r in rows if r["active"]}
    return {
        "ingress_on": bool(s.ingress_auth_enabled),
        "kind": s.effective_ingress_kind,
        "store": store_name,
        "store_error": store_error,
        "id_error": id_error,
        "keys": rows,
        "identities": ids,
        "no_key_agents": [a for a in agents if a not in with_key],
        "rotate_cli": ROTATE_CLI.format(agent_id="<agent_id>"),
    }
