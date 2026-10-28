"""The pattern library of the plain-words author (WP-G1): common Vietnamese bank patterns.

Each entry is deterministic and passes ``regex_problems`` (the existing custom-rule checks): a
test proves it. The author looks for a trigger word in the person's sentence; no model is asked.
Synthetic examples only.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class LibraryPattern:
    id: str
    label_en: str
    triggers: tuple[str, ...]  # lower case, accents removed
    pattern: str
    mask: str
    example: str  # a synthetic text the pattern matches


LIBRARY: tuple[LibraryPattern, ...] = (
    LibraryPattern(
        id="card_number",
        label_en="Payment card number (16 digits in a row)",
        triggers=("card number", "so the", "the tin dung", "credit card", "debit card", "pan"),
        pattern=r"(?<!\d)\d{16}(?!\d)",
        mask="<CARD>",
        example="the 9704123456789012 het han 12/29",
    ),
    LibraryPattern(
        id="cccd",
        label_en="Citizen identity card number CCCD (12 digits starting with 0)",
        triggers=("cccd", "can cuoc", "citizen id", "national id", "id card", "identity card"),
        pattern=r"(?<!\d)0\d{11}(?!\d)",
        mask="<CCCD>",
        example="CCCD 079123456789",
    ),
    LibraryPattern(
        id="phone_vn",
        label_en="Vietnamese mobile phone number (+84 or 0, then 9 digits)",
        triggers=("phone", "mobile", "dien thoai", "sdt", "so di dong", "hotline"),
        pattern=r"(?<!\d)(?:\+84|0)[35789]\d{8}(?!\d)",
        mask="<PHONE>",
        example="goi 0912345678 de xac nhan",
    ),
    LibraryPattern(
        id="amount_vnd",
        label_en="Amount in VND written with thousand separators and a unit",
        triggers=("amount", "so tien", "vnd", "dong", "money", "payment value", "gia tri"),
        pattern=r"\d{1,3}(?:[.,]\d\d\d)+(?:\s(?:VND|VNĐ|đồng)|đ)",
        mask="<AMOUNT>",
        example="chuyen 1.500.000 đồng cho nguoi nhan",
    ),
    LibraryPattern(
        id="account_number",
        label_en="Bank account number (9 to 14 digits)",
        triggers=(
            "account number",
            "account no",
            "bank account",
            "so tai khoan",
            "stk",
            "tai khoan",
            "account",
        ),
        pattern=r"(?<!\d)\d{9,14}(?!\d)",
        mask="<ACCOUNT>",
        example="chuyen den tai khoan 190312345678",
    ),
)

_QUOTED = re.compile(r"[\"'“‘«]([^\"'”’»]{1,80})[\"'”’»]")
_AFTER_WORDS = re.compile(
    r"(?:words?|terms?|phrases?|keywords?|tu khoa|cac tu|tu)\s*[:\-]\s*(.+)$", re.IGNORECASE
)


def fold(text: str) -> str:
    """Lower case, accents removed (đ -> d): the form triggers are compared in."""
    t = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in t if not unicodedata.combining(c))


def find_pattern(sentence: str) -> tuple[LibraryPattern | None, list[LibraryPattern]]:
    """The library entry the sentence asks for, and the other entries that also matched.
    The entry with the earliest trigger in the sentence wins; ties go to the longer trigger."""
    f = fold(sentence)
    hits: list[tuple[int, int, LibraryPattern]] = []
    for entry in LIBRARY:
        best: tuple[int, int] | None = None
        for trig in entry.triggers:
            m = re.search(r"(?<![a-z0-9])" + re.escape(trig) + r"(?![a-z0-9])", f)
            if m and (best is None or (m.start(), -len(trig)) < best):
                best = (m.start(), -len(trig))
        if best is not None:
            hits.append((best[0], best[1], entry))
    if not hits:
        return None, []
    hits.sort(key=lambda h: (h[0], h[1]))
    return hits[0][2], [h[2] for h in hits[1:]]


def find_words(sentence: str) -> list[str]:
    """Named words in a sentence: quoted words, else the comma list after "words:"."""
    quoted = [m.group(1).strip() for m in _QUOTED.finditer(sentence)]
    words = quoted
    if not words:
        m = _AFTER_WORDS.search(sentence.strip().rstrip("."))
        if m:
            words = [w.strip(" \t\"'.") for w in re.split(r"[,;]", m.group(1))]
    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w and w.casefold() not in seen:
            seen.add(w.casefold())
            out.append(w)
    return out
