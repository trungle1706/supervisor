"""D05 (family is derived, never trusted) and D15 (challenger scope)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from supervisor.adapters.factory import make_judge_chat_model
from supervisor.adapters.llm.openai_compatible import OpenAICompatibleChat
from supervisor.config import load_settings
from supervisor.core.errors import ConfigError
from supervisor.judge.family import FamilyDeclarationError, resolve_family
from supervisor.judge.mockjudge import MockJudgeChat
from supervisor.judge.mrm.card import build_card, render_card_md
from supervisor.judge.mrm.validation import render_md, run_validation
from supervisor.judge.router import (
    FamilyConflictError,
    JudgeRouter,
    load_registry_families,
)
from tests.judge.conftest import MemoryEvidence, MemoryTables

REMOTE = {"LLM_ALLOW_REMOTE": "1"}


def _env(monkeypatch: pytest.MonkeyPatch, **kv: str) -> None:
    for k, v in {**REMOTE, **kv}.items():
        monkeypatch.setenv(k, v)


# -- D05 ---------------------------------------------------------------------------------
def test_family_is_derived_from_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, JUDGE_T1_MODEL="claude-haiku-5-5", JUDGE_T1_BASE_URL="https://x.example/v1")
    chat = make_judge_chat_model(load_settings(_env_file=None), "t1")
    assert (chat.family, chat.family_source) == ("anthropic", "derived")  # type: ignore[attr-defined]


def test_declared_family_that_agrees_is_accepted_as_derived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(
        monkeypatch,
        JUDGE_T1_MODEL="claude-haiku-5-5",
        JUDGE_T1_BASE_URL="https://x.example/v1",
        JUDGE_T1_FAMILY="anthropic",
    )
    chat = make_judge_chat_model(load_settings(_env_file=None), "t1")
    assert chat.family_source == "derived"  # type: ignore[attr-defined]


def test_lying_declared_family_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The D05 attack: a qwen judge declared as another family."""
    _env(
        monkeypatch,
        JUDGE_T1_MODEL="qwen3.8-27b-int4",
        JUDGE_T1_BASE_URL="http://127.0.0.1:8001/v1",
        JUDGE_T1_FAMILY="anthropic",
    )
    with pytest.raises(FamilyDeclarationError, match="not trusted"):
        JudgeRouter.from_settings(load_settings(_env_file=None))


def test_override_needs_flag_and_marks_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        JUDGE_T1_MODEL="qwen3.8-27b-int4",
        JUDGE_T1_BASE_URL="http://127.0.0.1:8001/v1",
        JUDGE_T1_FAMILY="anthropic",
        JUDGE_FAMILY_OVERRIDE_TEST_ONLY="1",
    )
    chat = make_judge_chat_model(load_settings(_env_file=None), "t1")
    assert (chat.family, chat.family_source) == ("anthropic", "declared-test-only")  # type: ignore[attr-defined]


def test_override_flag_is_refused_in_databricks_app_mode() -> None:
    with pytest.raises(ConfigError, match="databricks_app"):
        load_settings(
            _env_file=None,
            supervisor_mode="databricks_app",
            judge_family_override_test_only=True,
            databricks_host="https://adb-1.example.invalid",
        )
    s = load_settings(_env_file=None, judge_family_override_test_only=True)
    assert s.supervisor_mode == "laptop" and s.judge_family_override_test_only


def test_default_flags_are_off() -> None:
    s = load_settings(_env_file=None)
    assert s.judge_family_override_test_only is False and s.judge_family_probe is False


def test_resolve_family_endpoint_disagreement_is_refused() -> None:
    with pytest.raises(FamilyDeclarationError, match="endpoint metadata"):
        resolve_family(
            "JUDGE_T1_FAMILY", "claude-x", None, override_test_only=False, endpoint_family="qwen"
        )
    fam = resolve_family(
        "JUDGE_T1_FAMILY", "my-finetune", None, override_test_only=False, endpoint_family="qwen"
    )
    assert fam == ("qwen", "derived")


def _models_transport(entry: dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [entry]})

    return httpx.MockTransport(handler)


def test_endpoint_metadata_family_probe() -> None:
    chat = OpenAICompatibleChat(
        "http://127.0.0.1:8001/v1",
        "bank-judge",
        transport=_models_transport({"id": "bank-judge", "root": "Qwen/Qwen3-27B"}),
    )
    assert chat.endpoint_family() == "qwen"
    other = OpenAICompatibleChat(
        "http://127.0.0.1:8001/v1",
        "bank-judge",
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    assert other.endpoint_family() is None  # a failed probe adds no evidence, never blocks


def test_probe_flag_catches_mislabelled_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model id says claude, the endpoint serves qwen weights: refused."""
    _env(
        monkeypatch,
        JUDGE_T1_MODEL="claude-fake-1",
        JUDGE_T1_BASE_URL="http://127.0.0.1:8001/v1",
        JUDGE_FAMILY_PROBE="1",
    )
    real_get = OpenAICompatibleChat.endpoint_family

    def fake(self: OpenAICompatibleChat, timeout_s: float = 5.0) -> str | None:
        self._client = httpx.Client(
            transport=_models_transport({"id": "claude-fake-1", "root": "Qwen/Qwen3-27B"})
        )
        return real_get(self, timeout_s)

    monkeypatch.setattr(OpenAICompatibleChat, "endpoint_family", fake)
    with pytest.raises(FamilyDeclarationError, match="endpoint metadata"):
        make_judge_chat_model(load_settings(_env_file=None), "t1")


def test_mock_judges_carry_mock_source() -> None:
    chat = make_judge_chat_model(load_settings(_env_file=None), "t1")
    assert isinstance(chat, MockJudgeChat)
    router = JudgeRouter.from_settings(load_settings(_env_file=None))
    assert router.describe()["t1"]["family_source"] == "mock"


def test_family_source_in_verdict_row_payload_card_and_report(clock, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tests.judge.conftest import make_events
    from tests.judge.test_service import BENIGN, make_service

    tables, evidence = MemoryTables(), MemoryEvidence()
    svc = make_service(clock, tables, evidence)
    svc.evaluate_trace(make_events(BENIGN))
    assert tables.tables["verdict"][0]["family_source"] == "mock"
    assert evidence.of_type("judge_verdict")[0]["family_source"] == "mock"

    settings = load_settings(_env_file=None)
    card = build_card(settings)
    assert card["identity"]["tiers"]["t1"]["family_source"] == "mock"
    assert "[mock]" in render_card_md(card)
    report = run_validation(settings, runs=1, record=False)
    assert report["identity"]["t1_family_source"] == "mock"
    assert "family_source: mock" in render_md(report)

    ev = MemoryEvidence()
    run_validation(settings, runs=1, evidence=ev, tables=MemoryTables(), record=True)
    (rec,) = ev.of_type("judge_validation")
    assert rec["t1_family_source"] == "mock" and rec["t2_family_source"] == "mock"
    json.dumps(rec)


def test_declared_test_only_reaches_the_verdict_rows(clock, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from supervisor.judge.service import JudgeService
    from tests.judge.conftest import make_events
    from tests.judge.test_service import BENIGN

    class Real:
        """A non-mock chat whose family was declared under the test-only override."""

        is_mock = False
        family = "qwen"
        family_source = "declared-test-only"

        def __init__(self, model_id: str) -> None:
            self.model_id = model_id

        def complete_json(self, messages, json_schema, timeout_s=None):  # type: ignore[no-untyped-def]
            return {
                "suspicion_bp": 100,
                "label": "benign",
                "evidence_spans": [],
                "rationale": "ok",
                "policy_refs": [],
            }

    t1, t2 = Real("qwen-judge-t1@1"), Real("qwen-judge-t2@1")
    router = JudgeRouter.from_settings(
        load_settings(_env_file=None, judge_t2_sample_bp=0),
        chats={"t1": t1, "t2": t2},
        agent_families={},
    )
    assert router.t1.family_source == "declared-test-only"
    tables, evidence = MemoryTables(), MemoryEvidence()
    JudgeService(router, clock, tables=tables, evidence=evidence).evaluate_trace(
        make_events(BENIGN)
    )
    assert tables.tables["verdict"][0]["family_source"] == "declared-test-only"
    assert evidence.of_type("judge_verdict")[0]["family_source"] == "declared-test-only"


# -- D15 ---------------------------------------------------------------------------------
class FakeState:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def query(self, table: str, *a: Any, **k: Any) -> list[dict[str, Any]]:
        return list(self.rows) if table == "agent" else []


def _qwen_challenger(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        JUDGE_T1_MODEL="claude-haiku-5-5",
        JUDGE_T1_BASE_URL="https://x.example/v1",
        JUDGE_T2_MODEL="gpt-5.4-mini-2026-08-01",
        JUDGE_T2_BASE_URL="https://x.example/v1",
        JUDGE_CHALLENGER_MODEL="qwen3.8-27b-int4",
        JUDGE_CHALLENGER_BASE_URL="http://127.0.0.1:8001/v1",
    )


def test_qwen_challenger_ignores_demo_manifests(monkeypatch: pytest.MonkeyPatch) -> None:
    """D15: the demo manifests are qwen; a qwen challenger no longer stops the router."""
    _qwen_challenger(monkeypatch)
    router = JudgeRouter.from_settings(load_settings(_env_file=None))
    assert router.challenger is not None and router.challenger.family == "qwen"
    assert router.challenger_agent_families == {}
    assert "customer_service" in router.agent_families  # T1/T2 still see every manifest


def test_challenger_is_checked_against_registered_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    _qwen_challenger(monkeypatch)
    state = FakeState([{"agent_id": "credit_memo", "model_family": "qwen", "status": "active"}])
    with pytest.raises(FamilyConflictError, match="credit_memo"):
        JudgeRouter.from_settings(load_settings(_env_file=None), state=state)  # type: ignore[arg-type]


def test_retired_agents_do_not_clash(monkeypatch: pytest.MonkeyPatch) -> None:
    _qwen_challenger(monkeypatch)
    rows = [
        {"agent_id": "old", "model_family": "qwen", "status": "retired"},
        {"agent_id": "new", "model_family": "llama", "status": "active"},
    ]
    state = FakeState(rows)
    router = JudgeRouter.from_settings(load_settings(_env_file=None), state=state)  # type: ignore[arg-type]
    assert set(router.challenger_agent_families) == {"new"}
    assert set(load_registry_families(state, include_retired=False)) == {"new"}  # type: ignore[arg-type]
    assert set(load_registry_families(state)) == {"old", "new"}  # type: ignore[arg-type]


def test_judge_agents_adds_manifests_of_enabled_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    _qwen_challenger(monkeypatch)
    monkeypatch.setenv("JUDGE_AGENTS", "customer_service")
    with pytest.raises(FamilyConflictError, match="customer_service"):
        JudgeRouter.from_settings(load_settings(_env_file=None))


def test_primary_judges_are_still_checked_against_all_manifests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, JUDGE_T1_MODEL="qwen3:8b", JUDGE_T1_BASE_URL="http://127.0.0.1:8001/v1")
    with pytest.raises(FamilyConflictError, match="same as agent"):
        JudgeRouter.from_settings(load_settings(_env_file=None))


def test_mrm_validate_runs_with_a_qwen_challenger(monkeypatch: pytest.MonkeyPatch) -> None:
    _qwen_challenger(monkeypatch)
    report = run_validation(load_settings(_env_file=None), runs=1, record=False)
    assert report["decision"] in ("GO", "NO_GO")


def test_challenger_comparison_section_accepts_a_qwen_challenger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Found by the live run: the comparison router puts the challenger in its T1 slot, which
    was checked against every manifest (qwen demo agents) and stopped `validate`."""
    from supervisor.judge.eval.datasets import build_eval_sets
    from supervisor.judge.mrm.validation import _challenger_section

    _qwen_challenger(monkeypatch)
    settings = load_settings(_env_file=None)
    chal = MockJudgeChat(1, model_id="mock-qwen-challenger-v1", family="qwen")
    primary = JudgeRouter.from_settings(settings, chats={"challenger": chal})
    assert primary.challenger is not None
    items = [i for i in build_eval_sets() if i.split == "heldout"][:6]
    section = _challenger_section(settings, "settings", items, primary)
    assert section["status"] == "ok" and section["n"] == len(items)
