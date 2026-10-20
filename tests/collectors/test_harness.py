"""Regression test of the WP38 collectors harness (mock path = fake framework objects)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from supervisor.collectors import harness as h
from supervisor.collectors.probes import PROBES, run_probes
from supervisor.gateway.adapters import common


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    return h.run_all(latency_n=60)


def test_help_works() -> None:
    with pytest.raises(SystemExit) as e:
        h.main(["--help"])
    assert e.value.code == 0


def test_contract_is_complete_and_passes(result: dict[str, Any]) -> None:
    c = result["contract"]
    assert c["n"] == len(h.ADAPTERS) * len(h.SCENARIOS) * len(h.SETTINGS) == 144
    assert c["failures"] == [], c["failures"][:3]
    assert c["ci_bp"][0] > 9500


def test_every_status_of_the_brief_is_in_the_recorded_answers() -> None:
    answers = h.load_answers()
    for scenario in ("allow", "report", "transform", "pause", "block", "skip"):
        assert (scenario, "flat") in answers
    statuses = {s: a.get("status") for (s, shape), a in answers.items() if shape == "flat"}
    assert statuses["allow"] == "allow" and statuses["report"] == "report"
    assert statuses["transform"] == "transform" and statuses["pause"] == "pause"
    assert statuses["block"] == "block" and statuses["skip"] == "skip"
    assert set(h.SCENARIOS) - {"401", "429", "timeout"} <= {s for s, _ in answers}
    assert ("transform", "body") in answers and ("transform", "messages") in answers


def test_recorded_answers_hold_no_raw_personal_data() -> None:
    text = h.ANSWERS.read_text(encoding="utf-8")
    assert "0912345678" not in text and "NGUYEN VAN THU" not in text
    assert "001203004567" not in text


def test_probes_are_at_least_twenty_and_pass() -> None:
    assert len(PROBES) >= 20
    res = run_probes()
    assert res["failed"] == [], res["failed"]


def test_no_drop_below_the_baseline(result: dict[str, Any]) -> None:
    base = json.loads(h.BASELINE.read_text(encoding="utf-8"))
    assert h.check_against_baseline(result, base) == []
    assert base["contract"]["n"] == 144 and base["probes"]["n"] >= 26


def test_overhead_is_inside_the_illustrative_limit(result: dict[str, Any]) -> None:
    for name, v in result["latency_us"].items():
        assert v["p95"] <= h.THRESHOLDS["overhead_p95_us"], name
    assert result["verdict"]["overall"] == "GO"


def test_the_harness_fails_when_an_adapter_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mutation: an adapter that treats an outage as allowed must be caught by the contract."""
    real = common.GateClient.check

    def lenient(self: Any, *a: Any, **kw: Any) -> Any:
        ans = real(self, *a, **kw)
        if ans.rule_id in common.UNAVAILABLE_RULES:
            raw = {"allow": True, "action": "alert", "rule_id": ans.rule_id, "reason": "x"}
            return common.GateAnswer(raw, ans.correlation_id, ans.tool_name, ans.direction)
        return ans

    monkeypatch.setattr(common.GateClient, "check", lenient)
    res = h.run_contract(h.load_answers())
    assert res["pass"] < res["n"]
    assert any(
        f["scenario"] in ("429", "timeout") and f["tool_class"] == "money" for f in res["failures"]
    )


def test_the_report_renders(result: dict[str, Any]) -> None:
    md = h.render_md(result, "abc", "2026-10-20")
    assert "Collectors validation report" in md and "P26" in md and "ILLUSTRATIVE" in md


def test_cli_output_is_ascii(capsys: pytest.CaptureFixture[str]) -> None:
    code = h.main(["--check"])
    out = capsys.readouterr().out
    assert code == 0 and out.isascii() and "OVERALL: GO" in out and "[OK]" in out
