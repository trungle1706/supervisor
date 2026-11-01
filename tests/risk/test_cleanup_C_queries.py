"""Clean-up audit N12 and N13: the evidence pass and the risk list read ``verdict``,
``eval_result``, ``oversight_metric`` and ``risk_evidence`` with a number of statements that does
not grow with the agents or the risks, and give the same result as the per-row reads."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Edge, Node, node_id_for
from supervisor.inventory.store import InventoryStore
from supervisor.risk.harness import _Env

TABLES = ("verdict", "eval_result", "oversight_metric", "risk_evidence")


def _count_reads(env: _Env) -> dict[str, int]:
    seen = {t: 0 for t in TABLES}
    ex = env.adapters.executor
    real = ex.query

    def counting(sql: str, *a: Any, **k: Any) -> Any:
        m = re.search(r'FROM\s+"?(\w+)"?', sql)
        if m and m.group(1) in seen and sql.lstrip().upper().startswith("SELECT"):
            seen[m.group(1)] += 1
        return real(sql, *a, **k)

    ex.query = counting  # type: ignore[method-assign]
    env._seen = seen  # type: ignore[attr-defined]
    env._unwrap = lambda: setattr(ex, "query", real)  # type: ignore[attr-defined]
    return seen


def _shared_risk(env: _Env, n_agents: int) -> str:
    names = [f"ag{i}" for i in range(n_agents)]
    g = Graph()
    for a in names:
        env.agent(a)
        g.add_node(Node("system", a, attrs={"role": "agent"}))
    g.add_node(Node("model_endpoint", "ep"))
    for a in names:
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
        links=[("rule", "PAY-02"), ("pack", "pack_a"), ("monitor", "drift")],
    )["risk_id"]  # fmt: skip
    day = (env.adapters.clock.now() - dt.timedelta(days=1)).date()
    for i, a in enumerate(names):
        env.verdict(a, "PAY-02", "block", env.window_time())
        if i % 2 == 0:
            env.verdict(a, "PAY-02", "alert", env.window_time(3))
        env.pack(a, "pack_a", "ok", env.window_time())
        env.pack(a, "pack_a", "ok", env.window_time(), target_kind="trace")
        env.adapters.state.insert(
            "oversight_metric",
            {
                "metric_date": day,
                "agent_id": a,
                "computed_at": env.adapters.clock.now(),
                "monitor_status": {"drift": {"status": "ok", "code": "x", "reason": "x", "n": 1}},
            },
        )
    return rid


def _evidence_reads(n_agents: int) -> tuple[dict[str, int], dict[str, Any]]:
    env = _Env()
    try:
        rid = _shared_risk(env, n_agents)
        seen = _count_reads(env)
        out = env.svc.run_evidence()
        env._unwrap()  # type: ignore[attr-defined]
        row = env.svc.get(rid)["evidence"][0]
        return dict(seen), {"out": out, "row": {k: row[k] for k in row if k not in ("ts",)}}
    finally:
        env.close()


def test_evidence_pass_reads_do_not_grow_with_the_agents() -> None:
    few, few_out = _evidence_reads(3)
    many, many_out = _evidence_reads(12)
    assert few["verdict"] == many["verdict"] == 1
    assert few["eval_result"] == many["eval_result"] == 2  # two target kinds
    assert few["oversight_metric"] == many["oversight_metric"] == 1
    assert many_out["out"]["working"] == 1
    assert many_out["row"]["agents_n"] == 12 and few_out["row"]["agents_n"] == 3
    # 12 agents: 1 block + (6 even agents) 1 alert each = hits 18, stops 12
    assert (many_out["row"]["rule_hits"], many_out["row"]["rule_stops"]) == (18, 12)


def test_batch_and_per_row_reads_give_the_same_evidence() -> None:
    def run(batch: bool) -> tuple[dict[str, Any], dict[str, Any]]:
        env = _Env()
        try:
            rid = _shared_risk(env, 5)
            if not batch:  # a store without the batch read: the old one-query-per-row path
                env.adapters.tables.query_by = None  # type: ignore[method-assign,assignment]
                env.adapters.state.query_by = None  # type: ignore[method-assign,assignment]
            out = env.svc.run_evidence()
            row = dict(env.svc.get(rid)["evidence"][0])
            for k in ("ts", "evidence_id", "chain_hash", "risk_id", "digest"):
                row.pop(k, None)
            return out, row
        finally:
            env.close()

    assert run(True) == run(False)


def _latest_reads(n_risks: int) -> tuple[int, list[str]]:
    env = _Env()
    try:
        env.agent("pay")
        ids = [env.risk(f"risk {i}", "pay", [("rule", "PAY-02")]) for i in range(n_risks)]
        env.verdict("pay", "PAY-02", "block", env.window_time())
        env.svc.run_evidence()
        seen = _count_reads(env)
        listed = env.svc.list_risks()
        env._unwrap()  # type: ignore[attr-defined]
        states = sorted(f"{r['risk_id']}:{r['evidence_state']}" for r in listed)
        assert len(listed) == len(ids)
        return seen["risk_evidence"], states
    finally:
        env.close()


def test_risk_list_reads_evidence_in_one_statement() -> None:
    few, _ = _latest_reads(3)
    many, states = _latest_reads(15)
    assert few == many == 1
    assert all(s.endswith(":working") for s in states)


def test_evidence_rerun_checks_existing_ids_in_one_statement() -> None:
    env = _Env()
    try:
        env.agent("pay")
        for i in range(10):
            env.risk(f"r{i}", "pay", [("rule", "PAY-02")])
        env.verdict("pay", "PAY-02", "block", env.window_time())
        assert env.svc.run_evidence()["written"] == 10
        seen = _count_reads(env)
        again = env.svc.run_evidence()
        env._unwrap()  # type: ignore[attr-defined]
        assert again["repeat"] == 10 and again["written"] == 0
        assert seen["risk_evidence"] == 1
    finally:
        env.close()
