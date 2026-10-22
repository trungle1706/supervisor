"""WP-G6 fixtures: the real app with the MCP routers mounted (as app.py does with the flag on),
a key file for the apps, and a small rig that signs requests like a connected app."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.agent_creds import FileKeyStore, rotate_keys
from supervisor.gateway.ingress_auth import IngressVerifier
from supervisor.gateway.ingress_sign import IngressCredential, new_secret
from supervisor.mcp_server import auth
from supervisor.mcp_server.apps import McpAppService
from tests.console.conftest import Console, adapters, console, seeded  # noqa: F401  (fixtures)

PATH = "/mcp"
ALL_SCOPES = ("governance.read", "governance.write", "library.read", "supervisor.read")


@dataclass
class Cred:
    app_id: str
    secret: str

    def sign(self, body: bytes, path: str = PATH) -> dict[str, str]:
        return IngressCredential(self.app_id, self.secret).headers_for("POST", path, body)


class Rig:
    def __init__(self, con: Console, keys: FileKeyStore) -> None:
        self.console = con
        self.ctx = con.ctx
        self.keys = keys
        self.apps = McpAppService(con.ctx.state, con.ctx.clock)
        self.n = 0

    def new_app(
        self,
        name: str = "pipeline",
        scopes: tuple[str, ...] = ALL_SCOPES,
        roles: tuple[str, ...] = ("reviewer",),
        approved: bool = True,
    ) -> Cred:
        secret = new_secret()
        row = self.apps.create(name, scopes, roles, "ops.lan", secret)
        data = self.keys.read_all()
        from datetime import UTC, datetime, timedelta

        data[row["app_id"]] = rotate_keys([], secret, datetime.now(UTC), timedelta(hours=1))
        self.keys.write_all(data)
        if approved:
            self.apps.approve(row["app_id"], "admin.chi")
        return Cred(row["app_id"], secret)

    def post(self, cred: Cred | None, body: Any, *, raw: bytes | None = None, **kw: Any) -> Any:
        data = raw if raw is not None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if cred is not None:
            headers.update(cred.sign(data))
        headers.update(kw.pop("headers", {}))
        return self.console.client.post(PATH, content=data, headers=headers, **kw)

    def rpc(self, cred: Cred | None, method: str, params: Any = None, id_: Any = 1) -> Any:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": id_, "method": method}
        if params is not None:
            msg["params"] = params
        return self.post(cred, msg)

    def call(self, cred: Cred, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """The JSON-RPC answer (a dict with result or error) of one tools/call."""
        r = self.rpc(cred, "tools/call", {"name": name, "arguments": args or {}})
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()  # type: ignore[no-any-return]

    def ok(self, cred: Cred, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        out = self.call(cred, name, args)
        assert "result" in out, out
        return out["result"]["structuredContent"]  # type: ignore[no-any-return]

    def err(self, cred: Cred, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        out = self.call(cred, name, args)
        assert "error" in out, out
        return out["error"]  # type: ignore[no-any-return]

    def actions(self, **where: Any) -> list[dict[str, Any]]:
        return self.ctx.tables.query("console_action", where or None, order_by=("ts",))


@pytest.fixture(autouse=True)
def fresh_state() -> Iterator[None]:
    """The KPI cache and the chain_verify limit are process state: start each test clean."""
    from supervisor.governance import kpis
    from supervisor.mcp_server import tools_supervisor

    kpis.clear_cache()
    tools_supervisor._LAST_VERIFY.clear()  # noqa: SLF001
    yield
    kpis.clear_cache()
    tools_supervisor._LAST_VERIFY.clear()  # noqa: SLF001


@pytest.fixture
def mounted_mcp() -> Iterator[None]:
    """Mount the MCP routers on the global app and take them off again."""
    from supervisor.app import app
    from supervisor.governance.routes import router as systems_router
    from supervisor.mcp_server.routes import admin_router, mcp_router
    from tests.governance.conftest import restore_app

    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(systems_router)
    app.include_router(mcp_router)
    app.include_router(admin_router)
    try:
        yield
    finally:
        restore_app(app, saved, lifespan)  # routes, lifespan chain and the cached schema


@pytest.fixture
def rig(
    console: Console,  # noqa: F811
    mounted_mcp: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[Rig]:
    s = console.ctx.settings
    for flag in (
        "governance_enabled",
        "mcp_server_enabled",
        "controls_enabled",
        "risk_register_enabled",
        "transparency_enabled",
    ):
        monkeypatch.setattr(s, flag, True)
    keys = FileKeyStore(tmp_path / "agent_keys.yaml")
    r = Rig(console, keys)
    from supervisor.mcp_server.apps import McpAppService as Svc
    from supervisor.mcp_server.auth import AppKeyStore

    auth.set_verifier(
        IngressVerifier(
            kind="hmac", keys=AppKeyStore(keys, Svc(console.ctx.state, console.ctx.clock))
        )
    )
    try:
        yield r
    finally:
        auth.set_verifier(None)
