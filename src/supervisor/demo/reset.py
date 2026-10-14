"""Snapshot and restore of the demo data dir, so a demo can be rerun in seconds.

    python -m supervisor.cli demo reset [--data-dir DIR]        # restore the snapshot
    python -m supervisor.cli demo reset --snapshot              # take a new snapshot

The snapshot is a plain file copy of the data dir (SQLite store, signing key, anchors,
case files) into ``<data dir>/.demo-snapshot``, taken by ``seed`` right after the normal
day. Restore deletes everything else in the data dir and copies the snapshot back, then
reads the store (read only, no chain writer) and checks it matches the snapshot facts:
same chain entry count and root head, no cases, every agent RUNNING.

Stop the server first: the store must not be open (Windows locks open SQLite files).
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.config import Settings
from supervisor.core.errors import SupervisorError
from supervisor.demo.session import MARKER, SNAPSHOT_DIR, Echo, default_echo, is_demo_dir

FACTS_FILE = "snapshot_facts.json"


class ResetError(SupervisorError):
    """The snapshot cannot be taken or restored."""


@dataclass
class ResetReport:
    lines: list[str] = field(default_factory=list)
    ok: bool = True
    seconds: float = 0.0


def snapshot_path(data_dir: Path) -> Path:
    return Path(data_dir) / SNAPSHOT_DIR


def has_snapshot(data_dir: Path) -> bool:
    return (snapshot_path(data_dir) / FACTS_FILE).is_file()


def store_facts(settings: Settings) -> dict[str, Any]:
    """Read-only facts about the demo store (no chain writer is opened)."""
    from supervisor.adapters.factory import build_adapters

    a = build_adapters(settings)
    try:
        entries = a.tables.query("chain_entry", order_by=["lane", "seq"])
        roots = [e for e in entries if e["lane"] == "root"]
        agents = a.state.query("agent")
        cases = a.state.query("cases")
        return {
            "chain_entries": len(entries),
            "root_head": roots[-1]["entry_hash"] if roots else None,
            "cases": len(cases),
            "agent_states": {r["agent_id"]: r["gate_state"] for r in agents},
            "gate_decisions": len(a.tables.query("agent_event", {"event_type": "gate_decision"})),
        }
    finally:
        a.close()


def _ignore_snapshot(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n == SNAPSHOT_DIR]


def snapshot(settings: Settings, echo: Echo = default_echo) -> dict[str, Any]:
    """Copy the (closed) data dir into ``.demo-snapshot``. Returns the snapshot facts."""
    data_dir = Path(settings.data_dir)
    if not is_demo_dir(data_dir):
        raise ResetError(f"not a demo data dir (no {MARKER} file): {data_dir}")
    facts = store_facts(settings)
    snap = snapshot_path(data_dir)
    if snap.exists():
        shutil.rmtree(snap)
    try:
        shutil.copytree(data_dir, snap, ignore=_ignore_snapshot)
    except OSError as exc:
        raise ResetError(
            f"cannot copy {data_dir} to the snapshot ({exc}). Stop the server first."
        ) from exc
    (snap / FACTS_FILE).write_text(json.dumps(facts, sort_keys=True, indent=2), encoding="utf-8")
    echo(
        f"[OK] snapshot taken: {snap} (chain entries {facts['chain_entries']}, "
        f"cases {facts['cases']})"
    )
    return facts


def restore(settings: Settings, echo: Echo = default_echo) -> ResetReport:
    """Restore the snapshot and check the restored store against the snapshot facts."""
    t0 = time.perf_counter()
    rep = ResetReport()
    data_dir = Path(settings.data_dir)
    snap = snapshot_path(data_dir)
    if not is_demo_dir(data_dir):
        raise ResetError(f"not a demo data dir (no {MARKER} file): {data_dir}")
    if not has_snapshot(data_dir):
        raise ResetError(
            f"no snapshot in {snap}. Fix: python -m supervisor.cli demo seed --data-dir {data_dir}"
        )
    want = json.loads((snap / FACTS_FILE).read_text(encoding="utf-8"))
    try:
        for child in data_dir.iterdir():
            if child.name in (SNAPSHOT_DIR, MARKER):
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in snap.iterdir():
            if child.name == FACTS_FILE:
                continue
            dest = data_dir / child.name
            if child.is_dir():
                shutil.copytree(child, dest)
            else:
                shutil.copy2(child, dest)
    except OSError as exc:
        raise ResetError(
            f"cannot restore {data_dir} ({exc}). Stop the server (it holds the store open) "
            "and run the reset again."
        ) from exc
    got = store_facts(settings)
    rep.seconds = time.perf_counter() - t0
    checks = [
        ("chain entries", got["chain_entries"], want["chain_entries"]),
        ("chain root head", got["root_head"], want["root_head"]),
        ("cases", got["cases"], want["cases"]),
        ("agent gate states", got["agent_states"], want["agent_states"]),
    ]
    bad = [f"{name}: {g!r} != {w!r}" for name, g, w in checks if g != w]
    if bad:
        rep.ok = False
        rep.lines.append(
            "[FAIL] reset: restored store differs from the snapshot: " + "; ".join(bad[:4])
        )
    else:
        states = ",".join(sorted(set(got["agent_states"].values()))) or "-"
        rep.lines.append(
            f"[OK] reset: snapshot restored in {rep.seconds:.2f} s; chain entries "
            f"{got['chain_entries']}, cases {got['cases']}, agents {states}"
        )
    for line in rep.lines:
        echo(line)
    return rep


__all__ = [
    "FACTS_FILE",
    "ResetError",
    "ResetReport",
    "has_snapshot",
    "restore",
    "snapshot",
    "snapshot_path",
    "store_facts",
]
