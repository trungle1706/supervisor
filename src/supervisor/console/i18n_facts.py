# ruff: noqa: E501
"""Labels of the Facts card (WP-O2), English and Vietnamese, prefix ``fk_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

FK: dict[str, tuple[str, str]] = {
    "fk_title": ("Facts", "Dữ kiện"),
    "fk_hint": (
        "What we know about this agent, read from the stored source on the server. Every row points to a file and a line with a short quote. A claim of the model without a file and line is dropped.",
        "Những gì ta biết về tác tử này, đọc từ mã nguồn đã lưu trên máy chủ. Mỗi dòng trỏ tới một tệp và một dòng kèm trích dẫn ngắn. Khẳng định của mô hình không có tệp và dòng sẽ bị loại.",
    ),
    "fk_none": (
        "No facts yet. Add the source in the Source panel, then press Re-read.",
        "Chưa có dữ kiện. Hãy thêm mã nguồn ở mục Mã nguồn, rồi bấm Đọc lại.",
    ),
    "fk_from_attempt": ("Read from source attempt {n}.", "Đọc từ lần nhận mã nguồn {n}."),
    "fk_newer": ("attempt {n} is newer: press Re-read", "lần {n} mới hơn: bấm Đọc lại"),
    "fk_dropped": (
        "{n} claims dropped (no evidence)",
        "{n} khẳng định bị loại (không có bằng chứng)",
    ),
    "fk_mock": (
        "No real model answered: the model step was skipped (labelled mock). Only rule facts are shown.",
        "Không có mô hình thật trả lời: bước mô hình bị bỏ qua (gắn nhãn mock). Chỉ có dữ kiện theo luật.",
    ),
    "fk_empty_card": ("The source holds no facts.", "Mã nguồn không có dữ kiện nào."),
    "fk_reread": ("Re-read", "Đọc lại"),
    "fk_reread_hint": (
        "Builds the facts again from the newest source attempt.",
        "Tạo lại dữ kiện từ lần nhận mã nguồn mới nhất.",
    ),
    "fk_view_only": (
        "Your role may look at the facts but not build them.",
        "Vai trò của bạn chỉ xem được dữ kiện, không tạo được.",
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
    "fk_k_secret_use": ("Secrets (kind only)", "Bí mật (chỉ loại)"),
    "fk_k_external_url": ("External addresses", "Địa chỉ bên ngoài"),
    "fk_k_mcp_server": ("MCP servers", "Máy chủ MCP"),
    "fk_k_approval_point": ("Human approval points", "Điểm phê duyệt của con người"),
    "fk_k_autonomy": ("Autonomy level", "Mức tự chủ"),
    "fk_k_decision33": ("Decision 33 (proposal)", "Quyết định 33 (đề xuất)"),
    "fk_k_weak_spot": ("Weak spots", "Điểm yếu"),
    "fk_k_claim": ("Purpose and other claims", "Mục đích và khẳng định khác"),
}
