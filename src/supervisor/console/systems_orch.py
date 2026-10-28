"""The Run assessment button and the run panel of the Risk assessment tab (WP-F4,
``ONBOARD_ORCHESTRATOR``). The rules are in ``onboard/orchestrator.py``; this module is the console
side: the view model of the panel and what a person may press. Not legal advice."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import PermissionDenied
from supervisor.core import rbac
from supervisor.governance import risk_dimensions as rd
from supervisor.onboard import orchestrator as orch


def is_on(ctx: Any) -> bool:
    return orch.enabled(ctx.settings)


def person(me: Any) -> str:
    if getattr(me, "kind", "") != "user":
        raise PermissionDenied("this action needs a signed-in person")
    return str(me.user_id)


def may_run(me: Any, system: Mapping[str, Any]) -> bool:
    user = getattr(me, "kind", "") == "user"
    return bool(
        user and rbac.allowed(me.roles, "systems.edit") and system.get("status") != "archived"
    )


def panel_data(ctx: Any, me: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    """Template variables of ``_system_orch_panel.html``; only ``orch_on`` (false) when off."""
    if not is_on(ctx):
        return {"orch_on": False}
    run = orch.latest(ctx, str(system["system_id"]))
    labels = {d.id: (d.label_en, d.label_vi) for d in rd.load_config().dimensions}
    view = run.to_dict() if run else None
    return {
        "orch_on": True,
        "orch_run": view,
        "orch_labels": labels,
        "orch_can_run": may_run(me, system) and not (run and run.running),
        "orch_banner": orch.BANNER,
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
