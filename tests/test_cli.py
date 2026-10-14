from __future__ import annotations

from pathlib import Path

import pytest

from supervisor import sandbox
from tests.conftest import REPO_ROOT


def _cli(*args: str, env: dict[str, str] | None = None, cwd: Path = REPO_ROOT):
    return sandbox.run(
        [sandbox.python_executable(), "-m", "supervisor.cli", *args],
        cwd=cwd,
        timeout_s=120,
        env=env,
    )


def test_preflight_exits_zero_with_ascii_ok_skip_lines(tmp_path: Path) -> None:
    res = _cli("preflight", env={"SUPERVISOR_MODE": "dev"}, cwd=tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.isascii()
    lines = [x for x in res.stdout.splitlines() if x.startswith("[")]
    assert lines, res.stdout
    assert all(x.startswith(("[OK]", "[SKIP]")) for x in lines), res.stdout
    for name in ("python", "no DATABRICKS_TOKEN", "config", "paths absolute", "llm endpoint"):
        assert any(name in x for x in lines), name


def test_preflight_fails_on_databricks_token(tmp_path: Path) -> None:
    secret = "notarealtoken123456"
    res = _cli("preflight", env={"DATABRICKS_TOKEN": secret}, cwd=tmp_path)
    assert res.returncode == 1
    assert "[FAIL] no DATABRICKS_TOKEN" in res.stdout
    assert secret not in res.stdout + res.stderr
    assert res.stdout.isascii()


def test_preflight_fails_on_remote_llm(tmp_path: Path) -> None:
    res = _cli("preflight", env={"LLM_BASE_URL": "https://example.com/v1"}, cwd=tmp_path)
    assert res.returncode == 1
    assert "[FAIL] config" in res.stdout and "loopback" in res.stdout


@pytest.mark.parametrize(
    "args,code",
    [(("demo", "--data-dir", "demo"), 0), (("release", "--help"), 0), (("verify",), 2)],
)
def test_stub_commands(args: tuple[str, ...], code: int, tmp_path: Path) -> None:
    # WP11: demo runs the full runbook (relative --data-dir resolves against the cwd);
    # release is exercised on a temp clone in tests/e2e/test_release.py.
    res = _cli(*args, cwd=tmp_path)
    assert res.returncode == code, res.stdout + res.stderr
    assert res.stdout.isascii() and res.stdout.strip()
    if args[0] == "demo":
        assert "[OK] demo run 1: PASS" in res.stdout, res.stdout
        assert (tmp_path / "demo" / ".supervisor-demo").is_file()


def test_serve_answers_healthz(tmp_path: Path) -> None:
    """Start the real server with `python -m supervisor.cli serve` and call /healthz."""
    import socket
    import time
    import urllib.request

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = sandbox.start(
        [sandbox.python_executable(), "-m", "supervisor.cli", "serve", "--port", str(port)],
        cwd=tmp_path,
    )
    body = b""
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                    body = r.read()
                    break
            except OSError:
                if not proc.running():
                    break
                time.sleep(0.2)
    finally:
        proc.stop()
    assert body == b'{"status":"ok"}'
