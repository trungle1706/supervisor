"""Showcase seeders: ``python -m supervisor.demo.showcase portfolio | journeys | factory``.

A tiny dispatcher shared by WP-D1 (portfolio), WP-D2 (journeys) and WP-D3 (factory). Each
subcommand lives in its own module ``showcase_<name>`` and exposes ``main(argv) -> int``. A module
that is not there yet answers ``[SKIP]``.
"""

from __future__ import annotations

import importlib
import sys

COMMANDS: tuple[str, ...] = ("portfolio", "journeys", "factory")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        print(  # noqa: T201 (CLI output)
            f"usage: python -m supervisor.demo.showcase {{{' | '.join(COMMANDS)}}} [options]"
        )
        return 2
    try:
        mod = importlib.import_module(f"supervisor.demo.showcase_{args[0]}")
    except ModuleNotFoundError as exc:
        if exc.name != f"supervisor.demo.showcase_{args[0]}":
            raise
        print(f"[SKIP] showcase {args[0]} is not installed in this build")  # noqa: T201
        return 1
    return int(mod.main(args[1:]))


if __name__ == "__main__":
    from supervisor.bootstrap import bootstrap

    bootstrap()
    raise SystemExit(main())
