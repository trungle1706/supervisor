# ruff: noqa: E501
"""Labels of the Duties tab (WP-L3), English and Vietnamese, prefix ``du_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only. Not legal advice."""

from __future__ import annotations

DU: dict[str, tuple[str, str]] = {
    "du_tab": ("Duties", "Nghĩa vụ"),
    "du_pill": ("Duties closed {pct}%", "Nghĩa vụ đã đóng {pct}%"),
    "du_score_title": ("Gap closure score", "Điểm đóng khoảng trống"),
    "du_score_none": (
        "No duty of this system applies yet, so there is no score.",
        "Chưa có nghĩa vụ nào áp dụng cho hệ thống này nên chưa có điểm.",
    ),
    "du_score_line": (
        "of the duties that apply are closed ({closed} of {total}).",
        "nghĩa vụ áp dụng đã đóng ({closed} / {total}).",
    ),
    "du_score_note": (
        "Waived duties ({waived}) are not in the score. Groups still open: {groups}. Risk line:",
        "Nghĩa vụ đã miễn trừ ({waived}) không tính vào điểm. Nhóm còn mở: {groups}. Dòng rủi ro:",
    ),
    "du_reeval": ("Re-evaluate", "Đánh giá lại"),
    "du_reeval_hint": (
        "Runs the matrix again on the stored answers and updates applies and coverage. Nothing is deleted.",
        "Chạy lại ma trận trên các câu trả lời đã lưu và cập nhật áp dụng và độ bao phủ. Không xóa gì.",
    ),
    "du_filter": ("Filter duties", "Lọc nghĩa vụ"),
    "du_f_open": ("Open", "Đang mở"),
    "du_f_closed": ("Closed", "Đã đóng"),
    "du_f_waived": ("Waived", "Đã miễn trừ"),
    "du_f_needs_answer": ("Needs answer", "Cần trả lời"),
    "du_f_all": ("All", "Tất cả"),
    "du_empty": ("No duty row matches this filter.", "Không có nghĩa vụ nào khớp bộ lọc này."),
    "du_cov_none": ("No coverage", "Chưa bao phủ"),
    "du_cov_partial": ("Partial coverage", "Bao phủ một phần"),
    "du_cov_full": ("Full coverage", "Bao phủ đầy đủ"),
    "du_cov_unknown": ("Coverage unknown", "Chưa rõ độ bao phủ"),
    "du_group_counts": (
        "{open} open, {closed} closed, {waived} waived",
        "{open} mở, {closed} đóng, {waived} miễn trừ",
    ),
    "du_col_obl": ("Obligation and article", "Nghĩa vụ và điều khoản"),
    "du_col_duty": ("Duty", "Nội dung"),
    "du_col_applies": ("Applies", "Áp dụng"),
    "du_col_cov": ("Coverage", "Độ bao phủ"),
    "du_col_owner": ("Owner", "Chủ sở hữu"),
    "du_col_due": ("Due", "Hạn"),
    "du_col_control": ("Closing control", "Kiểm soát đóng"),
    "du_ap_yes": ("yes", "có"),
    "du_ap_no": ("no", "không"),
    "du_ap_needs_answer": ("needs answer", "cần trả lời"),
    "du_st_open": ("open", "mở"),
    "du_st_closed": ("closed", "đóng"),
    "du_st_waived": ("waived", "miễn trừ"),
    "du_needs_answer": (
        "Answer the open question, then re-evaluate.",
        "Trả lời câu hỏi còn mở, rồi đánh giá lại.",
    ),
    "du_close": ("Close", "Đóng"),
    "du_waive": ("Waive", "Miễn trừ"),
    "du_control": ("Closing control", "Kiểm soát đóng"),
    "du_control_ph": (
        "Control id, or manual:<bank control id>",
        "Mã kiểm soát, hoặc manual:<mã kiểm soát của ngân hàng>",
    ),
    "du_evidence": ("Evidence reference", "Tham chiếu bằng chứng"),
    "du_evidence_ph": (
        "Evidence reference (at most 200 characters)",
        "Tham chiếu bằng chứng (tối đa 200 ký tự)",
    ),
    "du_waive_ph": (
        "Reason for the waiver ({n} characters or more)",
        "Lý do miễn trừ (từ {n} ký tự)",
    ),
    "du_owner_note": (
        "You own this system, so you cannot waive its duties. A second person with approval rights does it.",
        "Bạn là chủ sở hữu hệ thống này nên không thể miễn trừ nghĩa vụ của nó. Người thứ hai có quyền phê duyệt sẽ làm việc này.",
    ),
    "du_paging": (
        "Rows {first} to {last} of {total} (page {page} of {pages}).",
        "Dòng {first} đến {last} trên {total} (trang {page} / {pages}).",
    ),
    "du_prev": ("Previous page", "Trang trước"),
    "du_next": ("Next page", "Trang sau"),
    "du_ov_line": (
        "{avg}% on average, {n} systems, {open} with open groups",
        "trung bình {avg}%, {n} hệ thống, {open} còn nhóm mở",
    ),
    "du_ok_close": ("Duty closed.", "Đã đóng nghĩa vụ."),
    "du_ok_waive": ("Duty waived.", "Đã miễn trừ nghĩa vụ."),
    "du_ok_reeval": ("Duties evaluated again.", "Đã đánh giá lại nghĩa vụ."),
    # --- WP-L4 (REGULATOR_PACK): evidence per control and the regulator pack ---
    "du_ok_refresh": ("Evidence read again.", "Đã đọc lại bằng chứng."),
    "du_refresh": ("Refresh evidence", "Làm mới bằng chứng"),
    "du_refresh_hint": (
        "Reads the live counts of the mapped controls (last {days} days). A full-coverage duty whose controls all work is closed by the system. Partial and none are never closed here.",
        "Đọc số liệu trực tiếp của các kiểm soát đã ánh xạ ({days} ngày gần nhất). Nghĩa vụ bao phủ đầy đủ có mọi kiểm soát đang hoạt động sẽ do hệ thống đóng. Bao phủ một phần hoặc chưa bao phủ không bao giờ đóng ở đây.",
    ),
    "du_pack": ("Regulator pack", "Hồ sơ cho cơ quan quản lý"),
    "du_pack_json": ("JSON (signed)", "JSON (đã ký)"),
    "du_pack_html": ("HTML", "HTML"),
    "du_col_evidence": ("Evidence (rows in window)", "Bằng chứng (số dòng trong kỳ)"),
    "du_ev_works": ("works", "đang hoạt động"),
    "du_ev_no": ("no evidence", "chưa có bằng chứng"),
    "du_ev_nomap": ("no Supervisor control", "không có kiểm soát của Supervisor"),
    "du_ev_advisory": ("advisory", "chỉ tham khảo"),
    "du_ev_unmeasured": ("unmeasured", "chưa đo"),
    "du_by_evidence": ("closed by evidence", "đóng theo bằng chứng"),
    "du_by_person": ("closed by a person", "đóng bởi người dùng"),
}
