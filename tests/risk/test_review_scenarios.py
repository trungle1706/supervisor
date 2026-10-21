"""WP29 review: five scenarios written by the reviewer, not by the author of the code or of
``tests/fixtures/risk/generate.py``. Rubric: operational risk manager (score = likelihood x
impact; ILLUSTRATIVE bands low <= 4, medium <= 9, high <= 15, critical above; agent level = the
worst risk it reaches; a lower residual needs a control that worked for the supervised agents).

Every expected number below was computed by hand from that rubric; nothing is derived from the
code under test."""

from __future__ import annotations

import datetime as dt

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Edge, Node, node_id_for
from supervisor.inventory.store import InventoryStore
from supervisor.risk.harness import _Env

from .test_review_evidence import _monitor, _verdict

EP = node_id_for("model_endpoint", "ep-shared")


def _risk(env: _Env, rid: str, agent: str | None, l: int, i: int, rl: int, ri: int, **kw):  # noqa: ANN202, E741
    data = {
        "title": rid,
        "category": kw.pop("category", "money_movement"),
        "agent_id": agent,
        "inherent_likelihood": l,
        "inherent_impact": i,
        "residual_likelihood": rl,
        "residual_impact": ri,
        "treatment": kw.pop("treatment", "mitigate"),
        "owner": "Op Risk",
        "review_date": "2027-04-20",
        "status": kw.pop("status", "active"),
    } | kw
    links = data.pop("links", [])
    return env.svc.create(data, "reviewer", risk_id=rid, links=links)


def _graph(env: _Env, agents: tuple[str, ...]) -> None:
    g = Graph()
    for a in agents:
        g.add_node(Node("system", a, attrs={"role": "agent"}))
    g.add_node(Node("model_endpoint", "ep-shared"))
    for a in agents:
        g.add_edge(Edge(node_id_for("system", a), EP, "uses", "manual", "h"))
    InventoryStore(env.adapters.state, env.adapters.clock).apply(g, source="manual")


def test_s1_payment_limit_rule_enforced_lowers_to_declared(env: _Env) -> None:
    # L4 x I5 = 20 critical; declared L2 x I5 = 10 high; PAY-02 blocked once in the window.
    env.agent("pay")
    _risk(env, "S1", "pay", 4, 5, 2, 5, links=[("rule", "PAY-02"), ("pack", "pack_a")])
    _verdict(env, "pay", "PAY-02", "block", "matched")
    env.svc.run_evidence()
    r = env.svc.get("S1")
    assert (r["inherent_score"], r["inherent_band"]) == (20, "critical")
    assert (r["residual_score"], r["residual_band"], r["evidence_state"]) == (10, "high", "working")
    lv = env.svc.agent_levels()["pay"]
    assert (lv.inherent_level, lv.residual_level, lv.residual_score) == ("critical", "high", 10)


def test_s2_failing_pack_beats_a_working_rule(env: _Env) -> None:
    # L3 x I4 = 12 high; declared L1 x I4 = 4 low; rule hit but the pack failed -> stays 12.
    env.agent("crd")
    _risk(
        env, "S2", "crd", 3, 4, 1, 4, category="credit_decision",
        links=[("rule", "PAY-02"), ("pack", "pack_a")],
    )  # fmt: skip
    _verdict(env, "crd", "PAY-02", "block", "matched")
    env.pack("crd", "pack_a", "fail", env.window_time())
    env.svc.run_evidence()
    r = env.svc.get("S2")
    assert (r["residual_score"], r["residual_band"]) == (12, "high")
    assert (r["evidence_state"], r["evidence_reason"]) == ("failing", "control_failing")


def test_s3_shared_endpoint_reaches_both_agents_and_max_wins(env: _Env) -> None:
    # Shared: L3 x I3 = 9 medium (top of medium); declared L1 x I3 = 3 low; drift ok on both.
    # ag1 own: L2 x I5 = 10 high (bottom of high), accepted, residual = inherent.
    env.agent("ag1")
    env.agent("ag2")
    _graph(env, ("ag1", "ag2"))
    _risk(
        env, "S3-SH", None, 3, 3, 1, 3, node_id=EP, category="availability",
        links=[("monitor", "drift")],
    )  # fmt: skip
    _risk(env, "S3-OWN", "ag1", 2, 5, 2, 5, treatment="accept", treatment_note="board accepted")
    _monitor(env, "ag1", "drift")
    _monitor(env, "ag2", "drift")
    env.svc.run_evidence()
    sh = env.svc.get("S3-SH")
    assert sh["agents"] == ["ag1", "ag2"]
    assert (sh["inherent_band"], sh["residual_score"], sh["residual_band"]) == ("medium", 3, "low")
    lv = env.svc.agent_levels()
    assert (lv["ag1"].inherent_level, lv["ag1"].residual_level) == ("high", "high")
    assert (lv["ag1"].inherent_score, lv["ag1"].residual_score) == (10, 10)
    assert (lv["ag2"].inherent_level, lv["ag2"].residual_level) == ("medium", "low")
    assert (lv["ag2"].inherent_score, lv["ag2"].residual_score) == (9, 3)
    assert {x["risk_id"] for x in lv["ag2"].reached} == {"S3-SH"}


def test_s4_draft_and_retired_do_not_count_and_no_links_keeps_inherent(env: _Env) -> None:
    # Draft L4 x I4 = 16 and retired L5 x I5 = 25 are listed, not counted. Active L1 x I4 = 4
    # low with no control link: declared 1 x 1 is not used, residual stays 4.
    env.agent("ag3")
    _risk(env, "S4-D", "ag3", 4, 4, 4, 4, status="draft")
    _risk(env, "S4-R", "ag3", 5, 5, 5, 5, status="retired")
    _risk(env, "S4-A", "ag3", 1, 4, 1, 1)
    env.svc.run_evidence()
    a = env.svc.get("S4-A")
    assert (a["residual_score"], a["evidence_reason"]) == (4, "no_links")
    lv = env.svc.agent_levels()["ag3"]
    assert (lv.inherent_level, lv.residual_level, lv.inherent_score) == ("low", "low", 4)
    assert {x["risk_id"] for x in lv.reached} == {"S4-A"}


def test_s5_shadow_agent_is_no_evidence_and_transfer_needs_a_note(env: _Env) -> None:
    # SHADOW agent: L4 x I3 = 12 high stays 12 although the rule "would have" blocked.
    # Transfer: L2 x I4 = 8 medium, declared L1 x I4 = 4 low with a contract note.
    env.agent("ag4", "SHADOW")
    _risk(env, "S5-M", "ag4", 4, 3, 1, 3, links=[("rule", "PAY-02")])
    _risk(env, "S5-T", "ag4", 2, 4, 1, 4, treatment="transfer", treatment_note="insured")
    _verdict(env, "ag4", "PAY-02", "log", "shadow_would_block")
    env.svc.run_evidence()
    m = env.svc.get("S5-M")
    assert (m["residual_score"], m["evidence_reason"]) == (12, "no_supervised_agent")
    t = env.svc.get("S5-T")
    assert (t["residual_score"], t["residual_band"], t["evidence_reason"]) == (
        4,
        "low",
        "treatment_declared",
    )
    lv = env.svc.agent_levels()["ag4"]
    assert (lv.inherent_level, lv.residual_level, lv.residual_score) == ("high", "high", 12)
    assert env.svc.get("S5-M")["evidence"][0]["agents_excluded"] == 1
    assert dt.date.fromisoformat(m["review_date"]) > dt.date(2026, 10, 20)
