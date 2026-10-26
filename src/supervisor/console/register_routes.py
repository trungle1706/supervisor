"""Register workflow v2 routes (WP-N3): ``/console/register``. Docs: ``docs/register-v2.md``.

Mounted through ``systems_routes`` (so the Systems page flags apply) and answering HTTP 400
with the flag name while CONSOLE_REGISTER_V2 is off. Permission ``systems.edit`` everywhere.
Every error is HTTP 400 with the field name; a bad step value re-renders the step with the
message. The submit is the one write route and has the console audit rows."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console import systems_wizard
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import (
    ConsoleInputError,
    _call,
    audited,
    form_or_plain,
    render,
)
from supervisor.core import rbac
from supervisor.governance.model import ensure_on
from supervisor.governance.register_v2 import model as rm
from supervisor.governance.register_v2 import service as rs

router = APIRouter(prefix="/register", tags=["console"])  # included under /console
_CTX = Depends(get_context)
_ME = Depends(current_principal)
_EDIT = [Depends(needs("systems.edit"))]


def _off(ctx: ConsoleContext) -> None:
    """HTTP 400 naming the flag unless the workflow and what it needs are on."""
    if not ctx.settings.console_register_v2:
        raise ConsoleInputError("The register workflow is off (CONSOLE_REGISTER_V2=1 turns it on)")
    ensure_on(ctx.settings)


def _person(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("registering an AI system needs a signed-in person")
    return str(me.user_id)


def _step_no(raw: str) -> int:
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= rm.STEPS:
        raise rm.RegisterError("step", f"must be 1 to {rm.STEPS}")
    return int(raw)


def _go(request: Request, plain: bool, url: str) -> Response:
    lang = request.query_params.get("lang") or ""
    if lang in ("en", "vi"):
        url += ("&" if "?" in url else "?") + f"lang={lang}"
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})


def step_data(
    ctx: ConsoleContext, me: AuthPrincipal, draft: dict[str, Any], n: int
) -> dict[str, Any]:
    """The view model of one step."""
    out: dict[str, Any] = {"draft": draft, "step": n, "steps": rm.STEPS}
    out["v"] = rs.values_of(draft)
    out["sg"] = draft["data"]["sg"]
    out["marks"] = {f: rs.mark(draft, f) for f in (*rm.STEP1, *rm.STEP2)}
    out["scoped"] = rs.scoped(ctx, me)
    if n == 1:
        out["kinds"] = rm.KINDS
    elif n == 2:
        out["choices"] = rm.CHOICES
    elif n == 3:
        out["gaps"] = rs.gaps(ctx, me, draft)
        out["check"] = draft["data"].get("check") or {}
        out["repo"] = draft["data"].get("repo_path") or ""
        out["can_repo"] = bool(
            rbac.allowed(me.roles, "onboard.start") and systems_wizard.allowed_roots(ctx.settings)
        )
        full = rs._full_or_none(ctx, me, draft)  # noqa: SLF001
        out["prelim"] = (
            {
                "cls": systems_wizard._class_preview(ctx, full)  # noqa: SLF001
                or systems_wizard.declared_class(full),
                "packs": systems_wizard.packs_for(full),
            }
            if full is not None
            else None
        )
    elif n == 4:
        out["cls"] = rs.class_view(ctx, me, draft)
    elif n == 5:
        out["g"] = rs.guardian_view(ctx, me, draft)
    else:
        out["r"] = rs.review_view(ctx, me, draft)
    return out


def _render_step(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    draft: dict[str, Any],
    n: int,
    *,
    error: str = "",
    posted: dict[str, str] | None = None,
    status: int = 200,
) -> Response:
    data = step_data(ctx, me, draft, n)
    return render(
        request,
        ctx,
        me,
        "register_step.html",
        status_code=status,
        section="systems",
        error=error,
        posted=posted or {},
        **data,
    )


@router.get("", response_class=HTMLResponse, dependencies=_EDIT)
async def register_list(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """My open drafts, with the link to resume each."""
    _off(ctx)
    uid = _person(me)
    drafts = await _call(rs.store_of(ctx).list_mine, uid)
    return render(request, ctx, me, "register_list.html", section="systems", drafts=drafts)


@router.get("/new", dependencies=_EDIT)
async def register_new(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Make a draft (``?from=<node id>`` scan prefill, ``?agent=<agent id>`` policy prefill, none
    = blank) and go to step 1."""
    _off(ctx)
    _person(me)
    q = request.query_params
    draft = await _call(rs.start, ctx, me, q.get("from") or "", q.get("agent") or "")
    return _go(request, True, f"/console/register/{draft['draft_id']}/step/1")


@router.get("/{draft_id}/step/{n}", response_class=HTMLResponse, dependencies=_EDIT)
async def register_step(
    draft_id: str, n: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    uid = _person(me)
    num = _step_no(n)
    draft = await _call(rs.store_of(ctx).get, draft_id, uid)
    if draft["status"] != "draft":
        return _go(request, True, f"/console/register/{draft_id}/result")
    return _render_step(request, ctx, me, draft, num)


@router.post("/{draft_id}/step/{n}", dependencies=_EDIT)
async def register_save(
    draft_id: str, n: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Validate and save step n, then go to n+1 (``?save=1``, or accepting a suggestion or
    running the check: stay)."""
    _off(ctx)
    uid = _person(me)
    num = _step_no(n)
    form, plain = await form_or_plain(request)
    store = rs.store_of(ctx)
    draft = await _call(store.get, draft_id, uid)
    if draft["status"] != "draft":
        raise rm.RegisterError("draft_id", f"this draft is {draft['status']}")
    stay = request.query_params.get("save") == "1" or bool(form.get("accept") or form.get("run"))
    try:
        saved = await _call(rs.save_step, ctx, me, draft, num, form, stay=stay)
    except rm.RegisterError as exc:
        return _render_step(request, ctx, me, draft, num, error=str(exc), posted=form, status=400)
    target = num if stay else min(num + 1, rm.STEPS)
    return _go(request, plain, f"/console/register/{saved['draft_id']}/step/{target}")


@router.post("/{draft_id}/submit", dependencies=_EDIT)
@audited("systems.edit")
async def register_submit(
    draft_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """The writes of spec 3.2 in one service call, then the result page."""
    _off(ctx)
    uid = _person(me)
    _, plain = await form_or_plain(request)
    draft = await _call(rs.store_of(ctx).get, draft_id, uid)
    await _call(rs.submit, ctx, me, draft)
    request.state.audit_detail = "register submit"
    return _go(request, plain, f"/console/register/{quote(draft_id)}/result")


@router.post("/{draft_id}/abandon", dependencies=_EDIT)
@audited("systems.edit")
async def register_abandon(
    draft_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    uid = _person(me)
    _, plain = await form_or_plain(request)
    store = rs.store_of(ctx)
    draft = await _call(store.get, draft_id, uid)
    await _call(store.save, draft, status="abandoned")
    request.state.audit_detail = "register abandon"
    return _go(request, plain, "/console/register")


@router.get("/{draft_id}/result", response_class=HTMLResponse, dependencies=_EDIT)
async def register_result(
    draft_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    uid = _person(me)
    store = rs.store_of(ctx)
    draft = await _call(store.get, draft_id, uid)
    result = (draft["data"].get("result") or {}) if draft["status"] == "submitted" else {}
    sid = str(result.get("system_id") or "")
    if not sid:
        raise rm.RegisterError("draft_id", "this draft was not submitted")
    d = await _call(rs.result_view, ctx, me, draft)
    return render(request, ctx, me, "register_result.html", section="systems", d=d)
