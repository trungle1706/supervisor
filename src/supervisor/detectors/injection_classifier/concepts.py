"""Concept features: a small bilingual lexicon that lets the model generalise across wordings.

Character n-grams learn the exact words of the training templates. A concept layer maps words
(Vietnamese without diacritics, English) to a few classes, and the model learns from how classes
combine, whatever the wording and the language: "override verb then rule noun" (``ignore ...
instructions``, ``bo qua ... huong dan``), a negation or a quote marker in front of it (policy text,
complaints, training notes), a claim of authority, a request for secrecy, an exfiltration verb with
a data noun, an address to the assistant. The lexicon is hand written for this repo (not copied
from a vendor), is part of ``FEATURE_VERSION`` and is listed in docs/injection-classifier.md.

Classes (short ids used in feature names): OVR override or skip verbs, RUL rule and control nouns,
AGT words that address the assistant or the system, SEC secrecy, AUT authority claim, NOW new
instruction markers, EXF exfiltration or reveal verbs, DAT sensitive data nouns, MON money
movement or approval verbs, NEG negation or prohibition, QUO quote, policy, training or
discussion markers, REQ polite customer request markers, TAG role tags.
"""

from __future__ import annotations

import re
import zlib

from supervisor.detectors.injection_classifier._cache import HashedLRU

CBUCKETS = 1 << 14
_TOKEN = re.compile(r"[a-z0-9<>/\[\]]+|[.!?;:\n]")

_WORDS: dict[str, tuple[str, ...]] = {
    "OVR": (
        "ignore ignored ignoring disregard forget bypass bypassing skip skipping override overrule "
        "circumvent suspend lift waive cancel drop abandon stop pretend phot quen vuot huy go ngung"
    ).split(),
    "RUL": (
        "instruction instructions rule rules guideline guidelines prompt prompts policy policies limit "
        "limits restriction restrictions check checks approval verification otp kyc screening control "
        "controls constraint constraints configuration config step directive directives "
        "huong quy chi han phe xac kiem rang gioi chinh buoc"
    ).split(),
    "AGT": (
        "assistant ai model agent bot llm automated reviewer system he thong tro mo hinh"
    ).split(),
    "SEC": ("silently quietly secretly hidden covertly stealthily confidential am tham").split(),
    "AUT": (
        "ceo cfo cto director admin administrator owner auditor compliance manager treasury giam doc "
        "quan tri chu kiem toan truong"
    ).split(),
    "NOW": ("immediately instead now obey priority urgent asap lap tuc thay chi").split(),
    "EXF": (
        "send forward email reveal disclose print dump paste leak export copy gui tiet lo in liet sao"
    ).split(),
    "DAT": (
        "customer customers database password credentials token ids id cccd account accounts balance "
        "khach khach_hang so tai khoan sao ke mat khau co"
    ).split(),
    "MON": (
        "transfer wire pay release approve disburse payment funds move chuyen giai ngan thanh toan duyet "
        "phe"
    ).split(),
    "NEG": (
        "not never no cannot cant dont doesnt wont without must_not khong dung cam chua tuyet "
        "nobody none"
    ).split(),
    "QUO": (
        "example quote quoted training handbook manual states stated according per reminder note "
        "article question why how explain complaint complained told said asks asked "
        "vi du dao tao so tay noi quy theo trich nhac bai bao cau hoi giai thich khieu nai phan anh "
        "hoi nhan"
    ).split(),
    "REQ": ("please kindly thank thanks thankyou cam on nho vui long xin").split(),
    "YOU": "you your ban".split(),
    "ME": "i my me mine toi em".split(),
    "SUBJ": "staff employee employees officer officers customers clients personnel clerk teller".split(),
    "REF": (
        "previous previously above earlier prior preceding former before aforementioned truoc tren "
        "cu"
    ).split(),
    "INS": "instead rather thay".split(),
    "MOD": "must should shall required need needs phai nen can".split(),
    "TAG": (
        "<system>",
        "</system>",
        "<important>",
        "</important>",
        "<assistant>",
        "[system]",
        "[hidden]",
    ),
}
# words that are only a concept inside the listed phrase (checked on bigrams)
_BIGRAMS: dict[str, tuple[str, ...]] = {
    "OVR": ("bo qua", "vuot qua", "bo buoc", "khong can", "thay vi", "stop following", "do away"),
    "RUL": (
        "huong dan",
        "quy tac",
        "quy dinh",
        "chi dan",
        "han muc",
        "phe duyet",
        "xac minh",
        "kiem tra",
        "loi nhac",
        "system prompt",
        "dual control",
        "second approver",
    ),
    "SEC": (
        "dung bao",
        "khong thong",
        "khong nhac",
        "khong hien",
        "dung ghi",
        "khong noi",
        "do not tell",
        "dont tell",
        "never mention",
        "do not mention",
        "do not display",
        "do not log",
        "dont log",
        "keep quiet",
        "bi mat",
    ),
    "AUT": ("i am", "this is", "on behalf", "as the", "tu cach"),
    "NOW": ("new instructions", "from now", "tu gio", "chi thi", "nhiem vu"),
    "AGT": ("language model", "tro ly"),
    "REF": ("truoc do", "o tren", "luc truoc", "ban dau", "da neu", "nhu tren"),
    "INS": ("thay vao", "thay vi", "no longer", "khong con"),
    "MOD": ("co the", "can phai", "ban phai"),
    "EXF": ("in ra", "liet ke", "gui toan", "gui ban"),
    "DAT": ("khach hang", "tai khoan", "so du", "ma otp", "co so", "system prompt"),
    "SUBJ": ("nhan vien", "can bo", "khach hang", "bo phan"),
    "ME": ("cho minh", "minh muon"),
    "NEG": ("do not", "must not", "should not", "may not", "khong duoc", "khong bao", "khong the"),
    "MON": ("giai ngan", "thanh toan", "chuyen tien", "chuyen khoan"),
}
_PREFIX = {
    "OVR": ("ignor", "disregard", "bypass", "overrid", "overrul", "circumvent", "forget", "forgot"),
    "SEC": ("secret", "silent", "quiet", "covert"),
}

_WORD_CLASSES: dict[str, list[str]] = {}
for _c, _ws in _WORDS.items():
    for _w in _ws:
        _WORD_CLASSES.setdefault(_w, []).append(_c)
_BIGRAM_CLASSES: dict[str, list[str]] = {}
for _c, _bs in _BIGRAMS.items():
    for _b in _bs:
        _BIGRAM_CLASSES.setdefault(_b, []).append(_c)

# Words that are too common to count as a class alone (they only count inside a bigram above).
_WEAK = frozenset(
    "chi thay co so dung xin in theo nho hoi gui he thong tro mo hinh sao khach quen huy go ngung "
    "the an ai bo huong quy phe xac kiem rang gioi chinh buoc cam chua tuyet lift drop stop note "
    "per system owner manager control step now".split()
)
# Verbs that open an instruction when they start a clause (also after please / hay / xin).
_IMP_VERBS = frozenset(
    (
        "ignore disregard forget bypass skip override send forward transfer wire pay release approve "
        "reveal print show list set mark add update call run execute copy output repeat pretend act "
        "treat disable switch stop cancel confirm sign take put leave give reply respond tell "
        "delete remove change replace append include disclose dump paste move make let turn "
        "hay dung bo quen chuyen gui duyet in liet dat danh them goi chay sao thuc tat huy xac ky "
        "lay cho phat doi xoa tiet cap tra noi"
    ).split()
)
_IMP_LEAD = frozenset("please kindly just now then also hay xin vui long lam on nhe".split())
_VOWELS = frozenset("aeiou")

_SPAN = 6
_TRIPLE_SPAN = 9
_TRIPLE_CLASSES = frozenset(
    {
        "NEG",
        "QUO",
        "AUT",
        "OVR",
        "RUL",
        "SEC",
        "MON",
        "EXF",
        "DAT",
        "AGT",
        "NOW",
        "REQ",
        "YOU",
        "ME",
        "SUBJ",
    }
)


def stem(t: str) -> str:
    """Light English stemmer for lookup: ignoring -> ignor, instructions -> instruction."""
    n = len(t)
    if n > 5 and t.endswith("ing"):
        return t[:-3]
    if n > 4 and t.endswith("ed"):
        return t[:-2]
    if n > 4 and t.endswith("es") and t[-3] in "sxz":
        return t[:-2]
    if n > 4 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    if n > 5 and t.endswith("ly"):
        return t[:-2]
    return t


# Typo tolerance (Damerau distance 1) for words of five letters or more, without a model: a symmetric
# delete index of the lexicon words. A token that is not a lexicon word but is one edit away from one
# gets that word's classes.
_FUZZY_VOCAB = sorted({w for w in _WORD_CLASSES if len(w) >= 5 and w.isalpha()})
_DELETES: dict[str, set[str]] = {}
for _w in _FUZZY_VOCAB:
    _DELETES.setdefault(_w, set()).add(_w)
    for _i in range(len(_w)):
        _DELETES.setdefault(_w[:_i] + _w[_i + 1 :], set()).add(_w)


def _fuzzy_uncached(t: str) -> tuple[str, ...]:
    """Classes of the lexicon word within one edit of ``t`` ('' when none or ambiguous)."""
    if len(t) < 5 or len(t) > 20 or not t.isalpha():
        return ()
    found: set[str] = set()
    for d in [t] + [t[:i] + t[i + 1 :] for i in range(len(t))]:
        for w in _DELETES.get(d, ()):
            if w != t and abs(len(w) - len(t)) <= 1:
                found.add(w)
    for i in range(len(t) - 1):  # adjacent transposition
        sw = t[:i] + t[i + 1] + t[i] + t[i + 2 :]
        if sw in _WORD_CLASSES and len(sw) >= 5:
            found.add(sw)
    if len(found) != 1:
        return ()
    return tuple(sorted(_WORD_CLASSES[next(iter(found))]))


_FUZZY_CACHE = HashedLRU(_fuzzy_uncached, 8192)  # keyed by a hash of the token (G5)


def _fuzzy(t: str) -> tuple[str, ...]:
    return _FUZZY_CACHE(t)


def _word_classes(t: str) -> list[str]:
    cls = _WORD_CLASSES.get(t)
    if cls:
        return list(cls)
    st = stem(t)
    if st != t:
        cls = _WORD_CLASSES.get(st) or _WORD_CLASSES.get(st + "e")
        if cls:
            return list(cls)
    return list(_fuzzy(t))


def classify_tokens(
    tokens: list[str], starts: frozenset[int] | set[int] = frozenset()
) -> list[tuple[int, str]]:
    """(position, class) pairs for the tokens of one window. ``starts`` are clause start positions:
    a verb of instruction at a clause start (after please / hay) gets the class IMP."""
    out: list[tuple[int, str]] = []
    n = len(tokens)
    for i, t in enumerate(tokens):
        cls: set[str] = set()
        if i + 1 < n:
            for c in _BIGRAM_CLASSES.get(f"{t} {tokens[i + 1]}", ()):
                cls.add(c)
        if t not in _WEAK:
            for c in _word_classes(t):
                cls.add(c)
            for c, pre in _PREFIX.items():
                if t.startswith(pre):
                    cls.add(c)
        elif t in ("must", "never", "not"):
            cls.add("NEG")
        if t in _IMP_VERBS or stem(t) in _IMP_VERBS:
            j = i
            while j > 0 and tokens[j - 1] in _IMP_LEAD:
                j -= 1
            if j in starts:
                cls.add("IMP")
        for c in sorted(cls):
            out.append((i, c))
    return out


def _h(name: str) -> int:
    return zlib.crc32(name.encode("ascii")) & (CBUCKETS - 1)


def concept_features(text: str, surface: str = "args") -> list[int]:
    """Sorted unique concept feature ids (0 .. CBUCKETS-1) of one window of one variant. Each feature
    is emitted twice: shared by all surfaces, and tagged with the surface (own weight block)."""
    raw = _TOKEN.findall(text)
    tokens: list[str] = []
    starts: set[int] = {0}
    for t in raw:
        if t in ".!?;:\n":
            starts.add(len(tokens))
        else:
            tokens.append(t)
    marks = classify_tokens(tokens, starts)
    names: set[str] = set()
    for pos, c in marks:
        # a class at the start of a clause (or right after one word): imperative or declarative
        if pos in starts or (pos - 1) in starts:
            names.add("s:" + c)
    for _, c in marks:
        names.add("u:" + c)
    for a in range(len(marks)):
        ia, ca = marks[a]
        for b in range(a + 1, len(marks)):
            ib, cb = marks[b]
            if ib - ia > _TRIPLE_SPAN:
                break
            if ib != ia and ib - ia <= _SPAN:
                names.add(f"p:{ca}>{cb}")
            if ca in _TRIPLE_CLASSES and cb in _TRIPLE_CLASSES and ib != ia:
                for c in range(b + 1, len(marks)):
                    ic, cc = marks[c]
                    if ic - ia > _TRIPLE_SPAN:
                        break
                    if ic != ib and cc in _TRIPLE_CLASSES:
                        names.add(f"t:{ca}>{cb}>{cc}")
    if "?" in text:
        names.add("g:question")
    if text.count(" ") < 3:
        names.add("g:short")
    names.add(f"n:{min(8, len(marks) // 2)}")  # how many concept marks (length normalisation)
    shared = {_h(n) for n in names}
    tagged = {_h(f"{surface}|{n}") for n in names}
    return sorted(shared | tagged)
