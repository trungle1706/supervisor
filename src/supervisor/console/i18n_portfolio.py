# ruff: noqa: E501
"""Labels of the portfolio blocks on My overview (WP-C4), English and Vietnamese, prefix ``pf_``.
Merged into ``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

PF: dict[str, tuple[str, str]] = {
    "nv3_factory": ("Factory", "Xưởng tác tử"),
    "nv3_guardian_factory": ("Guardian factory", "Xưởng guardian"),
    "nv3_t_regkb_internal": ("Internal documents", "Tài liệu nội bộ"),
    "pf_class": ("Classification", "Phân loại"),
    "pf_class_off": (
        "Turn on CLASSIFICATION_V2 to see the classification of your systems here.",
        "Bật CLASSIFICATION_V2 để xem phân loại các hệ thống tại đây.",
    ),
    "pf_class_foot": (
        "{waiting} waiting for approval · {due} due for review",
        "{waiting} chờ phê duyệt · {due} đến hạn rà soát",
    ),
    "pf_out_prohibited": ("Prohibited", "Bị cấm"),
    "pf_out_high_certify": ("High risk, certify", "Rủi ro cao, chứng nhận"),
    "pf_out_high_self": ("High risk, self-assess", "Rủi ro cao, tự đánh giá"),
    "pf_out_medium": ("Medium risk", "Rủi ro trung bình"),
    "pf_out_low": ("Low risk", "Rủi ro thấp"),
    "pf_out_not_system": ("Not an AI system", "Không phải hệ thống AI"),
    "pf_out_none": ("Not classified", "Chưa phân loại"),
    "pf_filter_outcome": ("Filtered by classification: {outcome}", "Lọc theo phân loại: {outcome}"),
    "pf_filter_clear": ("Clear", "Bỏ lọc"),
    "pf_risk": ("Risk assessment", "Đánh giá rủi ro"),
    "pf_risk_off": (
        "Turn on RISK_DIMENSIONS to see the eight risk types of your systems here.",
        "Bật RISK_DIMENSIONS để xem tám loại rủi ro của các hệ thống tại đây.",
    ),
    "pf_risk_past": (
        "{n} system(s) with a risk type past its valid-until date",
        "{n} hệ thống có loại rủi ro đã quá hạn hiệu lực",
    ),
    "pf_risk_none": ("No systems in this scope.", "Không có hệ thống trong phạm vi này."),
    "pf_system": ("System", "Hệ thống"),
    "pf_more": (
        "Showing {shown} of {total} systems (most failed types first).",
        "Hiển thị {shown} trên {total} hệ thống (nhiều loại không đạt trước).",
    ),
    "pf_more_link": ("All systems", "Tất cả hệ thống"),
    "pf_dim_model": ("Model", "Mô hình"),
    "pf_dim_data_governance": ("Data governance", "Quản trị dữ liệu"),
    "pf_dim_cybersecurity": ("Cybersecurity", "An ninh mạng"),
    "pf_dim_legal_compliance": ("Legal compliance", "Tuân thủ pháp luật"),
    "pf_dim_ethics": ("Ethics", "Đạo đức"),
    "pf_dim_third_party": ("Third party", "Bên thứ ba"),
    "pf_dim_supply_chain": ("Supply chain", "Chuỗi cung ứng"),
    "pf_dim_reputation": ("Reputation", "Danh tiếng"),
    "pf_st_pass": ("Pass", "Đạt"),
    "pf_st_open": ("Open", "Đang mở"),
    "pf_st_not_started": ("Not started", "Chưa bắt đầu"),
    "pf_st_in_progress": ("In progress", "Đang làm"),
    "pf_st_fail": ("Fail", "Không đạt"),
    "pf_st_waived": ("Waived", "Miễn trừ"),
    "pf_st_not_applicable": ("Not applicable", "Không áp dụng"),
    "pf_sh_pass": ("P", "Đ"),
    "pf_sh_not_started": ("-", "-"),
    "pf_sh_in_progress": ("...", "..."),
    "pf_sh_fail": ("F", "K"),
    "pf_sh_waived": ("W", "M"),
    "pf_sh_not_applicable": ("n/a", "k/a"),
}
