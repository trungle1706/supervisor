"""View model of the smart guardian panel (WP-G4, ``SMART_GUARDIAN``). The rules are in
``onboard/smart_guardian.py``; this module is the console side: what the panel shows and what a
person may press. The panel sits on the Guardians tab of the system page and on the Guardian fit
step of the register workflow. Not legal advice."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.core import rbac
from supervisor.onboard import smart_guardian as sg

GROUP_TITLES = {
    "guardian_set": "sgd_g_guardian_set",
    "thresholds": "sgd_g_thresholds",
    "autonomy_limits": "sgd_g_autonomy_limits",
    "floor": "sgd_g_floor",
}


def is_on(ctx: Any) -> bool:
    return sg.enabled(ctx.settings)


def _vtext(ln: Mapping[str, Any]) -> str:
    if ln["group"] == "floor":
        return ", ".join(ln.get("rules") or [])
    if ln["group"] == "guardian_set":
        return "on"
    val = ln.get("value")
    text = ", ".join(str(x) for x in val) if isinstance(val, list) else str(val)
    return f"{text} {ln['unit']}" if ln.get("unit") else text


def may_edit(me: Any, system: Mapping[str, Any]) -> bool:
    user = getattr(me, "kind", "") == "user"
    return bool(
        user and rbac.allowed(me.roles, "systems.edit") and system.get("status") != "archived"
    )


def panel_data(ctx: Any, me: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    """Template variables of ``_smart_guardian_panel.html``; only ``sg_on`` (false) when off, and
    then no table is read."""
    if not is_on(ctx):
        return {"sg_on": False}
    sid = str(system["system_id"])
    row = sg.current(ctx, sid)
    groups: dict[str, list[dict[str, Any]]] = {g: [] for g in sg.GROUPS}
    if row is not None:
        for ln in row["proposal"].get("lines", []):
            groups.setdefault(ln["group"], []).append({**ln, "vtext": _vtext(ln)})
    nodes = sorted(
        {str(c["ref_id"]) for c in system.get("components", []) if c["ref_kind"] == "node"}
    )
    open_ = bool(row and row["status"] == "proposed")
    return {
        "sg_on": True,
        "sg_sid": sid,
        "sg_row": row,
        "sg_groups": groups,
        "sg_titles": GROUP_TITLES,
        "sg_open": open_,
        "sg_can": may_edit(me, system),
        "sg_nodes": nodes if getattr(ctx.settings, "onboard_predeploy", False) else [],
        "sg_banner": sg.BANNER,
        "sg_decision": (row["proposal"].get("decision") if row else None) or {},
    }


def do_create(ctx: Any, me: Any, system: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    sg.ensure_on(ctx.settings)
    row = sg.create(ctx, str(system["system_id"]), _person(me))
    return row, f"proposal={row['proposal_id']} attempt={row['attempt_n']}"


def do_accept(
    ctx: Any, me: Any, system: Mapping[str, Any], form: Mapping[str, str]
) -> tuple[dict[str, Any], str]:
    sg.ensure_on(ctx.settings)
    ids = [k[4:] for k, v in form.items() if k.startswith("sel_") and v]
    row = sg.accept(
        ctx,
        str(system["system_id"]),
        _person(me),
        ids,
        form.get("note"),
        proposal_id=form.get("proposal_id") or None,
    )
    return row, f"accept proposal={row['proposal_id']} lines={len(ids)}"


def do_reject(
    ctx: Any, me: Any, system: Mapping[str, Any], form: Mapping[str, str]
) -> tuple[dict[str, Any], str]:
    sg.ensure_on(ctx.settings)
    row = sg.reject(
        ctx,
        str(system["system_id"]),
        _person(me),
        form.get("reason"),
        proposal_id=form.get("proposal_id") or None,
    )
    return row, f"reject proposal={row['proposal_id']}"


def _person(me: Any) -> str:
    from supervisor.cases.service import PermissionDenied

    if getattr(me, "kind", "") != "user":
        raise PermissionDenied("this action needs a signed-in person")
    return str(me.user_id)
