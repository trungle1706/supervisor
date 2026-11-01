# ruff: noqa: E501
"""Labels of the Pre-deploy panel (WP-O3), English and Vietnamese, prefix ``pd_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

PD: dict[str, tuple[str, str]] = {
    "pd_title": ("Pre-deploy", "Trước triển khai"),
    "pd_hint": (
        "One report for each source upload. It covers facts, readiness, test packs, red team and duties. The result follows fixed rules, not a model.",
        "Mỗi lần tải mã nguồn có một báo cáo. Báo cáo gồm dữ kiện, mức sẵn sàng, gói kiểm thử, red team và nghĩa vụ. Kết luận theo quy tắc cố định, không do mô hình quyết định.",
    ),
    "pd_none": (
        "No assessment yet. Upload the source code and read the facts first, then run the assessment.",
        "Chưa có đánh giá. Hãy tải mã nguồn lên và đọc dữ kiện trước, rồi chạy đánh giá.",
    ),
    "pd_from_attempt": ("Assessment of source upload {n}.", "Đánh giá của lần tải mã nguồn {n}."),
    "pd_newer": ("upload {n} is newer: run again", "lần tải {n} mới hơn: hãy chạy lại"),
    "pd_running": (
        "Assessment running. This page refreshes every 3 seconds.",
        "Đang đánh giá. Trang này tự làm mới sau mỗi 3 giây.",
    ),
    "pd_failed": (
        "The assessment could not finish. Read the summary, then run it again.",
        "Đánh giá chưa hoàn tất được. Hãy xem phần tóm tắt, rồi chạy lại.",
    ),
    "pd_verdict": ("Verdict", "Kết luận"),
    "pd_v_go": ("GO", "ĐƯỢC"),
    "pd_v_no_go": ("NO-GO", "KHÔNG ĐƯỢC"),
    "pd_v_questions": ("QUESTIONS", "CÂU HỎI"),
    "pd_v_none": ("not finished", "chưa hoàn tất"),
    "pd_s_queued": ("queued", "đang chờ"),
    "pd_s_running": ("running", "đang chạy"),
    "pd_s_done": ("done", "xong"),
    "pd_s_failed": ("failed", "không thành công"),
    "pd_counts": (
        "{fail} failed, {question} open questions, {warn} warnings",
        "{fail} không đạt, {question} câu hỏi mở, {warn} cảnh báo",
    ),
    "pd_sec_facts": ("Facts", "Dữ kiện"),
    "pd_sec_readiness": ("Readiness", "Mức sẵn sàng"),
    "pd_sec_packs": ("Required test packs", "Gói kiểm thử bắt buộc"),
    "pd_sec_multiturn": (
        "Multi-turn red team (for reference)",
        "Red team nhiều lượt (để tham khảo)",
    ),
    "pd_sec_duties": ("Duties", "Nghĩa vụ"),
    "pd_required": (
        "a failure here means NO-GO",
        "không đạt ở mục này nghĩa là KHÔNG ĐƯỢC triển khai",
    ),
    "pd_st_ok": ("ok", "đạt"),
    "pd_st_warn": ("warning", "cảnh báo"),
    "pd_st_fail": ("failed", "không đạt"),
    "pd_st_question": ("open question", "câu hỏi mở"),
    "pd_st_skip": ("skipped", "bỏ qua"),
    "pd_c_status": ("Status", "Trạng thái"),
    "pd_c_item": ("Item", "Mục"),
    "pd_c_pointer": ("Evidence", "Bằng chứng"),
    "pd_run": ("Run again", "Chạy lại"),
    "pd_run_first": ("Run assessment", "Chạy đánh giá"),
    "pd_run_hint": (
        "Starts a new assessment of the latest source upload. Old reports are kept.",
        "Bắt đầu đánh giá mới cho lần tải mã nguồn mới nhất. Báo cáo cũ vẫn được giữ.",
    ),
    "pd_view_only": (
        "You can view this report. To run it again, you need permission to edit systems.",
        "Bạn có thể xem báo cáo này. Để chạy lại, bạn cần quyền chỉnh sửa hệ thống.",
    ),
    "pd_open_page": ("Open the Pre-deploy page", "Mở trang Trước triển khai"),
    "pd_reg_line": (
        "Pre-deploy result for the scanned source: {verdict}.",
        "Kết quả trước triển khai của mã nguồn đã quét: {verdict}.",
    ),
    "pd_reg_link": ("Open the report", "Mở báo cáo"),
}
