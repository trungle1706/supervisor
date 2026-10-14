"""Principal adapters (WP8): ``dev_header`` (laptop) and ``databricks_app`` (SSO headers).

``current_principal`` is the FastAPI dependency. It resolves the caller once per request,
puts the user token (if any) on ``request.state.user_token`` for that request only, and
returns an ``AuthPrincipal``. Errors are ``AuthError`` (HTTP 400 with a message).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from fastapi import Request

from supervisor.adapters.auth.base import (
    ROLES,
    AuthError,
    AuthPrincipal,
    PrincipalProvider,
    UserToken,
)

if TYPE_CHECKING:
    from supervisor.config import Settings

_lock = threading.Lock()
_provider: PrincipalProvider | None = None


def build_principal_provider(settings: Settings) -> PrincipalProvider:
    if settings.effective_auth_kind == "databricks_app":
        from supervisor.adapters.auth.databricks_app import DatabricksAppPrincipal

        assert settings.auth_config_file is not None
        return DatabricksAppPrincipal.from_file(
            settings.auth_config_file, host=settings.databricks_host
        )
    from supervisor.adapters.auth.dev_header import DevHeaderPrincipal

    assert settings.users_file is not None
    return DevHeaderPrincipal.from_file(settings.users_file)


def set_provider(provider: PrincipalProvider | None) -> None:
    """Install the process-wide provider (app startup, tests)."""
    global _provider
    with _lock:
        _provider = provider


def get_provider() -> PrincipalProvider:
    global _provider
    with _lock:
        if _provider is None:
            from supervisor.config import get_settings

            _provider = build_principal_provider(get_settings())
        return _provider


def current_principal(request: Request) -> AuthPrincipal:
    """FastAPI dependency: who is calling. The token stays on this request only."""
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, AuthPrincipal):
        return cached
    principal, token = get_provider().resolve(request.headers, request.cookies)
    request.state.principal = principal
    request.state.user_token = token
    return principal


def request_user_token(request: Request) -> UserToken | None:
    """The signed-in user's token for this request (Databricks App), or None."""
    return getattr(request.state, "user_token", None)


__all__ = [
    "ROLES",
    "AuthError",
    "AuthPrincipal",
    "PrincipalProvider",
    "UserToken",
    "build_principal_provider",
    "current_principal",
    "get_provider",
    "request_user_token",
    "set_provider",
]
