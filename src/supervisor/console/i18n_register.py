# ruff: noqa: E501
"""Labels of the register workflow v2 (WP-N3), English and Vietnamese, prefix ``rg2_``.
Merged into ``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

RG2: dict[str, tuple[str, str]] = {
    "rg2_title": ("Register an AI system", "Đăng ký hệ thống AI"),
    "rg2_steps": ("Steps", "Các bước"),
    "rg2_step_1": ("Identify", "Nhận diện"),
    "rg2_step_2": ("AI information", "Thông tin AI"),
    "rg2_step_3": ("Pre-deployment check", "Kiểm tra trước triển khai"),
    "rg2_step_4": ("Quick risk assessment", "Đánh giá rủi ro nhanh"),
    "rg2_step_5": ("Guardian tools", "Công cụ bảo vệ"),
    "rg2_step_6": ("Review and submit", "Xem lại và gửi"),
    "rg2_hint_1": (
        "Name the system, say what kind of object it is and who owns it.",
        "Đặt tên hệ thống, nêu loại đối tượng và người chịu trách nhiệm.",
    ),
    "rg2_hint_2": (
        "Each field shows a suggestion with its reason. One click accepts it. A value you change "
        "is marked as set by a person.",
        "Mỗi trường có gợi ý kèm lý do. Một cú nhấp để chấp nhận. Giá trị bạn sửa được đánh dấu "
        "là do người đặt.",
    ),
    "rg2_hint_3": (
        "Read-only checks. Each gap has a fix. Nothing is applied.",
        "Các kiểm tra chỉ đọc. Mỗi thiếu sót có cách sửa. Không có gì được áp dụng.",
    ),
    "rg2_hint_4": (
        "The rules prefill the Decision 33 questions. Answer the open ones. Nothing is applied "
        "here.",
        "Các quy tắc điền sẵn câu hỏi Quyết định 33. Trả lời các câu còn mở. Không áp dụng gì ở "
        "bước này.",
    ),
    "rg2_hint_5": (
        "The floor is locked on. Other features start on; set one off only with a reason to.",
        "Mức sàn luôn bật. Các tính năng khác mặc định bật; chỉ tắt khi có lý do.",
    ),
    "rg2_hint_6": (
        "Check everything. Submit writes the draft system and opens the tasks.",
        "Kiểm tra tất cả. Gửi sẽ ghi hệ thống ở trạng thái nháp và mở các nhiệm vụ.",
    ),
    "rg2_from_scan": (
        "Prefilled from the workspace scan.",
        "Điền sẵn từ lần quét workspace.",
    ),
    "rg2_from_policy": (
        "Prefilled from the agent manifest in the policy.",
        "Điền sẵn từ bản kê khai tác tử trong chính sách.",
    ),
    "rg2_from_kind_scan": ("Scan", "Quét"),
    "rg2_from_kind_policy": ("Policy", "Chính sách"),
    "rg2_from_kind_blank": ("New", "Mới"),
    "rg2_f_name": ("Name", "Tên"),
    "rg2_f_kind": ("Kind of object", "Loại đối tượng"),
    "rg2_f_agent_id": ("Agent id (optional)", "Mã tác tử (tùy chọn)"),
    "rg2_f_owner_user": ("Owner (user)", "Người chịu trách nhiệm"),
    "rg2_f_owner_team": ("Owner team", "Nhóm chịu trách nhiệm"),
    "rg2_f_description": ("Description", "Mô tả"),
    "rg2_f_purpose": ("Purpose", "Mục đích"),
    "rg2_f_system_type": ("System type", "Loại hệ thống"),
    "rg2_f_org_role": ("Role of the bank", "Vai trò của ngân hàng"),
    "rg2_f_user_segment": ("User segment", "Nhóm người dùng"),
    "rg2_f_personal_data": ("Personal data", "Dữ liệu cá nhân"),
    "rg2_f_human_control": ("Human control", "Kiểm soát của con người"),
    "rg2_f_autonomy_level": ("Autonomy level", "Mức tự chủ"),
    "rg2_f_money_movement": ("Moves money", "Chuyển tiền"),
    "rg2_f_credit_decision": ("Makes a credit decision", "Ra quyết định tín dụng"),
    "rg2_f_model_family": ("Model family", "Họ mô hình"),
    "rg2_f_data_sources": ("Data sources", "Nguồn dữ liệu"),
    "rg2_kind_app": ("App", "Ứng dụng"),
    "rg2_kind_endpoint": ("Serving endpoint", "Endpoint phục vụ"),
    "rg2_kind_genie": ("Genie space", "Không gian Genie"),
    "rg2_kind_job": ("Job", "Công việc"),
    "rg2_kind_other": ("Other", "Khác"),
    "rg2_agent_id_hint": (
        "Give an id only if the object is an agent that calls the gate. The agent row is made "
        "only when the policy already knows the id.",
        "Chỉ nhập mã nếu đối tượng là tác tử gọi cổng. Dòng tác tử chỉ được tạo khi chính sách "
        "đã biết mã đó.",
    ),
    "rg2_owner_scoped": (
        "Owner: {user} (you). A scoped person registers for themselves.",
        "Người chịu trách nhiệm: {user} (bạn). Người có phạm vi hẹp chỉ đăng ký cho chính mình.",
    ),
    "rg2_suggested": ("Suggested", "Gợi ý"),
    "rg2_accept": ("Use this", "Dùng gợi ý"),
    "rg2_accept_all": ("Accept all suggestions of this step", "Chấp nhận mọi gợi ý của bước này"),
    "rg2_by_scan": ("suggested (scan)", "gợi ý (quét)"),
    "rg2_by_policy": ("suggested (policy)", "gợi ý (chính sách)"),
    "rg2_by_person": ("set by person", "do người đặt"),
    "rg2_src_scan": ("scan", "quét"),
    "rg2_src_policy": ("policy", "chính sách"),
    "rg2_src_person": ("person", "người"),
    "rg2_yes": ("Yes", "Có"),
    "rg2_no": ("No", "Không"),
    "rg2_back": ("Back", "Quay lại"),
    "rg2_continue": ("Save and continue", "Lưu và tiếp tục"),
    "rg2_off_reason": ("Reason if set off (optional)", "Lý do nếu tắt (không bắt buộc)"),
    "rg2_saved": ("Saved", "Đã lưu"),
    "rg2_save_later": ("Save for later", "Lưu để làm sau"),
    "rg2_my_drafts": ("My drafts", "Bản nháp của tôi"),
    # reasons
    "rg2_why_name_node": ("name of the scanned object", "tên của đối tượng đã quét"),
    "rg2_why_kind_node": ("workspace kind of the object", "loại đối tượng trong workspace"),
    "rg2_why_type_node": (
        "an app, endpoint or space that answers people",
        "ứng dụng, endpoint hoặc không gian trả lời người dùng",
    ),
    "rg2_why_type_job": (
        "a job runs steps without a chat",
        "công việc chạy các bước không có hội thoại",
    ),
    "rg2_why_org_role": (
        "the bank deploys what it runs",
        "ngân hàng triển khai những gì mình chạy",
    ),
    "rg2_why_segment": (
        "a workspace object is for staff by default",
        "đối tượng workspace mặc định dành cho nhân viên",
    ),
    "rg2_why_human_none": (
        "the scan cannot see an approval step; the safe side is none",
        "lần quét không thấy bước phê duyệt; mặc định an toàn là không có",
    ),
    "rg2_why_agent_hosted": (
        "an agent in the inventory runs on this object",
        "một tác tử trong kiểm kê chạy trên đối tượng này",
    ),
    "rg2_why_owner_map": (
        "owner map in config/governance.yaml",
        "bản đồ chủ sở hữu trong config/governance.yaml",
    ),
    "rg2_why_desc_scan": ("built from the scan evidence", "tạo từ bằng chứng của lần quét"),
    "rg2_why_purpose_scan": (
        "built from the scan evidence; edit it",
        "tạo từ bằng chứng của lần quét; hãy chỉnh sửa",
    ),
    "rg2_why_pd_tables": (
        "it reads Unity Catalog tables; safe side",
        "đọc bảng Unity Catalog; mặc định an toàn",
    ),
    "rg2_why_sources_tables": (
        "tables the object reads or writes",
        "các bảng đối tượng đọc hoặc ghi",
    ),
    "rg2_why_auto_proposal": (
        "level proposed by the onboarding run",
        "mức do lần onboarding đề xuất",
    ),
    "rg2_why_auto_tools": ("it uses tools", "có dùng công cụ"),
    "rg2_why_auto_notools": ("no tools found", "không thấy công cụ"),
    "rg2_why_money_tool": ("a money tool is linked", "có công cụ tiền được liên kết"),
    "rg2_why_money_none": ("no money tool found", "không thấy công cụ tiền"),
    "rg2_why_credit_tool": ("a credit tool is linked", "có công cụ tín dụng được liên kết"),
    "rg2_why_credit_none": ("no credit tool found", "không thấy công cụ tín dụng"),
    "rg2_why_family_model": ("family of the linked model", "họ của mô hình được liên kết"),
    "rg2_why_family_provider": (
        "external provider of the endpoint",
        "nhà cung cấp bên ngoài của endpoint",
    ),
    "rg2_why_name_policy": ("name in the policy manifest", "tên trong bản kê khai chính sách"),
    "rg2_why_kind_policy": (
        "the policy does not say where it runs",
        "chính sách không nói nó chạy ở đâu",
    ),
    "rg2_why_agent_policy": ("agent id in the policy", "mã tác tử trong chính sách"),
    "rg2_why_owner_policy": (
        "owner in the policy manifest",
        "người chịu trách nhiệm trong bản kê khai",
    ),
    "rg2_why_family_policy": (
        "model family in the policy manifest",
        "họ mô hình trong bản kê khai",
    ),
    "rg2_why_desc_policy": ("built from the policy manifest", "tạo từ bản kê khai chính sách"),
    "rg2_why_purpose_policy": (
        "built from the policy manifest; edit it",
        "tạo từ bản kê khai chính sách; hãy chỉnh sửa",
    ),
    # step 3
    "rg2_run_check": ("Run the readiness check", "Chạy kiểm tra mức sẵn sàng"),
    "rg2_no_repo_right": (
        "The readiness check on a repository folder needs the right to start onboarding and a "
        "folder inside ONBOARD_ALLOWED_ROOTS.",
        "Kiểm tra mức sẵn sàng trên thư mục mã nguồn cần quyền bắt đầu onboarding và một thư "
        "mục trong ONBOARD_ALLOWED_ROOTS.",
    ),
    "rg2_gaps": ("Gaps and fixes", "Thiếu sót và cách sửa"),
    "rg2_check": ("Check", "Kiểm tra"),
    "rg2_result": ("Result", "Kết quả"),
    "rg2_fix": ("Fix", "Cách sửa"),
    "rg2_st_ok": ("ok", "đạt"),
    "rg2_st_gap": ("gap", "thiếu"),
    "rg2_st_info": ("not checked", "chưa kiểm tra"),
    "rg2_st_failed": ("failed", "lỗi"),
    "rg2_st_skipped": ("skipped", "bỏ qua"),
    "rg2_chk_readiness": ("Readiness advisor", "Bộ tư vấn mức sẵn sàng"),
    "rg2_chk_policy": ("Agent id is in a policy", "Mã tác tử có trong chính sách"),
    "rg2_chk_rules": (
        "Policy rules in scope of the agent",
        "Quy tắc chính sách áp dụng cho tác tử",
    ),
    "rg2_chk_tools": ("Tools declared in the policy", "Công cụ khai báo trong chính sách"),
    "rg2_chk_sp": ("Service principal identity mapped", "Danh tính service principal đã ánh xạ"),
    "rg2_fix_readiness": (
        "Apply the patches the advisor lists, then run it again.",
        "Áp dụng các bản vá bộ tư vấn liệt kê, rồi chạy lại.",
    ),
    "rg2_fix_readiness_run": (
        "Give a repository folder and run the check (optional).",
        "Nhập thư mục mã nguồn và chạy kiểm tra (tùy chọn).",
    ),
    "rg2_fix_no_agent": (
        "No agent id: the policy and identity checks do not apply.",
        "Không có mã tác tử: bỏ qua kiểm tra chính sách và danh tính.",
    ),
    "rg2_fix_policy_missing": (
        "Add the agent to the policy file (agents section). A task will open.",
        "Thêm tác tử vào tệp chính sách (mục agents). Một nhiệm vụ sẽ được mở.",
    ),
    "rg2_fix_rules": (
        "Add a rule whose scope includes the agent.",
        "Thêm quy tắc có phạm vi gồm tác tử.",
    ),
    "rg2_fix_tools": (
        "Declare the tools of the agent with a risk class in the policy.",
        "Khai báo công cụ của tác tử kèm nhóm rủi ro trong chính sách.",
    ),
    "rg2_fix_sp": (
        "Add the service principal and the agent id to config/agent_identities.yaml. A task will open.",
        "Thêm service principal và mã tác tử vào config/agent_identities.yaml. Một nhiệm vụ sẽ được mở.",
    ),
    # step 4
    "rg2_need_steps_12": ("Finish steps 1 and 2 first.", "Hãy hoàn tất bước 1 và 2 trước."),
    "rg2_rule": ("rule", "quy tắc"),
    "rg2_inherited": ("Inherited risk over the graph", "Rủi ro kế thừa theo đồ thị"),
    "rg2_inherited_none": ("not available", "không có"),
    "rg2_question": ("Question", "Câu hỏi"),
    "rg2_answer": ("Answer", "Trả lời"),
    "rg2_justification": ("Justification", "Lý do"),
    "rg2_qsrc_rules": ("from the rules", "từ quy tắc"),
    "rg2_qsrc_ai_prefill": ("from the AI prefill", "từ AI điền sẵn"),
    "rg2_qsrc_person": ("person", "người"),
    "rg2_nothing_applied_4": (
        "This stays a draft. A person applies the classification later on the system page.",
        "Phần này vẫn là bản nháp. Một người sẽ áp dụng phân loại sau, trên trang hệ thống.",
    ),
    # step 5
    "rg2_bindings_off": (
        "Guardian bindings are off here (GUARDIAN_BINDINGS_ENABLED=1 turns them on). Every feature stays on.",
        "Ràng buộc công cụ bảo vệ đang tắt (GUARDIAN_BINDINGS_ENABLED=1 để bật). Mọi tính năng giữ bật.",
    ),
    "rg2_policy_rules_n": ("Policy rules in scope: {n}", "Quy tắc chính sách áp dụng: {n}"),
    "rg2_feature": ("Feature", "Tính năng"),
    "rg2_group": ("Group", "Nhóm"),
    "rg2_state": ("State", "Trạng thái"),
    "rg2_grp_detect": ("Detector", "Bộ phát hiện"),
    "rg2_grp_gate": ("Gate", "Cổng"),
    "rg2_grp_judge": ("Judge", "Giám khảo"),
    "rg2_grp_monitor": ("Monitor", "Giám sát"),
    "rg2_floor_on": ("On (floor, locked)", "Bật (mức sàn, khóa)"),
    "rg2_on": ("On", "Bật"),
    "rg2_unavailable": ("Not available here", "Không có ở đây"),
    "rg2_needs": ("needs {flag}", "cần {flag}"),
    "rg2_guardian_hint": (
        "A row is written only for a feature you set off. A floor feature cannot be set off.",
        "Chỉ ghi dòng cho tính năng bạn tắt. Tính năng mức sàn không thể tắt.",
    ),
    # step 6, result
    "rg2_will_write": ("What the submit writes", "Những gì gửi sẽ ghi"),
    "rg2_w_system": ("AI system (draft)", "Hệ thống AI (nháp)"),
    "rg2_w_team": ("Owner on the system team", "Người chịu trách nhiệm trong nhóm hệ thống"),
    "rg2_w_link_node": ("Link to the scanned object", "Liên kết tới đối tượng đã quét"),
    "rg2_w_agent": ("Agent row", "Dòng tác tử"),
    "rg2_w_link_agent": ("Link to the agent", "Liên kết tới tác tử"),
    "rg2_w_class": ("Decision 33 draft (not applied)", "Bản nháp Quyết định 33 (chưa áp dụng)"),
    "rg2_w_binding": ("Guardian set off:", "Công cụ bảo vệ tắt:"),
    "rg2_w_no_binding": (
        "No guardian binding row (nothing set off)",
        "Không có dòng ràng buộc (không tắt gì)",
    ),
    "rg2_w_tasks": ("Intake tasks", "Nhiệm vụ tiếp nhận"),
    "rg2_answers_n": ("{n} answers", "{n} câu trả lời"),
    "rg2_tasks_open": ("Tasks that will open", "Nhiệm vụ sẽ được mở"),
    "rg2_task_SYS-INTAKE-CONFIRM": ("Confirm the intake answers", "Xác nhận câu trả lời tiếp nhận"),
    "rg2_task_SYS-INTAKE-CHECKS": (
        "Review the checks and the classification proposal",
        "Xem lại kiểm tra và đề xuất phân loại",
    ),
    "rg2_task_SYS-REG-POLICY": ("Add the agent to the policy", "Thêm tác tử vào chính sách"),
    "rg2_task_SYS-REG-SPID": (
        "Map the service principal identity",
        "Ánh xạ danh tính service principal",
    ),
    "rg2_who_approves": ("Who approves what", "Ai phê duyệt gì"),
    "rg2_appr_intake": (
        "The owner confirms the intake answers.",
        "Người chịu trách nhiệm xác nhận câu trả lời tiếp nhận.",
    ),
    "rg2_appr_class": (
        "A person who is not the owner applies the classification.",
        "Một người không phải chủ sở hữu áp dụng phân loại.",
    ),
    "rg2_appr_stage": (
        "A stage move needs an approved stage approval.",
        "Chuyển giai đoạn cần phê duyệt giai đoạn.",
    ),
    "rg2_submit": ("Submit", "Gửi"),
    "rg2_abandon": ("Drop this draft", "Bỏ bản nháp này"),
    "rg2_done": ("Registered as a draft.", "Đã đăng ký ở trạng thái nháp."),
    "rg2_done_line": (
        "Nothing is applied. These are the next actions.",
        "Chưa áp dụng gì. Đây là các việc tiếp theo.",
    ),
    "rg2_written": ("What was written", "Những gì đã ghi"),
    "rg2_next": ("Next actions", "Việc tiếp theo"),
    "rg2_next_intake": ("Confirm the intake answers", "Xác nhận câu trả lời tiếp nhận"),
    "rg2_next_class": ("Review and apply the classification", "Xem lại và áp dụng phân loại"),
    "rg2_next_policy": ("Add the agent to the policy file", "Thêm tác tử vào tệp chính sách"),
    "rg2_next_spid": (
        "Add the service principal identity to config/agent_identities.yaml",
        "Thêm danh tính service principal vào config/agent_identities.yaml",
    ),
    "rg2_next_running": (
        "Later: move the agent from SHADOW to RUNNING",
        "Sau này: chuyển tác tử từ SHADOW sang RUNNING",
    ),
    "rg2_open_system": ("Open the system", "Mở hệ thống"),
    "rg2_register_another": ("Register another", "Đăng ký thêm"),
    # list
    "rg2_drafts": ("My registration drafts", "Bản nháp đăng ký của tôi"),
    "rg2_register_btn": ("+ Register", "+ Đăng ký"),
    "rg2_source": ("Source", "Nguồn"),
    "rg2_step_word": ("Step", "Bước"),
    "rg2_updated": ("Updated", "Cập nhật"),
    "rg2_resume": ("Resume", "Tiếp tục"),
    "rg2_unnamed": ("(no name yet)", "(chưa có tên)"),
    "rg2_no_drafts": ("No open drafts", "Không có bản nháp"),
    "rg2_no_drafts_line": (
        "Start a registration with + Register.",
        "Bắt đầu đăng ký bằng + Đăng ký.",
    ),
}
