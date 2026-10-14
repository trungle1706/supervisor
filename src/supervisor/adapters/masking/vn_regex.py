"""Regex masker for Vietnamese PII. Pure, deterministic, stdlib only.

Each detected span becomes ``<TYPE:hex>`` where hex is a keyed HMAC-SHA256 pseudonym, so the
same person or number gets the same token across formats, and a key change changes the tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass

from supervisor.data import wordlists as W

__all__ = ["PiiSpan", "VnRegexMasker"]


@dataclass(frozen=True)
class PiiSpan:
    start: int
    end: int
    type: str
    text: str


def _fold(text: str) -> str:
    out = unicodedata.normalize("NFD", text)
    out = "".join(c for c in out if unicodedata.category(c) != "Mn")
    return out.replace("đ", "d").replace("Đ", "D")


def luhn_ok(digits: str) -> bool:
    if not 13 <= len(digits) <= 19 or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_MST_WEIGHTS = (31, 29, 23, 19, 17, 13, 7, 5, 3)


def _tax_ok(code: str) -> bool:
    if len(code) != 10 or not code.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(code[:9], _MST_WEIGHTS, strict=True))
    return 10 - (total % 11) == int(code[9])


def _alt(words: set[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=lambda w: (-len(w), w)))


def _with_folded(words: tuple[str, ...]) -> set[str]:
    return set(words) | {_fold(w) for w in words}


_SUR = _alt(_with_folded(W.SURNAMES))
_MID = _alt(_with_folded(W.MIDDLE_MALE + W.MIDDLE_FEMALE))
_GIVEN = _alt(_with_folded(W.GIVEN_MALE + W.GIVEN_FEMALE))
_ANY_NAME = _alt(
    _with_folded(W.SURNAMES + W.MIDDLE_MALE + W.MIDDLE_FEMALE + W.GIVEN_MALE + W.GIVEN_FEMALE)
)
_PROVINCES = _alt(set(W.PROVINCES.values()) | {_fold(p) for p in W.PROVINCES.values()})

_RE_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w-])")
_RE_CARD = re.compile(r"(?<![\w.+-])(?:\d[ -]?){12,18}\d(?![\w])")
_RE_TAX_BRANCH = re.compile(r"(?<![\w.+-])\d{10}-\d{3}(?![\w])")
_RE_PHONE = re.compile(
    r"(?<![\w+.,-])(?:(?:\+84|0084)[ .-]?[2-9]\d(?:[ .-]?\d){7}|0[2-9]\d(?:[ .-]?\d){7})(?!\d)"
)
_RE_RUN = re.compile(r"(?<![\w.+-])\d{6,19}(?![\w])")
_RE_PERSON_PLAIN = re.compile(rf"(?<!\w)(?:{_SUR})(?: (?:{_MID})){{1,2}} (?:{_GIVEN})(?!\w)")
_HONORIFICS = (
    r"anh|chị|ông|bà|cô|chú|mr\.?|ms\.?|mrs\.?|miss|khách hàng|customer|người nhận|của|"
    r"applicant|tôi là|tên|họ tên|holder|this is|name|payee|beneficiary"
)
_RE_PERSON_LABELLED = re.compile(
    rf"(?<!\w)(?i:{_HONORIFICS})[:,]? +((?:{_ANY_NAME})(?: (?:{_ANY_NAME})){{1,3}})(?!\w)"
)
_RE_ADDRESS = re.compile(
    r"(?<!\w)(?:Số|No\.?|So) ?\d{1,4}[A-Za-z]?(?:/\d+)* [^,\n;()]{2,40}, "
    r"(?:Phường|Xã|Thị trấn|Phuong|Xa) [^,\n;()]{1,30}, "
    r"(?:Quận|Huyện|Thành phố|Thị xã|Thị trấn|Quan|Huyen|Thanh pho|Thi xa) [^,\n;()]{1,30}"
    rf"(?:, (?:{_PROVINCES})(?!\w))?"
)

_LABELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CMND", re.compile(r"cmnd|chứng minh|old id card|old id|\bcmt\b", re.I)),
    ("CCCD", re.compile(r"cccd|căn cước|citizen id|\bid\b", re.I)),
    ("TAX_CODE", re.compile(r"mã số thuế|\bmst\b|tax code|tax id|\bthuế", re.I)),
    ("BANK_ACCOUNT", re.compile(r"tài khoản|account|\bstk\b|số tk|\bacct\b|a/c", re.I)),
)

_PRIORITY = {
    "label": 100,
    "email": 90,
    "card_strong": 102,
    "tax_branch": 101,
    "phone": 70,
    "person_label": 65,
    "id_valid": 60,
    "address": 75,
    "cmnd": 50,
    "person_plain": 45,
    "bank": 40,
    "card_weak": 30,
}

_Cand = tuple[int, int, int, str]  # priority, start, end, type


def _nearest_label(text: str, start: int) -> str | None:
    window = text[max(0, start - 32) : start]
    # A digit between the label and the number means the label belongs to another number.
    last_digit = max((i for i, c in enumerate(window) if c.isdigit()), default=-1)
    window = window[last_digit + 1 :]
    best: tuple[int, str] | None = None
    for kind, pat in _LABELS:
        for m in pat.finditer(window):
            if best is None or m.end() > best[0]:
                best = (m.end(), kind)
    return best[1] if best else None


def _classify_run(text: str, start: int, run: str) -> tuple[str, str] | None:
    n = len(run)
    label = _nearest_label(text, start)
    if label == "BANK_ACCOUNT":
        return "label", "BANK_ACCOUNT"
    if label == "TAX_CODE" and n == 10:
        return "label", "TAX_CODE"
    if label == "CMND" and n in (9, 12):
        return "label", "CMND"
    if label == "CCCD" and n == 12:
        return "label", "CCCD"
    if n == 12 and run[:3] in W.PROVINCES and run[3] in "0123":
        return "id_valid", "CCCD"
    if n == 10 and _tax_ok(run):
        return "id_valid", "TAX_CODE"
    if n == 9:
        return "cmnd", "CMND"
    if 10 <= n <= 15:
        return "bank", "BANK_ACCOUNT"
    return None


class VnRegexMasker:
    """Masker for Vietnamese banking text. Implements the ``Masker`` protocol."""

    def __init__(self, key: bytes, key_id: str = "dev", *, token_len: int = 6) -> None:
        if not key:
            raise ValueError("masking key must not be empty")
        self._key = key
        self.key_id = key_id
        self.token_len = token_len
        self.mask_version = f"vn_regex-1:{key_id}"

    # -- pseudonyms -------------------------------------------------------------
    @staticmethod
    def normalise(type_: str, value: str) -> str:
        if type_ == "EMAIL":
            return value.strip().lower()
        if type_ in ("PERSON", "ADDRESS"):
            return " ".join(_fold(value).lower().split())
        digits = re.sub(r"\D", "", value)
        if type_ == "PHONE":
            if digits.startswith("0084"):
                digits = "0" + digits[4:]
            elif digits.startswith("84") and len(digits) == 11:
                digits = "0" + digits[2:]
        return digits

    def pseudonym(self, type_: str, value: str) -> str:
        msg = f"{type_}:{self.normalise(type_, value)}".encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()[: self.token_len]

    # -- detection --------------------------------------------------------------
    @staticmethod
    def _candidates(text: str) -> list[_Cand]:
        c: list[_Cand] = []

        def add(start: int, end: int, prio: str, type_: str) -> None:
            c.append((_PRIORITY[prio], start, end, type_))

        for m in _RE_EMAIL.finditer(text):
            add(m.start(), m.end(), "email", "EMAIL")
        for m in _RE_TAX_BRANCH.finditer(text):
            add(m.start(), m.end(), "tax_branch", "TAX_CODE")
        for m in _RE_PHONE.finditer(text):
            add(m.start(), m.end(), "phone", "PHONE")
        for m in _RE_CARD.finditer(text):
            digits = re.sub(r"\D", "", m.group())
            if luhn_ok(digits):
                strong = len(digits) >= 15 and digits[0] in "2345679"
                add(m.start(), m.end(), "card_strong" if strong else "card_weak", "CARD_NUMBER")
        for m in _RE_RUN.finditer(text):
            kind = _classify_run(text, m.start(), m.group())
            if kind:
                add(m.start(), m.end(), kind[0], kind[1])
        for m in _RE_PERSON_PLAIN.finditer(text):
            add(m.start(), m.end(), "person_plain", "PERSON")
        for m in _RE_PERSON_LABELLED.finditer(text):
            add(m.start(1), m.end(1), "person_label", "PERSON")
        for m in _RE_ADDRESS.finditer(text):
            add(m.start(), m.end(), "address", "ADDRESS")
        return c

    def find(self, text: str) -> list[PiiSpan]:
        """Non-overlapping spans sorted by position. Higher priority, then longer, wins."""
        chosen: list[tuple[int, int, str]] = []
        for _prio, s, e, t in sorted(self._candidates(text), key=lambda x: (-x[0], x[1] - x[2])):
            if all(e <= cs or s >= ce for cs, ce, _ in chosen):
                chosen.append((s, e, t))
        chosen.sort()
        return [PiiSpan(s, e, t, text[s:e]) for s, e, t in chosen]

    def mask(self, text: str) -> str:
        out: list[str] = []
        pos = 0
        for sp in self.find(text):
            out.append(text[pos : sp.start])
            out.append(f"<{sp.type}:{self.pseudonym(sp.type, sp.text)}>")
            pos = sp.end
        out.append(text[pos:])
        return "".join(out)
