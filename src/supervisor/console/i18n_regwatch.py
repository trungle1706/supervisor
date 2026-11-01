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
        "The watcher runs on a laptop or dev host, not in the App (no internet). An administrator imports a signed update package here. Importing only stores the package; it does not change RegKB.",
        "Bộ theo dõi chạy trên máy xách tay hoặc máy phát triển, không chạy trong App (không có internet). Quản trị viên nhập gói cập nhật đã ký tại đây. Việc nhập chỉ lưu gói, không thay đổi RegKB.",
    ),
    "rw_runs": ("Runs", "Lần chạy"),
    "rw_reports": ("Watch reports", "Báo cáo theo dõi"),
    "rw_packages": ("Imported packages", "Gói đã nhập"),
    "rw_no_runs": ("No run yet.", "Chưa có lần chạy nào."),
    "rw_no_reports": ("No report yet.", "Chưa có báo cáo nào."),
    "rw_no_packages": ("No package imported yet.", "Chưa nhập gói nào."),
    "rw_no_changes": ("No change found.", "Không phát hiện thay đổi."),
    "rw_not_applied": ("Stored, not applied.", "Đã lưu, chưa áp dụng."),
    "rw_pending": ("waiting for review", "chờ xem xét"),
    "rw_candidates": ("new documents to review", "văn bản mới cần xem xét"),
    "rw_c_run": ("Run", "Lần chạy"),
    "rw_c_started": ("Started", "Bắt đầu"),
    "rw_c_status": ("Status", "Trạng thái"),
    "rw_c_checked": ("Documents checked", "Văn bản đã kiểm tra"),
    "rw_c_changes": ("changes", "thay đổi"),
    "rw_c_instrument": ("Document", "Văn bản"),
    "rw_c_kind": ("Kind", "Loại"),
    "rw_c_detail": ("Detail", "Chi tiết"),
    "rw_c_date": ("Date", "Ngày"),
    "rw_c_review": ("Review", "Xem xét"),
}
