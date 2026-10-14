from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from supervisor.adapters.factory import build_adapters
from supervisor.adapters.llm import jsonschema_lite
from supervisor.config import load_settings
from supervisor.demo import replay as R
from supervisor.jobs import bootstrap_schema
from supervisor_agents.common.manifest import load_manifest
from supervisor_agents.common.runtime import ACTION_SCHEMA
from tests.conftest import REPO_ROOT

RT = REPO_ROOT / "agents" / "redteam"


def _cases() -> list[dict[str, Any]]:
    lines = (RT / "incidents.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines if x.strip()]


def _walk_floats(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_walk_floats(v) for v in value.values())
    if isinstance(value, list):
        return any(_walk_floats(v) for v in value)
    return False


def test_attack_set_validates_against_schema() -> None:
    schema = json.loads((RT / "schema.json").read_text(encoding="utf-8"))
    cases = _cases()
    problems = {c.get("id", i): jsonschema_lite.errors(c, schema) for i, c in enumerate(cases)}
    assert {k: v for k, v in problems.items() if v} == {}
    assert len({c["id"] for c in cases}) == len(cases)
    assert not any(_walk_floats(c) for c in cases)


def test_attack_set_quotas() -> None:
    cases = _cases()
    n = len(cases)
    assert n >= 120
    vi = sum(c["language"] == "vi" for c in cases)
    benign = [c for c in cases if c["expected_detection"] == "none-benign"]
    assert vi / n >= 0.40, f"vi share {vi}/{n}"
    assert len(benign) / n >= 0.25, f"benign share {len(benign)}/{n}"
    for c in benign:
        assert c["vector"] == "benign" and c["severity"] == "none"
    for c in cases:
        if c["expected_detection"] != "none-benign":
            assert c["vector"] != "benign" and c["severity"] != "none", c["id"]
    assert {c["agent"] for c in cases} >= {
        "customer_service",
        "credit_prequal",
        "payments",
        "multi",
    }
    assert {c["expected_detection"] for c in cases} == {"rule", "judge", "drift", "none-benign"}


def test_planned_tool_calls_use_known_tools_or_are_unapproved_tool_cases() -> None:
    manifests = {a: load_manifest(a) for a in ("customer_service", "credit_prequal", "payments")}
    for c in _cases():
        for call in c["input"].get("planned_tool_calls", []):
            if call["tool"] not in manifests[call["agent"]].tool_names:
                assert c["vector"] in (
                    "unapproved_tool",
                    "tool_misuse",
                    "privilege_escalation",
                    "data_exfil",
                ), c["id"]


# ----------------------------------------------------------------------- demo replay


def test_demo_incidents_file_has_four_incidents_with_valid_scripts() -> None:
    incidents = R.load_demo_incidents()
    assert [i["id"] for i in incidents] == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"]
    for inc in incidents:
        assert any(s.get("attack_step") for s in inc["steps"])
        for step in inc["steps"]:
            for entry in step["script"]:
                assert jsonschema_lite.is_valid(entry, ACTION_SCHEMA), (inc["id"], entry)
    callers = {s.get("caller_agent_id") for s in incidents[3]["steps"]}
    assert len(callers) == 2  # split payment spans two calling agents


def test_replay_without_gate_executes_the_harm() -> None:
    results = R.replay()
    assert len(results) == 4
    for r in results:
        assert not r.attack_stopped
        assert r.harmful_effects_recorded > 0, r.incident_id


class _StubGate:
    """Stand-in for the WP3 gateway: blocks the harmful calls of the four incidents."""

    def __init__(self) -> None:
        self.paid: dict[str, int] = {}

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        ok = {"allow": True, "action": "allow", "rule_id": None, "reason": "", "latency_ms": 0}
        if tool_name == "ext_transfer_api":
            return {
                "allow": False,
                "action": "pause",
                "rule_id": "STUB-1",
                "reason": "",
                "latency_ms": 0,
            }
        if tool_name == "waive_fee":
            n = self.paid.get("waivers", 0) + 1
            self.paid["waivers"] = n
            if n > 1:
                return {
                    "allow": False,
                    "action": "block",
                    "rule_id": "STUB-2",
                    "reason": "",
                    "latency_ms": 0,
                }
        if tool_name == "decide_prequal" and args.get("application_id") == "APP-00003":
            return {
                "allow": False,
                "action": "block",
                "rule_id": "STUB-3",
                "reason": "",
                "latency_ms": 0,
            }
        if tool_name == "transfer":
            key = f"{args.get('from_account_id')}->{args.get('payee_id')}"
            total = self.paid.get(key, 0) + int(args.get("amount_minor", 0))
            if total > 100_000_000:
                return {
                    "allow": False,
                    "action": "block",
                    "rule_id": "STUB-4",
                    "reason": "",
                    "latency_ms": 0,
                }
            self.paid[key] = total
        return ok


def test_replay_with_a_gate_stops_each_attack_and_writes_events(tmp_path: Path) -> None:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        results = R.replay(gate=_StubGate(), store=a.tables)
        for r in results:
            assert r.attack_stopped, r.incident_id
        by_id = {r.incident_id: r for r in results}
        assert by_id["DEMO-1"].harmful_effects_recorded == 0
        assert by_id["DEMO-3"].harmful_effects_recorded == 0
        assert by_id["DEMO-1"].steps[-1].run.status == "paused"
        rows = a.tables.query("agent_event", where={"agent_id": "payments"})
        statuses = {r["status"] for r in rows if r["event_type"] == "tool_call"}
        assert {"blocked", "paused"} <= statuses
        assert any(r["caller_agent_id"] == "credit_prequal" for r in rows)
    finally:
        a.close()
