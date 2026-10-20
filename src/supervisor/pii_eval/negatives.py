"""Negative prose corpus (WP24b follow-up): Vietnamese and English banking sentences with NO
personal data. Anything the masker types in these items is a false mask.

Content: UPPER-case document headers (with and without diacritics), street and brand names that
look like person names, place names (`Hồ Chí Minh`, `Hà Nam`), product names, amounts, dates,
reference numbers, code and column names. Dev and held-out use different word pools; fixes are
guided by dev only. Amounts and dates are `keep` strings (must stay intact).
"""

from __future__ import annotations

import random
from typing import Any

from supervisor.pii_eval.generate import LICENCE, Doc

HEADERS_DEV = (
    "LÝ DO TỪ CHỐI", "ĐIỀU KHOẢN VÀ ĐIỀU KIỆN", "HỒ SƠ VAY VỐN", "DANH MỤC TÀI SẢN ĐẢM BẢO",
    "THÔNG TIN KHOẢN VAY", "BIÊN BẢN THẨM ĐỊNH", "PHƯƠNG ÁN TRẢ NỢ", "KẾT LUẬN CỦA CÁN BỘ TÍN DỤNG",
    "LY DO TU CHOI", "DIEU KHOAN VA DIEU KIEN", "HO SO VAY VON", "THONG TIN KHOAN VAY",
)  # fmt: skip
HEADERS_HELD = (
    "QUYẾT ĐỊNH PHÊ DUYỆT", "BÁO CÁO RỦI RO TÍN DỤNG", "DANH SÁCH HỒ SƠ CHỜ XỬ LÝ",
    "TỔNG HỢP DƯ NỢ", "CAM KẾT CỦA KHÁCH HÀNG", "NHẬT KÝ GIAO DỊCH", "LÃI SUẤT VÀ PHÍ",
    "GHI CHÚ THẨM ĐỊNH", "BAO CAO RUI RO TIN DUNG", "TONG HOP DU NO",
)  # fmt: skip
BRANDS_DEV = (
    "Võ Văn Kiệt Street", "Hoang Long Group", "Lê Lợi Plaza", "Trần Hưng Đạo Tower",
    "Nguyễn Huệ Walking Street", "Sao Mai Mobile", "Ho Chi Minh City", "Hồ Chí Minh City",
    "Phạm Ngọc Thạch Hospital", "Bách Khoa Center",
)  # fmt: skip
BRANDS_HELD = (
    "Phan Chu Trinh Street", "Lạc Hồng Group", "Bình Minh Mobile", "Hoa Sen Plaza",
    "Thăng Long Tower", "Đà Nẵng City Tour", "Lý Thường Kiệt Street", "Hà Nội Tower",
)  # fmt: skip
PLACES_DEV = (
    "Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Cần Thơ", "Hải Phòng", "Thừa Thiên Huế",
    "Bà Rịa - Vũng Tàu", "Ho Chi Minh", "Ha Noi", "Hà Nam", "Thái Bình", "Hà Giang",
)  # fmt: skip
PLACES_HELD = (
    "Thành phố Hồ Chí Minh", "Quảng Ninh", "Bắc Giang", "Hưng Yên", "Nam Định", "Lâm Đồng",
    "Thanh Hóa", "Ninh Bình", "Thua Thien Hue", "TP Ho Chi Minh",
)  # fmt: skip
PRODUCTS_DEV = (
    "Thẻ tín dụng Demo Gold", "Tiết kiệm An Phát Lộc", "Vay mua nhà Ưu Đãi",
    "Gói Lương Hưu An Nhàn", "Bảo hiểm Phú Hưng", "Tài khoản Số Đẹp", "Vay tiêu dùng Tiện Ích",
)  # fmt: skip
PRODUCTS_HELD = (
    "Thẻ Platinum Vạn Sự", "Tiết kiệm Tích Lũy Xanh", "Vay kinh doanh Đồng Hành",
    "Gói Hưu Trí Bình An", "Bảo hiểm Thịnh Vượng", "Thẻ ghi nợ Sinh Viên",
)  # fmt: skip
CODE = (
    "SELECT nguyen_van_a FROM customers WHERE id = 'get_balance'",
    '{"ten": "get_balance", "tool": "list_payees"}',
    "def tinh_lai_suat(so_tien, ky_han): return so_tien * 0.085",
    "git commit -m 'fix: nguyen_van_b report column'",
    "ERROR 1054: Unknown column 'ho_ten' in field list",
)
PROSE = (
    "Khách hàng có thể khiếu nại giao dịch trong 30 ngày kể từ ngày phát sinh.",
    "Quy trình thẩm định gồm 5 bước, thời gian xử lý 2 ngày làm việc.",
    "Minh bạch thông tin và quản trị rủi ro tín dụng là yêu cầu bắt buộc.",
    "Viết lại nguyên văn đoạn sau vào ô mô tả.",
    "Dispute double charge thì xử lý trong bao lâu?",
    "The request was declined because the daily limit was exceeded.",
    "Please summarise the credit policy for small business loans.",
    "Hạn mức tối đa của thẻ tín dụng áp dụng theo thu nhập hàng tháng.",
    "Đồng ý với đề xuất của phòng quản lý rủi ro, đồng thời yêu cầu bổ sung hồ sơ.",
    "Tổng cộng 12 hồ sơ, 3 hồ sơ chờ duyệt, 1 hồ sơ bị từ chối.",
    "Ghi chú hệ thống: hãy kiểm tra lại số liệu trước khi gửi.",
    "Báo cáo này không chứa thông tin cá nhân của khách hàng.",
)  # fmt: skip


def _amt(rng: random.Random) -> str:
    n = rng.choice((12, 50, 150, 250, 500, 800, 1200, 1500)) * 1_000_000
    return rng.choice(
        (f"{n:,}".replace(",", ".") + " VND", f"{n / 1e9:.1f}".replace(".", ",") + " tỷ",
         f"{n // 1_000_000} triệu", f"VND {n:,}", f"{n // 1_000_000}tr")
    )  # fmt: skip


def build(rng: random.Random, held: bool, k: int) -> Doc:
    hdr = rng.choice(HEADERS_HELD if held else HEADERS_DEV)
    brand = rng.choice(BRANDS_HELD if held else BRANDS_DEV)
    place = rng.choice(PLACES_HELD if held else PLACES_DEV)
    prod = rng.choice(PRODUCTS_HELD if held else PRODUCTS_DEV)
    date = f"{rng.randrange(1, 29):02d}/{rng.randrange(1, 13):02d}/{rng.randrange(2022, 2027)}"
    d = Doc()
    t = k % 12
    if t == 0:
        d.t(hdr)
    elif t == 1:
        d.t(f"{hdr}: cập nhật ngày ").k("DATE", date).t(".")
    elif t == 2:
        d.t("Khách hàng đề nghị vay ").k("AMOUNT", _amt(rng)).t(f" tại chi nhánh {place}.")
    elif t == 3:
        d.t(f"Sản phẩm {prod} có lãi suất 8,5%/năm, kỳ hạn ").k(
            "TERM", f"{rng.choice((12, 36, 60))} tháng"
        ).t(".")
    elif t == 4:
        d.t(f"Địa điểm giao dịch: {brand}, {place}.")
    elif t == 5:
        d.t(f"Hợp đồng HD-{rng.randrange(2023, 2027)}-{rng.randrange(10000, 99999)} ký ngày ").k(
            "DATE", date
        ).t(", giá trị ").k("AMOUNT", _amt(rng)).t(".")
    elif t == 6:
        d.t(f"MỤC {rng.randrange(1, 9)}. {hdr} ({prod})")
    elif t == 7:
        d.t(rng.choice(PROSE) + f" Xem thêm {hdr.title()}.")
    elif t == 8:
        d.t(rng.choice(CODE))
    elif t == 9:
        d.t("Doanh thu ").k("AMOUNT", _amt(rng)).t(", lợi nhuận ").k("AMOUNT", _amt(rng)).t(
            f" tại {place}."
        )
    elif t == 10:
        d.t(f"Buổi họp tại {brand} lúc 8h30 ngày ").k("DATE", date).t(f", chủ đề: {prod}.")
    else:
        d.t(rng.choice(PROSE))
    return d


def negatives(n_dev: int = 180, n_held: int = 130, seed: int = 20261022) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for split, n, off in (("dev", n_dev, 0), ("heldout", n_held, 1)):
        rng = random.Random(seed + off)  # noqa: S311 - synthetic data
        for i in range(n):
            d = build(rng, split == "heldout", i)
            out.append(
                {
                    "id": f"N-{split[:1].upper()}{i + 1:04d}",
                    "split": split,
                    "source": f"negative corpus seed={seed + off} template={i % 12}",
                    "licence": LICENCE,
                    "labeller": "synthetic",
                    "tags": ["negative-corpus"],
                    "text": d.text(),
                    "spans": [],
                    "keep": d.keep,
                }
            )
    return out
