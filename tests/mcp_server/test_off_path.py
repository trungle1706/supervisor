"""WP-G6 off path (tested first): with MCP_SERVER_ENABLED off nothing is mounted, no table is
read or written, the Governance overview is unchanged and the command line does nothing."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from supervisor.app import app
from supervisor.config import Settings, load_settings
from tests.console.conftest import Console

PATHS = [
    "/mcp",
    "/v1/mcp/apps",
    "/v1/mcp/apps/mcp-x/approve",
    "/v1/mcp/apps/mcp-x/block",
    "/v1/kpis",
]


def _paths() -> set[str]:
    from tests.console.test_rbac_matrix import app_routes

    return {p for _, p, _ in app_routes()}


def test_the_flag_is_off_by_default() -> None:
    assert Settings.model_fields["mcp_server_enabled"].default is False
    s = load_settings(sql_backend="sqlite", llm_base_url="")
    assert s.mcp_server_enabled is False
    assert (s.mcp_server_host, s.mcp_server_port) == ("127.0.0.1", 8765)


def test_no_route_is_mounted_with_the_flag_off() -> None:
    mounted = _paths()
    assert not [p for p in mounted if p == "/mcp" or p.startswith(("/v1/mcp/apps", "/v1/kpis"))]
    doc = app.openapi()["paths"]
    assert not [p for p in doc if p == "/mcp" or p.startswith(("/v1/mcp/apps", "/v1/kpis"))]
    assert "/v1/mcp/tools/observe" in mounted  # the WP26 routes are unharmed


@pytest.mark.parametrize("path", PATHS)
def test_the_urls_do_not_exist_with_the_flag_off(console: Console, path: str) -> None:
    for method in ("GET", "POST"):
        r = console.client.request(method, path, json={}, headers={"X-Dev-User": "admin.chi"})
        assert r.status_code in (404, 405), (method, path, r.status_code)


def test_the_table_stays_empty_and_the_overview_is_as_before(console: Console) -> None:
    from supervisor.console import systems_overview

    s = console.ctx.settings
    s.governance_enabled = True
    me = console.ctx.provider.users["reviewer.an"]
    d = systems_overview.governance_overview(console.ctx, me, "all", dt.datetime.now(dt.UTC))
    assert "kpis" not in d
    html = console.get("/console/?lang=en").text
    assert "/mcp" not in html and "kpis" not in html.lower()
    assert console.ctx.state.query("mcp_app") == []
    s.governance_enabled = False


def test_the_command_line_does_nothing_when_off(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from supervisor.mcp_server.cli import main

    monkeypatch.delenv("MCP_SERVER_ENABLED", raising=False)
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    for argv in (
        ["serve"],
        ["tools"],
        ["app", "list"],
        ["app", "issue", "x", "--scopes", "a", "--by", "u"],
    ):
        assert main(argv) == 0
        out = capsys.readouterr().out
        assert out.startswith("[SKIP]") and out.isascii()
    assert not (tmp_path / "data").exists()  # no store was opened


def test_registering_tools_needs_no_flag_and_mounts_nothing() -> None:
    from supervisor.mcp_server.server import build_registry

    assert len(build_registry()) > 10
    assert "/mcp" not in _paths()
