"""Dev-only: capture every console screen at 1360x900 in English and Vietnamese (WP12).

    uv run python tools/console_screenshots.py              # demo store data/local/demo
    uv run python tools/console_screenshots.py --reseed     # seed + inject 4, 2, 3, 1 first
    uv run python tools/console_screenshots.py --out docs/design/screens --port 8765

What it does:
1. (``--reseed``) ``python -m supervisor.cli demo seed`` then ``demo inject 4, 2, 3, 1``
   (payments stays PAUSED by PAY-07, as after the live demo);
2. serves that store with ``python -m supervisor.cli serve`` on 127.0.0.1 (scheduler off,
   the console Onboard start on so the form is live);
3. drives a headless Chromium with Playwright and writes ``<screen>-<lang>.png`` (the first
   1360x900 viewport) and ``<screen>-<lang>-full.png`` (whole page) to ``--out``, plus a
   dark-theme overview.

Playwright is NOT a project dependency. The capture runs in the interpreter at
``PLAYWRIGHT_PYTHON`` (default ``/home/trung/supervisor-handoff/analysis/.venv/bin/python``);
when it is missing or cannot import Playwright the script prints ``[SKIP]`` and exits 0.
Processes start through ``supervisor.sandbox`` (the only module allowed to spawn them).
Output is ASCII only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from supervisor import sandbox  # noqa: E402

DEFAULT_PW = "/home/trung/supervisor-handoff/analysis/.venv/bin/python"

CAPTURE = r"""
import json, sys
from playwright.sync_api import sync_playwright
cfg = json.loads(open(sys.argv[1], encoding="utf-8").read())
with sync_playwright() as p:
    b = p.chromium.launch()
    for shot in cfg["shots"]:
        page = b.new_page(viewport={"width": 1360, "height": 900},
                          color_scheme=shot.get("scheme", "light"))
        page.goto(cfg["base"] + shot["path"], wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        if shot.get("click") and page.locator(shot["click"]).count():
            page.click(shot["click"])
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)
        page.screenshot(path=shot["file"])
        page.screenshot(path=shot["file"].replace(".png", "-full.png"), full_page=True)
        print("[OK] " + shot["file"].rsplit("/", 1)[-1])
        page.close()
    b.close()
"""


def say(line: str) -> None:
    print(line.encode("ascii", "backslashreplace").decode("ascii"))  # noqa: T201 - CLI output


def _get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - localhost
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, OSError):
        return 0, ""


def _first_case(data_dir: Path) -> str | None:
    """The most severe open case (the case screen shows it)."""
    sys.path.insert(0, str(REPO / "src"))
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings

    settings = load_settings(data_dir=data_dir, sql_backend="sqlite")
    a = build_adapters(settings)
    try:
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        rows = [r for r in a.state.query("cases") if r["status"] != "closed"]
        rows.sort(key=lambda r: (rank.get(r["severity"], 9), r["opened_at"]))
        return rows[0]["case_id"] if rows else None
    finally:
        a.close()


def _seed_ux2(data_dir: Path, py: str, env: dict[str, str]) -> None:
    """WP-UX2: rows for the new pages (alerts, tool rollup, inventory). Failures are [SKIP]."""
    steps = [
        [py, "-m", "supervisor.analytics.tools", "rollup", "--backfill"],
        [
            py,
            "-m",
            "supervisor.jobs.inventory",
            "--fixture",
            str(REPO / "tests" / "fixtures" / "inventory" / "workspace_7.json"),
        ],
    ]
    flags = {"TOOL_ANALYTICS_ENABLED": "1", "INVENTORY_ENABLED": "1"}
    for step in steps:
        r = sandbox.run(step, cwd=REPO, timeout_s=300, env={**env, **flags})
        say(("[OK] " if r.returncode == 0 else "[SKIP] ") + " ".join(step[2:4]))
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings

    a = build_adapters(load_settings(data_dir=data_dir, sql_backend="sqlite"))
    try:
        if not a.state.query("alert"):
            now = a.clock.now()
            for i, (sev, rule, agent) in enumerate(
                [
                    ("critical", "AL-BLOCK-BURST", "payments"),
                    ("high", "AL-PAUSE-REPEAT", "credit_prequal"),
                    ("medium", "AL-CHAIN-VERIFY-FAIL", None),
                ]
            ):
                a.state.insert(
                    "alert",
                    {
                        "alert_id": f"{i:032x}",
                        "ts": now,
                        "dedupe_key": f"{rule}:{i}",
                        "rule_id": rule,
                        "rule_hash": "h" * 64,
                        "severity": sev,
                        "status": "open",
                        "title": f"Demo alert {rule}",
                        "agent_id": agent,
                        "group_value": agent,
                        "window_s": 600,
                        "window_count": 5,
                        "threshold": 5,
                        "first_ts": now,
                        "last_ts": now,
                        "suppressed_count": i,
                        "case_id": None,
                        "chain_lane": "root",
                        "chain_seq": i,
                        "entry_hash": "e" * 64,
                        "refs": ["demo"],
                        "routes": ["inbox"],
                        "route_status": {"inbox": "sent"},
                    },
                )
    finally:
        a.close()


def _post(base: str, path: str, data: dict[str, str], user: str) -> int:
    from urllib.parse import urlencode

    req = urllib.request.Request(  # noqa: S310 - localhost
        base + path,
        data=urlencode(data).encode(),
        headers={"HX-Request": "true", "X-Dev-User": user},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _row_version(data_dir: Path, case_id: str) -> int:
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings

    a = build_adapters(load_settings(data_dir=data_dir, sql_backend="sqlite"))
    try:
        return int(a.state.get("cases", {"case_id": case_id})["row_version"])
    finally:
        a.close()


def _waiting_case(data_dir: Path) -> str | None:
    """A high / critical open case (the sign-off list needs one that is triaged)."""
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings

    a = build_adapters(load_settings(data_dir=data_dir, sql_backend="sqlite"))
    try:
        rows = [
            r
            for r in a.state.query("cases")
            if r["status"] == "open" and r["severity"] in ("high", "critical")
        ]
        return rows[0]["case_id"] if rows else None
    finally:
        a.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/console_screenshots.py")
    ap.add_argument("--data-dir", default=str(REPO / "data" / "local" / "demo"))
    ap.add_argument("--out", default=str(REPO / "docs" / "design" / "screens"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--reseed", action="store_true", help="seed + inject 4, 2, 3, 1 first")
    ap.add_argument(
        "--nav", choices=("sidebar", "top"), default="sidebar", help="CONSOLE_NAV (WP-UX1)"
    )
    args = ap.parse_args(argv)

    pw = os.environ.get("PLAYWRIGHT_PYTHON", DEFAULT_PW)
    if not Path(pw).is_file():
        say(f"[SKIP] Playwright interpreter not found: {pw} (set PLAYWRIGHT_PYTHON)")
        return 0
    probe = sandbox.run([pw, "-c", "import playwright.sync_api"], cwd=REPO, timeout_s=60)
    if probe.returncode != 0:
        say(f"[SKIP] {pw} cannot import playwright")
        return 0

    py = sandbox.python_executable()
    data_dir = Path(os.path.abspath(args.data_dir))
    env = {"PYTHONPATH": str(REPO / "src"), "DATA_DIR": str(data_dir)}
    if args.reseed:
        cli = [py, "-m", "supervisor.cli"]
        # the demo harness reads --data-dir, not DATA_DIR: without it the seed went to the
        # default data/local/demo while the server below served --data-dir
        dd = ["--data-dir", str(data_dir)]
        steps = [[*cli, "demo", "seed", *dd]] + [[*cli, "demo", "inject", n, *dd] for n in "4231"]
        # one onboarding run (mock model, labelled) so the Onboard cards have real artefacts
        out = data_dir / "onboard" / "payments"
        steps.append(
            [
                py,
                "-m",
                "supervisor.onboard",
                "--target",
                "src/supervisor_agents/payments",
                "--out",
                str(out),
                "--mock-llm",
            ]
        )
        for step in steps:
            r = sandbox.run(step, cwd=REPO, timeout_s=600, env=env)
            say(("[OK] " if r.returncode == 0 else "[FAIL] ") + " ".join(step[2:]))
            if r.returncode != 0:
                return 1
    if not data_dir.is_dir():
        say(f"[FAIL] no demo store at {data_dir}; run with --reseed")
        return 1
    case_id = _first_case(data_dir)
    if args.reseed:
        _seed_ux2(data_dir, py, env)

    out = Path(os.path.abspath(args.out))
    out.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{args.port}"
    server = sandbox.start(
        [py, "-m", "supervisor.cli", "serve", "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=REPO,
        env={
            **env,
            "SCHEDULER_ENABLED": "0",
            "CONSOLE_ONBOARD_ENABLED": "1",
            "CONSOLE_NAV": args.nav,
            "CONSOLE_NAV_PLACEHOLDERS": "1",  # WP-UX1: show the whole sidebar
            # WP-UX2: every agent tab and the Tools tab of Analytics
            "CONSOLE_TOOLS_ENABLED": "1",
            "TOOL_ANALYTICS_ENABLED": "1",
            "INVENTORY_ENABLED": "1",
            "CONSOLE_ASSURANCE_ENABLED": "1",
            "CONSOLE_COMPLIANCE_ENABLED": "1",
        },
    )
    try:
        deadline = time.monotonic() + 60
        while _get(base + "/console/")[0] != 200:
            if time.monotonic() > deadline:
                say("[FAIL] the console did not answer within 60 s")
                return 1
            time.sleep(0.5)
        waiting = _waiting_case(data_dir)
        if waiting and args.reseed:
            v = _row_version(data_dir, waiting)
            _post(
                base,
                f"/console/cases/{waiting}/assign",
                {"assignee": "reviewer.an", "row_version": str(v)},
                "reviewer.an",
            )
            v = _row_version(data_dir, waiting)
            _post(
                base,
                f"/console/cases/{waiting}/transition",
                {"to": "triaged", "note": "demo", "row_version": str(v)},
                "reviewer.an",
            )
        screens = [
            ("overview", "/console/", None),
            ("agents", "/console/agents", None),
            ("cases", "/console/cases", None),
            ("evidence", "/console/evidence", None),
            ("onboard", "/console/onboard", None),
            ("health", "/console/health", None),
        ]
        if args.nav == "sidebar":  # WP-UX1: the row drawer open, and the collapsed sidebar
            screens.insert(2, ("agents-drawer", "/console/agents", "a.rowlink"))
            screens.insert(3, ("agents-collapsed", "/console/agents", "[data-side-collapse]"))
        if args.nav == "sidebar":  # WP-UX2 pages
            screens += [
                ("agent-overview", "/console/agents/payments", None),
                ("agent-policy", "/console/agents/payments?tab=policy", None),
                ("agent-tools", "/console/agents/payments?tab=tools", None),
                ("agent-inventory", "/console/agents/payments?tab=inventory", None),
                ("agent-traces", "/console/agents/payments?tab=traces", None),
                ("agent-cases", "/console/agents/payments?tab=cases", None),
                ("agent-assurance", "/console/agents/payments?tab=assurance", None),
                ("agent-compliance", "/console/agents/payments?tab=compliance", None),
                ("alerts", "/console/alerts", None),
                ("alerts-drawer", "/console/alerts", "a.chipbtn[hx-get*='/drawer']"),
                ("signoff", "/console/signoff", None),
                ("analytics-gate", "/console/analytics?tab=gate", None),
                ("analytics-tools", "/console/analytics?tab=tools", None),
                ("analytics-metrics", "/console/analytics?tab=metrics", None),
                ("analytics-latency", "/console/analytics?tab=latency", None),
                ("cases-drawer", "/console/cases", "a.chipbtn[hx-get*='/drawer']"),
                ("inbox", "/console/inbox", None),
                ("inventory", "/console/inventory", None),
            ]
        if case_id:
            screens.insert(3, ("case", f"/console/cases/{case_id}", None))
            screens.insert(4, ("case-rules", f"/console/cases/{case_id}", "a[data-tab=rules]"))
        shots = []
        for lang in ("en", "vi"):
            for name, path, click in screens:
                sep = "&" if "?" in path else "?"
                shot = {"path": f"{path}{sep}lang={lang}", "file": str(out / f"{name}-{lang}.png")}
                if click:
                    shot["click"] = click
                shots.append(shot)
        dark = {"path": "/console/?lang=en", "file": str(out / "overview-en-dark.png")}
        shots.append({**dark, "scheme": "dark"})
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "capture.py"
            script.write_text(CAPTURE, encoding="utf-8")
            cfg = Path(tmp) / "cfg.json"
            cfg.write_text(json.dumps({"base": base, "shots": shots}), encoding="utf-8")
            r = sandbox.run([pw, str(script), str(cfg)], cwd=tmp, timeout_s=600)
        say(r.stdout.strip())
        if r.returncode != 0:
            say("[FAIL] capture: " + (r.stderr.strip().splitlines() or ["?"])[-1])
            return 1
        say(f"[OK] {len(shots)} screens in {out}")
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    sys.exit(main())
