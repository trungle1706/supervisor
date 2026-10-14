"""Word lists for the synthetic generator. Own lists; no third-party data."""

from __future__ import annotations

SURNAMES: tuple[str, ...] = (
    "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng",
    "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý", "Trịnh", "Đinh", "Mai", "Cao",
)  # fmt: skip

MIDDLE_MALE: tuple[str, ...] = ("Văn", "Hữu", "Đức", "Minh", "Quang", "Công", "Thành", "Gia")
MIDDLE_FEMALE: tuple[str, ...] = ("Thị", "Ngọc", "Thu", "Thanh", "Mỹ", "Kim", "Phương", "Bảo")

GIVEN_MALE: tuple[str, ...] = (
    "An", "Bình", "Cường", "Dũng", "Hùng", "Huy", "Khang", "Khoa", "Long", "Nam",
    "Phong", "Phúc", "Quân", "Sơn", "Tài", "Thắng", "Toàn", "Trung", "Tuấn", "Việt",
)  # fmt: skip
GIVEN_FEMALE: tuple[str, ...] = (
    "Anh", "Chi", "Dung", "Giang", "Hà", "Hạnh", "Hằng", "Hoa", "Hương", "Lan",
    "Linh", "Mai", "My", "Ngân", "Nhung", "Oanh", "Quyên", "Thảo", "Trang", "Vy",
)  # fmt: skip

# CCCD province codes (Circular 07/2016/TT-BCA, 63 pre-2025 provinces). Code -> name.
PROVINCES: dict[str, str] = {
    "001": "Hà Nội", "002": "Hà Giang", "004": "Cao Bằng", "006": "Bắc Kạn",
    "008": "Tuyên Quang", "010": "Lào Cai", "011": "Điện Biên", "012": "Lai Châu",
    "014": "Sơn La", "015": "Yên Bái", "017": "Hòa Bình", "019": "Thái Nguyên",
    "020": "Lạng Sơn", "022": "Quảng Ninh", "024": "Bắc Giang", "025": "Phú Thọ",
    "026": "Vĩnh Phúc", "027": "Bắc Ninh", "030": "Hải Dương", "031": "Hải Phòng",
    "033": "Hưng Yên", "034": "Thái Bình", "035": "Hà Nam", "036": "Nam Định",
    "037": "Ninh Bình", "038": "Thanh Hóa", "040": "Nghệ An", "042": "Hà Tĩnh",
    "044": "Quảng Bình", "045": "Quảng Trị", "046": "Thừa Thiên Huế", "048": "Đà Nẵng",
    "049": "Quảng Nam", "051": "Quảng Ngãi", "052": "Bình Định", "054": "Phú Yên",
    "056": "Khánh Hòa", "058": "Ninh Thuận", "060": "Bình Thuận", "062": "Kon Tum",
    "064": "Gia Lai", "066": "Đắk Lắk", "067": "Đắk Nông", "068": "Lâm Đồng",
    "070": "Bình Phước", "072": "Tây Ninh", "074": "Bình Dương", "075": "Đồng Nai",
    "077": "Bà Rịa - Vũng Tàu", "079": "Hồ Chí Minh", "080": "Long An", "082": "Tiền Giang",
    "083": "Bến Tre", "084": "Trà Vinh", "086": "Vĩnh Long", "087": "Đồng Tháp",
    "089": "An Giang", "091": "Kiên Giang", "092": "Cần Thơ", "093": "Hậu Giang",
    "094": "Sóc Trăng", "095": "Bạc Liêu", "096": "Cà Mau",
}  # fmt: skip

# Weighted toward large cities so slices have enough rows.
PROVINCE_WEIGHTS: dict[str, int] = {"001": 18, "079": 22, "048": 6, "031": 5, "092": 4}

DISTRICTS: dict[str, tuple[str, ...]] = {
    "001": ("Quận Ba Đình", "Quận Hoàn Kiếm", "Quận Cầu Giấy", "Quận Đống Đa", "Quận Hà Đông"),
    "079": ("Quận 1", "Quận 3", "Quận Bình Thạnh", "Quận Tân Bình", "Thành phố Thủ Đức"),
    "048": ("Quận Hải Châu", "Quận Thanh Khê", "Quận Sơn Trà"),
    "031": ("Quận Lê Chân", "Quận Ngô Quyền", "Quận Hồng Bàng"),
    "092": ("Quận Ninh Kiều", "Quận Cái Răng", "Quận Bình Thủy"),
}
GENERIC_DISTRICTS: tuple[str, ...] = ("Thành phố", "Thị xã", "Huyện")

STREETS: tuple[str, ...] = (
    "Lê Lợi", "Trần Hưng Đạo", "Nguyễn Huệ", "Hai Bà Trưng", "Lý Thường Kiệt",
    "Phan Đình Phùng", "Điện Biên Phủ", "Nguyễn Trãi", "Lê Duẩn", "Cách Mạng Tháng Tám",
    "Võ Văn Tần", "Hùng Vương", "Quang Trung", "Bạch Đằng", "Nguyễn Văn Cừ",
)  # fmt: skip
WARDS: tuple[str, ...] = (
    "Phường 1", "Phường 2", "Phường 7", "Phường Bến Nghé", "Phường Tràng Tiền",
    "Phường Dịch Vọng", "Phường Thạc Gián", "Xã Tân Phú", "Phường An Hải",
)  # fmt: skip

MOBILE_PREFIXES: tuple[str, ...] = (
    "032", "033", "034", "035", "036", "037", "038", "039", "070", "076", "077", "078",
    "079", "081", "082", "083", "084", "085", "086", "088", "089", "090", "091", "093",
    "094", "096", "097", "098",
)  # fmt: skip

EMAIL_DOMAINS: tuple[str, ...] = ("example.com", "example.org", "example.net")

# Synthetic bank codes (short names only; numbers are random, not real accounts).
BANK_CODES: tuple[str, ...] = ("TCB", "VCB", "BIDV", "CTG", "ACB", "MBB", "VPB", "TPB")

FEE_CODES: tuple[str, ...] = ("ANNUAL_CARD", "SMS_BANKING", "LATE_PAYMENT", "ATM_OTHER_BANK")
