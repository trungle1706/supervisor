"""Read models of the test gate and promotion pages (WP-F3, flag ``AGENT_FACTORY_GATE``).

The routes (``factory_gate_routes.py``) stay thin. With the flag off none of these functions is
called: ``card_extra`` returns an empty dict without a table read and the editor has no gate step.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from supervisor.console import factory_view as fv
from supervisor.console.context import ConsoleContext
from supervisor.factory import caps, gate, golden, helpers, promotion
from supervisor.factory.store import FactoryError

GATE_STEP = "gate"
RUNNING = ("queued", "running")


def on(ctx: ConsoleContext) -> bool:
    return gate.enabled(ctx.settings)


def env(ctx: ConsoleContext) -> gate.GateEnv:
    return gate.GateEnv.from_console(
        ctx, getattr(ctx, "gate_chat", None), fv.tool_registry(), fv.group_registry()
    )


def steps(ctx: ConsoleContext) -> tuple[str, ...]:
    return (*fv.STEPS, GATE_STEP) if on(ctx) else fv.STEPS


def run_summary(r: Mapping[str, Any]) -> dict[str, Any]:
    """One row of the run table: integers, enums and the verdict."""
    l1, l2, l3 = r.get("layer1") or {}, r.get("layer2") or {}, r.get("layer3") or {}
    cal = l2.get("calibration") or {}
    reg = l2.get("regression") or {}
    return {
        "run_id": r["run_id"],
        "version": r["version"],
        "kind": r["kind"],
        "status": r["status"],
        "running": r["status"] in RUNNING,
        "verdict": r["verdict"],
        "started_at": r.get("started_at"),
        "finished_at": r.get("finished_at"),
        "created_by": r.get("created_by"),
        "progress": (l1.get("progress") or {}) if r["status"] in RUNNING else {},
        "error": l1.get("error", "") if r["status"] == "failed" else "",
        "layer1": l1 if "checks" in l1 else {},
        "layer2": l2,
        "layer3": l3,
        "cal": cal if "kappa_hundredths" in cal else {},
        "reg": reg if "lost" in reg else {},
        "cost": r.get("cost") or {},
        "report_sha256": r.get("report_sha256") or "",
        "definition_sha256": r.get("definition_sha256") or "",
    }


def card_extra(ctx: ConsoleContext, row: Mapping[str, Any]) -> dict[str, Any]:
    """The last gate result and the live version for the catalogue card (flag on only)."""
    if not on(ctx):
        return {"last_gate": None, "live_version": None}
    e = env(ctx)
    last = gate.last_gate(e, row["id"])
    live = e.store.live_version(row["id"])
    if last is None:
        summary = None
    else:
        s = run_summary(last)
        summary = {
            "kind": s["kind"],
            "verdict": s["verdict"],
            "version": s["version"],
            "layer1_percent": s["layer1"].get("percent", 0),
            "kappa": s["cal"].get("kappa_hundredths"),
            "match_percent": s["layer2"].get("match_percent"),
        }
    return {"last_gate": summary, "live_version": live["version"] if live else None}


def _approve_kinds(
    me: Any, store: Any, row: Mapping[str, Any], need: Mapping[str, Any]
) -> list[str]:
    """The approvals ``me`` could give now."""
    a = promotion.actor_of(me)
    if row["state"] != "tested" or not promotion.is_submitted(store, row):
        return []
    given = promotion.approvals_of(row)
    if a.user_id.casefold() in promotion.authors_of(store, row):
        return []
    if any(promotion.same_person(g["by"], a.user_id) for g in given):
        return []
    have = {g["role"] for g in given}
    return [
        k
        for k in need["kinds"]
        if k not in have and promotion.eligible(k, a, row["owner_group"], store)
    ]


def gate_data(ctx: ConsoleContext, me: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """The data of the editor step ``gate``: golden readiness, runs, promotion state and which
    buttons ``me`` may press."""
    e = env(ctx)
    store = e.store
    defn = row["definition"]
    ids = [c["id"] for c in defn["checklist"]]
    cases = golden.all_gate_cases(ctx.settings.data_dir, row["id"])
    strat = golden.gate_stratification(cases, ids)
    labels = golden.load_labels(ctx.settings.data_dir, row["id"])
    runs = [run_summary(r) for r in gate.latest_runs(e, row["id"], None, 12)]
    promo = promotion.summary(store, row)
    need = promotion.required_approvals(store, row)
    actor = promotion.actor_of(me) if getattr(me, "kind", "user") == "user" else None
    editor = fv.may_edit(me, row["owner_group"])
    state = row["state"]
    lead = actor is not None and promotion.eligible("owner_lead", actor, row["owner_group"], store)
    second = actor is not None and promotion.eligible(
        "second_line", actor, row["owner_group"], store
    )
    target = promotion.rollback_target(store, row["id"])
    return {
        "enabled": True,
        "model_ready": helpers.model_ready(ctx.settings)
        or getattr(ctx, "gate_chat", None) is not None,
        "golden": strat,
        "labels": len(labels),
        "labels_min": caps.CALIBRATION_MIN_LABELS,
        "runs": runs,
        "running": any(r["running"] for r in runs),
        "promo": promo,
        "need": need,
        "can_run": editor and state in ("draft", "tested"),
        "can_run_nondraft": state == "draft",
        "can_submit": editor and state == "tested" and not promo["submitted"],
        "approve_kinds": _approve_kinds(me, store, row, need) if actor else [],
        "can_reject": state in ("tested", "approved") and (lead or second),
        "can_activate": state == "approved" and lead,
        "can_reopen": editor and state in ("tested", "approved"),
        "can_rollback": actor is not None
        and actor.is_admin
        and (state == "live" or target is not None)
        and target is not None,
        "rollback_to": target["version"] if target else "",
        "kinds": caps.GATE_KINDS,
        "sample_default": caps.SAMPLE_DEFAULT,
        "sample_max": caps.SAMPLE_MAX,
        "caps": caps,
    }


def run_detail(ctx: ConsoleContext, agent_id: str, run_id: str) -> dict[str, Any]:
    e = env(ctx)
    r = gate.get_run(e, run_id)
    if r is None or r["agent_id"] != agent_id:
        raise FactoryError("not_found", "this gate run does not exist")
    out = run_summary(r)
    out["row"] = r
    return out


def parse_systems(raw: str) -> list[str]:
    ids = [p for p in re.split(r"[,\s;]+", raw or "") if p]
    return list(dict.fromkeys(ids))[: caps.SIMULATION_MAX_SYSTEMS + 1]


def int_field(raw: str, field: str, default: int = 0) -> int:
    raw = (raw or "").strip()
    if not raw:
        return default
    if not (raw.isascii() and raw.isdigit() and len(raw) < 6):
        raise gate.GateError("bad_size", f"{field} must be a whole number")
    return int(raw)
