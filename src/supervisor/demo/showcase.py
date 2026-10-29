"""Dispatcher of the Databricks showcase: ``python -m supervisor.demo.showcase <command> ...``.

    portfolio | journeys | factory

This is the minimal dispatcher of WP-D3. WP-D1 (portfolio) and WP-D2 (journeys) replace the two
placeholder branches when they merge; ``factory`` is ``showcase_factory.main``. Needs
``SHOWCASE_ENABLED=1`` (checked by each command).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

COMMANDS = ("portfolio", "journeys", "factory")


def _say(line: str) -> None:
    sys.stdout.write(line.encode("ascii", "replace").decode("ascii") + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        _say("usage: python -m supervisor.demo.showcase {" + "|".join(COMMANDS) + "} [options]")
        return 0 if args else 2
    cmd, rest = args[0], args[1:]
    if cmd == "factory":
        from supervisor.demo import showcase_factory

        return showcase_factory.main(rest)
    if cmd in COMMANDS:
        _say(f"[SKIP] {cmd} is not in this build yet (WP-D1 / WP-D2)")
        return 1
    _say(f"[FAIL] unknown command {cmd!r}; use one of {', '.join(COMMANDS)}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
