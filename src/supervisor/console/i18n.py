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
    # ---- WP12 overview
    "greet_morning": ("Good morning, {name}", "Chào buổi sáng, {name}"),
    "greet_afternoon": ("Good afternoon, {name}", "Chào buổi chiều, {name}"),
    "greet_evening": ("Good evening, {name}", "Chào buổi tối, {name}"),
    "greet_agents_0": ("No agent is under supervision yet.", "Chưa có tác tử nào được giám sát."),
    "greet_agents_1": ("1 agent is under supervision.", "1 tác tử đang được giám sát."),
    "greet_agents_n": ("{n} agents are under supervision.", "{n} tác tử đang được giám sát."),
    "greet_stopped_0": ("No action was stopped today.", "Hôm nay chưa có thao tác nào bị chặn."),
    "greet_stopped_1": ("1 action was stopped today.", "Hôm nay 1 thao tác đã bị chặn."),
    "greet_stopped_n": ("{n} actions were stopped today.", "Hôm nay {n} thao tác đã bị chặn."),
    "greet_cases_0": ("No case is waiting for a decision.", "Không có vụ việc nào chờ quyết định."),
    "greet_cases_1": ("1 case needs a decision.", "1 vụ việc cần quyết định."),
    "greet_cases_n": ("{n} cases need a decision.", "{n} vụ việc cần quyết định."),
    "greet_clock_left": (
        "The nearest SBV 24-hour report clock has {d} left.",
        "Hạn báo cáo NHNN 24 giờ gần nhất còn {d}.",
    ),
    "greet_clock_over": (
        "The nearest SBV 24-hour report is overdue by {d}.",
        "Báo cáo NHNN 24 giờ gần nhất đã quá hạn {d}.",
    ),
    "what_is_lead": (
        "Supervisor watches the AI agents your bank runs.",
        "Supervisor giám sát các tác tử AI mà ngân hàng đang vận hành.",
    ),
    "what_is_rest": (
        "It records every action, stops the dangerous ones before they execute, and keeps "
        "evidence that a regulator can check.",
        "Hệ thống ghi lại mọi thao tác, chặn thao tác nguy hiểm trước khi thực thi, và lưu "
        "bằng chứng mà cơ quan quản lý có thể kiểm tra.",
    ),
    "what_is_why": (
        "Think of a pit boss on a casino floor. The dealers are your agents. The pit boss "
        "never deals, but watches every table, steps in when a hand looks wrong, and the "
        "cameras keep the tape.",
        "Hãy hình dung người giám sát sàn sòng bài. Người chia bài là các tác tử. Người giám "
        "sát không chia bài, nhưng theo dõi mọi bàn, can thiệp khi có ván bất thường, và "
        "camera luôn ghi hình.",
    ),
    "pillar_onboard": ("Onboard", "Tiếp nhận"),
    "pillar_onboard_text": (
        "Read an agent's code and traces. Write its risk profile, its rules and a pull "
        "request. Nothing is merged without a person.",
        "Đọc mã nguồn và vết hoạt động của tác tử. Viết hồ sơ rủi ro, quy tắc và một pull "
        "request. Không gì được hợp nhất nếu không có người duyệt.",
    ),
    "pillar_watch": ("Watch", "Giám sát"),
    "pillar_watch_text": (
        "Every tool call passes a gate. Hard rules block or pause in milliseconds. AI "
        "judges read the rest and only advise.",
        "Mọi lệnh gọi công cụ đi qua cổng kiểm soát. Quy tắc cứng chặn hoặc tạm dừng trong "
        "vài mili giây. Giám khảo AI đọc phần còn lại và chỉ đưa ý kiến.",
    ),
    "pillar_prove": ("Prove", "Chứng minh"),
    "pillar_prove_text": (
        "Decisions go into a signed hash chain. A case file answers the SBV clock. Anyone "
        "can verify the chain offline.",
        "Mọi quyết định được ghi vào chuỗi băm có chữ ký. Hồ sơ vụ việc đáp ứng hạn của "
        "NHNN. Ai cũng có thể kiểm tra chuỗi khi không có mạng.",
    ),
    "num_checked": ("Actions checked today", "Thao tác đã kiểm tra hôm nay"),
    "num_checked_sub": (
        "across {n} agent(s) · every call passed the gate",
        "trên {n} tác tử · mọi lệnh gọi đều qua cổng",
    ),
    "median_ms": ("median {ms} ms", "trung vị {ms} ms"),
    "num_stopped": ("Stopped by a rule", "Bị quy tắc chặn"),
    "blocked_paused": ("{b} blocked · {p} paused", "{b} bị chặn · {p} tạm dừng"),
    "num_stopped_sub": ("before execution", "trước khi thực thi"),
    "num_cases": ("Open cases", "Vụ việc đang mở"),
    "n_critical": ("{n} critical", "{n} nghiêm trọng"),
    "num_cases_sub": (
        "SBV 24 h report clock running on {n}",
        "Đồng hồ báo cáo NHNN 24 giờ đang chạy cho {n} vụ",
    ),
    "n_entries": ("{n} entries", "{n} mục"),
    "signed_root": ("signed root", "gốc đã ký"),
    "no_signed_root": ("no signed root yet", "chưa có gốc đã ký"),
    "anchored": ("anchored", "đã neo"),
    "not_anchored": ("not anchored yet", "chưa neo"),
    "verified_at": ("verified {time}", "đã kiểm tra {time}"),
    "not_verified_short": ("not verified yet", "chưa kiểm tra"),
    "latest_decisions": ("Latest gate decisions", "Quyết định mới nhất của cổng"),
    "all_cases": ("All cases", "Tất cả vụ việc"),
    "outcome_blocked": ("blocked", "bị chặn"),
    "outcome_paused": ("paused", "tạm dừng"),
    "outcome_allowed": ("allowed", "cho phép"),
    "rule_word": ("rule", "quy tắc"),
    "case_arrow": ("case", "vụ việc"),
    "no_decisions": (
        "No gate decision yet. Decisions appear here when an agent calls a tool.",
        "Chưa có quyết định nào. Quyết định xuất hiện khi tác tử gọi công cụ.",
    ),
    "risk_read_only": ("read-only", "chỉ đọc"),
    "risk_money": ("moves money", "di chuyển tiền"),
    "risk_credit": ("credit decision", "quyết định tín dụng"),
    "risk_pii_export": ("exports personal data", "xuất dữ liệu cá nhân"),
    "demo_line": (
        "Demo data only. Every customer and every agent reply is synthetic. The gate "
        "decisions, the pause and the evidence chain are real.",
        "Chỉ là dữ liệu demo. Mọi khách hàng và mọi câu trả lời của tác tử đều là dữ liệu "
        "giả lập. Quyết định của cổng, việc tạm dừng và chuỗi bằng chứng là thật.",
    ),
    "demo_note": (
        "Demo data: the agents' replies are scripted and the customers are synthetic. The "
        "gate decisions, the pause and the chain are real.",
        "Dữ liệu demo: câu trả lời của tác tử theo kịch bản và khách hàng là giả lập. Quyết "
        "định của cổng, việc tạm dừng và chuỗi bằng chứng là thật.",
    ),
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
