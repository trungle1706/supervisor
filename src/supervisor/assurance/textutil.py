"""Small pure-Python text helpers for Vietnamese and English (no models, no downloads).

Integer results only (basis points). Used by several runners; keep it dependency-free.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence

_WORD = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[^\W\d_]+", re.UNICODE)
_SENT = re.compile(r"(?<=[.!?…])\s+|\n+")

# Short function words (vi + en) ignored by overlap metrics.
STOPWORDS: frozenset[str] = frozenset(
    "và của là có cho các những một được với không này đó thì để khi trong tại theo từ "
    "về đã sẽ đang bạn tôi quý khách vui lòng ạ nhé thể "
    "the a an of to in on for is are was were be and or with by at from that this it as "
    "your you i we please".split()
)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def strip_diacritics(text: str) -> str:
    """'Đà Nẵng' -> 'Da Nang' (also maps đ/Đ)."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return unicodedata.normalize(
        "NFC", "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    )


def normalise(text: str, *, fold_diacritics: bool = False) -> str:
    text = nfc(text).lower()
    if fold_diacritics:
        text = strip_diacritics(text)
    return " ".join(text.split())


def tokens(text: str, *, fold_diacritics: bool = False, drop_stop: bool = False) -> list[str]:
    out = _WORD.findall(normalise(text, fold_diacritics=fold_diacritics))
    if drop_stop:
        out = [t for t in out if t not in STOPWORDS]
    return out


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(nfc(text)) if s and s.strip()]


def numbers(text: str) -> set[str]:
    """Numbers in the text, separators removed ('1.500.000' -> '1500000')."""
    return {re.sub(r"[.,]", "", m) for m in re.findall(r"\d+(?:[.,]\d+)*", text)}


def bp(num: int, den: int) -> int | None:
    """Integer basis points num/den (None when den == 0)."""
    return None if den == 0 else num * 10000 // den


def token_f1_bp(pred: str, gold: str, *, fold_diacritics: bool = True) -> int:
    """SQuAD-style token F1 in bp (stopwords dropped)."""
    p = Counter(tokens(pred, fold_diacritics=fold_diacritics, drop_stop=True))
    g = Counter(tokens(gold, fold_diacritics=fold_diacritics, drop_stop=True))
    common = sum((p & g).values())
    if not p or not g or common == 0:
        return 0
    precision_x = common * 10000 // sum(p.values())
    recall_x = common * 10000 // sum(g.values())
    return 2 * precision_x * recall_x // (precision_x + recall_x)


def overlap_bp(a: str, b: str, *, fold_diacritics: bool = True) -> int:
    """Share of content tokens of ``a`` that appear in ``b`` (bp)."""
    ta = set(tokens(a, fold_diacritics=fold_diacritics, drop_stop=True))
    tb = set(tokens(b, fold_diacritics=fold_diacritics, drop_stop=True))
    return bp(len(ta & tb), len(ta)) or 0


def jaccard_bp(a: str, b: str, *, fold_diacritics: bool = True) -> int:
    ta = set(tokens(a, fold_diacritics=fold_diacritics, drop_stop=True))
    tb = set(tokens(b, fold_diacritics=fold_diacritics, drop_stop=True))
    return bp(len(ta & tb), len(ta | tb)) or 0


def mean_int(values: Iterable[int]) -> int | None:
    vals = list(values)
    return None if not vals else sum(vals) // len(vals)


def sha256_lines(lines: Sequence[str]) -> str:
    h = hashlib.sha256()
    for line in lines:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def stable_rank(salt: str, key: str) -> int:
    """Deterministic pseudo-random int from (salt, key) (sampling without RNG state)."""
    return int.from_bytes(hashlib.sha256(f"{salt}:{key}".encode()).digest()[:8], "big")
