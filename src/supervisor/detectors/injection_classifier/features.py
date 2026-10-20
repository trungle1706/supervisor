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
import json
import re
import unicodedata
import zlib
from collections.abc import Iterable, Mapping
from typing import Any

from supervisor.detectors.injection_classifier import concepts as C
from supervisor.gateway import tier0b

FEATURE_VERSION = "feat-2"
BUCKETS = 1 << 16  # character n-gram and word buckets
MASK = BUCKETS - 1
CONCEPT_SCALE = 0.25  # value of a concept feature (n-gram features have 1/sqrt(n))
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


def clip_unit(text: str, limit: int = MAX_UNIT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    return text[:head] + " \n " + text[-(limit - head) :]


def prepare(text: str) -> list[str]:
    """Variants of ``text`` to score. Deterministic; the first is the main one."""
    text = clip_unit(flatten_json(text))
    marks: list[str] = []
    if "<!--" in text:
        marks.append(MARK_COMMENT)
    text = _HTML_COMMENT.sub(" ", text)
    base = unicodedata.normalize("NFKC", text)
    if any(_is_invisible(c) for c in base):
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
    # decoding triggers: ROT13 and reversed text, only when the lexicon says so
    if _lexicon_hits(main) == 0 and len(main) >= 12:
        for alt in (codecs.encode(main, "rot13"), main[::-1]):
            if _lexicon_hits(alt) >= 2:
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


def features(window: str) -> list[int]:
    """Sorted unique feature ids of one window of one variant: hashed n-grams and words below
    BUCKETS, concept features (concepts.py) from BUCKETS up."""
    t = _DIGITS.sub("#", window)
    ids: set[int] = set()
    padded = f" {t} "
    n = len(padded)
    crc = zlib.crc32
    for k, tag in ((3, b"3"), (4, b"4"), (5, b"5")):
        for i in range(n - k + 1):
            ids.add(crc(tag + padded[i : i + k].encode("utf-8")) & MASK)
    words = _ALNUM.findall(t)
    prev = ""
    for w in words:
        ids.add(crc(b"w" + w.encode("utf-8")) & MASK)
        if prev:
            ids.add(crc(b"b" + prev.encode("utf-8") + b" " + w.encode("utf-8")) & MASK)
        prev = w
    ids.update(BUCKETS + i for i in C.concept_features(t))
    return sorted(ids)


def unit_feature_sets(text: str) -> list[list[int]]:
    """Feature lists of every window of every variant of ``text`` (training uses the variant
    structure: ``prepare`` then ``windows`` then ``features``)."""
    out: list[list[int]] = []
    for v in prepare(text):
        for w in windows(v):
            out.append(features(w))
    return out


def variant_feature_sets(text: str) -> list[list[list[int]]]:
    """Per variant, the feature lists of its windows."""
    return [[features(w) for w in windows(v)] for v in prepare(text)]


def usable(text: str) -> bool:
    return len(text.strip()) >= MIN_TEXT_CHARS


def join_leaves(leaves: Iterable[str]) -> str:
    """The text of a payload part: its string leaves in order, one per line."""
    return "\n".join(x for x in leaves if x)
