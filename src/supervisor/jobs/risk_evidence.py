"""Risk evidence job (WP29): count what the controls linked to each risk did, per window.

Run: python -m supervisor.jobs.risk_evidence
Also callable in-process (scheduler): ``run(ctx, settings)``; on by RISK_REGISTER_ENABLED.

For every active risk it counts the gate rule hits, assurance pack verdicts and monitor statuses
of the supervised agents the risk applies to (SHADOW and RETIRED agents are not evidence), writes
one ``risk_evidence`` row (integers, codes and hashes, no text) and one ``risk_evidence`` chain
record, and lets the evidence rule decide the residual score (docs/risk-register.md). A second
run in the same window writes nothing. The chain has one writer per lane: run the command line
only when the app is stopped, or let the app's scheduler run it.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402
from supervisor.risk.service import RiskService  # noqa: E402


def service_for(ctx: MonitorContext, settings: Settings) -> RiskService:
    return RiskService(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)


def run(
    ctx: MonitorContext, settings: Settings, service: RiskService | None = None
) -> dict[str, Any]:
    return (service or service_for(ctx, settings)).run_evidence()


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m supervisor.jobs.risk_evidence", description=__doc__.splitlines()[0]
    ).parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            if not settings.risk_register_enabled:
                print("[SKIP] risk register is off (RISK_REGISTER_ENABLED=1 turns it on)")  # noqa: T201
                return 0
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] risk_evidence: {exc}"))  # noqa: T201
        return 1
    print(ascii_line("[OK] risk_evidence: " + ", ".join(f"{k}={v}" for k, v in out.items())))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
