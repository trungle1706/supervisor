# ruff: noqa: E501
"""Labels added by UI audit batch 1 (docs/ui/redundancy-audit.md): broken links, counts that
disagree, placeholders. Prefix ``b1_``. Merged into ``i18n._T`` by the last lines of ``i18n.py``."""

from __future__ import annotations

B1: dict[str, tuple[str, str]] = {
    # UI-002 My overview
    "b1_all_cases": ("All {n} open cases", "Tất cả {n} vụ việc đang mở"),
    "b1_due_tip": (
        "Required tasks past their due date, for the systems and agents shown.",
        "Nhiệm vụ bắt buộc đã quá hạn, của các hệ thống và tác tử đang hiển thị.",
    ),
    "b1_view_all_systems": ("View all {n} systems", "Xem tất cả {n} hệ thống"),
    # UI-040 Governance overview
    "nv3_na_tasks_unreadable": (
        "Cannot read the task list.",
        "Không đọc được danh sách công việc.",
    ),
    # UI-062 duty and task counts
    "b1_du_closed_of": (
        "of {total} applicable duties closed",
        "trên {total} nghĩa vụ áp dụng đã đóng",
    ),
    "b1_du_score_tip": (
        "Closed duties as a share of open and closed duties. Waived duties and duties waiting for an answer are not counted.",
        "Tỷ lệ nghĩa vụ đã đóng trên tổng nghĩa vụ đang mở và đã đóng. Nghĩa vụ đã miễn trừ và đang chờ trả lời không được tính.",
    ),
    "b1_du_f_all": ("All, including waiting for an answer", "Tất cả, gồm đang chờ trả lời"),
    "b1_du_all_tip": (
        "All duties: open, closed, waived and waiting for an answer.",
        "Mọi nghĩa vụ: đang mở, đã đóng, đã miễn trừ và đang chờ trả lời.",
    ),
    "b1_badge_duties": ("Open duties", "Nghĩa vụ đang mở"),
    "b1_badge_tasks": (
        "Open tasks (not started or in progress). Duty tasks are on the Duties tab.",
        "Nhiệm vụ đang mở (chưa bắt đầu hoặc đang thực hiện). Nhiệm vụ về nghĩa vụ nằm ở tab Nghĩa vụ.",
    ),
    # UI-063 risk assessment
    "b1_orch_none_set": (
        "No risk assessment run yet. Statuses last updated on {date}.",
        "Chưa chạy đánh giá rủi ro. Trạng thái được cập nhật lần cuối ngày {date}.",
    ),
    # UI-092 inventory
    "b1_not_registered_tip": (
        "This item is not a registered agent, so it has no agent page.",
        "Mục này không phải tác tử đã đăng ký nên không có trang tác tử.",
    ),
    # UI-350 guardian counts: Attach adds the gate rules to the guardian features of the Guardians tab
    "b1_attach_list": (
        "Show guardian list ({n}: {f} guardian features and {g} gate rules)",
        "Hiện danh sách bộ bảo vệ ({n}: {f} tính năng bảo vệ và {g} luật cổng)",
    ),
    # UI-350 My agents: what the tiles count
    "b1_mya_compose": (
        "{reg} registered agents ({run} running). {gate} are seen by the gate only. {cand} are not yet registered. Home and the Agents page count registered agents only.",
        "{reg} tác tử đã đăng ký ({run} đang chạy). {gate} chỉ cổng nhìn thấy. {cand} chưa đăng ký. Trang chủ và trang Tác tử chỉ đếm tác tử đã đăng ký.",
    ),
    # UI-110 limits table
    "b1_th_manifest": ("Agent setting", "Cài đặt của tác tử"),
}
