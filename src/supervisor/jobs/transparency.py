"""Transparency job (WP31): build and sign the reports of every registered, running agent.

Run: python -m supervisor.jobs.transparency
Also callable in-process (scheduler): ``run(ctx, settings)``; on by TRANSPARENCY_ENABLED.

For each agent that is not retired, for each variant, it builds the report from the current
facts. When the facts differ from the last version it writes the next version (JSON, HTML and PDF
in Vietnamese and English), one ``transparency_report`` chain record that carries the diff to the
previous version (which sections changed; counts and fixed section ids only), and the
``transparency_report`` rows. A run with no change writes nothing. One agent that fails is
counted and the others go on. The chain has one writer per lane: run the command line only when
the app is stopped, or let the app's scheduler run it.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.common import MonitorContext  # noqa: E402
from supervisor.monitors.jobctx import ascii_line, standalone  # noqa: E402
from supervisor.transparency.facts import Sources  # noqa: E402
from supervisor.transparency.service import TransparencyService  # noqa: E402

log = logging.getLogger("supervisor.transparency")
ACTOR = "system:transparency"


def service_for(ctx: MonitorContext, settings: Settings) -> TransparencyService:
    from supervisor.adapters.factory import make_masker

    src = Sources(
        ctx.state, ctx.tables, ctx.clock, settings, chain=ctx.evidence, masker=make_masker(settings)
    )
    return TransparencyService(src, evidence=ctx.evidence)


def run(
    ctx: MonitorContext, settings: Settings, service: TransparencyService | None = None
) -> dict[str, Any]:
    svc = service or service_for(ctx, settings)
    out = {"agents": 0, "made": 0, "unchanged": 0, "failed": 0, "changed_sections": 0}
    for agent_id in svc.facts.running_agents():
        out["agents"] += 1
        try:
            results = svc.generate(agent_id, actor=ACTOR)
        except Exception as exc:  # noqa: BLE001 - one agent must not stop the others
            out["failed"] += 1
            log.warning("transparency job: %s failed: %s", agent_id, type(exc).__name__)
            continue
        for r in results:
            if r["status"] == "made":
                out["made"] += 1
                out["changed_sections"] += len(r["diff"]["changed"]) + len(r["diff"]["added"])
            else:
                out["unchanged"] += 1
    return out


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m supervisor.jobs.transparency", description=__doc__.splitlines()[0]
    ).parse_args(argv)
    try:
        with standalone() as (settings, _, ctx):
            if not settings.transparency_enabled:
                print("[SKIP] transparency reports are off (TRANSPARENCY_ENABLED=1 turns them on)")  # noqa: T201
                return 0
            out = run(ctx, settings)
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] transparency: {exc}"))  # noqa: T201
        return 1
    print(ascii_line("[OK] transparency: " + ", ".join(f"{k}={v}" for k, v in out.items())))  # noqa: T201
    return 0 if out["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
