"""UX5 overrides for the shell (CONSOLE_UX5): shorter text, same keys."""

from __future__ import annotations

UX5: dict[str, tuple[str, str]] = {
    # Shown as the tooltip of the "Dev identity" chip under the search bar.
    "dev_banner": (
        "Dev identity (X-Dev-User): not a real identity. Laptop demo only.",
        "Danh tính dev (X-Dev-User): không phải danh tính thật. Chỉ dùng demo.",
    ),
}
