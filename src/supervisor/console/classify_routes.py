"""Classification tree routes (WP-C1 of phase 12, CLASSIFICATION_V2, docs/classification.md).
The routers are always mounted; with the flag off every route answers HTTP 400
``classification_v2_off`` (nothing is read or written).

JSON API:

* ``GET  /v1/systems/{id}/classification-v2``
      the approved record, the one waiting for approval, the triggers (``systems.view``)
* ``POST /v1/systems/{id}/classification-v2``
      a person stores a path; 201 (``systems.edit``); ``?preview=1`` walks the tree and stores
      nothing; 200
* ``POST /v1/systems/{id}/classification-v2/approve``
      a second person approves (``systems.approve``)
* ``GET  /v1/classification/summary``
      counts per outcome (``systems.view``)

Console:

* ``GET  /console/systems/{id}/classify``          the page (a fragment with ``HX-Request``)
* ``POST /console/systems/{id}/classify``          Evaluate (``do=preview``) or Save (``do=decide``)
* ``POST /console/systems/{id}/classify/approve``  Approve

The existing ``/v1/systems/{id}/classification`` routes stay the Decision 33 flow. A system out of
the caller's scope answers 404. Every POST writes two ``console_action`` rows (``@audited``)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import agent_detail
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import (
    _call,
    _check_id,
    _lang,
    audited,
    form_or_plain,
    message_html,
    render,
)
from supervisor.core import rbac
from supervisor.core.errors import NotFoundError
from supervisor.governance import classification_v2 as c2
from supervisor.governance.routes import _actor, _body, _not_found, _service, _visible

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _svc(ctx: ConsoleContext) -> c2.ClassificationV2Service:
    c2.require_on(ctx.settings)
    svc: c2.ClassificationV2Service = ctx.classification_v2
    return svc


def _see(ctx: ConsoleContext, me: AuthPrincipal, system_id: str) -> str:
    return _visible(_service(ctx), me, system_id)


# ------------------------------------------------------------------------------- JSON API


@api_router.get(
    "/systems/{system_id}/classification-v2", dependencies=[Depends(needs("systems.view"))]
)
def get_record(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _svc(ctx)
    try:
        return svc.get(_see(ctx, me, system_id))
    except NotFoundError as exc:
        return _not_found(exc)


@api_router.post(
    "/systems/{system_id}/classification-v2", dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def post_record(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _svc(ctx)
    _actor(me)
    data = await _body(request)
    preview = request.query_params.get("preview") in ("1", "true")
    try:
        sid = _see(ctx, me, system_id)
        if preview:
            request.state.audit_detail = "classification_v2 preview"
            return await _call(svc.preview, sid, data)
        out = await _call(svc.decide, sid, me, data)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"classification_v2 decide {out['outcome']}"
    return JSONResponse(status_code=201, content=out)


@api_router.post(
    "/systems/{system_id}/classification-v2/approve",
    dependencies=[Depends(needs("systems.approve"))],
)
@audited("systems.approve")
async def post_approve(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _svc(ctx)
    _actor(me)
    try:
        out = await _call(svc.approve, _see(ctx, me, system_id), me)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"classification_v2 approve {out['outcome']}"
    return out


@api_router.get("/classification/summary", dependencies=[Depends(needs("systems.view"))])
def get_summary(ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _svc(ctx)
    systems = _service(ctx)
    rows = systems.list_systems(systems.scope_for(me), {})
    return svc.summary([str(r["system_id"]) for r in rows])


# ------------------------------------------------------------------------------- console


def _payload_of(record: dict[str, Any] | None) -> dict[str, Any]:
    """Answers of a stored record as a form payload, so the page shows the path as it was."""
    answers: dict[str, Any] = {}
    d33_answers: dict[str, Any] = {}
    inherited = False
    if record:
        inherited = bool(record["inherited_from_provider"])
        for s in record["path"]:
            if s.get("source") == "person":
                answers[s["node"]] = {
                    "answer": s["answer"],
                    "evidence": s.get("evidence", ""),
                    "note": s.get("note", ""),
                }
            for qid, a in ((s.get("d33") or {}).get("answers") or {}).items():
                if a.get("source") == "person" and a.get("answer"):
                    d33_answers[qid] = {"answer": a["answer"], "justification": a.get("why", "")}
    return {"answers": answers, "decision33": d33_answers, "inherited_from_provider": inherited}


def panel_data(
    ctx: ConsoleContext,
    me: AuthPrincipal,
    system_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Template variables of the classify panel (``_classify_panel.html``)."""
    svc = _svc(ctx)
    got = svc.get(system_id)
    shown = got["pending"] or got["current"]
    try:
        live = svc.preview(system_id, payload if payload is not None else _payload_of(shown))
    except c2.V2Error:  # a stored path that no longer fits the tree file: show the rules only
        if payload is not None:
            raise
        live = svc.preview(system_id, {})
    system = ctx.state.get("ai_system", {"system_id": system_id}) or {}
    uid = str(me.user_id)
    can_edit = agent_detail.can(me, "systems.edit")
    pending = got["pending"]
    can_approve = bool(
        pending
        and rbac.allowed(me.roles, "systems.approve")
        and pending["decided_by"] != uid
        and not svc._is_owner(system_id, uid)  # noqa: SLF001
    )
    return {
        "cv": {
            "system_id": system_id,
            "system_name": str(system.get("name") or system_id),
            "got": got,
            "tree": live,
            "can_edit": can_edit,
            "can_approve": can_approve,
            "me": uid,
            "base": f"/console/systems/{system_id}/classify",
        }
    }


@router.get(
    "/systems/{system_id}/classify",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def classify_page(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _svc(ctx)
    _check_id(system_id, "system id")
    try:
        sid = await _call(_see, ctx, me, system_id)
    except NotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    data = await _call(panel_data, ctx, me, sid)
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_classify_panel.html", **data)
    return render(request, ctx, me, "classify.html", section="systems", **data)


async def _respond(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    sid: str,
    plain: bool,
    note: str,
    payload: dict[str, Any] | None = None,
    *,
    redirect: bool = True,
) -> Response:
    if plain and redirect:  # a plain post goes back to the page (no JavaScript needed)
        return RedirectResponse(
            f"/console/systems/{sid}/classify?lang={_lang(request, ctx)}", status_code=303
        )
    data = await _call(panel_data, ctx, me, sid, payload)
    template = "classify.html" if plain else "_classify_panel.html"
    resp = render(request, ctx, me, template, section="systems", **data)
    if not plain and note:
        resp.body = resp.body + message_html(note, ok=True, oob=True).encode()
        resp.headers["content-length"] = str(len(resp.body))
    return resp


@router.post(
    "/systems/{system_id}/classify",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def classify_post(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    svc = _svc(ctx)
    _check_id(system_id, "system id")
    form, plain = await form_or_plain(request)
    try:
        sid = await _call(_see, ctx, me, system_id)
    except NotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    tree = svc.tree()
    payload = c2.payload_from_form(form, tree, svc.d33.flow().ids)
    if form.get("do") == "decide":
        out = await _call(svc.decide, sid, me, payload)
        request.state.audit_detail = f"classification_v2 decide {out['outcome']}"
        return await _respond(
            request, ctx, me, sid, plain, f"{sid}: {out['outcome']} (waiting for approval)"
        )
    request.state.audit_detail = "classification_v2 preview"
    return await _respond(request, ctx, me, sid, plain, "", payload, redirect=False)


@router.post(
    "/systems/{system_id}/classify/approve",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.approve"))],
)
@audited("systems.approve")
async def classify_approve(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    svc = _svc(ctx)
    _check_id(system_id, "system id")
    _, plain = await form_or_plain(request)
    try:
        sid = await _call(_see, ctx, me, system_id)
    except NotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    out = await _call(svc.approve, sid, me)
    request.state.audit_detail = f"classification_v2 approve {out['outcome']}"
    return await _respond(request, ctx, me, sid, plain, f"{sid}: {out['outcome']} approved")
