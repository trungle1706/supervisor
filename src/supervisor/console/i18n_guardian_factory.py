# ruff: noqa: E501
"""Labels of the guardian factory (WP-G1), English and Vietnamese, prefix ``gf_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

GF: dict[str, tuple[str, str]] = {
    "gf_title": ("Guardian factory", "Xưởng tạo guardian"),
    "gf_purpose": (
        "Define a detector as data: a regex, a keyword list, a classifier, a judge prompt or a small policy. Write the rule in words, check the artifact the platform drafts, then save it as a draft.",
        "Định nghĩa một bộ phát hiện dưới dạng dữ liệu: regex, danh sách từ khóa, bộ phân loại, câu lệnh cho giám khảo hoặc chính sách nhỏ. Viết quy tắc bằng lời, kiểm tra bản nháp do nền tảng soạn, rồi lưu thành bản nháp.",
    ),
    "gf_why": (
        "Only a deterministic rule (regex, keyword list, policy) can block or redact. A model type can only log or ask for approval.",
        "Chỉ quy tắc xác định (regex, danh sách từ khóa, chính sách) mới được chặn hoặc che. Loại dùng mô hình chỉ được ghi nhận hoặc yêu cầu phê duyệt.",
    ),
    "gf_new": ("New guardian", "Guardian mới"),
    "gf_filter": ("Filter", "Lọc"),
    "gf_all": ("all", "tất cả"),
    "gf_state": ("State", "Trạng thái"),
    "gf_group": ("Owner group", "Nhóm sở hữu"),
    "gf_stage": ("Stage", "Giai đoạn"),
    "gf_type": ("Type", "Loại"),
    "gf_id": ("Id", "Mã"),
    "gf_name": ("Name", "Tên"),
    "gf_description": ("Description", "Mô tả"),
    "gf_version": ("Version", "Phiên bản"),
    "gf_updated": ("Updated", "Cập nhật"),
    "gf_none": ("No guardian definitions match.", "Không có định nghĩa guardian phù hợp."),
    "gf_count": ("{n} guardian(s)", "{n} guardian"),
    "gf_action": ("Action on fail", "Hành động khi vi phạm"),
    "gf_action_hint": (
        "regex, keyword list and policy: block, redact, require approval or log. Classifier and judge prompt: log or require approval only.",
        "regex, danh sách từ khóa và chính sách: chặn, che, yêu cầu phê duyệt hoặc ghi nhận. Bộ phân loại và câu lệnh giám khảo: chỉ ghi nhận hoặc yêu cầu phê duyệt.",
    ),
    "gf_sensitivity": ("Sensitivity (1-4)", "Độ nhạy (1-4)"),
    "gf_scope": ("Scope", "Phạm vi"),
    "gf_scope_agents": (
        "Agents (comma list or *)",
        "Agent (danh sách phân cách bằng dấu phẩy hoặc *)",
    ),
    "gf_scope_tools": (
        "Tools (comma list or *)",
        "Công cụ (danh sách phân cách bằng dấu phẩy hoặc *)",
    ),
    "gf_scope_data": (
        "Data classes (comma list, empty = all)",
        "Nhóm dữ liệu (danh sách, trống = tất cả)",
    ),
    "gf_thresholds": ("Thresholds (whole numbers)", "Ngưỡng (số nguyên)"),
    "gf_min_tpr": ("Min true positive rate (%)", "Tỷ lệ phát hiện đúng tối thiểu (%)"),
    "gf_max_fpr": ("Max false positive rate (%)", "Tỷ lệ báo nhầm tối đa (%)"),
    "gf_max_p95": ("Max p95 latency (ms)", "Độ trễ p95 tối đa (ms)"),
    "gf_shadow_days": ("Shadow days", "Số ngày chạy bóng"),
    "gf_bench_pack": (
        "Benchmark pack id (may be empty in draft)",
        "Mã bộ đánh giá (có thể trống ở bản nháp)",
    ),
    "gf_words_box": ("Write the rule in words", "Viết quy tắc bằng lời"),
    "gf_words_hint": (
        'For example: block account numbers, or the words "urgent transfer", "secret code". The sentence goes to the model only after masking, and only when no library pattern fits.',
        'Ví dụ: chặn số tài khoản, hoặc các từ "chuyển khoản gấp", "mã bí mật". Câu chỉ được gửi tới mô hình sau khi che dữ liệu, và chỉ khi thư viện không có mẫu phù hợp.',
    ),
    "gf_draft_btn": ("Draft the artifact", "Soạn bản nháp"),
    "gf_draft_note": (
        "This is a draft. Nothing is saved until you press Save.",
        "Đây là bản nháp. Chưa có gì được lưu cho tới khi bạn bấm Lưu.",
    ),
    "gf_draft_src_library": ("from the pattern library", "từ thư viện mẫu"),
    "gf_draft_src_model": ("from the gateway model", "từ mô hình qua cổng"),
    "gf_over_broad": (
        "Over broad: the artifact matches {n} percent of a benign sample. It is not refused. Check it.",
        "Quá rộng: bản nháp khớp {n} phần trăm mẫu lành tính. Không bị từ chối. Hãy kiểm tra lại.",
    ),
    "gf_artifact": ("Artifact (JSON, you can edit it)", "Bản nháp (JSON, bạn có thể sửa)"),
    "gf_save": ("Save draft", "Lưu bản nháp"),
    "gf_create": ("Create draft", "Tạo bản nháp"),
    "gf_retire": ("Retire", "Ngừng sử dụng"),
    "gf_reopen": ("Reopen as draft", "Mở lại thành bản nháp"),
    "gf_new_version": ("New version", "Phiên bản mới"),
    "gf_view_only": (
        "You can read this guardian but not change it.",
        "Bạn chỉ xem được guardian này, không sửa được.",
    ),
    "gf_not_draft": (
        "Only a draft is edited in place. Make a new version to change it.",
        "Chỉ bản nháp mới sửa trực tiếp. Hãy tạo phiên bản mới để thay đổi.",
    ),
    "gf_history": ("History", "Lịch sử"),
    "gf_bench_panel": ("Benchmark", "Đánh giá chuẩn"),
    "gf_bench_soon": (
        "The benchmark (true positive rate, false positive rate, p95 latency) arrives with the next work package.",
        "Phần đánh giá chuẩn (tỷ lệ phát hiện đúng, báo nhầm, độ trễ p95) sẽ có ở gói công việc tiếp theo.",
    ),
    "gf_shadow_panel": ("Shadow mode and promotion", "Chạy bóng và thăng cấp"),
    "gf_shadow_soon": (
        "Shadow runs on live traffic, approval and going live arrive with a later work package. Only draft and retired can be reached now.",
        "Chạy bóng trên lưu lượng thật, phê duyệt và đưa vào hoạt động sẽ có ở gói sau. Hiện chỉ có bản nháp và ngừng sử dụng.",
    ),
    "gf_state_draft": ("draft", "nháp"),
    "gf_state_benchmarked": ("benchmarked", "đã đánh giá"),
    "gf_state_shadow": ("shadow", "chạy bóng"),
    "gf_state_approved": ("approved", "đã duyệt"),
    "gf_state_live": ("live", "đang chạy"),
    "gf_state_retired": ("retired", "ngừng sử dụng"),
    "gf_open": ("Open", "Mở"),
    "gf_off_note": (
        "Illustrative and not legal advice.",
        "Chỉ mang tính minh họa, không phải tư vấn pháp lý.",
    ),
}
