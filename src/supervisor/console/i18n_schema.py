# ruff: noqa: E501
"""Labels of the schema self-check page (WP-P3), English and Vietnamese, prefix ``sch_``.
Merged into ``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

SCH: dict[str, tuple[str, str]] = {
    "sch_title": ("Data structure check", "Kiểm tra cấu trúc dữ liệu"),
    "sch_purpose": (
        "Checks that the data warehouse matches what the console expects. View only.",
        "Kiểm tra kho dữ liệu có khớp với những gì console cần. Chỉ xem.",
    ),
    "sch_why": (
        "A missing table or column breaks console pages. The console never changes the warehouse. An admin must run the fix script.",
        "Thiếu bảng hoặc cột sẽ làm hỏng các trang console. Console không tự sửa kho dữ liệu. Quản trị viên cần chạy tập lệnh sửa.",
    ),
    "sch_status": ("Status", "Trạng thái"),
    "sch_status_ok": ("Data structure matches", "Cấu trúc dữ liệu khớp"),
    "sch_status_missing": ("Data structure differs", "Cấu trúc dữ liệu khác"),
    "sch_status_unknown": ("Check failed (unknown)", "Kiểm tra lỗi (chưa rõ)"),
    "sch_status_off": (
        "Check is off (SCHEMA_SELFCHECK=0)",
        "Kiểm tra đang tắt (SCHEMA_SELFCHECK=0)",
    ),
    "sch_checked_at": ("Checked at", "Kiểm tra lúc"),
    "sch_tables": ("Tables in the model", "Số bảng trong mô hình"),
    "sch_missing_tables": ("Missing tables", "Bảng thiếu"),
    "sch_missing_cols": ("Missing columns", "Cột thiếu"),
    "sch_not_checked": ("Not checked", "Chưa kiểm tra"),
    "sch_plan": (
        "Fix script (copy and run in the SQL editor)",
        "Tập lệnh sửa (sao chép và chạy trong trình soạn SQL)",
    ),
    "sch_plan_hint": (
        "Run it as a schema owner. It is safe to run twice. New columns can stay empty. Or run python -m supervisor.jobs.bootstrap_schema.",
        "Chạy bằng quyền chủ sở hữu schema. Chạy lại nhiều lần vẫn an toàn. Cột mới có thể để trống. Hoặc chạy python -m supervisor.jobs.bootstrap_schema.",
    ),
    "sch_invisible_note": (
        "Unity Catalog shows the app only what it may see. A table the app has no access to also shows as missing. Creating it again is harmless; the real fix is GRANT.",
        "Unity Catalog chỉ cho ứng dụng thấy những gì được phép. Bảng ứng dụng chưa có quyền truy cập cũng hiện là thiếu. Tạo lại bảng không gây hại; cách sửa đúng là GRANT.",
    ),
    "sch_recheck": ("Check again", "Kiểm tra lại"),
    "sch_banner": (
        "The data warehouse is missing {tables} table(s) and {cols} column(s) that the console needs.",
        "Kho dữ liệu thiếu {tables} bảng và {cols} cột mà console cần.",
    ),
    "sch_banner_link": ("See the fix (SQL)", "Xem cách sửa (SQL)"),
}
