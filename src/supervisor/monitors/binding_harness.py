"""Harness for the per-agent monitor bindings (WP1b-B, D06; TEAM_BRIEF section 3).

    python -m supervisor.monitors.binding_harness [--json] [--expected FILE] [--keep DIR]

Builds a synthetic trace of three agents in a throw-away SQLite store, runs the quality,
fairness, drift and multi-agent monitors with the bindings resolver, and compares the status
each monitor wrote for each agent with the golden file ``data/eval/monitor_bindings/
expected.json``:

=================  =========================================================================
``memo_agent``     bound by policy YAML and manifest: every monitor must produce values
``helpdesk``       no binding; the reply tool is derived from its name: quality ok, the
                   other three monitors ``not_applicable`` with a reason
``lookup_agent``   no binding and nothing to derive: all four ``not_applicable``
=================  =========================================================================

The question behind the rubric is the platform-engineer one (benchmark defect D06): "is a
monitor that is switched on silent for this agent, and does anyone see it?". A monitor
that cannot run must say so; one that can must produce a value. No model is called (the
quality scorer is the labelled mock); the run is deterministic and takes a few seconds.
Thresholds are ILLUSTRATIVE: the gate is exact equality with the golden statuses.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from supervisor.core.models import AgentEvent
from supervisor.monitors.seed import event as make_event

T0 = datetime(2026, 9, 7, 0, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=7)
GOLDEN = (
    Path(__file__).resolve().parents[3] / "data" / "eval" / "monitor_bindings" / "expected.json"
)

POLICY_YAML = """\
policy_version: 1
tools:
  read_facility: read_only
  compose_memo: read_only
  decide_limit: credit
  release_funds: money
  lookup_account: read_only
  list_branches: read_only
  reply: read_only
agents:
  memo_agent:
    name: Memo agent (synthetic)
    owner_user: memo-lead@example.invalid
    owner_team: Credit Operations
    monitors:
      quality: {reply_tools: [compose_memo], text_arg: body}
      fairness:
        decision_tool: decide_limit
        decision_arg: outcome
        subject_arg: case_id
        approve_values: [granted]
        protected_attribute_keys: {gender: applicant_gender}
      split_payment: {tool: release_funds, customer_key: payer_id, payee_key: beneficiary_id}
      drift: {window_s: 3600, baseline_windows: 3, min_baseline_windows: 2, min_n: 5}
  helpdesk:
    name: Helpdesk agent (synthetic)
    owner_user: help-lead@example.invalid
    owner_team: Customer Care
  lookup_agent:
    name: Lookup agent (synthetic)
    owner_user: lookup-lead@example.invalid
    owner_team: Branch Network
"""

MANIFESTS = {
    "memo_agent": [
        "read_facility:read_only",
        "compose_memo:read_only",
        "decide_limit:credit",
        "release_funds:money",
    ],  # fmt: skip
    "helpdesk": ["lookup_account:read_only", "reply:read_only"],
    "lookup_agent": ["lookup_account:read_only", "list_branches:read_only"],
}


def write_fixture(root: Path) -> tuple[Path, Path]:
    """Policy folder and manifest folder for the three agents. Returns (policies, manifests)."""
    policies, manifests = root / "policies", root / "agents"
    policies.mkdir(parents=True)
    (policies / "bindings.yaml").write_text(POLICY_YAML, encoding="utf-8")
    for agent, tools in MANIFESTS.items():
        d = manifests / agent
        d.mkdir(parents=True)
        lines = [f"id: {agent}", "tools:"]
        for t in tools:
            name, cls = t.split(":")
            lines += [f"  - name: {name}", f"    risk_class: {cls}"]
        (d / "manifest.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return policies, manifests


def build_events() -> list[AgentEvent]:
    """Seven hours of synthetic traffic for the three agents (all values invented)."""
    from supervisor.gateway.engine import key_hash

    out: list[AgentEvent] = []

    def ev(ts: datetime, agent: str, etype: str, **kw: Any) -> AgentEvent:
        version = kw.pop("version", None)
        args = kw.pop("args", None)
        e = make_event(ts, agent, version or "", etype, **kw)
        update: dict[str, Any] = {"agent_version": version}
        if args is not None:
            update["args_masked"] = json.dumps(args, sort_keys=True)
        return e.model_copy(update=update)

    # memo_agent: versioned, 7 hourly windows of gate traffic (drift), 200 limit decisions
    # split evenly by gender (fairness), 12 memo texts (quality), two payments of two callers.
    for h in range(7):
        for i in range(8):
            ts = T0 + timedelta(hours=h, minutes=5 * i + 1)
            out.append(ev(ts, "memo_agent", "gate_decision", tool="read_facility", version="2.0.0",
                          latency_ms=1))  # fmt: skip
            out.append(ev(ts, "memo_agent", "llm_call", version="2.0.0", latency_ms=500 + 10 * i))
    for i in range(200):
        out.append(
            ev(
                T0 + timedelta(seconds=40 * i),
                "memo_agent",
                "tool_call",
                tool="decide_limit",
                version="2.0.0",
                args={
                    "case_id": f"CASE-{i:04d}",
                    "outcome": "granted" if i % 3 else "declined",
                    "applicant_gender": "female" if i % 2 else "male",
                },
            )
        )
    for i in range(12):
        out.append(
            ev(
                T0 + timedelta(minutes=7 * i),
                "memo_agent",
                "tool_call",
                tool="compose_memo",
                version="2.0.0",
                args={"body": f"Draft memo {i}: facility reviewed, DSCR within policy."},
            )
        )
    keys = {
        "payer_id": key_hash("payer_id", "PAYER-0001"),
        "beneficiary_id": key_hash("beneficiary_id", "BENEF-0001"),
    }
    for i, (amount, caller) in enumerate([(60_000_000, "helpdesk"), (55_000_000, "lookup_agent")]):
        out.append(
            ev(
                T0 + timedelta(minutes=10 * i + 2),
                "memo_agent",
                "gate_decision",
                tool="release_funds",
                version="2.0.0",
                amount=amount,
                caller=caller,
                keys=keys,
            )
        )
    # helpdesk: replies only, no version on the events
    for i in range(10):
        out.append(
            ev(
                T0 + timedelta(minutes=9 * i),
                "helpdesk",
                "tool_call",
                tool="reply",
                args={"text": f"Your ticket {i} is resolved."},
            )
        )
    # lookup_agent: read-only lookups, no version
    for i in range(10):
        out.append(
            ev(T0 + timedelta(minutes=11 * i), "lookup_agent", "tool_call", tool="lookup_account")
        )
    return out


class _Sink:
    """EvidenceSink for the harness: keeps entries, refuses floats like the real chain."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def record(self, record_type: str, record_ref: str, payload: Any) -> str:
        from supervisor.core.canonical import canonical_json, sha256_hex

        canonical_json(payload)
        self.entries.append((record_type, record_ref))
        return sha256_hex({"t": record_type, "r": record_ref})


def run_fixture(root: Path, *, legacy: bool = False) -> dict[str, dict[str, dict[str, Any]]]:
    """Run the four monitors on the fixture; returns {agent: {monitor: status entry}}.

    ``legacy=True`` runs them without the resolver (the behaviour before WP1b-B): the result
    is empty, which is the silence that defect D06 describes."""
    from supervisor.adapters.clock import FixedClock
    from supervisor.adapters.factory import build_adapters
    from supervisor.adapters.llm.mock import MockChat
    from supervisor.config import load_settings
    from supervisor.jobs import bootstrap_schema
    from supervisor.monitors.bindings import BindingResolver
    from supervisor.monitors.common import MonitorContext
    from supervisor.monitors.drift import DriftConfig, DriftMonitor
    from supervisor.monitors.fairness import FairnessConfig, FairnessMonitor, build_source
    from supervisor.monitors.multiagent import MultiAgentMonitor, SplitPaymentConfig
    from supervisor.monitors.quality import QualityScorer
    from supervisor.monitors.status import read_status
    from supervisor.monitors.sweeps import QualitySweep

    policies, manifests = write_fixture(root / "fixture")
    resolver = (
        None if legacy else BindingResolver(manifest_roots=[manifests], policy_dirs=[policies])
    )
    settings = load_settings(sql_backend="sqlite", data_dir=root / "data")
    clock = FixedClock(NOW)
    adapters = build_adapters(settings, clock=clock)
    try:
        bootstrap_schema.run(settings, adapters)
        adapters.tables.append("agent_event", [e.row() for e in build_events()])
        ctx = MonitorContext.from_adapters(adapters, _Sink())
        scorer = QualityScorer(
            MockChat(seed=3, model_id="mock-quality-harness"),
            clock,
            tables=adapters.tables,
            evidence=ctx.evidence,
            sample_bp=10000,
        )
        QualitySweep(ctx, scorer, settle_s=60, resolver=resolver, sample_bp=10000).run(NOW)
        cfg = FairnessConfig(agents=[], attribute_source="none")
        source = build_source(ctx, cfg, b"harness-key", allow_arg_attributes=True)
        if source is None:
            raise RuntimeError("fairness source was not built")
        FairnessMonitor(ctx, cfg, source, method="python", resolver=resolver).run(NOW)
        DriftMonitor(ctx, DriftConfig(), resolver).run(NOW)
        MultiAgentMonitor(ctx, SplitPaymentConfig(), resolver).run(NOW)
        return {
            a: read_status(ctx, NOW.date(), a) for a in ("memo_agent", "helpdesk", "lookup_agent")
        }
    finally:
        adapters.close()


def compare(
    got: dict[str, dict[str, dict[str, Any]]], golden: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows of (agent, monitor, expected, got) and the list of mismatches."""
    rows, bad = [], []
    for agent, monitors in golden["expected"].items():
        for monitor, want in monitors.items():
            have = got.get(agent, {}).get(monitor, {})
            ok = have.get("status") == want["status"] and have.get("code", "") == want.get(
                "code", ""
            )
            rows.append({"agent": agent, "monitor": monitor, "want": want, "got": have, "ok": ok})
            if not ok:
                bad.append(f"{agent}/{monitor}: want {want}, got {have}")
    return rows, bad


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.monitors.binding_harness")
    ap.add_argument("--expected", type=Path, default=GOLDEN, help="golden statuses (JSON)")
    ap.add_argument("--json", action="store_true", help="print the result rows as JSON")
    ap.add_argument("--keep", type=Path, default=None, help="work folder (default: a temp dir)")
    args = ap.parse_args(argv)
    golden = json.loads(args.expected.read_text(encoding="utf-8"))
    if args.keep is not None:
        args.keep.mkdir(parents=True, exist_ok=True)
        got = run_fixture(args.keep)
    else:
        with tempfile.TemporaryDirectory(prefix="sv-bindings-") as tmp:
            got = run_fixture(Path(tmp))
    rows, bad = compare(got, golden)
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=True))  # noqa: T201
    else:
        for r in rows:
            tag = "[OK]" if r["ok"] else "[FAIL]"
            got = r["got"]
            line = (
                f"{tag} {r['agent']:13s} {r['monitor']:10s} {got.get('status', '-')} "
                f"{got.get('code', '')} {got.get('reason', '')}"
            )
            print(line.rstrip().encode("ascii", "replace").decode())  # noqa: T201
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
