"""FastAPI application. Databricks App command: python -m uvicorn supervisor.app:app."""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import logging  # noqa: E402
import platform  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse, Response  # noqa: E402

from supervisor import __version__  # noqa: E402
from supervisor.config import get_settings  # noqa: E402
from supervisor.console import context as console_context  # noqa: E402
from supervisor.console.errors import console_error, is_console  # noqa: E402
from supervisor.console.routes import router as console_router  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.gateway import wiring as gate_wiring  # noqa: E402
from supervisor.gateway.routes import router as gate_router  # noqa: E402
from supervisor.recorder.otlp_receiver import router as otlp_router  # noqa: E402

log = logging.getLogger("supervisor.app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Startup: build the runtime (store, policy, evidence chain, gateway) once.

    A failure here is logged, not fatal: /healthz still answers and the routes retry
    the build on first use (they fail closed until it succeeds). Shutdown always seals
    the chain of whichever runtime was installed. One process, one worker: the chain
    has a single writer (app.yaml runs uvicorn without --workers)."""
    try:
        await run_in_threadpool(gate_wiring.install_runtime, get_settings())
    except Exception:  # noqa: BLE001 - startup must not crash the app process
        log.exception("runtime build failed at startup; gateway routes will retry")
    try:
        yield
    finally:
        console_context.set_context(None)  # WP8: the console context holds the runtime
        gate_wiring.shutdown_runtime()


app = FastAPI(title="Supervisor", version=__version__, lifespan=lifespan)
app.include_router(gate_router)
app.include_router(otlp_router)  # WP4: POST /v1/traces (OTLP/HTTP JSON)
app.include_router(console_router)  # WP8: reviewer console (/console)


@app.exception_handler(SupervisorError)
async def _supervisor_error(request: Request, exc: SupervisorError) -> Response:
    # htmx drops 5xx silently; user-visible errors are 400 with a message.
    if is_console(request):  # WP8: an HTML message partial htmx can render
        return console_error(request, str(exc))
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
    if is_console(request):
        return console_error(request, "invalid request")
    return JSONResponse(
        status_code=400, content={"error": "invalid request", "detail": exc.errors()}
    )


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> Response:
    log.exception("unhandled error")
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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
def version() -> dict[str, str]:
    settings = get_settings()
    return {
        "version": __version__,
        "mode": settings.supervisor_mode,
        "sql_backend": settings.effective_sql_backend,
        "python": platform.python_version(),
    }
