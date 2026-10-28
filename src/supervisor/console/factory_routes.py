"""Agent factory routes (WP-F2, flag ``AGENT_FACTORY``, needs ``GOVERNANCE_ENABLED``).

The routers are always mounted; with the flag off every route answers HTTP 400
``agent_factory_off`` and reads no table. ``systems.view`` reads the catalogue and the editor;
``factory.edit`` (reviewer, approver, admin) writes, and the handler then checks that the role is
one the owner group lists in ``config/factory_groups.yaml`` (admin edits every group). Every POST
writes the two ``console_action`` rows (``@audited``) and a ``factory_agent_event`` row.

* ``GET  /v1/factory/agents``, ``/v1/factory/agents/{id}``, ``/v1/factory/portfolio``  (JSON)
* ``GET  /console/factory``                       catalogue and the portfolio strip
* ``POST /console/factory/new``                   create from a template (htmx; HX-Redirect)
* ``GET  /console/factory/{id}``                  the editor (a full page)
* ``GET  /console/factory/{id}/step/{step}``      one step (an htmx fragment)
* ``POST /console/factory/{id}/step/{step}``      save one step (validated by agent_definition_v1)
* ``GET  /console/factory/{id}/preview``          dry preview (no model call)
* ``POST /console/factory/{id}/golden``           upload a golden set (JSON or CSV)
* ``POST /console/factory/{id}/helpers/{helper}`` run a helper agent (gateway model)
* ``POST /console/factory/{id}/drafts/{draft_id}/accept|drop``
* ``POST /console/factory/{id}/new-version`` and ``/retire``
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import factory_view as fv
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.intake_routes import _same_site, parse_multipart
from supervisor.console.routes import (
    _call,
    _htmx_only,
    _version,
    audited,
    form,
    message_html,
    render,
)
from supervisor.factory import golden, helpers, linter
from supervisor.factory.store import FactoryError, require_on

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
UPLOAD_LIMIT = golden.MAX_BYTES + 65_536


def _flash(resp: Any, note: str, ok: bool = True) -> Any:
    resp.body = resp.body + message_html(note, ok=ok, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


def _step_response(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    agent_id: str,
    version: str,
    step: str,
    note: str = "",
    ok: bool = True,
    **extra: Any,
) -> Response:
    data = fv.editor_data(ctx, me, agent_id, version, step)
    data["ed"].update(extra)
    resp = render(request, ctx, me, f"_factory_step_{step}.html", **data)
    return _flash(resp, note, ok) if note else resp


# ------------------------------------------------------------------------------- JSON API


@api_router.get("/factory/agents", dependencies=[Depends(needs("systems.view"))])
def api_agents(
    group: str = "",
    dimension: str = "",
    state: str = "",
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Any:
    require_on(ctx.settings)
    return {"agents": fv.catalogue_data(ctx, me, group, dimension, state)["fa"]["cards"]}


@api_router.get("/factory/agents/{agent_id}", dependencies=[Depends(needs("systems.view"))])
def api_agent(
    agent_id: str, version: str = "", ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    require_on(ctx.settings)
    row = fv.load_row(ctx, agent_id, version)
    return {**fv.card(ctx, me, row), "definition": row["definition"]}


@api_router.get("/factory/portfolio", dependencies=[Depends(needs("systems.view"))])
def api_portfolio(ctx: ConsoleContext = _CTX) -> Any:
    require_on(ctx.settings)
    return {"dimensions": fv.store(ctx).portfolio()}


# ------------------------------------------------------------------------------- catalogue


@router.get("/factory", response_class=HTMLResponse, dependencies=[Depends(needs("systems.view"))])
async def catalogue(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require_on(ctx.settings)
    q = request.query_params
    data = await _call(
        fv.catalogue_data, ctx, me, q.get("group", ""), q.get("dimension", ""), q.get("state", "")
    )
    return render(request, ctx, me, "factory.html", section="", **data)


@router.post(
    "/factory/new", response_class=HTMLResponse, dependencies=[Depends(needs("factory.edit"))]
)
@audited("factory.edit")
async def create_agent(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require_on(ctx.settings)
    f = await form(request)
    dimension = f.get("dimension_id", "")
    owner = fv.group_registry().owner_of(dimension)
    if owner is None:
        raise FactoryError("invalid_definition", "dimension_id: choose one of the eight dimensions")
    who = fv.require_edit(me, owner.group_id)
    row = await _call(
        fv.store(ctx).create_from_template,
        dimension,
        (f.get("id") or "").strip(),
        f.get("name", ""),
        who,
    )
    request.state.audit_detail = f"create {row['id']} {row['version']}"
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = f"/console/factory/{row['id']}"
    return resp


# ------------------------------------------------------------------------------- editor


@router.get(
    "/factory/{agent_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def editor(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require_on(ctx.settings)
    q = request.query_params
    step = q.get("step", "template")
    data = await _call(fv.editor_data, ctx, me, agent_id, q.get("v", ""), step)
    return render(request, ctx, me, "factory_editor.html", section="", **data)


@router.get(
    "/factory/{agent_id}/step/{step}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def step_fragment(
    agent_id: str, step: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require_on(ctx.settings)
    version = request.query_params.get("v", "")
    data = await _call(fv.editor_data, ctx, me, agent_id, version, step)
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, f"_factory_step_{step}.html", **data)
    return render(request, ctx, me, "factory_editor.html", section="", **data)


def _save(
    ctx: ConsoleContext, me: AuthPrincipal, agent_id: str, step: str, f: dict[str, str]
) -> str:
    row = fv.load_row(ctx, agent_id, f.get("version", ""))
    who = fv.require_edit(me, row["owner_group"])
    defn = fv.apply_step(row, step, f)
    st = fv.store(ctx)
    st.save_draft(agent_id, row["version"], defn, who, _version(f))
    return row["version"]


@router.post(
    "/factory/{agent_id}/step/{step}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def step_save(
    agent_id: str, step: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require_on(ctx.settings)
    f = await form(request)
    if step not in fv.STEPS:
        raise FactoryError("bad_step", f"step must be one of {', '.join(fv.STEPS)}")
    lint_only = step == "instructions" and f.get("op") == "lint"
    if lint_only:
        row = await _call(fv.load_row, ctx, agent_id, f.get("version", ""))
        fv.require_edit(me, row["owner_group"])
        row["definition"]["instructions"] = f.get("instructions", "")
        issues = [i.as_dict() for i in linter.lint_definition(row["definition"])]
        request.state.audit_detail = "lint"
        return await _call(
            _render_lint,
            request,
            ctx,
            me,
            agent_id,
            row["version"],
            f.get("instructions", ""),
            issues,
        )
    version = await _call(_save, ctx, me, agent_id, step, f)
    request.state.audit_detail = f"{step} saved {agent_id} {version}"
    return await _call(
        _step_response, request, ctx, me, agent_id, version, step, f"{agent_id} {version}: saved"
    )


def _render_lint(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    agent_id: str,
    version: str,
    text: str,
    issues: list[dict[str, str]],
) -> Response:
    data = fv.editor_data(ctx, me, agent_id, version, "instructions")
    data["ed"]["lint"] = issues
    data["ed"]["defn"] = {**data["ed"]["defn"], "instructions": text}
    return render(request, ctx, me, "_factory_step_instructions.html", **data)


@router.get(
    "/factory/{agent_id}/preview",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def preview(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Dry preview: reads stored facts exports, calls no model, writes nothing."""
    require_on(ctx.settings)
    q = request.query_params

    def work() -> dict[str, Any]:
        row = fv.load_row(ctx, agent_id, q.get("v", ""))
        data = fv.editor_data(ctx, me, agent_id, row["version"], "preview")
        data["ed"]["plan"] = fv.preview_data(ctx, row, q.get("nodes", ""))
        data["ed"]["picked"] = q.get("nodes", "")
        return data

    data = await _call(work)
    return render(request, ctx, me, "_factory_step_preview.html", **data)


@router.post(
    "/factory/{agent_id}/golden",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def golden_upload(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    require_on(ctx.settings)
    _same_site(request)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > UPLOAD_LIMIT:
        raise golden.GoldenError("the file is larger than 1 MB")
    body = await request.body()
    if len(body) > UPLOAD_LIMIT:
        raise golden.GoldenError("the file is larger than 1 MB")
    files, fields = parse_multipart(request.headers.get("content-type", ""), body)

    def work() -> tuple[str, str]:
        row = fv.load_row(ctx, agent_id, fields.get("version", ""))
        who = fv.require_edit(me, row["owner_group"])
        if row["state"] == "retired":
            raise golden.GoldenError("the agent version is retired")
        if not files:
            raise golden.GoldenError("choose a .json or .csv file")
        name, raw = files[0]
        cases = golden.parse_upload(name, raw)
        ids = [c["id"] for c in row["definition"]["checklist"]]
        ok, bad = golden.check_cases(cases, ids)
        if ok:
            golden.store_cases(ctx.settings.data_dir, agent_id, ok)
        fv.store(ctx).record_event(
            agent_id,
            row["version"],
            "golden_uploaded",
            who,
            f"{len(ok)} stored, {len(bad)} refused",
        )
        note = f"{len(ok)} case(s) stored, {len(bad)} refused"
        if bad:
            note += ": " + "; ".join(f"{b['case_id']} ({b['reason']})" for b in bad[:5])
        return row["version"], note

    version, note = await _call(work)
    request.state.audit_detail = note[:200]
    return await _call(
        _step_response,
        request,
        ctx,
        me,
        agent_id,
        version,
        "golden",
        note,
        not note.startswith("0 "),
    )


# ------------------------------------------------------------------------------- helper agents


@router.post(
    "/factory/{agent_id}/helpers/{helper}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def helper_run(
    agent_id: str,
    helper: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    require_on(ctx.settings)
    f = await form(request)
    if helper not in helpers.HELPERS:
        raise helpers.HelperError(
            "bad_helper", f"helper must be one of {', '.join(helpers.HELPERS)}"
        )
    step = {"checklist_drafter": "checklist", "golden_generator": "golden"}.get(helper, "preview")

    def work() -> tuple[str, str]:
        row = fv.load_row(ctx, agent_id, f.get("version", ""))
        who = fv.require_edit(me, row["owner_group"])
        chat = helpers.require_model(
            ctx.settings
        )  # model_not_configured while LLM_BASE_URL is empty
        st, hs = fv.store(ctx), fv.helper_store(ctx)
        if helper == "checklist_drafter":
            text = f.get("policy_text", "")
            doc_id = f.get("internal_doc_id", "").strip()
            if doc_id and not text.strip():
                raise helpers.HelperError(
                    "no_input",
                    "internal documents arrive with WP-W3; paste the section text here for now",
                )
            res = helpers.run_checklist_drafter(st, hs, chat, row, text, f.get("section", ""), who)
        elif helper == "golden_generator":
            n = fv._int(f.get("per_item", ""), "per_item", 2) or 2
            res = helpers.run_golden_generator(st, hs, chat, row, n, who)
        else:
            res = helpers.run_result_explainer(st, hs, chat, row, f.get("report_json", ""), who)
        note = f"{helper}: {res['added']} row(s) proposed, {res['dropped']} dropped"
        if res.get("refused"):
            note += f" ({len(res['refused'])} refused by the masker or the rules)"
        return row["version"], note

    version, note = await _call(work)
    request.state.audit_detail = note[:200]
    return await _call(_step_response, request, ctx, me, agent_id, version, step, note)


async def _decide(
    action: str,
    agent_id: str,
    draft_id: str,
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
) -> Response:
    require_on(ctx.settings)
    f = await form(request)
    rv = _version(f)

    def work() -> tuple[str, str]:
        d = fv.helper_store(ctx).get(draft_id)
        if d is None or d["agent_id"] != agent_id:
            raise helpers.HelperError("not_found", "this draft does not exist")
        row = fv.load_row(ctx, agent_id, d["version"])
        who = fv.require_edit(me, row["owner_group"])
        st, hs = fv.store(ctx), fv.helper_store(ctx)
        if action == "accept":
            helpers.accept(st, hs, draft_id, who, rv, ctx.settings.data_dir)
        else:
            helpers.drop(st, hs, draft_id, who, rv)
        step = {"checklist_drafter": "checklist", "golden_generator": "golden"}.get(
            d["helper"], "preview"
        )
        return d["version"], step

    version, step = await _call(work)
    request.state.audit_detail = f"helper_{action}"
    return await _call(
        _step_response,
        request,
        ctx,
        me,
        agent_id,
        version,
        step,
        "draft accepted" if action == "accept" else "draft dropped",
    )


@router.post(
    "/factory/{agent_id}/drafts/{draft_id}/accept",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def draft_accept(
    agent_id: str,
    draft_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    return await _decide("accept", agent_id, draft_id, request, ctx, me)


@router.post(
    "/factory/{agent_id}/drafts/{draft_id}/drop",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def draft_drop(
    agent_id: str,
    draft_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    return await _decide("drop", agent_id, draft_id, request, ctx, me)


# ------------------------------------------------------------------------------- versions


@router.post(
    "/factory/{agent_id}/new-version",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def new_version(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require_on(ctx.settings)
    f = await form(request)

    def work() -> str:
        row = fv.load_row(ctx, agent_id, f.get("version", ""))
        who = fv.require_edit(me, row["owner_group"])
        return fv.store(ctx).new_version(agent_id, row["version"], who)["version"]

    version = await _call(work)
    request.state.audit_detail = f"new_version {agent_id} {version}"
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = f"/console/factory/{agent_id}?v={version}"
    return resp


@router.post(
    "/factory/{agent_id}/retire",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def retire(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require_on(ctx.settings)
    f = await form(request)

    def work() -> str:
        row = fv.load_row(ctx, agent_id, f.get("version", ""))
        who = fv.require_edit(me, row["owner_group"])
        fv.store(ctx).retire(agent_id, row["version"], who, f.get("reason", ""))
        return row["version"]

    version = await _call(work)
    request.state.audit_detail = f"retire {agent_id} {version}"
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = f"/console/factory/{agent_id}?v={version}"
    return resp
