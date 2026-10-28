"""The Risk assessment tab of the system page and its buttons (WP-C2, ``RISK_DIMENSIONS``).

The rules are in ``governance/risk_dimensions.py``; this module is the console side: the view
model (eight rows with status pill, owner team, assessed by, evidence pointers, threshold, the
rule proposal and the risk register lines of the matching categories), what a person may press and
the audit note of each button (fixed text and counts; a typed reason is never written to
``console_action``, only the first 12 characters of its SHA-256).

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import PermissionDenied
from supervisor.core import rbac
from supervisor.governance import risk_dimensions as rd

TAB = "riskdim"


def person(me: Any) -> str:
    if getattr(me, "kind", "") != "user":
        raise PermissionDenied("this action needs a signed-in person")
    return str(me.user_id)


def is_on(ctx: Any) -> bool:
    return rd.tab_enabled(ctx.settings)


def ensure_on(ctx: Any) -> None:
    rd.ensure_on(ctx.settings)


def env_of(ctx: Any) -> rd.Env:
    return rd.Env.from_console(ctx)


def may_edit(me: Any, system: Mapping[str, Any]) -> bool:
    user = getattr(me, "kind", "") == "user"
    return bool(
        user and rbac.allowed(me.roles, "systems.edit") and system.get("status") != "archived"
    )


def may_waive(me: Any, system: Mapping[str, Any]) -> bool:
    user = getattr(me, "kind", "") == "user"
    return bool(
        user and rbac.allowed(me.roles, "systems.approve") and system.get("status") != "archived"
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def audit_note(out: Mapping[str, Any], typed: str | None = None) -> str:
    """``risk_dim model not_started>pass n=2`` and ``text_sha=<12 hex>`` for typed text."""
    note = f"risk_dim {out['dimension_id']} {out['from']}>{out['to']} n={out['evidence_n']}"
    if typed:
        note += " text_sha=" + _sha(typed)
    return note


def _lines(ctx: Any, system: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Risk register lines of the system by category (empty when the register is off)."""
    if not getattr(ctx.settings, "risk_register_enabled", False):
        return {}
    try:
        from supervisor.console.systems_tabs import risks_tab

        data = risks_tab(ctx, system)
    except Exception:  # noqa: BLE001 - the register never breaks this tab
        return {}
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in data.get("rk_rows") or []:
        if r.get("status") == "retired":
            continue
        by_cat.setdefault(str(r.get("category")), []).append(
            {
                "risk_id": r["risk_id"],
                "title": str(r.get("title") or "")[:120],
                "band": r.get("residual_band") or "",
            }
        )
    return by_cat


def tab_data(ctx: Any, me: Any, system: Mapping[str, Any]) -> dict[str, Any]:
    data = rd.view(env_of(ctx), system)
    by_cat = _lines(ctx, system)
    for row in data["dimensions"]:
        seen: dict[str, dict[str, Any]] = {}
        for cat in row["risk_categories"]:
            for line in by_cat.get(cat, []):
                seen.setdefault(line["risk_id"], {**line, "category": cat})
        row["risk_lines"] = list(seen.values())
    from supervisor.console import systems_orch  # WP-F4: the Run assessment panel

    return {
        **systems_orch.panel_data(ctx, me, system),
        "rd_on": True,
        "rd_rows": data["dimensions"],
        "rd_counts": data["counts"],
        "rd_banner": data["banner"],
        "rd_illustrative": data["illustrative"],
        "rd_statuses": rd.SETTABLE,
        "rd_all_statuses": list(rd.STATUSES),
        "rd_can_edit": may_edit(me, system),
        "rd_can_waive": may_waive(me, system),
        "rd_is_owner": rd.is_owner(system, str(getattr(me, "user_id", ""))),
        "rd_min_reason": rd.MIN_REASON,
        "rd_register": bool(getattr(ctx.settings, "risk_register_enabled", False)),
    }


def open_count(counts: Mapping[str, int]) -> int:
    """Types that still need work: not started, in progress or failed."""
    return int(counts.get("not_started", 0) + counts.get("in_progress", 0) + counts.get("fail", 0))


# ------------------------------------------------------------------------------ the buttons


def do_set(
    ctx: Any, me: Any, system: Mapping[str, Any], dim_id: str, form: Mapping[str, str]
) -> tuple[dict[str, Any], str]:
    ensure_on(ctx)
    actor = person(me)
    out = rd.set_status(
        env_of(ctx),
        actor,
        system,
        dim_id,
        form.get("status"),
        evidence=form.get("evidence"),
        note=form.get("note"),
    )
    return out, audit_note(out, form.get("note"))


def do_confirm(
    ctx: Any, me: Any, system: Mapping[str, Any], dim_id: str
) -> tuple[dict[str, Any], str]:
    ensure_on(ctx)
    out = rd.confirm_proposal(env_of(ctx), person(me), system, dim_id)
    return out, audit_note(out) + " proposal=1"


def do_waive(
    ctx: Any, me: Any, system: Mapping[str, Any], dim_id: str, form: Mapping[str, str]
) -> tuple[dict[str, Any], str]:
    ensure_on(ctx)
    out = rd.waive(env_of(ctx), person(me), system, dim_id, form.get("reason"))
    return out, audit_note(out, form.get("reason"))
