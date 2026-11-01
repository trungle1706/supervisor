"""Helpers shared by the small command-line tools and the GO / NO-GO harnesses of the risk,
controls, tasks, transparency, alerts and inventory packages (clean-up audit D10).

The file name starts with an underscore on purpose: the architecture test demands a
``bootstrap()`` call in every public module of ``jobs/``, and this is a helper, not a job.

Standard library only at module level, so a ``__main__`` module may import it right after
``bootstrap()``. Output is ASCII (``[OK]``, ``[FAIL]``, ``[SKIP]``).
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_BY_PATTERN = re.compile(r"[A-Za-z0-9_.@+-]{1,64}")


def say(text: str) -> None:
    """Print text as ASCII (other characters become ``?``)."""
    print(text.encode("ascii", "replace").decode("ascii"))  # noqa: T201


def by_arg(value: str) -> str:
    """``argparse`` type of ``--by``: a user id of 1 to 64 safe characters."""
    if not _BY_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "--by must be 1 to 64 characters from A-Z a-z 0-9 _ . @ + -"
        )
    return value


def cut(text: str, n: int) -> str:
    """At most ``n`` characters; a longer text ends with ``~``."""
    return text if len(text) <= n else text[: n - 1] + "~"


def audit_cli_action(svc: Any, by: str, permission: str, path: str, kind: str, detail: str) -> None:
    """One ``console_action`` row for a command-line action (the operator is trusted as given)."""
    from supervisor.adapters.auth.audit import write_action

    write_action(
        svc.tables,
        svc.clock,
        request_id=None,
        actor=None,
        actor_fallback=(by, "operator", "cli"),
        permission=permission,
        method="CLI",
        path=path,
        outcome="ok",
        target_kind=kind,
        detail=detail,
    )


def print_verdicts(verdicts: Mapping[str, str]) -> int:
    """Print ``name: GO|NO-GO`` lines; returns the number that are not ``GO``."""
    bad = 0
    for name, v in verdicts.items():
        print(f"    {name}: {v}")  # noqa: T201
        bad += v != "GO"
    return bad


def write_baseline(path: Path, doc: Mapping[str, Any]) -> None:
    """Write a harness ``baseline.json``: sorted keys, indent 2, UTF-8, LF, final newline."""
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
