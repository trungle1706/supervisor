# ruff: noqa: E501
"""UX5 overrides for package G2 (systems list and detail, wizard, candidates, onboard, integration,
tasks): shorter text, same keys. English and Vietnamese. Text that is removed is dropped in the
template under ``{% if ux5 %}``, not here."""

from __future__ import annotations

UX5: dict[str, tuple[str, str]] = {
    "sy_purpose": (
        "AI systems of the bank, with owner, stage and risk level.",
        "Các hệ thống AI của ngân hàng, kèm đơn vị sở hữu, giai đoạn và mức rủi ro.",
    ),
    "sy_rules_intro": (
        "Rules that assign guardians and duties to this system. The same inputs always give the same list.",
        "Các quy tắc gán bộ bảo vệ và nghĩa vụ cho hệ thống này. Cùng đầu vào luôn cho cùng danh sách.",
    ),
    "sy_cls_intro": (
        "Answer the 4 Decision 33 questions. Some answers fill from the system record. Nothing applies until a person applies it.",
        "Trả lời 4 câu hỏi theo Quyết định 33. Một số câu tự điền từ hồ sơ hệ thống. Không có gì được áp dụng cho đến khi một người áp dụng.",
    ),
    "sy_cls_why_min": ("Reason ({n}+ characters)", "Lý do (từ {n} ký tự)"),
    "rd_intro": (
        "Rules propose a status. A person confirms it. Pass needs evidence. A waiver needs a reason and a second person.",
        "Quy tắc đề xuất trạng thái. Một người xác nhận. Đạt cần bằng chứng. Miễn trừ cần lý do và người thứ hai.",
    ),
    "rk_illustrative_short": ("Illustrative bands", "Mức điểm minh họa"),
    "ux4b_risks_none": (
        "No active risk. Link an agent with risks, or add one in Risks.",
        "Chưa có rủi ro đang áp dụng. Hãy liên kết tác tử có rủi ro, hoặc thêm trong mục Rủi ro.",
    ),
    "ux4b_risks_line": (
        "{active} active risks ({inherited} inherited)",
        "{active} rủi ro đang áp dụng ({inherited} kế thừa)",
    ),
    "ux4b_policies_sum": ("Obligations that apply", "Nghĩa vụ áp dụng"),
    "ux4b_policies_none": ("No obligation applies yet.", "Chưa có nghĩa vụ nào áp dụng."),
    "ux4b_na_transparency_off": (
        "Transparency reports are switched off. Ask an administrator to turn them on.",
        "Báo cáo minh bạch đang tắt. Hãy nhờ quản trị viên bật.",
    ),
    "sgd_intro": (
        "Rules propose guardians, thresholds and limits. Nothing is attached until a person accepts.",
        "Quy tắc đề xuất bộ bảo vệ, ngưỡng và giới hạn. Không có gì được gắn cho đến khi một người chấp nhận.",
    ),
    "sgd_proof_hint": ("Run the pre-deploy test now.", "Chạy kiểm thử trước triển khai ngay."),
    "wf_request_hint": (
        "A second person must approve. You cannot approve your own request.",
        "Cần người thứ hai duyệt. Bạn không thể tự duyệt yêu cầu của mình.",
    ),
    "sy_stage_now": ("Stage", "Giai đoạn"),
    "sy_stage_needs_approval": ("Approval needed to enter", "Cần duyệt để chuyển sang"),
    "sy_tasks_no_agents": (
        "No agent is linked to this system yet. Link an agent to see this information.",
        "Chưa có tác tử nào liên kết với hệ thống này. Hãy liên kết một tác tử để xem thông tin này.",
    ),
    "du_reeval_hint": (
        "Re-run the matrix on the stored answers. Nothing is deleted.",
        "Chạy lại ma trận trên các câu trả lời đã lưu. Không xóa gì.",
    ),
    "du_refresh_hint": (
        "Read the live counts of the mapped controls (last {days} days). A full-coverage duty whose controls all work is closed. Partial and none are never closed here.",
        "Đọc số liệu trực tiếp của các kiểm soát đã ánh xạ ({days} ngày gần nhất). Nghĩa vụ bao phủ đầy đủ có mọi kiểm soát đang hoạt động sẽ được đóng. Bao phủ một phần hoặc chưa có không bao giờ đóng ở đây.",
    ),
    "tri_purpose": (
        "Workspace objects not yet registered as AI systems. Highest score first.",
        "Các đối tượng trong workspace chưa đăng ký thành hệ thống AI. Điểm cao xếp trước.",
    ),
    "ob_purpose_lead": (
        "Bring an agent under supervision in 6 steps. A person approves every step.",
        "Đưa một tác tử vào giám sát qua 6 bước. Một người duyệt từng bước.",
    ),
    "repo_path": (
        "Agent code folder (prefilled example; pick one from Candidates)",
        "Thư mục mã của tác tử (ví dụ điền sẵn; chọn từ Ứng viên)",
    ),
    "start_hint": (
        "Read-only. Secrets are removed before a model reads the code.",
        "Chỉ đọc. Bí mật được xóa trước khi mô hình đọc mã.",
    ),
    "no_runs": ("No onboarding runs yet.", "Chưa có lần tiếp nhận nào."),
    "int_purpose_lead": (
        "Readiness reports for agents to bring under Watch.",
        "Báo cáo mức sẵn sàng của các tác tử cần đưa vào giám sát.",
    ),
    "int_why": (
        "Patches are never applied here. The owning team applies them.",
        "Bản vá không bao giờ được áp dụng ở đây. Nhóm sở hữu áp dụng.",
    ),
    "int_none": (
        "No integration reports yet. Ask an administrator to run the advisor.",
        "Chưa có báo cáo tích hợp. Hãy nhờ quản trị viên chạy bộ tư vấn.",
    ),
    "tk_purpose": (
        "Tasks per system and lifecycle stage. A required task blocks the move to the next stage.",
        "Nhiệm vụ theo hệ thống và giai đoạn vòng đời. Nhiệm vụ bắt buộc chặn việc chuyển giai đoạn.",
    ),
    "tk_illustrative": (
        "Task sets are illustrative until the bank sets them.",
        "Bộ nhiệm vụ chỉ mang tính minh họa cho đến khi ngân hàng quy định.",
    ),
    "rg3_hint_source": (
        "Upload the code as a zip file, or skip and give a reason.",
        "Tải mã lên dạng zip, hoặc bỏ qua và nêu lý do.",
    ),
    "rg3_strip_title": ("Duties for this step", "Nghĩa vụ ở bước này"),
    "rg3_strip_hint": (
        "Duties that apply at this step. Status is set by rules.",
        "Các nghĩa vụ áp dụng ở bước này. Trạng thái do quy tắc đặt.",
    ),
    "rg3_skip_reason": (
        "Reason for no source (10+ characters). Saved with the draft.",
        "Lý do không có nguồn (từ 10 ký tự). Lưu cùng bản nháp.",
    ),
    "ik_hint": (
        "Upload code as a zip (max {mb} MB). Secrets are removed before storing.",
        "Tải mã lên dạng zip (tối đa {mb} MB). Bí mật được xóa trước khi lưu.",
    ),
    "ux4b_audit_pack_line": ("Build it on the Evidence page.", "Tạo ở trang Bằng chứng."),
    "ux4b_audit_pack_open": ("Open Evidence", "Mở trang Bằng chứng"),
    "sy_rv_none": (
        "No reviews yet. Reviews start at the Validation stage.",
        "Chưa có đợt rà soát. Rà soát bắt đầu ở giai đoạn Xác nhận.",
    ),
    "sy_col_components": ("Components", "Thành phần"),
    "sy_inherited": ("from parts", "từ thành phần"),
    "sy_cls_none_applied": ("Not classified yet.", "Chưa được phân loại."),
    "sy_cls_no_draft": (
        "No draft yet. Make one from the rules.",
        "Chưa có bản nháp. Hãy tạo từ quy tắc.",
    ),
    "sy_cls_remake": ("Discard draft and restart", "Hủy bản nháp và làm lại"),
    "sy_cls_outcome": ("Draft outcome", "Kết quả bản nháp"),
    "rg2_done_line": ("Next actions:", "Việc tiếp theo:"),
}
