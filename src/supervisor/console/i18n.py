"""Console labels in English and Vietnamese (``?lang=vi|en``; default from settings).

Synthetic UI text only. Regulator wording in Vietnamese needs legal review before use.
"""

from __future__ import annotations

from collections.abc import Callable

LANGS = ("en", "vi")

_T: dict[str, tuple[str, str]] = {
    # key: (English, Vietnamese)
    "app": ("Supervisor console", "Bảng điều khiển Supervisor"),
    "queue": ("Queue", "Hàng đợi"),
    "cases": ("Cases", "Vụ việc"),
    "case": ("Case", "Vụ việc"),
    "agents": ("Agents", "Tác tử"),
    "metrics": ("Metrics", "Chỉ số"),
    "export": ("Audit pack", "Gói kiểm toán"),
    "inbox": ("Inbox", "Hộp thư"),
    "signoff": ("Sign-off", "Phê duyệt"),
    "signed_in_as": ("Signed in as", "Đăng nhập với"),
    "roles": ("Roles", "Vai trò"),
    "dev_banner": (
        "Dev identity (users file, X-Dev-User): not a real identity. Laptop demo only.",
        "Danh tính dev (tệp người dùng, X-Dev-User): không phải danh tính thật. Chỉ dùng demo.",
    ),
    "sp_banner": (
        "No SSO user header: acting as the app service principal (read-only).",
        "Không có tiêu đề SSO: đang dùng service principal của ứng dụng (chỉ đọc).",
    ),
    "switch_user": ("Switch user", "Đổi người dùng"),
    "severity": ("Severity", "Mức độ"),
    "status": ("Status", "Trạng thái"),
    "agent": ("Agent", "Tác tử"),
    "source": ("Source", "Nguồn"),
    "summary": ("Summary", "Tóm tắt"),
    "opened": ("Opened", "Mở lúc"),
    "assignee": ("Assignee", "Người xử lý"),
    "sbv_clock": ("SBV 24 h report", "Báo cáo NHNN 24 giờ"),
    "sbv_remediation": ("SBV 5-day remediation", "Khắc phục NHNN 5 ngày"),
    "left": ("left", "còn lại"),
    "overdue": ("overdue", "quá hạn"),
    "all": ("All", "Tất cả"),
    "open_cases": ("Open", "Đang mở"),
    "closed": ("Closed", "Đã đóng"),
    "filter": ("Filter", "Lọc"),
    "no_cases": ("No cases.", "Không có vụ việc."),
    "what_happened": ("What happened", "Chuyện gì đã xảy ra"),
    "why_matters": ("Why it matters", "Vì sao quan trọng"),
    "what_next": ("What you can do", "Bạn có thể làm gì"),
    "timeline": ("Timeline", "Dòng thời gian"),
    "transcript": ("Transcript excerpts (masked)", "Trích đoạn hội thoại (đã che)"),
    "verdicts": ("Verdicts", "Kết luận kiểm tra"),
    "rules_broken": ("Rules broken", "Quy tắc bị vi phạm"),
    "judge_findings": ("Judge findings (advisory)", "Nhận định của giám khảo AI (tham khảo)"),
    "rationale": ("Rationale", "Lý do"),
    "chain": ("Evidence chain", "Chuỗi bằng chứng"),
    "verify_now": ("Verify now", "Kiểm tra ngay"),
    "verify_ok": ("verified", "đã kiểm tra"),
    "verify_fail": ("BROKEN", "BỊ PHÁ VỠ"),
    "not_verified": ("not verified in this session", "chưa kiểm tra trong phiên này"),
    "actions": ("Actions", "Thao tác"),
    "assign": ("Assign", "Giao việc"),
    "comment": ("Comment", "Bình luận"),
    "triage": ("Triage", "Phân loại"),
    "contain": ("Contain", "Ngăn chặn"),
    "close": ("Close", "Đóng"),
    "itsm_ref": ("ITSM ref", "Mã ITSM"),
    "save": ("Save", "Lưu"),
    "note": ("Note", "Ghi chú"),
    "resolution": ("Resolution", "Kết quả"),
    "confirmed": ("Confirmed incident", "Sự cố đã xác nhận"),
    "false_alarm": ("False alarm", "Báo động nhầm"),
    "signoffs": ("Sign-offs", "Phê duyệt"),
    "approve": ("Approve", "Đồng ý"),
    "reject": ("Reject", "Từ chối"),
    "statement": ("Statement (stored verbatim)", "Lời xác nhận (lưu nguyên văn)"),
    "signoff_text": (
        "I have reviewed this case, its evidence and its containment. I approve closing it.",
        "Tôi đã xem xét vụ việc này, bằng chứng và biện pháp ngăn chặn. Tôi đồng ý đóng vụ việc.",
    ),
    "signoff_rule": (
        "High and critical cases need two sign-offs by two different people, "
        "at least one an approver.",
        "Vụ việc mức cao và nghiêm trọng cần hai phê duyệt của hai người khác nhau, "
        "ít nhất một người là người phê duyệt.",
    ),
    "affirm": ("I sign this statement as myself", "Tôi tự ký lời xác nhận này"),
    "state": ("Gate state", "Trạng thái cổng"),
    "coverage": ("Coverage", "Độ bao phủ"),
    "owner": ("Owner", "Chủ sở hữu"),
    "pending_resume": ("Pending resume", "Chờ mở lại"),
    "pause": ("Pause", "Tạm dừng"),
    "resume": ("Resume", "Mở lại"),
    "quarantine": ("Quarantine", "Cách ly"),
    "release": ("Release", "Gỡ cách ly"),
    "reason": ("Reason", "Lý do"),
    "resume_rule": (
        "Pause: one click. Resume: the agent owner and a reviewer, two different people "
        "(ADR D04). Quarantine release: admin only.",
        "Tạm dừng: một lần bấm. Mở lại: chủ sở hữu tác tử và một người duyệt, hai người "
        "khác nhau (ADR D04). Gỡ cách ly: chỉ quản trị viên.",
    ),
    "oversight": ("Oversight metrics", "Chỉ số giám sát"),
    "no_metrics": (
        "No oversight metrics yet (the daily metrics job fills this table).",
        "Chưa có chỉ số giám sát (tác vụ chỉ số hằng ngày sẽ điền bảng này).",
    ),
    "gate_latency": ("Gateway latency", "Độ trễ cổng"),
    "chain_status": ("Chain status", "Trạng thái chuỗi"),
    "lanes": ("Lanes", "Làn"),
    "entries": ("Entries", "Mục"),
    "export_help": (
        "Builds a zip: chain export + offline verify report + case files (JSON, HTML) "
        "+ judge eval report. Written under the data directory; download it below.",
        "Tạo tệp zip: bản xuất chuỗi + báo cáo kiểm tra ngoại tuyến + hồ sơ vụ việc "
        "(JSON, HTML) + báo cáo đánh giá giám khảo. Lưu trong thư mục dữ liệu; tải bên dưới.",
    ),
    "build_pack": ("Build audit pack", "Tạo gói kiểm toán"),
    "download": ("Download", "Tải về"),
    "no_notices": ("No notices.", "Không có thông báo."),
    "mark_read": ("Mark read", "Đánh dấu đã đọc"),
    "subject": ("Subject", "Tiêu đề"),
    "channel": ("Channel", "Kênh"),
    "time": ("Time", "Thời gian"),
    "refresh_cases": ("Refresh cases", "Làm mới hồ sơ"),
    "saved": ("Saved.", "Đã lưu."),
    "mock": ("MOCK", "GIẢ LẬP"),
    "low": ("low", "thấp"),
    "medium": ("medium", "trung bình"),
    "high": ("high", "cao"),
    "critical": ("critical", "nghiêm trọng"),
    "open": ("open", "mở"),
    "triaged": ("triaged", "đã phân loại"),
    "contained": ("contained", "đã ngăn chặn"),
    "language": ("Tiếng Việt", "English"),
    # ---- WP12 shell
    "tagline": ("Onboard · Watch · Prove", "Tiếp nhận · Giám sát · Chứng minh"),
    "nav_label": ("Main sections", "Các mục chính"),
    "nav_overview": ("Overview", "Tổng quan"),
    "nav_evidence": ("Evidence", "Bằng chứng"),
    "nav_onboard": ("Onboard", "Tiếp nhận"),
    "nav_health": ("Health", "Sức khỏe"),
    "env_title": (
        "Where Supervisor runs, and whether this is a demo store",
        "Nơi Supervisor đang chạy, và đây có phải kho dữ liệu demo không",
    ),
    "demo_data": ("demo data", "dữ liệu demo"),
    "theme_toggle": ("Switch light / dark", "Đổi giao diện sáng / tối"),
    "auth_method": ("Sign-in method", "Cách đăng nhập"),
    "mode": ("mode", "chế độ"),
    "role_admin": ("admin", "quản trị"),
    "role_approver": ("approver", "người phê duyệt"),
    "role_reviewer": ("reviewer", "người duyệt"),
    "role_owner": ("owner", "chủ sở hữu"),
    "role_auditor": ("auditor", "kiểm toán"),
    "role_service": ("service", "dịch vụ"),
    "role_viewer": ("viewer", "người xem"),
}


def translator(lang: str) -> Callable[..., str]:
    """``t(key)`` or ``t(key, n=3, ...)`` (``str.format`` placeholders). Unknown keys come
    back unchanged, so a template never fails on a label."""
    idx = 1 if lang == "vi" else 0

    def t(key: str, **kw: object) -> str:
        pair = _T.get(key)
        text = pair[idx] if pair else key
        if kw:
            try:
                return text.format(**kw)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    return t


def keys() -> list[str]:
    return sorted(_T)


def table() -> dict[str, tuple[str, str]]:
    """Both dictionaries (tests check every key has an English and a Vietnamese text)."""
    return dict(_T)


def pick_lang(query: str | None, cookie: str | None, default: str) -> str:
    for value in (query, cookie, default):
        if value in LANGS:
            return value
    return "en"
