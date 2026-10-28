"""FastAPI application. Databricks App command: python -m uvicorn supervisor.app:app."""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import logging  # noqa: E402
import platform  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from typing import Any  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse, Response  # noqa: E402

from supervisor import __version__, scheduler  # noqa: E402
from supervisor.adapters.auth.audit import request_id_of  # noqa: E402
from supervisor.analytics.tools_routes import router as tools_analytics_router  # noqa: E402
from supervisor.cases.service import PermissionDenied  # noqa: E402
from supervisor.config import get_settings  # noqa: E402
from supervisor.console import context as console_context  # noqa: E402
from supervisor.console.errors import console_error, is_console  # noqa: E402
from supervisor.console.regkb_routes import router as regkb_console_router  # noqa: E402
from supervisor.console.routes import router as console_router  # noqa: E402
from supervisor.controls.api import router as controls_router  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.evidence.casefile.builder import CaseFileError  # noqa: E402
from supervisor.gateway import ingress_auth  # noqa: E402
from supervisor.gateway import wiring as gate_wiring  # noqa: E402
from supervisor.gateway.routes import router as gate_router  # noqa: E402
from supervisor.inventory.api import router as inventory_router  # noqa: E402
from supervisor.mcp_tools.api import router as mcp_lock_router  # noqa: E402
from supervisor.monitors.session_api import router as session_router  # noqa: E402
from supervisor.ops import healthz as healthz_body  # noqa: E402
from supervisor.ops import middleware as ops_middleware  # noqa: E402
from supervisor.ops import openapi as openapi_doc  # noqa: E402
from supervisor.ops import schema_selfcheck  # noqa: E402
from supervisor.ops.logging_setup import configure_logging  # noqa: E402
from supervisor.ops.readiness import readiness  # noqa: E402
from supervisor.recorder.otlp_receiver import router as otlp_router  # noqa: E402
from supervisor.risk.api import router as risk_router  # noqa: E402
from supervisor.tasks.api import router as tasks_router  # noqa: E402
from supervisor.transparency.api import router as transparency_router  # noqa: E402

log = logging.getLogger("supervisor.app")
configure_logging(get_settings())  # WP18: LOG_LEVEL / LOG_FORMAT / LOG_FILE (idempotent)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Startup: build the runtime (store, policy, evidence chain, gateway) once.

    A failure here is logged, not fatal: /healthz still answers and the routes retry
    the build on first use (they fail closed until it succeeds). Shutdown always seals
    the chain of whichever runtime was installed. One process, one worker: the chain
    has a single writer (app.yaml runs uvicorn without --workers)."""
    runtime = None
    if not get_settings().console_audit_enabled:
        log.warning("CONSOLE_AUDIT_ENABLED=0 (dev mode): console actions are NOT audited")
    try:  # WP20: one log line when ingress auth is off (non-dev) or cannot work
        ingress_auth.startup_check(get_settings())
    except Exception:  # noqa: BLE001 - never block startup
        log.exception("ingress auth startup check failed")
    try:
        runtime = await run_in_threadpool(gate_wiring.install_runtime, get_settings())
    except Exception:  # noqa: BLE001 - startup must not crash the app process
        log.exception("runtime build failed at startup; gateway routes will retry")
        if get_settings().sql_user_token_forward:  # WP-P5
            log.warning(
                "[WARN] SP has no SQL access; the runtime was not built. Console reads run as the "
                "signed-in user; gateway and evidence chain answer HTTP 400 until the service "
                "principal is granted"
            )
    try:  # WP-P3: read-only schema self-check (SCHEMA_SELFCHECK=1); never blocks startup
        check = await run_in_threadpool(schema_selfcheck.run_startup, get_settings(), runtime)
        if check is not None:
            app.state.schema_check = check
    except Exception:  # noqa: BLE001
        log.warning("schema self-check did not run", exc_info=True)
    if runtime is not None:  # WP7: in-process scheduler (on in laptop mode by default)
        try:
            await run_in_threadpool(scheduler.start_for_runtime, get_settings(), runtime)
        except Exception:  # noqa: BLE001 - the app serves without the scheduler
            log.exception("scheduler did not start")
    try:
        yield
    finally:
        try:
            # Before the chain is sealed: no job writes after it. Off the event loop:
            # stop() waits for a running job.
            await run_in_threadpool(scheduler.stop)
        finally:
            console_context.set_context(None)  # WP8: the console context holds the runtime
            gate_wiring.shutdown_runtime()


app = FastAPI(
    title="Supervisor",
    version=__version__,
    lifespan=lifespan,
    openapi_tags=openapi_doc.TAGS,
    # Swagger UI / ReDoc load their JS from a CDN: not allowed offline and blocked by the
    # CSP. The schema stays at /openapi.json (docs/api.md).
    docs_url=None,
    redoc_url=None,
)
# WP18 API versioning (docs/api.md): /v1/gate/... is the versioned path; /gate/... keeps
# working and is marked deprecated in the schema only.
app.include_router(gate_router, prefix="/v1")
app.include_router(gate_router, deprecated=True)
app.include_router(otlp_router)  # WP4: POST /v1/traces (OTLP/HTTP JSON)
app.include_router(console_router)  # WP8: reviewer console (/console)
app.include_router(regkb_console_router)  # WP-L1: /console/regkb/<id>/drafts (400 while off)
app.include_router(tools_analytics_router, prefix="/v1")  # WP22: GET /v1/analytics/tools
app.include_router(inventory_router)  # WP24: GET /v1/inventory/... (off unless INVENTORY_ENABLED)
app.include_router(mcp_lock_router)  # WP26: /v1/mcp/tools/... (off unless MCP_HTTP_ENABLED)
app.include_router(risk_router)  # WP29: /v1/risks/... (off unless RISK_REGISTER_ENABLED)
app.include_router(session_router)  # WP27: /v1/sessions/{id} (off unless SESSION_MONITOR_ENABLED)
app.include_router(controls_router)  # WP30: /v1/controls/... (off unless CONTROLS_ENABLED)
app.include_router(tasks_router)  # WP30: /v1/tasks/... (off unless CONTROLS_ENABLED)
app.include_router(
    transparency_router
)  # WP31: /v1/transparency/... (off unless TRANSPARENCY_ENABLED)
if get_settings().governance_enabled:  # WP-G0: mounted only when the flag is on
    from supervisor.governance.routes import router as systems_router

    app.include_router(systems_router)  # /v1/systems/...
    from supervisor.governance.rules_routes import router as rules_router  # WP-G2

    app.include_router(rules_router)  # /v1/systems/{id}/assignments, /classification, ...
if get_settings().governance_enabled and get_settings().guardian_bindings_enabled:  # WP-S1
    from supervisor.governance.guardian_routes import console_router as guardians_console_router
    from supervisor.governance.guardian_routes import router as guardians_router

    app.include_router(guardians_router)  # /v1/systems/{id}/guardians
    app.include_router(guardians_console_router)  # POST /console/systems/{id}/guardians/{slug}
if get_settings().console_systems_enabled:  # WP-G0: /console/systems (needs the flag above)
    from supervisor.console.systems_routes import router as systems_console_router

    app.include_router(systems_console_router)
if get_settings().console_overview_v4:  # WP-N1: mounted only when the flag is on
    from supervisor.console.candidates_routes import api_router as candidates_api_router
    from supervisor.console.candidates_routes import router as candidates_console_router

    app.include_router(candidates_console_router)  # /console/candidates
    app.include_router(candidates_api_router)  # GET /v1/candidates
# WP-O1: always mounted; with ONBOARD_INTAKE=0 every route answers HTTP 400 with the flag name
from supervisor.console.intake_routes import api_router as intake_api_router  # noqa: E402
from supervisor.console.intake_routes import router as intake_console_router  # noqa: E402

app.include_router(intake_console_router)  # /console/intake/{node_id}
app.include_router(intake_api_router)  # /v1/intake/{node_id}
# WP-O2: always mounted; with ONBOARD_FACTS=0 every route answers HTTP 400 with the flag name
from supervisor.console.facts_routes import api_router as facts_api_router  # noqa: E402
from supervisor.console.facts_routes import router as facts_console_router  # noqa: E402

app.include_router(facts_console_router)  # /console/facts/{node_id}
app.include_router(facts_api_router)  # /v1/facts/{node_id}
# WP-O3: always mounted; with ONBOARD_PREDEPLOY=0 every route answers HTTP 400 predeploy_off
from supervisor.console.predeploy_routes import api_router as predeploy_api_router  # noqa: E402
from supervisor.console.predeploy_routes import router as predeploy_console_router  # noqa: E402

app.include_router(predeploy_console_router)  # /console/predeploy/{node_id}
app.include_router(predeploy_api_router)  # /v1/predeploy/{node_id}
if get_settings().governance_actions_enabled:  # WP-G5: mounted only when the flag is on
    from supervisor.console.incidents_routes import router as incidents_console_router
    from supervisor.governance.incident_routes import router as incidents_router

    app.include_router(incidents_router)  # /v1/incidents/...
    app.include_router(incidents_console_router)  # /console/incidents (needs GOVERNANCE_ENABLED)
if get_settings().agents_api_enabled:  # WP-P2: mounted only when the flag is on
    from supervisor.gateway.agents_routes import router as agents_router

    app.include_router(agents_router)  # /v1/agents
if get_settings().mcp_server_enabled:  # WP-G6: mounted only when the flag is on
    from supervisor.mcp_server.routes import admin_router as mcp_admin_router
    from supervisor.mcp_server.routes import mcp_router

    app.include_router(mcp_router)  # POST /mcp (JSON-RPC 2.0, streamable HTTP)
    app.include_router(mcp_admin_router)  # /v1/mcp/apps, /v1/kpis
openapi_doc.install(app)  # WP18: tags, security schemes
ops_middleware.install(app, get_settings())  # WP18: request id, headers, size and rate limits


@app.exception_handler(ingress_auth.IngressRejected)
async def _ingress_rejected(request: Request, exc: ingress_auth.IngressRejected) -> Response:
    # WP20: 401/403 (and 413/429) with a short message and no detail; the reason is audited.
    return JSONResponse(
        status_code=exc.status_code, content={"error": exc.detail}, headers=exc.headers
    )


@app.exception_handler(PermissionDenied)
async def _permission_denied(request: Request, exc: PermissionDenied) -> Response:
    # WP18: a missing role is 403 (still a 4xx user error with a message, never 5xx).
    if is_console(request):
        return console_error(request, str(exc), 403)
    return JSONResponse(status_code=403, content={"error": str(exc)})


@app.exception_handler(SupervisorError)
async def _supervisor_error(request: Request, exc: SupervisorError) -> Response:
    # htmx drops 5xx silently; user-visible errors are 400 with a message.
    if is_console(request):  # WP8: an HTML message partial htmx can render
        return console_error(request, str(exc))
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(CaseFileError)
async def _case_file_error(request: Request, exc: CaseFileError) -> Response:
    # Minor 1: a missing / unbuildable case file is a 404, not a generic 400.
    if is_console(request):
        return console_error(request, str(exc), 404)
    return JSONResponse(status_code=404, content={"error": str(exc)})


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
    if is_console(request):
        return console_error(request, "invalid request")
    return JSONResponse(
        status_code=400, content={"error": "invalid request", "detail": exc.errors()}
    )


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> Response:
    log.error(
        "unhandled error request_id=%s class=%s",
        request_id_of(request),
        type(exc).__name__,
        exc_info=exc,
    )
    if is_console(request):
        return console_error(
            request, f"unexpected error: {type(exc).__name__}. See the server log."
        )
    return JSONResponse(
        status_code=400,
        content={"error": f"unexpected error: {type(exc).__name__}. See the server log."},
    )


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/console/", status_code=303)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, Any]:
    """Liveness plus the live-run facts of WP-P3: schema_ok, judge_sweep, gate_timeout_s,
    model_resource. Fast and secret-free; the model probe runs in the background."""
    return healthz_body.body(get_settings(), scheduler.current())


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness for probes: 200 while the process runs."""
    return {"status": "ok", "version": __version__}


@app.get("/ready", tags=["ops"])
def ready() -> JSONResponse:
    """Readiness for probes (not users): 200 when ready, else 503 with the failed check names.
    The body has no secrets, hosts, paths or error text."""
    body = readiness(get_settings(), getattr(gate_wiring, "_runtime", None), scheduler.current())
    return JSONResponse(body, status_code=200 if body["ready"] else 503)


@app.get("/version", tags=["ops"])
def version() -> dict[str, str]:
    settings = get_settings()
    return {
        "version": __version__,
        "mode": settings.supervisor_mode,
        "sql_backend": settings.effective_sql_backend,
        "python": platform.python_version(),
    }
