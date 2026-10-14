"""Databricks App identity: workspace SSO headers + a configured role map.

* User: ``X-Forwarded-Email`` (else ``X-Forwarded-User``); ``auth_method=databricks_sso``.
* Roles: ``config/auth.yaml`` ``roles.<role>.users`` and, with ``group_lookup: scim_me``,
  ``roles.<role>.groups`` matched against the user's workspace groups.
* ``X-Forwarded-Access-Token`` (bank guide 5.3): used inside the request only, through a
  fresh, uncached client per call (group lookup), never logged, never stored, never put in
  a principal. It is handed back as a ``UserToken`` for ``request.state`` only.
* No SSO header (local runs, background tasks): the app service principal, with
  ``service_principal_roles`` (none by default: read-only).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from supervisor.adapters.auth.base import ROLES, AuthError, AuthPrincipal, UserToken, clean_roles
from supervisor.config import is_placeholder

log = logging.getLogger("supervisor.auth")

USER_HEADERS = ("x-forwarded-email", "x-forwarded-user")
TOKEN_HEADER = "x-forwarded-access-token"  # noqa: S105 - a header name, not a secret
AUTH_METHOD = "databricks_sso"
SP_AUTH_METHOD = "databricks_app_sp"
DEFAULT_SP_ID = "app-service-principal"

GroupResolver = Callable[[str, UserToken], Sequence[str]]


def scim_me_groups(host: str, token: UserToken) -> list[str]:
    """Groups of the signed-in user via SCIM ``Me``. Fresh client per call; the token is
    revealed only into that client and the client is dropped at return."""
    from databricks.sdk import WorkspaceClient  # optional extra: databricks

    client = WorkspaceClient(host=host, token=token.reveal(), auth_type="pat")
    me = client.current_user.me()
    return [g.display for g in (me.groups or []) if getattr(g, "display", None)]


class DatabricksAppPrincipal:
    name = "databricks_app"

    def __init__(
        self,
        role_users: Mapping[str, Sequence[str]],
        role_groups: Mapping[str, Sequence[str]],
        *,
        service_principal_id: str = DEFAULT_SP_ID,
        service_principal_roles: Sequence[str] = (),
        group_lookup: str = "none",
        host: str | None = None,
        group_resolver: GroupResolver | None = None,
    ) -> None:
        if group_lookup not in ("none", "scim_me"):
            raise AuthError("auth config: group_lookup must be none or scim_me")
        self.role_users = {
            r: {u.strip().lower() for u in role_users.get(r, ()) if not is_placeholder(u)}
            for r in ROLES
        }
        self.role_groups = {
            r: {g.strip() for g in role_groups.get(r, ()) if not is_placeholder(g)} for r in ROLES
        }
        self.sp_id = service_principal_id
        self.sp_roles = clean_roles(service_principal_roles)
        self.group_lookup = group_lookup
        self.host = host
        self.group_resolver = group_resolver or scim_me_groups

    @classmethod
    def from_file(
        cls, path: Path, *, host: str | None = None, group_resolver: GroupResolver | None = None
    ) -> DatabricksAppPrincipal:
        try:
            doc: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError as exc:
            raise AuthError(f"cannot read auth config {path}: {exc.strerror}") from None
        except yaml.YAMLError as exc:
            raise AuthError(f"auth config {path} is not valid YAML: {exc}") from None
        roles = doc.get("roles") or {}
        if not isinstance(roles, Mapping):
            raise AuthError(f"auth config {path}: 'roles' must be a mapping")
        clean_roles(roles.keys())
        sp = str(doc.get("service_principal_id") or "")
        return cls(
            {r: [str(u) for u in (spec or {}).get("users") or ()] for r, spec in roles.items()},
            {r: [str(g) for g in (spec or {}).get("groups") or ()] for r, spec in roles.items()},
            service_principal_id=DEFAULT_SP_ID if is_placeholder(sp) else sp,
            service_principal_roles=doc.get("service_principal_roles") or (),
            group_lookup=str(doc.get("group_lookup") or "none"),
            host=host or os.environ.get("DATABRICKS_HOST"),
            group_resolver=group_resolver,
        )

    def _groups(self, user_id: str, token: UserToken | None) -> set[str]:
        if self.group_lookup != "scim_me" or token is None:
            return set()
        if not self.host:
            log.warning("group lookup skipped for %s: DATABRICKS_HOST is not set", user_id)
            return set()
        try:
            return set(self.group_resolver(self.host, token))
        except Exception as exc:  # noqa: BLE001 - roles fall back to the users list
            # Name the type only: an SDK message could echo request details.
            log.warning("group lookup failed for %s: %s", user_id, type(exc).__name__)
            return set()

    def resolve(
        self, headers: Mapping[str, str], cookies: Mapping[str, str]
    ) -> tuple[AuthPrincipal, UserToken | None]:
        user = next((headers.get(h, "").strip() for h in USER_HEADERS if headers.get(h)), "")
        if not user:
            return self.background(), None
        if len(user) > 256:
            raise AuthError("SSO user header is too long")
        raw_token = headers.get(TOKEN_HEADER, "").strip()
        token = UserToken(raw_token) if raw_token else None
        key = user.lower()
        groups = self._groups(user, token)
        roles = {r for r in ROLES if key in self.role_users[r]}
        roles |= {r for r in ROLES if groups & self.role_groups[r]}
        name = headers.get("x-forwarded-preferred-username", "").strip()[:128]
        return AuthPrincipal(user, "user", AUTH_METHOD, frozenset(roles), name), token

    def background(self) -> AuthPrincipal:
        return AuthPrincipal(self.sp_id, "service_principal", SP_AUTH_METHOD, self.sp_roles)

    def known_users(self) -> list[AuthPrincipal]:
        return []
