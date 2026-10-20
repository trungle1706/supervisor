"""Transparency page (WP31): agents with the latest report per variant, a row drawer with the
sections, a generate button (reviewer, admin) and the Transparency tab of the Agent page.

Read model over ``TransparencyService`` (``ctx.transparency``). The drawer shows the latest
signed report, or a PREVIEW of the current facts when none is signed yet. Generating writes
files, rows and a chain record through the audited route; nothing is written here."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from supervisor.console.listing import ListingError
from supervisor.core import rbac
from supervisor.core.errors import NotFoundError, SupervisorError
from supervisor.transparency import render
from supervisor.transparency.model import (
    VARIANTS,
    TransparencyError,
    check_agent,
    check_lang,
    check_variant,
)


def can_generate(me: Any) -> bool:
    return rbac.allowed(getattr(me, "roles", ()), "transparency.generate")


def list_view(ctx: Any, me: Any) -> dict[str, Any]:
    rows = ctx.transparency.overview()
    return {
        "rows": rows,
        "variants": VARIANTS,
        "can_generate": can_generate(me),
        "pdf_ready": _pdf_ready(ctx),
    }


def _pdf_ready(ctx: Any) -> bool:
    try:
        import fpdf  # noqa: F401
    except ImportError:
        return False
    from supervisor.evidence.casefile.render_pdf import find_font

    return find_font(getattr(ctx.settings, "casefile_pdf_font", None)) is not None


def drawer_view(ctx: Any, agent_id: str, variant: str, lang: str) -> dict[str, Any]:
    try:
        check_agent(agent_id)
        check_variant(variant)
        check_lang(lang)
    except TransparencyError as exc:
        raise ListingError(str(exc)) from None
    try:
        report, info = ctx.transparency.report(agent_id, variant)
    except NotFoundError as exc:
        raise ListingError(str(exc)) from None
    except SupervisorError as exc:
        raise ListingError(str(exc)) from None
    doc = render.document(report, lang)
    avail = sum(1 for s in report["sections"].values() if s["available"])
    return {
        "agent_id": agent_id,
        "variant": variant,
        "variants": VARIANTS,
        "info": info,
        "doc": doc,
        "avail": avail,
        "total": len(report["sections"]),
        "json_text": json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2),
    }


def agent_tab(ctx: Any, me: Any, agent_id: str) -> dict[str, Any]:
    """Data of the Transparency tab on the Agent page."""
    if not ctx.settings.transparency_enabled:
        return {"tp_off": True}
    per = {}
    for v in VARIANTS:
        row = ctx.transparency.latest(agent_id, v)
        per[v] = (
            {
                "version": int(row["version"]),
                "generated_at": row["generated_at"],
                "verify_state": row["verify_state"],
                "has_pdf": row.get("pdf_hash") is not None,
            }
            if row
            else None
        )
    return {
        "tp_off": False,
        "tp": per,
        "tp_variants": VARIANTS,
        "tp_page": bool(ctx.settings.console_transparency_enabled),
        "tp_can_generate": can_generate(me),
    }


def check_generate_input(data: Mapping[str, str]) -> tuple[str, ...]:
    """Variants from the form: all three unless one is named."""
    v = (data.get("variant") or "").strip()
    if not v:
        return VARIANTS
    return (check_variant(v),)
