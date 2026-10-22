"""Connected apps of the MCP server (WP-G6): the ``mcp_app`` table.

An app is a pipeline or an AI assistant. It is issued a key (HMAC, WP20 key store, id = app id)
by an operator with ``python -m supervisor.mcp_server app issue``; the row is ``pending`` until
an admin approves it (``POST /v1/mcp/apps/{id}/approve`` or ``app approve``). A blocked app is
refused at once. The row holds the scopes the app may call and the console roles it acts with
(never ``admin``), so its view of the AI systems is scoped like a person's. The secret is never
stored here, only the SHA-256 of the current one (``key_hash``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any

from supervisor.core import rbac
from supervisor.core.errors import DuplicateKeyError, NotFoundError, SupervisorError
from supervisor.mcp_server import SCOPES

STATUSES: tuple[str, ...] = ("pending", "approved", "blocked")
DEFAULT_ROLES: tuple[str, ...] = ("viewer",)
APP_PREFIX = "mcp-"
APP_ID_RE = re.compile(r"^mcp-[a-z0-9][a-z0-9-]{1,58}\Z")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{1,58}[A-Za-z0-9]\Z")
USER_RE = re.compile(r"^[A-Za-z0-9_.:@+-]{1,128}\Z")
MAX_APPS = 500


class McpAppError(SupervisorError):
    """A bad request about a connected app (HTTP 400 with the message)."""


def key_hash_of(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def app_id_for(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise McpAppError(
            "name must be 3 to 60 characters: letters, digits, space, _ . - (start and end "
            "with a letter or digit)"
        )
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (APP_PREFIX + slug)[:60].rstrip("-")


def check_scopes(scopes: Iterable[Any]) -> list[str]:
    out = sorted({str(s) for s in scopes})
    if not out:
        raise McpAppError(f"give at least one scope: {', '.join(SCOPES)}")
    bad = [s for s in out if s not in SCOPES]
    if bad:
        raise McpAppError(f"unknown scope {', '.join(bad)}; scopes are {', '.join(SCOPES)}")
    return out


def check_roles(roles: Iterable[Any]) -> list[str]:
    out = sorted({str(r).strip().lower() for r in roles})
    if not out:
        out = list(DEFAULT_ROLES)
    bad = [r for r in out if r not in rbac.ROLES]
    if bad:
        raise McpAppError(f"unknown role {', '.join(bad)}; roles are {', '.join(rbac.ROLES)}")
    if "admin" in out:
        raise McpAppError("an app never holds the admin role")
    return out


def check_user(value: str, what: str) -> str:
    if not isinstance(value, str) or not USER_RE.match(value):
        raise McpAppError(f"{what} must be 1 to 128 characters from A-Z a-z 0-9 _ . : @ + -")
    return value


class McpAppService:
    def __init__(self, state: Any, clock: Any) -> None:
        self.state = state
        self.clock = clock

    def view(self, row: Any) -> dict[str, Any]:
        """The row without the key hash."""
        return {
            "app_id": row["app_id"],
            "name": row["name"],
            "scopes": _list(row["scopes"]),
            "roles": _list(row["roles"]),
            "status": row["status"],
            "created_by": row["created_by"],
            "approved_by": row.get("approved_by"),
            "created_at": _iso(row["created_at"]),
            "approved_at": _iso(row.get("approved_at")),
            "first_connected_at": _iso(row.get("first_connected_at")),
        }

    def get_row(self, app_id: str) -> dict[str, Any] | None:
        if not isinstance(app_id, str) or not APP_ID_RE.match(app_id):
            return None
        row = self.state.get("mcp_app", {"app_id": app_id})
        return dict(row) if row is not None else None

    def get(self, app_id: str) -> dict[str, Any]:
        row = self.get_row(app_id)
        if row is None:
            raise NotFoundError(f"connected app {app_id} does not exist")
        return self.view(row)

    def list_apps(self) -> list[dict[str, Any]]:
        return [self.view(r) for r in self.state.query("mcp_app", order_by=("app_id",))]

    def create(
        self,
        name: str,
        scopes: Iterable[Any],
        roles: Iterable[Any],
        created_by: str,
        secret: str,
    ) -> dict[str, Any]:
        """A new app in status ``pending``. ``secret`` is the HMAC key just issued."""
        app_id = app_id_for(name)
        scope_list = check_scopes(scopes)
        role_list = check_roles(roles)
        check_user(created_by, "created_by")
        if len(self.state.query("mcp_app", limit=MAX_APPS + 1)) > MAX_APPS:
            raise McpAppError(f"at most {MAX_APPS} connected apps")
        row = {
            "app_id": app_id,
            "name": name,
            "scopes": scope_list,
            "roles": role_list,
            "created_by": created_by,
            "approved_by": None,
            "status": "pending",
            "key_hash": key_hash_of(secret),
            "created_at": self.clock.now(),
            "approved_at": None,
            "first_connected_at": None,
        }
        try:
            stored = self.state.insert("mcp_app", row)
        except DuplicateKeyError:
            raise McpAppError(f"a connected app named {name!r} already exists") from None
        return self.view(stored)

    def _change(self, app_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        row = self.get_row(app_id)
        if row is None:
            raise NotFoundError(f"connected app {app_id} does not exist")
        stored = self.state.update("mcp_app", {"app_id": app_id}, changes, row["row_version"])
        return self.view(stored)

    def approve(self, app_id: str, by: str) -> dict[str, Any]:
        """pending or blocked -> approved. The approver is a person (checked by the caller)."""
        check_user(by, "approved_by")
        cur = self.get_row(app_id)
        if cur is None:
            raise NotFoundError(f"connected app {app_id} does not exist")
        if cur["status"] == "approved":
            raise McpAppError(f"{app_id} is already approved")
        return self._change(
            app_id, {"status": "approved", "approved_by": by, "approved_at": self.clock.now()}
        )

    def block(self, app_id: str, by: str) -> dict[str, Any]:
        check_user(by, "blocked_by")  # the who is in the console_action row of the change
        cur = self.get_row(app_id)
        if cur is None:
            raise NotFoundError(f"connected app {app_id} does not exist")
        if cur["status"] == "blocked":
            raise McpAppError(f"{app_id} is already blocked")
        return self._change(app_id, {"status": "blocked"})

    def set_key(self, app_id: str, secret: str) -> dict[str, Any]:
        return self._change(app_id, {"key_hash": key_hash_of(secret)})

    def mark_connected(self, row: dict[str, Any]) -> None:
        """First successful signature of the app: remember when (once)."""
        if row.get("first_connected_at") is None:
            self._change(str(row["app_id"]), {"first_connected_at": self.clock.now()})


def _list(value: Any) -> list[str]:
    import json

    if isinstance(value, list):
        return [str(v) for v in value]
    try:
        out = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(v) for v in out] if isinstance(out, list) else []


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
