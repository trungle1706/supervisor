"""Guardian kit routes (GUARDIAN_KIT): the "Connect your app to Guardian" block of the Guardians
step of the registration and of the Guardians tab of a system. The router is always mounted; with
the setting off every route answers HTTP 400 ``guardian_kit_off`` (nothing is read or written).

* ``GET  /console/guardian-kit/{system_id}``
    the block (an htmx fragment; a full page without htmx); ``?src=`` names the source key when
    the system record has none
* ``GET  /console/guardian-kit/{system_id}/guardian_client.py``
    the one code file, as a download
* ``POST /console/guardian-kit/{system_id}/check``
    **Check my code again** (``systems.edit``), htmx only; ``fetch=1`` clones the git address first

The block is loaded by htmx when the page opens, so the two pages that show it only need the
include line ``_guardian_kit.html``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console import agent_detail, attach_view
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import ConsoleInputError, _call, _htmx_only, audited, form, render
from supervisor.core.errors import SupervisorError
from supervisor.onboard import guardian_kit as gk
from supervisor.onboard import intake

router = APIRouter(prefix="/console", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)

FRAMEWORK_LABEL = {
    "langgraph": "LangGraph",
    "deepagents": "Deep Agents (LangGraph)",
    "langchain": "LangChain",
    "crewai": "CrewAI",
    "fastmcp": "FastMCP",
    "llamaindex": "LlamaIndex",
    "openai_sdk": "OpenAI SDK",
    "anthropic_sdk": "Anthropic SDK",
    "databricks_agents": "Databricks Agent (MLflow)",
    "fastapi": "FastAPI",
}
_AGENT_ENV = re.compile(
    r"SUPERVISOR_AGENT_ID[\"']?\s*(?:[:=]|\n\s*(?:-\s*)?value:)\s*[\"']?([A-Za-z0-9_.:@-]{1,128})"
)
_SLUG = re.compile(r"[^a-z0-9_.-]+")


def service(ctx: ConsoleContext) -> gk.GuardianKitService:
    return gk.GuardianKitService(ctx.settings, ctx.state, ctx.clock, ctx.runtime.chain)


def _off(ctx: ConsoleContext) -> None:
    gk.require_on(ctx.settings)


def _system(ctx: ConsoleContext, system_id: str) -> dict[str, Any]:
    try:
        return dict(ctx.systems.get(system_id))
    except SupervisorError:
        raise ConsoleInputError(f"AI system {system_id} does not exist") from None


def _tags(system: dict[str, Any]) -> dict[str, Any]:
    tags = system.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = {}
    return tags if isinstance(tags, dict) else {}


def _known_key(ctx: ConsoleContext, system: dict[str, Any]) -> str:
    """The source key the system record knows: the node it was registered from, its first node
    component, or the key of its newest stored check (a draft that had no node)."""
    node = str(_tags(system).get("node_id") or "")
    if not node:
        node = next(
            (str(c["ref_id"]) for c in system.get("components", []) if c["ref_kind"] == "node"), ""
        )
    if not node:
        last = service(ctx).latest(str(system["system_id"]))
        node = str(last["node_id"]) if last else ""
    return node


def _draft_of_system(ctx: ConsoleContext, key: str, system_id: str) -> bool:
    """True when ``key`` is the id of a registration draft whose system record is ``system_id``."""
    got = ctx.state.get("registration_draft", {"draft_id": key})
    data = (got or {}).get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = {}
    return isinstance(data, dict) and str(data.get("sys") or "") == system_id


def source_key_of(ctx: ConsoleContext, system: dict[str, Any], src: str = "") -> str:
    """The key the source attempts are stored under. The system record decides when it knows the
    key; a ``src`` of the page (the register step passes it) is accepted only when it is that key
    or the id of the draft that made this system. Any other ``src`` is refused (HTTP 400)."""
    known = _known_key(ctx, system)
    if src:
        intake.check_node_id(src)
        if known and src != known:
            raise ConsoleInputError("src: this source does not belong to this AI system")
        if not known and not _draft_of_system(ctx, src, str(system["system_id"])):
            raise ConsoleInputError("src: this source does not belong to this AI system")
        return src
    return intake.check_node_id(known) if known else ""


def agent_id_of(system: dict[str, Any], tree: Path | None) -> str:
    """The agent id the code file is made for: the one typed at registration, else the one in the
    app file of the source, else the system name as a plain id."""
    typed = str(_tags(system).get("agent_id") or "")
    if gk.valid_agent_id(typed):
        return typed
    if tree is not None:
        for name in ("app.yaml", "app.yml"):
            try:
                text = (tree / name).read_text(encoding="utf-8")[:200_000]
            except OSError:
                continue
            m = _AGENT_ENV.search(text)
            if m and gk.valid_agent_id(m.group(1)):
                return m.group(1)
    slug = re.sub(r"-{2,}", "-", _SLUG.sub("-", str(system.get("name") or "").lower()))
    slug = slug.strip("-.")[:100]
    return slug if gk.valid_agent_id(slug) else "FILL-ME-agent-id"


def panel_data(
    ctx: ConsoleContext, me: AuthPrincipal, system_id: str, src: str, base_url: str
) -> dict[str, Any]:
    """Template variables of the block (``_guardian_kit_panel.html``)."""
    system = _system(ctx, system_id)
    svc = service(ctx)
    node = source_key_of(ctx, system, src)
    on_intake = bool(ctx.settings.onboard_intake)
    attempts = svc.attempts(node) if node and on_intake else []
    newest = attempts[0] if attempts else None
    n = newest["n"] if newest else None
    tree = svc.tree_path(node, n) if node and n else None
    tools = svc.tools_of(node, n) if node else []
    last = svc.latest(system_id)
    agent_id = agent_id_of(system, tree)
    version = "1.0.0"
    framework = svc.framework_of(node, n) if node and n else "custom"
    public = str(getattr(ctx.settings, "collectors_public_url", "") or "").strip().rstrip("/")
    gate_url = public or base_url.rstrip("/")
    how = gk.guide(
        agent_id=agent_id,
        tools=tools,
        framework=framework,
        credential=attach_view.credential_kind(ctx.settings),
        gate_url=gate_url,
    )
    by_name = {r["name"]: r for r in (last["detail"].get("tools", []) if last else [])}
    rows = []
    for t in tools:
        got = by_name.get(t.name)
        rows.append(
            {
                "name": t.name,
                "risk": t.risk,
                "state": got["state"] if got else "unknown",
                "file": (got or {}).get("file") or t.file,
                "line": (got or {}).get("line") or t.line,
                "found_name": (got or {}).get("found_name"),
                "found_risk": (got or {}).get("found_risk"),
            }
        )
    git = next((a for a in attempts if a["source_kind"] == "git"), None)
    can_edit = agent_detail.can(me, "systems.edit")
    status = last["status"] if last else "not_checked"
    return {
        "gk": {
            "system_id": system_id,
            "src": node,
            "on_intake": on_intake,
            "status": status,
            "last": last,
            "checked_attempt": next(
                (a for a in attempts if last and a["n"] == last["attempt_n"]), None
            ),
            "newer": bool(newest and last and newest["n"] > last["attempt_n"]),
            "newest": newest,
            "rows": rows,
            "extras": (last or {}).get("detail", {}).get("extras", []),
            "notes": (last or {}).get("detail", {}).get("notes", []),
            "guide": how,
            "framework_label": FRAMEWORK_LABEL.get(how["framework"], ""),
            "can_edit": can_edit,
            "can_git": bool(
                can_edit and git is not None and on_intake and intake.git_hosts(ctx.settings)
            ),
            "has_source": bool(newest),
            "file_text": gk.client_source(agent_id, version, {t.name: t.risk for t in tools}),
        }
    }


def _check(ctx: ConsoleContext, me: AuthPrincipal, system_id: str, src: str, fetch: bool) -> dict:
    system = _system(ctx, system_id)
    node = source_key_of(ctx, system, src)
    if not node:
        raise gk.KitError("no_source", "there is no stored source; add the code first")
    if me.kind != "user":
        raise PermissionDenied("checking the code needs a signed-in person")
    intake.require_on(ctx.settings)
    return service(ctx).run_check(system_id, node, str(me.user_id), fetch_git=fetch)


def _src_param(request: Request, form: dict[str, str] | None = None) -> str:
    raw = (form or {}).get("src") or request.query_params.get("src") or ""
    if raw and not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", raw):
        raise ConsoleInputError("src: the source key must be 1 to 128 of A-Z a-z 0-9 _ . : @ -")
    return raw


@router.get(
    "/guardian-kit/{system_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def kit_panel(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    data = await _call(panel_data, ctx, me, system_id, _src_param(request), str(request.base_url))
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_guardian_kit_panel.html", **data)
    return render(request, ctx, me, "guardian_kit.html", section="systems", **data)


@router.get(
    "/guardian-kit/{system_id}/guardian_client.py",
    dependencies=[Depends(needs("systems.view"))],
)
async def kit_file(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    data = await _call(panel_data, ctx, me, system_id, _src_param(request), str(request.base_url))
    return Response(
        data["gk"]["file_text"],
        media_type="text/x-python; charset=utf-8",
        headers={
            "content-disposition": f'attachment; filename="{gk.FILE_NAME}"',
            "cache-control": "no-store",
        },
    )


@router.post(
    "/guardian-kit/{system_id}/check",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def kit_check(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    _off(ctx)
    posted = await form(request)
    src = _src_param(request, posted)
    fetch = posted.get("fetch") == "1"
    res = await _call(_check, ctx, me, system_id, src, fetch)
    request.state.audit_detail = f"attempt={res['attempt_n']} status={res['status']}"
    data = await _call(panel_data, ctx, me, system_id, src, str(request.base_url))
    return render(request, ctx, me, "_guardian_kit_panel.html", **data)
