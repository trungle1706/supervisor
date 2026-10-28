"""``python -m supervisor.demo drill`` runs the fail-mode drill; ``seed --databricks`` seeds the
configured SQL backend (WP-P3); anything else is the demo
runbook (same as ``python -m supervisor.cli demo``)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "drill":
        from supervisor.demo import drill

        return drill.main(args[1:])
    if args[:1] == ["seed"] and "--databricks" in args:  # WP-P3: seed the configured SQL backend
        from supervisor.demo import seed_backend

        return seed_backend.main([a for a in args[1:]])
    from supervisor.demo import runbook

    return runbook.main(args)


if __name__ == "__main__":
    from supervisor.bootstrap import bootstrap

    bootstrap()
    raise SystemExit(main())
