# ruff: noqa: E501
"""UX5 text for group G6 (CONSOLE_UX5): agent factory, cases, decisions, evidence, assurance.

``UX5`` shortens existing keys (a test checks that every key exists). ``NEW`` holds keys that only
the UX5 templates use (prefix ``u6_``); ``ALL`` is merged into the base table by i18n.py. Both have English and Vietnamese text."""

from __future__ import annotations

UX5: dict[str, tuple[str, str]] = {
    # ---- agent factory
    "fa_intro": (
        "Build and test assessment agents. Locked parts are set by the platform.",
        "Xây dựng và kiểm thử tác tử đánh giá. Các phần khóa do nền tảng đặt.",
    ),
    "fa_portfolio_hint": (
        "Circular 53, Art. 14(3): one agent or rule proposal per dimension.",
        "Thông tư 53, Điều 14(3): mỗi khía cạnh có một tác tử hoặc một đề xuất theo luật.",
    ),
    "fa_live_agent": ("Live", "Đang chạy"),
    "fa_rule_proposal": ("No agent yet", "Chưa có tác tử"),
    "fa_agents_n": ("{n} agents", "{n} tác tử"),
    "fa_new_hint": (
        "Owner group is set by the dimension. You can create agents only for your own groups.",
        "Nhóm sở hữu do khía cạnh quyết định. Bạn chỉ tạo được tác tử cho nhóm của mình.",
    ),
    "fa_gate_later": ("Not tested yet", "Chưa kiểm thử"),
    "fa_readonly": (
        "Read only. Only drafts can be edited, by the owner group.",
        "Chỉ đọc. Chỉ bản nháp được sửa, bởi nhóm sở hữu.",
    ),
    "fa_template_hint": (
        "Fixed at creation: dimension, owner group, output schema.",
        "Cố định khi tạo: khía cạnh, nhóm sở hữu, lược đồ đầu ra.",
    ),
    "fa_f_eval_pack": ("Eval pack", "Bộ đánh giá"),
    "fa_policy_hint": (
        "Pick the policy the agent checks: a regulation (RegKB) or an internal document.",
        "Chọn chính sách mà tác tử kiểm tra: văn bản pháp lý (RegKB) hoặc tài liệu nội bộ.",
    ),
    "fa_checklist_hint": (
        "Each check is a question, allowed evidence, a severity and a pass rule. Maximum {max}.",
        "Mỗi mục kiểm tra gồm câu hỏi, bằng chứng được dùng, mức nghiêm trọng và quy tắc đạt. "
        "Tối đa {max}.",
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
        "Your instructions follow the locked platform preamble. Limit {max} tokens.",
        "Hướng dẫn của bạn nằm sau phần mở đầu khóa của nền tảng. Giới hạn {max} token.",
    ),
    "fa_instr_preamble": ("Show preamble {name} (locked)", "Phần mở đầu {name} (đã khóa)"),
    "fa_harness_hint": (
        "Defaults are shown. Edit only the open fields.",
        "Giá trị mặc định được hiển thị. Chỉ sửa các trường đang mở.",
    ),
    "fa_guardians_hint": (
        "Required guardians are locked on. You may add more.",
        "Guardian bắt buộc luôn bật. Bạn có thể thêm guardian khác.",
    ),
    "fa_preview_hint": (
        "Dry run. No model and no tool call. Shows what each check would read.",
        "Chạy thử khô. Không gọi mô hình hay công cụ. Cho thấy mỗi mục kiểm tra sẽ đọc gì.",
    ),
    "fa_golden_hint": (
        "Upload cases as JSON or CSV. Use synthetic Vietnamese text only; personal data is refused.",
        "Tải ca lên dạng JSON hoặc CSV. Chỉ dùng văn bản tiếng Việt tổng hợp; dữ liệu cá nhân bị từ chối.",
    ),
    "fg_no_run": (
        "No run possible: the version is live or you are not in the owner group.",
        "Không chạy được: phiên bản đang chạy hoặc bạn không thuộc nhóm sở hữu.",
    ),
    "fg_model_off": (
        "Gate runs are off: no AI model is connected. Ask an administrator.",
        "Chạy cổng đang tắt: chưa kết nối mô hình AI. Hãy hỏi quản trị viên.",
    ),
    "fg_sim_hint": (
        "Mark each finding: agree, disagree (give the right verdict) or unsure. "
        "Marks calibrate the judges. A simulation never promotes an agent.",
        "Đánh dấu từng phát hiện: đồng ý, không đồng ý (nêu kết luận đúng) hoặc chưa chắc. "
        "Dấu đánh dấu hiệu chuẩn giám khảo. Mô phỏng không bao giờ đưa tác tử vào chạy.",
    ),
    # ---- cases
    "cases_purpose": (
        "A case needs a human decision. Rules, judges and monitors open it. "
        "People triage and close it.",
        "Vụ việc cần con người quyết định. Quy tắc, giám khảo và bộ giám sát mở vụ việc. "
        "Con người phân loại và đóng.",
    ),
    "st_t0b": (
        "Prompt-injection pattern found: {why} (advisory).",
        "Phát hiện mẫu tiêm lệnh: {why} (tham khảo).",
    ),
    "need_two": (
        "Closing a {sev} case needs 2 sign-offs from different people, one an approver.",
        "Đóng vụ việc mức {sev} cần 2 phê duyệt từ hai người khác nhau, một người là người phê duyệt.",
    ),
    "comment_masked": ("Masked on save.", "Được che dữ liệu cá nhân khi lưu."),
    "case_on_chain_why": (
        "Every gate decision and human action on this case is on the evidence chain.",
        "Mọi quyết định của cổng và thao tác của con người trong vụ việc đều nằm trên chuỗi bằng chứng.",
    ),
    # ---- evidence
    "ev_purpose_lead": (
        "Every decision and every human action is written to a tamper-evident chain. "
        "The verifier finds any change.",
        "Mọi quyết định và thao tác của con người đều được ghi vào chuỗi chống sửa đổi. "
        "Công cụ kiểm tra phát hiện mọi thay đổi.",
    ),
    "export_help": (
        "Builds a zip: chain, verify report, case files, judge report. Download it below.",
        "Tạo tệp zip: chuỗi, báo cáo kiểm tra, hồ sơ vụ việc, báo cáo giám khảo. Tải về bên dưới.",
    ),
    "no_packs": ("No export yet.", "Chưa có bản xuất."),
    # ---- incidents, alerts, sign-off, assurance
    "inc_why": (
        "Alerts, gate stops, failed checks and escalations become incidents. "
        "Only a person moves or closes one. Incidents never block an agent.",
        "Cảnh báo, lần chặn của cổng, kiểm tra thất bại và leo thang trở thành sự cố. "
        "Chỉ con người chuyển hoặc đóng sự cố. Sự cố không bao giờ chặn tác tử.",
    ),
    "alerts_purpose": (
        "Rules raise alerts. An operator acknowledges one; the action is audited.",
        "Quy tắc tạo cảnh báo. Người vận hành xác nhận; hành động được ghi nhật ký.",
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
    "as_no_runs": (
        "No assurance run yet.",
        "Chưa có lần chạy đánh giá nào.",
    ),
}

_X = {
    "facts_v1": ("System facts card", "Thẻ dữ kiện hệ thống"),
    "pack_results": ("Pack results", "Kết quả bộ kiểm thử"),
    "system_record": ("System record", "Hồ sơ hệ thống"),
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
    "rationale_length": ("Rationale length", "Độ dài lý do"),
    "no_personal_data": ("No personal data", "Không có dữ liệu cá nhân"),
}

NEW: dict[str, tuple[str, str]] = {
    # case page
    "u6_next": ("Next action", "Việc cần làm tiếp"),
    "u6_stops_line": (
        "{n} stops by hard rules on this case.",
        "{n} lần chặn bởi quy tắc cứng trong vụ việc này.",
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
    "u6_grp_join": ("{n} more stops joined this case.", "{n} lần chặn khác được gộp vào vụ việc."),
    "u6_grp_t0b": (
        "Prompt-injection pattern found {n} times, {a}-{b} (advisory).",
        "Phát hiện mẫu tiêm lệnh {n} lần, {a}-{b} (tham khảo).",
    ),
    "u6_times": ("{n} times", "{n} lần"),
    "u6_hard_rule": ("Hard rule", "Quy tắc cứng"),
    "u6_pattern_screen": ("Pattern screen", "Sàng lọc mẫu"),
    "u6_tier": ("tier {n}", "cấp {n}"),
    "u6_checker": ("Checker", "Bộ kiểm tra"),
    "u6_hits": ("Hits", "Số lần"),
    "u6_when": ("When", "Lúc"),
    "u6_check_log": ("Check details ({n})", "Chi tiết kiểm tra ({n})"),
    "u6_show_masked": ("Show masked text", "Xem văn bản đã che"),
    "u6_last_signed": ("last signed {time}", "ký lần cuối {time}"),
    "u6_chain_details": ("Chain details", "Chi tiết chuỗi"),
    "u6_sources": ("Sources ({n})", "Nguồn ({n})"),
    "u6_unassigned": ("Unassigned", "Chưa giao"),
    "u6_by": ("by {who}", "bởi {who}"),
    # evidence page
    "u6_lane_search": ("Find a lane", "Tìm làn"),
    "u6_search": ("Search", "Tìm"),
    "u6_no_lane": ("No lane matches.", "Không có làn nào khớp."),
    "u6_lanes_hint": (
        "One square = one entry, newest right. Shows the last {cap}.",
        "Một ô = một mục, mới nhất bên phải. Hiện {cap} mục cuối.",
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
    "u6_id_help": ("Lowercase letters, digits, hyphens", "Chữ thường, chữ số, dấu gạch ngang"),
    "u6_id_ph": ("agent-id", "ma-tac-tu"),
    "u6_owner": ("owner", "nhóm sở hữu"),
    "u6_eval_pack_help": ("Test pack used by the gate", "Bộ kiểm thử mà cổng dùng"),
    "u6_stage_define": ("Define", "Xác định"),
    "u6_stage_build": ("Build", "Xây dựng"),
    "u6_stage_check": ("Check", "Rà soát"),
    "u6_stage_test": ("Test", "Kiểm thử"),
    "u6_ev_live": ("Went live", "Đưa vào chạy"),
    "u6_ev_approved": ("Approved", "Đã duyệt"),
    "u6_ev_approval": ("Approval given", "Đã phê duyệt"),
    "u6_ev_submitted": ("Submitted", "Đã nộp"),
    "u6_ev_tested": ("Tested", "Đã kiểm thử"),
    "u6_ev_gate_run": ("Gate run", "Chạy cổng"),
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
    "u6_hs_hitl": ("{n} approval points", "{n} điểm cần duyệt"),
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
    "u6_perm_propose": ("read and propose", "đọc và đề xuất"),
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
    "u6_mark_label": ("Your mark", "Đánh dấu của bạn"),
    "u6_marked": ("Marked {mark} by {who}", "{who} đã đánh dấu: {mark}"),
    "u6_correct_verdict": ("If disagree: right verdict", "Nếu không đồng ý: kết luận đúng"),
    "u6_note_ph": ("Note (max 300)", "Ghi chú (tối đa 300)"),
    "u6_evidence_n": ("Evidence ({n})", "Bằng chứng ({n})"),
    "u6_save_marks": ("Save marks", "Lưu các dấu"),
}


# What i18n.py merges into the base table: NEW and the plain labels (prefix ``u6_x_``).
ALL: dict[str, tuple[str, str]] = {**NEW, **{"u6_x_" + k: v for k, v in _X.items()}}
