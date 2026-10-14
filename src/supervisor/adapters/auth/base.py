"""Principal port adapters: who is acting, with which roles and which auth method.

Two adapters (``dev_header`` for the laptop, ``databricks_app`` for the App) return an
``AuthPrincipal`` per request. The Databricks user token (``X-Forwarded-Access-Token``)
lives in a ``UserToken`` that is kept on ``request.state`` for that request only; it is
never logged, never stored and never part of a principal's repr.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from supervisor.core.errors import SupervisorError

ROLES: tuple[str, ...] = ("reviewer", "approver", "owner", "auditor", "admin")
Kind = Literal["user", "service_principal", "system"]


class AuthError(SupervisorError):
    """The caller cannot be identified or lacks a role (shown as HTTP 400)."""


@dataclass(frozen=True)
class AuthPrincipal:
    """Implements ``core.ports.Principal`` and adds roles for the console."""

    user_id: str
    kind: Kind
    auth_method: str
    roles: frozenset[str] = field(default_factory=frozenset)
    display_name: str = ""

    def has(self, *roles: str) -> bool:
        return any(r in self.roles for r in roles)

    @property
    def is_human(self) -> bool:
        return self.kind == "user"

    @property
    def label(self) -> str:
        return self.display_name or self.user_id


class UserToken:
    """A per-request user token. ``repr``/``str`` never show it; use ``reveal()`` once,
    inside the request, to open a fresh client."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "UserToken(***)"

    __str__ = __repr__

    def __reduce__(self) -> tuple[object, ...]:  # never pickled into a cache or a queue
        raise TypeError("UserToken cannot be pickled")


class PrincipalProvider(Protocol):
    name: str

    def resolve(
        self, headers: Mapping[str, str], cookies: Mapping[str, str]
    ) -> tuple[AuthPrincipal, UserToken | None]:
        """The principal for one request (and the user token, if any)."""
        ...

    def background(self) -> AuthPrincipal:
        """Identity for background tasks (no request, so no user token)."""
        ...

    def known_users(self) -> list[AuthPrincipal]:
        """Users a dev switcher may offer (empty for SSO)."""
        ...


def clean_roles(values: Iterable[object]) -> frozenset[str]:
    out = set()
    for v in values or ():
        role = str(v).strip().lower()
        if role not in ROLES:
            raise AuthError(f"unknown role {role!r}; roles are {', '.join(ROLES)}")
        out.add(role)
    return frozenset(out)
