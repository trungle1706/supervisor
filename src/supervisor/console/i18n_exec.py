"""Labels of the executive findings in the assessment summary (``ORCH_EXEC_FINDINGS``, prefix
``exec_``). Plain business wording, English and Vietnamese; see the copy style of the console."""

from __future__ import annotations

EX: dict[str, tuple[str, str]] = {
    "exec_bottom": ("Bottom line", "Kết luận chính"),
    "exec_bottom_hint": (
        "The most important findings over all risk types.",
        "Các phát hiện quan trọng nhất trên mọi loại rủi ro.",
    ),
    "exec_key": ("Key findings", "Phát hiện chính"),
    "exec_none": ("No key findings.", "Không có phát hiện chính."),
    "exec_why": ("Why it matters", "Vì sao quan trọng"),
    "exec_next": ("Next step", "Bước tiếp theo"),
    "exec_who": ("Who acts", "Ai thực hiện"),
    "exec_applies": ("Applies to", "Áp dụng cho"),
    "exec_code": ("Where in the code", "Vị trí trong mã"),
    "exec_all": ("All checks ({n})", "Tất cả kiểm tra ({n})"),
    "exec_sev_high": ("High", "Cao"),
    "exec_sev_medium": ("Medium", "Trung bình"),
    "exec_sev_low": ("Low", "Thấp"),
    "exec_st_fail": ("Problem found", "Có vấn đề"),
    "exec_st_open": ("Open", "Còn mở"),
    "exec_st_pass": ("Pass", "Đạt"),
    "exec_rating_high": ("High concern", "Cần chú ý cao"),
    "exec_rating_medium": ("Medium concern", "Cần chú ý vừa"),
    "exec_rating_low": ("Low concern", "Cần chú ý ít"),
    "exec_rating_clear": ("Clear", "Ổn"),
    "exec_rating_open": ("Open", "Còn mở"),
    "exec_owner_system_owner": ("The system owner", "Chủ hệ thống"),
    "exec_owner_risk_team": ("Risk team", "Bộ phận rủi ro"),
    "exec_owner_security": ("Security team", "Bộ phận an ninh thông tin"),
    "exec_owner_data_owner": ("Data owner", "Chủ sở hữu dữ liệu"),
    "exec_owner_legal": ("Legal and compliance", "Pháp chế và tuân thủ"),
    "exec_owner_model_validation": ("Model validation", "Kiểm định mô hình"),
    "exec_writer_rules": ("Written by rules", "Viết theo quy tắc"),
    "exec_writer_ai": ("AI-written ({model})", "AI viết ({model})"),
    "exec_writer_mock": ("mock", "mock"),
    "exec_kind_rule": ("Rule check", "Kiểm tra theo quy tắc"),
    "exec_kind_live": ("Assessment agent", "Tác tử đánh giá"),
    "exec_kind_draft": ("Draft agent, not tested", "Tác tử bản nháp, chưa kiểm thử"),
    "exec_advisory": (
        "These lines help you read the results. A person decides.",
        "Các dòng này giúp bạn đọc kết quả. Con người quyết định.",
    ),
}
