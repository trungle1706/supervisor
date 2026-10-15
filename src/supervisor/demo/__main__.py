"""``python -m supervisor.demo drill`` runs the fail-mode drill; anything else is the demo
runbook (same as ``python -m supervisor.cli demo``)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "drill":
        from supervisor.demo import drill

        return drill.main(args[1:])
    from supervisor.demo import runbook

    return runbook.main(args)


if __name__ == "__main__":
    from supervisor.bootstrap import bootstrap

    bootstrap()
    raise SystemExit(main())
