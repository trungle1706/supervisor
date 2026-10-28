"""Seed the synthetic demo systems, agents, cases and evidence into the CONFIGURED SQL backend
(WP-P3).

    python -m supervisor.demo seed --databricks [--data-dir DIR]

The local demo seed (``python -m supervisor.cli demo seed``) wipes a demo data dir and fills a
fresh SQLite store. This command does not wipe anything. It writes through the same services the
console uses (AI system service, case service, evidence chain) into whatever store the
settings name: the Databricks warehouse in an App or on a laptop with a CLI profile, or SQLite
(used by the tests). Run ``python -m supervisor.jobs.bootstrap_schema`` first.

What it writes (all synthetic; no real bank data):

* three AI systems whose names start with ``demo-`` and their agents ``demo-kb-chatbot``,
  ``demo-customer-service``, ``demo-payments-ops`` (registry rows, shadow state, one
  ``agent_registered`` chain record each), linked to the systems; a Decision 33 classification
  draft per system (never applied);
* three cases opened from monitor findings with source ref ``demo-seed:demo-00N`` and a
  ``[demo]`` summary marker; each opening is a ``case`` record on the chain.

The tables have no ``demo`` column, so the marker is the id prefix: agent ids ``demo-*``,
system names ``demo-*``, case source refs ``demo-seed:demo-*``. Idempotent: a second run adds
nothing. The seed never deletes rows (the evidence tables are append only).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.config import Settings
from supervisor.demo.seed_systems import Manifest, SeedSystemsReport, seed_one
from supervisor.demo.session import Echo, build_session, default_echo

DEMO_PREFIX = "demo-"
MONITOR_ID = "demo-seed"
OWNER_TEAM = "Demo team (synthetic)"

_COMMON: dict[str, Any] = {
    "owner_team": OWNER_TEAM,
    "org_role": "deployer",
    "user_segment": "internal",
    "human_control": "post_review",
}

SYSTEMS: tuple[Manifest, ...] = (
    Manifest(
        system={
            **_COMMON,
            "name": "demo-kb-chatbot",
            "owner_user": "owner.demo",
            "purpose": (
                "Synthetic demo: answers staff questions from made-up policy text. "
                "It makes no decision and moves no money."
            ),
            "system_type": "assistant",
            "personal_data": "none",
            "money_movement": False,
            "credit_decision": False,
            "business_impact": "low",
            "autonomy_level": "l1_assistive",
        },
        agent_id="demo-kb-chatbot",
        agent_name="Demo knowledge chatbot",
        model_family="qwen",
        plug_point="fastapi_middleware",
        tools=(("search_policies", "read_only"),),
        path=Path("demo-kb-chatbot"),
    ),
    Manifest(
        system={
            **_COMMON,
            "name": "demo-customer-service",
            "owner_user": "owner.demo",
            "purpose": (
                "Synthetic demo: drafts replies to made-up customer questions "
                "and may export a masked customer summary."
            ),
            "system_type": "assistant",
            "personal_data": "identifiable",
            "money_movement": False,
            "credit_decision": False,
            "business_impact": "medium",
            "autonomy_level": "l1_assistive",
        },
        agent_id="demo-customer-service",
        agent_name="Demo customer service agent",
        model_family="llama",
        plug_point="fastapi_middleware",
        tools=(("lookup_customer", "pii_export"), ("draft_reply", "read_only")),
        path=Path("demo-customer-service"),
    ),
    Manifest(
        system={
            **_COMMON,
            "name": "demo-payments-ops",
            "owner_user": "owner.demo",
            "purpose": (
                "Synthetic demo: prepares made-up payment instructions for a person to approve."
            ),
            "system_type": "automation",
            "personal_data": "identifiable",
            "money_movement": True,
            "credit_decision": False,
            "business_impact": "high",
            "autonomy_level": "l3_tool_using_supervised",
        },
        agent_id="demo-payments-ops",
        agent_name="Demo payments operations agent",
        model_family="mistral",
        plug_point="langgraph_middleware",
        tools=(("prepare_payment", "money"), ("get_balance", "read_only")),
        path=Path("demo-payments-ops"),
    ),
)

# (agent, finding ref, severity, summary). Synthetic text only.
CASES: tuple[tuple[str, str, str, str], ...] = (
    (
        "demo-kb-chatbot",
        "demo-001",
        "low",
        "[demo] Answer cited a document that is not in the synthetic policy set.",
    ),
    (
        "demo-customer-service",
        "demo-002",
        "medium",
        "[demo] Reply draft contained an unmasked synthetic account number.",
    ),
    (
        "demo-payments-ops",
        "demo-003",
        "high",
        "[demo] Payment instruction above the synthetic per-transaction cap was prepared.",
    ),
)


@dataclass
class BackendSeedReport:
    lines: list[str] = field(default_factory=list)
    ok: bool = True
    backend: str = ""
    systems: int = 0
    systems_new: int = 0
    cases: int = 0
    cases_new: int = 0

    def fail(self, text: str) -> None:
        self.ok = False
        self.lines.append(f"[FAIL] {text}")


def seed_backend(settings: Settings, echo: Echo = default_echo) -> BackendSeedReport:
    """Write the demo rows into the store named by ``settings``. Never raises for a store
    problem: the report carries ``[FAIL]`` with the fix."""
    rep = BackendSeedReport(backend=settings.effective_sql_backend)

    def say(line: str) -> None:
        rep.lines.append(line)
        echo(line)

    say(f"[OK] demo seed target: {settings.describe_target()}")
    if not settings.governance_enabled:
        # The AI system service refuses writes while the flag is off. The flag only gates the
        # product pages; for this one process the seed turns it on so the rows can be written.
        settings = settings.model_copy(update={"governance_enabled": True})
        say("[OK] GOVERNANCE_ENABLED is off in the settings: on for this seed run only")
    try:
        session = build_session(settings)
    except Exception as exc:  # noqa: BLE001 - report with the fix, never a traceback
        rep.fail(
            f"cannot open the store ({type(exc).__name__}: {str(exc)[:200]}). "
            "Fix: python -m supervisor.jobs.bootstrap_schema, then retry"
        )
        echo(rep.lines[-1])
        return rep
    try:
        sys_rep = SeedSystemsReport()

        def say_sys(line: str) -> None:
            sys_rep.lines.append(line)
            say(line)

        for m in SYSTEMS:
            seed_one(session, m, say_sys, sys_rep)
        rep.systems = len(sys_rep.systems)
        rep.systems_new = sys_rep.created
        if sys_rep.skipped:
            rep.fail(f"{sys_rep.skipped} demo system(s) were refused by the registry")
            echo(rep.lines[-1])
        for agent_id, ref, severity, summary in CASES:
            before = session.cases.linked_case("monitor", f"{MONITOR_ID}:{ref}")
            case = session.cases.open_from_monitor(
                agent_id=agent_id,
                monitor_id=MONITOR_ID,
                finding_ref=ref,
                severity=severity,
                summary=summary,
            )
            rep.cases += 1
            if before is None:
                rep.cases_new += 1
            say(
                f"[OK] case {case['case_id']} {'opened' if before is None else 'already open'} "
                f"for {agent_id} ({severity})"
            )
    except Exception as exc:  # noqa: BLE001
        rep.fail(f"seed stopped ({type(exc).__name__}: {str(exc)[:200]})")
        echo(rep.lines[-1])
    finally:
        session.close()  # seals the chain with a signed root
    if rep.ok:
        say(
            f"[OK] demo seed: {rep.systems} system(s) ({rep.systems_new} new), "
            f"{rep.cases} case(s) ({rep.cases_new} new). All rows are synthetic and carry the "
            f"{DEMO_PREFIX!r} marker (agent id, system name, case source ref)"
        )
    return rep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m supervisor.demo seed --databricks",
        description="Write the synthetic demo systems, agents, cases and evidence into the "
        "configured SQL backend (idempotent, nothing is deleted).",
    )
    parser.add_argument("--databricks", action="store_true", required=True)
    parser.add_argument(
        "--data-dir", default=None, help="DATA_DIR override (signer key, SQLite file, spool)"
    )
    ns = parser.parse_args(sys.argv[1:] if argv is None else argv)
    from supervisor.config import load_settings

    kwargs: dict[str, Any] = {}
    if ns.data_dir:
        kwargs["data_dir"] = Path(ns.data_dir)
    try:
        settings = load_settings(**kwargs)
    except Exception as exc:  # noqa: BLE001
        default_echo(f"[FAIL] settings: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    return 0 if seed_backend(settings).ok else 1


__all__ = ["BackendSeedReport", "CASES", "SYSTEMS", "main", "seed_backend"]
