"""WP29: runtime evidence and the rule that may lower a residual score (rubric: internal auditor,
Three Lines): a lowered score needs working evidence and a recorded reason; a broken control
raises it again; SHADOW, retired and mock results are not evidence."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from supervisor.core.errors import AppendOnlyError
from supervisor.risk import evidence as ev
from supervisor.risk.harness import _Env
from supervisor.risk.model import RiskConfig

from .conftest import ListSink

CFG = RiskConfig()


def _c(**kw: int) -> ev.Counts:
    return ev.Counts(**kw)


# ---- the pure rule ------------------------------------------------------------------------


def test_working_lowers_to_the_declared_residual() -> None:
    d = ev.assess("mitigate", (4, 5), (2, 5), _c(agents_n=1, rule_links=1, controls_working=1), CFG)
    assert (d.state, d.reason, d.residual) == ("working", "controls_working", (2, 5))


@pytest.mark.parametrize(
    ("counts", "state", "reason"),
    [
        (dict(agents_n=1, rule_links=1, controls_idle=1), "no_evidence", "no_working_control"),
        (dict(agents_n=1, rule_links=1, controls_failing=1), "failing", "control_failing"),
        (dict(agents_n=1), "no_evidence", "no_links"),
        (dict(agents_n=0, rule_links=1, controls_idle=1), "no_evidence", "no_supervised_agent"),
        (
            dict(agents_n=1, rule_links=2, controls_working=1, controls_failing=1),
            "failing",
            "control_failing",
        ),
    ],
)
def test_without_working_evidence_the_residual_is_the_inherent_score(
    counts: dict[str, int], state: str, reason: str
) -> None:
    d = ev.assess("mitigate", (4, 5), (2, 5), _c(**counts), CFG)
    assert (d.state, d.reason, d.residual) == (state, reason, (4, 5))


def test_residual_never_goes_below_the_declared_value() -> None:
    many = _c(agents_n=9, rule_links=5, rule_hits=999, controls_working=5)
    assert ev.assess("mitigate", (5, 5), (3, 3), many, CFG).residual == (3, 3)


def test_min_working_controls_is_honoured() -> None:
    cfg = RiskConfig(min_working_controls=2)
    one = _c(agents_n=1, rule_links=2, controls_working=1, controls_idle=1)
    assert ev.assess("mitigate", (4, 4), (2, 2), one, cfg).residual == (4, 4)
    two = _c(agents_n=1, rule_links=2, controls_working=2)
    assert ev.assess("mitigate", (4, 4), (2, 2), two, cfg).residual == (2, 2)


@pytest.mark.parametrize("treatment", ["avoid", "accept", "transfer"])
def test_other_treatments_keep_the_declared_residual(treatment: str) -> None:
    d = ev.assess(treatment, (4, 4), (4, 4), _c(agents_n=1), CFG)
    assert d.residual == (4, 4) and d.reason == "treatment_declared"


def test_window_is_whole_hours_and_ends_before_now() -> None:
    now = dt.datetime(2026, 10, 20, 17, 41, 9, tzinfo=dt.UTC)
    w = ev.window_for(now, 7)
    assert w.end == dt.datetime(2026, 10, 20, 17, 0, tzinfo=dt.UTC)
    assert w.seconds == 7 * 86400


def test_every_reason_code_is_known() -> None:
    for state in (
        dict(agents_n=1, rule_links=1, controls_working=1),
        dict(agents_n=1),
        dict(agents_n=0, rule_links=1),
    ):
        assert ev.assess("mitigate", (3, 3), (2, 2), _c(**state), CFG).reason in ev.REASONS


# ---- against a real store -----------------------------------------------------------------


def _seed_monitor(env: _Env, agent: str, status: str, day: dt.date) -> None:
    env.adapters.state.insert(
        "oversight_metric",
        {
            "metric_date": day,
            "agent_id": agent,
            "computed_at": env.adapters.clock.now(),
            "monitor_status": {"oversight": {"status": status, "code": "x", "reason": "x", "n": 1}},
        },
    )


def test_rule_hit_makes_the_control_work_and_lowers_the_score(env: _Env) -> None:
    sink = ListSink()
    env.svc.evidence_sink = sink
    env.agent("pay")
    rid = env.risk("rule works", "pay", [("rule", "PAY-02"), ("matrix", "OB-1")])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    out = env.svc.run_evidence()
    assert out["written"] == 1 and out["working"] == 1
    r = env.svc.get(rid)
    assert (r["evidence_state"], r["residual_score"], r["inherent_score"]) == ("working", 10, 20)
    assert r["evidence_reason"] == "controls_working"
    (row,) = r["evidence"]
    assert (row["rule_links"], row["rule_hits"], row["rule_stops"], row["controls_working"]) == (
        1,
        1,
        1,
        1,
    )
    assert row["agents_n"] == 1 and row["agents_excluded"] == 0 and len(row["digest"]) == 64
    assert row["chain_hash"]
    (payload,) = sink.of("risk_evidence")
    assert payload["agent_id"] == "pay" and payload["state"] == "working"
    assert payload["reason"] == "controls_working" and payload["residual_likelihood"] == 2


def test_chain_payload_has_only_ints_and_text(env: _Env) -> None:
    sink = ListSink()
    env.svc.evidence_sink = sink
    env.agent("pay")
    env.risk("payload", "pay", [("rule", "PAY-02"), ("pack", "pack_a"), ("monitor", "oversight")])
    env.svc.run_evidence()
    for _, ref, payload in sink.records:
        assert ref.startswith("risk:")
        for k, v in payload.items():
            assert isinstance(v, (int, str)) and not isinstance(v, float), (k, v)


def test_a_second_run_in_the_same_window_writes_nothing(env: _Env) -> None:
    sink = ListSink()
    env.svc.evidence_sink = sink
    env.agent("pay")
    env.risk("repeat", "pay", [("rule", "PAY-02")])
    assert env.svc.run_evidence()["written"] == 1
    again = env.svc.run_evidence()
    assert again["written"] == 0 and again["repeat"] == 1
    assert len(sink.of("risk_evidence")) == 1


def test_hits_outside_the_window_and_advisory_or_allow_rows_do_not_count(env: _Env) -> None:
    env.agent("pay")
    rid = env.risk("window", "pay", [("rule", "PAY-02")])
    w = ev.window_for(env.adapters.clock.now(), env.settings.risk_evidence_window_days)
    env.verdict("pay", "PAY-02", "block", w.start - dt.timedelta(hours=1))  # before
    env.verdict("pay", "PAY-02", "block", w.end + dt.timedelta(hours=1))  # after
    env.verdict("pay", "PAY-02", "allow", env.window_time())  # not a hit
    env.svc.run_evidence()
    r = env.svc.get(rid)
    assert r["evidence_state"] == "no_evidence" and r["residual_score"] == 20
    assert r["evidence"][0]["rule_hits"] == 0


def test_log_and_alert_hits_count_as_hits_but_not_stops(env: _Env) -> None:
    env.agent("pay")
    rid = env.risk("detective", "pay", [("rule", "PAY-02")])
    env.verdict("pay", "PAY-02", "alert", env.window_time())
    env.svc.run_evidence()
    row = env.svc.get(rid)["evidence"][0]
    assert (row["rule_hits"], row["rule_stops"]) == (1, 0)


def test_pack_ok_and_monitor_ok_are_working(env: _Env) -> None:
    env.agent("pay")
    r1 = env.risk("pack", "pay", [("pack", "pack_a")])
    r2 = env.risk("monitor", "pay", [("monitor", "oversight")])
    env.pack("pay", "pack_a", "ok", env.window_time())
    _seed_monitor(env, "pay", "ok", (env.adapters.clock.now() - dt.timedelta(days=1)).date())
    env.svc.run_evidence()
    assert env.svc.get(r1)["evidence_state"] == "working"
    assert env.svc.get(r2)["evidence_state"] == "working"


def test_monitor_not_applicable_is_idle_and_pack_warn_is_idle(env: _Env) -> None:
    env.agent("pay")
    r1 = env.risk("monitor idle", "pay", [("monitor", "oversight")])
    r2 = env.risk("pack warn", "pay", [("pack", "pack_a")])
    env.pack("pay", "pack_a", "warn", env.window_time())
    _seed_monitor(
        env, "pay", "not_applicable", (env.adapters.clock.now() - dt.timedelta(days=1)).date()
    )
    env.svc.run_evidence()
    for rid in (r1, r2):
        got = env.svc.get(rid)
        assert got["evidence_state"] == "no_evidence" and got["residual_score"] == 20


def test_shared_risk_counts_every_agent_that_reaches_it(env: _Env) -> None:
    """A risk on a node (no agent_id) is looked at for the agents that reach the node."""
    from supervisor.inventory.graph import Graph
    from supervisor.inventory.model import Edge, Node, node_id_for
    from supervisor.inventory.store import InventoryStore

    env.agent("ag1")
    env.agent("ag2", "SHADOW")
    g = Graph()
    for a in ("ag1", "ag2"):
        g.add_node(Node("system", a, attrs={"role": "agent"}))
    g.add_node(Node("model_endpoint", "ep"))
    for a in ("ag1", "ag2"):
        g.add_edge(
            Edge(
                node_id_for("system", a), node_id_for("model_endpoint", "ep"), "uses", "manual", "h"
            )
        )
    InventoryStore(env.adapters.state, env.adapters.clock).apply(g, source="manual")
    rid = env.svc.create(
        {
            "title": "shared", "category": "third_party",
            "node_id": node_id_for("model_endpoint", "ep"),
            "inherent_likelihood": 3, "inherent_impact": 4, "residual_likelihood": 2,
            "residual_impact": 3, "treatment": "mitigate", "owner": "o",
            "review_date": "2027-04-20", "status": "active",
        },
        "t",
        links=[("rule", "PAY-02")],
    )["risk_id"]  # fmt: skip
    env.verdict("ag1", "PAY-02", "block", env.window_time())
    env.verdict("ag2", "PAY-02", "block", env.window_time())
    env.svc.run_evidence()
    row = env.svc.get(rid)["evidence"][0]
    assert (row["agents_n"], row["agents_excluded"], row["rule_hits"]) == (1, 1, 1)


def test_risk_evidence_rows_are_append_only(env: _Env) -> None:
    env.agent("pay")
    env.risk("append", "pay", [("rule", "PAY-02")])
    env.svc.run_evidence()
    x = env.adapters.executor
    with pytest.raises(AppendOnlyError):
        x.execute("UPDATE risk_evidence SET state = 'working'")
    with pytest.raises(AppendOnlyError):
        x.execute("DELETE FROM risk_evidence")


def test_only_active_risks_get_evidence(env: _Env) -> None:
    env.agent("pay")
    env.risk("draft", "pay", [("rule", "PAY-02")], status="draft")
    env.risk("retired", "pay", [("rule", "PAY-02")], status="retired")
    assert env.svc.run_evidence()["risks"] == 0


def test_evidence_round_trip_values(env: _Env) -> None:
    env.agent("pay")
    rid = env.risk("values", "pay", [("rule", "PAY-02")])
    env.verdict("pay", "PAY-02", "pause", env.window_time())
    env.svc.run_evidence()
    row: dict[str, Any] = env.adapters.tables.query("risk_evidence", {"risk_id": rid})[0]
    ints = [
        "agents_n", "rule_hits", "rule_stops", "controls_working", "residual_likelihood",
        "residual_impact", "declared_residual_likelihood", "declared_residual_impact",
    ]  # fmt: skip
    assert all(isinstance(row[k], int) for k in ints)
    assert (row["residual_likelihood"], row["residual_impact"]) == (2, 5)


def test_one_pass_asks_the_same_control_question_once(env: _Env) -> None:
    """Two risks that share an agent and a rule cost one verdict query in a pass."""
    env.agent("pay")
    env.risk("first", "pay", [("rule", "PAY-02")])
    env.risk("second", "pay", [("rule", "PAY-02")])
    env.verdict("pay", "PAY-02", "block", env.window_time())
    seen: list[str] = []
    real = env.adapters.tables.query

    def spy(table: str, *a: Any, **k: Any) -> Any:
        seen.append(table)
        return real(table, *a, **k)

    env.adapters.tables.query = spy  # type: ignore[method-assign]
    try:
        out = env.svc.run_evidence()
    finally:
        env.adapters.tables.query = real  # type: ignore[method-assign]
    assert out["written"] == 2 and out["working"] == 2
    assert seen.count("verdict") == 1
