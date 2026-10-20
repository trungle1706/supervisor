"""Golden set generator for Vietnamese PII (WP24b). Seeded, stdlib only, synthetic values only.

Every item is built from segments, so the span offsets are exact by construction. The held-out
split uses its OWN name pools (``HELD_*``): given names and surnames that must never be added to
the masker lexicon (a test asserts the pools stay disjoint from ``vn_regex``'s lexicon). Dev items
use the ordinary pools.

Item keys: id, split, source, licence, labeller, tags, text, spans[{type,start,end,text}],
keep[{kind,start,end,text}]. ``keep`` = strings that are NOT personal data and must reach the
rules intact (amounts, dates, references); ``kind`` AMOUNT is also an entity when the capture
level asks for amount masking.
"""

from __future__ import annotations

import hashlib
import json
import random
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.data import wordlists as W
from supervisor.data.synthetic import luhn_check_digit

SEED = 20261020
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "eval" / "pii_vn"
LICENCE = "own (synthetic, MIT)"

ENTITY_TYPES = (
    "PERSON",
    "CCCD",
    "CMND",
    "PHONE",
    "EMAIL",
    "TAX_CODE",
    "BANK_ACCOUNT",
    "CARD_NUMBER",
    "ADDRESS",
)

# Name pools. DEV words may be in the masker lexicon; HELD words must not be.
DEV_SURNAMES = tuple(W.SURNAMES) + ("Trương", "Lương", "Phùng")
DEV_MIDDLE_M = tuple(W.MIDDLE_MALE) + ("Xuân", "Hải", "Tiến")
DEV_MIDDLE_F = tuple(W.MIDDLE_FEMALE) + ("Hồng", "Diệu", "Tuyết")
DEV_GIVEN = tuple(W.GIVEN_MALE + W.GIVEN_FEMALE) + (
    "Thử", "Tâm", "Tùng", "Đạt", "Hiếu", "Nghĩa", "Kiên", "Lộc", "Thuận", "Uyên",
    "Vân", "Yến", "Bích", "Châu", "Diễn", "Giao", "Khánh", "Liên", "Nguyên", "Sương",
)  # fmt: skip
HELD_SURNAMES = ("Thạch", "Quách", "Tống", "Lữ", "Kiều")
HELD_MIDDLE = ("Duy", "Anh", "Tuấn", "Khắc", "Nhật", "Diễm", "Tường")
HELD_GIVEN = (
    "Bách", "Cảnh", "Duyên", "Hậu", "Huệ", "Khôi", "Lâm", "Mẫn", "Nhàn", "Nghiêu",
    "Quang", "Rạng", "Sinh", "Tấn", "Thịnh", "Triều", "Tuyền", "Út", "Vĩnh", "Xuyến",
)  # fmt: skip
HELD_STREETS = ("Cao Thắng", "Pasteur", "Võ Thị Sáu", "Lạc Long Quân", "Hoàng Hoa Thám")
HELD_WARDS = ("Phường Cầu Ông Lãnh", "Phường Thảo Điền", "Phường Nghĩa Tân", "Xã Tân Hiệp")
DEV_STREETS = tuple(W.STREETS) + ("Nguyễn Huệ", "Lê Lợi", "Trần Hưng Đạo", "Hai Bà Trưng")
DEV_WARDS = tuple(W.WARDS) + ("Phường Bến Nghé", "Phường 12", "Phường Dịch Vọng")
DISTRICTS = (
    "Quận 1", "Quận 3", "Quận Bình Thạnh", "Quận Cầu Giấy", "Quận Hải Châu", "Huyện Củ Chi",
    "Thành phố Thủ Đức", "Quận Ba Đình", "Thị xã Dĩ An",
)  # fmt: skip
CITIES = ("TP.HCM", "Hà Nội", "Đà Nẵng", "Cần Thơ", "Hải Phòng", "TP Hồ Chí Minh", "Bình Dương")


def fold(text: str) -> str:
    out = unicodedata.normalize("NFD", text)
    out = "".join(c for c in out if unicodedata.category(c) != "Mn")
    return out.replace("đ", "d").replace("Đ", "D")


_TELEX_TONE = {
    "á": "s", "à": "f", "ả": "r", "ã": "x", "ạ": "j",
}  # fmt: skip


def telex_word(word: str) -> str:
    """Rough telex typing of one Vietnamese word, tone letter at the end (Thử -> Thuwr)."""
    out = []
    tone = ""
    for ch in unicodedata.normalize("NFD", word):
        cat = unicodedata.category(ch)
        if cat == "Mn":
            tone = {"́": "s", "̀": "f", "̉": "r", "̃": "x", "̣": "j"}.get(ch, "") or tone
            if ch == "̆":
                out.append("w")
            elif ch == "̛":
                out.append("w")
            elif ch == "̂":
                out.append(out[-1] if out else "")
            continue
        if ch in "đĐ":
            out.append("dd" if ch == "đ" else "DD")
            continue
        out.append(ch)
    return "".join(out) + tone


def strip_some(word: str, rng: random.Random) -> str:
    return fold(word) if rng.random() < 0.5 else word


@dataclass
class Doc:
    parts: list[str] = field(default_factory=list)
    spans: list[dict[str, Any]] = field(default_factory=list)
    keep: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pos(self) -> int:
        return sum(len(p) for p in self.parts)

    def t(self, s: str) -> Doc:
        self.parts.append(s)
        return self

    def e(self, type_: str, s: str) -> Doc:
        self.spans.append({"type": type_, "start": self.pos, "end": self.pos + len(s), "text": s})
        self.parts.append(s)
        return self

    def k(self, kind: str, s: str) -> Doc:
        self.keep.append({"kind": kind, "start": self.pos, "end": self.pos + len(s), "text": s})
        self.parts.append(s)
        return self

    def text(self) -> str:
        return "".join(self.parts)


class Gen:
    def __init__(self, seed: int, held: bool) -> None:
        self.rng = random.Random(seed)  # noqa: S311 - synthetic data
        self.held = held

    # -- primitives --------------------------------------------------------
    def digits(self, n: int) -> str:
        return "".join(self.rng.choice("0123456789") for _ in range(n))

    def name_parts(self) -> list[str]:
        r = self.rng
        if self.held:
            sur = r.choice(HELD_SURNAMES + tuple(W.SURNAMES[:6]))
            mid = r.choice(("Thị", "Văn") + HELD_MIDDLE)
            given = r.choice(HELD_GIVEN)
            return [sur, mid, given] if r.random() < 0.8 else [sur, given]
        female = r.random() < 0.5
        mid = r.choice(DEV_MIDDLE_F if female else DEV_MIDDLE_M)
        given = r.choice(DEV_GIVEN)
        parts = [r.choice(DEV_SURNAMES), mid, given]
        if r.random() < 0.12:
            parts.insert(2, r.choice(DEV_MIDDLE_F + DEV_MIDDLE_M))
        return parts

    def person(self) -> tuple[str, str, list[str]]:
        """(surface text, form tag, tags). Forms: title, UPPER, nodiac, UPPER nodiac, lower
        nodiac, partial diacritics, telex."""
        parts = self.name_parts()
        form = self.rng.choice(
            ("title", "title", "upper", "upper", "nodiac", "upper_nodiac", "lower_nodiac",
             "partial", "telex")
        )  # fmt: skip
        full = " ".join(parts)
        if form == "title":
            return full, form, []
        if form == "upper":
            return full.upper(), form, ["uppercase"]
        if form == "nodiac":
            return fold(full), form, ["no-diacritics"]
        if form == "upper_nodiac":
            return fold(full).upper(), form, ["uppercase", "no-diacritics"]
        if form == "lower_nodiac":
            return fold(full).lower(), form, ["lowercase", "no-diacritics"]
        if form == "partial":
            return " ".join(strip_some(p, self.rng) for p in parts), form, ["partial-diacritics"]
        return " ".join(telex_word(p).capitalize() for p in parts), form, ["telex"]

    def cccd(self) -> str:
        pc = self.rng.choice(list(W.PROVINCES))
        year = self.rng.randrange(1955, 2007)
        g = (0 if year < 2000 else 2) + self.rng.randrange(2)
        return f"{pc}{g}{year % 100:02d}{self.digits(6)}"

    def cccd_surface(self) -> tuple[str, list[str]]:
        c = self.cccd()
        f = self.rng.choice(("plain", "plain", "3x4", "dash", "6x2"))
        if f == "3x4":
            return " ".join(c[i : i + 3] for i in range(0, 12, 3)), ["grouped"]
        if f == "dash":
            return "-".join(c[i : i + 4] for i in range(0, 12, 4)), ["grouped"]
        if f == "6x2":
            return f"{c[:6]} {c[6:]}", ["grouped"]
        return c, []

    def phone(self) -> tuple[str, list[str]]:
        prefix = self.rng.choice(W.MOBILE_PREFIXES)
        rest = self.digits(7)
        f = self.rng.choice(("plain", "plain", "space", "dot", "intl", "intl_plain", "84"))
        if f == "space":
            return f"{prefix} {rest[:3]} {rest[3:]}", ["grouped"]
        if f == "dot":
            return f"{prefix}.{rest[:3]}.{rest[3:]}", ["grouped"]
        if f == "intl":
            return f"+84 {prefix[1:]} {rest[:3]} {rest[3:]}", ["intl"]
        if f == "intl_plain":
            return f"+84{prefix[1:]}{rest}", ["intl"]
        if f == "84":
            return f"84{prefix[1:]}{rest}", ["intl"]
        return f"{prefix}{rest}", []

    def email(self, parts: list[str]) -> tuple[str, list[str]]:
        p = [fold(x).lower() for x in parts]
        local = self.rng.choice(
            (
                "".join(p),
                f"{p[-1]}.{p[0]}",
                ".".join(p),
                f"{p[-1]}{p[0][0]}{p[1][0]}{self.rng.randrange(10, 99)}",
                f"{p[0]}_{p[-1]}{self.rng.randrange(1, 99)}",
            )
        )
        host = self.rng.choice(("example.invalid", "mail.example.invalid", "bank-test.invalid"))
        em = f"{local}@{host}"
        if self.rng.random() < 0.25:
            return em.upper(), ["uppercase"]
        return em, ["name-in-email"]

    def tax(self) -> str:
        from supervisor.data.synthetic import _MST_WEIGHTS

        while True:
            base = self.digits(9)
            total = sum(int(d) * w for d, w in zip(base, _MST_WEIGHTS, strict=True))
            check = 10 - (total % 11)
            if 0 <= check <= 9:
                return f"{base}{check}" + (f"-{self.digits(3)}" if self.rng.random() < 0.2 else "")

    def account(self) -> tuple[str, list[str]]:
        n = self.rng.choice((10, 12, 13, 14, 15, 16))
        a = self.digits(n)
        a = str(self.rng.randrange(1, 10)) + a[1:]
        if self.rng.random() < 0.3 and n >= 12:
            return " ".join(a[i : i + 4] for i in range(0, n, 4)), ["grouped"]
        return a, []

    def card(self) -> str:
        prefix = self.rng.choice(("9704", "4", "5"))
        partial = prefix + self.digits(15 - len(prefix))
        num = partial + luhn_check_digit(partial)
        return " ".join(num[i : i + 4] for i in range(0, 16, 4)) if self.rng.random() < 0.5 else num

    def address(self) -> tuple[str, list[str]]:
        r = self.rng
        streets = HELD_STREETS if self.held else DEV_STREETS
        wards = HELD_WARDS if self.held else DEV_WARDS
        no = f"{r.randrange(1, 400)}" + (f"/{r.randrange(1, 60)}" if r.random() < 0.3 else "")
        form = r.choice(("so", "bare", "duong", "short", "ngo", "to"))
        street, ward = r.choice(streets), r.choice(wards)
        dist, city = r.choice(DISTRICTS), r.choice(CITIES)
        if form == "so":
            a = f"Số {no} {street}, {ward}, {dist}, {city}"
        elif form == "bare":
            a = f"{no} {street}, {ward}, {dist}, {city}"
        elif form == "duong":
            a = f"{no} đường {street}, {ward}, {dist}, {city}"
        elif form == "short":
            a = f"{no} {street}, P.{r.randrange(1, 15)}, Q.{r.randrange(1, 12)}, {city}"
        elif form == "ngo":
            a = f"Số {r.randrange(1, 90)} ngõ {r.randrange(1, 300)} {street}, {dist}, {city}"
        else:
            a = f"Tổ {r.randrange(1, 30)}, Khu phố {r.randrange(1, 9)}, {ward}, {dist}, {city}"
        tags = ["address"]
        v = r.choice(("keep", "keep", "upper", "nodiac", "upper_nodiac"))
        if v == "upper":
            return a.upper(), tags + ["uppercase"]
        if v == "nodiac":
            return fold(a), tags + ["no-diacritics"]
        if v == "upper_nodiac":
            return fold(a).upper(), tags + ["uppercase", "no-diacritics"]
        return a, tags

    def amount(self) -> str:
        r = self.rng
        n = r.choice((12, 50, 150, 250, 500, 800, 1200, 1500, 2300, 9100)) * 1_000_000
        f = r.choice(("dots_vnd", "dots_vnd", "commas", "ty", "ty_dong", "trieu", "tr", "vnd_pre",
                      "d", "usd", "ngan"))  # fmt: skip
        if f == "dots_vnd":
            return f"{n:,}".replace(",", ".") + " VND"
        if f == "commas":
            return f"VND {n:,}"
        if f == "ty":
            return f"{n / 1e9:.1f}".replace(".", ",") + " tỷ"
        if f == "ty_dong":
            return f"{n / 1e9:.1f} tỷ đồng"
        if f == "trieu":
            return f"{n // 1_000_000} triệu"
        if f == "tr":
            return f"{n // 1_000_000}tr"
        if f == "vnd_pre":
            return f"{n:,}".replace(",", ".") + "đ"
        if f == "d":
            return f"{n:,}".replace(",", ".") + " đồng"
        if f == "usd":
            return f"USD {n // 25_000:,}"
        return f"{n // 1000:,}".replace(",", ".") + " nghìn đồng"

    def date(self) -> str:
        r = self.rng
        d, m, y = r.randrange(1, 29), r.randrange(1, 13), r.randrange(2022, 2027)
        return f"{d:02d}/{m:02d}/{y}"

    def ref(self) -> str:
        return f"HD-{self.rng.randrange(2023, 2027)}-{self.digits(5)}"


TITLES = ("Ông", "Bà", "Anh", "Chị", "Khách hàng", "Người nhận", "Họ tên")
TITLES_ASCII = ("Ong", "Ba", "Anh", "Chi", "Khach hang", "Nguoi nhan", "Ho ten")


def build_item(g: Gen, template: int) -> Doc:
    d = Doc()
    r = g.rng
    name, _form, ntags = g.person()
    parts = name.split()
    nodiac = "no-diacritics" in ntags
    title = (TITLES_ASCII if nodiac else TITLES)[r.randrange(len(TITLES))]
    if template == 0:  # labelled person + CCCD + loan amount
        cc, ct = g.cccd_surface()
        d.t(f"{title} ").e("PERSON", name).t(", CCCD ").e("CCCD", cc)
        d.t(" đề nghị vay ").k("AMOUNT", g.amount()).t(" kỳ hạn ").k(
            "TERM", f"{r.choice((12, 24, 36, 60))} tháng"
        )
        d.t(f", hợp đồng {g.ref()}.")
    elif template == 1:  # JSON args
        em, _ = g.email(parts)
        ph, _ = g.phone()
        d.t('{"full_name": "').e("PERSON", name).t('", "phone": "').e("PHONE", ph)
        d.t('", "email": "').e("EMAIL", em).t('", "limit_minor": ').k(
            "AMOUNT", str(r.randrange(1, 99) * 100_000_000)
        ).t("}")
    elif template == 2:  # transfer: amount next to account number
        acct, _ = g.account()
        d.t("Chuyển ").k("AMOUNT", g.amount()).t(" đến STK ").e("BANK_ACCOUNT", acct)
        d.t(" của ").e("PERSON", name).t(" ngày ").k("DATE", g.date()).t(".")
    elif template == 3:  # address
        addr, _ = g.address()
        d.t("Địa chỉ thường trú: ").e("ADDRESS", addr).t(". Người liên hệ: ").e("PERSON", name).t(
            "."
        )
    elif template == 4:  # phone + email, name in email
        ph, _ = g.phone()
        em, _ = g.email(parts)
        d.t("Liên hệ SĐT ").e("PHONE", ph).t(" hoặc ").e("EMAIL", em).t(f" (mã hồ sơ {g.ref()}).")
    elif template == 5:  # tax + card + account
        d.t("MST ").e("TAX_CODE", g.tax()).t(", thẻ ").e("CARD_NUMBER", g.card()).t(", tài khoản ")
        d.e("BANK_ACCOUNT", g.account()[0]).t(", số dư ").k("AMOUNT", g.amount()).t(".")
    elif template == 6:  # CMND old id
        d.t(f"{title} ").e("PERSON", name).t(", CMND ").e(
            "CMND", f"{r.choice('0123')}{g.digits(8)}"
        )
        d.t(", cấp ngày ").k("DATE", g.date()).t(".")
    elif template == 7:  # unlabelled name in prose
        d.t("Hợp đồng được ký bởi ").e("PERSON", name).t(" tại chi nhánh vào ").k("DATE", g.date())
        d.t(", giá trị ").k("AMOUNT", g.amount()).t(".")
    elif template == 8:  # JSON with address, number key
        addr, _ = g.address()
        d.t('{"customer": {"name": "').e("PERSON", name).t('", "address": "').e("ADDRESS", addr)
        d.t('"}, "outstanding": ').k("AMOUNT", f"{r.randrange(1, 90) * 100_000_000}.0").t("}")
    elif template == 9:  # tool result row
        cc, _ = g.cccd_surface()
        ph, _ = g.phone()
        d.t("| ").e("PERSON", name).t(" | ").e("CCCD", cc).t(" | ").e("PHONE", ph).t(" | ")
        d.k("AMOUNT", g.amount()).t(" |")
    else:  # whole upper-case sentence variant (OCR / memo header)
        addr, _ = g.address()
        d.t("KHÁCH HÀNG: ").e("PERSON", name.upper()).t(" - ĐỊA CHỈ: ").e("ADDRESS", addr.upper())
        d.t(" - SỐ TIỀN: ").k("AMOUNT", g.amount().upper())
    return d


N_TEMPLATES = 11


def generate(n_dev: int = 440, n_held: int = 220, seed: int = SEED) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for split, n, off in (("dev", n_dev, 0), ("heldout", n_held, 1)):
        g = Gen(seed + off, held=split == "heldout")
        for i in range(n):
            d = build_item(g, i % N_TEMPLATES)
            items.append(
                {
                    "id": f"G-{split[:1].upper()}{i + 1:04d}",
                    "split": split,
                    "source": f"generator seed={seed + off} template={i % N_TEMPLATES}",
                    "licence": LICENCE,
                    "labeller": "synthetic",
                    "tags": sorted({s["type"].lower() for s in d.spans}),
                    "text": d.text(),
                    "spans": d.spans,
                    "keep": d.keep,
                }
            )
    return items


# ---------------------------------------------------------------- hand-written hard cases
# Each: (text, [(type, substring)], [(kind, substring)], tags, split). A substring must occur once
# (or use "substring@N" for the N-th occurrence, 0-based).
HardCase = tuple[str, list[tuple[str, str]], list[tuple[str, str]], list[str], str]

HARD: list[HardCase] = [
    # upper-case names
    (
        '{"full_name": "NGUYỄN VĂN THỬ"}',
        [("PERSON", "NGUYỄN VĂN THỬ")],
        [],
        ["uppercase", "g7"],
        "dev",
    ),
    (
        "Giám đốc: TRẦN THỊ BÍCH NGỌC ký tên.",
        [("PERSON", "TRẦN THỊ BÍCH NGỌC")],
        [],
        ["uppercase"],
        "dev",
    ),
    ("ĐẠI DIỆN PHÁP LUẬT: LÊ HOÀNG NAM", [("PERSON", "LÊ HOÀNG NAM")], [], ["uppercase"], "dev"),
    (
        "Chủ thẻ PHAM VAN HUNG vui long xac nhan.",
        [("PERSON", "PHAM VAN HUNG")],
        [],
        ["uppercase", "no-diacritics"],
        "dev",
    ),
    ("Ông Nguyễn Văn Thử đã đến chi nhánh.", [("PERSON", "Nguyễn Văn Thử")], [], ["g7"], "dev"),
    (
        "Ong Nguyen Van Thu den chi nhanh",
        [("PERSON", "Nguyen Van Thu")],
        [],
        ["no-diacritics", "g7"],
        "dev",
    ),
    ("Bà Đặng Thị Hồng Nhung vay thế chấp.", [("PERSON", "Đặng Thị Hồng Nhung")], [], [], "dev"),
    ("Anh Tuấn gọi lúc 9h sáng.", [("PERSON", "Tuấn")], [], ["single-name"], "dev"),
    ("Chị Lan xác nhận giao dịch.", [("PERSON", "Lan")], [], ["single-name"], "dev"),
    (
        "Khach hang: nguyen thi mai hoa",
        [("PERSON", "nguyen thi mai hoa")],
        [],
        ["lowercase", "no-diacritics"],
        "dev",
    ),
    (
        "Nguyeenx Vawn Thuwr vay 500 trieu",
        [("PERSON", "Nguyeenx Vawn Thuwr")],
        [("AMOUNT", "500 trieu")],
        ["telex"],
        "dev",
    ),
    (
        "Hoang Thi Thanh Thuy chuyen khoan",
        [("PERSON", "Hoang Thi Thanh Thuy")],
        [],
        ["no-diacritics"],
        "dev",
    ),
    ("Người thụ hưởng: LƯƠNG ĐÌNH KHÔI", [("PERSON", "LƯƠNG ĐÌNH KHÔI")], [], ["uppercase"], "dev"),
    ("Họ và tên: Tống Khắc Triều", [("PERSON", "Tống Khắc Triều")], [], [], "heldout"),
    ("Giám đốc: QUÁCH DUY HẬU", [("PERSON", "QUÁCH DUY HẬU")], [], ["uppercase"], "heldout"),
    ("Ông Thạch Tường Vĩnh ký hợp đồng", [("PERSON", "Thạch Tường Vĩnh")], [], [], "heldout"),
    ("Bà Kiều Diễm Xuyến nhận tiền", [("PERSON", "Kiều Diễm Xuyến")], [], [], "heldout"),
    ("Ong Lu Nhat Thinh dang ky", [("PERSON", "Lu Nhat Thinh")], [], ["no-diacritics"], "heldout"),
    # titles with companies (company name must NOT be masked as a person)
    (
        "Công ty TNHH Thương mại Sao Mai, người đại diện: Ông Trần Văn Bách",
        [("PERSON", "Trần Văn Bách")],
        [],
        ["company"],
        "dev",
    ),
    (
        "Cong ty TNHH Hoang Long do ba Pham Thi Lien dai dien",
        [("PERSON", "Pham Thi Lien")],
        [],
        ["company", "no-diacritics"],
        "dev",
    ),
    # addresses
    (
        "Địa chỉ: Số 12 Nguyễn Huệ, Phường Bến Nghé, Quận 1, TP.HCM",
        [("ADDRESS", "Số 12 Nguyễn Huệ, Phường Bến Nghé, Quận 1, TP.HCM")],
        [],
        ["address"],
        "dev",
    ),
    (
        "DIA CHI: SO 45 LE LOI, PHUONG 3, QUAN 5, TP HO CHI MINH",
        [("ADDRESS", "SO 45 LE LOI, PHUONG 3, QUAN 5, TP HO CHI MINH")],
        [],
        ["address", "uppercase", "no-diacritics"],
        "dev",
    ),
    (
        "ĐỊA CHỈ: 18/2 ĐƯỜNG TRẦN HƯNG ĐẠO, PHƯỜNG CỬA NAM, QUẬN HOÀN KIẾM, HÀ NỘI",
        [("ADDRESS", "18/2 ĐƯỜNG TRẦN HƯNG ĐẠO, PHƯỜNG CỬA NAM, QUẬN HOÀN KIẾM, HÀ NỘI")],
        [],
        ["address", "uppercase", "g7"],
        "dev",
    ),
    (
        "ở 99 Hai Bà Trưng, P.6, Q.3, TPHCM nhé",
        [("ADDRESS", "99 Hai Bà Trưng, P.6, Q.3, TPHCM")],
        [],
        ["address"],
        "dev",
    ),
    (
        "Thường trú tại số 7 ngõ 120 Trần Duy Hưng, Cầu Giấy, Hà Nội",
        [("ADDRESS", "số 7 ngõ 120 Trần Duy Hưng, Cầu Giấy, Hà Nội")],
        [],
        ["address"],
        "dev",
    ),
    (
        "Tổ 4, Khu phố 2, Phường Tân Phong, Quận 7, TP.HCM",
        [("ADDRESS", "Tổ 4, Khu phố 2, Phường Tân Phong, Quận 7, TP.HCM")],
        [],
        ["address"],
        "dev",
    ),
    (
        "so 5 nguyen trai, phuong thuong dinh, quan thanh xuan, ha noi",
        [("ADDRESS", "so 5 nguyen trai, phuong thuong dinh, quan thanh xuan, ha noi")],
        [],
        ["address", "lowercase", "no-diacritics"],
        "dev",
    ),
    (
        "Nhà ở 221B đường Võ Thị Sáu, Phường Võ Thị Sáu, Quận 3, TP.HCM",
        [("ADDRESS", "221B đường Võ Thị Sáu, Phường Võ Thị Sáu, Quận 3, TP.HCM")],
        [],
        ["address", "name-in-address"],
        "heldout",
    ),
    (
        "ĐỊA CHỈ: 64 PASTEUR, PHƯỜNG BẾN NGHÉ, QUẬN 1, TP.HCM",
        [("ADDRESS", "64 PASTEUR, PHƯỜNG BẾN NGHÉ, QUẬN 1, TP.HCM")],
        [],
        ["address", "uppercase"],
        "heldout",
    ),
    (
        "Giao hàng tới 15 Lạc Long Quân, Phường 10, Quận 11, TP.HCM",
        [("ADDRESS", "15 Lạc Long Quân, Phường 10, Quận 11, TP.HCM")],
        [],
        ["address"],
        "heldout",
    ),
    # amounts (must stay intact) and account numbers next to them
    (
        "Số dư 1.500.000.000 VND, STK 19034567890123",
        [("BANK_ACCOUNT", "19034567890123")],
        [("AMOUNT", "1.500.000.000 VND")],
        ["amount-next-to-account"],
        "dev",
    ),
    ("Hạn mức 1,5 tỷ đồng cho khách hàng", [], [("AMOUNT", "1,5 tỷ đồng")], ["amount"], "dev"),
    ("Khoản vay 2 tỷ rưỡi, lãi 8,5%/năm", [], [("AMOUNT", "2 tỷ rưỡi")], ["amount"], "dev"),
    (
        '{"item_27": 9100000000.0, "item_28": 1250000000.0}',
        [],
        [("AMOUNT", "9100000000.0"), ("AMOUNT", "1250000000.0")],
        ["amount", "g7"],
        "dev",
    ),
    (
        '{"total_assets": 12500000000, "revenue": 8700000000}',
        [],
        [("AMOUNT", "12500000000"), ("AMOUNT", "8700000000")],
        ["amount", "bare-digits"],
        "dev",
    ),
    (
        "Doanh thu 250.000.000.000 đồng, lợi nhuận 12.300.000.000đ",
        [],
        [("AMOUNT", "250.000.000.000 đồng"), ("AMOUNT", "12.300.000.000đ")],
        ["amount"],
        "dev",
    ),
    (
        "Chuyển 500tr cho Anh Hùng, STK 0123456789012",
        [("PERSON", "Hùng"), ("BANK_ACCOUNT", "0123456789012")],
        [("AMOUNT", "500tr")],
        ["amount-next-to-account"],
        "dev",
    ),
    (
        "Giải ngân 3.000.000.000 VND vào tài khoản 190 3456 7890 12",
        [("BANK_ACCOUNT", "190 3456 7890 12")],
        [("AMOUNT", "3.000.000.000 VND")],
        ["amount-next-to-account"],
        "dev",
    ),
    (
        "Loan 750,000,000 VND to account 9704220101010101",
        [("BANK_ACCOUNT", "9704220101010101")],
        [("AMOUNT", "750,000,000 VND")],
        ["amount-next-to-account", "en"],
        "dev",
    ),
    (
        "Tổng dư nợ 4,2 tỷ, ngày 15/10/2026, hợp đồng HD-2026-00123",
        [],
        [("AMOUNT", "4,2 tỷ"), ("DATE", "15/10/2026"), ("REF", "HD-2026-00123")],
        ["amount", "date"],
        "heldout",
    ),
    (
        '{"principal": 6400000000.0, "rate": 8.5}',
        [],
        [("AMOUNT", "6400000000.0")],
        ["amount", "g7"],
        "heldout",
    ),
    (
        "Giá trị tài sản đảm bảo 7.800.000.000 đ, STK 1234567890",
        [("BANK_ACCOUNT", "1234567890")],
        [("AMOUNT", "7.800.000.000 đ")],
        ["amount-next-to-account"],
        "heldout",
    ),
    # CCCD vs phone collisions
    (
        "CCCD 001203004567, SĐT 0912345678",
        [("CCCD", "001203004567"), ("PHONE", "0912345678")],
        [],
        ["cccd-phone"],
        "dev",
    ),
    ("Số 079203004567 là căn cước", [("CCCD", "079203004567")], [], ["cccd-phone"], "dev"),
    (
        "Gọi 84912345678 hoặc +84 912 345 678",
        [("PHONE", "84912345678"), ("PHONE", "+84 912 345 678")],
        [],
        ["cccd-phone", "intl"],
        "dev",
    ),
    (
        "CMND 024678123 và CCCD 034090123456",
        [("CMND", "024678123"), ("CCCD", "034090123456")],
        [],
        ["cccd-phone"],
        "dev",
    ),
    ("sdt0912345678", [("PHONE", "0912345678")], [], ["glued"], "dev"),
    ("CCCD: 092 303 004 567", [("CCCD", "092 303 004 567")], [], ["cccd-phone"], "heldout"),
    (
        "Hotline 1900 5588 98 (không phải số cá nhân)",
        [],
        [("HOTLINE", "1900 5588 98")],
        ["negative"],
        "dev",
    ),
    # emails with names
    (
        "Email: nguyen.van.thu@example.invalid",
        [("EMAIL", "nguyen.van.thu@example.invalid")],
        [],
        ["name-in-email"],
        "dev",
    ),
    (
        "EMAIL: TRANTHIBICHNGOC@EXAMPLE.INVALID",
        [("EMAIL", "TRANTHIBICHNGOC@EXAMPLE.INVALID")],
        [],
        ["name-in-email", "uppercase"],
        "dev",
    ),
    (
        "gửi tới lephamquynh_92@mail.example.invalid ạ",
        [("EMAIL", "lephamquynh_92@mail.example.invalid")],
        [],
        ["name-in-email"],
        "dev",
    ),
    (
        "Mail: quach.duy.hau@bank-test.invalid",
        [("EMAIL", "quach.duy.hau@bank-test.invalid")],
        [],
        ["name-in-email"],
        "heldout",
    ),
    # tax, card
    ("Mã số thuế 0100109106", [("TAX_CODE", "0100109106")], [], ["tax"], "dev"),
    (
        "Thẻ 4111 1111 1111 1111 hết hạn 12/28",
        [("CARD_NUMBER", "4111 1111 1111 1111")],
        [("EXPIRY", "12/28")],
        ["card"],
        "dev",
    ),
    # negatives: nothing to mask
    (
        "Chi nhánh Hà Nội mở cửa lúc 8h30, ngày 15/10/2026.",
        [],
        [("DATE", "15/10/2026")],
        ["negative"],
        "dev",
    ),
    ("Minh bạch thông tin và quản trị rủi ro tín dụng.", [], [], ["negative"], "dev"),
    (
        "Lãi suất 8,5%/năm, kỳ hạn 36 tháng, phí 0,5%.",
        [],
        [("TERM", "36 tháng")],
        ["negative"],
        "dev",
    ),
    ("Tổng cộng 12 hồ sơ, 3 hồ sơ chờ duyệt, 1 hồ sơ bị từ chối.", [], [], ["negative"], "dev"),
    ("Mai gửi hồ sơ, Cao Bằng chưa có số liệu.", [], [], ["negative"], "heldout"),
    (
        "Quy trình thẩm định 5 bước, thời gian xử lý 2 ngày làm việc.",
        [],
        [],
        ["negative"],
        "heldout",
    ),
]


def _find(text: str, sub: str, used: set[int]) -> tuple[int, int]:
    start = text.find(sub)
    while start in used:
        start = text.find(sub, start + 1)
    if start < 0:
        raise ValueError(f"substring {sub!r} not in {text!r}")
    used.add(start)
    return start, start + len(sub)


def hard_items() -> list[dict[str, Any]]:
    out = []
    for i, (text, spans, keep, tags, split) in enumerate(HARD):
        used: set[int] = set()
        sp = []
        for typ, sub in spans:
            s, e = _find(text, sub, used)
            sp.append({"type": typ, "start": s, "end": e, "text": sub})
        kp = []
        for kind, sub in keep:
            s, e = _find(text, sub, used)
            kp.append({"kind": kind, "start": s, "end": e, "text": sub})
        out.append(
            {
                "id": f"H-{split[:1].upper()}{i + 1:04d}",
                "split": split,
                "source": "hand-written hard case",
                "licence": LICENCE,
                "labeller": "expert rubric",
                "tags": sorted(set(tags)),
                "text": text,
                "spans": sp,
                "keep": kp,
            }
        )
    return out


def all_items() -> list[dict[str, Any]]:
    from supervisor.pii_eval.negatives import negatives

    return generate() + hard_items() + negatives()


def heldout_ablation_words() -> list[str]:
    """Held-out name pool words that are NOT in the generator word lists. The masker ships the
    full lexicon; the held-out split is scored with these words removed (``vn_text.ablate``)."""
    base = {fold(w).lower() for w in W.SURNAMES + W.MIDDLE_MALE + W.MIDDLE_FEMALE}
    base |= {fold(w).lower() for w in W.GIVEN_MALE + W.GIVEN_FEMALE}
    pool = HELD_SURNAMES + HELD_MIDDLE + HELD_GIVEN
    return sorted({w for w in pool if fold(w).lower() not in base})


def write(out_dir: Path = DATA_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    items = all_items()
    paths = []
    manifest: dict[str, Any] = {"seed": SEED, "licence": LICENCE, "splits": {}}
    for split in ("dev", "heldout"):
        rows = [it for it in items if it["split"] == split]
        p = out_dir / f"{split}.jsonl"
        body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
        p.write_text(body, encoding="utf-8")
        manifest["splits"][split] = {
            "n_items": len(rows),
            "n_spans": sum(len(r["spans"]) for r in rows),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
        paths.append(p)
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return paths


if __name__ == "__main__":
    for p in write():
        print(f"[OK] wrote {p}")  # noqa: T201 (CLI output)
