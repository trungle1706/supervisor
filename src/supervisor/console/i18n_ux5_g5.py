"""UX5 text for group G5 (CONSOLE_UX5): guardian catalog, guardian factory, playground, analytics
tabs, metrics, traces.

``UX5`` overrides existing keys (a test checks the keys exist). ``NEW`` holds text that has no
base key; templates read it as ``x.<name>`` (see :func:`texts`). Both carry real English and
Vietnamese."""

from __future__ import annotations

UX5: dict[str, tuple[str, str]] = {
    # --- catalog cards (T006-T018) ---
    "cat_session_monitor_d": (
        "Scores a whole session. Pauses it when the score is too high.",
        "Chấm điểm cả phiên. Tạm dừng phiên khi điểm quá cao.",
    ),
    "cat_ingress_auth_d": (
        "Each agent proves who it is. Unknown callers are refused.",
        "Mỗi tác tử chứng minh danh tính của mình. Bên gọi lạ bị từ chối.",
    ),
    "cat_mcp_gateway_d": (
        "Checks every tool call an agent makes through MCP, and the tool descriptions it reads.",
        "Kiểm tra mọi lệnh gọi công cụ của tác tử qua MCP và các mô tả công cụ mà nó đọc.",
    ),
    "cat_dlp_vn": ("Vietnamese personal data", "Dữ liệu cá nhân tiếng Việt"),
    "cat_dlp_vn_d": (
        "Hides Vietnamese personal data (ID number, phone, account, address) before an agent "
        "tool sees it.",
        "Che dữ liệu cá nhân tiếng Việt (số CCCD, điện thoại, tài khoản, địa chỉ) trước khi "
        "công cụ của tác tử nhìn thấy.",
    ),
    "cat_injection_regex_d": (
        "Known injection patterns in Vietnamese and English. Reports a finding.",
        "Các mẫu chèn lệnh đã biết bằng tiếng Việt và tiếng Anh. Báo một phát hiện.",
    ),
    "cat_injection_classifier_d": (
        "Checks tool results and tool descriptions. May pause money and credit tools.",
        "Kiểm tra kết quả và mô tả công cụ. Có thể tạm dừng công cụ tiền và tín dụng.",
    ),
    "cat_document_intake_d": (
        "Checks files and links an agent receives for hidden instructions and personal data. "
        "A file that cannot be read stops money, credit and personal-data calls.",
        "Kiểm tra tệp và liên kết tác tử nhận được xem có chỉ dẫn ẩn và dữ liệu cá nhân không. "
        "Tệp không đọc được sẽ dừng các lệnh gọi về tiền, tín dụng và dữ liệu cá nhân.",
    ),
    "cat_guard_model": ("Guard model", "Mô hình bảo vệ"),
    "cat_guard_model_d": (
        "An AI model scores text for jailbreak and hidden instructions. It reports findings. "
        "It can pause money and credit calls only when an approver is named.",
        "Một mô hình AI chấm văn bản để tìm jailbreak và lệnh ẩn. Nó báo phát hiện. Chỉ khi có "
        "người phê duyệt được nêu tên, nó mới được tạm dừng lệnh gọi về tiền và tín dụng.",
    ),
    "cat_judge_moderation_d": (
        "An AI judge checks user text and replies for toxic language and off-topic content. "
        "It advises only.",
        "Giám khảo AI kiểm tra văn bản người dùng và câu trả lời xem có lời lẽ độc hại hoặc lạc "
        "đề không. Chỉ tư vấn.",
    ),
    "cat_judge_tiers_d": (
        "AI judges review every trace. A second judge confirms. They open cases but never block "
        "a call.",
        "Giám khảo AI xem xét mọi trace. Giám khảo thứ hai xác nhận. Họ mở hồ sơ nhưng không "
        "bao giờ chặn lệnh gọi.",
    ),
    "cat_judge_advisory_d": (
        "An AI judge gives an opinion during the call. It advises only and never blocks.",
        "Giám khảo AI đưa ý kiến ngay trong lệnh gọi. Chỉ tư vấn, không bao giờ chặn.",
    ),
    "cat_redteam_d": (
        "Every night, tests each agent with Vietnamese attack conversations. Results go to the "
        "test packs.",
        "Mỗi đêm, thử từng tác tử bằng các cuộc hội thoại tấn công tiếng Việt. Kết quả đưa vào "
        "gói kiểm thử.",
    ),
    "cat_evidence_chain_d": (
        "Every decision is saved in a tamper-proof record. An auditor can verify it offline.",
        "Mọi quyết định được lưu trong một bản ghi chống sửa đổi. Kiểm toán viên có thể xác "
        "minh ngoại tuyến.",
    ),
    "cat_open": ("Open", "Mở"),
    # --- other catalog / guardians shell text ---
    "cat_rule": (
        "Only fixed rules block or pause an agent. AI judges advise only. This page is read only.",
        "Chỉ quy tắc cố định mới chặn hoặc tạm dừng tác tử. Giám khảo AI chỉ tư vấn. Trang này "
        "chỉ để xem.",
    ),
}

NEW: dict[str, tuple[str, str]] = {
    "cat_title": ("Guardian catalog", "Danh mục bộ bảo vệ"),
    # --- catalog ---
    "cat_purpose": (
        "The checks that run on every agent call, and what each one may do.",
        "Các kiểm tra chạy trên mọi lệnh gọi của tác tử, và mỗi kiểm tra được phép làm gì.",
    ),
    "cat_n_on": ("{n} of {total} on", "{n} / {total} đang bật"),
    "cat_all": ("All", "Tất cả"),
    "cat_f_on": ("On", "Bật"),
    "cat_f_off": ("Off", "Tắt"),
    "cat_sys_pick": ("Show for system", "Xem theo hệ thống"),
    "cat_sys_none": ("No system chosen", "Chưa chọn hệ thống"),
    "cat_sys_hint": (
        "Choose a system to see which guardians are on for it.",
        "Chọn một hệ thống để xem bộ bảo vệ nào đang bật cho nó.",
    ),
    "cat_off": ("Off", "Tắt"),
    "cat_off_hint": (
        "Off. Ask the platform team to turn it on.",
        "Đang tắt. Hãy nhờ nhóm nền tảng bật.",
    ),
    "cat_required": ("Required", "Bắt buộc"),
    "cat_mrm_go": ("Model-risk approved", "Đã được duyệt rủi ro mô hình"),
    "cat_mrm_nogo": ("Model-risk not approved", "Chưa được duyệt rủi ro mô hình"),
    "cat_eff_blocks": ("Can block", "Có thể chặn"),
    "cat_eff_pauses": ("Can pause", "Có thể tạm dừng"),
    "cat_eff_masks": ("Masks", "Che dữ liệu"),
    "cat_eff_reports": ("Reports", "Báo cáo"),
    "cat_eff_advises": ("Advises", "Tư vấn"),
    "cat_eff_proves": ("Proves", "Chứng minh"),
    "cat_empty": ("Nothing matches this filter.", "Không có mục nào khớp bộ lọc này."),
    "cat_gh_gate": ("Run before the tool call", "Chạy trước lệnh gọi công cụ"),
    "cat_gh_detect": ("Read the call and its data", "Đọc lệnh gọi và dữ liệu của nó"),
    "cat_gh_judge": ("AI opinions and tests", "Ý kiến và kiểm thử của AI"),
    "cat_gh_monitor": ("Watch behavior over time", "Theo dõi hành vi theo thời gian"),
    "cat_gh_prove": ("Keep proof for auditors", "Lưu bằng chứng cho kiểm toán"),
    "cat_gh_connect": ("Send data in and out", "Đưa dữ liệu vào và ra"),
    "cat_tech_rows": ("Technical details for admins", "Chi tiết kỹ thuật cho quản trị viên"),
    "cat_sw_on": ("On for this system", "Bật cho hệ thống này"),
    "cat_sw_off": ("Off for this system", "Tắt cho hệ thống này"),
    "cat_sw_locked": ("Always on (policy floor)", "Luôn bật (mức sàn chính sách)"),
    "cat_sw_inst_off": ("Off in this instance", "Tắt trên toàn phiên bản"),
    "cat_filter_cat": ("Group", "Nhóm"),
}


# --- guardian factory (list, new form, detail) ---
UX5.update(
    {
        "gf_purpose": (
            "Create a new guardian. Describe the rule in words. Review the draft. Save it.",
            "Tạo guardian mới. Mô tả quy tắc bằng lời. Xem lại bản nháp. Lưu lại.",
        ),
        "gf_why": (
            "Only fixed rules can block. Model types only log or ask approval.",
            "Chỉ quy tắc cố định mới chặn được. Loại dùng mô hình chỉ ghi nhận hoặc xin phê duyệt.",
        ),
        "gf_action_hint": (
            "Fixed rules can block, hide data, ask approval or log. Model types can only log or "
            "ask approval.",
            "Quy tắc cố định có thể chặn, che dữ liệu, xin phê duyệt hoặc ghi nhận. Loại dùng mô "
            "hình chỉ ghi nhận hoặc xin phê duyệt.",
        ),
        "gf_bench_pack": ("Test pack (optional)", "Bộ kiểm thử (tùy chọn)"),
        "gf_words_hint": (
            "Example: block account numbers. Your text goes to a model only after masking.",
            "Ví dụ: chặn số tài khoản. Văn bản của bạn chỉ đến mô hình sau khi đã che dữ liệu.",
        ),
        "gf_b_save_first": ("Save the draft first.", "Hãy lưu bản nháp trước."),
        "gf_b_purpose": (
            "Tests the rule on attack cases (must be caught) and normal cases (must pass). A "
            "pass lets you mark the version tested.",
            "Thử quy tắc trên ca tấn công (phải bị bắt) và ca bình thường (phải được qua). Đạt thì "
            "có thể đánh dấu phiên bản đã kiểm thử.",
        ),
        "gf_s_purpose": (
            "Trial run: the guardian watches live calls and records what it would do. Nothing is "
            "blocked. Mark each finding Correct or False.",
            "Chạy thử: guardian theo dõi lệnh gọi thật và ghi lại việc nó sẽ làm. Không chặn gì. "
            "Đánh dấu từng phát hiện là Đúng hoặc Sai.",
        ),
        "gf_s_allow_hint": (
            "Agents on this list are not checked. Each entry ends on a date.",
            "Các agent trong danh sách này không bị kiểm tra. Mỗi mục có ngày hết hạn.",
        ),
        "gf_p_purpose": (
            "Two different people approve a finished trial run: the lead of the owner group and "
            "platform security. The author never approves. Then the owner lead sets the version "
            "live. A live version cannot be changed.",
            "Hai người khác nhau phê duyệt lần chạy thử đã xong: trưởng nhóm sở hữu và bảo mật "
            "nền tảng. Tác giả không được phê duyệt. Sau đó trưởng nhóm sở hữu đưa phiên bản vào "
            "hoạt động. Phiên bản đang chạy không sửa được.",
        ),
        "gf_p_live_note": (
            "This version is live. Its action applies to calls in its scope.",
            "Phiên bản này đang chạy. Hành động của nó áp dụng cho các lệnh gọi trong phạm vi.",
        ),
    }
)

NEW.update(
    {
        "gf_owner": ("Owner", "Nhóm sở hữu"),
        "gf_where": ("Where it runs", "Nơi chạy"),
        "gf_about_full": (
            "Only a deterministic rule (regex, keyword list, policy) can block or redact. A "
            "model type (classifier, judge prompt) can only log or ask for approval.",
            "Chỉ quy tắc xác định (regex, danh sách từ khóa, chính sách) mới được chặn hoặc che. "
            "Loại dùng mô hình (bộ phân loại, câu lệnh giám khảo) chỉ được ghi nhận hoặc xin "
            "phê duyệt.",
        ),
        "gf_new_title": ("New guardian", "Guardian mới"),
        "gf_new_purpose": (
            "Describe the rule in words, review the draft, then save it.",
            "Mô tả quy tắc bằng lời, xem lại bản nháp, rồi lưu.",
        ),
        "gf_sec_describe": ("Describe the guardian", "Mô tả guardian"),
        "gf_f_id": ("Identifier (letters, digits, dashes)", "Mã định danh (chữ, số, dấu gạch)"),
        "gf_f_does": ("What it does", "Nó làm gì"),
        "gf_f_type": ("Rule type", "Loại quy tắc"),
        "gf_f_action": ("When it matches", "Khi khớp quy tắc"),
        "gf_adv": ("Advanced", "Nâng cao"),
        "gf_adv_json": ("Rule definition (JSON)", "Định nghĩa quy tắc (JSON)"),
        "gf_f_sens": ("Sensitivity (1-4)", "Độ nhạy (1-4)"),
        "gf_f_thr": ("Pass thresholds for the test", "Ngưỡng đạt của bài kiểm thử"),
        "gf_f_tpr": ("Catch rate at least (%)", "Tỷ lệ bắt đúng tối thiểu (%)"),
        "gf_f_fpr": ("False-alarm rate at most (%)", "Tỷ lệ báo nhầm tối đa (%)"),
        "gf_f_p95": ("Speed, 95th percentile at most (ms)", "Tốc độ, phân vị 95 tối đa (ms)"),
        "gf_f_days": ("Trial run days", "Số ngày chạy thử"),
        "gf_steps_new": (
            "Next steps after saving: Test, Trial run, Approval, Live.",
            "Các bước sau khi lưu: Kiểm thử, Chạy thử, Phê duyệt, Đang chạy.",
        ),
        "gf_nav_rule": ("Rule", "Quy tắc"),
        "gf_nav_test": ("Test", "Kiểm thử"),
        "gf_nav_trial": ("Trial run", "Chạy thử"),
        "gf_nav_approval": ("Approval", "Phê duyệt"),
        "gf_nav_history": ("History", "Lịch sử"),
        "gf_status_line": (
            "{state}, version {v}. Owner: {owner}. Updated {when}.",
            "{state}, phiên bản {v}. Nhóm sở hữu: {owner}. Cập nhật {when}.",
        ),
        "gf_step_draft": ("Draft", "Nháp"),
        "gf_step_benchmarked": ("Tested", "Đã kiểm thử"),
        "gf_step_shadow": ("Trial run", "Chạy thử"),
        "gf_step_approved": ("Approved", "Đã duyệt"),
        "gf_step_live": ("Live", "Đang chạy"),
        "gf_step_retired": ("Retired", "Đã ngưng"),
        "gf_b_latest": ("Latest run: {status}.", "Lần chạy gần nhất: {status}."),
        "gf_b_details": ("Details", "Chi tiết"),
        "gf_b_manage": ("Manage test packs", "Quản lý bộ kiểm thử"),
        "gf_b_all_levels": ("All sensitivity levels", "Mọi mức nhạy"),
        "gf_b_c_level": ("Level", "Mức"),
        "gf_b_c_caught": ("Caught", "Bắt đúng"),
        "gf_b_c_missed": ("Missed", "Bỏ sót"),
        "gf_b_c_false": ("False alarms", "Báo nhầm"),
        "gf_b_c_ok": ("Correctly passed", "Cho qua đúng"),
        "gf_b_c_rate": ("Catch rate", "Tỷ lệ bắt đúng"),
        "gf_b_c_frate": ("False-alarm rate", "Tỷ lệ báo nhầm"),
        "gf_b_c_speed": ("Speed (ms)", "Tốc độ (ms)"),
        "gf_b_pass_line": (
            "Pass. Catches {tpr}% (needs {mtpr}%). False alarms {fpr}% (limit {mfpr}%).",
            "Đạt. Bắt đúng {tpr}% (cần {mtpr}%). Báo nhầm {fpr}% (giới hạn {mfpr}%).",
        ),
        "gf_b_fail_line": (
            "Not passed. Catches {tpr}% (needs {mtpr}%). False alarms {fpr}% (limit {mfpr}%).",
            "Chưa đạt. Bắt đúng {tpr}% (cần {mtpr}%). Báo nhầm {fpr}% (giới hạn {mfpr}%).",
        ),
        "gf_s_k_days": ("Days", "Ngày"),
        "gf_s_k_calls": ("Calls seen", "Lệnh gọi đã xem"),
        "gf_s_k_act": ("Would act", "Sẽ hành động"),
        "gf_s_k_ok": ("Correct", "Đúng"),
        "gf_s_k_false": ("False", "Sai"),
        "gf_s_k_pending": ("Not reviewed", "Chưa xem xét"),
        "gf_s_k_skipped": ("Skipped (budget)", "Bỏ qua (ngân sách)"),
        "gf_s_k_rate": ("False rate / limit", "Tỷ lệ sai / giới hạn"),
        "gf_s_show_all": ("Show all {n}", "Xem cả {n}"),
        "gf_s_first": ("First {n} of {total} findings", "{n} phát hiện đầu / {total}"),
        "gf_s_c_rule": ("Finding", "Phát hiện"),
        "gf_p_slug_details": ("Details", "Chi tiết"),
        "gf_p_slug_label": ("Name used in logs", "Tên dùng trong nhật ký"),
        "gf_hist_none": ("No events yet.", "Chưa có sự kiện nào."),
        "gfe_created": ("created the draft", "tạo bản nháp"),
        "gfe_saved": ("saved the draft", "lưu bản nháp"),
        "gfe_new_version": ("made a new version", "tạo phiên bản mới"),
        "gfe_benchmarked": ("marked the version tested", "đánh dấu đã kiểm thử"),
        "gfe_shadow_started": ("started a trial run", "bắt đầu chạy thử"),
        "gfe_shadow_stopped": ("stopped the trial run", "dừng chạy thử"),
        "gfe_approval": ("gave an approval", "đã phê duyệt"),
        "gfe_approved": ("version approved", "phiên bản đã được duyệt"),
        "gfe_live": ("set the version live", "đưa phiên bản vào chạy"),
        "gfe_retired": ("retired the version", "ngưng phiên bản"),
        "gfe_rolled_back": ("rolled back", "khôi phục phiên bản trước"),
        "gfe_reopened": ("reopened as draft", "mở lại thành bản nháp"),
        "gfe_allow_added": ("added an allow-list entry", "thêm một mục cho phép"),
        "gfe_allow_removed": ("removed an allow-list entry", "xóa một mục cho phép"),
        "gfe_allow_expired": ("an allow-list entry expired", "một mục cho phép hết hạn"),
    }
)


# --- playground ---
UX5.update(
    {
        "playground_purpose": (
            "Test what the gate would decide for a call. Nothing is sent or saved.",
            "Thử xem cổng sẽ quyết định thế nào cho một lệnh gọi. Không gửi và không lưu gì.",
        ),
        "pg_args": ("Call details (JSON)", "Chi tiết lệnh gọi (JSON)"),
        "pg_context": ("Extra details (optional)", "Chi tiết bổ sung (tùy chọn)"),
        "pg_consumer": ("Caller id", "Mã bên gọi"),
        "pg_tool_class": ("Tool type", "Loại công cụ"),
        "pg_samples_line": ("Pick a sample to fill the form.", "Chọn một mẫu để điền biểu mẫu."),
    }
)

NEW.update(
    {
        "pg_advanced": ("Advanced", "Nâng cao"),
        "pg_version": ("Agent version", "Phiên bản tác tử"),
    }
)


# --- analytics tabs, metrics ---
UX5.update(
    {
        "an_purpose": (
            "Gate results, tool use and oversight, per agent.",
            "Kết quả của cổng, mức dùng công cụ và giám sát, theo từng tác tử.",
        ),
        "an_window_days": (
            "{a} to {b} ({n} days)",
            "{a} đến {b} ({n} ngày)",
        ),
        "an_window_stored": (
            "Every stored day, {a} to {b}",
            "Mọi ngày đã lưu, {a} đến {b}",
        ),
        "an_window_stored_none": ("Every stored day (none yet)", "Mọi ngày đã lưu (chưa có)"),
        "an_window_live": ("Since the service started", "Từ lúc dịch vụ khởi động"),
        "an_p95": ("95th percentile (ms)", "Phân vị 95 (ms)"),
    }
)

NEW.update(
    {
        "an_show_all": ("Show all {n}", "Xem cả {n}"),
        "an_how": ("How counts are computed", "Cách tính số liệu"),
        "an_totals_differ": (
            "Totals here count by verdict, so they can differ from the tiles above.",
            "Tổng ở đây đếm theo phán quyết nên có thể khác các ô phía trên.",
        ),
        "an_c_reported": ("Reported", "Đã báo cáo"),
        "an_c_masked": ("Data masked", "Đã che dữ liệu"),
        "an_c_paused": ("Paused", "Đã tạm dừng"),
        "an_c_blocked": ("Blocked", "Đã chặn"),
        "an_c_skipped": ("Skipped", "Đã bỏ qua"),
        "an_c_notchk": ("Not checked", "Chưa kiểm tra"),
        "an_lat_none": (
            "No calls checked yet since the service started.",
            "Chưa có lệnh gọi nào được kiểm tra từ lúc dịch vụ khởi động.",
        ),
        "an_lat_none_line": (
            "Numbers appear after the first call.",
            "Số liệu xuất hiện sau lệnh gọi đầu tiên.",
        ),
        "an_lat_calls": ("Calls measured", "Lệnh gọi đã đo"),
        "an_lat_p50": ("Median (ms)", "Trung vị (ms)"),
        "an_lat_p95": ("95th percentile (ms)", "Phân vị 95 (ms)"),
        "an_lat_p99": ("99th percentile (ms)", "Phân vị 99 (ms)"),
        "an_lat_max": ("Slowest (ms)", "Chậm nhất (ms)"),
        "an_det_p50": ("Median (ms)", "Trung vị (ms)"),
        "an_det_p95": ("95th percentile (ms)", "Phân vị 95 (ms)"),
        "an_det_result": ("Test result", "Kết quả kiểm thử"),
        "an_det_notrun": ("Not run", "Chưa chạy"),
        "an_det_cmd_label": ("Run the detector test", "Chạy kiểm thử bộ phát hiện"),
        "an_more_codes": ("more finding codes", "mã phát hiện khác"),
        "an_mon_purpose": (
            "Status of each monitor per agent. Agents with nothing to measure are folded.",
            "Trạng thái từng bộ giám sát theo tác tử. Tác tử không có gì để đo được gộp lại.",
        ),
        "an_mon_line": (
            "{ok} ok, {nd} no data, {na} not applicable",
            "{ok} bình thường, {nd} chưa có dữ liệu, {na} không áp dụng",
        ),
        "an_mon_fold": (
            "agents: not applicable (nothing to measure)",
            "tác tử: không áp dụng (không có gì để đo)",
        ),
        "an_no_data": (
            "No data yet. Metrics appear after the first daily run.",
            "Chưa có dữ liệu. Số liệu xuất hiện sau lần chạy hằng ngày đầu tiên.",
        ),
        "an_chain": ("Evidence chain", "Chuỗi bằng chứng"),
        "an_chain_line": (
            "{lanes} lanes, {entries} entries.",
            "{lanes} làn, {entries} bản ghi.",
        ),
        "an_chain_open": ("Open the evidence chain", "Mở chuỗi bằng chứng"),
    }
)


# --- traces ---
UX5.update(
    {
        "traces_why": (
            "Open a trace to see each step. Text is masked.",
            "Mở một dấu vết để xem từng bước. Văn bản đã được che.",
        ),
        "digest_only": (
            "No text stored for this step. Only hashes and numbers.",
            "Bước này không lưu văn bản. Chỉ có mã băm và số.",
        ),
    }
)

NEW.update(
    {
        "tr_trace": ("Trace", "Dấu vết"),
        "tr_steps": ("Steps", "Số bước"),
        "tr_checks": ("Checks", "Kiểm tra"),
        "tr_paused": ("Paused", "Đã tạm dừng"),
        "tr_blocked": ("Blocked", "Đã chặn"),
        "tr_blocked_paused": ("Blocked and paused", "Đã chặn và tạm dừng"),
        "tr_alert": ("Alert", "Cảnh báo"),
        "tr_judge": ("AI judge notes: {n}", "Ghi chú của giám khảo AI: {n}"),
        "tr_ai_judge": ("AI judge", "Giám khảo AI"),
        "tr_more_filters": ("More filters", "Thêm bộ lọc"),
        "tr_view_case": ("View case", "Xem vụ việc"),
        "tr_view_decision": ("View decision", "Xem quyết định"),
        "tr_view_chain": ("View in evidence chain", "Xem trong chuỗi bằng chứng"),
        "tr_meta": ("Steps: {n}. Duration: {ms} ms.", "Số bước: {n}. Thời lượng: {ms} ms."),
    }
)


def texts(lang: str) -> dict[str, str]:
    """``NEW`` for one language, as a plain dict a template reads (``x.cat_all``)."""
    i = 1 if lang == "vi" else 0
    return {k: v[i] for k, v in NEW.items()}
