# ruff: noqa: E501
"""Labels of the task and stage buttons (WP-P1), English and Vietnamese, prefix ``wf_``.
Merged into ``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

WF: dict[str, tuple[str, str]] = {
    "wf_actions": ("Actions", "Thao tác"),
    "wf_done": ("Done", "Hoàn thành"),
    "wf_waive": ("Waive", "Miễn trừ"),
    "wf_waive_reason": (
        "Reason for the waiver (10 characters or more)",
        "Lý do miễn trừ (từ 10 ký tự)",
    ),
    "wf_evidence": ("Document reference", "Mã tài liệu"),
    "wf_waive_pending": (
        "Waiver waits for a second person",
        "Miễn trừ đang chờ người thứ hai",
    ),
    "wf_waive_approve": ("Approve waiver", "Duyệt miễn trừ"),
    "wf_waive_reject": ("Reject waiver", "Từ chối miễn trừ"),
    "wf_waive_reject_reason": ("Reason to reject", "Lý do từ chối"),
    "wf_request_title": ("Request a move", "Yêu cầu chuyển giai đoạn"),
    "wf_request_hint": (
        "A second person approves or rejects the request. You cannot answer your own request.",
        "Người thứ hai duyệt hoặc từ chối yêu cầu. Bạn không thể tự trả lời yêu cầu của mình.",
    ),
    "wf_to_stage": ("Target stage", "Giai đoạn đích"),
    "wf_reason": ("Reason (10 characters or more)", "Lý do (từ 10 ký tự)"),
    "wf_request": ("Request move", "Yêu cầu chuyển"),
    "wf_approve": ("Approve", "Đồng ý"),
    "wf_reject": ("Reject", "Từ chối"),
    "wf_reject_reason": ("Reason (needed to reject)", "Lý do (bắt buộc khi từ chối)"),
    "wf_move": ("Move", "Chuyển"),
    "wf_move_direct": (
        "Move to a stage that needs no approval",
        "Chuyển sang giai đoạn không cần phê duyệt",
    ),
    "wf_wait": ("Waits for a second person", "Chờ người thứ hai"),
    "wf_ap_reason": ("Reason", "Lý do"),
    "wf_ok_done": ("Task marked done.", "Đã đánh dấu nhiệm vụ hoàn thành."),
    "wf_ok_waive": (
        "Waiver asked. A second person must approve it.",
        "Đã đề nghị miễn trừ. Cần người thứ hai duyệt.",
    ),
    "wf_ok_waive_approve": ("Waiver approved. The task is waived.", "Đã duyệt miễn trừ."),
    "wf_ok_waive_reject": ("Waiver rejected. The task stays open.", "Đã từ chối miễn trừ."),
    "wf_ok_request": (
        "Move requested. A second person must answer.",
        "Đã yêu cầu chuyển giai đoạn. Cần người thứ hai trả lời.",
    ),
    "wf_ok_approve": ("Request approved. Use Move.", "Đã đồng ý yêu cầu. Hãy bấm Chuyển."),
    "wf_ok_reject": ("Request rejected.", "Đã từ chối yêu cầu."),
    "wf_ok_move": ("The system moved to the new stage.", "Hệ thống đã chuyển giai đoạn."),
}
