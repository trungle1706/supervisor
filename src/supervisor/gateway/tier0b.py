"""Tier 0b (ADR D02): asynchronous injection / PII pre-filter. Never blocks.

``Classifier`` is the port; ``RegexClassifier`` is the default. Findings become
``alert`` verdicts after the call; the gate decision is already made.
Findings carry only a kind and a count (no matched text: PII never enters the chain).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

MAX_SCAN_CHARS = 20_000


@dataclass(frozen=True)
class Finding:
    kind: str  # injection | pii_cccd | pii_phone | pii_email | pii_account
    count: int


class Classifier(Protocol):
    name: str

    def classify(self, tool_name: str, args: Mapping[str, Any]) -> list[Finding]: ...


# Injection patterns run over the diacritics-stripped, case-folded candidates (see
# ``candidates``), so one pattern covers "bỏ qua", "bo qua" and decoded telex "bor qua".
_INJECTION = [
    # verb and rule noun close together, in either language or mixed (code-switching
    # reorders words: "ignore all instructions previous")
    r"\b(?:ignore|disregard|bo qua)\b[^.;!?\n]{0,30}?\b(?:instructions?|rules?|prompts?|"
    r"restrictions|huong dan|quy tac|chi dan|gioi han)\b",
    r"you are now (?:in )?(?:developer|admin|dan) mode",
    r"system prompt",
    r"override (?:the )?(?:policy|limit|rules)",
    # urgent transfer to an account; "chuyen ngay hom nay" is a time expression, not urgency
    r"chuyen (?:ngay|gap)(?! (?:hom nay|trong ngay|ngay mai)).{0,40}"
    r"(?:sang|vao|toi|den) (?:tai khoan|tk|account)",
    r"<\s*/?\s*(?:system|assistant)\s*>",
]
_PII = {
    "pii_cccd": r"(?<!\d)0\d{11}(?!\d)",
    "pii_phone": r"(?<!\d)(?:\+?84|0)(?:3|5|7|8|9)\d{8}(?!\d)",
    "pii_email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "pii_account": r"(?<!\d)\d{13,19}(?!\d)",
}

# ------------------------------------------------------------------------ normalisation
# Format (Cf) and invisible characters: zero-width, bidi controls, soft hyphen, BOM, tags,
# variation selectors, fillers. Listed explicitly so import stays fast (checked in tests
# against unicodedata for the BMP).
_INVISIBLE_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x0600, 0x0605),
    (0x061C, 0x061C),
    (0x06DD, 0x06DD),
    (0x070F, 0x070F),
    (0x0890, 0x0891),
    (0x08E2, 0x08E2),
    (0x115F, 0x1160),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF9, 0xFFFB),
    (0x110BD, 0x110BD),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0001, 0xE007F),
    (0xE0100, 0xE01EF),
)
_DROP = {cp: None for lo, hi in _INVISIBLE_RANGES for cp in range(lo, hi + 1)}

# Look-alikes of Latin letters (own small table after Unicode TR39 confusables; lower case,
# applied after case folding). Not the full confusables.txt.
_CONFUSABLES = {
    # Cyrillic
    "а": "a",
    "в": "b",
    "е": "e",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "х": "x",
    "і": "i",
    "ї": "i",
    "ј": "j",
    "ѕ": "s",
    "ԁ": "d",
    "ԛ": "q",
    "ԝ": "w",
    "һ": "h",
    "ӏ": "l",
    "ь": "b",
    "ѵ": "v",
    "ү": "y",
    # Greek
    "α": "a",
    "β": "b",
    "γ": "y",
    "ε": "e",
    "ι": "i",
    "κ": "k",
    "ν": "v",
    "ο": "o",
    "ρ": "p",
    "τ": "t",
    "υ": "u",
    "χ": "x",
    "ω": "w",
    "η": "n",
    "μ": "u",
    # Latin variants and symbols that survive NFKC
    "ı": "i",
    "ɩ": "i",
    "ɑ": "a",
    "ɡ": "g",
    "ʏ": "y",
    "ꜱ": "s",
    "ᴀ": "a",
    "ᴄ": "c",
    "ᴇ": "e",
    "ᴏ": "o",
    "ᴘ": "p",
    "ᴛ": "t",
    "ᴜ": "u",
    "ᴠ": "v",
    "ᴡ": "w",
    "ᴢ": "z",
    "ǀ": "l",
    "ⅼ": "l",
    "ⅰ": "i",
    "ⅹ": "x",
    "ⅽ": "c",
    "ⅾ": "d",
    "ⅿ": "m",
    "ό": "o",
}
_CONFUSABLES = {k: v for k, v in _CONFUSABLES.items() if len(k) == 1 and k != v}
_FOLD = str.maketrans(_CONFUSABLES)
_WS = re.compile(r"\s+")
_COMBINING = re.compile(r"[\u0300-\u036f]")
_WORD = re.compile(r"[^\W\d_]+")

_TELEX_VOWEL_MARKS = (("aa", "â"), ("aw", "ă"), ("ee", "ê"), ("oo", "ô"), ("ow", "ơ"), ("uw", "ư"))
_TELEX_TONES = {
    "s": "\u0301",  # acute
    "f": "\u0300",  # grave
    "r": "\u0309",  # hook above
    "x": "\u0303",  # tilde
    "j": "\u0323",  # dot below
}
_MARKED = "âăêôơư"


def normalise(text: str) -> str:
    """NFKC, drop Cf / zero-width characters, case fold, fold Latin look-alikes, NFC,
    collapse whitespace. Pure and deterministic."""
    if not text.isascii():
        text = unicodedata.normalize("NFKC", text).translate(_DROP).casefold()
        text = unicodedata.normalize("NFC", text.translate(_FOLD))
    else:
        text = text.lower()
    return _WS.sub(" ", text).strip()


def strip_diacritics(text: str) -> str:
    """'bỏ qua' -> 'bo qua', 'đ' -> 'd'."""
    if text.isascii():
        return text
    text = unicodedata.normalize("NFD", text)
    return _COMBINING.sub("", text).replace("đ", "d")


def _telex_word(word: str) -> str:
    tone = ""
    if len(word) > 2 and word[-1] in _TELEX_TONES and any(c in "aeiouy" for c in word[:-1]):
        tone = _TELEX_TONES[word[-1]]
        word = word[:-1]
    word = word.replace("dd", "đ")
    for key, mark in _TELEX_VOWEL_MARKS:
        word = word.replace(key, mark)
    if tone:
        vowels = [i for i, c in enumerate(word) if c in "aeiouyâăêôơư"]
        if vowels:
            marked = [i for i in vowels if word[i] in _MARKED]
            idx = marked[-1] if marked else vowels[-1]
            word = word[: idx + 1] + tone + word[idx + 1 :]
    return unicodedata.normalize("NFC", word)


def telex_decode(text: str) -> str:
    """Decode raw Telex keystrokes ('bor qua', 'huwowngs daanx') to Vietnamese.

    Rules: aa aw ee oo ow uw dd for the vowel and đ marks; a trailing s f r x j is the tone
    (acute, grave, hook, tilde, dot below). English words get mangled, so the result is only a
    second candidate for matching, never a replacement."""
    return _WORD.sub(lambda m: _telex_word(m.group(0)), text)


def candidates(text: str) -> list[str]:
    """Strings the injection patterns run on: normalised, diacritics-stripped, and the
    stripped form of the Telex decoding. Duplicates are dropped."""
    base = normalise(text)
    plain = strip_diacritics(base)
    out = [plain]
    if base != plain:
        out.append(base)
    decoded = strip_diacritics(telex_decode(plain))
    if decoded not in out:
        out.append(decoded)
    return out


def _strings(value: Any, depth: int = 0) -> Iterator[str]:
    if depth > 6:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _strings(v, depth + 1)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _strings(v, depth + 1)


class RegexClassifier:
    """Default Tier 0b classifier: Vietnamese + English injection phrases, VN PII shapes."""

    name = "regex_v1"

    def __init__(self) -> None:
        self._inj = [re.compile(p) for p in _INJECTION]
        self._pii = {k: re.compile(p) for k, p in _PII.items()}

    def classify(self, tool_name: str, args: Mapping[str, Any]) -> list[Finding]:
        text = "\n".join(_strings(args))[:MAX_SCAN_CHARS]
        out: list[Finding] = []
        # injection: best count over the candidate strings; PII: the raw text (unchanged)
        inj = max(
            (sum(len(p.findall(c)) for p in self._inj) for c in candidates(text)),
            default=0,
        )
        if inj:
            out.append(Finding("injection", inj))
        for kind, pattern in self._pii.items():
            n = len(pattern.findall(text))
            if n:
                out.append(Finding(kind, n))
        return out
