"""WP26: the review CLI (`python -m supervisor.gateway.mcp_http tools ...`). ASCII output."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.config import load_settings
from supervisor.gateway import mcp_http
from supervisor.gateway.mcp_lock_service import ToolLockService
from supervisor.wiring import build_runtime
from tests.fixtures.mcp_http.fake_server import tool

SERVER = "bank-mcp.example_mcp"
T = tool("get_balance", "Returns the đồng balance.", {"a": {"type": "string"}})


@pytest.fixture
def seeded_db(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("MCP_HTTP_ENABLED", "1")
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    settings = load_settings()
    rt = build_runtime(settings)
    try:
        svc = ToolLockService(rt.adapters.state, rt.chain, rt.adapters.clock)
        svc.observe(SERVER, "payments", [T])
        return str(svc.list_tools(SERVER)[0]["observed_hash"])
    finally:
        rt.close()


def test_list_diff_propose_approve(seeded_db: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert mcp_http.main(["tools", "list"]) == 0
    out = capsys.readouterr().out
    assert "get_balance" in out and "HIDDEN" in out and "approvals 0/2" in out
    assert out.isascii()
    assert mcp_http.main(["tools", "diff", SERVER, "get_balance"]) == 0
    out = capsys.readouterr().out
    assert "never approved" in out and out.isascii() and "\\u0111" in out  # escaped, not raw
    h = seeded_db[:16]
    args = ["tools", "propose", SERVER, "get_balance", "--by", "op.khanh", "--hash", h]
    assert mcp_http.main(args) == 0
    assert "waiting for a second" in capsys.readouterr().out
    assert mcp_http.main(args) == 1  # same person again
    assert "second, different person" in capsys.readouterr().out
    ok = ["tools", "approve", SERVER, "get_balance", "--by", "rev.an", "--hash", h]
    assert mcp_http.main(ok) == 0
    assert "LOCKED" in capsys.readouterr().out
    assert mcp_http.main(["tools", "list", SERVER]) == 0
    assert "APPROVED" in capsys.readouterr().out


def test_cli_is_off_with_the_flag_off(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.delenv("MCP_HTTP_ENABLED", raising=False)
    assert mcp_http.main(["tools", "list"]) == 2
    assert "MCP_HTTP_ENABLED=1" in capsys.readouterr().out


def test_cli_needs_a_hash_and_a_name(capsys: Any) -> None:
    with pytest.raises(SystemExit):
        mcp_http.main(["tools", "approve", SERVER, "t", "--by", "x"])


def test_cli_over_http_uses_the_routes(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    seen: list[tuple[str, str, Any]] = []

    def fake_get(url: str, timeout: float, headers: Any = None) -> dict[str, Any]:
        seen.append(("GET", url, headers))
        return {"tools": []}

    def fake_post(url: str, payload: Any, timeout: float, headers: Any = None) -> dict[str, Any]:
        seen.append(("POST", url, (payload, headers)))
        return {"locked": False}

    import supervisor.adapters.http_json as hj

    monkeypatch.setattr(hj, "get_json", fake_get)
    monkeypatch.setattr(hj, "post_json", fake_post)
    base = ["tools", "--supervisor-url", "http://127.0.0.1:1"]
    assert mcp_http.main([*base, "list", SERVER]) == 0
    assert mcp_http.main([*base, "approve", SERVER, "t", "--by", "rev.an", "--hash", "a" * 12]) == 0
    assert seen[0][1].endswith(f"/v1/mcp/tools?server_id={SERVER}")
    assert seen[1][2][1] == {"X-Dev-User": "rev.an"}
    assert seen[1][2][0]["observed_hash"] == "a" * 12
