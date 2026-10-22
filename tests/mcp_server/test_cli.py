"""WP-G6 command line: issue, rotate, list, approve, block, tools. ASCII output, no secret in a
listing, the key in the WP20 key file with mode 600."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.agent_creds import FileKeyStore
from supervisor.config import load_settings
from supervisor.mcp_server.cli import main


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, Path]]:
    keys = tmp_path / "keys.yaml"
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("MCP_SERVER_ENABLED", "1")
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INGRESS_KEYS_FILE", str(keys))
    monkeypatch.setenv("INGRESS_KEY_STORE", "file")
    monkeypatch.setenv("LLM_BASE_URL", "")
    yield {"keys": keys, "dir": tmp_path}


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    rc = main(list(argv))
    out = capsys.readouterr().out
    assert out.isascii(), "CLI output must be ASCII"
    return rc, out


def table_rows(env: dict[str, Path], table: str) -> list[dict[str, Any]]:
    from supervisor.adapters.factory import build_adapters

    a = build_adapters(load_settings())
    try:
        return (
            [dict(r) for r in a.tables.query(table)]
            if table == "console_action"
            else [dict(r) for r in a.state.query(table)]
        )
    finally:
        a.close()


def test_issue_approve_list_block(env: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    secret_file = env["dir"] / "app.secret"
    rc, out = run(
        capsys,
        "app",
        "issue",
        "Nightly job",
        "--scopes",
        "governance.read,library.read",
        "--roles",
        "reviewer",
        "--by",
        "ops.lan",
        "--out-key-file",
        str(secret_file),
    )
    assert rc == 0, out
    assert "mcp-nightly-job is pending" in out and "secret (shown once)" not in out
    secret = secret_file.read_text().strip()
    assert len(secret) == 64 and secret not in out
    if os.name == "posix":
        assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(env["keys"].stat().st_mode) == 0o600
    keys = FileKeyStore(env["keys"]).keys_for("mcp-nightly-job")
    assert [k.secret for k in keys] == [secret]
    rows = table_rows(env, "mcp_app")
    assert rows[0]["status"] == "pending" and rows[0]["created_by"] == "ops.lan"
    assert rows[0]["key_hash"] != secret and len(rows[0]["key_hash"]) == 64

    rc, out = run(capsys, "app", "list")
    assert rc == 0 and "mcp-nightly-job" in out and "pending" in out and secret not in out
    rc, out = run(capsys, "app", "approve", "mcp-nightly-job", "--by", "admin.chi")
    assert rc == 0 and "approved" in out
    rc, out = run(capsys, "app", "approve", "mcp-nightly-job", "--by", "admin.chi")
    assert rc == 1 and "already approved" in out
    rc, out = run(capsys, "app", "block", "mcp-nightly-job", "--by", "admin.chi")
    assert rc == 0
    rows = table_rows(env, "mcp_app")
    assert rows[0]["status"] == "blocked" and rows[0]["approved_by"] == "admin.chi"
    audit = [r for r in table_rows(env, "console_action") if r["permission"] == "mcp.apps"]
    assert [r["detail"] for r in audit] == ["issue", "approve", "block"]
    assert {r["actor"] for r in audit} == {"ops.lan", "admin.chi"} and audit[0]["method"] == "CLI"


def test_issue_prints_the_secret_once_without_an_out_file(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out = run(capsys, "app", "issue", "Assistant X", "--scopes", "library.read", "--by", "ops")
    assert rc == 0 and "secret (shown once): " in out
    secret = out.split("secret (shown once): ")[1].split()[0]
    assert FileKeyStore(env["keys"]).keys_for("mcp-assistant-x")[0].secret == secret
    rc, out = run(capsys, "app", "list")
    assert secret not in out


def test_rotate_keeps_the_old_key_for_the_overlap_and_changes_the_hash(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    run(capsys, "app", "issue", "Job", "--scopes", "library.read", "--by", "ops")
    first = table_rows(env, "mcp_app")[0]["key_hash"]
    rc, out = run(capsys, "app", "rotate", "mcp-job", "--by", "ops")
    assert rc == 0
    keys = FileKeyStore(env["keys"]).keys_for("mcp-job")
    assert [k.state for k in keys] == ["current", "previous"]
    assert table_rows(env, "mcp_app")[0]["key_hash"] != first
    rc, out = run(capsys, "app", "rotate", "mcp-ghost", "--by", "ops")
    assert rc == 1 and "does not exist" in out


@pytest.mark.parametrize(
    ("argv", "text"),
    [
        (("app", "issue", "x", "--scopes", "library.read", "--by", "ops"), "name must be"),
        (("app", "issue", "Good name", "--scopes", "root.all", "--by", "ops"), "unknown scope"),
        (("app", "issue", "Good name", "--scopes", "", "--by", "ops"), "at least one scope"),
        (
            (
                "app",
                "issue",
                "Good name",
                "--scopes",
                "library.read",
                "--roles",
                "admin",
                "--by",
                "o",
            ),
            "never holds the admin role",
        ),
        (
            ("app", "issue", "Good name", "--scopes", "library.read", "--by", "bad user"),
            "created_by",
        ),
        (("app", "approve", "mcp-ghost", "--by", "ops"), "does not exist"),
        (("app", "block", "not-an-app", "--by", "ops"), "does not exist"),
    ],
)
def test_bad_input_is_a_fail_line_and_nothing_is_stored(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], text: str
) -> None:
    rc, out = run(capsys, *argv)
    assert rc == 1 and out.startswith("[FAIL]") and text in out, out
    assert table_rows(env, "mcp_app") == []
    assert not env["keys"].exists()


def test_a_second_issue_for_the_same_name_is_refused(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(capsys, "app", "issue", "Twin", "--scopes", "library.read", "--by", "o")[0] == 0
    rc, out = run(capsys, "app", "issue", "Twin", "--scopes", "library.read", "--by", "o")
    assert rc == 1 and "already exists" in out
    assert len(FileKeyStore(env["keys"]).keys_for("mcp-twin")) == 1


def test_tools_lists_the_registry(env: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = run(capsys, "tools")
    assert rc == 0
    lines = out.strip().splitlines()
    assert any(
        line.split()[:3] == ["register_system", "governance.write", "write"] for line in lines
    )
    assert not [line for line in lines if "approve" in line or "accept_risk" in line]
    assert json.dumps(lines)


def test_serve_builds_a_small_app_with_only_the_mcp_route(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    from supervisor.mcp_server.cli import make_app

    paths = make_app().openapi()["paths"]
    assert "post" in paths["/mcp"]
    assert not [p for p in paths if p.startswith(("/v1", "/console"))]
    seen: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    rc, out = run(capsys, "serve", "--port", "9123")
    assert rc == 0 and "http://127.0.0.1:9123/mcp" in out and "[WARN]" not in out
    assert seen["host"] == "127.0.0.1" and seen["port"] == 9123 and seen["workers"] == 1
    rc, out = run(capsys, "serve", "--host", "0.0.0.0")  # noqa: S104
    assert rc == 0 and "[WARN]" in out and "TLS" in out
