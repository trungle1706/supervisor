"""Test gate, simulation review and promotion routes (WP-F3, flag ``AGENT_FACTORY_GATE``).

Always mounted; with the flag off every route answers HTTP 400 ``factory_gate_off`` and reads no
``gate_run`` row. Runs and marks are ``factory.edit`` plus the group check of the editor;
approve, reject and activate are ``factory.approve``; rollback is ``factory.rollback`` (admin).
Every POST writes the two ``console_action`` rows (``@audited``), a ``factory_agent_event`` row and,
for a move of the state, a chain record ``factory_promotion``.

* ``GET  /v1/factory/agents/{id}/gate``                      runs of an agent (JSON)
* ``GET  /v1/factory/gate/{run_id}``                         one run (JSON)
* ``GET  /console/factory/{id}/gate``                        the gate step, polled while a run goes
* ``POST /console/factory/{id}/gate/run``                    start full, sample, simulation, shadow
* ``GET  /console/factory/{id}/gate/{run_id}``               one run in detail (fragment)
* ``GET  /console/factory/{id}/simulation/{run_id}``         the simulation review page
* ``POST /console/factory/{id}/simulation/{run_id}/mark``    agree / disagree / unsure + note
* ``POST /console/factory/{id}/promote/{submit|approve|reject|activate|reopen|rollback}``
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import factory_gate_view as fgv
from supervisor.console import factory_view as fv
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.factory_routes import _step_response
from supervisor.console.routes import _call, audited, form, render
from supervisor.factory import gate, promotion, simulation
from supervisor.factory.store import FactoryError

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


def _on(ctx: ConsoleContext) -> None:
    gate.require_on(ctx.settings)


def _redirect(agent_id: str, version: str) -> Response:
    resp = Response(status_code=200)
    resp.headers["HX-Redirect"] = f"/console/factory/{agent_id}?v={version}&step=gate"
    return resp


# ------------------------------------------------------------------------------- JSON API


@api_router.get("/factory/agents/{agent_id}/gate", dependencies=[Depends(needs("systems.view"))])
def api_runs(agent_id: str, ctx: ConsoleContext = _CTX) -> Any:
    _on(ctx)
    e = fgv.env(ctx)
    fv.load_row(ctx, agent_id)
    return {"runs": [fgv.run_summary(r) for r in gate.latest_runs(e, agent_id, None, 50)]}


@api_router.get("/factory/gate/{run_id}", dependencies=[Depends(needs("systems.view"))])
def api_run(run_id: str, ctx: ConsoleContext = _CTX) -> Any:
    _on(ctx)
    r = gate.get_run(fgv.env(ctx), run_id)
    if r is None:
        raise FactoryError("not_found", "this gate run does not exist")
    return fgv.run_summary(r)


# ------------------------------------------------------------------------------- the gate step


@router.get(
    "/factory/{agent_id}/gate",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def gate_step(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """The poll target of the gate panel. When the state of the version changed since the page was
    drawn (a full run passed or failed) the browser is sent to the whole editor page."""
    _on(ctx)
    q = request.query_params
    data = await _call(fv.editor_data, ctx, me, agent_id, q.get("v", ""), "gate")
    seen = q.get("state", "")
    if seen and seen != data["ed"]["agent"]["state"] and request.headers.get("hx-request"):
        return _redirect(agent_id, data["ed"]["version"])
    return render(request, ctx, me, "_factory_step_gate.html", **data)


@router.post(
    "/factory/{agent_id}/gate/run",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def gate_run(
    agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _on(ctx)
    f = await form(request)

    def work() -> tuple[str, str]:
        row = fv.load_row(ctx, agent_id, f.get("version", ""))
        who = fv.require_edit(me, row["owner_group"])
        kind = f.get("kind", "")
        run = gate.start(
            fgv.env(ctx),
            agent_id,
            row["version"],
            kind,
            who,
            n=fgv.int_field(f.get("n", ""), "n"),
            systems=fgv.parse_systems(f.get("systems", "")),
        )
        return row["version"], f"{kind} run {run['run_id']} queued"

    version, note = await _call(work)
    request.state.audit_detail = note[:200]
    return await _call(_step_response, request, ctx, me, agent_id, version, "gate", note)


@router.get(
    "/factory/{agent_id}/gate/{run_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def gate_detail(
    agent_id: str,
    run_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _on(ctx)
    run = await _call(fgv.run_detail, ctx, agent_id, run_id)
    return render(request, ctx, me, "_factory_gate_run.html", run=run, agent_id=agent_id)


# ------------------------------------------------------------------------------- simulation


def _sim_data(ctx: ConsoleContext, me: Any, agent_id: str, run_id: str) -> dict[str, Any]:
    row = fv.load_row(ctx, agent_id)
    review = simulation.review_data(fgv.env(ctx), agent_id, run_id)
    out = {
        "sim": review,
        "agent": fv.card(ctx, me, row),
        "can_mark": fv.may_edit(me, row["owner_group"]),
        "verdicts": ("pass", "fail", "not_applicable", "question"),
    }
    if ctx.settings.console_ux5:  # --- UX5 G6 --- the question text on every finding card
        out["questions"] = {
            str(c.get("id")): str(c.get("question") or "")
            for c in (row["definition"].get("checklist") or [])
        }
    return out


def _bulk_marks(
    ctx: ConsoleContext, me: Any, agent_id: str, run_id: str, f: dict[str, str]
) -> tuple[dict[str, Any], int]:
    """UX5 G6: one Save for the whole review page. Fields ``mark_<n>``, ``cv_<n>``, ``note_<n>``,
    ``sys_<n>``, ``fid_<n>``, ``orig_<n>``; an empty or unchanged mark is left as it is."""
    row = fv.load_row(ctx, agent_id)
    who = fv.require_edit(me, row["owner_group"])
    todo = []
    for key in sorted(f):
        if not key.startswith("mark_") or not f[key]:
            continue
        n = key[5:]
        now_val = "|".join((f[key], f.get(f"cv_{n}", ""), f.get(f"note_{n}", "")))
        if now_val == f.get(f"orig_{n}"):  # unchanged: do not rewrite the mark
            continue
        todo.append(
            (
                f.get(f"sys_{n}", ""),
                f.get(f"fid_{n}", ""),
                f[key],
                f.get(f"cv_{n}", ""),
                f.get(f"note_{n}", ""),
            )
        )
    for _s, fid, value, cv, _note in todo:  # check all first: nothing half saved
        if value == "disagree" and cv not in fv.caps.VERDICTS:
            raise FactoryError(
                "verdict_needed", f"finding {fid}: a disagree mark names the correct verdict"
            )
    for sysname, fid, value, cv, note in todo:
        simulation.mark(fgv.env(ctx), agent_id, run_id, sysname, fid, value, cv, note, who)
    return _sim_data(ctx, me, agent_id, run_id), len(todo)


@router.get(
    "/factory/{agent_id}/simulation/{run_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def simulation_page(
    agent_id: str,
    run_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _on(ctx)
    data = await _call(_sim_data, ctx, me, agent_id, run_id)
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_factory_sim_body.html", **data)
    return render(request, ctx, me, "factory_simulation.html", section="", **data)


@router.post(
    "/factory/{agent_id}/simulation/{run_id}/mark",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("factory.edit"))],
)
@audited("factory.edit")
async def simulation_mark(
    agent_id: str,
    run_id: str,
    request: Request,
    ctx: ConsoleContext = _CTX,
    me: AuthPrincipal = _ME,
) -> Response:
    _on(ctx)
    f = await form(request)
    if ctx.settings.console_ux5 and any(k.startswith("mark_") for k in f):  # UX5 G6: one Save
        data, n = await _call(_bulk_marks, ctx, me, agent_id, run_id, f)
        request.state.audit_detail = f"marks {n}"[:200]
        return render(request, ctx, me, "_factory_sim_body.html", **data)

    def work() -> dict[str, Any]:
        row = fv.load_row(ctx, agent_id)
        who = fv.require_edit(me, row["owner_group"])
        simulation.mark(
            fgv.env(ctx),
            agent_id,
            run_id,
            f.get("system", ""),
            f.get("finding_id", ""),
            f.get("mark", ""),
            f.get("correct_verdict", ""),
            f.get("note", ""),
            who,
        )
        return _sim_data(ctx, me, agent_id, run_id)

    data = await _call(work)
    request.state.audit_detail = f"mark {f.get('mark', '')}"[:200]
    return render(request, ctx, me, "_factory_sim_body.html", **data)


# ------------------------------------------------------------------------------- promotion


async def _promote(
    action: str, agent_id: str, request: Request, ctx: ConsoleContext, me: AuthPrincipal
) -> Response:
    _on(ctx)
    f = await form(request)

    def work() -> str:
        if getattr(me, "kind", "user") != "user":
            raise FactoryError("not_a_person", "a promotion needs a signed-in person")
        e = fgv.env(ctx)
        st = e.store
        row = fv.load_row(ctx, agent_id, f.get("version", ""))
        actor = promotion.actor_of(me)
        if action in ("submit", "reopen"):
            fv.require_edit(me, row["owner_group"])
        if action == "submit":
            promotion.submit(st, e.sink, row, actor)
        elif action == "reopen":
            promotion.reopen(st, e.sink, row, actor, f.get("reason", ""))
        elif action == "approve":
            kinds = fgv._approve_kinds(me, st, row, promotion.required_approvals(st, row))
            kind = f.get("kind") or (kinds[0] if kinds else "owner_lead")
            promotion.approve(st, e.sink, row, actor, kind, f.get("note", ""))
        elif action == "reject":
            promotion.reject(st, e.sink, row, actor, f.get("reason", ""))
        elif action == "activate":
            promotion.activate(st, e.sink, row, actor)
        else:
            promotion.rollback(st, e.sink, agent_id, actor, f.get("reason", ""), f.get("to", ""))
        return row["version"]

    version = await _call(work)
    request.state.audit_detail = f"{action} {agent_id} {version}"[:200]
    return _redirect(agent_id, version)


def _route(action: str, permission: str) -> None:
    async def handler(
        agent_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
    ) -> Response:
        return await _promote(action, agent_id, request, ctx, me)

    handler.__name__ = f"promote_{action}"
    router.post(
        f"/factory/{{agent_id}}/promote/{action}",
        response_class=HTMLResponse,
        dependencies=[Depends(needs(permission))],
    )(audited(permission)(handler))


for _action, _perm in (
    ("submit", "factory.edit"),
    ("reopen", "factory.edit"),
    ("approve", "factory.approve"),
    ("reject", "factory.approve"),
    ("activate", "factory.approve"),
    ("rollback", "factory.rollback"),
):
    _route(_action, _perm)
