"""WP4 masking tests: recall/precision on the labelled fixture plus behaviour checks."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.masking.presidio import PresidioMasker
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.core.errors import ConfigError
from supervisor.core.ports import Masker

FIXTURE = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "pii_labelled.jsonl"
ID_TYPES = ("CCCD", "CMND", "PHONE", "EMAIL", "TAX_CODE", "BANK_ACCOUNT", "CARD_NUMBER")


@pytest.fixture(scope="module")
def masker() -> VnRegexMasker:
    return VnRegexMasker(b"test-key", "t1")


def _rows() -> list[dict[str, Any]]:
    return [json.loads(x) for x in FIXTURE.read_text(encoding="utf-8").splitlines() if x]


def _covered(gold: dict[str, Any], text: str, spans: list[Any]) -> bool:
    need = {i for i in range(gold["start"], gold["end"]) if not text[i].isspace()}
    got: set[int] = set()
    for sp in spans:
        got.update(range(max(sp.start, gold["start"]), min(sp.end, gold["end"])))
    return bool(got) and need <= got


def test_recall_precision(masker: VnRegexMasker) -> None:
    hit: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    p_hit: dict[str, int] = defaultdict(int)
    p_tot: dict[str, int] = defaultdict(int)
    leaked = 0
    gold_n = 0
    for row in _rows():
        text = row["text"]
        spans = masker.find(text)
        masked = masker.mask(text)
        for g in row["spans"]:
            total[g["type"]] += 1
            gold_n += 1
            if _covered(g, text, spans):
                hit[g["type"]] += 1
            if g["text"] in masked:
                leaked += 1
        for sp in spans:
            p_tot[sp.type] += 1
            if any(sp.start < g["end"] and g["start"] < sp.end for g in row["spans"]):
                p_hit[sp.type] += 1
    print()
    print("type          recall   precision")
    for t in sorted(total):
        r = hit[t] / total[t]
        p = p_hit[t] / p_tot[t] if p_tot[t] else 0.0
        print(f"{t:<13} {r:6.3f}   {p:6.3f}   (n={total[t]})")
    recall = sum(hit.values()) / gold_n
    precision = sum(p_hit.values()) / max(1, sum(p_tot.values()))
    print(f"OVERALL       {recall:6.3f}   {precision:6.3f}")
    assert recall >= 0.95
    for t in ID_TYPES:
        assert hit[t] / total[t] >= 0.9, t
    assert 1 - leaked / gold_n >= 0.95
    assert precision >= 0.9


def test_pseudonym_deterministic_across_formats(masker: VnRegexMasker) -> None:
    a = masker.pseudonym("PHONE", "0901 234 567")
    assert a == masker.pseudonym("PHONE", "0901234567")
    assert a == masker.pseudonym("PHONE", "+84 901 234 567")
    assert a == masker.pseudonym("PHONE", "0901.234.567")
    assert len(a) == 6
    assert masker.pseudonym("EMAIL", "A@Example.com") == masker.pseudonym("EMAIL", "a@example.com")
    assert masker.mask("SĐT 0901 234 567") == masker.mask("SĐT 0901 234 567")
    assert f"<PHONE:{a}>" in masker.mask("SĐT +84 901 234 567")


def test_key_rotation() -> None:
    m1 = VnRegexMasker(b"k1", "k1")
    m2 = VnRegexMasker(b"k2", "k2")
    assert m1.pseudonym("CCCD", "001305443571") != m2.pseudonym("CCCD", "001305443571")
    assert m1.mask_version != m2.mask_version
    assert m1.mask_version == "vn_regex-1:k1"


@pytest.mark.parametrize(
    "text",
    [
        "Phí 3.910.000 VND đã hoàn.",
        "Order 2026-10-14 for 3.910.000 VND has been shipped; hotline 1800 0000.",
        "Mã giao dịch FT26287001234.",
        "Gọi hotline 1900 5588 68 để được hỗ trợ.",
        "Lãi suất 5,2%/năm, ngày 14/10/2026.",
    ],
)
def test_hard_negatives_not_masked(masker: VnRegexMasker, text: str) -> None:
    assert masker.find(text) == []
    assert masker.mask(text) == text


def test_luhn(masker: VnRegexMasker) -> None:
    good = "4111111111111111"
    bad = "4111111111111112"
    assert any(s.type == "CARD_NUMBER" for s in masker.find(f"Thẻ {good} bị khóa"))
    assert all(s.type != "CARD_NUMBER" for s in masker.find(f"Thẻ {bad} bị khóa"))


def test_masker_protocol(masker: VnRegexMasker) -> None:
    m: Masker = masker
    assert callable(m.mask)
    assert "<CCCD:" in m.mask("Số CCCD của tôi là 001305443571.")


def test_presidio_stub_fails_closed_without_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "presidio_analyzer", None)  # import -> ImportError
    with pytest.raises(ConfigError, match="presidio-analyzer"):
        PresidioMasker()


def test_make_masker_default_is_vn_regex_with_dev_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.adapters.factory import make_masker
    from supervisor.config import load_settings

    m = make_masker(load_settings())
    assert isinstance(m, VnRegexMasker) and m.mask_version == "vn_regex-1:dev"
    monkeypatch.setenv("MASK_HMAC_KEY", "bank-key-2026")
    monkeypatch.setenv("MASK_KEY_ID", "k2026q4")
    m2 = make_masker(load_settings())
    assert isinstance(m2, VnRegexMasker) and m2.mask_version == "vn_regex-1:k2026q4"
    text = "Số CCCD của tôi là 001305443571."
    assert m.mask(text) != m2.mask(text)  # key rotation changes tokens
    assert make_masker(load_settings(masker_kind="none")) is None
