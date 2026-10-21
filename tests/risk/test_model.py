"""WP29: scoring, bands, config and input validation (rubric: operational risk manager)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from supervisor.risk import BANDS, CATEGORIES, TREATMENTS, RiskError, Thresholds, band_of, score_of
from supervisor.risk.model import BAND_RANK, load_config, normalise
from tests.conftest import REPO_ROOT

from .conftest import risk_data


def test_score_is_likelihood_times_impact_for_every_cell() -> None:
    for lik in range(1, 6):
        for imp in range(1, 6):
            assert score_of(lik, imp) == lik * imp


def test_bands_are_monotonic_and_cover_1_to_25() -> None:
    th = Thresholds()
    seen = [th.band(s) for s in range(1, 26)]
    assert [BAND_RANK[b] for b in seen] == sorted(BAND_RANK[b] for b in seen)
    assert set(seen) == set(BANDS)
    assert (th.band(4), th.band(5), th.band(9), th.band(10), th.band(15), th.band(16)) == (
        "low",
        "medium",
        "medium",
        "high",
        "high",
        "critical",
    )


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(RiskError):
        Thresholds(low_max=9, medium_max=5, high_max=15)
    with pytest.raises(RiskError):
        Thresholds(low_max=4, medium_max=9, high_max=25)


def test_config_file_is_illustrative_and_loads() -> None:
    cfg = load_config(REPO_ROOT / "config" / "risk.yaml")
    assert cfg.thresholds.illustrative is True
    assert (cfg.thresholds.low_max, cfg.thresholds.medium_max, cfg.thresholds.high_max) == (
        4,
        9,
        15,
    )
    assert cfg.min_working_controls == 1
    assert "ILLUSTRATIVE" in (REPO_ROOT / "config" / "risk.yaml").read_text(encoding="utf-8")


def test_missing_config_gives_defaults_and_bad_config_is_a_user_error(tmp_path: Path) -> None:
    assert load_config(tmp_path / "none.yaml").thresholds == Thresholds()
    bad = tmp_path / "bad.yaml"
    bad.write_text("bands: {low_max: 20, medium_max: 9, high_max: 15}\n", encoding="utf-8")
    with pytest.raises(RiskError):
        load_config(bad)
    bad.write_text("bands: [1, 2\n", encoding="utf-8")
    with pytest.raises(RiskError):
        load_config(bad)


def test_valid_record_normalises() -> None:
    out = normalise(risk_data())
    assert out["category"] in CATEGORIES and out["treatment"] in TREATMENTS
    assert out["residual_likelihood"] == 2 and out["marginal_risk"] is None


def test_residual_defaults_to_inherent() -> None:
    data = risk_data()
    for k in ("residual_likelihood", "residual_impact"):
        del data[k]
    out = normalise(data)
    assert (out["residual_likelihood"], out["residual_impact"]) == (4, 5)


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"title": ""}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"category": "weather"}, "category"),
        ({"treatment": "ignore"}, "treatment"),
        ({"status": "closed"}, "status"),
        ({"owner": ""}, "owner"),
        ({"agent_id": None, "node_id": None}, "agent_id or an inventory node_id"),
        ({"inherent_likelihood": 0}, "between"),
        ({"inherent_impact": 6}, "between"),
        ({"inherent_impact": 5.0}, "whole number"),
        ({"inherent_likelihood": "4"}, "whole number"),
        ({"inherent_likelihood": True}, "whole number"),
        ({"residual_likelihood": 5}, "cannot be above"),
        ({"marginal_risk": 9}, "between"),
        ({"review_date": "20 Oct"}, "date"),
        ({"review_date": None}, "review_date"),
        ({"treatment": "accept"}, "accept"),
        ({"agent_id": "a b"}, "agent_id"),
    ],
)
def test_bad_input_is_a_clear_user_error(change: dict[str, Any], fragment: str) -> None:
    with pytest.raises(RiskError) as err:
        normalise(risk_data(**change))
    assert fragment in str(err.value)


def test_accept_needs_equal_residual_and_a_note() -> None:
    ok = normalise(
        risk_data(
            treatment="accept",
            residual_likelihood=4,
            residual_impact=5,
            treatment_note="Board accepted on 2026-10-01",
        )
    )
    assert ok["treatment"] == "accept"
    with pytest.raises(RiskError):
        normalise(risk_data(treatment="accept", treatment_note="n"))  # residual lowered


def test_band_of_helper_uses_default_thresholds() -> None:
    assert band_of(16) == "critical" and band_of(1) == "low"
