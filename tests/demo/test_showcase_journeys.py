"""WP-D2: the three showcase journeys, the traffic generator, reset and the flag-off refusal.

The model is never called here. The facts step uses the rule path, except in one test that gives
a scripted stand-in for the gateway model (named fake, not a mock label).
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import REPO_ROOT, load_settings
from supervisor.demo import showcase
from supervisor.demo import showcase_journeys as sj
from supervisor.demo import showcase_traffic as st
from supervisor.jobs import bootstrap_schema

FIXTURES = REPO_ROOT / "src" / "supervisor" / "demo" / "showcase_data"
EXPECTED = {
    "kb-helpdesk-bot": "low",
    "cs-assistant": "medium",
    "payment-ops-copilot": "high_self",
}


class FakeGatewayChat:
    """A scripted stand-in for the gateway model: not a mock label, an answer given in the test."""

    family = "fake"
    model_id = "fake-gateway-v1"
    is_mock = False

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        self.calls += 1
        return {"claims": []}


def settings_for(data_dir: Path, **over: Any) -> Any:
    flags = dict.fromkeys(sj.REQUIRED_FLAGS, True)
    return load_settings(
        sql_backend="sqlite",
        data_dir=data_dir,
        llm_base_url="",
        console_nav_v3=True,
        console_overview_v4=True,
        agents_api_enabled=True,
        detectors_enabled=True,
        inline_redaction_enabled=True,
        policy_dir=REPO_ROOT / "policies",
        policy_dir_extra=(FIXTURES / "policy",),
        _env_file=None,
        **{**flags, **over},
    )


def open_rig(data_dir: Path, **over: Any) -> Iterator[sj.Rig]:
    settings = settings_for(data_dir, **over)
    adapters: Adapters = build_adapters(settings)
    bootstrap_schema.run(settings, adapters)
    rig = sj.open_rig(settings, adapters=adapters)
    try:
        yield rig
    finally:
        rig.close()
        adapters.close()


@pytest.fixture(autouse=True)
def _showcase_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOWCASE_ENABLED", "1")


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[sj.Rig]:
    yield from open_rig(tmp_path / "data")


@pytest.fixture(scope="module")
def full(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[sj.Rig, dict[str, sj.Journey]]]:
    """All three journeys run to the end once; the tests read the result."""
    import os

    os.environ["SHOWCASE_ENABLED"] = "1"
    gen = open_rig(tmp_path_factory.mktemp("showcase") / "data")
    rig = next(gen)
    try:
        yield (
            rig,
            {
                cid: sj.run_journey(rig, cand, upto=9, echo=False)
                for cid, cand in sj.CANDIDATES.items()
            },
        )
    finally:
        next(gen, None)
        os.environ.pop("SHOWCASE_ENABLED", None)


# ----------------------------------------------------------------------------- flag off


def test_flag_off_refuses_every_command(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.delenv("SHOWCASE_ENABLED", raising=False)
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    for argv in (["--dry-run"], ["--reset"], ["--step", "3"]):
        assert sj.main(argv) == 2
        assert "SHOWCASE_ENABLED" in capsys.readouterr().out
    assert st.main(["--candidate", "kb-helpdesk-bot", "--dry-run"]) == 2
    assert "SHOWCASE_ENABLED" in capsys.readouterr().out
    assert showcase.main(["journeys", "--dry-run"]) == 2
    with pytest.raises(sj.ShowcaseError, match="showcase_off"):
        sj.require(settings_for(Path("/nonexistent")))


def test_flag_off_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.delenv("SHOWCASE_ENABLED", raising=False)
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    assert sj.main([]) == 2
    capsys.readouterr()
    assert not (tmp_path / "d").exists() or not list((tmp_path / "d").glob("*.db"))


def test_a_missing_feature_flag_is_named(tmp_path: Path) -> None:
    s = settings_for(tmp_path / "d", smart_guardian=False, register_v3=False)
    with pytest.raises(sj.ShowcaseError, match="SMART_GUARDIAN.*|REGISTER_V3.*"):
        sj.require(s)
    assert set(sj.missing_flags(s)) == {"SMART_GUARDIAN", "REGISTER_V3"}


def test_dry_run_prints_the_plan_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    for env in sj.REQUIRED_FLAGS.values():
        monkeypatch.setenv(env, "1")
    assert sj.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "expected class high_self" in out and "step 9: done" in out
    assert not list((tmp_path / "d").glob("*.db"))


# ----------------------------------------------------------------------------- sources


def test_source_zips_are_text_only_and_clean() -> None:
    for cid in EXPECTED:
        path = FIXTURES / f"{cid}.zip"
        assert path.is_file(), path
        with zipfile.ZipFile(path) as zf:
            assert zf.namelist(), cid
            for info in zf.infolist():
                name = info.filename
                assert not name.startswith(".") and ".env" not in name and "/." not in name
                assert name.endswith((".py", ".md", ".txt", ".yaml", ".yml", ".json")), name
                text = zf.read(info).decode("utf-8")  # text only: a binary file would not decode
                for needle in ("AKIA", "BEGIN PRIVATE KEY", "BEGIN RSA", "dapi", "eyJ"):
                    assert needle not in text, (name, needle)
                for old in ("kb_chatbot", "cs_agent", "payops_agent"):
                    assert old not in text, (name, old)


def test_the_tool_rebuilds_the_same_bytes() -> None:
    tool = REPO_ROOT / "tools" / "showcase_sources.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("showcase_sources", tool)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = mod.DEFAULT_CANDIDATES
    if not (base / "a1-kb-chatbot").is_dir():
        pytest.skip("the testbed candidates are not on this host")
    for folder, spec_ in mod.CANDIDATES.items():
        built = mod.build_one(base / folder, spec_)
        assert built == (FIXTURES / f"{spec_['name']}.zip").read_bytes(), folder


def test_the_showcase_policy_loads_next_to_the_baseline() -> None:
    from supervisor.gateway.policy import load_policy_dirs

    pol = load_policy_dirs([REPO_ROOT / "policies", FIXTURES / "policy"])
    assert set(EXPECTED) <= set(pol.doc.agents)
    assert any(r.id == "SHOW-PAY-01" for r in pol.doc.rules)


# ----------------------------------------------------------------------------- journeys


@pytest.mark.parametrize("cid", sorted(EXPECTED))
def test_each_journey_reaches_its_class_and_running(
    full: tuple[sj.Rig, dict[str, sj.Journey]], cid: str
) -> None:
    rig, journeys = full
    j = journeys[cid]
    assert j.done == list(sj.STEPS)
    assert j.outcome == EXPECTED[cid]
    assert j.class_path[0] == "N-SYSTEM" and j.class_path[-1] == EXPECTED[cid]
    assert j.gate_state == "RUNNING" and j.stage == "operation"
    state = rig.ctx.state
    assert state.get("agent", {"agent_id": cid})["gate_state"] == "RUNNING"
    system = rig.ctx.systems.get(j.system_id)
    assert system["lifecycle_stage"] == "operation"
    assert system["tags"][sj.TAG] == "1" and system["tags"]["showcase_candidate"] == cid
    assert (
        system["risk_level"]
        == {"low": "low", "medium": "medium", "high_self": "high"}[EXPECTED[cid]]
    )


@pytest.mark.parametrize("cid", sorted(EXPECTED))
def test_two_persons_and_the_eight_types(
    full: tuple[sj.Rig, dict[str, sj.Journey]], cid: str
) -> None:
    rig, journeys = full
    j = journeys[cid]
    state = rig.ctx.state
    rows = state.query("classification_v2", {"system_id": j.system_id})
    assert len(rows) == 1 and rows[0]["decided_by"] == sj.DECIDER
    assert rows[0]["approved_by"] == sj.APPROVER != rows[0]["decided_by"]
    approvals = state.query("stage_approval", {"system_id": j.system_id})
    assert {a["to_stage"] for a in approvals} == {"deployment", "operation"}
    for a in approvals:
        assert a["status"] == "approved" and a["requested_by"] != a["decided_by"]
        assert a.get("applied_at") is not None
    assert len(j.dims) == 8 and set(j.dims) == set(
        ("model", "data_governance", "cybersecurity", "legal_compliance", "ethics")
        + ("third_party", "supply_chain", "reputation")
    )
    assert "pass" not in j.dims.values()  # the orchestrator never writes pass
    assert j.predeploy  # honest verdict, no harness here: no_go
    assert j.floor and "dlp_vn" in j.floor


def test_the_class_changes_what_the_orchestrator_assesses(
    full: tuple[sj.Rig, dict[str, sj.Journey]],
) -> None:
    _, journeys = full
    na = {
        c: sorted(k for k, v in j.dims.items() if v == "not_applicable")
        for c, j in journeys.items()
    }
    assert len(na["kb-helpdesk-bot"]) > len(na["cs-assistant"]) >= len(na["payment-ops-copilot"])
    assert na["payment-ops-copilot"] == []  # high: all eight apply (the institution is a bank)
    guards = {c: j.guardians for c, j in journeys.items()}
    assert all(g.startswith("session_max") for g in guards["kb-helpdesk-bot"])  # limits only
    assert any(g.startswith("session_monitor") for g in guards["cs-assistant"])
    assert any(g.startswith("monitor_split_payment") for g in guards["payment-ops-copilot"])
    # the autonomy cap is left for the presenter to accept live (SCRIPT.md, act 2)
    assert not any(g.startswith("max_level") for g in guards["payment-ops-copilot"])


def test_step_stops_and_a_later_run_continues(rig: sj.Rig) -> None:
    cand = sj.CANDIDATES["kb-helpdesk-bot"]
    state = rig.ctx.state

    j = sj.run_journey(rig, cand, upto=2, echo=False)
    assert j.done == ["source", "facts"]
    assert state.query("ai_system", {}) == [] and state.query("registration_draft", {}) == []
    assert state.query("intake_attempt", {"node_id": j.node_id})

    j = sj.run_journey(rig, cand, upto=3, echo=False)
    assert j.system_id and state.query("classification_v2", {"system_id": j.system_id}) == []
    assert state.get("agent", {"agent_id": cand.cid})["gate_state"] == "SHADOW"

    j = sj.run_journey(rig, cand, upto=4, echo=False)
    assert (
        j.outcome == "low"
        and state.query("risk_dimension_status", {"system_id": j.system_id}) == []
    )

    j = sj.run_journey(rig, cand, upto=7, echo=False)
    assert len(j.dims) == 8 and state.query("stage_approval", {"system_id": j.system_id}) == []
    assert rig.ctx.systems.get(j.system_id)["lifecycle_stage"] == "initiation"

    before = {t: len(state.query(t, {})) for t in ("ai_system", "agent", "classification_v2")}
    j = sj.run_journey(rig, cand, upto=9, echo=False)
    assert j.gate_state == "RUNNING"
    again = sj.run_journey(rig, cand, upto=9, echo=False)  # nothing changes on a second run
    assert again.gate_state == "RUNNING"
    assert {t: len(state.query(t, {})) for t in before} == before
    assert len(state.query("stage_approval", {"system_id": j.system_id})) == 2


def test_the_console_urls_are_printed(rig: sj.Rig) -> None:
    j = sj.run_journey(rig, sj.CANDIDATES["cs-assistant"], upto=4, base="http://console.test")
    text = "\n".join(j.lines)
    assert "open: http://console.test/console/candidates?drawer=" in text
    assert "/console/register/rd_" in text and "tab=classification" in text


def test_facts_use_the_model_when_one_is_given(rig: sj.Rig) -> None:
    chat = FakeGatewayChat()
    rig.chat_factory = lambda: chat
    j = sj.run_journey(rig, sj.CANDIDATES["kb-helpdesk-bot"], upto=2, echo=False)
    assert j.model_path == "model" and chat.calls >= 1
    assert not any("rule path" in line for line in j.lines)


def test_facts_say_the_rule_path_without_a_model(rig: sj.Rig) -> None:
    j = sj.run_journey(rig, sj.CANDIDATES["kb-helpdesk-bot"], upto=2, echo=False)
    assert j.model_path == "rule"
    assert any("LLM_BASE_URL is empty" in line for line in j.lines)


def test_a_wrong_class_is_an_error(rig: sj.Rig) -> None:
    import dataclasses

    wrong = dataclasses.replace(sj.CANDIDATES["kb-helpdesk-bot"], expected="medium")
    with pytest.raises(sj.ShowcaseError, match="unexpected_class"):
        sj.run_journey(rig, wrong, upto=4, echo=False)


# ----------------------------------------------------------------------------- traffic


@pytest.mark.parametrize("cid", sorted(EXPECTED))
def test_traffic_proportions_follow_the_plan(
    full: tuple[sj.Rig, dict[str, sj.Journey]], cid: str
) -> None:
    rig, _ = full
    gate, note = st.in_process_gate(rig, cid)
    assert note == ""
    total = 200
    rep = st.run_traffic(
        gate,
        cid,
        total,
        seed=7,
        on_paused=lambda: st.resume_agent(rig.runtime.gateway, rig.ctx.state, cid),
    )
    assert rep.total == total and sum(rep.seen.values()) == total
    for kind in st.KINDS:
        planned = st.MIXES[cid][kind]
        assert abs(rep.share(kind) - planned) <= 4.0, (cid, kind, rep.seen)
    assert rep.seen["allowed"] > rep.seen["masked"] > 0
    assert rep.seen["blocked"] > 0
    assert (rep.seen["paused"] > 0) == (st.MIXES[cid]["paused"] > 0)
    if rep.seen["paused"]:
        assert rep.resumes >= rep.seen["paused"]
    assert rig.ctx.state.get("agent", {"agent_id": cid})["gate_state"] == "RUNNING"


def test_a_masked_call_is_stored_masked(full: tuple[sj.Rig, dict[str, sj.Journey]]) -> None:
    rig, _ = full
    gate, _ = st.in_process_gate(rig, "payment-ops-copilot")
    import random

    tool, args = st.build_call("payment-ops-copilot", "masked", random.Random(3), 1)  # noqa: S311
    res = gate("payment-ops-copilot", "1", tool, args, {"source": sj.TAG})
    assert st.kind_of(res) == "masked" and res["allow"] is True
    sent = json.dumps(res.get("transformed_args") or res.get("transformed_payload"))
    assert args["phone"] not in sent and args["cccd"] not in sent


def test_the_plan_is_exact_and_repeatable() -> None:
    import random

    a = st.plan_kinds("payment-ops-copilot", 50, random.Random(1))  # noqa: S311
    b = st.plan_kinds("payment-ops-copilot", 50, random.Random(1))  # noqa: S311
    assert a == b and len(a) == 50
    assert {k: a.count(k) for k in st.KINDS} == {
        "allowed": 36,
        "masked": 6,
        "paused": 4,
        "blocked": 4,
    }
    for mix in st.MIXES.values():
        assert sum(mix.values()) == 100


def test_kind_of_reads_the_v2_status() -> None:
    assert st.kind_of({"allow": True, "status": "allow"}) == "allowed"
    assert st.kind_of({"allow": True, "status": "report"}) == "allowed"
    assert st.kind_of({"allow": True, "status": "transform"}) == "masked"
    assert st.kind_of({"allow": False, "status": "pause", "action": "pause"}) == "paused"
    assert st.kind_of({"allow": False, "status": "block", "action": "pause"}) == "blocked"
    assert st.kind_of({"allow": False, "status": "block", "action": "block"}) == "blocked"


def test_traffic_dry_run_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    assert (
        st.main(["--candidate", "cs-assistant", "--minutes", "2", "--rate", "10", "--dry-run"]) == 0
    )
    out = capsys.readouterr().out
    assert "plan: 20 calls over 2 min" in out and "nothing is sent" in out


def test_http_mode_signs_with_the_agent_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = tmp_path / "agent.key"
    key.write_text("x" * 40 + "\n", encoding="utf-8")
    key.chmod(0o600)
    gate = st.http_gate("https://app.example.invalid", "payment-ops-copilot", str(key), None)
    seen: list[Mapping[str, str]] = []

    def transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        seen.append(headers)
        return {"allow": True, "action": "allow", "status": "allow"}

    gate.signed_transport = transport
    res = gate.check("payment-ops-copilot", "1", "reconcile", {"statement_id": "S1"}, {})
    assert res["allow"] is True and seen
    assert any(k.lower().startswith("x-supervisor") for k in seen[0])
    assert "x" * 40 not in json.dumps(dict(seen[0]))  # the key never travels as text


# ----------------------------------------------------------------------------- reset


def test_reset_removes_the_journey_rows_only(rig: sj.Rig) -> None:
    ctx = rig.ctx
    other = ctx.systems.register(
        {
            "name": "other-system",
            "owner_user": "owner.x@example.invalid",
            "owner_team": "Other",
            "purpose": "Not a showcase system.",
            "system_type": "assistant",
            "org_role": "deployer",
            "user_segment": "internal",
            "personal_data": "none",
            "human_control": "post_review",
        },
        "reviewer.an",
    )
    from supervisor.inventory.graph import Graph
    from supervisor.inventory.model import Node
    from supervisor.inventory.store import InventoryStore

    g = Graph()
    app = Node("system", "other-app", status="unmanaged", attrs={"role": "databricks_app"})
    app.add_evidence("workspace_scan", "workspace:app/other-app")
    g.add_node(app)
    InventoryStore(ctx.state, ctx.clock).apply(g, source="workspace_scan")
    for cand in sj.CANDIDATES.values():
        sj.run_journey(rig, cand, upto=9, echo=False)
    state = ctx.state
    assert len(state.query("ai_system", {})) == 4 and len(state.query("agent", {})) >= 3
    deleted = sj.reset(rig, sj.Say([], echo=False))
    assert deleted["ai_system"] == 3 and deleted["agent"] == 3
    left = state.query("ai_system", {})
    assert [r["system_id"] for r in left] == [other["system_id"]]
    for table in (
        "agent",
        "system_component",
        "classification_v2",
        "risk_dimension_status",
        "orchestrator_run",
        "stage_approval",
        "registration_draft",
        "intake_attempt",
        "onboard_facts",
        "predeploy_report",
        "guardian_proposal",
    ):
        try:
            rows = state.query(table, {})
        except Exception:  # noqa: BLE001 - a table this build does not have
            continue
        assert rows == [], table
    assert [n["node_id"] for n in state.query("inventory_node", {})] == [app.node_id]
    assert state.query("inventory_edge", {}) == []
    for cand in sj.CANDIDATES.values():
        assert not (Path(rig.settings.data_dir) / "intake" / sj.make_node_id(cand)).exists()
    # a second reset finds nothing; a new run starts again from the beginning
    assert sj.reset(rig, sj.Say([], echo=False)) == {}
    again = sj.run_journey(rig, sj.CANDIDATES["kb-helpdesk-bot"], upto=4, echo=False)
    assert again.outcome == "low"


def test_the_zip_names_match_the_candidates() -> None:
    assert sorted(p.stem for p in FIXTURES.glob("*.zip")) == sorted(sj.CANDIDATES)
    data = (FIXTURES / "cs-assistant.zip").read_bytes()
    assert zipfile.ZipFile(io.BytesIO(data)).testzip() is None
