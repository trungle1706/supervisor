"""W4: run one risk assessment agent over the whole AI inventory (factory.inventory_run).

A fake ChatModel and a small synthetic inventory (five systems, Vietnamese names). No network."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.factory import gate, probe
from supervisor.factory import inventory_run as inv
from tests.factory.f3_helpers import FakeChat

AGENT = "mr-agent"


def mk_system(ctx: Any, sid: str, name: str, **kw: Any) -> None:
    row = {
        "system_id": sid,
        "name": name,
        "owner_user": "nguoi-so-huu",
        "owner_team": kw.pop("team", "Nhom The"),
        "business_owner": None,
        "purpose": "He thong tong hop thu nghiem",
        "system_type": "assistant",
        "org_role": "deployer",
        "user_segment": kw.pop("segment", "internal"),
        "personal_data": kw.pop("pd", "none"),
        "money_movement": False,
        "credit_decision": False,
        "human_control": "pre_approval",
        "lifecycle_stage": kw.pop("stage", "operation"),
        "risk_level": kw.pop("level", "medium"),
        "risk_level_source": "manual",
        "risk_justification": None,
        "decision33_class": kw.pop("d33", "not_high_risk"),
        "business_impact": "medium",
        "autonomy_level": "unspecified",
        "status": kw.pop("status", "active"),
        "tags": {},
        "created_at": ctx.clock.now(),
        "created_by": "reviewer.an",
    }
    assert not kw, kw
    ctx.state.insert("ai_system", row)


@pytest.fixture
def inventory(console: Any) -> Any:
    s = console.ctx.settings
    for flag in ("governance_enabled", "agent_factory", "factory_inventory_run"):
        setattr(s, flag, True)
    ctx = console.ctx
    mk_system(ctx, "sys-a", "Tro ly tin dung", level="high", d33="high_risk", team="Nhom Tin dung")
    mk_system(ctx, "sys-b", "Chatbot khach hang", level="low", segment="customer")
    mk_system(ctx, "sys-c", "He thong cu", status="archived")
    mk_system(ctx, "sys-d", "He thong nghi huu", stage="retirement")
    mk_system(ctx, "sys-e", "He thong bi cam", level="prohibited")
    return console


class Chat(FakeChat):
    """Fails the first item for systems named in ``fail_for``, raises for ``break_for``."""

    def __init__(self, fail_for: tuple[str, ...] = (), break_for: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.fail_for, self.break_for = fail_for, break_for
        self.gate: threading.Event | None = None

    def complete_json(self, messages: Any, json_schema: Mapping[str, Any], timeout_s: float) -> Any:
        text = json.dumps(list(messages), default=str)
        if self.gate is not None:
            self.gate.wait(10)
        if any(s in text for s in self.break_for):
            raise RuntimeError("model down")
        if any(s in text for s in self.fail_for):
            self.agent_answer = probe.answer_verdict("fail")
        else:
            self.agent_answer = probe.answer_good
        return super().complete_json(messages, json_schema, timeout_s)


class StubExec:
    """The executive module of W3, as far as KEYS.md fixes it."""

    def __init__(self) -> None:
        self.built: list[str] = []

    def build(self, dim: str, report: Any, facts: Any, system: Any, definition: Any = None) -> Any:
        self.built.append(report["system_id"])
        failed = any(f["verdict"] == "fail" for f in report["findings"])
        item = {
            "key": "money_tool_no_gate",
            "severity": "high",
            "status": "fail" if failed else "pass",
            "headline": {"en": "Sends money with no approval", "vi": "Chuyen tien khong phe duyet"},
            "impact": {"en": "x", "vi": "x"},
            "action": {"en": "y", "vi": "y"},
            "owner": "security",
            "finding_ids": [],
            "fact_refs": [],
        }
        return {
            "version": 1,
            "dimension_id": dim,
            "rating": "high" if failed else "clear",
            "bottom_line": {"en": "b", "vi": "b"},
            "items": [item],
            "writer": "rules",
            "created_at": "2026-11-01T00:00:00Z",
        }

    def write(self, d: Path, doc: Mapping[str, Any]) -> str:
        p = Path(d) / f"{doc['dimension_id']}.exec.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return str(p)


def make_env(c: Any, chat: Any) -> inv.InvEnv:
    env = inv.InvEnv.from_console(c.ctx, chat)
    env.gate.store.create_from_template("model", AGENT, "Mine", "reviewer.an")
    return env


# ------------------------------------------------------------------------------ the plan


def test_derived_outcome_mapping() -> None:
    d = inv.derived_outcome
    assert d({"risk_level": "prohibited"}) == "prohibited"
    assert d({"risk_level": "high"}) == "high_self"
    assert d({"risk_level": "low", "decision33_class": "high_risk"}) == "high_self"
    assert d({"risk_level": "medium"}) == "medium"
    assert d({"risk_level": "low"}) == "low"
    assert d({"risk_level": "unspecified", "decision33_class": "unclassified"}) == "medium"
    assert d({}) == "medium"
    assert inv.level_of("high_certify") == "high" and inv.level_of("low") == "low"


def test_scope_skips_archived_retired_and_prohibited(inventory: Any) -> None:
    env = make_env(inventory, Chat())
    scope = inv.build_scope(env, "model")
    assert [i.system_id for i in scope.items] == ["sys-a", "sys-b"]
    assert scope.skipped == {"archived": 1, "retired": 1, "prohibited": 1}
    assert scope.inventory_n == 5
    a = scope.items[0]
    assert (a.level, a.outcome_source, a.owner_team) == ("high", "derived", "Nhom Tin dung")
    assert scope.items[1].customer_facing is True


def test_scope_uses_the_orchestrator_rules_for_non_core_types(inventory: Any) -> None:
    env = make_env(inventory, Chat())
    # reputation: high systems only, or medium ones that customers use (low is core-only)
    ids = [i.system_id for i in inv.build_scope(env, "reputation").items]
    assert ids == ["sys-a"]


def test_max_cuts_the_scope(inventory: Any) -> None:
    env = make_env(inventory, Chat())
    scope = inv.build_scope(env, "model", 1)
    assert len(scope.items) == 1 and scope.cut_n == 1


def test_settings_are_clamped(inventory: Any) -> None:
    s = SimpleNamespace(factory_inventory_parallel=99, factory_inventory_max=-3)
    assert inv.parallel_of(s) == 16 and inv.max_of(s) == 0
    assert inv.parallel_of(SimpleNamespace(factory_inventory_parallel=0)) == 1
    assert inv.parallel_of(SimpleNamespace()) == 4


# ------------------------------------------------------------------------------ the run


def run_sync(env: inv.InvEnv) -> dict[str, Any]:
    return inv.start(env, AGENT, "0.1", "reviewer.an", background=False)


def test_a_run_stores_a_report_and_an_executive_document_per_system(
    inventory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubExec()
    monkeypatch.setattr(inv, "_executive", lambda: stub)
    chat = Chat(fail_for=("sys-a",))
    env = make_env(inventory, chat)
    before = {t: len(inventory.ctx.state.query(t)) for t in ("ai_system", "risk_dimension_status")}
    run = run_sync(env)
    assert run["status"] == "done" and run["draft"] is True and run["agent_version"] == "0.1"
    assert (run["total"], run["done"], run["errors"]) == (2, 2, 0)
    assert run["needs_action"] == 1 and run["model_calls"] >= 2 and run["tokens"] > 0
    assert run["model_id"] == "fake-gateway-1" and run["started_by"] == "reviewer.an"
    assert sorted(stub.built) == ["sys-a", "sys-b"]
    d = inv.run_dir(env.data_dir, AGENT, run["run_id"])
    for sid in ("sys-a", "sys-b"):
        assert (d / "systems" / sid / "model.json").is_file()
        assert (d / "systems" / sid / "model.exec.json").is_file()
    rows = {r["system_id"]: r for r in inv.read_rows(d)}
    assert rows["sys-a"]["worst"] == "fail" and rows["sys-a"]["rating"] == "high"
    assert rows["sys-b"]["status"] == "assessed" and rows["sys-b"]["worst"] != "fail"
    assert rows["sys-a"]["exec_items"][0]["key"] == "money_tool_no_gate"
    # a simulation changes nothing else
    after = {t: len(inventory.ctx.state.query(t)) for t in before}
    assert after == before
    assert env.gate.store.get(AGENT, "0.1")["state"] == "draft"


def test_the_inputs_are_what_the_orchestrator_builds(inventory: Any) -> None:
    chat = Chat()
    env = make_env(inventory, chat)
    run_sync(env)
    seen = " ".join(json.dumps(p, default=str) for p in chat.prompts)
    assert "sys-a" in seen and "sys-b" in seen and "sys-c" not in seen and "sys-e" not in seen


def test_one_failing_system_is_recorded_and_the_run_goes_on(
    inventory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = inv.rt.run_agent

    def run_agent(definition: Any, inputs: Any, *a: Any, **k: Any) -> Any:
        if inputs["system_id"] == "sys-a":
            raise RuntimeError("one system broke")
        return real(definition, inputs, *a, **k)

    monkeypatch.setattr(inv.rt, "run_agent", run_agent)
    env = make_env(inventory, Chat())
    run = run_sync(env)
    assert run["status"] == "done" and (run["done"], run["errors"]) == (2, 1)
    rows = {
        r["system_id"]: r for r in inv.read_rows(inv.run_dir(env.data_dir, AGENT, run["run_id"]))
    }
    assert rows["sys-a"]["status"] == "error" and rows["sys-a"]["error"].startswith("run_broke")
    assert rows["sys-b"]["status"] == "assessed"
    assert inv.aggregate(run, list(rows.values()))["tiles"]["errors"] == 1


def test_without_the_executive_module_failed_items_stand_in(
    inventory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inv, "_executive", lambda: None)
    env = make_env(inventory, Chat(fail_for=("sys-a",)))
    run = run_sync(env)
    agg = inv.aggregate(run, inv.read_rows(inv.run_dir(env.data_dir, AGENT, run["run_id"])))
    assert agg["executive"] is False
    assert agg["risks"] and agg["risks"][0]["key"].startswith("item:") and agg["risks"][0]["n"] == 1


def test_a_broken_executive_module_does_not_fail_the_system(
    inventory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Bad:
        def build(self, *a: Any, **k: Any) -> Any:
            raise ValueError("boom")

    monkeypatch.setattr(inv, "_executive", lambda: Bad())
    env = make_env(inventory, Chat())
    run = run_sync(env)
    assert run["errors"] == 0 and run["done"] == 2


def test_refusals(inventory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_env(inventory, Chat())
    with pytest.raises(inv.InventoryError, match="not_found"):
        inv.start(env, "nope-agent", "", "reviewer.an", background=False)
    mock = Chat()
    mock.is_mock = True
    with pytest.raises(gate.GateError, match="model_not_configured"):
        inv.start(make_env_reuse(inventory, mock), AGENT, "0.1", "reviewer.an", background=False)
    monkeypatch.setitem(inv._RUNNING, AGENT, "inv_" + "0" * 20)
    with pytest.raises(inv.InventoryError, match="run_in_progress"):
        run_sync(env)


def make_env_reuse(c: Any, chat: Any) -> inv.InvEnv:
    return inv.InvEnv.from_console(c.ctx, chat)


def test_off_by_default_and_needs_the_factory(inventory: Any) -> None:
    env = make_env(inventory, Chat())
    inventory.ctx.settings.factory_inventory_run = False
    with pytest.raises(inv.InventoryError, match="factory_inventory_off"):
        run_sync(env)
    assert inv.enabled(SimpleNamespace()) is False
    inventory.ctx.settings.factory_inventory_run = True
    inventory.ctx.settings.agent_factory = False
    assert inv.enabled(inventory.ctx.settings) is False


def test_nothing_to_run(inventory: Any) -> None:
    for sid in ("sys-a", "sys-b"):
        row = inventory.ctx.state.get("ai_system", {"system_id": sid})
        inventory.ctx.state.update(
            "ai_system", {"system_id": sid}, {"status": "archived"}, row["row_version"]
        )
    env = make_env(inventory, Chat())
    with pytest.raises(inv.InventoryError, match="nothing_to_run"):
        run_sync(env)


def test_cancel_stops_after_the_systems_in_flight(inventory: Any) -> None:
    inventory.ctx.settings.factory_inventory_parallel = 1
    chat = Chat()
    chat.gate = threading.Event()
    env = make_env(inventory, chat)
    run = inv.start(env, AGENT, "0.1", "reviewer.an")
    inv.cancel(env, AGENT, run["run_id"])
    chat.gate.set()
    inv.join(AGENT)
    done = inv.read_run(env.data_dir, AGENT, run["run_id"])
    assert done["status"] == "cancelled" and done["done"] < done["total"]
    with pytest.raises(inv.InventoryError, match="not_running"):
        inv.cancel(env, AGENT, run["run_id"])


def test_a_stale_active_run_reads_as_failed(inventory: Any) -> None:
    env = make_env(inventory, Chat())
    run = run_sync(env)
    d = inv.run_dir(env.data_dir, AGENT, run["run_id"])
    doc = json.loads((d / "run.json").read_text())
    doc["status"] = "running"
    (d / "run.json").write_text(json.dumps(doc))
    got = inv.read_run(env.data_dir, AGENT, run["run_id"])
    assert got["status"] == "failed" and got["error"] == "stopped_by_restart"


def test_bad_ids_are_refused(inventory: Any) -> None:
    for bad in ("../x", "inv_zz", "", "inv_" + "0" * 19):
        with pytest.raises(inv.InventoryError, match="bad_id"):
            inv.run_dir(Path("/tmp"), AGENT, bad)
    with pytest.raises(inv.InventoryError, match="bad_id"):
        inv.run_dir(Path("/tmp"), "../etc", "inv_" + "0" * 20)


# ------------------------------------------------------------------------------ aggregation


def row(sid: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "system_id": sid,
        "name": sid,
        "owner_team": "T1",
        "level": "medium",
        "customer_facing": False,
        "status": "assessed",
        "verdicts": {"M1": "pass", "M2": "pass"},
        "worst": "pass",
        "n_fail": 0,
        "n_question": 0,
        "exec_items": [],
    }
    base.update(kw)
    return base


RUN = {
    "checklist": [
        {"id": "M1", "question": "q1", "severity": "high"},
        {"id": "M2", "question": "q2", "severity": "low"},
    ]
}


def test_aggregate_counts_keys_teams_and_levels() -> None:
    def item(key: str, status: str, sev: str = "high") -> dict[str, Any]:
        return {"key": key, "severity": sev, "status": status, "headline": {"en": "h", "vi": "h"}}

    rows = [
        row(
            "a",
            worst="fail",
            n_fail=1,
            verdicts={"M1": "fail", "M2": "pass"},
            exec_items=[item("k1", "fail"), item("k2", "open", "low")],
            level="high",
        ),
        row(
            "b",
            worst="fail",
            n_fail=1,
            verdicts={"M1": "fail", "M2": "question"},
            exec_items=[item("k1", "fail"), item("k2", "fail", "medium")],
            owner_team="T2",
        ),
        row(
            "c",
            worst="question",
            n_question=1,
            verdicts={"M1": "question", "M2": "pass"},
            exec_items=[item("k2", "open", "low")],
        ),
        row("d"),
        {"system_id": "e", "name": "e", "status": "error", "owner_team": "T2", "level": "low"},
    ]
    agg = inv.aggregate(RUN, rows)
    assert agg["tiles"] == {"needs_action": 2, "open": 1, "clear": 1, "errors": 1}
    assert agg["assessed"] == 4 and agg["executive"] is True
    # risks found: fails only, by severity then count
    assert [(r["key"], r["n"], r["severity"]) for r in agg["risks"]] == [
        ("k1", 2, "high"),
        ("k2", 1, "medium"),
    ]
    # evidence gaps: open only, a system that fails a key is not also a gap of that key
    assert [(g["key"], g["n"]) for g in agg["gaps"]] == [("k2", 2)]
    assert agg["mix"][0] == {
        "id": "M1",
        "text": "q1",
        "label": {},
        "fail": 2,
        "question": 1,
        "pass": 1,
        "not_applicable": 0,
    }
    assert [t["name"] for t in agg["by_team"]] == ["T1", "T2"] and agg["by_team"][1]["errors"] == 1
    assert [t["name"] for t in agg["by_level"]] == ["high", "medium", "low"]
    assert agg["teams"] == ["T1", "T2"]


def test_filter_rows_and_order() -> None:
    rows = [
        row("a", name="Alpha", worst="question", n_question=1, verdicts={"M1": "question"}),
        row("b", name="Beta", worst="fail", n_fail=2, customer_facing=True, level="high"),
        row("c", name="Gamma", owner_team="T9", worst="fail", n_fail=1),
    ]
    assert [r["system_id"] for r in inv.filter_rows(rows)] == ["b", "c", "a"]
    assert [r["system_id"] for r in inv.filter_rows(rows, customer="yes")] == ["b"]
    assert [r["system_id"] for r in inv.filter_rows(rows, customer="no")] == ["c", "a"]
    assert [r["system_id"] for r in inv.filter_rows(rows, team="T9")] == ["c"]
    assert [r["system_id"] for r in inv.filter_rows(rows, level="high")] == ["b"]
    assert [r["system_id"] for r in inv.filter_rows(rows, q="alp")] == ["a"]
    assert [r["system_id"] for r in inv.filter_rows(rows, bucket="needs_action")] == ["b", "c"]
    got = inv.filter_rows(rows, key="item:M1", checklist=RUN["checklist"])
    assert [r["system_id"] for r in got] == ["a"]


def test_csv_has_a_column_per_item_and_neutralises_formulas() -> None:
    rows = [
        row("a", name="=SUM(A1)", worst="fail", n_fail=1, verdicts={"M1": "fail", "M2": "pass"})
    ]
    text = inv.to_csv(RUN, rows)
    lines = text.splitlines()
    assert lines[0].split(",")[8:11] == ["rating", "M1", "M2"]
    assert "'=SUM(A1)" in lines[1] and "needs_action" in lines[1] and "fail,pass" in lines[1]


def test_a_failed_executive_finding_needs_action_even_when_the_agent_asks_a_question() -> None:
    r = row("x", worst="question", n_question=2, exec_fail=1, verdicts={"M1": "question"})
    assert inv.bucket_of(r) == "needs_action"
    assert inv.bucket_of(row("y", worst="question")) == "open"
    assert inv.bucket_of(row("z", worst="pass")) == "clear"
    assert inv.bucket_of({"status": "error"}) == "errors"
    ranked = inv.filter_rows([row("y", worst="question", n_question=3), r])
    assert [x["system_id"] for x in ranked] == ["x", "y"]


def test_check_keys_map_to_the_checklist_item_and_fold_into_the_block_key() -> None:
    res = inv.Resolver(
        [{"id": "MR-01", "key": "hardcoded_secret", "evidence": ["fact"]}, {"id": "MR-02"}]
    )
    assert res.item_id("check_mr_02") == "MR-02" and res.item_id("item:MR-01") == "MR-01"
    assert res.item_id("hardcoded_secret") == "MR-01" and res.item_id("money_tool_no_gate") == ""
    assert res.canon("check_mr_01") == "hardcoded_secret" == res.canon("hardcoded_secret")
    assert res.canon("check_mr_02") == "check_mr_02"


CHECK = {
    "checklist": [
        {
            "id": "C1",
            "question": "q1",
            "severity": "high",
            "evidence": ["fact"],
            "key": "hardcoded_secret",
            "headline_fail": {"en": "Secret in code", "vi": "Bi mat trong ma"},
            "headline_open": {"en": "Secrets not checked", "vi": "Chua kiem tra bi mat"},
        },
        {"id": "C2", "question": "q2", "severity": "high", "evidence": ["pack"], "key": "pack_a"},
        {"id": "C3", "question": "q3", "severity": "high", "evidence": ["pack"], "key": "pack_b"},
    ]
}


def test_gaps_group_every_required_test_into_one_line() -> None:
    def it(key: str, status: str) -> dict[str, Any]:
        return {"key": key, "severity": "high", "status": status, "headline": {"en": "", "vi": ""}}

    rows = [
        row("a", exec_items=[it("check_c2", "open"), it("pack_b", "open"), it("check_c1", "open")]),
        row("b", exec_items=[it("check_c2", "open"), it("hardcoded_secret", "fail")]),
        row("c", exec_items=[it("check_c3", "open")]),
        row("d", exec_items=[it("no_tracing", "open")]),
    ]
    agg = inv.aggregate(CHECK, rows)
    pack = agg["gaps"][0]
    assert (pack["key"], pack["kind"], pack["n"], pack["items"]) == (inv.GAP_PACK, "pack", 3, 2)
    others = {g["key"]: g["n"] for g in agg["gaps"][1:]}
    assert others == {"hardcoded_secret": 1, "no_tracing": 1}  # system b fails it: not a gap
    assert [(r["key"], r["n"]) for r in agg["risks"]] == [("hardcoded_secret", 1)]
    assert agg["risks"][0]["text"]["en"] == "Secret in code"
    assert not any(
        r["key"].startswith("pack") or r["key"].startswith("check_") for r in agg["risks"]
    )
    # the mix label is the executive headline when the item has one
    assert agg["mix"][0]["label"]["en"] == "Secret in code" and agg["mix"][1]["label"] == {}
    got = inv.filter_rows(rows, key=inv.GAP_PACK, checklist=CHECK["checklist"])
    assert sorted(r["system_id"] for r in got) == ["a", "b", "c"]
    got = inv.filter_rows(
        rows, key="hardcoded_secret", kstatus="open", checklist=CHECK["checklist"]
    )
    assert [r["system_id"] for r in got] == ["a"]
    got = inv.filter_rows(
        rows, key="hardcoded_secret", kstatus="fail", checklist=CHECK["checklist"]
    )
    assert [r["system_id"] for r in got] == ["b"]


def test_run_json_keeps_the_executive_wording_of_the_definition(inventory: Any) -> None:
    env = make_env(inventory, Chat())
    run = run_sync(env)
    first = run["checklist"][0]
    assert first["evidence"] and "question" in first and "severity" in first
    blocks = [c for c in run["checklist"] if c.get("key")]
    for c in blocks:
        assert c["headline_fail"]["en"] and c["headline_open"]["vi"]
