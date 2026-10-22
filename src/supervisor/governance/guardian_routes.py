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
    request.state.audit_detail = f"guardian {slug} {out['state']}"
    return out


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
    request.state.audit_detail = f"guardian {slug} {out['state']}"
    lang = request.query_params.get("lang") or ""
    url = f"/console/catalog?system={sid}" + (f"&lang={lang}" if lang else "")
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})
