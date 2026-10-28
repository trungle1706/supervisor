"""Systems pages routes (WP-G0): ``/console/systems``. Mounted by ``app.py`` only when
CONSOLE_SYSTEMS_ENABLED=1; the page also needs GOVERNANCE_ENABLED=1 (HTTP 400 with a message
when it is off). Minimal pages on the old navigation; the full governance pages come later."""

from __future__ import annotations

import functools
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console import systems_duties, systems_views, systems_wizard, systems_workflow
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.i18n import translator
from supervisor.console.routes import (
    ConsoleInputError,
    _call,
    _check_id,
    _drawer_query,
    _lang,
    audited,
    form_or_plain,
    message_html,
    render,
)
from supervisor.core.errors import SupervisorError
from supervisor.governance.model import ensure_on
from supervisor.governance.systems import ALL

router = APIRouter(prefix="/console", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _off(ctx: ConsoleContext) -> None:
    """HTTP 400 unless both CONSOLE_SYSTEMS_ENABLED and GOVERNANCE_ENABLED are on."""
    if not ctx.settings.console_systems_enabled:
        raise ConsoleInputError("The Systems page is off (CONSOLE_SYSTEMS_ENABLED=1 turns it on)")
    ensure_on(ctx.settings)


@router.get("/systems", response_class=HTMLResponse, dependencies=[Depends(needs("systems.view"))])
async def systems_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    query = dict(request.query_params)
    data: dict[str, Any] = await _call(systems_views.list_view, ctx, me, query)
    opened = query.get("drawer")
    if opened:  # no-JS fallback of the row drawer
        _check_id(opened, "system id")
        data["drawer"] = await _call(
            systems_views.drawer_view,
            ctx,
            me,
            opened,
            query.get("dtab") or "details",
            _drawer_query(query),
        )
    return render(request, ctx, me, "systems.html", section="systems", **data)


@router.get(
    "/systems/rows", response_class=HTMLResponse, dependencies=[Depends(needs("systems.view"))]
)
async def systems_rows(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    data = await _call(systems_views.list_view, ctx, me, dict(request.query_params))
    return render(request, ctx, me, "_systems_list.html", **data)


# --- WP-UX4b --- register wizard. Declared before "/systems/{system_id}" so "new" is not an id.


def _wizard_off(ctx: ConsoleContext) -> None:
    """HTTP 400 unless the page flags are on and CONSOLE_NAV_V3 is on (the wizard is a v3 page)."""
    _off(ctx)
    if not ctx.settings.console_nav_v3:
        raise ConsoleInputError("The register wizard needs CONSOLE_NAV_V3=1")


def _person(me: AuthPrincipal) -> None:
    if me.kind != "user":
        raise PermissionDenied("registering an AI system needs a signed-in person")


@router.get(
    "/systems/new", response_class=HTMLResponse, dependencies=[Depends(needs("systems.edit"))]
)
async def system_new_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _wizard_off(ctx)
    _person(me)
    data = await _call(systems_wizard.form_view, ctx, me, request.query_params.get("from") or "")
    return render(request, ctx, me, "system_new.html", section="systems", **data)


@router.post(
    "/systems/new/checks",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
async def system_new_checks(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Step 2: the preliminary checks. Read only; nothing is stored."""
    _wizard_off(ctx)
    _person(me)
    form, _ = await form_or_plain(request)
    d = await _call(systems_wizard.checks, ctx, me, form)
    return render(request, ctx, me, "system_new_result.html", section="systems", d=d)


@router.post("/systems/new", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def system_new_register(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Step 3: register the draft and open the initiation tasks. Applies nothing else."""
    _wizard_off(ctx)
    _person(me)
    form, plain = await form_or_plain(request)
    out = await _call(systems_wizard.register, ctx, me, form)
    request.state.audit_detail = "create"
    url = f"/console/systems/{out['system_id']}?tab=tasks"
    if out["tasks_missing"]:  # L3: the draft is stored; the tasks page says so and offers a retry
        url += "&intake=missing"
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})


@router.post("/systems/{system_id}/intake-tasks", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def system_intake_tasks(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Open the initiation tasks of a system again (same ids: a repeat is a no-op)."""
    _wizard_off(ctx)
    _person(me)
    _check_id(system_id, "system id")
    await form_or_plain(request)
    await _call(systems_views.detail_view, ctx, me, system_id, "overview")  # scope check
    await _call(systems_wizard.open_tasks, ctx, system_id, str(me.user_id))
    request.state.audit_detail = "intake_tasks"
    url = f"/console/systems/{system_id}?tab=tasks"
    if request.headers.get("hx-request") == "true":
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@router.get(
    "/systems/{system_id}/drawer",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def system_drawer(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    _check_id(system_id, "system id")
    query = dict(request.query_params)
    data = await _call(
        systems_views.drawer_view,
        ctx,
        me,
        system_id,
        query.get("tab") or "details",
        _drawer_query(query),
    )
    return render(request, ctx, me, "_system_drawer.html", drawer=data)


@router.get(
    "/systems/{system_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def system_page(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    _check_id(system_id, "system id")
    tab = request.query_params.get("tab") or "overview"
    data = await _call(
        systems_views.detail_view, ctx, me, system_id, tab, dict(request.query_params)
    )
    if tab == "tasks" and request.query_params.get("intake") == "missing":  # WP-UX4b L3
        data["intake_missing"] = bool(await _call(systems_wizard.missing_tasks, ctx, system_id))
    return render(request, ctx, me, "system.html", section="systems", **data)


@router.post("/systems", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def systems_register(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    if me.kind != "user":
        raise PermissionDenied("registering an AI system needs a signed-in person")
    form, plain = await form_or_plain(request)
    draft = systems_views.draft_from_form(form, me)
    if ctx.systems.scope_for(me) is not ALL:
        draft["owner_user"] = str(me.user_id)
    out = await _call(functools.partial(ctx.systems.register, draft, str(me.user_id), for_user=me))
    request.state.audit_detail = "create"
    url = f"/console/systems/{out['system_id']}"
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})


# --- WP-G2: Rules and Classification tabs (docs/assignment-rules.md, docs/decision33.md) -------
def _done(request: Request, plain: bool, system_id: str, tab: str) -> Response:
    lang = request.query_params.get("lang") or ""
    url = f"/console/systems/{system_id}?tab={tab}" + (f"&lang={lang}" if lang else "")
    if plain:
        return RedirectResponse(url, status_code=303)
    return Response(status_code=200, headers={"HX-Redirect": url})


def _person(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("this action needs a signed-in person")
    return str(me.user_id)


@router.post("/systems/{system_id}/rules/run", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def system_rules_run(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _off(ctx)
    actor = _person(me)
    _, plain = await form_or_plain(request)
    seen = await _call(systems_views.detail_view, ctx, me, system_id, "overview")
    sid = seen["s"]["system_id"]
    await _call(functools.partial(ctx.rules.run, sid, actor, "manual"))
    request.state.audit_detail = "rules run"
    return _done(request, plain, sid, "rules")


@router.post(
    "/systems/{system_id}/classification/{step}", dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def system_classification_step(
    system_id: str,
    step: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _off(ctx)
    actor = _person(me)
    if step not in ("draft", "answers", "apply"):
        raise ConsoleInputError("unknown classification step")
    form, plain = await form_or_plain(request)
    seen = await _call(systems_views.detail_view, ctx, me, system_id, "overview")
    sid = seen["s"]["system_id"]
    svc = ctx.classification
    if step == "draft":
        await _call(functools.partial(svc.draft, sid, actor))
    elif step == "answers":
        current = (await _call(svc.get, sid))["draft"]
        if current is None:
            raise ConsoleInputError("there is no draft to edit; make one first")
        changes = systems_views.classification_changes(form, current)
        if changes:
            await _call(functools.partial(svc.edit, sid, actor, changes))
    else:
        confirm = form.get("confirm_ai_prefill", "") in ("1", "true", "on")
        await _call(functools.partial(svc.apply, sid, me, confirm_ai_prefill=confirm))
    request.state.audit_detail = f"classification {step}"
    return _done(request, plain, sid, "classification")


# --- WP-P1: tasks and stage approvals as buttons (CONSOLE_WORKFLOW_ACTIONS) --------------------
# Every route answers HTTP 400 naming the flag while it is off (systems_workflow.ensure_on). The
# answer is the refreshed Tasks tab (an htmx fragment for #tab-body) with the result in #flash, or a
# 303 back to the tab for a plain form post. The audit row note is set by the route
# (``request.state.audit_detail``): action, status before and after, hash of the reason.


async def _wf_run(fn: Any, *args: Any) -> Any:
    """Run a workflow step; a service text that names an API path is shown without it."""
    try:
        return await _call(fn, *args)
    except (systems_workflow.WorkflowError, PermissionDenied):
        raise
    except SupervisorError as exc:
        text = systems_workflow.console_text(str(exc))
        if text != str(exc):
            raise type(exc)(text) from None
        raise


async def _wf_answer(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    plain: bool,
    system_id: str,
    note: str,
    ok_key: str,
) -> Response:
    request.state.audit_detail = note
    if plain:
        return _done(request, True, system_id, "tasks")
    data = await _call(systems_views.detail_view, ctx, me, system_id, "tasks")
    resp = render(request, ctx, me, "_system_tasks.html", **data)
    msg = translator(_lang(request, ctx))(ok_key)
    resp.body = resp.body + message_html(msg, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


async def _wf_system(
    request: Request, ctx: ConsoleContext, me: AuthPrincipal, system_id: str
) -> tuple[dict[str, str], bool, dict[str, Any]]:
    """Flag check, the form, and the system if it is in the caller's scope."""
    _off(ctx)
    systems_workflow.ensure_on(ctx)
    systems_workflow.person(me)
    _check_id(system_id, "system id")
    form, plain = await form_or_plain(request)
    system = await _call(systems_views._need_visible, ctx, me, system_id)
    return form, plain, system


@router.post(
    "/systems/{system_id}/tasks/{task_id}/done", dependencies=[Depends(needs("tasks.view"))]
)
@audited("tasks.edit")
async def system_task_done(
    system_id: str,
    task_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    """Done. The role of the task or ``systems.edit`` (checked in the handler)."""
    form, plain, system = await _wf_system(request, ctx, me, system_id)
    _, note = await _wf_run(
        systems_workflow.task_done, ctx, me, system, task_id, form.get("evidence_ref")
    )
    return await _wf_answer(request, ctx, me, plain, system["system_id"], note, "wf_ok_done")


@router.post(
    "/systems/{system_id}/tasks/{task_id}/waive", dependencies=[Depends(needs("tasks.view"))]
)
@audited("tasks.edit")
async def system_task_waive(
    system_id: str,
    task_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    """Waive: a reason of 10 characters or more; not the creator of the task; a second person
    closes it (the next route)."""
    form, plain, system = await _wf_system(request, ctx, me, system_id)
    _, note = await _wf_run(
        systems_workflow.task_waive, ctx, me, system, task_id, form.get("reason")
    )
    return await _wf_answer(request, ctx, me, plain, system["system_id"], note, "wf_ok_waive")


@router.post(
    "/systems/{system_id}/tasks/{task_id}/waive/{answer}",
    dependencies=[Depends(needs("tasks.approve"))],
)
@audited("tasks.approve")
async def system_task_waive_answer(
    system_id: str,
    task_id: str,
    answer: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    """The second person approves or rejects the waiver (``tasks.approve``)."""
    if answer not in ("approve", "reject"):
        raise ConsoleInputError("unknown waiver answer")
    form, plain, system = await _wf_system(request, ctx, me, system_id)
    _, note = await _wf_run(
        systems_workflow.task_waive_answer,
        ctx,
        me,
        system,
        task_id,
        answer == "approve",
        form.get("reason"),
    )
    key = "wf_ok_waive_approve" if answer == "approve" else "wf_ok_waive_reject"
    return await _wf_answer(request, ctx, me, plain, system["system_id"], note, key)


@router.post("/systems/{system_id}/stage/request", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def system_stage_request(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    form, plain, system = await _wf_system(request, ctx, me, system_id)
    _, note = await _wf_run(
        systems_workflow.stage_request,
        ctx,
        me,
        system,
        form.get("to_stage", ""),
        form.get("reason"),
    )
    return await _wf_answer(request, ctx, me, plain, system["system_id"], note, "wf_ok_request")


@router.post(
    "/systems/{system_id}/stage/{approval_id}/decide",
    dependencies=[Depends(needs("systems.approve"))],
)
@audited("systems.approve")
async def system_stage_decide(
    system_id: str,
    approval_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    """Approve or reject by a second person. The requester gets HTTP 400 ``same_person``."""
    form, plain, system = await _wf_system(request, ctx, me, system_id)
    decision = form.get("decision", "")
    _, note = await _wf_run(
        systems_workflow.stage_decide,
        ctx,
        me,
        system,
        approval_id,
        decision,
        form.get("reason"),
    )
    key = "wf_ok_approve" if decision == "approve" else "wf_ok_reject"
    return await _wf_answer(request, ctx, me, plain, system["system_id"], note, key)


@router.post("/systems/{system_id}/stage/move", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def system_stage_move(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    form, plain, system = await _wf_system(request, ctx, me, system_id)
    _, note = await _wf_run(systems_workflow.stage_move, ctx, me, system, form.get("to_stage", ""))
    return await _wf_answer(request, ctx, me, plain, system["system_id"], note, "wf_ok_move")


# --- WP-L3: duties of a system (RISK_DUTIES) ----------------------------------------------------
# Close and Re-evaluate need systems.edit, Waive needs systems.approve (the owner of the system
# cannot waive: 400 owner_cannot_waive). Every route answers HTTP 400 risk_duties_off while the
# flag is off. The answer is the refreshed Duties tab (htmx fragment for #tab-body) with the result
# in #flash, or a 303 back to the tab for a plain form post. Two console_action rows per POST.


async def _duty_answer(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    plain: bool,
    system_id: str,
    note: str,
    ok_key: str,
) -> Response:
    request.state.audit_detail = note
    if plain:
        return _done(request, True, system_id, "duties")
    data = await _call(systems_views.detail_view, ctx, me, system_id, "duties", {})
    resp = render(request, ctx, me, "_system_duties.html", **data)
    msg = translator(_lang(request, ctx))(ok_key)
    resp.body = resp.body + message_html(msg, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp


async def _duty_system(
    request: Request, ctx: ConsoleContext, me: AuthPrincipal, system_id: str
) -> tuple[dict[str, str], bool, dict[str, Any]]:
    _off(ctx)
    systems_duties.ensure_on(ctx)
    systems_duties.person(me)
    _check_id(system_id, "system id")
    form, plain = await form_or_plain(request)
    system = await _call(systems_views._need_visible, ctx, me, system_id)
    return form, plain, system


@router.post("/systems/{system_id}/duties/close", dependencies=[Depends(needs("systems.edit"))])
@audited("systems.edit")
async def system_duties_close(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Close one duty (``status_id``) or one group (``group``): closing control and evidence."""
    form, plain, system = await _duty_system(request, ctx, me, system_id)
    _, note = await _call(systems_duties.do_close, ctx, me, system, form)
    return await _duty_answer(request, ctx, me, plain, system["system_id"], note, "du_ok_close")


@router.post("/systems/{system_id}/duties/waive", dependencies=[Depends(needs("systems.approve"))])
@audited("systems.approve")
async def system_duties_waive(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Waive one duty or one group: reason of 20 characters or more; not by the system owner."""
    form, plain, system = await _duty_system(request, ctx, me, system_id)
    _, note = await _call(systems_duties.do_waive, ctx, me, system, form)
    return await _duty_answer(request, ctx, me, plain, system["system_id"], note, "du_ok_waive")


@router.post(
    "/systems/{system_id}/duties/reevaluate", dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def system_duties_reevaluate(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Run the matrix again on the stored answers and update the rows. Nothing is deleted."""
    _, plain, system = await _duty_system(request, ctx, me, system_id)
    _, note = await _call(systems_duties.do_reevaluate, ctx, me, system)
    return await _duty_answer(request, ctx, me, plain, system["system_id"], note, "du_ok_reeval")


@router.post(
    "/systems/{system_id}/duties/refresh-evidence", dependencies=[Depends(needs("systems.edit"))]
)
@audited("systems.edit")
async def system_duties_refresh_evidence(
    system_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """WP-L4 (REGULATOR_PACK): read the live evidence again and close the full-coverage duties
    whose mapped controls all work. Answers HTTP 400 regulator_pack_off while the flag is off."""
    _, plain, system = await _duty_system(request, ctx, me, system_id)
    _, note = await _call(systems_duties.do_refresh, ctx, me, system)
    return await _duty_answer(request, ctx, me, plain, system["system_id"], note, "du_ok_refresh")


# --- WP-N3 --- register workflow v2: /console/register (answers 400 while the flag is off)
from supervisor.console.register_routes import router as _register_router  # noqa: E402

router.include_router(_register_router)
