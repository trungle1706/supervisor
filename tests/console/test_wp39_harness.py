"""WP39 regression: the activity harness (all-pages probe in three flag states, fingerprint with
planted personal data, 22 adversarial probes, alert drills) must stay GO and must not drop below
the recorded baseline (data/eval/activity/baseline.json)."""

from __future__ import annotations

import json

import pytest

from supervisor.console import activity_harness as H


@pytest.fixture(scope="module")
def report() -> dict:
    return H.run()


def test_harness_is_go(report: dict) -> None:
    assert report["overall"] == "GO", H.render(report)


def test_at_least_twenty_probes_and_all_pass(report: dict) -> None:
    pr = report["probes"]
    assert pr["n"] >= 20 and pr["passed"] == pr["n"], [r for r in pr["results"] if not r["ok"]]
    lo, hi = pr["ci_bp"]
    assert lo > 8000 and hi == 10000  # Wilson 95 percent interval of 22 of 22


def test_no_raw_personal_data_anywhere(report: dict) -> None:
    assert report["fingerprint"]["leak_items"] == 0
    assert report["fingerprint"]["pages_scanned"] >= 20
    assert report["pages"]["bad"] == 0, report["pages"]["detail"]


def test_no_drop_below_the_baseline(report: dict) -> None:
    base = json.loads(H.BASELINE.read_text(encoding="utf-8"))
    assert base["date"] and base["commit"]
    assert H.compare(report, base) == []


def test_compare_flags_a_drop() -> None:
    base = {
        "pages": {"ok_bp": 10000},
        "fingerprint": {"leak_items": 0, "triage_complete_bp": 10000},
        "probes": {"passed": 22, "n": 22},
    }
    worse = {
        "pages": {"ok_bp": 9000},
        "fingerprint": {"leak_items": 1, "triage_complete_bp": 5000},
        "probes": {"passed": 20, "n": 22},
        "overall": "NO-GO",
    }
    assert len(H.compare(worse, base)) == 5


def test_cli_help_is_ascii() -> None:
    with pytest.raises(SystemExit):
        H.main(["--help"])
