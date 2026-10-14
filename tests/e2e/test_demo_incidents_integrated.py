"""M1 "it blocks", end to end: three WP2 agents behind the real WP3 gateway, evidence on
the real WP6 chain, offline verification of the export, and a tamper that the verifier
catches. Fresh SQLite, no network, MockChat only (no setup or onboarding step needed).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.llm.mock import MockChat
from supervisor.config import load_settings
from supervisor.core.canonical import canonical_json
from supervisor.demo import replay as R
from supervisor.evidence.export import export_chain
from supervisor.evidence.verify import verify_export
from supervisor.gateway.policy import load_deployed, load_policy_dir
from supervisor.jobs import bootstrap_schema
from supervisor.wiring import POLICY_DIR

EXPECTED = {
    "DEMO-1": ("PAY-07", "pause"),
    "DEMO-2": ("SVC-02", "block"),
    "DEMO-3": ("CRD-01", "block"),
    "DEMO-4": ("PAY-08", "block"),
}


class _NoNetwork(Exception):
    pass


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> None:
        raise _NoNetwork("network access attempted during the demo replay")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def chats(monkeypatch: pytest.MonkeyPatch) -> list[MockChat]:
    made: list[MockChat] = []

    class Recording(MockChat):
        def __init__(self, *a: Any, **k: Any) -> None:
            super().__init__(*a, **k)
            made.append(self)

    monkeypatch.setattr(R, "MockChat", Recording)
    return made


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="")
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def report(adapters: Adapters, no_network: None, chats: list[MockChat]) -> R.GatedReport:
    rep = R.run_gated(adapters.settings, adapters=adapters)
    assert chats and all(c.is_mock for c in chats)
    return rep


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def _payloads(a: Adapters, record_type: str) -> list[dict[str, Any]]:
    out = []
    for e in a.tables.query("chain_entry", {"record_type": record_type}, ["lane", "seq"]):
        p = a.tables.query("chain_payload", {"lane": e["lane"], "seq": e["seq"]})
        out.append(json.loads(p[0]["payload"]))
    return out


def test_all_four_incidents_stopped_by_real_rules(
    report: R.GatedReport, adapters: Adapters
) -> None:
    assert report.ok, "\n".join(report.lines)
    by_id = {r.incident_id: r for r in report.results}
    assert sorted(by_id) == sorted(EXPECTED)
    for inc_id, (rule, action) in EXPECTED.items():
        r = by_id[inc_id]
        assert r.attack_stopped and r.first_stop == (rule, action), inc_id
        assert r.stop_fail_mode is None, inc_id  # rule match, not a fail-closed error
        assert f"[OK] {inc_id} STOPPED by {rule} action={action}" in report.lines
        assert report.expected[inc_id] == action  # the incident file agrees
    # harm actually prevented (DEMO-2: two waivers before the third is blocked;
    # DEMO-4: the first 60m part executes, the second is blocked)
    assert by_id["DEMO-1"].harmful_effects_recorded == 0
    assert by_id["DEMO-2"].harmful_effects_recorded == 2
    assert by_id["DEMO-3"].harmful_effects_recorded == 0
    assert by_id["DEMO-4"].harmful_effects_recorded == 1
    assert all(line.isascii() for line in report.lines)
    assert report.chain_head and len(report.chain_head) == 64


def test_tier0_verdicts_registry_and_policy(report: R.GatedReport, adapters: Adapters) -> None:
    a = adapters
    for rule, action in EXPECTED.values():
        rows = a.tables.query("verdict", {"rule_id": rule, "action": action})
        assert rows, rule
        assert all(v["tier"] == 0 and not v["advisory"] and not v["is_mock"] for v in rows)
    policy = load_deployed(a.state)  # deployed to the rule table and read back
    assert policy.policy_hash == load_policy_dir(POLICY_DIR).policy_hash
    for agent_id in R.AGENT_IDS:
        row = a.state.get("agent", {"agent_id": agent_id})
        assert row is not None and row["gate_state"] == "RUNNING"  # resumed by two people
        assert a.tables.query("agent_version", {"agent_id": agent_id, "version": "1.0.0"})
    resumes = [p for p in _payloads(a, "gate_state_change") if p["event"] == "resume"]
    assert len(resumes) == 1 and resumes[0]["agent_id"] == "payments"
    assert resumes[0]["approver_1"] != resumes[0]["approver_2"]


def test_handoffs_record_caller_in_gate_evidence(report: R.GatedReport, adapters: Adapters) -> None:
    decisions = _payloads(adapters, "gate_decision")
    transfers = [d for d in decisions if d["tool_name"] == "transfer"]
    assert [d["caller_agent_id"] for d in transfers] == ["customer_service", "credit_prequal"]
    assert [d["allow"] for d in transfers] == [True, False]
    assert all(d["args_hmac_key_id"] == "dev" and len(d["args_hmac"]) == 64 for d in decisions)
    # every stop is a genuine rule match, never a rule error that failed closed
    stops = [d for d in decisions if d["rule_id"] in {rule for rule, _ in EXPECTED.values()}]
    assert {d["rule_id"] for d in stops if not d["allow"]} == {r for r, _ in EXPECTED.values()}
    assert all(d["fail_mode"] is None for d in decisions)
    ext = [d for d in decisions if d["tool_name"] == "ext_transfer_api"]
    assert ext[0]["caller_agent_id"] == "customer_service"
    direct = [d for d in decisions if d["agent_id"] == "credit_prequal"]
    assert direct and all(d["caller_agent_id"] is None for d in direct)
    events = adapters.tables.query("agent_event", {"event_type": "gate_decision"})
    assert {e["caller_agent_id"] for e in events if e["tool_name"] == "transfer"} == {
        "customer_service",
        "credit_prequal",
    }


def test_chain_export_verifies_and_tamper_fails(
    report: R.GatedReport, adapters: Adapters, tmp_path: Path
) -> None:
    out = tmp_path / "export"
    export_chain(adapters.tables, out)
    ok = verify_export(out, strict=True)
    assert ok.failures == 0, "\n".join(ok.lines)
    entries = _lines(out / "entries.jsonl")
    root_heads = [e for e in entries if e["lane"] == "root"]
    assert root_heads[-1]["entry_hash"] == report.chain_head

    # Tamper: rewrite the DEMO-4 block decision into an allow, and fix the manifest.
    bad = tmp_path / "tampered"
    shutil.copytree(out, bad)
    rows = _lines(bad / "payloads.jsonl")
    hit = 0
    for r in rows:
        payload = json.loads(r["payload"])
        if payload.get("rule_id") == "PAY-08" and payload.get("allow") is False:
            payload["allow"] = True
            payload["action"] = "allow"
            r["payload"] = canonical_json(payload)
            hit += 1
    assert hit == 1
    (bad / "payloads.jsonl").write_text(
        "".join(canonical_json(r) + "\n" for r in rows), encoding="utf-8"
    )
    m = json.loads((bad / "manifest.json").read_text(encoding="utf-8"))
    for name in m["files"]:
        m["files"][name]["sha256"] = hashlib.sha256((bad / name).read_bytes()).hexdigest()
    (bad / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    broken = verify_export(bad, strict=True)
    assert broken.failures > 0
    text = "\n".join(broken.lines)
    assert "[FAIL] lane agent:payments" in text and "payload" in text


def test_replay_opens_cases_without_the_console(report: R.GatedReport, adapters: Adapters) -> None:
    line = next(x for x in report.lines if x.startswith("[OK] cases opened: "))
    assert line == "[OK] cases opened: 4"  # DEMO-1..4, ints only
    assert len(adapters.tables.query("cases", {})) == 4
