"""Integrations page as a collector catalogue (WP38, flag COLLECTORS_ENABLED).

Three parts, all read-only except ``connect``:

* ``page``      template cards by category, agents with their key state and policy mode, and the
                delivery status table of the old page (SIEM, webhook, pager, ITSM, SCIM);
* ``connect``   Add: issue the first key of one agent (WP20 flow, ``collectors/credentials.py``)
                and return the setup text with the real URL and agent id. The secret is in the
                result once and nowhere else;
* ``drawer``    one agent: tabs Connection, Credential (metadata only), Policy binding.

The secret is never read back from the key store here (``AgentKey.secret`` is not touched; the
code asks ``valid_at()`` only), and the audit row carries the agent id and the template id.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from supervisor.collectors import catalog
from supervisor.collectors.credentials import ROTATE_CLI, issue_first_key
from supervisor.console import integrations_view
from supervisor.console.credentials_view import issued_from_key_id
from supervisor.console.listing import ListingError

DRAWER_TABS = ("connection", "credential", "policy")
MAX_AGENTS = 200


def base_url(ctx: Any, request_base: str) -> str:
    """The URL for the setup text: COLLECTORS_PUBLIC_URL, else the address the console was
    opened with. It is checked again by ``catalog.fill`` before use."""
    configured = (ctx.settings.collectors_public_url or "").strip()
    return (configured or request_base).rstrip("/")


def _meta(keys: Any, now: dt.datetime) -> list[dict[str, Any]]:
    """Key metadata only: ``AgentKey.secret`` is never read here."""
    return [
        {
            "key_id": k.key_id,
            "state": k.state,
            "active": k.valid_at(now),
            "issued": issued_from_key_id(k.key_id),
            "expires_at": k.expires_at,
        }
        for k in keys
    ]


def _store(ctx: Any) -> Any:
    from supervisor.gateway.ingress_auth import build_key_store

    return build_key_store(ctx.settings)


def _keys_of(ctx: Any, agent_id: str) -> list[dict[str, Any]]:
    try:
        return _meta(_store(ctx).keys_for(agent_id, ctx.clock.now()), ctx.clock.now())
    except Exception:  # noqa: BLE001 - a store outage shows as "no key", the page stays up
        return []


def _policy(ctx: Any) -> Any:
    try:
        return ctx.gateway.policy.current()
    except Exception:  # noqa: BLE001 - the page still works without the policy
        return None


def _agent_rows(ctx: Any) -> tuple[list[dict[str, Any]], str | None]:
    store_error: str | None = None
    all_keys: dict[str, list[Any]] | None = None
    now = ctx.clock.now()
    try:
        store = _store(ctx)
        all_keys = store.read_all() if hasattr(store, "read_all") else None
    except Exception as exc:  # noqa: BLE001 - the class only: the message could name a path
        store_error = type(exc).__name__
    policy = _policy(ctx)
    rows = []
    for a in sorted(ctx.state.query("agent"), key=lambda r: r["agent_id"])[:MAX_AGENTS]:
        aid = a["agent_id"]
        eff = policy.effective(aid) if policy is not None else None
        manifest = policy.doc.agents.get(aid) if policy is not None else None
        ks = _meta(all_keys.get(aid, []), now) if all_keys is not None else _keys_of(ctx, aid)
        rows.append(
            {
                "agent_id": aid,
                "name": a.get("name") or aid,
                "gate_state": a.get("gate_state"),
                "plug_point": a.get("plug_point"),
                "has_key": any(k["active"] for k in ks),
                "mode": eff.mode if eff is not None else "-",
                "consumers": len(manifest.consumers) if manifest is not None else 0,
            }
        )
    return rows, store_error


def page(ctx: Any, selected: str | None = None) -> dict[str, Any]:
    agents, store_error = _agent_rows(ctx)
    status = integrations_view.page(ctx)
    free = [a["agent_id"] for a in agents if not a["has_key"]]
    return {
        "groups": catalog.by_category(),
        "agents": agents,
        "agent_opts": free,
        "sel_agent": selected if selected in free else None,
        "store_error": store_error,
        "ingress_on": bool(ctx.settings.ingress_auth_enabled),
        "rows": status["rows"],
        "dead_total": status["dead_total"],
    }


def connect(ctx: Any, agent_id: str, template_id: str, request_base: str) -> dict[str, Any]:
    """Add: validate, issue the key, return the setup text. Raises SupervisorError (HTTP 400)."""
    tpl = catalog.get(template_id)
    if tpl is None:
        raise ListingError("unknown template")
    if not tpl.available:
        raise ListingError(f"{tpl.name} is {tpl.availability_note}")
    if ctx.state.get("agent", {"agent_id": agent_id}) is None:
        raise ListingError(f"agent {agent_id} is not registered")
    url = base_url(ctx, request_base)
    try:
        catalog.fill("x", url, agent_id)  # check the values BEFORE a key is issued
    except catalog.PlaceholderError as exc:
        raise ListingError(str(exc)) from exc
    issued = issue_first_key(ctx.settings, agent_id, ctx.clock.now())
    return {
        "tpl": catalog.filled(tpl, url, agent_id),
        "issued": issued,
        "agent_id": agent_id,
        "ingress_on": bool(ctx.settings.ingress_auth_enabled),
    }


def drawer(
    ctx: Any, agent_id: str, tab: str, template_id: str, request_base: str
) -> dict[str, Any]:
    if tab not in DRAWER_TABS:
        raise ListingError("unknown drawer tab")
    agent = ctx.state.get("agent", {"agent_id": agent_id})
    if agent is None:
        raise ListingError(f"agent {agent_id} is not registered")
    tpl = catalog.get(template_id) or catalog.get("python_sdk")
    assert tpl is not None
    url = base_url(ctx, request_base)
    out: dict[str, Any] = {
        "agent": agent,
        "agent_id": agent_id,
        "tab": tab,
        "tabs": DRAWER_TABS,
        "template_id": tpl.id,
        "templates": [(t.id, t.name, t.available) for t in catalog.TEMPLATES],
        "json_text": json.dumps(
            {
                "agent_id": agent_id,
                "name": agent.get("name"),
                "gate_state": agent.get("gate_state"),
            },
            sort_keys=True,
            indent=2,
            default=str,
        ),
    }
    if tab == "connection":
        try:
            out["tpl"] = catalog.filled(tpl, url, agent_id)
        except catalog.PlaceholderError as exc:
            raise ListingError(str(exc)) from exc
    elif tab == "credential":
        out["key_rows"] = _keys_of(ctx, agent_id)
        out["rotate_cli"] = ROTATE_CLI.format(agent_id=agent_id)
        out["ingress_on"] = bool(ctx.settings.ingress_auth_enabled)
        out["store"] = ctx.settings.effective_ingress_key_store
    else:
        out["binding"] = binding(ctx, agent_id)
        out["policies_on"] = bool(ctx.settings.console_policies_enabled)
    return out


def binding(ctx: Any, agent_id: str) -> dict[str, Any]:
    """Which policy settings apply to the agent: mode, detector override, rule switches and
    consumer overrides, as written in the policy file."""
    policy = _policy(ctx)
    if policy is None:
        return {"available": False}
    manifest = policy.doc.agents.get(agent_id)
    eff = policy.effective(agent_id)
    consumers = []
    if manifest is not None:
        for cid, over in sorted(manifest.consumers.items()):
            consumers.append(
                {
                    "consumer_id": cid,
                    "mode": over.mode or "-",
                    "preset": (over.detectors.preset if over.detectors else None) or "-",
                    "disable": list(over.rules.disable) if over.rules else [],
                    "enable": list(over.rules.enable) if over.rules else [],
                }
            )
    return {
        "available": True,
        "mode": eff.mode,
        "state": manifest.initial_state if manifest is not None else "-",
        "detector_preset": (manifest.detectors.preset if manifest and manifest.detectors else None)
        or "-",
        "disabled_rules": sorted(eff.disabled),
        "rules_in_scope": len(policy.rules_for(agent_id)),
        "consumers": consumers,
        "policy_hash": policy.policy_hash,
    }


__all__ = ["DRAWER_TABS", "binding", "connect", "drawer", "page"]
