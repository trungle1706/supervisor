# ruff: noqa: E501
"""Labels of the Facts card (WP-O2), English and Vietnamese, prefix ``fk_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

FK: dict[str, tuple[str, str]] = {
    "fk_title": ("Facts", "Dữ kiện"),
    "fk_hint": (
        "Facts found in the uploaded code. Each one names a file and line. Facts without one are left out.",
        "Dữ kiện tìm thấy trong mã đã tải lên. Mỗi dữ kiện nêu tệp và dòng. Dữ kiện không có thì bị loại.",
    ),
    "fk_none": (
        "No facts yet. Upload the source in the Source tab, then press Re-read.",
        "Chưa có dữ kiện. Hãy tải mã nguồn ở thẻ Mã nguồn, rồi bấm Đọc lại.",
    ),
    "fk_from_attempt": ("Based on source upload {n}.", "Dựa trên lần tải mã nguồn {n}."),
    "fk_newer": (
        "Upload {n} is newer. Read the source again.",
        "Lần tải lên {n} mới hơn. Hãy đọc lại nguồn.",
    ),
    "fk_dropped": (
        "{n} claims dropped (no evidence)",
        "{n} khẳng định bị loại (không có bằng chứng)",
    ),
    "fk_mock": (
        "The AI model step was skipped (mock mode), so only rule-based facts are shown.",
        "Bước dùng mô hình AI đã bị bỏ qua (chế độ mock), nên chỉ hiển thị dữ kiện theo quy tắc.",
    ),
    "fk_empty_card": (
        "No facts found in the source code.",
        "Không tìm thấy dữ kiện nào trong mã nguồn.",
    ),
    "fk_reread": ("Re-read", "Đọc lại"),
    "fk_reread_hint": (
        "Rebuilds the facts from the newest source upload.",
        "Tạo lại dữ kiện từ lần tải mã nguồn mới nhất.",
    ),
    "fk_view_only": (
        "You can view the facts but not rebuild them.",
        "Bạn xem được dữ kiện nhưng không tạo lại được.",
    ),
    "fk_open_page": ("Open the Facts page", "Mở trang Dữ kiện"),
    "fk_c_name": ("Name", "Tên"),
    "fk_c_detail": ("Detail", "Chi tiết"),
    "fk_c_pointer": ("File:line", "Tệp:dòng"),
    "fk_c_quote": ("Quote", "Trích dẫn"),
    "fk_c_source": ("Found by", "Do"),
    "fk_src_rule": ("rule", "luật"),
    "fk_src_model": ("model", "mô hình"),
    "fk_k_tool": ("Tools", "Công cụ"),
    "fk_k_model": ("Models", "Mô hình"),
    "fk_k_endpoint": ("Endpoints", "Endpoint"),
    "fk_k_dataset": ("Data", "Dữ liệu"),
    "fk_k_file": ("Files", "Tệp"),
    "fk_k_secret_use": ("Secrets used (type only)", "Thông tin bí mật được dùng (chỉ nêu loại)"),
    "fk_k_external_url": ("External addresses", "Địa chỉ bên ngoài"),
    "fk_k_mcp_server": ("MCP servers", "Máy chủ MCP"),
    "fk_k_approval_point": ("Points where a person approves", "Điểm cần con người phê duyệt"),
    "fk_k_autonomy": ("Autonomy level", "Mức tự chủ"),
    "fk_k_decision33": ("Decision 33 (suggested)", "Quyết định 33 (gợi ý)"),
    "fk_k_weak_spot": ("Weak spots", "Điểm yếu"),
    "fk_k_claim": ("Purpose and other claims", "Mục đích và khẳng định khác"),
}
