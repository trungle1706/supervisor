# ruff: noqa: E501
"""Labels of the Run assessment panel (WP-F4), English and Vietnamese, prefix ``orch_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only. Not legal advice."""

from __future__ import annotations

ORCH: dict[str, tuple[str, str]] = {
    "orch_title": ("Run assessment", "Chạy đánh giá"),
    "orch_intro": (
        "The assessment covers all eight risk types. Each type is assessed by its own AI agent or by rules, within a set budget. Results are suggestions. Confirm each risk type to make it final.",
        "Đánh giá bao gồm cả tám loại rủi ro. Mỗi loại do tác tử AI riêng hoặc quy tắc đánh giá, trong hạn mức đã đặt. Kết quả chỉ là đề xuất. Hãy xác nhận từng loại rủi ro để chốt kết quả.",
    ),
    "orch_run": ("Run assessment", "Chạy đánh giá"),
    "orch_running": (
        "Assessment running. This page updates automatically.",
        "Đang đánh giá. Trang này tự động cập nhật.",
    ),
    "orch_run_queued": ("Waiting", "Đang chờ"),
    "orch_run_running": ("Running", "Đang chạy"),
    "orch_run_done": ("Done", "Hoàn tất"),
    "orch_run_failed": ("Failed", "Không thành công"),
    "orch_attempt": ("Attempt", "Lần chạy"),
    "orch_outcome": ("Classification result", "Kết quả phân loại"),
    "orch_plan_hash": ("Plan ID", "Mã kế hoạch"),
    "orch_budget": ("Budget used", "Hạn mức đã dùng"),
    "orch_time": ("time", "thời gian"),
    "orch_tokens": ("tokens", "token"),
    "orch_summary": ("Summary", "Tóm tắt"),
    "orch_col_type": ("Risk type", "Loại rủi ro"),
    "orch_col_agent": ("Assessed by", "Đánh giá bởi"),
    "orch_col_status": ("Status", "Trạng thái"),
    "orch_col_verdict": ("Result", "Kết quả"),
    "orch_col_stop": ("Stopped at", "Dừng tại"),
    "orch_col_report": ("Report", "Báo cáo"),
    "orch_it_queued": ("Waiting", "Đang chờ"),
    "orch_it_running": ("Running", "Đang chạy"),
    "orch_it_done": ("Done", "Hoàn tất"),
    "orch_it_needs_person": ("Needs your review", "Cần bạn xem xét"),
    "orch_it_budget_exceeded": ("Over budget", "Vượt ngân sách"),
    "orch_it_failed": ("Failed", "Không thành công"),
    "orch_it_not_applicable": ("Not applicable", "Không áp dụng"),
    "orch_it_skipped": ("Skipped", "Đã bỏ qua"),
    "orch_needs_person": ("Needs your review", "Cần bạn xem xét"),
    "orch_reload": ("Refresh results", "Làm mới kết quả"),
    "orch_none": ("No assessment yet.", "Chưa có lần đánh giá nào."),
    "orch_ok_started": ("Assessment started.", "Đã bắt đầu đánh giá."),
    # Why a risk type is or is not assessed (plan reason codes of onboard/orchestrator.py).
    "orch_reason_bank_only": (
        "This risk type applies to banks only.",
        "Loại rủi ro này chỉ áp dụng cho ngân hàng.",
    ),
    "orch_reason_high_all_eight": (
        "High-risk systems are assessed on all eight risk types.",
        "Hệ thống rủi ro cao được đánh giá cả tám loại rủi ro.",
    ),
    "orch_reason_core": (
        "Core risk type: always assessed.",
        "Loại rủi ro cốt lõi: luôn được đánh giá.",
    ),
    "orch_reason_customer_decision_or_personal_data": (
        "The system makes customer decisions or uses personal data.",
        "Hệ thống đưa ra quyết định về khách hàng hoặc dùng dữ liệu cá nhân.",
    ),
    "orch_reason_no_customer_decision_no_personal_data": (
        "The system makes no customer decisions and uses no personal data.",
        "Hệ thống không quyết định về khách hàng và không dùng dữ liệu cá nhân.",
    ),
    "orch_reason_low_core_only": (
        "Low-risk systems are assessed on core risk types only.",
        "Hệ thống rủi ro thấp chỉ được đánh giá các loại rủi ro cốt lõi.",
    ),
    "orch_reason_unknown_assume_applies": (
        "It is not known whether this applies, so it is assessed.",
        "Chưa rõ loại rủi ro này có áp dụng hay không, nên vẫn được đánh giá.",
    ),
    "orch_reason_third_party_signal": (
        "The system relies on a third-party model or service.",
        "Hệ thống dựa vào mô hình hoặc dịch vụ của bên thứ ba.",
    ),
    "orch_reason_no_third_party_signal": (
        "The system does not rely on a third-party model or service.",
        "Hệ thống không dựa vào mô hình hoặc dịch vụ của bên thứ ba.",
    ),
    "orch_reason_dependency_signal": (
        "The system depends on outside tools, services or data.",
        "Hệ thống phụ thuộc vào công cụ, dịch vụ hoặc dữ liệu bên ngoài.",
    ),
    "orch_reason_no_dependency_signal": (
        "The system has no outside dependencies.",
        "Hệ thống không phụ thuộc vào bên ngoài.",
    ),
    "orch_reason_customer_facing": (
        "Customers use this system directly.",
        "Khách hàng dùng trực tiếp hệ thống này.",
    ),
    "orch_reason_medium_customer_facing_only": (
        "Medium-risk systems are assessed on this type only when customers use them.",
        "Hệ thống rủi ro trung bình chỉ được đánh giá loại này khi khách hàng sử dụng.",
    ),
    "orch_reason_applies": ("This risk type applies.", "Loại rủi ro này áp dụng."),
    "orch_reason_classification_required": (
        "The system has no approved classification yet.",
        "Hệ thống chưa có phân loại được phê duyệt.",
    ),
    "orch_reason_prohibited": (
        "The system is prohibited, so nothing is assessed.",
        "Hệ thống bị cấm nên không đánh giá gì.",
    ),
    "orch_reason_not_system": (
        "This is not an AI system, so nothing is assessed.",
        "Đây không phải hệ thống AI nên không đánh giá gì.",
    ),
    # Why a risk type stopped for a person (stop point codes).
    "orch_stop_high_fail": (
        "A high-severity check failed ({ref}). It needs your review.",
        "Một kiểm tra mức nghiêm trọng cao không đạt ({ref}). Cần bạn xem xét.",
    ),
    "orch_stop_approval_point": (
        "This result needs your approval ({ref}).",
        "Kết quả này cần bạn phê duyệt ({ref}).",
    ),
    # Counts on the assurance runs list.
    "orch_as_ok": ("{n} passed", "{n} đạt"),
    "orch_as_warn": ("{n} warnings", "{n} cảnh báo"),
    "orch_as_fail": ("{n} failed", "{n} không đạt"),
    "orch_as_error": ("{n} errors", "{n} lỗi"),
    "orch_as_skip": ("{n} skipped", "{n} bỏ qua"),
    "orch_as_all": ("all", "tất cả"),
}
