"""Fairness slices: injected bias -> gap computed, stored, case opened; n < 30 suppressed."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from supervisor.config import load_settings
from supervisor.core.errors import ConfigError
from supervisor.jobs import fairness as fairness_job
from supervisor.monitors.common import MonitorContext
from supervisor.monitors.fairness import (
    FairnessConfig,
    FairnessMonitor,
    FairnessRecord,
    SyntheticAttributeLookup,
    compute,
    fairlearn_available,
    subject_hash,
)
from supervisor.monitors.seed import LoanDecision, as_rows, loan_decision_events, loan_decisions
from tests.conftest import REPO_ROOT
from tests.judge.conftest import assert_no_floats
from tests.monitors.conftest import T0

KEY = b"test-fairness-key"
ATTRS = ["gender", "age_band", "province_code", "language"]


def _records(decisions: list[LoanDecision]) -> list[FairnessRecord]:
    return [
        FairnessRecord(
            subject_hash(KEY, d.application.application_id),
            {
                "gender": d.application.gender,
                "age_band": d.application.age_band,
                "province_code": d.application.province_code,
                "language": d.application.language,
            },
            d.decision == "approve",
            d.blocked,
        )
        for d in decisions
    ]


class ListSource:
    def __init__(self, records: list[FairnessRecord]) -> None:
        self._records = records

    def records(self, agent_id, ts_from, ts_to):  # noqa: ANN001, ANN201
        return self._records if agent_id == "credit_prequal" else []


def _biased() -> list[FairnessRecord]:
    return _records(loan_decisions(1200, bias=lambda a: a.gender == "female", bias_drop_bp=6000))


def test_committed_config_loads_and_never_slices_ethnicity_or_religion() -> None:
    cfg = FairnessConfig.load(REPO_ROOT / "config" / "fairness.yaml")
    assert cfg.active_attributes == ATTRS
    assert cfg.min_cell_n == 30
    for bad in ("ethnicity", "religion", "Religion"):
        with pytest.raises(ConfigError):
            FairnessConfig.from_dict({"attributes": {bad: {"permitted": True}}})
    with pytest.raises(ConfigError):
        FairnessConfig.from_dict({"min_cell_n": 10})
    cfg2 = FairnessConfig.from_dict(
        {"attributes": {"gender": {"permitted": True}, "language": {"permitted": False}}}
    )
    assert cfg2.active_attributes == ["gender"]
    with pytest.raises(ConfigError):
        compute([], ["religion"])


def test_injected_gender_bias_gap_and_case(adapters, clock, evidence) -> None:
    ctx = MonitorContext.from_adapters(adapters, evidence)
    cfg = FairnessConfig()
    monitor = FairnessMonitor(ctx, cfg, ListSource(_biased()), method="python")
    res = monitor.run()
    report = res.reports["credit_prequal"]
    gender = report.attributes["gender"]
    assert gender.approval_gap_bp is not None and gender.approval_gap_bp > 2000
    other = [report.attributes[a].approval_gap_bp for a in ("language",)]
    assert all(g is not None and g < 2000 for g in other)
    assert len(res.cases_opened) == 1
    case = adapters.state.get("cases", {"case_id": res.cases_opened[0]})
    assert case["case_type"] == "fairness" and case["severity"] == "medium"
    assert "gender" in case["summary"]

    rows = adapters.tables.query("fairness_slice", {"run_id": res.run_id})
    assert {r["attribute"] for r in rows} == set(ATTRS)
    for r in rows:
        if r["suppressed"]:
            assert r["n"] is None and r["approval_rate_bp"] is None
        else:
            assert r["n"] >= 30 and isinstance(r["approval_rate_bp"], int)
    assert any(r["suppressed"] for r in rows if r["attribute"] == "province_code")
    metric = adapters.state.get(
        "oversight_metric", {"metric_date": T0.date(), "agent_id": "credit_prequal"}
    )
    assert metric["fairness_gap_bp"] == report.max_approval_gap_bp
    for t, _, p in evidence.entries:
        assert_no_floats(p)
        if t in ("fairness_run", "case_opened"):
            for a in p["attributes"]:
                assert all(c["n"] >= 30 for c in a["cells"])  # suppressed cells never leave
    print(
        f"[OK] fairness: gender approval gap {gender.approval_gap_bp} bp "
        f"(threshold {cfg.approval_gap_threshold_bp}), cells "
        + ", ".join(f"{c.cell}={c.approval_rate_bp}bp/n{c.n}" for c in gender.cells)
        + f", case {res.cases_opened[0]}"
    )
    # Second run: the open fairness case is not duplicated.
    assert monitor.run().cases_opened == []


def test_no_bias_no_case(adapters, evidence) -> None:
    ctx = MonitorContext.from_adapters(adapters, evidence)
    res = FairnessMonitor(ctx, FairnessConfig(), ListSource(_records(loan_decisions(1200))),
                          method="python").run()  # fmt: skip
    assert res.cases_opened == []
    assert res.reports["credit_prequal"].attributes["gender"].approval_gap_bp < 2000


@pytest.mark.skipif(not fairlearn_available(), reason="monitors extra not installed")
def test_fairlearn_and_python_paths_agree() -> None:
    records = _biased()
    a = compute(records, ATTRS, method="fairlearn")
    b = compute(records, ATTRS, method="python")
    assert a.method == "fairlearn" and b.method == "python"
    for name in ATTRS:
        assert a.attributes[name].cells == b.attributes[name].cells
        assert a.attributes[name].approval_gap_bp == b.attributes[name].approval_gap_bp


def test_small_cells_suppressed() -> None:
    records = _records(loan_decisions(50))
    report = compute(records, ["gender", "province_code"], method="python")
    assert all(c.suppressed for c in report.attributes["province_code"].cells)
    assert report.attributes["province_code"].approval_gap_bp is None


def test_job_end_to_end_from_events(adapters, evidence, tmp_path: Path) -> None:
    """Recorder decide_prequal events + synthetic attribute lookup by hashed id."""
    cfg_path = tmp_path / "fairness.yaml"
    cfg_path.write_text(
        "agents: [credit_prequal]\nsynthetic_seed: 11\nsynthetic_customers: 1200\n"
        "attributes:\n  gender: {permitted: true}\n  language: {permitted: false}\n",
        encoding="utf-8",
    )
    decisions = loan_decisions(1200, bias=lambda a: a.gender == "female", bias_drop_bp=6000)
    adapters.tables.append(
        "agent_event", as_rows(loan_decision_events(decisions, T0 - timedelta(days=1)))
    )
    settings = load_settings()
    ctx = MonitorContext.from_adapters(adapters, evidence)
    out = fairness_job.run(ctx, settings, config_path=cfg_path, method="python")
    assert out["status"] == "ok" and out["cases_opened"] == 1 and out["max_gap_bp"] > 2000
    rows = adapters.tables.query("fairness_slice", {"attribute": "language"})
    assert rows == []  # permitted: false -> not computed
    lookup = SyntheticAttributeLookup(settings.mask_key[0], 11, 1200)
    h = subject_hash(settings.mask_key[0], decisions[0].application.application_id)
    assert lookup.attributes(h)["gender"] == decisions[0].application.gender
