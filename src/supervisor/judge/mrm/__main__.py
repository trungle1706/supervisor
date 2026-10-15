"""CLI: ``python -m supervisor.judge.mrm {card,validate,triggers} ...``.

``card --out DIR``                 model card (json + md).
``validate --out DIR [--runs N]``  validation report, GO / NO-GO, evidence + table row.
``triggers``                       re-validation triggers fired since the last validation.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())  # noqa: T201
        return 0 if args else 2
    cmd, rest = args[0], args[1:]
    if cmd == "card":
        from supervisor.judge.mrm.card import main as run
    elif cmd == "validate":
        from supervisor.judge.mrm.validation import main as run
    elif cmd == "triggers":
        from supervisor.judge.mrm.control import main as run
    else:
        print(f"[FAIL] unknown command {cmd!r}; use card | validate | triggers")  # noqa: T201
        return 2
    return run(rest)


if __name__ == "__main__":
    sys.exit(main())
