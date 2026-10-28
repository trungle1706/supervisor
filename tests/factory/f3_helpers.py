"""Helpers of the WP-F3 tests: a fake gateway ChatModel (tests only: the product has no mock path),
a gate environment on the test adapters, and synthetic golden cases (Vietnamese, no real data)."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from supervisor.evidence.signer import Ed25519FileSigner
from supervisor.factory import caps, gate, golden, probe, registry
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from supervisor.factory.store import FactoryStore

ACTOR = "reviewer.an"


class FakeChat:
    """A scripted gateway model. Agent calls answer like a careful agent (pass with a quote when a
    source of the right kind is loaded, else question); judge calls compare the expected and the
    actual verdicts in the prompt; label calls answer ``label_verdict`` (default: pass when a
    source is given, else question)."""

    family = "fake"
    model_id = "fake-gateway-1"
    is_mock = False

    def __init__(self) -> None:
        self.calls = 0
        self.judge_answer: str | None = None  # force "yes" / "no" for every judge question
        self.label_verdict: str | None = None
        self.agent_answer: Any = probe.answer_good
        self.fail_judge = False
        self.prompts: list[Mapping[str, Any]] = []

    def complete_json(self, messages: Any, json_schema: Mapping[str, Any], timeout_s: float) -> Any:
        self.calls += 1
        props = (json_schema or {}).get("properties", {})
        user = json.loads(messages[-1]["content"])
        self.prompts.append(user)
        if "findings" in props:
            return self.agent_answer(user)
        if "verdict_matches_expected" in props:
            if self.fail_judge:
                raise RuntimeError("judge down")
            exp, act = user["expected"], {a["checklist_id"]: a["verdict"] for a in user["actual"]}
            ok = all(act.get(k) == v for k, v in exp.items())
            ans = self.judge_answer or ("yes" if ok else "no")
            return {
                "verdict_matches_expected": {"answer": ans, "reason": "compared"},
                "rationale_faithful_to_evidence": {"answer": "yes", "reason": "supported"},
            }
        if "verdict" in props:
            if self.label_verdict:
                return {"verdict": self.label_verdict, "reason": "fixed"}
            return {"verdict": "pass" if user.get("sources") else "question", "reason": "sources"}
        if "score" in props:
            return {"score": 90, "reason": "good draft"}
        return {"reviews": []}


def make_env(
    adapters: Any,
    sink: Any,
    chat: Any,
    tmp: Path,
    *,
    inputs_for: Any = None,
) -> gate.GateEnv:
    settings = adapters.settings
    settings.governance_enabled = True
    settings.agent_factory = True
    settings.agent_factory_gate = True
    tools, groups = registry.load_tools(), registry.load_groups()
    store = FactoryStore(adapters.state, adapters.tables, adapters.clock, tools, groups)
    return gate.GateEnv(
        settings,
        adapters.state,
        adapters.tables,
        adapters.clock,
        sink,
        store,
        tools,
        chat,
        inputs_for,
        Ed25519FileSigner(tmp / "gate-key.pem"),
    )


def create_agent(
    env: gate.GateEnv, agent_id: str = "mr-agent", dim: str = "model"
) -> dict[str, Any]:
    return env.store.create_from_template(dim, agent_id, "Mine", ACTOR)


def case_for(
    defn: Mapping[str, Any], item: Mapping[str, Any], n: int, verdict: str = "pass"
) -> dict[str, Any]:
    """A synthetic gate case for one checklist item. The inputs hold a source of every kind the
    harness can read (refs honour the tool scopes), so a readable item can be answered."""
    inputs = probe.probe_inputs(AgentDefinitionV1.model_validate(dict(defn)), registry.load_tools())
    inputs.pop("now", None)
    inputs.pop("system_id", None)
    inputs["system"] = {
        "system_id": f"sys-{n}",
        "owner_user": "nguoi-so-huu",
        "model_version": "v3",
        "validation_date": "2026-09-01",
    }
    return {
        "case_id": f"c{n:03d}-{item['id'].lower()}",
        "inputs": inputs,
        "expected": {item["id"]: verdict},
        "expected_evidence_refs": [],
        "rubric_notes": "Vietnamese synthetic case",
    }


def readable(defn: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    """True when the harness of ``defn`` can load a source for one of the item's evidence kinds."""
    from supervisor.factory import runtime as rt

    tools = registry.load_tools()
    held = {tools.get(t["tool_id"]).kind for t in defn["tools"] if tools.get(t["tool_id"])}
    sources = defn["harness"]["context"]["sources"]
    return any(
        rt.SOURCE_OF_KIND[k] in sources and rt.TOOL_KIND_OF_SOURCE[rt.SOURCE_OF_KIND[k]] in held
        for k in item["evidence"]
    )


def golden_cases(defn: Mapping[str, Any], total: int = 50) -> list[dict[str, Any]]:
    items = defn["checklist"]
    out = []
    for i in range(total):
        item = items[i % len(items)]
        out.append(case_for(defn, item, i, "pass" if readable(defn, item) else "question"))
    return out


def load_golden(
    env: gate.GateEnv, row: Mapping[str, Any], total: int = 50, labels: int = 24
) -> None:
    cases = golden_cases(row["definition"], total)
    ok, bad = golden.check_gate_cases(cases, [c["id"] for c in row["definition"]["checklist"]])
    assert not bad, bad
    golden.store_gate_cases(env.data_dir, row["id"], ok)
    rows = [
        {
            "case_id": c["case_id"],
            "finding_id": "f-" + next(iter(c["expected"])),
            "human_verdict": "pass",
            "label_by": "reviewer.binh",
            "labelled_at": "2026-10-20T08:00:00Z",
        }
        for c in ok[:labels]
    ]
    good, bad2 = golden.check_labels(
        rows, [c["case_id"] for c in ok], [c["id"] for c in row["definition"]["checklist"]]
    )
    assert not bad2, bad2
    golden.store_labels(env.data_dir, row["id"], good)


def ready_definition(env: gate.GateEnv, row: Mapping[str, Any]) -> dict[str, Any]:
    """The template instructions already name every item; return a private copy of the row."""
    return copy.deepcopy(dict(row))


def kinds() -> tuple[str, ...]:
    return caps.GATE_KINDS


# ------------------------------------------------------------------------------ people
from supervisor.factory import promotion  # noqa: E402

AUTHOR = promotion.Actor("reviewer.an", frozenset({"reviewer"}))
LEAD = promotion.Actor("lead.model", frozenset({"approver"}), frozenset({"model_risk"}))
SECOND = promotion.Actor("second.line", frozenset({"approver"}), frozenset({"platform"}))
ADMIN = promotion.Actor("admin.chi", frozenset({"admin", "reviewer"}))
BINH = promotion.Actor("reviewer.binh", frozenset({"reviewer", "approver"}))


def to_tested(
    env: gate.GateEnv, agent_id: str = "mr-agent", version: str = "0.1"
) -> dict[str, Any]:
    """Create (when new), load the golden set and run the full gate until the version is tested."""
    row = env.store.get(agent_id, version) or create_agent(env, agent_id)
    if not golden.load_gate_cases(env.data_dir, agent_id):
        load_golden(env, row)
    run = gate.start(env, agent_id, version, "full", AUTHOR.user_id, background=False)
    assert run["verdict"] == "pass", (run["layer1"], run["layer2"])
    row = env.store.get(agent_id, version)
    assert row["state"] == "tested"
    return row


def to_live(env: gate.GateEnv, agent_id: str = "mr-agent", version: str = "0.1") -> dict[str, Any]:
    row = to_tested(env, agent_id, version)
    st, sink = env.store, env.sink
    promotion.submit(st, sink, row, AUTHOR)
    need = promotion.required_approvals(st, st.get(agent_id, version))
    if "owner_lead" in need["kinds"]:
        promotion.approve(st, sink, st.get(agent_id, version), LEAD, "owner_lead")
    if "second_line" in need["kinds"]:
        promotion.approve(st, sink, st.get(agent_id, version), SECOND, "second_line")
    return promotion.activate(st, sink, st.get(agent_id, version), LEAD)
