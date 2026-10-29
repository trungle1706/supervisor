"""UX5 overrides for the shell (CONSOLE_UX5): shorter text, same keys."""

from __future__ import annotations

UX5: dict[str, tuple[str, str]] = {
    # Shown as the tooltip of the "Dev identity" chip under the search bar.
    "dev_banner": (
        "Dev identity (X-Dev-User): not a real identity. Laptop demo only.",
        "Danh tính dev (X-Dev-User): không phải danh tính thật. Chỉ dùng demo.",
    ),
    # G1-L025: the sidebar entry opens the Gate decisions page; use one name.
    "nv3_activity": ("Gate decisions", "Quyết định của cổng"),
    # G6-T097..T099: the decision panel, shorter text (the governance rule stays).
    "signoffs_n": ("{n} of 2 so far.", "Đã có {n}/2."),
    "you_are_a": ("Your role: {role}.", "Vai trò của bạn: {role}."),
    "mark_triaged": ("Triage...", "Phân loại..."),
    "mark_prelim_sent": ("Mark preliminary report sent", "Đánh dấu đã gửi báo cáo sơ bộ"),
    "mark_formal_sent": ("Mark formal report sent", "Đánh dấu đã gửi báo cáo chính thức"),
    "comment_masked": ("Comment (masked on save)", "Bình luận (che dữ liệu khi lưu)"),
}
