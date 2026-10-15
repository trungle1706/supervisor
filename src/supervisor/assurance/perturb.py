"""Deterministic text perturbations for the robustness packs (WP17).

CheckList-style invariance tests (Ribeiro et al. 2020) and TextFlint / AdvGLUE-style
character perturbations, written for Vietnamese banking text. Every function is pure and
seeded: the same ``(text, seed)`` always gives the same output, with no global RNG state.
All mapping tables are our own small tables (no vendored Unicode data).

Kinds (``KINDS``): typo, no_diacritics, telex, code_switch, confusable, zero_width,
fullwidth_digits, nfd.

* ``typo``         adjacent-key substitution / drop / duplicate at ``rate_bp`` per letter
* ``no_diacritics`` 'chuyển khoản' -> 'chuyen khoan' (people type without tones)
* ``telex``        'chuyển tiền' -> 'chuyeenr tieenf' (raw Telex keystrokes, not converted)
* ``code_switch``  'chuyển khoản' <-> 'transfer' (mixed vi/en banking terms)
* ``confusable``   Latin letters -> Cyrillic / Greek look-alikes (TR39 style)
* ``zero_width``   U+200B / U+200C / U+200D / U+FEFF inside words
* ``fullwidth_digits`` '0123' -> U+FF10.. full-width digits
* ``nfd``          canonical decomposition (base letter + combining marks)

Kinds that must change a text of letters always change it (at least one edit is forced).
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.assurance import textutil

KINDS: tuple[str, ...] = (
    "typo",
    "no_diacritics",
    "telex",
    "code_switch",
    "confusable",
    "zero_width",
    "fullwidth_digits",
    "nfd",
)

ZERO_WIDTH: tuple[str, ...] = ("​", "‌", "‍", "﻿")

# Latin -> look-alike (own table; the common attacker picks, not the full TR39 list).
CONFUSABLES: dict[str, str] = {
    "a": "а",  # Cyrillic a
    "e": "е",  # Cyrillic ie
    "o": "о",  # Cyrillic o
    "p": "р",  # Cyrillic er
    "c": "с",  # Cyrillic es
    "x": "х",  # Cyrillic ha
    "y": "у",  # Cyrillic u
    "i": "і",  # Cyrillic Ukrainian i
    "A": "А",
    "E": "Е",
    "O": "Ο",  # Greek capital omicron
    "P": "Р",
    "C": "С",
    "X": "Х",
    "Y": "Υ",  # Greek capital upsilon
    "I": "Ι",  # Greek capital iota
}
CONFUSABLES_REVERSE: dict[str, str] = {v: k for k, v in CONFUSABLES.items()}

# QWERTY neighbours (ASCII letters) for adjacent-key typos.
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_NEIGHBOURS: dict[str, str] = {}
for _r, _row in enumerate(_ROWS):
    for _i, _ch in enumerate(_row):
        _n = ""
        if _i > 0:
            _n += _row[_i - 1]
        if _i < len(_row) - 1:
            _n += _row[_i + 1]
        _NEIGHBOURS[_ch] = _n

# (vi, en) banking terms, longest vi phrase first when matching.
CODE_SWITCH_TERMS: tuple[tuple[str, str], ...] = (
    ("chuyển khoản", "transfer"),
    ("tài khoản", "account"),
    ("hạn mức", "limit"),
    ("lãi suất", "interest rate"),
    ("số dư", "balance"),
    ("mật khẩu", "password"),
    ("ngân hàng", "bank"),
    ("sao kê", "statement"),
    ("khoản vay", "loan"),
    ("tiết kiệm", "savings"),
    ("giao dịch", "transaction"),
    ("chi nhánh", "branch"),
    ("tranh chấp", "dispute"),
    ("hoàn tiền", "refund"),
    ("người nhận", "payee"),
    ("khóa", "lock"),
    ("khoá", "lock"),
    ("phí", "fee"),
    ("thẻ", "card"),
    ("hướng dẫn", "instructions"),
    ("quy tắc", "rules"),
    ("bỏ qua", "ignore"),
    ("tất cả", "all"),
    ("trước đó", "previous"),
)

_TONES = {
    "́": "s",  # acute
    "̀": "f",  # grave
    "̉": "r",  # hook above
    "̃": "x",  # tilde
    "̣": "j",  # dot below
}
_CIRCUMFLEX = "̂"
_BREVE = "̆"
_HORN = "̛"
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _rng(seed: int, kind: str, text: str) -> random.Random:
    return random.Random(textutil.stable_rank(f"{seed}:{kind}", text))  # noqa: S311


def _pick_positions(rng: random.Random, candidates: Sequence[int], rate_bp: int) -> list[int]:
    """Each candidate is chosen with probability rate_bp/10000; at least one is forced."""
    if not candidates:
        return []
    chosen = [p for p in candidates if rng.randrange(10000) < rate_bp]
    if not chosen:
        chosen = [candidates[rng.randrange(len(candidates))]]
    return chosen


# ----------------------------------------------------------------------------- kinds
def typos(text: str, *, seed: int = 0, rate_bp: int = 500) -> str:
    """Adjacent-key substitution, drop or duplicate of letters at ``rate_bp`` per letter."""
    text = textutil.nfc(text)
    rng = _rng(seed, "typo", text)
    letters = [i for i, c in enumerate(text) if c.isalpha()]
    chosen = set(_pick_positions(rng, letters, rate_bp))
    out: list[str] = []
    for i, ch in enumerate(text):
        if i not in chosen:
            out.append(ch)
            continue
        op = rng.randrange(3)
        low = ch.lower()
        if op == 0 and low in _NEIGHBOURS:
            sub = _NEIGHBOURS[low][rng.randrange(len(_NEIGHBOURS[low]))]
            out.append(sub.upper() if ch.isupper() else sub)
        elif op == 1 and len(letters) > 1:
            continue  # drop
        else:
            out.append(ch + ch)  # duplicate
    res = "".join(out)
    return res if res != text else text + text[-1:]  # forced change on degenerate input


def no_diacritics(text: str) -> str:
    return textutil.strip_diacritics(text)


def _telex_word(word: str) -> str:
    out: list[str] = []
    tone = ""
    for ch in word.replace("đ", "dd").replace("Đ", "Dd"):
        for part in unicodedata.normalize("NFD", ch):
            if part in _TONES:
                tone = _TONES[part]
            elif part == _CIRCUMFLEX:
                out.append(out[-1].lower())
            elif part in (_BREVE, _HORN):
                out.append("w")
            elif unicodedata.category(part) == "Mn":
                continue
            else:
                out.append(part)
    return "".join(out) + tone


def telex(text: str) -> str:
    """Raw Telex keystrokes: 'chuyển tiền' -> 'chuyeenr tieenf'."""
    return _WORD.sub(lambda m: _telex_word(m.group(0)), textutil.nfc(text))


def _term_pattern(terms: Sequence[str]) -> re.Pattern[str]:
    alts = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
    return re.compile(rf"(?<!\w)({alts})(?!\w)", re.IGNORECASE)


def code_switch(
    text: str,
    *,
    direction: str = "auto",
    terms: Sequence[tuple[str, str]] = CODE_SWITCH_TERMS,
) -> str:
    """Swap banking terms between Vietnamese and English.

    ``direction``: vi2en, en2vi or auto (vi2en when a Vietnamese term occurs, else en2vi).
    """
    text = textutil.nfc(text)
    vi2en = {vi: en for vi, en in terms}
    en2vi: dict[str, str] = {}
    for vi, en in terms:
        en2vi.setdefault(en, vi)
    if direction == "auto":
        direction = "vi2en" if _term_pattern(list(vi2en)).search(text) else "en2vi"
    table = vi2en if direction == "vi2en" else en2vi
    pat = _term_pattern(list(table))

    def repl(m: re.Match[str]) -> str:
        src = m.group(1)
        dst = table[src.lower()]
        return dst[:1].upper() + dst[1:] if src[:1].isupper() else dst

    return pat.sub(repl, text)


def confusables(text: str, *, seed: int = 0, rate_bp: int = 3000) -> str:
    """Replace Latin letters by Cyrillic / Greek look-alikes at ``rate_bp`` per mappable letter."""
    text = textutil.nfc(text)
    rng = _rng(seed, "confusable", text)
    cands = [i for i, c in enumerate(text) if c in CONFUSABLES]
    chosen = set(_pick_positions(rng, cands, rate_bp))
    return "".join(CONFUSABLES[c] if i in chosen else c for i, c in enumerate(text))


def zero_width(text: str, *, seed: int = 0, rate_bp: int = 1500) -> str:
    """Insert zero-width characters between letters of a word at ``rate_bp`` per gap."""
    text = textutil.nfc(text)
    rng = _rng(seed, "zero_width", text)
    gaps = [i for i in range(1, len(text)) if text[i - 1].isalpha() and text[i].isalpha()]
    if not gaps:
        gaps = [len(text)]
    chosen = set(_pick_positions(rng, gaps, rate_bp))
    out: list[str] = []
    for i, ch in enumerate(text):
        if i in chosen:
            out.append(ZERO_WIDTH[rng.randrange(len(ZERO_WIDTH))])
        out.append(ch)
    if len(text) in chosen:
        out.append(ZERO_WIDTH[0])
    return "".join(out)


def fullwidth_digits(text: str) -> str:
    return "".join(chr(0xFF10 + int(c)) if "0" <= c <= "9" else c for c in text)


def nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


def apply(kind: str, text: str, *, seed: int = 0) -> str:
    """Apply one perturbation kind with default strength."""
    if kind == "typo":
        return typos(text, seed=seed)
    if kind == "no_diacritics":
        return no_diacritics(text)
    if kind == "telex":
        return telex(text)
    if kind == "code_switch":
        return code_switch(text)
    if kind == "confusable":
        return confusables(text, seed=seed)
    if kind == "zero_width":
        return zero_width(text, seed=seed)
    if kind == "fullwidth_digits":
        return fullwidth_digits(text)
    if kind == "nfd":
        return nfd(text)
    raise ValueError(f"unknown perturbation kind: {kind}")


# ------------------------------------------------------------------- agent_event dicts
_PREFIX = re.compile(r"^(\[[a-z_ ]{1,20}\]\s*)(.*)$", re.DOTALL)


def _free_text(value: str) -> bool:
    return len(value.split()) >= 3


def _perturb_json_strings(kind: str, node: Any, seed: int) -> Any:
    if isinstance(node, str):
        return apply(kind, node, seed=seed) if _free_text(node) else node
    if isinstance(node, list):
        return [_perturb_json_strings(kind, v, seed) for v in node]
    if isinstance(node, dict):
        return {k: _perturb_json_strings(kind, v, seed) for k, v in node.items()}
    return node


def perturb_events(
    kind: str, events: Sequence[Mapping[str, Any]], *, seed: int = 0
) -> list[dict[str, Any]]:
    """Perturb the free text of ``agent_event``-shaped dicts (messages, args, results).

    Ids, tool names, amounts and short identifiers are left alone: only strings of three
    or more words (customer text, memos, tool-result prose) change."""
    out: list[dict[str, Any]] = []
    for ev in events:
        e = dict(ev)
        args = e.get("args_masked")
        if isinstance(args, str) and args:
            if e.get("event_type") == "message":
                m = _PREFIX.match(args)
                head, body = (m.group(1), m.group(2)) if m else ("", args)
                e["args_masked"] = head + apply(kind, body, seed=seed)
            else:
                try:
                    parsed = json.loads(args)
                except ValueError:
                    e["args_masked"] = apply(kind, args, seed=seed) if _free_text(args) else args
                else:
                    e["args_masked"] = json.dumps(
                        _perturb_json_strings(kind, parsed, seed),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
        res = e.get("result_masked")
        if isinstance(res, str) and res and _free_text(res):
            e["result_masked"] = apply(kind, res, seed=seed)
        out.append(e)
    return out


def events_text(events: Sequence[Mapping[str, Any]]) -> str:
    """All free text of the events joined (used to tell whether a perturbation changed any)."""
    return "\n".join(f"{e.get('args_masked') or ''}|{e.get('result_masked') or ''}" for e in events)
