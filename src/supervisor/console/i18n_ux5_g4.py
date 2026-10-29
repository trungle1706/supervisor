# ruff: noqa: E501
"""UX5 group G4 text (CONSOLE_UX5): agent page, catalogues, inventory, tools, credentials,
integrations, users, audit log. ``G4`` adds new keys (merged into ``i18n._T`` by one line in
``i18n.py``; they exist with the flag off but nothing reads them). ``UX5`` overrides existing
keys and is read only with the flag on (``i18n_ux5.MODULES``)."""

from __future__ import annotations

G4: dict[str, tuple[str, str]] = {
    "g4_more": ("More", "Thêm"),
    "g4_grp_review": ("Review", "Rà soát"),
    "g4_grp_flow": ("Onboarding steps", "Các bước đưa vào vận hành"),
    "g4_demo_judge": ("Demo judge", "Bộ đánh giá thử"),
    "g4_demo_judge_tip": (
        "A built-in test judge answers here (mock). Replace it with a real model before production.",
        "Một bộ đánh giá thử (mock) đang trả lời ở đây. Hãy thay bằng mô hình thật trước khi vận hành.",
    ),
    "g4_more_facts": ("More facts", "Thêm dữ kiện"),
    "g4_last_days": ("Last {n} days", "{n} ngày qua"),
    "g4_suggest_only": ("Suggestion only (details)", "Chỉ là gợi ý (chi tiết)"),
    "g4_tools_none": (
        "{agent}: no tool calls in this window.",
        "{agent}: không có lệnh gọi công cụ nào trong khoảng này.",
    ),
    "g4_tools_none_all": (
        "No agent called a tool in this window.",
        "Không tác nhân nào gọi công cụ trong khoảng này.",
    ),
    "g4_tools_idle": (
        "{n} agents had no tool calls in this window.",
        "{n} tác nhân không gọi công cụ nào trong khoảng này.",
    ),
    "g4_details": ("Details", "Chi tiết"),
    "g4_results_zero": ("Results (all zero): show", "Kết quả (đều bằng 0): hiện"),
    "g4_guardian_list": ("Guardian list ({n}): show", "Danh sách công cụ bảo vệ ({n}): hiện"),
    "g4_auth_off": (
        "Agent authentication is off. Turn it on before production.",
        "Xác thực tác nhân đang tắt. Hãy bật trước khi vận hành.",
    ),
    "g4_dev_guide": (
        "How to connect this agent (developer guide)",
        "Cách kết nối tác nhân này (hướng dẫn cho nhà phát triển)",
    ),
    "g4_cat_models": (
        "Models and endpoints found in the workspace.",
        "Mô hình và endpoint tìm thấy trong workspace.",
    ),
    "g4_cat_tools": (
        "Tools that agents can call, found by the inventory scan.",
        "Công cụ mà tác nhân có thể gọi, do quét kiểm kê tìm thấy.",
    ),
    "g4_cat_datasets": ("Datasets found in the workspace.", "Bộ dữ liệu tìm thấy trong workspace."),
    "g4_cat_mcp": ("MCP servers found in the workspace.", "Máy chủ MCP tìm thấy trong workspace."),
    "g4_mcp_none": (
        "No MCP servers found yet. The next inventory scan fills this list.",
        "Chưa tìm thấy máy chủ MCP nào. Lần quét kiểm kê tới sẽ điền danh sách này.",
    ),
    "g4_cat_none": (
        "Nothing here yet. The next inventory scan fills this list.",
        "Chưa có gì. Lần quét kiểm kê tới sẽ điền danh sách này.",
    ),
    "g4_search": ("Search by name", "Tìm theo tên"),
    "g4_search_btn": ("Search", "Tìm"),
    "g4_all_statuses": ("All statuses", "Mọi trạng thái"),
    "g4_found": ("Found", "Số lần thấy"),
    "g4_no_match": (
        "Nothing matches. Change the search or the status.",
        "Không có kết quả khớp. Hãy đổi từ khóa hoặc trạng thái.",
    ),
    "g4_inv_purpose": (
        "What each agent runs on, and workspace items nobody has registered.",
        "Mỗi tác nhân chạy trên gì, và các mục trong workspace chưa ai đăng ký.",
    ),
    "g4_evidence": ("Evidence", "Bằng chứng"),
    "g4_evidence_n": ("Evidence ({n})", "Bằng chứng ({n})"),
    "g4_int_purpose": (
        "Connect an agent to Supervisor: choose a method, then the agent.",
        "Kết nối tác nhân với Supervisor: chọn cách kết nối, rồi chọn tác nhân.",
    ),
    "g4_int_nokey": (
        "{n} of {total} agents have no key yet.",
        "{n} / {total} tác nhân chưa có khóa.",
    ),
    "g4_int_fold": (
        "agents: state {state}, key {keystate}, mode {mode}, no consumers.",
        "tác nhân: trạng thái {state}, khóa {keystate}, chế độ {mode}, không có bên dùng.",
    ),
    "g4_int_show_all": ("Show all {n} agents", "Hiện cả {n} tác nhân"),
    "g4_int_show_less": ("Show only the exceptions", "Chỉ hiện các trường hợp khác thường"),
    "g4_cred_purpose": (
        "Which agents have a key and who may act for them.",
        "Tác nhân nào có khóa và ai được hành động thay mặt.",
    ),
    "g4_cred_nokey": ("agents have no key yet.", "tác nhân chưa có khóa."),
    "g4_unregistered": ("not registered", "chưa đăng ký"),
    "g4_cred_rotate": ("How to issue or rotate a key", "Cách cấp hoặc đổi khóa"),
    "g4_users_purpose": (
        "Who holds which role, and what each role may do. Read only.",
        "Ai giữ vai trò nào, và mỗi vai trò được làm gì. Chỉ đọc.",
    ),
    "g4_matrix_show": ("Role matrix: show {n} permissions", "Ma trận vai trò: hiện {n} quyền"),
    "g4_soon": ("Coming soon", "Sắp có"),
    "g4_cov_none": ("no traffic yet", "chưa có lưu lượng"),
    "g4_audit_trail": ("Audit trail: {n} entries", "Nhật ký bằng chứng: {n} mục"),
}

UX5: dict[str, tuple[str, str]] = {
    "an_purpose": (
        "How agents use their tools and how the gate performs.",
        "Cách tác nhân dùng công cụ và cổng hoạt động ra sao.",
    ),
    "an_why": (
        "Range and agent apply to all tabs.",
        "Khoảng thời gian và tác nhân áp dụng cho mọi thẻ.",
    ),
    "no_audit": ("No entries match.", "Không có mục nào khớp."),
    "no_audit_line": ("Change the filters.", "Hãy đổi bộ lọc."),
    "no_identities": ("No identities mapped.", "Chưa có danh tính nào được ánh xạ."),
    "sch_purpose": (
        "Checks that the warehouse matches the data model. Read only.",
        "Kiểm tra kho dữ liệu khớp với mô hình dữ liệu. Chỉ đọc.",
    ),
    "sch_why": (
        "A missing table or column breaks console pages. The app never changes the warehouse. An admin runs the fix plan.",
        "Thiếu bảng hoặc cột sẽ làm hỏng các trang console. Ứng dụng không bao giờ sửa kho dữ liệu. Quản trị viên chạy kế hoạch sửa.",
    ),
    "ingress_off": (
        "Agent authentication is off. The gate accepts calls without a key.",
        "Xác thực tác nhân đang tắt. Cổng nhận lệnh gọi không cần khóa.",
    ),
    "integrations_note": (
        "Pager, ITSM and SCIM are demo stubs until connected.",
        "Pager, ITSM và SCIM chỉ là bản mô phỏng cho đến khi được kết nối.",
    ),
    "nv3_t_unmanaged": ("Inventory", "Kiểm kê"),
    "agents_purpose": (
        "Every agent the bank runs, and its gate state.",
        "Mọi tác nhân của ngân hàng và trạng thái cổng của nó.",
    ),
    # agent page: guardians, policy, tools, inventory, tabs
    "mya_g_status_line": (
        "Effective means on here and not switched off for the AI system. Gate rules cannot be switched off.",
        "Hiệu lực nghĩa là đang bật ở đây và chưa bị tắt cho hệ thống AI. Quy tắc cổng không thể tắt.",
    ),
    "mya_why_file_off": ("Switched off by the platform team", "Do đội nền tảng tắt"),
    "mya_why_flag_off": ("Not enabled in this environment", "Chưa bật trong môi trường này"),
    "mya_g_none_enabled": ("No judges enabled.", "Chưa bật bộ đánh giá nào."),
    "mya_g_no_packs": ("No pack results.", "Chưa có kết quả gói kiểm thử."),
    "as_no_agent_results": ("No assurance run yet.", "Chưa có lần kiểm thử nào."),
    "no_rules": (
        "No rules apply to this agent yet.",
        "Chưa có quy tắc nào áp dụng cho tác nhân này.",
    ),
    "policy_no_allow": ("No approved tools listed.", "Chưa có công cụ được duyệt."),
    "policy_readonly": (
        "Read only. Rules change by pull request.",
        "Chỉ đọc. Quy tắc đổi qua pull request.",
    ),
    "tl_unknown_agent": (
        "No policy entry yet, so no tools to compare. Add this agent to the policy, or run onboarding.",
        "Chưa có mục chính sách nên chưa có công cụ để so sánh. Thêm tác nhân vào chính sách hoặc chạy quy trình đưa vào vận hành.",
    ),
    "inv_not_listed": ("Not in the inventory yet.", "Chưa có trong kho kiểm kê."),
    "inv_not_listed_line": (
        "Check again after the next scan.",
        "Hãy kiểm tra lại sau lần quét tới.",
    ),
    "tl_in_analytics": ("Tool usage for all agents", "Mức dùng công cụ của mọi tác nhân"),
    "sbv_clock": (
        "SBV 24 h report (old rule, Circular 53 removed it)",
        "Báo cáo NHNN 24 giờ (quy định cũ, Thông tư 53 đã bỏ)",
    ),
    "rk_level": ("Risk level", "Mức rủi ro"),
    "tk_tab_none": ("No task list yet.", "Chưa có danh sách công việc."),
    "tp_tab_off": (
        "Transparency reports are not enabled. Ask an administrator.",
        "Báo cáo minh bạch chưa được bật. Hãy hỏi quản trị viên.",
    ),
    "ik_hint": (
        "Upload the agent code as a zip (max {mb} MB). Secrets are removed before storage. Each upload is a new attempt.",
        "Tải mã của tác nhân lên dạng zip (tối đa {mb} MB). Bí mật được loại bỏ trước khi lưu. Mỗi lần tải là một lần thử mới.",
    ),
    "ik_none": ("No source uploaded yet.", "Chưa tải mã nguồn nào."),
    "ik_upload": ("Upload zip", "Tải zip"),
    "fk_hint": (
        "Facts read from the uploaded code. Each fact cites a file and line. Facts without a citation are dropped.",
        "Dữ kiện đọc từ mã đã tải lên. Mỗi dữ kiện nêu tệp và dòng. Dữ kiện không có trích dẫn sẽ bị loại.",
    ),
    "fk_none": (
        "No facts yet. Upload the source (Source tab), then press Re-read.",
        "Chưa có dữ kiện. Hãy tải mã nguồn (thẻ Mã nguồn) rồi bấm Đọc lại.",
    ),
    "pd_hint": (
        "One report per source upload. Covers facts, readiness, assurance packs, red team and duties. The verdict follows fixed rules; no model sets it.",
        "Một báo cáo cho mỗi lần tải mã. Gồm dữ kiện, mức sẵn sàng, gói kiểm thử, red team và nghĩa vụ. Kết luận theo quy tắc cố định; không mô hình nào quyết định.",
    ),
    "pd_none": (
        "No assessment yet. Upload source and read facts first, then run the assessment.",
        "Chưa có đánh giá. Hãy tải mã nguồn và đọc dữ kiện trước, rồi chạy đánh giá.",
    ),
    "at_hint": (
        "Shows how this agent connects to the gate and which guardians watch it. Read only: Supervisor does not call the agent.",
        "Cho thấy tác nhân nối vào cổng thế nào và công cụ bảo vệ nào theo dõi nó. Chỉ đọc: Supervisor không gọi tác nhân.",
    ),
    "at_plug_is": ("Connection type:", "Kiểu kết nối:"),
    "at_check_hint": (
        "Refreshes from the store; does not call the agent.",
        "Làm mới từ kho dữ liệu; không gọi tác nhân.",
    ),
    "px_hint": (
        "Gate, judge, monitor and pack results for the last {days} days. Read only. Mock judges are counted separately.",
        "Kết quả cổng, bộ đánh giá, giám sát và gói kiểm thử trong {days} ngày qua. Chỉ đọc. Bộ đánh giá thử được đếm riêng.",
    ),
    "px_log_hint": (
        "Onboarding actions, oldest first. The tag shows who acted: rule, model or person. Rows never change.",
        "Các thao tác đưa vào vận hành, cũ nhất trước. Nhãn cho biết ai thực hiện: quy tắc, mô hình hay người. Dòng không bao giờ bị sửa.",
    ),
}
