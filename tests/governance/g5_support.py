"""WP-G5 test support: a store on a fixed clock, row builders for every event source, and a
runner wired like the job wires it (services on the same store, an in-memory evidence sink)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.notify import InboxNotifier
from supervisor.config import load_settings
from supervisor.controls.service import ControlService, map_id
from supervisor.governance.actions import ActionRunner
from supervisor.governance.actions_model import Rule, load_rules, parse_rules
from supervisor.governance.incidents import IncidentService
from supervisor.governance.lifecycle import LifecycleService
from supervisor.governance.reviews import ReviewService
from supervisor.governance.systems import SystemService
from supervisor.jobs import bootstrap_schema
from supervisor.monitors.common import MonitorContext

from .conftest import ListSink, add_agent, draft

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
STARTER = Path(__file__).resolve().parents[2] / "config" / "governance_actions.yaml"


def ago(seconds: int) -> datetime:
    return NOW - timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def store(tmp_path: Path, clock: FixedClock) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        governance_enabled=True,
        governance_actions_enabled=True,
        controls_enabled=True,
        webhooks_enabled=False,
    )
    a = build_adapters(settings, clock=clock)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


class Rig:
    """Everything a test needs: the store, the sink, the services and a runner factory."""

    def __init__(self, a: Adapters, sink: ListSink) -> None:
        self.a = a
        self.sink = sink
        self.ctx = MonitorContext.from_adapters(a, sink)
        self.systems = SystemService.from_adapters(a, evidence=sink)
        self.lifecycle = LifecycleService(self.systems)
        self.reviews = ReviewService(self.systems)
        self.incidents = IncidentService(a.state, a.clock, a.settings, evidence=sink)
        self.controls = ControlService(a.state, a.tables, a.clock, a.settings, evidence=sink)

    def runner(
        self,
        rules: list[Rule] | str | Path | None = None,
        *,
        sources: dict[str, Any] | None = None,
        controls: bool = True,
    ) -> ActionRunner:
        if rules is None:
            rules = load_rules(STARTER)
        elif isinstance(rules, (str, Path)):
            rules = load_rules(rules)
        return ActionRunner(
            self.ctx,
            self.a.settings,
            rules,
            systems=self.systems,
            lifecycle=self.lifecycle,
            reviews=self.reviews,
            incidents=self.incidents,
            notifier=InboxNotifier(self.a.state, self.a.clock),
            controls=self.controls if controls else None,
            sources=sources,
        )

    # ---------------------------------------------------------------- builders
    def system(
        self, name: str = "Payments - Assistant", agent: str | None = "agent-a", **over: Any
    ):
        row = self.systems.register(draft(name=name, **over), "owner.lan")
        sid = row["system_id"]
        if agent:
            if not self.a.state.get("agent", {"agent_id": agent}):
                add_agent(self.a, agent)
            self.systems.link(sid, "agent", agent, "owner.lan")
        return self.systems.get(sid)

    def stage(self, sid: str, stage: str) -> None:
        """Put a system in a stage (a test setup; the real move needs the approvals)."""
        row = self.a.state.get("ai_system", {"system_id": sid})
        assert row is not None
        self.a.state.update(
            "ai_system", {"system_id": sid}, {"lifecycle_stage": stage}, row["row_version"]
        )

    def team(self, sid: str, user: str, role: str) -> None:
        self.systems.add_member(sid, user, role, "owner.lan")

    def alert(
        self,
        alert_id: str = "al_1",
        rule_id: str = "AL-SECRETS-OUTPUT",
        severity: str = "critical",
        agent_id: str | None = "agent-a",
        ts: datetime | None = None,
        case_id: str | None = None,
    ) -> None:
        ts = ts or ago(60)
        self.a.state.insert(
            "alert",
            {
                "alert_id": alert_id,
                "ts": ts,
                "dedupe_key": f"{rule_id}:{agent_id}",
                "rule_id": rule_id,
                "rule_hash": "h" * 16,
                "severity": severity,
                "status": "open",
                "title": "t",
                "agent_id": agent_id,
                "group_value": None,
                "window_s": 60,
                "window_count": 1,
                "threshold": 1,
                "first_ts": ts,
                "last_ts": ts,
                "suppressed_count": 0,
                "case_id": case_id,
                "refs": [],
                "routes": [],
                "route_status": {},
            },
        )

    def case(
        self,
        case_id: str,
        case_type: str,
        severity: str = "medium",
        agent_id: str = "agent-a",
        ts: datetime | None = None,
    ) -> None:
        self.a.state.insert(
            "cases",
            {
                "case_id": case_id,
                "agent_id": agent_id,
                "severity": severity,
                "status": "open",
                "opened_at": ts or ago(60),
                "regulation_refs": [],
                "summary": "s",
                "case_type": case_type,
            },
        )

    def event_row(self, event_id: str, tool: str, agent_id: str = "agent-a") -> None:
        self.a.tables.append(
            "agent_event",
            [
                {
                    "event_id": event_id,
                    "ts": ago(61),
                    "trace_id": "tr",
                    "span_id": "sp",
                    "agent_id": agent_id,
                    "event_type": "gate_decision",
                    "tool_name": tool,
                    "env": "dev",
                    "source": "gate",
                    "capture_level": "full",
                }
            ],
        )

    def verdict(
        self,
        verdict_id: str,
        event_id: str | None,
        action: str = "block",
        agent_id: str = "agent-a",
        rule_id: str = "R-LIMIT",
        label: str = "block",
        tier: int = 0,
        checker_id: str = "gate:rules",
        ts: datetime | None = None,
    ) -> None:
        self.a.tables.append(
            "verdict",
            [
                {
                    "verdict_id": verdict_id,
                    "ts": ts or ago(60),
                    "event_id": event_id,
                    "agent_id": agent_id,
                    "tier": tier,
                    "checker_id": checker_id,
                    "is_mock": False,
                    "advisory": False,
                    "label": label,
                    "action": action,
                    "rule_id": rule_id,
                }
            ],
        )

    def finding(self, finding_id: str, reason: str | None, agent_id: str = "agent-a") -> None:
        self.a.tables.append(
            "finding",
            [
                {
                    "finding_id": finding_id,
                    "ts": ago(60),
                    "event_id": "e1",
                    "request_id": "r1",
                    "correlation_id": "c1",
                    "agent_id": agent_id,
                    "tool_name": "t",
                    "direction": "input",
                    "detector_slug": "pii",
                    "detector_id": "pii@1",
                    "code": "pii.x",
                    "score_bp": 0,
                    "threshold_bp": 5000,
                    "masked_count": 0,
                    "action_hint": "report",
                    "not_executed_reason": reason,
                    "is_mock": False,
                    "verdict_status": "allow",
                }
            ],
        )

    def eval_result(
        self,
        pack_id: str = "counterfactual_vi",
        status: str = "fail",
        gate: str = "required",
        target_id: str = "agent-a",
        run_id: str = "run1",
        is_mock: bool = False,
    ) -> None:
        self.a.tables.append(
            "eval_result",
            [
                {
                    "run_id": run_id,
                    "ts": ago(60),
                    "pack_id": pack_id,
                    "pack_version": 1,
                    "manifest_sha256": "m",
                    "dimension": "bias_fairness",
                    "target_kind": "agent",
                    "target_id": target_id,
                    "status": status,
                    "metrics": {},
                    "metric_status": {},
                    "thresholds": {},
                    "reasons": "",
                    "n_items": 1,
                    "data_mode": "synthetic",
                    "dataset_id": "d",
                    "dataset_sha256": "s",
                    "is_mock": is_mock,
                    "launch_gate": gate,
                    "judge_gate": False,
                    "details": {},
                }
            ],
        )

    def chain_verify(self, ok: bool, seq: int = 1) -> None:
        self.a.tables.append(
            "chain_entry",
            [
                {
                    "lane": "root",
                    "seq": seq,
                    "ts": ago(60),
                    "record_type": "chain_verify",
                    "record_ref": "verify",
                    "payload_hash": f"ph{seq}",
                    "prev_hash": "0" * 64,
                    "entry_hash": f"eh{seq}",
                    "writer": "w",
                    "env": "dev",
                }
            ],
        )
        self.a.tables.append(
            "chain_payload",
            [
                {
                    "lane": "root",
                    "seq": seq,
                    "payload_hash": f"ph{seq}",
                    "payload": json.dumps({"ok": ok, "failures": 0 if ok else 1}),
                }
            ],
        )

    def version(
        self, agent_id: str, version: str, endpoint: str, family: str, at: datetime
    ) -> None:
        self.a.tables.append(
            "agent_version",
            [
                {
                    "agent_id": agent_id,
                    "version": version,
                    "model_endpoint": endpoint,
                    "model_family": family,
                    "deployed_at": at,
                }
            ],
        )

    def control(
        self,
        control_id: str = "CTL-PII",
        kind: str = "pack",
        target: str = "counterfactual_vi",
        status: str = "active",
    ) -> None:
        """A control and one map entry, written straight to the tables (setup, no validation)."""
        self.a.state.insert(
            "control",
            {
                "control_id": control_id,
                "title": "A control",
                "objective": "o",
                "control_type": "detective",
                "implemented_by": "product",
                "owner": "risk.lead",
                "status": status,
                "review_date": None,
                "scope_agents": json.dumps(["*"]),
                "source": "manual",
                "created_at": NOW,
                "created_by": "owner.lan",
            },
        )
        self.a.state.insert(
            "control_map",
            {
                "map_id": map_id(control_id, kind, target),
                "control_id": control_id,
                "kind": kind,
                "target": target,
                "active": True,
                "created_at": NOW,
                "created_by": "owner.lan",
            },
        )


@pytest.fixture
def rig(store: Adapters) -> Rig:
    return Rig(store, ListSink())


def only(rules_doc: list[dict[str, Any]]) -> list[Rule]:
    return parse_rules({"version": 1, "rules": rules_doc})


def rule(
    kind: str, actions: list[str], *, rid: str = "T-1", min_severity: str = "low", **over: Any
) -> dict[str, Any]:
    return {"id": rid, "kind": kind, "min_severity": min_severity, "actions": actions, **over}
