"""WP-O3 (phase 9): the pre-deploy assessment. The verdict rules on synthetic items, a section that
breaks does not stop the others, one run at a time per node, a small synthetic repo through the
real pipeline (intake, facts with a scripted chat adapter, readiness advisor, the real required
packs on the offline repo target), no personal data and no floats in the items, and the flag off
path.

The fake chat adapter, the fake pack engine and the fake target below exist only in these unit
tests (owner decision 2): the product path uses the gateway model for the facts step and the real
engine for the packs; a mock demo agent is named mock in the item text."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.assurance.model import PackResult
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from supervisor.onboard import predeploy
from supervisor.onboard.facts import FactsService
from supervisor.onboard.predeploy import PredeployError, PredeployService, make_item, verdict_of
from tests.onboard.test_facts import (
    AGENT,
    AWS_KEY,
    MANIFEST,
    NODE,
    PASSWORD,
    FakeGatewayChat,
    line_of,
    take_in,
)

NOW = datetime(2026, 10, 28, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_leftover_runs() -> Iterator[None]:
    predeploy._RUNNING.clear()
    yield
    for th in list(predeploy._THREADS.values()):
        th.join(30)
    predeploy._RUNNING.clear()
    predeploy._THREADS.clear()


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        onboard_intake=True,
        onboard_facts=True,
        onboard_predeploy=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


def item(section: str, status: str, n: int = 1) -> dict[str, str]:
    return make_item(section, f"{section}:{status}:{n}", status, "text", "pointer")


def result(pack_id: str, status: str, *, reasons: Sequence[str] = (), mock: bool = False) -> Any:
    return PackResult(
        run_id="r",
        pack_id=pack_id,
        pack_version=1,
        dimension="security",
        target_kind="agent",
        target_id="t",
        status=status,  # type: ignore[arg-type]
        metrics={},
        metric_status={},
        reasons=list(reasons),
        n_items=1,
        data_mode="synthetic",
        dataset_id="",
        dataset_sha256="",
        is_mock=mock,
        launch_gate="required",
        judge_gate=False,
        started_at=NOW,
        finished_at=NOW,
    )


class _Target:
    kind = "agent"
    is_mock = False

    def close(self) -> None:
        return None


def fake_target(tree: Path, agent_id: str, work: Path, settings: Any) -> Any:
    return _Target()


def all_ok_executor(status: str = "ok", mock: bool = False) -> Callable[..., list[Any]]:
    """A pack engine that answers ``status`` for every pack it is given."""

    def run(packs: Sequence[Any], target: Any, ctx: Any, run_id: str, clock: Any) -> list[Any]:
        return [result(p.id, status, reasons=["fake reason"], mock=mock) for p in packs]

    return run


def svc(
    a: Adapters,
    *,
    executor: Callable[..., list[Any]] | None = None,
    target_factory: Callable[..., Any] | None = fake_target,
) -> PredeployService:
    return PredeployService(
        a.settings,
        a.state,
        a.clock,
        executor=executor,
        target_factory=target_factory,
    )


def build_facts(a: Adapters, n: int, chat: Any = None) -> None:
    from supervisor.adapters.llm.mock import MockChat

    FactsService(a.settings, a.state, a.clock, chat_factory=lambda: chat or MockChat()).build(
        NODE, n
    )


# ------------------------------------------------------------------------------ the verdict


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([("facts", "ok"), ("packs", "ok")], "go"),
        ([("facts", "warn"), ("readiness", "warn"), ("packs", "skip")], "go"),
        ([("packs", "question")], "questions"),
        ([("duties", "question"), ("packs", "ok")], "questions"),
        ([("packs", "fail")], "no_go"),
        ([("facts", "fail")], "no_go"),
        ([("readiness", "fail")], "no_go"),
        ([("packs", "fail"), ("duties", "question")], "no_go"),  # a fail beats a question
        ([("multiturn", "fail")], "go"),  # advisory section: never blocks
        ([("duties", "fail")], "go"),
        ([("multiturn", "fail"), ("duties", "question")], "questions"),
        ([], "go"),
    ],
)
def test_verdict_rules_on_synthetic_items(statuses: list[tuple[str, str]], expected: str) -> None:
    items = [item(s, st, i) for i, (s, st) in enumerate(statuses)]
    assert verdict_of(items) == expected
    assert verdict_of(list(reversed(items))) == expected  # order does not matter


def test_make_item_checks_status_scrubs_and_cuts() -> None:
    with pytest.raises(ValueError):
        make_item("packs", "x", "maybe", "t", "p")
    with pytest.raises(ValueError):
        make_item("nowhere", "x", "ok", "t", "p")
    got = make_item("facts", "x", "warn", f"key {AWS_KEY} " + "a" * 900, "agent.py:3\x00")
    assert AWS_KEY not in got["text"] and len(got["text"]) <= predeploy.MAX_TEXT
    assert "\x00" not in got["pointer"]
    assert set(got) == {"section", "id", "status", "text", "pointer"}


def test_required_sections_are_documented_in_the_module() -> None:
    assert predeploy.REQUIRED_SECTIONS == ("facts", "readiness", "packs")
    assert set(predeploy.SECTIONS) == {"facts", "readiness", "packs", "multiturn", "duties"}


# ------------------------------------------------------------------------------ the sections


def test_no_facts_is_a_question_and_the_other_sections_still_run(adapters: Adapters) -> None:
    n = take_in(adapters)
    s = svc(adapters, executor=all_ok_executor("ok"))
    rep = s.start(NODE, n, "reviewer.an", background=False)
    assert rep["status"] == "done"
    facts_items = [i for i in rep["items"] if i["section"] == "facts"]
    assert [i["status"] for i in facts_items] == ["question"]
    assert "no facts yet, build the facts card" in facts_items[0]["text"]
    sections = {i["section"] for i in rep["items"]}
    assert sections == {"facts", "readiness", "packs", "multiturn", "duties"}
    # every required pack is ok, so the open questions decide
    assert rep["verdict"] == "questions" and rep["items_question"] >= 2


def test_all_good_is_go_when_nothing_is_open(adapters: Adapters, monkeypatch: Any) -> None:
    n = take_in(adapters)
    build_facts(adapters, n)
    s = svc(adapters, executor=all_ok_executor("ok"))
    monkeypatch.setattr(
        "supervisor.console.systems_wizard.scan_folder",
        lambda tree: {"total": 91, "band": "ux4b_band_ready", "areas": [], "patches": 0},
    )
    rep = s.start(NODE, n, "reviewer.an", background=False)
    # only the duties question is left: the flag CONSOLE_REGISTER_DUTIES is off here
    open_q = [i for i in rep["items"] if i["status"] == "question"]
    assert [i["section"] for i in open_q] == ["duties"]
    assert open_q[0]["text"] == "duties: not run"
    assert rep["verdict"] == "questions"
    # with the duties question gone the same items would be GO
    assert verdict_of([i for i in rep["items"] if i["status"] != "question"]) == "go"


def test_a_broken_section_becomes_a_fail_item_and_the_others_continue(
    adapters: Adapters, monkeypatch: Any
) -> None:
    n = take_in(adapters)
    build_facts(adapters, n)

    def boom(tree: Path) -> dict[str, Any]:
        raise RuntimeError("advisor exploded")

    monkeypatch.setattr("supervisor.console.systems_wizard.scan_folder", boom)

    def broken_target(*a: Any, **k: Any) -> Any:
        raise OSError("no sandbox today")

    s = svc(adapters, target_factory=broken_target)
    rep = s.start(NODE, n, "reviewer.an", background=False)
    assert rep["status"] == "done"
    by = {i["id"]: i for i in rep["items"] if i["id"].endswith(":error")}
    assert set(by) == {"readiness:error", "packs:error", "multiturn:error"}
    assert all(i["status"] == "fail" for i in by.values())
    assert "advisor exploded" in by["readiness:error"]["text"]
    assert "no sandbox today" in by["packs:error"]["text"]
    # facts and duties still gave their items
    assert any(i["section"] == "facts" and i["status"] == "warn" for i in rep["items"])
    assert any(i["section"] == "duties" for i in rep["items"])
    assert rep["verdict"] == "no_go"
    assert rep["items_fail"] == 3


def test_a_broken_advisory_section_alone_does_not_block(
    adapters: Adapters, monkeypatch: Any
) -> None:
    n = take_in(adapters)
    build_facts(adapters, n)
    monkeypatch.setattr(
        "supervisor.console.systems_wizard.scan_folder",
        lambda tree: {"total": 91, "band": "ux4b_band_ready", "areas": [], "patches": 0},
    )
    calls = {"n": 0}

    def executor(packs: Sequence[Any], *a: Any, **k: Any) -> list[Any]:
        calls["n"] += 1
        if any(p.id == predeploy.MULTITURN_PACK for p in packs):
            raise RuntimeError("red team exploded")
        return [result(p.id, "ok") for p in packs]

    rep = svc(adapters, executor=executor).start(NODE, n, "reviewer.an", background=False)
    mt = [i for i in rep["items"] if i["section"] == "multiturn"]
    assert [i["status"] for i in mt] == ["fail"] and "red team exploded" in mt[0]["text"]
    assert rep["verdict"] == "questions"  # not no_go: the section is advisory


def test_required_pack_rules_skip_is_fail_not_applicable_is_a_note(adapters: Adapters) -> None:
    n = take_in(adapters)

    def executor(packs: Sequence[Any], *a: Any, **k: Any) -> list[Any]:
        out = []
        for p in packs:
            if p.id == "pii_canary":
                out.append(result(p.id, "skip", reasons=["no traces"]))
            elif p.id in ("four_fifths_rule", "fairness_metrics"):
                r = result(p.id, "skip", reasons=["not applicable: target lacks decide"])
                r.details = {"not_applicable": True}
                out.append(r)
            elif p.id == "truthfulqa_vi":
                out.append(result(p.id, "fail", reasons=["truthful_bp=10 misses no-go"]))
            elif p.id == "pin_hash_check":
                out.append(result(p.id, "error", reasons=["OSError: x"]))
            elif p.id == "licence_allowlist":
                out.append(result(p.id, "warn", reasons=["close to the limit"]))
            else:
                out.append(result(p.id, "ok"))
        return out

    rep = svc(adapters, executor=executor).start(NODE, n, "reviewer.an", background=False)
    packs = {i["id"]: i for i in rep["items"] if i["section"] == "packs"}
    assert packs["pack:pii_canary"]["status"] == "fail"
    assert packs["pack:truthfulqa_vi"]["status"] == "fail"
    assert packs["pack:pin_hash_check"]["status"] == "fail"
    assert packs["pack:licence_allowlist"]["status"] == "warn"
    assert packs["pack:four_fifths_rule"]["status"] == "skip"
    assert packs["pack:fairness_metrics"]["status"] == "skip"
    assert packs["pack:prefilter_evasion"]["status"] == "ok"
    assert rep["verdict"] == "no_go"


def test_the_multiturn_pack_is_an_advisory_item_that_never_fails(adapters: Adapters) -> None:
    n = take_in(adapters)
    rep = svc(adapters, executor=all_ok_executor("fail")).start(
        NODE, n, "reviewer.an", background=False
    )
    mt = [i for i in rep["items"] if i["section"] == "multiturn"]
    assert len(mt) == 1 and mt[0]["status"] == "warn"
    assert mt[0]["pointer"] == "pack multiturn_redteam_vi"


def test_mock_results_say_mock_and_mock_only_blocks_unless_accepted(adapters: Adapters) -> None:
    n = take_in(adapters)
    rep = svc(adapters, executor=all_ok_executor("ok", mock=True)).start(
        NODE, n, "reviewer.an", background=False
    )
    packs = [i for i in rep["items"] if i["section"] == "packs"]
    assert any("(mock)" in i["text"] for i in packs)
    only = [i for i in packs if i["id"] == "packs:mock_only"]
    assert only and only[0]["status"] == "fail" and rep["verdict"] == "no_go"
    adapters.settings.assurance_accept_mock_for_launch = True
    rep2 = svc(adapters, executor=all_ok_executor("ok", mock=True)).start(
        NODE, n, "reviewer.an", background=False
    )
    ids = {i["id"] for i in rep2["items"]}
    assert "packs:mock_only" not in ids and "packs:mock" in ids


# ------------------------------------------------------------------------------ concurrency


def test_a_second_start_while_running_answers_already_running(adapters: Adapters) -> None:
    n = take_in(adapters)
    gate = threading.Event()
    entered = threading.Event()

    def slow(packs: Sequence[Any], *a: Any, **k: Any) -> list[Any]:
        entered.set()
        assert gate.wait(30)
        return [result(p.id, "ok") for p in packs]

    s = svc(adapters, executor=slow)
    first = s.start(NODE, n, "reviewer.an")
    assert first["status"] in ("queued", "running") and first["verdict"] == "none"
    assert entered.wait(30)
    with pytest.raises(PredeployError) as exc:
        s.start(NODE, n, "reviewer.an")
    assert exc.value.code == "already_running" and "already_running" in str(exc.value)
    assert s.latest(NODE)["running"] is True
    # another node is not blocked by this one
    n2 = take_in(adapters, node="other-agent")
    other = svc(adapters, executor=all_ok_executor()).start("other-agent", n2, "reviewer.an")
    assert other["report_id"] != first["report_id"]
    gate.set()
    s.join(NODE)
    s.join("other-agent")
    done = s.latest(NODE)
    assert done["status"] == "done" and done["report_id"] == first["report_id"]
    again = s.start(NODE, n, "reviewer.an", background=False)  # free again
    assert again["report_id"] != first["report_id"] and len(s._rows(NODE)) == 2  # noqa: SLF001


def test_a_row_left_running_by_a_restart_does_not_block_the_node(adapters: Adapters) -> None:
    n = take_in(adapters)
    s = svc(adapters, executor=all_ok_executor())
    adapters.state.insert(
        "predeploy_report",
        {
            "report_id": "pdr_stale",
            "node_id": NODE,
            "attempt_n": n,
            "status": "running",
            "verdict": "none",
            "started_at": NOW,
            "finished_at": None,
            "items_total": 0,
            "items_fail": 0,
            "items_question": 0,
            "summary": "running",
            "items": "[]",
            "model_id": None,
            "created_by": "x",
            "created_at": NOW,
        },
    )
    s.start(NODE, n, "reviewer.an", background=False)
    stale = s.get("pdr_stale")
    assert stale and stale["status"] == "failed" and "restarted" in stale["summary"]


def test_start_refusals(adapters: Adapters) -> None:
    s = svc(adapters)
    with pytest.raises(PredeployError) as exc:
        s.start(NODE, 1, "reviewer.an")
    assert exc.value.code == "no_attempt"
    with pytest.raises(Exception) as bad:
        s.start("bad id", 1, "reviewer.an")
    assert "node id" in str(bad.value)
    assert adapters.state.query("predeploy_report") == []


# ------------------------------------------------------------------------------ the pipeline


def test_small_synthetic_repo_through_the_real_pipeline(adapters: Adapters) -> None:
    """Intake -> facts (scripted gateway chat) -> readiness advisor -> the real required packs on
    the offline repo target. Real engine, real runners, no fake pack engine."""
    n = take_in(adapters)
    claim = {
        "claim": "waive_fee has no per-call amount check",
        "category": "weak_spot",
        "file": "agent.py",
        "line": line_of(AGENT, "def waive_fee"),
        "quote": "def waive_fee(account_id",
    }
    chat = FakeGatewayChat([claim])
    build_facts(adapters, n, chat)
    s = PredeployService(adapters.settings, adapters.state, adapters.clock)
    rep = s.start(NODE, n, "reviewer.an", background=False)
    assert rep["status"] == "done" and rep["model_id"] == "fake-gateway-v1"
    assert rep["verdict"] == "no_go"  # the stored code is not run: required packs cannot pass
    by_section = {g["section"]: g["rows"] for g in rep["groups"]}
    assert list(by_section) == ["facts", "readiness", "packs", "multiturn", "duties"]
    facts_pointers = {i["pointer"] for i in by_section["facts"]}
    assert f"agent.py:{line_of(AGENT, 'MCP_URL')}" in facts_pointers
    assert f"agent.py:{line_of(AGENT, 'def waive_fee')}" in facts_pointers  # the model claim
    assert any(i["id"] == "packs:no_harness" for i in by_section["packs"])
    packs = {i["id"]: i for i in by_section["packs"]}
    assert packs["pack:prefilter_evasion"]["status"] == "ok"
    assert packs["pack:pii_canary"]["status"] == "fail"
    assert "readiness" in by_section["readiness"][0]["text"]
    assert by_section["duties"][0]["text"] == "duties: not run"
    # every item has a pointer and a status from the closed list
    assert all(i["pointer"] and i["pointer"] != "-" for i in rep["items"])
    assert {i["status"] for i in rep["items"]} <= set(predeploy.STATUSES)
    assert rep["items_total"] == len(rep["items"])
    assert rep["items_fail"] == sum(1 for i in rep["items"] if i["status"] == "fail")
    # the sandbox folder is gone after the run
    assert not (Path(adapters.settings.data_dir) / "predeploy").exists() or not any(
        (Path(adapters.settings.data_dir) / "predeploy").iterdir()
    )


def test_a_demo_agent_runs_in_the_launch_sandbox_and_is_named_mock(adapters: Adapters) -> None:
    """The manifest of the stored tree names a demo agent: the target is the sandbox demo agent
    (gate in SHADOW, synthetic world), and the items say mock."""
    entries = {"manifest.yaml": MANIFEST.replace("demo-fee-agent", "payments"), "agent.py": AGENT}
    n = take_in(adapters, entries, node="payments")
    seen: dict[str, Any] = {}

    def spy(tree: Path, agent_id: str, work: Path, settings: Any) -> Any:
        seen["agent_id"] = agent_id
        seen["tree"] = tree
        return _Target()

    s = svc(adapters, executor=all_ok_executor("ok", mock=True), target_factory=spy)
    rep = s.start("payments", n, "reviewer.an", background=False)
    assert seen["agent_id"] == "payments"
    assert any("(mock)" in i["text"] for i in rep["items"] if i["section"] == "packs")
    assert predeploy.agent_id_of(seen["tree"], "some-candidate") == "payments"
    assert predeploy.agent_id_of(seen["tree"], "payments") == "payments"


# ------------------------------------------------------------------------------ the rows


def test_report_row_is_integers_only_with_no_personal_data(adapters: Adapters) -> None:
    n = take_in(adapters)
    build_facts(adapters, n)
    s = PredeployService(adapters.settings, adapters.state, adapters.clock)
    s.start(NODE, n, "reviewer.an", background=False)
    row = dict(adapters.state.query("predeploy_report", {"node_id": NODE})[0])
    items = json.loads(row["items"])

    def no_float(v: Any) -> bool:
        if isinstance(v, float):
            return False
        if isinstance(v, dict):
            return all(no_float(x) for x in v.values())
        if isinstance(v, list):
            return all(no_float(x) for x in v)
        return True

    assert no_float(items) and isinstance(row["items_total"], int)
    assert len(row["summary"]) <= 2000
    dump = json.dumps(row, default=str)
    assert AWS_KEY not in dump and PASSWORD not in dump
    assert row["status"] == "done" and row["verdict"] in ("no_go", "questions", "go")
    assert row["created_by"] == "reviewer.an"
    assert all(set(i) == {"section", "id", "status", "text", "pointer"} for i in items)


def test_a_float_in_an_item_is_refused_before_it_is_stored(adapters: Adapters) -> None:
    n = take_in(adapters)
    s = svc(adapters)
    row = s.start(NODE, n, "reviewer.an", background=False)
    raw = dict(adapters.state.get("predeploy_report", {"report_id": row["report_id"]}))
    with pytest.raises(Exception, match="float"):
        s._finish(raw, "done", "go", [{"section": "facts", "n": 1.5}], "x")  # type: ignore[list-item]  # noqa: SLF001


def test_latest_is_the_newest_report(adapters: Adapters) -> None:
    n = take_in(adapters)
    s = svc(adapters, executor=all_ok_executor())
    assert s.latest(NODE) is None and s.has_report(NODE) is False
    first = s.start(NODE, n, "reviewer.an", background=False)
    second = s.start(NODE, n, "reviewer.an", background=False)
    assert s.has_report(NODE) is True
    assert s.latest(NODE)["report_id"] == second["report_id"] != first["report_id"]


# ------------------------------------------------------------------------------ flag off


def test_flag_defaults_off_and_every_entry_refuses(tmp_path: Path) -> None:
    assert load_settings(sql_backend="sqlite").onboard_predeploy is False
    settings = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "d", onboard_intake=True, onboard_facts=True
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        s = PredeployService(a.settings, a.state, a.clock)
        with pytest.raises(PredeployError) as exc:
            s.start(NODE, 1, "reviewer.an")
        assert exc.value.code == "predeploy_off" and "ONBOARD_PREDEPLOY=1" in str(exc.value)
        assert a.state.query("predeploy_report") == []
        assert not (Path(settings.data_dir) / "predeploy").exists()
    finally:
        a.close()


def test_setting_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONBOARD_PREDEPLOY", "1")
    assert load_settings(sql_backend="sqlite").onboard_predeploy is True
