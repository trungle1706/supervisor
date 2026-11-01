# ruff: noqa: E501
"""Labels of the inventory run dashboard (W4, FACTORY_INVENTORY_RUN), English and Vietnamese,
prefix ``finv_``. Merged into ``i18n._T`` by one line in ``i18n.py``. Wording follows the copy
style (plain business words, no setting names). Synthetic UI text only."""

from __future__ import annotations

_KEYS: dict[str, tuple[tuple[str, str], tuple[str, str], tuple[str, str]]] = {
    # key: (sentence, sentence for one system, short name for the open-question line)
    # each pair is (English, Vietnamese)
    "money_tool_no_gate": (
        (
            "{n} systems can send payments with no approval step",
            "{n} hệ thống có thể chuyển tiền mà không có bước phê duyệt",
        ),
        (
            "1 system can send payments with no approval step",
            "1 hệ thống có thể chuyển tiền mà không có bước phê duyệt",
        ),
        ("payments with no approval step", "chuyển tiền không có bước phê duyệt"),
    ),
    "declared_control_mismatch": (
        (
            "{n} systems say a person approves actions, but the code has no approval step",
            "{n} hệ thống khai có người phê duyệt, nhưng mã nguồn không có bước phê duyệt",
        ),
        (
            "1 system says a person approves actions, but the code has no approval step",
            "1 hệ thống khai có người phê duyệt, nhưng mã nguồn không có bước phê duyệt",
        ),
        (
            "human control that the code does not show",
            "kiểm soát của con người mà mã nguồn không thể hiện",
        ),
    ),
    "personal_data_fields": (
        (
            "{n} systems handle personal data fields such as ID numbers",
            "{n} hệ thống xử lý trường dữ liệu cá nhân như số căn cước",
        ),
        (
            "1 system handles personal data fields such as ID numbers",
            "1 hệ thống xử lý trường dữ liệu cá nhân như số căn cước",
        ),
        ("personal data in the code", "dữ liệu cá nhân trong mã nguồn"),
    ),
    "personal_data_mismatch": (
        (
            "{n} systems say they use no personal data, but the code handles it",
            "{n} hệ thống khai không dùng dữ liệu cá nhân, nhưng mã nguồn có xử lý",
        ),
        (
            "1 system says it uses no personal data, but the code handles it",
            "1 hệ thống khai không dùng dữ liệu cá nhân, nhưng mã nguồn có xử lý",
        ),
        ("personal data that the record does not show", "dữ liệu cá nhân chưa được khai báo"),
    ),
    "pii_export_tool": (
        (
            "{n} systems have a tool that can export personal data",
            "{n} hệ thống có công cụ có thể xuất dữ liệu cá nhân",
        ),
        (
            "1 system has a tool that can export personal data",
            "1 hệ thống có công cụ có thể xuất dữ liệu cá nhân",
        ),
        ("a tool that exports personal data", "công cụ xuất dữ liệu cá nhân"),
    ),
    "model_unknown": (
        (
            "{n} systems use an AI model that is not identified",
            "{n} hệ thống dùng mô hình AI chưa xác định được",
        ),
        (
            "1 system uses an AI model that is not identified",
            "1 hệ thống dùng mô hình AI chưa xác định được",
        ),
        ("an AI model that is not identified", "mô hình AI chưa xác định"),
    ),
    "no_tracing": (
        (
            "{n} systems keep no trace of what the AI does",
            "{n} hệ thống không lưu vết hoạt động của AI",
        ),
        (
            "1 system keeps no trace of what the AI does",
            "1 hệ thống không lưu vết hoạt động của AI",
        ),
        ("no trace of what the AI does", "không lưu vết hoạt động của AI"),
    ),
    "hardcoded_secret": (
        (
            "{n} systems keep a password or key inside the code",
            "{n} hệ thống để mật khẩu hoặc khóa ngay trong mã nguồn",
        ),
        (
            "1 system keeps a password or key inside the code",
            "1 hệ thống để mật khẩu hoặc khóa ngay trong mã nguồn",
        ),
        ("a password or key inside the code", "mật khẩu hoặc khóa trong mã nguồn"),
    ),
    "external_endpoint": (
        (
            "{n} systems send data to an outside service",
            "{n} hệ thống gửi dữ liệu đến dịch vụ bên ngoài",
        ),
        (
            "1 system sends data to an outside service",
            "1 hệ thống gửi dữ liệu đến dịch vụ bên ngoài",
        ),
        ("data sent to an outside service", "dữ liệu gửi đến dịch vụ bên ngoài"),
    ),
    "risk_level_mismatch": (
        (
            "{n} systems are high risk under Decision 33 but registered with a lower risk level",
            "{n} hệ thống có rủi ro cao theo Quyết định 33 nhưng đăng ký mức rủi ro thấp hơn",
        ),
        (
            "1 system is high risk under Decision 33 but registered with a lower risk level",
            "1 hệ thống có rủi ro cao theo Quyết định 33 nhưng đăng ký mức rủi ro thấp hơn",
        ),
        ("a risk level lower than Decision 33 says", "mức rủi ro thấp hơn Quyết định 33"),
    ),
    "tests_missing": (
        (
            "{n} systems have required tests that were not run",
            "{n} hệ thống chưa chạy các bài kiểm tra bắt buộc",
        ),
        (
            "1 system has required tests that were not run",
            "1 hệ thống chưa chạy các bài kiểm tra bắt buộc",
        ),
        ("required tests that were not run", "bài kiểm tra bắt buộc chưa chạy"),
    ),
    "tests_failed": (
        ("{n} systems failed a required test", "{n} hệ thống không đạt một bài kiểm tra bắt buộc"),
        ("1 system failed a required test", "1 hệ thống không đạt một bài kiểm tra bắt buộc"),
        ("a required test that failed", "bài kiểm tra bắt buộc không đạt"),
    ),
}

FINV: dict[str, tuple[str, str]] = {
    "finv_title": ("Run on the whole inventory", "Chạy trên toàn bộ danh mục"),
    "finv_entry": ("Run on the whole inventory", "Chạy trên toàn bộ danh mục"),
    "finv_banner": (
        "Simulation on the inventory. It does not change any assessment.",
        "Mô phỏng trên danh mục. Kết quả này không thay đổi bất kỳ đánh giá nào.",
    ),
    "finv_run_h": ("Run the agent on every AI system", "Chạy tác tử trên mọi hệ thống AI"),
    "finv_run_hint": (
        "The agent assesses each active AI system that needs this risk type. Nothing is saved to the systems.",
        "Tác tử đánh giá từng hệ thống AI đang hoạt động cần loại rủi ro này. Không có gì được ghi vào hệ thống.",
    ),
    "finv_version": ("Agent version", "Phiên bản tác tử"),
    "finv_run": ("Run on the inventory", "Chạy trên danh mục"),
    "finv_busy": (
        "A run of this agent is in progress. Wait or cancel it.",
        "Tác tử này đang có một lần chạy. Hãy chờ hoặc hủy.",
    ),
    "finv_limits": ("{n} systems are assessed at a time.", "Đánh giá {n} hệ thống cùng lúc."),
    "finv_limit_max": ("A run covers at most {n} systems.", "Mỗi lần chạy tối đa {n} hệ thống."),
    "finv_no_run": (
        "You can view runs. Only an editor of this agent can start one.",
        "Bạn xem được các lần chạy. Chỉ người chỉnh sửa tác tử này mới bắt đầu được.",
    ),
    "finv_runs": ("Earlier runs", "Các lần chạy trước"),
    "finv_no_runs": ("No run yet.", "Chưa có lần chạy nào."),
    "finv_open": ("Open", "Mở"),
    "finv_back": ("Back to the dashboard", "Quay lại bảng tổng quan"),
    "finv_c_started": ("Started", "Bắt đầu"),
    "finv_c_version": ("Version", "Phiên bản"),
    "finv_c_status": ("Status", "Trạng thái"),
    "finv_c_done": ("Systems", "Hệ thống"),
    "finv_c_model": ("Model", "Mô hình"),
    "finv_c_system": ("AI system", "Hệ thống AI"),
    "finv_c_systems": ("Systems", "Hệ thống"),
    "finv_c_team": ("Owner team", "Nhóm phụ trách"),
    "finv_c_level": ("Risk level", "Mức rủi ro"),
    "finv_c_result": ("Result", "Kết quả"),
    "finv_c_open": ("Open", "Câu hỏi mở"),
    "finv_c_found": ("Risks found", "Rủi ro phát hiện"),
    "finv_tiles_hint": (
        "Needs action: a check failed, or a finding from the code is a failure. Open questions need an answer from a person.",
        "Cần xử lý: có mục kiểm tra không đạt hoặc phát hiện từ mã nguồn không đạt. Câu hỏi mở cần một người trả lời.",
    ),
    "finv_c_clear": ("Clear", "Ổn"),
    "finv_draft_label": ("Draft agent, not tested", "Tác tử bản nháp, chưa kiểm thử"),
    "finv_draft_short": ("Draft", "Bản nháp"),
    "finv_state_draft": ("Draft", "Bản nháp"),
    "finv_state_tested": ("Tested", "Đã kiểm thử"),
    "finv_state_approved": ("Approved", "Đã phê duyệt"),
    "finv_state_live": ("Live", "Đang chạy"),
    "finv_state_retired": ("Retired", "Đã ngừng"),
    "finv_status_queued": ("Queued", "Đang chờ"),
    "finv_status_running": ("In progress", "Đang thực hiện"),
    "finv_status_done": ("Done", "Hoàn tất"),
    "finv_status_cancelled": ("Cancelled", "Đã hủy"),
    "finv_status_failed": ("Failed", "Thất bại"),
    "finv_running_h": ("Assessing the inventory", "Đang đánh giá danh mục"),
    "finv_running_hint": (
        "This page updates automatically. You can leave and come back.",
        "Trang tự cập nhật. Bạn có thể rời đi và quay lại sau.",
    ),
    "finv_progress": ("Progress", "Tiến độ"),
    "finv_progress_n": (
        "{done} of {total} systems assessed",
        "Đã đánh giá {done} / {total} hệ thống",
    ),
    "finv_progress_need": ("{n} need action so far", "Đến nay {n} cần xử lý"),
    "finv_cancel": ("Cancel run", "Hủy lần chạy"),
    "finv_cancelling": (
        "Cancelling. Systems already in progress will finish first.",
        "Đang hủy. Các hệ thống đang đánh giá sẽ hoàn tất trước.",
    ),
    "finv_failed": (
        "The run stopped with an error. Start it again.",
        "Lần chạy dừng do lỗi. Hãy chạy lại.",
    ),
    "finv_cancelled": (
        "The run was cancelled. {done} of {total} systems were assessed.",
        "Lần chạy đã bị hủy. Đã đánh giá {done} / {total} hệ thống.",
    ),
    "finv_cut": (
        "{n} more systems were left out. A run covers at most {max} systems.",
        "{n} hệ thống khác chưa được chạy. Mỗi lần chạy tối đa {max} hệ thống.",
    ),
    "finv_t_scope": ("Systems in scope", "Hệ thống trong phạm vi"),
    "finv_t_scope_sub": ("{n} of {inv} not in scope", "{n} / {inv} ngoài phạm vi"),
    "finv_t_assessed": ("Assessed", "Đã đánh giá"),
    "finv_t_errors": ("{n} could not be assessed", "{n} chưa đánh giá được"),
    "finv_t_fail": ("Needs action", "Cần xử lý"),
    "finv_t_open": ("Open questions only", "Chỉ còn câu hỏi mở"),
    "finv_t_clear": ("Clear", "Ổn"),
    "finv_t_calls": ("Model calls", "Lượt gọi mô hình"),
    "finv_t_tokens": ("Tokens", "Token"),
    "finv_t_time": ("Time", "Thời gian"),
    "finv_t_model": ("Model", "Mô hình"),
    "finv_found_h": ("Risks found", "Rủi ro phát hiện được"),
    "finv_found_hint": (
        "Failed checks and failed findings from the code. Choose one to see the systems.",
        "Mục không đạt và phát hiện không đạt từ mã nguồn. Chọn một mục để xem các hệ thống.",
    ),
    "finv_found_none": (
        "No failed check or finding in the systems assessed.",
        "Không có mục hoặc phát hiện nào không đạt trong các hệ thống đã đánh giá.",
    ),
    "finv_gaps_h": ("Evidence gaps", "Khoảng trống bằng chứng"),
    "finv_gaps_hint": (
        "Not risks yet. The evidence could not answer these, so a person must.",
        "Chưa phải rủi ro. Bằng chứng chưa trả lời được các mục này, nên cần một người xem xét.",
    ),
    "finv_gaps_none": ("No evidence gap.", "Không có khoảng trống bằng chứng."),
    "finv_gaps_all": ("Show all {n} gaps", "Xem cả {n} khoảng trống"),
    "finv_gap_pack": (
        "No test results yet for {n} systems ({m} required tests)",
        "Chưa có kết quả kiểm tra cho {n} hệ thống ({m} bài kiểm tra bắt buộc)",
    ),
    "finv_gap_pack_one": (
        "No test results yet for 1 system ({m} required tests)",
        "Chưa có kết quả kiểm tra cho 1 hệ thống ({m} bài kiểm tra bắt buộc)",
    ),
    "finv_headline_sentence": ("{n} systems: {text}", "{n} hệ thống: {text}"),
    "finv_headline_sentence_one": ("1 system: {text}", "1 hệ thống: {text}"),
    "finv_teams_all": ("Show all {n}", "Xem cả {n}"),
    "finv_risks_h": ("Top risks across the inventory", "Rủi ro hàng đầu trên toàn danh mục"),
    "finv_risks_hint": (
        "Findings grouped by what they mean. Choose one to see the systems.",
        "Phát hiện được gom theo ý nghĩa. Chọn một mục để xem các hệ thống.",
    ),
    "finv_risks_fallback": (
        "Showing failed checks, because no summary was written for this run.",
        "Đang hiển thị các mục kiểm tra không đạt vì lần chạy này chưa có bản tóm tắt.",
    ),
    "finv_risks_none": (
        "No risk found in the systems assessed.",
        "Không tìm thấy rủi ro trong các hệ thống đã đánh giá.",
    ),
    "finv_risks_all": ("Show all {n} risks", "Xem cả {n} rủi ro"),
    "finv_risk_plus_open": (
        "Plus {n} more with an open question",
        "Thêm {n} hệ thống còn câu hỏi mở",
    ),
    "finv_show": ("Show systems", "Xem hệ thống"),
    "finv_open_sentence": (
        "{n} systems need an answer on: {name}",
        "{n} hệ thống cần trả lời về: {name}",
    ),
    "finv_open_sentence_one": (
        "1 system needs an answer on: {name}",
        "1 hệ thống cần trả lời về: {name}",
    ),
    "finv_item_sentence_one": (
        "1 system does not meet: {item}",
        "1 hệ thống không đáp ứng: {item}",
    ),
    "finv_item_sentence": ("{n} systems do not meet: {item}", "{n} hệ thống không đáp ứng: {item}"),
    "finv_other_sentence": ("{n} systems: {text}", "{n} hệ thống: {text}"),
    "finv_sev_high": ("High", "Cao"),
    "finv_sev_medium": ("Medium", "Trung bình"),
    "finv_sev_low": ("Low", "Thấp"),
    "finv_mix_h": ("Results for each check", "Kết quả theo từng mục kiểm tra"),
    "finv_mix_hint": (
        "Each bar is the share of assessed systems with that result.",
        "Mỗi thanh là tỷ lệ hệ thống đã đánh giá có kết quả đó.",
    ),
    "finv_v_fail": ("Fail", "Không đạt"),
    "finv_v_question": ("Open question", "Câu hỏi mở"),
    "finv_v_pass": ("Pass", "Đạt"),
    "finv_v_not_applicable": ("Not applicable", "Không áp dụng"),
    "finv_v_none": ("No result", "Chưa có kết quả"),
    "finv_v_error": ("Not assessed", "Chưa đánh giá được"),
    "finv_team_h": ("By owner team", "Theo nhóm phụ trách"),
    "finv_level_h": ("By risk level", "Theo mức rủi ro"),
    "finv_level_high": ("High", "Cao"),
    "finv_level_medium": ("Medium", "Trung bình"),
    "finv_level_low": ("Low", "Thấp"),
    "finv_level_prohibited": ("Prohibited", "Bị cấm"),
    "finv_level_unspecified": ("Not set", "Chưa đặt"),
    "finv_heat_h": ("Systems and checks", "Hệ thống và mục kiểm tra"),
    "finv_f_search": ("Search", "Tìm kiếm"),
    "finv_f_search_ph": ("Name or id", "Tên hoặc mã"),
    "finv_f_all": ("All", "Tất cả"),
    "finv_f_customer": ("Used by customers", "Khách hàng sử dụng"),
    "finv_f_yes": ("Yes", "Có"),
    "finv_f_no": ("No", "Không"),
    "finv_f_apply": ("Apply", "Áp dụng"),
    "finv_f_reset": ("Clear filters", "Bỏ bộ lọc"),
    "finv_f_risk": ("Risk", "Rủi ro"),
    "finv_b_needs_action": ("Needs action", "Cần xử lý"),
    "finv_b_open": ("Open questions only", "Chỉ còn câu hỏi mở"),
    "finv_b_clear": ("Clear", "Ổn"),
    "finv_b_errors": ("Not assessed", "Chưa đánh giá được"),
    "finv_export": ("Download CSV", "Tải CSV"),
    "finv_shown_of": ("{shown} of {total} shown", "Hiển thị {shown} / {total}"),
    "finv_page_of": ("Page {page} of {pages}", "Trang {page} / {pages}"),
    "finv_prev": ("Previous {n}", "{n} trước"),
    "finv_next": ("Next {n}", "{n} tiếp"),
    "finv_none_match": ("No system matches these filters.", "Không có hệ thống nào khớp bộ lọc."),
    "finv_customer_short": ("Customer-facing", "Hướng đến khách hàng"),
    "finv_open_system": ("Open the AI system", "Mở hệ thống AI"),
    "finv_outcome_classification": ("Classification", "Phân loại"),
    "finv_outcome_derived": ("Level from the system record", "Mức lấy từ hồ sơ hệ thống"),
    "finv_exec_h": ("What it means", "Ý nghĩa"),
    "finv_exec_none": ("No finding to report.", "Không có phát hiện nào cần báo cáo."),
    "finv_no_exec": (
        "No plain-words summary for this system. The checks below are the result.",
        "Chưa có bản tóm tắt dễ hiểu cho hệ thống này. Kết quả là các mục kiểm tra bên dưới.",
    ),
    "finv_es_fail": ("Fail", "Không đạt"),
    "finv_es_open": ("Open question", "Câu hỏi mở"),
    "finv_es_pass": ("Pass", "Đạt"),
    "finv_action": ("Next step", "Bước tiếp theo"),
    "finv_role_system_owner": ("System owner", "Chủ sở hữu hệ thống"),
    "finv_role_risk_team": ("Risk team", "Đội rủi ro"),
    "finv_role_security": ("Security", "Bảo mật"),
    "finv_role_data_owner": ("Data owner", "Chủ sở hữu dữ liệu"),
    "finv_role_legal": ("Legal", "Pháp chế"),
    "finv_role_model_validation": ("Model validation", "Thẩm định mô hình"),
    "finv_find_h": ("Checks and evidence", "Kiểm tra và bằng chứng"),
    "finv_find_hint": (
        "Text is masked. Personal data is replaced.",
        "Văn bản đã được che. Dữ liệu cá nhân đã được thay thế.",
    ),
    "finv_find_none": ("No check result.", "Không có kết quả kiểm tra."),
    "finv_evidence_n": ("Evidence ({n})", "Bằng chứng ({n})"),
    "finv_sys_error": (
        "This system could not be assessed. Run the agent again.",
        "Chưa đánh giá được hệ thống này. Hãy chạy lại tác tử.",
    ),
}
for _k, (_en, _one, _name) in _KEYS.items():
    FINV[f"finv_key_{_k}"] = _en
    FINV[f"finv_key_{_k}_one"] = _one
    FINV[f"finv_keyname_{_k}"] = _name
