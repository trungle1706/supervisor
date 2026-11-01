# ruff: noqa: E501
"""Labels of the law change pages (WP-W2), English and Vietnamese, prefix ``rc_``. Merged into
``i18n._T`` by one line in ``i18n.py``. UI text only."""

from __future__ import annotations

RC: dict[str, tuple[str, str]] = {
    "rc_title": ("Law changes", "Thay đổi quy định"),
    "rc_banner": (
        "Not legal advice. Bank counsel must confirm.",
        "Không phải tư vấn pháp lý. Bộ phận pháp chế phải xác nhận.",
    ),
    "rc_hint": (
        "An update package brings new text. The law agent compares it article by article and drafts the changed duties. A reviewer accepts or drops each draft, then applies the change.",
        "Gói cập nhật mang văn bản mới. Tác tử pháp lý so sánh từng điều và soạn các nghĩa vụ thay đổi. Người xem xét chấp nhận hoặc bỏ từng bản nháp, rồi áp dụng thay đổi.",
    ),
    "rc_items": ("Imported changes", "Thay đổi đã nhập"),
    "rc_none": (
        "No changes imported yet. Import an update package to start.",
        "Chưa nhập thay đổi nào. Hãy nhập gói cập nhật để bắt đầu.",
    ),
    "rc_c_package": ("Package", "Gói"),
    "rc_c_instrument": ("Document", "Văn bản"),
    "rc_c_kinds": ("Types", "Loại"),
    "rc_c_status": ("Status", "Trạng thái"),
    "rc_c_action": ("Action", "Thao tác"),
    "rc_s_no_diff": ("not compared yet", "chưa so sánh"),
    "rc_s_diffed": ("compared, awaiting review", "đã so sánh, chờ xem xét"),
    "rc_s_applied": ("applied", "đã áp dụng"),
    "rc_open": ("Open the comparison", "Mở bản so sánh"),
    "rc_diff_btn": ("Compare with the text of record", "So sánh với văn bản gốc đã lưu"),
    "rc_no_text": (
        "The package has no changed text for this document. Bank counsel reads amendments directly.",
        "Gói không có văn bản thay đổi cho văn bản này. Pháp chế ngân hàng đọc trực tiếp văn bản sửa đổi.",
    ),
    "rc_detail": ("Law change", "Thay đổi quy định"),
    "rc_summary": ("Summary", "Tóm tắt"),
    "rc_unchanged": ("unchanged", "không đổi"),
    "rc_changed": ("changed", "thay đổi"),
    "rc_added": ("added", "thêm mới"),
    "rc_removed": ("removed", "bị bỏ"),
    "rc_chars": ("changed characters", "ký tự thay đổi"),
    "rc_classification": (
        "A classification article changed. Deployed systems go back for re-evaluation once you apply the change.",
        "Một điều về phân loại đã thay đổi. Hệ thống đang vận hành sẽ được đánh giá lại khi bạn áp dụng thay đổi.",
    ),
    "rc_outside": (
        "The text also differs outside the articles (annex, title or signature). Read these parts yourself.",
        "Văn bản còn khác ngoài các điều (phụ lục, tiêu đề hoặc phần ký). Hãy tự đọc các phần này.",
    ),
    "rc_articles": ("Articles", "Các điều"),
    "rc_old": ("Text of record", "Văn bản gốc đã lưu"),
    "rc_new": ("New text", "Văn bản mới"),
    "rc_affected": ("Affected duties", "Nghĩa vụ bị ảnh hưởng"),
    "rc_c_obligation": ("Duty", "Nghĩa vụ"),
    "rc_c_reason": ("Reason", "Lý do"),
    "rc_c_coverage": ("Coverage", "Mức bao phủ"),
    "rc_no_affected": (
        "No existing duty cites a changed article.",
        "Không có nghĩa vụ hiện có nào dẫn chiếu điều đã thay đổi.",
    ),
    "rc_drafts": ("Drafted duties", "Nghĩa vụ đã soạn"),
    "rc_no_drafts": ("No draft for this change.", "Không có bản nháp cho thay đổi này."),
    "rc_pending_drafts": ("drafts awaiting a decision", "bản nháp chờ quyết định"),
    "rc_confirmed_drafts": (
        "confirmed drafts become duties",
        "bản nháp đã xác nhận sẽ thành nghĩa vụ",
    ),
    "rc_apply": ("Apply change", "Áp dụng thay đổi"),
    "rc_apply_note": (
        "The new text becomes the text of record and the RegKB version changes. Duties under changed articles reopen for the affected systems. Source files stay unchanged; the change is saved under DATA_DIR/regkb/overrides.",
        "Văn bản mới trở thành văn bản gốc và phiên bản RegKB thay đổi. Nghĩa vụ thuộc các điều đã thay đổi được mở lại cho các hệ thống bị ảnh hưởng. Tệp gốc không bị sửa; thay đổi được lưu tại DATA_DIR/regkb/overrides.",
    ),
    "rc_apply_confirm": (
        "I have read the comparison and the drafts. Apply this change.",
        "Tôi đã đọc bản so sánh và các bản nháp. Áp dụng thay đổi này.",
    ),
    "rc_applied_on": ("Applied on", "Đã áp dụng vào"),
    "rc_by": ("by", "bởi"),
    "rc_counts": ("duties added / updated / removed", "nghĩa vụ thêm / cập nhật / bỏ"),
    "rc_version": ("RegKB version", "Phiên bản RegKB"),
    "rc_need_role": (
        "Only people with the confirm role can decide drafts and apply changes.",
        "Chỉ người có vai trò xác nhận mới quyết định bản nháp và áp dụng thay đổi.",
    ),
    "rc_ov_pending": ("Law change pending review: {n}", "Thay đổi quy định chờ xem xét: {n}"),
    "rc_ov_applied": (
        "Law change applied on {date}: {n} systems re-opened",
        "Thay đổi quy định đã áp dụng vào {date}: {n} hệ thống được mở lại",
    ),
    "rc_ov_open": ("Review", "Xem xét"),
    "rc_nav": ("Law changes", "Thay đổi quy định"),
    "rc_duty_link": (
        "Law change that re-opened this duty",
        "Thay đổi quy định đã mở lại nghĩa vụ này",
    ),
}
