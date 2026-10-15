"""(c) the readiness rubric, area by area, with edge cases."""

from __future__ import annotations

from typing import Any

from supervisor.advisory.integration.analysis import ToolFacts
from supervisor.advisory.integration.scoring import RUBRIC, score
from supervisor.onboard.models import Evidence, Inventory, LlmCallSite, ToolInfo

EV = Evidence.at("a.py", 1, "def f():")


def inv(**kw: Any) -> Inventory:
    base: dict[str, Any] = {
        "agent_id": "a",
        "name": "a",
        "version": "1",
        "owner_team": "t",
        "owner_user": "u",
    }
    return Inventory(**{**base, **kw})


def tool(name: str, rc: str = "read_only", **kw: Any) -> ToolInfo:
    kw.setdefault("definition", EV)
    return ToolInfo(name=name, risk_class=rc, risk_source="heuristic", **kw)  # type: ignore[arg-type]


def pts(i: Inventory, facts: dict[str, ToolFacts] | None = None) -> dict[str, int]:
    return {a.id: a.points for a in score(i, facts).areas}


def call(family: str) -> LlmCallSite:
    return LlmCallSite(provider="p", family=family, via="sdk", evidence=EV)


def test_rubric_is_the_published_table() -> None:
    assert [(a.id, a.weight) for a in RUBRIC] == [
        ("tracing", 20),
        ("gate_coverage", 30),
        ("tool_inventory", 15),
        ("money_args", 10),
        ("model_identity", 10),
        ("manifest", 10),
        ("hygiene", 5),
    ]
    assert all(a.en and a.vi for a in RUBRIC)


def test_empty_inventory() -> None:
    r = score(inv())
    assert pts(inv()) == {
        "tracing": 0,
        "gate_coverage": 30,
        "tool_inventory": 0,
        "money_args": 10,
        "model_identity": 10,
        "manifest": 0,
        "hygiene": 5,
    }
    assert r.total == 55


def test_tracing() -> None:
    assert pts(inv(tracing=["otel"]))["tracing"] == 20
    assert pts(inv(tracing=["mlflow"]))["tracing"] == 12
    assert pts(inv(tracing=["mlflow", "otel"]))["tracing"] == 20
    assert pts(inv())["tracing"] == 0


def test_gate_coverage() -> None:
    tools = [tool("a", "money"), tool("b", "credit"), tool("c", "pii_export"), tool("r")]
    i = inv(tools=tools)
    assert pts(i)["gate_coverage"] == 0
    facts = {"a": ToolFacts(gated=True), "r": ToolFacts(gated=True)}
    assert pts(i, facts)["gate_coverage"] == 10  # 30 * 1 // 3, the read tool does not count
    facts["b"] = ToolFacts(gated=True)
    assert pts(i, facts)["gate_coverage"] == 20
    assert pts(inv(tools=[tool("r")]))["gate_coverage"] == 30


def test_tool_inventory() -> None:
    i = inv(tools=[tool("a"), tool("b", definition=None), tool("c"), tool("d")])
    assert pts(i)["tool_inventory"] == 15 * 3 // 4


def test_money_args() -> None:
    good = tool("m", "money", args={"amount_minor": "int"}, amount_arg="amount_minor")
    good.destination_arg = "to"
    assert pts(inv(tools=[good]))["money_args"] == 10
    no_dest = tool("m", "money", amount_arg="amount_minor")
    assert pts(inv(tools=[no_dest]))["money_args"] == 5
    assert pts(inv(tools=[tool("m", "money")]))["money_args"] == 0
    assert pts(inv(tools=[tool("r")]))["money_args"] == 10  # no money tool


def test_money_args_float_amount_earns_nothing() -> None:
    t = tool("m", "money", args={"amount": "float"})
    t.destination_arg = "to"
    facts = {"m": ToolFacts(amount_arg="amount", amount_float=True)}
    assert pts(inv(tools=[t]), facts)["money_args"] == 5
    facts = {"m": ToolFacts(amount_arg="amount", amount_float=False)}
    assert pts(inv(tools=[t]), facts)["money_args"] == 10


def test_model_identity() -> None:
    assert pts(inv(llm_calls=[call("openai"), call("unknown")]))["model_identity"] == 5
    assert pts(inv(llm_calls=[call("unknown")]))["model_identity"] == 0
    assert pts(inv())["model_identity"] == 10


def test_manifest_and_hygiene() -> None:
    assert pts(inv(manifest_file="manifest.yaml"))["manifest"] == 10
    assert pts(inv())["manifest"] == 0
    assert pts(inv(scrub={"secrets_redacted": 2}))["hygiene"] == 0
    assert pts(inv(secret_refs=[EV]))["hygiene"] == 0
    assert pts(inv(injection_refs=[EV]))["hygiene"] == 0
    assert pts(inv(scrub={"secrets_redacted": 0}))["hygiene"] == 5


def test_every_row_has_integer_inputs_and_a_reason() -> None:
    for a in score(inv(tools=[tool("m", "money")], tracing=["otel"])).areas:
        assert a.reason and all(type(v) is int for v in a.inputs.values())


def test_gate_coverage_counts_writing_tools_and_central_gate() -> None:
    writer = tool("w", side_effects=["db write"])
    mutator = tool("m", mutates=["replies"])
    reader = tool("r")
    i = inv(tools=[writer, mutator, reader])
    assert pts(i)["gate_coverage"] == 0  # two gated tools, none covered
    facts = {"w": ToolFacts(gated=True)}
    assert pts(i, facts)["gate_coverage"] == 15
    central = {
        t.name: ToolFacts(gated=True, gate_via="central dispatch gate at a.py:3") for t in i.tools
    }
    r = score(i, central)
    area = next(a for a in r.areas if a.id == "gate_coverage")
    assert area.points == 30 and "central dispatch gate at a.py:3" in area.reason
