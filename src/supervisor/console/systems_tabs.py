"""Governance tabs of the system page (WP-UX4b): Risks, Controls, Policies, Guardians, Reports.

Read only. Every tab reads services that already exist and shows what they say about the agents
linked to the system (and, for risks, the inventory nodes linked to it). Numbers are integers
or basis points. A figure that cannot be computed is ``None`` with a ``na`` reason key, never a
made-up value. Judges that run without a model are labelled ``mock``. Nothing here writes.

The tabs exist only with CONSOLE_NAV_V3 (``systems_views.detail_tabs``). Each tab needs the
permission of the page it summarises (``TAB_PERM``); a role without it does not see the tab.

WP-G2 (Rules and Classification tabs, ``guardian-floor``) and WP-G5 are optional
neighbours: every use below goes through ``getattr`` or a ``try`` with a one-line comment, so
this module works with or without them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.console import (
    catalog_view,
    compliance_view,
    overview_v3,
)
from supervisor.core import rbac

# tab -> permission of the page it summarises
TAB_PERM: dict[str, str] = {
    "risks": "risks.view",
    "controls": "controls.view",
    "policies": "compliance.view",
    "guardians": "systems.view",
    "reports": "transparency.view",
}
GOV_TABS: tuple[str, ...] = tuple(TAB_PERM)
GAP_ROWS = 40  # obligations with a gap listed on the Policies tab


def may(me: Any, permission: str) -> bool:
    if getattr(me, "kind", "user") == "user":
        return rbac.allowed(me.roles, permission)
    return permission in rbac.NON_USER_OK


def agents_of(system: Mapping[str, Any]) -> list[str]:
    return sorted({str(c["ref_id"]) for c in system["components"] if c["ref_kind"] == "agent"})


def nodes_of(system: Mapping[str, Any]) -> list[str]:
    return sorted({str(c["ref_id"]) for c in system["components"] if c["ref_kind"] == "node"})


def tile(label: str, value: int | None, na: str = "", **extra: Any) -> dict[str, Any]:
    return {"label": label, "value": value, "na": na, **extra}


# ------------------------------------------------------------------------------ Risks


def risks_tab(ctx: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    """Register rows that reach the agents of the system, or sit on a node linked to it. The
    ``via`` column says where each risk is anchored (the agent itself, or a model, tool or
    dataset it uses); ``own`` is true when the anchor is the agent or node of this system."""
    if not ctx.settings.risk_register_enabled:
        return {"rk_off": True}
    agents = agents_of(system)
    nodes = set(nodes_of(system))
    levels = ctx.risks.agent_levels()
    by_id = {r["risk_id"]: r for r in ctx.risks.list_risks()}
    rows: dict[str, dict[str, Any]] = {}
    for a in agents:
        lv = levels.get(a.lower())
        for x in lv.reached if lv else []:
            risk = by_id.get(x["risk_id"])
            if risk is None or risk["status"] == "retired":
                continue
            row = rows.setdefault(
                risk["risk_id"], {**risk, "via": [], "agents": set(), "own": False}
            )
            if x["via"] not in row["via"]:
                row["via"].append(x["via"])
            row["agents"].add(a)
            row["own"] = row["own"] or bool(x["own"])
    for risk in by_id.values():  # a risk written for a node that this system links directly
        if risk.get("node_id") in nodes and risk["status"] != "retired":
            row = rows.setdefault(
                risk["risk_id"], {**risk, "via": [], "agents": set(), "own": True}
            )
            row["via"].append(f"node:{risk['node_id']}")
            row["own"] = True
    out = sorted(
        ({**r, "via": sorted(r["via"]), "agents": sorted(r["agents"])} for r in rows.values()),
        key=lambda r: (-r["residual_score"], -r["inherent_score"], r["risk_id"]),
    )
    active = [r for r in out if r["status"] == "active"]
    worst = max((r["residual_score"] for r in active), default=0)
    return {
        "rk_off": False,
        "rk_rows": out,
        "rk_active": len(active),
        "rk_worst": worst,
        "rk_worst_band": max(
            (r for r in active), key=lambda r: r["residual_score"], default={}
        ).get("residual_band"),
        "rk_inherited": sum(1 for r in out if not r["own"]),
        "rk_illustrative": bool(ctx.risks.cfg.thresholds.illustrative),
        "rk_page": bool(ctx.settings.console_risks_enabled),
    }


# ---------------------------------------------------------------------------- Controls


def controls_tab(ctx: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    """Controls in scope of the agents of the system, with the latest evidence status of each
    (working, failing, no_data) and the compliance figure in basis points."""
    if not ctx.settings.controls_enabled:
        return {"ct_off": True}
    from supervisor.controls import evidence as cev

    agents = agents_of(system)
    rows: list[dict[str, Any]] = []
    tally = {"working": 0, "failing": 0, "no_data": 0}
    unknown: list[str] = []
    for a in agents:
        comp = ctx.controls.agent_compliance(a)
        if not comp["known_agent"]:
            unknown.append(a)
            continue
        for c in comp["controls"]:
            tally[c["status"]] = tally.get(c["status"], 0) + 1
            rows.append({**c, "agent_id": comp["agent_id"]})
    in_scope = len(rows)
    rows.sort(
        key=lambda r: ({"failing": 0, "no_data": 1, "working": 2}[r["status"]], r["control_id"])
    )
    return {
        "ct_off": False,
        "ct_rows": rows,
        "ct_in_scope": in_scope,
        "ct_working": tally["working"],
        "ct_failing": tally["failing"],
        "ct_no_data": tally["no_data"],
        "ct_bp": cev.compliance_bp(tally["working"], in_scope),
        "ct_unknown": unknown,
        "ct_no_agents": not agents,
        "ct_page": bool(ctx.settings.console_controls_enabled),
    }


# ---------------------------------------------------------------------------- Policies


def policies_tab(ctx: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    """Compliance matrices of the agents of the system, added up by instrument: obligations
    that apply, met, partial, gap. Source = the matrix of the agent (demo or onboarding).
    An agent with no matrix is listed apart; it is never counted as met or as a gap."""
    if not ctx.settings.console_compliance_enabled:
        return {"pl_off": True}
    agents = agents_of(system)
    by_inst: dict[str, dict[str, Any]] = {}
    gaps: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    missing: list[str] = []
    for a in agents:
        try:
            m = compliance_view.matrix_for(ctx.settings, a)
        except compliance_view.ComplianceInputError:
            missing.append(a)
            continue
        sources.append({"agent_id": a, "kind": m.get("source_kind", ""), "n": len(m["rows"])})
        for r in m["rows"]:
            if r.get("applies") != "yes":
                continue
            inst = by_inst.setdefault(
                r["instrument_id"],
                {
                    "instrument_id": r["instrument_id"],
                    "label": r.get("instrument_number") or r["instrument_id"],
                    "binding": bool(r.get("binding")),
                    "applies": 0,
                    "met": 0,
                    "partial": 0,
                    "gap": 0,
                    "bank": 0,
                },
            )
            inst["applies"] += 1
            st = r.get("status")
            if st == "met":
                inst["met"] += 1
            elif st == "partial":
                inst["partial"] += 1
            elif st == "gap":
                inst["gap"] += 1
                gaps.append(
                    {
                        **{k: r.get(k) for k in ("obligation_id", "article_ref")},
                        "agent_id": a,
                        "instrument_id": r["instrument_id"],
                    }
                )
            elif st == "bank_process":
                inst["bank"] += 1
    insts = sorted(by_inst.values(), key=lambda i: (not i["binding"], i["instrument_id"]))
    for i in insts:
        i["bp"] = i["met"] * 10000 // i["applies"] if i["applies"] else None
    applies = sum(i["applies"] for i in insts)
    met = sum(i["met"] for i in insts)
    return {
        "pl_off": False,
        "pl_rows": insts,
        "pl_applies": applies,
        "pl_met": met,
        "pl_gap": sum(i["gap"] for i in insts),
        "pl_bp": met * 10000 // applies if applies else None,
        "pl_sources": sources,
        "pl_missing": missing,
        "pl_gaps": sorted(gaps, key=lambda g: (g["instrument_id"], g["obligation_id"]))[:GAP_ROWS],
        "pl_gaps_more": max(0, len(gaps) - GAP_ROWS),
        "pl_rule_source": _rule_obligations(ctx, system),
    }


def _rule_obligations(ctx: Any, system: Mapping[str, Any]) -> int | None:
    """Obligations the WP-G2 rules assigned to the system (source ``rule``), or None when they
    cannot be read."""
    try:
        return len(ctx.rules.obligations(str(system["system_id"])))
    except Exception:  # noqa: BLE001 - no figure rather than a broken tab
        return None


# ---------------------------------------------------------------------------- Guardians


def guardian_floor(ctx: Any, system: Mapping[str, Any]) -> tuple[list[dict[str, Any]] | None, str]:
    """The mandatory guardian floor of the system (WP-G2 ``RulesService.guardian_floor``, the
    reader of ``GET /v1/systems/{id}/guardian-floor``): ``[{slug, rules}]``. ``(None, reason
    key)`` when it cannot be read."""
    try:
        return list(ctx.rules.guardian_floor(str(system["system_id"]))), ""
    except Exception:  # noqa: BLE001 - rules service or its table is not there
        return None, "ux4b_na_no_rules"


def guardians_tab(ctx: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    """Read only (switches come with WP-S1): per linked agent the detectors on, whether the
    mandatory ones are on, and the judges and monitors that are on in this instance. The
    sources are the ones of the Supervisor overview and the Catalog page."""
    agents = agents_of(system)
    mandatory, mand_na = overview_v3.mandatory_detectors(ctx)
    enabled = overview_v3._file_enabled(ctx)  # noqa: SLF001 - same source as the overview
    master = bool(getattr(ctx.settings, "detectors_enabled", False))
    cat = catalog_view.page(ctx, "catalog", "en")
    judges: list[dict[str, Any]] = []
    monitors: list[dict[str, Any]] = []
    for c in cat["cats"]:
        if c["key"] == "judge":
            judges = [{"key": x["e"].key, "on": x["on"], "mock": x["mock"]} for x in c["cards"]]
        elif c["key"] == "monitor":
            monitors = [{"key": x["e"].key, "on": x["on"]} for x in c["cards"]]
    rows = []
    for a in agents:
        ov = overview_v3._override(ctx, a)  # noqa: SLF001
        extra = set(getattr(ov, "enable", None) or ())
        gone = set(getattr(ov, "disable", None) or ())
        on = sorted(s for s, e in enabled.items() if master and (e or s in extra) and s not in gone)
        cover = overview_v3.guardian_cover(ctx, a, mandatory, enabled)
        rows.append({"agent_id": a, "detectors": on, "cover": cover})
    floor, floor_na = guardian_floor(ctx, system)
    return {
        "gd_rows": rows,
        "gd_mandatory": mandatory,
        "gd_mand_na": mand_na,
        "gd_master": master,
        "gd_judges": judges,
        "gd_judges_on": any(j["on"] for j in judges),
        "gd_judge_mock": any(j["mock"] for j in judges),
        "gd_monitors": monitors,
        "gd_floor": floor,
        "gd_floor_na": floor_na,
        "gd_no_agents": not agents,
        "gd_bindings": _guardian_bindings(ctx, system),  # WP-S1
    }


def _guardian_bindings(ctx: Any, system: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """WP-S1 (guarded): the guardian features with their binding for this system, or None while
    GUARDIAN_BINDINGS_ENABLED is off. The switches themselves are on the Catalog page."""
    from supervisor.governance.guardians import guardian_bindings_on

    if not guardian_bindings_on(ctx.settings):
        return None
    try:
        return list(ctx.guardians.get(str(system["system_id"]))["guardians"])
    except Exception:  # noqa: BLE001 - the tab still shows the rest
        return None


# ------------------------------------------------------------------------------ Reports


def reports_tab(ctx: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    """Per linked agent: the latest transparency report of each variant (with its verify
    state), and the chain verify state of the agent lane. The audit pack is built on the
    Evidence page; this tab links to it and lists the packs that exist."""
    from supervisor.transparency.model import VARIANTS

    agents = agents_of(system)
    tp_on = bool(ctx.settings.transparency_enabled)
    heads = ctx.runtime.chain.heads()
    verify_all = ctx.last_verify.get("all")
    rows = []
    for a in agents:
        lane = f"agent:{a}"
        head = heads.get(lane)
        reports = {}
        if tp_on:
            for v in VARIANTS:
                row = ctx.transparency.latest(a, v)
                reports[v] = (
                    {
                        "version": int(row["version"]),
                        "generated_at": row["generated_at"],
                        "verify_state": row["verify_state"],
                    }
                    if row
                    else None
                )
        rows.append(
            {
                "agent_id": a,
                "reports": reports,
                "lane": lane,
                "entries": (head.seq + 1) if head else 0,
                "verify": ctx.last_verify.get(lane) or verify_all,
            }
        )
    return {
        "rp_rows": rows,
        "rp_variants": VARIANTS,
        "rp_tp_on": tp_on,
        "rp_tp_page": bool(ctx.settings.console_transparency_enabled),
    }


BUILDERS = {
    "risks": risks_tab,
    "controls": controls_tab,
    "policies": policies_tab,
    "guardians": guardians_tab,
    "reports": reports_tab,
}


def count_of(tab: str, data: Mapping[str, Any]) -> int | None:
    """The number on the tab label: the rows the tab shows, None when it is off."""
    key = {
        "risks": "rk_rows",
        "controls": "ct_rows",
        "policies": "pl_rows",
        "guardians": "gd_rows",
        "reports": "rp_rows",
    }[tab]
    rows = data.get(key)
    return len(rows) if rows is not None else None
