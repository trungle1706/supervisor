"""WP-D3: showcase acts 3 and 4 (two agents and two guardians) on a temporary SQLite store with the
development fake model (LLM_BASE_URL empty)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from supervisor.config import REPO_ROOT, load_settings
from supervisor.demo import showcase
from supervisor.demo import showcase_factory as sf
from supervisor.factory import devfake, golden, registry


class Lines:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    def text(self) -> str:
        return "\n".join(self.lines)


def make_settings(path: Path, **over: Any) -> Any:
    base: dict[str, Any] = {"llm_base_url": "", "llm_mock": False, **over}
    return load_settings(sql_backend="sqlite", data_dir=path / "data", **base)


@pytest.fixture(autouse=True)
def flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOWCASE_ENABLED", "1")


@pytest.fixture
def out() -> Lines:
    return Lines()


@pytest.fixture
def kit(tmp_path: Path, out: Lines) -> Iterator[sf.Kit]:
    with sf.open_kit(make_settings(tmp_path), out) as k:
        yield k


@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[sf.Kit, Lines]]:
    """One complete run (both agents and both guardians to live), shared by the read-only tests."""
    mp = pytest.MonkeyPatch()
    mp.setenv("SHOWCASE_ENABLED", "1")
    out = Lines()
    try:
        with sf.open_kit(make_settings(tmp_path_factory.mktemp("full")), out) as k:
            sf.run(k)
            yield k, out
    finally:
        mp.undo()


# ------------------------------------------------------------------------------ the full run


def test_both_agents_reach_live_through_the_gate_and_two_people(full: tuple[sf.Kit, Lines]) -> None:
    kit, _ = full
    store = kit.env.store
    for spec in sf.AGENTS:
        row = store.get(spec.agent_id)
        assert row["state"] == "live"
        assert sf.TAG in row["definition"]["description"]
        kinds = {a["role"]: a["by"] for a in row["definition"]["lifecycle"]["approvals"]}
        assert kinds == {"owner_lead": spec.lead.user_id, "second_line": "second.line"}
        refs = {r["doc_id"][:7] for r in row["definition"]["policy_refs"]}
        assert {"VN-TT53", "VN-INT-"} <= refs
    dg = store.get(sf.AGENT2)["definition"]
    assert dg["harness"]["loop"]["mode"] == "loop"
    assert dg["harness"]["loop"]["max_iterations"] == 3
    assert dg["harness"]["loop"]["loop_evaluator"] == "rules"
    assert store.get(sf.AGENT1)["definition"]["harness"]["loop"]["mode"] == "single_pass"
    assert store.get(sf.AGENT1)["dimension_id"] == "model"
    assert store.get(sf.AGENT2)["dimension_id"] == "data_governance"


def test_golden_sets_and_gate_numbers(full: tuple[sf.Kit, Lines]) -> None:
    kit, _ = full
    doc = json.loads(sf.results_path(kit).read_text(encoding="utf-8"))
    assert [a["id"] for a in doc["agents"]] == [sf.AGENT1, sf.AGENT2]
    for a in doc["agents"]:
        assert a["tag"] == sf.TAG and a["model"] == "fake model" and a["state"] == "live"
        assert a["golden"]["cases"] >= 60 and a["golden"]["labels"] >= 24
        g = a["gate"]
        assert g["verdict"] == "pass" and g["layer1_percent"] == 100
        assert g["kappa_hundredths"] >= 70 and g["calibration_labels"] >= 24
        assert g["regression_lost"] == 0
        assert a["sample"]["verdict"] == "pass"
        review = a["simulation"]
        assert review["systems"] == 3 and review["marked"] >= 10 and review["disagree"] >= 1
    assert len(golden.load_gate_cases(kit.data_dir, sf.AGENT1)) >= 60


def test_both_guardians_reach_live_with_numbers(full: tuple[sf.Kit, Lines]) -> None:
    kit, _ = full
    doc = json.loads(sf.results_path(kit).read_text(encoding="utf-8"))
    rows = {g["id"]: g for g in doc["guardians"]}
    assert set(rows) == {sf.GUARD1, sf.GUARD2}
    for g in rows.values():
        assert g["state"] == "live" and g["tag"] == sf.TAG and g["shadow_days"] == 1
        assert g["benchmark"]["gate"] == "pass"
        assert g["benchmark"]["tpr_pct"] >= 90 and g["benchmark"]["fpr_pct"] <= 5
        assert g["shadow"]["calls_seen"] > 0 and g["shadow"]["would_act"] > 0
        assert g["shadow"]["false_rate_pct"] <= g["shadow"]["max_fpr_pct"]
        assert {a["by"] for a in g["approvals"]} >= {"second.line"}
    mask, policy = rows[sf.GUARD1], rows[sf.GUARD2]
    assert mask["benchmark"]["live_slug"] == "dlp_vn"  # the live comparison
    assert mask["benchmark"]["attack"] == 100 and mask["benchmark"]["benign"] >= 120
    assert policy["benchmark"]["live_slug"] is None
    assert mask["approvals"][0]["by"] == "lead.data"
    assert policy["approvals"][0]["by"] == "lead.cyber"
    assert mask["action"] == "redact" and policy["action"] == "block"


def test_the_final_check_shows_a_block_and_a_mask(full: tuple[sf.Kit, Lines]) -> None:
    kit, out = full
    doc = json.loads(sf.results_path(kit).read_text(encoding="utf-8"))
    chk = doc["final_check"]
    assert chk["blocked"] is True and chk["masked"] is True
    assert chk["over_limit"]["allow"] is False
    assert chk["over_limit"]["rule_id"] == "GATE-GUARDIAN-BLOCK"
    assert chk["over_limit"]["guardian"] == [f"gf:{sf.GUARD2}@1"]
    assert chk["account_number"]["status"] == "transform"
    assert chk["account_number"]["guardian"] == [f"gf:{sf.GUARD1}@1"]
    assert chk["over_limit_approved"]["allow"] is True
    assert "190312345678" not in json.dumps(doc)
    assert "final check: over-limit transfer blocked" in out.text()


def test_output_is_ascii_labelled_and_lists_the_limits(full: tuple[sf.Kit, Lines]) -> None:
    _, out = full
    text = out.text()
    assert text.isascii()
    assert "fake model" in text and "demo:showcase" in text
    assert "shadow window 1 day" in text
    assert "Agents (act 3)" in text and "Guardians (act 4)" in text
    assert "[FAIL]" not in text


def _counts(kit: sf.Kit) -> dict[str, int]:
    tables = {
        "agents": "factory_agent",
        "runs": "gate_run",
        "docs": "regkb_internal_doc",
        "defs": "guardian_def",
        "bench": "guardian_bench_run",
        "findings": "guardian_shadow_finding",
    }
    return {k: len(kit.ctx.state.query(t)) for k, t in tables.items()}


def test_a_second_run_changes_nothing(full: tuple[sf.Kit, Lines]) -> None:
    kit, _ = full
    before = _counts(kit)
    again = Lines()
    kit.echo = again
    sf.run(kit)
    assert before == _counts(kit)
    assert "[SKIP]" in again.text() and "[FAIL]" not in again.text()
    assert kit.env.store.get(sf.AGENT1)["state"] == "live"


# ------------------------------------------------------------------------------ --until


def test_until_stops_agents_at_each_state_and_resumes(kit: sf.Kit) -> None:
    store = kit.env.store

    def states() -> list[str]:
        return [store.get(s.agent_id)["state"] for s in sf.AGENTS]

    sf.run(kit, "agents", "draft")
    assert states() == ["draft", "draft"]
    assert kit.ctx.state.query("gate_run", {"kind": "full"}) == []
    sf.run(kit, "agents", "tested")
    assert states() == ["tested", "tested"]
    sf.run(kit, "agents", "approved")
    assert states() == ["approved", "approved"]
    sf.run(kit, "agents", "live")
    assert states() == ["live", "live"]


def test_until_stops_guardians_and_the_presenter_can_finish_in_the_console(kit: sf.Kit) -> None:
    gstore, promo = kit.ctx.guardian_defs, kit.ctx.guardian_promotion
    sf.run(kit, "guardians", "benchmarked")
    assert [gstore.get(g)["state"] for g in (sf.GUARD1, sf.GUARD2)] == ["benchmarked"] * 2
    assert kit.ctx.state.query("guardian_shadow_finding") == []
    sf.run(kit, "guardians", "shadow")
    assert [gstore.get(g)["state"] for g in (sf.GUARD1, sf.GUARD2)] == ["shadow"] * 2
    # the presenter does the last steps: two people approve, the owner lead goes live
    for def_id, lead in ((sf.GUARD1, sf.LEAD_DATA), (sf.GUARD2, sf.LEAD_CYBER)):
        assert promo.status(gstore._latest(def_id))["passed"] is True
        promo.approve(def_id, lead.principal())
        promo.approve(def_id, sf.SECOND_LINE.principal())
        assert gstore.get(def_id)["state"] == "approved"
        promo.go_live(def_id, lead.principal())
        assert gstore.get(def_id)["state"] == "live"


def test_until_is_checked_per_part() -> None:
    with pytest.raises(sf.ShowcaseError):
        sf.validate_until("agents", "shadow")
    with pytest.raises(sf.ShowcaseError):
        sf.validate_until("guardians", "tested")
    with pytest.raises(sf.ShowcaseError):
        sf.validate_until(None, "draft")
    sf.validate_until(None, "live")
    sf.validate_until("guardians", "shadow")
    sf.validate_until("agents", "tested")


# ------------------------------------------------------------------------------ reset


def test_reset_removes_only_the_showcase_rows(kit: sf.Kit) -> None:
    sf.run(kit, "agents", "draft")
    sf.run(kit, "guardians", "benchmarked")
    # a foreign agent that is not tagged must survive
    kit.env.store.create_from_template("model", "someone-elses-agent", "Theirs", "reviewer.an")
    assert kit.ctx.state.query("regkb_internal_doc") and sf.results_path(kit).exists()
    counts = sf.reset(kit)
    assert counts["agents"] == 2 and counts["guardians"] == 2 and counts["documents"] == 2
    assert [r["id"] for r in kit.env.store.list_agents()] == ["someone-elses-agent"]
    for table in (
        "gate_run",
        "guardian_def",
        "guardian_bench_run",
        "regkb_internal_doc",
        "regkb_draft",
        "factory_helper_draft",
    ):
        assert kit.ctx.state.query(table) == [], table
    assert not sf.results_path(kit).exists() and not sf.manifest_path(kit).exists()
    assert not (kit.data_dir / "factory" / sf.AGENT1).exists()
    assert not (kit.data_dir / "guardian_factory" / sf.GUARD1).exists()
    assert list((kit.data_dir / "regkb" / "internal").glob("*")) == []
    # the rows can be built again from nothing
    sf.run(kit, "agents", "draft")
    assert kit.env.store.get(sf.AGENT1)["state"] == "draft"


def test_reset_leaves_an_untagged_agent_with_the_same_id(kit: sf.Kit, out: Lines) -> None:
    kit.env.store.create_from_template("model", sf.AGENT1, "Real one", "reviewer.an")
    counts = sf.reset(kit)
    assert counts["agents"] == 0
    assert kit.env.store.get(sf.AGENT1) is not None
    assert "not a showcase agent" in out.text()


# ------------------------------------------------------------------------------ refusals


def test_flag_off_refuses_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, out: Lines
) -> None:
    monkeypatch.delenv("SHOWCASE_ENABLED", raising=False)
    rc = sf.main(["--part", "agents"], settings=make_settings(tmp_path), echo=out)
    assert rc == 1 and "SHOWCASE_ENABLED=1" in out.text()
    rc = sf.main(["--reset"], settings=make_settings(tmp_path), echo=out)
    assert rc == 1
    assert not (tmp_path / "data" / "showcase").exists()
    assert not (tmp_path / "data" / "factory").exists()


def test_the_fake_model_is_refused_in_databricks_app_mode() -> None:
    app = SimpleNamespace(supervisor_mode="databricks_app", llm_base_url="", llm_mock=False)
    with pytest.raises(sf.ShowcaseError, match="databricks_app"):
        sf.chat_for(SimpleNamespace(model_ready=False, settings=app), {"checklist": []}, [])
    laptop = SimpleNamespace(model_ready=False, settings=SimpleNamespace(supervisor_mode="laptop"))
    assert sf.chat_for(laptop, {"checklist": []}, []).model_id == devfake.MODEL_ID
    gateway = SimpleNamespace(model_ready=True, settings=SimpleNamespace(supervisor_mode="laptop"))
    assert sf.chat_for(gateway, {"checklist": []}, []) is None  # the gateway model


def test_main_and_the_dispatcher(
    tmp_path: Path, out: Lines, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = make_settings(tmp_path)
    assert sf.main(["--part", "agents", "--until", "draft"], settings=s, echo=out) == 0
    assert out.text().isascii() and out.lines[-1] == "[OK] done"
    assert sf.main(["--until", "draft"], settings=s, echo=out) == 1 and "--part" in out.text()
    assert showcase.main(["bogus"]) == 2
    assert showcase.main(["portfolio"]) == 1
    monkeypatch.delenv("SHOWCASE_ENABLED")
    assert showcase.main(["factory"]) == 1  # the dispatcher goes to the same refusal


# ------------------------------------------------------------------------------ pieces


def test_law_agent_drafts_and_a_synthetic_counsel_confirms(kit: sf.Kit) -> None:
    duties = yaml.safe_load((REPO_ROOT / "regulations/schema/duties.yaml").read_text("utf-8"))
    duty = next(iter(duties["duties"]))
    empty = {
        "imposes_duty": False,
        "duties": [],
        "subject": "",
        "trigger": "",
        "evidence_asked": "",
        "quote": "",
        "summary_en": "",
        "dimensions": [],
    }

    class Law:
        model_id = "scripted-law"
        is_mock = False
        family = "scripted"

        def complete_json(self, messages: Any, schema: Any, timeout_s: float) -> dict[str, Any]:
            body = max(json.loads(messages[-1]["content"])["section_text"].split("\n"), key=len)
            if len(body) < 40:
                return empty
            return {
                **empty,
                "imposes_duty": True,
                "duties": [duty],
                "subject": "the bank",
                "trigger": "always",
                "evidence_asked": "the record",
                "quote": " ".join(body.split())[:120],
                "summary_en": "A synthetic duty.",
                "dimensions": ["model"],
            }

    kit.law_chat = Law()
    doc = sf.ensure_document(kit, sf.AGENTS[0])
    assert doc["status"] == "confirmed" and doc["confirmed"] >= 3
    rows = kit.ctx.state.query("regkb_draft", {"instrument_id": doc["instrument_id"]})
    assert rows and {r["confirmed_by"] for r in rows} == {"counsel.synthetic"}
    assert sf.TAG in kit.ctx.state.query("regkb_internal_doc")[0]["title"]


def test_without_a_model_the_law_agent_is_skipped_with_a_message(kit: sf.Kit, out: Lines) -> None:
    doc = sf.ensure_document(kit, sf.AGENTS[1])
    assert doc["status"] == "uploaded" and doc["confirmed"] == 0
    assert "LLM_BASE_URL is empty" in out.text()


def test_golden_builder_meets_the_gate_floor_for_both_templates() -> None:
    from supervisor.factory.templates import load_template

    tools = registry.load_tools()
    for spec in sf.AGENTS:
        raw = load_template(spec.dimension)
        defn = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else dict(raw)
        cases, labels = sf.build_golden(defn, spec.short, tools)
        ids = [c["id"] for c in defn["checklist"]]
        ok, bad = golden.check_gate_cases(cases, ids)
        assert not bad and len(ok) >= 60
        assert golden.gate_stratification(ok, ids)["ready"]
        good, bad2 = golden.check_labels(labels, [c["case_id"] for c in ok], ids)
        assert not bad2 and len(good) >= 24
        assert sum(1 for c in cases if "question" in c["expected"].values()) >= len(ids)
        assert sf.build_golden(defn, spec.short, tools) == (cases, labels)  # deterministic


def test_the_transfer_policy_means_what_the_sentence_says() -> None:
    from supervisor.guardian_factory.adapter import evaluate_policy
    from supervisor.guardian_factory.definition import validate_definition

    raw = sf.g2_definition(SimpleNamespace(payments_agent="payments"))  # type: ignore[arg-type]
    raw.update(created_by="x", lifecycle={"state": "draft", "version": 1})
    d = validate_definition(raw)

    def permitted(args: dict[str, Any]) -> bool:
        return evaluate_policy(d, args, {"tool_name": "transfer"})[0]

    assert permitted({"amount_minor": 20_000_000})  # at the limit
    assert not permitted({"amount_minor": 20_000_001})
    assert permitted({"amount_minor": 90_000_000, sf.APPROVAL_ARG: "AP-1"})
    assert not permitted({"amount_minor": 90_000_000, "approved_by": "x"})
    assert not permitted({"amount_minor": "90000000"})  # text amount, no approval
    assert not permitted({})  # no amount, no approval: fail safe
    assert d.scope.tools == ["transfer"] and d.action_on_fail == "block"


def test_the_demo_users_match_config_users_yaml() -> None:
    users = yaml.safe_load((REPO_ROOT / "config" / "users.yaml").read_text("utf-8"))["users"]
    groups = yaml.safe_load((REPO_ROOT / "config" / "factory_groups.yaml").read_text("utf-8"))
    for p in (sf.AUTHOR, sf.REVIEWER, sf.LEAD_MODEL, sf.LEAD_DATA, sf.LEAD_CYBER, sf.SECOND_LINE):
        spec = users[p.user_id]
        assert set(spec["roles"]) == set(p.roles), p.user_id
        assert set(spec.get("groups") or []) == set(p.groups), p.user_id
        assert set(p.groups) <= set(groups["groups"])


def test_the_policy_fixtures_are_marked_synthetic() -> None:
    for spec in sf.AGENTS:
        text = (sf.POLICY_DIR / spec.doc_file).read_text(encoding="utf-8")
        assert "SYNTHETIC" in text and text.count("Điều ") >= 8


def test_system_inputs_are_json_safe() -> None:
    from datetime import UTC, datetime

    from supervisor.factory import gate

    row = gate._json_safe({"name": "x", "created_at": datetime(2026, 10, 29, tzinfo=UTC), "n": 3})
    assert row == {"name": "x", "created_at": "2026-10-29T00:00:00.000000Z", "n": 3}
    json.dumps(row)


def test_with_a_gateway_model_the_drafter_adds_rows_and_the_law_agent_runs(
    tmp_path: Path, out: Lines, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM_BASE_URL set: the checklist drafter and the law agent run (scripted models stand in
    for the gateway; the product has no mock path) and the golden set covers the new rows."""
    from supervisor.factory import helpers
    from supervisor.regkb import internal

    calls: list[str] = []

    class Scripted:
        model_id = "scripted-gateway"
        is_mock = False
        family = "scripted"

        def complete_json(self, messages: Any, schema: Any, timeout_s: float) -> dict[str, Any]:
            props = schema.get("properties", {})
            if "rows" in props:
                calls.append("drafter")
                n = len(calls)
                row = {
                    "question": f"Is the rule {n} of the policy section applied?",
                    "evidence": ["document"],
                    "severity": "medium",
                    "pass_rule": "A document shows the rule is applied.",
                    "section": "Dieu 2",
                }
                return {
                    "rows": [row, {**row, "evidence": ["regkb"], "question": "Is it in RegKB?"}]
                }
            calls.append("law")
            return {"imposes_duty": False}

    monkeypatch.setattr(helpers, "default_chat", lambda settings: Scripted())
    monkeypatch.setattr(internal, "make_chat", lambda settings: Scripted())
    monkeypatch.setattr(
        sf, "chat_for", lambda kit, definition, cases: sf.make_fake_chat(definition, cases)
    )
    settings = make_settings(tmp_path, llm_base_url="http://127.0.0.1:9/v1")
    with sf.open_kit(settings, out) as kit:
        assert kit.model_ready and kit.model_label == "gateway model"
        sf.run(kit, "agents", "tested")
        text = out.text()
        row = kit.env.store.get(sf.AGENT1)
        assert row["state"] == "tested" and len(row["definition"]["checklist"]) == 8
        assert "MR-07" in row["definition"]["instructions"]
        assert len(golden.load_gate_cases(kit.data_dir, sf.AGENT1)) >= 60
    assert "drafter" in calls and "law" in calls
    assert "[SKIP] checklist drafter" not in text
    assert "full gate of credit-model-risk-assessor: pass" in text
