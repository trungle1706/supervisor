"""One demo session: the real runtime (store, policy, chain, gateway) on a demo data dir,
the console context built on it (the same ``CaseService`` the reviewer console uses) and
the synthetic bank world that answers the gateway's fact lookups.

The demo data dir is separate from the normal ``DATA_DIR`` (default ``data/local/demo``,
under the git-ignored ``data/local``). A marker file ``.supervisor-demo`` makes it safe to
wipe: ``seed`` refuses to delete a non-empty directory without the marker.

Single writer: a session owns the evidence chain of its data dir while it is open. Do not
open a session while ``serve`` (or ``demo serve``) runs on the same data dir.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT, Settings, load_settings

DEFAULT_DATA_DIR = REPO_ROOT / "data" / "local" / "demo"
MARKER = ".supervisor-demo"
SNAPSHOT_DIR = ".demo-snapshot"

Echo = Callable[[str], None]


def ascii_line(text: str) -> str:
    """CLI output is ASCII only (Windows cmd code pages)."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def default_echo(line: str) -> None:
    print(ascii_line(line), flush=True)  # noqa: T201 (CLI output)


def resolve_data_dir(data_dir: str | Path | None) -> Path:
    p = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    p = p.expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return Path(os.path.abspath(p))


def demo_settings(data_dir: str | Path | None = None, **overrides: Any) -> Settings:
    """Settings for the demo: SQLite, signing key and anchors under the demo data dir.

    Judge models and the masker come from the environment / ``.env`` as usual. With no
    judge model configured the judges are the deterministic MockJudge, labelled ``mock``
    in every verdict and on screen."""
    # Everything the demo writes stays under the demo data dir (and is reset with it).
    fixed: dict[str, Any] = {
        "sql_backend": "sqlite",
        "supervisor_mode": "laptop",
        "sqlite_path": None,
        "signer_kind": "ed25519_file",
        "signer_key_path": None,
        "anchor_kind": "worm_dir",
        "anchor_path": None,
        "casefile_dir": None,
        "console_export_dir": None,
        "recorder_spool_dir": None,
    }
    fixed.update(overrides)
    return load_settings(data_dir=resolve_data_dir(data_dir), **fixed)


@dataclass
class DemoSession:
    settings: Settings
    runtime: Any  # supervisor.wiring.Runtime
    console: Any  # supervisor.console.context.ConsoleContext
    world: Any  # supervisor_agents.common.world.BankWorld

    @property
    def cases(self) -> Any:
        return self.console.cases

    @property
    def tables(self) -> Any:
        return self.runtime.adapters.tables

    @property
    def state(self) -> Any:
        return self.runtime.adapters.state

    @property
    def gateway(self) -> Any:
        return self.runtime.gateway

    def close(self) -> None:
        self.runtime.close()


def build_session(settings: Settings, *, install_provider: bool = False) -> DemoSession:
    """Runtime + console context on ``settings``. The caller closes it.

    ``install_provider``: keep the console's principal provider installed process-wide
    (``demo serve``). Otherwise the previous provider is restored after the build, so an
    in-process demo run does not change the identity provider of the host process."""
    from supervisor.adapters import auth
    from supervisor.console.context import build_context
    from supervisor.demo.replay import world_facts
    from supervisor.wiring import build_runtime
    from supervisor_agents.common.world import BankWorld

    world = BankWorld.build()
    runtime = build_runtime(settings, facts=world_facts(world), policy_refresh_s=0.0)
    try:
        previous = auth._provider  # noqa: SLF001 - restored below (see docstring)
        ctx = build_context(runtime)
        if not install_provider:
            auth.set_provider(previous)
    except BaseException:
        runtime.close()
        raise
    return DemoSession(settings, runtime, ctx, world)


@contextmanager
def open_session(settings: Settings) -> Iterator[DemoSession]:
    s = build_session(settings)
    try:
        yield s
    finally:
        s.close()


def is_demo_dir(path: Path) -> bool:
    return (path / MARKER).is_file()


def mark_demo_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / MARKER).write_text(
        "Supervisor demo data dir (synthetic data only). Safe to delete.\n", encoding="utf-8"
    )


__all__ = [
    "DEFAULT_DATA_DIR",
    "MARKER",
    "SNAPSHOT_DIR",
    "DemoSession",
    "Echo",
    "ascii_line",
    "build_session",
    "default_echo",
    "demo_settings",
    "is_demo_dir",
    "mark_demo_dir",
    "open_session",
    "resolve_data_dir",
]
