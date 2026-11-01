"""Read models of the inventory run pages (W4, flag ``FACTORY_INVENTORY_RUN``).

The routes (``factory_inventory_routes.py``) stay thin. Everything on the pages comes from the
files of a run (``factory.inventory_run``); no table is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.console import factory_view as fv
from supervisor.console.context import ConsoleContext
from supervisor.factory import helpers
from supervisor.factory import inventory_run as inv
from supervisor.factory.store import FactoryError

PAGE_SIZE = 25
TOP_GAPS = 5
TOP_TEAMS = 10
BUCKETS = ("needs_action", "open", "clear", "errors")
CUSTOMER = ("", "yes", "no")
TOP_RISKS = 8
KEY_LABELS = (
    "money_tool_no_gate",
    "declared_control_mismatch",
    "personal_data_fields",
    "personal_data_mismatch",
    "pii_export_tool",
    "model_unknown",
    "no_tracing",
    "hardcoded_secret",
    "external_endpoint",
    "risk_level_mismatch",
    "tests_missing",
    "tests_failed",
)
CELL_GLYPH = {
    "fail": "✕",
    "question": "?",
    "pass": "✓",
    "not_applicable": "–",
    "none": "·",
    "error": "!",
}


def env(ctx: ConsoleContext) -> inv.InvEnv:
    return inv.InvEnv.from_console(
        ctx, getattr(ctx, "gate_chat", None), fv.tool_registry(), fv.group_registry()
    )


def on(ctx: ConsoleContext) -> bool:
    return inv.enabled(ctx.settings)


def summary(run: Mapping[str, Any]) -> dict[str, Any]:
    """One row of the run list."""
    total = int(run.get("total", 0))
    done = int(run.get("done", 0))
    return {
        **run,
        "active": run["status"] in inv.ACTIVE,
        "percent": (100 * done // total) if total else 0,
    }


def list_data(ctx: ConsoleContext, me: Any, agent_id: str) -> dict[str, Any]:
    row = fv.load_row(ctx, agent_id)
    versions = fv.store(ctx).versions(agent_id)
    runs = [summary(r) for r in inv.list_runs(ctx.settings.data_dir, agent_id)]
    return {
        "agent": fv.card(ctx, me, row),
        "versions": [
            {"version": v["version"], "state": v["state"]}
            for v in versions
            if v["state"] != "retired"
        ],
        "default_version": row["version"],
        "runs": runs,
        "running": any(r["active"] for r in runs),
        "can_run": fv.may_edit(me, row["owner_group"]),
        "model_ready": helpers.model_ready(ctx.settings)
        or getattr(ctx, "gate_chat", None) is not None,
        "parallel": inv.parallel_of(ctx.settings),
        "max": inv.max_of(ctx.settings),
    }


def _int(raw: str, field: str, default: int = 1) -> int:
    raw = (raw or "").strip()
    if not raw:
        return default
    if not (raw.isascii() and raw.isdigit() and len(raw) < 6):
        raise FactoryError("bad_page", f"{field} must be a whole number")
    return max(1, int(raw))


def parse_filters(q: Mapping[str, str]) -> dict[str, str]:
    """The filter fields of the dashboard (query string). A bad value is HTTP 400."""
    f = {
        "team": (q.get("team") or "")[:120],
        "level": (q.get("level") or "")[:20],
        "customer": (q.get("customer") or "")[:3],
        "q": (q.get("q") or "")[:80],
        "key": (q.get("key") or "")[:64],
        "bucket": (q.get("bucket") or "")[:20],
        "kstatus": (q.get("kstatus") or "")[:10],
    }
    if f["kstatus"] not in ("", "fail", "open"):
        raise FactoryError("bad_filter", "status must be fail or open")
    if f["level"] and f["level"] not in inv.LEVELS:
        raise FactoryError("bad_filter", f"level must be one of {', '.join(inv.LEVELS)}")
    if f["customer"] not in CUSTOMER:
        raise FactoryError("bad_filter", "customer must be yes or no")
    if f["bucket"] and f["bucket"] not in BUCKETS:
        raise FactoryError("bad_filter", f"result must be one of {', '.join(BUCKETS)}")
    return f


def load_run(ctx: ConsoleContext, agent_id: str, run_id: str) -> dict[str, Any]:
    fv.load_row(ctx, agent_id)  # 400 for an unknown agent
    try:
        return inv.read_run(ctx.settings.data_dir, agent_id, run_id)
    except inv.InventoryError as exc:
        raise FactoryError(exc.code, str(exc).partition(": ")[2]) from None


def run_data(
    ctx: ConsoleContext, me: Any, agent_id: str, run_id: str, q: Mapping[str, str]
) -> dict[str, Any]:
    filters = parse_filters(q)
    page = _int(q.get("page", ""), "page")
    run = load_run(ctx, agent_id, run_id)
    row = fv.load_row(ctx, agent_id)
    d = inv.run_dir(ctx.settings.data_dir, agent_id, run_id)
    out: dict[str, Any] = {
        "agent": fv.card(ctx, me, row),
        "run": summary(run),
        "can_cancel": fv.may_edit(me, row["owner_group"]),
        "filters": filters,
        "bucket_names": BUCKETS,
        "levels": inv.LEVELS,
        "key_labels": KEY_LABELS,
    }
    if run["status"] in inv.ACTIVE:
        return out
    rows = inv.read_rows(d)
    agg = inv.aggregate(run, rows)
    checklist = run.get("checklist") or []
    shown = inv.filter_rows(rows, checklist=checklist, **filters)
    pages = max(1, -(-len(shown) // PAGE_SIZE))
    page = min(page, pages)
    window = shown[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    ids = [c["id"] for c in checklist]
    heat = [
        {
            **r,
            "exec_fail": inv.exec_fail_of(r),
            "cells": [
                ((r.get("verdicts") or {}).get(i) or "none")
                if r.get("status") == "assessed"
                else "error"
                for i in ids
            ],
            "fails": [i for i in ids if (r.get("verdicts") or {}).get(i) == "fail"],
        }
        for r in window
    ]
    out.update(
        {
            "agg": agg,
            "rows": heat,
            "shown_n": len(shown),
            "total_n": len(rows),
            "page": page,
            "pages": pages,
            "checklist": checklist,
            "skipped_n": sum(int(v) for v in (run.get("skipped") or {}).values()),
            "glyph": CELL_GLYPH,
            "risk_limit": 99 if q.get("risks") == "all" else TOP_RISKS,
            "gap_limit": 99 if q.get("gaps") == "all" else TOP_GAPS,
            "top_teams": TOP_TEAMS,
            "page_size": PAGE_SIZE,
            "query": query_string(filters),
        }
    )
    return out


def query_string(filters: Mapping[str, str], **extra: str) -> str:
    """The filter fields as a query string (``&amp;``-safe in a template after ``|e``)."""
    from urllib.parse import urlencode

    merged = {**filters, **extra}
    return urlencode({k: v for k, v in merged.items() if v})


def system_data(
    ctx: ConsoleContext, me: Any, agent_id: str, run_id: str, system_id: str
) -> dict[str, Any]:
    run = load_run(ctx, agent_id, run_id)
    if run["status"] in inv.ACTIVE:
        raise FactoryError("not_done", "the run has not finished")
    rows = inv.read_rows(inv.run_dir(ctx.settings.data_dir, agent_id, run_id))
    row = next((r for r in rows if r.get("system_id") == system_id), None)
    if row is None:
        raise FactoryError("not_found", "this system is not in the run")
    detail = inv.system_detail(ctx.settings.data_dir, run, row)
    questions = {c["id"]: c["question"] for c in run.get("checklist") or []}
    findings = [
        {**f, "question": questions.get(f["checklist_id"], ""), "texts": detail["texts"]}
        for f in (detail["report"] or {}).get("findings") or []
    ]
    findings.sort(
        key=lambda f: inv.VERDICTS.index(f["verdict"]) if f["verdict"] in inv.VERDICTS else 9
    )
    return {
        "agent": fv.card(ctx, me, fv.load_row(ctx, agent_id)),
        "run": summary(run),
        "row": row,
        "exec": detail["exec"],
        "findings": findings,
        "texts": detail["texts"],
        "glyph": CELL_GLYPH,
    }
