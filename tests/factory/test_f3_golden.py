"""WP-F3: golden gate cases (schema, stratification, masker, floats), calibration labels, legacy
conversion."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from supervisor.factory import caps, golden

IDS = ["A", "B", "C"]


def case(n: int, cid: str = "A", verdict: str = "pass", **over: Any) -> dict[str, Any]:
    c: dict[str, Any] = {
        "case_id": f"c{n:03d}",
        "inputs": {"system": {"owner_user": "chu-he-thong"}, "documents": []},
        "expected": {cid: verdict},
        "expected_evidence_refs": ["doc#1"],
        "rubric_notes": "ghi chu",
    }
    c.update(over)
    return c


def test_a_valid_case_is_accepted_and_normalised() -> None:
    ok, bad = golden.check_gate_cases([case(1)], IDS)
    assert (
        not bad
        and ok[0]["expected"] == {"A": "pass"}
        and ok[0]["expected_evidence_refs"] == ["doc#1"]
    )


@pytest.mark.parametrize(
    ("over", "word"),
    [
        ({"case_id": "bad id!"}, "case_id"),
        ({"inputs": {}}, "inputs"),
        ({"inputs": {"secrets": {}}}, "unknown key"),
        ({"inputs": {"system": {"score": 0.5}}}, "decimal point"),
        ({"expected": {}}, "expected"),
        ({"expected": {"Z": "pass"}}, "not an item"),
        ({"expected": {"A": "maybe"}}, "verdict"),
        ({"expected_evidence_refs": "doc"}, "expected_evidence_refs"),
        ({"expected_evidence_refs": ["x"] * 21}, "expected_evidence_refs"),
        ({"rubric_notes": "x" * 301}, "rubric_notes"),
        ({"rubric_notes": "goi 0912345678"}, "personal data"),
        (
            {
                "inputs": {
                    "documents": [
                        {
                            "doc_id": "d",
                            "sections": [{"ref": "d#1", "text": "Email a.b@example.com"}],
                        }
                    ]
                }
            },
            "personal data",
        ),
        ({"inputs": {"system": {"blob": "x" * 70_000}}}, "larger"),
    ],
)
def test_every_refusal_names_its_reason(over: dict[str, Any], word: str) -> None:
    ok, bad = golden.check_gate_cases([case(1, **over)], IDS)
    assert not ok and word in bad[0]["reason"]


def test_a_repeated_case_id_is_refused() -> None:
    ok, bad = golden.check_gate_cases([case(1), case(1)], IDS)
    assert len(ok) == 1 and "twice" in bad[0]["reason"]


def test_stratification_needs_fifty_cases_and_every_item() -> None:
    cases = [case(i, "A") for i in range(caps.GOLDEN_MIN_CASES)]
    s = golden.gate_stratification(cases, IDS)
    assert s["total"] == 50 and s["uncovered"] == ["B", "C"] and not s["ready"]
    assert s["problems"] == ["items_without_case: B, C"]
    few = golden.gate_stratification([case(1, "A"), case(2, "B"), case(3, "C")], IDS)
    assert few["problems"] == ["too_few_cases: 3 of 50"] and not few["ready"]
    full = [case(i, IDS[i % 3], ["pass", "fail", "question"][i % 3]) for i in range(60)]
    ok = golden.gate_stratification(full, IDS)
    assert ok["ready"] and ok["problems"] == [] and ok["per_item"] == {"A": 20, "B": 20, "C": 20}
    assert ok["per_verdict"]["pass"] == 20 and ok["per_verdict"]["not_applicable"] == 0
    assert all(isinstance(v, int) for v in ok["per_item"].values())


def test_gate_cases_are_stored_and_merged(tmp_path: Path) -> None:
    ok, _ = golden.check_gate_cases([case(1), case(2)], IDS)
    golden.store_gate_cases(tmp_path, "my-agent", ok)
    ok2, _ = golden.check_gate_cases([case(2, "B"), case(3)], IDS)
    golden.store_gate_cases(tmp_path, "my-agent", ok2)
    stored = golden.load_gate_cases(tmp_path, "my-agent")
    assert [c["case_id"] for c in stored] == ["c001", "c002", "c003"]
    assert stored[1]["expected"] == {"B": "pass"}  # a new case replaces the old one with its id
    sha1 = golden.golden_sha256(tmp_path, "my-agent")
    golden.store_gate_cases(tmp_path, "my-agent", golden.check_gate_cases([case(4)], IDS)[0])
    assert golden.golden_sha256(tmp_path, "my-agent") != sha1


def test_legacy_f2_cases_become_gate_cases(tmp_path: Path) -> None:
    legacy = [
        {
            "case_id": "old1",
            "checklist_id": "A",
            "input": "He thong co chu so huu.",
            "expected_verdict": "pass",
            "note": "n",
        },
    ]
    ok, bad = golden.check_cases(legacy, IDS)
    assert not bad
    golden.store_cases(tmp_path, "my-agent", ok)
    gated = golden.all_gate_cases(tmp_path, "my-agent")
    assert gated[0]["expected"] == {"A": "pass"}
    sec = gated[0]["inputs"]["documents"][0]["sections"][0]
    assert sec["ref"] == "old1#1" and sec["text"] == "He thong co chu so huu."
    # a gate case with the same id wins over the legacy one
    golden.store_gate_cases(
        tmp_path, "my-agent", golden.check_gate_cases([case(1) | {"case_id": "old1"}], IDS)[0]
    )
    assert golden.all_gate_cases(tmp_path, "my-agent")[0]["inputs"].get("documents") == []


def test_json_rows_parser(tmp_path: Path) -> None:
    raw = b'{"cases": [{"case_id": "x"}]}'
    assert golden.parse_json_rows("f.json", raw) == [{"case_id": "x"}]
    assert golden.parse_json_rows("f.json", b'[{"a": 1}]') == [{"a": 1}]
    for name, data in (
        ("f.csv", raw),
        ("f.json", b"not json"),
        ("f.json", b"[]"),
        ("f.json", b"[1]"),
    ):
        with pytest.raises(golden.GoldenError):
            golden.parse_json_rows(name, data)
    assert golden.is_gate_upload([{"inputs": {}}]) and not golden.is_gate_upload([{"input": "t"}])


# ------------------------------------------------------------------------------ labels


def label(
    case_id: str = "c001", finding: str = "f-A", verdict: str = "pass", **over: Any
) -> dict[str, Any]:
    row = {
        "case_id": case_id,
        "finding_id": finding,
        "human_verdict": verdict,
        "label_by": "reviewer.binh",
        "labelled_at": "2026-10-20T08:00:00Z",
    }
    row.update(over)
    return row


def test_labels_are_checked_and_stored(tmp_path: Path) -> None:
    ok, bad = golden.check_labels([label(), label("c002", "f-B", "fail")], ["c001", "c002"], IDS)
    assert not bad and ok[0]["source"] == "golden"
    golden.store_labels(tmp_path, "my-agent", ok)
    golden.store_labels(
        tmp_path, "my-agent", golden.check_labels([label(verdict="question")], ["c001"], IDS)[0]
    )
    rows = golden.load_labels(tmp_path, "my-agent")
    assert [(r["case_id"], r["human_verdict"]) for r in rows] == [
        ("c001", "question"),
        ("c002", "fail"),
    ]
    golden.remove_label(tmp_path, "my-agent", "c001", "f-A")
    assert [r["case_id"] for r in golden.load_labels(tmp_path, "my-agent")] == ["c002"]


@pytest.mark.parametrize(
    "over",
    [
        {"case_id": "unknown"},
        {"finding_id": "f-Z"},
        {"human_verdict": "yes"},
        {"label_by": ""},
        {"labelled_at": "yesterday"},
    ],
)
def test_bad_labels_are_refused(over: dict[str, Any]) -> None:
    ok, bad = golden.check_labels([label(**over)], ["c001"], IDS)
    assert not ok and bad[0]["reason"]


def test_the_label_shape_is_the_brief() -> None:
    ok, _ = golden.check_labels([label()], ["c001"], IDS)
    assert set(ok[0]) >= {"case_id", "finding_id", "human_verdict", "label_by", "labelled_at"}
    assert golden.checklist_of_finding("f-MR-01") == "MR-01"
    assert copy.deepcopy(ok)  # plain data only
