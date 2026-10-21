"""Optional adapter for the WP30 control catalogue and task list (WP31 hook, ADR D31).

Used for the ``controls`` section. It looks for ``supervisor.controls`` without importing it,
so a build without WP30 works and the section says "not built". With the package present and
``CONTROLS_ENABLED`` off the section says the feature is off and nothing is imported. Only with
the flag on it imports ``supervisor.controls.service`` and ``supervisor.tasks.service`` (the
WP30 packages export their services from these modules, not from the package) and calls read
methods only: ``ControlService.agent_compliance``, ``obligation_coverage``, ``uncovered_risks``
(kept to the risks this agent reaches) and ``TaskService.agent_summary`` (named fields only).
Controls the bank owns cannot be observed by the product and never read "working"; when any
are in scope the report says so, so the compliance figure is not read as "the bank is
non-compliant".
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from types import SimpleNamespace
from typing import Any

from supervisor.transparency.builder import Ctx, na, ok
from supervisor.transparency.model import MAX_ROWS

CONTROL_FIELDS = ("control_id", "title", "control_type", "implemented_by", "status", "reason")
# TaskService.agent_summary (WP30, checked on branch wp30-controls): the plain fields the report
# shows. ``counts`` (status -> n) is flattened to ``counts_<status>``; the task rows, the agent
# id and the sizing inputs are not copied.
TASK_FIELDS = (
    "stage",
    "generated",
    "level",
    "required_open",
    "required_total",
    "stage_done_bp",
    "overdue",
    "next_stage",
)


def present(name: str = "supervisor.controls") -> bool:
    """True when the package is in this build (found without importing it)."""
    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _service(module: str, cls: str) -> Any:
    """The service class of a WP30 module, or None when it is not there."""
    try:
        return getattr(importlib.import_module(module), cls)
    except (ImportError, AttributeError):
        return None


def task_fields(summary: Any) -> dict[str, Any]:
    """The named plain fields of ``TaskService.agent_summary``; no float, no nested data."""
    if not isinstance(summary, dict):
        return {}
    out: dict[str, Any] = {
        k: summary[k]
        for k in TASK_FIELDS
        if k in summary
        and (summary[k] is None or isinstance(summary[k], bool | int | str))
        and not isinstance(summary[k], float)
    }
    counts = summary.get("counts")
    if isinstance(counts, dict):
        for k, v in sorted(counts.items()):
            if isinstance(v, int) and not isinstance(v, bool):
                out[f"counts_{k}"] = v
    return out


def _agent_risk_ids(c: Ctx) -> set[str] | None:
    try:
        summ = c.facts.risk_summary(c.agent_id)
    except Exception:  # noqa: BLE001 - the risks section says why
        return None
    if summ is None:
        return None
    return {str(r["risk_id"]) for r in summ.get("risks") or []}


def collect(c: Ctx) -> dict[str, Any]:
    if not present():
        return na("not_built", "WP30")
    if not getattr(c.settings, "controls_enabled", False):
        return na("flag_off", "CONTROLS_ENABLED")
    control_cls = _service("supervisor.controls.service", "ControlService")
    if control_cls is None:
        return na("not_built", "WP30")
    src = c.facts.src
    adapters = SimpleNamespace(
        state=src.state, tables=src.tables, clock=src.clock, settings=c.settings
    )
    svc = control_cls.from_adapters(adapters)
    comp = svc.agent_compliance(c.agent_id)
    items = list(comp.get("controls") or [])
    controls = [
        {k: x.get(k) for k in CONTROL_FIELDS}
        | {"stale": bool(x.get("stale")), "owner": c.facts.mask(x.get("owner"), 60)}
        for x in items[:MAX_ROWS]
    ]
    coverage = [
        {
            "obligation": x["obligation"],
            "status": x["status"],
            "controls_n": len(x.get("controls") or []),
        }
        for x in svc.obligation_coverage(c.agent_id)[:MAX_ROWS]
    ]
    # uncovered_risks() lists every active risk of the register; the report counts those this
    # agent reaches (None while the register is off).
    mine = _agent_risk_ids(c)
    uncovered = None if mine is None else sum(1 for r in svc.uncovered_risks() if r in mine)
    data: dict[str, Any] = {
        "in_scope": int(comp.get("in_scope") or 0),
        "working": int(comp.get("working") or 0),
        "failing": int(comp.get("failing") or 0),
        "no_data": int(comp.get("no_data") or 0),
        "compliance_bp": comp.get("compliance_bp"),
        "product_in_scope": int(comp.get("product_in_scope") or 0),
        "product_working": int(comp.get("product_working") or 0),
        "product_bp": comp.get("product_bp"),
        "bank_in_scope": int(comp.get("bank_in_scope") or 0),
        "bank_note": int(comp.get("bank_in_scope") or 0) > 0,
        "controls": controls,
        "coverage": coverage,
        "more": max(0, len(items) - len(controls)),
        "uncovered_risks_n": uncovered,
    }
    task_cls = _service("supervisor.tasks.service", "TaskService")
    data["tasks"] = (
        task_fields(task_cls.from_adapters(adapters).agent_summary(c.agent_id)) if task_cls else {}
    )
    return ok(data, illustrative=True)
