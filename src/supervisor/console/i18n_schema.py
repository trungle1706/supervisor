# ruff: noqa: E501
"""Labels of the schema self-check page (WP-P3), English and Vietnamese, prefix ``sch_``.
Merged into ``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

SCH: dict[str, tuple[str, str]] = {
    "sch_title": ("Schema check", "Kiểm tra lược đồ"),
    "sch_purpose": (
        "Compares the tables and columns of schema/model.yaml with the warehouse. Read only.",
        "So sánh bảng và cột của schema/model.yaml với warehouse. Chỉ đọc.",
    ),
    "sch_why": (
        "A table or column missing in the warehouse makes console pages fail. The app never runs DDL: a person runs the plan below in the SQL editor.",
        "Bảng hoặc cột thiếu trong warehouse làm các trang console lỗi. Ứng dụng không bao giờ chạy DDL: một người chạy kế hoạch bên dưới trong trình soạn SQL.",
    ),
    "sch_status": ("Status", "Trạng thái"),
    "sch_status_ok": ("Schema matches", "Lược đồ khớp"),
    "sch_status_missing": ("Schema differs", "Lược đồ khác"),
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
        "SQL plan (copy and run in the SQL editor)",
        "Kế hoạch SQL (sao chép và chạy trong trình soạn SQL)",
    ),
    "sch_plan_hint": (
        "Run it as an owner of the schema. Statements are safe to repeat. Added columns are nullable. Alternative: python -m supervisor.jobs.bootstrap_schema.",
        "Chạy với quyền chủ sở hữu schema. Các câu lệnh có thể chạy lại an toàn. Cột thêm vào cho phép NULL. Cách khác: python -m supervisor.jobs.bootstrap_schema.",
    ),
    "sch_invisible_note": (
        "Unity Catalog shows only objects this app identity may see. A table that exists but has no grant for the app also appears as missing; CREATE TABLE IF NOT EXISTS does no harm then, but GRANT is the fix.",
        "Unity Catalog chỉ hiện các đối tượng mà danh tính ứng dụng được thấy. Bảng đã có nhưng chưa cấp quyền cho ứng dụng cũng hiện là thiếu; khi đó CREATE TABLE IF NOT EXISTS không gây hại, nhưng cách sửa là GRANT.",
    ),
    "sch_detail": ("Detail", "Chi tiết"),
    "sch_recheck": ("Check again", "Kiểm tra lại"),
    "sch_none": ("None", "Không có"),
    "sch_banner": (
        "The warehouse schema differs from the model: {tables} table(s), {cols} column(s) missing.",
        "Lược đồ warehouse khác mô hình: thiếu {tables} bảng, {cols} cột.",
    ),
    "sch_banner_link": ("Show the SQL plan", "Xem kế hoạch SQL"),
}
