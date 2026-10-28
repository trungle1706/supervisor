"""JSON routes of the per-system guardian bindings (WP-S1, docs/guardian-bindings.md).

* ``GET /v1/systems/{id}/guardians`` (systems.view): every bindable guardian feature with the
  binding, the floor lock (``locked`` and the rule ids), whether the instance has it on, and the
  effective state.
* ``PUT /v1/systems/{id}/guardians/{slug}`` (systems.edit): body ``state`` (``on`` | ``off``) and
  an optional ``reason``. Switching a floor feature off, a gate rule (``policy_rules``) or an
  unknown slug is HTTP 400.

Mounted by ``app.py`` only when GOVERNANCE_ENABLED=1 and GUARDIAN_BINDINGS_ENABLED=1. A system
outside the caller's scope answers 404, like one that does not exist. Every write makes two
``console_action`` audit rows and a ``binding_change`` chain record. Never 500.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.governance.guardians import GuardianService, ensure_bindings_on
from supervisor.governance.routes import _actor, _body, _not_found, _service, _visible

router = APIRouter(prefix="/v1/systems", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def guardians(ctx: ConsoleContext) -> GuardianService:
    ensure_bindings_on(ctx.settings)
    svc: GuardianService = ctx.guardians
    return svc


@router.get("/{system_id}/guardians", dependencies=[Depends(needs("systems.view"))])
def get_guardians(system_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = guardians(ctx)
    try:
        return svc.get(_visible(_service(ctx), me, system_id))
    except NotFoundError as exc:
        return _not_found(exc)


@router.put("/{system_id}/guardians/{slug}", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def put_guardian(
    system_id: str,
    slug: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    svc = guardians(ctx)
    actor = _actor(me)
    data = await _body(request)
    try:
        out = svc.set(
            _visible(_service(ctx), me, system_id),
            slug,
            data.get("state"),
            actor,
            data.get("reason"),
        )
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = _detail(slug, out)
    return out


@router.post(
    "/{system_id}/guardian-off-requests/{request_id}/decide",
    dependencies=[Depends(needs("systems.approve"))],
)
@audited("systems.approve")
async def decide_guardian_off(
    system_id: str,
    request_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    """WP-P2 (phase 8, CONSOLE_STATE_ACTIONS): a second person approves or rejects a request to
    switch a guardian off on a production or high-risk system. Body ``decision``: approve | reject.
    The requester gets HTTP 400 ``same_person``."""
    svc = guardians(ctx)
    actor = _actor(me)
    data = await _body(request)
    try:
        out = svc.decide_off(
            _visible(_service(ctx), me, system_id),
            request_id,
            actor,
            str(data.get("decision", "approve")),
        )
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"guardian off {out['request_status']}"
    return out


def _detail(slug: str, out: dict[str, Any]) -> str:
    if out.get("pending_request"):  # WP-P2: asked, not yet switched off
        return f"guardian {slug} off requested"
    return f"guardian {slug} {out['state']}"


# ------------------------------------------------------------------------------ the console
# The switch on the Catalog page posts here. No CONSOLE_SYSTEMS_ENABLED needed: the page that
# holds the switches is the Catalog (CONSOLE_CATALOG_ENABLED). A hook for the system page
# (a Guardians tab) is ``supervisor.console.guardians_view.system_panel``.
console_router = APIRouter(prefix="/console", tags=["console"])


@console_router.post(
    "/systems/{system_id}/guardians/{slug}", dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def console_set_guardian(
    system_id: str,
    slug: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    from fastapi.responses import RedirectResponse, Response

    from supervisor.console.routes import _call, form_or_plain

    svc = guardians(ctx)
    actor = _actor(me)
    form, plain = await form_or_plain(request)
    try:
        sid = _visible(_service(ctx), me, system_id)
        out = await _call(svc.set, sid, slug, form.get("state"), actor, form.get("reason") or None)
    except NotFoundError as exc:
        from supervisor.console.errors import console_error

        return console_error(request, str(exc), 404)
    request.state.audit_detail = _detail(slug, out)
    lang = request.query_params.get("lang") or ""
    url = f"/console/catalog?system={sid}" + (f"&lang={lang}" if lang else "")
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})


@console_router.post(
    "/systems/{system_id}/guardian-requests/{request_id}/{decision}",
    dependencies=[Depends(needs("systems.approve"))],
)
@audited("systems.approve")
async def console_decide_guardian_off(
    system_id: str,
    request_id: str,
    decision: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    """WP-P2 (phase 8): Approve or Reject on the Catalog page (``decision``: approve | reject)."""
    from fastapi.responses import RedirectResponse, Response

    from supervisor.console.routes import _call, form_or_plain

    svc = guardians(ctx)
    actor = _actor(me)
    _, plain = await form_or_plain(request)
    try:
        sid = _visible(_service(ctx), me, system_id)
        out = await _call(svc.decide_off, sid, request_id, actor, decision)
    except NotFoundError as exc:
        from supervisor.console.errors import console_error

        return console_error(request, str(exc), 404)
    request.state.audit_detail = f"guardian off {out['request_status']}"
    lang = request.query_params.get("lang") or ""
    url = f"/console/catalog?system={sid}" + (f"&lang={lang}" if lang else "")
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})
