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

CBUCKETS = 1 << 12
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


def classify_tokens(tokens: list[str]) -> list[tuple[int, str]]:
    """(position, class) pairs for the tokens of one window."""
    out: list[tuple[int, str]] = []
    n = len(tokens)
    for i, t in enumerate(tokens):
        cls: set[str] = set()
        if i + 1 < n:
            for c in _BIGRAM_CLASSES.get(f"{t} {tokens[i + 1]}", ()):
                cls.add(c)
        if t not in _WEAK:
            for c in _WORD_CLASSES.get(t, ()):
                cls.add(c)
            for c, pre in _PREFIX.items():
                if t.startswith(pre):
                    cls.add(c)
        elif t in ("must", "never", "not"):
            cls.add("NEG")
        for c in sorted(cls):
            out.append((i, c))
    return out


def _h(name: str) -> int:
    return zlib.crc32(name.encode("ascii")) & (CBUCKETS - 1)


def concept_features(text: str) -> list[int]:
    """Sorted unique concept feature ids (0 .. CBUCKETS-1) of one window of one variant."""
    raw = _TOKEN.findall(text)
    tokens: list[str] = []
    starts: set[int] = {0}
    for t in raw:
        if t in ".!?;:\n":
            starts.add(len(tokens))
        else:
            tokens.append(t)
    marks = classify_tokens(tokens)
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
    return sorted({_h(n) for n in names})
