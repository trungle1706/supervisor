"""Law agent drafts page (WP-L1): ``/console/regkb/<instrument>/drafts``.

Mounted always; every route answers HTTP 400 with a message while LAWAGENT_ENABLED is off.
``regkb.view`` (every console role) reads the page; ``regkb.confirm`` (approver, admin) confirms
or drops one draft, with two ``console_action`` rows per POST and the person recorded on the row.
There is no "Run the agent" button: the CLI runs the agent. Not legal advice.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console import regkb_view
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, _check_id, _version, audited, form, render
from supervisor.regkb import internal
from supervisor.regkb.drafts import DRAFT_ID_RE, DraftStore

router = APIRouter(prefix="/console", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


@router.get(
    "/regkb/{instrument_id}/drafts",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("regkb.view"))],
)
async def drafts_page(
    instrument_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    regkb_view.ensure_on(ctx.settings)
    _check_id(instrument_id, "instrument id")
    status = request.query_params.get("status", "draft")
    data = await _call(regkb_view.drafts_view, ctx, me, instrument_id, status)
    return render(request, ctx, me, "regkb_drafts.html", section="", **data)


async def _decide(
    status: str,
    instrument_id: str,
    draft_id: str,
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
) -> Response:
    regkb_view.ensure_on(ctx.settings)
    _check_id(instrument_id, "instrument id")
    _check_id(draft_id, "draft id")
    d = await form(request)
    if me.kind != "user":
        raise PermissionDenied("confirming a draft needs a signed-in person")
    if not DRAFT_ID_RE.match(draft_id):
        raise regkb_view.RegkbInputError("invalid draft id")
    await _call(regkb_view.check_instrument, instrument_id, ctx)
    version = _version(d)

    def work() -> None:
        store = DraftStore(ctx.state, ctx.clock)
        row = store.get(draft_id)
        if row is None or row["instrument_id"] != instrument_id:
            raise regkb_view.RegkbInputError("this draft does not exist")
        store.decide(draft_id, status, me.user_id, expected_version=version)

    await _call(work)
    request.state.audit_detail = f"regkb_draft_{status}"
    if status == "confirmed" and internal.is_internal_instrument(instrument_id):
        # WP-W3: the confirmed rows of an internal document are rebuilt into its instrument file
        await _call(
            lambda: internal.service(ctx).after_decision(
                internal.doc_id_of(instrument_id), str(me.user_id)
            )
        )
    data = await _call(regkb_view.draft_view, ctx, me, instrument_id, draft_id)
    return render(request, ctx, me, "_regkb_draft.html", **data)


@router.post(
    "/regkb/{instrument_id}/drafts/{draft_id}/confirm",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("regkb.confirm"))],
)
@audited("regkb.confirm")
async def draft_confirm(
    instrument_id: str,
    draft_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    return await _decide("confirmed", instrument_id, draft_id, request, ctx, me)


@router.post(
    "/regkb/{instrument_id}/drafts/{draft_id}/drop",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("regkb.confirm"))],
)
@audited("regkb.confirm")
async def draft_drop(
    instrument_id: str,
    draft_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    return await _decide("dropped", instrument_id, draft_id, request, ctx, me)
