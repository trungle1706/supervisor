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

import re
import unicodedata

from supervisor.data import wordlists as W

__all__ = ["amount_spans", "address_spans", "person_spans"]


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
    "Liêu", "Trình", "Âu", "Nghiêm", "Vương", "Lê", "Giang",
)  # fmt: skip
MIDDLE_EXTRA: tuple[str, ...] = (
    "Bích", "Hồng", "Tuyết", "Diệu", "Thúy", "Xuân", "Hải", "Tiến", "Thái", "Ngọc", "Lan",
    "Yến", "Nhi", "Đình", "Hoàng", "Trọng", "Thùy", "Như", "Tú", "Quốc", "Hoài", "Thế",
    "Trung", "Đăng", "Nhật", "Bá", "Chí", "Hiền", "Hạ", "Lệ", "Cẩm", "Tâm", "Vĩnh",
)  # fmt: skip
# "Nhật" and "Vĩnh" would break the held-out disjointness: removed below.
_HELD_BLOCK = frozenset(
    _k(w)
    for w in (
        "Duy", "Khắc", "Nhật", "Diễm", "Tường", "Bách", "Cảnh", "Duyên", "Hậu", "Huệ", "Khôi",
        "Lâm", "Mẫn", "Nhàn", "Nghiêu", "Rạng", "Sinh", "Tấn", "Thịnh", "Triều", "Tuyền", "Út",
        "Vĩnh", "Xuyến", "Thạch", "Quách", "Tống", "Lữ", "Kiều",
    )
)  # fmt: skip
GIVEN_EXTRA: tuple[str, ...] = (
    "Thử", "Tâm", "Tùng", "Đạt", "Hiếu", "Nghĩa", "Kiên", "Lộc", "Thuận", "Uyên", "Vân",
    "Yến", "Bích", "Châu", "Diễn", "Giao", "Khánh", "Liên", "Nguyên", "Sương", "Hiền",
    "Hoài", "Hưng", "Hiệp", "Hòa", "Trâm", "Trinh", "Trúc", "Tuệ", "Phước", "Phú", "Quốc",
    "Quý", "Quyết", "Sang", "Tân", "Thiện", "Thọ", "Thông", "Thương", "Tiên", "Tín", "Trí",
    "Trường", "Vinh", "Vương", "Diệp", "Đan", "Đào", "Điệp", "Đông", "Giàu", "Hân", "Hiển",
    "Hoan", "Huân", "Kha", "Khải", "Lực", "Mạnh", "Nga", "Nghi", "Nhân", "Như", "Phát",
    "Phi", "Quỳnh", "Thắm", "Thanh", "Thành", "Thủy", "Tiến", "Trọng", "Tuyết", "Ánh",
    "Bảo", "Cúc", "Duyên_", "Hạ", "Hồng", "Huyền", "Lệ", "Loan", "Ly", "Ngọc", "Nhung",
    "Phượng", "Thơm", "Thư", "Thúy", "Xuân", "Tú", "Tuấn", "Hải", "Lan", "Minh", "Hoàng",
)  # fmt: skip


def _clean(words: tuple[str, ...]) -> set[str]:
    return {_k(w) for w in words if not w.endswith("_")} - _HELD_BLOCK


SURS = _clean(tuple(W.SURNAMES) + SURNAMES_EXTRA)
MIDS = _clean(tuple(W.MIDDLE_MALE + W.MIDDLE_FEMALE) + MIDDLE_EXTRA)
GIVENS = _clean(tuple(W.GIVEN_MALE + W.GIVEN_FEMALE) + GIVEN_EXTRA) | MIDS - {"van", "thi"}
NAME_LEXICON = SURS | MIDS | GIVENS

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
    k = _k(tok)
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
    r"(?i:đường|duong|phố|pho|ngõ|ngo|hẻm|hem|quận|quan|huyện|huyen|phường|phuong|xã|xa|"
    r"thành phố|thanh pho|tỉnh|tinh|tp\.?|đại lộ|dai lo|cầu|cau|chợ|cho|trường|truong)\s*$"
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
        if _cased(t.text):
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


def person_spans(text: str) -> tuple[list[tuple[int, int, str]], list[tuple[int, int, str]]]:
    """(plain, labelled) person spans as ``(start, end, why)``."""
    toks = _tokens(text)
    plain: list[tuple[int, int, str]] = []
    labelled: list[tuple[int, int, str]] = []

    def first_token_at(pos: int) -> int | None:
        for n in range(len(toks)):
            if toks[n].start >= pos:
                return n if toks[n].start - pos <= 3 else None
        return None

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
        if _STREET_BEFORE.search(text[: toks[n0].start]):
            continue
        words = [t.text for t in chain]
        if _place_like(words):
            continue
        if not strong:
            # "Anh Tuấn", "Chị Lan", "của Nguyễn Văn A": needs a name word from the lexicon.
            if not any(_in(w, NAME_LEXICON) for w in words):
                continue
            if _k(chain[0].text) == "nhanh":
                continue
            if len(chain) == 1 and m.group()[0].islower():
                continue  # "chuyen den anh Nam": a first name alone after a lower-case "anh"
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
            and not _STREET_BEFORE.search(text[: s.start])
            and not _place_like([t.text for t in toks[n : last + 1]])
        ):
            plain.append((s.start, toks[last].end, "plain"))
        n = last + 1
    return plain, labelled


def _plain_at(toks: list[_Tok], text: str, n: int) -> int | None:
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
        if not _chain_ok(text, prev, t) or _is_stop(t.text):
            break
        if cased and not _cased(t.text):
            break
        if not cased and not t.text.islower():
            break
        rest.append(t)
    mids = 0
    while mids < min(2, len(rest)) and _in(rest[mids].text, MIDS):
        mids += 1
    if not cased:  # lower case text: closed lexicon only, surname + middle + given at least
        if mids == 0:
            return None
        if mids < len(rest) and _in(rest[mids].text, GIVENS):
            return n + 1 + mids
        if mids == 2 and _in(rest[1].text, GIVENS):
            return n + 2
        return None
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
_STREET_KW = r"(?i:đường|duong|phố|pho|ngõ|ngo|ngách|ngach|hẻm|hem|kiệt|kiet|đại lộ|dai lo)"
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


def amount_spans(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for rx in (_RE_AMT_SCALE, _RE_AMT_K, _RE_AMT_CUR_AFTER, _RE_AMT_CUR_BEFORE, _RE_AMT_FLOAT):
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
