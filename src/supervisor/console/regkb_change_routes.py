"""Change to re-evaluation: the changes page, the diff and the Apply change action (WP-W2,
REGKB_CHANGE_LOOP, docs/regulations.md "Change to re-evaluation (WP-W2)").

The routers are always mounted; with the flag off (or LAWAGENT_ENABLED / GOVERNANCE_ENABLED off)
every route answers HTTP 400 ``change_loop_off`` and nothing is read or written.

JSON API:

* ``GET  /v1/regkb/changes``                     (regkb.view) pending items and change rows
* ``GET  /v1/regkb/changes/{sha}/{instrument}``  (regkb.view) the diff report and the state
* ``POST /v1/regkb/changes/{sha}/{instrument}/diff``           (regkb.confirm) run the diff mode;
  optional JSON ``{"incoming": "<instrument>/<date>/<file>.txt"}``
* ``POST /v1/regkb/changes/{sha}/{instrument}/apply``          (regkb.confirm) write the override

Console: ``/console/regkb/changes`` (list) and ``/console/regkb/changes/{sha}/{instrument}`` (old
and new text side by side, the drafted duties with Confirm and Drop as on the drafts page, the
affected obligations, and **Apply change** behind a confirmation tick). The actor is logged; a
second person is not required. Not legal advice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console import regkb_view
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.intake_routes import _same_site
from supervisor.console.routes import _call, audited, form_or_plain, render
from supervisor.core import rbac
from supervisor.core.canonical import format_ts
from supervisor.regkb import change
from supervisor.regkb.lawagent import split_articles

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
MAX_ROWS = 200
MAX_BODY = 8192


def _actor(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("this step needs a signed-in person")
    return str(me.user_id)


def _plain(row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in row.items():
        if k == "row_version":
            continue
        out[k] = format_ts(v) if hasattr(v, "isoformat") and hasattr(v, "tzinfo") else v
    return out


def list_data(ctx: ConsoleContext) -> dict[str, Any]:
    change.require_on(ctx.settings)
    items = change.pending_items(ctx.settings.data_dir, ctx.state)
    return {
        "items": [{**i, "change": _plain(i["change"]) if i["change"] else None} for i in items][
            :MAX_ROWS
        ],
        "rows": [_plain(r) for r in change.list_rows(ctx.state)][:MAX_ROWS],
        "banner": change.BANNER,
    }


def detail_data(ctx: ConsoleContext, me: AuthPrincipal, sha: str, instrument_id: str) -> dict:
    change.require_on(ctx.settings)
    change.check_ids(sha, instrument_id)
    row = change.get_row(ctx.state, sha, instrument_id)
    report = change.read_report(ctx.settings.data_dir, sha, instrument_id)
    out_dir = change.changes_dir(ctx.settings.data_dir, sha, instrument_id)
    try:
        articles = {
            a.number: a
            for a in split_articles((out_dir / "incoming.txt").read_text(encoding="utf-8"))
        }
    except OSError:
        articles = {}
    drafts = [
        {**regkb_view._item(d, articles), "change_ref": d["change_ref"]}  # noqa: SLF001
        for d in change.linked_drafts(ctx.state, row["change_id"] if row else "")
    ]
    return {
        "sha": sha,
        "instrument": instrument_id,
        "row": _plain(row) if row else None,
        "report": report,
        "pairs": change.side_by_side(ctx.settings.data_dir, sha, instrument_id, report),
        "drafts": drafts,
        "pending_drafts": sum(1 for d in drafts if d["status"] == "draft"),
        "confirmed_drafts": sum(1 for d in drafts if d["status"] == "confirmed"),
        "applied": bool(row and row["status"] == "applied"),
        "can_confirm": rbac.allowed(me.roles, "regkb.confirm"),
        "banner": change.BANNER,
    }


def _chain_recorder(ctx: ConsoleContext) -> Any:
    chain = getattr(ctx.runtime, "chain", None)
    return chain.record if chain is not None else None


def do_diff(
    ctx: ConsoleContext, actor: str, sha: str, instrument_id: str, incoming: str | None
) -> dict[str, Any]:
    return change.run_diff(
        data_dir=ctx.settings.data_dir,
        state=ctx.state,
        clock=ctx.clock,
        settings=ctx.settings,
        instrument_id=instrument_id,
        package_sha=sha,
        incoming=incoming or None,
        actor=actor,
        chat=None,
    )


def do_apply(ctx: ConsoleContext, actor: str, sha: str, instrument_id: str) -> dict[str, Any]:
    return change.apply_change(
        data_dir=Path(ctx.settings.data_dir),
        state=ctx.state,
        clock=ctx.clock,
        settings=ctx.settings,
        package_sha=sha,
        instrument_id=instrument_id,
        actor=actor,
        record=_chain_recorder(ctx),
    )


async def _json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    if len(raw) > MAX_BODY:
        raise change.ChangeError("too_large", "the request body is too large")
    try:
        data = json.loads(raw)
    except ValueError:
        raise change.ChangeError("bad_body", "the body must be JSON") from None
    if not isinstance(data, dict):
        raise change.ChangeError("bad_body", "the body must be a JSON object")
    return data


# ------------------------------------------------------------------------------- JSON API


@api_router.get("/regkb/changes", dependencies=[Depends(needs("regkb.view"))])
async def api_list(ctx: ConsoleContext = _CTX) -> Any:
    return await _call(list_data, ctx)


@api_router.get(
    "/regkb/changes/{package_sha}/{instrument_id}", dependencies=[Depends(needs("regkb.view"))]
)
async def api_detail(
    package_sha: str, instrument_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    data = await _call(detail_data, ctx, me, package_sha, instrument_id)
    return {
        "package_sha256": package_sha,
        "instrument_id": instrument_id,
        "change": data["row"],
        "report": data["report"],
        "drafts": [
            {k: d[k] for k in ("draft_id", "article", "duty_id", "status", "change_ref")}
            for d in data["drafts"]
        ],
        "banner": data["banner"],
    }


@api_router.post(
    "/regkb/changes/{package_sha}/{instrument_id}/diff",
    dependencies=[Depends(needs("regkb.confirm"))],
)
@audited("regkb.confirm")
async def api_diff(
    package_sha: str,
    instrument_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    change.require_on(ctx.settings)
    actor = _actor(me)
    _same_site(request)
    body = await _json_body(request)
    report = await _call(do_diff, ctx, actor, package_sha, instrument_id, body.get("incoming"))
    request.state.audit_detail = f"regkb diff {package_sha[:16]} {instrument_id}"
    return {
        "summary": report["summary"],
        "change_id": report["change_id"],
        "model": report["model"],
    }


@api_router.post(
    "/regkb/changes/{package_sha}/{instrument_id}/apply",
    dependencies=[Depends(needs("regkb.confirm"))],
)
@audited("regkb.confirm")
async def api_apply(
    package_sha: str,
    instrument_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    change.require_on(ctx.settings)
    actor = _actor(me)
    _same_site(request)
    result = await _call(do_apply, ctx, actor, package_sha, instrument_id)
    request.state.audit_detail = f"regkb apply {package_sha[:16]} {instrument_id}"
    return result


# ------------------------------------------------------------------------------- console


@router.get(
    "/regkb/changes", response_class=HTMLResponse, dependencies=[Depends(needs("regkb.view"))]
)
async def changes_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(list_data, ctx)
    return render(
        request,
        ctx,
        me,
        "regkb_changes.html",
        section="regkb_changes",
        ch=data,
        can_confirm=rbac.allowed(me.roles, "regkb.confirm"),
    )


@router.get(
    "/regkb/changes/{package_sha}/{instrument_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("regkb.view"))],
)
async def change_page(
    package_sha: str,
    instrument_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    data = await _call(detail_data, ctx, me, package_sha, instrument_id)
    return render(request, ctx, me, "regkb_change.html", section="regkb_changes", **data)


def _back(sha: str, instrument_id: str, request: Request) -> RedirectResponse:
    lang = request.query_params.get("lang")
    tail = f"?lang={lang}" if lang in ("en", "vi") else ""
    return RedirectResponse(f"/console/regkb/changes/{sha}/{instrument_id}{tail}", status_code=303)


@router.post(
    "/regkb/changes/{package_sha}/{instrument_id}/diff",
    dependencies=[Depends(needs("regkb.confirm"))],
)
@audited("regkb.confirm")
async def change_diff(
    package_sha: str,
    instrument_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    change.require_on(ctx.settings)
    actor = _actor(me)
    d, _plain_post = await form_or_plain(request)
    await _call(do_diff, ctx, actor, package_sha, instrument_id, d.get("incoming"))
    request.state.audit_detail = f"regkb diff {package_sha[:16]} {instrument_id}"
    return _back(package_sha, instrument_id, request)


@router.post(
    "/regkb/changes/{package_sha}/{instrument_id}/apply",
    dependencies=[Depends(needs("regkb.confirm"))],
)
@audited("regkb.confirm")
async def change_apply(
    package_sha: str,
    instrument_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    change.require_on(ctx.settings)
    actor = _actor(me)
    d, _plain_post = await form_or_plain(request)
    if d.get("confirm") != "yes":
        raise change.ChangeError(
            "confirm_required", "tick the confirmation: the change is written to the override"
        )
    await _call(do_apply, ctx, actor, package_sha, instrument_id)
    request.state.audit_detail = f"regkb apply {package_sha[:16]} {instrument_id}"
    return _back(package_sha, instrument_id, request)


__all__ = ["api_router", "regkb_view", "router"]
