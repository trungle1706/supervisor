"""The questionnaire: schema files are current, help in both languages, bad values rejected."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supervisor.advisory.compliance.facts import from_questionnaire
from supervisor.advisory.compliance.questionnaire import (
    CONTROL_FIELDS,
    EXAMPLE_FILE,
    FIELDS,
    QUESTIONS,
    SCHEMA_FILE,
    QuestionnaireError,
    load_answers_file,
    make_question,
    questionnaire_schema,
    schema_json,
    template_yaml,
    validate_answers,
)

OK = {"product_id": "p1", "name": "P one"}


def test_schema_file_is_current() -> None:
    assert SCHEMA_FILE.read_text(encoding="utf-8") == schema_json(), (
        "run: python -m supervisor.advisory.compliance.questionnaire --write"
    )
    assert json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) == questionnaire_schema()


def test_example_file_is_current_and_valid() -> None:
    assert EXAMPLE_FILE.read_text(encoding="utf-8") == template_yaml()
    p = from_questionnaire(EXAMPLE_FILE)
    assert p.product_id == "my-product"
    assert p.controls.known is False  # blank block = unknown


def test_schema_shape() -> None:
    s = questionnaire_schema()
    assert s["$schema"].endswith("2020-12/schema")
    assert s["required"] == ["product_id", "name"] and s["additionalProperties"] is False
    assert set(s["properties"]) == {f.name for f in FIELDS} | {"controls"}
    assert s["properties"]["max_daily_vnd"]["type"] == ["integer", "null"]
    for prop in s["properties"].values():
        assert " / " in prop["description"]


@pytest.mark.parametrize("f", [*FIELDS, *CONTROL_FIELDS], ids=lambda f: f.name)
def test_help_in_english_and_vietnamese(f) -> None:
    assert f.help_en.strip() and f.help_vi.strip()
    assert any(ord(c) > 127 for c in f.help_vi), f"{f.name}: Vietnamese needs diacritics"
    assert f.help_en != f.help_vi


def test_money_help_names_circular_53_lines() -> None:
    by = {f.name: f for f in FIELDS}
    for name in ("max_transaction_vnd", "max_daily_vnd"):
        assert "Art. 4(2)(a)" in by[name].help_en and "10,000,000" in by[name].help_en
        assert "50,000,000" in by[name].help_en and "100,000,000" in by[name].help_en
    assert "Art. 5(1)(g)(ii)" in by["max_daily_vnd"].help_en
    assert "500,000,000" in by["max_daily_vnd"].help_en
    assert "50,000,000" in by["max_credit_vnd"].help_en


def test_every_fact_has_a_question_text() -> None:
    for f in FIELDS:
        if f.name not in ("product_id", "name", "version", "owner_team", "purpose"):
            assert f.name in QUESTIONS, f.name
    q = make_question("customer_types", ("B", "A", "A"))
    assert q.id == "Q-customer_types" and q.obligation_ids == ("A", "B")
    assert q.text_en and q.text_vi


def test_bad_values_all_listed() -> None:
    bad = {
        "product_id": "no spaces allowed",
        "name": 5,
        "agent_classes": ["payment", "spaceship"],
        "autonomy": "sometimes",
        "cross_border": "yes",
        "max_transaction_vnd": 1.5,
        "max_daily_vnd": True,
        "max_credit_vnd": -1,
        "in_operation_since": "15/10/2026",
        "colour": "red",
        "controls": {"supervised": "yes", "monitors": ["nope"], "extra": 1},
    }
    with pytest.raises(QuestionnaireError) as exc:
        validate_answers(bad, require_identity=True)
    problems = exc.value.problems
    assert len(problems) >= 11
    joined = "\n".join(problems)
    for needle in (
        "product_id",
        "name",
        "agent_classes",
        "autonomy",
        "cross_border",
        "max_transaction_vnd",
        "max_daily_vnd",
        "max_credit_vnd",
        "in_operation_since",
        "colour",
        "controls.supervised",
        "controls.monitors",
        "controls.extra",
    ):
        assert needle in joined, needle


@pytest.mark.parametrize("value", [1.5, 1e8, 100000000.0, True, "100"])
def test_money_rejects_non_integers(value: object) -> None:
    for key in ("max_transaction_vnd", "max_daily_vnd", "max_credit_vnd"):
        with pytest.raises(QuestionnaireError):
            validate_answers({**OK, key: value})


def test_integers_and_blanks_accepted() -> None:
    out = validate_answers(
        {**OK, "max_daily_vnd": 20_000_000, "agent_classes": [], "autonomy": None}
    )
    assert out["max_daily_vnd"] == 20_000_000
    assert out["agent_classes"] == []  # [] = real answer "none"
    assert "autonomy" not in out  # blank = unknown


def test_identity_required_only_for_full_product() -> None:
    assert validate_answers({"customer_types": ["individual"]}) == {
        "customer_types": ["individual"]
    }
    with pytest.raises(QuestionnaireError) as exc:
        validate_answers({}, require_identity=True)
    assert len(exc.value.problems) == 2


def test_date_accepts_iso_string_and_yaml_date(tmp_path: Path) -> None:
    f = tmp_path / "a.yaml"
    f.write_text("in_operation_since: 2026-03-01\n", encoding="utf-8")
    assert validate_answers(load_answers_file(f)) == {"in_operation_since": "2026-03-01"}


def test_policy_files_must_stay_below() -> None:
    with pytest.raises(QuestionnaireError):
        validate_answers({**OK, "controls": {"policy_files": ["../secret.yaml"]}})
    with pytest.raises(QuestionnaireError):
        validate_answers({**OK, "controls": {"policy_files": ["/etc/passwd"]}})


def test_load_answers_file_errors(tmp_path: Path) -> None:
    bad = tmp_path / "b.yaml"
    bad.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(QuestionnaireError):
        load_answers_file(bad)
    bad.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(QuestionnaireError):
        load_answers_file(bad)
    with pytest.raises(QuestionnaireError):
        load_answers_file(tmp_path / "missing.yaml")
