"""Laptop identity: ``X-Dev-User`` header (or the console's dev cookie) + a local users file.

NOT a real identity (ADR D04): every principal it returns has ``auth_method=dev_header``,
and the console shows a "dev identity" banner. Refused with SUPERVISOR_MODE=databricks_app
(see Settings).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from supervisor.adapters.auth.base import AuthError, AuthPrincipal, UserToken, clean_roles

HEADER = "x-dev-user"
COOKIE = "sv_dev_user"
AUTH_METHOD = "dev_header"
_ID = re.compile(r"^[A-Za-z0-9_.@+-]{1,128}$")


_GROUP = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _groups(raw: Any, path: Path, uid: str) -> frozenset[str]:
    """The optional ``groups:`` list of a user (factory groups, WP-F3)."""
    if raw in (None, ""):
        return frozenset()
    if not isinstance(raw, (list, tuple)) or not all(
        isinstance(g, str) and _GROUP.match(g) for g in raw
    ):
        raise AuthError(f"users file {path}: groups of {uid!r} must be a list of group ids")
    return frozenset(raw)


class DevHeaderPrincipal:
    name = "dev_header"

    def __init__(self, users: Mapping[str, AuthPrincipal], default_user: str | None) -> None:
        self.users = dict(users)
        if default_user is not None and default_user not in self.users:
            raise AuthError(f"users file: default_user {default_user!r} is not in users")
        self.default_user = default_user

    @classmethod
    def from_file(cls, path: Path) -> DevHeaderPrincipal:
        try:
            doc: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError as exc:
            raise AuthError(f"cannot read users file {path}: {exc.strerror}") from None
        except yaml.YAMLError as exc:
            raise AuthError(f"users file {path} is not valid YAML: {exc}") from None
        raw = doc.get("users") or {}
        if not isinstance(raw, Mapping) or not raw:
            raise AuthError(f"users file {path}: 'users' must be a non-empty mapping")
        users = {}
        for uid, spec in raw.items():
            uid = str(uid)
            if not _ID.match(uid):
                raise AuthError(f"users file {path}: bad user id {uid!r}")
            spec = spec or {}
            users[uid] = AuthPrincipal(
                user_id=uid,
                kind="user",
                auth_method=AUTH_METHOD,
                roles=clean_roles(spec.get("roles") or ()),
                display_name=str(spec.get("name") or ""),
                groups=_groups(spec.get("groups"), path, uid),
            )
        return cls(users, doc.get("default_user"))

    def resolve(
        self, headers: Mapping[str, str], cookies: Mapping[str, str]
    ) -> tuple[AuthPrincipal, UserToken | None]:
        uid = (headers.get(HEADER) or cookies.get(COOKIE) or self.default_user or "").strip()
        if not uid:
            raise AuthError("no user: send the X-Dev-User header or set default_user")
        user = self.users.get(uid)
        if user is None:
            raise AuthError(f"unknown dev user {uid[:128]!r}; add it to the users file")
        return user, None

    def background(self) -> AuthPrincipal:
        return AuthPrincipal("supervisor-system", "system", "local_system")

    def known_users(self) -> list[AuthPrincipal]:
        return sorted(self.users.values(), key=lambda p: p.user_id)
