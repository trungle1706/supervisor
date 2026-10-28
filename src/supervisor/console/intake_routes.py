"""Source intake routes (WP-O1, ONBOARD_INTAKE): the Source panel of a candidate and an agent and
the JSON API. The routers are always mounted; with the flag off every route answers HTTP 400 with
the flag name (nothing is read or written).

* ``GET  /v1/intake/{node_id}``      the attempts of a node, newest first (``systems.view``)
* ``POST /v1/intake/{node_id}``      multipart ``file`` (a zip) or JSON ``{"git_url": ...}``
                                      (``systems.edit``); 201 with the attempt
* ``GET  /console/intake/{node_id}`` the Source panel (an htmx fragment; a full page without htmx)
* ``POST /console/intake/{node_id}`` the form of the panel (``systems.edit``), htmx only

Every POST writes two ``console_action`` rows (``@audited``). A refusal is HTTP 400 with
``<code>: <text>``; see ``supervisor.onboard.intake``."""

from __future__ import annotations

import contextlib
import json
from email import policy
from email.parser import BytesParser
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console import agent_detail
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, _htmx_only, audited, message_html, render
from supervisor.onboard import intake

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
FORM_SLACK = 256 * 1024  # multipart overhead on top of the zip limit


def service(ctx: ConsoleContext) -> intake.IntakeService:
    return intake.IntakeService(ctx.settings, ctx.state, ctx.clock)


def panel_data(ctx: ConsoleContext, me: AuthPrincipal, node_id: str) -> dict[str, Any]:
    """Template variables of the Source panel (``_intake_panel.html``)."""
    on = bool(ctx.settings.onboard_intake)
    hosts = intake.git_hosts(ctx.settings)
    return {
        "ik": {
            "node_id": node_id,
            "on": on,
            "attempts": service(ctx).attempts(node_id) if on else [],
            "max_mb": int(ctx.settings.onboard_intake_max_mb),
            "git_hosts": list(hosts),
            "can_edit": agent_detail.can(me, "systems.edit"),
        }
    }


def parse_multipart(
    content_type: str, body: bytes
) -> tuple[list[tuple[str, bytes]], dict[str, str]]:
    """([(file name, bytes)], {text field: value}) of a ``multipart/form-data`` body."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise intake.IntakeError("bad_body", "the body must be multipart/form-data")
    try:
        raw = b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n"
        msg = BytesParser(policy=policy.HTTP).parsebytes(raw + body)
        parts = list(msg.iter_parts()) if msg.is_multipart() else []
    except Exception:  # noqa: BLE001 - a body that does not parse is not an upload
        raise intake.IntakeError("bad_body", "the multipart body cannot be read") from None
    files: list[tuple[str, bytes]] = []
    fields: dict[str, str] = {}
    for part in parts:
        with contextlib.suppress(Exception):  # a part we cannot read is left out
            data = bytes(part.get_payload(decode=True) or b"")
            filename = part.get_filename()
            if filename is not None:
                if data or filename:
                    files.append((str(filename), data))
            else:
                label = str(part.get_param("name", header="content-disposition") or "")
                fields[label[:64]] = data.decode("utf-8", "replace")[:2000]
    return files, fields


def _same_site(request: Request) -> None:
    """A browser form post from another site is refused (the htmx header is not there on the
    JSON API). A client that sends neither Origin nor Sec-Fetch-Site (curl, a script) passes."""
    site = request.headers.get("sec-fetch-site", "")
    if site and site not in ("same-origin", "none"):
        raise intake.IntakeError("cross_site", "the upload must come from the console page")
    origin = request.headers.get("origin", "")
    if origin and origin != "null" and urlsplit(origin).netloc != request.headers.get("host", ""):
        raise intake.IntakeError("cross_site", "the upload must come from the console page")


async def _read_body(request: Request, ctx: ConsoleContext) -> bytes:
    limit = intake.max_bytes(ctx.settings) + FORM_SLACK
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise intake.IntakeError("too_large", f"the upload is larger than {limit // 1_048_576} MB")
    body = await request.body()
    if len(body) > limit:
        raise intake.IntakeError("too_large", f"the upload is larger than {limit // 1_048_576} MB")
    return body


def _actor(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("taking in a source needs a signed-in person")
    return str(me.user_id)


def _submit(
    ctx: ConsoleContext,
    node_id: str,
    actor: str,
    files: list[tuple[str, bytes]],
    fields: dict[str, str],
    git_url: str,
    workspace: str,
) -> dict[str, Any]:
    svc = service(ctx)
    if files:
        name, data = files[0]
        return svc.submit_zip(node_id, data, name, actor)
    if git_url.strip():
        return svc.submit_git(node_id, git_url, actor)
    if workspace.strip():
        return svc.submit_workspace(node_id, workspace, actor)
    raise intake.IntakeError("nothing_to_take_in", "send a zip file or a git URL")


# ------------------------------------------------------------------------------- JSON API


@api_router.get("/intake/{node_id}", dependencies=[Depends(needs("systems.view"))])
def list_attempts(node_id: str, ctx: ConsoleContext = _CTX) -> Any:
    intake.require_on(ctx.settings)
    return {"node_id": node_id, "attempts": service(ctx).attempts(node_id)}


@api_router.post("/intake/{node_id}", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def post_attempt(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    intake.require_on(ctx.settings)
    intake.check_node_id(node_id)
    actor = _actor(me)
    ctype = request.headers.get("content-type", "")
    files: list[tuple[str, bytes]] = []
    fields: dict[str, str] = {}
    git_url = workspace = ""
    if ctype.lower().startswith("application/json"):
        raw = await _read_body(request, ctx)
        try:
            doc = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            raise intake.IntakeError("bad_body", "the body must be JSON") from None
        if not isinstance(doc, dict):
            raise intake.IntakeError("bad_body", "the body must be a JSON object")
        git_url = str(doc.get("git_url") or "")
        workspace = str(doc.get("workspace") or doc.get("workspace_path") or "")
    else:
        _same_site(request)
        files, fields = parse_multipart(ctype, await _read_body(request, ctx))
        git_url = fields.get("git_url", "")
        workspace = fields.get("workspace", "")
    attempt = await _call(_submit, ctx, node_id, actor, files, fields, git_url, workspace)
    request.state.audit_detail = f"{attempt['source_kind']} n={attempt['n']}"
    return JSONResponse(status_code=201, content=attempt)


# ------------------------------------------------------------------------------- console


@router.get(
    "/intake/{node_id}", response_class=HTMLResponse, dependencies=[Depends(needs("systems.view"))]
)
async def intake_panel(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    intake.require_on(ctx.settings)
    intake.check_node_id(node_id)
    data = await _call(panel_data, ctx, me, node_id)
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_intake_panel.html", **data)
    return render(request, ctx, me, "intake.html", section="candidates", **data)


@router.post(
    "/intake/{node_id}", response_class=HTMLResponse, dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def intake_post(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    intake.require_on(ctx.settings)
    intake.check_node_id(node_id)
    actor = _actor(me)
    files, fields = parse_multipart(
        request.headers.get("content-type", ""), await _read_body(request, ctx)
    )
    attempt = await _call(
        _submit, ctx, node_id, actor, files, fields, fields.get("git_url", ""), ""
    )
    request.state.audit_detail = f"{attempt['source_kind']} n={attempt['n']}"
    data = await _call(panel_data, ctx, me, node_id)
    resp = render(request, ctx, me, "_intake_panel.html", **data)
    note = (
        f"{node_id}: attempt {attempt['n']} stored, {attempt['file_count']} file(s); "
        f"{attempt['detail'] or ''}"
    )
    resp.body = resp.body + message_html(note, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp
