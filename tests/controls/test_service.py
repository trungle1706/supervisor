"""WP30 control catalogue: model, map, evidence status, compliance bp (rubric: compliance officer,
internal auditor under the Three Lines model)."""

from __future__ import annotations

import pytest

from supervisor.controls import evidence as cev
from supervisor.controls.harness_env import CtlEnv
from supervisor.controls.model import ControlError, normalise
from supervisor.core.errors import NotFoundError

from .conftest import ListSink


def _data(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "T",
        "objective": "O",
        "control_type": "preventive",
        "implemented_by": "product",
        "owner": "ops",
        "status": "draft",
    }
    return base | kw


# ---- model ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"title": ""}, "title is required"),
        ({"objective": None}, "objective is required"),
        ({"control_type": "magic"}, "type must be one of"),
        ({"implemented_by": "vendor"}, "implemented_by must be one of"),
        ({"owner": " "}, "owner is required"),
        ({"status": "live"}, "status must be one of"),
        ({"status": "active"}, "needs a review_date"),
        ({"review_date": "31/01/2027"}, "must be a date"),
        ({"agents": []}, "agents must be a list"),
        ({"agents": ["*", "pay"]}, "cannot be mixed"),
        ({"agents": ["bad id"]}, "agent id must be"),
        ({"title": 5}, "title must be text"),
    ],
)
def test_model_refuses_bad_input(change: dict[str, object], fragment: str) -> None:
    with pytest.raises(ControlError, match=fragment):
        normalise(_data(**change))


def test_model_normalises_scope() -> None:
    assert normalise(_data())["scope_agents"] == ["*"]
    assert normalise(_data(agents=["Pay", "pay", "svc"]))["scope_agents"] == ["pay", "svc"]


# ---- create, map, rules of shape -------------------------------------------------------------


def test_create_stores_row_map_and_chain_record(env: CtlEnv, sink: ListSink) -> None:
    c = env.control("CTL-A", evidence=[("rule", "PAY-02"), ("pack", "pack_a")])
    assert c["status"] == "active" and c["agents"] == ["pay"]
    assert c["maps"] == {"matrix": ["OB-1"], "rule": ["PAY-02"], "pack": ["pack_a"]}
    (rec,) = sink.of("control_change")
    assert rec["action"] == "create" and rec["cover_n"] == 1 and rec["evidence_n"] == 2
    for v in rec.values():
        assert isinstance(v, (int, str)) and not isinstance(v, float)


def test_an_active_control_needs_something_covered_and_a_source(env: CtlEnv) -> None:
    with pytest.raises(ControlError, match="cover at least one obligation or risk"):
        env.control("CTL-NOCOVER", covers=[])
    with pytest.raises(ControlError, match="at least one evidence source"):
        env.control("CTL-NOSRC", evidence=[])


def test_a_draft_may_be_empty_but_cannot_become_active(env: CtlEnv) -> None:
    env.controls.create(_data(), "u", control_id="CTL-D")
    with pytest.raises(ControlError, match="cover at least one"):
        env.controls.update("CTL-D", {"status": "active", "review_date": "2027-01-01"}, "u")


def test_duplicate_id_and_bad_targets_are_refused(env: CtlEnv) -> None:
    env.control("CTL-A")
    with pytest.raises(ControlError, match="already exists"):
        env.control("CTL-A")
    with pytest.raises(ControlError, match="obligation|matrix 'NOPE' does not exist"):
        env.control("CTL-B", covers=[("matrix", "NOPE")])
    with pytest.raises(ControlError, match="rule 'GONE' does not exist"):
        env.control("CTL-C", evidence=[("rule", "GONE")])
    with pytest.raises(ControlError, match="risk 'RSK-X' does not exist"):
        env.control("CTL-D", covers=[("risk", "RSK-X")])
    with pytest.raises(ControlError, match="map target must be"):
        env.controls.add_map("CTL-A", "rule", "bad target", "u")


def test_a_rule_limited_to_one_agent_cannot_prove_another(env: CtlEnv) -> None:
    with pytest.raises(ControlError, match="limited to pay"):
        env.control("CTL-W", agents=["*"])
    with pytest.raises(ControlError, match="not in scope for svc"):
        env.control("CTL-X", agents=["pay", "svc"])
    env.control("CTL-OK", agents=["pay"])


def test_risk_map_writes_a_wp29_control_link(env: CtlEnv) -> None:
    env.agent("pay")
    rid = env.risk("r", "pay", [("matrix", "OB-1")])
    env.control("CTL-L", covers=[("matrix", "OB-1"), ("risk", rid)])
    assert ("control", "CTL-L") in [(x["kind"], x["target"]) for x in env.svc.get(rid)["links"]]
    c = env.controls.update("CTL-L", {"status": "retired"}, "u")
    assert c["status"] == "retired"
    assert ("control", "CTL-L") not in [(x["kind"], x["target"]) for x in env.svc.get(rid)["links"]]


def test_active_control_keeps_its_cover_and_source(env: CtlEnv) -> None:
    env.control("CTL-K", evidence=[("rule", "PAY-02")])
    with pytest.raises(ControlError, match="at least one evidence source"):
        env.controls.remove_map("CTL-K", "rule", "PAY-02", "u")
    with pytest.raises(ControlError, match="cover at least one"):
        env.controls.remove_map("CTL-K", "matrix", "OB-1", "u")


def test_retired_control_is_read_only(env: CtlEnv) -> None:
    env.control("CTL-R")
    env.controls.update("CTL-R", {"status": "retired"}, "u")
    with pytest.raises(ControlError, match="retired"):
        env.controls.update("CTL-R", {"title": "x"}, "u")
    with pytest.raises(ControlError, match="retired"):
        env.controls.add_map("CTL-R", "matrix", "OB-2", "u")


def test_unknown_control_is_not_found(env: CtlEnv) -> None:
    with pytest.raises(NotFoundError):
        env.controls.get("CTL-NONE")


# ---- evidence status -------------------------------------------------------------------------


def _status(env: CtlEnv, control: str, agent: str = "pay") -> dict[str, object]:
    env.controls.run_status()
    comp = env.controls.agent_compliance(agent)
    return next(c for c in comp["controls"] if c["control_id"] == control)


def test_rule_hit_makes_the_control_working(env: CtlEnv, sink: ListSink) -> None:
    env.agent("pay")
    env.control("CTL-A", evidence=[("rule", "PAY-02")])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    s = _status(env, "CTL-A")
    assert (s["status"], s["reason"]) == ("working", "sources_working")
    comp = env.controls.agent_compliance("pay")
    assert comp["compliance_bp"] == 10000 and comp["in_scope"] == 1
    (rec,) = sink.of("control_status")
    assert rec["agent_id"] == "pay" and rec["compliance_bp"] == 10000 and rec["working"] == 1


def test_quiet_rule_is_no_data_not_working(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-A")
    s = _status(env, "CTL-A")
    assert (s["status"], s["reason"]) == ("no_data", "no_working_source")
    assert env.controls.agent_compliance("pay")["compliance_bp"] == 0


def test_a_rule_that_left_the_policy_makes_the_control_failing(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-A", evidence=[("rule", "PAY-02"), ("pack", "pack_a")])
    env.pack("pay", "pack_a", "ok", env.window_time())
    env.rules.discard("PAY-02")  # the rule was retired from the policy
    s = _status(env, "CTL-A")
    assert (s["status"], s["reason"]) == ("failing", "source_failing")


def test_mock_pack_result_is_never_evidence(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-A", evidence=[("pack", "pack_a")])
    env.pack("pay", "pack_a", "ok", env.window_time(), mock=True)
    assert _status(env, "CTL-A")["status"] == "no_data"


def test_failing_pack_beats_working_rule(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-A", evidence=[("rule", "PAY-02"), ("pack", "pack_a")])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.pack("pay", "pack_a", "fail", env.window_time())
    assert _status(env, "CTL-A")["status"] == "failing"


def test_shadow_agent_is_not_supervised(env: CtlEnv) -> None:
    env.agent("pay", "SHADOW")
    env.control("CTL-A")
    env.verdict("pay", "PAY-02", "block", env.window_time())
    s = _status(env, "CTL-A")
    assert (s["status"], s["reason"]) == ("no_data", "no_supervised_agent")


def test_reference_only_control_never_works(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-DOC", evidence=[("document", "dpia-file"), ("detector", "cccd")])
    s = _status(env, "CTL-DOC")
    assert (s["status"], s["reason"]) == ("no_data", "reference_only")


def test_second_run_in_a_window_writes_nothing(env: CtlEnv, sink: ListSink) -> None:
    env.agent("pay")
    env.control("CTL-A")
    first = env.controls.run_status()
    again = env.controls.run_status()
    assert first["written"] == 1 and again["written"] == 0 and again["repeat"] == 1
    assert len(sink.of("control_status")) == 1


def test_control_status_is_append_only(env: CtlEnv) -> None:
    from supervisor.core.errors import AppendOnlyError

    env.agent("pay")
    env.control("CTL-A")
    env.controls.run_status()
    with pytest.raises(AppendOnlyError):
        env.adapters.executor.execute("UPDATE control_status SET status = 'working'")
    with pytest.raises(AppendOnlyError):
        env.adapters.executor.execute("DELETE FROM control_status")


def test_compliance_counts_only_controls_in_scope(env: CtlEnv) -> None:
    env.agent("pay")
    env.agent("svc")
    env.control("CTL-PAY", agents=["pay"])
    env.control("CTL-SVC", evidence=[("rule", "SVC-01")], agents=["svc"])
    env.control("CTL-ALL", evidence=[("monitor", "oversight")], agents=["*"])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.controls.run_status()
    pay = env.controls.agent_compliance("pay")
    svc = env.controls.agent_compliance("svc")
    assert pay["in_scope"] == 2 and pay["working"] == 1 and pay["compliance_bp"] == 5000
    assert svc["in_scope"] == 2 and svc["working"] == 0 and svc["compliance_bp"] == 0
    assert {c["control_id"] for c in svc["controls"]} == {"CTL-SVC", "CTL-ALL"}


def test_bank_controls_are_reported_apart(env: CtlEnv) -> None:
    env.agent("pay")
    env.control("CTL-P")
    env.control("CTL-B", evidence=[("document", "dpia")], implemented_by="bank")
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.controls.run_status()
    comp = env.controls.agent_compliance("pay")
    assert comp["compliance_bp"] == 5000
    assert (comp["product_in_scope"], comp["product_bp"], comp["bank_in_scope"]) == (1, 10000, 1)


def test_no_control_in_scope_is_no_claim(env: CtlEnv) -> None:
    env.agent("pay")
    assert env.controls.agent_compliance("pay")["compliance_bp"] is None
    assert cev.compliance_bp(0, 0) is None


def test_old_status_row_counts_as_stale(env: CtlEnv) -> None:
    import datetime as dt

    env.agent("pay")
    env.control("CTL-A")
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.controls.run_status()
    assert env.controls.agent_compliance("pay")["working"] == 1
    clock = env.adapters.clock
    later = clock.now() + dt.timedelta(days=30)
    env.controls.clock = type("C", (), {"now": staticmethod(lambda: later)})()
    comp = env.controls.agent_compliance("pay")
    assert comp["working"] == 0 and comp["controls"][0]["reason"] == "stale"


def test_retired_agent_has_no_scope(env: CtlEnv) -> None:
    env.agent("pay", "RETIRED")
    env.control("CTL-A")
    out = env.controls.run_status()
    assert out["written"] == 0
    assert env.controls.agent_compliance("pay")["in_scope"] == 0


# ---- the WP29 link kind ----------------------------------------------------------------------


def test_risk_sees_a_control_through_its_sources(env: CtlEnv) -> None:
    env.agent("pay")
    rid = env.risk("through control", "pay", [("matrix", "OB-1")])
    env.control("CTL-A", covers=[("matrix", "OB-1"), ("risk", rid)], evidence=[("rule", "PAY-02")])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.svc.run_evidence()
    r = env.svc.get(rid)
    assert r["evidence_state"] == "working" and r["residual_score"] == 10
    assert r["evidence"][0]["rule_links"] == 1


def test_draft_or_retired_control_gives_a_risk_no_evidence(env: CtlEnv) -> None:
    env.agent("pay")
    rid = env.risk("no draft", "pay", [("matrix", "OB-1")])
    env.controls.create(_data(), "u", control_id="CTL-DR", maps=[("risk", rid)])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    env.svc.run_evidence()
    r = env.svc.get(rid)
    assert r["evidence_state"] == "no_evidence" and r["evidence_reason"] == "no_links"
