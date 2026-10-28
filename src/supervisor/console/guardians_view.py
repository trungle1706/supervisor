"""Per-system guardian switches for the console (WP-S1, docs/guardian-bindings.md).

Two entry points, both read models (the switch itself posts to
``POST /console/systems/{id}/guardians/{slug}``, see ``governance/guardian_routes.py``):

* :func:`catalog_panel`: the Catalog page. A person picks an AI system; every capability card
  that maps to a bindable guardian feature shows a switch for that system. Only a person who holds
  ``systems.edit`` sees the button; the guardian floor shows a lock and the rule ids; a feature the
  instance has off shows as off in this instance (a binding cannot turn it on).
* :func:`system_panel`: the same rows for one system, for a Guardians tab on the system page. The
  tab is not part of this work package; the function is the hook.

With GUARDIAN_BINDINGS_ENABLED or GOVERNANCE_ENABLED off both return ``None`` and the pages are
as before.
"""

from __future__ import annotations

from typing import Any

from supervisor.core import rbac
from supervisor.core.errors import NotFoundError
from supervisor.governance.guardians import guardian_bindings_on

# Catalog card key -> bindable feature slugs (the card name is the slug where they match).
CARD_SLUGS: dict[str, tuple[str, ...]] = {
    "dlp_vn": ("dlp_vn",),
    "injection_regex": ("injection_regex",),
    "injection_classifier": ("injection_classifier",),
    "judge_advisory": ("judge_advisory",),
    "document_intake": ("document_intake",),  # WP-D1
    "judge_moderation": ("judge_moderation",),  # WP-D4
    "guard_model": ("guard_model",),  # WP-D3
    "session_monitor": ("session_monitor",),
    "judge_tiers": ("judge_t2_sample", "judge_challenger"),
    "drift": ("monitor_drift",),
    "fairness": ("monitor_fairness",),
    "quality": ("monitor_quality",),
    "multiagent": ("monitor_split_payment",),
}
# Cards whose feature is never bindable: shown with a lock and a line, no switch.
NEVER_CARDS: tuple[str, ...] = ("policy_rules",)


def _can_edit(me: Any) -> bool:
    return getattr(me, "kind", "") == "user" and rbac.allowed(me.roles, "systems.edit")


def _scope(ctx: Any, me: Any) -> Any:
    return ctx.systems.scope_for(me)


def system_panel(ctx: Any, me: Any, system_id: str) -> dict[str, Any] | None:
    """Rows of one system for a Guardians tab: ``{system_id, rows, can_edit}``, or None when the
    feature is off. NotFoundError for a system outside the caller's scope."""
    if not guardian_bindings_on(ctx.settings):
        return None
    if system_id not in _scope(ctx, me):
        raise NotFoundError(f"AI system {system_id} does not exist")
    data = ctx.guardians.get(system_id)
    return {
        "system_id": system_id,
        "rows": data["guardians"],
        "can_edit": _can_edit(me),
        "never_bindable": data["never_bindable"],
    }


def catalog_panel(ctx: Any, me: Any, system_id: str | None) -> dict[str, Any] | None:
    """Data for the Catalog page: the systems the caller may pick, the selected system, and the
    switch rows by card key. None when the feature is off."""
    if not guardian_bindings_on(ctx.settings):
        return None
    scope = _scope(ctx, me)
    systems = [
        {"system_id": s["system_id"], "name": s["name"]}
        for s in ctx.systems.list_systems(scope, {})
        if s["status"] != "archived"
    ]
    out: dict[str, Any] = {
        "systems": systems,
        "system": None,
        "by_card": {},
        "can_edit": _can_edit(me),
        "never_cards": NEVER_CARDS,
    }
    if not system_id:
        return out
    if system_id not in scope:
        raise NotFoundError(f"AI system {system_id} does not exist")
    rows = {g["slug"]: g for g in ctx.guardians.get(system_id)["guardians"]}
    out["system"] = next((s for s in systems if s["system_id"] == system_id), None) or {
        "system_id": system_id,
        "name": system_id,
    }
    out["by_card"] = {
        card: [rows[s] for s in slugs if s in rows] for card, slugs in CARD_SLUGS.items()
    }
    out["state_actions"] = bool(getattr(ctx.settings, "console_state_actions", False))
    if out["state_actions"]:  # WP-P2 (phase 8): the requests that wait for a second person
        out["pending_off"] = ctx.guardians.pending_off(system_id)
        out["me_id"] = getattr(me, "user_id", "")
        out["can_approve"] = getattr(me, "kind", "") == "user" and rbac.allowed(
            me.roles, "systems.approve"
        )
    return out
