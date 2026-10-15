"""Reviewer console routes (``/console``): server-rendered Jinja2 pages + htmx partials.

* Every POST is an htmx call (``HX-Request: true`` is required: a cross-site form cannot set
  it, so this doubles as CSRF protection for the dev cookie and the SSO session).
* User errors (``SupervisorError``: bad transition, missing role, same approver twice, stale
  row_version, ...) answer HTTP 400 with a message partial that htmx shows in ``#flash``
  (``static/console.js``). See ``console.errors``.
* Every mutating action records actor + auth_method: in ``case_event`` and the chain (case
  service), or in a ``console_gate_action`` chain record (pause / resume / quarantine /
  release, which go to the gateway state machine in-process).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from starlette.concurrency import run_in_threadpool

from supervisor import __version__
from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.dev_header import COOKIE as DEV_COOKIE
from supervisor.cases.service import (
    RESOLUTIONS,
    SEVERITIES,
    TRANSITIONS,
    TWO_PERSON_SEVERITIES,
    WORKFLOW_ROLES,
    CaseError,
    PermissionDenied,
    require,
)
from supervisor.console import auditpack, readmodels, views
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.i18n import LANGS, pick_lang, translator
from supervisor.core.canonical import format_ts
from supervisor.core.errors import SupervisorError
from supervisor.evidence.casefile.render_html import fmt_ict, fmt_utc
from supervisor.jobs import case_intake

router = APIRouter(prefix="/console", tags=["console"])
log = logging.getLogger("supervisor.console")

HERE = Path(__file__).parent
STATIC = {
    "htmx.min.js": "application/javascript",
    "console.js": "application/javascript",
    "console.css": "text/css",
    "htmx.LICENSE.txt": "text/plain",
}
FONTS = (
    "plus-jakarta-sans-latin.woff2",
    "plus-jakarta-sans-latin-ext.woff2",
    "plus-jakarta-sans-vietnamese.woff2",
    "jetbrains-mono-latin.woff2",
    "jetbrains-mono-latin-ext.woff2",
    "jetbrains-mono-vietnamese.woff2",
    "OFL-PlusJakartaSans.txt",
    "OFL-JetBrainsMono.txt",
)
LANG_COOKIE = "sv_lang"
MAX_FORM_BYTES = 64 * 1024
_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
VIEW_ROLES = ("reviewer", "approver", "owner", "auditor", "admin")
EXPORT_ROLES = ("auditor", "reviewer", "approver", "admin")
GATE_ROLES: dict[str, tuple[str, ...]] = {
    "pause": ("reviewer", "approver", "owner", "admin"),  # D04: any on-call reviewer
    "resume": ("reviewer", "owner", "admin"),  # D04: owner + reviewer, two people
    "quarantine": ("admin",),
    "release": ("admin",),
}

_env = Environment(
    loader=FileSystemLoader(str(HERE / "templates")),
    autoescape=select_autoescape(["html", "j2"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["utc"] = fmt_utc
_env.filters["ict"] = fmt_ict
_env.filters["metric"] = lambda v, name="": views.metric_cell(name, v)
_env.filters["hhmm"] = readmodels.hhmm
_env.filters["hhmmss"] = lambda v: readmodels.hhmm(v, seconds=True)
_env.filters["vnd"] = lambda v: "-" if v is None else f"{int(v):,}"


def ctx_dep() -> ConsoleContext:
    return get_context()


_CTX = Depends(ctx_dep)
_ME = Depends(current_principal)


# ---------------------------------------------------------------------------- helpers


class ConsoleInputError(SupervisorError):
    """Bad form input (HTTP 400)."""


def _lang(request: Request, ctx: ConsoleContext) -> str:
    return pick_lang(
        request.query_params.get("lang"),
        request.cookies.get(LANG_COOKIE),
        ctx.settings.console_lang,
    )


def render(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    template: str,
    status_code: int = 200,
    **data: Any,
) -> HTMLResponse:
    lang = _lang(request, ctx)
    cache: dict[str, Any] = {}

    def shell() -> dict[str, Any]:  # header data, computed only when a full page asks
        if "v" not in cache:
            cache["v"] = readmodels.shell(ctx, me)
        return cache["v"]

    data.setdefault("section", "")
    body = _env.get_template(template).render(
        t=translator(lang),
        dur=lambda secs: views.duration_text(secs, lang),
        shell=shell,
        lang=lang,
        other_lang="vi" if lang == "en" else "en",
        me=me,
        mode=ctx.settings.supervisor_mode,
        auth_kind=ctx.provider.name,
        known_users=ctx.provider.known_users(),
        now=ctx.clock.now(),
        version=__version__,
        path=request.url.path,
        **data,
    )
    resp = HTMLResponse(body, status_code=status_code)
    q = request.query_params.get("lang")
    if q in LANGS:
        resp.set_cookie(LANG_COOKIE, q, samesite="strict", httponly=True)
    return resp


def message_html(message: str, *, ok: bool = False, oob: bool = False) -> str:
    """The #flash partial (also used by the app-level 400 handler)."""
    from markupsafe import escape

    cls = "msg-ok" if ok else "msg-error"
    role = "status" if ok else "alert"
    inner = f'<div class="msg {cls}" role="{role}">{escape(message)}</div>'
    if oob:
        return f'<div id="flash" hx-swap-oob="true">{inner}</div>'
    return inner


def _htmx_only(request: Request) -> None:
    if request.headers.get("hx-request") != "true":
        raise ConsoleInputError("console actions must come from the console page (htmx)")


async def form(request: Request) -> dict[str, str]:
    """Parse an urlencoded form (no python-multipart dependency)."""
    _htmx_only(request)
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        raise ConsoleInputError("form is too large")
    try:
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=False)
    except UnicodeDecodeError:
        raise ConsoleInputError("form must be UTF-8") from None
    return {k: v[-1] for k, v in parsed.items()}


def _version(data: Mapping[str, str]) -> int:
    raw = data.get("row_version", "")
    if not raw.isdigit():
        raise ConsoleInputError("row_version is missing; reload the page")
    return int(raw)


def _check_id(value: str, what: str) -> str:
    if not _ID.match(value or ""):
        raise ConsoleInputError(f"invalid {what}")
    return value


def _view(me: AuthPrincipal) -> None:
    if me.kind == "user" and not me.has(*VIEW_ROLES):
        raise PermissionDenied(f"{me.user_id} has no console role")


async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await run_in_threadpool(fn, *args, **kwargs)


# ---------------------------------------------------------------------------- static


@router.get("/static/fonts/{name}")
def static_font(name: str) -> Response:
    if name not in FONTS:
        return Response("not found", status_code=404, media_type="text/plain")
    media = "font/woff2" if name.endswith(".woff2") else "text/plain"
    resp = FileResponse(HERE / "static" / "fonts" / name, media_type=media)
    resp.headers["cache-control"] = "public, max-age=604800"
    return resp


@router.get("/static/{name}")
def static(name: str) -> Response:
    media = STATIC.get(name)
    if media is None:
        return Response("not found", status_code=404, media_type="text/plain")
    return FileResponse(HERE / "static" / name, media_type=media)


# ---------------------------------------------------------------------------- queue


def _queue_data(ctx: ConsoleContext, request: Request) -> dict[str, Any]:
    sev = request.query_params.get("severity") or None
    if sev is not None and sev not in SEVERITIES:
        raise ConsoleInputError("unknown severity filter")
    status = request.query_params.get("status") or "open"
    if status not in ("open", "closed", "all"):
        raise ConsoleInputError("unknown status filter")
    agent = request.query_params.get("agent") or None
    if agent is not None:
        _check_id(agent, "agent filter")
    statuses = None
    if status == "open":
        statuses = [s for s in (*TRANSITIONS.keys(), "escalated", "resolved")]
    elif status == "closed":
        statuses = ["closed"]
    rows = ctx.cases.list_cases(statuses=statuses, severity=sev, agent_id=agent)
    now = ctx.clock.now()
    items = []
    for r in rows:
        kinds = sorted({link["source_kind"] for link in ctx.cases.links(r["case_id"])})
        items.append(
            {
                **r,
                "sources": kinds,
                "clock": views.countdown(r["report_due_at"], now)
                if r["status"] != "closed"
                else {"text": "-", "cls": "", "overdue": False},
            }
        )
    agents = sorted({a["agent_id"] for a in ctx.state.query("agent")})
    return {
        "items": items,
        "filters": {"severity": sev or "", "status": status, "agent": agent or ""},
        "severities": SEVERITIES,
        "agent_ids": agents,
    }


@router.get("/", response_class=HTMLResponse)
async def overview(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _view(me)
    now = ctx.clock.now()
    ov = await _call(readmodels.overview, ctx, now)
    return render(
        request,
        ctx,
        me,
        "overview.html",
        section="overview",
        ov=ov,
        greet_key=readmodels.greeting_key(now),
    )


@router.get("/cases", response_class=HTMLResponse)
async def queue(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Response:
    _view(me)
    data = await _call(_queue_data, ctx, request)
    return render(request, ctx, me, "queue.html", section="cases", **data)


@router.get("/queue/rows", response_class=HTMLResponse)
async def queue_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _view(me)
    data = await _call(_queue_data, ctx, request)
    return render(request, ctx, me, "_queue_rows.html", **data)


# ---------------------------------------------------------------------------- case


def _case_data(ctx: ConsoleContext, case_id: str) -> dict[str, Any]:
    _check_id(case_id, "case id")
    case = ctx.cases.get(case_id)
    cf = ctx.cases.case_file(case_id)
    now = ctx.clock.now()
    verdicts = ctx.cases.linked_verdicts(case_id)
    trace_ids = sorted({v["trace_id"] for v in verdicts if v.get("trace_id")})
    excerpts: list[dict[str, Any]] = []
    for tid in trace_ids[:5]:
        for ev in ctx.tables.query("agent_event", {"trace_id": tid}, order_by=("ts",)):
            if ev.get("args_masked") or ev.get("result_masked"):
                excerpts.append(
                    {
                        "ts": ev["ts"],
                        "agent_id": ev["agent_id"],
                        "event_type": ev["event_type"],
                        "tool_name": ev.get("tool_name"),
                        "status": ev.get("status"),
                        "args": (ev.get("args_masked") or "")[:600],
                        "result": (ev.get("result_masked") or "")[:600],
                    }
                )
    excerpts = excerpts[:30]
    lane = f"agent:{case['agent_id']}"
    status = case["status"]
    next_steps = list(TRANSITIONS.get(status, ()))
    approvals = ctx.cases._approvals(case_id)
    return {
        "case": case,
        "cf": cf,
        "events": ctx.cases.events(case_id),
        "signoffs": ctx.cases.signoffs(case_id),
        "approvals": approvals,
        "links": ctx.cases.links(case_id),
        "verdicts": verdicts,
        "excerpts": excerpts,
        "report_clock": views.countdown(cf.sbv.report_due_at, now) if status != "closed" else None,
        "remediation_clock": views.countdown(cf.sbv.remediation_due_at, now, 5 * 86400)
        if status != "closed"
        else None,
        "lane": lane,
        "verify": ctx.last_verify.get(lane) or ctx.last_verify.get("all"),
        "next_steps": next_steps,
        "resolutions": RESOLUTIONS,
        "two_person": case["severity"] in TWO_PERSON_SEVERITIES,
        "assignable": [u.user_id for u in ctx.provider.known_users() if u.has("reviewer", "admin")],
    }


@router.get("/cases/{case_id}", response_class=HTMLResponse)
async def case_page(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _view(me)
    data = await _call(_case_data, ctx, case_id)
    return render(request, ctx, me, "case.html", **data)


async def _case_action(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    case_id: str,
    action: Callable[[dict[str, str]], Any],
    done: str,
) -> Response:
    _check_id(case_id, "case id")
    data = await form(request)
    await _call(action, data)
    page = await _call(_case_data, ctx, case_id)
    resp = render(request, ctx, me, "_case_body.html", **page)
    t = translator(_lang(request, ctx))
    resp.body = resp.body + message_html(f"{t('saved')} {done}", ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


@router.post("/cases/{case_id}/assign", response_class=HTMLResponse)
async def assign(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    def act(d: dict[str, str]) -> Any:
        return ctx.cases.assign(case_id, d.get("assignee", ""), me, _version(d))

    return await _case_action(request, ctx, me, case_id, act, "assign")


@router.post("/cases/{case_id}/comment", response_class=HTMLResponse)
async def comment(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    def act(d: dict[str, str]) -> Any:
        return ctx.cases.comment(case_id, d.get("text", ""), me, _version(d))

    return await _case_action(request, ctx, me, case_id, act, "comment")


@router.post("/cases/{case_id}/itsm", response_class=HTMLResponse)
async def itsm(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    def act(d: dict[str, str]) -> Any:
        return ctx.cases.set_itsm_ref(case_id, d.get("itsm_ref", ""), me, _version(d))

    return await _case_action(request, ctx, me, case_id, act, "itsm_ref")


@router.post("/cases/{case_id}/transition", response_class=HTMLResponse)
async def transition(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    def act(d: dict[str, str]) -> Any:
        to = d.get("to", "")
        if to not in ("triaged", "contained", "closed"):
            raise ConsoleInputError("unknown target state")
        return ctx.cases.transition(
            case_id,
            to,
            me,
            _version(d),
            note=d.get("note", ""),
            assignee=d.get("assignee") or None,
            resolution=d.get("resolution") or None,
        )

    return await _case_action(request, ctx, me, case_id, act, "transition")


@router.post("/cases/{case_id}/verify", response_class=HTMLResponse)
async def verify_case_lane(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _view(me)
    _htmx_only(request)
    case = await _call(ctx.cases.get, _check_id(case_id, "case id"))
    result = await _call(auditpack.verify_chain, ctx, f"agent:{case['agent_id']}")
    return render(request, ctx, me, "_verify_result.html", verify=result)


# ---------------------------------------------------------------------------- sign-off


@router.get("/cases/{case_id}/signoff", response_class=HTMLResponse)
async def signoff_page(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _view(me)
    data = await _call(_case_data, ctx, case_id)
    return render(request, ctx, me, "signoff.html", **data)


@router.post("/cases/{case_id}/signoff", response_class=HTMLResponse)
async def signoff(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _check_id(case_id, "case id")
    d = await form(request)
    if d.get("affirm") != "yes":
        raise ConsoleInputError("tick the box to sign the statement as yourself")
    await _call(
        ctx.cases.sign_off, case_id, me, d.get("decision", ""), d.get("reason", ""), _version(d)
    )
    page = await _call(_case_data, ctx, case_id)
    resp = render(request, ctx, me, "_signoff_panel.html", **page)
    resp.body = resp.body + message_html("Sign-off recorded.", ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


# ---------------------------------------------------------------------------- agents


def _agents_data(ctx: ConsoleContext) -> dict[str, Any]:
    states = ctx.gateway.states
    rows = []
    for a in sorted(ctx.state.query("agent"), key=lambda r: r["agent_id"]):
        try:
            desc = states.describe(a["agent_id"])
        except SupervisorError:
            desc = {"state": a["gate_state"], "pending_resume": []}
        cov = views.coverage_bp(ctx.state.query("coverage", {"agent_id": a["agent_id"]}))
        open_cases = [
            c for c in ctx.cases.list_cases(agent_id=a["agent_id"]) if c["status"] != "closed"
        ]
        rows.append(
            {
                **a,
                "state": desc["state"],
                "pending": desc.get("pending_resume") or [],
                "coverage_bp": cov,
                "open_cases": len(open_cases),
            }
        )
    return {"agents": rows}


@router.get("/agents", response_class=HTMLResponse)
async def agents(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Response:
    _view(me)
    data = await _call(_agents_data, ctx)
    return render(request, ctx, me, "agents.html", **data)


def _policy_precheck(ctx: ConsoleContext, agent_id: str, action: str, me: AuthPrincipal) -> None:
    """The gateway decides resume / release authority from the deployed policy
    (``reviewers``, ``admins``) and ``agent.owner_user``, not from console roles. Say so
    clearly when the two lists disagree (ids must match exactly, e.g. the SSO email)."""
    if action not in ("resume", "release"):
        return
    doc = ctx.gateway.states.policy.current().doc
    if action == "release":
        if me.user_id not in doc.admins:
            raise CaseError(
                f"{me.user_id} has the console admin role but is not in the policy admins "
                "list (policies/*.yaml, admins:); only a policy admin can release"
            )
        return
    row = ctx.state.get("agent", {"agent_id": agent_id})
    owner = row["owner_user"] if row else None
    if me.user_id != owner and me.user_id not in doc.reviewers:
        raise CaseError(
            f"{me.user_id} may not approve a resume of {agent_id}: the gateway needs the agent "
            f"owner ({owner or '-'}) or a reviewer listed in the policy (policies/*.yaml, "
            "reviewers:); console roles alone are not enough"
        )


def _record_gate_action(
    ctx: ConsoleContext, agent_id: str, action: str, me: AuthPrincipal, result: dict[str, Any]
) -> None:
    ctx.runtime.chain.record(
        "console_gate_action",
        f"console:{agent_id}:{action}",
        {
            "agent_id": agent_id,
            "action": action,
            "actor": me.user_id,
            "actor_kind": me.kind,
            "auth_method": me.auth_method,
            "result_state": result.get("state"),
            "result_status": result.get("status")
            or ("changed" if result.get("changed") else "unchanged"),
            "ts": format_ts(ctx.clock.now()),
        },
    )


@router.post("/agents/{agent_id}/{action}", response_class=HTMLResponse)
async def agent_action(
    agent_id: str,
    action: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _check_id(agent_id, "agent id")
    if action not in GATE_ROLES:
        raise ConsoleInputError("unknown agent action")
    d = await form(request)
    require(me, GATE_ROLES[action], f"{action} an agent")
    reason = d.get("reason", "")
    if action in ("quarantine", "release") and not reason.strip():
        raise CaseError(f"a reason is required to {action}")

    def act() -> dict[str, Any]:
        states = ctx.gateway.states
        fn = {
            "pause": states.pause,
            "resume": states.resume,
            "quarantine": states.quarantine,
            "release": states.release_quarantine,
        }[action]
        _policy_precheck(ctx, agent_id, action, me)
        result = fn(agent_id, me.user_id, reason)
        try:
            _record_gate_action(ctx, agent_id, action, me, result)
        except Exception as exc:  # noqa: BLE001 - the state change already happened
            log.error("console_gate_action evidence failed: %s", type(exc).__name__)
            result = {**result, "evidence_warning": type(exc).__name__}
        return result

    result = await _call(act)
    warn = result.get("evidence_warning")
    if result.get("status") == "pending":
        needs = result.get("needs")
        msg = f"{agent_id}: resume approval recorded; needs the {needs} (a different person)"
    else:
        msg = f"{agent_id}: {action} -> {result.get('state')}"
    if warn:
        msg += f" (WARNING: the console evidence record failed: {warn}; see the server log)"
    data = await _call(_agents_data, ctx)
    resp = render(request, ctx, me, "_agents_table.html", **data)
    resp.body = resp.body + message_html(msg, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


# ---------------------------------------------------------------------------- metrics


def _metrics_data(ctx: ConsoleContext) -> dict[str, Any]:
    rows = ctx.state.query("oversight_metric")
    rows.sort(key=lambda r: (r["agent_id"], r["metric_date"]))
    cols = views.metric_columns(rows)
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_agent.setdefault(r["agent_id"], []).append(r)
    summary = []
    for agent_id, series in sorted(by_agent.items()):
        latest = series[-1]
        summary.append(
            {
                "agent_id": agent_id,
                "metric_date": latest["metric_date"],
                "latest": latest,
                "sparks": {
                    c: views.sparkline([views.to_int(r.get(c)) for r in series]) for c in cols
                },
                "points": len(series),
            }
        )
    heads = ctx.runtime.chain.heads()
    gate = ctx.gateway.metrics.snapshot()
    return {
        "metric_cols": cols,
        "summary": summary,
        "rows": rows[-200:],
        "heads": {k: {"seq": v.seq, "entry_hash": v.entry_hash} for k, v in sorted(heads.items())},
        "entries": sum(v.seq + 1 for v in heads.values()),
        "verify": ctx.last_verify.get("all"),
        "gate": gate,
    }


@router.get("/metrics", response_class=HTMLResponse)
async def metrics(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _view(me)
    data = await _call(_metrics_data, ctx)
    return render(request, ctx, me, "metrics.html", **data)


@router.post("/intake/run", response_class=HTMLResponse)
async def intake_run(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Explicit case intake for when the scheduler is off (a GET never writes)."""
    _htmx_only(request)
    require(me, WORKFLOW_ROLES, "refresh cases")
    touched = await _call(case_intake.run, ctx.cases)
    data = await _call(_queue_data, ctx, request)
    resp = render(request, ctx, me, "_queue_rows.html", **data)
    t = translator(_lang(request, ctx))
    note = f"{t('refresh_cases')}: {len(set(touched))}"
    resp.body = resp.body + message_html(note, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


@router.post("/chain/verify", response_class=HTMLResponse)
async def verify_all(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _view(me)
    _htmx_only(request)
    result = await _call(auditpack.verify_chain, ctx, None)
    return render(request, ctx, me, "_verify_result.html", verify=result)


# ---------------------------------------------------------------------------- export


@router.get("/export", response_class=HTMLResponse)
async def export_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _view(me)
    packs = await _call(auditpack.list_packs, ctx)
    return render(request, ctx, me, "export.html", packs=packs, pack=None)


@router.post("/export", response_class=HTMLResponse)
async def export_build(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    await form(request)
    require(me, EXPORT_ROLES, "export an audit pack")
    pack = await _call(auditpack.build_audit_pack, ctx, me)
    return render(request, ctx, me, "_export_result.html", pack=pack)


@router.get("/exports/{name}")
async def export_download(
    name: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require(me, EXPORT_ROLES, "download an audit pack")
    path = auditpack.pack_path(ctx, name)
    return FileResponse(path, media_type="application/zip", filename=name)


# ---------------------------------------------------------------------------- inbox


@router.get("/inbox", response_class=HTMLResponse)
async def inbox(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Response:
    _view(me)
    notices = await _call(ctx.inbox.list)
    return render(request, ctx, me, "inbox.html", notices=notices)


@router.post("/inbox/{notice_id}/read", response_class=HTMLResponse)
async def inbox_read(
    notice_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _check_id(notice_id, "notice id")
    d = await form(request)
    _view(me)
    if me.kind != "user":
        raise PermissionDenied("marking a notice read needs a signed-in person")
    await _call(ctx.inbox.mark_read, notice_id, me.user_id, _version(d))
    notices = await _call(ctx.inbox.list)
    return render(request, ctx, me, "_inbox_rows.html", notices=notices)


# ---------------------------------------------------------------------------- dev user


@router.post("/dev/user")
async def dev_user(request: Request, ctx: ConsoleContext = _CTX) -> Response:
    d = await form(request)
    if ctx.provider.name != "dev_header":
        raise ConsoleInputError("user switching exists only with the dev users file (laptop)")
    uid = d.get("user", "")
    if uid not in {u.user_id for u in ctx.provider.known_users()}:
        raise ConsoleInputError("unknown dev user")
    resp = Response(status_code=204)
    resp.set_cookie(DEV_COOKIE, uid, samesite="strict", httponly=True)
    resp.headers["HX-Refresh"] = "true"
    return resp


@router.get("/home")
def home() -> RedirectResponse:
    return RedirectResponse("/console/", status_code=303)
