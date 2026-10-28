# ruff: noqa: E501
"""Labels of the regulation watch page (WP-W1), English and Vietnamese, prefix ``rw_``. Merged
into ``i18n._T`` by one line in ``i18n.py``. UI text only."""

from __future__ import annotations

RW: dict[str, tuple[str, str]] = {
    "rw_title": ("Regulation watch", "Theo dõi quy định"),
    "rw_nav": ("Regulation watch", "Theo dõi quy định"),
    "rw_banner": (
        "Not legal advice. Bank counsel must confirm.",
        "Không phải tư vấn pháp lý. Bộ phận pháp chế phải xác nhận.",
    ),
    "rw_hint": (
        "The watcher runs on a laptop or the dev host (the App has no internet). A signed update package is imported with POST /v1/regkb/import. An import only stores the package; nothing is applied to RegKB.",
        "Bộ theo dõi chạy trên máy xách tay hoặc máy phát triển (App không có internet). Gói cập nhật đã ký được nhập bằng POST /v1/regkb/import. Nhập chỉ lưu gói; không có gì được áp dụng vào RegKB.",
    ),
    "rw_runs": ("Runs", "Lần chạy"),
    "rw_reports": ("Watch reports", "Báo cáo theo dõi"),
    "rw_packages": ("Imported packages", "Gói đã nhập"),
    "rw_no_runs": ("No run yet.", "Chưa có lần chạy nào."),
    "rw_no_reports": ("No report yet.", "Chưa có báo cáo nào."),
    "rw_no_packages": ("No package imported yet.", "Chưa nhập gói nào."),
    "rw_no_changes": ("No change found.", "Không phát hiện thay đổi."),
    "rw_not_applied": ("Stored, not applied.", "Đã lưu, chưa áp dụng."),
    "rw_pending": ("pending review (WP-W2)", "chờ xem xét (WP-W2)"),
    "rw_candidates": ("new candidates", "văn bản mới có thể liên quan"),
    "rw_c_run": ("Run", "Lần chạy"),
    "rw_c_started": ("Started", "Bắt đầu"),
    "rw_c_status": ("Status", "Trạng thái"),
    "rw_c_checked": ("Instruments", "Văn bản"),
    "rw_c_changes": ("changes", "thay đổi"),
    "rw_c_instrument": ("Instrument", "Văn bản"),
    "rw_c_kind": ("Kind", "Loại"),
    "rw_c_detail": ("Detail", "Chi tiết"),
    "rw_c_date": ("Date", "Ngày"),
    "rw_c_review": ("Review", "Xem xét"),
}
