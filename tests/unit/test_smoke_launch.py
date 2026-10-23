"""WP-P1: helpers of tools/smoke_launch.py, plus one real launch of the app."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tools import smoke_launch as sl


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        code = 404 if self.path == "/missing" else 200
        body = json.dumps({"path": self.path, "system_id": "sys_x"}).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n)
        body = json.dumps({"echo": data.decode(), "hx": self.headers.get("HX-Request")}).encode()
        self.send_response(201)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a: object) -> None:
        return


@pytest.fixture
def server() -> str:
    srv = HTTPServer((sl.HOST, 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://{sl.HOST}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def test_free_port_is_usable_twice_in_a_row() -> None:
    a, b = sl.free_port(), sl.free_port()
    assert 1024 <= a < 65536 and 1024 <= b < 65536


def test_build_env_sets_the_launch_flags_and_drops_databricks(tmp_path: Path) -> None:
    base = {
        "PATH": "/bin",
        "DATABRICKS_HOST": "https://x",
        "DATABRICKS_TOKEN": "t",
        "LLM_BASE_URL": "http://elsewhere",
        "SIGNER_KEY_PATH": "/k",
        "KEEP": "1",
    }
    env = sl.build_env(tmp_path, 4321, base)
    assert env["DATA_DIR"] == str(tmp_path)
    assert env["SUPERVISOR_PORT"] == "4321" and env["SUPERVISOR_MODE"] == "laptop"
    assert env["GOVERNANCE_ENABLED"] == "1" and env["CONSOLE_PLAYGROUND_ENABLED"] == "1"
    assert env["SCHEDULER_ENABLED"] == "0" and env["LLM_BASE_URL"] == ""
    assert env["KEEP"] == "1" and env["PATH"] == "/bin"
    assert not [k for k in env if k.startswith("DATABRICKS_")]
    assert "SIGNER_KEY_PATH" not in env
    assert Path(env["LOG_FILE"]).parent == tmp_path


def test_wait_for_succeeds_after_a_few_polls() -> None:
    calls = {"n": 0}
    now = {"t": 0.0}

    def probe() -> bool:
        calls["n"] += 1
        return calls["n"] >= 3

    def sleep(s: float) -> None:
        now["t"] += s

    assert sl.wait_for(probe, 10, clock=lambda: now["t"], sleep=sleep)
    assert calls["n"] == 3


def test_wait_for_times_out_and_stops_when_the_process_died() -> None:
    now = {"t": 0.0}

    def sleep(s: float) -> None:
        now["t"] += s

    assert not sl.wait_for(lambda: False, 1.0, clock=lambda: now["t"], sleep=sleep)
    assert now["t"] >= 1.0
    now["t"] = 0.0
    assert not sl.wait_for(
        lambda: False, 100, alive=lambda: False, clock=lambda: now["t"], sleep=sleep
    )
    assert now["t"] == 0.0


def test_http_returns_status_and_text_without_raising(server: str) -> None:
    ok = sl.http("GET", f"{server}/x")
    assert ok.status == 200 and sl.json_field(ok.text, "system_id") == "sys_x"
    assert sl.http("GET", f"{server}/missing").status == 404
    post = sl.http(
        "POST", f"{server}/p", headers={"HX-Request": "true"}, body=sl.form_body({"a": "b c"})
    )
    assert post.status == 201
    assert json.loads(post.text) == {"echo": "a=b+c", "hx": "true"}
    refused = sl.http("GET", f"http://{sl.HOST}:{sl.free_port()}/", timeout_s=2)
    assert refused.status == 0 and refused.text


def test_json_field_and_tail(tmp_path: Path) -> None:
    assert sl.json_field("not json", "a") is None
    assert sl.json_field("[1]", "a") is None
    assert sl.json_field('{"a": 3}', "a") == "3"
    log = tmp_path / "app.log"
    assert sl.tail(log) == []
    log.write_text("\n".join(str(i) for i in range(100)), encoding="utf-8")
    assert sl.tail(log, 3) == ["97", "98", "99"]


def test_verify_markers() -> None:
    assert sl.VERIFY_OK.search('<div class="ok-big" data-verify="ok">x</div>')
    assert sl.VERIFY_FAIL.search('<div data-verify="fail">')
    assert not sl.VERIFY_OK.search('<div data-verify="fail">')


def test_run_steps_counts_failures_and_stops_when_the_app_is_down() -> None:
    res = sl.Result()

    def good(_b: str, r: sl.Result) -> bool:
        r.ok("good")
        return True

    def bad(_b: str, r: sl.Result) -> bool:
        r.fail("bad")
        return False

    sl.run_steps("http://x", res, (good, bad, good))
    assert res.failed == 1 and res.lines == ["[OK] good", "[FAIL] bad", "[OK] good"]
    down = sl.Result()
    sl.run_steps("http://x", down, (bad, good))
    assert down.failed == 1 and len(down.lines) == 2 and "skipped" in down.lines[-1]


def test_steps_fail_cleanly_when_nothing_listens() -> None:
    res = sl.Result()
    base = f"http://{sl.HOST}:{sl.free_port()}"
    sl.run_steps(base, res)
    assert res.failed == 1
    assert res.lines[0].startswith("[FAIL] healthz")


def test_ascii_safe() -> None:
    assert sl.ascii_safe("Việt") == "Vi\\u1ec7t"


def test_smoke_launch_runs_the_real_app(capsys: pytest.CaptureFixture[str]) -> None:
    rc = sl.main(["--timeout", "120"])
    out = capsys.readouterr().out
    assert rc == 0, out
    out.encode("ascii")
    assert out.rstrip().endswith("[OK] smoke test passed")
    for needle in ("healthz", "console page", "AI system registered", "playground", "chain"):
        assert needle in out
