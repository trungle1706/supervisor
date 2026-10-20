"""Finders for names, street addresses and money amounts (``vn_regex-3``). Pure, stdlib only.

Why a separate module: the three finders need token-level logic that one regex cannot give.

* Names: upper-case, lower-case and mixed-case, with and without diacritics, telex-typed
  (``Nguyeenx Vawn Thuwr``). Anchored on the surname lexicon or on a title / label / JSON key;
  an unknown final name word is accepted when it is written as a name (Title or UPPER case).
* Addresses: house number + street + ward / district / province, in any case, with or without
  diacritics, with ``P.6``, ``Q.3`` abbreviations and ``TP.HCM``.
* Amounts: ``1.500.000.000 VND``, ``1,5 tỷ``, ``500tr``, JSON floats such as ``9100000000.0``,
  and bare digit runs next to an amount key. They run BEFORE account detection so a VND amount
  is never typed as a bank account (the credit-memo defect).

Each finder returns ``(start, end)`` tuples on the canonical text.
"""

from __future__ import annotations

import bisect
import contextlib
import re
import unicodedata
from collections.abc import Iterable, Iterator

from supervisor.data import wordlists as W

__all__ = ["amount_spans", "address_spans", "id_shaped", "person_spans"]


def fold(text: str) -> str:
    out = unicodedata.normalize("NFD", text)
    out = "".join(c for c in out if unicodedata.category(c) != "Mn")
    return out.replace("đ", "d").replace("Đ", "D")


def _k(word: str) -> str:
    return fold(word).lower()


# ---------------------------------------------------------------------------- lexicon
# Additions to the generator lists (src/supervisor/data/wordlists.py). Common Vietnamese
# names, own list. The held-out pools of the golden set (pii_eval/generate.py HELD_*) must
# stay OUT of this lexicon: a test asserts it.
SURNAMES_EXTRA: tuple[str, ...] = (
    "Trương", "Lương", "Phùng", "Tạ", "Đoàn", "Châu", "Hà", "Từ", "La", "Thái", "Triệu",
    "Diệp", "Ninh", "Doãn", "Chu", "Mạc", "Bạch", "Lưu", "Tô", "Tăng", "Khúc", "Hứa",
    "Liêu", "Trình", "Âu", "Nghiêm", "Vương", "Lê", "Giang", "Thạch", "Quách", "Tống",
    "Lữ", "Kiều",
)  # fmt: skip
MIDDLE_EXTRA: tuple[str, ...] = (
    "Bích", "Hồng", "Tuyết", "Diệu", "Thúy", "Xuân", "Hải", "Tiến", "Thái", "Ngọc", "Lan",
    "Yến", "Nhi", "Đình", "Hoàng", "Trọng", "Thùy", "Như", "Tú", "Quốc", "Hoài", "Thế",
    "Trung", "Đăng", "Nhật", "Bá", "Chí", "Hiền", "Hạ", "Lệ", "Cẩm", "Tâm", "Vĩnh",
    "Duy", "Khắc", "Diễm", "Tường",
)  # fmt: skip
GIVEN_EXTRA: tuple[str, ...] = (
    "Thử", "Tâm", "Tùng", "Đạt", "Hiếu", "Nghĩa", "Kiên", "Lộc", "Thuận", "Uyên", "Vân",
    "Yến", "Bích", "Châu", "Diễn", "Giao", "Khánh", "Liên", "Nguyên", "Sương", "Hiền",
    "Hoài", "Hưng", "Hiệp", "Hòa", "Trâm", "Trinh", "Trúc", "Tuệ", "Phước", "Phú", "Quốc",
    "Quý", "Quyết", "Sang", "Tân", "Thiện", "Thọ", "Thông", "Thương", "Tiên", "Tín", "Trí",
    "Trường", "Vinh", "Vương", "Diệp", "Đan", "Đào", "Điệp", "Đông", "Giàu", "Hân", "Hiển",
    "Hoan", "Huân", "Kha", "Khải", "Lực", "Mạnh", "Nga", "Nghi", "Nhân", "Như", "Phát",
    "Phi", "Quỳnh", "Thắm", "Thanh", "Thành", "Thủy", "Tiến", "Trọng", "Tuyết", "Ánh",
    "Bảo", "Cúc", "Duyên", "Bách", "Cảnh", "Hậu", "Huệ", "Khôi", "Lâm", "Mẫn", "Nhàn", "Nghiêu",
    "Rạng", "Sinh", "Tấn", "Thịnh", "Triều", "Tuyền", "Út", "Xuyến", "Hạ", "Hồng", "Huyền",
    "Lệ", "Loan", "Ly", "Ngọc", "Nhung",
    "Phượng", "Thơm", "Thư", "Thúy", "Xuân", "Tú", "Tuấn", "Hải", "Lan", "Minh", "Hoàng",
)  # fmt: skip


def _clean(words: tuple[str, ...]) -> set[str]:
    return {_k(w) for w in words if not w.endswith("_")}


SURS = _clean(tuple(W.SURNAMES) + SURNAMES_EXTRA)
MIDS = _clean(tuple(W.MIDDLE_MALE + W.MIDDLE_FEMALE) + MIDDLE_EXTRA)
GIVENS = _clean(tuple(W.GIVEN_MALE + W.GIVEN_FEMALE) + GIVEN_EXTRA) | MIDS - {"van", "thi"}
NAME_LEXICON = SURS | MIDS | GIVENS


def _exact(words: tuple[str, ...]) -> frozenset[str]:
    return frozenset(unicodedata.normalize("NFC", w).lower() for w in words if not w.endswith("_"))


_SURS_EX = _exact(tuple(W.SURNAMES) + SURNAMES_EXTRA)
_MIDS_EX = _exact(tuple(W.MIDDLE_MALE + W.MIDDLE_FEMALE) + MIDDLE_EXTRA)
_GIVENS_EX = _exact(tuple(W.GIVEN_MALE + W.GIVEN_FEMALE) + GIVEN_EXTRA) | _MIDS_EX
_EXACT_OF: dict[int, frozenset[str]] = {
    id(SURS): _SURS_EX,
    id(MIDS): _MIDS_EX,
    id(GIVENS): _GIVENS_EX,
    id(NAME_LEXICON): _SURS_EX | _MIDS_EX | _GIVENS_EX,
}
_EXACT_FULL = dict(_EXACT_OF)


@contextlib.contextmanager
def ablate(words: Iterable[str]) -> Iterator[None]:
    """Remove ``words`` from the lexicon for the duration of the block. EVALUATION ONLY: the
    held-out split of the golden set is scored with its own name pools removed, so the figure
    measures generalisation to names the lexicon does not know. Production always ships the
    full lexicon. Not thread safe."""
    keys = {_k(w) for w in words}
    exact = {unicodedata.normalize("NFC", w).lower() for w in words}
    saved = [(lex, set(lex)) for lex in (SURS, MIDS, GIVENS, NAME_LEXICON)]
    try:
        for lex, _old in saved:
            lex -= keys
        for k, v in _EXACT_FULL.items():
            _EXACT_OF[k] = v - exact
        yield
    finally:
        for lex, old in saved:
            lex.clear()
            lex.update(old)
        _EXACT_OF.update(_EXACT_FULL)


# Surnames that are also ordinary words are accepted in lower-case text only when spelled
# like a name with a distinctive surname.
LOWER_SURS = frozenset(
    "nguyen tran le pham hoang huynh phan vu dang bui duong trinh dinh luong truong phung "
    "doan chau ngo vo".split()
)

# Words that look like a name in Title or UPPER case but are not (function words, document
# words, role words). Folded, lower case.
STOP = frozenset(
    "a an and the va la co khong da dang se vay cho voi cua tai o trong ngoai ngay thang nam "
    "hop dong tien so dia chi khach hang nguoi nhan chu the tai khoan ngan hang chi nhanh "
    "cong ty tnhh co phan thuong mai dich vu ky ten xac nhan de nghi vay von muc dich "
    "giam doc ke toan truong phong ma ho so thu tuc phe duyet duyet tu choi den tu den "
    "quan huyen phuong xa thi tran thanh pho tinh tp quoc gia viet nam ria noi "
    "thong tin muc luong thu nhap lai suat ky han tai san bao dam the chap dien thoai "
    "email mail sdt cmnd cccd mst stk dai dien phap luat dinh danh can cuoc cong dan "
    "ngay sinh gioi tinh nu nam quoc tich".split()
)
_PLACE_FOLDED = frozenset(
    {_k(v) for v in W.PROVINCES.values()}
    | {"ho chi minh", "sai gon", "ha noi", "viet nam", "da nang", "hue", "can tho"}
)

_PLACES3 = sorted(
    {v for v in W.PROVINCES.values() if len(v.split()) >= 3}
    | {_k(v) for v in W.PROVINCES.values() if len(v.split()) >= 3}
    | {"Hồ Chí Minh", "Ho Chi Minh"},
    key=lambda x: (-len(x), x),
)
_RE_PLACE3 = re.compile(
    r"(?<!\w)(?i:"
    + "|".join(re.escape(x).replace(r"\ ", r"\s+") for x in _PLACES3)
    + r")(?:\s+(?i:city))?(?!\w)"
)
# A brand or street written in English after a surname-like pair is not a person.
_BRAND_SUFFIX = frozenset(
    "street st road rd avenue ave group corp corporation company co ltd jsc holdings holding "
    "walking hospital school university bank mobile plaza city center centre tower park hotel "
    "resort mall market shop store "
    "club studio media tech technology".split()
)
# Surnames that are ordinary function words: never a middle or given name.
_FUNC_SURS = frozenset({"do", "la", "ho"})
_WORD = re.compile(r"[^\W\d_]+")


def _telex(k: str) -> str:
    """Strip telex typing from a folded lower-case word (``thuwr`` -> ``thu``)."""
    if len(k) > 2 and k[-1] in "sfrxj":
        k = k[:-1]
    for a, b in (("uow", "uo"), ("aw", "a"), ("ow", "o"), ("uw", "u"), ("aa", "a"), ("ee", "e"),
                 ("oo", "o"), ("dd", "d")):  # fmt: skip
        k = k.replace(a, b)
    return k


def _in(tok: str, lex: set[str] | frozenset[str]) -> bool:
    """Is ``tok`` a lexicon word? A word with diacritics must be spelled exactly (so "nguyên",
    "đó", "thể" are not names); plain ASCII matches the folded form, also telex-typed."""
    k = _k(tok)
    if not tok.isascii():
        return k in lex and unicodedata.normalize("NFC", tok).lower() in _EXACT_OF[id(lex)]
    return k in lex or (len(k) > 2 and _telex(k) in lex)


def _cased(tok: str) -> bool:
    """Title case or UPPER case (a name as it is written), with or without diacritics."""
    return len(tok) >= 2 and tok[0].isupper() and (tok.isupper() or tok[1:].islower())


def _is_stop(tok: str) -> bool:
    k = _k(tok)
    return k in STOP and k not in NAME_LEXICON


class _Tok:
    __slots__ = ("end", "start", "text")

    def __init__(self, start: int, end: int, text: str) -> None:
        self.start, self.end, self.text = start, end, text


def _tokens(text: str) -> list[_Tok]:
    return [_Tok(m.start(), m.end(), m.group()) for m in _WORD.finditer(text)]


def _chain_ok(text: str, a: _Tok, b: _Tok) -> bool:
    return text[a.end : b.start] == " "


_STREET_BEFORE = re.compile(
    r"(?<![\w])(?i:đường|duong|phố|pho|ngõ|ngo|hẻm|hem|quận|quan|huyện|huyen|phường|phuong|"
    r"xã|thành phố|thanh pho|tỉnh|tinh|tp\.?|đại lộ|dai lo)\s*$"
)


def _place_like(words: list[str]) -> bool:
    return " ".join(_k(w) for w in words) in _PLACE_FOLDED


# Labels (honorific, role, key) that precede a person name. STRONG labels accept any written
# name; LOOSE labels are ordinary words too (Anh, Chi, Ba, của) and need lexicon evidence.
_LABEL_STRONG = (
    r"ông|ong|bà|ba|mr|ms|mrs|miss|mister|khách hàng|khach hang|người nhận|nguoi nhan|"
    r"người thụ hưởng|nguoi thu huong|chủ tài khoản|chu tai khoan|chủ thẻ|chu the|giám đốc|"
    r"giam doc|đại diện pháp luật|dai dien phap luat|đại diện|dai dien|người đại diện|"
    r"nguoi dai dien|họ và tên|ho va ten|họ tên|ho ten|tên khách hàng|ten khach hang|"
    r"tên|ten|tôi là|toi la|người vay|nguoi vay|bên vay|ben vay|bên a|bên b|ký bởi|ky boi|"
    r"bởi|boi|applicant|holder|payee|beneficiary|customer name|customer|this is|name"
)
_LABEL_LOOSE = r"anh|chị|chi|cô|co|chú|chu|của|cua|em|bác|bac|cháu|chau"
_RE_LABEL = re.compile(
    rf"(?<!\w)(?i:(?P<strong>{_LABEL_STRONG})|(?P<loose>{_LABEL_LOOSE}))(?!\w)"
    r"""[.:,]?["'\s]*"""
)
_RE_JSON_KEY = re.compile(
    r'(?i:"(?:full_?name|ho_?ten|ten_?khach_?hang|customer_?name|director|legal_?rep\w*|'
    r"holder|owner|applicant|giam_?doc|nguoi_?\w+|payee|beneficiary|name|ten|"
    r'account_?holder|contact\w*|representative)")\s*:\s*"'
)
_COMPANY = re.compile(
    r"(?i:công ty|cong ty|tnhh|ngân hàng|ngan hang|cổ phần|co phan|tập đoàn|tap doan|"
    r"doanh nghiệp|doanh nghiep|chi nhánh|chi nhanh|hợp tác xã|hop tac xa)"
)


def _open_ok(tok: str) -> bool:
    """A written name word that is not in the lexicon: Title or UPPER case, short like a
    Vietnamese syllable (so English words such as "Anything" do not pass), not a stop word."""
    return (
        _cased(tok)
        and len(tok) <= 7
        and (len(tok) > 2 or _in(tok, NAME_LEXICON))
        and not _is_stop(tok)
    )


def _lower_name(words: list[str]) -> bool:
    """Lower-case text is risky (thế, từ, thường are also words). Accept only surname + middle
    + given name(s), all from the lexicon, a diacritic word only in its exact spelling."""
    return (
        len(words) >= 3
        and _in(words[0], SURS)
        and (_k(words[0]) in LOWER_SURS or _k(words[1]) in ("thi", "van"))
        and _in(words[1], MIDS)
        and all(_in(w, NAME_LEXICON) for w in words)
    )


_WEAK_LABELS = frozenset(
    {"toi la", "this is", "khach hang", "customer", "boi", "ky boi", "nguoi vay", "ben vay",
     "applicant", "name"}
)  # fmt: skip
_HONORS = frozenset({"ong", "ba", "anh", "chi", "co", "chu", "mr", "ms", "mrs", "miss", "em"})


_COMPANY_CTX = re.compile(
    r"(?i:công ty|cong ty|tnhh|ngân hàng|ngan hang|cổ phần|co phan|tập đoàn|tap doan)"
    r"(?:\s+[^\W\d_]+){0,6}\s+$"
)


def _take_chain(toks: list[_Tok], text: str, i: int, limit: int) -> list[_Tok]:
    """Consecutive name-like tokens from index ``i`` (single space apart, one case mode)."""
    out: list[_Tok] = []
    mode = ""
    for j in range(i, min(len(toks), i + limit)):
        t = toks[j]
        if out and not _chain_ok(text, out[-1], t):
            break
        if not out and _k(t.text) in _HONORS and j + 1 < len(toks):
            continue  # "người đại diện: Ông Trần Văn Bách": the title is not the name
        if _is_stop(t.text):
            break
        if _cased(t.text) and (_in(t.text, NAME_LEXICON) or _open_ok(t.text)):
            this = "cased"
        elif _in(t.text, NAME_LEXICON) and t.text.islower():
            this = "lower"
        else:
            break
        if mode and this != mode:
            break
        mode = this
        out.append(t)
    return out


_PRODUCT_BEFORE = re.compile(
    r"(?i:gói|goi|sản phẩm|san pham|chương trình|chuong trinh|dịch vụ|dich vu|tiết kiệm|"
    r"tiet kiem|bảo hiểm|bao hiem)\s+$"
)


def _brand_follows(toks: list[_Tok], text: str, last: int) -> bool:
    """A brand or street suffix ("Street", "Group", "Tower") within 3 words after the match."""
    prev = toks[last]
    for t in toks[last + 1 : last + 4]:
        if not _chain_ok(text, prev, t):
            return False
        if _k(t.text) in _BRAND_SUFFIX:
            return True
        prev = t
    return False


def person_spans(text: str) -> tuple[list[tuple[int, int, str]], list[tuple[int, int, str]]]:
    """(plain, labelled) person spans as ``(start, end, why)``."""
    toks = _tokens(text)
    plain: list[tuple[int, int, str]] = []
    labelled: list[tuple[int, int, str]] = []

    starts = [t.start for t in toks]

    def first_token_at(pos: int) -> int | None:
        n = bisect.bisect_left(starts, pos)
        if n < len(toks) and toks[n].start - pos <= 3:
            return n
        return None

    def street_before(pos: int) -> bool:
        return bool(_STREET_BEFORE.search(text[max(0, pos - 24) : pos]))

    # ---- labelled: honorific / role / JSON key
    for m in list(_RE_LABEL.finditer(text)) + list(_RE_JSON_KEY.finditer(text)):
        strong = m.re is _RE_JSON_KEY or m.groupdict().get("strong") is not None
        n0 = first_token_at(m.end())
        if n0 is None:
            continue
        if _COMPANY.match(text, toks[n0].start):
            continue
        # A label word that is itself part of a longer word run is not a label ("Chi nhánh").
        chain = _take_chain(toks, text, n0, 4 if not strong else 5)
        if not chain:
            continue
        if street_before(toks[n0].start):
            continue
        words = [t.text for t in chain]
        if _place_like(words):
            continue
        if words[0].islower() and not (
            _lower_name(words)
            or (
                len(words) >= 3 and _in(words[0], SURS) and all(_in(w, NAME_LEXICON) for w in words)
            )
        ):
            continue  # lower case after a label: surname first and three name words at least
        label = m.group().strip(" .:,\"'")
        if not strong:
            # "Anh Tuấn", "Chị Lan", "của Nguyễn Văn A": the first word must be a lexicon name
            # (not "GHI CHÚ HỆ THỐNG"), and a lone name needs a capitalised, not UPPER, label.
            if not _in(words[0], NAME_LEXICON):
                continue
            if _k(chain[0].text) == "nhanh":
                continue
            if len(chain) == 1 and not (label[:1].isupper() and not label.isupper()):
                continue  # "chuyen den anh Nam": a first name alone after a lower-case "anh"
        elif (
            m.re is not _RE_JSON_KEY
            and _k(label) in _WEAK_LABELS
            and len(chain) < 3
            and not any(_in(w, NAME_LEXICON) for w in words)
        ):
            continue  # "tôi là: DROP TABLE": a weak label needs a lexicon name or 3 words
        elif (
            len(chain) == 1
            and not _in(words[0], NAME_LEXICON)
            and not (m.re is _RE_JSON_KEY or _k(label) in _HONORS)
        ):
            continue  # "khách hàng VIP": one unknown word is not enough without a title
        labelled.append((chain[0].start, chain[-1].end, "label"))

    # ---- plain: surname + middle(s) + given, any case, with or without diacritics
    n = 0
    while n < len(toks):
        s = toks[n]
        found = _plain_at(toks, text, n)
        if found is None:
            n += 1
            continue
        last = found
        in_company = last - n == 1 and _COMPANY_CTX.search(text[max(0, s.start - 80) : s.start])
        if (
            not in_company  # "Công ty TNHH Hoàng Long": a brand, not a person
            and not street_before(s.start)
            and not _place_like([t.text for t in toks[n : last + 1]])
        ):
            if _brand_follows(toks, text, last) or _PRODUCT_BEFORE.search(
                text[max(0, s.start - 24) : s.start]
            ):
                n = last + 1
                continue
            plain.append((s.start, toks[last].end, "plain"))
        n = last + 1
    places = [(m.start(), m.end()) for m in _RE_PLACE3.finditer(text)]
    if places:  # "Hồ Chí Minh", "Ho Chi Minh City": a province, not a person
        keep = lambda sp: not any(sp[0] < pe and ps < sp[1] for ps, pe in places)  # noqa: E731
        plain = [sp for sp in plain if keep(sp)]
        labelled = [sp for sp in labelled if keep(sp)]
    return plain, _merge_labelled(labelled, plain)


def _merge_labelled(
    labelled: list[tuple[int, int, str]], plain: list[tuple[int, int, str]]
) -> list[tuple[int, int, str]]:
    """A loose title can be part of the name ("Nguyễn Anh Tuấn": "Anh" is a middle name). The
    labelled span then covers only "Tuấn" and, having the higher priority, would leave
    "Nguyễn Anh" in the text. Grow a labelled span over every plain span it overlaps."""
    if not plain:
        return labelled
    starts = [p[0] for p in plain]  # plain spans are sorted and do not overlap
    out: list[tuple[int, int, str]] = []
    for ls, le, why in labelled:
        i = max(0, bisect.bisect_right(starts, ls) - 1)
        s, e = ls, le
        while i < len(plain) and plain[i][0] < le:
            ps, pe, _ = plain[i]
            if ps < le and ls < pe:
                s, e = min(s, ps), max(e, pe)
            i += 1
        out.append((s, e, why))
    return out


def _plain_at(toks: list[_Tok], text: str, n: int) -> int | None:
    end = _plain_end(toks, text, n)
    if end is not None and _k(toks[n].text) in _FUNC_SURS and end - n < 2:
        return None  # "DO TU" in "LY DO TU CHOI": a two-word name needs a real surname
    return end


def _plain_end(toks: list[_Tok], text: str, n: int) -> int | None:
    """Index of the last token of a name that starts at ``toks[n]`` (a surname), or None."""
    s = toks[n]
    if not _in(s.text, SURS):
        return None
    cased = _cased(s.text)
    if not cased and not s.text.islower():
        return None
    rest: list[_Tok] = []
    for t in toks[n + 1 : n + 5]:
        prev = rest[-1] if rest else s
        if not _chain_ok(text, prev, t) or _is_stop(t.text) or _k(t.text) in _FUNC_SURS:
            break
        if cased and not (_cased(t.text) and (_in(t.text, NAME_LEXICON) or _open_ok(t.text))):
            break
        if not cased and not (t.text.islower() and _in(t.text, NAME_LEXICON)):
            break
        rest.append(t)
    if not cased:  # lower case text: surname + thi/van + given name(s), lexicon only
        words = [s.text] + [t.text for t in rest]
        for k in (4, 3):
            if len(words) >= k and _lower_name(words[:k]):
                return n + k - 1
        return None
    mids = 0
    while mids < min(2, len(rest)) and _in(rest[mids].text, MIDS):
        mids += 1
    if mids >= 1:
        if mids < len(rest):  # open final word, written as a name
            end = mids
            if end + 1 < len(rest) and _in(rest[end + 1].text, GIVENS) and end < 3:
                end += 1
            return n + 1 + end
        if _in(rest[mids - 1].text, GIVENS):
            return n + mids  # "Trần Thị Ngọc": the last middle word is the given name
        return None
    if rest and _in(rest[0].text, GIVENS):
        end = 1 if len(rest) > 1 and _in(rest[1].text, GIVENS) else 0
        return n + 1 + end
    if len(rest) >= 2:  # surname + two unknown written words: "Nguyễn Duy Hậu"
        return n + 2
    return None


# ---------------------------------------------------------------------------- addresses
_UP = "A-ZĐÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ"
_CAP = rf"[{_UP}][^\W\d_]*"
_LEX_LOC = sorted(
    set(W.PROVINCES.values())
    | {_k(v) for v in W.PROVINCES.values()}
    | {"Hồ Chí Minh", "Sài Gòn", "Hà Nội", "Việt Nam", "Thủ Đức", "Tân Bình", "Bình Thạnh",
       "Gò Vấp", "Phú Nhuận", "Cầu Giấy", "Ba Đình", "Hoàn Kiếm", "Đống Đa", "Hải Châu",
       "Thanh Khê", "Ninh Kiều"}
    | {"ho chi minh", "sai gon", "ha noi", "viet nam", "vietnam", "hcm", "hn", "hue",
       "thu duc", "tan binh", "binh thanh", "go vap", "phu nhuan", "cau giay", "ba dinh",
       "hoan kiem", "dong da", "hai chau", "thanh khe", "ninh kieu"},
    key=lambda s: (-len(s), s),
)  # fmt: skip
_LEX_ALT = "|".join(re.escape(x).replace(r"\ ", " ") for x in _LEX_LOC)
_FOLD_LEX = f"(?i:{_LEX_ALT})"
_PROV = rf"(?:(?i:thành phố|thanh pho|tp\.?|tỉnh|tinh)\s*)?(?:{_FOLD_LEX}|{_CAP}(?: {_CAP}){{0,2}})"
_PROV_STRICT = (
    rf"(?:(?i:tp\.?\s*(?:hcm|hn|hcmc)|tphcm|tphn)(?!\w)|"
    rf"(?:(?i:thành phố|thanh pho|tp\.?|tỉnh|tinh)\s*)?{_FOLD_LEX}(?!\w)|"
    rf"(?i:thành phố|thanh pho|tp\.?|tỉnh|tinh)\s*{_CAP}(?: {_CAP}){{0,2}})"
)
_UNIT_KW = (
    r"(?i:phường|phuong|xã|xa|quận|quan|huyện|huyen|thị xã|thi xa|thị trấn|thi tran|"
    r"thành phố|thanh pho|tx|tt|khu phố|khu pho|khu đô thị|khu do thi|tổ dân phố|to dan pho|"
    r"tổ|to|thôn|thon|xóm|xom|ấp|ap|khu|kp)"
)
_UNIT_NAME = (
    r"(?:\d{1,2}\b|[^\W\d_]+(?: [^\W\d_]+){0,3}(?=\s*[,;)\n]|\s*$|\.(?:\s|$))"
    rf"|{_CAP}(?: {_CAP}){{0,3}})"
)
_UNIT = (
    rf"(?:(?<![\w]){_UNIT_KW}\.?\s*{_UNIT_NAME}"
    rf"|(?<![\w])(?:[PQpq]\.\s?|[PQ](?=\d))(?:\d{{1,2}}\b|{_CAP}(?: {_CAP}){{0,2}}))"
)
_STREET_KW = r"(?i:đường|duong|phố|pho|ngõ|ngo|ngách|ngach|hẻm|hem|đại lộ|dai lo)"
_NUM = r"(?:(?i:số|so|no\.?|sn)\.?\s*)?\d{1,4}[A-Za-z]?(?:[/-]\d{1,4}[A-Za-z]?){0,3}"
_STREET_NAME = (
    rf"(?:(?:{_CAP}|\d+)(?: (?:{_CAP}|\d+)){{0,5}}"
    rf"|[^\W\d_]+(?: [^\W\d_]+){{0,5}}(?=\s*,\s*(?:{_UNIT_KW}|{_PROV_STRICT})))"
)
_RE_ANCHOR = re.compile(
    rf"(?<![\w/.-])(?P<num>{_NUM})\s+(?:(?P<kw>{_STREET_KW})\s+)?(?P<name>{_STREET_NAME})"
    rf"|(?<![\w])(?P<kw2>{_STREET_KW})\s+(?P<name2>{_STREET_NAME})"
    r"|(?<![\w])(?P<kw3>(?i:tổ|to|khu phố|khu pho|kp|thôn|thon|xóm|xom|ấp|ap)\s+\d{1,3}\b)"
)
_RE_PART_SEP = re.compile(r"\s*[,;]\s*|\s+-\s+|\s+")
_RE_UNIT = re.compile(_UNIT)
_RE_PROV = re.compile(_PROV_STRICT)
_RE_BARE = re.compile(rf"(?:{_CAP}|\d{{1,2}}\b)(?: (?:{_CAP})){{0,3}}")


def address_spans(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    pos = 0
    while pos < len(text):
        m = _RE_ANCHOR.search(text, pos)
        if m is None:
            break
        has_kw = (m.group("kw") or m.group("kw2")) is not None
        has_num = m.group("num") is not None
        end = m.end()
        good_end: int | None = None
        p = end
        parts = 0
        while parts < 7:
            sep = _RE_PART_SEP.match(text, p)
            if sep is None:
                break
            q = sep.end()
            comma = "," in sep.group() or ";" in sep.group() or "-" in sep.group()
            u = _RE_UNIT.match(text, q) or _RE_PROV.match(text, q)
            if u is not None and u.end() > q:
                good_end = p = u.end()
                parts += 1
                continue
            if comma:
                b = _RE_BARE.match(text, q)
                if b is not None and b.end() > q:
                    p = b.end()
                    parts += 1
                    continue
            break
        if good_end is not None:
            out.append((m.start(), good_end))
            pos = good_end
        elif has_kw and has_num:
            out.append((m.start(), end))
            pos = end
        else:
            pos = m.start() + 1
    return out


# ---------------------------------------------------------------------------- amounts
_NUMTOK = r"(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_SCALE = r"(?i:tỷ|tỉ|ty|triệu|trieu|tr|nghìn|nghin|ngàn|ngan)"
_CUR = r"(?i:vnd|vnđ|vn đ|đồng|dong|đ|₫|usd|đô|do la)"
_RE_AMT_SCALE = re.compile(
    rf"(?<![\w.,]){_NUMTOK}\s{{0,2}}{_SCALE}(?!\w)"
    rf"(?:\s{{0,2}}(?i:rưỡi|ruoi))?"
    rf"(?:\s{{0,2}}{_NUMTOK}\s{{0,2}}{_SCALE}(?!\w))*"
    rf"(?:\s{{0,2}}{_CUR}(?!\w))?"
)
_RE_AMT_K = re.compile(rf"(?<![\w.,]){_NUMTOK}(?i:k)(?!\w)")
_RE_AMT_CUR_AFTER = re.compile(rf"(?<![\w.,]){_NUMTOK}\s{{0,2}}{_CUR}(?!\w)")
_RE_AMT_CUR_BEFORE = re.compile(rf"(?<![\w])(?i:vnd|vnđ|usd|₫|\$)\s?{_NUMTOK}(?![\w.,]?\d)")
_RE_AMT_FLOAT = re.compile(r"(?<![\w.,])\d{6,}\.\d{1,2}(?!\d)")
_RE_AMT_BARE = re.compile(r"(?<![\w.,+-])\d{7,19}(?![\w])")
# A key that names a money value, directly before the number: ``"total_assets": 1250000000``.
_RE_AMT_KEY = re.compile(
    r"(?:amount|amt|tien|gia tri|gia|phi|fee|balance|so du|limit|han muc|total|tong|value|"
    r"price|principal|von|income|salary|luong|revenue|doanh thu|profit|loi nhuan|asset|debt|"
    r"du no|outstanding|item_?\d+|collateral|tai san|loan|vay|capital|equity|turnover)"
    r"[\w ]{0,15}[\"']?\s*[:=]\s*[\"']?$"
)
_RE_ID_LABEL = re.compile(
    r"(stk|tk\b|tai khoan|account|acct|a/c|cccd|cmnd|can cuoc|so dinh danh|mst|ma so thue|"
    r"tax|the\b|card|iban|swift|phone|sdt|dt\b|so dien thoai)"
)


_RE_NUM_AT = re.compile(_NUMTOK)
_RE_GROUPS_BEFORE = re.compile(r"(?:\d{1,6}[ \t-]){1,6}$")
_RE_THOUSANDS_SHAPE = re.compile(r"\d{1,3}(?:([., ])\d{3})(?:\1\d{3})*(?:[.,]\d{1,2})?")


def _luhn(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def id_shaped(text: str, start: int, run: str) -> bool:
    """Is the digit run ``run`` (at ``start``) an identifier rather than an amount, although a
    currency word follows it? "đồng" is also a word ("đồng ý", "đồng thời"): a CCCD, phone or
    account followed by it must not be claimed as an amount. Leading 0 (CCCD, phone), a label
    such as CCCD / STK / SĐT before it, a Luhn card number, or digit groups that are not a
    thousands format mean an identifier."""
    digits = re.sub(r"\D", "", run)
    if len(digits) < 8:
        return False
    if digits[0] == "0":
        return True
    label = bool(_RE_ID_LABEL.search(_fold_window(text, start).split("\n")[-1][-24:]))
    shaped = _RE_THOUSANDS_SHAPE.fullmatch(run.strip())
    if shaped:
        return label and shaped.group(1) == " "  # "CMND 123 456 789 đồng thời"
    if any(not c.isdigit() for c in run.strip()):
        return True  # "1903 4567 8901 23 đồng": grouped like an account, not like money
    if digits.endswith("000"):
        return False
    return label or _luhn(digits)


def _guarded(text: str, s: int, e: int) -> tuple[int, int] | None:
    """The amount span, extended over space-grouped thousands before it ("1 500 000 VND"), or
    None when the number is an identifier (see ``id_shaped``)."""
    num = _RE_NUM_AT.match(text, s)
    if num is None:
        return s, e
    before = None
    if num.group().isdigit():  # "234 đồng" may be the tail of "079 203 001 234"
        before = _RE_GROUPS_BEFORE.search(text, max(0, s - 48), s)
    if before is not None and before.end() == s:
        run = text[before.start() : num.end()]
        if id_shaped(text, before.start(), run):
            return None
        if _RE_THOUSANDS_SHAPE.fullmatch(run):
            return before.start(), e
        return s, e
    if id_shaped(text, s, num.group()):
        return None
    return s, e


def amount_spans(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for rx in (_RE_AMT_SCALE, _RE_AMT_K, _RE_AMT_CUR_AFTER):
        for m in rx.finditer(text):
            span = _guarded(text, m.start(), m.end())
            if span is not None:
                out.append(span)
    for rx in (_RE_AMT_CUR_BEFORE, _RE_AMT_FLOAT):
        for m in rx.finditer(text):
            out.append((m.start(), m.end()))
    for m in _RE_AMT_BARE.finditer(text):
        run = m.group()
        window = _fold_window(text, m.start())
        if _RE_ID_LABEL.search(window.split("\n")[-1][-20:]):
            continue
        keyed = bool(_RE_AMT_KEY.search(fold(text[max(0, m.start() - 40) : m.start()]).lower()))
        zeros = len(run) - len(run.rstrip("0"))
        if (keyed and not _RE_ID_LABEL.search(window)) or (
            zeros >= 6 and run[0] != "0" and not _RE_ID_LABEL.search(window)
        ):
            out.append((m.start(), m.end()))
    return out


def _fold_window(text: str, start: int) -> str:
    w = fold(text[max(0, start - 40) : start]).lower()
    # a digit between a word and the run means the word belongs to another number
    last = max((i for i, c in enumerate(w) if c.isdigit()), default=-1)
    return w[last + 1 :]
