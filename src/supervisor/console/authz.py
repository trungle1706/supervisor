"""Who may do what in the console: the checks that several route modules need (audit D5).

``person`` is the "must be a signed-in person" gate for write actions; ``may`` is the role check
used to show or hide buttons; ``may_system`` adds the "system is not archived" rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.cases.service import PermissionDenied
from supervisor.core import rbac

NEEDS_PERSON = "this action needs a signed-in person"


def person(me: Any, message: str = NEEDS_PERSON, *, assume_user: bool = False) -> str:
    """The user id of ``me``; ``PermissionDenied`` (HTTP 400) with ``message`` for any other
    principal. ``assume_user`` reads a principal without a ``kind`` as a person."""
    if getattr(me, "kind", "user" if assume_user else "") != "user":
        raise PermissionDenied(message)
    return str(me.user_id)


def may(me: Any, permission: str) -> bool:
    """True when ``me`` may use ``permission``: a person by role, any other principal only for
    the read-only views in ``rbac.NON_USER_OK`` (the same rule as ``needs()``)."""
    if getattr(me, "kind", "user") == "user":
        return rbac.allowed(me.roles, permission)
    return permission in rbac.NON_USER_OK


def may_system(me: Any, system: Mapping[str, Any], permission: str) -> bool:
    """A person with ``permission`` and a system that is not archived."""
    user = getattr(me, "kind", "") == "user"
    return bool(user and rbac.allowed(me.roles, permission) and system.get("status") != "archived")
