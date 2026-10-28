"""Internal documents in RegKB (WP-W3, REGKB_INTERNAL, docs/regulations.md).

The routers are always mounted; with the flag off (or without LAWAGENT_ENABLED) every route answers
HTTP 400 ``regkb_internal_off`` and nothing is read or written.

JSON API:

* ``POST /v1/regkb/internal``                      multipart ``file`` (.txt .md .pdf) and the text
  fields ``title``, ``owner_group`` (required), ``version_label``; 201 (``regkb.upload``)
* ``GET  /v1/regkb/internal``                      the list (``regkb.view``)
* ``GET  /v1/regkb/internal/{doc_id}``             meta, status, sections, draft counts
* ``GET  /v1/regkb/internal/{doc_id}/sections/{n}`` masked text of one section (the reader of
  WP-F2: the checklist drafter and the ``policy_refs`` field of the factory editor)
* ``POST /v1/regkb/internal/{doc_id}/draft``       the law agent, internal mode (``regkb.upload``)

Console:

* ``GET  /console/regkb/internal``                 the page
* ``POST /console/regkb/internal``                 upload form (htmx)
* ``POST /console/regkb/internal/{doc_id}/draft``  the "Draft duties" button (htmx)

A person with ``regkb.confirm`` accepts rows on ``/console/regkb/VN-INT-<doc_id>/drafts`` (the
existing drafts page). Every POST writes two ``console_action`` rows. Not legal advice.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.intake_routes import _same_site, parse_multipart
from supervisor.console.routes import _call, _htmx_only, audited, message_html, render
from supervisor.core import rbac
from supervisor.regkb import internal

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
FORM_SLACK = 256 * 1024  # multipart overhead on top of the file limit


def _actor(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("this step needs a signed-in person")
    return str(me.user_id)


async def _read_body(request: Request, ctx: ConsoleContext) -> bytes:
    limit = internal.max_bytes(ctx.settings) + FORM_SLACK
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise internal.InternalError(
            "too_large", f"the upload is larger than {limit // 1_048_576} MB"
        )
    body = await request.body()
    if len(body) > limit:
        raise internal.InternalError(
            "too_large", f"the upload is larger than {limit // 1_048_576} MB"
        )
    return body


def _upload(
    ctx: ConsoleContext, files: list[tuple[str, bytes]], fields: dict[str, str], actor: str
) -> dict[str, Any]:
    if not files:
        raise internal.InternalError("nothing_to_upload", "send one file in the field 'file'")
    name, data = files[0]
    return internal.service(ctx).upload(
        name,
        data,
        title=fields.get("title", ""),
        owner_group=fields.get("owner_group", ""),
        version_label=fields.get("version_label", ""),
        actor=actor,
    )


def _draft(ctx: ConsoleContext, doc_id: str) -> internal.RunSummary:
    svc = internal.service(ctx)
    internal.require_on(ctx.settings)
    svc.get(doc_id)  # 400 for an unknown document before a model is built
    return svc.draft(doc_id, internal.make_chat(ctx.settings))


def panel_data(ctx: ConsoleContext, me: AuthPrincipal) -> dict[str, Any]:
    return {
        "ri": {
            "docs": internal.service(ctx).list(),
            "max_mb": int(ctx.settings.regkb_internal_max_mb),
            "can_upload": rbac.allowed(me.roles, "regkb.upload"),
        }
    }


# ------------------------------------------------------------------------------- JSON API


@api_router.post("/regkb/internal", dependencies=[Depends(needs("regkb.upload"))])
@audited("regkb.upload")
async def post_upload(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    internal.require_on(ctx.settings)
    actor = _actor(me)
    _same_site(request)
    files, fields = parse_multipart(
        request.headers.get("content-type", ""), await _read_body(request, ctx)
    )
    doc = await _call(_upload, ctx, files, fields, actor)
    request.state.audit_detail = f"regkb_internal upload {doc['doc_id']}"
    return JSONResponse(status_code=201, content=doc)


@api_router.get("/regkb/internal", dependencies=[Depends(needs("regkb.view"))])
async def list_docs(ctx: ConsoleContext = _CTX) -> Any:
    internal.require_on(ctx.settings)
    return {"documents": await _call(internal.service(ctx).list), "banner": internal.BANNER}


@api_router.get("/regkb/internal/{doc_id}", dependencies=[Depends(needs("regkb.view"))])
async def get_doc(doc_id: str, ctx: ConsoleContext = _CTX) -> Any:
    internal.require_on(ctx.settings)
    return await _call(internal.service(ctx).get, doc_id)


@api_router.get(
    "/regkb/internal/{doc_id}/sections/{n}", dependencies=[Depends(needs("regkb.view"))]
)
async def get_section(doc_id: str, n: int, ctx: ConsoleContext = _CTX) -> Any:
    internal.require_on(ctx.settings)
    return await _call(internal.service(ctx).section, doc_id, n)


@api_router.post("/regkb/internal/{doc_id}/draft", dependencies=[Depends(needs("regkb.upload"))])
@audited("regkb.upload")
async def post_draft(
    doc_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    internal.require_on(ctx.settings)
    _actor(me)
    summary = await _call(_draft, ctx, doc_id)
    request.state.audit_detail = f"regkb_internal draft {doc_id} kept={summary.kept}"
    return {
        **summary.as_dict(),
        "review": f"/console/regkb/{internal.instrument_id(doc_id)}/drafts",
    }


# ------------------------------------------------------------------------------- console


@router.get(
    "/regkb/internal", response_class=HTMLResponse, dependencies=[Depends(needs("regkb.view"))]
)
async def internal_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    internal.require_on(ctx.settings)
    data = await _call(panel_data, ctx, me)
    return render(request, ctx, me, "regkb_internal.html", section="", **data)


def _with_note(resp: Response, note: str) -> Response:
    resp.body = bytes(resp.body) + message_html(note, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


@router.post(
    "/regkb/internal", response_class=HTMLResponse, dependencies=[Depends(needs("regkb.upload"))]
)
@audited("regkb.upload")
async def internal_upload(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    internal.require_on(ctx.settings)
    actor = _actor(me)
    files, fields = parse_multipart(
        request.headers.get("content-type", ""), await _read_body(request, ctx)
    )
    doc = await _call(_upload, ctx, files, fields, actor)
    request.state.audit_detail = f"regkb_internal upload {doc['doc_id']}"
    data = await _call(panel_data, ctx, me)
    resp = render(request, ctx, me, "_regkb_internal_panel.html", **data)
    note = ctx_t(request, ctx, "ri_uploaded_note", id=doc["instrument_id"], n=doc["section_count"])
    return _with_note(resp, note)


def ctx_t(request: Request, ctx: ConsoleContext, key: str, **kw: Any) -> str:
    from supervisor.console.i18n import translator
    from supervisor.console.routes import _lang

    return str(translator(_lang(request, ctx))(key, **kw))


@router.post(
    "/regkb/internal/{doc_id}/draft",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("regkb.upload"))],
)
@audited("regkb.upload")
async def internal_draft(
    doc_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    internal.require_on(ctx.settings)
    _actor(me)
    summary = await _call(_draft, ctx, doc_id)
    request.state.audit_detail = f"regkb_internal draft {doc_id} kept={summary.kept}"
    data = await _call(panel_data, ctx, me)
    resp = render(request, ctx, me, "_regkb_internal_panel.html", **data)
    note = ctx_t(
        request,
        ctx,
        "ri_drafted_note",
        id=internal.instrument_id(doc_id),
        kept=summary.kept,
        dropped=summary.dropped,
        nodut=summary.no_duty,
    )
    return _with_note(resp, note)
