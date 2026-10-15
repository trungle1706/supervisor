"""vn_regex-2: separator-written ids, grouped accounts, invisible characters, amounts untouched."""

from __future__ import annotations

import re
import unicodedata

import pytest

from supervisor.adapters.masking.vn_regex import VnRegexMasker, canonical

ZW = "​"
SHY = "­"
WJ = "⁠"
BOM = "﻿"


@pytest.fixture(scope="module")
def m() -> VnRegexMasker:
    return VnRegexMasker(b"test-key", "t1")


def _clean(out: str) -> bool:
    return not any(unicodedata.category(c) == "Cf" for c in out)


def _no_value_digits(out: str, value: str) -> bool:
    """No 3-digit slice of the value survives outside mask tokens, and no Cf char survives."""
    digits = re.sub(r"\D", "", value)
    rest = re.sub(r"<[A-Z_]+:[0-9a-f]+>", "", out)
    return _clean(out) and not any(digits[i : i + 3] in rest for i in range(len(digits) - 2))


POSITIVE = [
    ("CCCD 001-203-004-567", "CCCD", "001-203-004-567"),
    ("CCCD 001 203 004 567", "CCCD", "001 203 004 567"),
    ("CCCD 079-203-004-567", "CCCD", "079-203-004-567"),
    ("CCCD 001  203  004  567", "CCCD", "001203004567"),
    ("CCCD 001\t203\t004\t567", "CCCD", "001203004567"),
    ("CCCD 001/203/004/567", "CCCD", "001203004567"),
    ("CCCD 001_203_004_567", "CCCD", "001203004567"),
    ("CCCD 123 456 789 012", "CCCD", "123456789012"),
    ("CCCD 123.456.789.012", "CCCD", "123456789012"),
    ("can cuoc 123 456 789 012", "CCCD", "123456789012"),
    ("CMND 024 678 123", "CMND", "024678123"),
    ("STK 1903-4567 8901.23", "BANK_ACCOUNT", "19034567890123"),
    ("STK 1903/4567/8901/23", "BANK_ACCOUNT", "19034567890123"),
    ("CCCD 0012\u034f03004567", "CCCD", "001203004567"),
    ("CCCD 0012\u316403004567", "CCCD", "001203004567"),
    ("CCCD 0012\u280003004567", "CCCD", "001203004567"),
    ("CCCD 0012\ufe0f03004567", "CCCD", "001203004567"),
    ("CCCD 0012\U000e000103004567", "CCCD", "001203004567"),
    ("CCCD 0012\u180e03004567", "CCCD", "001203004567"),
    ("CCCD 0012\u17b403004567", "CCCD", "001203004567"),
    ("CCCD 0012\U000e010003004567", "CCCD", "001203004567"),
    ("CCCD 001.203.004.567", "CCCD", "001.203.004.567"),
    ("so 0012 0300 4567 la cua toi", "CCCD", "0012 0300 4567"),
    ("so 001203 004567 la cua toi", "CCCD", "001203 004567"),
    ("chuyen den 1903 4567 8901 23", "BANK_ACCOUNT", "1903 4567 8901 23"),
    ("Chuyển đến 1903-4567-8901-23 nhé", "BANK_ACCOUNT", "1903-4567-8901-23"),
    ("transfer to 1903.4567.8901.23", "BANK_ACCOUNT", "1903.4567.8901.23"),
    ("vào TK 9704 2201 0101", "BANK_ACCOUNT", "9704 2201 0101"),
    ("gui sang tai khoan 9704 2201 0101 0", "BANK_ACCOUNT", "9704 2201 0101 0"),
    ("ref 1903 4567 8901 2345", "BANK_ACCOUNT", "1903 4567 8901 2345"),  # 16 digits, no label
    ("ref 12345 67890 12345 678", "BANK_ACCOUNT", "12345 67890 12345 678"),  # 18 digits
    ("SDT 0912 345 678", "PHONE", "0912 345 678"),
    ("SDT 0912.345.678", "PHONE", "0912.345.678"),
    ("SDT 0912-345-678", "PHONE", "0912-345-678"),
    ("goi +84 912 345 678 nhe", "PHONE", "+84 912 345 678"),
    (f"CCCD 0012{ZW}03004567", "CCCD", "001203004567"),
    (f"CCCD 001203{BOM}004567", "CCCD", "001203004567"),
    (f"SDT 0912{SHY}345678", "PHONE", "0912345678"),
    (f"SDT 09{SHY}12 345{ZW} 678", "PHONE", "0912345678"),
    (f"STK 1903{WJ}4567890123", "BANK_ACCOUNT", "19034567890123"),
    (f"STK{WJ} 1903 4567{ZW} 8901 23", "BANK_ACCOUNT", "19034567890123"),
    (f"email an{ZW}.nguyen@example.vn", "EMAIL", "an.nguyen@example.vn"),
    (f"email an.nguyen@exam{SHY}ple.vn", "EMAIL", "an.nguyen@example.vn"),
    (f"CCCD {ZW}001-203-004-567", "CCCD", "001203004567"),
]

NEGATIVE = [
    "12.05.2026 10.30.00",
    "01.01.2026 31.12.2026",
    "15-10-2026 10-30-00",
    "2026 10 15 10 30 00",
    "20.000.000 20.000.000",
    "100.000 200.000 300.000",
    "5.000.000-10.000.000",
    "chuyen den 2026 10 15 1030 00",
    "ma GD 2026 10 15 123456",
    "123456789012 VND",
    "15/10/2026",
    "CCCD 15/10/2026",
    "ngay 15/10/2026 10/30/00",
    "001/203/004/567",
    "001_203_004_567",
    "12.000.000.000.000",
    "phi 100.000.000.000",
    "khoan vay 250 000 000 000",
    "IP 192.168.100.200",
    "so du tai khoan 1.500.000",
    "chuyen den 100.000.000.000",
    "stk 100.000.000.000",
    "1.500.000",
    "1.500.000 VND",
    "15.000.000đ",
    "250,000,000 dong",
    "12.345.678.900",
    "chuyen 1.500.000 den",
    "chuyen 1.500.000 den anh Nam",
    "chuyen den tai khoan so tien 2.000.000",
    "chuyen den 5.000.000.000 dong",
    "tai khoan so du 12.345.678",
    "ngay 15/10/2026",
    "2026-10-15",
    "15.10.2026",
    "15-10-2026",
    "15 10 2026",
    "luc 10:30",
    "ma GD 123456",
    "ma GD 123456 ngay 15.10.2026 luc 10:30",
    "so luong 12 345 hang",
]


@pytest.mark.parametrize(("text", "kind", "value"), POSITIVE)
def test_positive_masked(m: VnRegexMasker, text: str, kind: str, value: str) -> None:
    out = m.mask(text)
    assert f"<{kind}:" in out, (text, out)
    assert _no_value_digits(out, value), (text, out)
    assert [s.type for s in m.find(text)] == [kind]


@pytest.mark.parametrize("text", NEGATIVE)
def test_negative_unchanged(m: VnRegexMasker, text: str) -> None:
    assert m.mask(text) == text
    assert m.find(text) == []


@pytest.mark.parametrize(("text", "kind", "value"), POSITIVE)
def test_idempotent(m: VnRegexMasker, text: str, kind: str, value: str) -> None:
    once = m.mask(text)
    assert m.mask(once) == once


def test_idempotent_when_token_is_all_digits(m: VnRegexMasker) -> None:
    text = "<CCCD:123456> and <PHONE:001203>"
    assert m.mask(text) == text


def test_same_value_same_token_across_formats(m: VnRegexMasker) -> None:
    toks = set()
    for v in ("001203004567", "001-203-004-567", "001 203 004 567", f"0012{ZW}03004567"):
        hit = re.search(r"<CCCD:[0-9a-f]+>", m.mask(f"CCCD {v}"))
        assert hit
        toks.add(hit.group())
    assert len(toks) == 1


def test_no_partial_group_at_start(m: VnRegexMasker) -> None:
    # "12" must not stay while "345 678 901 234" is masked as a CCCD.
    assert m.mask("ma 12 345 678 901 234") == "ma 12 345 678 901 234"


def test_mask_output_is_normalised(m: VnRegexMasker) -> None:
    assert m.mask(f"a{ZW}b１ x") == "ab1 x"
    assert canonical("plain ascii") == "plain ascii"
    assert m.mask("n‑a") == "n-a"


def test_find_offsets_refer_to_canonical_text(m: VnRegexMasker) -> None:
    text = f"x{ZW}y CCCD 001203004567"
    sp = m.find(text)[0]
    assert m.canonical(text)[sp.start : sp.end] == sp.text == "001203004567"


def test_mask_version(m: VnRegexMasker) -> None:
    assert m.mask_version == "vn_regex-2:t1"


def test_scrub_uses_canonical_offsets() -> None:
    from supervisor.ops.logging_setup import scrub

    assert scrub(f"user{ZW} CCCD 0012{ZW}03004567 ok") == "user CCCD [CCCD] ok"


def test_unseparated_12_digits_unchanged(m: VnRegexMasker) -> None:
    assert m.mask("so 079203004567 ok").startswith("so <CCCD:")
    assert m.mask("CCCD 001203004567").startswith("CCCD <CCCD:")
    assert [x.type for x in m.find("x 190345678901 y")] == ["BANK_ACCOUNT"]


def test_account_tail_may_be_short_but_inner_groups_may_not(m: VnRegexMasker) -> None:
    assert "<BANK_ACCOUNT:" in m.mask("chuyen den 1903 4567 8901 23")
    assert m.mask("chuyen den 1903 45 8901 2345") == "chuyen den 1903 45 8901 2345"


def test_currency_after_unseparated_run_is_an_amount(m: VnRegexMasker) -> None:
    assert m.mask("phi 123456789012 VND") == "phi 123456789012 VND"
    assert m.mask("phi 123456789012 dong") == "phi 123456789012 dong"
    assert "<BANK_ACCOUNT:" in m.mask("phi 123456789012")


def test_label_does_not_mask_a_following_amount_or_date(m: VnRegexMasker) -> None:
    for t in ("tai khoan so du 100.000.000", "tk 5 000 000 000", "stk 2026 10 15"):
        assert m.mask(t) == t, t


def test_canonical_strips_default_ignorables_not_in_cf() -> None:
    for cp in (0x34F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180F, 0x2800, 0x3164, 0xFE00,
               0xFE0F, 0xFFA0, 0xE0100, 0xE01EF):  # fmt: skip
        assert canonical(f"a{chr(cp)}b") == "ab", hex(cp)
