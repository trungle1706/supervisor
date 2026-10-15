"""Bilingual (English / Vietnamese) headings and words for the matrix reports (WP14).

Obligation text is NOT translated here: it stays in its source language.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

_T: dict[str, tuple[str, str]] = {
    # sections
    "title": ("Obligations matrix", "Ma trận nghĩa vụ"),
    "header": ("Header", "Thông tin chung"),
    "summary": ("Summary", "Tổng hợp"),
    "narrative": ("Narrative", "Diễn giải"),
    "decision33": ("Decision 33 suggestion", "Gợi ý theo Quyết định 33"),
    "thresholds": ("Threshold findings", "Kết quả kiểm tra hạn mức"),
    "questions": ("Open questions", "Câu hỏi còn mở"),
    "rows": ("Obligations", "Nghĩa vụ"),
    "not_applicable_list": ("Not applicable obligations", "Nghĩa vụ không áp dụng"),
    "no_items": ("none", "không có"),
    # header fields
    "product": ("Product", "Sản phẩm"),
    "source": ("Source", "Nguồn"),
    "kb_version": ("RegKB version", "Phiên bản RegKB"),
    "instruments": ("Instruments", "Văn bản"),
    "obligations": ("Obligations", "Nghĩa vụ"),
    "internal_rules": ("Internal rules loaded", "Có quy định nội bộ"),
    "as_of": ("As of", "Tính đến ngày"),
    "generated_at": ("Generated at", "Tạo lúc"),
    "yes": ("yes", "có"),
    "no": ("no", "không"),
    # summary
    "by_status": ("By status (applies = yes)", "Theo trạng thái (áp dụng = có)"),
    "by_applies": ("By applicability", "Theo khả năng áp dụng"),
    "needs_answer_rows": ("Rows that need an answer", "Dòng cần trả lời"),
    "open_questions": ("Open questions", "Câu hỏi còn mở"),
    "threshold_gaps": ("Threshold gaps", "Hạn mức vượt trần"),
    # status words
    "status.met": ("Met", "Đạt"),
    "status.partial": ("Partial", "Một phần"),
    "status.gap": ("Gap", "Thiếu"),
    "status.bank_process": ("Bank process", "Quy trình ngân hàng"),
    "status.not_applicable": ("Not applicable", "Không áp dụng"),
    # applies words
    "applies.yes": ("Applies", "Áp dụng"),
    "applies.no": ("Does not apply", "Không áp dụng"),
    "applies.needs_answer": ("Needs answer", "Cần trả lời"),
    # decision 33
    "d33.high_risk": ("High risk", "Rủi ro cao"),
    "d33.not_high_risk": ("Not high risk", "Không thuộc rủi ro cao"),
    "d33.needs_answer": ("Needs answer", "Cần trả lời"),
    "d33.triggered": ("triggered", "kích hoạt"),
    "d33.not_triggered": ("not triggered", "không kích hoạt"),
    "d33.unknown": ("needs answer", "cần trả lời"),
    # threshold verdicts
    "verdict.exceeds": ("Exceeds", "Vượt trần"),
    "verdict.at_cap": ("At cap", "Bằng trần"),
    "verdict.within": ("Within", "Trong trần"),
    "verdict.needs_answer": ("Needs answer", "Cần trả lời"),
    # table columns
    "col.obligation": ("Obligation", "Nghĩa vụ"),
    "col.article": ("Article", "Điều"),
    "col.summary": ("Summary", "Tóm tắt"),
    "col.applies": ("Applies", "Áp dụng"),
    "col.status": ("Status", "Trạng thái"),
    "col.reason": ("Reason", "Lý do"),
    "col.controls": ("Controls", "Biện pháp kiểm soát"),
    "col.evidence": ("Evidence pointers", "Dẫn chứng"),
    "col.dates": ("Dates", "Ngày"),
    "col.questions": ("Questions", "Câu hỏi"),
    "col.limit": ("Limit", "Hạn mức"),
    "col.cap": ("Cap", "Trần"),
    "col.verdict": ("Verdict", "Kết luận"),
    "col.id": ("Id", "Mã"),
    "col.question": ("Question", "Câu hỏi"),
    "col.decides": ("Decides", "Quyết định"),
    "col.count": ("Count", "Số lượng"),
    # misc
    "effective": ("effective", "hiệu lực"),
    "compliance_deadline": ("compliance deadline", "hạn tuân thủ"),
    "article_effective": ("article effective", "điều có hiệu lực"),
    "present": ("present", "có"),
    "absent": ("absent", "không có"),
    "process": ("bank process", "quy trình ngân hàng"),
    "advisory_label": ("advisory", "tham khảo"),
    "mock_label": ("mock", "giả lập"),
    "caveat": ("Caveat", "Lưu ý"),
    "section_note": (
        "Obligation text is shown in its source language.",
        "Nội dung nghĩa vụ giữ nguyên ngôn ngữ gốc.",
    ),
}


def tr(key: str, lang: str) -> str:
    """Text for ``key`` in ``lang`` ('en' or 'vi'). Unknown key: raise KeyError."""
    en, vi = _T[key]
    if lang == "en":
        return en
    if lang == "vi":
        return vi
    raise ValueError(f"unknown language {lang!r}")


def both(key: str) -> str:
    """'English / Vietnamese'."""
    en, vi = _T[key]
    return f"{en} / {vi}"


def keys() -> tuple[str, ...]:
    return tuple(_T)
