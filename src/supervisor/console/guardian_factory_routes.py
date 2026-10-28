"""Guardian factory routes (WP-G1, GUARDIAN_FACTORY, docs/guardian-factory.md).

The routers are always mounted; with the flag off (or DETECTORS_ENABLED off) every route answers
HTTP 400 ``guardian_factory_off`` and nothing is read or written.

JSON API:

* ``GET  /v1/guardian-defs``                       the newest version of each guardian
  (``?state= &owner_group= &stage= &type=``) and counts per state (``guardians.view``)
* ``POST /v1/guardian-defs``                       create a draft; 201 (``guardians.edit``)
* ``GET  /v1/guardian-defs/{id}``                  one definition (``?version=``)
* ``POST /v1/guardian-defs/{id}``                  save the draft in place
* ``POST /v1/guardian-defs/{id}/draft-artifact``   plain words -> artifact draft; stores nothing
* ``POST /v1/guardian-defs/{id}/retire`` | ``reopen`` | ``new-version``
* ``GET  /v1/guardian-defs-schema``                the JSON Schema of the definition

Console: ``/console/guardian-factory`` (registry) and ``/console/guardian-factory/{id}`` (editor;
``new`` opens an empty one). Every POST writes two ``console_action`` rows (``@audited``)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import agent_detail
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import (
    _call,
    _check_id,
    _lang,
    audited,
    form_or_plain,
    message_html,
    render,
)
from supervisor.core.errors import NotFoundError
from supervisor.governance.routes import _body
from supervisor.guardian_factory import caps
from supervisor.guardian_factory import store as gstore
from supervisor.guardian_factory.definition import (
    GuardianFactoryError,
    json_schema,
    owner_groups,
)

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
NEW = "new"


def _svc(ctx: ConsoleContext) -> Any:
    gstore.require_on(ctx.settings)
    return ctx.guardian_defs


def _not_found(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": str(exc)})


# ------------------------------------------------------------------------------- JSON API


@api_router.get("/guardian-defs", dependencies=[Depends(needs("guardians.view"))])
def list_defs(request: Request, ctx: ConsoleContext = _CTX) -> Any:
    svc = _svc(ctx)
    filters = {
        k: request.query_params.get(k, "") for k in ("state", "owner_group", "stage", "type")
    }
    return {"items": svc.list_defs(filters), "counts": svc.counts()}


@api_router.get("/guardian-defs-schema", dependencies=[Depends(needs("guardians.view"))])
def get_schema(ctx: ConsoleContext = _CTX) -> Any:
    _svc(ctx)
    return json_schema()


@api_router.post("/guardian-defs", dependencies=[Depends(needs("guardians.edit"))])
@audited("guardians.edit")
async def create_def(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    svc = _svc(ctx)
    data = await _body(request)
    out = await _call(svc.create, data, me)
    request.state.audit_detail = f"guardian_def create {out['id']}"
    return JSONResponse(status_code=201, content=out)


@api_router.get("/guardian-defs/{def_id}", dependencies=[Depends(needs("guardians.view"))])
def get_def(def_id: str, request: Request, ctx: ConsoleContext = _CTX) -> Any:
    svc = _svc(ctx)
    _check_id(def_id, "guardian id")
    raw = request.query_params.get("version")
    try:
        version = int(raw) if raw else None
    except ValueError:
        raise GuardianFactoryError("bad_version", "version: a whole number") from None
    try:
        return svc.get(def_id, version)
    except NotFoundError as exc:
        return _not_found(exc)


@api_router.post("/guardian-defs/{def_id}", dependencies=[Depends(needs("guardians.edit"))])
@audited("guardians.edit")
async def save_def(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _svc(ctx)
    _check_id(def_id, "guardian id")
    data = await _body(request)
    try:
        out = await _call(svc.save, def_id, data, me)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"guardian_def save {def_id}"
    return out


@api_router.post(
    "/guardian-defs/{def_id}/draft-artifact", dependencies=[Depends(needs("guardians.edit"))]
)
@audited("guardians.edit")
async def draft_artifact(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    _svc(ctx)
    _check_id(def_id, "guardian id")
    data = await _body(request)
    extra = sorted(set(data) - {"type", "text"})
    if extra:
        raise GuardianFactoryError("bad_request", f"unknown key: {', '.join(extra)}")
    out = await _call(ctx.guardian_author.draft, data.get("type"), data.get("text"))
    request.state.audit_detail = f"guardian_def draft {out['source']}"
    return out


async def _move(
    what: str, def_id: str, request: Request, ctx: ConsoleContext, me: AuthPrincipal
) -> Any:
    svc = _svc(ctx)
    _check_id(def_id, "guardian id")
    fn = {
        "retire": svc.retire,
        "reopen": svc.reopen,
        "new-version": svc.new_version,
        "mark-benchmarked": svc.mark_benchmarked,
    }[what]
    try:
        out = await _call(fn, def_id, me)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"guardian_def {what} {def_id}"
    return out


@api_router.post("/guardian-defs/{def_id}/retire", dependencies=[Depends(needs("guardians.edit"))])
@audited("guardians.edit")
async def retire_def(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    return await _move("retire", def_id, request, ctx, me)


@api_router.post("/guardian-defs/{def_id}/reopen", dependencies=[Depends(needs("guardians.edit"))])
@audited("guardians.edit")
async def reopen_def(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    return await _move("reopen", def_id, request, ctx, me)


@api_router.post(
    "/guardian-defs/{def_id}/new-version", dependencies=[Depends(needs("guardians.edit"))]
)
@audited("guardians.edit")
async def new_version_def(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    return await _move("new-version", def_id, request, ctx, me)


# ------------------------------------------------------------------------------- console form

_SCALARS = (
    "id",
    "name",
    "description",
    "owner_group",
    "type",
    "stage",
    "action_on_fail",
    "sensitivity",
    "scope_agents",
    "scope_tools",
    "scope_data_classes",
    "benchmark_pack",
    "min_tpr_pct",
    "max_fpr_pct",
    "max_p95_ms",
    "shadow_days",
    "config_json",
)


def _csv(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


def _star_or_list(text: str) -> Any:
    items = _csv(text)
    return "*" if not items or items == ["*"] else items


def _int(form: dict[str, str], key: str, field: str) -> int:
    raw = (form.get(key) or "").strip()
    try:
        return int(raw)
    except ValueError:
        raise GuardianFactoryError(
            "invalid_definition",
            f"{field}: a whole number",
            [{"field": field, "message": "a whole number"}],
        ) from None


def vals_from_def(view: dict[str, Any] | None) -> dict[str, str]:
    """The editor fields of a stored definition (strings, as a form holds them)."""
    if not view:
        return {
            "id": "",
            "name": "",
            "description": "",
            "owner_group": "",
            "type": "regex",
            "stage": "input",
            "action_on_fail": "log",
            "sensitivity": "2",
            "scope_agents": "*",
            "scope_tools": "*",
            "scope_data_classes": "",
            "benchmark_pack": "",
            "min_tpr_pct": str(caps.DEFAULT_THRESHOLDS["min_tpr_pct"]),
            "max_fpr_pct": str(caps.DEFAULT_THRESHOLDS["max_fpr_pct"]),
            "max_p95_ms": str(caps.DEFAULT_THRESHOLDS["max_p95_ms"]),
            "shadow_days": "0",
            "config_json": "{}",
        }
    d = view["definition"]
    sc, th = d["scope"], d["thresholds"]
    star = lambda v: "*" if v == "*" else ", ".join(v)  # noqa: E731
    return {
        "id": d["id"],
        "name": d["name"],
        "description": d.get("description", ""),
        "owner_group": d["owner_group"],
        "type": d["type"],
        "stage": d["stage"],
        "action_on_fail": d["action_on_fail"],
        "sensitivity": str(d["sensitivity"]),
        "scope_agents": star(sc["agents"]),
        "scope_tools": star(sc["tools"]),
        "scope_data_classes": ", ".join(sc["data_classes"]),
        "benchmark_pack": d.get("benchmark_pack", ""),
        "min_tpr_pct": str(th["min_tpr_pct"]),
        "max_fpr_pct": str(th["max_fpr_pct"]),
        "max_p95_ms": str(th["max_p95_ms"]),
        "shadow_days": str(d["lifecycle"]["shadow_days"]),
        "config_json": json.dumps(d["config"], indent=2, ensure_ascii=False, sort_keys=True),
    }


def definition_from_form(form: dict[str, str], current: dict[str, Any] | None) -> dict[str, Any]:
    """The definition dict for the store. Fields the form does not carry (allow-list, the
    lifecycle beyond draft) come from the stored version."""
    raw = form.get("config_json") or "{}"
    try:
        config = json.loads(raw)
    except ValueError:
        raise GuardianFactoryError(
            "invalid_definition",
            "config: not valid JSON",
            [{"field": "config", "message": "not valid JSON"}],
        ) from None
    life = dict((current or {}).get("lifecycle") or {})
    life["shadow_days"] = _int(form, "shadow_days", "lifecycle.shadow_days")
    return {
        "id": form.get("id", ""),
        "name": form.get("name", ""),
        "description": form.get("description", ""),
        "owner_group": form.get("owner_group", ""),
        "type": form.get("type", ""),
        "stage": form.get("stage", ""),
        "action_on_fail": form.get("action_on_fail", ""),
        "sensitivity": _int(form, "sensitivity", "sensitivity"),
        "scope": {
            "agents": _star_or_list(form.get("scope_agents", "")),
            "tools": _star_or_list(form.get("scope_tools", "")),
            "data_classes": _csv(form.get("scope_data_classes", "")),
        },
        "config": config,
        "benchmark_pack": form.get("benchmark_pack", "").strip(),
        "thresholds": {
            "min_tpr_pct": _int(form, "min_tpr_pct", "thresholds.min_tpr_pct"),
            "max_fpr_pct": _int(form, "max_fpr_pct", "thresholds.max_fpr_pct"),
            "max_p95_ms": _int(form, "max_p95_ms", "thresholds.max_p95_ms"),
        },
        "lifecycle": life,
    }


def panel_data(
    ctx: ConsoleContext,
    me: AuthPrincipal,
    def_id: str,
    vals: dict[str, str] | None = None,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    svc = _svc(ctx)
    view = None if def_id == NEW else svc.get(def_id)
    owner = (view or {}).get("owner_group") or (vals or {}).get("owner_group") or ""
    can = agent_detail.can(me, "guardians.edit") and (not owner or gstore.can_edit(me, owner))
    editable = can and (view is None or view["state"] in gstore.EDITABLE)
    bench = bench_data(ctx, me, def_id) if view is not None else {}
    return {
        **bench,
        "gf": {
            "id": def_id,
            "is_new": view is None,
            "view": view,
            "vals": vals if vals is not None else vals_from_def(view),
            "draft": draft,
            "can_edit": can,
            "editable": editable,
            "groups": owner_groups(),
            "types": caps.TYPES,
            "stages": caps.STAGES,
            "actions": caps.ACTIONS_BY_TYPE,
            "all_actions": caps.ACTIONS,
            "states": caps.STATES,
            "base": "/console/guardian-factory",
            "events": _events(ctx, def_id) if view else [],
        },
    }


def _events(ctx: ConsoleContext, def_id: str) -> list[dict[str, Any]]:
    rows = ctx.tables.query(gstore.EVENTS, {"def_id": def_id}, order_by=("at",), limit=50)
    return [
        {
            "version": int(r["version"]),
            "action": r["action"],
            "from_state": r.get("from_state") or "-",
            "to_state": r["to_state"],
            "actor": r["actor"],
            "at": str(r["at"]),
        }
        for r in rows
    ]


def list_data(ctx: ConsoleContext, request: Request) -> dict[str, Any]:
    svc = _svc(ctx)
    filters = {
        k: request.query_params.get(k, "") for k in ("state", "owner_group", "stage", "type")
    }
    return {
        "gl": {
            "rows": svc.list_defs(filters),
            "counts": svc.counts(),
            "filters": filters,
            "groups": owner_groups(),
            "types": caps.TYPES,
            "stages": caps.STAGES,
            "states": caps.STATES,
            "base": "/console/guardian-factory",
        }
    }


@router.get(
    "/guardian-factory",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.view"))],
)
async def registry_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _svc(ctx)
    data = await _call(list_data, ctx, request)
    template = "_gf_list.html" if request.headers.get("hx-request") == "true" else "gf_list.html"
    return render(request, ctx, me, template, section="", **data)


@router.get(
    "/guardian-factory/{def_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.view"))],
)
async def editor_page(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _svc(ctx)
    _check_id(def_id, "guardian id")
    try:
        data = await _call(panel_data, ctx, me, def_id)
    except NotFoundError as exc:
        return _not_found(exc)
    template = (
        "_gf_editor.html" if request.headers.get("hx-request") == "true" else "gf_editor.html"
    )
    return render(request, ctx, me, template, section="", **data)


async def _respond(
    request: Request,
    ctx: ConsoleContext,
    me: AuthPrincipal,
    def_id: str,
    plain: bool,
    note: str,
    vals: dict[str, str] | None = None,
    draft: dict[str, Any] | None = None,
) -> Response:
    if plain and vals is None:
        return RedirectResponse(
            f"/console/guardian-factory/{def_id}?lang={_lang(request, ctx)}", status_code=303
        )
    data = await _call(panel_data, ctx, me, def_id, vals, draft)
    resp = render(
        request, ctx, me, "gf_editor.html" if plain else "_gf_editor.html", section="", **data
    )
    if not plain and note:
        resp.body = resp.body + message_html(note, ok=True, oob=True).encode()
        resp.headers["content-length"] = str(len(resp.body))
    return resp


@router.post(
    "/guardian-factory/{def_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.edit"))],
)
@audited("guardians.edit")
async def editor_save(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Save the draft (``new`` creates it). Validation errors answer HTTP 400 with the field."""
    svc = _svc(ctx)
    _check_id(def_id, "guardian id")
    form, plain = await form_or_plain(request)
    try:
        current = None if def_id == NEW else (await _call(svc.get, def_id))["definition"]
        data = definition_from_form(
            {**form, "id": form.get("id", "") if def_id == NEW else def_id}, current
        )
        out = await _call(
            svc.create if def_id == NEW else svc.save,
            *([data, me] if def_id == NEW else [def_id, data, me]),
        )
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"guardian_def save {out['id']}"
    if def_id == NEW:
        target = f"/console/guardian-factory/{out['id']}?lang={_lang(request, ctx)}"
        if plain:
            return RedirectResponse(target, status_code=303)
        return Response(status_code=200, headers={"HX-Redirect": target})
    return await _respond(request, ctx, me, out["id"], plain, f"{out['id']}: saved")


@router.post(
    "/guardian-factory/{def_id}/draft",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.edit"))],
)
@audited("guardians.edit")
async def editor_draft(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """ "Draft the artifact": the plain words become a draft that fills the artifact box. Nothing
    is saved; the person edits the box and presses Save."""
    _svc(ctx)
    _check_id(def_id, "guardian id")
    form, plain = await form_or_plain(request)
    vals = {**vals_from_def(None), **{k: form[k] for k in _SCALARS if k in form}}
    out = await _call(ctx.guardian_author.draft, vals["type"], form.get("text"))
    vals["config_json"] = json.dumps(out["config"], indent=2, ensure_ascii=False, sort_keys=True)
    if not vals["name"].strip():
        vals["name"] = out["name"]
    if not vals["description"].strip():
        vals["description"] = out["description"]
    if vals["action_on_fail"] not in caps.ACTIONS_BY_TYPE.get(vals["type"], ()):
        vals["action_on_fail"] = "log"
    request.state.audit_detail = f"guardian_def draft {out['source']}"
    draft = {**out, "text": form.get("text", "")}
    return await _respond(request, ctx, me, def_id, plain, "", vals, draft)


async def _console_move(
    what: str, def_id: str, request: Request, ctx: ConsoleContext, me: AuthPrincipal
) -> Response:
    svc = _svc(ctx)
    _check_id(def_id, "guardian id")
    _, plain = await form_or_plain(request)
    fn = {
        "retire": svc.retire,
        "reopen": svc.reopen,
        "new-version": svc.new_version,
        "mark-benchmarked": svc.mark_benchmarked,
    }[what]
    try:
        out = await _call(fn, def_id, me)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"guardian_def {what} {def_id}"
    return await _respond(
        request,
        ctx,
        me,
        def_id,
        plain,
        f"{def_id}: {what} -> version {out['version']} {out['state']}",
    )


@router.post(
    "/guardian-factory/{def_id}/retire",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.edit"))],
)
@audited("guardians.edit")
async def editor_retire(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    return await _console_move("retire", def_id, request, ctx, me)


@router.post(
    "/guardian-factory/{def_id}/reopen",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.edit"))],
)
@audited("guardians.edit")
async def editor_reopen(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    return await _console_move("reopen", def_id, request, ctx, me)


@router.post(
    "/guardian-factory/{def_id}/new-version",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.edit"))],
)
@audited("guardians.edit")
async def editor_new_version(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    return await _console_move("new-version", def_id, request, ctx, me)


# ------------------------------------------------------------------------------- benchmark (WP-G2)
# JSON API: GET/POST /v1/guardian-defs/{id}/bench-packs, POST .../benchmark,
# GET .../benchmark/{run_id}, POST .../mark-benchmarked. Console: the Benchmark panel at
# /console/guardian-factory/{id}/benchmark and its POST actions. Same flag, same 400.

_UPLOAD_LIMIT = caps.BENCH_MAX_BYTES + 65_536


async def _json_body(request: Request) -> dict[str, Any]:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > 2 * _UPLOAD_LIMIT:
        raise GuardianFactoryError("pack_too_large", "the request body is too large")
    raw = await request.body()
    if len(raw) > 2 * _UPLOAD_LIMIT:
        raise GuardianFactoryError("pack_too_large", "the request body is too large")
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise GuardianFactoryError("bad_request", "request body must be JSON") from None
    if not isinstance(data, dict):
        raise GuardianFactoryError("bad_request", "request body must be a JSON object")
    return data


def _bench(ctx: ConsoleContext) -> Any:
    gstore.require_on(ctx.settings)
    return ctx.guardian_bench


def _pack_op(svc: Any, def_id: str, data: dict[str, Any], me: AuthPrincipal) -> dict[str, Any]:
    op = data.get("op")
    extra = sorted(set(data) - {"op", "pack_id", "attack_jsonl", "benign_jsonl", "limit"})
    if extra:
        raise GuardianFactoryError("bad_request", f"unknown key: {', '.join(extra)}")
    if op == "upload":
        for k in ("attack_jsonl", "benign_jsonl"):
            if data.get(k) is not None and not isinstance(data[k], str):
                raise GuardianFactoryError("bad_request", f"{k}: JSONL text")
        return svc.upload(
            def_id, data.get("pack_id"), data.get("attack_jsonl"), data.get("benign_jsonl"), me
        )
    if op == "generate":
        return svc.generate(def_id, data.get("pack_id"), me)
    if op == "import_traces":
        kw = {"limit": data["limit"]} if "limit" in data else {}
        return svc.import_traces(def_id, data.get("pack_id"), me, **kw)
    raise GuardianFactoryError("bad_request", "op: upload, generate or import_traces")


@api_router.get(
    "/guardian-defs/{def_id}/bench-packs", dependencies=[Depends(needs("guardians.view"))]
)
def list_bench_packs(def_id: str, ctx: ConsoleContext = _CTX) -> Any:
    svc = _bench(ctx)
    _check_id(def_id, "guardian id")
    try:
        return {"items": svc.list_packs(def_id)}
    except NotFoundError as exc:
        return _not_found(exc)


@api_router.post(
    "/guardian-defs/{def_id}/bench-packs", dependencies=[Depends(needs("guardians.edit"))]
)
@audited("guardians.edit")
async def post_bench_pack(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _bench(ctx)
    _check_id(def_id, "guardian id")
    data = await _json_body(request)
    try:
        out = await _call(_pack_op, svc, def_id, data, me)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"guardian_bench pack {data.get('op')} {def_id}/{out['id']}"
    return JSONResponse(status_code=201, content=out)


@api_router.post(
    "/guardian-defs/{def_id}/benchmark", dependencies=[Depends(needs("guardians.edit"))]
)
@audited("guardians.edit")
async def post_benchmark(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    svc = _bench(ctx)
    _check_id(def_id, "guardian id")
    data = await _json_body(request)
    extra = sorted(set(data) - {"pack_id"})
    if extra:
        raise GuardianFactoryError("bad_request", f"unknown key: {', '.join(extra)}")
    try:
        out = await _call(svc.start_run, def_id, me, data.get("pack_id"))
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"guardian_bench run {def_id} {out['run_id']}"
    return JSONResponse(status_code=202, content=out)


@api_router.get(
    "/guardian-defs/{def_id}/benchmark/{run_id}", dependencies=[Depends(needs("guardians.view"))]
)
def get_benchmark(def_id: str, run_id: str, ctx: ConsoleContext = _CTX) -> Any:
    svc = _bench(ctx)
    _check_id(def_id, "guardian id")
    _check_id(run_id, "run id")
    try:
        return svc.get_run(def_id, run_id)
    except NotFoundError as exc:
        return _not_found(exc)


@api_router.post(
    "/guardian-defs/{def_id}/mark-benchmarked", dependencies=[Depends(needs("guardians.edit"))]
)
@audited("guardians.edit")
async def post_mark_benchmarked(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Any:
    return await _move("mark-benchmarked", def_id, request, ctx, me)


def bench_data(ctx: ConsoleContext, me: AuthPrincipal, def_id: str) -> dict[str, Any]:
    """The data of the Benchmark panel."""
    svc = _bench(ctx)
    store = ctx.guardian_defs
    view = store.get(def_id)
    row = store._latest(def_id)  # noqa: SLF001
    can = bool(
        agent_detail.can(me, "guardians.edit")
        and gstore.can_edit(me, view["owner_group"])
        and view["state"] in gstore.EDITABLE
    )
    runs = svc.list_runs(def_id, 5)
    latest = runs[0] if runs else None
    why = store.bench_problem(row) if view["state"] == "draft" else ""
    d = view["definition"]
    return {
        "gb": {
            "id": def_id,
            "base": f"/console/guardian-factory/{def_id}",
            "view": view,
            "can_edit": can,
            "packs": svc.list_packs(def_id),
            "runs": runs,
            "latest": latest,
            "active": bool(latest and latest["status"] in ("queued", "running")),
            "can_mark": can and view["state"] == "draft" and not why,
            "mark_problem": why,
            "pack_id": d.get("benchmark_pack", ""),
            "thresholds": d["thresholds"],
            "sensitivity": d["sensitivity"],
            "generator_ok": d["type"] in ("regex", "keyword_list"),
        }
    }


@router.get(
    "/guardian-factory/{def_id}/benchmark",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.view"))],
)
async def bench_page(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _svc(ctx)
    _check_id(def_id, "guardian id")
    try:
        data = await _call(bench_data, ctx, me, def_id)
    except NotFoundError as exc:
        return _not_found(exc)
    template = "_gf_bench.html" if request.headers.get("hx-request") == "true" else "gf_bench.html"
    return render(request, ctx, me, template, section="", **data)


async def _bench_respond(
    request: Request, ctx: ConsoleContext, me: AuthPrincipal, def_id: str, plain: bool, note: str
) -> Response:
    if plain:
        return RedirectResponse(
            f"/console/guardian-factory/{def_id}/benchmark?lang={_lang(request, ctx)}",
            status_code=303,
        )
    data = await _call(bench_data, ctx, me, def_id)
    resp = render(request, ctx, me, "_gf_bench.html", section="", **data)
    if note:
        resp.body = resp.body + message_html(note, ok=True, oob=True).encode()
        resp.headers["content-length"] = str(len(resp.body))
    return resp


@router.post(
    "/guardian-factory/{def_id}/bench-packs/{op}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.edit"))],
)
@audited("guardians.edit")
async def bench_pack_action(
    def_id: str, op: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    """Console pack actions: ``upload`` (one multipart file, ``which`` = attack or benign),
    ``generate``, ``import-traces``. Every refusal is HTTP 400 with a message."""
    from supervisor.console.intake_routes import _same_site, parse_multipart
    from supervisor.console.routes import _htmx_only

    svc = _bench(ctx)
    _check_id(def_id, "guardian id")
    _htmx_only(request)
    if op not in ("upload", "generate", "import-traces"):
        raise GuardianFactoryError("bad_request", "op: upload, generate or import-traces")
    _same_site(request)
    work: Any
    if op == "upload":
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > _UPLOAD_LIMIT:
            raise GuardianFactoryError("pack_too_large", "the file is larger than 5 MB")
        body = await request.body()
        if len(body) > _UPLOAD_LIMIT:
            raise GuardianFactoryError("pack_too_large", "the file is larger than 5 MB")
        files, fields = parse_multipart(request.headers.get("content-type", ""), body)
        if not files:
            raise GuardianFactoryError("pack_invalid", "choose a .jsonl file")
        which = fields.get("which", "")
        if which not in ("attack", "benign"):
            raise GuardianFactoryError("bad_request", "which: attack or benign")
        raw = files[0][1]

        def work() -> dict[str, Any]:
            return svc.upload(
                def_id,
                fields.get("pack_id", ""),
                raw if which == "attack" else None,
                raw if which == "benign" else None,
                me,
            )

    else:
        fields, _ = await form_or_plain(request)

        def work() -> dict[str, Any]:
            if op == "generate":
                return svc.generate(def_id, fields.get("pack_id", ""), me)
            raw_limit = (fields.get("limit") or "").strip()
            kw: dict[str, int] = {}
            if raw_limit:
                if not raw_limit.isdigit():
                    raise GuardianFactoryError("bad_limit", "limit: a whole number from 1")
                kw["limit"] = int(raw_limit)
            return svc.import_traces(def_id, fields.get("pack_id", ""), me, **kw)

    try:
        out = await _call(work)
    except NotFoundError as exc:
        return _not_found(exc)
    note = f"pack {out['id']} v{out['version']}: {out['attack']} attack, {out['benign']} benign"
    request.state.audit_detail = f"guardian_bench pack {op} {def_id}/{out['id']}"
    return await _bench_respond(request, ctx, me, def_id, False, note)


@router.post(
    "/guardian-factory/{def_id}/benchmark",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.edit"))],
)
@audited("guardians.edit")
async def bench_run_action(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    svc = _bench(ctx)
    _check_id(def_id, "guardian id")
    fields, plain = await form_or_plain(request)
    pid = (fields.get("pack_id") or "").strip() or None
    try:
        out = await _call(svc.start_run, def_id, me, pid)
    except NotFoundError as exc:
        return _not_found(exc)
    request.state.audit_detail = f"guardian_bench run {def_id} {out['run_id']}"
    note = f"benchmark {out['run_id']} started"
    return await _bench_respond(request, ctx, me, def_id, plain, note)


@router.post(
    "/guardian-factory/{def_id}/mark-benchmarked",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("guardians.edit"))],
)
@audited("guardians.edit")
async def editor_mark_benchmarked(
    def_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    return await _console_move("mark-benchmarked", def_id, request, ctx, me)
