# ruff: noqa: E501
"""Labels of the task and stage buttons (WP-P1), English and Vietnamese, prefix ``wf_``.
Merged into ``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

WF: dict[str, tuple[str, str]] = {
    "wf_actions": ("Actions", "Thao tác"),
    "wf_done": ("Done", "Hoàn thành"),
    "wf_waive": ("Waive", "Miễn trừ"),
    "wf_waive_reason": (
        "Reason for the waiver (at least 10 characters)",
        "Lý do miễn trừ (tối thiểu 10 ký tự)",
    ),
    "wf_evidence": ("Document reference", "Mã tài liệu"),
    "wf_waive_pending": (
        "Waiver waits for a second approver",
        "Miễn trừ đang chờ người phê duyệt thứ hai",
    ),
    "wf_waive_approve": ("Approve waiver", "Phê duyệt miễn trừ"),
    "wf_waive_reject": ("Reject waiver", "Từ chối miễn trừ"),
    "wf_waive_reject_reason": ("Reason to reject", "Lý do từ chối"),
    "wf_request_title": ("Request a move", "Yêu cầu chuyển giai đoạn"),
    "wf_request_hint": (
        "A second approver must approve. You cannot approve your own request.",
        "Cần người phê duyệt thứ hai. Bạn không thể tự phê duyệt yêu cầu của mình.",
    ),
    "wf_to_stage": ("Move to stage", "Chuyển đến giai đoạn"),
    "wf_reason": ("Reason (at least 10 characters)", "Lý do (tối thiểu 10 ký tự)"),
    "wf_request": ("Request move", "Yêu cầu chuyển"),
    "wf_approve": ("Approve", "Phê duyệt"),
    "wf_reject": ("Reject", "Từ chối"),
    "wf_reject_reason": ("Reason (needed to reject)", "Lý do (bắt buộc khi từ chối)"),
    "wf_move": ("Move", "Chuyển"),
    "wf_move_direct": (
        "Move to a stage that needs no approval",
        "Chuyển sang giai đoạn không cần phê duyệt",
    ),
    "wf_wait": ("Waits for a second approver", "Chờ người phê duyệt thứ hai"),
    "wf_ap_reason": ("Reason", "Lý do"),
    "wf_ok_done": ("Task marked done.", "Đã đánh dấu nhiệm vụ hoàn thành."),
    "wf_ok_waive": (
        "Waiver requested. A second approver must approve it.",
        "Đã đề nghị miễn trừ. Cần người phê duyệt thứ hai phê duyệt.",
    ),
    "wf_ok_waive_approve": (
        "Waiver approved. The task is waived.",
        "Đã phê duyệt miễn trừ. Nhiệm vụ được miễn.",
    ),
    "wf_ok_waive_reject": (
        "Waiver rejected. The task stays open.",
        "Đã từ chối miễn trừ. Nhiệm vụ vẫn còn mở.",
    ),
    "wf_ok_request": (
        "Move requested. A second approver must approve or reject it.",
        "Đã yêu cầu chuyển giai đoạn. Cần người phê duyệt thứ hai quyết định.",
    ),
    "wf_ok_approve": (
        "Request approved. Now select Move.",
        "Đã phê duyệt yêu cầu. Hãy bấm Chuyển.",
    ),
    "wf_ok_reject": ("Request rejected.", "Đã từ chối yêu cầu."),
    "wf_ok_move": ("The system is now in the new stage.", "Hệ thống đã sang giai đoạn mới."),
}
