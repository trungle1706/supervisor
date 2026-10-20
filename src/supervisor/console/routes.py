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

import functools
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
from supervisor.adapters.auth.audit import (
    audit_active,
    request_id_of,
    snapshot_hash,
    target_of,
    write_attempt,
    write_outcome,
)
from supervisor.adapters.auth.authz import needs
from supervisor.adapters.auth.dev_header import COOKIE as DEV_COOKIE
from supervisor.cases.service import RESOLUTIONS, SEVERITIES, CaseError, PermissionDenied
from supervisor.console import (
    agents_list,
    assurance_views,
    audit_view,
    auditpack,
    compliance_view,
    credentials_view,
    decisions,
    health,
    integration_reports,
    integrations_view,
    inventory_views,
    nav,
    onboard_runs,
    playground,
    policies_view,
    readmodels,
    search,
    tools_views,
    traces,
    users_view,
    views,
)
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.i18n import LANGS, pick_lang, translator
from supervisor.core import rbac
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
# Role tuples come from the role matrix (core/rbac.py); the old names stay as aliases.
VIEW_ROLES = rbac.roles_for("console.view")
EXPORT_ROLES = rbac.roles_for("evidence.export")
GATE_ROLES: dict[str, tuple[str, ...]] = {  # D04: pause = any on-call reviewer; resume = two
    a: rbac.roles_for(f"agent.{a}") for a in ("pause", "resume", "quarantine", "release")
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
_env.filters["day"] = lambda v: "-" if v is None else readmodels.ict(v).strftime("%Y-%m-%d %H:%M")
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
    data["compliance_enabled"] = bool(ctx.settings.console_compliance_enabled)  # WP14 nav link
    compliance_on = data["compliance_enabled"]
    integration_on = bool(ctx.settings.console_integration_enabled)
    body = _env.get_template(template).render(
        t=translator(lang),
        dur=lambda secs: views.duration_text(secs, lang),
        shell=shell,
        side_nav=ctx.settings.console_nav != "top",  # CONSOLE_NAV=top is the rollback
        nav_groups=lambda: nav.groups(
            shell(), compliance=compliance_on, integration=integration_on, lang=lang
        ),
        lang=lang,
        other_lang="vi" if lang == "en" else "en",
        me=me,
        mode=ctx.settings.supervisor_mode,
        integration_on=integration_on,
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
    if not (raw.isascii() and raw.isdigit() and len(raw) < 12):
        raise ConsoleInputError("row_version is missing; reload the page")
    return int(raw)


def _check_id(value: str, what: str) -> str:
    if not _ID.match(value or ""):
        raise ConsoleInputError(f"invalid {what}")
    return value


async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await run_in_threadpool(fn, *args, **kwargs)


def _warn_html(body: bytes, warning: str) -> bytes:
    """Add the audit WARNING to the #flash message already in an htmx response (or append a
    new #flash message when there is none)."""
    text = body.decode("utf-8")
    tail = "</div></div>"
    if text.endswith(tail) and 'id="flash"' in text:
        from markupsafe import escape

        return (text[: -len(tail)] + " " + str(escape(warning)) + tail).encode("utf-8")
    return (text + message_html(warning, oob=True)).encode("utf-8")


def audited(permission: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Two ``console_action`` rows for this mutating route (WP18, M4): ``attempted`` before the
    side effect (no row, no action: HTTP 400), then ok, denied or error with the target row hash
    before and after (a failed outcome write is a WARNING in the flash message, never a 5xx).
    Off only with CONSOLE_AUDIT_ENABLED=0 in dev mode.
    The route function must take ``request`` and ``ctx`` (and ``me`` when it has a person)."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request = kwargs["request"]
            ctx: ConsoleContext = kwargs["ctx"]
            if not audit_active(ctx.settings):  # off only with CONSOLE_AUDIT_ENABLED=0 in dev
                return await fn(*args, **kwargs)
            me = kwargs.get("me")
            if me is None:
                try:
                    me = current_principal(request)
                except Exception:  # noqa: BLE001 - no identity: nothing to attribute
                    return await fn(*args, **kwargs)
            perm = rbac.resolve_permission(permission, request.path_params)
            if perm not in rbac.PERMISSIONS and perm != "dev.user":
                perm = permission.split(".")[0] + ".invalid"  # a bad action name from the URL
            kind, tid = target_of(request.url.path, request.path_params)
            before = await _call(snapshot_hash, ctx.state, kind, tid)
            common: dict[str, Any] = {
                "request_id": request_id_of(request),
                "actor": me,
                "permission": perm,
                "method": request.method,
                "path": request.url.path,
                "target_kind": kind,
                "target_id": tid,
            }
            # M4: row 1 BEFORE the side effect; if it fails nothing is done (AuditUnavailable
            # -> HTTP 400 "audit store unavailable; the action was not done").
            await _call(write_attempt, ctx.tables, ctx.clock, before_hash=before, **common)
            outcome, detail, exc_out, resp = "ok", None, None, None
            try:
                resp = await fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raised below after the audit row
                exc_out = exc
                denied = isinstance(exc, PermissionDenied)
                outcome = "denied" if denied else "error"
                detail = "permission_denied" if denied else type(exc).__name__
            if outcome == "ok":  # --- WP-UX3 --- a route may add a fixed note (never typed text)
                detail = getattr(request.state, "audit_detail", None)
            after = await _call(snapshot_hash, ctx.state, kind, tid)
            warning = await _call(
                write_outcome,
                ctx.tables,
                ctx.clock,
                outcome=outcome,
                before_hash=before,
                after_hash=after,
                detail=detail,
                **common,
            )
            if warning:
                if exc_out is not None:
                    if isinstance(exc_out, SupervisorError):
                        exc_out.args = (f"{exc_out} ({warning})",)
                elif isinstance(resp, Response) and hasattr(resp, "body"):
                    resp.body = _warn_html(bytes(resp.body), warning)
                    resp.headers["content-length"] = str(len(resp.body))
            if exc_out is not None:
                raise exc_out
            return resp

        return wrapper

    return decorate


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


SOURCE_KINDS = ("gate", "judge", "monitor", "manual")


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
    source = request.query_params.get("source") or None
    if source is not None and source not in SOURCE_KINDS:
        raise ConsoleInputError("unknown opened-by filter")
    statuses = None
    if status == "open":
        statuses = list(readmodels.OPEN_STATUSES)
    elif status == "closed":
        statuses = ["closed"]
    rows = ctx.cases.list_cases(statuses=statuses, severity=sev, agent_id=agent)
    items = readmodels.case_rows(ctx, rows, ctx.clock.now())
    if source is not None:
        items = [i for i in items if source in i["sources"]]
    agents = sorted({a["agent_id"] for a in ctx.state.query("agent")})
    filters = {
        "severity": sev or "",
        "status": status,
        "agent": agent or "",
        "source": source or "",
    }
    return {
        "items": items,
        "filters": filters,
        "query": "&".join(f"{k}={v}" for k, v in filters.items() if v),
        "severities": SEVERITIES,
        "sources": SOURCE_KINDS,
        "agent_ids": agents,
        "closed_n": len(ctx.cases.list_cases(statuses=["closed"])),
    }


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))])
async def overview(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
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


@router.get("/cases", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))])
async def queue(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Response:
    data = await _call(_queue_data, ctx, request)
    return render(request, ctx, me, "queue.html", section="cases", **data)


@router.get(
    "/queue/rows", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))]
)
async def queue_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(_queue_data, ctx, request)
    return render(request, ctx, me, "_queue_rows.html", **data)


# ---------------------------------------------------------------------------- case


CASE_TABS = ("story", "rules", "transcript", "evidence", "casefile")


def _case_data(
    ctx: ConsoleContext, case_id: str, me: AuthPrincipal, tab: str = "story"
) -> dict[str, Any]:
    _check_id(case_id, "case id")
    if tab not in CASE_TABS:
        raise ConsoleInputError("unknown case tab")
    data = readmodels.case_detail(ctx, case_id, me, ctx.clock.now())
    data["tab"] = tab
    data["resolutions"] = RESOLUTIONS
    return data


@router.get(
    "/cases/{case_id}", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))]
)
async def case_page(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    tab = request.query_params.get("tab") or "story"
    data = await _call(_case_data, ctx, case_id, me, tab)
    return render(request, ctx, me, "case.html", section="cases", **data)


@router.get(
    "/cases/{case_id}/tab/{tab}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("console.view"))],
)
async def case_tab(
    case_id: str, tab: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """One pill tab of the case page (htmx partial)."""
    data = await _call(_case_data, ctx, case_id, me, tab)
    return render(request, ctx, me, f"_tab_{tab}.html", **data)


@router.get("/cases/{case_id}/casefile.{fmt}", dependencies=[Depends(needs("console.view"))])
async def case_file_view(
    case_id: str, fmt: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """The case file as the regulator sees it (HTML) or as data (JSON). A view: nothing is
    written; the audit pack writes and chains the files."""
    _check_id(case_id, "case id")
    if fmt not in ("html", "json"):
        raise ConsoleInputError("case file format must be html or json")
    from supervisor.evidence.casefile.render_html import render_html
    from supervisor.evidence.casefile.render_json import render_json

    cf = await _call(ctx.cases.case_file, case_id)
    if fmt == "html":
        return Response(render_html(cf), media_type="text/html; charset=utf-8")
    return Response(
        render_json(cf),
        media_type="application/json",
        headers={"content-disposition": f'attachment; filename="{case_id}.json"'},
    )


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
    page = await _call(_case_data, ctx, case_id, me)
    resp = render(request, ctx, me, "_case_body.html", **page)
    t = translator(_lang(request, ctx))
    resp.body = resp.body + message_html(f"{t('saved')} {done}", ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


@router.post(
    "/cases/{case_id}/assign",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("case.assign"))],
)
@audited("case.assign")
async def assign(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    def act(d: dict[str, str]) -> Any:
        return ctx.cases.assign(case_id, d.get("assignee", ""), me, _version(d))

    return await _case_action(request, ctx, me, case_id, act, "assign")


@router.post(
    "/cases/{case_id}/comment",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("case.comment"))],
)
@audited("case.comment")
async def comment(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    def act(d: dict[str, str]) -> Any:
        return ctx.cases.comment(case_id, d.get("text", ""), me, _version(d))

    return await _case_action(request, ctx, me, case_id, act, "comment")


@router.post(
    "/cases/{case_id}/itsm", response_class=HTMLResponse, dependencies=[Depends(needs("case.itsm"))]
)
@audited("case.itsm")
async def itsm(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    def act(d: dict[str, str]) -> Any:
        return ctx.cases.set_itsm_ref(case_id, d.get("itsm_ref", ""), me, _version(d))

    return await _case_action(request, ctx, me, case_id, act, "itsm_ref")


@router.post(
    "/cases/{case_id}/report-sent",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("case.report_sent"))],
)
@audited("case.report_sent")
async def report_sent(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Mark the preliminary or formal incident report as sent (Decree 142 Art. 19)."""

    def act(d: dict[str, str]) -> Any:
        return ctx.cases.record_report_sent(case_id, d.get("kind", ""), me, _version(d))

    return await _case_action(request, ctx, me, case_id, act, "report_sent")


@router.post(
    "/cases/{case_id}/transition",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("case.transition"))],
)
@audited("case.transition")
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


@router.post(
    "/cases/{case_id}/verify",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("case.verify"))],
)
@audited("case.verify")
async def verify_case_lane(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    case = await _call(ctx.cases.get, _check_id(case_id, "case id"))
    result = await _call(auditpack.verify_chain, ctx, f"agent:{case['agent_id']}")
    chain = await _call(readmodels.chain_summary, ctx)
    return render(request, ctx, me, "_verify_result.html", verify=result, chain=chain)


# ---------------------------------------------------------------------------- sign-off


@router.get(
    "/cases/{case_id}/signoff",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("console.view"))],
)
async def signoff_page(
    case_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(_case_data, ctx, case_id, me)
    return render(request, ctx, me, "signoff.html", section="cases", **data)


@router.post(
    "/cases/{case_id}/signoff",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("case.signoff"))],
)
@audited("case.signoff")
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
    page = await _call(_case_data, ctx, case_id, me)
    resp = render(request, ctx, me, "_signoff_panel.html", **page)
    resp.body = (
        resp.body
        + message_html(
            translator(_lang(request, ctx))("signoff_recorded"), ok=True, oob=True
        ).encode()
    )
    resp.headers["content-length"] = str(len(resp.body))
    return resp


# ---------------------------------------------------------------------------- agents


def _agents_data(ctx: ConsoleContext, me: AuthPrincipal) -> dict[str, Any]:
    return {"agents": readmodels.agent_cards(ctx, me)}


def _agents_page_data(
    ctx: ConsoleContext, me: AuthPrincipal, query: Mapping[str, str]
) -> dict[str, Any]:
    data = _agents_data(ctx, me)
    data.update(agents_list.list_view(data["agents"], query))
    return data


@router.get("/agents", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))])
async def agents(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Response:
    query = dict(request.query_params)
    data = await _call(_agents_page_data, ctx, me, query)
    opened = query.get("drawer")
    if opened:  # no-JS fallback of the row drawer: the same content, rendered with the page
        _check_id(opened, "agent id")
        dq = {k: v for k, v in query.items() if k not in ("drawer", "dtab", "lang")}
        data["drawer"] = await _call(
            agents_list.drawer_view,
            ctx,
            data["agents"],
            opened,
            query.get("dtab") or "overview",
            dq,
        )
        data["drawer_open"] = True
    return render(request, ctx, me, "agents.html", section="agents", **data)


@router.get(
    "/agents/rows", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))]
)
async def agents_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(_agents_page_data, ctx, me, dict(request.query_params))
    return render(request, ctx, me, "_agents_list.html", **data)


@router.get(
    "/agents/{agent_id}/drawer",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("console.view"))],
)
async def agent_drawer(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _check_id(agent_id, "agent id")
    query = dict(request.query_params)
    tab = query.pop("tab", "overview")
    query.pop("lang", None)
    cards = await _call(readmodels.agent_cards, ctx, me)
    data = await _call(agents_list.drawer_view, ctx, cards, agent_id, tab, query)
    return render(request, ctx, me, "_agent_drawer.html", drawer=data)


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


@router.post(
    "/agents/{agent_id}/{action}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("agent.{action}"))],
)
@audited("agent.{action}")
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
        result = fn(agent_id, me.user_id, reason, auth_method=me.auth_method, actor_kind=me.kind)
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
    data = await _call(_agents_page_data, ctx, me, {})
    resp = render(request, ctx, me, "_agents_table.html", **data)
    # the list above the cards shows the new state too (out-of-band swap, default filters)
    oob = render(request, ctx, me, "_agents_list.html", **data).body
    resp.body = (
        resp.body
        + b'<div id="list" hx-swap-oob="innerHTML">'
        + oob
        + b"</div>"
        + message_html(msg, ok=True, oob=True).encode()
    )
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
        **_alerts_data(ctx),
        "metric_cols": cols,
        "monitor_rows": views.monitor_status_rows(rows),
        "monitor_order": views.MONITOR_ORDER,
        "summary": summary,
        "rows": rows[-200:],
        "heads": {k: {"seq": v.seq, "entry_hash": v.entry_hash} for k, v in sorted(heads.items())},
        "entries": sum(v.seq + 1 for v in heads.values()),
        "verify": ctx.last_verify.get("all"),
        "gate": gate,
    }


def _alerts_data(ctx: ConsoleContext) -> dict[str, Any]:
    """Alerts panel (WP21): counts and the open / acknowledged alerts, newest first."""
    counts = ctx.alerts.counts()
    shown = [a for a in ctx.alerts.list(limit=50) if a["status"] in ("open", "acknowledged")]
    return {"alert_counts": counts, "alert_rows": shown}


@router.get("/metrics", response_class=HTMLResponse, dependencies=[Depends(needs("metrics.view"))])
async def metrics(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(_metrics_data, ctx)
    return render(request, ctx, me, "metrics.html", section="metrics", **data)


@router.post(
    "/intake/run", response_class=HTMLResponse, dependencies=[Depends(needs("intake.run"))]
)
@audited("intake.run")
async def intake_run(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Explicit case intake for when the scheduler is off (a GET never writes)."""
    _htmx_only(request)
    touched = await _call(case_intake.run, ctx.cases)
    data = await _call(_queue_data, ctx, request)
    resp = render(request, ctx, me, "_queue_rows.html", **data)
    t = translator(_lang(request, ctx))
    note = f"{t('refresh_cases')}: {len(set(touched))}"
    resp.body = resp.body + message_html(note, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


@router.post(
    "/chain/verify", response_class=HTMLResponse, dependencies=[Depends(needs("chain.verify"))]
)
@audited("chain.verify")
async def verify_all(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    result = await _call(auditpack.verify_chain, ctx, None)
    chain = await _call(readmodels.chain_summary, ctx)
    return render(request, ctx, me, "_verify_result.html", verify=result, chain=chain)


# ---------------------------------------------------------------------------- export


def _evidence_data(ctx: ConsoleContext) -> dict[str, Any]:
    data = readmodels.evidence(ctx)
    data["packs"] = auditpack.list_packs(ctx)
    audits = [p["name"] for p in data["packs"] if p["kind"] == "audit"]
    data["offline_pack"] = audits[0] if audits else "audit-pack-YYYYMMDDTHHMMSSZ-xxxxxx.zip"
    data["verify"] = ctx.last_verify.get("all")
    return data


@router.get("/evidence", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))])
async def evidence_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(_evidence_data, ctx)
    return render(request, ctx, me, "evidence.html", section="evidence", pack=None, **data)


@router.get("/export")
def export_page() -> RedirectResponse:
    """The audit pack lives on the Evidence screen since WP12."""
    return RedirectResponse("/console/evidence", status_code=303)


@router.post(
    "/chain/export", response_class=HTMLResponse, dependencies=[Depends(needs("evidence.export"))]
)
@audited("evidence.export")
async def chain_export(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    await form(request)
    pack = await _call(auditpack.build_chain_export, ctx, me)
    return render(request, ctx, me, "_export_result.html", pack=pack)


@router.post(
    "/export", response_class=HTMLResponse, dependencies=[Depends(needs("evidence.export"))]
)
@audited("evidence.export")
async def export_build(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    await form(request)
    pack = await _call(auditpack.build_audit_pack, ctx, me)
    return render(request, ctx, me, "_export_result.html", pack=pack)


@router.get("/exports/{name}", dependencies=[Depends(needs("evidence.download"))])
async def export_download(
    name: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    path = auditpack.pack_path(ctx, name)
    return FileResponse(path, media_type="application/zip", filename=name)


# ---------------------------------------------------------------------------- onboard

ONBOARD_ROLES = rbac.roles_for("onboard.start")


def _onboard_data(ctx: ConsoleContext) -> dict[str, Any]:
    runs = onboard_runs.last_runs(ctx.settings)
    job = ctx.onboard.latest()
    if job is not None and job.status == "running":
        arts = readmodels.onboard_artefacts(ctx.settings, job.agent)
    else:
        arts = set(runs[0]["files"]) if runs else set()
    return {
        "runs": runs,
        "job": job,
        "wizard": readmodels.lifecycle(None, arts),
        "enabled": bool(ctx.settings.console_onboard_enabled),
    }


@router.get("/onboard", response_class=HTMLResponse, dependencies=[Depends(needs("onboard.view"))])
async def onboard_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(_onboard_data, ctx)
    return render(request, ctx, me, "onboard.html", section="onboard", **data)


@router.get(
    "/onboard/status", response_class=HTMLResponse, dependencies=[Depends(needs("onboard.view"))]
)
async def onboard_status(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(_onboard_data, ctx)
    return render(request, ctx, me, "_onboard_status.html", **data)


@router.post(
    "/onboard/start", response_class=HTMLResponse, dependencies=[Depends(needs("onboard.start"))]
)
@audited("onboard.start")
async def onboard_start(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    d = await form(request)
    if not ctx.settings.console_onboard_enabled:
        raise ConsoleInputError(
            "Onboard from the console is off (CONSOLE_ONBOARD_ENABLED=1 turns it on); "
            "use python -m supervisor.onboard --target <folder> --out <folder>"
        )
    if me.kind != "user":
        raise PermissionDenied("starting an onboarding run needs a signed-in person")
    target = onboard_runs.resolve_target(d.get("target", ""))
    await _call(ctx.onboard.start, ctx, target, me)
    data = await _call(_onboard_data, ctx)
    return render(request, ctx, me, "_onboard_status.html", **data)


@router.get("/onboard/files/{agent}/{name}", dependencies=[Depends(needs("onboard.view"))])
async def onboard_file(
    agent: str, name: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    path = onboard_runs.artefact_path(ctx.settings, agent, name)
    media = "application/json" if name.endswith(".json") else "text/plain"
    resp = FileResponse(path, media_type=f"{media}; charset=utf-8")
    resp.headers["x-content-type-options"] = "nosniff"
    return resp


# ---------------------------------------------------------------------------- compliance (WP14)
# Read-only, advisory only. Off by default (CONSOLE_COMPLIANCE_ENABLED=1). When off, every
# compliance page answers HTTP 400 with a message (the Onboard Start and Integration pattern)
# and the nav link is hidden. Unknown agent, obligation or filter value: HTTP 400.


def _compliance_ctx(request: Request, ctx: ConsoleContext) -> dict[str, Any]:
    lang = _lang(request, ctx)
    return {
        "section": "compliance",
        "cw": lambda key: compliance_view.word(key, lang),
        "status_pill": compliance_view.STATUS_PILL,
        "d33_pill": compliance_view.D33_PILL,
        "statuses": compliance_view.STATUSES,
    }


def _compliance_off(request: Request, ctx: ConsoleContext, me: AuthPrincipal) -> Response:
    raise ConsoleInputError(
        "The Compliance tab is off (CONSOLE_COMPLIANCE_ENABLED=1 turns it on); use "
        "python -m supervisor.advisory.compliance --profile <file> --out <folder>"
    )


@router.get(
    "/compliance", response_class=HTMLResponse, dependencies=[Depends(needs("compliance.view"))]
)
async def compliance_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    if not ctx.settings.console_compliance_enabled:
        return _compliance_off(request, ctx, me)
    cards = await _call(compliance_view.cards, ctx.settings)
    return render(
        request,
        ctx,
        me,
        "compliance.html",
        enabled=True,
        cards=cards,
        **_compliance_ctx(request, ctx),
    )


@router.get(
    "/compliance/{agent}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("compliance.view"))],
)
async def compliance_agent(
    agent: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    if not ctx.settings.console_compliance_enabled:
        return _compliance_off(request, ctx, me)
    q = request.query_params

    def work() -> tuple[dict[str, Any], dict[str, Any]]:
        m = compliance_view.matrix_for(ctx.settings, agent)
        f = compliance_view.filter_rows(
            m,
            instrument=q.get("instrument", ""),
            status=q.get("status", ""),
            duty=q.get("duty", ""),
            applies=q.get("applies", ""),
        )
        return m, f

    matrix, filtered = await _call(work)
    return render(
        request,
        ctx,
        me,
        "compliance_agent.html",
        agent=agent,
        matrix=matrix,
        f=filtered,
        **_compliance_ctx(request, ctx),
    )


@router.get(
    "/compliance/{agent}/obligation/{obligation_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("compliance.view"))],
)
async def compliance_obligation(
    agent: str,
    obligation_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    if not ctx.settings.console_compliance_enabled:
        return _compliance_off(request, ctx, me)
    detail = await _call(compliance_view.obligation_detail, ctx.settings, agent, obligation_id)
    return render(
        request,
        ctx,
        me,
        "compliance_obligation.html",
        agent=agent,
        row=detail["row"],
        ob=detail["ob"],
        controls=detail["controls"],
        **_compliance_ctx(request, ctx),
    )


# ---------------------------------------------------------------------------- integration


def _integration_on(ctx: ConsoleContext) -> None:
    if not ctx.settings.console_integration_enabled:
        raise ConsoleInputError(
            "The Integration tab is off (CONSOLE_INTEGRATION_ENABLED=1 turns it on); "
            "use python -m supervisor.advisory.integration --target <folder> --out <folder>"
        )


@router.get(
    "/integration", response_class=HTMLResponse, dependencies=[Depends(needs("onboard.view"))]
)
async def integration_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _integration_on(ctx)
    rows = await _call(integration_reports.list_reports, ctx.settings)
    return render(request, ctx, me, "integration.html", section="integration", reports=rows)


@router.get("/integration/{name}/patches/{file}", dependencies=[Depends(needs("onboard.view"))])
async def integration_patch(
    name: str, file: str, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _integration_on(ctx)
    path = await _call(integration_reports.patch_path, ctx.settings, name, file)
    resp = FileResponse(path, media_type="text/plain; charset=utf-8")
    resp.headers["x-content-type-options"] = "nosniff"
    return resp


@router.get(
    "/integration/{name}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("onboard.view"))],
)
async def integration_report(
    name: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _integration_on(ctx)
    data = await _call(integration_reports.load_report, ctx.settings, name)
    return render(request, ctx, me, "integration_report.html", section="integration", **data)


# ---------------------------------------------------------------------------- assurance


def _assurance_off(request: Request, ctx: ConsoleContext) -> Response | None:
    """Off unless CONSOLE_ASSURANCE_ENABLED is on: HTTP 400 with a message (the Compliance and
    Integration pattern), and the nav link is hidden."""
    if ctx.settings.console_assurance_enabled:
        return None
    raise ConsoleInputError(
        "The Assurance tab is off (CONSOLE_ASSURANCE_ENABLED=1 turns it on); use "
        "python -m supervisor.assurance run <pack> --target <target> --out <folder>"
    )


@router.get(
    "/assurance",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("console.view"))],
)
async def assurance_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    off = _assurance_off(request, ctx)
    if off is not None:
        return off
    runs = await _call(assurance_views.runs, ctx.tables)
    return render(request, ctx, me, "assurance.html", section="assurance", runs=runs, run_id="")


@router.get(
    "/assurance/{run_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("console.view"))],
)
async def assurance_run_page(
    run_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    off = _assurance_off(request, ctx)
    if off is not None:
        return off
    data = await _call(assurance_views.run_detail, ctx.tables, run_id)
    return render(request, ctx, me, "assurance.html", section="assurance", **data)


# ---------------------------------------------------------------------------- tools (WP22)


def _tools_off(ctx: ConsoleContext) -> None:
    """Off unless CONSOLE_TOOLS_ENABLED is on: HTTP 400 with a message and no nav link."""
    if not ctx.settings.console_tools_enabled:
        raise ConsoleInputError(
            "The Tools tab is off (CONSOLE_TOOLS_ENABLED=1 turns it on); use "
            "python -m supervisor.analytics.tools report"
        )


@router.get("/tools", response_class=HTMLResponse, dependencies=[Depends(needs("tools.view"))])
async def tools_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _tools_off(ctx)
    q = request.query_params
    data = await _call(
        tools_views.page,
        ctx,
        agent_id=q.get("agent_id"),
        days=q.get("days"),
        sort=q.get("sort", "default"),
        desc=q.get("dir") == "desc",
    )
    can_download = rbac.allowed(me.roles, "tools.download")
    return render(
        request, ctx, me, "tools.html", section="tools", can_download=can_download, **data
    )


@router.get("/tools/{agent_id}/diff", dependencies=[Depends(needs("tools.download"))])
async def tools_diff(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """The suggested policy diff as a text file. Built in memory: no file is written, no
    policy is touched."""
    _tools_off(ctx)
    name, text = await _call(
        tools_views.diff_download, ctx, agent_id, request.query_params.get("days")
    )
    return Response(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------------------------------------------------------------------------- inventory


@router.get(
    "/inventory",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("inventory.view"))],
)
async def inventory_page(
    request: Request,
    agent: str | None = None,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    """WP24: per-agent inventory subgraph and the unmanaged workspace items. Off unless
    INVENTORY_ENABLED is on: HTTP 400 with a message and no nav entry."""
    if not ctx.settings.inventory_enabled:
        raise ConsoleInputError(
            "The Inventory tab is off (INVENTORY_ENABLED=1 turns it on); "
            "python -m supervisor.jobs.inventory fills it"
        )
    data = await _call(inventory_views.page, ctx, agent)
    return render(request, ctx, me, "inventory.html", section="inventory", **data)


# ---------------------------------------------------------------------------- search, soon


@router.get("/search", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))])
async def global_search(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Top-bar search: agents, cases and exact trace ids. htmx gets the popover partial, a
    plain GET (no JS) gets a full page."""
    found = await _call(search.run, ctx, request.query_params.get("q"))
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_search_results.html", found=found)
    return render(request, ctx, me, "search.html", found=found)


@router.get(
    "/soon/{page}", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))]
)
async def soon_page(
    page: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Placeholder for pages that WP-UX3 builds. HTTP 400 unless CONSOLE_NAV_PLACEHOLDERS=1."""
    if page not in nav.PLACEHOLDERS:
        raise ConsoleInputError("unknown page")
    if not ctx.settings.console_nav_placeholders:
        raise ConsoleInputError(
            "This page is not built yet (CONSOLE_NAV_PLACEHOLDERS=1 shows its placeholder)"
        )
    return render(
        request,
        ctx,
        me,
        "soon.html",
        section=page,
        title_key=nav.PLACEHOLDERS[page],
    )


# ---------------------------------------------------------------------------- --- WP-UX3 ---
# New pages, each behind its own flag (default off: HTTP 400 with a message, no nav link).

_UX3_FLAGS = {
    "decisions": ("CONSOLE_DECISIONS_ENABLED", "Gate decisions"),
    "traces": ("CONSOLE_TRACES_ENABLED", "Traces"),
    "playground": ("CONSOLE_PLAYGROUND_ENABLED", "Playground"),
    "policies": ("CONSOLE_POLICIES_ENABLED", "Policies"),
    "credentials": ("CONSOLE_CREDENTIALS_ENABLED", "Credentials"),
    "users": ("CONSOLE_USERS_ENABLED", "Users and roles"),
    "audit": ("CONSOLE_AUDITLOG_ENABLED", "Audit log"),
    "integrations": ("CONSOLE_INTEGRATIONS_ENABLED", "Integrations"),
}


def _ux3_off(ctx: ConsoleContext, page: str) -> None:
    """HTTP 400 unless the page flag is on (Playground also needs PLAYGROUND_ALLOW_APP=1 when
    SUPERVISOR_MODE=databricks_app)."""
    env, label = _UX3_FLAGS[page]
    if not getattr(ctx.settings, nav.PAGES[page], False):
        raise ConsoleInputError(f"The {label} page is off ({env}=1 turns it on)")
    if (
        page == "playground"
        and ctx.settings.supervisor_mode == "databricks_app"
        and not ctx.settings.playground_allow_app
    ):
        raise ConsoleInputError(
            "The Playground is off in databricks_app mode (PLAYGROUND_ALLOW_APP=1 allows it)"
        )


def _drawer_query(query: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in query.items() if k not in ("drawer", "dtab", "tab", "lang")}


# -- gate decisions


@router.get(
    "/decisions", response_class=HTMLResponse, dependencies=[Depends(needs("decisions.view"))]
)
async def decisions_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "decisions")
    query = dict(request.query_params)
    data = await _call(decisions.list_view, ctx, query)
    opened = query.get("drawer")
    if opened:  # no-JS fallback of the row drawer
        _check_id(opened, "decision id")
        data["drawer"] = await _call(
            decisions.drawer_view, ctx, opened, query.get("dtab") or "details", _drawer_query(query)
        )
    return render(request, ctx, me, "decisions.html", section="decisions", **data)


@router.get(
    "/decisions/rows",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("decisions.view"))],
)
async def decisions_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "decisions")
    data = await _call(decisions.list_view, ctx, dict(request.query_params))
    return render(request, ctx, me, "_decisions_list.html", **data)


@router.get(
    "/decisions/{event_id}/drawer",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("decisions.view"))],
)
async def decision_drawer(
    event_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "decisions")
    _check_id(event_id, "decision id")
    query = dict(request.query_params)
    data = await _call(
        decisions.drawer_view, ctx, event_id, query.get("tab") or "details", _drawer_query(query)
    )
    return render(request, ctx, me, "_decision_drawer.html", drawer=data)


# -- traces


@router.get("/traces", response_class=HTMLResponse, dependencies=[Depends(needs("traces.view"))])
async def traces_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "traces")
    data = await _call(traces.list_view, ctx, dict(request.query_params))
    return render(request, ctx, me, "traces.html", section="traces", **data)


@router.get(
    "/traces/rows", response_class=HTMLResponse, dependencies=[Depends(needs("traces.view"))]
)
async def traces_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "traces")
    data = await _call(traces.list_view, ctx, dict(request.query_params))
    return render(request, ctx, me, "_traces_list.html", **data)


@router.get(
    "/traces/{trace_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("traces.view"))],
)
async def trace_page(
    trace_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "traces")
    _check_id(trace_id, "trace id")
    span = request.query_params.get("span")
    if span:
        _check_id(span, "span id")
    data = await _call(traces.trace_detail, ctx, trace_id, span)
    return render(request, ctx, me, "trace.html", section="traces", **data)


@router.get(
    "/traces/{trace_id}/span/{span_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("traces.view"))],
)
async def trace_span(
    trace_id: str,
    span_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _ux3_off(ctx, "traces")
    _check_id(trace_id, "trace id")
    _check_id(span_id, "span id")
    data = await _call(traces.span_view, ctx, trace_id, span_id)
    return render(request, ctx, me, "_span_detail.html", **data)


# -- playground (dry run)


@router.get(
    "/playground", response_class=HTMLResponse, dependencies=[Depends(needs("playground.run"))]
)
async def playground_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "playground")
    data = await _call(playground.form_options, ctx)
    return render(request, ctx, me, "playground.html", section="playground", **data)


@router.post(
    "/playground/run",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("playground.run"))],
)
@audited("playground.run")
async def playground_run(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Dry-run gate check. Side-effect free (``Gateway.evaluate_only``); the outcome audit row
    carries the keyed hash of the arguments in ``detail``, never the arguments."""
    _ux3_off(ctx, "playground")
    parsed = playground.parse_form(await form(request))
    result = await _call(playground.run, ctx, parsed)
    digest = await _call(playground.input_hash, ctx, parsed["args"])
    request.state.audit_detail = f"in:{digest[:24]}"
    return render(request, ctx, me, "_playground_result.html", result=result)


# -- policies (read-only)


@router.get(
    "/policies", response_class=HTMLResponse, dependencies=[Depends(needs("policies.view"))]
)
async def policies_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "policies")
    query = dict(request.query_params)
    data = await _call(policies_view.list_view, ctx, query)
    opened = query.get("drawer")
    if opened:
        _check_id(opened, "rule id")
        data["drawer"] = await _call(
            policies_view.drawer_view,
            ctx,
            opened,
            query.get("dtab") or "details",
            _drawer_query(query),
        )
    return render(request, ctx, me, "policies.html", section="policies", **data)


@router.get(
    "/policies/rows", response_class=HTMLResponse, dependencies=[Depends(needs("policies.view"))]
)
async def policies_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "policies")
    data = await _call(policies_view.list_view, ctx, dict(request.query_params))
    return render(request, ctx, me, "_policies_list.html", **data)


@router.get(
    "/policies/{rule_id}/drawer",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("policies.view"))],
)
async def policy_drawer(
    rule_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "policies")
    _check_id(rule_id, "rule id")
    query = dict(request.query_params)
    data = await _call(
        policies_view.drawer_view,
        ctx,
        rule_id,
        query.get("tab") or "details",
        _drawer_query(query),
    )
    return render(request, ctx, me, "_policy_drawer.html", drawer=data)


# -- credentials, users, integrations (read-only)


@router.get(
    "/credentials",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("credentials.view"))],
)
async def credentials_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "credentials")
    data = await _call(credentials_view.page, ctx)
    return render(request, ctx, me, "credentials.html", section="credentials", **data)


@router.get("/users", response_class=HTMLResponse, dependencies=[Depends(needs("users.view"))])
async def users_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "users")
    data = await _call(users_view.page, ctx)
    return render(request, ctx, me, "users.html", section="users", **data)


@router.get(
    "/integrations",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("integrations.view"))],
)
async def integrations_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "integrations")
    data = await _call(integrations_view.page, ctx)
    return render(request, ctx, me, "integrations.html", section="integrations", **data)


# -- audit log (read-only)


@router.get("/audit", response_class=HTMLResponse, dependencies=[Depends(needs("audit.view"))])
async def audit_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "audit")
    query = dict(request.query_params)
    data = await _call(audit_view.list_view, ctx, query)
    opened = query.get("drawer")
    if opened:
        _check_id(opened, "audit row id")
        data["drawer"] = await _call(audit_view.drawer_view, ctx, opened, _drawer_query(query))
    return render(request, ctx, me, "audit.html", section="audit", **data)


@router.get("/audit/rows", response_class=HTMLResponse, dependencies=[Depends(needs("audit.view"))])
async def audit_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "audit")
    data = await _call(audit_view.list_view, ctx, dict(request.query_params))
    return render(request, ctx, me, "_audit_list.html", **data)


@router.get(
    "/audit/{action_id}/drawer",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("audit.view"))],
)
async def audit_drawer(
    action_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _ux3_off(ctx, "audit")
    _check_id(action_id, "audit row id")
    query = _drawer_query(dict(request.query_params))
    data = await _call(audit_view.drawer_view, ctx, action_id, query)
    return render(request, ctx, me, "_audit_drawer.html", drawer=data)


# ---------------------------------------------------------------------------- --- end WP-UX3 ---

# ---------------------------------------------------------------------------- health


@router.get("/health", response_class=HTMLResponse, dependencies=[Depends(needs("health.view"))])
async def health_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    data = await _call(health.health, ctx)
    return render(request, ctx, me, "health.html", section="health", **data)


# ---------------------------------------------------------------------------- inbox


@router.get("/inbox", response_class=HTMLResponse, dependencies=[Depends(needs("console.view"))])
async def inbox(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Response:
    notices = await _call(ctx.inbox.list)
    return render(request, ctx, me, "inbox.html", section="inbox", notices=notices)


@router.post(
    "/inbox/{notice_id}/read",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("inbox.read"))],
)
@audited("inbox.read")
async def inbox_read(
    notice_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _check_id(notice_id, "notice id")
    d = await form(request)
    if me.kind != "user":
        raise PermissionDenied("marking a notice read needs a signed-in person")
    await _call(ctx.inbox.mark_read, notice_id, me.user_id, _version(d))
    notices = await _call(ctx.inbox.list)
    return render(request, ctx, me, "_inbox_rows.html", notices=notices)


@router.post(
    "/alerts/{alert_id}/ack",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("alert.ack"))],
)
@audited("alert.ack")
async def alert_ack(
    alert_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _check_id(alert_id, "alert id")
    d = await form(request)
    if me.kind != "user":
        raise PermissionDenied("acknowledging an alert needs a signed-in person")
    await _call(ctx.alerts.acknowledge, alert_id, me.user_id, _version(d))
    data = await _call(_alerts_data, ctx)
    return render(request, ctx, me, "_alerts_panel.html", **data)


# ---------------------------------------------------------------------------- dev user


@router.post("/dev/user")
@audited("dev.user")
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
