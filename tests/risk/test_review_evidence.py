"""WP29 review (internal auditor, bank security reviewer): holes in the evidence rule.

Each test is a way a residual score could go down without evidence that the linked control
works for the agents the risk applies to. Before the review fixes every one of them lowered the
score."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Edge, Node, node_id_for
from supervisor.inventory.store import InventoryStore
from supervisor.risk import evidence as ev
from supervisor.risk.harness import _Env
from supervisor.risk.model import RiskError, normalise

from .conftest import risk_data


def _verdict(env: _Env, agent: str, rule: str, action: str, label: str, **kw: Any) -> None:
    env.n += 1
    env.adapters.tables.append(
        "verdict",
        [
            {
                "verdict_id": f"rv{env.n}",
                "ts": env.window_time(),
                "agent_id": agent,
                "tier": 0,
                "checker_id": kw.get("checker_id", "gate:tier0a"),
                "is_mock": kw.get("is_mock", False),
                "advisory": False,
                "label": label,
                "action": action,
                "rule_id": rule,
            }
        ],
    )


def _monitor(env: _Env, agent: str, monitor: str, status: str = "ok") -> None:
    day = (env.adapters.clock.now() - dt.timedelta(days=1)).date()
    cur = env.adapters.state.get("oversight_metric", {"metric_date": day, "agent_id": agent})
    statuses = dict((cur or {}).get("monitor_status") or {})
    statuses[monitor] = {"status": status, "n": 1}
    if cur is None:
        env.adapters.state.insert(
            "oversight_metric",
            {
                "metric_date": day,
                "agent_id": agent,
                "computed_at": env.adapters.clock.now(),
                "monitor_status": statuses,
            },
        )
    else:
        env.adapters.state.update(
            "oversight_metric",
            {"metric_date": day, "agent_id": agent},
            {"monitor_status": statuses},
            cur["row_version"],
        )


def _shared(env: _Env, agents: tuple[str, ...], links: list[tuple[str, str]]) -> str:
    g = Graph()
    for a in agents:
        g.add_node(Node("system", a, attrs={"role": "agent"}))
    g.add_node(Node("model_endpoint", "ep"))
    for a in agents:
        g.add_edge(
            Edge(
                node_id_for("system", a), node_id_for("model_endpoint", "ep"), "uses", "manual", "h"
            )
        )
    InventoryStore(env.adapters.state, env.adapters.clock).apply(g, source="manual")
    data = risk_data(agent_id=None, node_id=node_id_for("model_endpoint", "ep"))
    return env.svc.create(data, "t", links=links)["risk_id"]


# ---- H1: a hit that enforced nothing is not evidence ---------------------------------------


@pytest.mark.parametrize(
    ("action", "label", "extra"),
    [
        ("log", "shadow_would_block", {}),  # the agent was in SHADOW at the time of the hit
        ("log", "shadow_would_pause", {}),
        ("block", "rule_error", {}),  # the rule raised; the fail mode decided, not the rule
        ("alert", "fail_open", {"checker_id": "gate:fail_mode"}),
        ("block", "matched", {"is_mock": True}),
    ],
)
def test_shadow_error_fail_and_mock_rows_are_not_rule_hits(
    env: _Env, action: str, label: str, extra: dict[str, Any]
) -> None:
    env.agent("pay")  # RUNNING now (it may have been SHADOW when the row was written)
    rid = env.risk("shadow", "pay", [("rule", "PAY-02")])
    _verdict(env, "pay", "PAY-02", action, label, **extra)
    env.svc.run_evidence()
    r = env.svc.get(rid)
    assert r["evidence"][0]["rule_hits"] == 0
    assert (r["evidence_state"], r["residual_score"]) == ("no_evidence", 20)


def test_an_enforced_match_still_counts(env: _Env) -> None:
    env.agent("pay")
    rid = env.risk("enforced", "pay", [("rule", "PAY-02")])
    _verdict(env, "pay", "PAY-02", "block", "matched")
    env.svc.run_evidence()
    assert env.svc.get(rid)["residual_score"] == 10


# ---- M1: evidence from one agent does not lower a shared risk for another ------------------


def test_a_pack_run_on_one_agent_does_not_prove_the_control_for_all(env: _Env) -> None:
    env.agent("ag1")
    env.agent("ag2")
    rid = _shared(env, ("ag1", "ag2"), [("pack", "pack_a")])
    env.pack("ag1", "pack_a", "ok", env.window_time())
    env.svc.run_evidence()
    r = env.svc.get(rid)
    assert r["agents"] == ["ag1", "ag2"]
    assert (r["evidence_state"], r["residual_score"]) == ("no_evidence", 20)
    env.pack("ag2", "pack_a", "ok", env.window_time(3))
    later = env.adapters.clock.now() + dt.timedelta(hours=1)
    env.svc.run_evidence(later)
    assert env.svc._latest_evidence(rid)[rid]["state"] == "working"  # noqa: SLF001


def test_a_monitor_ok_on_one_agent_does_not_prove_it_for_all(env: _Env) -> None:
    env.agent("ag1")
    env.agent("ag2")
    rid = _shared(env, ("ag1", "ag2"), [("monitor", "drift")])
    _monitor(env, "ag1", "drift")
    env.svc.run_evidence()
    assert env.svc.get(rid)["residual_score"] == 20
    _monitor(env, "ag2", "drift")
    env.svc.run_evidence(env.adapters.clock.now() + dt.timedelta(hours=1))
    assert env.svc._latest_evidence(rid)[rid]["state"] == "working"  # noqa: SLF001


def test_a_shadow_agent_on_a_shared_risk_is_excluded_not_required(env: _Env) -> None:
    env.agent("ag1")
    env.agent("ag2", "SHADOW")
    rid = _shared(env, ("ag1", "ag2"), [("pack", "pack_a")])
    env.pack("ag1", "pack_a", "ok", env.window_time())
    env.svc.run_evidence()
    r = env.svc.get(rid)
    assert (r["evidence_state"], r["residual_score"]) == ("working", 10)
    assert r["evidence"][0]["agents_excluded"] == 1


# ---- M2: an advisory judge or a monitor that writes no status is not evidence ---------------


@pytest.mark.parametrize("monitor", ["quality", "oversight"])
def test_judge_and_statusless_monitors_never_lower_a_score(env: _Env, monitor: str) -> None:
    env.agent("pay")
    rid = env.risk("monitor", "pay", [("monitor", monitor)])
    _monitor(env, "pay", monitor)  # even a hand-written "ok" does not count
    env.svc.run_evidence()
    r = env.svc.get(rid)
    assert (r["evidence_state"], r["residual_score"]) == ("no_evidence", 20)
    assert r["evidence"][0]["monitor_other"] == 1


# ---- M3: a change to the risk after the evidence pass needs a new pass ---------------------


def _working(env: _Env) -> str:
    env.agent("pay")
    env.agent("svc")
    rid = env.risk("edit", "pay", [("rule", "PAY-02"), ("pack", "pack_a")])
    _verdict(env, "pay", "PAY-02", "block", "matched")
    env.svc.run_evidence()
    assert env.svc.get(rid)["residual_score"] == 10
    return rid


def test_unlinking_the_working_control_puts_the_score_back_up(env: _Env) -> None:
    rid = _working(env)
    env.svc.remove_link(rid, "rule", "PAY-02", "t")
    r = env.svc.get(rid)
    assert (r["evidence_reason"], r["residual_score"]) == ("changed_since_evidence", 20)
    out = env.svc.run_evidence()  # same window: a new row for the new control set
    assert out["written"] == 1
    r = env.svc.get(rid)
    assert (r["evidence_reason"], r["residual_score"]) == ("no_working_control", 20)


def test_lowering_the_declared_residual_needs_a_new_pass(env: _Env) -> None:
    rid = _working(env)
    env.svc.update(rid, {"residual_likelihood": 1}, "t")
    r = env.svc.get(rid)
    assert (r["evidence_reason"], r["residual_score"]) == ("changed_since_evidence", 20)
    env.svc.run_evidence()
    assert env.svc.get(rid)["residual_score"] == 5


def test_moving_the_risk_to_another_agent_drops_the_old_evidence(env: _Env) -> None:
    rid = _working(env)
    env.svc.update(rid, {"agent_id": "svc"}, "t")
    r = env.svc.get(rid)
    assert (r["evidence_reason"], r["residual_score"]) == ("changed_since_evidence", 20)
    env.svc.run_evidence()
    assert env.svc.get(rid)["residual_score"] == 20  # svc has no hit


def test_a_text_edit_keeps_the_evidence(env: _Env) -> None:
    rid = _working(env)
    env.svc.update(rid, {"title": "new title", "owner": "someone else"}, "t")
    assert env.svc.get(rid)["residual_score"] == 10
    assert env.svc.run_evidence()["repeat"] == 1  # nothing material changed


def test_list_and_agent_levels_agree_with_get_after_an_edit(env: _Env) -> None:
    rid = _working(env)
    env.svc.remove_link(rid, "rule", "PAY-02", "t")
    (row,) = [r for r in env.svc.list_risks() if r["risk_id"] == rid]
    assert row["residual_score"] == 20
    assert env.svc.agent_levels()["pay"].residual_score == 20


# ---- M4: avoid and transfer may lower a declared residual only with a justification -------


@pytest.mark.parametrize("treatment", ["avoid", "transfer"])
def test_avoid_or_transfer_below_inherent_needs_a_note(treatment: str) -> None:
    with pytest.raises(RiskError, match="justification"):
        normalise(risk_data(treatment=treatment, residual_likelihood=1))
    ok = normalise(risk_data(treatment=treatment, residual_likelihood=1, treatment_note="contract"))
    assert ok["residual_likelihood"] == 1
    same = normalise(risk_data(treatment=treatment, residual_likelihood=4))  # not lowered
    assert same["treatment_note"] is None


# ---- L1: the window does not depend on the host time zone ----------------------------------


def test_window_is_the_same_instant_in_every_time_zone() -> None:
    utc = dt.datetime(2026, 10, 20, 17, 41, tzinfo=dt.UTC)
    ict = utc.astimezone(dt.timezone(dt.timedelta(hours=7)))
    naive = utc.replace(tzinfo=None)  # a naive time is read as UTC, never as host local time
    ends = {ev.window_for(t, 7).end for t in (utc, ict, naive)}
    assert ends == {dt.datetime(2026, 10, 20, 17, 0, tzinfo=dt.UTC)}


# ---- both modes: bootstrap on an existing SQLite file -------------------------------------


def test_bootstrap_on_an_existing_store_adds_the_risk_tables_and_keeps_rows(env: _Env) -> None:
    from supervisor.jobs import bootstrap_schema

    env.agent("keep")
    x = env.adapters.executor
    for trg in ("trg_risk_evidence_no_update", "trg_risk_evidence_no_delete"):
        x.execute(f"DROP TRIGGER {trg}")
    for table in ("risk_evidence", "risk_link", "risk"):
        x.execute(f"DROP TABLE {table}")  # a store from before WP29
    bootstrap_schema.run(env.settings, env.adapters)
    assert env.adapters.state.get("agent", {"agent_id": "keep"}) is not None
    rid = env.risk("after upgrade", "keep", [("rule", "PAY-02")])
    env.svc.run_evidence()
    assert env.svc.get(rid)["evidence"]
    from supervisor.core.errors import AppendOnlyError

    with pytest.raises(AppendOnlyError):
        x.execute("DELETE FROM risk_evidence")
