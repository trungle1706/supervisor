"""FastAPI application. Databricks App command: python -m uvicorn supervisor.app:app."""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import logging  # noqa: E402
import platform  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from supervisor import __version__  # noqa: E402
from supervisor.config import get_settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402

log = logging.getLogger("supervisor.app")

app = FastAPI(title="Supervisor", version=__version__)


@app.exception_handler(SupervisorError)
async def _supervisor_error(_: Request, exc: SupervisorError) -> JSONResponse:
    # htmx drops 5xx silently; user-visible errors are 400 with a message.
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400, content={"error": "invalid request", "detail": exc.errors()}
    )


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse(
        status_code=400,
        content={"error": f"unexpected error: {type(exc).__name__}. See the server log."},
    )


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
