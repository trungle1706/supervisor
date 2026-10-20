"""Users and roles page (WP-UX3, read-only, admin only).

Reads the principal provider the app already built: the dev users file (``config/users.yaml``,
laptop) or the Databricks App role map (``config/auth.yaml``). It shows who holds which role and
the role x permission matrix from ``core/rbac.py``. It writes nothing; roles change in the
config file under Git. On the App only the configured role map is shown (users and group
names per role), never a token or a session."""

from __future__ import annotations

from typing import Any

from supervisor.console.credentials_view import short_principal
from supervisor.core import rbac


def matrix() -> list[dict[str, Any]]:
    """One row per permission: id, description, and the roles that hold it."""
    return [
        {
            "permission": perm,
            "text": text,
            "roles": {r: r in roles for r in rbac.ROLES},
        }
        for perm, (roles, text) in rbac.PERMISSIONS.items()
    ]


def page(ctx: Any) -> dict[str, Any]:
    provider = ctx.provider
    users: list[dict[str, Any]] = []
    role_map: list[dict[str, Any]] = []
    source = getattr(provider, "name", "unknown")
    if hasattr(provider, "users"):  # dev_header: config/users.yaml
        for p in sorted(provider.users.values(), key=lambda p: p.user_id):
            users.append(
                {
                    "user_id": p.user_id,
                    "name": getattr(p, "display_name", None) or "",
                    "roles": sorted(p.roles),
                    "source": "users.yaml",
                }
            )
    if hasattr(provider, "role_users"):  # databricks_app: config/auth.yaml
        for role in rbac.ROLES:
            members = sorted(provider.role_users.get(role, ()))
            groups = sorted(provider.role_groups.get(role, ()))
            role_map.append({"role": role, "users": members, "groups": groups})
            for u in members:
                users.append({"user_id": u, "name": "", "roles": [role], "source": "auth.yaml"})
    merged: dict[str, dict[str, Any]] = {}
    for u in users:  # one row per user id, roles added up (a person may hold several)
        row = merged.setdefault(u["user_id"], {**u, "roles": []})
        row["roles"] = sorted(set(row["roles"]) | set(u["roles"]))
    sp = None
    if hasattr(provider, "sp_id"):
        sp = {"id": short_principal(str(provider.sp_id)), "roles": sorted(provider.sp_roles)}
    holders = {r: sum(1 for u in merged.values() if r in u["roles"]) for r in rbac.ROLES}
    return {
        "source": source,
        "users": sorted(merged.values(), key=lambda u: u["user_id"]),
        "role_map": role_map,
        "group_lookup": getattr(provider, "group_lookup", None),
        "service_principal": sp,
        "roles": [{"role": r, "n": holders[r]} for r in rbac.ROLES],
        "matrix": matrix(),
        "role_names": rbac.ROLES,
    }
