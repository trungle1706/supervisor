"""Guardian attachment view (WP-O4, ``ONBOARD_ATTACH_VIEW``): where an agent plugs into the
Supervisor, which guardians sit on that plug point, and which of them have shown evidence lately.

Read only. The model is built from rows the Supervisor already holds; nothing here calls the
candidate or the gate. Two public functions:

* :func:`attach_model` - plug point, gate state, and the guardians in four groups
  (``gate``, ``detectors``, ``judges``, ``monitors``; the last one also holds the assurance packs).
  Every item has ``slug``, ``label``, ``floor``, ``enabled``, ``last_evidence_at`` (RFC 3339 text or
  ``None``), ``count_7d`` (int) and ``lit`` (evidence within 7 days). No floats anywhere.
* :func:`how_to_attach` - the exact environment lines for the plug point in use, copied from the
  settings and ``config/agent_identities.yaml``. Only the ``principal`` and ``agents`` keys of that
  file are read, and no secret or token is ever put in the text.

Enabled follows the engines (``agent_guardians.feature_rows``: instance flags, detector file, the
agent's policy override, and the guardian bindings). Floor comes from the assignment rules
(``RulesService.guardian_floor`` of every AI system the agent is linked to) and always includes the
gate rules. Docs: ``docs/guardian-bindings.md`` "Attach view (WP-O4)".
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from supervisor.console import agent_guardians, readmodels
from supervisor.core.canonical import format_ts
from supervisor.governance import guardians as gd

LIT_WINDOW = dt.timedelta(days=7)
SCAN = 5000
POLICY_RULES = agent_guardians.POLICY_RULES
SDK, HTTP_PROXY, MCP_GATEWAY, DATABRICKS_APP, UNKNOWN = (
    "sdk",
    "http_proxy",
    "mcp_gateway",
    "databricks_app",
    "unknown",
)
PLUG_KINDS = (SDK, HTTP_PROXY, MCP_GATEWAY, DATABRICKS_APP, UNKNOWN)
GROUPS = ("gate", "detectors", "judges", "monitors")
# value of agent.plug_point (or the policy manifest) -> plug kind
_PLUG_WORDS: dict[str, str] = {
    "gate_hook": SDK,
    "sdk": SDK,
    "http_gate": SDK,
    "mcp_proxy": MCP_GATEWAY,
    "mcp": MCP_GATEWAY,
    "mcp_gateway": MCP_GATEWAY,
    "mcp_http": MCP_GATEWAY,
    "proxy_log": HTTP_PROXY,
    "http_proxy": HTTP_PROXY,
    "proxy": HTTP_PROXY,
    "llm_proxy": HTTP_PROXY,
    "databricks_app": DATABRICKS_APP,
}
_APP_HOSTS = ("databricks_app", "databricks_apps", "databricks-app", "databricks app")
# short English names for the slugs a person meets most; the rest show the slug
LABELS: dict[str, str] = {
    "policy_rules": "Gate rules",
    "session_monitor": "Session monitor",
    "judge_t1": "Judge tier 1",
    "judge_t2": "Judge tier 2",
    "judge_challenger": "Judge challenger",
    "monitor_quality": "Quality",
    "monitor_fairness": "Fairness",
    "monitor_drift": "Drift",
    "monitor_split_payment": "Split payment",
}
# monitor slug -> key of oversight_metric.monitor_status
MONITOR_KEY = agent_guardians.MONITOR_KEY


# ------------------------------------------------------------------------------------ helpers


def _dt(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    return None


def _text(value: dt.datetime | None) -> str | None:
    return format_ts(value) if value is not None else None


def _evidence(stamps: Iterable[dt.datetime | None], now: dt.datetime) -> tuple[str | None, int]:
    """(newest timestamp as text or None, number of stamps inside the last 7 days)."""
    live = [s for s in stamps if s is not None]
    since = now - LIT_WINDOW
    return _text(max(live)) if live else None, sum(1 for s in live if since <= s <= now)


def _lit(last: str | None, now: dt.datetime) -> bool:
    if last is None:
        return False
    from supervisor.core.canonical import parse_ts

    return now - parse_ts(last) <= LIT_WINDOW


def _item(
    slug: str,
    group: str,
    *,
    floor: bool,
    enabled: bool,
    stamps: Iterable[dt.datetime | None],
    now: dt.datetime,
    label: str | None = None,
    mock: bool = False,
    detail: str = "",
    status: str = "",
) -> dict[str, Any]:
    last, n = _evidence(stamps, now)
    return {
        "slug": slug,
        "label": label or LABELS.get(slug) or slug,
        "group": group,
        "floor": bool(floor),
        "enabled": bool(enabled),
        "last_evidence_at": last,
        "count_7d": int(n),
        "lit": _lit(last, now),
        "mock": bool(mock),
        "detail": detail,
        "status": status,
    }


# ------------------------------------------------------------------------------- plug point


def _recognise(plug: Any, host: Any) -> str:
    word = str(plug or "").strip().lower()
    kind = _PLUG_WORDS.get(word, UNKNOWN)
    host_s = str(host or "").strip().lower()
    if kind in (SDK, UNKNOWN) and host_s in _APP_HOSTS:
        return DATABRICKS_APP
    return kind


def plug_point(ctx: Any, agent_id: str) -> dict[str, Any]:
    """The plug point in use and how it was decided: ``kind`` (one of :data:`PLUG_KINDS`),
    ``decided_by`` (``agent_row``, ``policy`` or ``none``), and the raw ``plug_point`` and
    ``host_type`` values that were read."""
    seen: list[tuple[str, str, str]] = []
    try:
        row = ctx.state.get("agent", {"agent_id": agent_id})
    except Exception:  # noqa: BLE001 - a store problem leaves the policy to decide
        row = None
    if row is not None:
        seen.append(
            ("agent_row", str(row.get("plug_point") or ""), str(row.get("host_type") or ""))
        )
    try:
        manifest = ctx.gateway.states.policy.current().doc.agents.get(agent_id)
    except Exception:  # noqa: BLE001 - no policy loaded
        manifest = None
    if manifest is not None:
        seen.append(("policy", str(manifest.plug_point or ""), str(manifest.host_type or "")))
    for source, plug, host in seen:
        kind = _recognise(plug, host)
        if kind != UNKNOWN:
            return {"kind": kind, "decided_by": source, "plug_point": plug, "host_type": host}
    first = seen[0] if seen else ("none", "", "")
    return {"kind": UNKNOWN, "decided_by": first[0], "plug_point": first[1], "host_type": first[2]}


# -------------------------------------------------------------------------------------- floor


def agent_floor(ctx: Any, agent_id: str) -> set[str]:
    """Floor slugs of every AI system the agent is linked to (the union), plus the gate rules.
    A rules file that cannot be read gives no floor, never an error."""
    out = {POLICY_RULES}
    try:
        names = {
            str(r["system_id"]) for r in ctx.state.query("ai_system") if r["status"] != "archived"
        }
        for c in ctx.state.query("system_component", {"ref_kind": "agent"}):
            sid = str(c["system_id"])
            if (
                sid in names
                and str(c["ref_id"]).lower() == agent_id.lower()
                and gd._on(c["active"])
            ):
                try:
                    out |= {f["slug"] for f in gd._floor(ctx.settings, ctx.state, sid)}
                except Exception:  # noqa: BLE001, S112 - no rules file: no floor from this system
                    continue
    except Exception:  # noqa: BLE001, S110 - tables missing (governance off): gate rules only
        pass
    return out


# ----------------------------------------------------------------------------------- gate


def gate_info(ctx: Any, agent_id: str) -> dict[str, Any]:
    """Gate state and the fail modes of the rules that apply to the agent (counts)."""
    state: str | None = None
    try:
        state = ctx.gateway.states.get_state(agent_id)
    except Exception:  # noqa: BLE001 - no policy and no row: state unknown
        state = None
    closed = opened = 0
    try:
        for r in ctx.gateway.states.policy.current().rules_for(agent_id):
            if r.effective_fail_mode == "closed":
                closed += 1
            else:
                opened += 1
    except Exception:  # noqa: BLE001, S110 - no policy loaded: no rules counted
        pass
    return {
        "state": state,
        "rules": closed + opened,
        "fail_closed": closed,
        "fail_open": opened,
        "shadow": state == "SHADOW",
    }


# --------------------------------------------------------------------------------- the model


def _rows(ctx: Any, table: str, where: Mapping[str, Any], order: str) -> list[Mapping[str, Any]]:
    try:
        return list(ctx.tables.query(table, dict(where), order_by=(order,), limit=SCAN))
    except Exception:  # noqa: BLE001 - a table that cannot be read shows as no evidence
        return []


def _judge_items(
    ctx: Any,
    agent_id: str,
    now: dt.datetime,
    floor: set[str],
    by: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    s = ctx.settings
    verdicts = [
        v
        for v in _rows(ctx, "verdict", {"agent_id": agent_id}, "-ts")
        if int(v.get("tier") or 0) >= 1 and v.get("role") != "protocol"
    ]
    primary = [v for v in verdicts if v.get("role") != "challenger"]
    t1 = [_dt(v["ts"]) for v in primary if int(v["tier"]) == 1]
    t2 = [_dt(v["ts"]) for v in primary if int(v["tier"]) >= 2]
    ch = [_dt(v["ts"]) for v in verdicts if v.get("role") == "challenger"]
    on = bool(getattr(s, "judge_enabled", False))
    sample = by.get("judge_t2_sample", {})
    sample_note = "random sample on" if sample.get("effective") else "random sample off"
    out = [
        _item(
            "judge_t1",
            "judges",
            floor=False,
            enabled=on,
            stamps=t1,
            now=now,
            mock=not str(getattr(s, "judge_t1_model", "") or ""),
            detail="advises only",
        ),
        _item(
            "judge_t2",
            "judges",
            floor="judge_t2_sample" in floor,
            enabled=on,
            stamps=t2,
            now=now,
            mock=not str(getattr(s, "judge_t2_model", "") or ""),
            detail=f"advises only; {sample_note}",
        ),
    ]
    chall = by.get("judge_challenger", {})
    out.append(
        _item(
            "judge_challenger",
            "judges",
            floor="judge_challenger" in floor,
            enabled=bool(chall.get("effective")),
            stamps=ch,
            now=now,
            mock=not str(getattr(s, "judge_challenger_model", "") or ""),
            detail="advises only",
        )
    )
    return out


def _monitor_items(
    ctx: Any,
    agent_id: str,
    now: dt.datetime,
    floor: set[str],
    by: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    metrics = _rows(ctx, "oversight_metric", {"agent_id": agent_id}, "-metric_date")[:60]
    out: list[dict[str, Any]] = []
    for slug, key in MONITOR_KEY.items():
        stamps: list[dt.datetime | None] = []
        newest_status = ""
        for m in metrics:
            raw = readmodels.jloads(m.get("monitor_status"), {})
            entry = raw.get(key) if isinstance(raw, Mapping) else None
            if not isinstance(entry, Mapping):
                continue
            if not newest_status:
                newest_status = str(entry.get("status") or "")
            if entry.get("status") == "ok":
                stamps.append(_dt(m.get("computed_at")))
        row = by.get(slug, {})
        out.append(
            _item(
                slug,
                "monitors",
                floor=slug in floor,
                enabled=bool(row.get("effective")),
                stamps=stamps,
                now=now,
                status=newest_status,
            )
        )
    sess = by.get(gd.SESSION, {})
    return out + [
        _item(
            "session_monitor",
            "monitors",
            floor=gd.SESSION in floor,
            enabled=bool(sess.get("effective")),
            stamps=[
                _dt(c.get("created_at"))
                for c in _rows(ctx, "session_control", {"agent_id": agent_id}, "-created_at")
            ],
            now=now,
            detail="pauses money and credit tools",
        )
    ]


def _pack_items(ctx: Any, agent_id: str, now: dt.datetime) -> list[dict[str, Any]]:
    packs: dict[str, list[Mapping[str, Any]]] = {}
    for r in _rows(ctx, "eval_result", {"target_id": agent_id}, "-ts"):
        packs.setdefault(str(r["pack_id"]), []).append(r)
    out = []
    for pack_id in sorted(packs):
        rows = packs[pack_id]  # newest first
        out.append(
            _item(
                f"pack:{pack_id}",
                "monitors",
                floor=False,
                enabled=True,
                stamps=[_dt(r.get("ts")) for r in rows],
                now=now,
                label=pack_id,
                mock=bool(rows[0].get("is_mock")),
                status=str(rows[0].get("status") or ""),
                detail="assurance pack",
            )
        )
    return out


def attach_model(ctx: Any, agent_or_node_id: str) -> dict[str, Any]:
    """The whole view of one agent (or candidate node id). See the module docstring."""
    agent_id = str(agent_or_node_id)
    now = ctx.clock.now()
    floor = agent_floor(ctx, agent_id)
    rows = agent_guardians.feature_rows(ctx, agent_id)
    by = {r["slug"]: r for r in rows}
    gate = gate_info(ctx, agent_id)

    gate_events = [
        _dt(e.get("ts"))
        for e in _rows(
            ctx, "agent_event", {"agent_id": agent_id, "event_type": "gate_decision"}, "-ts"
        )
    ]
    gate_items = [
        _item(
            POLICY_RULES,
            "gate",
            floor=True,
            enabled=True,
            stamps=gate_events,
            now=now,
            detail=(
                f"{gate['state'] or 'state unknown'}; fail closed {gate['fail_closed']}, "
                f"fail open {gate['fail_open']}"
            ),
        )
    ]
    findings: dict[str, list[dt.datetime | None]] = {}
    mock_last: dict[str, bool] = {}
    for f in _rows(ctx, "finding", {"agent_id": agent_id}, "-ts"):
        slug = str(f.get("detector_slug") or "")
        findings.setdefault(slug, []).append(_dt(f.get("ts")))
        mock_last.setdefault(slug, bool(f.get("is_mock")))
    det_items = [
        _item(
            r["slug"],
            "detectors",
            floor=r["slug"] in floor,
            enabled=bool(r["effective"]),
            stamps=findings.get(r["slug"], []),
            now=now,
            mock=mock_last.get(r["slug"], False),
            detail="" if r["effective"] else str(r.get("reason") or ""),
        )
        for r in rows
        if r["group"] == "detect"
    ]
    groups = {
        "gate": gate_items,
        "detectors": det_items,
        "judges": _judge_items(ctx, agent_id, now, floor, by),
        "monitors": _monitor_items(ctx, agent_id, now, floor, by) + _pack_items(ctx, agent_id, now),
    }
    items = [i for g in GROUPS for i in groups[g]]
    plug = plug_point(ctx, agent_id)
    return {
        "agent_id": agent_id,
        "checked_at": format_ts(now),
        "plug": plug,
        "gate": gate,
        "groups": [{"key": g, "items": groups[g]} for g in GROUPS],
        "counts": {
            "total": len(items),
            "lit": sum(1 for i in items if i["lit"]),
            "floor": sum(1 for i in items if i["floor"]),
            "enabled": sum(1 for i in items if i["enabled"]),
        },
    }


# ---------------------------------------------------------------------------- how to attach


def credential_kind(settings: Any) -> str:
    """The credential kind a candidate sets in ``SUPERVISOR_CREDENTIAL_KIND``: ``hmac`` or
    ``databricks_oauth`` (the bearer of its own service principal), from ``INGRESS_CREDENTIAL_KIND``
    and the mode."""
    kind = str(getattr(settings, "ingress_credential_kind", "auto") or "auto")
    if kind == "auto":
        kind = "databricks_proxy" if settings.supervisor_mode == "databricks_app" else "hmac"
    return "hmac" if kind == "hmac" else "databricks_oauth"


def timeout_s(settings: Any) -> int:
    """``SUPERVISOR_TIMEOUT_S``: the gate budget rounded up plus 5 s (``docs/ingress-auth.md``,
    "Timeout budget"). An integer."""
    return int(math.ceil(float(settings.gate_decision_timeout_s))) + 5


def gate_url(settings: Any) -> str:
    public = str(getattr(settings, "collectors_public_url", "") or "").strip().rstrip("/")
    if public:
        return public
    if settings.supervisor_mode == "databricks_app":
        return "https://FILL-ME-supervisor-app-url"
    return "http://127.0.0.1:8000"


def principals_of(settings: Any, agent_id: str) -> list[str]:
    """Principals that ``config/agent_identities.yaml`` lists for the agent (ids only; the file's
    other keys are never read)."""
    from supervisor.adapters.auth.agent_creds_identity import AgentIdentityMap, IdentityError

    path = getattr(settings, "ingress_identities_file", None)
    if not path:
        return []
    try:
        entries = AgentIdentityMap.from_file(Path(path)).entries()
    except (IdentityError, OSError):
        return []
    return sorted(p for p, agents in entries.items() if agent_id in agents)


def how_to_attach(ctx: Any, agent_id: str, kind: str | None = None) -> dict[str, Any]:
    """The env lines for the plug point. ``lines`` is the copy block (one string per line),
    ``variant`` the plug kind, ``principals`` the principals listed for the agent and ``notes``
    keys of fixed hints (``attach_note_*`` in the i18n file). No secret or token appears."""
    s = ctx.settings
    kind = kind or plug_point(ctx, agent_id)["kind"]
    url = gate_url(s)
    cred = credential_kind(s)
    t = timeout_s(s)
    notes: list[str] = []
    if cred == "hmac":
        notes.append("secret_hmac")
    else:
        notes.append("secret_oauth")
    if not getattr(s, "ingress_auth_enabled", False):
        notes.append("ingress_off")
    principals = principals_of(s, agent_id) if cred != "hmac" else []
    if cred != "hmac" and not principals:
        notes.append("no_principal")
    env = [
        ("SUPERVISOR_GATE_URL", url),
        ("SUPERVISOR_AGENT_ID", agent_id),
        ("SUPERVISOR_CREDENTIAL_KIND", cred),
        ("SUPERVISOR_TIMEOUT_S", str(t)),
    ]
    lines: list[str]
    if kind == DATABRICKS_APP:
        lines = ["env:"]
        for name, value in env:
            lines += [f"  - name: {name}", f'    value: "{value}"']
    else:
        lines = [f"set {name}={value}" for name, value in env]
        if kind == HTTP_PROXY:
            lines.append(f"set SUPERVISOR_URL={url}")
            notes.append("proxy")
        elif kind == MCP_GATEWAY:
            lines += [
                "set MCP_HTTP_ENABLED=1",
                "python -m supervisor.gateway.mcp_http --upstream FILL-ME-mcp-server-url"
                f" --agent {agent_id} --listen 127.0.0.1:9701 --gate-url {url}"
                " --key-file FILL-ME-path-to-key-file",
            ]
            notes.append("mcp")
        elif kind == UNKNOWN:
            notes.append("unknown_plug")
    return {
        "variant": kind,
        "lines": lines,
        "text": "\n".join(lines),
        "principals": principals,
        "notes": notes,
        "credential_kind": cred,
        "timeout_s": t,
    }
