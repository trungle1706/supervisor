# ruff: noqa: E501
"""Labels of the Risk assessment tab (WP-C2), English and Vietnamese, prefix ``rd_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only. Not legal advice."""

from __future__ import annotations

RD: dict[str, tuple[str, str]] = {
    "rd_tab": ("Risk assessment", "Đánh giá rủi ro"),
    "rd_title": (
        "Eight risk types (Circular 53 Art. 14(3))",
        "Tám loại rủi ro (Thông tư 53 Điều 14 khoản 3)",
    ),
    "rd_intro": (
        "One row per risk type. The rules propose a status from pack results and monitors; a person confirms it. Pass needs an evidence pointer. A waiver needs a reason and a second person.",
        "Mỗi loại rủi ro một dòng. Quy tắc đề xuất trạng thái từ kết quả bộ kiểm thử và giám sát; một người xác nhận. Đạt cần con trỏ bằng chứng. Miễn trừ cần lý do và người thứ hai.",
    ),
    "rd_date_note": (
        "Art. 14 applies from 2027-01-01.",
        "Điều 14 có hiệu lực từ 2027-01-01.",
    ),
    "rd_illustrative": (
        "Definitions and thresholds are placeholders: the bank sets them.",
        "Định nghĩa và ngưỡng chỉ là mẫu: ngân hàng tự đặt.",
    ),
    "rd_st_not_started": ("Not started", "Chưa bắt đầu"),
    "rd_st_in_progress": ("In progress", "Đang thực hiện"),
    "rd_st_pass": ("Pass", "Đạt"),
    "rd_st_fail": ("Fail", "Không đạt"),
    "rd_st_waived": ("Waived", "Đã miễn trừ"),
    "rd_st_not_applicable": ("Not applicable", "Không áp dụng"),
    "rd_expired": ("Pass expired", "Hết hạn hiệu lực"),
    "rd_bank_only": ("Banks only", "Chỉ áp dụng cho ngân hàng"),
    "rd_owner_team": ("Owner team", "Nhóm sở hữu"),
    "rd_assessed_by": ("Assessed by", "Người đánh giá"),
    "rd_evidence": ("Evidence pointers", "Con trỏ bằng chứng"),
    "rd_threshold": ("Threshold (set by the bank)", "Ngưỡng (ngân hàng đặt)"),
    "rd_valid_until": ("Valid until", "Có hiệu lực đến"),
    "rd_note": ("Note", "Ghi chú"),
    "rd_report": ("Assessment report", "Báo cáo đánh giá"),
    "rd_proposal": ("Rule proposal", "Đề xuất theo quy tắc"),
    "rd_no_rules": (
        "no rule measures this type; a person decides",
        "không có quy tắc đo loại này; một người quyết định",
    ),
    "rd_chk_ok": ("ok", "đạt"),
    "rd_chk_fail": ("failed", "không đạt"),
    "rd_chk_weak": ("warning", "cảnh báo"),
    "rd_chk_missing": ("no result", "chưa có kết quả"),
    "rd_chk_stale": ("old pack version", "phiên bản bộ kiểm thử cũ"),
    "rd_lines": ("Risk register lines", "Dòng sổ đăng ký rủi ro"),
    "rd_lines_none": ("none for this system", "không có cho hệ thống này"),
    "rd_confirm": ("Confirm proposal", "Xác nhận đề xuất"),
    "rd_set": ("Set status", "Đặt trạng thái"),
    "rd_status": ("Status", "Trạng thái"),
    "rd_evidence_ph": (
        "pack:<pack>:<run>:<agent> fact:<id> doc:<id>",
        "pack:<bộ>:<lần chạy>:<agent> fact:<id> doc:<id>",
    ),
    "rd_note_ph": ("Note (no personal data)", "Ghi chú (không dữ liệu cá nhân)"),
    "rd_reassess": ("Request re-assessment", "Yêu cầu đánh giá lại"),
    "rd_reassess_hint": (
        "Available when the assessment agents ship (WP-F4).",
        "Dùng được khi có agent đánh giá (WP-F4).",
    ),
    "rd_waive": ("Waive", "Miễn trừ"),
    "rd_waive_ph": ("Reason, at least {n} characters", "Lý do, ít nhất {n} ký tự"),
    "rd_ok_set": ("Status saved.", "Đã lưu trạng thái."),
    "rd_ok_confirm": ("Proposal confirmed.", "Đã xác nhận đề xuất."),
    "rd_ok_waive": ("Risk type waived.", "Đã miễn trừ loại rủi ro."),
}
