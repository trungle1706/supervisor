"""Regex masker for Vietnamese PII. Pure, deterministic, stdlib only.

Each detected span becomes ``<TYPE:hex>`` where hex is a keyed HMAC-SHA256 pseudonym, so the
same person or number gets the same token across formats, and a key change changes the tokens.

Masked output is NORMALISED (``vn_regex-2``). Before matching, the text is stripped of every
Unicode format character (category Cf: zero-width space, soft hyphen, word joiner, BOM, bidi
marks) and put through NFKC (full-width digits become ASCII, no-break space becomes a space);
Unicode dashes become ``-``. ``mask()`` returns the normalised text with PII spans replaced,
and ``find()`` returns offsets into that normalised text (``canonical()`` gives it). This way an
invisible character can never sit inside or next to a masked value and leak part of it. Pure
ASCII input is returned unchanged by the normalisation step.
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


_DASHES = str.maketrans(
    dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d", "-")
)


def canonical(text: str) -> str:
    """Strip Unicode Cf characters, apply NFKC, map Unicode dashes to ``-``.

    Cf is removed first so that characters on both sides of an invisible one compose and match
    as if it were not there. Pure ASCII has no Cf and is returned as is (fast path).
    """
    if text.isascii():
        return text
    out = "".join(c for c in text if unicodedata.category(c) != "Cf")
    out = unicodedata.normalize("NFKC", out)
    out = "".join(c for c in out if unicodedata.category(c) != "Cf")
    return out.translate(_DASHES)


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


# Name words beyond the generator lists, so real 4-word names (Trần Thị Bích Ngọc) still match.
_EXTRA_NAME_WORDS: tuple[str, ...] = (
    "Bích", "Hồng", "Tuyết", "Diệu", "Thúy", "Xuân", "Hải", "Tiến", "Thái", "Ngọc", "Lan",
    "Yến", "Nhi", "Đình", "Hoàng", "Trọng", "Xuân", "Thùy", "Như", "Tú",
)  # fmt: skip
_SUR = _alt(_with_folded(W.SURNAMES))
_MID = _alt(_with_folded(W.MIDDLE_MALE + W.MIDDLE_FEMALE + _EXTRA_NAME_WORDS))
_LAST = _alt(
    _with_folded(
        W.GIVEN_MALE + W.GIVEN_FEMALE + W.MIDDLE_MALE + W.MIDDLE_FEMALE + _EXTRA_NAME_WORDS
    )
)
_ANY_NAME = _alt(
    _with_folded(
        W.SURNAMES
        + W.MIDDLE_MALE
        + W.MIDDLE_FEMALE
        + W.GIVEN_MALE
        + W.GIVEN_FEMALE
        + _EXTRA_NAME_WORDS
    )
)
_PROVINCES = _alt(set(W.PROVINCES.values()) | {_fold(p) for p in W.PROVINCES.values()})
_PROV_TAIL = rf"(?:TP\.? ?)?(?:{_PROVINCES})|TP\.? ?(?:HCM|HN|HCMC)|TPHCM"

_RE_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w-])")
_RE_CARD = re.compile(r"(?<![\w.+-])(?:\d[ -]?){12,18}\d(?![\w])")
_RE_TAX_BRANCH = re.compile(r"(?<![\w.+-])\d{10}-\d{3}(?![\w])")
_RE_PHONE = re.compile(
    r"(?<![\w+.,-])(?:"
    r"\(?(?:\+84|0084)\)?[ .-]?[2-9](?:[ .-]?\d){8}"
    r"|0[2-9](?:[ .-]?\d){8}"
    r"|84[35789]\d{8}"
    r")(?!\d)"
)
_RE_RUN = re.compile(r"(?<![\w.+-])\d{6,19}(?![\w])")
_RE_GROUPED = re.compile(r"(?<![\w.+-])\d{3,6}(?:[ -]\d{2,6}){1,5}(?![\w])")
# Digit groups written with single space / dot / dash separators. First group 2-6 digits, then
# 1-5 more. Not preceded by another digit group ("12 345 678 901 234" must not match at "345").
_RE_SEP_RUN = re.compile(r"(?<![\w.+-])(?<!\d[ .-])\d{2,6}(?:[ .-]\d{1,6}){1,5}(?!\w)")
_RE_CURRENCY_AFTER = re.compile(r"\s{0,2}(?:vnd|vnđ|vn đ|đồng|dong|đ|₫|usd|đ/)(?!\w)", re.I)
_RE_TOKEN = re.compile(r"<[A-Z_]{2,20}:[0-9a-f]{4,64}>")
# Cue words that make a grouped digit run an account number ("chuyen den 1903 4567 8901 23").
# Matched on folded (no diacritics, lower case) text, whole words, in the 40 chars before the run.
_RE_ACCOUNT_CUE = re.compile(
    r"\b(?:chuyen|den|sang|vao|stk|tk|tai khoan|account|acct|transfer|to)\b"
)
_RE_STRONG_CUE = re.compile(r"\b(?:stk|tk|tai khoan|account|acct)\b")
_RE_THOUSANDS = re.compile(r"\d{1,3}(?:([. ])\d{3})+")
_RE_PERSON_PLAIN = re.compile(
    rf"(?<!\w)(?:{_SUR})(?: (?:{_MID})){{1,2}} (?:{_LAST})(?!\w)", re.IGNORECASE
)
_HONORIFICS = (
    r"anh|chị|ông|bà|cô|chú|mr\.?|ms\.?|mrs\.?|miss|khách hàng|customer|người nhận|của|"
    r"applicant|tôi là|tên|họ tên|holder|this is|name|payee|beneficiary|"
    r"ong|khach hang|nguoi nhan|cua|toi la|ten|ho ten"
)
_RE_PERSON_LABELLED = re.compile(
    rf"(?<!\w)(?:{_HONORIFICS})[:,]? +((?:{_ANY_NAME})(?: (?:{_ANY_NAME})){{1,3}})(?!\w)",
    re.IGNORECASE,
)
_DISTRICT = r"(?:Quận|Huyện|Thành phố|Thị xã|Thị trấn|Quan|Huyen|Thanh pho|Thi xa) [^,\n;()]{1,30}"
_WARD = r"(?:Phường|Xã|Thị trấn|Phuong|Xa) [^,\n;()]{1,30}"
_ADDR_TAIL = rf"(?:{_WARD}, )?{_DISTRICT}(?:, (?:{_PROV_TAIL})(?!\w))?"
_RE_ADDRESS = re.compile(
    r"(?<![\w/])(?i:Số|No\.?|So) ?\d{1,4}[A-Za-z]?(?:/\d+)* [^,\n;()]{2,40}, " + _ADDR_TAIL
)
_RE_ADDRESS_BARE = re.compile(
    r"(?<![\w/])\d{1,4}[A-Za-z]?(?:/\d+)* (?:[Đđ]ường )?[A-ZĐ][^\W\d_]*"
    r"(?: [A-ZĐ][^\W\d_]*){0,4}, " + _ADDR_TAIL
)

_LABELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CMND", re.compile(r"cmnd|chứng minh|old id card|old id|\bcmt\b", re.I)),
    ("CCCD", re.compile(r"cccd|căn cước|citizen id|\bid\b", re.I)),
    ("TAX_CODE", re.compile(r"mã số thuế|\bmst\b|tax code|tax id|\bthuế", re.I)),
    ("BANK_ACCOUNT", re.compile(r"tài khoản|account|\bstk\b|số tk|\bacct\b|a/c", re.I)),
    ("CARD", re.compile(r"thẻ|card", re.I)),
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


def _has_account_cue(text: str, start: int, pat: re.Pattern[str] = _RE_ACCOUNT_CUE) -> bool:
    window = text[max(0, start - 40) : start]
    # A digit between the cue and the run means the cue belongs to another number
    # ("chuyen 1.500.000 den ..." keeps "den" because it is after the amount).
    last_digit = max((i for i, c in enumerate(window) if c.isdigit()), default=-1)
    return bool(pat.search(_fold(window[last_digit + 1 :]).lower()))


def _classify_sep_run(text: str, m: re.Match[str]) -> tuple[str, str] | None:
    """Type for a separator-written digit run, or None.

    Rules (a wrongly masked amount is a defect; so is an unmasked CCCD):
    * Followed by a currency word or sign (VND, d, dong, USD): amount, never masked.
    * Exactly 12 digits in 2-4 groups of 3+ digits: CCCD (3-3-3-3, 4-4-4, 6-6, mixed), or
      BANK_ACCOUNT after STK / TK / tai khoan / account. This wins over the amount rule, because
      001.203.004.567 is a CCCD.
    * Otherwise a thousands format (1-3 digits, then groups of exactly 3, joined by one kind of
      separator, dot or space) is an amount: 1.500.000, 12.345.678.900.
    * 13-19 digits: BANK_ACCOUNT regardless of label.
    * 9-19 digits: BANK_ACCOUNT when an account/transfer cue word is within 40 chars before it.
    * Everything else (dates, times, short refs, < 9 digits): not masked.
    """
    run = m.group()
    if _RE_CURRENCY_AFTER.match(text, m.end()):
        return None
    groups = re.split(r"[ .-]", run)
    n = sum(len(g) for g in groups)
    if n == 12 and 2 <= len(groups) <= 4 and all(len(g) >= 3 for g in groups):
        if _has_account_cue(text, m.start(), _RE_STRONG_CUE):
            return "bank", "BANK_ACCOUNT"  # "STK 9704 2201 0101": a 12-digit account
        return "id_valid", "CCCD"
    if _RE_THOUSANDS.fullmatch(run):
        return None
    if 13 <= n <= 19:
        return "bank", "BANK_ACCOUNT"
    if 9 <= n <= 19 and _has_account_cue(text, m.start()):
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
        self.mask_version = f"vn_regex-2:{key_id}"

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

    def keyed_hash(self, text: str) -> str:
        """Full HMAC-SHA256 hex digest of ``text`` under the masker key."""
        return hmac.new(self._key, text.encode("utf-8"), hashlib.sha256).hexdigest()

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
                if _nearest_label(text, m.start()) == "BANK_ACCOUNT":
                    strong = False
                add(m.start(), m.end(), "card_strong" if strong else "card_weak", "CARD_NUMBER")
        for m in _RE_RUN.finditer(text):
            kind = _classify_run(text, m.start(), m.group())
            if kind:
                add(m.start(), m.end(), kind[0], kind[1])
        for m in _RE_GROUPED.finditer(text):
            if _nearest_label(text, m.start()) == "BANK_ACCOUNT":
                add(m.start(), m.end(), "label", "BANK_ACCOUNT")
        for m in _RE_SEP_RUN.finditer(text):
            kind = _classify_sep_run(text, m)
            if kind:
                add(m.start(), m.end(), kind[0], kind[1])
        for m in _RE_PERSON_PLAIN.finditer(text):
            add(m.start(), m.end(), "person_plain", "PERSON")
        for m in _RE_PERSON_LABELLED.finditer(text):
            add(m.start(1), m.end(1), "person_label", "PERSON")
        for rx in (_RE_ADDRESS, _RE_ADDRESS_BARE):
            for m in rx.finditer(text):
                add(m.start(), m.end(), "address", "ADDRESS")
        return c

    @staticmethod
    def canonical(text: str) -> str:
        """The normalised text that ``find`` offsets refer to (see module docstring)."""
        return canonical(text)

    def find(self, text: str) -> list[PiiSpan]:
        """Non-overlapping spans sorted by position. Higher priority, then longer, wins.

        Offsets are into ``canonical(text)``, which equals ``text`` for plain ASCII.
        """
        text = canonical(text)
        tokens = [(t.start(), t.end()) for t in _RE_TOKEN.finditer(text)]
        chosen: list[tuple[int, int, str]] = []
        for _prio, s, e, t in sorted(self._candidates(text), key=lambda x: (-x[0], x[1] - x[2])):
            if any(s < te and ts < e for ts, te in tokens):
                continue  # already a mask token: keeps mask() idempotent
            if all(e <= cs or s >= ce for cs, ce, _ in chosen):
                chosen.append((s, e, t))
        chosen.sort()
        return [PiiSpan(s, e, t, text[s:e]) for s, e, t in chosen]

    def mask(self, text: str) -> str:
        """Mask ``canonical(text)``: the result is normalised, see the module docstring."""
        text = canonical(text)
        out: list[str] = []
        pos = 0
        for sp in self.find(text):
            out.append(text[pos : sp.start])
            out.append(f"<{sp.type}:{self.pseudonym(sp.type, sp.text)}>")
            pos = sp.end
        out.append(text[pos:])
        return "".join(out)
