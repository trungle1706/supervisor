"""Launch smoke test: does a fresh install start and do the main things? (WP-P1)

    python tools/smoke_launch.py [--keep] [--timeout 90] [--port N]

Runs on Linux and Windows with Python 3.11, no bash, no network, no model. It uses only the
standard library and the repository itself:

1. start the app (``python -m supervisor.cli serve``) on a free port with a temporary DATA_DIR;
2. wait for ``/healthz``;
3. open ``/console/``;
4. register an AI system through ``POST /v1/systems`` and read it back;
5. run a Playground dry-run check (a console POST, htmx header);
6. verify the evidence chain (``POST /console/chain/verify``);
7. stop the app and remove the temporary folder.

One ``[OK]`` / ``[FAIL]`` line per step, ASCII only. Exit code 0 only when every step passed.
On a failure the last lines of the app log are printed. The identity is the dev header
``X-Dev-User`` (laptop mode); nothing here touches a Databricks workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

HOST = "127.0.0.1"
DEV_USER = "reviewer.an"
SYSTEM_NAME = "Smoke test system"
SYSTEM_FIELDS = {
    "name": SYSTEM_NAME,
    "owner_user": "owner.credit",
    "owner_team": "Smoke test team",
    "purpose": "Synthetic system registered by tools/smoke_launch.py. Safe to delete.",
    "system_type": "assistant",
    "org_role": "deployer",
    "user_segment": "internal",
    "personal_data": "none",
    "human_control": "post_review",
    "business_impact": "low",
    "autonomy_level": "l1_assistive",
}
# Settings that must not leak in from the shell of the person who runs the smoke test.
CLEARED_ENV_PREFIXES = ("DATABRICKS_",)
CLEARED_ENV_NAMES = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_ENDPOINT", "SIGNER_KEY_PATH")
VERIFY_OK = re.compile(r'data-verify="ok"')
VERIFY_FAIL = re.compile(r'data-verify="fail"')


def ascii_safe(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


# ----------------------------------------------------------------------------- helpers


def free_port(host: str = HOST) -> int:
    """A TCP port nobody listens on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def build_env(data_dir: Path, port: int, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for the app under test: laptop mode, SQLite, one temp folder, the flags the
    smoke steps need, no judge model, no scheduler. Anything from a Databricks shell is dropped."""
    env = {
        k: v
        for k, v in (os.environ if base is None else base).items()
        if not k.startswith(CLEARED_ENV_PREFIXES) and k not in CLEARED_ENV_NAMES
    }
    data = str(data_dir)
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "PYTHONIOENCODING": "utf-8",
            "SUPERVISOR_MODE": "laptop",
            "SQL_BACKEND": "sqlite",
            "DATA_DIR": data,
            "SUPERVISOR_HOST": HOST,
            "SUPERVISOR_PORT": str(port),
            "SSL_OS_TRUSTSTORE": "0",
            "SCHEDULER_ENABLED": "0",
            "JUDGE_ENABLED": "0",
            "LLM_MOCK": "1",
            "LLM_BASE_URL": "",
            "GOVERNANCE_ENABLED": "1",
            "CONSOLE_SYSTEMS_ENABLED": "1",
            "CONSOLE_PLAYGROUND_ENABLED": "1",
            "LOG_FILE": str(data_dir / "app.log"),
        }
    )
    return env


@dataclass
class Reply:
    status: int
    text: str


def http(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout_s: float = 20.0,
) -> Reply:
    """One request. An HTTP error status is a reply, not an exception; a connection error is
    status 0 with the reason as text."""
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            return Reply(resp.status, resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return Reply(exc.code, exc.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError) as exc:
        return Reply(0, f"{type(exc).__name__}: {exc}")


def wait_for(
    probe: Callable[[], bool],
    timeout_s: float,
    *,
    interval_s: float = 0.25,
    alive: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """True when ``probe()`` is true before the deadline. Stops early when ``alive()`` is false."""
    deadline = clock() + timeout_s
    while True:
        if probe():
            return True
        if alive is not None and not alive():
            return False
        if clock() >= deadline:
            return False
        sleep(interval_s)


def form_body(fields: Mapping[str, str]) -> bytes:
    return urllib.parse.urlencode(fields).encode("utf-8")


def tail(path: Path, lines: int = 25) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-lines:]


def json_field(text: str, key: str) -> str | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return str(value[key]) if isinstance(value, dict) and key in value else None


# ----------------------------------------------------------------------------- steps


@dataclass
class Result:
    lines: list[str] = field(default_factory=list)
    failed: int = 0

    def ok(self, text: str) -> None:
        self.lines.append(f"[OK] {text}")

    def fail(self, text: str) -> None:
        self.failed += 1
        self.lines.append(f"[FAIL] {text}")

    def info(self, text: str) -> None:
        self.lines.append(f"     {text}")


Step = Callable[[str, Result], bool]


def step_healthz(base: str, res: Result) -> bool:
    r = http("GET", f"{base}/healthz")
    if r.status == 200:
        res.ok("healthz answers 200")
        return True
    res.fail(f"healthz: HTTP {r.status} {r.text[:120]}")
    return False


def step_console(base: str, res: Result) -> bool:
    r = http("GET", f"{base}/console/", headers={"X-Dev-User": DEV_USER})
    if r.status == 200 and "<html" in r.text.lower():
        res.ok("console page opens (/console/)")
        return True
    res.fail(f"/console/: HTTP {r.status} {r.text[:120]}")
    return False


def step_register(base: str, res: Result) -> bool:
    hdr = {"X-Dev-User": DEV_USER, "Content-Type": "application/json"}
    r = http("POST", f"{base}/v1/systems", headers=hdr, body=json.dumps(SYSTEM_FIELDS).encode())
    sid = json_field(r.text, "system_id")
    if r.status not in (200, 201) or not sid:
        res.fail(f"register system: HTTP {r.status} {r.text[:160]}")
        return False
    back = http("GET", f"{base}/v1/systems/{sid}", headers={"X-Dev-User": DEV_USER})
    if back.status != 200 or json_field(back.text, "name") != SYSTEM_NAME:
        res.fail(f"read the system back: HTTP {back.status} {back.text[:160]}")
        return False
    res.ok(f"AI system registered and read back ({sid})")
    return True


def step_playground(base: str, res: Result) -> bool:
    body = form_body(
        {
            "agent_id": "payments",
            "tool": "get_balance",
            "version": "1.0",
            "tool_class": "read_only",
            "args": json.dumps({"account_id": "ACC-0001"}),
            "context": "{}",
        }
    )
    hdr = {
        "X-Dev-User": DEV_USER,
        "HX-Request": "true",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    r = http("POST", f"{base}/console/playground/run", headers=hdr, body=body)
    if r.status == 200 and "get_balance" in r.text and "payload" in r.text:
        res.ok("playground dry-run check answered (nothing recorded)")
        return True
    res.fail(f"playground run: HTTP {r.status} {r.text[:160]}")
    return False


def step_verify(base: str, res: Result) -> bool:
    hdr = {"X-Dev-User": DEV_USER, "HX-Request": "true"}
    r = http("POST", f"{base}/console/chain/verify", headers=hdr, body=b"")
    if r.status == 200 and VERIFY_OK.search(r.text):
        res.ok("evidence chain verifies")
        return True
    if r.status == 200 and VERIFY_FAIL.search(r.text):
        res.fail("evidence chain verification FAILED")
        return False
    res.fail(f"chain verify: HTTP {r.status} {r.text[:160]}")
    return False


STEPS: tuple[Step, ...] = (step_healthz, step_console, step_register, step_playground, step_verify)


def run_steps(base: str, res: Result, steps: Sequence[Step] = STEPS) -> None:
    """Run the steps in order. A failed step does not stop the later ones, except that nothing
    runs when the app never answered /healthz."""
    for i, step in enumerate(steps):
        if not step(base, res) and i == 0:
            res.info("the app is not up: later steps skipped")
            return


# ----------------------------------------------------------------------------- main


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Supervisor launch smoke test")
    p.add_argument("--timeout", type=float, default=90.0, help="seconds to wait for /healthz")
    p.add_argument("--port", type=int, default=0, help="port (default: a free one)")
    p.add_argument("--keep", action="store_true", help="keep the temporary folder")
    args = p.parse_args(list(argv) if argv is not None else None)

    from supervisor import sandbox

    res = Result()
    tmp = Path(tempfile.mkdtemp(prefix="supervisor-smoke-"))
    port = args.port or free_port()
    base = f"http://{HOST}:{port}"
    res.ok(f"python {sys.version.split()[0]} on {sys.platform}; app on {base}; data {tmp}")
    proc = None
    try:
        proc = sandbox.start(
            [
                sandbox.python_executable(),
                "-m",
                "supervisor.cli",
                "serve",
                "--host",
                HOST,
                "--port",
                str(port),
            ],
            cwd=tmp,
            env=build_env(tmp, port),
        )
        res.ok(f"app started (pid {proc.pid})")
        up = wait_for(
            lambda: http("GET", f"{base}/healthz", timeout_s=2.0).status == 200,
            args.timeout,
            alive=proc.running,
        )
        if up:
            run_steps(base, res)
        else:
            why = "the process exited" if not proc.running() else f"no answer in {args.timeout:g} s"
            res.fail(f"healthz: {why}")
    finally:
        if proc is not None:
            code = proc.stop()
            res.ok(f"app stopped (exit {code})")
        if res.failed:
            for line in tail(tmp / "app.log"):
                res.info("log: " + line)
        if args.keep:
            res.info(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    for line in res.lines:
        print(ascii_safe(line), flush=True)  # noqa: T201 (CLI output)
    summary = "[FAIL] smoke test: %d step(s) failed" if res.failed else "[OK] smoke test passed"
    print(ascii_safe(summary % res.failed if res.failed else summary), flush=True)  # noqa: T201
    return 1 if res.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
