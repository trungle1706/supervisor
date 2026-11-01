# ruff: noqa: E501
"""Labels added by UI audit batch 3 (docs/ui/redundancy-audit.md): names, labels, raw ids,
en/vi. Prefixes ``lbl_`` (label_for in ``labels.py``) and ``b3_``. Merged into ``i18n._T`` by the
last lines of ``i18n.py``.

* ``NEW``     keys that did not exist.
* ``CHANGED`` existing keys with a new text. They are merged into the base table and also listed
  as a UX5 override (``i18n_ux5_b3.py``), so the new text wins whether CONSOLE_UX5 is on or off.
"""

from __future__ import annotations

NEW: dict[str, tuple[str, str]] = {
    "lbl_demo_data": ("Demo data", "Dữ liệu minh họa"),
    "b3_int_none_admin": (
        "No integration reports yet. Run the advisor from the command line:",
        "Chưa có báo cáo tích hợp. Chạy bộ tư vấn từ dòng lệnh:",
    ),
    "b3_col_owner": ("Owner", "Chủ sở hữu"),
    "b3_inherited_tip": (
        "Risk level is taken from this system's agents, models and tools. Nobody set it by hand.",
        "Mức rủi ro được lấy từ các tác tử, mô hình và công cụ của hệ thống này. Không ai đặt thủ công.",
    ),
    "b3_not_legal": ("Not legal advice", "Không phải tư vấn pháp lý"),
    "g3_kind_catalogue": ("Guardian feature", "Tính năng bảo vệ"),
    # UI-171: the guardian factory form shows words, not stored values
    "lbl_gf_type_regex": ("Pattern (regex)", "Mẫu (regex)"),
    "lbl_gf_type_keyword_list": ("Keyword list", "Danh sách từ khóa"),
    "lbl_gf_type_classifier": ("Classifier", "Bộ phân loại"),
    "lbl_gf_type_judge_prompt": ("Judge prompt", "Câu lệnh cho giám khảo AI"),
    "lbl_gf_type_policy": ("Policy rule", "Quy tắc chính sách"),
    "lbl_gf_stage_preflight": ("Before the run", "Trước khi chạy"),
    "lbl_gf_stage_input": ("Input to the agent", "Đầu vào của tác tử"),
    "lbl_gf_stage_tool_call": ("Tool call", "Lệnh gọi công cụ"),
    "lbl_gf_stage_output": ("Reply of the agent", "Câu trả lời của tác tử"),
    "lbl_gf_act_block": ("Block", "Chặn"),
    "lbl_gf_act_redact": ("Mask", "Che"),
    "lbl_gf_act_require_approval": ("Ask for approval", "Yêu cầu phê duyệt"),
    "lbl_gf_act_log": ("Log only", "Chỉ ghi nhận"),
    "lbl_gf_group_model_risk": ("Model risk", "Rủi ro mô hình"),
    "lbl_gf_group_data": ("Data", "Dữ liệu"),
    "lbl_gf_group_cyber": ("Cyber security", "An ninh mạng"),
    "lbl_gf_group_legal": ("Legal", "Pháp chế"),
    "lbl_gf_group_third_party": ("Third party", "Bên thứ ba"),
    "lbl_gf_group_ethics": ("Ethics", "Đạo đức"),
    "lbl_gf_group_platform": ("Platform", "Nền tảng"),
    # UI-005 / UI-340: task titles come from config/tasks.yaml templates, so they are translated by code
    "lbl_task_INI_REGISTER": (
        "Register the agent in the inventory and name the owner",
        "Đăng ký tác tử vào kho kiểm kê và nêu tên chủ sở hữu",
    ),
    "lbl_task_INI_PURPOSE": (
        "Write the intended use and the limits of use",
        "Viết mục đích sử dụng và giới hạn sử dụng",
    ),
    "lbl_task_INI_D33": (
        "Classify the agent under Decision 33 and record the class",
        "Phân loại tác tử theo Quyết định 33 và ghi lại nhóm",
    ),
    "lbl_task_INI_RISKS": (
        "Enter the first risks in the risk register",
        "Nhập các rủi ro đầu tiên vào sổ đăng ký rủi ro",
    ),
    "lbl_task_DES_TOOLS": (
        "Approve the list of tools the agent may call",
        "Duyệt danh sách công cụ mà tác tử được gọi",
    ),
    "lbl_task_DES_DATA": (
        "Describe the data the agent reads and the personal data classes",
        "Mô tả dữ liệu tác tử đọc và các nhóm dữ liệu cá nhân",
    ),
    "lbl_task_DES_CONTROLS": (
        "Map the controls to the obligations and risks of the agent",
        "Ánh xạ các biện pháp kiểm soát với nghĩa vụ và rủi ro của tác tử",
    ),
    "lbl_task_DES_DPIA": (
        "Prepare the personal data impact assessment",
        "Lập đánh giá tác động đến dữ liệu cá nhân",
    ),
    "lbl_task_DES_D33": (
        "Plan the duties of a Decision 33 high-risk system (registration, notice, oversight)",
        "Lập kế hoạch cho các nghĩa vụ của hệ thống rủi ro cao theo Quyết định 33 (đăng ký, thông báo, giám sát)",
    ),
    "lbl_task_VAL_REDTEAM": (
        "Run the agentic red-team pack and clear every failed metric",
        "Chạy gói kiểm thử đối kháng (red team) cho tác tử và xử lý mọi chỉ số không đạt",
    ),
    "lbl_task_VAL_PII": (
        "Run the personal data canary pack",
        "Chạy gói kiểm thử dữ liệu cá nhân (canary)",
    ),
    "lbl_task_VAL_INJECT": (
        "Run the indirect injection pack",
        "Chạy gói kiểm thử tiêm lệnh gián tiếp",
    ),
    "lbl_task_VAL_FAIR": (
        "Review fairness results on the agent's decisions",
        "Rà soát kết quả công bằng của các quyết định của tác tử",
    ),
    "lbl_task_VAL_SECOND": (
        "Independent review of the validation report by the second line",
        "Tuyến phòng vệ thứ hai rà soát độc lập báo cáo thẩm định",
    ),
    "lbl_task_DEP_SHADOW": (
        "Run in SHADOW and review the list of calls the gate would have stopped",
        "Chạy ở chế độ SHADOW và rà soát danh sách lệnh gọi mà cổng sẽ chặn",
    ),
    "lbl_task_DEP_LAUNCH": (
        "Obtain a GO from the launch report",
        "Nhận kết luận GO từ báo cáo ra mắt",
    ),
    "lbl_task_DEP_OVERSIGHT": (
        "Name who pauses the agent and the two people who approve a resume",
        "Nêu tên người tạm dừng tác tử và hai người duyệt khi tiếp tục",
    ),
    "lbl_task_DEP_D33": (
        "Confirm human supervision for the Decision 33 high-risk class before enforcement",
        "Xác nhận việc giám sát của con người cho nhóm rủi ro cao theo Quyết định 33 trước khi thực thi",
    ),
    "lbl_task_OPS_OVERSIGHT": (
        "Review the human oversight metrics and record that the agent is healthy",
        "Rà soát các chỉ số giám sát của con người và ghi nhận tác tử hoạt động tốt",
    ),
    "lbl_task_OPS_CHAIN": (
        "Verify the evidence chain and record the result",
        "Kiểm tra chuỗi bằng chứng và ghi lại kết quả",
    ),
    "lbl_task_OPS_MASK": (
        "Personal data masking shows working evidence",
        "Việc che dữ liệu cá nhân có bằng chứng đang hoạt động",
    ),
    "lbl_task_OPS_RESUME_2P": (
        "Two-person resume is approved and tested (a second person approves every resume)",
        "Việc tiếp tục bởi hai người đã được duyệt và thử nghiệm (người thứ hai duyệt mọi lần tiếp tục)",
    ),
    "lbl_task_OPS_DRIFT": (
        "The behaviour drift monitor is in its band",
        "Bộ giám sát lệch hành vi nằm trong ngưỡng",
    ),
    "lbl_task_OPS_REVIEW": (
        "Review the open cases and the risks of the agent",
        "Rà soát các vụ việc đang mở và các rủi ro của tác tử",
    ),
    "lbl_task_REV_RISKS": (
        "Assess the risks again and update the residual scores",
        "Đánh giá lại rủi ro và cập nhật điểm rủi ro dư",
    ),
    "lbl_task_REV_APPROVE": (
        "Approve the agent again for continued use (second line)",
        "Duyệt lại việc tiếp tục sử dụng tác tử (tuyến phòng vệ thứ hai)",
    ),
    "lbl_task_RET_ARCHIVE": (
        "Archive the case files and the evidence export",
        "Lưu trữ hồ sơ vụ việc và bản xuất bằng chứng",
    ),
    "lbl_task_RET_ACCESS": (
        "Remove the agent identity and its tool access",
        "Gỡ danh tính của tác tử và quyền dùng công cụ",
    ),
    # label_for('rule', ...): the assignment rules of config/assignment_rules.yaml
    "lbl_rule_AR_BASELINE": (
        "Internal baseline for every AI system",
        "Mức nền nội bộ cho mọi hệ thống AI",
    ),
    "lbl_rule_AR_PDPL_CUSTOMER": (
        "Customer personal data duties",
        "Nghĩa vụ về dữ liệu cá nhân của khách hàng",
    ),
    "lbl_rule_AR_PDPL_STAFF": (
        "Personal data of staff or partners",
        "Dữ liệu cá nhân của nhân viên hoặc đối tác",
    ),
    "lbl_rule_AR_C53_MONEY": ("Circular 53 money movement", "Chuyển tiền theo Thông tư 53"),
    "lbl_rule_AR_D33_HIGH": ("Decision 33 high risk", "Rủi ro cao theo Quyết định 33"),
    "lbl_rule_AR_TOOL_PII_EXPORT": (
        "The system reaches a tool that exports personal data",
        "Hệ thống dùng công cụ xuất dữ liệu cá nhân",
    ),
    "lbl_rule_AR_AUTONOMY_L3": (
        "The model chooses and calls tools (level L3 and above)",
        "Mô hình tự chọn và gọi công cụ (từ mức L3)",
    ),
    "lbl_rule_AR_AUTONOMY_L4": (
        "The agent runs a multi-step workflow end to end (level L4 and above)",
        "Tác tử chạy trọn quy trình nhiều bước (từ mức L4)",
    ),
    "lbl_rule_AR_AUTONOMY_L5": (
        "Self-directed agent (level L5, prohibited by default)",
        "Tác tử tự định hướng (mức L5, mặc định bị cấm)",
    ),
    # UI-341: "1 agent" / "2 agents" (plural() in routes.render looks for <key>_one when n is 1)
    "fa_agents_n_one": ("{n} agent", "{n} tác tử"),
    "g2_rules_count_one": ("{n} assignment", "{n} mục được gán"),
    "b3_kindn_obligation": ("{n} obligations", "{n} nghĩa vụ"),
    "b3_kindn_obligation_one": ("{n} obligation", "{n} nghĩa vụ"),
    "b3_kindn_control": ("{n} controls", "{n} biện pháp kiểm soát"),
    "b3_kindn_control_one": ("{n} control", "{n} biện pháp kiểm soát"),
    "b3_kindn_risk": ("{n} risks", "{n} rủi ro"),
    "b3_kindn_risk_one": ("{n} risk", "{n} rủi ro"),
    "b3_kindn_task": ("{n} tasks", "{n} nhiệm vụ"),
    "b3_kindn_task_one": ("{n} task", "{n} nhiệm vụ"),
    "b3_kindn_guardian": ("{n} guardian features", "{n} tính năng bảo vệ"),
    "b3_kindn_guardian_one": ("{n} guardian feature", "{n} tính năng bảo vệ"),
    # label_for('field', ...): the intake fields an assignment rule matches on
    "lbl_field_system_type": ("System type", "Loại hệ thống"),
    "lbl_field_org_role": ("Role of the bank", "Vai trò của ngân hàng"),
    "lbl_field_user_segment": ("User segment", "Nhóm người dùng"),
    "lbl_field_personal_data": ("Personal data", "Dữ liệu cá nhân"),
    "lbl_field_money_movement": ("Moves money", "Chuyển tiền"),
    "lbl_field_credit_decision": ("Credit decision", "Quyết định tín dụng"),
    "lbl_field_human_control": ("Human control", "Kiểm soát của con người"),
    "lbl_field_lifecycle_stage": ("Stage", "Giai đoạn"),
    "lbl_field_risk_level": ("Risk level", "Mức rủi ro"),
    "lbl_field_effective_risk_level": ("Effective risk level", "Mức rủi ro hiệu lực"),
    "lbl_field_decision33_class": ("Decision 33 class", "Nhóm theo Quyết định 33"),
    "lbl_field_business_impact": ("Business impact", "Tác động kinh doanh"),
    "lbl_field_autonomy_level": ("Autonomy level", "Mức tự chủ"),
    "lbl_field_status": ("Status", "Trạng thái"),
    # label_for('guardian', ...): features that have no cat_ key
    "lbl_guardian_judge_t2_sample": (
        "Random sample for the AI judge",
        "Mẫu ngẫu nhiên cho giám khảo AI",
    ),
    "lbl_guardian_judge_challenger": ("Challenger judge", "Giám khảo đối chứng"),
    "lbl_guardian_monitor_quality": ("Quality monitor", "Bộ giám sát chất lượng"),
    "lbl_guardian_monitor_fairness": ("Fairness monitor", "Bộ giám sát công bằng"),
    "lbl_guardian_monitor_split_payment": (
        "Split-payment monitor",
        "Bộ giám sát chia nhỏ giao dịch",
    ),
    "lbl_guardian_monitor_drift": ("Drift monitor", "Bộ giám sát lệch hành vi"),
    "b3_cmd_line": ("From the command line:", "Từ dòng lệnh:"),
    # label_for('kind', ...): inventory and catalogue kinds
    "lbl_kind_system": ("AI system", "Hệ thống AI"),
    "lbl_kind_agent": ("Agent", "Tác tử"),
    "lbl_kind_model": ("Model", "Mô hình"),
    "lbl_kind_model_endpoint": ("Model endpoint", "Điểm cuối mô hình"),
    "lbl_kind_tool": ("Tool", "Công cụ"),
    "lbl_kind_mcp_server": ("MCP server", "Máy chủ MCP"),
    "lbl_kind_dataset": ("Dataset", "Bộ dữ liệu"),
    "lbl_kind_prompt": ("Prompt", "Prompt"),
    "lbl_kind_supplier": ("Supplier", "Nhà cung cấp"),
    "lbl_kind_entrypoint": ("Entry point", "Điểm vào"),
    "lbl_kind_genie_space": ("Genie space", "Không gian Genie"),
    "lbl_kind_job": ("Job", "Công việc"),
    "lbl_kind_vector_index": ("Vector index", "Chỉ mục vector"),
    "lbl_kind_uc_function": ("Unity Catalog function", "Hàm Unity Catalog"),
}

CHANGED: dict[str, tuple[str, str]] = {
    # UI-331 / UI-042: no flag names and no API paths in text for people; admins get the flag
    # name as a tooltip (labels.Labeler.flag_title)
    "g6_kpi_sub": (
        "Figures for the AI systems in your scope. Rates show as percentages. If a figure cannot be calculated, the reason is shown.",
        "Số liệu của các hệ thống AI trong phạm vi của bạn. Tỷ lệ hiển thị theo phần trăm. Số liệu không tính được sẽ ghi rõ lý do.",
    ),
    "onboard_off": (
        "Starting onboarding from this page is not turned on.",
        "Chưa bật việc chạy tiếp nhận từ trang này.",
    ),
    "rw_hint": (
        "The watcher runs on a laptop or dev host, not in the App (no internet). An administrator imports a signed update package here. Importing only stores the package; it does not change RegKB.",
        "Bộ theo dõi chạy trên máy xách tay hoặc máy phát triển, không chạy trong App (không có internet). Quản trị viên nhập gói cập nhật đã ký tại đây. Việc nhập chỉ lưu gói, không thay đổi RegKB.",
    ),
    "sy_no_systems_line": (
        "Register your first AI system with the form below.",
        "Đăng ký hệ thống AI đầu tiên bằng biểu mẫu bên dưới.",
    ),
    "int_purpose_lead": (
        "Readiness reports for agents you plan to put under Watch.",
        "Báo cáo mức sẵn sàng của các tác tử dự kiến đưa vào giám sát.",
    ),
    "ob_why": (
        "Nothing is merged automatically. The onboarding agent is itself watched by the AI guardian.",
        "Không có gì được hợp nhất tự động. Bản thân tác tử tiếp nhận cũng chịu giám sát của bộ bảo vệ AI.",
    ),
    "ws_operate": ("Hand over to the AI guardian.", "Bàn giao cho giám sát AI."),
    # UI-014: one case rule for chips, headers and filter labels (first letter upper case)
    "low": ("Low", "Thấp"),
    "medium": ("Medium", "Trung bình"),
    "high": ("High", "Cao"),
    "critical": ("Critical", "Nghiêm trọng"),
    "risk": ("Risk", "Rủi ro"),
    "rule_word": ("Rule", "Quy tắc"),
    "open": ("Open", "Đang mở"),
    "triaged": ("Triaged", "Đã phân loại"),
    "contained": ("Contained", "Đã ngăn chặn"),
    "flow_open": ("Open", "Đang mở"),
    "flow_triaged": ("Triaged", "Đã phân loại"),
    "flow_contained": ("Contained", "Đã ngăn chặn"),
    "flow_closed": ("Closed", "Đã đóng"),
    "mya_cover_full": ("Full", "Đủ"),
    "mya_cover_below_floor": ("Below floor", "Dưới mức sàn"),
    "mya_cover_none": ("None", "Không có"),
    # UI-301 / UI-193 / UI-111: one name per page (sidebar item = tab = h1), en and vi
    "nv3_gov_overview": ("AI management overview", "Tổng quan quản lý AI"),
    "nv3_sup_overview": ("AI guardian overview", "Tổng quan giám sát AI"),
    "nv3_t_library": ("Catalog", "Danh mục"),
    "cp_title": ("Compliance", "Tuân thủ"),
    "signoff": ("Approvals", "Phê duyệt"),
    "nv3_risks_controls": ("Risk & compliance", "Rủi ro và tuân thủ"),
    # UI-115: one wording of the legal disclaimer, and a short chip text
    "cp_disclaimer": (
        "Not legal advice. Bank counsel confirms.",
        "Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận.",
    ),
    "ri_banner": (
        "Not legal advice. Bank counsel confirms.",
        "Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận.",
    ),
    "rc_banner": (
        "Not legal advice. Bank counsel confirms.",
        "Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận.",
    ),
    "kg_banner": (
        "Not legal advice. Bank counsel confirms.",
        "Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận.",
    ),
    "rw_banner": (
        "Not legal advice. Bank counsel confirms.",
        "Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận.",
    ),
    "cp_this_product": ("This agent", "Tác tử này"),
    "gf_draft_btn": ("Fill the form from my description", "Điền biểu mẫu từ mô tả của tôi"),
    "gf_scope_agents": (
        "Agents (separate names with commas, or * for all)",
        "Tác tử (các tên cách nhau bằng dấu phẩy, hoặc * cho tất cả)",
    ),
    "gf_scope_tools": (
        "Tools (separate names with commas, or * for all)",
        "Công cụ (các tên cách nhau bằng dấu phẩy, hoặc * cho tất cả)",
    ),
    "gf_scope_data": (
        "Data classes (separate with commas; leave empty for all)",
        "Nhóm dữ liệu (cách nhau bằng dấu phẩy; để trống để áp dụng cho tất cả)",
    ),
    # UI-341: wording a person would say, one case rule for filter values
    "ik_send": ("Upload", "Tải lên"),
    "fk_reread": ("Read the source again", "Đọc lại nguồn"),
    "fk_none": (
        "No facts yet. Upload the source in the Source tab, then press Re-read.",
        "Chưa có dữ kiện. Hãy tải mã nguồn ở thẻ Mã nguồn, rồi bấm Đọc lại.",
    ),
    "fk_newer": (
        "Upload {n} is newer. Read the source again.",
        "Lần tải lên {n} mới hơn. Hãy đọc lại nguồn.",
    ),
    "rg3_hint_facts": (
        "The facts read from the source. You cannot edit them here. Read the source again to build them again.",
        "Các dữ kiện đọc từ nguồn. Bạn không sửa được ở đây. Hãy đọc lại nguồn để dựng lại.",
    ),
    "sy_rules_run": ("Apply the rules again", "Áp dụng lại quy tắc"),
    "rg2_rule": ("Rule", "Quy tắc"),
    "fk_src_rule": ("Rule", "Luật"),
    "px_by_rule": ("Rule", "Quy tắc"),
    "cv_src_rules": ("Rule", "Quy tắc"),
    "rg2_d_f_all": ("All", "Tất cả"),
    "gf_all": ("All", "Tất cả"),
    "fa_all": ("All", "Tất cả"),
    "g2_du_cov_all": ("All", "Tất cả"),
    "g6_na_risk_register_off": ("The risk register is off.", "Sổ đăng ký rủi ro đang tắt."),
    "g6_na_controls_off": ("The control catalogue is off.", "Danh mục kiểm soát đang tắt."),
    "g6_na_governance_off": ("AI systems are off.", "Hệ thống AI đang tắt."),
}
