"""WP-F5: the six starter agents, the two templates, their golden sets, the seed command and the
fake-model gate run (development path)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.factory import caps, devfake, gate, golden, linter, registry, starters, store
from supervisor.factory.__main__ import main, validate_file
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from tests.factory.f3_helpers import FakeChat, make_env
from tools import factory_golden_gen as gen

DIR = starters.STARTERS_DIR
SIX = starters.STARTER_IDS
TEMPLATES = starters.TEMPLATE_IDS
DIMENSION = {
    "model-risk-assessor": "model",
    "data-governance-assessor": "data_governance",
    "cyber-assessor": "cybersecurity",
    "legal-compliance-assessor": "legal_compliance",
    "third-party-assessor": "third_party",
    "ethics-assessor": "ethics",
}


def definition(agent_id: str) -> dict[str, Any]:
    doc = yaml.safe_load((DIR / f"{agent_id}.yaml").read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def cases(agent_id: str) -> list[dict[str, Any]]:
    return json.loads((DIR / "golden" / agent_id / "cases.json").read_text(encoding="utf-8"))


def labels(agent_id: str) -> list[dict[str, Any]]:
    return json.loads((DIR / "golden" / agent_id / "calibration.json").read_text(encoding="utf-8"))


@pytest.fixture
def env(adapters: Any, sink: Any, tmp_path: Path) -> gate.GateEnv:
    return make_env(adapters, sink, FakeChat(), tmp_path)


# ------------------------------------------------------------------------------ definitions


@pytest.mark.parametrize("agent_id", [*SIX, *TEMPLATES])
def test_definition_validates(agent_id: str) -> None:
    name, errors = validate_file(DIR / f"{agent_id}.yaml", None)
    assert (name, errors) == ("agent_definition_v1", [])
    d = definition(agent_id)
    model = store.validate_definition(d, registry.load_tools(), registry.load_groups())
    assert model.lifecycle.state == "draft" and model.lifecycle.approvals == []
    assert caps.estimate_tokens(model.instructions) <= 2500
    assert not any(i.severity == "error" for i in linter.lint_definition(d))
    assert linter.is_ready(linter.lint_definition(d))  # every checklist id is named
    assert model.guardians[:3] == list(caps.MANDATORY_GUARDIANS)
    for item in model.checklist:
        assert re.search(r"Art\. \d+", item.question), item.id  # the article pointer is in the text
        assert item.pass_rule


@pytest.mark.parametrize("agent_id", SIX)
def test_starter_shape(agent_id: str) -> None:
    d = AgentDefinitionV1.model_validate(definition(agent_id))
    assert d.dimension_id == DIMENSION[agent_id]
    assert 8 <= len(d.checklist) <= 14
    assert d.policy_refs and d.policy_refs[0].doc_id == "VN-TT53-2026"
    assert d.eval_pack == f"{agent_id}-golden-v1"
    loop = d.harness.loop
    if agent_id == "cyber-assessor":
        assert (loop.mode, loop.loop_evaluator, loop.max_iterations) == ("loop", "rules", 3)
    else:
        assert loop.mode == "single_pass"


@pytest.mark.parametrize("agent_id", TEMPLATES)
def test_templates_are_marked_and_empty(agent_id: str) -> None:
    d = definition(agent_id)
    assert "TEMPLATE" in d["description"] and d["lifecycle"]["state"] == "draft"
    assert cases(agent_id) == []
    assert not (DIR / "golden" / agent_id / "calibration.json").exists()


def test_pack_items_read_the_pack_result() -> None:
    """The checklist items that a pack measures read the pack result through the tool and pass
    when the pack passed at the current version."""
    dims = yaml.safe_load(
        (Path(registry.__file__).parents[3] / "config/risk_dimensions.yaml").read_text()
    )
    measured = {
        d["id"]: {m["id"] for m in d["measured_by"] if m["kind"] == "pack"}
        for d in dims["dimensions"]
    }
    for agent_id in SIX:
        d = definition(agent_id)
        pack_items = [c for c in d["checklist"] if c["evidence"] == ["pack"]]
        mentioned = {
            p for c in pack_items for p in re.findall(r"[a-z0-9]+(?:_[a-z0-9]+)+", c["question"])
        }
        # each pack of a pack item is a real measured_by pack of the dimension
        assert mentioned <= measured[d["dimension_id"]], (agent_id, mentioned)
        if pack_items:
            assert any(t["tool_id"] == "read_pack_results" for t in d["tools"])
            assert all("current version" in c["pass_rule"] for c in pack_items)
    # every required pack of the dimension is mapped by the agent that owns it
    required = {
        d["id"]: {m["id"] for m in d["measured_by"] if m["kind"] == "pack" and m["required"]}
        for d in dims["dimensions"]
    }
    for agent_id in SIX:
        d = definition(agent_id)
        text = " ".join(c["question"] for c in d["checklist"])
        for pack in required[d["dimension_id"]]:
            assert pack in text, (agent_id, pack)


# ------------------------------------------------------------------------------ golden sets


@pytest.mark.parametrize("agent_id", SIX)
def test_golden_stratification(agent_id: str) -> None:
    d = definition(agent_id)
    ids = [c["id"] for c in d["checklist"]]
    rows = cases(agent_id)
    ok, bad = golden.check_gate_cases(rows, ids)
    assert not bad and len(ok) == len(rows) >= 50
    strat = golden.gate_stratification(ok, ids)
    assert strat["ready"], strat["problems"]
    assert all(n >= 3 for n in strat["per_item"].values()), strat["per_item"]
    assert strat["per_verdict"]["pass"] and strat["per_verdict"]["fail"]
    assert strat["per_verdict"]["question"]
    lab = labels(agent_id)
    good, bad2 = golden.check_labels(lab, [c["case_id"] for c in rows], ids)
    assert not bad2 and len(good) >= 20
    assert {r["label_by"] for r in lab} == {"synthetic.labeller"}


@pytest.mark.parametrize("agent_id", SIX)
def test_expected_refs_point_at_the_case_inputs(agent_id: str) -> None:
    for c in cases(agent_id):
        refs = set(devfake._refs_of(c["inputs"]))
        want = c["expected_evidence_refs"]
        verdict = next(iter(c["expected"].values()))
        assert set(want) <= refs, c["case_id"]
        assert (verdict == "question") == (not want) or verdict == "not_applicable" or want
        if verdict in ("pass", "fail"):
            assert want, c["case_id"]


@pytest.mark.parametrize("agent_id", SIX)
def test_no_personal_data_in_any_case(agent_id: str) -> None:
    def strings(v: Any) -> Any:
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for k, x in v.items():
                yield k
                yield from strings(x)
        elif isinstance(v, list):
            for x in v:
                yield from strings(x)

    for c in cases(agent_id):
        for text in strings(c):
            assert not golden.trips_masker(text), (c["case_id"], text[:60])
    for r in labels(agent_id):
        assert not any(golden.trips_masker(t) for t in strings(r))


def test_generator_output_is_current() -> None:
    """The committed golden files are exactly what the generator writes (same seed, same bytes)."""
    for path, text in gen.build().items():
        assert path.read_text(encoding="utf-8") == text, path.name


# ------------------------------------------------------------------------------ seed


def test_seed_creates_six_drafts_and_two_templates_once(env: gate.GateEnv) -> None:
    first = starters.seed(env.store, env.data_dir)
    assert first["created"] == [*SIX, *TEMPLATES] and first["skipped"] == []
    rows = {r["id"]: r for r in env.store.list_agents()}
    assert set(rows) == {*SIX, *TEMPLATES}
    assert {r["state"] for r in rows.values()} == {"draft"}
    for agent_id in SIX:
        assert len(golden.load_gate_cases(env.data_dir, agent_id)) == len(cases(agent_id))
        assert len(golden.load_labels(env.data_dir, agent_id)) == len(labels(agent_id))
    for agent_id in TEMPLATES:
        assert golden.load_gate_cases(env.data_dir, agent_id) == []
    before = [(r["id"], r["version"], r["row_version"]) for r in env.store.list_agents()]
    second = starters.seed(env.store, env.data_dir)
    assert second["created"] == [] and sorted(second["skipped"]) == sorted([*SIX, *TEMPLATES])
    assert before == [(r["id"], r["version"], r["row_version"]) for r in env.store.list_agents()]
    assert len(env.store.events("model-risk-assessor")) == 2  # created, golden_uploaded


def test_seed_keeps_a_team_edit(env: gate.GateEnv) -> None:
    starters.seed(env.store, env.data_dir)
    row = env.store.get("ethics-assessor", "0.1")
    edited = json.loads(json.dumps(row["definition"]))
    edited["description"] = "Edited by the ethics group."
    env.store.save_draft("ethics-assessor", "0.1", edited, "reviewer.an", row["row_version"])
    starters.seed(env.store, env.data_dir)
    assert env.store.get("ethics-assessor", "0.1")["definition"]["description"].startswith("Edited")


def test_seed_cli(env: gate.GateEnv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["seed"], gate_env=env) == 0
    out = capsys.readouterr().out
    assert out.count("[OK] created") == 8 and "template supply-chain-assessor" in out
    assert main(["seed"], gate_env=env) == 0
    assert capsys.readouterr().out.count("[SKIP]") == 8


def test_seed_flag_is_off_by_default(adapters: Any) -> None:
    from supervisor.config import Settings

    assert Settings.model_fields["factory_seed_starters"].default is False
    assert starters.seed_for_runtime(adapters.settings, object()) is None


# ------------------------------------------------------------------------------ the fake gate


@pytest.mark.parametrize("agent_id", SIX)
def test_full_gate_with_fake_model_layer1_is_100(
    env: gate.GateEnv, agent_id: str, capsys: pytest.CaptureFixture[str]
) -> None:
    starters.seed(env.store, env.data_dir)
    code = main(["gate", agent_id, "--kind", "full", "--model", "fake"], gate_env=env)
    out = capsys.readouterr().out
    run = gate.latest_runs(env, agent_id, None, 1)[0]
    assert run["status"] == "done", out
    assert run["layer1"]["percent"] == 100 and run["layer1"]["ok"], run["layer1"]
    assert run["layer2"]["cases"] >= 50 and run["layer2"]["judge_errors"] == 0
    assert run["layer2"]["calibration"]["labels_used"] >= 20
    # the replay judge agrees with its own fixture (plumbing only); 3 flipped labels give a kappa
    # between the floor and 100 (see docs/factory.md "Starter agents")
    assert run["layer2"]["match_percent"] == 100 and run["verdict"] == "pass"
    assert caps.CALIBRATION_KAPPA_FLOOR <= run["layer2"]["calibration"]["kappa_hundredths"] < 100
    assert "dev-fixture-replay" in out and code == (0 if run["verdict"] == "pass" else 1)
    # the committed file stays a draft; the gate only moved the catalogue row
    assert definition(agent_id)["lifecycle"]["state"] == "draft"


def test_fake_model_is_refused_in_databricks_app_mode(
    env: gate.GateEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    starters.seed(env.store, env.data_dir)
    env.settings.supervisor_mode = "databricks_app"
    code = main(["gate", "cyber-assessor", "--kind", "full", "--model", "fake"], gate_env=env)
    out = capsys.readouterr().out
    assert code == 1 and "[FAIL]" in out and "databricks_app" in out
    assert gate.latest_runs(env, "cyber-assessor", None, 1) == []


def test_replay_model_is_not_a_mock_and_says_what_it_is() -> None:
    chat = devfake.ReplayChat(definition("cyber-assessor"), cases("cyber-assessor"))
    assert chat.is_mock is False and chat.model_id == "dev-fixture-replay"
