"""Data of the CONSOLE_NAV_V3 pages (WP-UX4a): My overview, Governance overview, Supervisor
overview, Workflows, the Catalogues asset tabs and the Guardians category tabs.

Everything here reads services that already exist (agent cards, gate events, verdicts, cases,
alerts, tasks, control status, risks, compliance cards, inventory nodes, assurance runs, the
detector file). Numbers are integers or basis points. A figure that cannot be computed is
``None`` with a ``na`` reason key, never a made-up value; the page shows "not available" and the
reason. Judges that run without a model are labelled ``mock``. Read only: nothing here writes."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from supervisor.console import catalog_view, readmodels, views
from supervisor.core import rbac
from supervisor.core.errors import SupervisorError

SCOPES = ("my", "team", "all")
DAY = dt.timedelta(hours=24)
WEEK = dt.timedelta(days=7)
# inventory node kinds behind each Catalogues asset tab
ASSET_KINDS: dict[str, tuple[str, ...]] = {
    "models": ("model", "model_endpoint"),
    "tools": ("tool",),
    "datasets": ("dataset",),
    "mcp": ("mcp_server",),
}
GUARD_CATS = {"detectors": "detect", "judges": "judge", "monitors": "monitor"}


class ScopeError(SupervisorError):
    """Unknown scope (HTTP 400)."""


def tile(
    key: str, value: int | None, detail: str = "", na: str = "", **extra: Any
) -> dict[str, Any]:
    """One number tile. ``value`` None means not available; ``na`` is the i18n key of why."""
    return {"key": key, "value": value, "detail": detail, "na": na, **extra}


# ---------------------------------------------------------------------------- scope


def parse_scope(raw: str | None, cards: list[dict[str, Any]], me: Any) -> str:
    if raw in (None, ""):
        return "my" if any(c.get("owner_user") == me.user_id for c in cards) else "all"
    if raw not in SCOPES:
        raise ScopeError("scope must be my, team or all")
    return raw


def in_scope(cards: list[dict[str, Any]], me: Any, scope: str) -> list[dict[str, Any]]:
    """My agents (owner), the agents of my teams (owner team of one of my agents), or all."""
    if scope == "all":
        return list(cards)
    mine = [c for c in cards if c.get("owner_user") == me.user_id]
    if scope == "my":
        return mine
    teams = {c.get("owner_team") for c in mine if c.get("owner_team")}
    return [c for c in cards if c.get("owner_team") in teams]


def tier_detail(cards: list[dict[str, Any]]) -> list[tuple[str, int]]:
    out: dict[str, int] = {}
    for c in cards:
        out[str(c.get("risk_tier") or "-")] = out.get(str(c.get("risk_tier") or "-"), 0) + 1
    return sorted(out.items())


# ---------------------------------------------------------------------------- guardians


def mandatory_detectors(ctx: Any) -> tuple[list[str], str]:
    """(slugs, na reason). Mandatory = ``fail_closed`` in the file AND allowed to fail closed by
    the registry (an advisory detector, or one without its approval, never is): the same test
    the gate applies (``ResolvedDetectors.for_agent``). There is no other 'mandatory' flag."""
    from supervisor.adapters.masking.vn_regex import VnRegexMasker
    from supervisor.detectors import build_registry
    from supervisor.detectors.config import load_config

    try:
        conf = load_config(ctx.settings.detectors_config)
        key, key_id = ctx.settings.mask_key
        registry = build_registry(VnRegexMasker(key, key_id))
        slugs = sorted(
            s for s, e in conf.detectors.items() if e.fail_closed and registry.may_fail_closed(s)
        )
    except Exception:  # noqa: BLE001 - a bad file is the gate's error, not this page's
        return [], "nv3_na_detector_file"
    return (slugs, "") if slugs else ([], "nv3_na_no_mandatory")


def _file_enabled(ctx: Any) -> dict[str, bool]:
    return catalog_view._detectors_on(ctx.settings)


def _override(ctx: Any, agent_id: str) -> Any:
    try:
        return ctx.gateway.states.policy.current().doc.agents[agent_id].detectors
    except Exception:  # noqa: BLE001 - no policy or no entry: no per-agent override
        return None


def guardian_cover(ctx: Any, agent_id: str, mandatory: list[str], enabled: dict[str, bool]) -> dict:
    """Which mandatory detectors are on for one agent: the file value, switched by the agent's
    ``enable`` / ``disable`` in the policy; all off while DETECTORS_ENABLED is off."""
    ov = _override(ctx, agent_id)
    extra = set(getattr(ov, "enable", None) or ())
    gone = set(getattr(ov, "disable", None) or ())
    master = bool(getattr(ctx.settings, "detectors_enabled", False))
    off = [
        s for s in mandatory if not (master and (enabled.get(s) or s in extra) and s not in gone)
    ]
    return {"total": len(mandatory), "off": off, "full": bool(mandatory) and not off}


def cover_for(ctx: Any, cards: list[dict[str, Any]]) -> dict[str, Any]:
    """``{agent_id: cover}`` plus the tile numbers. ``covered`` is None when no mandatory
    detector is defined (a share of nothing is not a figure)."""
    slugs, na = mandatory_detectors(ctx)
    enabled = _file_enabled(ctx)
    by = {c["agent_id"]: guardian_cover(ctx, c["agent_id"], slugs, enabled) for c in cards}
    covered = sum(1 for v in by.values() if v["full"])
    master = bool(getattr(ctx.settings, "detectors_enabled", False))
    return {
        "by_agent": by,
        "covered": covered if slugs else None,
        "total": len(cards),
        "na": na,
        "master": master,
        "mandatory": slugs,
    }


def cover_tile(cov: dict[str, Any]) -> dict[str, Any]:
    detail = "" if cov["master"] else "nv3_cover_master_off"
    return tile("cover", cov["covered"], detail, cov["na"], of=cov["total"])


# ---------------------------------------------------------------------------- actions


def open_actions(ctx: Any, me: Any, own_ids: set[str]) -> dict[str, Any]:
    """What waits on this person: open cases assigned to them, cases that need their sign-off,
    and open required tasks of the agents they own (``own_ids``)."""
    items: list[dict[str, Any]] = []
    cases = readmodels.open_cases(ctx)
    for c in sorted(cases, key=lambda c: c["case_id"]):
        if c.get("assignee") == me.user_id:
            items.append(
                {
                    "kind": "case",
                    "text": str(c.get("summary") or c["case_id"]),
                    "href": f"/console/cases/{c['case_id']}",
                    "due": c.get("report_due_at"),
                }
            )
    sign = 0
    if rbac.allowed(me.roles, "case.signoff"):
        try:
            waiting = ctx.cases.waiting_approvals(cases)
        except Exception:  # noqa: BLE001 - a convenience list, never a page failure
            waiting = []
        for w in waiting:
            if me.user_id in (w.get("approvals") or {}):
                continue
            sign += 1
            items.append(
                {
                    "kind": "approval",
                    "text": str(w["case"].get("summary") or w["case"]["case_id"]),
                    "href": f"/console/cases/{w['case']['case_id']}/signoff",
                    "due": w["case"].get("report_due_at"),
                }
            )
    n_task = 0
    if ctx.settings.controls_enabled:
        try:
            rows = ctx.tasks.list_tasks()
        except Exception:  # noqa: BLE001
            rows = []
        for r in rows:
            if (
                r["agent_id"] in own_ids
                and r["required"]
                and r["status"] in ("open", "in_progress")
            ):
                n_task += 1
                items.append(
                    {
                        "kind": "task",
                        "text": str(r["title"]),
                        "href": "/console/tasks",
                        "due": r.get("due_at"),
                    }
                )
    n_case = sum(1 for i in items if i["kind"] == "case")
    return {"items": items, "n": len(items), "cases": n_case, "approvals": sign, "tasks": n_task}


def own_ids_of(ctx: Any, me: Any) -> set[str]:
    return {str(a["agent_id"]) for a in ctx.state.query("agent", {"owner_user": me.user_id})}


# ---------------------------------------------------------------------------- gate, 24 h


def gate_24h(ctx: Any, now: dt.datetime, agents: set[str] | None) -> dict[str, Any]:
    """Gate decisions of the last 24 hours (rolling): checked, blocked, paused, p95 latency,
    per agent. ``agents`` limits the rows (None = all)."""
    since = now - DAY
    events = ctx.tables.query(
        "agent_event",
        {"event_type": "gate_decision"},
        order_by=("-ts",),
        limit=readmodels.SCAN_CAP,
    )
    recent = [e for e in events if e["ts"] >= since and (agents is None or e["agent_id"] in agents)]
    ids = {e["event_id"] for e in recent}
    stops: dict[str, str] = {}
    for v in readmodels.stop_verdicts(ctx, readmodels.SCAN_CAP):
        key = v.get("event_id")
        if v["advisory"] or key not in ids:
            continue
        if stops.get(key) != "pause":
            stops[key] = v["action"]
    per: dict[str, dict[str, Any]] = {}
    for e in recent:
        row = per.setdefault(e["agent_id"], {"checked": 0, "blocked": 0, "paused": 0, "lat": []})
        row["checked"] += 1
        action = stops.get(e["event_id"])
        row["blocked"] += action == "block"
        row["paused"] += action == "pause"
        if e.get("latency_ms") is not None:
            row["lat"].append(int(e["latency_ms"]))
    for row in per.values():
        lat = sorted(row.pop("lat"))
        row["p95_ms"] = lat[max(0, (len(lat) * 95 + 99) // 100 - 1)] if lat else None
    return {
        "per": per,
        "checked": len(recent),
        "blocked": sum(1 for a in stops.values() if a == "block"),
        "paused": sum(1 for a in stops.values() if a == "pause"),
        "agents": len(per),
        "capped": len(events) >= readmodels.SCAN_CAP,
    }


# ---------------------------------------------------------------------------- My overview


def my_overview(ctx: Any, me: Any, scope_raw: str | None, now: dt.datetime) -> dict[str, Any]:
    cards = readmodels.agent_cards(ctx, me)
    scope = parse_scope(scope_raw, cards, me)
    scoped = in_scope(cards, me, scope)
    ids = {c["agent_id"] for c in scoped}
    cov = cover_for(ctx, scoped)
    acts = open_actions(ctx, me, own_ids_of(ctx, me))
    tiers = tier_detail(scoped)
    models = _asset_count(ctx, "models")
    tiles = [
        tile("agents", len(scoped), "", "", tiers=tiers),
        (
            tile("models", models[0], "", "", unmanaged=models[1])
            if models is not None
            else tile("models", None, "", "nv3_na_inventory_off", unmanaged=0)
        ),
        cover_tile(cov),
        tile(
            "actions",
            acts["n"],
            "",
            "",
            cases=acts["cases"],
            approvals=acts["approvals"],
            tasks=acts["tasks"],
        ),
    ]
    rows = [
        {
            "agent_id": c["agent_id"],
            "name": c.get("name") or c["agent_id"],
            "state": c["state"],
            "risk_tier": c.get("risk_tier") or "-",
            "cover": cov["by_agent"].get(c["agent_id"]),
            "open_cases": c.get("open_cases", 0),
            "coverage_bp": (c.get("coverage") or {}).get("bp"),
        }
        for c in scoped
    ]
    recent = [e for e in readmodels.latest_decisions(ctx, 40) if e["agent_id"] in ids][:6]
    return {
        "scope": scope,
        "scopes": SCOPES,
        "tiles": tiles,
        "rows": rows,
        "actions": acts["items"][:10],
        "actions_n": acts["n"],
        "recent": recent,
        "cases_n": len(readmodels.open_cases(ctx)),
        "clock": _nearest_clock(ctx, now),
    }


def _nearest_clock(ctx: Any, now: dt.datetime) -> dict[str, Any] | None:
    """The countdown of the open case whose report deadline in force is nearest (UX5-S: the
    Decree 142 clock from ``readmodels.incident_clock``, not the deprecated 24 h clock)."""
    clocks = [
        clk
        for c in readmodels.open_cases(ctx)
        if (clk := readmodels.incident_clock(c, now)) is not None
    ]
    if not clocks:
        return None
    return min(clocks, key=lambda k: (not k["overdue"], -k["secs"] if k["overdue"] else k["secs"]))


def actions_count(ctx: Any, me: Any) -> int:
    """The badge of My overview: the same count as the page (own agents only)."""
    return int(open_actions(ctx, me, own_ids_of(ctx, me))["n"])


def _asset_nodes(ctx: Any, tab: str) -> list[dict[str, Any]] | None:
    if not ctx.settings.inventory_enabled:
        return None
    out: list[dict[str, Any]] = []
    for kind in ASSET_KINDS[tab]:
        out += [
            n for n in ctx.state.query("inventory_node", {"kind": kind}) if n["status"] != "gone"
        ]
    return sorted(out, key=lambda n: (n["kind"], str(n["display_name"])))


def _asset_count(ctx: Any, tab: str) -> tuple[int, int] | None:
    nodes = _asset_nodes(ctx, tab)
    if nodes is None:
        return None
    return len(nodes), sum(1 for n in nodes if n["status"] == "unmanaged")


def asset_page(ctx: Any, tab: str) -> dict[str, Any]:
    nodes = _asset_nodes(ctx, tab)
    rows = [
        {
            "kind": n["kind"],
            "name": n["display_name"],
            "status": n["status"],
            "own_risk": n.get("own_risk"),
            "risk_source": n.get("risk_source") or "none",
            "last_seen": n.get("last_seen"),
        }
        for n in (nodes or [])
    ]
    return {"tab": tab, "rows": rows, "off": nodes is None}


# ---------------------------------------------------------------------------- Governance


STATUS_CAP = 20000


def _latest_status(ctx: Any, ids: set[str]) -> tuple[dict[tuple[str, str], str], bool]:
    """Newest status per (control, agent) and whether the scan hit its row limit."""
    rows = ctx.tables.query("control_status", None, order_by=("-ts",), limit=STATUS_CAP)
    out: dict[tuple[str, str], str] = {}
    for r in rows:
        key = (r["control_id"], r["agent_id"])
        if r["agent_id"] in ids and key not in out:
            out[key] = r["status"]
    return out, len(rows) >= STATUS_CAP


def governance_overview(
    ctx: Any, me: Any, scope_raw: str | None, now: dt.datetime
) -> dict[str, Any]:
    cards = readmodels.agent_cards(ctx, me)
    scope = parse_scope(scope_raw, cards, me)
    scoped = in_scope(cards, me, scope)
    ids = {c["agent_id"] for c in scoped}
    s = ctx.settings
    classified = sum(1 for c in scoped if (c.get("d33") or {}).get("source") == "registry")
    class_tile = (
        tile("classified", classified * 10000 // len(scoped), "", "", n=classified, of=len(scoped))
        if scoped
        else tile("classified", None, "", "nv3_na_no_agents", n=0, of=0)
    )
    # control readiness: latest evidence status of each control per agent, working / all
    if not s.controls_enabled:
        ready = tile("readiness", None, "", "nv3_na_controls_off", n=0, of=0, capped=False)
    else:
        latest, capped = _latest_status(ctx, ids)
        working = sum(1 for v in latest.values() if v == "working")
        ready = (
            tile(
                "readiness",
                working * 10000 // len(latest),
                "",
                "",
                n=working,
                of=len(latest),
                capped=capped,
            )
            if latest
            else tile("readiness", None, "", "nv3_na_no_status", n=0, of=0, capped=False)
        )
    # tasks: overdue and the stage table
    stage_rows: list[dict[str, Any]] = []
    if not s.controls_enabled:
        overdue = tile("overdue", None, "", "nv3_na_controls_off", oldest=None)
        stage_na = "nv3_na_controls_off"
    else:
        tasks = ctx.tasks
        late = [
            r for r in tasks.list_tasks() if r["agent_id"] in ids and r["overdue"] and r["required"]
        ]
        oldest = _oldest_days(late, now)
        overdue = tile("overdue", len(late), "", "", oldest=oldest)
        by_stage: dict[str, dict[str, int]] = {}
        for c in scoped:
            st = tasks.current_stage(c["agent_id"]) or "-"
            row = by_stage.setdefault(st, {"agents": 0, "open": 0})
            row["agents"] += 1
            row["open"] += len(tasks.open_required(c["agent_id"]))
        stage_rows = [{"stage": k, **v} for k, v in sorted(by_stage.items())]
        stage_na = ""
    return {
        "scope": scope,
        "scopes": SCOPES,
        "tiles": [
            tile("agents", len(scoped), "", "", tiers=tier_detail(scoped)),
            class_tile,
            ready,
            overdue,
        ],
        "stages": stage_rows,
        "stage_na": stage_na,
        "risks": _risk_posture(ctx, ids, scope),
        "policy": _policy_rows(ctx, ids),
    }


def _oldest_days(rows: list[Mapping[str, Any]], now: dt.datetime) -> int | None:
    dues = []
    for r in rows:
        due = r.get("due_at")
        if isinstance(due, str):
            try:
                due = dt.datetime.fromisoformat(due.replace("Z", "+00:00"))
            except ValueError:
                due = None
        if isinstance(due, dt.datetime):
            dues.append(due if due.tzinfo else due.replace(tzinfo=dt.UTC))
    return (now - min(dues)).days if dues else None


def _risk_posture(ctx: Any, ids: set[str], scope: str) -> dict[str, Any]:
    if not ctx.settings.risk_register_enabled:
        return {"na": "nv3_na_risks_off", "rows": []}
    rows = [r for r in ctx.risks.list_risks() if r["status"] == "active"]
    if scope != "all":
        rows = [r for r in rows if ids & set(r.get("agents") or [])]
    out = []
    for band in ("critical", "high", "medium", "low"):
        sel = [r for r in rows if r["residual_band"] == band]
        if not sel:
            continue
        accepted = sum(1 for r in sel if r["treatment"] == "accept")
        out.append(
            {"band": band, "n": len(sel), "treated": len(sel) - accepted, "accepted": accepted}
        )
    return {"na": "", "rows": out}


def _policy_rows(ctx: Any, ids: set[str]) -> dict[str, Any]:
    if not ctx.settings.console_compliance_enabled:
        return {"na": "nv3_na_compliance_off", "rows": []}
    from supervisor.console import compliance_view

    out = []
    for c in compliance_view.cards(ctx.settings):
        if c["agent"] not in ids:
            continue
        applies = int(c["applies_yes"])
        met = int(c["by_status"].get("met", 0))
        out.append(
            {
                "agent": c["agent"],
                "name": c["name"],
                "applies": applies,
                "met": met,
                "gap": int(c["by_status"].get("gap", 0)),
                "bp": met * 10000 // applies if applies else None,
            }
        )
    return {"na": "", "rows": out}


# ---------------------------------------------------------------------------- Supervisor


def supervisor_overview(
    ctx: Any, me: Any, scope_raw: str | None, now: dt.datetime
) -> dict[str, Any]:
    cards = readmodels.agent_cards(ctx, me)
    scope = parse_scope(scope_raw, cards, me)
    scoped = in_scope(cards, me, scope)
    ids = {c["agent_id"] for c in scoped}
    cov = cover_for(ctx, scoped)
    gate = gate_24h(ctx, now, ids)
    cases = [c for c in readmodels.open_cases(ctx) if c["agent_id"] in ids]
    due = [c for c in cases if c.get("report_due_at") is not None]
    nearest = min(due, key=lambda c: c["report_due_at"]) if due else None
    clock = (
        views.countdown(nearest["report_due_at"], now, severity=nearest["severity"])
        if nearest
        else None
    )
    critical = sum(1 for c in cases if c["severity"] == "critical")
    stopped = gate["blocked"] + gate["paused"]
    tiles = [
        tile("checked", gate["checked"], agents=gate["agents"], capped=gate["capped"]),
        tile("stopped", stopped, blocked=gate["blocked"], paused=gate["paused"]),
        cover_tile(cov),
        tile("cases", len(cases), critical=critical, clock=clock),
    ]
    verify_all = ctx.last_verify.get("all")
    rows = []
    for c in scoped:
        aid = c["agent_id"]
        g = gate["per"].get(aid, {})
        rows.append(
            {
                "agent_id": aid,
                "coverage_bp": (c.get("coverage") or {}).get("bp"),
                "cover": cov["by_agent"].get(aid),
                "blocks": int(g.get("blocked", 0)) + int(g.get("paused", 0)),
                "p95_ms": g.get("p95_ms"),
                "verify": ctx.last_verify.get(aid) or verify_all,
            }
        )
    return {
        "scope": scope,
        "scopes": SCOPES,
        "tiles": tiles,
        "rows": rows,
        "alerts": _alerts_7d(ctx, now, ids),
        "judges": _judges(ctx),
        "packs": _last_pack(ctx),
        "redteam": bool(ctx.settings.redteam_nightly_enabled),
    }


def _alerts_7d(ctx: Any, now: dt.datetime, ids: set[str]) -> list[dict[str, Any]]:
    since = now - WEEK
    per: dict[str, dict[str, Any]] = {}
    for a in ctx.alerts.list(limit=5000):
        if a["ts"] < since or (a.get("agent_id") and a["agent_id"] not in ids):
            continue
        row = per.setdefault(a["rule_id"], {"rule_id": a["rule_id"], "title": a["title"], "n": 0})
        row["n"] += 1
    return sorted(per.values(), key=lambda r: (-r["n"], r["rule_id"]))


def _judges(ctx: Any) -> dict[str, Any]:
    s = ctx.settings
    return {
        "on": bool(s.judge_enabled),
        "mock": bool(s.judge_enabled) and catalog_view._judge_is_mock(s),
    }


def _last_pack(ctx: Any) -> dict[str, Any] | None:
    rows = ctx.tables.query("eval_run", order_by=("-started_at",), limit=1)
    if not rows:
        return None
    r = rows[0]
    return {
        "run_id": r["run_id"],
        "ok": int(r["ok"]),
        "warn": int(r["warn"]),
        "fail": int(r["fail"]),
        "mock": bool(r.get("is_mock")),
        "started_at": r["started_at"],
    }


# ---------------------------------------------------------------------------- Guardians


def guardian_cards(ctx: Any, tab: str, lang: str) -> dict[str, Any]:
    """The catalogue cards of one category (detectors, judges, monitors) and, for detectors,
    the mandatory list from the detector file."""
    data = catalog_view.page(ctx, "catalog", lang)
    cat = GUARD_CATS[tab]
    cats = [c for c in data["cats"] if c["key"] == cat]
    out: dict[str, Any] = {"tab": tab, "cats": cats, "det_rows": []}
    if tab == "detectors":
        from supervisor.detectors.config import load_config

        try:
            conf = load_config(ctx.settings.detectors_config)
            out["det_rows"] = [
                {
                    "slug": slug,
                    "enabled": bool(e.enabled),
                    "mandatory": bool(e.fail_closed),
                    "mrm": e.mrm_status,
                }
                for slug, e in sorted(conf.detectors.items())
            ]
        except Exception:  # noqa: BLE001
            out["det_na"] = "nv3_na_detector_file"
        out["master"] = bool(getattr(ctx.settings, "detectors_enabled", False))
    return out


# ---------------------------------------------------------------------------- Workflows


def workflows(ctx: Any) -> dict[str, Any]:
    """Read-only list of what runs. Scheduler state exists only in the process that runs the
    scheduler; elsewhere the page says so instead of guessing."""
    from supervisor import scheduler as sched_mod

    s = ctx.settings
    sched = sched_mod.current()
    rows: list[dict[str, Any]] = []
    if sched is None:
        rows.append(
            {"name": "scheduler", "kind": "job", "state": "off", "detail": "nv3_wf_sched_none",
             "last": None, "interval": None}
        )  # fmt: skip
    else:
        for name, job in sorted(sched.jobs.items()):
            try:
                last = sched.last_run(name)
            except Exception:  # noqa: BLE001
                last = None
            rows.append(
                {"name": name, "kind": "job", "state": "on" if job.enabled else "off",
                 "detail": "", "last": last, "interval": int(job.interval_s)}
            )  # fmt: skip
    rules_na = ""
    try:
        from supervisor.alerts.rules import load_rules

        for r in load_rules(s.alerts_config).rules:
            rows.append(
                {"name": r.id, "kind": "alert", "state": "on" if s.alerts_enabled else "off",
                 "detail": "", "last": None, "interval": int(r.window_s),
                 "threshold": int(r.threshold)}
            )  # fmt: skip
    except Exception:  # noqa: BLE001 - a bad rules file is shown as a reason, not a failure
        rules_na = "nv3_wf_rules_unreadable"
    rows += [
        {"name": "signoff", "kind": "approval", "state": "on", "detail": "nv3_wfd_signoff",
         "last": None, "interval": None},
        {"name": "resume", "kind": "approval", "state": "on", "detail": "nv3_wfd_resume",
         "last": None, "interval": None},
        {"name": "waive", "kind": "approval", "state": "on" if s.controls_enabled else "off",
         "detail": "nv3_wfd_waive", "last": None, "interval": None},
        {"name": "siem", "kind": "sink", "state": "on" if s.siem_enabled else "off",
         "detail": "", "last": None, "interval": int(s.sched_siem_s)},
        {"name": "webhook", "kind": "sink", "state": "on" if s.notify_webhook_enabled else "off",
         "detail": "", "last": None, "interval": None},
    ]  # fmt: skip
    return {"rows": rows, "rules_na": rules_na, "sched": sched is not None}
