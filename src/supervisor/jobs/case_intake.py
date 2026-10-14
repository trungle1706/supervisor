"""Case intake job (WP8): open or join a case for every gate block/pause not yet linked.

Run: python -m supervisor.jobs.case_intake
Also callable in-process (scheduler, console queue): ``run(case_service)``.

Idempotent (one ``case_link`` row per gate decision). The standalone command writes to
the evidence chain, so run it only when the app is not running (single-writer rule); the
app calls ``run`` with its own case service instead.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.core.errors import SupervisorError  # noqa: E402


def run(case_service: Any) -> list[str]:
    """Return the case ids opened or joined."""
    return case_service.sync_gate_cases()


def main(argv: list[str] | None = None) -> int:
    from supervisor.cases import build_case_service
    from supervisor.config import load_settings
    from supervisor.wiring import build_runtime

    try:
        runtime = build_runtime(load_settings())
    except SupervisorError as exc:
        print(f"[FAIL] runtime: {exc}".encode("ascii", "replace").decode("ascii"))  # noqa: T201
        return 1
    try:
        touched = run(build_case_service(runtime))
    finally:
        runtime.close()
    print(f"[OK] case intake: {len(set(touched))} case(s) opened or joined")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
