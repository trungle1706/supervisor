# ruff: noqa: E501
"""Labels of the Run assessment panel (WP-F4), English and Vietnamese, prefix ``orch_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only. Not legal advice."""

from __future__ import annotations

ORCH: dict[str, tuple[str, str]] = {
    "orch_title": ("Run assessment", "Chạy đánh giá"),
    "orch_intro": (
        "The orchestrator plans the eight risk types, runs the assessment agent of each (or the rule proposal) under a budget and writes a proposal into the rows. It never sets Pass: a person confirms.",
        "Bộ điều phối lập kế hoạch cho tám loại rủi ro, chạy agent đánh giá của từng loại (hoặc đề xuất theo quy tắc) trong ngân sách và ghi đề xuất vào các dòng. Nó không bao giờ đặt Đạt: một người xác nhận.",
    ),
    "orch_run": ("Run assessment", "Chạy đánh giá"),
    "orch_running": (
        "A run is in progress. This panel updates by itself.",
        "Đang chạy. Bảng này tự cập nhật.",
    ),
    "orch_run_queued": ("Queued", "Đang chờ"),
    "orch_run_running": ("Running", "Đang chạy"),
    "orch_run_done": ("Done", "Hoàn tất"),
    "orch_run_failed": ("Failed", "Lỗi"),
    "orch_attempt": ("Attempt", "Lần chạy"),
    "orch_outcome": ("Classification outcome", "Kết quả phân loại"),
    "orch_plan_hash": ("Plan hash", "Mã băm kế hoạch"),
    "orch_budget": ("Budget used", "Ngân sách đã dùng"),
    "orch_time": ("time", "thời gian"),
    "orch_tokens": ("tokens", "token"),
    "orch_summary": ("Summary", "Tóm tắt"),
    "orch_col_type": ("Risk type", "Loại rủi ro"),
    "orch_col_agent": ("Assessed by", "Đánh giá bởi"),
    "orch_col_status": ("Status", "Trạng thái"),
    "orch_col_verdict": ("Verdict", "Kết luận"),
    "orch_col_stop": ("Stop point", "Điểm dừng"),
    "orch_col_report": ("Report", "Báo cáo"),
    "orch_it_queued": ("Queued", "Đang chờ"),
    "orch_it_running": ("Running", "Đang chạy"),
    "orch_it_done": ("Done", "Hoàn tất"),
    "orch_it_needs_person": ("Needs a person", "Cần người xử lý"),
    "orch_it_budget_exceeded": ("Over budget", "Vượt ngân sách"),
    "orch_it_failed": ("Failed", "Lỗi"),
    "orch_it_not_applicable": ("Not applicable", "Không áp dụng"),
    "orch_it_skipped": ("Skipped", "Bỏ qua"),
    "orch_needs_person": ("Person needed", "Cần người"),
    "orch_reload": ("Refresh the rows", "Làm mới các dòng"),
    "orch_none": ("No run yet.", "Chưa có lần chạy."),
    "orch_ok_started": ("Run started.", "Đã bắt đầu chạy."),
}
