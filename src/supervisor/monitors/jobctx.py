"""Plumbing for monitor jobs run from the command line (``python -m supervisor.jobs.X``).

The command line builds its own store and chain writer. The chain has one writer per
lane (ADR D05): run monitor jobs from the command line only when the app is stopped,
or let the app's in-process scheduler run them (it passes the app's chain writer).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import Settings, load_settings
from supervisor.monitors.common import MonitorContext


@contextmanager
def standalone(
    settings: Settings | None = None,
) -> Iterator[tuple[Settings, Adapters, MonitorContext]]:
    """Settings, adapters and a MonitorContext whose evidence sink is a new chain writer.

    On exit the chain is sealed with a signed root and the store is closed."""
    from supervisor.evidence.chain import build_chain_writer
    from supervisor.jobs import bootstrap_schema

    settings = settings or load_settings()
    adapters = build_adapters(settings)
    try:
        if adapters.executor.dialect == "sqlite":
            bootstrap_schema.run(settings, adapters)
        chain = build_chain_writer(settings, adapters.tables, adapters.clock)
        ok = False
        try:
            yield settings, adapters, MonitorContext.from_adapters(adapters, chain)
            ok = True
        finally:
            chain.close(seal=ok)
    finally:
        adapters.close()


def ascii_line(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


__all__ = ["ascii_line", "standalone"]
