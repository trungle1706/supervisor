"""OpenAPI document: tags per area, security schemes, agent-ingress notes (WP18).

``install(app)`` replaces ``app.openapi`` with a cached builder. The document describes
the API only; it changes no behaviour. Policy: ``docs/api.md``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

TAGS: list[dict[str, str]] = [
    {
        "name": "gate",
        "description": "Gateway. POST /v1/gate/check decides one tool call (agent ingress); "
        "pause, resume, quarantine, release, state and metrics are control and read routes "
        "for human principals. /gate/... without /v1 is deprecated.",
    },
    {
        "name": "traces",
        "description": "Trace ingest (OTLP/HTTP JSON). POST /v1/traces is agent ingress.",
    },
    {
        "name": "console",
        "description": "Reviewer console (HTML UI for people, not a stable API).",
    },
    {
        "name": "analytics",
        "description": "Analytics read routes (WP22): GET /v1/analytics/tools, the tool usage "
        "rollup. Off unless TOOL_ANALYTICS_ENABLED=1.",
    },
    {
        "name": "ops",
        "description": "Operations: /health (liveness), /ready (readiness), /healthz, /version.",
    },
]

SECURITY_SCHEMES: dict[str, dict[str, Any]] = {
    "devHeader": {
        "type": "apiKey",
        "in": "header",
        "name": "X-Dev-User",
        "description": "Laptop only. The user name is looked up in a local users file. It is "
        "NOT a real identity (ADR D04).",
    },
    "databricksSSO": {
        "type": "apiKey",
        "in": "header",
        "name": "X-Forwarded-Email",
        "description": "Set by the Databricks App proxy after SSO.",
    },
}

_HUMAN_SECURITY: list[dict[str, list[str]]] = [{"devHeader": []}, {"databricksSSO": []}]
_INGRESS_NOTE = (
    "Agent ingress: called by agents (SDK or collector), not by people. No human "
    "identity is required."
)
_INGRESS = {"/gate/check", "/v1/gate/check", "/v1/traces"}
_METHODS = {"get", "put", "post", "delete", "patch", "head", "options"}


def _is_human_path(path: str) -> bool:
    if path in _INGRESS:
        return False
    return path.startswith(("/console", "/gate/", "/v1/gate/", "/v1/analytics/", "/v1/inventory/"))


def build_openapi(app: FastAPI) -> dict[str, Any]:
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="Supervisor gateway and reviewer console. Versioning policy: docs/api.md.",
        routes=app.routes,
        tags=TAGS,
    )
    schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schemes.update(SECURITY_SCHEMES)
    for path, item in schema.get("paths", {}).items():
        for method, op in item.items():
            if method not in _METHODS or not isinstance(op, dict):
                continue
            if path in _INGRESS:
                op["security"] = []
                op["description"] = (op.get("description", "") + "\n\n" + _INGRESS_NOTE).strip()
            elif _is_human_path(path):
                op["security"] = _HUMAN_SECURITY
    return schema


def install(app: FastAPI) -> None:
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = build_openapi(app)
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
