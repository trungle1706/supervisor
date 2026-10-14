from __future__ import annotations

import json
import re

from supervisor.data import wordlists as W
from supervisor.data.synthetic import (
    FIXTURES_DIR,
    PII_TYPES,
    SyntheticGenerator,
    build_dataset,
    cccd_valid,
    luhn_valid,
    tax_code_valid,
)


def test_same_seed_same_output() -> None:
    assert build_dataset(7, 30) == build_dataset(7, 30)
    assert build_dataset(7, 30) != build_dataset(8, 30)


def test_customer_identifiers_are_valid() -> None:
    gen = SyntheticGenerator(1)
    customers = gen.customers(300)
    for c in customers:
        assert cccd_valid(c.cccd), c.cccd
        assert c.cccd[:3] == c.province_code and c.province_code in W.PROVINCES
        assert c.cccd[4:6] == f"{c.birth_year % 100:02d}"
        female = int(c.cccd[3]) % 2 == 1
        assert female == (c.gender == "female")
        if c.cmnd is not None:
            assert len(c.cmnd) == 9 and c.cmnd.isdigit()
        digits = re.sub(r"\D", "", c.phone)
        assert (digits.startswith("84") and len(digits) == 11) or (
            digits.startswith("0") and len(digits) == 10
        ), c.phone
        assert tax_code_valid(c.tax_code)
        assert re.fullmatch(r"[a-z0-9.]+@example\.(com|org|net)", c.email), c.email
        assert c.province in c.address
    assert len({c.customer_id for c in customers}) == 300


def test_accounts_and_cards() -> None:
    gen = SyntheticGenerator(2)
    accounts = gen.accounts(gen.customers(100))
    assert accounts
    for a in accounts:
        assert type(a.balance_minor) is int and a.balance_minor >= 0
        assert a.account_number.isdigit() and 10 <= len(a.account_number) <= 14
        if a.card_number:
            assert len(a.card_number) == 16 and luhn_valid(a.card_number)


def test_luhn_and_tax_code_negative_cases() -> None:
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")
    assert not tax_code_valid("0100109107")  # wrong check digit
    assert not cccd_valid("999123456789")  # unknown province
    assert not cccd_valid("00112345678")  # 11 digits


def test_tickets_have_planted_injections_in_both_languages() -> None:
    gen = SyntheticGenerator(3)
    tickets = gen.tickets(gen.customers(200), 400)
    injected = [t for t in tickets if t.injected]
    assert 0 < len(injected) < len(tickets)
    assert {t.language for t in injected} == {"vi", "en"}
    assert all(t.injection_kind for t in injected)


def test_loan_applications_have_fairness_attributes() -> None:
    gen = SyntheticGenerator(4)
    apps = gen.loan_applications(gen.customers(300), 300)
    assert {a.gender for a in apps} == {"male", "female"}
    assert len({a.age_band for a in apps}) >= 4
    assert len({a.province_code for a in apps}) >= 10
    assert {a.language for a in apps} == {"vi", "en"}
    for a in apps:
        assert type(a.amount_minor) is int and type(a.credit_score) is int
        assert 0 <= a.credit_score <= 1000
    assert any(not a.documents_complete for a in apps)
    assert any(a.documents_complete for a in apps)


def test_pii_fixture_schema_and_offsets() -> None:
    lines = (FIXTURES_DIR / "pii_labelled.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 300
    seen_types: set[str] = set()
    ids = set()
    for line in lines:
        item = json.loads(line)
        assert set(item) == {"id", "language", "text", "spans"}
        assert item["language"] in ("vi", "en")
        ids.add(item["id"])
        prev_end = 0
        for span in item["spans"]:
            assert set(span) == {"start", "end", "type", "text"}
            assert span["type"] in PII_TYPES
            assert 0 <= prev_end <= span["start"] < span["end"] <= len(item["text"])
            assert item["text"][span["start"] : span["end"]] == span["text"]
            prev_end = span["end"]
            seen_types.add(span["type"])
            if span["type"] == "CARD_NUMBER":
                assert luhn_valid(span["text"])
            if span["type"] == "CCCD":
                assert cccd_valid(span["text"])
    assert len(ids) == len(lines)
    assert seen_types == set(PII_TYPES)
    assert any(not json.loads(x)["spans"] for x in lines), "need hard negatives"


def test_pii_fixture_is_current() -> None:
    """The committed fixture equals the generator output (regenerate with --write-fixtures)."""
    expected = [
        json.dumps(r, ensure_ascii=False, sort_keys=True)
        for r in SyntheticGenerator().pii_labelled(400)
    ]
    actual = (FIXTURES_DIR / "pii_labelled.jsonl").read_text(encoding="utf-8").splitlines()
    assert actual == expected
