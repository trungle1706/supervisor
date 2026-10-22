"""WP-G6 library tools (read only) and supervisor tools (gate state, decisions, findings, chain,
packs) with the visibility of the console."""

from __future__ import annotations

import uuid
from typing import Any

from .conftest import Rig

# ------------------------------------------------------------------------ library


def test_regulations_and_obligations(rig: Rig) -> None:
    cred = rig.new_app("lib", scopes=("library.read",), roles=("viewer",))
    regs = rig.ok(cred, "regulations")
    assert regs["count"] >= 20 and "Not legal advice" in regs["disclaimer"]
    ids = {i["instrument_id"] for i in regs["items"]}
    assert any(i.startswith("VN-") for i in ids)
    vn = rig.ok(cred, "regulations", {"jurisdiction": "VN"})
    assert 0 < vn["count"] < regs["count"] and all(i["jurisdiction"] == "VN" for i in vn["items"])
    found = rig.ok(cred, "obligations", {"query": "model risk", "limit": 3})
    assert found["count"] >= 1 and len(found["items"]) <= 3
    assert all(
        "model" in (i["summary_en"] + i["article_ref"] + " ".join(i["duties"])).lower()
        or "risk" in i["summary_en"].lower()
        for i in found["items"]
    )
    one = rig.ok(cred, "obligations", {"instrument_id": found["items"][0]["instrument_id"]})
    assert one["count"] >= 1
    assert rig.ok(cred, "obligations", {"query": "zzzzqqqq"})["count"] == 0


def test_starters_guardians_and_rules(rig: Rig) -> None:
    cred = rig.new_app("lib", scopes=("library.read",), roles=("viewer",))
    risks = rig.ok(cred, "starter_risks", {"limit": 5})
    assert risks["count"] >= 10 and len(risks["items"]) == 5
    assert risks["items"][0]["id"].startswith("RSK-") and "title" in risks["items"][0]
    controls = rig.ok(cred, "starter_controls")
    assert any(c["id"] == "CTL-PII-MASK" for c in controls["items"])
    guard = rig.ok(cred, "guardian_catalog")
    assert {"dlp_vn", "injection_regex"} <= {g["slug"] for g in guard["items"]}
    rules = rig.ok(cred, "assignment_rules")
    assert rules["items"][0]["id"] == "AR-BASELINE" and "assign" in rules["items"][0]


def test_the_library_does_not_depend_on_the_systems_flag(rig: Rig) -> None:
    rig.ctx.settings.governance_enabled = False
    cred = rig.new_app("lib", scopes=("library.read",), roles=("viewer",))
    assert rig.ok(cred, "regulations")["count"] > 0


def test_there_is_no_way_to_write_the_library(rig: Rig) -> None:
    cred = rig.new_app("lib", scopes=("library.read", "governance.write"))
    listed = {t["name"] for t in rig.rpc(cred, "tools/list").json()["result"]["tools"]}
    assert not {n for n in listed if n.startswith(("add_", "update_", "delete_", "import_"))}
    for name in ("regulations", "starter_risks", "guardian_catalog"):
        assert rig.err(cred, name, {"confirm": True})["code"] == -32602  # no confirm, no write


# ------------------------------------------------------------------------ supervisor


def add_event(rig: Rig, agent: str, *, tool: str = "transfer", args: str = "ARGS-MASKED") -> str:
    eid = uuid.uuid4().hex
    rig.ctx.tables.append(
        "agent_event",
        [
            {
                "event_id": eid,
                "ts": rig.ctx.clock.now(),
                "trace_id": "t-" + eid[:8],
                "span_id": "s-" + eid[:8],
                "agent_id": agent,
                "event_type": "gate_decision",
                "tool_name": tool,
                "args_masked": args,
                "result_masked": "RESULT-MASKED",
                "status": "denied",
                "env": "test",
                "source": "gate",
                "capture_level": "full",
            }
        ],
    )
    rig.ctx.tables.append(
        "verdict",
        [
            {
                "verdict_id": uuid.uuid4().hex,
                "ts": rig.ctx.clock.now(),
                "trace_id": "t-" + eid[:8],
                "event_id": eid,
                "agent_id": agent,
                "tier": 0,
                "checker_id": "gate.tier0a",
                "is_mock": False,
                "advisory": False,
                "label": "matched",
                "action": "block",
                "rule_id": "TEST-01",
                "rationale_masked": "rule TEST-01 matched [PERSON_1]",
            }
        ],
    )
    return eid


def test_an_app_sees_an_agent_only_when_a_person_with_its_roles_would(rig: Rig) -> None:
    boss = rig.new_app("boss", roles=("reviewer",))
    viewer = rig.new_app("viewer app", scopes=("supervisor.read",), roles=("viewer",))
    assert rig.ok(boss, "gate_state", {"agent_id": "payments"})["state"] == "RUNNING"
    for name in ("gate_state", "decisions", "findings", "pack_results", "chain_verify"):
        err = rig.err(viewer, name, {"agent_id": "payments"})
        assert err["code"] in (-32004, -32003), (name, err)
    err = rig.err(boss, "gate_state", {"agent_id": "no-such-agent"})
    assert err["code"] == -32004 and "does not exist" in err["message"]
    # the viewer joins a system that holds the agent
    sid = rig.ok(boss, "register_system", {"draft": _draft(), "confirm": True})["system_id"]
    rig.ok(
        boss,
        "link_component",
        {"system_id": sid, "ref_kind": "agent", "ref_id": "payments", "confirm": True},
    )
    rig.ctx.systems.add_member(sid, f"mcp:{viewer.app_id}", "technical_specialist", "reviewer.an")
    assert rig.ok(viewer, "gate_state", {"agent_id": "PAYMENTS"})["agent_id"] == "payments"
    assert rig.err(viewer, "gate_state", {"agent_id": "customer_service"})["code"] == -32004


def _draft() -> dict[str, Any]:
    return {
        "name": "Pay assist",
        "owner_user": "reviewer.an",
        "owner_team": "Payments Ops",
        "purpose": "x",
        "system_type": "assistant",
        "org_role": "deployer",
        "user_segment": "internal",
        "personal_data": "none",
        "human_control": "post_review",
    }


def test_decisions_carry_the_rule_and_the_masked_rationale_only(rig: Rig) -> None:
    cred = rig.new_app()
    eid = add_event(rig, "payments", args="SECRET-ARGS-123")
    out = rig.ok(cred, "decisions", {"agent_id": "payments", "limit": 200})
    mine = next(i for i in out["items"] if i["event_id"] == eid)
    assert mine["outcome"] == "blocked" and mine["rule_id"] == "TEST-01"
    assert mine["rationale_masked"] == "rule TEST-01 matched [PERSON_1]"
    text = str(out)
    assert "SECRET-ARGS-123" not in text and "RESULT-MASKED" not in text
    assert "args_masked" not in text and "result_masked" not in text


def test_decisions_since_and_limit(rig: Rig) -> None:
    cred = rig.new_app()
    add_event(rig, "payments")
    assert (
        rig.ok(cred, "decisions", {"agent_id": "payments", "since": "2999-01-01T00:00:00Z"})[
            "count"
        ]
        == 0
    )
    assert (
        rig.ok(cred, "decisions", {"agent_id": "payments", "since": "2000-01-01T00:00:00Z"})[
            "count"
        ]
        >= 1
    )
    assert rig.ok(cred, "decisions", {"agent_id": "payments", "limit": 1})["count"] == 1
    err = rig.err(cred, "decisions", {"agent_id": "payments", "since": "yesterday"})
    assert err["code"] == -32602 and "RFC 3339" in err["message"]


def test_findings_are_the_masked_rows(rig: Rig) -> None:
    cred = rig.new_app()
    eid = add_event(rig, "payments")
    rig.ctx.tables.append(
        "finding",
        [
            {
                "finding_id": uuid.uuid4().hex,
                "ts": rig.ctx.clock.now(),
                "event_id": eid,
                "request_id": "r1",
                "correlation_id": "c1",
                "agent_id": "payments",
                "tool_name": "transfer",
                "direction": "input",
                "detector_slug": "dlp_vn",
                "detector_id": "dlp_vn@1",
                "code": "PII-PHONE",
                "score_bp": 9000,
                "threshold_bp": 5000,
                "masked_count": 1,
                "action_hint": "transform",
                "is_mock": False,
                "verdict_status": "transform",
                "entities_masked": ["[PHONE_1]"],
                "fragments_masked": ["call [PHONE_1] now"],
            }
        ],
    )
    out = rig.ok(cred, "findings", {"agent_id": "payments"})
    assert out["count"] == 1
    f = out["items"][0]
    assert f["code"] == "PII-PHONE" and f["score_bp"] == 9000 and f["fragments_masked"]
    assert isinstance(f["score_bp"], int)


def test_chain_verify_needs_the_role_and_gives_no_server_path(rig: Rig) -> None:
    cred = rig.new_app()
    out = rig.ok(cred, "chain_verify", {"agent_id": "payments"})
    assert out["ok"] is True and out["failures"] == 0 and out["lane"] == "agent:payments"
    assert out["last_lines"] and all(line.startswith("[") for line in out["last_lines"])
    assert "/tmp" not in str(out) and "export" not in out["last_lines"][0].lower()[:12]
    viewer = rig.new_app("viewer app", scopes=("supervisor.read",), roles=("viewer",))
    assert rig.err(viewer, "chain_verify", {"agent_id": "payments"})["code"] == -32003


def test_pack_results_label_mock_runs(rig: Rig) -> None:
    cred = rig.new_app()
    assert rig.ok(cred, "pack_results", {"agent_id": "payments"})["count"] == 0
    for mock, status in ((True, "ok"), (False, "warn")):
        rig.ctx.tables.append(
            "eval_result",
            [
                {
                    "run_id": uuid.uuid4().hex,
                    "ts": rig.ctx.clock.now(),
                    "pack_id": "owasp_agentic_redteam",
                    "pack_version": 1,
                    "manifest_sha256": "0" * 64,
                    "dimension": "security",
                    "target_kind": "agent",
                    "target_id": "payments",
                    "status": status,
                    "metrics": {"asr_bp": 1200},
                    "metric_status": {"asr_bp": status},
                    "thresholds": {},
                    "reasons": "",
                    "n_items": 40,
                    "data_mode": "synthetic",
                    "dataset_id": "d",
                    "dataset_sha256": "1" * 64,
                    "is_mock": mock,
                    "launch_gate": "advisory",
                    "judge_gate": False,
                    "details": {},
                }
            ],
        )
    out = rig.ok(cred, "pack_results", {"agent_id": "payments"})
    assert out["count"] == 2 and {i["is_mock"] for i in out["items"]} == {True, False}
    assert all(i["metrics"] == {"asr_bp": 1200} for i in out["items"])
