# ruff: noqa: E501
"""Labels of the internal documents page (WP-W3), English and Vietnamese, prefix ``ri_``. Merged
into ``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

RI: dict[str, tuple[str, str]] = {
    "ri_title": ("Internal documents", "Tài liệu nội bộ"),
    "ri_hint": (
        "Upload a policy, standard or procedure (.txt, .md, or .pdf with text; max {mb} MB). Personal data is masked first. AI drafts one duty per section, and a compliance reviewer confirms each one.",
        "Tải lên chính sách, tiêu chuẩn hoặc quy trình (.txt, .md, hoặc .pdf có chữ; tối đa {mb} MB). Dữ liệu cá nhân được che trước. AI soạn một nghĩa vụ cho mỗi mục, và người rà soát tuân thủ xác nhận từng nghĩa vụ.",
    ),
    "ri_banner": (
        "Not legal advice. Bank counsel must confirm.",
        "Không phải tư vấn pháp lý. Bộ phận pháp chế phải xác nhận.",
    ),
    "ri_none": ("No internal document yet.", "Chưa có tài liệu nội bộ nào."),
    "ri_c_doc": ("Document", "Tài liệu"),
    "ri_c_owner": ("Owner group", "Nhóm sở hữu"),
    "ri_c_version": ("Version", "Phiên bản"),
    "ri_c_status": ("Status", "Trạng thái"),
    "ri_c_drafts": ("Drafts", "Bản nháp"),
    "ri_c_by": ("Uploaded by", "Người tải lên"),
    "ri_c_actions": ("Actions", "Thao tác"),
    "ri_st_uploaded": ("uploaded", "đã tải lên"),
    "ri_st_drafted": ("drafted", "đã soạn nháp"),
    "ri_st_confirmed": ("confirmed", "đã xác nhận"),
    "ri_st_retired": ("retired", "đã ngừng"),
    "ri_draft": ("Draft duties", "Soạn nghĩa vụ"),
    "ri_open_drafts": ("Open drafts", "Mở bản nháp"),
    "ri_upload": ("Upload a document", "Tải lên tài liệu"),
    "ri_file": ("File", "Tệp"),
    "ri_f_title": ("Title", "Tiêu đề"),
    "ri_f_owner": ("Owner group", "Nhóm sở hữu"),
    "ri_f_version": ("Version label", "Nhãn phiên bản"),
    "ri_send": ("Upload", "Tải lên"),
    "ri_view_only": (
        "You can read this page but not upload. Ask for the upload permission.",
        "Bạn chỉ xem được trang này. Hãy xin quyền tải lên để tải tài liệu.",
    ),
    "ri_instrument": ("Register entry", "Mục đăng ký"),
    "ri_has_instrument": ("in RegKB", "đã vào RegKB"),
    "ri_not_yet": ("Not in RegKB yet", "Chưa vào RegKB"),
    "ri_drafted_note": (
        "{id}: {kept} draft(s) saved, {dropped} dropped by the rules, {nodut} section(s) without a duty.",
        "{id}: đã lưu {kept} bản nháp, quy tắc loại {dropped}, {nodut} mục không có nghĩa vụ.",
    ),
    "ri_uploaded_note": (
        "{id} uploaded; {n} section(s) found.",
        "Đã tải lên {id}; tìm thấy {n} mục.",
    ),
}
