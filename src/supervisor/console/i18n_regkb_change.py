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
        "A change comes from an imported update package. The law agent compares the stored text with the incoming text article by article and drafts the changed duties. A person with the confirm role accepts or drops each draft and then applies the change. Nothing is applied by itself.",
        "Thay đổi đến từ gói cập nhật đã nhập. Tác nhân pháp lý so sánh văn bản đã lưu với văn bản mới theo từng điều và soạn các nghĩa vụ thay đổi. Người có vai trò xác nhận chấp nhận hoặc bỏ từng bản nháp rồi áp dụng thay đổi. Không có gì tự động được áp dụng.",
    ),
    "rc_items": ("Imported changes", "Thay đổi đã nhập"),
    "rc_none": ("No imported change yet.", "Chưa có thay đổi nào được nhập."),
    "rc_c_package": ("Package", "Gói"),
    "rc_c_instrument": ("Instrument", "Văn bản"),
    "rc_c_kinds": ("Kinds", "Loại"),
    "rc_c_status": ("State", "Trạng thái"),
    "rc_c_action": ("Action", "Thao tác"),
    "rc_s_no_diff": ("no diff yet", "chưa so sánh"),
    "rc_s_diffed": ("diffed, pending review", "đã so sánh, chờ xem xét"),
    "rc_s_applied": ("applied", "đã áp dụng"),
    "rc_open": ("Open the diff", "Mở bản so sánh"),
    "rc_diff_btn": ("Diff against the text of record", "So sánh với văn bản gốc đã lưu"),
    "rc_no_text": (
        "The package holds no changed text of this instrument (an amendment is read by counsel).",
        "Gói không có văn bản mới của văn bản này (văn bản sửa đổi do pháp chế đọc).",
    ),
    "rc_detail": ("Law change", "Thay đổi quy định"),
    "rc_summary": ("Summary", "Tóm tắt"),
    "rc_unchanged": ("unchanged", "không đổi"),
    "rc_changed": ("changed", "thay đổi"),
    "rc_added": ("added", "thêm mới"),
    "rc_removed": ("removed", "bị bỏ"),
    "rc_chars": ("changed characters", "ký tự thay đổi"),
    "rc_classification": (
        "A classification article changed: deployed systems go back to re-evaluation when the change is applied.",
        "Một điều về phân loại đã thay đổi: hệ thống đang vận hành sẽ quay lại đánh giá lại khi áp dụng thay đổi.",
    ),
    "rc_outside": (
        "The text differs outside the articles (annex, title or signature block). Read it.",
        "Văn bản khác nhau ngoài các điều (phụ lục, tiêu đề hoặc phần ký). Hãy đọc.",
    ),
    "rc_articles": ("Articles", "Các điều"),
    "rc_old": ("Text of record", "Văn bản gốc đã lưu"),
    "rc_new": ("Incoming text", "Văn bản mới"),
    "rc_affected": ("Affected obligations", "Nghĩa vụ bị ảnh hưởng"),
    "rc_c_obligation": ("Obligation", "Nghĩa vụ"),
    "rc_c_reason": ("Reason", "Lý do"),
    "rc_c_coverage": ("Coverage", "Mức bao phủ"),
    "rc_no_affected": (
        "No existing obligation names a changed article.",
        "Không có nghĩa vụ hiện có nào nêu điều đã thay đổi.",
    ),
    "rc_drafts": ("Drafted duties", "Nghĩa vụ đã soạn"),
    "rc_no_drafts": ("No draft for this change.", "Không có bản nháp cho thay đổi này."),
    "rc_pending_drafts": ("drafts still open", "bản nháp chưa quyết định"),
    "rc_confirmed_drafts": (
        "confirmed drafts become obligations",
        "bản nháp đã xác nhận sẽ thành nghĩa vụ",
    ),
    "rc_apply": ("Apply change", "Áp dụng thay đổi"),
    "rc_apply_note": (
        "Writes the override under DATA_DIR/regkb/overrides. The committed regulation files are not touched. The incoming text becomes the text of record, the RegKB version changes, and the duties of the changed articles are opened again for the systems that have them.",
        "Ghi bản ghi đè trong DATA_DIR/regkb/overrides. Các tệp quy định đã commit không bị sửa. Văn bản mới trở thành văn bản gốc, phiên bản RegKB đổi, và các nghĩa vụ của điều đã thay đổi được mở lại cho các hệ thống có chúng.",
    ),
    "rc_apply_confirm": (
        "I read the diff and the drafts. Apply this change.",
        "Tôi đã đọc bản so sánh và các bản nháp. Áp dụng thay đổi này.",
    ),
    "rc_applied_on": ("Applied on", "Đã áp dụng vào"),
    "rc_by": ("by", "bởi"),
    "rc_counts": ("added / updated / removed obligations", "nghĩa vụ thêm / cập nhật / bỏ"),
    "rc_version": ("RegKB version", "Phiên bản RegKB"),
    "rc_need_role": (
        "You need the confirm role to decide drafts and apply.",
        "Bạn cần vai trò xác nhận để quyết định bản nháp và áp dụng.",
    ),
    "rc_ov_pending": ("Law change pending review: {n}", "Thay đổi quy định chờ xem xét: {n}"),
    "rc_ov_applied": (
        "Law change applied on {date}: {n} systems re-opened",
        "Thay đổi quy định đã áp dụng vào {date}: {n} hệ thống được mở lại",
    ),
    "rc_ov_open": ("Review", "Xem xét"),
}
