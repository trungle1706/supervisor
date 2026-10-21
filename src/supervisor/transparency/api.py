"""JSON routes of the transparency report (WP31): ``/v1/transparency/...``.

=======  ====================================  =======================  ===========================
method   path                                  permission               does
=======  ====================================  =======================  ===========================
GET      /v1/transparency                      transparency.view        agents with the latest
                                                                        version per variant
GET      /v1/transparency/{agent_id}           transparency.view        the report; query variant
                                                                        (regulator|customer|
                                                                        internal), format (json|
                                                                        html|pdf), lang (vi|en),
                                                                        live=1 (current facts)
POST     /v1/transparency/{agent_id}/generate  transparency.generate    build and sign; body
                                                                        {variants, force}
=======  ====================================  =======================  ===========================

Every role that can sign in reads all three variants (the customer variant holds nothing internal
and is meant to be handed on, but it still sits behind the login). Reviewer and admin generate.
A generate writes two ``console_action`` audit rows and a ``transparency_report`` chain record
per new version. Off unless TRANSPARENCY_ENABLED=1 (HTTP 400 with a message). A bad input is
HTTP 400, an unknown agent 404; never 500.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import audited
from supervisor.core.errors import NotFoundError
from supervisor.transparency.model import (
    VARIANTS,
    TransparencyError,
    UnknownAgent,
    check_agent,
    check_format,
    check_lang,
    check_variant,
    ensure_on,
)

router = APIRouter(prefix="/v1/transparency", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
MAX_BODY = 8_000


def _service(ctx: ConsoleContext) -> Any:
    ensure_on(ctx.settings)
    return ctx.transparency


def _missing(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": str(exc)})


def _actor(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("generating a report needs a signed-in person")
    return str(me.user_id)


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise TransparencyError("request body is too large")
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise TransparencyError("request body must be JSON") from None
    if not isinstance(data, dict):
        raise TransparencyError("request body must be a JSON object")
    return data


@router.get("", dependencies=[Depends(needs("transparency.view"))])
def overview(ctx: ConsoleContext = _CTX) -> Any:
    return {"agents": _service(ctx).overview(), "variants": list(VARIANTS)}


@router.get("/{agent_id}", dependencies=[Depends(needs("transparency.view"))])
def get_report(
    agent_id: str,
    variant: str = "regulator",
    format: str = "json",  # noqa: A002 - the query parameter is called format
    lang: str = "en",
    live: int = 0,
    ctx: ConsoleContext = _CTX,
) -> Any:
    svc = _service(ctx)
    check_agent(agent_id)
    check_variant(variant)
    check_format(format)
    check_lang(lang)
    try:
        data, ctype, info = svc.read(agent_id, variant, format, lang, live=bool(live))
    except (UnknownAgent, NotFoundError) as exc:
        return _missing(exc)
    headers = {
        "x-report-status": info["status"],
        "x-report-version": str(info["version"]),
        "x-report-sha256": info["hash"],
    }
    if format != "html":
        ext = {"json": "json", "pdf": "pdf"}[format]
        suffix = "" if format == "json" else f".{lang}"
        headers["content-disposition"] = (
            f'attachment; filename="transparency-{variant}-v{info["version"]}{suffix}.{ext}"'
        )
    return Response(data, media_type=ctype, headers=headers)


@router.post("/{agent_id}/generate", dependencies=[Depends(needs("transparency.generate"))])
@audited("transparency.generate")
async def generate(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _service(ctx)
    check_agent(agent_id)
    data = await _body(request)
    variants = data.get("variants") or list(VARIANTS)
    if not isinstance(variants, list):
        raise TransparencyError("variants must be a list")
    force = data.get("force", False)
    if not isinstance(force, bool):
        raise TransparencyError("force must be true or false")
    actor = _actor(me)
    try:
        out = await run_in_threadpool(
            lambda: svc.generate(
                agent_id, tuple(check_variant(v) for v in variants), actor=actor, force=force
            )
        )
    except UnknownAgent as exc:
        return _missing(exc)
    made = [r for r in out if r["status"] == "made"]
    request.state.audit_detail = f"generate:{len(made)}"
    return {"agent_id": agent_id, "results": out}
