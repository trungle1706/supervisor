# ruff: noqa: E501
"""Labels of the classification tree (WP-C1), English and Vietnamese, prefix ``cv_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

CV: dict[str, tuple[str, str]] = {
    "cv_title": ("Classification tree", "Cây phân loại"),
    "cv_hint": (
        "Walk the tree from the first question. Each box names the article behind the question. A rule can fill an answer from the system record; a person can always change it. The result is a record that a second person approves.",
        "Đi theo cây từ câu hỏi đầu tiên. Mỗi ô nêu điều luật đứng sau câu hỏi. Một quy tắc có thể điền câu trả lời từ hồ sơ hệ thống; người dùng luôn có thể sửa. Kết quả là một bản ghi mà người thứ hai phê duyệt.",
    ),
    "cv_illustrative": (
        "Illustrative and not legal advice: counsel confirms the questions.",
        "Chỉ mang tính minh họa, không phải tư vấn pháp lý: bộ phận pháp chế xác nhận các câu hỏi.",
    ),
    "cv_current": ("Approved classification", "Phân loại đã phê duyệt"),
    "cv_pending": ("Waiting for approval", "Đang chờ phê duyệt"),
    "cv_none": ("No classification record yet.", "Chưa có bản ghi phân loại."),
    "cv_decided_by": ("Decided by", "Người quyết định"),
    "cv_approved_by": ("Approved by", "Người phê duyệt"),
    "cv_valid_until": ("Review by", "Rà soát trước ngày"),
    "cv_review_due": ("review is due", "đến hạn rà soát"),
    "cv_inherited": (
        "Result taken from the provider (Circular 53 Art. 4(4))",
        "Kết quả kế thừa từ nhà cung cấp (Thông tư 53 Điều 4 khoản 4)",
    ),
    "cv_tree_changed": (
        "The tree file changed after this record was made.",
        "Tệp cây đã thay đổi sau khi bản ghi này được tạo.",
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
    "cv_evidence": ("Evidence pointer", "Con trỏ bằng chứng"),
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
        "These questions answer the node. An answer from a rule is shown; pick yes or no to set it yourself.",
        "Các câu hỏi này trả lời cho nút. Câu trả lời từ quy tắc được hiển thị; chọn có hoặc không để tự đặt.",
    ),
    "cv_sub_outcome": ("Decision 33 outcome", "Kết quả Quyết định 33"),
    "cv_inherited_label": ("The result is taken from the provider", "Kết quả lấy từ nhà cung cấp"),
    "cv_evaluate": ("Evaluate", "Đánh giá"),
    "cv_evaluate_hint": (
        "Shows the path for these answers. Nothing is stored.",
        "Hiển thị đường đi cho các câu trả lời này. Không lưu gì.",
    ),
    "cv_save": ("Save the record", "Lưu bản ghi"),
    "cv_approve": ("Approve", "Phê duyệt"),
    "cv_approve_hint": (
        "A different person from the one who decided, and not the system owner, approves. Only then does the risk level change (it never goes down here).",
        "Người phê duyệt phải khác người quyết định và không phải chủ sở hữu hệ thống. Chỉ khi đó mức rủi ro mới thay đổi (ở đây không bao giờ bị hạ xuống).",
    ),
    "cv_cannot_approve": (
        "You cannot approve this record: you decided it, you own the system, or you lack the permission.",
        "Bạn không thể phê duyệt bản ghi này: bạn đã quyết định nó, bạn sở hữu hệ thống, hoặc bạn không có quyền.",
    ),
    "cv_view_only": (
        "You can read this page. Deciding needs the permission systems.edit.",
        "Bạn chỉ xem được trang này. Quyết định cần quyền systems.edit.",
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
        "No extra duty from the classification.",
        "Phân loại không kéo theo nghĩa vụ bổ sung.",
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
    "cv_not_triggers": ("Not a trigger", "Không phải sự kiện kích hoạt"),
    "cv_records_n": ("Records for this system: {n}", "Số bản ghi của hệ thống này: {n}"),
    "cv_open_page": ("Open the classification tree", "Mở cây phân loại"),
    "cv_register_note": (
        "This is the path the rules and the Decision 33 answers give now. The record is made and approved on the Classify page of the system after you submit.",
        "Đây là đường đi mà các quy tắc và câu trả lời Quyết định 33 cho hiện tại. Bản ghi được tạo và phê duyệt ở trang Phân loại của hệ thống sau khi bạn gửi.",
    ),
    "cv_incomplete": (
        "The path does not end in an outcome yet.",
        "Đường đi chưa kết thúc ở một kết quả.",
    ),
    "cv_back": ("Back to the system", "Quay lại hệ thống"),
}
