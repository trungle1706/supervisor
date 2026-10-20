"""Text to features for the injection classifier (WP25, ADR D27). Pure Python, no model file here.

The same code runs at training time (``tools/train_classifier.py``) and at run time, so a change
here is a change of the model: bump ``FEATURE_VERSION`` (the loader refuses weights made with
another version).

Pipeline for one text (``prepare``), producing one or more *variants* of it:

1. JSON in a string is flattened (a value that is itself a JSON document is read as one).
2. Unicode normalisation of Tier 0b (NFKC, zero-width and format characters dropped, case fold,
   Latin look-alikes folded) -> then diacritics removed ("no-diacritic form").
3. Leetspeak folding for letters swapped for look-alike digits or symbols *inside a word*
   (``1gn0re``, ``in$tructions``, ``5ystem``).
4. Decoding attempts: a long base64-looking token that decodes to readable text is appended
   as plain words. Two conditional variants, ROT13 and reversed text, are added only when they
   contain two or more words of a small trigger lexicon and the plain text contains none (a decoding
   trigger, not a classification rule).
5. A Telex variant (raw Telex keystrokes decoded to Vietnamese, then diacritics removed). It is a
   second variant, never a replacement: Telex decoding mangles English words.

Features of a window of a variant (``features``): character 3-, 4- and 5-grams over the whole
string (spaces included, digit runs replaced by ``#`` so amounts and ids do not matter), word
unigrams and word bigrams, plus marker words for structure that no n-gram sees (a hidden HTML
comment, invisible characters, a decoded payload). Each feature is hashed with CRC-32 into
``BUCKETS`` buckets. The score of a text is the maximum over variants and windows.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import functools
import json
import re
import unicodedata
import zlib
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from supervisor.detectors.injection_classifier import concepts as C
from supervisor.gateway import tier0b

FEATURE_VERSION = "feat-3"
BUCKETS = 1 << 16  # character n-gram and word buckets
MASK = BUCKETS - 1
CONCEPT_SCALE = 0.12
TOTAL = BUCKETS + C.CBUCKETS  # concept features (concepts.py) live above BUCKETS
WINDOW = 150  # characters per scoring window
STRIDE = 75
MAX_UNIT_CHARS = 12_000  # per scored unit; longer text keeps its head and its tail
MIN_TEXT_CHARS = 6  # shorter strings are not classified

_DIGITS = re.compile(r"\d+")
_WS = re.compile(r"\s+")
_B64_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
_LEET_INNER = re.compile(r"(?<=[a-z])[01345@$7!|](?=[a-z])")
_LEET_START = re.compile(r"(?<![a-z0-9])[1345$@7](?=[a-z]{2})")
_LEET_END = re.compile(r"(?<=[a-z]{2})[3@$5](?![a-z0-9])")
_LEET_MAP = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "@": "a",
        "$": "s",
        "!": "i",
        "|": "l",
    }
)
_HTML_COMMENT = re.compile(r"<!--|-->")
_ALNUM = re.compile(r"[a-z0-9#]+")

# Words (no diacritics) that make a ROT13 or reversed variant worth scoring. Decoding trigger only.
_LEXICON = frozenset(
    "ignore instruction instructions previous system prompt override disregard bypass approve "
    "transfer rules limit password admin reveal forget qua huong dan quy tac bo chuyen "
    "hang muc duyet tai khoan".split()
)

# Common words (English and Vietnamese without diacritics). A text with almost none of them whose
# ROT13 or reversed form has many is probably encoded. Plausibility only, never a verdict.
_COMMON = frozenset(
    (
        "the a an of to in on for is are was were be and or with by at from that this it as your you i "
        "we they not no yes please if then do does did can will would should must all any each every "
        "my our their its his her me us them what when where which who how why have has had but so "
        "than too very just also into out up down over under about after before again more most some "
        "such only own same new old send transfer account customer payment approve instruction "
        "va cua la co cho cac nhung mot duoc voi khong nay do thi de khi trong tai theo tu ve da se "
        "dang ban toi anh chi em quy khach vui long xin hay dung nhe nha ma neu thi cung con cho "
        "nhu rat hon nhat tat ca moi sau truoc tren duoi ngay thang nam gio phut so tien tai khoan "
        "chuyen gui duyet giao dich"
    ).split()
)


def common_share(text: str) -> int:
    """Share of the words of ``text`` that are common words, in basis points (0 for no words)."""
    words = [w for w in _ALNUM.findall(text) if w.isalpha()]
    if len(words) < 3:
        return 0
    return sum(1 for w in words if w in _COMMON) * 10_000 // len(words)


# Marker words appended to a variant (they never occur in normal text).
MARK_COMMENT = "zzcmt"
MARK_INVISIBLE = "zzinv"
MARK_DECODED = "zzdec"
MARK_ROT = "zzrot"
MARK_LEET = "zzleet"


def _is_invisible(c: str) -> bool:
    return ord(c) in tier0b._DROP  # noqa: SLF001 - the Tier 0b table is the shared definition


def flatten_json(text: str) -> str:
    """A string that is a JSON object or array becomes its keys and string values, one per line."""
    s = text.lstrip()
    if len(s) < 2 or s[0] not in "{[" or len(s) > MAX_UNIT_CHARS * 2:
        return text
    try:
        doc = json.loads(s)
    except ValueError:
        return text
    out: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, str):
            out.append(flatten_json(node) if depth < 8 else node)
        elif isinstance(node, Mapping):
            for k, v in node.items():
                out.append(str(k))
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(doc)
    return "\n".join(out) if out else text


def leet_fold(text: str) -> tuple[str, bool]:
    """Fold digits and symbols used as letters inside words. Returns (text, changed)."""
    t = text
    t = _LEET_INNER.sub(lambda m: m.group(0).translate(_LEET_MAP), t)
    t = _LEET_START.sub(lambda m: m.group(0).translate(_LEET_MAP), t)
    t = _LEET_END.sub(lambda m: m.group(0).translate(_LEET_MAP), t)
    return t, t != text


def decode_b64_tokens(text: str, limit: int = 4) -> list[str]:
    """Readable text hidden in base64-looking tokens (at most ``limit`` tokens)."""
    out: list[str] = []
    for m in _B64_TOKEN.finditer(text):
        tok = m.group(0).rstrip("=")
        if len(tok) < 16 or len(tok) % 4 == 1:
            continue
        pad = "=" * (-len(tok) % 4)
        raw = tok.replace("-", "+").replace("_", "/")
        try:
            data = base64.b64decode(raw + pad, validate=True)
            dec = data.decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        printable = sum(c.isprintable() or c in "\n\t" for c in dec)
        letters = sum(c.isalpha() or c.isspace() for c in dec)
        if (
            len(dec) >= 8
            and printable >= 0.97 * len(dec)
            and letters >= 0.6 * len(dec)
            and " " in dec
        ):
            out.append(dec)
            if len(out) >= limit:
                break
    return out


def _lexicon_hits(text: str) -> int:
    return sum(1 for w in _ALNUM.findall(text) if w in _LEXICON)


# Words that make a part of a long text worth scoring (selection only, never a verdict).
_CUES = frozenset(
    _LEXICON
    | set(C._WORDS["OVR"])  # noqa: SLF001 - the concept lexicon is the shared definition
    | set(C._WORDS["RUL"])  # noqa: SLF001
    | set(C._WORDS["SEC"])  # noqa: SLF001
    | set(C._WORDS["AGT"])  # noqa: SLF001
)
SEGMENT = 600  # characters per middle segment of a long text
SEGMENT_STEP = 450  # segments overlap by 150 characters (one window), so no cut hides a clause
_B64_RUN = re.compile(r"[A-Za-z0-9+/]{24,}")  # linear scan; a run with a digit or + / counts
MAX_SCAN_CHARS = 200_000  # a longer text is cut to its head and tail before segments are chosen
_SURROGATES = re.compile("[\ud800-\udfff]")


def drop_surrogates(text: str) -> tuple[str, bool]:
    """Lone surrogates (possible in JSON input, ``"\\ud800"``) cannot be encoded: drop them."""
    if text.isascii():
        return text, False
    out = _SURROGATES.sub("", text)
    return out, out != text


def cue_count(text: str) -> int:
    """Number of cue words in ``text`` after normalisation (used to choose segments)."""
    plain, _ = leet_fold(tier0b.strip_diacritics(tier0b.normalise(text)))
    b64 = any(any(c.isdigit() or c in "+/" for c in m.group(0)) for m in _B64_RUN.finditer(text))
    return sum(1 for w in _ALNUM.findall(plain) if w in _CUES) + (1 if b64 else 0)


def plain_form(text: str) -> str:
    """Normalised, diacritics-free, leet-folded text (the first step of ``prepare``)."""
    plain, _ = leet_fold(tier0b.strip_diacritics(tier0b.normalise(text)))
    return plain


def clip_unit(
    text: str, limit: int = MAX_UNIT_CHARS, rank: Callable[[str], int] | None = None
) -> str:
    """At most about ``limit`` characters of ``text``: its head, its tail and, from the middle, the
    segments with the most cue words (WP25 review: a head-and-tail cut let an instruction hide in
    the middle of a long document). Text up to ``limit`` is returned unchanged. Deterministic."""
    if len(text) <= limit:
        return text
    if len(text) > MAX_SCAN_CHARS:  # bounded work (the gate refuses payloads over 100,000 chars)
        text = text[: MAX_SCAN_CHARS // 2] + " \n " + text[-(MAX_SCAN_CHARS // 2) :]
    head, tail = limit * 5 // 12, limit // 4
    mid_start, mid_end = head, len(text) - tail
    k = max(1, (limit - head - tail) // SEGMENT)
    starts = list(range(mid_start, max(mid_start + 1, mid_end - SEGMENT + 1), SEGMENT_STEP))
    if starts[-1] + SEGMENT < mid_end:
        starts.append(mid_end - SEGMENT)
    score = rank or cue_count  # WP25b: the model's cheap first-stage score when it is given
    ranked = sorted(starts, key=lambda s: (-score(text[s : s + SEGMENT]), s))[:k]
    middle = " \n ".join(text[s : min(s + SEGMENT, mid_end)] for s in sorted(ranked))
    return text[:head] + " \n " + middle + " \n " + text[-tail:]


def prepare(text: str, rank: Callable[[str], int] | None = None) -> list[str]:
    """Variants of ``text`` to score. Deterministic; the first is the main one."""
    text, had_surrogates = drop_surrogates(text)
    text = clip_unit(flatten_json(text), MAX_UNIT_CHARS, rank)
    marks: list[str] = []
    if "<!--" in text:
        marks.append(MARK_COMMENT)
    text = _HTML_COMMENT.sub(" ", text)
    base = unicodedata.normalize("NFKC", text)
    if had_surrogates or any(_is_invisible(c) for c in base):
        marks.append(MARK_INVISIBLE)
    plain = tier0b.strip_diacritics(tier0b.normalise(text))
    plain, leeted = leet_fold(plain)
    if leeted:
        marks.append(MARK_LEET)
    decoded = decode_b64_tokens(text)
    if decoded:
        plain = (
            plain + " " + " ".join(tier0b.strip_diacritics(tier0b.normalise(d)) for d in decoded)
        )
        marks.append(MARK_DECODED)
    main = _WS.sub(" ", plain).strip()
    variants = [(main + " " + " ".join(marks)).strip()]
    # Telex: a second reading, only when it changes the text
    telex = tier0b.strip_diacritics(tier0b.telex_decode(main))
    if telex != main:
        variants.append((telex + " " + " ".join(marks)).strip())
    # decoding: ROT13 and reversed text, when the decoded form reads as normal text and the plain
    # form does not (common-word share), or when the lexicon fires on it (WP25 1.0.0 rule)
    if len(main) >= 12 and _lexicon_hits(main) == 0:
        plain_share = common_share(main)
        for alt in (codecs.encode(main, "rot13"), main[::-1]):
            if _lexicon_hits(alt) >= 2 or (plain_share < 1_500 and common_share(alt) >= 3_500):
                variants.append(f"{alt} {MARK_ROT} " + " ".join(marks))
    return variants


def windows(text: str) -> list[str]:
    """Overlapping windows of at most about WINDOW characters, cut at spaces."""
    if len(text) <= WINDOW + STRIDE // 2:
        return [text]
    out: list[str] = []
    n = len(text)
    start = 0
    while start < n:
        end = min(n, start + WINDOW)
        if end < n:
            sp = text.rfind(" ", start + WINDOW // 2, end)
            if sp > start:
                end = sp
        out.append(text[start:end])
        if end >= n:
            break
        nxt = text.find(" ", start + STRIDE)
        start = nxt + 1 if 0 < nxt < end else end
    return out


_SEEDS = ((3, zlib.crc32(b"3")), (4, zlib.crc32(b"4")), (5, zlib.crc32(b"5")))
_SURFACE_SEED = {
    "args": zlib.crc32(b"s:args"),
    "tool_results": zlib.crc32(b"s:tool_results"),
    "tool_description": zlib.crc32(b"s:tool_description"),
}


@functools.lru_cache(maxsize=4096)
def features(window: str, surface: str = "args") -> tuple[int, ...]:
    """Sorted unique feature ids of one window of one variant on one surface: hashed character
    n-grams (shared by the surfaces), words and stems (shared and tagged with the surface), below
    BUCKETS; concept features (concepts.py, shared and tagged) from BUCKETS up. Cached."""
    t = _DIGITS.sub("#", window)
    ids: set[int] = set()
    padded = f" {t} "
    n = len(padded)
    crc = zlib.crc32
    if padded.isascii():
        # same ids as crc32(tag + gram), computed with the tag as the CRC seed (no concatenation)
        pb = padded.encode("ascii")
        for k, seed in _SEEDS:
            ids.update({crc(pb[i : i + k], seed) & MASK for i in range(n - k + 1)})
    else:
        for k, seed in _SEEDS:
            ids.update(
                {crc(padded[i : i + k].encode("utf-8"), seed) & MASK for i in range(n - k + 1)}
            )
    ss = _SURFACE_SEED.get(surface, _SURFACE_SEED["args"])
    words = _ALNUM.findall(t)
    prev = ""
    for w in words:
        sw = C.stem(w) if w.isalpha() else w
        wb = b"w" + sw.encode("utf-8")
        ids.add(crc(wb) & MASK)
        ids.add(crc(wb, ss) & MASK)
        if prev:
            bb = b"b" + prev.encode("utf-8") + b" " + sw.encode("utf-8")
            ids.add(crc(bb) & MASK)
            ids.add(crc(bb, ss) & MASK)
        prev = sw
    ids.update(BUCKETS + i for i in C.concept_features(t, surface))
    return tuple(sorted(ids))


def unit_feature_sets(text: str, surface: str = "args") -> list[tuple[int, ...]]:
    """Feature lists of every window of every variant of ``text`` (training uses the variant
    structure: ``prepare`` then ``windows`` then ``features``)."""
    out: list[tuple[int, ...]] = []
    for v in prepare(text):
        for w in windows(v):
            out.append(features(w, surface))
    return out


def variant_feature_sets(
    text: str, surface: str = "args", rank: Callable[[str], int] | None = None
) -> list[list[tuple[int, ...]]]:
    """Per variant, the feature lists of its windows."""
    return [[features(w, surface) for w in windows(v)] for v in prepare(text, rank)]


def usable(text: str) -> bool:
    return len(text.strip()) >= MIN_TEXT_CHARS


def join_leaves(leaves: Iterable[str]) -> str:
    """The text of a payload part: its string leaves in order, one per line."""
    return "\n".join(x for x in leaves if x)
