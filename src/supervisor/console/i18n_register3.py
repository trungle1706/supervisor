# ruff: noqa: E501
"""Labels of the nine-step register workflow (WP-C3), English and Vietnamese, prefix ``rg3_``.
Merged into ``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

RG3: dict[str, tuple[str, str]] = {
    "rg3_step_source": ("Source", "Nguồn"),
    "rg3_step_facts": ("Facts", "Dữ kiện"),
    "rg3_step_identify": ("Identify and AI type", "Nhận diện và loại AI"),
    "rg3_step_classify": ("Classify", "Phân loại"),
    "rg3_step_assess": ("Risk assessment", "Đánh giá rủi ro"),
    "rg3_step_duties": ("Duties", "Nghĩa vụ"),
    "rg3_step_guardians": ("Suitable guardians", "Bộ bảo vệ phù hợp"),
    "rg3_step_review": ("Review and submit", "Rà soát và gửi"),
    "rg3_step_done": ("Done", "Hoàn tất"),
    "rg3_hint_source": (
        "Upload the code as a zip file or give a git address. Or go on without a source and say why.",
        "Tải mã nguồn lên dạng zip hoặc nhập địa chỉ git. Hoặc tiếp tục không có nguồn và nêu lý do.",
    ),
    "rg3_hint_facts": (
        "The facts read from the source. You cannot edit them here. Press Re-read to build them again.",
        "Các dữ kiện đọc từ nguồn. Bạn không sửa được ở đây. Nhấn Đọc lại để dựng lại.",
    ),
    "rg3_hint_identify": (
        "Fields filled from the facts carry a 'from facts' mark. You can change every field and every AI type flag.",
        "Các trường điền từ dữ kiện có nhãn 'từ dữ kiện'. Bạn có thể sửa mọi trường và mọi cờ loại AI.",
    ),
    "rg3_hint_classify": (
        "Walk the classification tree. The approval stays on the system page after you submit.",
        "Đi theo cây phân loại. Việc phê duyệt vẫn ở trang hệ thống sau khi bạn gửi.",
    ),
    "rg3_hint_assess": (
        "The eight risk types of Circular 53 Art. 14(3). Confirm the proposal or run the assessment.",
        "Tám loại rủi ro theo Điều 14(3) Thông tư 53. Xác nhận đề xuất hoặc chạy đánh giá.",
    ),
    "rg3_hint_duties": (
        "Duties that follow from the classification and the assessment are pre-filled and marked. You can change them.",
        "Các nghĩa vụ suy ra từ phân loại và đánh giá được điền sẵn và có nhãn. Bạn có thể sửa.",
    ),
    "rg3_hint_guardians": (
        "The pre-deploy report and the proposed guardian set. You can run the report from here.",
        "Báo cáo trước triển khai và bộ lớp bảo vệ đề xuất. Bạn có thể chạy báo cáo ở đây.",
    ),
    "rg3_hint_review": (
        "Check the summary. Submit writes the records and asks for the stage approval.",
        "Kiểm tra tóm tắt. Gửi sẽ ghi các bản ghi và yêu cầu phê duyệt giai đoạn.",
    ),
    "rg3_hint_done": ("Done.", "Hoàn tất."),
    "rg3_turn_on": (
        "This step is not available yet. Ask an admin to turn on {flag}, or continue without it.",
        "Bước này chưa dùng được. Nhờ quản trị viên bật {flag}, hoặc tiếp tục mà không cần bước này.",
    ),
    "rg3_skip_reason": ("Reason to go on without a source", "Lý do tiếp tục không có nguồn"),
    "rg3_skip_hint": (
        "At least 10 characters. The reason is saved with the draft and shown on the compliance strip.",
        "Ít nhất 10 ký tự. Lý do được lưu cùng bản nháp và hiện trên dải tuân thủ.",
    ),
    "rg3_skipped": ("No source", "Không có nguồn"),
    "rg3_skip": ("Skip, no source", "Bỏ qua, không có nguồn"),
    "rg3_facts_next": (
        "Continue to carry the facts into step 3. Fields you already changed are kept.",
        "Tiếp tục để đưa dữ kiện sang bước 3. Các trường bạn đã sửa được giữ nguyên.",
    ),
    "rg3_facts_used": ("Filled in from facts v1, attempt {n}.", "Điền sẵn từ dữ kiện v1, lần {n}."),
    "rg3_from_facts": ("from facts", "từ dữ kiện"),
    "rg3_from_classification": ("from classification", "từ phân loại"),
    "rg3_from_assessment": ("from assessment", "từ đánh giá"),
    "rg3_from_ai_type": ("from AI type", "từ loại AI"),
    "rg3_ai_type": ("AI type", "Loại AI"),
    "rg3_proposed_type": ("Suggested type", "Loại gợi ý"),
    "rg3_flag_generative": ("Generative", "Sinh nội dung"),
    "rg3_flag_agentic": ("Agentic (uses tools)", "Tác tử (dùng công cụ)"),
    "rg3_flag_customer_facing": ("Customer facing", "Tiếp xúc khách hàng"),
    "rg3_flag_decides": ("Decides (not only supports)", "Ra quyết định (không chỉ hỗ trợ)"),
    "rg3_flag_src_rule": ("by rule", "theo quy tắc"),
    "rg3_flag_src_person": ("set by a person", "do người đặt"),
    "rg3_flag_rule_generative": (
        "A model or endpoint is used, or a model family is set.",
        "Có dùng mô hình hoặc endpoint, hoặc đã nêu họ mô hình.",
    ),
    "rg3_flag_rule_agentic": (
        "The agent uses a tool, or its autonomy level is L2 or higher.",
        "Tác tử dùng công cụ, hoặc mức tự chủ từ L2 trở lên.",
    ),
    "rg3_flag_rule_customer_facing": ("The users are customers.", "Người dùng là khách hàng."),
    "rg3_flag_rule_decides": (
        "Credit decision, decision-type system, or an agent with no human control.",
        "Quyết định tín dụng, hệ thống loại ra quyết định, hoặc tác tử không có kiểm soát của con người.",
    ),
    "rg3_why_type_flags": ("from the AI type", "từ loại AI"),
    "rg3_system_made": (
        "Continue saves the AI system as a draft. Later steps build on it.",
        "Tiếp tục sẽ lưu hệ thống AI ở trạng thái nháp. Các bước sau dựa trên bản này.",
    ),
    "rg3_need_step3": (
        "Save step 3 first. The AI system is created there.",
        "Hãy lưu bước 3 trước. Hệ thống AI được tạo ở bước đó.",
    ),
    "rg3_class_approval_note": (
        "Save the classification in the panel above. A second approver approves it on the system page.",
        "Lưu phân loại ở khung trên. Người phê duyệt thứ hai phê duyệt tại trang hệ thống.",
    ),
    "rg3_assess_note": (
        "Results are suggestions. Confirm each risk type to make it final.",
        "Kết quả chỉ là gợi ý. Hãy xác nhận từng loại rủi ro để chốt.",
    ),
    "rg3_prefilled": ("Pre-filled duties", "Nghĩa vụ điền sẵn"),
    "rg3_prefilled_hint": (
        "Duties already settled by earlier steps: the classification level and the assessment reports.",
        "Các nghĩa vụ đã được xác định ở bước trước: mức phân loại và báo cáo đánh giá.",
    ),
    "rg3_level_is": ("Level: {level}.", "Mức: {level}."),
    "rg3_source": ("Source", "Nguồn gốc"),
    "rg3_confirmed": ("confirmed", "đã xác nhận"),
    "rg3_proposal": ("suggestion", "gợi ý"),
    "rg3_reapply": ("Fill in again", "Điền sẵn lại"),
    "rg3_stage_request": (
        "Submit asks for approval to move to stage {stage}. A second approver answers on the system page.",
        "Khi gửi, hệ thống xin phê duyệt chuyển sang giai đoạn {stage}. Người phê duyệt thứ hai trả lời tại trang hệ thống.",
    ),
    "rg3_stage_none": (
        "No stage move needs approval from here.",
        "Không có việc chuyển giai đoạn nào cần phê duyệt từ bước này.",
    ),
    "rg3_submit": ("Submit and ask for approval", "Gửi và yêu cầu phê duyệt"),
    "rg3_w_stage": ("Stage approval request", "Yêu cầu phê duyệt giai đoạn"),
    "rg3_strip_title": ("Compliance strip", "Dải tuân thủ"),
    "rg3_attempt": ("attempt {n}", "lần {n}"),
    "rg3_strip_hint": (
        "Articles that apply at this step. A rule sets each status from the draft and the records. Not legal advice.",
        "Các điều luật áp dụng ở bước này. Một quy tắc đặt từng trạng thái từ bản nháp và các bản ghi. Không phải tư vấn pháp lý.",
    ),
    "rg3_st_met": ("met", "đạt"),
    "rg3_st_open": ("open", "còn mở"),
    "rg3_st_not_applicable": ("not applicable", "không áp dụng"),
    "rg3_evidence": ("Evidence", "Bằng chứng"),
    "rg3_when_high": ("high risk only", "chỉ rủi ro cao"),
    "rg3_when_medium_high": ("medium and high risk", "rủi ro trung bình và cao"),
    "rg3_links": ("Where to look next", "Xem tiếp ở đâu"),
    "rg3_link_agent": ("Agent page", "Trang tác tử"),
    "rg3_link_facts": ("Facts tab", "Tab Dữ kiện"),
    "rg3_link_predeploy": ("Pre-deploy tab", "Tab Trước triển khai"),
    "rg3_link_class": ("Classification tab", "Tab Phân loại"),
    "rg3_link_riskdim": ("Risk assessment tab", "Tab Đánh giá rủi ro"),
    "rg3_link_approval": ("Tasks and stage approval", "Nhiệm vụ và phê duyệt giai đoạn"),
}
