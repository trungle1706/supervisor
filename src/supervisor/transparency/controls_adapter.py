"""Optional adapter for the WP30 control catalogue and task list (WP31 hook, ADR D31).

Used for the ``controls`` section. It imports ``supervisor.controls`` and ``supervisor.tasks``
lazily, so a build without WP30 works and the section says "not built". With the package
present and ``CONTROLS_ENABLED`` off the section says the feature is off. The adapter only
calls read methods: ``ControlService.agent_compliance``, ``obligation_coverage``,
``uncovered_risks`` and ``TaskService.agent_summary``. Controls the bank owns cannot be observed
by the product and never read "working"; when any are in scope the report says so, so the
compliance figure is not read as "the bank is non-compliant".
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

from supervisor.transparency.builder import Ctx, na, ok
from supervisor.transparency.model import MAX_ROWS

CONTROL_FIELDS = ("control_id", "title", "control_type", "implemented_by", "status", "reason")


def _scalars(d: Any) -> dict[str, Any]:
    """Top-level plain values of a dict (int, bool, text); no float, no nested data."""
    if not isinstance(d, dict):
        return {}
    return {
        str(k): v
        for k, v in d.items()
        if isinstance(v, bool | int | str) and not isinstance(v, float)
    }


def collect(c: Ctx) -> dict[str, Any]:
    try:
        ctl = importlib.import_module("supervisor.controls")
    except ImportError:
        return na("not_built", "WP30")
    if not getattr(c.settings, "controls_enabled", False):
        return na("flag_off", "CONTROLS_ENABLED")
    src = c.facts.src
    adapters = SimpleNamespace(
        state=src.state, tables=src.tables, clock=src.clock, settings=c.settings
    )
    svc = ctl.ControlService.from_adapters(adapters)
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
    uncovered = list(svc.uncovered_risks())
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
        "uncovered_risks_n": len(uncovered),
    }
    try:
        tasks = importlib.import_module("supervisor.tasks")
        data["tasks"] = _scalars(
            tasks.TaskService.from_adapters(adapters).agent_summary(c.agent_id)
        )
    except ImportError:
        data["tasks"] = {}
    return ok(data, illustrative=True)
