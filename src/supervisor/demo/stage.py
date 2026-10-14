"""Stage mode: the console and the demo steps in ONE process (single chain writer).

    python -m supervisor.cli demo seed
    python -m supervisor.cli demo serve            then open http://127.0.0.1:8000/console/

The app (``supervisor.app:app``: gateway routes, console) serves the demo data dir. The
terminal that runs ``demo serve`` takes the operator's keys:

    1..4  inject incident 1..4 (real agents + gateway; console updates on refresh)
    t     tamper test (export, flip one byte in a copy, verify both)
    r     resume paused agents by two people (owner + reviewer) - [DEMO] shortcut;
          on stage, prefer the two clicks in the console (Agents page)
    z     reset to the seed snapshot (seconds), the console keeps running
    s     status (agents, open cases, chain entries)
    q     stop the server

Why one process: the evidence chain has a single writer. A second process writing the
same store would hit ``ChainConflictError``. Here the demo steps use the same runtime,
gateway and ``CaseService`` instance that the console routes use.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any

from supervisor.config import Settings
from supervisor.demo.session import DemoSession, Echo, build_session, default_echo

HELP = "keys: 1-4 inject | t tamper | r resume | z reset | s status | q quit"


class Stage:
    def __init__(self, settings: Settings, *, replay: bool = False, echo: Echo = default_echo):
        self.settings = settings
        self.replay = replay
        self.echo = echo
        self.session: DemoSession | None = None
        self.server: Any = None
        self._lock = threading.RLock()

    # -- install the session as the app's runtime and console context ------------
    def install(self) -> None:
        from supervisor.console import context as console_context
        from supervisor.gateway import wiring as gate_wiring

        session = build_session(self.settings, install_provider=True)
        with gate_wiring._lock, console_context._lock:  # noqa: SLF001 - swap atomically
            gate_wiring._runtime = session.runtime  # noqa: SLF001 - app lifespan reuses it
            gate_wiring.set_gateway(session.runtime.gateway)
            console_context.set_context(session.console)
            self.session = session

    def uninstall(self) -> None:
        from supervisor.console import context as console_context
        from supervisor.gateway import wiring as gate_wiring

        with gate_wiring._lock, console_context._lock:  # noqa: SLF001
            console_context.set_context(None)
            gate_wiring.shutdown_runtime()  # closes the session runtime (signed root)
            self.session = None

    # -- operator commands -------------------------------------------------------
    def command(self, key: str) -> bool:
        """Run one operator key. Returns False when the operator asked to quit."""
        from supervisor.demo import inject, reset, tamper

        key = key.strip().lower()
        with self._lock:
            if key in ("q", "quit", "exit"):
                return False
            if not key:
                return True
            if self.session is None:
                self.echo("[FAIL] no demo session (reset failed?); press z to retry")
                return True
            if key in ("1", "2", "3", "4"):
                inject.inject(self.session, key, echo=self.echo, replay=self.replay)
            elif key == "t":
                tamper.tamper(self.session, echo=self.echo)
            elif key == "r":
                self._resume_all()
            elif key == "z":
                from supervisor.console import context as console_context
                from supervisor.core.errors import SupervisorError
                from supervisor.gateway import wiring as gate_wiring

                # Hold both locks for the whole swap: a request that arrives meanwhile
                # waits for the new context instead of seeing a closed runtime.
                with gate_wiring._lock, console_context._lock:  # noqa: SLF001
                    self.uninstall()
                    try:
                        reset.restore(self.settings, echo=self.echo)
                    except SupervisorError as exc:
                        self.echo(f"[FAIL] {exc} (a second reset is safe: the snapshot is kept)")
                    self.install()
                self.echo("[OK] console now shows the reset store (refresh the page)")
            elif key == "s":
                self._status()
            else:
                self.echo(HELP)
        return True

    def _resume_all(self) -> None:
        from supervisor.demo.inject import DEMO_REVIEWER

        s = self.session
        assert s is not None
        done = 0
        for row in s.state.query("agent"):
            if row["gate_state"] != "PAUSED":
                continue
            reason = "demo stage: case reviewed"
            s.gateway.states.resume(row["agent_id"], row["owner_user"], reason)
            s.gateway.states.resume(row["agent_id"], DEMO_REVIEWER, reason)
            done += 1
            self.echo(
                f"[OK] {row['agent_id']} resumed by two people (owner + {DEMO_REVIEWER}); "
                "[DEMO] shortcut, recorded on the chain"
            )
        if not done:
            self.echo("[OK] no paused agent")

    def _status(self) -> None:
        s = self.session
        assert s is not None
        agents = ", ".join(f"{r['agent_id']}={r['gate_state']}" for r in s.state.query("agent"))
        open_cases = [c for c in s.cases.list_cases() if c["status"] != "closed"]
        entries = len(s.tables.query("chain_entry"))
        self.echo(f"[OK] agents: {agents}")
        self.echo(f"[OK] open cases: {len(open_cases)}; chain entries: {entries}")

    def command_loop(self) -> None:
        self.echo(HELP)
        while True:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                break
            if line == "":  # stdin closed
                break
            try:
                if not self.command(line):
                    break
            except Exception as exc:  # noqa: BLE001 - keep the stage alive; show the error
                self.echo(f"[FAIL] {type(exc).__name__}: {exc}")
        if self.server is not None:
            self.server.should_exit = True


def serve(
    settings: Settings, *, host: str = "127.0.0.1", port: int = 8000, replay: bool = False
) -> int:
    """Run the app on the demo data dir with the operator key loop. Blocks until quit."""
    import uvicorn

    from supervisor.config import get_settings
    from supervisor.demo.reset import has_snapshot

    if not has_snapshot(settings.data_dir):
        default_echo(
            f"[FAIL] no seeded demo in {settings.data_dir}. Fix: python -m supervisor.cli demo seed"
        )
        return 1
    # The app reads settings through get_settings(): point it at the demo data dir too.
    os.environ["DATA_DIR"] = str(settings.data_dir)
    os.environ["SQL_BACKEND"] = "sqlite"
    get_settings.cache_clear()
    stage = Stage(settings, replay=replay)
    stage.install()
    from supervisor.app import app

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    stage.server = uvicorn.Server(config)
    default_echo(f"[OK] demo console on http://{host}:{port}/console/ (data {settings.data_dir})")
    threading.Thread(target=stage.command_loop, daemon=True, name="demo-keys").start()
    stage.server.run()
    if stage.session is not None:
        stage.uninstall()
    default_echo("[OK] demo server stopped")
    return 0


__all__ = ["HELP", "Stage", "serve"]
