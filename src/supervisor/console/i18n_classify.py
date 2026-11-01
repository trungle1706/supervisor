# ruff: noqa: E501
"""Labels of the classification tree (WP-C1), English and Vietnamese, prefix ``cv_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

CV: dict[str, tuple[str, str]] = {
    "cv_title": ("Classification tree", "Cây phân loại"),
    "cv_hint": (
        "Start at the first question. Each box names the article behind it. Rules can fill in some answers, and you can always change them. A second approver then confirms the result.",
        "Bắt đầu từ câu hỏi đầu tiên. Mỗi ô nêu điều luật đứng sau câu hỏi. Quy tắc có thể điền sẵn một số câu trả lời và bạn luôn sửa được. Người phê duyệt thứ hai sau đó xác nhận kết quả.",
    ),
    "cv_illustrative": (
        "For illustration only. Not legal advice. Bank counsel confirms the questions.",
        "Chỉ mang tính minh họa. Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận các câu hỏi.",
    ),
    "cv_current": ("Approved classification", "Phân loại đã phê duyệt"),
    "cv_pending": ("Waiting for approval", "Đang chờ phê duyệt"),
    "cv_none": ("Not classified yet.", "Chưa phân loại."),
    "cv_decided_by": ("Decided by", "Người quyết định"),
    "cv_approved_by": ("Approved by", "Người phê duyệt"),
    "cv_valid_until": ("Review by", "Rà soát trước ngày"),
    "cv_review_due": ("review is due", "đến hạn rà soát"),
    "cv_inherited": (
        "Result taken from the provider (Circular 53 Art. 4(4))",
        "Kết quả kế thừa từ nhà cung cấp (Thông tư 53 Điều 4 khoản 4)",
    ),
    "cv_tree_changed": (
        "The classification tree changed after this classification was made.",
        "Cây phân loại đã thay đổi sau khi phân loại này được tạo.",
    ),
    "cv_status_on": ("on the path", "trên đường đi"),
    "cv_status_open": ("next question", "câu hỏi tiếp theo"),
    "cv_status_off": ("not reached", "chưa tới"),
    "cv_article": ("Article", "Điều luật"),
    "cv_answer": ("Answer", "Trả lời"),
    "cv_source": ("Source", "Nguồn"),
    "cv_src_rules": ("rule", "quy tắc"),
    "cv_src_person": ("person", "người dùng"),
    "cv_src_decision33": ("Decision 33 flow", "luồng Quyết định 33"),
    "cv_evidence": ("Evidence reference", "Tham chiếu bằng chứng"),
    "cv_evidence_hint": ("Hint", "Gợi ý"),
    "cv_note": (
        "Note (300 characters at most, no personal data)",
        "Ghi chú (tối đa 300 ký tự, không có dữ liệu cá nhân)",
    ),
    "cv_open": ("not answered", "chưa trả lời"),
    "cv_yes": ("yes", "có"),
    "cv_no": ("no", "không"),
    "cv_excluded": ("excluded", "loại trừ"),
    "cv_high_risk": ("in the list (high)", "thuộc danh mục (cao)"),
    "cv_not_high_risk": ("not in the list", "không thuộc danh mục"),
    "cv_sub_title": ("Decision 33 questions", "Câu hỏi của Quyết định 33"),
    "cv_sub_hint": (
        "These questions settle the step above. Rules fill in some answers. Choose yes or no to set your own.",
        "Các câu hỏi này quyết định bước phía trên. Quy tắc điền sẵn một số câu trả lời. Chọn có hoặc không để tự đặt.",
    ),
    "cv_sub_outcome": ("Decision 33 outcome", "Kết quả Quyết định 33"),
    "cv_inherited_label": ("The result is taken from the provider", "Kết quả lấy từ nhà cung cấp"),
    "cv_evaluate": ("Evaluate", "Đánh giá"),
    "cv_evaluate_hint": (
        "Shows the result for these answers. Nothing is saved.",
        "Hiển thị kết quả cho các câu trả lời này. Không lưu gì.",
    ),
    "cv_save": ("Save classification", "Lưu phân loại"),
    "cv_approve": ("Approve", "Phê duyệt"),
    "cv_approve_hint": (
        "A second approver must confirm. This cannot be the person who decided or the system owner. The risk level changes only then, and never goes down here.",
        "Cần người phê duyệt thứ hai xác nhận, không phải người đã quyết định hay chủ sở hữu hệ thống. Chỉ khi đó mức rủi ro mới thay đổi, và không bao giờ bị hạ xuống ở đây.",
    ),
    "cv_cannot_approve": (
        "You cannot approve this classification. You decided it, you own the system, or you lack permission.",
        "Bạn không thể phê duyệt phân loại này. Bạn đã quyết định nó, bạn sở hữu hệ thống, hoặc bạn không có quyền.",
    ),
    "cv_view_only": (
        "You can view this page only. To decide, you need the permission systems.edit.",
        "Bạn chỉ xem được trang này. Để quyết định, bạn cần quyền systems.edit.",
    ),
    "cv_next": ("Next question", "Câu hỏi tiếp theo"),
    "cv_reason_decision33_open": (
        "the Decision 33 questions are not all answered",
        "chưa trả lời hết câu hỏi Quyết định 33",
    ),
    "cv_reason_unanswered": ("waiting for an answer", "đang chờ câu trả lời"),
    "cv_outcome": ("Outcome", "Kết quả"),
    "cv_level": ("Risk level", "Mức rủi ro"),
    "cv_level_none": ("no change", "không thay đổi"),
    "cv_duties": ("Duties that follow", "Nghĩa vụ kèm theo"),
    "cv_duties_none": (
        "This classification adds no duties.",
        "Phân loại này không phát sinh nghĩa vụ nào.",
    ),
    "cv_thresholds": ("SBV thresholds (VND)", "Ngưỡng của Ngân hàng Nhà nước (đồng)"),
    "cv_th_personal_per_transaction_vnd": ("person, per transaction", "cá nhân, mỗi giao dịch"),
    "cv_th_personal_per_day_vnd": ("person, per day", "cá nhân, mỗi ngày"),
    "cv_th_organisation_per_transaction_vnd": (
        "organisation, per transaction",
        "tổ chức, mỗi giao dịch",
    ),
    "cv_th_organisation_per_day_vnd": ("organisation, per day", "tổ chức, mỗi ngày"),
    "cv_th_credit_vnd": ("credit, from", "tín dụng, từ"),
    "cv_triggers": (
        "Classify again when (Decree 142 Art. 11)",
        "Phân loại lại khi (Nghị định 142 Điều 11)",
    ),
    "cv_not_triggers": ("No need to reclassify", "Không cần phân loại lại"),
    "cv_records_n": (
        "Classifications for this system: {n}",
        "Số lần phân loại của hệ thống này: {n}",
    ),
    "cv_open_page": ("Open the classification tree", "Mở cây phân loại"),
    "cv_register_note": (
        "This is the result from the rules and your Decision 33 answers so far. After you submit, classify and approve it on the system's Classify page.",
        "Đây là kết quả từ các quy tắc và câu trả lời Quyết định 33 của bạn cho đến nay. Sau khi gửi, hãy phân loại và phê duyệt ở trang Phân loại của hệ thống.",
    ),
    "cv_incomplete": (
        "Answer the next question to reach an outcome.",
        "Hãy trả lời câu hỏi tiếp theo để có kết quả.",
    ),
    "cv_back": ("Back to the system", "Quay lại hệ thống"),
}
