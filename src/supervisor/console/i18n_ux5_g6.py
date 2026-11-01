# ruff: noqa: E501
"""UX5 text for group G6 (CONSOLE_UX5): agent factory, cases, decisions, evidence, assurance.

``UX5`` shortens existing keys (a test checks that every key exists). ``NEW`` holds keys that only
the UX5 templates use (prefix ``u6_``); ``ALL`` is merged into the base table by i18n.py. Both have English and Vietnamese text."""

from __future__ import annotations

UX5: dict[str, tuple[str, str]] = {
    # ---- agent factory
    "fa_intro": (
        "Build and test assessment agents. The platform sets the locked parts.",
        "Xây dựng và kiểm thử tác tử đánh giá. Nền tảng đặt các phần đã khóa.",
    ),
    "fa_portfolio_hint": (
        "Circular 53, Art. 14(3): each risk type needs one agent or one rule-based check.",
        "Thông tư 53, Điều 14(3): mỗi loại rủi ro cần một tác tử hoặc một kiểm tra theo quy tắc.",
    ),
    "fa_live_agent": ("Live", "Đang chạy"),
    "fa_rule_proposal": ("No agent yet", "Chưa có tác tử"),
    "fa_agents_n": ("{n} agents", "{n} tác tử"),
    "fa_new_hint": (
        "The risk type sets the owner group. You can create agents only for your own groups.",
        "Loại rủi ro quyết định nhóm sở hữu. Bạn chỉ tạo được tác tử cho nhóm của mình.",
    ),
    "fa_gate_later": ("Not tested yet", "Chưa kiểm thử"),
    "fa_readonly": (
        "Read only. Only the owner group can edit drafts.",
        "Chỉ xem. Chỉ nhóm sở hữu được sửa bản nháp.",
    ),
    "fa_template_hint": (
        "Set at creation and cannot change: risk type, owner group, output format.",
        "Đặt khi tạo và không đổi được: loại rủi ro, nhóm sở hữu, định dạng đầu ra.",
    ),
    "fa_f_eval_pack": ("Eval pack", "Bộ đánh giá"),
    "fa_policy_hint": (
        "Pick the policy the agent checks: a regulation (RegKB) or an internal document.",
        "Chọn chính sách mà tác tử kiểm tra: văn bản pháp lý (RegKB) hoặc tài liệu nội bộ.",
    ),
    "fa_checklist_hint": (
        "Each check has a question, the evidence it may use, a severity and a pass rule. Up to {max}.",
        "Mỗi mục kiểm tra có câu hỏi, bằng chứng được dùng, mức nghiêm trọng và quy tắc đạt. Tối đa {max}.",
    ),
    "fa_model_off": (
        "Drafting is off: no AI model is connected. Ask an administrator.",
        "Chức năng soạn thảo đang tắt: chưa kết nối mô hình AI. Hãy hỏi quản trị viên.",
    ),
    "fa_tools_hint": (
        "Tools come from the allow-list of the {group} group.",
        "Công cụ lấy từ danh sách cho phép của nhóm {group}.",
    ),
    "fa_instr_hint": (
        "Your instructions come after the locked platform instructions. Limit: {max} tokens.",
        "Hướng dẫn của bạn nằm sau hướng dẫn nền tảng đã khóa. Giới hạn: {max} token.",
    ),
    "fa_instr_preamble": (
        "Show platform instructions {name} (locked)",
        "Xem hướng dẫn nền tảng {name} (đã khóa)",
    ),
    "fa_harness_hint": (
        "Defaults are shown. Edit only the open fields.",
        "Giá trị mặc định được hiển thị. Chỉ sửa các trường đang mở.",
    ),
    "fa_guardians_hint": (
        "Required guardians are locked on. You may add more.",
        "Guardian bắt buộc luôn bật. Bạn có thể thêm guardian khác.",
    ),
    "fa_preview_hint": (
        "Preview only. No AI model or tool is called. Shows what each check would read.",
        "Chỉ xem thử. Không gọi mô hình AI hay công cụ. Cho thấy mỗi mục kiểm tra sẽ đọc gì.",
    ),
    "fa_golden_hint": (
        "Upload cases as JSON or CSV. Use made-up Vietnamese text only. Personal data is rejected.",
        "Tải ca lên dạng JSON hoặc CSV. Chỉ dùng văn bản tiếng Việt tự soạn. Dữ liệu cá nhân sẽ bị từ chối.",
    ),
    "fg_no_run": (
        "You cannot run tests here: this version is already live, or you are not in the owner group.",
        "Bạn chưa thể chạy kiểm thử: phiên bản này đang chạy, hoặc bạn không thuộc nhóm sở hữu.",
    ),
    "fg_model_off": (
        "Test runs are off because no AI model is connected. Ask your administrator.",
        "Chưa chạy kiểm thử được vì chưa kết nối mô hình AI. Hãy liên hệ quản trị viên.",
    ),
    "fg_sim_hint": (
        "Mark each finding: agree, disagree (give the right verdict) or unsure. Your marks help calibrate the judges. A simulation never puts an agent live.",
        "Đánh dấu từng phát hiện: đồng ý, không đồng ý (nêu kết luận đúng) hoặc chưa chắc. Các dấu của bạn giúp hiệu chuẩn giám khảo. Mô phỏng không bao giờ đưa tác tử vào chạy.",
    ),
    # ---- cases
    "cases_purpose": (
        "A case needs a decision from you. Rules, AI judges and monitors open cases. Your team reviews and closes them.",
        "Vụ việc cần bạn quyết định. Quy tắc, giám khảo AI và bộ giám sát sẽ mở vụ việc. Đội của bạn xem xét và đóng.",
    ),
    "st_t0b": (
        "Possible prompt injection found: {why} (advice only).",
        "Phát hiện dấu hiệu tiêm lệnh: {why} (chỉ tư vấn).",
    ),
    "need_two": (
        "Closing a {sev} case needs sign-off from 2 different people, one of them an approver.",
        "Đóng vụ việc mức {sev} cần 2 người khác nhau phê duyệt, trong đó có một người phê duyệt.",
    ),
    "comment_masked": ("Masked on save.", "Được che dữ liệu cá nhân khi lưu."),
    "case_on_chain_why": (
        "Every gate decision and human action on this case is on the evidence chain.",
        "Mọi quyết định của cổng và thao tác của con người trong vụ việc đều nằm trên chuỗi bằng chứng.",
    ),
    # ---- evidence
    "ev_purpose_lead": (
        "Every decision and every action by a person is recorded in a tamper-evident chain. The verifier detects any change.",
        "Mọi quyết định và thao tác của con người đều được ghi vào chuỗi chống sửa đổi. Công cụ kiểm tra phát hiện mọi thay đổi.",
    ),
    "export_help": (
        "Creates a zip with the evidence chain, verification report, case files and judge report. Download it below.",
        "Tạo tệp zip gồm chuỗi bằng chứng, báo cáo kiểm tra, hồ sơ vụ việc và báo cáo giám khảo. Tải về bên dưới.",
    ),
    "no_packs": ("Nothing exported yet.", "Chưa có bản xuất nào."),
    # ---- incidents, alerts, sign-off, assurance
    "inc_why": (
        "Alerts, gate stops, failed checks and escalations become incidents. Only a person can change the status or close one. Incidents never stop an agent.",
        "Cảnh báo, lần chặn của cổng, kiểm tra thất bại và leo thang trở thành sự cố. Chỉ con người mới đổi trạng thái hoặc đóng sự cố. Sự cố không bao giờ chặn tác tử.",
    ),
    "alerts_purpose": (
        "Alerts come from rules. Acknowledge an alert to confirm you have seen it. Your action is logged.",
        "Cảnh báo do quy tắc tạo ra. Hãy xác nhận để cho biết bạn đã xem. Thao tác của bạn được ghi lại.",
    ),
    "so_none": ("Nothing to sign", "Không có gì cần ký"),
    "so_none_line": (
        "Triaged high and critical cases appear here.",
        "Vụ việc mức cao và nghiêm trọng đã phân loại sẽ hiện ở đây.",
    ),
    "as_purpose": (
        "Test results for accuracy, hallucination, bias, dependency, security and robustness.",
        "Kết quả kiểm thử độ chính xác, ảo giác, thiên vị, phụ thuộc, bảo mật và độ bền.",
    ),
    "as_no_runs": ("No tests run yet.", "Chưa chạy kiểm thử nào."),
}

_X = {
    "facts_v1": ("System facts card", "Thẻ dữ kiện hệ thống"),
    "pack_results": ("Test pack results", "Kết quả bộ kiểm thử"),
    "system_record": ("AI system details", "Thông tin hệ thống AI"),
    "regkb_rows": ("Regulation rows", "Điều khoản pháp lý"),
    "document_sections": ("Document sections", "Các phần tài liệu"),
    "prior_verdicts": ("Earlier verdicts", "Kết luận trước đó"),
    "open_questions": ("Open questions", "Câu hỏi còn mở"),
    "waivers": ("Waivers", "Miễn trừ"),
    "rules": ("Rules only", "Chỉ quy tắc"),
    "rules+judge": ("Rules and judge", "Quy tắc và giám khảo"),
    "single_pass": ("One pass", "Một lượt"),
    "loop": ("Repeat until done", "Lặp đến khi xong"),
    "judge": ("Judge", "Giám khảo"),
    "all_answered": ("All checks answered", "Mọi mục đã trả lời"),
    "evaluator_done": ("Evaluator says done", "Bộ đánh giá báo xong"),
    "evidence_kind_allowed": ("Evidence kind allowed", "Loại bằng chứng hợp lệ"),
    "evidence_age": ("Evidence age", "Tuổi bằng chứng"),
    "rationale_length": ("Reason length", "Độ dài lý do"),
    "fact": ("Fact", "Dữ kiện"),
    "document": ("Document", "Tài liệu"),
    "regkb": ("Regulation", "Văn bản pháp lý"),
    "pack": ("Test pack", "Bộ kiểm thử"),
    "no_personal_data": ("No personal data", "Không có dữ liệu cá nhân"),
}

NEW: dict[str, tuple[str, str]] = {
    # ---- agent editor layout (stepper, header, checklist, preview)
    "u7_next_action": ("Next step", "Bước tiếp theo"),
    "u7_all_done": ("All steps are complete", "Mọi bước đã hoàn tất"),
    "u7_version": ("Version", "Phiên bản"),
    "u7_edit": ("Edit", "Sửa"),
    "u7_confirm_drop": ("Remove this check from the draft?", "Gỡ kiểm tra này khỏi bản nháp?"),
    "u7_no_evidence": ("No evidence types selected", "Chưa chọn loại bằng chứng"),
    "u7_st_done": ("done", "xong"),
    "u7_st_todo": ("to do", "chưa làm"),
    "u7_st_warn": ("needs attention", "cần xem lại"),
    "u7_st_current": ("current step", "bước hiện tại"),
    "u7_pick_label": ("Systems with stored facts", "Hệ thống đã có thẻ dữ kiện"),
    "u7_pick_hint": (
        "Tick up to 3 systems, or type their ids in the box.",
        "Chọn tối đa 3 hệ thống, hoặc gõ mã vào ô.",
    ),
    "u7_pick_none": (
        "No system has a stored facts card yet.",
        "Chưa có hệ thống nào có thẻ dữ kiện.",
    ),
    "u7_yes": ("Yes", "Có"),
    "u7_no": ("No", "Không"),
    "u7_days": ("{n} days", "{n} ngày"),
    "u7_tokens": ("{n} tokens", "{n} token"),
    "u7_chars": ("{n} characters", "{n} ký tự"),
    "u7_none": ("None", "Không có"),
    "u7_h_setting": ("Setting", "Thiết lập"),
    "u7_h_expected": ("Expected result", "Kết quả mong đợi"),
    "u7_h_input": ("Test input", "Nội dung kiểm thử"),
    "u7_h_check": ("Check", "Mục kiểm tra"),
    "u7_pk_preamble": ("Fixed preamble", "Phần mở đầu cố định"),
    "u7_pk_sources": ("Sources", "Nguồn"),
    "u7_pk_budget_tokens": ("Token budget", "Ngân sách token"),
    "u7_pk_max_document_chars": ("Max document size", "Cỡ tài liệu tối đa"),
    "u7_pk_progressive": ("Load in stages", "Nạp từng phần"),
    "u7_pk_run": ("Run memory", "Bộ nhớ lượt chạy"),
    "u7_pk_system_memory": ("System memory", "Bộ nhớ hệ thống"),
    "u7_pk_retention_days": ("Retention", "Thời hạn lưu"),
    "u7_pk_approval_points": ("Approval points", "Điểm phê duyệt"),
    "u7_pk_verifier": ("Verifier", "Bộ kiểm chứng"),
    "u7_pk_locked_validators": ("Locked checks", "Kiểm tra cố định"),
    "u7_pk_mode": ("Mode", "Chế độ"),
    "u7_pk_max_iterations": ("Maximum rounds", "Số vòng tối đa"),
    "u7_h_component": ("Component", "Thành phần"),
    # case page
    "u6_next": ("Next action", "Việc cần làm tiếp"),
    "u6_stops_line": (
        "{n} calls blocked by mandatory rules in this case.",
        "{n} lệnh gọi bị chặn bởi quy tắc bắt buộc trong vụ việc này.",
    ),
    "u6_grp_rule": (
        "{rule} matched {n} times, {a}-{b}.",
        "{rule} khớp {n} lần, {a}-{b}.",
    ),
    "u6_act_pause": (
        "Agent paused; calls did not run.",
        "Tác tử bị tạm dừng; lệnh gọi không chạy.",
    ),
    "u6_act_block": ("Calls blocked; they did not run.", "Lệnh gọi bị chặn; không chạy."),
    "u6_grp_join": (
        "{n} more blocked calls were added to this case.",
        "{n} lệnh gọi bị chặn khác đã được gộp vào vụ việc này.",
    ),
    "u6_grp_t0b": (
        "Possible prompt-injection attempt seen {n} times, {a}-{b} (advice only).",
        "Phát hiện dấu hiệu tiêm lệnh {n} lần, {a}-{b} (chỉ tham khảo).",
    ),
    "u6_times": ("{n} times", "{n} lần"),
    "u6_hard_rule": ("Mandatory rule", "Quy tắc bắt buộc"),
    "u6_pattern_screen": ("Pattern check", "Kiểm tra mẫu"),
    "u6_tier": ("tier {n}", "cấp {n}"),
    "u6_checker": ("Checker", "Bộ kiểm tra"),
    "u6_hits": ("Times", "Số lần"),
    "u6_when": ("When", "Lúc"),
    "u6_check_log": ("Check details ({n})", "Chi tiết kiểm tra ({n})"),
    "u6_show_masked": ("Show masked text", "Xem văn bản đã che"),
    "u6_last_signed": ("last signed {time}", "ký lần cuối {time}"),
    "u6_chain_details": ("Evidence chain details", "Chi tiết chuỗi bằng chứng"),
    "u6_sources": ("Sources ({n})", "Nguồn ({n})"),
    "u6_unassigned": ("Unassigned", "Chưa giao"),
    "u6_by": ("by {who}", "bởi {who}"),
    # evidence page
    "u6_lane_search": ("Search by agent", "Tìm theo tác tử"),
    "u6_search": ("Search", "Tìm"),
    "u6_no_lane": ("No agent matches.", "Không có tác tử nào khớp."),
    "u6_lanes_hint": (
        "Each square is one entry, newest on the right. Shows the last {cap}.",
        "Mỗi ô là một bản ghi, mới nhất ở bên phải. Hiển thị {cap} bản ghi cuối.",
    ),
    # alerts
    "u6_no_alerts": ("No alerts", "Không có cảnh báo"),
    "u6_no_alerts_line": ("All clear.", "Mọi thứ ổn."),
    # assurance
    "u6_as_empty_line": (
        "Ask the platform team to start one.",
        "Hãy nhờ đội nền tảng bắt đầu một lần chạy.",
    ),
    # factory
    "u6_col_agent": ("Agent", "Tác tử"),
    "u6_rule_checks": ("Rule checks", "Kiểm tra quy tắc"),
    "u6_id_help": (
        "Use lowercase letters, digits and hyphens.",
        "Dùng chữ thường, chữ số và dấu gạch ngang.",
    ),
    "u6_id_ph": ("agent-id", "ma-tac-tu"),
    "u6_eval_pack_help": ("Tests the gate runs", "Bộ kiểm thử mà cổng chạy"),
    "u6_stage_define": ("Define", "Xác định"),
    "u6_stage_build": ("Build", "Xây dựng"),
    "u6_stage_check": ("Check", "Rà soát"),
    "u6_stage_test": ("Test", "Kiểm thử"),
    "u6_ev_live": ("Went live", "Đưa vào chạy"),
    "u6_ev_approved": ("Approved", "Đã duyệt"),
    "u6_ev_approval": ("Approval given", "Đã phê duyệt"),
    "u6_ev_submitted": ("Submitted", "Đã nộp"),
    "u6_ev_tested": ("Tested", "Đã kiểm thử"),
    "u6_ev_gate_run": ("Gate check", "Kiểm tra cổng"),
    "u6_ev_simulation": ("Simulation review", "Rà soát mô phỏng"),
    "u6_ev_retired": ("Retired", "Đã ngừng"),
    "u6_ev_created": ("Created", "Đã tạo"),
    "u6_ev_new_version": ("New version", "Phiên bản mới"),
    "u6_ev_sim_line": (
        "{agree} agree, {disagree} disagree, {unsure} unsure ({n} saves)",
        "{agree} đồng ý, {disagree} không đồng ý, {unsure} chưa chắc ({n} lần lưu)",
    ),
    "u6_range": ("{a} to {b}", "{a} đến {b}"),
    "u6_order": ("order", "thứ tự"),
    "u6_ctx_sources": ("Sources", "Nguồn"),
    "u6_hs_system_prompt": (
        "platform preamble plus your instructions",
        "phần mở đầu nền tảng cộng hướng dẫn của bạn",
    ),
    "u6_hs_context": ("{n} sources", "{n} nguồn"),
    "u6_hs_memory_on": ("system memory on", "bật bộ nhớ hệ thống"),
    "u6_hs_memory_off": ("system memory off", "tắt bộ nhớ hệ thống"),
    "u6_hs_hitl": ("{n} approval steps", "{n} bước cần duyệt"),
    "u6_hs_loop": ("up to {n} rounds", "tối đa {n} vòng"),
    "u6_locked_context": (
        "Locked: documents load in steps.",
        "Đã khóa: tài liệu được nạp theo từng bước.",
    ),
    "u6_locked_memory": (
        "Locked: memory lasts one run only.",
        "Đã khóa: bộ nhớ chỉ giữ trong một lần chạy.",
    ),
    "u6_remember": ("Remember", "Ghi nhớ"),
    "u6_extra_checks": ("Extra checks", "Kiểm tra thêm"),
    "u6_stop_when": ("Stop when", "Dừng khi"),
    "u6_perm_read": ("read", "đọc"),
    "u6_perm_propose": ("read and suggest", "đọc và đề xuất"),
    "u6_gate_how": ("How the gate works", "Cổng hoạt động thế nào"),
    "u6_gate_ready_live": ("Live: version {v}.", "Đang chạy: phiên bản {v}."),
    "u6_gate_ready_other": ("Not live yet.", "Chưa đưa vào chạy."),
    "u6_gate_last": (
        "Last gate: {verdict} ({kind}, v{v}).",
        "Cổng gần nhất: {verdict} ({kind}, v{v}).",
    ),
    "u6_gate_approvals": ("Approvals {n} of {m}.", "Phê duyệt {n} / {m}."),
    "u6_cost": (
        "{calls} calls, {tokens} tokens, {s} s",
        "{calls} lần gọi, {tokens} token, {s} giây",
    ),
    "u6_verdict_not_run": ("Not run", "Chưa chạy"),
    # simulation review
    "u6_mark_agree": ("Agree", "Đồng ý"),
    "u6_mark_disagree": ("Disagree", "Không đồng ý"),
    "u6_mark_unsure": ("Unsure", "Chưa chắc"),
    "u6_mark_label": ("Your view", "Ý kiến của bạn"),
    "u6_marked": ("{who} marked: {mark}", "{who} đã đánh dấu: {mark}"),
    "u6_correct_verdict": ("If you disagree: correct result", "Nếu không đồng ý: kết quả đúng"),
    "u6_note_ph": ("Note (up to 300 characters)", "Ghi chú (tối đa 300 ký tự)"),
    "u6_evidence_n": ("Evidence ({n})", "Bằng chứng ({n})"),
    "u6_save_marks": ("Save your views", "Lưu ý kiến"),
}


# What i18n.py merges into the base table: NEW and the plain labels (prefix ``u6_x_``).
ALL: dict[str, tuple[str, str]] = {**NEW, **{"u6_x_" + k: v for k, v in _X.items()}}
