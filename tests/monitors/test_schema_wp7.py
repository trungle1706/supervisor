"""WP7 schema additions: verdict judge columns are filled by the judge service."""

from __future__ import annotations

from supervisor.config import load_settings
from supervisor.core.schema import load_model
from supervisor.judge.mockjudge import MockJudgeChat
from supervisor.judge.router import JudgeRouter
from supervisor.judge.service import JudgeService
from tests.judge.conftest import make_events


def test_new_tables_and_columns_exist() -> None:
    model = load_model()
    cols = set(model.table("verdict").column_names)
    assert {"score_bp", "role", "region", "model_version", "mask_version"} <= cols
    for name in (
        "policy_baseline",
        "policy_threshold",
        "fairness_slice",
        "monitor_state",
        "scheduler_lease",
    ):
        assert model.table(name).name == name
    assert "case_type" in model.table("cases").column_names


def test_judge_fills_verdict_columns(adapters, clock, evidence) -> None:
    settings = load_settings(judge_t2_sample_bp=0, judge_region="vn-hcm")
    chats = {"t1": MockJudgeChat(1, model_id="mock-judge-t1"), "t2": MockJudgeChat(2)}
    router = JudgeRouter.from_settings(settings, chats=chats)
    svc = JudgeService(router, clock, tables=adapters.tables, evidence=evidence)
    out = svc.evaluate_trace(make_events(["Xem so du tai khoan"], trace_id="tr-x"))
    rows = adapters.tables.query("verdict", {"trace_id": "tr-x"})
    assert rows and len(rows) == len(out.verdicts)
    for r in rows:
        assert r["role"] == "primary"
        assert r["region"] == "vn-hcm"
        assert r["model_version"]
        assert r["mask_version"]
        assert isinstance(r["score_bp"], int) and 0 <= r["score_bp"] <= 10000
