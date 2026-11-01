# ruff: noqa: E501
"""UX5 text of group G3 (compliance advisor, risks, controls, policies, internal documents, law
changes, drafts). ``NEW`` holds keys that did not exist (prefix ``g3_``; merged into the base
table by one line in ``i18n.py``). ``UX5`` overrides existing keys and is only read with
CONSOLE_UX5. Legal text is never shortened here."""

from __future__ import annotations

NEW: dict[str, tuple[str, str]] = {
    # --- compliance: evidence labels, thresholds
    "g3_ev_bank": (
        "Bank process: {names}. No Supervisor control.",
        "Quy trình của ngân hàng: {names}. Không có biện pháp Supervisor.",
    ),
    "g3_ev_have": ("Evidence: {names}.", "Bằng chứng: {names}."),
    "g3_ev_missing": ("Missing: {names}.", "Còn thiếu: {names}."),
    "g3_ev_nomissing": ("Nothing missing.", "Không thiếu gì."),
    "g3_ev_limit": (
        "A limit is above the legal cap. See Decision 33 and limits.",
        "Có hạn mức vượt mức trần theo luật. Xem Quyết định 33 và hạn mức.",
    ),
    "g3_ev_off": ("not switched on", "chưa bật"),
    "g3_th_txn": ("single transfer", "một lần chuyển"),
    "g3_th_day": ("daily total", "tổng trong ngày"),
    "g3_th_exceeds": (
        "{limit_id} allows {limit} ({period}). This is above the legal cap of {cap} per day.",
        "{limit_id} cho phép {limit} ({period}). Mức này vượt mức trần theo luật là {cap} mỗi ngày.",
    ),
    "g3_th_atcap": (
        "{limit_id} allows {limit} ({period}). The legal cap is {cap} per day. One transfer can use the whole daily cap.",
        "{limit_id} cho phép {limit} ({period}). Mức trần theo luật là {cap} mỗi ngày. Một lần chuyển có thể dùng hết mức trần ngày.",
    ),
    "g3_th_within": (
        "{limit_id} allows {limit} ({period}). This is within the legal cap of {cap} per day.",
        "{limit_id} cho phép {limit} ({period}). Nằm trong mức trần theo luật là {cap} mỗi ngày.",
    ),
    # --- compliance: tabs, blocks
    "g3_purpose_agent": (
        "Legal duties for this agent and the controls that cover each one.",
        "Nghĩa vụ pháp lý của tác tử này và biện pháp kiểm soát đáp ứng từng nghĩa vụ.",
    ),
    "g3_tab_summary": ("Summary", "Tóm tắt"),
    "g3_tab_d33": ("Decision 33 and limits", "Quyết định 33 và hạn mức"),
    "g3_tab_all": ("All duties, {n}", "Tất cả nghĩa vụ, {n}"),
    "g3_tabs": ("Views", "Chế độ xem"),
    "g3_strip": ("Status of the duties that apply", "Trạng thái các nghĩa vụ áp dụng"),
    "g3_strip_apply": ("Duties apply", "Nghĩa vụ áp dụng"),
    "g3_answer_first": ("Answer first", "Trả lời trước"),
    "g3_answer_sub": ("{q} questions block {n} duties", "{q} câu hỏi đang chặn {n} nghĩa vụ"),
    "g3_blocks": ("Blocks {n} duties", "Chặn {n} nghĩa vụ"),
    "g3_show_duties": ("Show duties", "Xem nghĩa vụ"),
    "g3_none_q": ("No open question.", "Không còn câu hỏi mở."),
    "g3_none_limits": (
        "No limit above the legal cap.",
        "Không có hạn mức nào vượt mức trần theo luật.",
    ),
    "g3_gaps": ("Gaps to close", "Thiếu sót cần xử lý"),
    "g3_gaps_sub": ("{n} duties with no control", "{n} nghĩa vụ chưa có biện pháp"),
    "g3_d33_title": ("Decision 33 suggestion", "Gợi ý theo Quyết định 33"),
    "g3_d33_entry_transactions": ("Payments", "Thanh toán"),
    "g3_d33_entry_credit": ("Credit", "Tín dụng"),
    "g3_reasoning": ("Show reasoning ({n} lines)", "Xem lập luận ({n} dòng)"),
    "g3_caveat": (
        "Why a guardian pause does not lower the risk class",
        "Vì sao việc bộ bảo vệ tạm dừng không làm giảm hạng rủi ro",
    ),
    "g3_d33_more": ("Full detail and limits", "Chi tiết đầy đủ và hạn mức"),
    "g3_by_inst": ("Duties by legal instrument", "Nghĩa vụ theo văn bản pháp lý"),
    "g3_inst_sub": ("{n} instruments, gaps first", "{n} văn bản, thiếu sót lên đầu"),
    "g3_legend_lead": ("One mark per duty:", "Mỗi vạch là một nghĩa vụ:"),
    "g3_f_status": ("Status", "Trạng thái"),
    "g3_f_all": ("All", "Tất cả"),
    "g3_f_wait": ("Needs answer", "Cần trả lời"),
    "g3_search": ("Search duty or article", "Tìm nghĩa vụ hoặc điều"),
    "g3_filter": ("Filter", "Lọc"),
    "g3_q_filter": ("Open question: {id}", "Câu hỏi mở: {id}"),
    "g3_clear": ("Clear", "Bỏ lọc"),
    "g3_show_more": ("Show 25 more", "Xem thêm 25"),
    "g3_more_in": ("{n} more duties in this instrument.", "Còn {n} nghĩa vụ trong văn bản này."),
    "g3_cnt": ("{n} duties", "{n} nghĩa vụ"),
    "g3_cnt_gap": ("{n} gap", "{n} thiếu"),
    "g3_export": ("Export CSV", "Xuất CSV"),
    "g3_legal_data": ("Legal data: RegKB {v} · {d}", "Dữ liệu pháp lý: RegKB {v} · {d}"),
    "g3_none_rows": ("No duty matches this filter.", "Không có nghĩa vụ nào khớp bộ lọc."),
    "g3_shown_n": (
        "Showing {n} duties in {g} instruments",
        "Hiển thị {n} nghĩa vụ trong {g} văn bản",
    ),
    "g3_th_col_id": ("Limit", "Hạn mức"),
    "g3_card_line": (
        "{a} duties apply · {w} need an answer · {q} open questions · {g} limits above the legal cap",
        "{a} nghĩa vụ áp dụng · {w} cần trả lời · {q} câu hỏi mở · {g} hạn mức vượt mức trần luật",
    ),
    "g3_col_agent": ("Agent", "Tác tử"),
    "g3_col_status": ("Duties", "Nghĩa vụ"),
    "g3_col_risk": ("Decision 33", "Quyết định 33"),
    # --- compliance: obligation page
    "g3_ob_applies": ("Applies to this agent", "Áp dụng cho tác tử này"),
    "g3_ob_wait": ("Depends on an open answer", "Phụ thuộc câu trả lời còn mở"),
    "g3_ob_noapply": ("Does not apply", "Không áp dụng"),
    "g3_ob_prev": ("Previous in this instrument", "Nghĩa vụ trước trong văn bản"),
    "g3_ob_next": ("Next in this instrument", "Nghĩa vụ sau trong văn bản"),
    "g3_ob_all": ("All duties of this instrument", "Mọi nghĩa vụ của văn bản này"),
    "g3_col_control": ("Control", "Biện pháp"),
    "g3_col_kind": ("Kind", "Loại"),
    "g3_col_covers": ("Covers", "Mức đáp ứng"),
    "g3_kind_evidence": ("Evidence", "Bằng chứng"),
    "g3_kind_process": ("Bank process", "Quy trình ngân hàng"),
    "g3_kind_rule": ("Rule", "Quy tắc"),
    "g3_kind_control": ("Control", "Biện pháp"),
    "g3_cov_full": ("fully", "đầy đủ"),
    "g3_cov_partial": ("partly", "một phần"),
    "g3_cov_none": ("not yet", "chưa"),
    "g3_src_note": ("Source note", "Ghi chú nguồn"),
    "g3_instr_row": ("{number} · {issuer} · {status}", "{number} · {issuer} · {status}"),
    # --- risks / controls / policies
    "g3_risks_nowork": (
        "{n} risks have no evidence that their controls work, so the residual score equals the inherent score.",
        "{n} rủi ro chưa có bằng chứng kiểm soát đang hoạt động, nên điểm dư bằng điểm gốc.",
    ),
    "g3_same": ("same", "như điểm dư"),
    "g3_ct_open_list": ("Open the list", "Mở danh sách"),
    "g3_pol_version_line": (
        "Version {hash}, in force since {since}, {n} rules.",
        "Phiên bản {hash}, có hiệu lực từ {since}, {n} quy tắc.",
    ),
    "g3_pol_history": ("Version history", "Lịch sử phiên bản"),
    "g3_pol_tools": ("Tools and risk classes ({n})", "Công cụ và nhóm rủi ro ({n})"),
    "g3_fail_mode": ("If the gate fails", "Khi cổng bị lỗi"),
    "g3_fm_closed": ("blocks", "chặn"),
    "g3_fm_open": ("allows", "cho qua"),
    # --- internal documents, law changes, drafts
    "g3_ri_purpose": (
        "Bank policies, standards and procedures you uploaded. The AI model drafts duties; a reviewer confirms them.",
        "Chính sách, tiêu chuẩn và quy trình của ngân hàng đã tải lên. Mô hình AI soạn nghĩa vụ; người rà soát xác nhận.",
    ),
    "g3_ri_dr": (
        "{d} draft · {c} confirmed · {x} dropped",
        "{d} nháp · {c} đã xác nhận · {x} đã bỏ",
    ),
    "g3_rc_purpose": (
        "Updates to laws and rules already in the register.",
        "Cập nhật của luật và quy định đã có trong sổ đăng ký.",
    ),
    "g3_dr_title": ("Drafts for {name}", "Bản nháp cho {name}"),
    "g3_dr_purpose": (
        "Duties drafted by the AI model. A draft becomes a duty only after a reviewer confirms it.",
        "Nghĩa vụ do mô hình AI soạn. Bản nháp chỉ trở thành nghĩa vụ sau khi người rà soát xác nhận.",
    ),
    "g3_dr_internal": (
        "{title}, {version}, owner {owner}. The AI model read masked text only.",
        "{title}, {version}, chủ sở hữu {owner}. Mô hình AI chỉ đọc văn bản đã che dữ liệu.",
    ),
    "g3_dr_internal_note": (
        "A confirmed duty is added to the internal document right away.",
        "Nghĩa vụ đã xác nhận được đưa ngay vào văn bản nội bộ.",
    ),
    "g3_dr_all_docs": ("All internal documents", "Mọi tài liệu nội bộ"),
    "g3_dr_draft": ("Drafts", "Bản nháp"),
    "g3_dr_confirmed": ("Confirmed", "Đã xác nhận"),
    "g3_dr_dropped": ("Dropped", "Đã bỏ"),
    "g3_dr_all": ("All", "Tất cả"),
    "g3_dr_empty_t": ("No drafts yet", "Chưa có bản nháp"),
    "g3_dr_empty_internal": (
        'Press "Draft duties" on the Internal documents page.',
        'Nhấn "Soạn nghĩa vụ" ở trang Tài liệu nội bộ.',
    ),
    "g3_dr_empty_other": ("Pick another status above.", "Chọn trạng thái khác ở trên."),
    "g3_dr_details": ("Details", "Chi tiết"),
    "g3_dr_model": ("Model", "Mô hình"),
    "g3_dr_prompt": ("Prompt version", "Phiên bản câu lệnh"),
    "g3_dr_source": ("Source", "Nguồn"),
    "g3_dr_clause": ("Clause {c}", "Khoản {c}"),
    "g3_dr_section": ("Section {s}", "Mục {s}"),
    "g3_dr_subject": ("Subject", "Đối tượng"),
    "g3_dr_trigger": ("When it applies", "Khi nào áp dụng"),
    "g3_dr_evidence": ("Evidence required", "Bằng chứng yêu cầu"),
    "g3_dr_decided": ("Decided by", "Quyết định bởi"),
    "g3_dr_confirm": ("Confirm", "Xác nhận"),
    "g3_dr_drop": ("Drop", "Bỏ"),
    "g3_dr_mock": ("Test model (mock)", "Mô hình thử nghiệm (mock)"),
    "g3_dr_cli": ("Command line", "Dòng lệnh"),
    "g3_dr_notext": (
        "The official text is not on file, so quotes appear without the surrounding article.",
        "Chưa có văn bản chính thức được lưu, nên các trích dẫn hiển thị không kèm điều xung quanh.",
    ),
}

UX5: dict[str, tuple[str, str]] = {
    # compliance
    "cp_disclaimer": (
        "Advisory only. Not legal advice. Bank counsel confirms.",
        "Chỉ mang tính tham khảo. Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận.",
    ),
    "cp_counts": ("Status of the duties that apply", "Trạng thái các nghĩa vụ áp dụng"),
    "cp_thresholds": ("Limits above the legal cap", "Hạn mức vượt mức trần theo luật"),
    "cp_decides": ("{n} duties wait on this answer", "{n} nghĩa vụ đang chờ câu trả lời này"),
    "cp_any": ("All", "Tất cả"),
    "cp_showing": ("Showing {n} of {m} duties", "Hiển thị {n} / {m} nghĩa vụ"),
    "cp_open": ("Open compliance matrix", "Mở ma trận tuân thủ"),
    "cp_source_demo": ("demo", "demo"),
    "cp_source_onboard": ("registered", "đã đăng ký"),
    "cp_col_obligation": ("Duty", "Nghĩa vụ"),
    "cp_none": ("None", "Không có"),
    "cp_no_text_vi": (
        "No Vietnamese text for this duty yet.",
        "Chưa có văn bản tiếng Việt cho nghĩa vụ này.",
    ),
    "cp_status_reason": ("Why this status", "Vì sao có trạng thái này"),
    # risks
    "rk_ev_none": ("Not run yet", "Chưa chạy"),
    "rk_illustrative": (
        "Score bands are illustrative until the bank sets its own.",
        "Các mức điểm chỉ minh họa cho đến khi ngân hàng đặt mức riêng.",
    ),
    # controls
    "ct_purpose": (
        "Controls the bank and the product use, what each covers, and whether it works.",
        "Các biện pháp kiểm soát ngân hàng và sản phẩm dùng, phạm vi từng biện pháp, và việc nó có hoạt động không.",
    ),
    "ct_uncovered_line": (
        "{n} active risks have no control.",
        "{n} rủi ro đang áp dụng chưa có kiểm soát.",
    ),
    "ct_no_controls_line": (
        "Ask an administrator to load the starter catalogue.",
        "Nhờ quản trị viên nạp danh mục kiểm soát mẫu.",
    ),
    "ct_no_controls": ("No controls yet", "Chưa có kiểm soát"),
    # policies
    "policies_purpose": (
        "The rules the gate enforces now, and the version history.",
        "Các quy tắc cổng đang áp dụng và lịch sử phiên bản.",
    ),
    "policies_why": (
        "Read only. Changes are made in Git and reviewed first.",
        "Chỉ đọc. Mọi thay đổi thực hiện trong Git và được rà soát trước.",
    ),
    # internal documents
    "ri_hint": (
        "Upload a policy, standard or procedure (.txt, .md, or .pdf with text; max {mb} MB). Personal data is masked first. AI drafts one duty per section, and a compliance reviewer confirms each one.",
        "Tải lên chính sách, tiêu chuẩn hoặc quy trình (.txt, .md, hoặc .pdf có chữ; tối đa {mb} MB). Dữ liệu cá nhân được che trước. AI soạn một nghĩa vụ cho mỗi mục, và người rà soát tuân thủ xác nhận từng nghĩa vụ.",
    ),
    "ri_banner": (
        "Not legal advice. Bank counsel confirms.",
        "Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận.",
    ),
    "ri_not_yet": ("Not in RegKB yet", "Chưa vào RegKB"),
    "ri_open_drafts": ("Review drafts", "Xem bản nháp"),
    # law changes
    "rc_banner": (
        "Not legal advice. Bank counsel confirms.",
        "Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận.",
    ),
    "rc_hint": (
        "An update package brings new text. The law agent compares it article by article and drafts the changed duties. A reviewer accepts or drops each draft, then applies the change.",
        "Gói cập nhật mang văn bản mới. Tác tử pháp lý so sánh từng điều và soạn các nghĩa vụ thay đổi. Người xem xét chấp nhận hoặc bỏ từng bản nháp, rồi áp dụng thay đổi.",
    ),
    "rc_none": (
        "No changes imported yet. Import an update package to start.",
        "Chưa nhập thay đổi nào. Hãy nhập gói cập nhật để bắt đầu.",
    ),
}
