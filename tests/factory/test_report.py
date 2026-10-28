"""assessment_report_v1: evidence rule, no floats, summary counts, trace of integers."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from supervisor.factory import caps
from supervisor.factory.__main__ import format_errors
from supervisor.factory.schemas import AssessmentReportV1


def errors(doc: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as exc:
        AssessmentReportV1.model_validate(doc)
    return format_errors(exc.value)


def assert_names(doc: dict[str, Any], field: str) -> None:
    lines = errors(doc)
    assert any(field in line for line in lines), (field, lines)


def test_example_is_valid(report: dict) -> None:
    AssessmentReportV1.model_validate(report)


@pytest.mark.parametrize("verdict", ["pass", "fail"])
def test_pass_and_fail_need_evidence(report: dict, verdict: str) -> None:
    report["findings"][0]["verdict"] = verdict
    report["findings"][0]["evidence"] = []
    report["summary"] = {
        "total": 2,
        "passed": 1 if verdict == "pass" else 0,
        "failed": 1 if verdict == "fail" else 0,
        "not_applicable": 0,
        "questions": 1,
    }
    assert_names(report, "findings[0]")
    assert any("evidence" in line for line in errors(report))


@pytest.mark.parametrize("verdict", ["not_applicable", "question"])
def test_other_verdicts_may_have_no_evidence(report: dict, verdict: str) -> None:
    report["findings"][0]["verdict"] = verdict
    report["findings"][0]["evidence"] = []
    report["summary"] = {
        "total": 2,
        "passed": 0,
        "failed": 0,
        "not_applicable": 1 if verdict == "not_applicable" else 0,
        "questions": 1 + (1 if verdict == "question" else 0),
    }
    AssessmentReportV1.model_validate(report)


def test_float_confidence_is_refused(report: dict) -> None:
    report["findings"][0]["confidence"] = 0.9
    assert_names(report, "findings[0].confidence")


def test_float_in_counts_and_trace_is_refused(report: dict) -> None:
    report["summary"]["total"] = 2.0
    assert_names(report, "summary.total")
    report["summary"]["total"] = 2
    report["harness_trace"]["context"]["tokens_used"] = 4200.5
    assert_names(report, "harness_trace.context.tokens_used")


def test_rationale_cap(report: dict) -> None:
    report["findings"][0]["rationale"] = "r" * (caps.RATIONALE_MAX + 1)
    assert_names(report, "findings[0].rationale")


def test_dimension_must_be_one_of_the_eight(report: dict) -> None:
    report["dimension_id"] = "sustainability"
    assert_names(report, "dimension_id")


@pytest.mark.parametrize("field", ["verdict"])
def test_verdict_vocabulary(report: dict, field: str) -> None:
    report["findings"][0][field] = "n/a"
    assert_names(report, "findings[0].verdict")


def test_summary_must_match_the_findings(report: dict) -> None:
    report["summary"]["passed"] = 2
    assert any("summary" in line for line in errors(report))


def test_duplicate_finding_id(report: dict) -> None:
    report["findings"][1]["finding_id"] = report["findings"][0]["finding_id"]
    assert any("finding_id" in line for line in errors(report))


def test_timestamp_is_rfc3339_utc(report: dict) -> None:
    report["created_at"] = "28/10/2026"
    assert_names(report, "created_at")


def test_loop_trace_stops_inside_the_cap(report: dict) -> None:
    report["harness_trace"]["loop"]["iterations"] = caps.LOOP_MAX_ITERATIONS + 1
    assert_names(report, "harness_trace.loop.iterations")
    report["harness_trace"]["loop"]["iterations"] = 1
    report["harness_trace"]["loop"]["stopped_by"] = "boredom"
    assert_names(report, "harness_trace.loop.stopped_by")


def test_evidence_line_needs_file(report: dict) -> None:
    report["findings"][0]["evidence"] = [{"kind": "fact", "ref": "fct_1", "line": 3}]
    assert any("line needs file" in line for line in errors(report))


def test_unknown_field_in_trace(report: dict) -> None:
    report["harness_trace"]["loop"]["raw_text"] = "document text"
    assert_names(report, "harness_trace.loop.raw_text")
