"""JSON routes of the incidents of the governance loop (WP-G5): ``/v1/incidents``.

* ``GET /v1/incidents`` (incidents.view): incidents in the caller's scope; filters status
  (open, investigating, resolved, closed, active (the default: not closed), all), severity,
  kind, system, agent, q.
* ``GET /v1/incidents/{id}`` (incidents.view): one incident.
* ``POST /v1/incidents/{id}/transition`` (incidents.transition): body ``status``
  (investigating, resolved, closed), optional ``root_cause``, ``affected_scope``,
  ``row_version``. A signed-in person only; closing too.

There is no route that creates an incident: the governance action job makes them, from events.
Mounted by ``app.py`` only when GOVERNANCE_ACTIONS_ENABLED=1; the handlers also need
GOVERNANCE_ENABLED=1 (HTTP 400 with a message otherwise). A system out of the caller's scope
answers 404, like a missing incident. A bad input is HTTP 400 with the reason; never 500. Every
write makes two ``console_action`` audit rows and an ``incident_change`` chain record.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.governance.incidents import IncidentError

router = APIRouter(prefix="/v1/incidents", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
MAX_BODY = 16_000


def ensure_actions_on(settings: Any) -> None:
    """HTTP 400 unless GOVERNANCE_ACTIONS_ENABLED and GOVERNANCE_ENABLED are both on."""
    if not getattr(settings, "governance_actions_enabled", False):
        raise IncidentError("incidents are off (GOVERNANCE_ACTIONS_ENABLED=1 turns them on)")
    if not getattr(settings, "governance_enabled", False):
        raise IncidentError("incidents need GOVERNANCE_ENABLED=1 as well")


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise IncidentError("request body is too large")
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise IncidentError("request body must be JSON") from None
    if not isinstance(data, dict):
        raise IncidentError("request body must be a JSON object")
    return data


def _service(ctx: ConsoleContext) -> Any:
    ensure_actions_on(ctx.settings)
    return ctx.incidents


def _not_found(exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": str(exc)})


def _person(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("moving an incident needs a signed-in person")
    return str(me.user_id)


@router.get("", dependencies=[Depends(needs("incidents.view"))])
def list_incidents(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _service(ctx)
    rows = svc.list_incidents(me, dict(request.query_params))
    return {"count": len(rows), "incidents": rows}


@router.get("/{incident_id}", dependencies=[Depends(needs("incidents.view"))])
def get_incident(incident_id: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _service(ctx)
    try:
        return svc.get(incident_id, me)
    except NotFoundError as exc:
        return _not_found(exc)


@router.post("/{incident_id}/transition", dependencies=[Depends(needs("incidents.transition"))])
@audited("incidents.transition")
async def transition_incident(
    incident_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    _person(me)
    data = await _body(request)
    version = data.get("row_version")
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        raise IncidentError("row_version must be a whole number")
    try:
        out = svc.transition(
            incident_id,
            str(data.get("status", "")),
            me,
            root_cause=data.get("root_cause"),
            affected_scope=data.get("affected_scope"),
            expected_version=version,
            me_scope=me,
        )
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"incident_{out['status']}"
    return out
