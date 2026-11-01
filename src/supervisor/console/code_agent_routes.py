# ruff: noqa: E501
"""Source analysis routes (flag ``CODE_AGENT_ENABLED``): the Source analysis panel of a candidate, of
an agent and of the register workflow, and the JSON API. The routers are always mounted; with the
flag off every route answers HTTP 400 ``code_agent_off`` (nothing is read or written).

* ``GET  /v1/code-analysis/{node_id}``           status and newest report (``systems.view``)
* ``POST /v1/code-analysis/{node_id}/run``       start a background run on the newest attempt (202)
* ``POST /v1/code-analysis/{node_id}/apply``     "Use in assessment" (``systems.edit``)
* ``GET  /console/code-analysis/{node_id}``      the panel (htmx fragment; polls while a run goes)
* ``POST /console/code-analysis/{node_id}/run``  the **Run analysis** button (htmx only)
* ``POST /console/code-analysis/{node_id}/apply`` the **Use in assessment** button (htmx only)
* ``GET  /console/code-analysis/{node_id}/file`` the stored scrubbed file, one line marked

Every POST writes two ``console_action`` rows (``@audited``). A refusal is HTTP 400 with
``<code>: <text>``."""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import agent_detail
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import (
    ConsoleInputError,
    _call,
    _htmx_only,
    audited,
    message_html,
    render,
)
from supervisor.onboard import intake
from supervisor.onboard.codeagent import service as ca
from supervisor.onboard.codeagent.models import KINDS, CodeAnalysisReport, Finding
from supervisor.onboard.codeagent.workspace import ToolError, Workspace

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
FEEDS = {
    "tool",
    "model",
    "external_url",
    "approval_point",
    "dataset",
    "claim",
    "secret_use",
    "weak_spot",
}


def service(ctx: ConsoleContext) -> ca.CodeAgentService:
    return ca.CodeAgentService(ctx.settings, ctx.state, ctx.clock, tables=ctx.tables)


# ------------------------------------------------------------------------------- view model


def _attr_text(f: Finding) -> str:
    return ", ".join(
        f"{k}={'yes' if v is True else 'no' if v is False else v}" for k, v in f.attrs.items()
    )


def cards_of(rep: CodeAnalysisReport) -> dict[str, Any]:
    tools = rep.of("tool")
    irrev = [f for f in tools if f.attrs.get("irreversible") is True]
    unguarded = [f for f in irrev if f.attrs.get("approval") is not True]
    egress = rep.of("egress")
    external = [f for f in egress if f.attrs.get("internal") is not True]
    pii = {f.name.split(":")[-1] for f in rep.of("pii")}
    logging_ = rep.of("logging")
    return {
        "framework": ", ".join(f.name for f in rep.of("framework")) or "-",
        "models": [
            f"{f.name} ({f.attrs.get('provider', '?')}{', pinned' if f.attrs.get('pinned') is True else ''})"
            for f in rep.of("model")
        ],
        "tools": len(tools),
        "tools_irreversible": len(irrev),
        "tools_unguarded": len(unguarded),
        "tool_rows": [
            {
                "name": f.name,
                "effect": f.attrs.get("effect", "-"),
                "irreversible": f.attrs.get("irreversible"),
                "approval": f.attrs.get("approval"),
            }
            for f in tools
        ],
        "flows": len(rep.of("data_flow")),
        "pii": len(pii),
        "egress": len(egress),
        "egress_external": len(external),
        "egress_hosts": [f.name for f in egress][:6],
        "guardrails": sorted({f.name for f in rep.of("guardrail")}),
        "hitl": len(rep.of("hitl")),
        "hitl_modes": sorted({str(f.attrs.get("mode")) for f in rep.of("hitl")}),
        "secrets": sorted({f.name for f in rep.of("secret_handling")}),
        "logging": sorted({f.name for f in logging_}),
        "logging_pii": any(f.attrs.get("logs_pii") is True for f in logging_),
    }


def groups_of(rep: CodeAnalysisReport) -> list[dict[str, Any]]:
    out = []
    for kind in KINDS:
        rows = [
            {
                "name": f.name,
                "attrs": _attr_text(f),
                "evidence": [
                    {"ref": e.ref(), "file": e.file, "line": e.line, "quote": e.quote}
                    for e in f.evidence[:3]
                ],
                "source": f.source,
                "conf": f.confidence_bp // 100,
                "corroborated": f.corroborated,
            }
            for f in rep.findings
            if f.kind == kind
        ]
        if rows:
            out.append({"kind": kind, "rows": rows})
    return out


def _node_name(ctx: ConsoleContext, node_id: str) -> str:
    """The inventory node's display name (the title of the page); the id when there is none."""
    try:
        row = ctx.state.get("inventory_node", {"node_id": node_id})
    except Exception:  # noqa: BLE001 - a title never breaks the page
        row = None
    if row:
        return str(row.get("display_name") or row.get("name") or node_id)
    return node_id


def panel_data(
    ctx: ConsoleContext, me: AuthPrincipal, node_id: str, compact: bool = False
) -> dict[str, Any]:
    """Template variables of the panel (``_code_agent_panel.html``)."""
    on = bool(getattr(ctx.settings, "code_agent_enabled", False))
    ca_: dict[str, Any] = {
        "node_id": node_id,
        "node_name": _node_name(ctx, node_id),
        "on": on,
        "can_edit": agent_detail.can(me, "systems.edit"),
        "status": None,
        "report": None,
        "cards": None,
        "groups": [],
        "downstream": [],
        "rejected": {},
        "polling": False,
        "stop_reason": "",
        "compact": compact,
    }
    if on:
        svc = service(ctx)
        st = svc.status(node_id)
        ca_["status"] = st
        ca_["polling"] = st["state"] in ("queued", "running")
        rep = svc.report(node_id)
        if rep is not None:
            ca_["report"] = rep
            ca_["cards"] = cards_of(rep)
            ca_["groups"] = groups_of(rep)
            ca_["downstream"] = svc.downstream(rep) if rep.mode == "agent" else []
            ca_["rejected"] = dict(Counter(r.reason for r in rep.rejected))
            ca_["feeds"] = FEEDS
    return {"ca": ca_}


def _public(ctx: ConsoleContext, node_id: str) -> dict[str, Any]:
    svc = service(ctx)
    rep = svc.report(node_id)
    return {"status": svc.status(node_id), "report": rep.model_dump(mode="json") if rep else None}


# ------------------------------------------------------------------------------- JSON API


@api_router.get("/code-analysis/{node_id}", dependencies=[Depends(needs("systems.view"))])
def get_analysis(node_id: str, ctx: ConsoleContext = _CTX) -> Any:
    ca.require_on(ctx.settings)
    intake.check_node_id(node_id)
    return _public(ctx, node_id)


@api_router.post("/code-analysis/{node_id}/run", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def post_run(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    ca.require_on(ctx.settings)
    st = await _call(service(ctx).start, node_id, None, str(me.user_id or me.kind))
    request.state.audit_detail = f"attempt={st['attempt_n']}"
    return JSONResponse(status_code=202, content=st)


@api_router.post("/code-analysis/{node_id}/apply", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def post_apply(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    ca.require_on(ctx.settings)
    res = await _call(service(ctx).apply, node_id, None, str(me.user_id or me.kind))
    request.state.audit_detail = f"attempt={res['attempt_n']} facts={res['facts_written']}"
    return JSONResponse(status_code=201, content=res)


# ------------------------------------------------------------------------------- console


@router.get(
    "/code-analysis/{node_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def analysis_panel(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    ca.require_on(ctx.settings)
    intake.check_node_id(node_id)
    compact = request.query_params.get("compact") == "1"  # the narrow candidate drawer
    data = await _call(panel_data, ctx, me, node_id, compact)
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_code_agent_panel.html", **data)
    return render(request, ctx, me, "code_agent.html", section="candidates", **data)


@router.post(
    "/code-analysis/{node_id}/run",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def analysis_run(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    ca.require_on(ctx.settings)
    intake.check_node_id(node_id)
    st = await _call(service(ctx).start, node_id, None, str(me.user_id or me.kind))
    request.state.audit_detail = f"attempt={st['attempt_n']}"
    data = await _call(panel_data, ctx, me, node_id)
    return render(request, ctx, me, "_code_agent_panel.html", **data)


@router.post(
    "/code-analysis/{node_id}/apply",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def analysis_apply(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    ca.require_on(ctx.settings)
    intake.check_node_id(node_id)
    res = await _call(service(ctx).apply, node_id, None, str(me.user_id or me.kind))
    request.state.audit_detail = f"attempt={res['attempt_n']} facts={res['facts_written']}"
    data = await _call(panel_data, ctx, me, node_id)
    resp = render(request, ctx, me, "_code_agent_panel.html", **data)
    resp.body = (
        resp.body
        + message_html(
            f"{node_id}: {res['facts_written']} fact(s) written to the Facts card",
            ok=True,
            oob=True,
        ).encode()
    )
    resp.headers["content-length"] = str(len(resp.body))
    return resp


def file_view(ctx: ConsoleContext, node_id: str, n: int, path: str, line: int) -> dict[str, Any]:
    """The stored scrubbed file as numbered lines. Path-confined: only a key of the stored tree."""
    svc = service(ctx)
    tree = svc.tree_for(node_id, n)
    ws = Workspace.from_tree(tree)
    try:
        ws.resolve(path)
    except ToolError:
        raise ConsoleInputError("that file is not in the stored source") from None
    rows = ws.lines[path]
    lo = max(1, line - 30)
    hi = min(len(rows), line + 30)
    return {
        "node_id": node_id,
        "n": n,
        "path": path,
        "line": line,
        "total": len(rows),
        "rows": [(i, rows[i - 1]) for i in range(lo, hi + 1)],
    }


@router.get(
    "/code-analysis/{node_id}/file",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def analysis_file(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    ca.require_on(ctx.settings)
    intake.check_node_id(node_id)
    q = request.query_params
    try:
        n = int(q.get("n", "0"))
        line = int(q.get("line", "1"))
    except ValueError:
        raise ConsoleInputError("n and line must be numbers") from None
    data = await _call(file_view, ctx, node_id, n, str(q.get("path", "")), line)
    return render(request, ctx, me, "code_agent_file.html", section="candidates", fv=data)
