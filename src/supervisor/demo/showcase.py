"""``python -m supervisor.demo.showcase portfolio | journeys | traffic | factory`` (WP-D2).

Dispatcher of the Databricks showcase commands. Each command lives in its own module
(``showcase_<command>.py``) and is imported only when it is called, so a build that does not
have a command yet answers ``[SKIP]`` for it. Needs ``SHOWCASE_ENABLED=1`` (the command checks
it).

NOTE: WP-D2 made this file as the minimal dispatcher because WP-D1 was not on main yet. WP-D1
owns it and may replace it; keep the same shape (a ``COMMANDS`` table and ``main(argv)``).
"""

from __future__ import annotations

import importlib
import sys

COMMANDS: dict[str, str] = {
    "portfolio": "supervisor.demo.showcase_portfolio",  # WP-D1
    "journeys": "supervisor.demo.showcase_journeys",  # WP-D2
    "traffic": "supervisor.demo.showcase_traffic",  # WP-D2
    "factory": "supervisor.demo.showcase_factory",  # WP-D3
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        print("usage: python -m supervisor.demo.showcase " + " | ".join(COMMANDS) + " [options]")
        return 2
    try:
        mod = importlib.import_module(COMMANDS[args[0]])
    except ModuleNotFoundError as exc:
        if exc.name != COMMANDS[args[0]]:
            raise
        print(f"[SKIP] {args[0]} is not in this build yet")
        return 2
    return int(mod.main(args[1:]))


if __name__ == "__main__":
    from supervisor.bootstrap import bootstrap

    bootstrap()
    raise SystemExit(main())
