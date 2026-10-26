"""WP-N1: candidate triage. Every signal, the score, the actions, the overrides, a golden test on
a fixture graph, and a test that no workspace URL or id reaches a row. Pure: no store, no web."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from supervisor.governance import triage
from supervisor.governance.next_action import describe_agent, describe_system, recommend
from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Node


def mk(g: Graph, kind: str, name: str, **kw: Any) -> Node:
    attrs = kw.pop("attrs", {})
    n = Node(kind, name, attrs=attrs, **kw)
    n.add_evidence("workspace_scan", f"workspace:{kind}/{name}")
    g.add_node(n)
    return g.nodes[n.node_id]


def app(g: Graph, name: str = "demo", **attrs: Any) -> Node:
    return mk(
        g,
        "system",
        f"app:{name}",
        display_name=name,
        status="unmanaged",
        attrs={"role": "databricks_app", "workspace_kind": "app", **attrs},
    )


def endpoint(g: Graph, name: str = "ep", **attrs: Any) -> Node:
    return mk(g, "model_endpoint", name, status="unmanaged", attrs=attrs)


def rows_of(g: Graph, **kw: Any) -> dict[str, dict[str, Any]]:
    return {r["name"]: r for r in triage.triage(g, **kw)}


# ------------------------------------------------------------------ candidates


def test_only_unmanaged_candidates_of_the_four_kinds_are_listed() -> None:
    g = Graph()
    app(g, "a1")
    mk(g, "system", "agent-x", attrs={"role": "agent"}, status="unmanaged")  # an agent, not an app
    app(g, "known").status = "active"  # managed
    endpoint(g, "plain-llm", task="llm/v1/chat")  # not an agent endpoint
    endpoint(g, "agent-ep", agent_endpoint=True)
    endpoint(g, "agent-task", task="agent")
    mk(g, "genie_space", "space", status="unmanaged")
    mk(g, "job", "job1", status="unmanaged")
    mk(g, "dataset", "main.x.t", status="unmanaged")
    got = {r["name"]: r["kind"] for r in triage.triage(g)}
    assert got == {
        "a1": "app",
        "agent-ep": "endpoint",
        "agent-task": "endpoint",
        "space": "genie_space",
        "job1": "job",
    }


def test_exclude_leaves_a_node_out() -> None:
    g = Graph()
    n = app(g, "a1")
    assert triage.triage(g, exclude={n.node_id}) == []


# ------------------------------------------------------------------ one test per signal


def test_signal_external_model_via_linked_endpoint() -> None:
    g = Graph()
    a = app(g, "a")
    e = endpoint(g, "gpt", external_providers=["openai"])
    g.link(a, "uses", e, "workspace_scan", "r")
    r = rows_of(g)["a"]
    assert "external_model" in r["signals"] and r["impact"] == 20
    assert r["facts"]["providers"] == ["openai"]


def test_signal_external_model_on_the_endpoint_itself() -> None:
    g = Graph()
    endpoint(g, "gpt-agent", agent_endpoint=True, external_providers=["openai"])
    r = rows_of(g)["gpt-agent"]
    assert r["signals"][:2] == ["external_model", "agent_endpoint"] and r["impact"] == 30


@pytest.mark.parametrize(
    "table,fires",
    [
        ("main.lending.loan_applications", True),
        ("main.crm.customer_master", True),
        ("main.crm.customers", True),
        ("main.pay.thanh_toan_2026", True),
        ("main.cards.the_tin_dung", True),
        ("main.core.tai_khoan", True),
        ("main.pay.txn_log", True),
        ("main.ops.other_stuff", False),  # "the" inside "other" must not match
        ("main.ops.daily_summary", False),
    ],
)
def test_signal_customer_table(table: str, fires: bool) -> None:
    g = Graph()
    s = mk(g, "genie_space", "sp", status="unmanaged")
    g.link(s, "reads", mk(g, "dataset", table), "workspace_scan", "r")
    r = rows_of(g)["sp"]
    assert ("customer_table" in r["signals"]) is fires
    assert r["impact"] == (35 if fires else 10)  # genie space adds 10


@pytest.mark.parametrize(
    "cls,fires", [("money", True), ("credit", True), ("pii_export", True), ("read_only", False)]
)
def test_signal_money_tool(cls: str, fires: bool) -> None:
    g = Graph()
    a = app(g, "a")
    t = mk(g, "tool", "do_it", attrs={"risk_class": cls})
    g.link(a, "uses", t, "workspace_scan", "r")
    r = rows_of(g)["a"]
    assert ("money_tool" in r["signals"]) is fires
    assert r["impact"] == (30 if fires else 5)  # nothing scoring: "unknown" 5


def test_signal_money_tool_on_a_uc_function() -> None:
    g = Graph()
    a = app(g, "a")
    g.link(
        a,
        "uses",
        mk(g, "uc_function", "main.x.pay", attrs={"risk_class": "money"}),
        "workspace_scan",
        "r",
    )
    assert "money_tool" in rows_of(g)["a"]["signals"]


def test_signal_writes_only_for_a_job() -> None:
    g = Graph()
    j = mk(g, "job", "j", status="unmanaged")
    g.link(j, "writes", mk(g, "dataset", "main.ops.out"), "workspace_scan", "r")
    a = app(g, "a")
    g.link(a, "writes", mk(g, "dataset", "main.ops.out2"), "workspace_scan", "r")
    rows = rows_of(g)
    assert "writes" in rows["j"]["signals"] and rows["j"]["impact"] == 10
    assert "writes" not in rows["a"]["signals"]


def test_signal_agent_endpoint_and_genie_space() -> None:
    g = Graph()
    endpoint(g, "e", agent_endpoint=True)
    mk(g, "genie_space", "s", status="unmanaged")
    rows = rows_of(g)
    assert rows["e"]["signals"] == ["agent_endpoint", "no_owner"] and rows["e"]["impact"] == 10
    assert rows["s"]["signals"] == ["genie_space", "no_owner"] and rows["s"]["impact"] == 10


def test_signal_app_with_an_agent_endpoint_behind_it() -> None:
    g = Graph()
    a = app(g, "a")
    g.link(a, "uses", endpoint(g, "e", agent_endpoint=True), "workspace_scan", "r")
    r = rows_of(g)["a"]
    assert "app_agent" in r["signals"] and r["impact"] == 10


def test_signal_unknown_when_nothing_scores_and_owner_group_adds_nothing() -> None:
    g = Graph()
    app(g, "bare")
    app(g, "owned", owner_group="lending")
    rows = rows_of(g)
    assert rows["bare"]["signals"] == ["unknown", "no_owner"] and rows["bare"]["impact"] == 5
    assert rows["owned"]["signals"] == ["unknown"] and rows["owned"]["impact"] == 5


def test_signal_scheduled_is_shown_and_scores_nothing() -> None:
    g = Graph()
    mk(g, "job", "j", status="unmanaged", attrs={"schedule": "0 2 * * *", "owner_group": "x"})
    r = rows_of(g)["j"]
    assert "scheduled" in r["signals"] and r["impact"] == 5  # only "unknown" scores


def test_impact_is_capped_at_100() -> None:
    assert (
        triage.impact_of(
            [
                "external_model",
                "customer_table",
                "money_tool",
                "writes",
                "agent_endpoint",
            ]
        )
        == 95
    )
    assert triage.impact_of(list(triage.SIGNALS) * 3) == 100


def test_signal_points_table_matches_the_plan() -> None:
    pts = {k: v[0] for k, v in triage.SIGNALS.items()}
    assert pts == {
        "external_model": 20,
        "customer_table": 25,
        "money_tool": 30,
        "writes": 10,
        "agent_endpoint": 10,
        "genie_space": 10,
        "app_agent": 10,
        "unknown": 5,
        "scheduled": 0,
        "no_owner": 0,
    }


# ------------------------------------------------------------------ autonomy, complexity, score


def test_autonomy_rules() -> None:
    g = Graph()
    mk(g, "genie_space", "genie", status="unmanaged")
    endpoint(g, "ep-plain", agent_endpoint=True)
    a_tools = app(g, "tools")
    g.link(
        a_tools,
        "uses",
        mk(g, "tool", "t1", attrs={"risk_class": "read_only"}),
        "workspace_scan",
        "r",
    )
    app(g, "bare")
    job_w = mk(g, "job", "job-w", status="unmanaged", attrs={"schedule": "daily"})
    g.link(job_w, "writes", mk(g, "dataset", "main.o.x"), "workspace_scan", "r")
    mk(g, "job", "job-plain", status="unmanaged")
    rows = rows_of(g)
    assert rows["genie"]["autonomy"] == "l1_assistive"
    assert rows["ep-plain"]["autonomy"] == "l1_assistive"
    assert rows["tools"]["autonomy"] == "l3_tool_using_supervised"
    assert rows["bare"]["autonomy"] == "unspecified"
    assert rows["job-w"]["autonomy"] == "l4_autonomous_bounded"
    assert rows["job-plain"]["autonomy"] == "unspecified"


def test_autonomy_proposal_wins_when_valid() -> None:
    g = Graph()
    app(g, "p1", autonomy_proposal="l2_workflow_step")
    app(g, "p2", autonomy_proposal="l9_bogus")
    rows = rows_of(g)
    assert rows["p1"]["autonomy"] == "l2_workflow_step"
    assert rows["p2"]["autonomy"] == "unspecified"


@pytest.mark.parametrize("n,base", [(0, 0), (1, 30), (2, 30), (3, 60), (5, 60), (6, 90), (9, 90)])
def test_complexity_scale(n: int, base: int) -> None:
    f = {"linked_n": n, "providers": []}
    assert triage.complexity_of(f) == base
    assert triage.complexity_of({"linked_n": n, "providers": ["openai"]}) == min(100, base + 10)


def test_complexity_counts_models_tools_datasets_and_mcp_servers() -> None:
    g = Graph()
    a = app(g, "a")
    for kind, name in (
        ("model", "m"),
        ("tool", "t"),
        ("dataset", "main.o.d"),
        ("mcp_server", "srv"),
    ):
        g.link(a, "uses", mk(g, kind, name), "workspace_scan", "r")
    g.link(a, "uses", endpoint(g, "e"), "workspace_scan", "r")  # an endpoint is not counted
    assert rows_of(g)["a"]["complexity"] == 60


def test_score_formula_and_rank() -> None:
    assert triage.score_of(0, "l0_rule_based", 0) == 0
    assert triage.score_of(0, "unspecified", 0) == 10  # unspecified ranks 1
    assert triage.score_of(100, "l5_self_directed", 100) == 100  # 60 + 50 + 20 = 130, capped
    assert triage.score_of(85, "l3_tool_using_supervised", 40) == 89
    assert triage.score_of(35, "l1_assistive", 30) == 37
    assert isinstance(triage.score_of(33, "l2_workflow_step", 33), int)


# ------------------------------------------------------------------ recommended action


def test_recommended_action_order() -> None:
    assert triage.action_of(70, ["money_tool"]) == "register_now"
    assert triage.action_of(69, ["money_tool", "external_model"]) == "register_and_classify"
    assert triage.action_of(30, ["customer_table"]) == "register_and_classify"
    assert triage.action_of(30, ["external_model"]) == "register_review_vendor"
    assert triage.action_of(30, ["unknown"]) == "register_when_convenient"
    assert set(triage.ACTIONS) == {
        "register_now",
        "register_and_classify",
        "register_review_vendor",
        "register_when_convenient",
    }


def test_score_bands() -> None:
    assert [triage.band_of(s) for s in (0, 39, 40, 69, 70, 100)] == [
        "low",
        "low",
        "medium",
        "medium",
        "high",
        "high",
    ]


# ------------------------------------------------------------------ overrides


def test_override_from_attrs_replaces_fields_and_recomputes_the_score() -> None:
    g = Graph()
    app(g, "a", triage={"impact": 90, "description": "Richer text from the analyst."})
    r = rows_of(g)["a"]
    assert r["from_override"] and r["impact"] == 90
    assert r["description"] == "Richer text from the analyst."
    assert r["score"] == triage.score_of(90, r["autonomy"], r["complexity"])


def test_override_argument_wins_and_bad_fields_are_ignored() -> None:
    g = Graph()
    n = app(g, "a", triage={"impact": 90})
    rows = triage.triage(
        g,
        overrides={
            n.node_id: {
                "impact": 10,
                "score": 55,
                "autonomy": "l9",
                "recommended_action": "do_it_now",
                "signals": ["money_tool", "bogus"],
                "evil": 1,
            }
        },
    )
    r = rows[0]
    assert (r["impact"], r["score"]) == (10, 55)
    assert r["autonomy"] == "unspecified"  # invalid value ignored
    assert r["recommended_action"] == triage.action_of(55, ["money_tool"])
    assert r["signals"] == ["money_tool"]
    assert "evil" not in r


def test_override_action_is_kept_when_valid() -> None:
    g = Graph()
    n = app(g, "a")
    r = triage.triage(g, overrides={n.node_id: {"recommended_action": "register_now"}})[0]
    assert (
        r["recommended_action"] == "register_now" and r["reason_key"] == "tri_reason_register_now"
    )


# ------------------------------------------------------------------ golden


def golden_graph() -> Graph:
    """App, endpoint with an external provider, customer table, money tool, Genie space, job."""
    g = Graph()
    a = app(g, "loan-copilot", owner_group="lending")
    gpt = endpoint(g, "gpt-gateway", task="llm/v1/chat", external_providers=["openai"])
    memo = endpoint(g, "agent-credit-memo", agent_endpoint=True)
    loans = mk(g, "dataset", "main.lending.loan_applications", attrs={"workspace_kind": "uc_table"})
    pay = mk(g, "tool", "transfer_money", attrs={"risk_class": "money"})
    g.link(a, "uses", gpt, "workspace_scan", "r1")
    g.link(a, "uses", memo, "workspace_scan", "r2")
    g.link(a, "reads", loans, "workspace_scan", "r3")
    g.link(a, "uses", pay, "workspace_scan", "r4")
    g.link(memo, "serves", mk(g, "model", "main.ml.credit_memo_agent"), "workspace_scan", "r5")
    c = endpoint(
        g, "gpt-agent", agent_endpoint=True, external_providers=["openai"], owner_group="ai"
    )
    g.link(
        c, "serves", mk(g, "model", "gpt-4o", attrs={"family": "openai"}), "workspace_scan", "r6"
    )
    sp = mk(
        g, "genie_space", "Lending analytics", status="unmanaged", attrs={"owner_group": "lending"}
    )
    g.link(sp, "reads", loans, "workspace_scan", "r7")
    job = mk(g, "job", "nightly-memo-batch", status="unmanaged", attrs={"schedule": "0 2 * * *"})
    g.link(job, "uses", gpt, "workspace_scan", "r8")
    g.link(job, "writes", mk(g, "dataset", "main.ops.daily_summary"), "workspace_scan", "r9")
    app(g, "managed").status = "active"
    return g


GOLDEN = [
    # name, kind, impact, autonomy, complexity, score, signals, action
    (
        "loan-copilot",
        "app",
        85,
        "l3_tool_using_supervised",
        70,
        95,
        ["external_model", "customer_table", "money_tool", "app_agent"],
        "register_now",
    ),
    (
        "nightly-memo-batch",
        "job",
        30,
        "l4_autonomous_bounded",
        40,
        66,
        ["external_model", "writes", "scheduled", "no_owner"],
        "register_review_vendor",
    ),
    (
        "Lending analytics",
        "genie_space",
        35,
        "l1_assistive",
        30,
        37,
        ["customer_table", "genie_space"],
        "register_and_classify",
    ),
    (
        "gpt-agent",
        "endpoint",
        30,
        "l1_assistive",
        40,
        36,
        ["external_model", "agent_endpoint"],
        "register_review_vendor",
    ),
    (
        "agent-credit-memo",
        "endpoint",
        10,
        "l1_assistive",
        30,
        22,
        ["agent_endpoint", "no_owner"],
        "register_when_convenient",
    ),
]


def test_golden_fixture_graph() -> None:
    rows = triage.triage(golden_graph())
    got = [
        (
            r["name"],
            r["kind"],
            r["impact"],
            r["autonomy"],
            r["complexity"],
            r["score"],
            r["signals"],
            r["recommended_action"],
        )
        for r in rows
    ]
    assert got == [tuple(x) for x in GOLDEN]
    top = rows[0]
    assert top["description"] == (
        "Databricks App `loan-copilot` in group `lending`; calls endpoint `agent-credit-memo`, "
        "`gpt-gateway` (external provider `openai`); reads 1 customer table; "
        "calls 1 money or credit tool."
    )
    assert top["reason_key"] == "tri_reason_register_now" and top["band"] == "high"
    assert all(isinstance(r[k], int) for r in rows for k in ("impact", "complexity", "score"))


def test_golden_is_stable_when_nodes_are_added_in_another_order() -> None:
    g1 = golden_graph()
    g2 = Graph()
    for n in reversed(list(g1.nodes.values())):
        g2.add_node(n)
    for e in reversed(list(g1.edges.values())):
        g2.add_edge(e)
    assert triage.triage(g1) == triage.triage(g2)


def test_filters() -> None:
    rows = triage.triage(golden_graph())
    assert [r["name"] for r in triage.filter_rows(rows, kind="endpoint")] == [
        "gpt-agent",
        "agent-credit-memo",
    ]
    assert [r["name"] for r in triage.filter_rows(rows, signal="customer_table")] == [
        "loan-copilot",
        "Lending analytics",
    ]
    assert [r["name"] for r in triage.filter_rows(rows, band="high")] == ["loan-copilot"]
    assert triage.filter_rows(rows, kind="job", band="high") == []


# ------------------------------------------------------------------ no workspace id or URL


def test_no_workspace_url_or_id_reaches_a_row() -> None:
    host = "https://adb-" + "1234567890123456" + ".7." + "azure" + "databricks.net"
    g = Graph()
    a = mk(
        g,
        "system",
        "app:leaky",
        display_name=f"leaky {host}/apps/leaky",
        status="unmanaged",
        attrs={
            "role": "databricks_app",
            "owner_group": "grp-1234567890123456",
            "workspace_url": host,
        },
    )
    a.add_evidence("workspace_scan", f"{host}/api/2.0/apps/leaky")
    a.add_evidence("workspace_scan", "dbc-" + "a1b2c3d4-e5f6.cloud.databricks.com")
    e = endpoint(g, "ep-agent", agent_endpoint=True, workspace_id="1234567890123456")
    e.add_evidence("workspace_scan", "workspace:serving-endpoint/ep-agent")
    g.link(a, "uses", e, "workspace_scan", "r")
    ds = mk(g, "dataset", "main.lending.loan_1234567890123456")
    g.link(a, "reads", ds, "workspace_scan", "r")
    g.nodes[e.node_id].attrs["triage"] = {
        "description": f"See {host}/x for workspace 1234567890123456."
    }
    blob = json.dumps(triage.triage(g))
    assert "http" not in blob and "azuredatabricks" not in blob and "dbc-" not in blob
    assert not re.search(r"\d{10,}", blob)
    assert "leaky" in blob  # the name stays


def test_scrub() -> None:
    assert triage.scrub("a https://x.example/y b") == "a [url removed] b"
    assert triage.scrub("id 1234567890") == "id [id removed]"
    assert triage.scrub("plain name") == "plain name"


# ------------------------------------------------------------------ next_action


def sysrow(**kw: Any) -> dict[str, Any]:
    return {
        "system_id": "sys_1",
        "decision33_class": "high_risk",
        "purpose": "  A   purpose. ",
        **kw,
    }


def task(title: str = "T", overdue: bool = False, **kw: Any) -> dict[str, Any]:
    return {
        "agent_id": "sys_1",
        "required": True,
        "status": "open",
        "task_id": "t1",
        "title": title,
        "overdue": overdue,
        "due_at": None,
        **kw,
    }


def rec(**kw: Any) -> str:
    base: dict[str, Any] = dict(
        system=sysrow(),
        agents=[],
        tasks=[],
        waiting={},
        can_decide=False,
        below_floor=[],
        shadow_agents=[],
        open_cases=0,
    )
    base.update(kw)
    return recommend(**base)["key"]


def test_next_action_rule_order() -> None:
    wait = {"sys_1": {"from_stage": "design", "to_stage": "validation"}}
    everything = dict(
        tasks=[task(overdue=True)],
        waiting=wait,
        can_decide=True,
        system=sysrow(decision33_class="unclassified"),
        below_floor=["pii"],
        shadow_agents=["a"],
        open_cases=2,
        agents=["a"],
    )
    assert rec(**everything) == "finish_task_overdue"
    everything["tasks"] = []
    assert rec(**everything) == "approve_stage"
    everything["can_decide"] = False
    assert rec(**everything) == "classify"
    everything["system"] = sysrow()
    assert rec(**everything) == "switch_on"
    everything["below_floor"] = []
    assert rec(**everything) == "triage_case"  # an open case beats the shadow rule
    everything["open_cases"] = 0
    assert rec(**everything) == "request_running"
    everything["shadow_agents"] = []
    assert rec(**everything) == "none"
    assert rec(open_cases=1) == "triage_case"
    assert rec(tasks=[task()]) == "finish_task"
    assert rec(shadow_agents=["a"], open_cases=1) == "triage_case"  # shadow rule needs no open case


def test_next_action_text_and_href() -> None:
    r = recommend(
        system=sysrow(),
        agents=[],
        tasks=[task("Fix X", overdue=True)],
        waiting={},
        can_decide=False,
        below_floor=[],
        shadow_agents=[],
        open_cases=0,
    )
    assert r == {"key": "finish_task_overdue", "arg": "Fix X", "href": "/console/tasks"}
    r = recommend(
        system=sysrow(),
        agents=[],
        tasks=[],
        waiting={},
        can_decide=False,
        below_floor=["pii_mask"],
        shadow_agents=[],
        open_cases=0,
    )
    assert r["arg"] == "pii_mask" and r["href"].endswith("tab=guardians")


def test_agent_without_a_system_skips_the_system_rules() -> None:
    r = recommend(
        system=None,
        agents=["a1"],
        tasks=[],
        waiting={},
        can_decide=True,
        below_floor=[],
        shadow_agents=["a1"],
        open_cases=0,
        owner_id="a1",
    )
    assert r["key"] == "request_running"


def test_descriptions() -> None:
    assert describe_system(sysrow()) == "A purpose."
    text = describe_agent(
        {
            "agent_id": "pay",
            "name": "Pay",
            "model_family": "qwen",
            "host_type": "app",
            "tools_n": 3,
            "risk_tier": "high",
        }
    )
    assert text == "Agent Pay: model family qwen, hosted as app, 3 tools, risk tier high."
    assert describe_agent({"agent_id": "x"}) == "Agent x."


def test_safe_ref_keeps_only_name_and_line() -> None:
    from supervisor.governance.triage import safe_ref

    assert safe_ref("workspace:job/nightly") == "workspace:job/nightly"
    assert safe_ref("/home/ops/repo/agents/a.yaml:12") == "a.yaml:12"
    assert safe_ref("C:\\work\\a.yaml:3") == "a.yaml:3"
    assert safe_ref("agents/a.yaml") == "a.yaml"
    assert safe_ref("manifest.yaml:7") == "manifest.yaml:7"
