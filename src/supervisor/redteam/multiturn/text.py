"""Text views and cue lexicon shared by the susceptibility model and the session monitor.

Both consumers read a turn through the same folded views, so a cue written in telex, without
diacritics, with symbol substitutions ("$" for s, "0" for o) or inside base64 / hex / percent
encoding is seen once, not four times. The Tier 0b helpers (``supervisor.gateway.tier0b``) do
the Unicode work (NFKC, invisible characters, look-alikes, telex); this module adds leet
folding and the decoders.

The lexicon is deliberately small and written by hand. It stands in for "what a counter-based
session monitor can count" (WP27) and for "what pressure a language model feels" in the mock
agent. It is not a classifier and never blocks anything.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import re
import urllib.parse

from supervisor.gateway.tier0b import candidates, normalise

# "$" for s, "@" for a, digits for letters. Applied only inside a token that also holds a letter,
# so amounts such as "95.000.000" or "100tr" are not turned into words.
_LEET = str.maketrans(
    {"$": "s", "@": "a", "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "!": "i"}
)
_TOKEN = re.compile(r"\S+")
_B64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=])")
_HEX = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){8,}(?![0-9A-Fa-f])")
_PCT = re.compile(r"(?:%[0-9A-Fa-f]{2}){4,}")
# Telex lets the tone key follow the vowel ("bajn" for "ban" + dot below) as well as end the word
# ("banj"). The Tier 0b decoder only reads the second form, so the first is moved to the end.
_MID_TONE = re.compile(r"\b([a-z]*[aeiouy][aeiouwdy]*)([sfrxj])(ng|nh|ch|n|c|m|p|t)\b")
MAX_VIEW_CHARS = 8000


def leet_fold(text: str) -> str:
    def fix(m: re.Match[str]) -> str:
        tok = m.group(0)
        if any(c.isalpha() for c in tok):
            return tok.translate(_LEET)
        return tok

    return _TOKEN.sub(fix, text)


def telex_tone_to_end(text: str) -> str:
    """'bajn' -> 'banj', 'nhuw bajn' -> 'nhuw banj' (ASCII lower case words only)."""
    return _MID_TONE.sub(lambda m: m.group(1) + m.group(3) + m.group(2), text)


def _printable(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(text) < 4 or sum(c.isprintable() or c.isspace() for c in text) < len(text) * 0.9:
        return None
    return text


def decoded_fragments(text: str) -> list[str]:
    """Plain text hidden in base64, hex or percent encoding inside ``text`` (best effort)."""
    out: list[str] = []
    for m in _B64.finditer(text):
        try:
            frag = _printable(base64.b64decode(m.group(0) + "=" * (-len(m.group(0)) % 4)))
        except (binascii.Error, ValueError):
            frag = None
        if frag:
            out.append(frag)
    for m in _HEX.finditer(text):
        try:
            frag = _printable(bytes.fromhex(m.group(0)))
        except ValueError:
            frag = None
        if frag:
            out.append(frag)
    for m in _PCT.finditer(text):
        frag = urllib.parse.unquote(m.group(0))
        if frag != m.group(0):
            out.append(frag)
    return out


def views(text: str) -> list[str]:
    """Folded strings to match on: the Tier 0b candidates of the text, of its leet-folded form,
    of its decoded fragments and of its ROT13 form. Duplicates dropped, size capped."""
    text = text[:MAX_VIEW_CHARS]
    folded = normalise(text)
    sources = [text, leet_fold(folded), telex_tone_to_end(folded)]
    sources += decoded_fragments(text)
    sources.append(codecs.encode(normalise(text), "rot13"))
    seen: dict[str, None] = {}
    for src in sources:
        for cand in candidates(src):
            seen.setdefault(cand, None)
    return list(seen)


# --------------------------------------------------------------------------- cue lexicon
# Patterns run on folded views (lower case, no diacritics, "d" for "d-stroke").

CUES: dict[str, tuple[str, ...]] = {
    # asks the other side to continue or widen what it said ("expand on step two")
    "expand": (
        r"\bmo rong\b",
        r"\bchi tiet hon\b",
        r"\bnoi ro hon\b",
        r"\bgiai thich them\b",
        r"\btiep tuc\b",
        r"\bbuoc (?:hai|2|tiep theo|ke tiep|ba|3)\b",
        r"\bexpand on\b",
        r"\belaborate\b",
        r"\bstep (?:two|2|three|3)\b",
        r"\bgo on\b",
        r"\bmore detail",
    ),
    # leans on what the agent said earlier (consistency)
    "consistency": (
        r"\bnhu ban (?:da|vua) (?:noi|neu|de cap|viet)\b",
        r"\btheo nhu ban\b",
        r"\bban (?:da|vua) noi\b",
        r"\bas you (?:said|mentioned|noted|explained)\b",
        r"\byou just (?:said|told|explained)\b",
        r"\blike you (?:said|explained)\b",
        r"\bdung nhu ban noi\b",
    ),
    "authority": (
        r"\bgiam doc\b",
        r"\btong giam doc\b",
        r"\btruong phong\b",
        r"\bquan ly\b",
        r"\bda (?:duoc )?(?:duyet|phe duyet)\b",
        r"\bcap tren\b",
        r"\bdirector\b",
        r"\bmanager\b",
        r"\bapproved by\b",
        r"\b(?:cfo|ceo)\b",
        r"\bauthori[sz]ed\b",
    ),
    "urgency": (
        r"\bgap\b",
        r"\bkhan cap\b",
        r"\bngay bay gio\b",
        r"\bngay lap tuc\b",
        r"\bhan chot\b",
        r"\burgent",
        r"\basap\b",
        r"\bright now\b",
        r"\bdeadline\b",
    ),
    # hypothetical, story, role play, training: lowers the felt risk
    "frame": (
        r"\bgia su\b",
        r"\bkich ban\b",
        r"\bdong vai\b",
        r"\bcau chuyen\b",
        r"\bdao tao\b",
        r"\bhypothetical",
        r"\brole ?play\b",
        r"\bpretend\b",
        r"\bimagine\b",
        r"\bfor a training\b",
        r"\bin a story\b",
        r"\bbai viet\b",
        r"\ban article\b",
    ),
    # text that imitates a policy or a system message
    "policy_fake": (
        r"<\s*/?\s*(?:policy|rules?|config|system|chinh sach)\b",
        r"\bchinh sach (?:moi|noi bo)\b",
        r"\bhan muc moi\b",
        r"\bnang han muc\b",
        r"\bnew policy\b",
        r"\blimit (?:raised|increased)\b",
        r"\ballowlist\b",
        r"\[\s*he thong\s*\]",
        r"\bsystem notice\b",
        r"\"?(?:policy|max_transfer|override)\"?\s*[:=]",
        r"^\s*\[(?:policy|limits?)\]",
    ),
    # asks the agent to keep something for later
    "remember": (
        r"\bghi nho\b",
        r"\bluu lai\b",
        r"\bremember (?:that|this)\b",
        r"\bkeep in mind\b",
        r"\bnote that\b",
        r"\bfrom now on\b",
        r"\btu gio\b",
    ),
    # points back at something stored earlier
    "recall": (
        r"\bnhu da (?:ghi nho|luu|noi)\b",
        r"\btheo ghi chu\b",
        r"\bnhu (?:truoc|luc dau)\b",
        r"\bas (?:remembered|noted|stored|agreed)\b",
        r"\bas before\b",
        r"\bper the note\b",
        r"\btheo chinh sach (?:tren|vua)\b",
        r"\bper the policy above\b",
    ),
    # asks for data about other customers or many files at once
    "scope_creep": (
        r"\bkhach (?:hang )?khac\b",
        r"\bnhieu ho so\b",
        r"\bhang loat\b",
        r"\banother customer",
        r"\bother customers\b",
        r"\bseveral files\b",
        r"\bmany files\b",
    ),
    # talk about limits and how to stay under them
    "limit_talk": (
        r"\bhan muc\b",
        r"\bgioi han\b",
        r"\blimit\b",
        r"\bduoi (?:muc|han muc|nguong)\b",
        r"\bunder the limit\b",
        r"\bchia nho\b",
        r"\btach (?:ra )?(?:thanh|lam)\b",
        r"\bsplit\b",
        r"\bnhieu lan\b",
        r"\bnhieu khoan\b",
        r"\bin parts\b",
        r"\binstallments?\b",
    ),
}
_COMPILED = {k: [re.compile(p) for p in pats] for k, pats in CUES.items()}


def cue_counts(text: str) -> dict[str, int]:
    """{cue: hits} over all views of ``text`` (the largest count of any view per cue)."""
    out: dict[str, int] = {}
    vs = views(text)
    for name, pats in _COMPILED.items():
        best = 0
        for v in vs:
            n = sum(len(p.findall(v)) for p in pats)
            best = max(best, n)
        if best:
            out[name] = best
    return out
