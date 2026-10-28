# ruff: noqa: E501
"""Labels of the Pre-deploy panel (WP-O3), English and Vietnamese, prefix ``pd_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

PD: dict[str, tuple[str, str]] = {
    "pd_title": ("Pre-deploy", "Trước triển khai"),
    "pd_hint": (
        "One report for one source attempt: facts, readiness, the required assurance packs in the launch sandbox (gate in SHADOW), the multi-turn red team and the duties. The verdict comes from the rows below by fixed rules; no model sets it.",
        "Một báo cáo cho một lần nhận mã nguồn: dữ kiện, mức sẵn sàng, các gói đảm bảo bắt buộc trong hộp cát khởi chạy (cổng ở chế độ SHADOW), red team nhiều lượt và các nghĩa vụ. Kết luận được tính từ các dòng bên dưới theo luật cố định; không có mô hình nào quyết định.",
    ),
    "pd_none": (
        "No assessment yet. Add the source in the Source panel and build the facts, then press Run again.",
        "Chưa có đánh giá. Hãy thêm mã nguồn ở mục Mã nguồn và dựng dữ kiện, rồi bấm Chạy lại.",
    ),
    "pd_from_attempt": ("Assessment of source attempt {n}.", "Đánh giá lần nhận mã nguồn {n}."),
    "pd_newer": ("attempt {n} is newer: press Run again", "lần {n} mới hơn: bấm Chạy lại"),
    "pd_running": (
        "The assessment is running. This panel refreshes itself every 3 seconds.",
        "Đang chạy đánh giá. Bảng này tự làm mới sau mỗi 3 giây.",
    ),
    "pd_failed": (
        "The run itself broke. See the summary, then press Run again.",
        "Bản thân lần chạy bị lỗi. Xem phần tóm tắt, rồi bấm Chạy lại.",
    ),
    "pd_verdict": ("Verdict", "Kết luận"),
    "pd_v_go": ("GO", "ĐƯỢC"),
    "pd_v_no_go": ("NO-GO", "KHÔNG ĐƯỢC"),
    "pd_v_questions": ("QUESTIONS", "CÂU HỎI"),
    "pd_v_none": ("not finished", "chưa xong"),
    "pd_s_queued": ("queued", "đang chờ"),
    "pd_s_running": ("running", "đang chạy"),
    "pd_s_done": ("done", "xong"),
    "pd_s_failed": ("failed", "lỗi"),
    "pd_counts": (
        "{fail} fail, {question} question, {warn} warn",
        "{fail} lỗi, {question} câu hỏi, {warn} cảnh báo",
    ),
    "pd_sec_facts": ("Facts", "Dữ kiện"),
    "pd_sec_readiness": ("Readiness", "Mức sẵn sàng"),
    "pd_sec_packs": ("Required assurance packs", "Gói đảm bảo bắt buộc"),
    "pd_sec_multiturn": ("Multi-turn red team (advisory)", "Red team nhiều lượt (tham khảo)"),
    "pd_sec_duties": ("Duties", "Nghĩa vụ"),
    "pd_required": ("a fail here is NO-GO", "lỗi ở đây là KHÔNG ĐƯỢC"),
    "pd_st_ok": ("ok", "đạt"),
    "pd_st_warn": ("warn", "cảnh báo"),
    "pd_st_fail": ("fail", "lỗi"),
    "pd_st_question": ("question", "câu hỏi"),
    "pd_st_skip": ("skip", "bỏ qua"),
    "pd_c_status": ("Status", "Trạng thái"),
    "pd_c_item": ("Item", "Mục"),
    "pd_c_pointer": ("Pointer", "Con trỏ"),
    "pd_run": ("Run again", "Chạy lại"),
    "pd_run_first": ("Run assessment", "Chạy đánh giá"),
    "pd_run_hint": (
        "Starts a new assessment of the newest source attempt. Old reports stay.",
        "Bắt đầu đánh giá mới cho lần nhận mã nguồn mới nhất. Báo cáo cũ được giữ lại.",
    ),
    "pd_view_only": (
        "You can look at this report; you need the right to edit systems to run it again.",
        "Bạn chỉ xem được báo cáo này; cần quyền sửa hệ thống để chạy lại.",
    ),
    "pd_open_page": ("Open the Pre-deploy page", "Mở trang Trước triển khai"),
    "pd_reg_line": (
        "Pre-deploy report of the scanned source: {verdict}.",
        "Báo cáo trước triển khai của mã nguồn đã quét: {verdict}.",
    ),
    "pd_reg_link": ("Open the report", "Mở báo cáo"),
}
