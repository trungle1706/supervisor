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
        "Rules suggest a status. You confirm it. Pass needs evidence. A waiver needs a reason and a second approver.",
        "Quy tắc gợi ý trạng thái. Bạn xác nhận. Đạt cần bằng chứng. Miễn trừ cần lý do và người phê duyệt thứ hai.",
    ),
    "rd_date_note": (
        "Art. 14 applies from 2027-01-01.",
        "Điều 14 có hiệu lực từ 2027-01-01.",
    ),
    "rd_illustrative": (
        "Definitions and thresholds are examples. The bank sets the real ones.",
        "Định nghĩa và ngưỡng chỉ là ví dụ. Ngân hàng đặt giá trị thực.",
    ),
    "rd_st_not_started": ("Not started", "Chưa bắt đầu"),
    "rd_st_in_progress": ("In progress", "Đang thực hiện"),
    "rd_st_pass": ("Pass", "Đạt"),
    "rd_st_fail": ("Fail", "Không đạt"),
    "rd_st_waived": ("Waived", "Đã miễn trừ"),
    "rd_st_not_applicable": ("Not applicable", "Không áp dụng"),
    "rd_expired": ("Pass expired", "Kết quả Đạt đã hết hạn"),
    "rd_bank_only": ("Banks only", "Chỉ áp dụng cho ngân hàng"),
    "rd_owner_team": ("Owner team", "Nhóm sở hữu"),
    "rd_assessed_by": ("Assessed by", "Người đánh giá"),
    "rd_evidence": ("Evidence", "Bằng chứng"),
    "rd_threshold": ("Threshold (set by the bank)", "Ngưỡng (ngân hàng đặt)"),
    "rd_valid_until": ("Valid until", "Có hiệu lực đến"),
    "rd_note": ("Note", "Ghi chú"),
    "rd_report": ("Assessment report", "Báo cáo đánh giá"),
    "rd_proposal": ("Suggested result", "Kết quả gợi ý"),
    "rd_no_rules": (
        "no automated check covers this risk type; you decide",
        "không có kiểm tra tự động cho loại rủi ro này; bạn quyết định",
    ),
    "rd_chk_ok": ("ok", "đạt"),
    "rd_chk_fail": ("failed", "không đạt"),
    "rd_chk_weak": ("warning", "cảnh báo"),
    "rd_chk_missing": ("no result", "chưa có kết quả"),
    "rd_chk_stale": ("outdated check version", "phiên bản kiểm tra cũ"),
    "rd_lines": ("Risk register entries", "Mục trong sổ đăng ký rủi ro"),
    "rd_lines_none": ("none for this system", "không có cho hệ thống này"),
    "rd_confirm": ("Confirm suggestion", "Xác nhận gợi ý"),
    "rd_set": ("Save status", "Lưu trạng thái"),
    "rd_status": ("Status", "Trạng thái"),
    "rd_evidence_ph": (
        "pack:<pack>:<run>:<agent> fact:<id> doc:<id>",
        "pack:<bộ>:<lần chạy>:<agent> fact:<id> doc:<id>",
    ),
    "rd_note_ph": ("Note (no personal data)", "Ghi chú (không dữ liệu cá nhân)"),
    "rd_reassess": ("Request re-assessment", "Yêu cầu đánh giá lại"),
    "rd_reassess_hint": (
        "Not available yet. It comes with the assessment agents (WP-F4).",
        "Chưa dùng được. Sẽ có cùng các tác tử đánh giá (WP-F4).",
    ),
    "rd_waive": ("Waive", "Miễn trừ"),
    "rd_waive_ph": ("Reason, at least {n} characters", "Lý do, ít nhất {n} ký tự"),
    "rd_ok_set": ("Status saved.", "Đã lưu trạng thái."),
    "rd_ok_confirm": ("Proposal confirmed.", "Đã xác nhận đề xuất."),
    "rd_ok_waive": ("Risk type waived.", "Đã miễn trừ loại rủi ro."),
}
