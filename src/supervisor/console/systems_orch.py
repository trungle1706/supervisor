"""The Run assessment button and the run panel of the Risk assessment tab (WP-F4,
``ONBOARD_ORCHESTRATOR``). The rules are in ``onboard/orchestrator.py``; this module is the console
side: the view model of the panel and what a person may press. Not legal advice."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.console.authz import may_system, person
from supervisor.console.listing import ListingError
from supervisor.governance import risk_dimensions as rd
from supervisor.onboard import executive
from supervisor.onboard import orchestrator as orch


def is_on(ctx: Any) -> bool:
    return orch.enabled(ctx.settings)


def may_run(me: Any, system: Mapping[str, Any]) -> bool:
    return may_system(me, system, "systems.edit")


def _last_status_day(ctx: Any, system_id: str) -> str | None:
    """UI-063: with no assessment run, the day of the last status a person or a job set on a risk
    type (not_started rows do not count). None when no type has a status."""
    try:
        rows = ctx.state.query("risk_dimension_status", {"system_id": system_id})
    except Exception:  # noqa: BLE001 - a convenience line, never a page failure
        return None
    days = [
        str(r.get("updated_at") or "")[:10]
        for r in rows
        if r.get("status") not in (None, "not_started") and r.get("updated_at")
    ]
    return max(days) if days else None


def panel_data(ctx: Any, me: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    """Template variables of ``_system_orch_panel.html``; only ``orch_on`` (false) when off."""
    if not is_on(ctx):
        return {"orch_on": False}
    run = orch.latest(ctx, str(system["system_id"]))
    labels = {d.id: (d.label_en, d.label_vi) for d in rd.load_config().dimensions}
    view = run.to_dict() if run else None
    exec_on = executive.enabled(ctx.settings)
    return {
        "orch_on": True,
        "orch_run": view,
        "orch_labels": labels,
        "orch_exec_on": exec_on,
        "orch_exec_top": exec_tops(ctx, system, run) if (exec_on and run) else {},
        "orch_progress": progress(ctx, run) if run else None,
        "orch_can_run": may_run(me, system) and not (run and run.running),
        "orch_banner": orch.BANNER,
        "orch_set_on": None if run else _last_status_day(ctx, str(system["system_id"])),
    }


# The state of one risk type in the progress bar: q (waits), run, ok, bad (a person or an error).
_STEP = {
    "queued": "q",
    "running": "run",
    "done": "ok",
    "needs_person": "bad",
    "budget_exceeded": "bad",
    "failed": "bad",
}
_FINISHED = ("done", "needs_person", "budget_exceeded", "failed", "skipped")


def _seconds(start: str | None, end: str | None, now: dt.datetime) -> int | None:
    try:
        t0 = dt.datetime.fromisoformat(str(start))
        t1 = dt.datetime.fromisoformat(str(end)) if end else now
    except ValueError:
        return None
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=dt.UTC)
    if t1.tzinfo is None:
        t1 = t1.replace(tzinfo=dt.UTC)
    return max(0, int((t1 - t0).total_seconds()))


def progress(ctx: Any, run: orch.OrchestratorRun) -> dict[str, Any]:
    """The live progress bar of a run: one step per applicable risk type in run order, how many
    finished, the type that runs now and the seconds since the start (to the end when done)."""
    steps = [
        {"dimension_id": str(i["dimension_id"]), "kind": _STEP.get(str(i["status"]), "na"),
         "status": str(i["status"])}
        for i in run.items
        if i.get("applies")
    ]  # fmt: skip
    finished = sum(1 for i in run.items if i.get("applies") and i["status"] in _FINISHED)
    now = ctx.clock.now()
    return {
        "steps": steps,
        "done": finished,
        "n": len(steps),
        "pct": 100 if not steps else finished * 100 // len(steps),
        "current": next((s["dimension_id"] for s in steps if s["kind"] == "run"), None),
        "not_applicable": len(run.items) - len(steps),
        "seconds": _seconds(run.started_at, run.finished_at, now),
    }


_VERDICT_ORDER = {v: k for k, v in enumerate(orch.VERDICT_RANK)}
TOP_POINTS = 3
BOTTOM_ITEMS = 3  # the executive bottom line shows the top three findings over all risk types
_SEV = {"high": 0, "medium": 1, "low": 2}
_ST = {"fail": 0, "open": 1, "pass": 2}


def _report(ctx: Any, run: orch.OrchestratorRun, dim: str) -> dict[str, Any] | None:
    path = orch.report_path(ctx.settings, run.system_id, run.attempt_n, dim)
    if path is None:
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def exec_docs(
    ctx: Any,
    system: Mapping[str, Any],
    run: orch.OrchestratorRun,
    reports: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> dict[str, dict[str, Any]]:
    """ORCH_EXEC_FINDINGS: the executive findings of each risk type of a run: the stored
    ``<type>.exec.json``, else (run ended) the rule-made findings of the stored report built on the
    fly. Not stored. A type with no report has none. Never raises."""
    out: dict[str, dict[str, Any]] = {}
    out_dir = orch.report_dir(ctx.settings, run.system_id, run.attempt_n)
    facts: Any = False  # not loaded yet
    for item in run.items:
        dim = str(item["dimension_id"])
        if not item.get("report_ref"):
            continue
        doc = executive.read(out_dir, dim)
        if doc is None and not run.running:
            try:
                rep = (reports or {}).get(dim) or _report(ctx, run, dim)
                if rep is not None:
                    if facts is False:
                        facts = orch.facts_for(ctx, run.system_id)
                    doc = executive.build(dim, rep, facts, system)
            except Exception:  # noqa: BLE001 - the page shows the raw findings instead
                doc = None
        if doc is not None:
            out[dim] = doc
    return out


def exec_tops(ctx: Any, system: Mapping[str, Any], run: orch.OrchestratorRun) -> dict[str, Any]:
    """The top headline and rating of each risk type, for the Result column of the table."""
    tops: dict[str, Any] = {}
    for dim, doc in exec_docs(ctx, system, run).items():
        first = doc["items"][0] if doc["items"] else None
        tops[dim] = {
            "rating": doc["rating"],
            "headline": first["headline"] if first else doc["bottom_line"],
        }
    return tops


def exec_bottom(
    docs: Mapping[str, Mapping[str, Any]], order: Sequence[str]
) -> list[dict[str, Any]]:
    """The top findings over all risk types: one line per key (the same finding in several types is
    shown once with all its types), failed before open, then high before low, then in more types."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for dim in order:
        for it in (docs.get(dim) or {}).get("items") or []:
            # a finding made from the code scan reads the same in every type; a test or
            # dependency finding is about one type, so it is never merged
            same = (it["key"], it["headline"]["en"] if it["key"] in executive.FACT_KEYS else dim)
            cur = merged.get(same)
            if cur is None:
                merged[same] = {**it, "dims": [dim], "_n": len(merged)}
            else:
                cur["dims"].append(dim)
    ranked = sorted(
        merged.values(),
        key=lambda m: (_ST[m["status"]], _SEV[m["severity"]], -len(m["dims"]), m["_n"]),
    )
    return [{k: v for k, v in m.items() if k != "_n"} for m in ranked[:BOTTOM_ITEMS]]


def _kind(item: Mapping[str, Any]) -> str:
    k = str(item.get("agent_kind") or "")
    if k in ("rule", "live", "draft"):
        return k
    return "rule" if str(item.get("agent") or "rule") == "rule" else "live"


def brief_view(
    ctx: Any, system: Mapping[str, Any], run_id: str, open_dim: str | None = None
) -> dict[str, Any]:
    """The brief report of one run: the totals, the points a person must look at (fail first, then
    the open questions) and one block per risk type with its top findings. ``open_dim`` opens the
    block of that type. Reads the stored ``assessment_report_v1`` files; changes nothing."""
    run = orch.get(ctx, run_id) if len(run_id) <= 64 else None
    if run is None or run.system_id != str(system["system_id"]):
        raise ListingError(f"assessment run {run_id[:64]} does not exist")
    labels = {d.id: (d.label_en, d.label_vi) for d in rd.load_config().dimensions}
    totals = {"passed": 0, "failed": 0, "questions": 0, "not_applicable": 0, "total": 0}
    types: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    reports = {
        str(i["dimension_id"]): (
            _report(ctx, run, str(i["dimension_id"])) if i.get("report_ref") else None
        )
        for i in run.items
    }
    exec_on = executive.enabled(ctx.settings)
    docs = exec_docs(ctx, system, run, reports) if exec_on else {}
    for item in run.items:
        dim = str(item["dimension_id"])
        rep = reports[dim]
        findings = sorted(
            (rep or {}).get("findings") or [],
            key=lambda f: _VERDICT_ORDER.get(str(f.get("verdict")), 9),
        )
        summary = dict((rep or {}).get("summary") or {})
        for k in totals:
            totals[k] += int(summary.get(k) or 0)
        for f in findings:
            if f.get("verdict") == "fail":
                points.append({"dimension_id": dim, "finding": f})
        types.append(
            {
                "dimension_id": dim,
                "applies": bool(item.get("applies")),
                "reason": str(item.get("reason") or ""),
                "status": str(item["status"]),
                "verdict": str(item.get("verdict") or ""),
                "needs_person": bool(item.get("needs_person")),
                "stop_point": str(item.get("stop_point") or ""),
                "note": str(item.get("note") or ""),
                "agent": str(item.get("agent") or ""),
                "model_id": str((rep or {}).get("model_id") or ""),
                "seconds": int(item.get("ms_used") or 0) // 1000,
                "ms": int(item.get("ms_used") or 0),
                "tokens": int(item.get("tokens_used") or 0),
                "summary": summary,
                "top": [f for f in findings if f.get("verdict") != "not_applicable"][:TOP_POINTS],
                "findings": findings,
                "has_report": rep is not None,
                "open": open_dim == dim,
                "agent_kind": _kind(item),
                "exec": docs.get(dim),
            }
        )
    applicable = [t for t in types if t["applies"]]
    return {
        "brief_run": run.to_dict(),
        "brief_types": types,
        "brief_labels": labels,
        "brief_totals": totals,
        "brief_points": points,
        "brief_n": len(types),
        "brief_applicable": len(applicable),
        "brief_reported": sum(1 for t in applicable if t["has_report"]),
        "brief_need": sum(1 for t in applicable if t["needs_person"]),
        "brief_problems": sum(
            1 for t in applicable if t["status"] in ("budget_exceeded", "failed")
        ),
        "brief_outcome": str(run.plan.get("outcome") or ""),
        "brief_seconds": _seconds(run.started_at, run.finished_at, ctx.clock.now()),
        "brief_banner": orch.BANNER,
        "brief_exec_on": exec_on and bool(docs),
        "brief_bottom": exec_bottom(docs, [t["dimension_id"] for t in types if t["applies"]]),
    }


def do_start(ctx: Any, me: Any, system: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    orch.ensure_on(ctx.settings)
    from supervisor.factory import catalog as factory_catalog  # WP-F3: live factory agents

    run = orch.start(
        ctx, str(system["system_id"]), person(me), catalog=factory_catalog.for_console(ctx)
    )
    return run.to_dict(), f"orchestrate attempt={run.attempt_n} plan_sha={run.plan_hash[:12]}"


def ensure_on(ctx: Any) -> None:
    orch.ensure_on(ctx.settings)
