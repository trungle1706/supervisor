"""WP-D3: the guard_model harness on the WP25 corpus (mock adapter in CI, no network)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from supervisor.adapters.guard.classifier_endpoint import ClassifierEndpointGuard
from supervisor.adapters.guard.mock import MockGuardModel
from supervisor.detectors import guard_harness as gh
from tests.conftest import REPO_ROOT


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return gh.run()


def test_the_corpus_is_the_wp25_one_with_guard_codes() -> None:
    items = gh.load_split("dev")
    assert len(items) == 1200 and {i["detector"] for i in items} == {"guard_model"}
    codes = {c for i in items for c in i["expect_codes"]}
    assert codes <= {"guard.jailbreak", "guard.indirect_injection"} and codes
    assert gh.load_split("adversarial") and gh.load_split("heldout")


def test_a_mock_run_is_labelled_deterministic_and_never_go(report: dict[str, Any]) -> None:
    again = gh.run()
    strip = lambda r: {k: v for k, v in r.items() if k not in ("splits", "go_no_go")}  # noqa: E731
    assert strip(report) == strip(again)
    for sp in ("dev", "heldout", "adversarial"):
        a, b = report["splits"][sp], again["splits"][sp]
        for k in ("n", "tp", "fp", "fn", "recall_bp", "precision_bp", "typed_recall_bp"):
            assert a[k] == b[k]
    assert report["mode"] == "mock" and report["model"]["kind"] == "mock"
    assert report["verdict"] == "NO-GO"
    assert report["go_no_go"]["_note"]["verdict"] == "MOCK"


def test_privacy_and_fragments_hold_on_the_whole_corpus(report: dict[str, Any]) -> None:
    for sp, s in report["splits"].items():
        assert s["leak_items"] == 0, sp
        assert s["fragment_exact_bp"] in (None, 10_000), sp
        assert not any(k.startswith("not_executed") for k in s["taxonomy"]), sp


def test_the_run_matches_the_recorded_mock_baseline(report: dict[str, Any]) -> None:
    baseline = json.loads(gh.BASELINE.read_text(encoding="utf-8"))
    assert baseline["mode"] == "mock"
    assert gh.compare(report, baseline) == []
    worse = json.loads(json.dumps(baseline))
    worse["splits"]["dev"]["recall_bp"] += 1
    assert gh.compare(report, worse)


def test_a_real_port_gives_a_real_run_but_the_corpus_still_decides() -> None:
    class Real(MockGuardModel):
        name = "real-fake"
        model_id = "real-fake-1"
        is_mock = False

    r = gh.run(["dev"], port=Real())
    assert r["mode"] == "real" and r["go_no_go"]["_note"]["verdict"] == "REAL"
    assert r["verdict"] == "NO-GO"  # cue words do not reach the illustrative thresholds


def test_the_environment_url_selects_the_real_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GUARD_MODEL_URL", raising=False)
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", str(REPO_ROOT / "does-not-exist.env"))
    assert gh.real_port_from_env() is None
    monkeypatch.setenv("GUARD_MODEL_URL", "http://127.0.0.1:9/guard")
    port = gh.real_port_from_env()
    assert isinstance(port, ClassifierEndpointGuard)


def test_the_report_renders(report: dict[str, Any]) -> None:
    text = gh.render_text(report)
    md = gh.render_markdown(report)
    assert "VERDICT: NO-GO" in text and "MockGuardModel" in text
    assert "never be GO" in md and "| dev |" in md
