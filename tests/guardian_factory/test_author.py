"""WP-G1: plain-words authoring. The library works with no model; the model path is validated."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.guardian_factory.author import Author, over_broad_pct
from supervisor.guardian_factory.benign_sample import benign_sample
from supervisor.guardian_factory.definition import GuardianFactoryError

from .conftest import FakeChat


def test_library_account_number_without_a_model() -> None:
    out = Author(chat=None).draft("regex", "Hide every bank account number in the tool arguments")
    assert out["source"] == "library" and out["library_id"] == "account_number"
    assert re.search(out["config"]["pattern"], "chuyen den tai khoan 190312345678 nhe")
    assert not re.search(out["config"]["pattern"], "don hang 12345")
    assert out["saved"] is False and out["over_broad"] is False


def test_library_phone_vietnamese_sentence() -> None:
    out = Author().draft("regex", "Che số điện thoại của khách")
    assert out["library_id"] == "phone_vn"
    assert re.search(out["config"]["pattern"], "goi 0912345678 ngay")
    assert re.search(out["config"]["pattern"], "goi +84912345678 ngay")


def test_library_cccd() -> None:
    out = Author().draft("regex", "Mask the CCCD number")
    assert out["library_id"] == "cccd"
    assert re.search(out["config"]["pattern"], "CCCD 079123456789")
    assert not re.search(out["config"]["pattern"], "so 1234567")


def test_library_amount_and_card() -> None:
    out = Author().draft("regex", "Flag the amount of money written in VND")
    assert out["library_id"] == "amount_vnd"
    assert re.search(out["config"]["pattern"], "chuyen 1.500.000 đồng")
    out = Author().draft("regex", "Block the card number")
    assert out["library_id"] == "card_number"


def test_library_named_words() -> None:
    out = Author().draft("keyword_list", "Block the words \"chuyển khoản gấp\", 'mã bí mật'")
    assert out["config"]["words"] == ["chuyển khoản gấp", "mã bí mật"]
    out = Author().draft("keyword_list", "Words: alpha, beta, gamma.")
    assert out["config"]["words"] == ["alpha", "beta", "gamma"]


def test_no_library_match_and_no_model_says_model_not_configured() -> None:
    with pytest.raises(GuardianFactoryError) as e:
        Author(chat=None).draft("regex", "match order references that start with ZX")
    assert e.value.code == "model_not_configured" and "model not configured" in str(e.value)
    for type_ in ("judge_prompt", "policy"):
        with pytest.raises(GuardianFactoryError) as e:
            Author(chat=None).draft(type_, "anything")
        assert e.value.code == "model_not_configured"


def test_model_path_regex_is_validated_and_returned() -> None:
    chat = FakeChat(
        {"name": "ZX refs", "description": "d", "config": {"pattern": r"\bZX\d{4,8}\b"}}
    )
    out = Author(chat=chat).draft("regex", "match order references that start with ZX")
    assert out["source"] == "model" and out["model_id"] == "fake-model"
    assert out["config"]["pattern"] == r"\bZX\d{4,8}\b" and out["saved"] is False
    assert len(chat.calls) == 1


def test_model_sentence_is_masked_and_scrubbed_before_the_call() -> None:
    class Mask:
        def mask(self, text: str) -> str:
            return text.replace("0912345678", "<PHONE>")

    chat = FakeChat({"config": {"pattern": r"ZX\d{4}"}})
    Author(chat=chat, masker=Mask()).draft("regex", "ZX refs, for example 0912345678")
    sent = chat.calls[0][1]["content"]
    assert "0912345678" not in sent and "<PHONE>" in sent


def test_model_judge_prompt_and_policy() -> None:
    judge = {
        "config": {
            "prompt": "Does the text threaten the customer?",
            "verdict_labels": ["ok", "threat"],
            "fail_labels": ["threat"],
        }
    }
    out = Author(chat=FakeChat(judge)).draft("judge_prompt", "Find threats")
    assert out["config"]["fail_labels"] == ["threat"]
    pol = {
        "config": {
            "rules": [
                {
                    "id": "cap",
                    "when": [{"kind": "amount", "op": "gt", "name": "amount", "value": 100}],
                    "then": "forbid",
                }
            ]
        }
    }
    out = Author(chat=FakeChat(pol)).draft("policy", "Forbid transfers over 100")
    assert out["config"]["default"] == "permit"


@pytest.mark.parametrize(
    "answer",
    [
        {"config": {"pattern": r"(a+)+b"}},  # nested repeat: the existing safety check refuses it
        {"config": {"pattern": "a*"}},  # matches the empty text
        {"config": {"pattern": "a", "danger": 1}},  # unknown key
        {"config": "not an object"},
        {"nothing": 1},
        {"config": {"pattern": "a"}, "extra": 1},
    ],
)
def test_bad_model_output_is_refused(answer: dict[str, Any]) -> None:
    with pytest.raises(GuardianFactoryError) as e:
        Author(chat=FakeChat(answer)).draft("regex", "something odd with ZX")
    assert e.value.code == "model_output_refused"
    assert e.value.problems


def test_bad_model_output_names_the_field() -> None:
    with pytest.raises(GuardianFactoryError) as e:
        Author(chat=FakeChat({"config": {"pattern": r"(a+)+b"}})).draft("regex", "odd ZX thing")
    assert [p["field"] for p in e.value.problems] == ["config.pattern"]


def test_model_failure_is_a_400_code_not_a_crash() -> None:
    with pytest.raises(GuardianFactoryError) as e:
        Author(chat=FakeChat(error=TimeoutError("slow"))).draft("regex", "odd ZX thing")
    assert e.value.code == "model_failed"


def test_over_broad_flag_is_an_integer_and_does_not_refuse() -> None:
    chat = FakeChat({"config": {"pattern": r"\d+"}})
    out = Author(chat=chat).draft("regex", "match numbers please")
    assert out["over_broad"] is True and isinstance(out["match_pct"], int)
    assert out["match_pct"] > 5
    assert any(n.startswith("over_broad") for n in out["notes"])
    assert out["config"]["pattern"] == r"\d+"  # kept: flagged, not refused


def test_over_broad_counts_the_benign_sample() -> None:
    sample = benign_sample()
    assert len(sample) == 120 and all(not re.search(r"\d{9}", t) for t in sample)
    assert over_broad_pct("regex", {"pattern": r"\d{9,14}"}) == 0
    assert over_broad_pct("regex", {"pattern": "a"}, ["a", "b", "c", "d"]) == 25
    assert over_broad_pct("keyword_list", {"words": ["đơn hàng"]}) > 0
    assert over_broad_pct("policy", {}) is None


def test_input_limits() -> None:
    a = Author()
    for bad in (None, "", "   ", "x" * 1001):
        with pytest.raises(GuardianFactoryError) as e:
            a.draft("regex", bad)
        assert e.value.code == "bad_sentence"
    with pytest.raises(GuardianFactoryError) as e:
        a.draft("magic", "text")
    assert e.value.code == "bad_type"
