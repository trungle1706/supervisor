# ruff: noqa: E501
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
        "Test sign-in (X-Dev-User). Not a real identity. For laptop demos only.",
        "Đăng nhập thử nghiệm (X-Dev-User). Không phải danh tính thật. Chỉ dùng cho demo trên máy tính xách tay.",
    ),
    "sp_banner": (
        "You are not signed in through SSO. The console runs as the app account and is view only.",
        "Bạn chưa đăng nhập qua SSO. Console đang chạy bằng tài khoản dịch vụ của ứng dụng và chỉ cho xem.",
    ),
    "switch_user": ("Switch user", "Đổi người dùng"),
    "severity": ("Severity", "Mức độ"),
    "status": ("Status", "Trạng thái"),
    "agent": ("Agent", "Tác tử"),
    "source": ("Source", "Nguồn"),
    "summary": ("Summary", "Tóm tắt"),
    "opened": ("Opened", "Mở lúc"),
    "assignee": ("Assignee", "Người xử lý"),
    "report_due_col": ("Report due", "Hạn báo cáo"),
    "incident_urgency": ("Incident urgency", "Mức khẩn cấp sự cố"),
    "urgency_urgent": ("urgent (72 h)", "khẩn cấp (72 giờ)"),
    "urgency_standard": ("standard (5 working days)", "thông thường (5 ngày làm việc)"),
    "prelim_due": ("Preliminary report due", "Hạn báo cáo sơ bộ"),
    "formal_due": ("Formal report due", "Hạn báo cáo chính thức"),
    "sent_at": ("sent", "đã gửi"),
    "mark_prelim_sent": ("Mark preliminary report as sent", "Đánh dấu đã gửi báo cáo sơ bộ"),
    "mark_formal_sent": ("Mark formal report as sent", "Đánh dấu đã gửi báo cáo chính thức"),
    "ev_report_prelim": (
        "{who} recorded the preliminary incident report as sent.",
        "{who} ghi nhận đã gửi báo cáo sơ bộ sự cố.",
    ),
    "ev_report_formal": (
        "{who} recorded the formal incident report as sent.",
        "{who} ghi nhận đã gửi báo cáo chính thức sự cố.",
    ),
    "sbv_remediation": ("SBV 5-day remediation", "Khắc phục NHNN 5 ngày"),
    "overdue": ("overdue", "quá hạn"),
    "all": ("All", "Tất cả"),
    "open_cases": ("Open", "Đang mở"),
    "closed": ("Closed", "Đã đóng"),
    "filter": ("Filter", "Lọc"),
    "no_cases": ("No cases.", "Không có vụ việc."),
    "what_happened": ("What happened", "Chuyện gì đã xảy ra"),
    "why_matters": ("Why it matters", "Vì sao quan trọng"),
    "timeline": ("Timeline", "Dòng thời gian"),
    "transcript": ("Masked transcript excerpt", "Trích đoạn hội thoại (đã che)"),
    "verdicts": ("Verdicts", "Kết luận kiểm tra"),
    "rules_broken": ("Rules broken", "Quy tắc bị vi phạm"),
    "judge_findings": ("Judge findings (advisory)", "Nhận định của giám khảo AI (tham khảo)"),
    "rationale": ("Reason", "Lý do"),
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
    "approve": ("Approve", "Phê duyệt"),
    "reject": ("Reject", "Từ chối"),
    "statement": ("Statement (stored verbatim)", "Lời xác nhận (lưu nguyên văn)"),
    "signoff_text": (
        "I have reviewed this case, its evidence and its containment. I approve closing it.",
        "Tôi đã xem xét vụ việc này, bằng chứng và biện pháp ngăn chặn. Tôi đồng ý đóng vụ việc.",
    ),
    "signoff_rule": (
        "High and critical cases need sign-off from two different people. At least one must be an approver.",
        "Vụ việc mức cao và nghiêm trọng cần hai người khác nhau phê duyệt. Ít nhất một người phải là người phê duyệt.",
    ),
    "affirm": ("I sign this statement as myself", "Tôi tự ký lời xác nhận này"),
    "state": ("Gate state", "Trạng thái cổng"),
    "coverage": ("Coverage", "Độ bao phủ"),
    "kept_args": ("Arguments passed unmasked", "Tham số được chuyển không che"),
    "kept_args_hint": (
        "The policy passes these arguments on as sent (they are lookup keys). The audit trail and findings still store them masked.",
        "Chính sách chuyển các tham số này đi nguyên bản (đây là khóa tra cứu). Nhật ký kiểm toán và phát hiện vẫn lưu chúng ở dạng đã che.",
    ),
    "owner": ("Owner", "Chủ sở hữu"),
    "pending_resume": ("Waiting to restart", "Chờ chạy lại"),
    "pause": ("Pause", "Tạm dừng"),
    "resume": ("Resume", "Mở lại"),
    "quarantine": ("Quarantine", "Cách ly"),
    "release": ("Release", "Gỡ cách ly"),
    "reason": ("Reason", "Lý do"),
    "oversight": ("Oversight metrics", "Chỉ số giám sát"),
    "no_metrics": (
        "No oversight metrics yet. They fill in after the daily metrics job runs.",
        "Chưa có chỉ số giám sát. Chỉ số sẽ hiện sau khi tác vụ chỉ số hằng ngày chạy.",
    ),
    "gate_latency": ("Gateway latency", "Độ trễ cổng"),
    "chain_status": ("Chain status", "Trạng thái chuỗi"),
    "lanes": ("Lanes", "Làn"),
    "entries": ("Entries", "Mục"),
    "export_help": (
        "Creates a zip with the evidence chain, verification report, case files and judge report. Download it below.",
        "Tạo tệp zip gồm chuỗi bằng chứng, báo cáo kiểm tra, hồ sơ vụ việc và báo cáo giám khảo. Tải về bên dưới.",
    ),
    "build_pack": ("Build audit pack", "Tạo gói kiểm toán"),
    "download": ("Download", "Tải về"),
    "no_notices": ("No notices.", "Không có thông báo."),
    "mark_read": ("Mark read", "Đánh dấu đã đọc"),
    "subject": ("Subject", "Tiêu đề"),
    "channel": ("Channel", "Kênh"),
    "time": ("Time", "Thời gian"),
    "refresh_cases": ("Refresh cases", "Làm mới vụ việc"),
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
    "tagline": ("AI\u00a0management · AI\u00a0guardian", "Quản lý AI · Giám sát AI"),
    "nav_label": ("Main sections", "Các mục chính"),
    "nav_overview": ("Overview", "Tổng quan"),
    "nav_evidence": ("Evidence", "Bằng chứng"),
    "nav_onboard": ("Onboard", "Tiếp nhận"),
    "nav_health": ("Health", "Sức khỏe"),
    "env_title": (
        "Where Supervisor runs, and whether it holds demo data",
        "Nơi Supervisor đang chạy, và có đang dùng dữ liệu demo không",
    ),
    "demo_data": ("demo data", "demo"),
    "theme_toggle": ("Switch light / dark", "Đổi giao diện sáng / tối"),
    "auth_method": ("Sign-in method", "Cách đăng nhập"),
    "mode": ("mode", "chế độ"),
    "role_admin": ("admin", "quản trị"),
    "role_approver": ("approver", "người phê duyệt"),
    "role_reviewer": ("reviewer", "người duyệt"),
    "role_owner": ("owner", "chủ sở hữu"),
    "role_auditor": ("auditor", "kiểm toán"),
    "role_service": ("service", "dịch vụ"),
    "role_operator": ("operator", "vận hành"),  # WP-UX3 review: the header showed "viewer"
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
        "Next report to SBV is due in {d}.",
        "Báo cáo gần nhất gửi NHNN còn {d}.",
    ),
    "greet_clock_over": (
        "Next report to SBV is overdue by {d}.",
        "Báo cáo gần nhất gửi NHNN đã quá hạn {d}.",
    ),
    "what_is_lead": (
        "Supervisor watches the AI agents your bank runs.",
        "Supervisor giám sát các tác tử AI mà ngân hàng đang vận hành.",
    ),
    "what_is_rest": (
        "It records every action, blocks risky ones before they run, and keeps evidence a regulator can check.",
        "Hệ thống ghi lại mọi thao tác, chặn thao tác rủi ro trước khi chạy, và lưu bằng chứng để cơ quan quản lý kiểm tra.",
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
        "Reads an agent's code and activity. Drafts its risk profile, rules and a change request. Nothing is accepted without a person's review.",
        "Đọc mã nguồn và hoạt động của tác tử. Soạn hồ sơ rủi ro, quy tắc và đề xuất thay đổi. Không có gì được chấp nhận nếu chưa có người duyệt.",
    ),
    "pillar_watch": ("Watch", "Giám sát"),
    "pillar_watch_text": (
        "Every tool call passes the gate. Hard rules block or pause a call within milliseconds. AI judges review the rest and only advise.",
        "Mọi lệnh gọi công cụ đều đi qua cổng kiểm soát. Quy tắc cứng chặn hoặc tạm dừng trong vài mili giây. Giám khảo AI xem xét phần còn lại và chỉ đưa ý kiến.",
    ),
    "pillar_prove": ("Prove", "Chứng minh"),
    "pillar_prove_text": (
        "Every decision goes into a signed log that shows any tampering. A case file meets the SBV deadline. Anyone can check the log offline.",
        "Mọi quyết định được ghi vào nhật ký có chữ ký, mọi chỉnh sửa đều bị phát hiện. Hồ sơ vụ việc đáp ứng hạn của NHNN. Ai cũng có thể kiểm tra nhật ký khi không có mạng.",
    ),
    "num_checked": ("Actions checked today", "Thao tác đã kiểm tra hôm nay"),
    "num_checked_sub": (
        "across {n} agent(s) · every call went through the gate",
        "trên {n} tác tử · mọi lệnh gọi đều qua cổng",
    ),
    "median_ms": ("median {ms} ms", "trung vị {ms} ms"),
    "num_stopped": ("Stopped by a rule", "Bị quy tắc chặn"),
    "blocked_paused": ("{b} blocked · {p} paused", "{b} bị chặn · {p} tạm dừng"),
    "num_stopped_sub": ("before they ran", "trước khi thực hiện"),
    "num_cases": ("Open cases", "Vụ việc đang mở"),
    "n_critical": ("{n} critical", "{n} nghiêm trọng"),
    "num_cases_sub": (
        "SBV 24-hour reporting clock running on {n}",
        "Đồng hồ báo cáo NHNN 24 giờ đang chạy cho {n} vụ",
    ),
    "n_entries": ("{n} entries", "{n} mục"),
    "signed_root": ("signed root", "gốc đã ký"),
    "no_signed_root": ("not signed yet", "chưa ký"),
    "anchored": ("anchored", "đã neo"),
    "not_anchored": ("not sealed yet", "chưa niêm phong"),
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
        "Chưa có quyết định nào của cổng. Quyết định sẽ hiện ở đây khi tác tử gọi công cụ.",
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
    # ---- WP12 agents
    "agents_purpose": (
        "All agents the bank runs and their current state.",
        "Mọi tác tử ngân hàng đang vận hành và trạng thái hiện tại.",
    ),
    "agents_why": (
        "Any reviewer can pause an agent. To resume it, the agent owner and a reviewer both approve. Only admins can quarantine.",
        "Người rà soát nào cũng có thể tạm dừng tác tử. Để cho chạy lại, cần cả chủ sở hữu tác tử và một người rà soát phê duyệt. Chỉ quản trị viên được cách ly.",
    ),
    "by_rule": ("by rule {rule}", "do quy tắc {rule}"),
    "by_person": ("by {who}", "bởi {who}"),
    "shadow_word": ("shadow", "chế độ bóng"),
    "enforced_word": ("enforced", "đang thực thi"),
    "risk": ("risk", "rủi ro"),
    "d33_high": ("Decision 33 high-risk", "Quyết định 33: rủi ro cao"),
    "d33_not_high": ("not high-risk under Decision 33", "không thuộc rủi ro cao theo QĐ 33"),
    "d33_label": ("Decision 33", "Quyết định 33"),
    "d33_none": ("Decision 33 not classified yet", "chưa phân loại theo Quyết định 33"),
    "proposal": ("suggested", "gợi ý"),
    "model_family": ("model family", "họ mô hình"),
    "judge_family": ("judge family", "họ giám khảo"),
    "lifecycle": ("Lifecycle", "Vòng đời"),
    "stage_discover": ("Discover", "Khám phá"),
    "stage_understand": ("Understand", "Hiểu"),
    "stage_plan": ("Plan", "Lập kế hoạch"),
    "stage_instrument": ("Add monitoring", "Gắn giám sát"),
    "stage_launch": ("Launch", "Ra mắt"),
    "stage_operate": ("Operate", "Vận hành"),
    "stage_note_shadow": ("shadow mode", "chế độ bóng"),
    "stage_note_enforced": ("enforced", "đang thực thi"),
    "cov_src_capabilities": (
        "{detail} monitoring functions switched on",
        "{detail} chức năng giám sát đang bật",
    ),
    "cov_src_metric": (
        "share of tool calls that went through the gate (daily figure {detail})",
        "tỷ lệ lệnh gọi công cụ đi qua cổng (số liệu ngày {detail})",
    ),
    "cov_src_events": (
        "{detail} recent tool calls passed the gate",
        "{detail} lệnh gọi công cụ gần đây đã đi qua cổng",
    ),
    "cov_src_none": (
        "No activity yet, so coverage is not measured",
        "Chưa có hoạt động nên chưa đo độ bao phủ",
    ),
    "cov_planned": (
        "{p} of {n} monitoring functions planned, not yet active",
        "{p}/{n} chức năng giám sát đã lên kế hoạch, chưa hoạt động",
    ),
    "cov_missing": ("Not visible to monitoring: {items}", "Giám sát chưa thấy: {items}"),
    "tools_summary": ("{n} tools, {m} can move money", "{n} công cụ, {m} có thể chuyển tiền"),
    "fail_mode_is": ("fail mode {mode}", "khi lỗi: {mode}"),
    "fail_closed": ("closed", "đóng (chặn)"),
    "fail_open": ("open", "mở (cho qua)"),
    "fail_mixed": ("mixed", "hỗn hợp"),
    "fail_-": ("-", "-"),
    "open_cases_n": ("{n} open case(s)", "{n} vụ việc đang mở"),
    "pause_now": ("Pause now", "Tạm dừng ngay"),
    "pause_rule": (
        "Any reviewer can pause with one click. It takes effect at the agent's next tool call.",
        "Người rà soát nào cũng có thể tạm dừng chỉ bằng một cú nhấp. Có hiệu lực ở lệnh gọi công cụ tiếp theo của tác tử.",
    ),
    "approve_resume": ("Approve resuming", "Phê duyệt cho chạy lại"),
    "second_approval": ("Give the second approval", "Phê duyệt lần hai"),
    "approved_by": ("Approved by {who} ({role}).", "{who} ({role}) đã phê duyệt."),
    "waiting_for": ("Waiting for the {role}.", "Đang chờ {role}."),
    "resume_rule_short": (
        "Needs the agent owner and a reviewer, two different people.",
        "Cần chủ sở hữu tác tử và một người duyệt, là hai người khác nhau.",
    ),
    "you_are_role": ("You are the {role}.", "Bạn là {role}."),
    "you_approved": (
        "You approved. The second approver must approve too.",
        "Bạn đã phê duyệt. Cần người phê duyệt thứ hai phê duyệt nữa.",
    ),
    "you_cannot_resume": (
        "Only the owner or a policy reviewer can approve. You are neither.",
        "Chỉ chủ sở hữu hoặc người duyệt chính sách mới được phê duyệt. Bạn không thuộc hai nhóm này.",
    ),
    "release_rule": (
        "Only an admin named in the policy can release a quarantine. Give a reason.",
        "Chỉ quản trị viên được nêu trong chính sách mới gỡ được cách ly. Cần ghi lý do.",
    ),
    "quarantine_rule": (
        "Admin only. Stops every call until an admin releases it.",
        "Chỉ quản trị viên. Chặn mọi lệnh gọi cho đến khi quản trị viên gỡ.",
    ),
    "reason_required": ("Reason (required)", "Lý do (bắt buộc)"),
    "no_agents": (
        "No agent is registered yet. Use Onboard to bring the first agent under supervision.",
        "Chưa có tác tử nào được đăng ký. Dùng Tiếp nhận để đưa tác tử đầu tiên vào giám sát.",
    ),
    # ---- WP12 cases
    "archive": ("Archive", "Lưu trữ"),
    "cases_purpose": (
        "A case needs a decision from you. Rules, AI judges and monitors open cases. Your team reviews and closes them.",
        "Vụ việc cần bạn quyết định. Quy tắc, giám khảo AI và bộ giám sát sẽ mở vụ việc. Đội của bạn xem xét và đóng.",
    ),
    "cases_why": (
        "Deadlines follow the draft SBV circular: report within 24 hours, fix within 5 days.",
        "Thời hạn theo dự thảo thông tư NHNN: báo cáo trong 24 giờ, khắc phục trong 5 ngày.",
    ),
    "cases_note": (
        "Closed cases move to the archive with their case file. The list refreshes every 30 s.",
        "Vụ việc đã đóng chuyển vào lưu trữ cùng hồ sơ. Danh sách tự làm mới mỗi 30 giây.",
    ),
    "opened_by": ("Opened by", "Mở bởi"),
    "src_gate": ("gate", "cổng"),
    "src_judge": ("judge", "giám khảo"),
    "src_monitor": ("monitor", "giám sát"),
    "src_manual": ("person", "người"),
    "joined_n": ("+{n} more stop(s) joined", "+{n} lần chặn khác gộp vào"),
    "hl_pause": (
        "{agent} paused: {what} was stopped before it ran",
        "{agent} bị tạm dừng: {what} đã bị chặn trước khi chạy",
    ),
    "hl_block": (
        "{agent}: {what} was blocked before it ran",
        "{agent}: {what} đã bị chặn trước khi chạy",
    ),
    "what_money": ("a money transfer ({tool})", "một lệnh chuyển tiền ({tool})"),
    "what_credit": ("a credit decision ({tool})", "một quyết định tín dụng ({tool})"),
    "what_pii": ("a personal-data export ({tool})", "một lần xuất dữ liệu cá nhân ({tool})"),
    "what_read": ("a read ({tool})", "một lần đọc dữ liệu ({tool})"),
    "what_call": ("a tool call ({tool})", "một lệnh gọi công cụ ({tool})"),
    "time_left": ("{d} left", "còn {d}"),
    "overdue_by": ("overdue by {d}", "quá hạn {d}"),
    "escalated": ("escalated", "đã chuyển cấp"),
    "resolved": ("resolved", "đã giải quyết"),
    # ---- WP12 case page
    "opened_by_gate": ("opened by the gate", "mở bởi cổng"),
    "opened_by_judge": ("opened by an AI judge", "mở bởi bộ đánh giá AI"),
    "opened_by_monitor": ("opened by a monitor", "mở bởi bộ giám sát"),
    "opened_by_manual": ("opened by a person", "mở bởi người dùng"),
    "case_line_pause": (
        "Rule {rule} ({desc}) paused the agent before the call reached the bank system.",
        "Quy tắc {rule} ({desc}) đã tạm dừng tác tử trước khi lệnh gọi tới hệ thống ngân hàng.",
    ),
    "case_line_block": (
        "Rule {rule} ({desc}) blocked the call before it reached the bank system.",
        "Quy tắc {rule} ({desc}) đã chặn lệnh gọi trước khi tới hệ thống ngân hàng.",
    ),
    "case_line_amount": ("Amount: {amount} {cur}.", "Số tiền: {amount} {cur}."),
    "case_line_latency": (
        "Time from detection to block: {ms} ms.",
        "Từ phát hiện đến chặn: {ms} ms.",
    ),
    "d33_pending": (
        "Decision 33 classification pending (bank counsel)",
        "Phân loại theo Quyết định 33 đang chờ (pháp chế ngân hàng)",
    ),
    "regulation": ("Regulation", "Quy định"),
    "tab_story": ("Story", "Diễn biến"),
    "tab_rules": ("Rules & judges", "Quy tắc & giám khảo"),
    "tab_transcript": ("Transcript", "Hội thoại"),
    "tab_evidence": ("Evidence", "Bằng chứng"),
    "tab_casefile": ("Case file", "Hồ sơ vụ việc"),
    "chain_lane": ("Chain", "Chuỗi"),
    "head": ("head", "đầu chuỗi"),
    "verify_again": ("Verify again", "Kiểm tra lại"),
    "casefile_btn": ("Case file", "Hồ sơ vụ việc"),
    "your_decision": ("Your decision", "Quyết định của bạn"),
    "need_two": (
        "Closing a {sev} case needs sign-off from 2 different people, one of them an approver.",
        "Đóng vụ việc mức {sev} cần 2 người khác nhau phê duyệt, trong đó có một người phê duyệt.",
    ),
    "signoffs_n": ("{n}/2 sign-offs so far.", "Đã có {n}/2 phê duyệt."),
    "you_are_a": ("You are a {role}.", "Bạn là {role}."),
    "need_one": (
        "One reviewer can close a {sev} case with a resolution and a reason.",
        "Một người duyệt có thể đóng vụ việc mức {sev} với kết quả và lý do.",
    ),
    "assign_to_me": ("Assign to me", "Giao cho tôi"),
    "assigned_to": ("Assigned to {who}.", "Đã giao cho {who}."),
    "assigned_to_you": ("Assigned to you.", "Đã giao cho bạn."),
    "mark_triaged": ("Mark triaged · add note", "Đánh dấu đã phân loại · ghi chú"),
    "triage_note_ph": ("What you checked", "Bạn đã kiểm tra gì"),
    "contain_btn": ("Contain and keep agent paused", "Ngăn chặn và giữ tác tử tạm dừng"),
    "contain_btn_running": ("Contain and record action taken", "Ngăn chặn và ghi lại việc đã làm"),
    "contain_note": (
        "What you did to contain it (required)",
        "Bạn đã làm gì để ngăn chặn (bắt buộc)",
    ),
    "agent_now": ("Agent {agent} is {state} now.", "Tác tử {agent} hiện đang {state}."),
    "pause_on_agents": ("Pause it on the Agents page →", "Tạm dừng ở trang Tác tử →"),
    "close_needs_two": ("Close (needs 2 sign-offs)", "Đóng (cần 2 phê duyệt)"),
    "close_why_open": ("Review the case first.", "Hãy xem xét vụ việc trước."),
    "close_why_two": (
        "{n} of 2 sign-offs so far. You need two different people, one of them an approver.",
        "Đã có {n}/2 phê duyệt. Cần hai người khác nhau, trong đó có một người phê duyệt.",
    ),
    "close_why_role": (
        "Only a reviewer or an admin can close a case.",
        "Chỉ người duyệt hoặc quản trị viên được đóng vụ việc.",
    ),
    "close_from_triaged": (
        "Until the issue is contained, only a false alarm can be closed.",
        "Khi sự cố chưa được ngăn chặn, chỉ báo động nhầm mới được đóng.",
    ),
    "add_comment": ("Add a comment", "Thêm bình luận"),
    "comment_masked": (
        "Comments are masked before they are stored.",
        "Bình luận được che dữ liệu cá nhân trước khi lưu.",
    ),
    "case_closed_line": (
        "Closed {when}. The case file is final.",
        "Đã đóng {when}. Hồ sơ đã chốt.",
    ),
    "itsm_ticket": ("ITSM ticket", "Phiếu ITSM"),
    "itsm_hint": (
        "Link an ITSM ticket so the bank's ITSM matches this case.",
        "Liên kết phiếu ITSM để ITSM của ngân hàng khớp với vụ việc này.",
    ),
    "st_planned": ("Agent asked to run {tool}.", "Tác tử yêu cầu chạy {tool}."),
    "st_amount": ("Amount {amount} {cur}.", "Số tiền {amount} {cur}."),
    "st_read": ("Agent read data with {tool}.", "Tác tử đọc dữ liệu bằng {tool}."),
    "st_called": (
        "Agent called {tool} (allowed by the gate).",
        "Tác tử gọi {tool} (cổng cho phép).",
    ),
    "st_rule_pause": (
        "Rule {rule} matched: {desc}. The call was paused and did not run.",
        "Quy tắc {rule} khớp: {desc}. Lệnh gọi đã bị tạm dừng và không được chạy.",
    ),
    "st_rule_block": (
        "Rule {rule} matched: {desc}. The call was blocked and did not run.",
        "Quy tắc {rule} khớp: {desc}. Lệnh gọi đã bị chặn và không được chạy.",
    ),
    "st_latency": ("Stopped {ms} ms after detection.", "Chặn sau {ms} ms kể từ khi phát hiện."),
    "st_t0b": (
        "Possible prompt injection found: {why} (advice only).",
        "Phát hiện dấu hiệu tiêm lệnh: {why} (chỉ tư vấn).",
    ),
    "st_judge": (
        "Tier {tier} judge: {label}, {action} (advice only).",
        "Giám khảo cấp {tier}: {label}, {action} (chỉ tư vấn).",
    ),
    "ev_open": (
        "{who} opened the case. Reviewers were notified in the inbox.",
        "{who} mở vụ việc. Người duyệt đã được báo trong hộp thư.",
    ),
    "ev_assign": ("{who} assigned the case.", "{who} đã giao vụ việc."),
    "ev_triage": ("{who} marked the case triaged.", "{who} đánh dấu vụ việc đã phân loại."),
    "ev_contain": ("{who} recorded the containment.", "{who} ghi nhận biện pháp ngăn chặn."),
    "ev_comment": ("{who} commented.", "{who} đã bình luận."),
    "ev_itsm": ("{who} linked an ITSM ticket.", "{who} liên kết phiếu ITSM."),
    "ev_join": (
        "Another blocked call was added to this case.",
        "Một lệnh gọi bị chặn khác được thêm vào vụ việc.",
    ),
    "ev_raise": ("{who} raised the severity.", "{who} nâng mức độ nghiêm trọng."),
    "ev_close": ("{who} closed the case ({detail}).", "{who} đóng vụ việc ({detail})."),
    "ev_other": ("{who}: {action}", "{who}: {action}"),
    "st_signoff": ("{who} signed off: {decision}.", "{who} phê duyệt: {decision}."),
    "st_waiting": ("Needs a decision: {next}.", "Cần quyết định: {next}."),
    "rules_and_judges": ("Rules and judges", "Quy tắc và giám khảo"),
    "details": ("Details", "Chi tiết"),
    "verdict": ("Verdict", "Kết luận"),
    "judge_word": ("judge", "giám khảo"),
    "judge_mock_note": (
        "No real model configured. Judges never block.",
        "Chưa cấu hình mô hình thật. Giám khảo không bao giờ chặn.",
    ),
    "judge_advisory_note": (
        "Advisory only. Judges never block.",
        "Chỉ tham khảo. Giám khảo không bao giờ chặn.",
    ),
    "no_verdicts": (
        "No result from a rule or AI judge yet.",
        "Chưa có kết quả từ quy tắc hoặc bộ đánh giá AI.",
    ),
    "rules_tab_why": (
        "Only fixed rules can block or pause an action. AI judges give advice only.",
        "Chỉ quy tắc cố định mới chặn hoặc tạm dừng hành động. Giám khảo AI chỉ đưa ra tư vấn.",
    ),
    "verdict_details": ("Every check on this case", "Mọi lần kiểm tra của vụ việc"),
    "checker": ("Checker", "Bộ kiểm tra"),
    "label": ("Label", "Nhãn"),
    "score_bp": ("Score (0-10000)", "Điểm (0-10000)"),
    "more_lines": ("{n} more lines in the Transcript tab", "còn {n} dòng ở thẻ Hội thoại"),
    "no_transcript": (
        "No agent events were recorded for this case.",
        "Chưa ghi nhận sự kiện nào của tác tử cho vụ việc này.",
    ),
    "masking_note": (
        "Personal data is masked when captured. Raw text never enters the evidence chain or reaches the judges.",
        "Dữ liệu cá nhân được che ngay khi ghi nhận. Văn bản gốc không bao giờ vào chuỗi bằng chứng hay tới giám khảo.",
    ),
    "mask_version": ("mask version", "phiên bản che"),
    "event": ("Event", "Sự kiện"),
    "masked_text": ("Masked arguments / result", "Tham số / kết quả đã che"),
    "case_on_chain": ("This case on the evidence chain", "Vụ việc này trên chuỗi bằng chứng"),
    "case_on_chain_why": (
        "Every gate decision and every human action on this case is an entry in the agent's lane.",
        "Mọi quyết định của cổng và mọi thao tác của con người trong vụ việc là một mục trong "
        "làn của tác tử.",
    ),
    "seq_range": ("Sequence", "Số thứ tự"),
    "last_signed_root": ("Last signed root", "Gốc ký gần nhất"),
    "key": ("key", "khóa"),
    "key_dev": ("test key", "khóa thử nghiệm"),
    "key_managed": ("managed key", "khóa được quản lý"),
    "last_anchor": ("Last anchor", "Lần neo gần nhất"),
    "links": ("Sources", "Nguồn"),
    "reference": ("Reference", "Tham chiếu"),
    "casefile_why": (
        "The case file answers the SBV report: what happened, the rules, the people and the "
        "evidence.",
        "Hồ sơ vụ việc đáp ứng báo cáo NHNN: chuyện gì xảy ra, quy tắc, con người và bằng chứng.",
    ),
    "items": ("items", "mục"),
    "open_casefile_html": ("Open case file (HTML)", "Mở hồ sơ (HTML)"),
    "download_json": ("Download JSON", "Tải JSON"),
    "casefile_hint": (
        "View only. The audit pack creates the files and records their hashes in the evidence chain.",
        "Chỉ để xem. Gói kiểm toán tạo các tệp và ghi mã băm của chúng vào chuỗi bằng chứng.",
    ),
    "signoff_purpose": (
        "Sign the statement in your own name. It is saved exactly as written and recorded in the audit trail.",
        "Ký xác nhận bằng tên của chính bạn. Nội dung được lưu nguyên văn và ghi vào nhật ký kiểm toán.",
    ),
    "no_signoffs": ("No approval yet.", "Chưa có phê duyệt."),
    "go_close": ("Go to the case to close it", "Về vụ việc để đóng"),
    "signoff_recorded": ("Sign-off recorded.", "Đã ghi nhận phê duyệt."),
    # ---- WP12 evidence
    "ev_purpose_lead": (
        "Every decision and every action by a person is recorded in a tamper-evident chain. The verifier detects any change.",
        "Mọi quyết định và thao tác của con người đều được ghi vào chuỗi chống sửa đổi. Công cụ kiểm tra phát hiện mọi thay đổi.",
    ),
    "ev_purpose_rest": (
        "Change a single character and the verifier shows where.",
        "Chỉ cần đổi một ký tự, công cụ kiểm tra sẽ chỉ ra vị trí.",
    ),
    "ev_why": (
        "The chain is sealed with a signed root and stored where it cannot be altered. You can check an export offline on a laptop.",
        "Chuỗi được niêm phong bằng một gốc có chữ ký và lưu ở nơi không thể sửa. Bạn có thể kiểm tra bản xuất ngoại tuyến trên máy tính xách tay.",
    ),
    "lanes_sub": ("{n} agent lane(s) + 1 root lane", "{n} làn tác tử + 1 làn gốc"),
    "anchor_target_worm": ("write-once folder", "thư mục chỉ-ghi-một-lần"),
    "anchor_target_uc": ("UC Volume", "UC Volume"),
    "not_anchored_why": (
        "The evidence has not been secured yet. The anchor job does this (scheduled, or run python -m supervisor.jobs.anchor).",
        "Bằng chứng chưa được xác nhận. Tác vụ neo sẽ thực hiện (theo lịch, hoặc chạy python -m supervisor.jobs.anchor).",
    ),
    "signed_n": ("{n} signed", "{n} đã ký"),
    "ok_word": ("OK", "ổn"),
    "no_chain": ("No evidence has been recorded yet.", "Chưa có bằng chứng nào được ghi."),
    "lg_decision": ("gate decision / event", "quyết định cổng / sự kiện"),
    "lg_case": ("case opened", "mở vụ việc"),
    "lg_state": ("pause / resume", "tạm dừng / mở lại"),
    "lg_human": ("a person's action", "thao tác của con người"),
    "lg_signed": ("signed root (locks all lane heads)", "gốc có chữ ký (khóa đầu mọi làn)"),
    "lanes_hint": (
        "Each square is one entry, newest on the right; a lane shows its last {cap} entries "
        "and the number of earlier ones.",
        "Mỗi ô là một mục, mới nhất ở bên phải; mỗi làn hiện {cap} mục cuối và số mục trước đó.",
    ),
    "export_chain": ("Export evidence chain", "Xuất chuỗi bằng chứng"),
    "working": ("working…", "đang xử lý…"),
    "chain_exported": ("Chain exported", "Đã xuất chuỗi"),
    "pack_built": ("Audit pack ready ({n} case files)", "Đã tạo gói kiểm toán ({n} hồ sơ)"),
    "offline_verify": ("offline check", "kiểm tra ngoại tuyến"),
    "how_offline": ("How to verify offline", "Cách kiểm tra ngoại tuyến"),
    "how_offline_intro": (
        "On any Windows laptop with Python 3.11 and the Supervisor release unpacked in "
        "C:\\supervisor, no network needed:",
        "Trên máy Windows có Python 3.11 và bản phát hành Supervisor giải nén ở C:\\supervisor, "
        "không cần mạng:",
    ),
    "how_offline_hint": (
        "Exit code 0 and RESULT: OK mean every hash, link and signature matched. Add "
        "--pubkey <bank key>.pem to pin the signing key.",
        "Mã thoát 0 và RESULT: OK nghĩa là mọi mã băm, liên kết và chữ ký đều khớp. Thêm "
        "--pubkey <khóa ngân hàng>.pem để cố định khóa ký.",
    ),
    "kind_audit": ("audit pack", "gói kiểm toán"),
    "kind_chain": ("chain export", "bản xuất chuỗi"),
    "no_packs": ("Nothing exported yet.", "Chưa có bản xuất nào."),
    # ---- WP12 onboard
    "onboard_title": ("Onboard an agent", "Tiếp nhận một tác tử"),
    "ob_purpose_lead": (
        "Bring an agent under supervision in 6 steps. A person approves every step.",
        "Đưa một tác tử vào giám sát qua 6 bước. Mỗi bước đều do con người duyệt.",
    ),
    "ob_purpose_rest": (
        "Supervisor reads the agent's code and activity, suggests rules and opens a pull request. People approve every step.",
        "Supervisor đọc mã nguồn và hoạt động của tác tử, đề xuất quy tắc và mở pull request. Con người duyệt từng bước.",
    ),
    "ob_why": (
        "Nothing is merged automatically. The onboarding agent is itself watched by the AI guardian.",
        "Không có gì được hợp nhất tự động. Bản thân tác tử tiếp nhận cũng chịu giám sát của bộ bảo vệ AI.",
    ),
    "ws_discover": (
        "Find the code, prompts, tools, data tables and activity logs.",
        "Tìm mã nguồn, prompt, công cụ, bảng dữ liệu và nhật ký hoạt động.",
    ),
    "ws_understand": (
        "Risk profile with evidence from the code (file and line). Decision 33 class.",
        "Hồ sơ rủi ro có bằng chứng từ mã nguồn (tệp và dòng). Phân loại theo Quyết định 33.",
    ),
    "ws_plan": (
        "Choose checks from the catalogue. Set thresholds. Estimate cost.",
        "Chọn kiểm tra từ danh mục. Đặt ngưỡng. Ước tính chi phí.",
    ),
    "ws_instrument": (
        "Add the rules, activity logging and dashboard, then open a pull request.",
        "Thêm quy tắc, ghi nhật ký hoạt động và bảng theo dõi, rồi mở pull request.",
    ),
    "ws_launch": (
        "Attack tests in a safe test area. Set the baseline. Decide go or no-go.",
        "Chạy bộ tấn công thử trong môi trường thử nghiệm. Đặt mốc chuẩn. Quyết định đi hay dừng.",
    ),
    "ws_operate": ("Hand over to Watch.", "Bàn giao cho Giám sát."),
    "start": ("Start", "Bắt đầu"),
    "repo_path": (
        "Agent folder (inside a git repo; relative to the Supervisor folder)",
        "Thư mục tác tử (trong repo git; tính từ thư mục Supervisor)",
    ),
    "discover_btn": ("Start scan", "Bắt đầu quét"),
    "start_hint": (
        "View only. Passwords and keys are removed before the AI reads the code.",
        "Chỉ xem. Mật khẩu và khóa được xóa trước khi AI đọc mã nguồn.",
    ),
    "onboard_off": (
        "Starting onboarding from this page is not turned on.",
        "Chưa bật việc chạy tiếp nhận từ trang này.",
    ),
    "ob_running": ("running: {agent}", "đang chạy: {agent}"),
    "ob_done": ("done: {agent}", "đã xong: {agent}"),
    "ob_failed": ("failed: {agent}", "không thành công: {agent}"),
    "ob_started": ("started by {who} at {time}", "{who} bắt đầu lúc {time}"),
    "last_run": ("Last run · {agent}", "Lần chạy gần nhất · {agent}"),
    "ob_profile": ("Profile", "Hồ sơ"),
    "ob_plan": ("Plan", "Kế hoạch"),
    "ob_launch": ("Launch report", "Báo cáo triển khai"),
    "high_risk": ("high-risk", "rủi ro cao"),
    "not_high_risk": ("not high-risk", "không rủi ro cao"),
    "human_gate": ("Human approval step in code", "Bước con người duyệt trong mã"),
    "yes": ("yes", "có"),
    "no": ("no", "không"),
    "proposed_risk": ("Suggested risk level", "Mức rủi ro gợi ý"),
    "no_human_gate_hint": (
        "Pausing an agent is not the same as approving its actions first. The agent needs its own approval step.",
        "Tạm dừng tác tử không thay cho việc phê duyệt hành động trước khi thực hiện. Tác tử cần có bước phê duyệt riêng.",
    ),
    "caps_selected": ("{on} of {n} capabilities on", "{on}/{n} năng lực được bật"),
    "rules_proposed": (
        "{n} rules suggested. {s} can block or pause and need two approvers.",
        "Đề xuất {n} quy tắc. {s} quy tắc có thể chặn hoặc tạm dừng và cần hai người phê duyệt.",
    ),
    "judges_planned": ("Judges", "Giám khảo"),
    "caught_n": ("{c} of {e} red-team attacks caught", "bắt được {c}/{e} đợt tấn công thử"),
    "false_alarms": (
        "false alarms {p}% ({f} of {b} benign)",
        "báo động nhầm {p}% ({f} trên {b} tình huống lành)",
    ),
    "branch": ("branch", "nhánh"),
    "launch_mock_note": (
        "profile written with the mock model; rules and red-team results are real",
        "hồ sơ viết bằng mô hình giả lập; quy tắc và kết quả tấn công thử là thật",
    ),
    "not_yet": ("Not available yet.", "Chưa có."),
    "artefacts": ("Output files", "Tệp kết quả"),
    "no_runs": ("No onboarding yet.", "Chưa có lần tiếp nhận nào."),
    # ---- WP12 health
    "health_lead": ("Is Supervisor itself healthy?", "Bản thân Supervisor có ổn không?"),
    "health_rest": (
        "The same checks as the preflight command, on screen.",
        "Các kiểm tra giống lệnh preflight, hiển thị trên màn hình.",
    ),
    "health_why": (
        "A supervisor that is misconfigured gives false comfort. Fix every FAIL before a demo "
        "or a go-live.",
        "Một hệ thống giám sát cấu hình sai sẽ tạo cảm giác an toàn giả. Hãy sửa mọi FAIL "
        "trước khi demo hoặc vận hành thật.",
    ),
    "check": ("Check", "Kiểm tra"),
    "detail": ("Detail", "Chi tiết"),
    "fix": ("How to fix", "Cách sửa"),
    "h_mode": ("Mode", "Chế độ"),
    "h_mode_sched_on": ("one process · scheduler on", "một tiến trình · bộ lập lịch bật"),
    "h_mode_sched_off": ("one process · scheduler off", "một tiến trình · bộ lập lịch tắt"),
    "h_identity": ("Identity", "Danh tính"),
    "h_identity_dev": (
        "Not a real identity. The Databricks App uses workspace SSO.",
        "Không phải danh tính thật. Databricks App dùng SSO của workspace.",
    ),
    "h_identity_sso": (
        "People sign in with workspace SSO. Each action records how they signed in.",
        "Người dùng đăng nhập bằng SSO của workspace. Mỗi thao tác ghi lại cách đăng nhập.",
    ),
    "h_judge": ("Judge model", "Mô hình giám khảo"),
    "h_judge_mock": (
        "No judge model configured: mock judges, labelled mock. Set JUDGE_T1_MODEL to a "
        "loopback model or the bank endpoint.",
        "Chưa cấu hình mô hình giám khảo: dùng giám khảo giả lập, có nhãn mock. Đặt "
        "JUDGE_T1_MODEL tới mô hình nội bộ hoặc endpoint của ngân hàng.",
    ),
    "h_key": ("Signing key", "Khóa ký"),
    "h_key_dev": (
        "Test key on this machine. The bank has not yet decided where to keep its key (HSM / KMS).",
        "Khóa thử nghiệm trên máy này. Ngân hàng chưa quyết định nơi lưu giữ khóa (HSM / KMS).",
    ),
    "h_key_managed": ("Key managed by the bank.", "Khóa do ngân hàng quản lý."),
    "h_anchor": ("Anchor target", "Nơi neo"),
    "h_no_anchor": (
        "No anchor yet. The scheduler creates it.",
        "Chưa có lần neo. Bộ lập lịch sẽ tạo.",
    ),
    "h_databricks": ("Databricks", "Databricks"),
    "h_databricks_in_use": (
        "Live workspace checks create a probe table: run python -m supervisor.preflight.",
        "Kiểm tra workspace trực tiếp tạo bảng thử: chạy python -m supervisor.preflight.",
    ),
    "h_databricks_off": (
        "Not connected on this machine (no OAuth profile; local SQLite storage).",
        "Chưa kết nối trên máy này (không có hồ sơ OAuth; dùng lưu trữ SQLite cục bộ).",
    ),
    "h_onboard": ("Onboard from the console", "Tiếp nhận từ bảng điều khiển"),
    "h_onboard_detail": ("Form to start onboarding.", "Biểu mẫu để bắt đầu tiếp nhận."),
    "preflight_checks": ("Readiness checks", "Kiểm tra mức sẵn sàng"),
    "n_failed": ("{n} failed", "{n} lỗi"),
    "all_pass": ("no failure", "không có lỗi"),
    "health_note": (
        "Secret values are never shown. The command line gives the same list: "
        "python -m supervisor.cli preflight.",
        "Không bao giờ hiển thị giá trị bí mật. Dòng lệnh cho cùng danh sách: "
        "python -m supervisor.cli preflight.",
    ),
    "health_note_dbx": (
        "Databricks checks (sign-in, warehouse, schema, serving endpoint, Volume) run only from the command line, because they write test data.",
        "Các kiểm tra Databricks (đăng nhập, warehouse, schema, endpoint, Volume) chỉ chạy từ dòng lệnh vì chúng ghi dữ liệu thử.",
    ),
    # ---- WP12 inbox, metrics
    "inbox_purpose": (
        "Notices from the case workflow: a new case, a sign-off needed, a case closed.",
        "Thông báo từ quy trình vụ việc: vụ việc mới, cần phê duyệt, vụ việc đã đóng.",
    ),
    "inbox_why": (
        "The bank's ITSM and pager get the same notices when those links are switched on.",
        "ITSM và hệ thống nhắn tin của ngân hàng nhận cùng thông báo khi bật kết nối.",
    ),
    # ---- WP1b-B monitor status on the Metrics page
    "monitor_status": ("Monitor status", "Trạng thái bộ giám sát"),
    "monitor_status_purpose": (
        "What each monitor did for each agent. 'not applicable' names the missing setup. 'no data' means setup is done but nothing has been measured yet.",
        "Mỗi bộ giám sát đã làm gì với từng tác tử. 'không áp dụng' nêu phần thiết lập còn thiếu. 'chưa có dữ liệu' nghĩa là đã thiết lập nhưng chưa đo được gì.",
    ),
    "no_monitor_status": (
        "No monitor has reported yet.",
        "Chưa có bộ giám sát nào báo cáo.",
    ),
    "ms_ok": ("ok", "bình thường"),
    "ms_not_applicable": ("not applicable", "không áp dụng"),
    "ms_no_data": ("no data", "chưa có dữ liệu"),
    # ---- WP21 alerts panel on the Metrics page
    "alerts": ("Alerts", "Cảnh báo"),
    "alerts_purpose": (
        "Alerts come from rules. Acknowledge an alert to confirm you have seen it. Your action is logged.",
        "Cảnh báo do quy tắc tạo ra. Hãy xác nhận để cho biết bạn đã xem. Thao tác của bạn được ghi lại.",
    ),
    "alerts_open": ("open", "đang mở"),
    "alerts_ack": ("acknowledged", "đã xác nhận"),
    "alert_ack_btn": ("Acknowledge", "Xác nhận"),
    "alert_rule": ("Rule", "Quy tắc"),
    "alert_window": ("Time window", "Khoảng thời gian"),
    "alert_repeats": ("Repeats", "Lặp lại"),
    "alert_chain": ("Evidence record", "Bản ghi bằng chứng"),
    "no_alerts": ("No alerts.", "Không có cảnh báo."),
    "day": ("Day", "Ngày"),
    "all_rows": ("All items ({n})", "Tất cả mục ({n})"),
    "flow_open": ("open", "mở"),
    "flow_triaged": ("triaged", "đã phân loại"),
    "flow_contained": ("contained", "đã ngăn chặn"),
    "flow_closed": ("closed", "đã đóng"),
    "next_triaged": ("assess and prioritise", "đánh giá và xếp ưu tiên"),
    "next_contained": ("contain the issue", "ngăn chặn sự cố"),
    "next_closed": ("approve and close", "phê duyệt và đóng"),
    "itsm_ph": ("e.g. INC0012345", "ví dụ INC0012345"),
    "demo_note": (
        "Demo data: the agents' replies are scripted and the customers are synthetic. The "
        "gate decisions, the pause and the chain are real.",
        "Dữ liệu demo: câu trả lời của tác tử theo kịch bản và khách hàng là giả lập. Quyết "
        "định của cổng, việc tạm dừng và chuỗi bằng chứng là thật.",
    ),
    # ---- WP14 compliance advisor tab
    "nav_compliance": ("Compliance", "Tuân thủ"),
    "cp_title": ("Compliance advisor", "Cố vấn tuân thủ"),
    "cp_purpose": (
        "See which legal duties apply to each agent and which Supervisor controls cover them.",
        "Xem nghĩa vụ pháp lý nào áp dụng cho từng tác tử và biện pháp nào của Supervisor đáp ứng.",
    ),
    "cp_why": (
        "Each status names the control and the fact behind it. If a fact is unknown, we ask a question. We never guess.",
        "Mỗi trạng thái nêu rõ biện pháp kiểm soát và dữ kiện làm căn cứ. Nếu chưa biết dữ kiện, hệ thống đặt câu hỏi, không phỏng đoán.",
    ),
    "cp_advisory": ("Advisory only", "Chỉ mang tính tham khảo"),
    "cp_disclaimer": (
        "Not legal advice. Bank counsel must confirm.",
        "Không phải tư vấn pháp lý. Cần pháp chế ngân hàng xác nhận.",
    ),
    "cp_off": (
        "The Compliance tab is switched off. To turn it on, set CONSOLE_COMPLIANCE_ENABLED=1 and restart the console. Or use the command line:",
        "Thẻ Tuân thủ đang tắt. Để bật, đặt CONSOLE_COMPLIANCE_ENABLED=1 rồi khởi động lại bảng điều khiển. Hoặc dùng dòng lệnh:",
    ),
    "cp_no_agents": ("No compliance matrix yet.", "Chưa có ma trận tuân thủ nào."),
    "cp_source_demo": ("demo agent", "tác tử demo"),
    "cp_source_onboard": ("registered", "đã đăng ký"),
    "cp_applies_yes": ("Applicable", "Áp dụng"),
    "cp_needs_answer": ("Need an answer", "Cần trả lời"),
    "cp_questions": ("Open questions", "Câu hỏi còn mở"),
    "cp_threshold_gaps": ("Limits over the legal cap", "Hạn mức vượt trần luật định"),
    "cp_d33": ("Decision 33 (suggestion)", "Quyết định 33 (gợi ý)"),
    "cp_open": ("Open matrix", "Mở ma trận"),
    "cp_back": ("All agents", "Tất cả tác tử"),
    "cp_counts": (
        "Rows that apply ({n}), by status",
        "Dòng áp dụng ({n}), theo trạng thái",
    ),
    "cp_rows_no": ("{k} more duties do not apply", "{k} nghĩa vụ khác không áp dụng"),
    "cp_rows_split": (
        "{yes} apply and {na} need an answer: {n} duties in the table below",
        "{yes} áp dụng và {na} cần trả lời: {n} nghĩa vụ trong bảng bên dưới",
    ),
    "cp_filters": ("Filters", "Bộ lọc"),
    "cp_instrument": ("Legal document", "Văn bản pháp lý"),
    "cp_duty": ("Duty", "Nghĩa vụ"),
    "cp_applies": ("Applies", "Áp dụng"),
    "cp_any": ("any", "tất cả"),
    "cp_apply_filter": ("Apply filter", "Lọc"),
    "cp_showing": ("Showing {n} of {m} rows", "Hiển thị {n} trên {m} dòng"),
    "cp_col_obligation": ("Obligation", "Nghĩa vụ"),
    "cp_col_article": ("Article", "Điều"),
    "cp_col_reason": ("Reason", "Lý do"),
    "cp_thresholds": ("Threshold findings", "Kết quả kiểm tra hạn mức"),
    "cp_col_limit": ("Limit (VND)", "Hạn mức (VND)"),
    "cp_col_cap": ("Cap (VND)", "Trần (VND)"),
    "cp_col_verdict": ("Result", "Kết quả"),
    "cp_none": ("none", "không có"),
    "cp_questions_list": ("Open questions", "Câu hỏi còn mở"),
    "cp_decides": ("{n} duties wait on this answer", "{n} nghĩa vụ đang chờ câu trả lời này"),
    "cp_ob_title": ("Obligation", "Nghĩa vụ"),
    "cp_text_vi": ("Text (Vietnamese)", "Nội dung (tiếng Việt)"),
    "cp_summary_en": ("Summary (English)", "Tóm tắt (tiếng Anh)"),
    "cp_no_text_vi": (
        "No Vietnamese text for this duty yet.",
        "Chưa có văn bản tiếng Việt cho nghĩa vụ này.",
    ),
    "cp_instrument_line": ("Legal document", "Văn bản pháp lý"),
    "cp_sources": ("Sources", "Nguồn"),
    "cp_controls": ("Controls that cover it", "Biện pháp kiểm soát"),
    "cp_coverage": ("coverage", "độ bao phủ"),
    "cp_this_product": ("This product", "Sản phẩm này"),
    "cp_status_reason": ("Why this status", "Vì sao có trạng thái này"),
    "cp_evidence_needed": ("Evidence needed", "Bằng chứng cần có"),
    # ---- WP15 integration advice
    "nav_integration": (
        "Integration",
        "Tích hợp",
    ),
    "integration_title": (
        "Integration advice",
        "Tư vấn tích hợp",
    ),
    "int_purpose_lead": (
        "Readiness reports for agents you plan to put under Watch.",
        "Báo cáo mức sẵn sàng của các tác tử dự kiến đưa vào giám sát.",
    ),
    "int_purpose_rest": (
        "Each report lists what the advisor found in the code, what Supervisor needs, "
        "a readiness score and patches.",
        "Mỗi báo cáo nêu điều tìm thấy trong mã, điều Supervisor cần, điểm sẵn sàng và các bản vá.",
    ),
    "int_why": (
        "Read-only. The patches are never applied by the console: "
        "the owning team reviews and applies them.",
        "Chỉ đọc. Bảng điều khiển không bao giờ áp dụng bản vá: nhóm sở hữu xem xét và áp dụng.",
    ),
    "int_none": (
        "No integration report yet. Run python -m supervisor.advisory.integration "
        "or turn on ONBOARD_ADVISOR_ENABLED.",
        "Chưa có báo cáo tích hợp. Chạy python -m supervisor.advisory.integration "
        "hoặc bật ONBOARD_ADVISOR_ENABLED.",
    ),
    "int_report": (
        "Report",
        "Báo cáo",
    ),
    "int_agent": (
        "Agent",
        "Tác tử",
    ),
    "int_framework": (
        "Framework",
        "Khung",
    ),
    "int_readiness": (
        "Readiness",
        "Mức sẵn sàng",
    ),
    "int_patches": (
        "Patches",
        "Bản vá",
    ),
    "int_unreadable": (
        "Report file cannot be read",
        "Không đọc được tệp báo cáo",
    ),
    "int_back": (
        "Back to the list",
        "Về danh sách",
    ),
    "int_never_applied": (
        "Patches are advice. Nothing was applied to the agent code.",
        "Bản vá chỉ là tư vấn. Chưa áp dụng gì vào mã của tác tử.",
    ),
    "int_area": (
        "Area",
        "Hạng mục",
    ),
    "int_points": (
        "Points",
        "Điểm",
    ),
    "int_reason": (
        "Reason",
        "Lý do",
    ),
    "int_found": (
        "Found in the code",
        "Tìm thấy trong mã",
    ),
    "int_llm_calls": (
        "LLM calls",
        "Lệnh gọi LLM",
    ),
    "int_tracing": (
        "Tracing",
        "Truy vết",
    ),
    "int_tools": (
        "Tools",
        "Công cụ",
    ),
    "int_gated": (
        "gated",
        "đã có cổng",
    ),
    "int_data_access": (
        "Data access",
        "Truy cập dữ liệu",
    ),
    "int_pii": (
        "PII fields",
        "Trường PII",
    ),
    "int_needed": (
        "What Supervisor needs",
        "Supervisor cần gì",
    ),
    "int_semconv": (
        "Semantic attributes",
        "Thuộc tính ngữ nghĩa",
    ),
    "int_gate_sites": (
        "Gate call sites",
        "Vị trí đặt cổng",
    ),
    "int_mcp_proxy": (
        "MCP proxy",
        "Proxy MCP",
    ),
    "int_catalogue": (
        "Catalogue capabilities",
        "Năng lực trong danh mục",
    ),
    "int_settings": (
        "Settings",
        "Cài đặt",
    ),
    "int_test_plan": (
        "Test plan dimensions",
        "Hạng mục kế hoạch kiểm thử",
    ),
    "int_policy": (
        "Policy scaffold",
        "Khung chính sách",
    ),
    "int_patch_missing": (
        "The patch file is not in the report folder.",
        "Tệp bản vá không có trong thư mục báo cáo.",
    ),
    "int_no_patches": (
        "No patch in this report.",
        "Báo cáo này không có bản vá.",
    ),
    "int_narrative": (
        "Narrative",
        "Diễn giải",
    ),
    # ---- WP22 tools (analytics and least privilege)
    "tl_window": ("Period", "Khoảng thời gian"),
    "tl_tool": ("Tool", "Công cụ"),
    "tl_risk": ("Risk", "Rủi ro"),
    "tl_status": ("Status", "Trạng thái"),
    "tl_calls": ("Calls", "Số lần gọi"),
    "tl_allow": ("Allow", "Cho phép"),
    "tl_block": ("Block", "Chặn"),
    "tl_pause": ("Pause", "Tạm dừng"),
    "tl_err": ("Err", "Lỗi"),
    "tl_p50": ("Typical time (µs)", "Thời gian điển hình (µs)"),
    "tl_p95": ("Slow calls, p95 (µs, worst day)", "Lệnh gọi chậm, p95 (µs, ngày tệ nhất)"),
    "tl_users": ("Peak users per day", "Số người dùng tối đa mỗi ngày"),
    "tl_last": ("Last seen", "Lần cuối"),
    "tl_declared_from": ("declared from", "khai báo từ"),
    "tl_st_used": ("used", "đã dùng"),
    "tl_st_unused": ("unused", "chưa dùng"),
    "tl_st_undeclared": ("not declared", "chưa khai báo"),
    "tl_st_exception": ("exception", "ngoại lệ"),
    "tl_conf_ok": ("data ok", "dữ liệu đủ"),
    "tl_conf_low": ("low history", "ít dữ liệu"),
    "tl_conf_no_data": ("no data", "chưa có dữ liệu"),
    "tl_suggest": ("Suggested minimum access", "Đề xuất quyền truy cập tối thiểu"),
    "tl_remove": (
        "Remove (unused tools, riskiest first)",
        "Gỡ bỏ (công cụ chưa dùng, rủi ro nhất trước)",
    ),
    "tl_none": ("No unused tools in this period.", "Không có công cụ chưa dùng trong kỳ này."),
    "tl_undeclared": ("Called but not declared", "Đã gọi nhưng chưa khai báo"),
    "tl_warning": ("Warning", "Cảnh báo"),
    "tl_not_applied": (
        "Suggestion only. Nothing has changed. To apply it, follow the policy change process (docs/tool-analytics.md).",
        "Chỉ là đề xuất, chưa có gì thay đổi. Để áp dụng, làm theo quy trình thay đổi chính sách (docs/tool-analytics.md).",
    ),
    "tl_download": ("Download changes", "Tải bản thay đổi"),
    "tl_download_owner": (
        "Only the agent owner can download the changes.",
        "Chỉ chủ sở hữu tác tử mới được tải bản thay đổi.",
    ),
    "tl_unknown_agent": (
        "This agent is not in the policy yet, so there are no tools to compare. Add it to the policy or start onboarding.",
        "Tác tử này chưa có trong chính sách nên chưa có công cụ để so sánh. Hãy thêm vào chính sách hoặc bắt đầu đưa vào vận hành.",
    ),
    "tl_nodata": (
        "No usage data yet. Run:",
        "Chưa có dữ liệu sử dụng. Hãy chạy:",
    ),
    # ---- WP24 inventory
    "nav_inventory": ("Inventory", "Kiểm kê"),
    "inv_purpose": (
        "What each agent runs on: models, tools, MCP servers, datasets and hosting, with evidence. Risk passes up from tools and models to the agent.",
        "Mỗi tác tử chạy trên gì: mô hình, công cụ, máy chủ MCP, dữ liệu và nơi lưu trữ, kèm bằng chứng. Mức rủi ro đi lên từ công cụ và mô hình tới tác tử.",
    ),
    "inv_why": (
        "Unmanaged items run in the workspace but are not registered with Supervisor (shadow AI). Each opens one low-severity case. Only people set the Decision 33 classification.",
        "Mục chưa quản lý chạy trong workspace nhưng chưa đăng ký với Supervisor (AI ngầm). Mỗi mục mở một vụ việc mức thấp. Chỉ con người mới đặt phân loại theo Quyết định 33.",
    ),
    "inv_agent": ("Agent", "Tác tử"),
    "inv_tree": ("Dependencies (tree view)", "Thành phần phụ thuộc (dạng cây)"),
    "inv_nodes": ("Nodes", "Nút"),
    "inv_kind": ("Kind", "Loại"),
    "inv_name": ("Name", "Tên"),
    "inv_own": ("Own risk", "Rủi ro riêng"),
    "inv_eff": ("Effective risk", "Rủi ro hiệu lực"),
    "inv_evidence": ("Evidence", "Bằng chứng"),
    "inv_unmanaged": ("Unmanaged items", "Mục chưa quản lý"),
    "inv_no_unmanaged": (
        "No unmanaged item. Every App and endpoint seen in the last refresh is registered "
        "or allow-listed.",
        "Không có mục chưa quản lý. Mọi App và endpoint thấy ở lần làm mới gần nhất đã đăng ký "
        "hoặc nằm trong danh sách cho phép.",
    ),
    "inv_no_agents": (
        "The inventory is empty. Run:",
        "Kiểm kê đang trống. Hãy chạy:",
    ),
    "inv_case": ("Case", "Hồ sơ"),
    # ---- WP17 assurance
    "nav_assurance": ("Assurance", "Đảm bảo chất lượng"),
    "as_purpose": (
        "Results of the assurance eval packs: accuracy, hallucination, bias, dependency, "
        "security and robustness tests run on agents, traces and the judge.",
        "Kết quả các gói kiểm thử đảm bảo: độ chính xác, ảo giác, thiên vị, phụ thuộc, "
        "bảo mật và độ bền, chạy trên tác tử, dấu vết và giám khảo AI.",
    ),
    "as_why": (
        "Thresholds are examples until the bank sets its own. A skipped test never counts as a pass.",
        "Ngưỡng chỉ là ví dụ cho đến khi ngân hàng đặt ngưỡng riêng. Kiểm thử bị bỏ qua không bao giờ được tính là đạt.",
    ),
    "as_run": ("Run", "Lần chạy"),
    "as_target": ("Target", "Đối tượng"),
    "as_counts": ("Results", "Kết quả"),
    "as_kind": ("Label", "Nhãn"),
    "as_selector": ("selector", "bộ chọn"),
    "as_no_runs": ("No tests run yet.", "Chưa chạy kiểm thử nào."),
    "as_all_runs": ("All runs", "Tất cả lần chạy"),
    "as_mock_note": (
        "MOCK: at least one result comes from a mock model or target. The numbers prove the "
        "harness, not a real model.",
        "MÔ PHỎNG: ít nhất một kết quả đến từ mô hình hoặc đối tượng giả lập. Số liệu chỉ "
        "chứng minh bộ kiểm thử, không phải mô hình thật.",
    ),
    "as_pack": ("Test set", "Bộ kiểm thử"),
    "as_dimension": ("Test area", "Lĩnh vực kiểm thử"),
    "as_metrics": ("Results against thresholds", "Kết quả so với ngưỡng"),
    "as_data": ("Data", "Dữ liệu"),
    "as_reasons": ("Reasons", "Lý do"),
    "as_gate": ("launch gate", "cổng ra mắt"),
    "as_judge_gate": ("AI judge check", "kiểm tra bằng giám khảo AI"),
    "as_no_chain": ("not in the evidence chain", "chưa ghi vào chuỗi bằng chứng"),
    "as_no_results": ("No results in this run.", "Lần chạy này chưa có kết quả."),
    "as_illustrative": (
        "Thresholds are examples until the bank sets its own.",
        "Ngưỡng chỉ là ví dụ cho đến khi ngân hàng đặt ngưỡng riêng.",
    ),
    # --- WP-UX1: shell, sidebar, list and drawer components
    "nav_g_watch": ("Watch", "Giám sát"),
    "nav_g_act": ("Act", "Xử lý"),
    "nav_g_prove": ("Prove", "Chứng minh"),
    "nav_g_onboard": ("Onboard", "Tiếp nhận"),
    "nav_g_analytics": ("Analytics", "Phân tích"),
    "nav_g_settings": ("Settings", "Cài đặt"),
    "nav_decisions": ("Gate decisions", "Quyết định của cổng"),
    "nav_traces": ("Traces", "Dấu vết"),
    "nav_alerts": ("Alerts", "Cảnh báo"),
    "nav_policies": ("Policies", "Chính sách"),
    "nav_credentials": ("Credentials", "Thông tin xác thực"),
    "nav_users": ("Users and roles", "Người dùng và vai trò"),
    "nav_audit": ("Audit log", "Nhật ký kiểm toán"),
    "nav_integrations": ("Integrations", "Tích hợp"),
    "nav_collapse": ("Collapse or open the sidebar", "Thu gọn hoặc mở thanh bên"),
    "nav_menu": ("Open the menu", "Mở menu"),
    "skip_to_main": ("Skip to the main content", "Chuyển đến nội dung chính"),
    "search_label": ("Search the console", "Tìm trong bảng điều khiển"),
    "search_placeholder": ("Search agents, cases, traces", "Tìm tác tử, vụ việc, dấu vết"),
    "search_title": ("Search results", "Kết quả tìm kiếm"),
    "search_min": ("Type at least 2 characters.", "Nhập ít nhất 2 ký tự."),
    "search_none": ("No match for {q}.", "Không có kết quả cho {q}."),
    "search_agents": ("Search agents", "Tìm tác tử"),
    "breadcrumb": ("You are here", "Vị trí hiện tại"),
    "filter_quick": ("Quick filter", "Lọc nhanh"),
    "apply": ("Apply", "Áp dụng"),
    "reset": ("Reset", "Đặt lại"),
    "tabs_label": ("Sections", "Các mục"),
    "pager_label": ("Pages", "Chuyển trang"),
    "pager_showing": ("Showing {a}-{b} of {n}", "Hiển thị {a}-{b} trên {n}"),
    "pager_prev": ("Previous", "Trước"),
    "pager_next": ("Next", "Tiếp"),
    "pager_page": ("page {p} of {n}", "trang {p} trên {n}"),
    "drawer_prev": ("Previous row", "Dòng trước"),
    "drawer_next": ("Next row", "Dòng sau"),
    "drawer_close": ("Close the panel", "Đóng bảng bên"),
    "copy_json": ("Copy JSON", "Sao chép JSON"),
    "dtab_overview": ("Overview", "Tổng quan"),
    "dtab_policy": ("Policy", "Chính sách"),
    "dtab_cases": ("Cases", "Vụ việc"),
    "state_RUNNING": ("Running", "Đang chạy"),
    "state_SHADOW": ("Shadow", "Chế độ bóng"),
    "state_PAUSED": ("Paused", "Tạm dừng"),
    "state_QUARANTINED": ("Quarantined", "Cách ly"),
    "agent_controls_hint": (
        "To pause, resume or quarantine an agent, open its agent page.",
        "Để tạm dừng, cho chạy lại hoặc cách ly tác tử, hãy mở trang của tác tử đó.",
    ),
    "no_agents_filtered": (
        "No agent matches these filters.",
        "Không có tác tử nào khớp bộ lọc này.",
    ),
    "no_rules": (
        "No rules apply to this agent yet.",
        "Chưa có quy tắc nào áp dụng cho tác tử này.",
    ),
    "no_rules_line": (
        "No rule in force names this agent.",
        "Chưa có quy tắc nào đang áp dụng cho tác tử này.",
    ),
    "no_cases_agent": (
        "This agent has no open case.",
        "Tác tử này không có vụ việc đang mở.",
    ),
    "name": ("Name", "Tên"),
    "tools": ("Tools", "Công cụ"),
    "action": ("Action", "Hành động"),
    "fail_mode": ("Fail mode", "Chế độ lỗi"),
    "act_allow": ("allow", "cho phép"),
    "act_log": ("log", "ghi nhận"),
    "act_alert": ("alert", "cảnh báo"),
    "act_block": ("block", "chặn"),
    "act_pause": ("pause", "tạm dừng"),
    "soon_pill": ("Coming soon", "Sắp có"),
    "soon_line": ("This page is coming soon.", "Trang này sắp ra mắt."),
    "soon_why": (
        "The menu item is here already. Nothing is lost: your data is still being recorded.",
        "Mục menu đã có sẵn. Không mất dữ liệu: dữ liệu vẫn được ghi lại.",
    ),
    "see_all": ("See all", "Xem tất cả"),
    "span_tree": ("Span tree", "Cây span"),
    "no_decisions_line": (
        "Decisions appear here when an agent calls a tool.",
        "Quyết định sẽ hiện ở đây khi tác tử gọi công cụ.",
    ),
    # --- WP-UX3: new pages
    "nav_playground": ("Playground", "Chạy thử"),
    "rule_col": ("Rule", "Quy tắc"),
    "actor": ("Done by", "Người thực hiện"),
    "actor_kind": ("Type of user", "Loại người dùng"),
    "agent_scope": ("Agent scope", "Phạm vi tác tử"),
    "amount_vnd": ("Amount (VND)", "Số tiền (VND)"),
    "approvals": ("Approvals", "Phê duyệt"),
    "arg_keys": ("Input fields", "Trường đầu vào"),
    "args_hash": ("Input hash", "Mã băm đầu vào"),
    "args_masked": ("Inputs (data hidden)", "Đầu vào (đã che dữ liệu)"),
    "result_masked": ("Result (masked)", "Kết quả (đã che)"),
    "advisory": ("advice only", "chỉ tư vấn"),
    "caller_agent": ("Caller agent", "Tác tử gọi"),
    "capture_level": ("Logging level", "Mức ghi nhận"),
    "chain_seq": ("Chain number", "Số thứ tự trong chuỗi"),
    "description": ("Description", "Mô tả"),
    "effective_from": ("Effective from", "Hiệu lực từ"),
    "entry_hash": ("Entry hash", "Mã băm của mục"),
    "payload_hash": ("Content hash", "Mã băm nội dung"),
    "git_sha": ("Git commit", "Mã commit Git"),
    "latency": ("Latency", "Độ trễ"),
    "latency_us": ("Latency (us)", "Độ trễ (us)"),
    "off": ("off", "tắt"),
    "on": ("on", "bật"),
    "permission": ("Permission", "Quyền"),
    "read_only": ("read-only", "chỉ đọc"),
    "regulation_refs": ("Regulation references", "Tham chiếu quy định"),
    "request": ("Request", "Yêu cầu"),
    "request_id": ("Request id", "Mã yêu cầu"),
    "risk_class": ("Risk class", "Nhóm rủi ro"),
    "role": ("Role", "Vai trò"),
    "scan_capped": (
        "Only the newest 20,000 entries are counted. Older ones are left out.",
        "Chỉ tính 20.000 mục mới nhất. Các mục cũ hơn không được tính.",
    ),
    "span_id": ("Span id", "Mã span"),
    "target": ("Target", "Đối tượng"),
    "this_row": ("this decision", "quyết định này"),
    "time_range": ("Time range", "Khoảng thời gian"),
    "range_1h": ("Last hour", "1 giờ qua"),
    "range_24h": ("Last 24 hours", "24 giờ qua"),
    "range_7d": ("Last 7 days", "7 ngày qua"),
    "range_30d": ("Last 30 days", "30 ngày qua"),
    "tool": ("Tool", "Công cụ"),
    "trace_id": ("Trace id", "Mã dấu vết"),
    "user": ("User", "Người dùng"),
    "version": ("Version", "Phiên bản"),
    "dtab_details": ("Details", "Chi tiết"),
    "dtab_rules": ("Rules", "Quy tắc"),
    "dtab_evidence": ("Evidence", "Bằng chứng"),
    "dtab_versions": ("Versions", "Phiên bản"),
    "open_trace": ("Open trace", "Mở dấu vết"),
    "outcome_attempted": ("tried", "đã thử"),
    "outcome_ok": ("succeeded", "thành công"),
    "outcome_denied": ("denied", "bị từ chối"),
    "outcome_error": ("error", "lỗi"),
    "decisions_purpose": (
        "Every allow, block, pause and alert the gate decided, newest first.",
        "Mọi quyết định cho phép, chặn, tạm dừng và cảnh báo của cổng, mới nhất trước.",
    ),
    "decisions_why": (
        "Open a decision to see the rules that matched, the evidence and the case it opened. Call details are never shown, only a protected code.",
        "Mở một quyết định để xem quy tắc đã khớp, bằng chứng và vụ việc đã mở. Chi tiết lệnh gọi không bao giờ hiển thị, chỉ có mã bảo vệ.",
    ),
    "no_rule_hits": ("No rule matched", "Không có quy tắc nào khớp"),
    "no_rule_hits_line": (
        "No rule applied to this call, so it was allowed by default.",
        "Không quy tắc nào áp dụng cho lệnh gọi này nên được cho phép mặc định.",
    ),
    "no_chain_entry": ("No evidence found", "Không tìm thấy bằng chứng"),
    "no_chain_entry_line": (
        "This decision has no evidence entry yet, or evidence is not being saved permanently.",
        "Quyết định này chưa có bằng chứng được ghi, hoặc bằng chứng chưa được lưu lâu dài.",
    ),
    "traces_purpose": (
        "One row per trace: the agent, when it started, how many steps and what the checks said.",
        "Mỗi dòng là một dấu vết: tác tử, thời điểm bắt đầu, số bước và kết luận của các kiểm tra.",
    ),
    "traces_why": (
        "Open a trace to walk its span tree. Only masked text is shown, and the capture "
        "level of each event decides how much.",
        "Mở một dấu vết để xem cây span. Chỉ hiển thị văn bản đã che; mức ghi nhận của "
        "từng sự kiện quyết định mức hiển thị.",
    ),
    "started": ("Started", "Bắt đầu"),
    "spans": ("Spans", "Span"),
    "verdict_labels": ("Verdicts", "Kết luận"),
    "judge_n": ("judge {n}", "giám khảo {n}"),
    "trace_ok": ("ok", "bình thường"),
    "trace_alert": ("alert", "cảnh báo"),
    "trace_blocked": ("blocked", "bị chặn"),
    "trace_paused": ("paused", "tạm dừng"),
    "traces_no_match": ("No trace matches", "Không có dấu vết nào khớp"),
    "traces_no_match_line": (
        "Change the filters or wait for new agent activity.",
        "Đổi bộ lọc hoặc chờ hoạt động mới của tác tử.",
    ),
    "trace_title": ("Trace", "Dấu vết"),
    "copy_id": ("Copy id", "Sao chép mã"),
    "n_spans": ("{n} spans", "{n} span"),
    "span_detail": ("Selected span", "Span đã chọn"),
    "tree_legend": (
        "P = pause, B = block, A = alert, J = AI judge verdict (advice only).",
        "P tạm dừng, B chặn, A cảnh báo, J kết luận của bộ đánh giá AI (chỉ tham khảo).",
    ),
    "trace_capped": (
        "Large trace: some steps are not shown (+{n} more).",
        "Dấu vết lớn: một số bước không được hiển thị (+{n} nữa).",
    ),
    "plus_more": ("+{n} more spans", "+{n} span nữa"),
    "event_word": ("Event", "Sự kiện"),
    "parent_span": ("Parent step", "Bước cha"),
    "digest_only": (
        "No text is kept for this step. Only codes and numbers.",
        "Bước này không lưu văn bản, chỉ có mã và số.",
    ),
    "no_verdicts_span": (
        "No result is linked to this step.",
        "Chưa có kết quả nào gắn với bước này.",
    ),
    "src_tier0": ("Gate rule", "Quy tắc cổng"),
    "src_tier0b": ("Tier 0b finding", "Phát hiện Tier 0b"),
    "no_span": ("No step selected", "Chưa chọn bước nào"),
    "no_span_line": ("Pick a step in the tree.", "Chọn một bước trong cây."),
    "dry_run_pill": ("test run, nothing saved", "chạy thử, không lưu"),
    "playground_purpose": (
        "Ask the gate what it would decide for a call, without making the call.",
        "Hỏi cổng xem sẽ quyết định thế nào cho một lệnh gọi, mà không thực hiện lệnh gọi.",
    ),
    "playground_why": (
        "Nothing is saved: no verdict, evidence, agent change or metric. Rules that count calls over time are not applied.",
        "Không lưu gì: không kết luận, bằng chứng, thay đổi tác tử hay số liệu. Quy tắc đếm lệnh gọi theo thời gian không được áp dụng.",
    ),
    "pg_inputs": ("Call to test", "Lệnh gọi cần thử"),
    "pg_args": ("Arguments (JSON object)", "Đối số (đối tượng JSON)"),
    "pg_context": ("Context (JSON object)", "Ngữ cảnh (đối tượng JSON)"),
    "pg_note": (
        "Use made-up data. Arguments are not saved. The audit log keeps only a keyed hash.",
        "Hãy dùng dữ liệu giả lập. Đối số không được lưu. Nhật ký kiểm toán chỉ giữ mã băm có khóa.",
    ),
    "pg_check": ("Test the call (dry run)", "Thử lệnh gọi (chạy thử)"),
    "pg_result": ("Result", "Kết quả"),
    "pg_empty": ("No result yet", "Chưa có kết quả"),
    "pg_empty_line": (
        "Fill in the form and press Test the call.",
        "Điền biểu mẫu và nhấn Thử lệnh gọi.",
    ),
    "pg_error": ("The test failed", "Thử không thành công"),
    "pg_would_pause": ("would pause the agent", "sẽ tạm dừng tác tử"),
    "pg_allow": ("Call allowed", "Cho phép lệnh gọi"),
    "pg_state_unchanged": (
        "The agent was not changed. This result is not saved in the evidence.",
        "Tác tử không bị thay đổi. Kết quả này không được lưu vào bằng chứng.",
    ),
    "pg_rule_hits": ("Rules that applied", "Quy tắc đã áp dụng"),
    "pg_not_evaluated": (
        "Not tested in a dry run (these rules count calls over time)",
        "Không thử được khi chạy thử (các quy tắc này đếm lệnh gọi theo thời gian)",
    ),
    "pg_transformed": ("Arguments after changes", "Đối số sau khi thay đổi"),
    "pg_preview_line": (
        "Masked preview of the arguments, as saved in the evidence ({n} value(s) changed).",
        "Xem trước đối số đã che, như được lưu trong bằng chứng ({n} giá trị đã đổi).",
    ),
    "pg_no_masker": (
        "Masking is not set up, so no argument text is shown.",
        "Chưa thiết lập che dữ liệu nên không hiển thị nội dung đối số.",
    ),
    "rule_error": ("rule error", "lỗi quy tắc"),
    "policies_purpose": (
        "The policy deployed to the gate: its versions and the rules in force.",
        "Chính sách đã triển khai cho cổng: các phiên bản và quy tắc đang hiệu lực.",
    ),
    "policies_why": (
        "Read-only. A change goes through Git and a pull request, never through this page.",
        "Chỉ đọc. Mọi thay đổi đi qua Git và pull request, không qua trang này.",
    ),
    "policies_git_note": (
        "To change a rule, edit the policy file in Git and deploy it.",
        "Để đổi một quy tắc, sửa tệp chính sách trong Git rồi triển khai.",
    ),
    "policy_versions": ("Deployed policy versions", "Các phiên bản chính sách đã triển khai"),
    "policies_in_force": ("Rules in force", "Quy tắc đang hiệu lực"),
    "policy_tools": ("Tools and risk classes", "Công cụ và nhóm rủi ro"),
    "policy_active": ("in force", "đang hiệu lực"),
    "policy_retired": ("retired", "đã ngừng"),
    "rules_n": ("Rules", "Số quy tắc"),
    "search_rules": ("Search rules", "Tìm quy tắc"),
    "no_policy": ("No policy in force", "Chưa áp dụng chính sách"),
    "no_policy_line": (
        "Deploy a policy file to apply rules.",
        "Triển khai tệp chính sách để áp dụng quy tắc.",
    ),
    "no_rules_filtered": ("No rule matches the filters.", "Không có quy tắc nào khớp bộ lọc."),
    "catalogue_caps": ("Guardians that apply", "Bộ bảo vệ áp dụng"),
    "catalogue_none": (
        "No guardian in the catalog applies to this risk class.",
        "Không có bộ bảo vệ nào trong danh mục áp dụng cho nhóm rủi ro này.",
    ),
    "credentials_purpose": (
        "See which agents have an access key and which service accounts may act for them.",
        "Xem tác tử nào có khóa truy cập và tài khoản dịch vụ nào được hoạt động thay cho tác tử.",
    ),
    "credentials_why": (
        "Details only. Secret values are never shown or stored here.",
        "Chỉ có thông tin mô tả. Giá trị bí mật không bao giờ hiển thị hay lưu ở đây.",
    ),
    "ingress_off": (
        "Agent authentication is off, so the gate accepts calls without a key.",
        "Xác thực tác tử đang tắt nên cổng nhận lệnh gọi không cần khóa.",
    ),
    "cred_kind": ("Credential kind", "Loại thông tin xác thực"),
    "cred_store": ("Key store", "Nơi lưu khóa"),
    "cred_agents_nokey": ("Agents without an active key", "Tác tử chưa có khóa hiệu lực"),
    "cred_store_error": ("Cannot read", "Không đọc được"),
    "cred_keys": ("Agent keys", "Khóa của tác tử"),
    "cred_identities": ("Identities allowed per agent", "Danh tính được phép theo tác tử"),
    "cred_rotate": ("Issue or rotate a key", "Cấp hoặc đổi khóa"),
    "cred_rotate_line": (
        "Issue or change keys on the command line. A new key never passes through the browser.",
        "Cấp hoặc đổi khóa bằng dòng lệnh. Khóa mới không bao giờ đi qua trình duyệt.",
    ),
    "key_id": ("Key id", "Mã khóa"),
    "key_current": ("current", "hiện tại"),
    "key_previous": ("previous", "trước đó"),
    "key_inactive": ("not valid now", "không còn hiệu lực"),
    "issued": ("Issued", "Cấp lúc"),
    "expires": ("Expires", "Hết hạn"),
    "last_used": ("Last used", "Dùng lần cuối"),
    "last_used_note": (
        "Last use is not tracked yet, so that column is empty.",
        "Chưa theo dõi lần dùng cuối nên cột này để trống.",
    ),
    "not_registered": ("not registered", "chưa đăng ký"),
    "no_keys": ("No key issued", "Chưa cấp khóa"),
    "no_keys_line": ("Issue a key with the command below.", "Cấp khóa bằng lệnh bên dưới."),
    "principal": ("Service identity", "Danh tính dịch vụ"),
    "no_identities": ("No identities set up.", "Chưa thiết lập danh tính nào."),
    "no_identities_line": (
        "Add the identities to the identities file.",
        "Thêm danh tính vào tệp danh tính.",
    ),
    "users_purpose": (
        "Who holds which role, and what each role may do.",
        "Ai giữ vai trò nào, và mỗi vai trò được làm gì.",
    ),
    "users_why": (
        "View only. To change a role, edit the config file in Git.",
        "Chỉ xem. Muốn đổi vai trò, hãy sửa tệp cấu hình trong Git.",
    ),
    "users_source": ("Role source", "Nguồn vai trò"),
    "service_principal": ("App service principal", "Service principal của ứng dụng"),
    "users_users": ("Users", "Người dùng"),
    "users_roles": ("Roles", "Vai trò"),
    "users_matrix": ("Role matrix", "Ma trận vai trò"),
    "users_matrix_note": (
        "Generated from the code. The same table is in",
        "Sinh từ mã nguồn. Cùng bảng này nằm trong",
    ),
    "holders": ("Holders", "Số người giữ"),
    "groups": ("Groups", "Nhóm"),
    "no_users": ("No users set up", "Chưa thiết lập người dùng"),
    "no_users_line": (
        "Add users to the users file or the role map.",
        "Thêm người dùng vào tệp người dùng hoặc bảng vai trò.",
    ),
    "audit_purpose": (
        "Every action taken in the console: who, what, on which target, and the result.",
        "Mọi thao tác trong bảng điều khiển: ai, làm gì, trên đối tượng nào, và kết quả.",
    ),
    "audit_why": (
        "Read-only. Entries cannot be changed or deleted. Each action is logged when attempted and again with its result.",
        "Chỉ để xem. Không thể sửa hay xóa mục nào. Mỗi thao tác được ghi khi bắt đầu và ghi lại kết quả.",
    ),
    "before_hash": ("Hash before", "Mã băm trước"),
    "after_hash": ("Hash after", "Mã băm sau"),
    "hash_changed": ("Target changed", "Đối tượng đã đổi"),
    "same_request": ("Other decisions in this request", "Các quyết định khác trong cùng yêu cầu"),
    "no_audit": ("No audit row matches", "Không có dòng kiểm toán nào khớp"),
    "no_audit_line": (
        "Change the filters, or take an action in the console.",
        "Đổi bộ lọc, hoặc thực hiện một thao tác trong bảng điều khiển.",
    ),
    "integrations_purpose": (
        "Status of connections to other systems: SIEM, webhook, pager, ITSM and SCIM.",
        "Trạng thái các kết nối tới hệ thống khác: SIEM, webhook, pager, ITSM và SCIM.",
    ),
    "integrations_why": (
        "Read-only. Secrets and full URLs are never shown.",
        "Chỉ đọc. Bí mật và URL đầy đủ không bao giờ hiển thị.",
    ),
    "integrations_note": (
        "Pager, ITSM and SCIM show demo data until connected.",
        "Pager, ITSM và SCIM hiển thị dữ liệu mẫu cho đến khi được kết nối.",
    ),
    "integration_word": ("Integration", "Tích hợp"),
    "configured": ("Configured", "Đã cấu hình"),
    "enabled": ("Enabled", "Đã bật"),
    "last_delivery": ("Last delivery", "Lần gửi cuối"),
    "dead_letter": ("Undelivered", "Gửi không thành công"),
    "stub_fake": ("simulated (test)", "mô phỏng (thử nghiệm)"),
    "integ_siem": ("SIEM sink", "Đích SIEM"),
    "integ_webhook": ("Webhook notifier", "Webhook thông báo"),
    "integ_pager": ("Pager", "Pager"),
    "integ_itsm": ("ITSM", "ITSM"),
    "integ_scim": ("SCIM", "SCIM"),
    "integ_lanes": ("{n} lane(s) tracked", "{n} làn đang theo dõi"),
    "integ_queued": ("{n} queued", "{n} đang chờ"),
}


# --- WP29: risk register (Risks page, drawer, Risks tab on the Agent page) ---
_T.update(
    {
        "nav_risks": ("Risks", "Rủi ro"),
        "atab_risks": ("Risks", "Rủi ro"),
        "dtab_links": ("Links", "Liên kết"),
        "rk_purpose": (
            "Your risk register: what can go wrong, how serious it is, and which controls reduce it.",
            "Sổ đăng ký rủi ro: điều gì có thể xảy ra, mức độ nghiêm trọng và kiểm soát nào giúp giảm rủi ro.",
        ),
        "rk_why": (
            "A mitigated risk keeps its lower score only while its controls show evidence that they work.",
            "Rủi ro được giảm thiểu chỉ giữ điểm thấp khi các kiểm soát liên kết còn bằng chứng hoạt động.",
        ),
        "rk_illustrative": (
            "Score bands are ILLUSTRATIVE (low up to {low}, medium up to {med}, high up to {high}) "
            "until the bank sets its own.",
            "Các mức điểm chỉ MINH HỌA (thấp đến {low}, trung bình đến {med}, cao đến {high}) "
            "cho đến khi ngân hàng đặt mức riêng.",
        ),
        "rk_illustrative_short": (
            "Score bands are ILLUSTRATIVE until the bank sets its own.",
            "Các mức điểm chỉ MINH HỌA cho đến khi ngân hàng đặt mức riêng.",
        ),
        "rk_edit_note": (
            "Read only. Change risks with /v1/risks or python -m supervisor.risk import.",
            "Chỉ đọc. Sửa rủi ro qua /v1/risks hoặc python -m supervisor.risk import.",
        ),
        "rk_tile_active": ("Active", "Đang áp dụng"),
        "rk_tile_critical": ("Critical", "Nghiêm trọng"),
        "rk_tile_high": ("High", "Cao"),
        "rk_overdue_line": (
            "{n} active risk(s) are past their review date.",
            "{n} rủi ro đang áp dụng đã quá hạn rà soát.",
        ),
        "rk_unproven_line": (
            "{n} mitigated risk(s) have no proof that controls work. Their residual score stays at the inherent score.",
            "{n} rủi ro giảm thiểu chưa có bằng chứng kiểm soát hoạt động. Điểm còn lại giữ bằng điểm tiềm ẩn.",
        ),
        "rk_cat_money_movement": ("Money movement", "Di chuyển tiền"),
        "rk_cat_credit_decision": ("Credit decision", "Quyết định tín dụng"),
        "rk_cat_pii": ("Personal data", "Dữ liệu cá nhân"),
        "rk_cat_injection": ("Prompt injection", "Tấn công tiêm lệnh (prompt injection)"),
        "rk_cat_model_behaviour": ("Model behaviour", "Hành vi mô hình"),
        "rk_cat_availability": ("Availability", "Tính sẵn sàng"),
        "rk_cat_third_party": ("Third party", "Bên thứ ba"),
        "rk_cat_duties_gap": ("Open regulatory duties", "Nghĩa vụ pháp lý chưa hoàn thành"),
        "rk_st_draft": ("Draft", "Bản nháp"),
        "rk_st_active": ("Active", "Đang áp dụng"),
        "rk_st_retired": ("Retired", "Đã gỡ"),
        "rk_treat_avoid": ("Avoid", "Tránh"),
        "rk_treat_mitigate": ("Mitigate", "Giảm thiểu"),
        "rk_treat_accept": ("Accept", "Chấp nhận"),
        "rk_treat_transfer": ("Transfer", "Chuyển giao"),
        "rk_col_risk": ("Risk", "Rủi ro"),
        "rk_col_category": ("Category", "Nhóm"),
        "rk_col_agents": ("Applies to", "Áp dụng cho"),
        "rk_col_inherent": ("Inherent risk", "Rủi ro tiềm ẩn"),
        "rk_col_residual": ("Residual risk", "Rủi ro còn lại"),
        "rk_col_evidence": ("Evidence", "Bằng chứng"),
        "rk_col_treatment": ("Treatment", "Xử lý"),
        "rk_col_review": ("Review", "Rà soát"),
        "rk_overdue": ("overdue", "quá hạn"),
        "rk_no_risks": ("No risks", "Chưa có rủi ro"),
        "rk_no_risks_line": (
            "Import the starter risks: python -m supervisor.risk import config/risks.",
            "Nhập rủi ro mẫu: python -m supervisor.risk import config/risks.",
        ),
        "rk_no_match": ("No risk matches the filters.", "Không có rủi ro khớp bộ lọc."),
        "rk_ev_working": ("working", "hoạt động"),
        "rk_ev_failing": ("failing", "lỗi"),
        "rk_ev_no_evidence": ("no evidence", "chưa có bằng chứng"),
        "rk_ev_none": ("not run yet", "chưa chạy"),
        "rk_reason_controls_working": ("controls working", "kiểm soát hoạt động"),
        "rk_reason_control_failing": ("a control is failing", "có kiểm soát bị lỗi"),
        "rk_reason_no_working_control": (
            "no control is proven to work",
            "chưa có kiểm soát nào được chứng minh là hoạt động",
        ),
        "rk_reason_no_links": ("no control linked", "chưa liên kết kiểm soát"),
        "rk_reason_no_supervised_agent": ("no supervised agent", "chưa có tác tử được giám sát"),
        "rk_reason_treatment_declared": (
            "residual risk as declared",
            "rủi ro còn lại như đã khai báo",
        ),
        "rk_reason_stale_evidence": ("evidence is too old", "bằng chứng đã cũ"),
        "rk_reason_no_evidence_yet": ("evidence not collected yet", "chưa thu thập bằng chứng"),
        "rk_reason_changed_since_evidence": (
            "risk or controls changed since the last evidence check",
            "rủi ro hoặc kiểm soát đã thay đổi kể từ lần kiểm tra bằng chứng gần nhất",
        ),
        "rk_score_val": ("{s} ({l} x {i})", "{s} ({l} x {i})"),
        "rk_marginal": ("Marginal risk (AI)", "Rủi ro biên (AI)"),
        "rk_treatment_note": ("Treatment note", "Ghi chú xử lý"),
        "rk_declared": ("Residual risk as declared", "Rủi ro còn lại theo khai báo"),
        "rk_applies_to": ("Applies to agents", "Áp dụng cho tác tử"),
        "rk_anchor": ("Linked to", "Liên kết với"),
        "rk_lnk_matrix": ("Compliance matrix items", "Mục trong ma trận tuân thủ"),
        "rk_lnk_rule": ("Gate rules", "Quy tắc cổng"),
        "rk_lnk_pack": ("Assurance checks", "Bộ kiểm tra bảo đảm"),
        "rk_lnk_monitor": ("Monitoring checks", "Kiểm tra giám sát"),
        "rk_lnk_case": ("Cases", "Vụ việc"),
        "rk_no_links": ("No links", "Chưa có liên kết"),
        "rk_trend": ("Residual risk score over time", "Điểm rủi ro còn lại theo thời gian"),
        "rk_window_end": ("Window end", "Cuối kỳ"),
        "rk_rule_hits": ("Rules triggered", "Quy tắc đã kích hoạt"),
        "rk_rules_missing": ("Rules missing", "Quy tắc không còn"),
        "rk_pack_ok": ("Assurance checks passing", "Kiểm tra bảo đảm đạt"),
        "rk_pack_fail": ("Assurance checks failed", "Kiểm tra bảo đảm không đạt"),
        "rk_mon_ok": ("Monitoring checks passing", "Kiểm tra giám sát đạt"),
        "rk_ctl_working": ("Working", "Hoạt động"),
        "rk_ctl_failing": ("Failing", "Lỗi"),
        "rk_ctl_idle": ("Idle", "Chưa hoạt động"),
        "rk_agents_n": ("Agents", "Tác tử"),
        "rk_agents_excl": ("Excluded", "Bị loại"),
        "rk_no_trend": (
            "No evidence yet. Run python -m supervisor.jobs.risk_evidence to collect it.",
            "Chưa có bằng chứng. Chạy python -m supervisor.jobs.risk_evidence để thu thập.",
        ),
        "rk_level": ("Register level", "Mức trong sổ rủi ro"),
        "rk_via": ("via", "qua"),
        "rk_own": ("own", "riêng"),
        "rk_inherited": ("inherited", "kế thừa"),
        "rk_tab_none": (
            "No active risk applies to this agent.",
            "Không có rủi ro đang áp dụng nào liên quan đến tác tử này.",
        ),
        "rk_tab_off": (
            "The risk register is turned off. An admin can turn it on with RISK_REGISTER_ENABLED=1.",
            "Sổ rủi ro đang tắt. Quản trị viên có thể bật bằng RISK_REGISTER_ENABLED=1.",
        ),
        "rk_open_page": ("Open the Risks page", "Mở trang Rủi ro"),
    }
)


# --- WP30: control catalogue and task list (pages, drawers, Agent tabs) ---
_T.update(
    {
        "nav_controls": ("Controls", "Kiểm soát"),
        "nav_tasks": ("Tasks", "Nhiệm vụ"),
        "atab_controls": ("Controls", "Kiểm soát"),
        "atab_tasks": ("Tasks", "Nhiệm vụ"),
        "rk_lnk_control": ("Controls", "Kiểm soát"),
        "ct_purpose": (
            "The control catalogue: what the bank and the product do, what each control covers, and whether it works.",  # noqa: E501
            "Danh mục kiểm soát: ngân hàng và sản phẩm làm gì, mỗi kiểm soát bao phủ gì, và nó có hoạt động không.",  # noqa: E501
        ),
        "ct_why": (
            "One control can cover many duties and risks. It counts as working only when live results prove it: a rule that fired, an automated check that passed, or a monitor that is healthy.",
            "Một kiểm soát có thể bao phủ nhiều nghĩa vụ và rủi ro. Nó chỉ được tính là hoạt động khi kết quả thực tế chứng minh: quy tắc đã kích hoạt, kiểm tra tự động đã đạt, hoặc bộ giám sát vẫn ổn.",
        ),
        "ct_edit_note": (
            "Read only. To change controls, use /v1/controls or python -m supervisor.controls import.",
            "Chỉ xem. Để sửa, dùng /v1/controls hoặc python -m supervisor.controls import.",
        ),
        "ct_tile_active": ("Active", "Đang áp dụng"),
        "ct_tile_product": ("By the product", "Do sản phẩm"),
        "ct_tile_bank": ("By the bank", "Do ngân hàng"),
        "ct_failing_line": (
            "{n} active controls are failing for at least one agent.",
            "{n} kiểm soát đang áp dụng không hoạt động với ít nhất một tác tử.",
        ),
        "ct_uncovered_line": (
            "{n} active risk(s) have no control.",
            "{n} rủi ro đang áp dụng chưa có kiểm soát.",
        ),
        "ct_col_control": ("Control", "Kiểm soát"),
        "ct_col_type": ("Type", "Loại"),
        "ct_col_by": ("Implemented by", "Thực hiện bởi"),
        "ct_col_covers": ("Duties / risks", "Nghĩa vụ / rủi ro"),
        "ct_col_sources": ("Evidence sources", "Nguồn bằng chứng"),
        "ct_col_status": ("Evidence", "Bằng chứng"),
        "ct_type_preventive": ("Preventive", "Phòng ngừa"),
        "ct_type_detective": ("Detective", "Phát hiện"),
        "ct_type_corrective": ("Corrective", "Khắc phục"),
        "ct_by_product": ("Product", "Sản phẩm"),
        "ct_by_bank": ("Bank", "Ngân hàng"),
        "ct_ev_working": ("working", "hoạt động"),
        "ct_ev_failing": ("failing", "lỗi"),
        "ct_ev_no_data": ("no data", "chưa có dữ liệu"),
        "ct_no_controls": ("No controls", "Chưa có kiểm soát"),
        "ct_no_controls_line": (
            "python -m supervisor.controls import config/controls loads the starter catalogue.",
            "python -m supervisor.controls import config/controls nạp danh mục mẫu.",
        ),
        "ct_dtab_map": ("Map", "Ánh xạ"),
        "ct_dtab_status": ("Status", "Trạng thái"),
        "ct_objective": ("Objective", "Mục tiêu"),
        "ct_agents": ("Agents", "Tác tử"),
        "ct_map_matrix": ("Duties (compliance matrix)", "Nghĩa vụ (ma trận tuân thủ)"),
        "ct_map_risk": ("Risks", "Rủi ro"),
        "ct_map_rule": ("Gate rules", "Quy tắc cổng"),
        "ct_map_pack": ("Automated checks", "Kiểm tra tự động"),
        "ct_map_monitor": ("Monitoring", "Giám sát"),
        "ct_map_detector": ("Detectors (reference)", "Bộ phát hiện (tham chiếu)"),
        "ct_map_document": ("Documents (reference)", "Tài liệu (tham chiếu)"),
        "ct_no_map": ("Nothing mapped", "Chưa ánh xạ gì"),
        "ct_status_by_agent": ("Status by agent", "Trạng thái theo tác tử"),
        "ct_refs": ("References", "Tham chiếu"),
        "ct_no_status": (
            "No status yet. Run python -m supervisor.jobs.control_status to create it.",
            "Chưa có trạng thái. Chạy python -m supervisor.jobs.control_status để tạo.",
        ),
        "ct_reason_sources_working": ("a source works", "có nguồn hoạt động"),
        "ct_reason_source_failing": ("a source fails", "có nguồn bị lỗi"),
        "ct_reason_no_working_source": (
            "no source shows it works",
            "không nguồn nào cho thấy hoạt động",
        ),
        "ct_reason_reference_only": ("documents only", "chỉ có tài liệu"),
        "ct_reason_no_sources": ("no evidence source", "chưa có nguồn bằng chứng"),
        "ct_reason_no_supervised_agent": ("agent is not supervised", "tác tử chưa được giám sát"),
        "ct_reason_not_evaluated": ("not evaluated yet", "chưa được đánh giá"),
        "ct_reason_stale": ("evidence too old", "bằng chứng đã cũ"),
        "ct_reason_bank_owned": (
            "bank process, not monitored",
            "quy trình của ngân hàng, không được giám sát",
        ),
        "ct_reason_changed_since_evidence": (
            "changed after the evidence was taken",
            "đã đổi sau khi lấy bằng chứng",
        ),
        "ct_tab_off": (
            "The control catalogue is switched off. Set CONTROLS_ENABLED=1 to turn it on.",
            "Danh mục kiểm soát đang tắt. Đặt CONTROLS_ENABLED=1 để bật.",
        ),
        "ct_tab_none": (
            "No control is in scope for this agent.",
            "Không có kiểm soát nào áp dụng cho tác tử này.",
        ),
        "ct_compliance": ("Controls with working evidence", "Kiểm soát có bằng chứng hoạt động"),
        "ct_none_in_scope": (
            "No controls apply, so there is no figure.",
            "Chưa có kiểm soát áp dụng nên chưa có số liệu.",
        ),
        "ct_in_scope": ("in scope", "áp dụng"),
        "ct_product_line": (
            "Product controls: {n} apply, {bp} bp working. Bank-owned controls that apply: {b} (never shown as working).",
            "Kiểm soát của sản phẩm: {n} áp dụng, {bp} bp hoạt động. Kiểm soát của ngân hàng: {b} (không bao giờ hiện là hoạt động).",
        ),
        "ct_obligations": ("Duties", "Nghĩa vụ"),
        "ct_open_page": ("Open the Controls page", "Mở trang Kiểm soát"),
        "tk_purpose": (
            "Tasks for each AI system and lifecycle stage. Finish all required tasks before the system moves to the next stage.",
            "Nhiệm vụ cho từng hệ thống AI và giai đoạn vòng đời. Phải hoàn tất nhiệm vụ bắt buộc trước khi hệ thống chuyển giai đoạn.",
        ),
        "tk_why": (
            "The task set depends on the Decision 33 class and the risk level. Finish all required tasks of the current stage before the next stage and the launch GO.",
            "Bộ nhiệm vụ phụ thuộc phân loại Quyết định 33 và mức rủi ro. Phải hoàn tất nhiệm vụ bắt buộc của giai đoạn hiện tại trước khi chuyển giai đoạn và GO ra mắt.",
        ),
        "tk_illustrative": (
            "Task sets and thresholds are ILLUSTRATIVE until the bank sets them (config/tasks.yaml).",  # noqa: E501
            "Bộ nhiệm vụ và ngưỡng chỉ MINH HỌA cho đến khi ngân hàng quy định (config/tasks.yaml).",  # noqa: E501
        ),
        "tk_edit_note": (
            "Read only. Change tasks through /v1/tasks or python -m supervisor.tasks.",
            "Chỉ đọc. Đổi nhiệm vụ qua /v1/tasks hoặc python -m supervisor.tasks.",
        ),
        "tk_tile_open_required": ("Required, open", "Bắt buộc, chưa xong"),
        "tk_tile_overdue": ("Overdue", "Quá hạn"),
        "tk_tile_waiver": ("Waiver needs second approver", "Miễn trừ chờ người phê duyệt thứ hai"),
        "tk_col_task": ("Task", "Nhiệm vụ"),
        "tk_col_stage": ("Stage", "Giai đoạn"),
        "tk_col_required": ("Required", "Bắt buộc"),
        "tk_col_role": ("Owner role", "Vai trò"),
        "tk_col_due": ("Due", "Hạn"),
        "tk_stage_initiation": ("Initiation", "Khởi tạo"),
        "tk_stage_design": ("Design", "Thiết kế"),
        "tk_stage_validation": ("Validation", "Thẩm định"),
        "tk_stage_deployment": ("Deployment", "Triển khai"),
        "tk_stage_operation": ("Operation", "Vận hành"),
        "tk_stage_re_evaluation": ("Re-evaluation", "Đánh giá lại"),
        "tk_stage_retirement": ("Retirement", "Ngừng sử dụng"),
        "tk_st_open": ("open", "chưa làm"),
        "tk_st_in_progress": ("in progress", "đang làm"),
        "tk_st_done": ("done", "xong"),
        "tk_st_waived": ("waived", "miễn trừ"),
        "tk_required": ("required", "bắt buộc"),
        "tk_optional": ("optional", "tùy chọn"),
        "tk_waive_pending": ("waiver pending", "chờ miễn trừ"),
        "tk_no_tasks": ("No tasks", "Chưa có nhiệm vụ"),
        "tk_no_match": ("No task matches the filters.", "Không có nhiệm vụ khớp bộ lọc."),
        "tk_no_tasks_line": (
            "python -m supervisor.tasks generate --agent <id> --user <name> makes the list of an agent.",  # noqa: E501
            "python -m supervisor.tasks generate --agent <id> --user <name> tạo danh sách cho tác tử.",  # noqa: E501
        ),
        "tk_dtab_history": ("History", "Lịch sử"),
        "tk_level": ("Task set for (level, class)", "Bộ nhiệm vụ áp dụng cho (mức, phân loại)"),
        "tk_evidence": ("Evidence", "Bằng chứng"),
        "tk_done_by": ("Done by", "Hoàn thành bởi"),
        "tk_waive_reason": ("Waiver reason", "Lý do miễn trừ"),
        "tk_waive_by": ("Waiver (asked by, approved by)", "Miễn trừ (người đề nghị, người duyệt)"),
        "tk_action": ("Action", "Hành động"),
        "tk_actor": ("Person", "Người"),
        "tk_no_history": ("No events.", "Chưa có sự kiện."),
        "tk_tab_off": (
            "The task list is turned off. An admin can turn it on with CONTROLS_ENABLED=1.",
            "Danh sách nhiệm vụ đang tắt. Quản trị viên có thể bật bằng CONTROLS_ENABLED=1.",
        ),
        "tk_tab_none": ("No task list yet.", "Chưa có danh sách nhiệm vụ."),
        "tk_stage_now": ("Stage", "Giai đoạn"),
        "tk_sizing": (
            "Task set for class {cls}, band {band} ({src}): level {level}.",
            "Bộ nhiệm vụ theo phân loại {cls}, mức {band} ({src}): cấp {level}.",
        ),
        "tk_required_open": (
            "{n} of {total} required tasks open",
            "{n} trên {total} nhiệm vụ bắt buộc chưa xong",
        ),
        "tk_next_stage": ("next stage", "giai đoạn tiếp"),
        "tk_open_page": ("Open the Tasks page", "Mở trang Nhiệm vụ"),
    }
)


# --- WP-UX2: agent page, Alerts, Sign-off list, Analytics, Cases list ---
_T.update(
    {
        "atab_overview": ("Overview", "Tổng quan"),
        "atab_policy": ("Policy", "Chính sách"),
        "atab_tools": ("Tools", "Công cụ"),
        "atab_inventory": ("Inventory", "Kiểm kê"),
        "atab_traces": ("Traces", "Dấu vết"),
        "atab_cases": ("Cases", "Vụ việc"),
        "atab_assurance": ("Assurance", "Đảm bảo chất lượng"),
        "atab_compliance": ("Compliance", "Tuân thủ"),
        "agent_purpose": (
            "Status, rules, tools, activity and cases of one agent, and the action you can take now.",
            "Trạng thái, quy tắc, công cụ, hoạt động và vụ việc của một tác tử, cùng thao tác bạn có thể làm ngay.",
        ),
        "agent_why": (
            "Any reviewer can pause an agent. Resuming needs two different people.",
            "Người rà soát nào cũng có thể tạm dừng tác tử. Cho chạy lại cần hai người khác nhau.",
        ),
        "open_agent_page": ("Open the agent page", "Mở trang tác tử"),
        "gate_24h": ("Gate, last 24 hours", "Cổng, 24 giờ qua"),
        "gate_checked": ("Calls checked", "Lệnh gọi đã kiểm tra"),
        "gate_blocked": ("Blocked", "Bị chặn"),
        "gate_paused": ("Paused", "Bị tạm dừng"),
        "gate_median": ("Median latency", "Độ trễ trung vị"),
        "policy_rules": ("Rules in scope", "Quy tắc áp dụng"),
        "policy_shadow_note": (
            "Shadow mode: rules are checked and logged, but nothing is blocked.",
            "Chế độ theo dõi (shadow): quy tắc được kiểm tra và ghi lại, nhưng không chặn gì.",
        ),
        "policy_hash": ("policy hash", "mã băm chính sách"),
        "policy_version": ("policy version", "phiên bản chính sách"),
        "policy_all_agents": ("all agents", "mọi tác tử"),
        "policy_approvers": ("Approvers", "Người phê duyệt"),
        "policy_allow": ("Approved tools (allow-list)", "Công cụ được duyệt (danh sách cho phép)"),
        "policy_no_allow": (
            "No approved-tools rule names this agent.",
            "Chưa có quy tắc công cụ được duyệt cho tác tử này.",
        ),
        "policy_readonly": (
            "Read only. Rule changes go through review in Git.",
            "Chỉ đọc. Quy tắc chỉ đổi qua rà soát trong Git.",
        ),
        "tl_in_analytics": ("See tool usage for all agents", "Xem mức dùng công cụ của mọi tác tử"),
        "inv_not_listed": (
            "This agent is not in the inventory",
            "Tác tử này chưa có trong kiểm kê",
        ),
        "inv_not_listed_line": (
            "The inventory job has not seen it yet.",
            "Tác vụ kiểm kê chưa thấy tác tử này.",
        ),
        "inv_all_link": ("Open the Inventory page", "Mở trang Kiểm kê"),
        "trace": ("Trace", "Dấu vết"),
        "trace_events": ("Events", "Sự kiện"),
        "outcome": ("Outcome", "Kết quả"),
        "traces_last_n": ("Last {n} traces of this agent.", "{n} dấu vết gần nhất của tác tử này."),
        "no_traces": ("No activity trace yet", "Chưa có dấu vết hoạt động"),
        "no_traces_line": (
            "Traces appear here once this agent sends events.",
            "Dấu vết sẽ hiện ở đây khi tác tử này gửi sự kiện.",
        ),
        "as_no_agent_results": ("No tests run yet.", "Chưa chạy kiểm thử nào."),
        "as_no_agent_results_line": (
            "No test has been run on this agent.",
            "Chưa có kiểm thử nào chạy trên tác tử này.",
        ),
        "alerts_why": (
            "An alert means a rule found something in the evidence. One person acknowledges it, and the name is recorded.",
            "Cảnh báo cho biết một quy tắc đã phát hiện điều đáng chú ý trong bằng chứng. Một người xác nhận và tên người đó được ghi lại.",
        ),
        "alerts_active": ("Active", "Đang hoạt động"),
        "alerts_st_open": ("Open", "Đang mở"),
        "alerts_st_acknowledged": ("Acknowledged", "Đã xác nhận"),
        "alerts_st_closed": ("Closed", "Đã đóng"),
        "no_alerts_line": (
            "No alert matches these filters. Change the filters to see more.",
            "Không có cảnh báo nào khớp bộ lọc. Hãy đổi bộ lọc để xem thêm.",
        ),
        "alert_first": ("First seen", "Lần đầu"),
        "alert_last": ("Last seen", "Lần cuối"),
        "alert_entry_hash": ("Evidence hash", "Mã băm bằng chứng"),
        "alert_rule_hash": ("Rule hash", "Mã băm quy tắc"),
        "alert_routes": ("Sent to", "Gửi tới"),
        "alert_acked_by": ("Acknowledged by", "Người xác nhận"),
        "so_purpose": (
            "High and critical cases that wait for a signature.",
            "Vụ việc mức cao và nghiêm trọng đang chờ chữ ký.",
        ),
        "so_signatures": ("Signatures (2 needed)", "Chữ ký (cần 2)"),
        "so_none": ("Nothing waits for a signature", "Không có gì chờ chữ ký"),
        "so_none_line": (
            "Cases that need two people appear here once they are triaged.",
            "Vụ việc cần hai người sẽ hiện ở đây sau khi được phân loại.",
        ),
        "nav_analytics": ("Analytics", "Phân tích"),
        "an_purpose": (
            "How agents use their tools, how the gate performs and how oversight is doing.",
            "Cách tác tử dùng công cụ, cổng hoạt động ra sao và giám sát đang thế nào.",
        ),
        "an_why": (
            "Range and agent apply to all tabs.",
            "Khoảng thời gian và tác tử áp dụng cho mọi thẻ.",
        ),
        "an_tab_gate": ("Gate", "Cổng"),
        "an_tab_tools": ("Tools", "Công cụ"),
        "an_tab_metrics": ("Oversight metrics", "Chỉ số giám sát"),
        "an_tab_latency": ("Latency", "Độ trễ"),
        "an_range": ("Range", "Khoảng thời gian"),
        "an_range_default": ("default", "mặc định"),
        "an_days": ("{n} days", "{n} ngày"),
        "an_capped": (
            "Limit reached. Older events are not counted.",
            "Đã chạm giới hạn. Sự kiện cũ hơn không được tính.",
        ),
        "an_p95": ("p95 latency (ms)", "Độ trễ p95 (ms)"),
        "an_gate_none": (
            "No gate decision in this range",
            "Không có quyết định của cổng trong khoảng này",
        ),
        "an_gate_none_line": (
            "Decisions appear when an agent calls the gate.",
            "Quyết định hiện ở đây khi tác tử gọi cổng.",
        ),
        "an_see_alerts": ("see all", "xem tất cả"),
        # review fix: the toolbar always names the window the numbers cover
        "an_window_days": (
            "Window: {a} .. {b} ({n} days, UTC)",
            "Khoảng: {a} .. {b} ({n} ngày, UTC)",
        ),
        "an_window_stored": (
            "All days on record, {a} to {b}",
            "Mọi ngày đã có dữ liệu, {a} đến {b}",
        ),
        "an_window_stored_none": (
            "All days on record (none yet)",
            "Mọi ngày đã có dữ liệu (chưa có)",
        ),
        "an_window_live": (
            "Window: live counters since this process started",
            "Khoảng: bộ đếm trực tiếp từ lúc tiến trình này khởi động",
        ),
        "so_sig_n": ("{n}/2 signatures", "{n}/2 chữ ký"),
        "alert_window_val": ("{n}/{max} in {s} s", "{n}/{max} trong {s} giây"),
        "an_latency_note": (
            "Live counts since the service started.",
            "Số liệu trực tiếp từ lúc dịch vụ khởi động.",
        ),
        "open_case": ("Open the case", "Mở vụ việc"),
        "inbox_st_unread": ("Unread", "Chưa đọc"),
        "inbox_st_read": ("Read", "Đã đọc"),
        "inbox_st_queued": ("Queued", "Đang chờ gửi"),
        "cp_no_matrix": ("No compliance matrix", "Chưa có ma trận tuân thủ"),
        "cp_no_matrix_line": (
            "This agent has no compliance matrix yet. Ask an administrator to build one with the advisor command.",
            "Tác tử này chưa có ma trận tuân thủ. Hãy nhờ quản trị viên tạo bằng lệnh của cố vấn.",
        ),
    }
)


# --- WP38 --- Integrations catalogue, Playground samples and attributes.
_T.update(
    {
        "col_purpose": (
            "Attach an agent to Supervisor. Pick a way, choose the agent, press Add, and follow "
            "the steps.",
            "Gắn một tác tử vào Supervisor. Chọn cách gắn, chọn tác tử, nhấn Thêm và làm theo "
            "các bước.",
        ),
        "col_why": (
            "Add creates the first key for this agent. The key is shown once only.",
            "Thêm sẽ tạo khóa đầu tiên cho tác tử này. Khóa chỉ hiện một lần.",
        ),
        "col_cat_sdk": ("SDK", "SDK (thư viện)"),
        "col_cat_middleware": ("Middleware", "Middleware (lớp trung gian)"),
        "col_cat_gateway": ("Gateway and API", "Cổng và API"),
        "col_cat_mcp": ("MCP", "MCP (giao thức công cụ)"),
        "col_cat_ide": ("Developer tools", "Công cụ lập trình"),
        "col_add": ("Add", "Thêm"),
        "col_pick_agent": ("Agent without a key", "Tác tử chưa có khóa"),
        "col_no_free_agent": (
            "Every registered agent has a key. Open one below to see its steps.",
            "Mọi tác tử đã đăng ký đều có khóa. Mở một tác tử bên dưới để xem các bước.",
        ),
        "col_unavailable": ("Not available yet", "Chưa dùng được"),
        "col_agents": ("Agents and keys", "Tác tử và khóa"),
        "col_key_state": ("Key", "Khóa"),
        "col_key_active": ("active", "đang dùng"),
        "col_key_none": ("none", "chưa có"),
        "col_consumers": ("Callers", "Bên gọi"),
        "col_open": ("Open", "Mở"),
        "col_none_agents": ("No agent is registered", "Chưa có tác tử nào được đăng ký"),
        "col_none_agents_line": (
            "Register the agent in the policy file first.",
            "Hãy đăng ký tác tử trong tệp chính sách trước.",
        ),
        "col_status_title": ("Delivery integrations", "Tích hợp gửi dữ liệu"),
        "col_store_error": ("The key store could not be read", "Không đọc được kho khóa"),
        "col_result_title": ("Connected: {agent}", "Đã kết nối: {agent}"),
        "col_secret_once": (
            "Copy this key now. It is shown once and Supervisor cannot show it again.",
            "Hãy sao chép khóa này ngay. Khóa chỉ hiện một lần và Supervisor không thể hiện lại.",
        ),
        "col_secret": ("Key (secret)", "Khóa (bí mật)"),
        "col_steps": ("Setup steps", "Các bước cài đặt"),
        "col_snippet": ("Code", "Mã"),
        "col_manual": (
            "Supervisor could not save the key to {store}. Do this first:",
            "Supervisor không lưu được khóa vào {store}. Hãy làm bước này trước:",
        ),
        "col_ingress_off": (
            "Agent sign-in is off (INGRESS_AUTH_ENABLED=0), so keys are not checked. Turn it on before go-live.",
            "Đăng nhập của tác tử đang tắt (INGRESS_AUTH_ENABLED=0) nên khóa không được kiểm tra. Hãy bật trước khi chạy thật.",
        ),
        "col_template": ("Way to attach", "Cách gắn"),
        "dtab_connection": ("Connection", "Kết nối"),
        "dtab_credential": ("Credential", "Thông tin xác thực"),
        "dtab_binding": ("Linked policy", "Chính sách đã gắn"),
        "col_cred_note": (
            "Only the key ID, status and dates are shown. The key itself is never shown again.",
            "Chỉ hiện mã khóa, trạng thái và ngày. Bản thân khóa không bao giờ hiện lại.",
        ),
        "col_rotate": ("Replace the key from the command line", "Đổi khóa bằng dòng lệnh"),
        "col_no_keys_agent": (
            "This agent has no active key. Select Add in the catalog.",
            "Tác tử này chưa có khóa đang dùng. Chọn Thêm trong danh mục.",
        ),
        "col_bind_mode": ("Policy mode", "Chế độ chính sách"),
        "col_bind_preset": ("Detector sensitivity", "Mức nhạy của bộ dò"),
        "col_bind_disabled": ("Rules switched off", "Quy tắc đã tắt"),
        "col_bind_rules": ("Rules in scope", "Quy tắc áp dụng"),
        "col_bind_consumers": ("Settings per caller", "Cấu hình riêng theo bên gọi"),
        "col_bind_none": (
            "No special settings for callers. All callers use the agent settings.",
            "Không có cấu hình riêng cho bên gọi. Mọi bên gọi dùng cấu hình của tác tử.",
        ),
        "col_bind_note": (
            "The policy is kept in git. To change the mode or callers, edit the policy file and have the change reviewed.",
            "Chính sách được lưu trong git. Muốn đổi chế độ hoặc bên gọi, hãy sửa tệp chính sách và nhờ duyệt thay đổi.",
        ),
        "col_bind_enable": ("switch on", "bật"),
        "col_bind_disable": ("switch off", "tắt"),
        "col_bind_unavailable": (
            "The policy could not be read. Check the policy file.",
            "Không đọc được chính sách. Hãy kiểm tra tệp chính sách.",
        ),
        "mode_enforce": ("enforce", "thực thi"),
        "mode_observe": ("observe", "quan sát"),
        "pg_samples": ("Sample library", "Thư viện mẫu"),
        "pg_samples_line": (
            "Pick a sample to fill the form. Nothing is sent until you press Check.",
            "Chọn một mẫu để điền biểu mẫu. Không có gì được gửi cho đến khi bạn nhấn Kiểm tra.",
        ),
        "pg_sample_pick": ("Load a sample", "Nạp một mẫu"),
        "pg_extra": ("Extra attributes", "Thuộc tính bổ sung"),
        "pg_extra_line": (
            "These are added to the details of the test.",
            "Các thuộc tính này được thêm vào chi tiết của lần thử.",
        ),
        "pg_consumer": ("Caller ID", "Mã bên gọi"),
        "pg_direction": ("Direction", "Hướng"),
        "pg_dir_input": ("input (sent by the agent)", "input (tác tử gửi đi)"),
        "pg_dir_output": ("output (returned by a tool)", "output (công cụ trả về)"),
        "pg_tool_class": ("Declared tool class", "Loại công cụ khai báo"),
        "pg_result_mode": ("Policy mode", "Chế độ chính sách"),
        "pg_observed": ("Observed decision", "Quyết định quan sát được"),
        "pg_observed_line": (
            "In observe mode, this decision would have stopped the call. The call was allowed.",
            "Ở chế độ quan sát, quyết định này lẽ ra đã chặn lệnh gọi. Lệnh gọi vẫn được cho phép.",
        ),
        "pg_consumer_ignored": (
            "This caller ID has no settings for this agent, so the agent's own settings were used.",
            "Mã bên gọi này không có cấu hình riêng cho tác tử, nên dùng cấu hình của tác tử.",
        ),
    }
)


# --- WP31: transparency report (document labels, Transparency page, Agent tab) ---
_T.update(
    {
        "nav_transparency": ("Transparency", "Minh bạch"),
        "atab_transparency": ("Transparency", "Minh bạch"),
        "tp_yes": ("yes", "có"),
        "tp_no": ("no", "không"),
        "tp_unknown": ("unknown", "chưa rõ"),
        "tp_more": ("{n} more not shown", "còn {n} mục không hiển thị"),
        "tp_illustrative_note": (
            "ILLUSTRATIVE: the thresholds behind this section are examples until the bank sets "
            "its own.",
            "MINH HỌA: các ngưỡng của phần này chỉ là ví dụ cho đến khi ngân hàng đặt ngưỡng "
            "riêng.",
        ),
        "tp_advisory": (
            "For guidance only. Not legal advice; bank counsel confirms.",
            "Chỉ để tham khảo. Không phải tư vấn pháp lý; pháp chế ngân hàng xác nhận.",
        ),
        "tp_d33_rows": ("Decision 33 duties", "Nghĩa vụ theo Quyết định 33"),
        "tp_d33_missing": (
            "The classification cites these Decision 33 duties, but the matrix does not have them: {ids}",
            "Phân loại nêu các nghĩa vụ sau của Quyết định 33 nhưng ma trận không có: {ids}",
        ),
        "tp_gaps": (
            "Open items in the compliance matrix: partly met, not met or unanswered",
            "Mục còn mở trong ma trận tuân thủ: đáp ứng một phần, chưa đáp ứng hoặc chưa trả lời",
        ),
        "tp_agent_card": ("Agent card", "Thẻ tác tử"),
        "tp_judge_card": (
            "Judge model card (Supervisor's own judge, not this agent's model)",
            "Thẻ mô hình của bộ đánh giá (bộ đánh giá của Supervisor, không phải mô hình của "
            "tác tử)",
        ),
        "tp_controls_empty": ("No control data yet.", "Chưa có dữ liệu kiểm soát."),
        "tp_backlog_none": (
            "No open items for this agent.",
            "Tác tử này không có hạng mục nào đang mở.",
        ),
        "tp_ns_none": ("Nothing to add.", "Không có gì bổ sung."),
        "tp_verify_failed": (
            "The offline check of the evidence chain FAILED. Treat this agent's records as unproven until the cause is found.",
            "Kiểm tra ngoại tuyến chuỗi bằng chứng KHÔNG ĐẠT. Chưa coi hồ sơ của tác tử này là đáng tin cho đến khi tìm ra nguyên nhân.",
        ),
        # section titles
        "tp_s_identity": ("Identity and ownership", "Danh tính và trách nhiệm"),
        "tp_s_classification": ("Classification (Decision 33)", "Phân loại (Quyết định 33)"),
        "tp_s_inventory": ("Components", "Thành phần"),
        "tp_s_compliance": ("Compliance matrix", "Ma trận tuân thủ"),
        "tp_s_cards": ("Agent and model cards", "Thẻ tác tử và thẻ mô hình"),
        "tp_s_assurance": ("Assurance results", "Kết quả đảm bảo"),
        "tp_s_judge_mrm": ("Judge model risk status", "Tình trạng rủi ro mô hình của bộ đánh giá"),
        "tp_s_masking": ("Masking of personal data", "Che dữ liệu cá nhân"),
        "tp_s_monitors": ("Monitors", "Bộ giám sát"),
        "tp_s_risks": ("Risk register", "Sổ đăng ký rủi ro"),
        "tp_s_controls": ("Controls and tasks", "Kiểm soát và công việc"),
        "tp_s_evidence": ("Evidence chain", "Chuỗi bằng chứng"),
        "tp_s_cases": ("Open cases", "Vụ việc đang mở"),
        "tp_s_backlog": ("Open backlog items", "Hạng mục tồn đọng đang mở"),
        "tp_s_not_shown": ("What this report does not show", "Báo cáo này không thể hiện điều gì"),
        # reasons a section has no data
        "tp_reason_flag_off": (
            "Not available: the feature that holds this data is switched off.",
            "Không có: tính năng chứa dữ liệu này đang tắt.",
        ),
        "tp_reason_no_data": ("Not available: no data yet.", "Không có: chưa có dữ liệu."),
        "tp_reason_not_in_inventory": (
            "Not available: the agent is not in the inventory.",
            "Không có: tác tử chưa có trong kiểm kê.",
        ),
        "tp_reason_no_matrix": (
            "Not available: no compliance matrix for this agent.",
            "Không có: tác tử này chưa có ma trận tuân thủ.",
        ),
        "tp_reason_source_error": (
            "Not available: the source failed when the report was built.",
            "Không có: nguồn dữ liệu bị lỗi khi tạo báo cáo.",
        ),
        "tp_reason_not_built": (
            "Not available: the package that supplies this section is not in this build.",
            "Không có: gói cung cấp phần này chưa có trong bản này.",
        ),
        "tp_reason_not_for_variant": (
            "Not part of this version of the report.",
            "Không thuộc phiên bản báo cáo này.",
        ),
        # the not-shown list
        "tp_ns_section_flag_off": (
            "A section is empty because its feature is switched off",
            "Một phần để trống vì tính năng của nó đang tắt",
        ),
        "tp_ns_section_no_data": ("A section has no data yet", "Một phần chưa có dữ liệu"),
        "tp_ns_section_not_in_inventory": (
            "The agent is not in the inventory",
            "Tác tử chưa có trong kiểm kê",
        ),
        "tp_ns_section_no_matrix": (
            "No compliance matrix exists for this agent",
            "Chưa có ma trận tuân thủ cho tác tử này",
        ),
        "tp_ns_section_source_error": (
            "A source failed when the report was built",
            "Một nguồn dữ liệu bị lỗi khi tạo báo cáo",
        ),
        "tp_ns_section_not_built": (
            "A section is not built yet (controls and tasks)",
            "Một phần chưa được xây dựng (kiểm soát và công việc)",
        ),
        "tp_ns_section_not_for_variant": (
            "A section is left out of this version of the report",
            "Một phần được lược bỏ khỏi phiên bản báo cáo này",
        ),
        "tp_ns_illustrative": (
            "Thresholds in this section are ILLUSTRATIVE, not set by the bank",
            "Ngưỡng trong phần này chỉ MINH HỌA, chưa do ngân hàng đặt",
        ),
        "tp_ns_mock_judge": (
            "The judge model is a mock: its numbers say nothing about real judge quality",
            "Mô hình đánh giá là bản giả lập: số liệu không nói lên chất lượng thật",
        ),
        "tp_ns_mock_results": (
            "Some assurance results come from a mock target",
            "Một số kết quả đảm bảo đến từ đối tượng giả lập",
        ),
        "tp_ns_chain_not_verified": (
            "The evidence chain was not checked when this report was built",
            "Chuỗi bằng chứng chưa được kiểm tra khi tạo báo cáo",
        ),
        "tp_ns_chain_empty": (
            "The evidence chain holds no record of this agent yet, so there was nothing to check",
            "Chuỗi bằng chứng chưa có bản ghi nào của tác tử này nên chưa có gì để kiểm tra",
        ),
        "tp_ns_chain_verify_failed": (
            "The offline check of the evidence chain FAILED",
            "Kiểm tra ngoại tuyến chuỗi bằng chứng KHÔNG ĐẠT",
        ),
        "tp_ns_obligation_missing": (
            "A Decision 33 obligation id is cited but missing from the matrix",
            "Một mã nghĩa vụ của Quyết định 33 được nêu nhưng không có trong ma trận",
        ),
        "tp_ns_truncated": (
            "A list is cut to keep the report short",
            "Một danh sách bị cắt ngắn để báo cáo gọn",
        ),
        "tp_ns_agent_retired": ("The agent is retired", "Tác tử đã ngừng hoạt động"),
        "tp_ns_monitors_off": (
            "Some monitors are switched off",
            "Một số giám sát đang tắt",
        ),
        "tp_ns_masking_off": (
            "Masking of personal data is switched off",
            "Che dữ liệu cá nhân đang tắt",
        ),
        "tp_ns_judge_not_validated": (
            "The AI judge has no validation run yet",
            "Bộ đánh giá AI chưa có lần thẩm định nào",
        ),
        "tp_ns_advisory_only": (
            "The compliance matrix is advisory and is not a statement of compliance",
            "Ma trận tuân thủ chỉ mang tính tham khảo, không phải tuyên bố tuân thủ",
        ),
        "tp_ns_judge_advice_only": (
            "AI judge findings are advice; only rules and people decide",
            "Kết luận của bộ đánh giá AI chỉ là tư vấn; chỉ quy tắc và con người quyết định",
        ),
        "tp_ns_no_personal_data": (
            "No customer data or raw prompts are in this report",
            "Báo cáo không chứa dữ liệu khách hàng hay lời nhắc gốc",
        ),
        "tp_ns_variant_limited": (
            "This version shows fewer fields than the internal version",
            "Phiên bản này thể hiện ít trường hơn phiên bản nội bộ",
        ),
        # field labels
        "tp_f_agent_id": ("Agent id", "Mã tác tử"),
        "tp_f_name": ("Name", "Tên"),
        "tp_f_owner_team": ("Owner team", "Nhóm phụ trách"),
        "tp_f_owner_user": ("Owner", "Người phụ trách"),
        "tp_f_business_owner": ("Business owner", "Chủ nghiệp vụ"),
        "tp_f_kind": ("Kind", "Loại"),
        "tp_f_purpose": ("Purpose", "Mục đích"),
        "tp_f_host": ("Where it runs / connection point", "Nơi chạy / điểm kết nối"),
        "tp_f_model_family": ("Model family", "Họ mô hình"),
        "tp_f_risk_tier": ("Risk tier", "Hạng rủi ro"),
        "tp_f_status": ("Status", "Trạng thái"),
        "tp_f_registered": ("Registered", "Ngày đăng ký"),
        "tp_f_ov_executes_payments": ("Executes payments itself", "Tự thực hiện thanh toán"),
        "tp_f_ov_human_approval_before_execution": (
            "A person approves before execution",
            "Có người phê duyệt trước khi thực hiện",
        ),
        "tp_f_ov_credit_decisions": ("Decides credit itself", "Tự quyết định tín dụng"),
        "tp_f_ov_independent_credit_approval": (
            "Independent credit approval",
            "Có phê duyệt tín dụng độc lập",
        ),
        "tp_f_d33_class": ("Decision 33 class", "Phân loại theo Quyết định 33"),
        "tp_f_class_source": ("Where the class comes from", "Nguồn của phân loại"),
        "tp_f_matrix_class": ("Class suggested by the matrix", "Phân loại do ma trận đề xuất"),
        "tp_f_entry": ("Entry", "Mục"),
        "tp_f_triggered": ("Triggered", "Kích hoạt"),
        "tp_f_obligations": ("Duty ids", "Mã nghĩa vụ"),
        "tp_f_own_risk": ("Own risk level", "Mức rủi ro riêng"),
        "tp_f_eff_risk": ("Effective risk level", "Mức rủi ro hiệu lực"),
        "tp_f_nodes": ("Items in the graph", "Số mục trong đồ thị"),
        "tp_f_group": ("Link", "Liên kết"),
        "tp_f_component": ("Component", "Thành phần"),
        "tp_f_source": ("Source", "Nguồn"),
        "tp_f_evidence_ref": ("Evidence (file:line)", "Bằng chứng (tệp:dòng)"),
        "tp_f_matrix_source": ("Matrix source", "Nguồn của ma trận"),
        "tp_f_as_of": ("As of", "Tính đến ngày"),
        "tp_f_regkb": ("Regulation library version", "Phiên bản kho quy định"),
        "tp_f_obl_total": ("Duties in the matrix", "Số nghĩa vụ trong ma trận"),
        "tp_f_by_status": ("By status", "Theo trạng thái"),
        "tp_f_by_applies": ("By applicability", "Theo mức áp dụng"),
        "tp_f_questions": ("Open questions", "Câu hỏi còn mở"),
        "tp_f_thr_gaps": ("Threshold gaps", "Khoảng trống ngưỡng"),
        "tp_f_thr_exceeds": ("Limits above a cap", "Hạn mức vượt trần"),
        "tp_f_obligation": ("Duty", "Nghĩa vụ"),
        "tp_f_article": ("Article", "Điều"),
        "tp_f_applies": ("Applies", "Áp dụng"),
        "tp_f_version": ("Version", "Phiên bản"),
        "tp_f_classes": ("Agent classes", "Loại tác tử"),
        "tp_f_autonomy": ("Autonomy", "Mức tự chủ"),
        "tp_f_data_classes": ("Data classes", "Loại dữ liệu"),
        "tp_f_roles": ("Roles", "Vai trò"),
        "tp_f_customer_types": ("Customer types", "Loại khách hàng"),
        "tp_f_provenance": ("Facts with a source", "Số dữ kiện có nguồn"),
        "tp_f_limit": ("Limit", "Hạn mức"),
        "tp_f_period": ("Period", "Kỳ"),
        "tp_f_scope": ("Scope", "Phạm vi"),
        "tp_f_value_vnd": ("Value (VND)", "Giá trị (VND)"),
        "tp_f_source_ref": ("Source (file:line)", "Nguồn (tệp:dòng)"),
        "tp_f_judge": ("Judge", "Bộ đánh giá"),
        "tp_f_mock": ("Mock", "Giả lập"),
        "tp_f_model_version": ("Model version", "Phiên bản mô hình"),
        "tp_f_prompt_version": ("Prompt version", "Phiên bản lời nhắc"),
        "tp_f_rubric": ("Rubric version", "Phiên bản tiêu chí"),
        "tp_f_mask_version": ("Mask version", "Phiên bản che dữ liệu"),
        "tp_f_metrics": ("Metrics", "Chỉ số"),
        "tp_f_catch": ("Catch rate (bp)", "Tỷ lệ phát hiện (bp)"),
        "tp_f_false_alarm": ("False alarm rate (bp)", "Tỷ lệ báo động giả (bp)"),
        "tp_f_roles_assigned": ("Model risk roles filled", "Vai trò rủi ro mô hình đã gán"),
        "tp_f_role_name": ("Role: {role}", "Vai trò: {role}"),
        "tp_f_packs": ("Checks run", "Số kiểm tra đã chạy"),
        "tp_f_mock_n": ("Mock results", "Kết quả giả lập"),
        "tp_f_pack": ("Check", "Kiểm tra"),
        "tp_f_day": ("Day", "Ngày"),
        "tp_f_items": ("Items", "Số mục"),
        "tp_f_validations": ("Validation runs", "Số lần thẩm định"),
        "tp_f_latest_decision": ("Latest decision", "Quyết định gần nhất"),
        "tp_f_required": ("Validation required to judge", "Bắt buộc thẩm định mới được đánh giá"),
        "tp_f_decision": ("Decision", "Quyết định"),
        "tp_f_masking_on": ("Masking on", "Đang che dữ liệu"),
        "tp_f_masker": ("Masking tool", "Công cụ che dữ liệu"),
        "tp_f_capture": ("Recording level", "Mức ghi nhận"),
        "tp_f_amounts": ("Amounts masked", "Che số tiền"),
        "tp_f_monitor": ("Monitor", "Bộ giám sát"),
        "tp_f_bound": ("Bound", "Đã gắn"),
        "tp_f_gap": ("Gap", "Khoảng trống"),
        "tp_f_coverage": ("Gate coverage (bp)", "Độ phủ cổng kiểm soát (bp)"),
        "tp_f_events_seen": ("Tool calls seen", "Số lệnh gọi công cụ"),
        "tp_f_events_gated": ("Gate decisions", "Số quyết định của cổng"),
        "tp_f_inherent": ("Inherent score", "Điểm rủi ro gốc"),
        "tp_f_residual": ("Residual score", "Điểm rủi ro còn lại"),
        "tp_f_risks_n": ("Risks reaching this agent", "Số rủi ro liên quan"),
        "tp_f_by_band": ("By band", "Theo mức"),
        "tp_f_by_evidence": ("By evidence", "Theo bằng chứng"),
        "tp_f_links": ("Links (evidence / reference)", "Liên kết (bằng chứng / tham chiếu)"),
        "tp_links_val": ("{e} evidence / {r} reference", "{e} bằng chứng / {r} tham chiếu"),
        "tp_evidence_rule": (
            "Evidence is limited to rule links, checks not scored by an AI judge, and these monitors: {m}. Everything else is a reference only and never lowers a score. This includes AI-judged checks (unless the owner allows them), other monitor links, matrix links and case links.",
            "Chỉ liên kết quy tắc, kiểm tra không do bộ đánh giá AI chấm và các bộ giám sát sau được tính là bằng chứng: {m}. Còn lại chỉ là tham chiếu và không bao giờ làm giảm điểm, gồm kiểm tra do bộ đánh giá AI chấm (trừ khi chủ sở hữu cho phép), liên kết bộ giám sát khác, ma trận và vụ việc.",
        ),
        "tp_f_ctl_in_scope": ("Controls in scope", "Số kiểm soát trong phạm vi"),
        "tp_f_ctl_working": ("Working", "Đang hoạt động"),
        "tp_f_ctl_failing": ("Failing", "Đang lỗi"),
        "tp_f_ctl_no_data": ("No data", "Chưa có dữ liệu"),
        "tp_f_ctl_bp": ("Share working (bp)", "Tỷ lệ hoạt động (bp)"),
        "tp_f_ctl_product": (
            "Product controls working / in scope",
            "Kiểm soát của sản phẩm hoạt động / trong phạm vi",
        ),
        "tp_f_ctl_product_bp": ("Product share working (bp)", "Tỷ lệ hoạt động của sản phẩm (bp)"),
        "tp_f_ctl_bank": ("Bank-owned controls in scope", "Kiểm soát do ngân hàng sở hữu"),
        "tp_f_ctl_uncovered": (
            "Active risks with no control",
            "Rủi ro đang hoạt động chưa có kiểm soát",
        ),
        "tp_f_ctl_id": ("Control", "Kiểm soát"),
        "tp_f_ctl_title": ("Title", "Tên"),
        "tp_f_ctl_by": ("Implemented by", "Do ai thực hiện"),
        "tp_f_ctl_n": ("Controls", "Số kiểm soát"),
        "tp_ctl_bank_note": (
            "The product cannot see controls the bank owns, so they never show as working. The figure above does not mean the bank is non-compliant.",
            "Sản phẩm không thể quan sát các kiểm soát do ngân hàng sở hữu nên chúng không bao giờ hiển thị là đang hoạt động. Tỷ lệ trên không có nghĩa ngân hàng không tuân thủ.",
        ),
        "tp_f_risk": ("Risk", "Rủi ro"),
        "tp_f_category": ("Category", "Nhóm"),
        "tp_f_evidence": ("Evidence", "Bằng chứng"),
        "tp_f_via": ("Reached via", "Đến qua"),
        "tp_f_owner": ("Owner", "Người phụ trách"),
        "tp_f_lane": ("Record trail", "Chuỗi bản ghi"),
        "tp_f_entries": ("Entries", "Số bản ghi"),
        "tp_f_head": ("Latest record code", "Mã bản ghi mới nhất"),
        "tp_f_root_key": ("Signing key (kind / id)", "Khóa ký (loại / mã)"),
        "tp_f_anchored": ("Anchored outside the system", "Đã neo bên ngoài hệ thống"),
        "tp_f_verify": ("Offline check", "Kiểm tra ngoại tuyến"),
        "tp_f_verify_how": ("How the check was made", "Cách kiểm tra"),
        "tp_f_failures": ("Failures", "Số lỗi"),
        "tp_f_open": ("Open", "Đang mở"),
        "tp_f_closed": ("Closed", "Đã đóng"),
        "tp_f_total": ("Total", "Tổng"),
        "tp_f_by_severity": ("Open by severity", "Đang mở theo mức độ"),
        "tp_f_oldest": ("Oldest open (hours)", "Mở lâu nhất (giờ)"),
        "tp_f_case": ("Case", "Vụ việc"),
        "tp_f_severity": ("Severity", "Mức độ"),
        "tp_f_summary": ("Summary (masked)", "Tóm tắt (đã che)"),
        "tp_f_item": ("Item", "Hạng mục"),
        "tp_f_returns": ("Returns when", "Quay lại khi"),
        # words for codes
        "tp_kind_payment": ("payment", "thanh toán"),
        "tp_kind_credit_decision": ("credit decision", "quyết định tín dụng"),
        "tp_kind_customer_facing": ("customer facing", "giao tiếp khách hàng"),
        "tp_kind_internal_tool": ("internal tool", "công cụ nội bộ"),
        "tp_kind_other": ("other", "khác"),
        "tp_d33_high_risk": ("high risk", "rủi ro cao"),
        "tp_d33_not_high_risk": ("not high risk", "không thuộc rủi ro cao"),
        "tp_d33_needs_answer": ("needs an answer", "cần trả lời thêm"),
        "tp_src_registry": ("registry (set by a person)", "sổ đăng ký (do người đặt)"),
        "tp_src_proposal": ("onboarding proposal", "đề xuất khi tiếp nhận"),
        "tp_src_matrix": ("compliance matrix", "ma trận tuân thủ"),
        "tp_src_demo": ("demo profile", "hồ sơ minh họa"),
        "tp_src_onboard": ("onboarding run", "lần tiếp nhận"),
        "tp_entry_transactions": ("transactions", "giao dịch"),
        "tp_entry_credit": ("credit", "tín dụng"),
        "tp_lvl_low": ("low", "thấp"),
        "tp_lvl_medium": ("medium", "trung bình"),
        "tp_lvl_high": ("high", "cao"),
        "tp_lvl_critical": ("critical", "nghiêm trọng"),
        "tp_st_met": ("met", "đạt"),
        "tp_st_partial": ("partial", "một phần"),
        "tp_st_gap": ("gap", "thiếu"),
        "tp_st_bank_process": ("bank process", "quy trình ngân hàng"),
        "tp_st_not_applicable": ("not applicable", "không áp dụng"),
        "tp_st_needs_answer": ("needs an answer", "cần trả lời"),
        "tp_ap_yes": ("yes", "có"),
        "tp_ap_no": ("no", "không"),
        "tp_ap_needs_answer": ("needs an answer", "cần trả lời"),
        "tp_ast_ok": ("ok", "đạt"),
        "tp_ast_warn": ("warning", "cảnh báo"),
        "tp_ast_fail": ("fail", "không đạt"),
        "tp_ast_error": ("error", "lỗi"),
        "tp_ast_skip": ("skipped", "bỏ qua"),
        "tp_mst_ok": ("report found", "có báo cáo"),
        "tp_mst_no_eval_report": ("no evaluation report", "chưa có báo cáo đánh giá"),
        "tp_mon_drift": ("Drift", "Lệch hành vi"),
        "tp_mon_fairness": ("Fairness", "Công bằng"),
        "tp_mon_quality": ("Quality", "Chất lượng"),
        "tp_mon_multiagent": ("Multi-agent", "Đa tác tử"),
        "tp_mon_metrics": ("Metrics", "Chỉ số"),
        "tp_mon_split": ("Split payment", "Chia nhỏ thanh toán"),
        "tp_rev_working": ("working", "đang hoạt động"),
        "tp_rev_failing": ("failing", "đang lỗi"),
        "tp_rev_no_evidence": ("no evidence", "chưa có bằng chứng"),
        "tp_rev_none": ("no evidence yet", "chưa có bằng chứng"),
        "tp_ver_ok": ("passed", "đạt"),
        "tp_ver_failed": ("FAILED", "KHÔNG ĐẠT"),
        "tp_ver_not_run": ("not run", "chưa chạy"),
        "tp_ver_empty": ("no records yet", "chưa có bản ghi"),
        "tp_how_run_now": ("run when the report was built", "chạy khi tạo báo cáo"),
        "tp_how_console_cache": (
            "last result from the console",
            "kết quả gần nhất từ bảng điều khiển",
        ),
        "tp_how_none": ("not run", "chưa chạy"),
        "tp_sev_low": ("low", "thấp"),
        "tp_sev_medium": ("medium", "trung bình"),
        "tp_sev_high": ("high", "cao"),
        "tp_sev_critical": ("critical", "nghiêm trọng"),
        # customer variant (plain language)
        "tp_c_h_what": ("What this assistant does", "Trợ lý này làm gì"),
        "tp_c_h_class": ("How the law classes it", "Pháp luật phân loại như thế nào"),
        "tp_c_h_protect": ("How your data is protected", "Dữ liệu của bạn được bảo vệ ra sao"),
        "tp_c_h_checks": ("How we check it", "Chúng tôi kiểm tra ra sao"),
        "tp_c_what": ("This is {what}.", "Đây là {what}."),
        "tp_c_kind_payment": (
            "an automated assistant that can help you move money between accounts",
            "một trợ lý tự động có thể giúp bạn chuyển tiền giữa các tài khoản",
        ),
        "tp_c_kind_credit_decision": (
            "an automated assistant that supports credit decisions",
            "một trợ lý tự động hỗ trợ các quyết định tín dụng",
        ),
        "tp_c_kind_customer_facing": (
            "an automated assistant that answers customer questions",
            "một trợ lý tự động trả lời câu hỏi của khách hàng",
        ),
        "tp_c_kind_internal_tool": (
            "an automated tool used by bank staff",
            "một công cụ tự động do nhân viên ngân hàng sử dụng",
        ),
        "tp_c_kind_other": (
            "an automated assistant used by the bank",
            "một trợ lý tự động do ngân hàng sử dụng",
        ),
        "tp_c_pay_approved": (
            "A person approves each money transfer before it is made.",
            "Có người phê duyệt từng lệnh chuyển tiền trước khi thực hiện.",
        ),
        "tp_c_pay_auto": (
            "It can make a money transfer without a person approving each one. Automatic limits "
            "and checks apply.",
            "Trợ lý có thể thực hiện chuyển tiền mà không cần người duyệt từng lệnh. Có hạn mức "
            "và kiểm tra tự động.",
        ),
        "tp_c_pay_unknown": (
            "We have not recorded whether a person approves each money transfer.",
            "Chúng tôi chưa ghi nhận việc có người duyệt từng lệnh chuyển tiền hay không.",
        ),
        "tp_c_credit_approved": (
            "A credit officer approves credit decisions independently.",
            "Cán bộ tín dụng phê duyệt độc lập các quyết định tín dụng.",
        ),
        "tp_c_credit_auto": (
            "It takes part in credit decisions. We have not recorded an independent approval.",
            "Trợ lý tham gia vào các quyết định tín dụng. Chúng tôi chưa ghi nhận phê duyệt "
            "độc lập.",
        ),
        "tp_c_d33_high_risk": (
            "Under Decision 33/2026/QD-TTg this kind of system is on the list of high-risk AI "
            "systems.",
            "Theo Quyết định 33/2026/QĐ-TTg, hệ thống loại này thuộc danh mục hệ thống AI rủi "
            "ro cao.",
        ),
        "tp_c_d33_not_high_risk": (
            "Under Decision 33/2026/QD-TTg this system is not on the list of high-risk AI systems.",
            "Theo Quyết định 33/2026/QĐ-TTg, hệ thống này không thuộc danh mục hệ thống AI rủi "
            "ro cao.",
        ),
        "tp_c_d33_needs_answer": (
            "We have not finished classifying this system under Decision 33/2026/QD-TTg.",
            "Chúng tôi chưa hoàn tất việc phân loại hệ thống này theo Quyết định 33/2026/QĐ-TTg.",
        ),
        "tp_c_mask_on": (
            "Personal data is masked before it is kept in our monitoring records.",
            "Dữ liệu cá nhân được che trước khi lưu vào hồ sơ giám sát của chúng tôi.",
        ),
        "tp_c_mask_off": (
            "Personal data is not masked in the monitoring records.",
            "Dữ liệu cá nhân chưa được che trong hồ sơ giám sát.",
        ),
        "tp_c_monitors": (
            "{n} of {m} kinds of automatic monitoring are switched on.",
            "{n} trên {m} loại giám sát tự động đang được bật.",
        ),
        "tp_c_chain_ok": (
            "Our tamper-evident records were checked and passed.",
            "Hồ sơ chống sửa đổi của chúng tôi đã được kiểm tra và đạt.",
        ),
        "tp_c_chain_failed": (
            "A check of our tamper-evident records did not pass. We are looking into it.",
            "Một lần kiểm tra hồ sơ chống sửa đổi không đạt. Chúng tôi đang tìm nguyên nhân.",
        ),
        "tp_c_chain_empty": (
            "There are no records in our tamper-evident log for this assistant yet.",
            "Chưa có bản ghi nào trong nhật ký chống sửa đổi cho trợ lý này.",
        ),
        "tp_c_chain_not_run": (
            "Our tamper-evident records were not checked when this report was made.",
            "Hồ sơ chống sửa đổi chưa được kiểm tra khi tạo báo cáo này.",
        ),
        "tp_c_risks": (
            "We track {n} risks for this assistant. Highest remaining level: {level}.",
            "Chúng tôi theo dõi {n} rủi ro của trợ lý này. Mức còn lại cao nhất: {level}.",
        ),
        "tp_c_risks_none": (
            "No risks are registered yet for this assistant.",
            "Chưa có rủi ro nào được đăng ký cho trợ lý này.",
        ),
        "tp_c_tests": (
            "{n} automatic tests were recorded; {ok} passed.",
            "Đã ghi nhận {n} bài kiểm tra tự động; {ok} bài đạt.",
        ),
        "tp_c_tests_mock": (
            "Some of these tests ran against a stand-in, not the real system.",
            "Một số bài kiểm tra chạy trên bản thay thế, không phải hệ thống thật.",
        ),
        # document frame
        "tp_title_regulator": (
            "Transparency report (regulator)",
            "Báo cáo minh bạch (cho cơ quan quản lý)",
        ),
        "tp_title_customer": (
            "Transparency report (customers)",
            "Báo cáo minh bạch (cho khách hàng)",
        ),
        "tp_title_internal": ("Transparency report (internal)", "Báo cáo minh bạch (nội bộ)"),
        "tp_meta_version": ("Report version", "Phiên bản báo cáo"),
        "tp_meta_generated": ("Generated at (UTC)", "Tạo lúc (UTC)"),
        "tp_meta_status": ("Status", "Tình trạng"),
        "tp_meta_schema": ("Report format version", "Phiên bản định dạng báo cáo"),
        "tp_meta_content": ("Content hash", "Mã băm nội dung"),
        "tp_status_signed": ("signed into the evidence chain", "đã ký vào chuỗi bằng chứng"),
        "tp_status_preview": (
            "PREVIEW: not yet signed into the evidence chain",
            "XEM TRƯỚC: chưa ký vào chuỗi bằng chứng",
        ),
        "tp_footer": (
            "SHA-256 hashes of the JSON file and each report file are saved in the evidence chain (record_type transparency_report). Not legal advice.",
            "Mã băm SHA-256 của tệp JSON và từng tệp báo cáo được lưu vào chuỗi bằng chứng (record_type transparency_report). Không phải tư vấn pháp lý.",
        ),
        "tp_footer_c": ("Not legal advice.", "Không phải tư vấn pháp lý."),
        # console page and Agent tab
        "tp_purpose": (
            "One report per agent, built from data Supervisor already holds. Three versions: customer, internal and regulator.",
            "Mỗi tác tử một báo cáo, tạo từ dữ liệu Supervisor đã có. Gồm ba phiên bản: khách hàng, nội bộ và cơ quan quản lý.",
        ),
        "tp_why": (
            "Regulators, customers and the bank each see only what their version allows.",
            "Cơ quan quản lý, khách hàng và ngân hàng chỉ thấy nội dung mà phiên bản của mình cho phép.",
        ),
        "tp_col_agent": ("Agent", "Tác tử"),
        "tp_col_variant": ("Version", "Phiên bản"),
        "tp_col_last": ("Last report", "Báo cáo gần nhất"),
        "tp_col_ver": ("No.", "Số"),
        "tp_col_files": ("Files", "Tệp"),
        "tp_col_state": ("State", "Tình trạng"),
        "tp_generate": ("Generate", "Tạo báo cáo"),
        "tp_generate_all": ("Create all versions", "Tạo mọi phiên bản"),
        "tp_never": ("never", "chưa có"),
        "tp_preview_line": ("Preview based on current data", "Xem trước theo dữ liệu hiện tại"),
        "tp_unchanged": (
            "Nothing changed since version {v}: no new version was made.",
            "Không có gì thay đổi từ phiên bản {v}: không tạo phiên bản mới.",
        ),
        "tp_generated": (
            "Report version {v} created and signed into the evidence chain.",
            "Đã tạo báo cáo phiên bản {v} và ký vào chuỗi bằng chứng.",
        ),
        "tp_download": ("Download", "Tải về"),
        "tp_open_page": ("Open the Transparency page", "Mở trang Minh bạch"),
        "tp_tab_off": (
            "Transparency reports are off for this installation.",
            "Báo cáo minh bạch đang tắt trong bản cài đặt này.",
        ),
        "tp_no_pdf": (
            "PDF needs the optional fpdf2 package and a Unicode font on this server. Without them, only JSON and HTML are made.",
            "Tệp PDF cần gói tùy chọn fpdf2 và phông Unicode trên máy chủ này. Nếu thiếu, chỉ tạo JSON và HTML.",
        ),
        "tp_no_agents": ("No agents are registered.", "Chưa có tác tử nào được đăng ký."),
        "tp_sections_ok": ("{n} of {m} sections have data", "{n} trên {m} phần có dữ liệu"),
    }
)


# --- WP39 --- verdict v2 drawer, filters, export, analytics tables, alert use cases
_T.update(
    {
        "decisions_purpose_v2": (
            "Every decision the gate made, with its verdict status, findings and coverage.",
            "Mọi quyết định của cổng, kèm trạng thái phán quyết, phát hiện và phạm vi kiểm tra.",
        ),
        "decisions_why_v2": (
            "Open a decision to see the request, response and findings.",
            "Mở một quyết định để xem yêu cầu, phản hồi và phát hiện.",
        ),
        "detection_code": ("Detection code", "Mã phát hiện"),
        "not_evaluated": ("Not assessed", "Chưa đánh giá"),
        "ne_only": ("Show only items not evaluated", "Chỉ hiện mục chưa được đánh giá"),
        "consumer": ("Calling application", "Ứng dụng gọi"),
        "direction": ("Direction", "Chiều"),
        "correlation_id": ("Correlation id", "Mã tương quan"),
        "detections": ("Detections", "Phát hiện"),
        "dir_input": ("input", "đầu vào"),
        "dir_output": ("output", "đầu ra"),
        "st_allow": ("Allow", "Cho phép"),
        "st_report": ("Report", "Báo cáo"),
        "st_transform": ("Transform", "Biến đổi"),
        "st_pause": ("Pause", "Tạm dừng"),
        "st_block": ("Block", "Chặn"),
        "st_skip": ("Skip", "Bỏ qua"),
        "ne_execution_failed": ("a detector failed", "một bộ phát hiện bị lỗi"),
        "ne_invalid_config": ("a detector had a bad setting", "một bộ phát hiện sai cấu hình"),
        "ne_payload_too_large": ("content too large", "nội dung quá lớn"),
        "ne_content_uninspectable": ("content could not be read", "không đọc được nội dung"),
        "ne_timed_out": ("a detector timed out", "một bộ phát hiện quá thời gian"),
        "ne_budget_exhausted": (
            "a detector used up its time or call limit",
            "một bộ phát hiện dùng hết giới hạn thời gian hoặc số lần gọi",
        ),
        "ne_skipped_by_policy": ("skipped by policy", "bị bỏ qua theo chính sách"),
        "ne_gate_failed": ("the gate could not decide", "cổng không thể quyết định"),
        "not_applicable": ("Not applicable", "Không áp dụng"),
        "ne_not_applicable_for_direction": (
            "not applicable to this direction",
            "không áp dụng cho chiều này",
        ),
        "dtab_request": ("Request", "Yêu cầu"),
        "dtab_response": ("Response", "Phản hồi"),
        "dtab_detections": ("Detections", "Phát hiện"),
        "dtab_metadata": ("Metadata", "Siêu dữ liệu"),
        "part_args": ("Inputs", "Tham số"),
        "part_tool_results": ("Tool results", "Kết quả công cụ"),
        "part_output": ("Output", "Đầu ra"),
        "request_note": (
            "Text is masked. The gate keeps only a keyed hash of the call details, not the details themselves.",
            "Văn bản đã được che. Cổng chỉ lưu mã băm có khóa của nội dung lệnh gọi, không lưu nội dung.",
        ),
        "no_request_text": ("No request text", "Không có văn bản yêu cầu"),
        "no_request_text_line": (
            "No masked text was saved for this call, or masking is not set up.",
            "Không có văn bản đã che nào được lưu cho lệnh gọi này, hoặc chưa thiết lập che dữ liệu.",
        ),
        "masked_record": ("Masked record (JSON)", "Bản ghi đã che (JSON)"),
        "decision": ("Decision", "Quyết định"),
        "allowed": ("allowed", "được phép"),
        "denied": ("denied", "bị từ chối"),
        "transformed_payload": ("Text after masking", "Nội dung sau khi che"),
        "transformed_note": (
            "Rebuilt from the masked record. The gate does not keep the text after masking.",
            "Dựng lại từ bản ghi đã che. Cổng không lưu văn bản sau khi che.",
        ),
        "no_transform": ("The content was not changed.", "Nội dung không bị thay đổi."),
        "detector": ("Detector", "Bộ phát hiện"),
        "code": ("Code", "Mã"),
        "entities": ("Entities and fragments (masked)", "Thực thể và đoạn (đã che)"),
        "action_hint": ("Action hint", "Gợi ý hành động"),
        "leaf_precision": ("whole text", "toàn văn bản"),
        "no_detections": ("No findings", "Không có phát hiện"),
        "no_detections_line": (
            "No automated check raised a finding on this decision.",
            "Không có kiểm tra tự động nào ghi nhận phát hiện cho quyết định này.",
        ),
        "located_fragments": ("Fragments in the masked text", "Đoạn trong văn bản đã che"),
        "unlocated_fragments": (
            "Text we could not place",
            "Đoạn văn bản chưa xác định được vị trí",
        ),
        "lat_total": ("Latency total", "Tổng độ trễ"),
        "lat_rules": ("Rules", "Quy tắc"),
        "lat_detectors": ("Detectors", "Bộ phát hiện"),
        "lat_overhead": ("Other processing", "Xử lý khác"),
        "open_trace_span": ("Open the trace span", "Mở đoạn dấu vết"),
        "same_correlation": (
            "{n} decisions belong to this request",
            "{n} quyết định thuộc cùng yêu cầu này",
        ),
        "open_alert": ("Open alert", "Mở cảnh báo"),
        "an_tab_detectors": ("Detectors", "Bộ phát hiện"),
        "dd_requests": ("Requests", "Yêu cầu"),
        "dd_none": ("No decisions in this period.", "Không có quyết định nào trong khoảng này."),
        "dd_empty": ("No daily summary yet", "Chưa có tổng hợp theo ngày"),
        "dd_empty_line": (
            "Run python -m supervisor.jobs.decision_rollup. The scheduler also runs it every hour.",
            "Chạy python -m supervisor.jobs.decision_rollup. Bộ lập lịch cũng tự chạy mỗi giờ.",
        ),
        "dd_series": (
            "Gate outcomes by day (daily summary)",
            "Kết quả của cổng theo ngày (tổng hợp theo ngày)",
        ),
        "dd_rollup_note": (
            "The chart and the four tables below use the daily summary. The tiles and the first table above count single gate calls in the period. The summary can include more traffic (for example, demo agent history), so totals can differ.",
            "Biểu đồ và bốn bảng bên dưới dùng tổng hợp theo ngày. Các ô và bảng đầu tiên ở trên đếm từng lệnh gọi qua cổng trong khoảng thời gian. Bản tổng hợp có thể gồm nhiều lưu lượng hơn (ví dụ lịch sử của tác tử demo), nên tổng số có thể khác.",
        ),
        "dd_per_agent": ("By agent (daily summary)", "Theo tác tử (tổng hợp theo ngày)"),
        "dd_per_consumer": ("Per application", "Theo ứng dụng"),
        "dd_per_rule": ("Per rule", "Theo quy tắc"),
        "dd_per_detector": ("Per detector and code", "Theo bộ phát hiện và mã"),
        "det_latency": ("Detector response time", "Thời gian phản hồi của bộ phát hiện"),
        "det_runs": ("Runs", "Lượt chạy"),
        "det_verdict": ("Test result", "Kết quả kiểm thử"),
        "det_adversarial": ("attack detection rate", "tỷ lệ phát hiện tấn công"),
        "det_approx": (
            "Over several days, p50 is the weighted average of the daily p50 and p95 is the highest daily p95. GO (indicative): the measured value passes, but the 95 percent interval does not prove it.",
            "Nhiều ngày: p50 là trung bình có trọng số của p50 từng ngày, p95 là p95 cao nhất trong ngày. GO (indicative): giá trị đo đạt, nhưng khoảng tin cậy 95 phần trăm chưa chứng minh.",
        ),
        "observed_mode": ("Mode", "Chế độ"),
        "mode_shadow": ("shadow", "chạy ngầm"),
        "observed_decision": ("Observed decision", "Quyết định quan sát được"),
        "would_block": (
            "would have blocked (not enforced)",
            "sẽ chặn nếu thực thi (chưa thực thi)",
        ),
        "would_pause": (
            "would have paused (not enforced)",
            "sẽ tạm dừng nếu thực thi (chưa thực thi)",
        ),
        "observed_approvals": ("Approvals", "Phê duyệt"),
        "approvals_yes": ("present", "có"),
        "approvals_no": ("not present", "không có"),
        "back_to_list": ("Back to the list", "Quay lại danh sách"),
        "det_not_run": ("not run", "chưa chạy"),
        "det_not_run_line": (
            "No test result recorded. Run python -m supervisor.detectors.harness --json DATA_DIR/eval/detectors_report.json",
            "Chưa có kết quả kiểm thử. Chạy python -m supervisor.detectors.harness --json DATA_DIR/eval/detectors_report.json",
        ),
        "dd_series_note": (
            "Counts each decision by its verdict, with Blocked ranked above Paused. The tiles above rank Paused above Blocked, so a call that matches both shows as Paused there and Blocked here.",
            "Đếm mỗi quyết định theo kết luận, ưu tiên Chặn hơn Tạm dừng. Các ô ở trên ưu tiên Tạm dừng hơn Chặn, nên một lệnh khớp cả hai hiện là Tạm dừng ở trên và Chặn ở đây.",
        ),
        "findings_chip": ("{n} findings", "{n} phát hiện"),
        "open_decision": ("Open the gate decision", "Mở quyết định của cổng"),
        "export_csv": ("Export CSV", "Xuất CSV"),
        "export_hint": (
            "Masked columns only, at most {n} rows.",
            "Chỉ các cột đã che, tối đa {n} dòng.",
        ),
        "export_done": (
            "CSV ready: {n} rows, {cols} columns.",
            "CSV đã sẵn sàng: {n} dòng, {cols} cột.",
        ),
        "export_once": (
            "This link works once, only for you, and expires in 15 minutes.",
            "Liên kết này chỉ dùng được một lần, chỉ cho bạn, và hết hạn sau 15 phút.",
        ),
    }
)


# --- Two-section sidebar (CONSOLE_NAV_SECTIONS) and the Catalog page (CONSOLE_CATALOG_ENABLED) ---
_T.update(
    {
        "nav_s_gov": ("AI Management and Governance", "Quản lý và quản trị AI"),
        "nav_s_gov_k": ("Governance", "Quản trị"),
        "nav_s_guard": ("AI Guardian and Supervisor", "Bảo vệ và giám sát AI"),
        "nav_s_guard_k": ("Runtime", "Vận hành"),
        "nav_g_protect": ("Protect", "Bảo vệ"),
        "nav_catalog": ("Catalog", "Danh mục"),
        "cat_lede": (
            "See which guardians this Supervisor offers.",
            "Xem các bộ bảo vệ mà Supervisor này cung cấp.",
        ),
        "cat_tab_catalog": ("Catalog", "Danh mục"),
        "cat_tab_active": ("Active", "Đang bật"),
        "cat_rule": (
            "Only deterministic rules block or pause an agent. Judges advise: they open a case "
            "or raise severity. Settings come from the environment and config/detectors.yaml; "
            "this page shows them and never changes them.",
            "Chỉ các quy tắc xác định mới chặn hoặc tạm dừng tác tử. Giám khảo chỉ tư vấn: mở hồ "
            "sơ hoặc nâng mức nghiêm trọng. Cài đặt lấy từ biến môi trường và "
            "config/detectors.yaml; trang này chỉ hiển thị, không thay đổi.",
        ),
        "cat_none": ("Nothing is on", "Chưa bật năng lực nào"),
        "cat_none_line": (
            "No capability is on in this instance.",
            "Không có năng lực nào đang bật trong phiên bản này.",
        ),
        "cat_on": ("On", "Đang bật"),
        "cat_turn_on": ("Turn on:", "Bật bằng:"),
        "cat_open": ("Open", "Mở"),
        "catg_gate": ("Gateway controls", "Kiểm soát tại cổng"),
        "catg_detect": ("Detectors", "Bộ phát hiện"),
        "catg_judge": ("AI judges and red team", "Giám khảo AI và red team"),
        "catg_monitor": ("Monitors", "Giám sát"),
        "catg_prove": ("Evidence and assurance", "Bằng chứng và bảo đảm"),
        "catg_connect": ("Connectors", "Kết nối"),
        "catk_blocks": ("Can block", "Có thể chặn"),
        "catk_transforms": ("Masks", "Che dữ liệu"),
        "catk_advises": ("Advises", "Tư vấn"),
        "catk_watches": ("Reports", "Báo cáo"),
        "catk_proves": ("Proves", "Chứng minh"),
        "cat_policy_rules": ("Policy rules", "Quy tắc chính sách"),
        "cat_policy_rules_d": (
            "Fixed rules for each agent and tool. A call can be allowed, logged, alerted, blocked or paused before it reaches the tool.",
            "Quy tắc cố định theo từng tác tử và công cụ. Lệnh gọi có thể được cho phép, ghi nhận, cảnh báo, chặn hoặc tạm dừng trước khi đến công cụ.",
        ),
        "cat_pause_switch": ("Pause switch and quarantine", "Công tắc tạm dừng và cách ly"),
        "cat_pause_switch_d": (
            "Pause or quarantine an agent: every later call is refused until a person resumes it.",
            "Tạm dừng hoặc cách ly tác tử: mọi lệnh gọi sau đó bị từ chối cho đến khi có người "
            "cho chạy lại.",
        ),
        "cat_session_monitor": ("Session monitor", "Giám sát phiên"),
        "cat_session_monitor_d": (
            "Scores a whole session (findings, spend, tool mix) and pauses the session above "
            "its threshold.",
            "Chấm điểm cả phiên (phát hiện, chi tiêu, loại công cụ) và tạm dừng phiên khi vượt "
            "ngưỡng.",
        ),
        "cat_ingress_auth": ("Agent credentials", "Thông tin xác thực tác tử"),
        "cat_ingress_auth_d": (
            "Each agent signs its gate checks and traces with its own credential; an unknown "
            "caller is refused.",
            "Mỗi tác tử ký yêu cầu kiểm tra và trace bằng thông tin xác thực riêng; bên gọi lạ "
            "bị từ chối.",
        ),
        "cat_mcp_gateway": ("MCP gateway", "Cổng MCP"),
        "cat_mcp_gateway_d": (
            "Puts the gate in front of MCP tools/call and scores tool descriptions from "
            "tools/list.",
            "Đặt cổng trước MCP tools/call và chấm điểm mô tả công cụ từ tools/list.",
        ),
        "cat_dlp_vn": ("Vietnamese data loss prevention", "Chống rò rỉ dữ liệu tiếng Việt"),
        "cat_dlp_vn_d": (
            "Finds Vietnamese personal data (CCCD, phone, account, address) in tool arguments "
            "and masks it on PII-export tools. WP-D2, optional: a secrets group (API keys, "
            "tokens, private keys, passwords) reported as secret findings, and your own keyword "
            "or regex rules.",
            "Tìm dữ liệu cá nhân tiếng Việt (CCCD, điện thoại, tài khoản, địa chỉ) trong tham số "
            "công cụ và che trên công cụ xuất dữ liệu cá nhân. WP-D2, tùy chọn: nhóm bí mật "
            "(khóa API, token, khóa riêng, mật khẩu) báo thành phát hiện bí mật, và quy tắc từ "
            "khóa hoặc regex của riêng bạn.",
        ),
        "cat_injection_regex": ("Prompt injection patterns", "Mẫu tấn công chèn lệnh"),
        "cat_injection_regex_d": (
            "Known prompt-injection patterns in Vietnamese and English; reports a finding, "
            "never blocks.",
            "Các mẫu chèn lệnh đã biết bằng tiếng Việt và tiếng Anh; báo phát hiện, không chặn.",
        ),
        "cat_injection_classifier": ("Indirect prompt injection", "Chèn lệnh gián tiếp"),
        "cat_injection_classifier_d": (
            "Local classifier over tool results and tool descriptions; may only pause money "
            "and credit tools.",
            "Bộ phân loại cục bộ trên kết quả và mô tả công cụ; chỉ được tạm dừng công cụ tiền "
            "và tín dụng.",
        ),
        "cat_inline_redaction": ("Data masking at the gate", "Che dữ liệu tại cổng"),
        "cat_inline_redaction_d": (
            "Hides amounts and personal data in the inputs of listed tools before the tool receives them.",
            "Che số tiền và dữ liệu cá nhân trong đầu vào của các công cụ được liệt kê trước khi công cụ nhận.",
        ),
        "cat_judge_tiers": ("Two-level AI judges", "Giám khảo AI hai tầng"),
        "cat_judge_tiers_d": (
            "AI judges review every conversation, and a second judge confirms. They open cases but never block a call.",
            "Giám khảo AI xem xét mọi cuộc hội thoại và giám khảo thứ hai xác nhận. Họ mở vụ việc nhưng không bao giờ chặn lệnh gọi.",
        ),
        "cat_judge_advisory": ("AI judge (advice only)", "Giám khảo AI (chỉ tư vấn)"),
        "cat_judge_advisory_d": (
            "Asks the Tier 1 judge for an opinion inside the gate call; report only, never "
            "fail closed.",
            "Hỏi ý kiến giám khảo tầng 1 trong lệnh gọi cổng; chỉ báo cáo, không bao giờ chặn "
            "khi lỗi.",
        ),
        "cat_redteam": ("Multi-turn red team", "Red team nhiều lượt"),
        "cat_redteam_d": (
            "Every night, tests each agent with simulated attack conversations in Vietnamese. Results feed the assurance tests.",
            "Mỗi đêm, thử từng tác tử bằng các cuộc hội thoại tấn công giả lập bằng tiếng Việt. Kết quả đưa vào bộ kiểm thử bảo đảm.",
        ),
        "cat_drift": ("Drift monitor", "Giám sát trôi dạt"),
        "cat_drift_d": (
            "Sets a normal range for each agent version. Opens a case when a metric stays outside it.",
            "Đặt dải bình thường cho từng phiên bản tác tử. Mở vụ việc khi một chỉ số liên tục nằm ngoài dải.",
        ),
        "cat_fairness": ("Fairness monitor", "Giám sát công bằng"),
        "cat_fairness_d": (
            "Compares approval and block rates across permitted customer groups. A gap above the threshold opens a case.",
            "So sánh tỷ lệ phê duyệt và chặn giữa các nhóm khách hàng được phép. Chênh lệch vượt ngưỡng sẽ mở vụ việc.",
        ),
        "cat_quality": ("Quality monitor", "Giám sát chất lượng"),
        "cat_quality_d": (
            "Scores customer replies on accuracy against sources and on the bank's reply guidelines.",
            "Chấm điểm câu trả lời khách hàng về độ chính xác so với nguồn và theo hướng dẫn trả lời của ngân hàng.",
        ),
        "cat_multiagent": ("Multi-agent monitor", "Giám sát đa tác tử"),
        "cat_multiagent_d": (
            "Finds a payment split across several agents to stay under a limit, and opens a case.",
            "Phát hiện khoản thanh toán bị chia qua nhiều tác tử để né hạn mức và mở vụ việc.",
        ),
        "cat_tool_analytics": ("Tool analytics", "Phân tích công cụ"),
        "cat_tool_analytics_d": (
            "Shows tool use by agent and flags tools that are granted but never used.",
            "Cho thấy mức dùng công cụ theo tác tử và chỉ ra công cụ được cấp nhưng không dùng.",
        ),
        "cat_alerts": ("Alerts", "Cảnh báo"),
        "cat_alerts_d": (
            "Turns monitor and gate signals into alerts with an owner and a deadline.",
            "Biến tín hiệu từ giám sát và cổng thành cảnh báo có người phụ trách và thời hạn.",
        ),
        "cat_evidence_chain": ("Tamper-proof evidence", "Bằng chứng chống sửa đổi"),
        "cat_evidence_chain_d": (
            "Every decision goes into a SHA-256 chain with a signed head; supervisor-verify "
            "checks it offline.",
            "Mọi quyết định được ghi vào chuỗi SHA-256 có đầu chuỗi được ký; supervisor-verify "
            "kiểm tra ngoại tuyến.",
        ),
        "cat_case_files": ("Case files", "Hồ sơ vụ việc"),
        "cat_case_files_d": (
            "One file per case with the decisions, verdicts and sign-offs an auditor needs.",
            "Mỗi vụ việc một hồ sơ gồm quyết định, phán quyết và phê duyệt mà kiểm toán viên cần.",
        ),
        "cat_assurance": ("Assurance tests", "Bộ kiểm thử bảo đảm"),
        "cat_assurance_d": (
            "Tests for the agent and its AI judge, with a go or no-go before launch.",
            "Bộ kiểm thử cho tác tử và giám khảo AI của nó, kết luận đạt hoặc không đạt trước khi triển khai.",
        ),
        "cat_transparency": ("Transparency report", "Báo cáo minh bạch"),
        "cat_transparency_d": (
            "A plain-language report per agent: what it does, its limits and its controls.",
            "Báo cáo dễ hiểu cho từng tác tử: chức năng, giới hạn và các biện pháp kiểm soát.",
        ),
        "cat_collectors": ("Activity collectors", "Bộ thu thập hoạt động"),
        "cat_collectors_d": (
            "Connect an agent framework so its activity is recorded.",
            "Kết nối framework của tác tử để hoạt động của nó được ghi lại.",
        ),
        "cat_siem": ("SIEM export", "Xuất sang SIEM"),
        "cat_siem_d": (
            "Sends gate decisions and alerts to the bank SIEM.",
            "Gửi quyết định của cổng và cảnh báo sang SIEM của ngân hàng.",
        ),
    }
)


_T.update(
    {
        # --- WP-G0: Systems pages (docs/governance.md) ---
        "nav_systems": ("Systems", "Hệ thống AI"),
        "sy_purpose": (
            "The bank's AI systems: who owns each, which stage it is in, and its risk level.",
            "Các hệ thống AI của ngân hàng: ai sở hữu, đang ở giai đoạn nào và mức rủi ro.",
        ),
        "sy_why": (
            "Governance works at the AI system level. Its risk level is the higher of the level you set and the level inherited from its linked agents and parts.",
            "Quản trị được thực hiện ở cấp hệ thống AI. Mức rủi ro là mức cao hơn giữa mức bạn đặt và mức kế thừa từ các tác tử và thành phần liên kết.",
        ),
        "sy_scope_note": (
            "You see AI systems you work on, own, or that your team owns.",
            "Bạn thấy các hệ thống AI bạn tham gia, sở hữu, hoặc do nhóm của bạn sở hữu.",
        ),
        "sy_tile_all": ("All systems", "Tất cả hệ thống"),
        "sy_tile_active": ("Active", "Đang hoạt động"),
        "sy_tile_high": ("High risk or more", "Rủi ro cao trở lên"),
        "sy_col_name": ("Name", "Tên"),
        "sy_col_team": ("Owner team", "Nhóm sở hữu"),
        "sy_col_stage": ("Stage", "Giai đoạn"),
        "sy_col_risk": ("Risk level", "Mức rủi ro"),
        "sy_col_components": ("Parts", "Thành phần"),
        "sy_no_systems": ("No AI systems", "Chưa có hệ thống AI"),
        "sy_no_systems_line": (
            "Register your first AI system with the form below.",
            "Đăng ký hệ thống AI đầu tiên bằng biểu mẫu bên dưới.",
        ),
        "sy_register": ("Register an AI system", "Đăng ký hệ thống AI"),
        "sy_register_hint": (
            "Fill in the required fields. The rest is added later or comes from linked parts. You become the owner.",
            "Điền các trường bắt buộc. Phần còn lại được bổ sung sau hoặc lấy từ các thành phần liên kết. Bạn là người sở hữu.",
        ),
        "sy_open": ("Open the system page", "Mở trang hệ thống"),
        "sy_dtab_team": ("Team", "Nhóm"),
        "sy_dtab_components": ("Parts", "Thành phần"),
        "sy_tab_overview": ("Overview", "Tổng quan"),
        "sy_tab_components": ("Components", "Thành phần"),
        "sy_effective": ("Effective risk level", "Mức rủi ro hiệu lực"),
        "sy_manual": ("Level set by a person", "Mức do người đặt"),
        "sy_inherited": ("Inherited level", "Mức kế thừa"),
        "sy_inherited_via": ("Inherited from", "Kế thừa từ"),
        "sy_source_manual": ("set by a person", "do người đặt"),
        "sy_source_inherited": ("inherited", "kế thừa"),
        "sy_source_classifier": ("from classification", "từ kết quả phân loại"),
        "sy_team_role": ("Team role", "Vai trò trong nhóm"),
        "sy_no_team": ("No team members.", "Chưa có thành viên."),
        "sy_no_components": (
            "No agents or parts are linked yet.",
            "Chưa liên kết tác tử hay thành phần nào.",
        ),
        "sy_ref": ("Linked item", "Mục liên kết"),
        "sy_link_role": ("Role", "Vai trò"),
        "sy_link_source": ("Source", "Nguồn"),
        "sy_yes": ("Yes", "Có"),
        "sy_no": ("No", "Không"),
        "sy_st_draft": ("Draft", "Bản nháp"),
        "sy_st_active": ("Active", "Đang hoạt động"),
        "sy_st_archived": ("Archived", "Đã lưu trữ"),
        "sy_stage_initiation": ("Initiation", "Khởi tạo"),
        "sy_stage_design": ("Design", "Thiết kế"),
        "sy_stage_validation": ("Validation", "Thẩm định"),
        "sy_stage_deployment": ("Deployment", "Triển khai"),
        "sy_stage_operation": ("Operation", "Vận hành"),
        "sy_stage_re_evaluation": ("Re-evaluation", "Đánh giá lại"),
        "sy_stage_retirement": ("Retirement", "Ngừng sử dụng"),
        "sy_risk_unspecified": ("Unspecified", "Chưa xác định"),
        "sy_risk_low": ("Low", "Thấp"),
        "sy_risk_medium": ("Medium", "Trung bình"),
        "sy_risk_high": ("High", "Cao"),
        "sy_risk_prohibited": ("Prohibited", "Bị cấm"),
        "sy_system_type_assistant": ("Assistant", "Trợ lý"),
        "sy_system_type_decision": ("Decision", "Ra quyết định"),
        "sy_system_type_automation": ("Automation", "Tự động hóa"),
        "sy_system_type_platform": ("Platform", "Nền tảng"),
        "sy_system_type_feature": ("Feature", "Tính năng"),
        "sy_org_role_provider": ("Provider", "Nhà cung cấp"),
        "sy_org_role_deployer": ("Deployer", "Bên triển khai"),
        "sy_org_role_both": ("Both", "Cả hai"),
        "sy_user_segment_internal": ("Internal", "Nội bộ"),
        "sy_user_segment_customer": ("Customer", "Khách hàng"),
        "sy_user_segment_partner": ("Partner", "Đối tác"),
        "sy_personal_data_none": ("None", "Không có"),
        "sy_personal_data_identifiable": ("Identifiable", "Nhận dạng được"),
        "sy_personal_data_pseudonymised": ("Pseudonymised", "Đã giả danh hóa"),
        "sy_personal_data_special": ("Special category", "Dữ liệu đặc biệt"),
        "sy_human_control_pre_approval": (
            "Approval before action",
            "Phê duyệt trước khi thực hiện",
        ),
        "sy_human_control_post_review": ("Review after action", "Xem xét sau khi thực hiện"),
        "sy_human_control_none": ("None", "Không có"),
        "sy_d33_high_risk": ("High risk", "Rủi ro cao"),
        "sy_d33_not_high_risk": ("Not high risk", "Không phải rủi ro cao"),
        "sy_d33_unclassified": ("Not classified", "Chưa phân loại"),
        "sy_impact_high": ("High", "Cao"),
        "sy_impact_medium": ("Medium", "Trung bình"),
        "sy_impact_low": ("Low", "Thấp"),
        "sy_impact_unspecified": ("Unspecified", "Chưa xác định"),
        "sy_role_system_owner": ("System owner", "Chủ hệ thống"),
        "sy_role_business_owner": ("Business owner", "Chủ nghiệp vụ"),
        "sy_role_technical_specialist": ("Technical specialist", "Chuyên viên kỹ thuật"),
        "sy_role_data_steward": ("Data steward", "Quản lý dữ liệu"),
        "sy_role_compliance_specialist": ("Compliance specialist", "Chuyên viên tuân thủ"),
        "sy_role_reviewer": ("Reviewer", "Người rà soát"),
        "sy_role_oversight_manager": ("Oversight manager", "Người giám sát"),
        "sy_ref_agent": ("Agent", "Tác tử"),
        "sy_ref_node": ("Inventory item", "Mục kiểm kê"),
        "sy_link_component_of": ("Component of", "Là thành phần của"),
        "sy_link_built_on": ("Built on", "Xây dựng trên"),
        "sy_link_depends_on": ("Depends on", "Phụ thuộc vào"),
        "sy_f_purpose": ("Purpose", "Mục đích"),
        "sy_f_owner_user": ("Owner", "Người sở hữu"),
        "sy_f_business_owner": ("Business owner", "Chủ nghiệp vụ"),
        "sy_f_system_type": ("Type", "Loại"),
        "sy_f_org_role": ("Role of the bank", "Vai trò của ngân hàng"),
        "sy_f_user_segment": ("Users", "Người dùng"),
        "sy_f_personal_data": ("Personal data", "Dữ liệu cá nhân"),
        "sy_f_money_movement": ("Moves money", "Chuyển tiền"),
        "sy_f_credit_decision": ("Makes credit decisions", "Đưa ra quyết định tín dụng"),
        "sy_f_human_control": ("Human control", "Kiểm soát của con người"),
        "sy_f_risk_justification": ("Risk justification", "Lý giải mức rủi ro"),
        "sy_f_decision33_class": ("Decision 33 class", "Phân loại theo Quyết định 33"),
        "sy_f_business_impact": ("Business impact", "Tác động nghiệp vụ"),
    }
)

# --- WP-UX4a --- CONSOLE_NAV_V3: merged sidebar, section tabs, overview pages, Workflows
_T.update(
    {
        "nv3_my": ("My overview", "Tổng quan của tôi"),
        "nv3_overview": ("Overview", "Tổng quan"),
        "nv3_gov": ("AI management", "Quản lý AI"),
        "nv3_gov_k": ("Governance", "Quản trị"),
        "nv3_sup": ("AI guardian", "Giám sát AI"),
        "nv3_sup_k": ("Supervisor", "Giám sát"),
        "nv3_systems": ("Systems", "Hệ thống"),
        "nv3_catalogues": ("Catalogues", "Danh mục"),
        "nv3_risks_controls": ("Risks & controls", "Rủi ro và kiểm soát"),
        "nv3_workflows": ("Workflows", "Quy trình"),
        "nv3_activity": ("Activity", "Hoạt động"),
        "nv3_guardians": ("Guardians", "Bộ bảo vệ"),
        "nv3_cases_alerts": ("Cases & alerts", "Vụ việc và cảnh báo"),
        "nv3_settings": ("Settings", "Cài đặt"),
        "nv3_close": ("Close", "Đóng"),
        "nv3_gear_none": (
            "No settings page is open to your role.",
            "Vai trò của bạn không có trang cài đặt nào.",
        ),
        "nv3_policies_code": ("Policies as code", "Chính sách dạng mã"),
        "nv3_on": ("on", "bật"),
        "nv3_off": ("off", "tắt"),
        "nv3_yes": ("yes", "có"),
        "nv3_no": ("no", "không"),
        "nv3_st_collectors_on": ("Data collection: on", "Thu thập dữ liệu: bật"),
        "nv3_st_collectors_off": ("Data collection: off", "Thu thập dữ liệu: tắt"),
        "nv3_st_ingress_on": ("Agents must sign in", "Tác tử phải xác thực"),
        "nv3_st_ingress_off": ("Agents do not need to sign in", "Tác tử không cần xác thực"),
        "nv3_st_audit_on": (
            "Console actions are logged",
            "Thao tác trên bảng điều khiển được ghi lại",
        ),
        "nv3_st_audit_off": ("Console action log is off", "Nhật ký thao tác đang tắt"),
        "nv3_st_auth": ("Sign-in: {kind}", "Đăng nhập: {kind}"),
        "nv3_st_mode": ("Mode: {mode}", "Chế độ: {mode}"),
        "nv3_st_policy": ("Rules in force (read only)", "Quy tắc đang áp dụng (chỉ đọc)"),
        # tabs
        "nv3_t_models": ("Models", "Mô hình"),
        "nv3_t_tools": ("Tools", "Công cụ"),
        "nv3_t_datasets": ("Datasets", "Bộ dữ liệu"),
        "nv3_t_mcp": ("MCP servers", "Máy chủ MCP"),
        "nv3_t_unmanaged": ("Inventory", "Kiểm kê"),
        "nv3_t_policies": ("Compliance", "Tuân thủ"),
        "nv3_t_obligations": ("Obligations", "Nghĩa vụ"),
        "nv3_t_library": ("Library", "Thư viện"),
        "nv3_t_rules": ("Rules", "Quy tắc"),
        "nv3_t_detectors": ("Detectors", "Bộ phát hiện"),
        "nv3_t_judges": ("Judges", "Bộ đánh giá AI"),
        "nv3_t_monitors": ("Monitors", "Bộ giám sát"),
        "nv3_t_packs": ("Packs", "Gói kiểm thử"),
        "nv3_t_approvals": ("Approvals", "Phê duyệt"),
        "nv3_t_evidence": ("Evidence", "Bằng chứng"),
        # scope and tiles
        "nv3_scope": ("Scope", "Phạm vi"),
        "nv3_scope_my": ("Mine", "Của tôi"),
        "nv3_scope_team": ("My team", "Nhóm của tôi"),
        "nv3_scope_all": ("All", "Tất cả"),
        "nv3_na": ("not available", "chưa có số liệu"),
        "nv3_tile_agents": ("Agents in scope", "Tác tử trong phạm vi"),
        "nv3_tile_models": ("Models in use", "Mô hình đang dùng"),
        "nv3_tile_cover": ("Guardian coverage", "Phạm vi bộ bảo vệ"),
        "nv3_tile_actions": ("Actions waiting", "Việc cần làm"),
        "nv3_tile_classified": ("Classification rate", "Tỷ lệ phân loại"),
        "nv3_tile_readiness": ("Control readiness", "Mức sẵn sàng của kiểm soát"),
        "nv3_tile_overdue": ("Overdue tasks", "Công việc quá hạn"),
        "nv3_tile_checked": ("Calls checked, 24 h", "Lệnh gọi đã kiểm tra, 24 giờ"),
        "nv3_tile_stopped": ("Stopped by a rule", "Bị quy tắc chặn"),
        "nv3_tile_cases": ("Open cases", "Vụ việc đang mở"),
        "nv3_unmanaged_n": ("{n} not managed", "{n} chưa quản lý"),
        "nv3_actions_split": (
            "{cases} cases · {approvals} approvals · {tasks} tasks",
            "{cases} vụ việc · {approvals} phê duyệt · {tasks} công việc",
        ),
        "nv3_classified_n": (
            "{n} of {of} agents have a Decision 33 class",
            "{n} trên {of} tác tử đã có phân loại Quyết định 33",
        ),
        "nv3_readiness_n": (
            "{n} of {of} control checks working",
            "{n} trên {of} kiểm tra kiểm soát đang hoạt động",
        ),
        "nv3_overdue_oldest": ("oldest: {d} days", "lâu nhất: {d} ngày"),
        "nv3_no_clock": (
            "no SBV reporting clock running",
            "không có đồng hồ báo cáo NHNN đang chạy",
        ),
        "nv3_cover_full": ("fully covered", "đủ"),
        "nv3_cover_below": ("below the minimum", "dưới mức tối thiểu"),
        "nv3_cover_master_off": (
            "Detectors are switched off, so no agent is covered.",
            "Bộ phát hiện đang tắt nên chưa có tác tử nào được bảo vệ.",
        ),
        # reasons a figure is not available
        "nv3_na_inventory_off": ("Inventory is switched off.", "Phần kiểm kê đang tắt."),
        "nv3_na_controls_off": ("Controls are switched off.", "Phần kiểm soát đang tắt."),
        "nv3_na_risks_off": ("The risk register is switched off.", "Sổ rủi ro đang tắt."),
        "nv3_na_compliance_off": ("The compliance tab is switched off.", "Tab tuân thủ đang tắt."),
        "nv3_na_detector_file": (
            "Cannot read config/detectors.yaml.",
            "Không đọc được config/detectors.yaml.",
        ),
        "nv3_na_no_mandatory": (
            "No detector in config/detectors.yaml is set to fail_closed.",
            "Chưa bộ phát hiện nào trong config/detectors.yaml được đặt fail_closed.",
        ),
        "nv3_na_no_agents": ("No agent is in scope.", "Không có tác tử nào trong phạm vi."),
        "nv3_na_no_status": (
            "No control status yet (the control_status job has not run).",
            "Chưa có trạng thái kiểm soát (tác vụ control_status chưa chạy).",
        ),
        # My overview
        "nv3_my_sub": (
            "{agents} agents in scope. {actions} actions wait on you. {cases} cases are open.",
            "{agents} tác tử trong phạm vi. {actions} việc đang chờ bạn. {cases} vụ việc đang mở.",
        ),
        "nv3_health_agents": ("Health per agent", "Tình trạng từng tác tử"),
        "nv3_c_risk": ("Risk tier", "Mức rủi ro"),
        "nv3_c_guardian": ("Guardian", "Bộ bảo vệ"),
        "nv3_c_cases": ("Open cases", "Vụ việc mở"),
        "nv3_c_coverage": ("Gate coverage", "Phạm vi cổng bảo vệ"),
        "nv3_no_agents": ("No agent in this scope", "Không có tác tử trong phạm vi này"),
        "nv3_no_agents_line": (
            "Change the scope to see more agents.",
            "Đổi phạm vi để xem thêm tác tử.",
        ),
        "nv3_waiting": ("Actions waiting on me", "Việc đang chờ tôi"),
        "nv3_waiting_none": ("Nothing waits on you", "Không có việc nào chờ bạn"),
        "nv3_waiting_none_line": (
            "Cases assigned to you, approvals and required tasks show here.",
            "Vụ việc được giao, phê duyệt và công việc bắt buộc dành cho bạn sẽ hiện ở đây.",
        ),
        "nv3_c_what": ("Action", "Việc cần làm"),
        "nv3_c_kind": ("Kind", "Loại"),
        "nv3_kind_case": ("case", "vụ việc"),
        "nv3_kind_approval": ("approval", "phê duyệt"),
        "nv3_kind_task": ("task", "công việc"),
        "nv3_inbox_n": ("{n} unread notices", "{n} thông báo chưa đọc"),
        "nv3_recent": ("Recent events", "Sự kiện gần đây"),
        # Governance overview
        "nv3_gov_overview": ("Governance overview", "Tổng quan quản trị"),
        "nv3_gov_sub": ("All {n} agents in scope.", "Toàn bộ {n} tác tử trong phạm vi."),
        "nv3_by_stage": ("By lifecycle stage", "Theo giai đoạn vòng đời"),
        "nv3_c_stage": ("Stage", "Giai đoạn"),
        "nv3_c_open_required": ("Required tasks open", "Công việc bắt buộc đang mở"),
        "nv3_risk_posture": ("Risk overview", "Tổng quan rủi ro"),
        "nv3_c_band": ("Band", "Mức"),
        "nv3_c_risks": ("Active risks", "Rủi ro hiện hành"),
        "nv3_c_treated": ("Treated", "Đã xử lý"),
        "nv3_c_accepted": ("Accepted", "Chấp nhận"),
        "nv3_no_risks": ("No active risks in scope.", "Không có rủi ro hiện hành trong phạm vi."),
        "nv3_policy_impl": ("Policy implementation", "Triển khai chính sách"),
        "nv3_c_obligations": ("Obligations that apply", "Nghĩa vụ áp dụng"),
        "nv3_c_met": ("Met", "Đã đạt"),
        "nv3_c_gap": ("Not met", "Chưa đạt"),
        "nv3_c_progress": ("Progress", "Tiến độ"),
        "nv3_no_matrix": (
            "No compliance matrix for the agents in scope.",
            "Chưa có ma trận tuân thủ cho các tác tử trong phạm vi.",
        ),
        "nv3_policy_note": (
            "From the advisory compliance matrix. Not legal advice. Bank counsel confirms.",
            "Lấy từ ma trận tuân thủ mang tính tham khảo. Không phải tư vấn pháp lý. Pháp chế ngân hàng xác nhận.",
        ),
        # Supervisor overview
        "nv3_sup_overview": ("Supervisor overview", "Tổng quan giám sát"),
        "nv3_sup_sub": (
            "How the {n} agents in scope are running.",
            "Tình hình vận hành của {n} tác tử trong phạm vi.",
        ),
        "nv3_c_blocks": ("Stopped, 24 h", "Bị chặn 24 giờ"),
        "nv3_c_detectors": ("Detectors", "Bộ phát hiện"),
        "nv3_c_p95": ("Latency p95", "Độ trễ p95"),
        "nv3_capped": (
            "scan limit reached, newest items only",
            "đạt giới hạn quét, chỉ hiển thị mục mới nhất",
        ),
        "nv3_classified_note": (
            "Classified means a Decision 33 class is set for the agent. A suggestion from Onboard does not count.",
            "Đã phân loại nghĩa là tác tử đã có phân loại Quyết định 33. Đề xuất từ Tiếp nhận chưa được tính.",
        ),
        "nv3_ast_active": ("in use", "đang dùng"),
        "nv3_ast_unmanaged": ("not managed", "chưa quản lý"),
        "nv3_ast_allowlisted": ("approved to run", "được phép dùng"),
        "nv3_ast_gone": ("no longer found", "không còn tìm thấy"),
        "nv3_stage_initiation": ("initiation", "khởi tạo"),
        "nv3_stage_design": ("design", "thiết kế"),
        "nv3_stage_validation": ("validation", "thẩm định"),
        "nv3_stage_deployment": ("deployment", "triển khai"),
        "nv3_stage_operation": ("operation", "vận hành"),
        "nv3_stage_re_evaluation": ("re-evaluation", "đánh giá lại"),
        "nv3_stage_retirement": ("retirement", "ngừng sử dụng"),
        "nv3_wf_scheduler": ("Scheduler", "Bộ lập lịch"),
        "nv3_ms": ("{ms} ms", "{ms} mili giây"),
        "nv3_checked_sub": ("across {n} agents", "trên {n} tác tử"),
        "nv3_no_task_list": ("no task list yet", "chưa có danh sách công việc"),
        "nv3_c_chain": ("Evidence", "Bằng chứng"),
        "nv3_alerts_7d": ("Alerts, last 7 days", "Cảnh báo 7 ngày qua"),
        "nv3_c_rule": ("Rule", "Quy tắc"),
        "nv3_c_count": ("Count", "Số lượng"),
        "nv3_no_alerts": (
            "No alerts in the last 7 days.",
            "Không có cảnh báo nào trong 7 ngày qua.",
        ),
        "nv3_judges_packs": ("AI judges and test packs", "Bộ đánh giá AI và gói kiểm thử"),
        "nv3_c_item": ("Item", "Mục"),
        "nv3_no_model": ("no AI judge model set", "chưa chọn mô hình cho bộ đánh giá AI"),
        "nv3_last_pack": ("Test packs, latest run", "Gói kiểm thử, lần chạy gần nhất"),
        "nv3_pack_counts": (
            "{ok} passed · {warn} warnings · {fail} failed",
            "{ok} đạt · {warn} cảnh báo · {fail} không đạt",
        ),
        "nv3_no_pack": ("not run yet", "chưa chạy"),
        # Catalogues and Guardians tabs
        "nv3_c_name": ("Name", "Tên"),
        "nv3_c_own_risk": ("Own risk", "Rủi ro riêng"),
        "nv3_c_last_seen": ("Last seen", "Thấy lần cuối"),
        "nv3_unspecified": ("unspecified", "chưa xác định"),
        "nv3_assets_none": ("Nothing listed yet", "Chưa có mục nào"),
        "nv3_assets_none_line": (
            "Run python -m supervisor.jobs.inventory to fill the list.",
            "Chạy python -m supervisor.jobs.inventory để lập danh sách.",
        ),
        "nv3_g_lede_detectors": (
            "Checks that run on every call through the gate. Only dlp_vn may change a call. The others only report.",
            "Các kiểm tra chạy trên mọi lệnh gọi qua cổng. Chỉ dlp_vn được sửa nội dung lệnh gọi. Các kiểm tra khác chỉ báo cáo.",
        ),
        "nv3_g_lede_judges": (
            "AI judges advise only. They can open a case or raise severity. They never block a call.",
            "Bộ đánh giá AI chỉ tư vấn. Chúng có thể mở vụ việc hoặc nâng mức độ, nhưng không chặn lệnh gọi.",
        ),
        "nv3_g_lede_monitors": (
            "Monitors watch agent behaviour over time. They open cases or alerts.",
            "Bộ giám sát theo dõi hành vi tác tử theo thời gian và mở vụ việc hoặc cảnh báo.",
        ),
        "nv3_c_detector": ("Detector", "Bộ phát hiện"),
        "nv3_c_in_file": ("In the config file", "Trong tệp cấu hình"),
        "nv3_c_mandatory": ("Mandatory", "Bắt buộc"),
        "nv3_mandatory_note": (
            "Mandatory means fail_closed in config/detectors.yaml. An agent is fully covered when all mandatory detectors are on for it.",
            "Bắt buộc nghĩa là fail_closed trong config/detectors.yaml. Tác tử được bảo vệ đầy đủ khi mọi bộ phát hiện bắt buộc đều bật cho tác tử đó.",
        ),
        # Workflows
        "nv3_wf_lede": (
            "Automatic jobs and rules. View only.",
            "Các công việc và quy tắc tự động. Chỉ xem.",
        ),
        "nv3_c_workflow": ("Workflow", "Quy trình"),
        "nv3_c_every": ("How often", "Tần suất"),
        "nv3_c_last_run": ("Last run", "Lần chạy cuối"),
        "nv3_kind_wf_job": ("scheduled job", "tác vụ theo lịch"),
        "nv3_kind_wf_alert": ("alert rule", "quy tắc cảnh báo"),
        "nv3_kind_wf_approval": ("approval", "phê duyệt"),
        "nv3_kind_wf_sink": ("evidence destination", "nơi lưu bằng chứng"),
        "nv3_wf_signoff": ("Case approval", "Phê duyệt vụ việc"),
        "nv3_wf_resume": ("Restart a paused agent", "Cho tác tử đang tạm dừng chạy lại"),
        "nv3_wf_waive": ("Waive a required task", "Miễn một công việc bắt buộc"),
        "nv3_wf_siem": ("SIEM export", "Xuất sang SIEM"),
        "nv3_wf_webhook": ("Webhook notices", "Thông báo webhook"),
        "nv3_wfd_signoff": (
            "two people for high and critical cases",
            "hai người cho vụ việc mức cao và nghiêm trọng",
        ),
        "nv3_wfd_resume": ("the owner and a reviewer", "chủ sở hữu và một người rà soát"),
        "nv3_wfd_waive": ("a reason and a second approver", "cần lý do và người phê duyệt thứ hai"),
        "nv3_wf_sched_none": (
            "not running here, so job status is not available",
            "không chạy tại đây nên chưa có trạng thái tác vụ",
        ),
        "nv3_wf_rules_unreadable": (
            "Cannot read config/alerts.yaml, so alert rules are not listed.",
            "Không đọc được config/alerts.yaml nên không liệt kê quy tắc cảnh báo.",
        ),
        "nv3_threshold": ("threshold {n}", "ngưỡng {n}"),
        "nv3_never": ("Never run", "Chưa chạy lần nào"),
        "nv3_wf_note": (
            "Assignment rules, the Decision 33 question flow and event actions will be listed here once they are set up.",
            "Quy tắc phân công, luồng câu hỏi Quyết định 33 và hành động theo sự kiện sẽ được liệt kê ở đây khi được thiết lập.",
        ),
    }
)


_T.update(
    {
        # --- WP-G1: Tasks and Reviews tabs of the system page (docs/governance.md) ---
        "sy_tab_tasks": ("Tasks", "Nhiệm vụ"),
        "sy_tab_reviews": ("Reviews", "Rà soát"),
        "sy_stage_now": ("Stage of the system", "Giai đoạn của hệ thống"),
        "sy_stage_needs_approval": (
            "A move into these stages needs an approval",
            "Chuyển sang các giai đoạn này cần được phê duyệt",
        ),
        "sy_ap_move": ("Move", "Chuyển"),
        "sy_ap_requested_by": ("Asked by", "Người đề nghị"),
        "sy_ap_decided_by": ("Answered by", "Người trả lời"),
        "sy_ap_when": ("Date", "Ngày"),
        "sy_ap_st_pending": ("Waiting", "Đang chờ"),
        "sy_ap_st_approved": ("Approved", "Đã duyệt"),
        "sy_ap_st_rejected": ("Rejected", "Từ chối"),
        "sy_ap_applied": ("used for the move", "đã dùng để chuyển"),
        "sy_ap_none": ("No stage approvals yet.", "Chưa có phê duyệt giai đoạn."),
        "sy_tasks_no_agents": (
            "No agent is linked to this system, so there is no task list.",
            "Chưa có tác tử nào liên kết với hệ thống này nên chưa có danh sách nhiệm vụ.",
        ),
        "sy_tasks_initiation_only": (
            "The risk level is not set yet. Only initiation tasks show until someone sets it.",
            "Chưa đặt mức rủi ro. Chỉ hiện các nhiệm vụ khởi tạo cho đến khi có người đặt mức.",
        ),
        "sy_rv_title": ("Review", "Rà soát"),
        "sy_rv_kind": ("Kind", "Loại"),
        "sy_rv_kind_internal": ("Internal", "Nội bộ"),
        "sy_rv_kind_external": ("External", "Bên ngoài"),
        "sy_rv_kind_conformity": ("Conformity", "Đánh giá sự phù hợp"),
        "sy_rv_kind_classification_audit": ("Classification audit", "Kiểm toán phân loại"),
        "sy_rv_reviewer": ("Reviewer", "Người rà soát"),
        "sy_rv_window": ("Period", "Khoảng thời gian"),
        "sy_rv_reports": ("Reports", "Báo cáo"),
        "sy_rv_st_planned": ("Planned", "Đã lên kế hoạch"),
        "sy_rv_st_in_progress": ("In progress", "Đang thực hiện"),
        "sy_rv_st_completed": ("Completed", "Hoàn tất"),
        "sy_rv_st_reopened": ("Reopened", "Mở lại"),
        "sy_rv_locked": ("locked", "đã khóa"),
        "sy_rv_reopened_n": ("reopened {n} times", "mở lại {n} lần"),
        "sy_rv_none": (
            "No reviews yet. Reviews start at the Validation stage.",
            "Chưa có đợt rà soát. Rà soát bắt đầu ở giai đoạn Thẩm định.",
        ),
    }
)


# --- WP-UX4b --- governance pages on the AI system: tabs, register wizard, overviews on systems
_T.update(
    {
        # tabs of the system page
        "ux4b_tab_reports": ("Reports", "Báo cáo"),
        "ux4b_risks_sum": ("Risks affecting this system", "Rủi ro ảnh hưởng đến hệ thống này"),
        "ux4b_risks_line": (
            "{active} active risks, {inherited} of them inherited from a part the system uses.",
            "{active} rủi ro đang áp dụng, trong đó {inherited} rủi ro thừa hưởng từ thành "
            "phần hệ thống sử dụng.",
        ),
        "ux4b_risks_worst": ("Highest residual score", "Điểm rủi ro còn lại cao nhất"),
        "ux4b_inherited_from": ("Inherited from", "Thừa hưởng từ"),
        "ux4b_risks_none": (
            "No active risk reaches this system.",
            "Không có rủi ro đang áp dụng nào chạm tới hệ thống này.",
        ),
        "ux4b_risks_none_line": (
            "Link an agent that has risks, or add a risk on the Risks page.",
            "Hãy liên kết tác tử có rủi ro, hoặc thêm rủi ro ở trang Rủi ro.",
        ),
        "ux4b_agents_unregistered": (
            "Linked agents that are not registered",
            "Tác tử đã liên kết nhưng chưa đăng ký",
        ),
        "ux4b_policies_sum": ("Duties that apply", "Nghĩa vụ áp dụng"),
        "ux4b_na_no_matrix": (
            "No linked agent has a compliance matrix yet.",
            "Chưa có tác tử nào liên kết có ma trận tuân thủ.",
        ),
        "ux4b_policies_source": ("Matrices read from", "Ma trận đọc từ"),
        "ux4b_policies_rule": ("{n} duties assigned by rules", "{n} nghĩa vụ do quy tắc gán"),
        "ux4b_policies_missing": (
            "Agents with no compliance matrix (not counted as met or gap)",
            "Tác tử chưa có ma trận tuân thủ (không tính là đạt hay thiếu)",
        ),
        "ux4b_class_approval_unchecked": (
            "Not classified yet. Approval before the action is declared, but the system does not check it. A reviewer confirms.",
            "Chưa phân loại. Có khai báo phê duyệt trước khi thực hiện, nhưng hệ thống chưa kiểm tra. Người có thẩm quyền xác nhận.",
        ),
        "ux4b_class_none_declared": (
            "Not classified yet. No money movement or credit decision declared. A reviewer classifies.",
            "Chưa phân loại. Chưa khai báo chuyển tiền hay quyết định tín dụng. Người có thẩm quyền phân loại.",
        ),
        "ux4b_na_repo_disabled": (
            "The readiness check is switched off. Ask an administrator to set ONBOARD_ALLOWED_ROOTS.",
            "Kiểm tra mức sẵn sàng đang tắt. Hãy nhờ quản trị viên đặt ONBOARD_ALLOWED_ROOTS.",
        ),
        "ux4b_na_time_limit": (
            "The readiness check took longer than 30 s and stopped.",
            "Kiểm tra mức sẵn sàng quá 30 giây nên đã dừng.",
        ),
        "ux4b_intake_missing": (
            "Draft registered, but the intake tasks were not created. Try again.",
            "Bản nháp đã đăng ký, nhưng chưa tạo được các nhiệm vụ khai báo. Hãy thử lại.",
        ),
        "ux4b_intake_retry": ("Create the intake tasks", "Tạo các nhiệm vụ khai báo"),
        "ux4b_dimname_accuracy": ("Accuracy", "Độ chính xác"),
        "ux4b_dimname_hallucination": ("Hallucination", "Ảo giác"),
        "ux4b_dimname_bias_fairness": ("Bias and fairness", "Thiên lệch và công bằng"),
        "ux4b_dimname_dependency": ("Dependency", "Phụ thuộc"),
        "ux4b_dimname_security": ("Security", "Bảo mật"),
        "ux4b_dimname_robustness": ("Robustness", "Độ bền vững"),
        "ux4b_gate_required": ("required", "bắt buộc"),
        "ux4b_gate_advisory": ("advice only", "chỉ khuyến nghị"),
        "ux4b_gate_off": ("off", "tắt"),
        "ux4b_class_open_questions": (
            "Some questions need a reviewer, so this class is only a suggestion. After you register, find the draft on the Classification tab.",
            "Một số câu hỏi cần người có thẩm quyền trả lời, nên phân loại này chỉ là đề xuất. Sau khi đăng ký, bạn xem bản nháp ở tab Phân loại.",
        ),
        "ux4b_instrument": ("Regulation", "Văn bản quy định"),
        "ux4b_partial": ("Partial", "Một phần"),
        "ux4b_binding": ("binding", "có hiệu lực bắt buộc"),
        "ux4b_policies_gaps": ("Duties with a gap", "Nghĩa vụ còn thiếu"),
        "ux4b_obligation": ("Duty", "Nghĩa vụ"),
        "ux4b_more": ("{n} more not shown.", "Còn {n} mục không hiển thị."),
        "ux4b_policies_none": ("No duty applies yet.", "Chưa có nghĩa vụ nào áp dụng."),
        "ux4b_policies_none_line": (
            "No duty is marked as applying in the compliance matrices.",
            "Chưa có nghĩa vụ nào được đánh dấu là áp dụng trong các ma trận tuân thủ.",
        ),
        "ux4b_detectors_on": ("Detectors on", "Bộ phát hiện đang bật"),
        "ux4b_mandatory_file": (
            "Mandatory in config/detectors.yaml (fail_closed)",
            "Bắt buộc trong config/detectors.yaml (fail_closed)",
        ),
        "ux4b_floor": ("Minimum required guardians", "Bộ bảo vệ tối thiểu bắt buộc"),
        "ux4b_floor_none": (
            "No rule assigns a guardian to this system.",
            "Chưa có quy tắc nào gán bộ bảo vệ cho hệ thống này.",
        ),
        "ux4b_guardians_readonly": (
            "View only. Switching guardians on or off per system is not available yet.",
            "Chỉ xem. Chưa thể bật hoặc tắt bộ bảo vệ cho từng hệ thống.",
        ),
        "ux4b_na_no_rules": (
            "Rule-based assignment is not available in this version.",
            "Phiên bản này chưa có tính năng gán theo quy tắc.",
        ),
        "ux4b_na_transparency_off": (
            "Transparency reports are off (TRANSPARENCY_ENABLED=1 turns them on).",
            "Báo cáo minh bạch đang tắt (TRANSPARENCY_ENABLED=1 để bật).",
        ),
        "ux4b_chain": ("Evidence chain", "Chuỗi bằng chứng"),
        "ux4b_lane": ("Lane", "Làn"),
        "ux4b_entries": ("Entries", "Số bản ghi"),
        "ux4b_audit_pack": ("Audit pack", "Gói kiểm toán"),
        "ux4b_audit_pack_line": (
            "The pack covers the whole chain and is built on the Evidence page.",
            "Gói bao phủ cả chuỗi và được tạo ở trang Bằng chứng.",
        ),
        "ux4b_audit_pack_open": ("Open the Evidence page", "Mở trang Bằng chứng"),
        "ux4b_incidents": ("Incidents", "Sự cố"),
        "ux4b_na_incidents_flag": (
            "Incidents are switched off. Ask an administrator to set GOVERNANCE_ACTIONS_ENABLED=1.",
            "Sự cố đang tắt. Hãy nhờ quản trị viên đặt GOVERNANCE_ACTIONS_ENABLED=1.",
        ),
        # register wizard
        "ux4b_register_wizard": ("Register a system", "Đăng ký hệ thống"),
        "ux4b_wiz_title": ("Register an AI system", "Đăng ký hệ thống AI"),
        "ux4b_wiz_steps": ("Steps", "Các bước"),
        "ux4b_step_intake": ("Intake", "Khai báo"),
        "ux4b_step_checks": ("Preliminary checks", "Kiểm tra sơ bộ"),
        "ux4b_step_register": ("Register the draft", "Đăng ký bản nháp"),
        "ux4b_wiz_hint": (
            "Answer the intake questions. Preliminary checks run on the next page. Nothing is saved until you confirm.",
            "Trả lời các câu hỏi khai báo. Kiểm tra sơ bộ chạy ở trang tiếp theo. Chưa lưu gì cho đến khi bạn xác nhận.",
        ),
        "ux4b_wiz_scope": (
            "You can register only for yourself, in a team you already work in: {teams}.",
            "Bạn chỉ đăng ký được cho chính mình, trong nhóm bạn đang làm việc: {teams}.",
        ),
        "ux4b_f_autonomy": ("Autonomy level", "Mức tự chủ"),
        "ux4b_autonomy_unset": ("not set", "chưa đặt"),
        "ux4b_autonomy_l0_rule_based": ("L0 Rule based", "L0 Theo quy tắc"),
        "ux4b_autonomy_l1_assistive": ("L1 Assistive", "L1 Hỗ trợ"),
        "ux4b_autonomy_l2_workflow_step": ("L2 Workflow step", "L2 Một bước quy trình"),
        "ux4b_autonomy_l3_tool_using_supervised": (
            "L3 Uses tools, supervised",
            "L3 Dùng công cụ, có giám sát",
        ),
        "ux4b_autonomy_l4_autonomous_bounded": (
            "L4 Autonomous, bounded",
            "L4 Tự chủ có giới hạn",
        ),
        "ux4b_autonomy_l5_self_directed": ("L5 Self directed", "L5 Tự định hướng"),
        "ux4b_f_repo": ("Repository folder (optional)", "Thư mục mã nguồn (không bắt buộc)"),
        "ux4b_f_repo_hint": (
            "Add a folder and the checks also review how ready your code is to connect. The folder is only read and must be in a git repository.",
            "Nếu có thư mục, kiểm tra sẽ đánh giá thêm mức sẵn sàng kết nối của mã nguồn. Thư mục chỉ được đọc và phải nằm trong một kho git.",
        ),
        "ux4b_run_checks": ("Run the preliminary checks", "Chạy kiểm tra sơ bộ"),
        "ux4b_cancel": ("Cancel", "Hủy"),
        "ux4b_back": ("Back to the form", "Quay lại biểu mẫu"),
        "ux4b_nothing_applied": ("Nothing is applied.", "Chưa áp dụng gì."),
        "ux4b_nothing_applied_line": (
            "These are suggestions. Registering saves a draft and opens the intake tasks. A reviewer sets the class and risk level later.",
            "Đây chỉ là đề xuất. Đăng ký sẽ lưu bản nháp và mở các nhiệm vụ khai báo. Người có thẩm quyền sẽ đặt phân loại và mức rủi ro sau.",
        ),
        "ux4b_readiness": ("Integration readiness", "Mức sẵn sàng tích hợp"),
        "ux4b_readiness_line": (
            "Folder {folder}: {tools} tools found, {patches} fixes suggested.",
            "Thư mục {folder}: tìm thấy {tools} công cụ, đề xuất {patches} bản sửa.",
        ),
        "ux4b_readiness_note": (
            "Based on a code scan only. No AI model produced these numbers. The rating is advice, not a decision.",
            "Chỉ dựa trên quét mã nguồn. Không có mô hình AI nào tạo ra các số này. Mức đánh giá chỉ là khuyến nghị, không phải quyết định.",
        ),
        "ux4b_area": ("Area", "Hạng mục"),
        "ux4b_points": ("Points", "Điểm"),
        "ux4b_band_ready": (
            "Ready to start in monitor-only mode",
            "Sẵn sàng chạy ở chế độ chỉ theo dõi",
        ),
        "ux4b_band_patches": (
            "Apply the suggested fixes first",
            "Cần áp dụng các bản sửa đề xuất trước",
        ),
        "ux4b_band_work": ("Needs work first", "Cần xử lý trước"),
        "ux4b_na_no_repo": (
            "No repository folder was given.",
            "Chưa cung cấp thư mục mã nguồn.",
        ),
        "ux4b_na_advisor_failed": (
            "The readiness check could not read this folder. Check the path and try again.",
            "Kiểm tra mức sẵn sàng không đọc được thư mục này. Hãy kiểm tra đường dẫn và thử lại.",
        ),
        "ux4b_class": ("Suggested risk class", "Phân loại rủi ro đề xuất"),
        "ux4b_class_level": ("Suggested risk level: {level}", "Mức rủi ro đề xuất: {level}"),
        "ux4b_class_nolevel": (
            "No level suggested. A reviewer sets it.",
            "Chưa đề xuất mức. Người có thẩm quyền sẽ đặt.",
        ),
        "ux4b_class_src_declared": ("from your answers", "từ nội dung bạn đã khai"),
        "ux4b_class_src_rules": ("from the classification rules", "từ quy tắc phân loại"),
        "ux4b_class_because": ("Based on", "Dựa trên"),
        "ux4b_class_note": (
            "Under Decision 33, moving money or making a credit decision without prior human approval is high risk. A reviewer confirms the class.",
            "Theo Quyết định 33, chuyển tiền hoặc ra quyết định tín dụng mà không có người phê duyệt trước là rủi ro cao. Người có thẩm quyền xác nhận phân loại.",
        ),
        "ux4b_packs": ("Automated checks to run", "Kiểm tra tự động cần chạy"),
        "ux4b_packs_sub": ("for the declared system", "cho hệ thống đã khai báo"),
        "ux4b_pack": ("Check", "Kiểm tra"),
        "ux4b_dimension": ("Risk type", "Loại rủi ro"),
        "ux4b_why": ("Why", "Lý do"),
        "ux4b_gate": ("Launch gate", "Cổng ra mắt"),
        "ux4b_packs_note": (
            "Run them once an agent is linked: python -m supervisor.assurance run <pack> "
            "--target agent:<id>.",
            "Hãy chạy khi đã liên kết tác tử: python -m supervisor.assurance run <gói> "
            "--target agent:<id>.",
        ),
        "ux4b_na_packs": (
            "No automated checks apply, or their details could not be read.",
            "Không có kiểm tra tự động nào áp dụng, hoặc không đọc được thông tin của chúng.",
        ),
        "ux4b_dim_acts": (
            "the system answers or acts for people",
            "hệ thống trả lời hoặc hành động thay cho con người",
        ),
        "ux4b_dim_text": (
            "the system writes free text",
            "hệ thống viết văn bản tự do",
        ),
        "ux4b_dim_bias": (
            "credit decisions, a decision system or personal data",
            "quyết định tín dụng, hệ thống ra quyết định hoặc dữ liệu cá nhân",
        ),
        "ux4b_dim_dep": (
            "every system depends on a model provider or an API",
            "mọi hệ thống đều phụ thuộc nhà cung cấp mô hình hoặc API",
        ),
        "ux4b_dim_sec": (
            "every system can be attacked through its inputs",
            "mọi hệ thống đều có thể bị tấn công qua đầu vào",
        ),
        "ux4b_dim_rob": (
            "the system runs tools or data flows that can fail",
            "hệ thống chạy công cụ hoặc luồng dữ liệu có thể lỗi",
        ),
        "ux4b_confirm_line": (
            "Register this draft and start its intake tasks?",
            "Đăng ký bản nháp này và mở các nhiệm vụ khai báo?",
        ),
        "ux4b_register_draft": ("Register the draft", "Đăng ký bản nháp"),
        # overviews on systems
        "ux4b_tile_systems": ("Systems in scope", "Hệ thống trong phạm vi"),
        "ux4b_tile_cover": ("Guardian coverage (systems)", "Độ phủ bộ bảo vệ (hệ thống)"),
        "ux4b_cover_idle": (
            " · {n} without an agent",
            " · {n} chưa có tác tử",
        ),
        "ux4b_my_sub": (
            "You look after {systems} systems. {actions} items wait for you. {cases} cases are open.",
            "Bạn phụ trách {systems} hệ thống. {actions} việc đang chờ bạn. {cases} vụ việc đang mở.",
        ),
        "ux4b_actions_split": (
            "{cases} cases · {approvals} approvals · {tasks} tasks · {stages} stage moves",
            "{cases} ca · {approvals} phê duyệt · {tasks} nhiệm vụ · {stages} lần chuyển giai đoạn",
        ),
        "ux4b_kind_stage": ("Stage move", "Chuyển giai đoạn"),
        "ux4b_health_systems": ("Health of my systems", "Tình trạng các hệ thống của tôi"),
        "ux4b_system": ("System", "Hệ thống"),
        "ux4b_agents_n": ("Agents: {n}", "Tác tử: {n}"),
        "ux4b_next_action": ("Next action", "Việc tiếp theo"),
        "ux4b_no_systems": (
            "No system in this scope.",
            "Không có hệ thống nào trong phạm vi này.",
        ),
        "ux4b_no_systems_line": (
            "Register an AI system, or widen the scope.",
            "Hãy đăng ký hệ thống AI, hoặc mở rộng phạm vi.",
        ),
        "ux4b_na_no_systems": ("No system is in scope.", "Không có hệ thống nào trong phạm vi."),
        "ux4b_gov_sub": (
            "Totals for the systems you can view: {n} of {total}.",
            "Tổng hợp cho các hệ thống bạn được xem: {n} trong {total}.",
        ),
        "ux4b_classified_note": (
            "Classification rate: systems with a Decision 33 class set by a reviewer, out of all systems in scope.",
            "Tỷ lệ phân loại: số hệ thống đã được người có thẩm quyền đặt phân loại theo Quyết định 33, trên tổng số hệ thống trong phạm vi.",
        ),
        "ux4b_classified_n": ("{n} of {of} systems", "{n} trên {of} hệ thống"),
        "ux4b_by_stage": ("Systems by stage", "Hệ thống theo giai đoạn"),
        "ux4b_pending_approval": ("Pending approval", "Chờ phê duyệt"),
        "ux4b_ready_by_system": (
            "Control readiness by system",
            "Mức sẵn sàng kiểm soát theo hệ thống",
        ),
        "ux4b_controls_n": ("Controls with evidence", "Kiểm soát có bằng chứng"),
        "ux4b_policy_by_system": (
            "Policy implementation by system",
            "Thực hiện chính sách theo hệ thống",
        ),
        "ux4b_by_autonomy": ("Systems by autonomy level", "Hệ thống theo mức tự chủ"),
        # Catalogues > Agents
        "ux4b_col_system": ("System", "Hệ thống"),
        "ux4b_sys_linked": ("Linked to a system", "Đã liên kết hệ thống"),
        "ux4b_sys_unlinked": ("Unlinked", "Chưa liên kết"),
        "ux4b_sys_none": ("unlinked", "chưa liên kết"),
        "ux4b_sys_other": ("linked (another team)", "đã liên kết (nhóm khác)"),
    }
)

_T.update(
    {
        # --- WP-G5: Incidents tab of Cases & alerts, Reports tab of the system page ---------
        "sy_source_event": ("raised by a governance event", "do sự kiện quản trị nâng"),
        "nav_incidents": ("Incidents", "Sự cố"),
        "nv3_t_incidents": ("Incidents", "Sự cố"),
        "sy_tab_reports": ("Reports", "Báo cáo"),
        "inc_title": ("Incidents", "Sự cố"),
        "inc_purpose": (
            "Incidents made from governance events",
            "Sự cố được tạo từ các sự kiện quản trị",
        ),
        "inc_why": (
            "Alerts, gate stops, failed checks and escalations become incidents. Only a person can change the status or close one. Incidents never stop an agent.",
            "Cảnh báo, lần chặn của cổng, kiểm tra thất bại và leo thang trở thành sự cố. Chỉ con người mới đổi trạng thái hoặc đóng sự cố. Sự cố không bao giờ chặn tác tử.",
        ),
        "inc_incident": ("Incident", "Sự cố"),
        "inc_system": ("System", "Hệ thống"),
        "inc_kind": ("Kind", "Loại"),
        "inc_event_ref": ("Event", "Sự kiện"),
        "inc_root_cause": ("Root cause", "Nguyên nhân gốc"),
        "inc_affected": ("Affected scope", "Phạm vi ảnh hưởng"),
        "inc_closed_by": ("Closed by", "Người đóng"),
        "inc_active": ("Not closed", "Chưa đóng"),
        "inc_st_open": ("Open", "Mới"),
        "inc_st_investigating": ("Investigating", "Đang điều tra"),
        "inc_st_resolved": ("Resolved", "Đã xử lý"),
        "inc_st_closed": ("Closed", "Đã đóng"),
        "inc_kind_alert": ("Alert", "Cảnh báo"),
        "inc_kind_gate_stop": (
            "Risky tool call stopped at the gate",
            "Cổng chặn lệnh gọi công cụ rủi ro",
        ),
        "inc_kind_detector_failed": ("Detector failed", "Bộ phát hiện lỗi"),
        "inc_kind_monitor_failing": ("Monitor is failing", "Bộ giám sát đang lỗi"),
        "inc_kind_pack_no_go": ("Assurance NO-GO", "NO-GO của bài đánh giá"),
        "inc_kind_chain_break": ("Evidence chain broken", "Chuỗi bằng chứng bị đứt"),
        "inc_kind_model_version_change": ("Model version change", "Đổi phiên bản mô hình"),
        "inc_kind_judge_escalation": (
            "Judge escalated for review",
            "Giám khảo chuyển lên để xem xét",
        ),
        "inc_none": ("No incidents.", "Không có sự cố."),
        "inc_none_line": (
            "Incidents appear here when a governance rule is triggered.",
            "Sự cố xuất hiện ở đây khi một quy tắc quản trị được kích hoạt.",
        ),
        "inc_move_to": ("New status", "Trạng thái mới"),
        "inc_move_btn": ("Change status", "Đổi trạng thái"),
        "inc_close_note": (
            "Only a person can close an incident, and closing is final. Root cause and affected scope are your own words. The evidence chain keeps only a hash of each.",
            "Chỉ con người mới đóng được sự cố, và đóng là quyết định cuối. Nguyên nhân gốc và phạm vi ảnh hưởng là lời của bạn. Chuỗi bằng chứng chỉ giữ giá trị băm của từng mục.",
        ),
        # --- WP-S1: per-system guardian switches on the Catalog page ---
        "gb_system": ("AI system", "Hệ thống AI"),
        "gb_tab_title": ("Guardian switches", "Công tắc bảo vệ"),
        "gb_tab_none": (
            "No feature is locked or switched off for this system.",
            "Chưa có tính năng nào bị khóa hoặc tắt cho hệ thống này.",
        ),
        "gb_tab_link": (
            "Change the switches on the Catalog page",
            "Đổi công tắc ở trang Danh mục bảo vệ",
        ),
        "gb_pick": ("Choose a system", "Chọn một hệ thống"),
        "gb_show": ("Show switches", "Hiện công tắc"),
        "gb_lede": (
            "Switches for {name}. A switch can only turn a feature off for this system's agents. It cannot turn on a feature that is off platform-wide.",
            "Công tắc cho {name}. Công tắc chỉ tắt một tính năng cho các tác tử của hệ thống này. Không thể bật một tính năng đang tắt trên toàn nền tảng.",
        ),
        "gb_read_only": (
            "You can view the switches. To change them, you need edit rights on this system.",
            "Bạn xem được các công tắc. Để thay đổi, bạn cần quyền sửa hệ thống này.",
        ),
        "gb_locked": ("Locked", "Đã khóa"),
        "gb_floor": (
            "Required by rules {rules}; cannot be switched off",
            "Bắt buộc theo quy tắc {rules}; không thể tắt",
        ),
        "gb_never": (
            "Gate rules block or pause calls. They cannot be switched off for one system.",
            "Quy tắc cổng chặn hoặc tạm dừng lệnh gọi. Không thể tắt cho từng hệ thống.",
        ),
        "gb_instance_off": ("Off for the whole platform", "Đang tắt trên toàn nền tảng"),
        "gb_state_on": ("On for this system", "Bật cho hệ thống này"),
        "gb_state_off": ("Off for this system", "Tắt cho hệ thống này"),
        "gb_switch_off": ("Switch off", "Tắt"),
        "gb_switch_on": ("Switch on", "Bật"),
        # --- WP-G2: Rules and Classification tabs of the system page ---
        "sy_tab_rules": ("Rules", "Quy tắc"),
        "sy_tab_classification": ("Classification", "Phân loại"),
        "sy_rules_intro": (
            "Rules that assign guardians and duties to this AI system. The same facts always give the same result.",
            "Các quy tắc gán bộ bảo vệ và nghĩa vụ cho hệ thống AI này. Cùng dữ kiện luôn cho cùng kết quả.",
        ),
        "sy_rules_none": (
            "No rule applies to this AI system yet.",
            "Chưa có quy tắc nào áp dụng cho hệ thống AI này.",
        ),
        "sy_rules_file": ("Rules file sha256", "sha256 của tệp quy tắc"),
        "sy_rules_run": ("Run the rules now", "Chạy quy tắc ngay"),
        "sy_rules_floor": (
            "Required guardians (cannot be switched off)",
            "Bộ bảo vệ bắt buộc (không thể tắt)",
        ),
        "sy_rules_floor_none": ("No guardian is required.", "Không có bộ bảo vệ bắt buộc."),
        "sy_rules_off_hint": (
            "Rules that are switched off stay here as history.",
            "Các quy tắc đã tắt vẫn được giữ lại làm lịch sử.",
        ),
        "sy_rule_col_kind": ("Kind", "Loại"),
        "sy_rule_col_ref": ("Assigned", "Được gán"),
        "sy_rule_col_rule": ("Rule", "Quy tắc"),
        "sy_rule_col_fields": ("Triggered by", "Kích hoạt bởi"),
        "sy_rule_col_status": ("Status", "Trạng thái"),
        "sy_rule_active": ("active", "đang bật"),
        "sy_rule_inactive": ("off", "đã tắt"),
        "sy_kind_obligation": ("Duty", "Nghĩa vụ"),
        "sy_kind_control": ("Control", "Kiểm soát"),
        "sy_kind_risk": ("Risk", "Rủi ro"),
        "sy_kind_task": ("Task", "Nhiệm vụ"),
        "sy_kind_guardian": ("Guardian", "Bộ bảo vệ"),
        "sy_cls_intro": (
            "Answer the 4 Decision 33 questions. Some are filled in from the AI system details. Nothing takes effect until you apply it.",
            "Trả lời 4 câu hỏi theo Quyết định 33. Một số câu được điền sẵn từ thông tin hệ thống AI. Chưa có gì có hiệu lực cho đến khi bạn áp dụng.",
        ),
        "sy_cls_illustrative": (
            "Illustrative. Not legal advice. Bank counsel confirms.",
            "Chỉ mang tính minh họa. Không phải tư vấn pháp lý. Bộ phận pháp chế của ngân hàng xác nhận.",
        ),
        "sy_cls_current": ("Applied classification", "Phân loại đã áp dụng"),
        "sy_cls_none_applied": ("Not applied yet.", "Chưa áp dụng."),
        "sy_cls_draft": ("Draft", "Bản nháp"),
        "sy_cls_no_draft": (
            "No draft yet. Create one from the rules.",
            "Chưa có bản nháp. Hãy tạo từ quy tắc.",
        ),
        "sy_cls_make": ("Create a draft from the rules", "Tạo bản nháp từ quy tắc"),
        "sy_cls_remake": ("Start again from the rules", "Làm lại từ quy tắc"),
        "sy_cls_save": ("Save answers", "Lưu câu trả lời"),
        "sy_cls_apply": ("Apply this classification", "Áp dụng phân loại này"),
        "sy_cls_confirm_ai": (
            "I checked the AI pre-filled answers",
            "Tôi đã kiểm tra các câu trả lời do AI điền sẵn",
        ),
        "sy_cls_outcome": ("Outcome of the draft", "Kết quả của bản nháp"),
        "sy_cls_rule": ("Decided by", "Quyết định bởi"),
        "sy_cls_q": ("Question", "Câu hỏi"),
        "sy_cls_a": ("Answer", "Trả lời"),
        "sy_cls_src": ("Source", "Nguồn"),
        "sy_cls_why": ("Justification", "Lý giải"),
        "sy_cls_open": ("not answered", "chưa trả lời"),
        "sy_cls_yes": ("yes", "có"),
        "sy_cls_no": ("no", "không"),
        "sy_cls_src_rules": ("from AI system details", "từ thông tin hệ thống AI"),
        "sy_cls_src_ai_prefill": ("Filled in by AI", "AI điền sẵn"),
        "sy_cls_src_person": ("a person", "do người nhập"),
        "sy_cls_mock": ("mock model", "mô hình giả lập"),
        "sy_cls_ai_note": (
            "AI-filled answers are suggestions. You must check them.",
            "Câu trả lời do AI điền sẵn chỉ là gợi ý. Bạn cần kiểm tra lại.",
        ),
        "sy_f_autonomy_level": ("Autonomy level", "Mức tự chủ"),
        "sy_autonomy_level_unspecified": ("Not set", "Chưa đặt"),
        "sy_autonomy_level_l0_rule_based": ("L0 rule based", "L0 dựa trên quy tắc"),
        "sy_autonomy_level_l1_assistive": ("L1 assistive", "L1 hỗ trợ"),
        "sy_autonomy_level_l2_workflow_step": (
            "L2 step in a workflow",
            "L2 một bước trong quy trình",
        ),
        "sy_autonomy_level_l3_tool_using_supervised": (
            "L3 tools, supervised",
            "L3 dùng công cụ, có giám sát",
        ),
        "sy_autonomy_level_l4_autonomous_bounded": (
            "L4 autonomous, bounded",
            "L4 tự chủ trong giới hạn",
        ),
        "sy_autonomy_level_l5_self_directed": ("L5 self-directed", "L5 tự đặt mục tiêu"),
        "sy_cls_autonomy_proposal": (
            "The scan suggests autonomy level {level}. You set the final level.",
            "Quá trình quét gợi ý mức tự chủ {level}. Bạn đặt mức cuối cùng.",
        ),
        "sy_cls_history": ("Classifications applied before", "Các phân loại đã áp dụng trước đây"),
    }
)


_T.update(
    {
        # --- WP-G6: KPI block of the Governance overview (MCP_SERVER_ENABLED) ----------------
        "g6_kpi_title": ("Governance KPIs", "Chỉ số KPI quản trị"),
        "g6_kpi_sub": (
            "Figures for the AI systems in your scope. Rates show as percentages. If a figure cannot be calculated, the reason is shown.",
            "Số liệu của các hệ thống AI trong phạm vi của bạn. Tỷ lệ hiển thị theo phần trăm. Số liệu không tính được sẽ ghi rõ lý do.",
        ),
        "g6_kpi_coverage": ("Coverage", "Phạm vi"),
        "g6_kpi_quality": ("Quality", "Chất lượng"),
        "g6_kpi_speed": ("Speed", "Tốc độ"),
        "g6_kpi_assets": ("Assets by kind", "Tài sản theo loại"),
        "g6_kpi_by_risk": ("Systems by risk level", "Hệ thống theo mức rủi ro"),
        "g6_kpi_policy_cov": ("Policy coverage", "Độ phủ chính sách"),
        "g6_kpi_risk_treat": ("Risk treatment coverage", "Độ phủ xử lý rủi ro"),
        "g6_kpi_residual": ("Acceptable residual rate", "Tỷ lệ rủi ro dư chấp nhận được"),
        "g6_kpi_readiness": ("Control readiness", "Mức sẵn sàng của kiểm soát"),
        "g6_kpi_impl": ("Implementation per policy", "Mức triển khai theo chính sách"),
        "g6_kpi_days": ("Average days per stage", "Số ngày trung bình mỗi giai đoạn"),
        "g6_kpi_inherit": ("Risk inheritance rate", "Tỷ lệ kế thừa mức rủi ro"),
        "g6_kpi_runs": ("Rule runs", "Số lần chạy quy tắc"),
        "g6_kpi_events": ("Governance events", "Sự kiện quản trị"),
        "g6_kpi_actions": ("Action success", "Tỷ lệ hành động thành công"),
        "g6_kpi_none": ("none", "không có"),
        "g6_na_risk_register_off": (
            "The risk register is off (RISK_REGISTER_ENABLED).",
            "Sổ đăng ký rủi ro đang tắt (RISK_REGISTER_ENABLED).",
        ),
        "g6_na_controls_off": (
            "The control catalogue is off (CONTROLS_ENABLED).",
            "Danh mục kiểm soát đang tắt (CONTROLS_ENABLED).",
        ),
        "g6_na_no_active_risks": ("No active risk yet.", "Chưa có rủi ro đang hiệu lực."),
        "g6_na_no_status": ("No control status yet.", "Chưa có trạng thái kiểm soát."),
        "g6_na_governance_off": (
            "AI systems are off (GOVERNANCE_ENABLED).",
            "Hệ thống AI đang tắt (GOVERNANCE_ENABLED).",
        ),
        "g6_na_error": (
            "The figures could not be calculated. Ask an administrator to check the server log.",
            "Không tính được số liệu. Hãy nhờ quản trị viên kiểm tra nhật ký máy chủ.",
        ),
        "g6_na_capped": (
            "There is more data than one pass can read, so this figure may be incomplete.",
            "Có nhiều dữ liệu hơn mức một lần đọc, nên số liệu này có thể chưa đầy đủ.",
        ),
        "g6_na_no_obligations": (
            "No obligation is assigned yet.",
            "Chưa có nghĩa vụ nào được gán.",
        ),
    }
)


_T.update(
    {
        # --- WP-D1: document and URL intake (docs/detectors.md "Documents and URLs") ----------
        "cat_document_intake": ("Document and URL intake", "Tiếp nhận tài liệu và đường dẫn"),
        "cat_document_intake_d": (
            "Reads the files and links an agent is given (PDF, DOCX, text, web pages) and checks "
            "their text for hidden instructions and personal data; reports a finding, never "
            "blocks. A file that cannot be read stops a money, credit or personal-data call.",
            "Đọc các tệp và liên kết được đưa cho tác tử (PDF, DOCX, văn bản, trang web) và kiểm "
            "tra nội dung xem có chỉ dẫn ẩn và dữ liệu cá nhân không; báo phát hiện, không chặn. "
            "Tệp không đọc được sẽ chặn lệnh gọi liên quan đến tiền, tín dụng hoặc dữ liệu "
            "cá nhân.",
        ),
        "part_documents": ("Documents", "Tài liệu"),
        "pg_documents": ("Documents read", "Tài liệu đã đọc"),
        "pg_doc_type": ("Type", "Loại"),
        "pg_doc_size": ("Size (bytes)", "Kích thước (byte)"),
        "pg_doc_status": ("Status", "Trạng thái"),
        "pg_doc_reason": ("Reason", "Lý do"),
        "pg_doc_note": (
            "Only the hash, size and type of a document are kept. The text is not saved.",
            "Chỉ lưu mã băm, kích thước và loại của tài liệu. Nội dung không được lưu.",
        ),
        "pg_doc_findings": ("Findings", "Phát hiện"),
    }
)


# WP-D4: judge moderation detector (Catalog card)
_T.update(
    {
        "cat_judge_moderation": ("AI judge: content check", "Giám khảo AI: kiểm tra nội dung"),
        "cat_judge_moderation_d": (
            "Asks the judge whether text is toxic and whether it belongs to up to five topics "
            "you define, on the user text and on the reply. Advises and reports only; the "
            "mock judge is labelled mock.",
            "Hỏi giám khảo xem văn bản có độc hại không và có thuộc tối đa năm chủ đề do bạn "
            "định nghĩa không, trên văn bản người dùng và trên câu trả lời. Chỉ tư vấn và báo "
            "cáo; giám khảo giả được gắn nhãn mock.",
        ),
    }
)


_T.update(
    {
        # --- WP-D3: Catalog card of the guard model detector -----------------------------------
        "cat_guard_model": (
            "Guard model (jailbreak and injection)",
            "Mô hình bảo vệ (jailbreak và chèn lệnh)",
        ),
        "cat_guard_model_d": (
            "An AI model checks text for jailbreak attempts and hidden instructions, and reports findings. It can pause money and credit calls only when a named approver is set.",
            "Một mô hình AI kiểm tra văn bản để tìm jailbreak và lệnh ẩn, rồi báo phát hiện. Chỉ khi đã có người phê duyệt được nêu tên, nó mới được tạm dừng lệnh gọi về tiền và tín dụng.",
        ),
    }
)


# --- WP-N2 --- My agents tab, Register and Guardians tabs of the Agent page
_T.update(
    {
        "mya_title": ("My agents", "Tác tử của tôi"),
        "mya_purpose": (
            "Every agent in your scope: registered, known only to the gate, or found in the workspace.",  # noqa: E501
            "Mọi tác tử trong phạm vi của bạn: đã đăng ký, chỉ cổng biết, hoặc tìm thấy trong workspace.",  # noqa: E501
        ),
        "mya_why": (
            "See which agent needs a step, and open one to see how it is set up and guarded.",
            "Xem tác tử nào cần xử lý, rồi mở để xem cách thiết lập và bảo vệ.",
        ),
        "mya_col_kind": ("Kind", "Loại"),
        "mya_col_autonomy": ("Autonomy", "Mức tự chủ"),
        "mya_col_guard": ("Guardian tools", "Công cụ bảo vệ"),
        "mya_col_last": ("Last activity", "Hoạt động gần nhất"),
        "mya_col_action": ("Recommended action", "Hành động đề xuất"),
        "mya_kind_registered": ("Registered", "Đã đăng ký"),
        "mya_kind_policy_only": ("Policy only", "Chỉ trong chính sách"),
        "mya_kind_candidate": ("Candidate", "Ứng viên"),
        "mya_node_system": ("Databricks App", "Ứng dụng Databricks"),
        "mya_node_model_endpoint": ("Agent endpoint", "Endpoint tác tử"),
        "mya_node_genie_space": ("Genie space", "Không gian Genie"),
        "mya_pending_resume": (
            "Waiting for {n} approval(s) to resume",
            "Đang chờ {n} phê duyệt để tiếp tục",
        ),
        "mya_on_of": ("on {n} / of {m}", "bật {n} / trên {m}"),
        "mya_cover_full": ("full", "đủ"),
        "mya_cover_below_floor": ("below floor", "dưới mức sàn"),
        "mya_cover_none": ("none", "không có"),
        "mya_register": ("Register", "Đăng ký"),
        "mya_none": ("No agents in this scope", "Không có tác tử trong phạm vi này"),
        "mya_none_line": (
            "Try the scope All, or clear the filters.",
            "Thử phạm vi Tất cả, hoặc xóa bộ lọc.",
        ),
        "mya_tile_total": ("Total, all kinds", "Tổng, mọi loại"),
        "mya_tile_running": ("Running", "Đang chạy"),
        "mya_tile_shadow": ("Shadow", "Giám sát"),
        "mya_tile_stopped": ("Paused or quarantined", "Tạm dừng hoặc cách ly"),
        "mya_tile_below": ("Below floor", "Dưới mức sàn"),
        "mya_ra_register": ("Register this agent", "Đăng ký tác tử này"),
        "mya_ra_task": ("Finish task: {title}", "Hoàn thành tác vụ: {title}"),
        "mya_ra_stage": ("Approve stage {frm} to {to}", "Phê duyệt giai đoạn {frm} sang {to}"),
        "mya_ra_classify": ("Classify (Decision 33)", "Phân loại (Quyết định 33)"),
        "mya_ra_guardian": ("Switch on {slug}", "Bật {slug}"),
        "mya_ra_running": (
            "Request RUNNING (in SHADOW {days} days)",
            "Yêu cầu RUNNING (đã ở SHADOW {days} ngày)",
        ),
        "mya_ra_case": ("Triage case ({n} open)", "Xử lý vụ việc ({n} đang mở)"),
        "mya_ra_none": ("No action", "Không cần hành động"),
        "mya_desc_built": (
            "{name} is an agent on {family}, hosted as {host}, with {tools} tools and risk tier {tier}.",  # noqa: E501
            "{name} là tác tử chạy trên {family}, lưu trữ dạng {host}, có {tools} công cụ, mức rủi ro {tier}.",  # noqa: E501
        ),
        "atab_register": ("Register", "Đăng ký"),
        "atab_guardians": ("Guardians", "Bộ bảo vệ"),
        "atab_source": ("Source", "Mã nguồn"),
        "atab_facts": ("Facts", "Dữ kiện"),
        "atab_predeploy": ("Pre-deploy", "Trước triển khai"),
        "atab_attach": ("Attach", "Gắn kết"),
        "atab_postdeploy": ("Post-deploy", "Sau triển khai"),
        "mya_reg_policy_only": ("Known to the gate, not registered", "Cổng biết, chưa đăng ký"),
        "mya_reg_policy_only_line": (
            "The gate policy lists this agent, but it is not registered. Register it under an AI system.",
            "Chính sách của cổng có tác tử này nhưng chưa đăng ký. Hãy đăng ký nó vào một hệ thống AI.",
        ),
        "mya_reg_registry": ("Registry entry", "Mục trong sổ đăng ký"),
        "mya_reg_manifest": ("Manifest values", "Giá trị trong manifest"),
        "mya_reg_team": ("Owner team", "Nhóm sở hữu"),
        "mya_reg_host": ("Host type", "Loại lưu trữ"),
        "mya_reg_plug": ("Connection point", "Điểm kết nối"),
        "mya_reg_since": ("Since", "Từ"),
        "mya_reg_initial": ("Initial state", "Trạng thái ban đầu"),
        "mya_reg_system": ("AI system", "Hệ thống AI"),
        "mya_reg_stage": ("Stage", "Giai đoạn"),
        "mya_reg_class": ("Decision 33 class", "Phân loại Quyết định 33"),
        "mya_reg_no_system": (
            "No AI system is linked to this agent.",
            "Chưa có hệ thống AI nào liên kết với tác tử này.",
        ),
        "mya_reg_description": ("Description", "Mô tả"),
        "mya_reg_assessment": ("Assessment", "Đánh giá"),
        "mya_reg_d33": ("Decision 33 outcome", "Kết quả Quyết định 33"),
        "mya_reg_d33_source": ("Decision 33 source", "Nguồn Quyết định 33"),
        "mya_reg_risk_level": ("Risk level", "Mức rủi ro"),
        "mya_reg_risk_source": ("Risk source", "Nguồn mức rủi ro"),
        "mya_src_registry": ("registry", "sổ đăng ký"),
        "mya_src_proposal": ("suggested during onboarding", "đề xuất khi tiếp nhận"),
        "mya_src_system": ("AI system", "hệ thống AI"),
        "mya_src_agent_tier": ("agent risk tier", "mức rủi ro của tác tử"),
        "mya_src_classifier": ("automatic classification", "phân loại tự động"),
        "mya_src_inherited": ("inherited from components", "kế thừa từ thành phần"),
        "mya_src_manual": ("set by a person", "do con người đặt"),
        "mya_f_system_type": ("System type", "Loại hệ thống"),
        "mya_f_org_role": ("Organisation role", "Vai trò tổ chức"),
        "mya_f_user_segment": ("User segment", "Nhóm người dùng"),
        "mya_f_personal_data": ("Personal data", "Dữ liệu cá nhân"),
        "mya_f_money_movement": ("Money movement", "Chuyển tiền"),
        "mya_f_credit_decision": ("Credit decision", "Quyết định tín dụng"),
        "mya_f_human_control": ("Human control", "Kiểm soát của con người"),
        "mya_g_status": ("Status of guardian features", "Trạng thái các tính năng bảo vệ"),
        "mya_g_status_line": (
            "Effective = on in this instance and not switched off for the AI system. The gate rules are never switchable.",  # noqa: E501
            "Hiệu lực = bật trong hệ thống này và không bị tắt cho hệ thống AI. Quy tắc cổng không bao giờ tắt được.",  # noqa: E501
        ),
        "mya_g_feature": ("Feature", "Tính năng"),
        "mya_g_group": ("Group", "Nhóm"),
        "mya_g_instance": ("Instance", "Hệ thống"),
        "mya_g_binding": ("Switch per AI system", "Công tắc theo hệ thống AI"),
        "mya_g_floor": ("Floor lock", "Khóa sàn"),
        "mya_g_effective": ("Effective", "Hiệu lực"),
        "mya_g_reason": ("Reason when off", "Lý do khi tắt"),
        "mya_g_never": ("never switchable", "không bao giờ tắt được"),
        "mya_g_bind_off": ("switches are off", "công tắc đang tắt"),
        "mya_g_no_system": ("no AI system", "chưa có hệ thống AI"),
        "mya_g_by": ("by {who}", "bởi {who}"),
        "mya_g_locked": ("locked", "đã khóa"),
        "mya_on": ("on", "bật"),
        "mya_off": ("off", "tắt"),
        "mya_grp_detect": ("Detectors", "Bộ phát hiện"),
        "mya_grp_gate": ("Gate", "Cổng"),
        "mya_grp_judge": ("Judges", "Giám khảo"),
        "mya_grp_monitor": ("Monitors", "Bộ giám sát"),
        "mya_grp_packs": ("Assurance checks", "Kiểm tra đảm bảo"),
        "mya_why_flag_off": ("flag off in this instance", "cờ đang tắt trong hệ thống"),
        "mya_why_file_off": ("off in config/detectors.yaml", "tắt trong config/detectors.yaml"),
        "mya_why_policy_off": ("off in the agent's policy", "tắt trong chính sách của tác tử"),
        "mya_why_binding_off": ("switched off by {who}", "do {who} tắt"),
        "mya_g_results": ("Results", "Kết quả"),
        "mya_g_window": ("Window", "Khoảng thời gian"),
        "mya_win_24h": ("24 h", "24 giờ"),
        "mya_win_7d": ("7 days", "7 ngày"),
        "mya_win_30d": ("30 days", "30 ngày"),
        "mya_g_counts_only": (
            "Counts only. No text excerpts are shown.",
            "Chỉ có số đếm. Không hiển thị đoạn trích nội dung.",
        ),
        "mya_g_none_enabled": (
            "No enabled feature in this group.",
            "Không có tính năng nào đang bật trong nhóm này.",
        ),
        "mya_g_findings": ("Findings", "Phát hiện"),
        "mya_g_top_codes": ("Most frequent codes", "Mã gặp nhiều nhất"),
        "mya_g_hints": ("Action hints", "Gợi ý hành động"),
        "mya_g_checks": ("Checks", "Lượt kiểm tra"),
        "mya_g_allowed": ("Allowed", "Cho phép"),
        "mya_g_blocked": ("Blocked", "Chặn"),
        "mya_g_paused": ("Paused", "Tạm dừng"),
        "mya_g_would": ("Would block in SHADOW", "Sẽ chặn trong SHADOW"),
        "mya_g_verdicts": ("Verdicts", "Phán quyết"),
        "mya_g_cases_opened": ("Cases opened", "Vụ việc đã mở"),
        "mya_g_last_status": ("Last status", "Trạng thái gần nhất"),
        "mya_g_no_status": ("no status yet", "chưa có trạng thái"),
        "mya_g_pack": ("Assurance check", "Bài kiểm tra đảm bảo"),
        "mya_g_no_packs": ("No assurance check results yet.", "Chưa có kết quả kiểm tra đảm bảo."),
        "mya_link_activity": ("Activity", "Hoạt động"),
        "mya_link_cases": ("Cases", "Vụ việc"),
        "mya_link_assurance": ("Assurance", "Đảm bảo"),
    }
)
from supervisor.console.i18n_register import RG2 as _RG2  # noqa: E402  (WP-N3, prefix rg2_)

_T.update(_RG2)
from supervisor.console.i18n_workflow import WF as _WF  # noqa: E402  (WP-P1, prefix wf_)

_T.update(_WF)
from supervisor.console.i18n_duties import DU as _DU  # noqa: E402  (WP-L3, prefix du_)

_T.update(_DU)
from supervisor.console.i18n_g2 import G2 as _G2  # noqa: E402  (UX5 package G2, prefix g2_)

_T.update(_G2)
from supervisor.console.i18n_riskdim import RD as _RD  # noqa: E402  (WP-C2, prefix rd_)

_T.update(_RD)
from supervisor.console.i18n_orch import ORCH as _ORCH  # noqa: E402  (WP-F4, prefix orch_)

_T.update(_ORCH)
from supervisor.console.i18n_smart_guardian import SG as _SG  # noqa: E402  (WP-G4, prefix sg_)

_T.update(_SG)

# --- WP-P2 (phase 8) --- CONSOLE_STATE_ACTIONS: RUNNING request, Decision 33 apply, guardian off
_T.update(
    {
        "sa_title": ("Move to RUNNING", "Chuyển sang RUNNING"),
        "sa_would_block": (
            "Calls shadow mode would have blocked in the last {days} days:",
            "Số lệnh gọi mà chế độ bóng lẽ ra đã chặn trong {days} ngày qua:",
        ),
        "sa_request": ("Request move to RUNNING", "Yêu cầu chuyển sang RUNNING"),
        "sa_approve": ("Approve move to RUNNING", "Duyệt chuyển sang RUNNING"),
        "sa_requested_by": (
            "{who} asked to move this agent to RUNNING.",
            "{who} đã yêu cầu chuyển tác tử này sang RUNNING.",
        ),
        "sa_you_requested": (
            "You asked for this. A different person approves it.",
            "Bạn đã yêu cầu. Một người khác phải duyệt.",
        ),
        "sa_cannot_approve": (
            "Only the agent owner or a policy reviewer can approve.",
            "Chỉ chủ sở hữu tác tử hoặc người rà soát chính sách mới được phê duyệt.",
        ),
        "sa_rule": (
            "Two people are needed. One asks. The agent owner or a policy reviewer approves.",
            "Cần hai người khác nhau: một người yêu cầu, chủ sở hữu tác tử hoặc người rà soát chính sách phê duyệt.",
        ),
        "gb_reason_ph": ("Reason (required)", "Lý do (bắt buộc)"),
        "gb_second_person": (
            "For a live or high-risk system, a second approver must approve each switch-off.",
            "Với hệ thống đang vận hành hoặc rủi ro cao, cần người phê duyệt thứ hai cho mỗi lần tắt.",
        ),
        "gb_pending_title": (
            "Switch-off requests waiting for a second approver",
            "Yêu cầu tắt đang chờ người phê duyệt thứ hai",
        ),
        "gb_pending_row": ("{slug}, requested by {who}", "{slug}, do {who} yêu cầu"),
        "gb_approve": ("Approve switch-off", "Duyệt việc tắt"),
        "gb_you_asked": (
            "You requested this. A second approver must approve it.",
            "Bạn đã yêu cầu. Cần người phê duyệt thứ hai duyệt.",
        ),
        "sy_cls_why_min": (
            "Every answer needs a justification of at least {n} characters.",
            "Mỗi câu trả lời cần lý do ít nhất {n} ký tự.",
        ),
    }
)


def translator(lang: str, ux5: bool = False) -> Callable[..., str]:
    """``t(key)`` or ``t(key, n=3, ...)`` (``str.format`` placeholders). Unknown keys come
    back unchanged, so a template never fails on a label. With ``ux5`` True (CONSOLE_UX5) the
    ``i18n_ux5_*`` overrides are looked up first; with it False nothing changes."""
    idx = 1 if lang == "vi" else 0
    over = ux5_overrides() if ux5 else {}

    def t(key: str, **kw: object) -> str:
        pair = over.get(key) or _T.get(key)
        text = pair[idx] if pair else key
        if kw:
            try:
                return text.format(**kw)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    return t


def ux5_overrides() -> dict[str, tuple[str, str]]:
    """All UX5 text overrides (console/i18n_ux5.py lists the modules)."""
    from supervisor.console.i18n_ux5 import load

    return load()


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


_T.update(
    {
        # --- WP-N1: My overview as a dashboard, candidate triage (CONSOLE_OVERVIEW_V4) ---------
        "ov4_t_overview": ("Overview", "Tổng quan"),
        "ov4_t_agents": ("My agents", "Tác tử của tôi"),
        "ov4_t_candidates": ("Candidates to register", "Ứng viên cần đăng ký"),
        "ov4_how": ("How we are doing", "Tình hình hiện nay"),
        "ov4_state_good": ("Good", "Tốt"),
        "ov4_state_work": ("Work to do", "Còn việc phải làm"),
        "ov4_state_attention": ("Attention", "Cần chú ý"),
        "ov4_why_overdue_high": (
            "Overdue high-risk task: {arg}.",
            "Công việc rủi ro cao quá hạn: {arg}.",
        ),
        "ov4_why_critical": (
            "Critical cases open: {arg}.",
            "Vụ việc nghiêm trọng đang mở: {arg}.",
        ),
        "ov4_why_candidate": (
            "A high-scoring candidate is waiting to be registered: {arg}.",
            "Có ứng viên điểm cao đang chờ đăng ký: {arg}.",
        ),
        "ov4_why_overdue": ("Required tasks overdue: {arg}.", "Công việc bắt buộc quá hạn: {arg}."),
        "ov4_why_high_case": ("High cases open: {arg}.", "Vụ việc mức cao đang mở: {arg}."),
        "ov4_why_actions": ("Items waiting on you: {arg}.", "Việc đang chờ bạn: {arg}."),
        "ov4_why_good": (
            "No overdue tasks, no high-severity cases, no high-scoring candidates.",
            "Không có công việc quá hạn, vụ việc mức cao hay ứng viên điểm cao.",
        ),
        "ov4_open_items": ("Open items: {n}", "Việc đang mở: {n}"),
        "ov4_pipeline": ("Registration pipeline", "Quy trình đăng ký"),
        "ov4_stage_candidates": ("Candidates", "Ứng viên"),
        "ov4_stage_draft": ("Draft", "Bản nháp"),
        "ov4_stage_intake": ("Registration confirmed", "Đã xác nhận đăng ký"),
        "ov4_stage_classified": ("Classified", "Đã phân loại"),
        "ov4_stage_guarded": ("Guarded", "Đã bảo vệ"),
        "ov4_stage_production": ("In production", "Đang vận hành"),
        "ov4_pipeline_note": (
            "Counts overlap: one system can be in several steps.",
            "Các số có thể trùng nhau: một hệ thống có thể ở nhiều bước.",
        ),
        "ov4_assess": ("Assessment completion", "Mức hoàn thành đánh giá"),
        "ov4_dim_intake": ("Registration details complete", "Thông tin đăng ký đầy đủ"),
        "ov4_dim_class": ("Decision 33 class set", "Đã có phân loại Quyết định 33"),
        "ov4_dim_checks": ("Readiness checked", "Đã kiểm tra mức sẵn sàng"),
        "ov4_dim_guardians": ("Guardians at the minimum", "Bộ bảo vệ đạt mức tối thiểu"),
        "ov4_dim_tasks": ("Required tasks done", "Công việc bắt buộc đã xong"),
        "ov4_dim_duties": ("Duties closed, average", "Nghĩa vụ đã hoàn tất, trung bình"),
        "ov4_risk_by_autonomy": (
            "Risk classification by autonomy level",
            "Phân loại rủi ro theo mức tự chủ",
        ),
        "ov4_risk_critical": ("Critical", "Nghiêm trọng"),
        "ov4_totals": ("Totals", "Tổng số"),
        "ov4_t_systems": ("AI systems", "Hệ thống AI"),
        "ov4_t_agents_gate": ("Registered agents", "Tác tử đã đăng ký"),
        "ov4_gate_split": (
            "{r} running · {s} shadow mode · {p} paused",
            "{r} đang chạy · {s} chế độ quan sát · {p} tạm dừng",
        ),
        "ov4_t_cover": ("Agents with a guardian", "Tác tử có bộ bảo vệ"),
        "ov4_t_cases": ("Open cases", "Vụ việc đang mở"),
        "ov4_t_due": ("Tasks overdue", "Công việc quá hạn"),
        "ov4_actions": ("Your actions", "Việc cần bạn xử lý"),
        "ov4_attention": ("Needs your attention ({n})", "Cần bạn chú ý ({n})"),
        "ov4_input": ("Waiting for your input ({n})", "Đang chờ bạn bổ sung ({n})"),
        "ov4_top_candidates": ("Register these first", "Nên đăng ký trước"),
        "ov4_all_candidates": ("All candidates", "Tất cả ứng viên"),
        "ov4_cand_off": ("Inventory is switched off", "Kiểm kê đang tắt"),
        "ov4_cand_off_line": (
            "Set INVENTORY_ENABLED=1 to turn it on. The workspace scan then finds candidates.",
            "Đặt INVENTORY_ENABLED=1 để bật. Sau đó quét workspace sẽ tìm ra ứng viên.",
        ),
        "ov4_cards": ("My systems and agents", "Hệ thống và tác tử của tôi"),
        "ov4_kind_system": ("AI system", "Hệ thống AI"),
        "ov4_kind_agent": ("Agent", "Tác tử"),
        "ov4_guard_none": ("no guardian data", "chưa có dữ liệu bộ bảo vệ"),
        "ov4_cases_n": ("Cases: {n}", "Vụ việc: {n}"),
        "ov4_na_none": ("Nothing to do", "Không cần làm gì"),
        "ov4_na_finish_task_overdue": (
            "Finish overdue task: {arg}",
            "Hoàn thành công việc quá hạn: {arg}",
        ),
        "ov4_na_finish_task": ("Finish task: {arg}", "Hoàn thành công việc: {arg}"),
        "ov4_na_approve_stage": ("Approve the stage", "Phê duyệt giai đoạn"),
        "ov4_na_classify": ("Classify (Decision 33)", "Phân loại (Quyết định 33)"),
        "ov4_na_switch_on": ("Switch on {arg}", "Bật {arg}"),
        "ov4_na_request_running": ("Ask to start {arg}", "Yêu cầu cho {arg} bắt đầu chạy"),
        "ov4_na_triage_case": ("Review cases ({arg})", "Xem xét vụ việc ({arg})"),
        # candidate triage
        "tri_title": ("Candidates to register", "Ứng viên cần đăng ký"),
        "tri_purpose": (
            "Workspace objects that no AI system covers yet, best score first.",
            "Các đối tượng trong workspace chưa thuộc hệ thống AI nào, điểm cao xếp trước.",
        ),
        "tri_why": (
            "The score shows what to register first. It is a guide based on fixed rules. You decide.",
            "Điểm cho biết nên đăng ký gì trước. Đây là gợi ý theo quy tắc cố định; bạn quyết định.",
        ),
        "tri_note": (
            "Score = impact x 0.6 + autonomy rank x 10 + complexity x 0.2, at most 100.",
            "Điểm = tác động x 0,6 + hạng tự chủ x 10 + độ phức tạp x 0,2, tối đa 100.",
        ),
        "tri_c_candidate": ("Candidate", "Ứng viên"),
        "tri_c_signals": ("Signals", "Tín hiệu"),
        "tri_c_impact": ("Impact", "Tác động"),
        "tri_c_autonomy": ("Autonomy", "Mức tự chủ"),
        "tri_c_score": ("Score", "Điểm"),
        "tri_c_action": ("Recommended action", "Hành động đề xuất"),
        "tri_c_complexity": ("Complexity", "Độ phức tạp"),
        "tri_c_group": ("Owner group", "Nhóm sở hữu"),
        "tri_evidence": ("Evidence", "Bằng chứng"),
        "tri_none": ("No candidate", "Không có ứng viên"),
        "tri_none_line": (
            "No unregistered objects match. Run the workspace scan or change the filters.",
            "Không có đối tượng chưa đăng ký nào phù hợp. Hãy chạy quét workspace hoặc đổi bộ lọc.",
        ),
        "tri_register": ("Register", "Đăng ký"),
        "tri_register_off": (
            "Registration is switched off. Ask an administrator to enable CONSOLE_SYSTEMS_ENABLED and CONSOLE_NAV_V3.",
            "Chức năng đăng ký đang tắt. Hãy nhờ quản trị viên bật CONSOLE_SYSTEMS_ENABLED và CONSOLE_NAV_V3.",
        ),
        "tri_kind_app": ("Databricks App", "Databricks App"),
        "tri_kind_endpoint": ("Serving endpoint", "Endpoint phục vụ"),
        "tri_kind_genie_space": ("Genie space", "Không gian Genie"),
        "tri_kind_job": ("Job", "Job"),
        "tri_sig_external_model": ("external model", "mô hình bên ngoài"),
        "tri_sig_customer_table": ("customer table", "bảng khách hàng"),
        "tri_sig_money_tool": ("money tool", "công cụ tiền"),
        "tri_sig_writes": ("writes data", "ghi dữ liệu"),
        "tri_sig_agent_endpoint": ("agent endpoint", "endpoint tác tử"),
        "tri_sig_genie_space": ("Genie space", "không gian Genie"),
        "tri_sig_app_agent": ("app with agent", "app có tác tử"),
        "tri_sig_unknown": ("unknown", "chưa rõ"),
        "tri_sig_scheduled": ("scheduled", "chạy theo lịch"),
        "tri_sig_no_owner": ("no owner", "chưa có chủ sở hữu"),
        "tri_sigd_external_model": (
            "It serves or calls a model from an external provider (+20).",
            "Nó phục vụ hoặc gọi mô hình của nhà cung cấp bên ngoài (+20).",
        ),
        "tri_sigd_customer_table": (
            "It accesses customer, card, account, loan or payment data (+25).",
            "Nó truy cập dữ liệu khách hàng, thẻ, tài khoản, khoản vay hoặc thanh toán (+25).",
        ),
        "tri_sigd_money_tool": (
            "It uses a money, credit or pii_export tool (+30).",
            "Nó dùng công cụ thuộc lớp money, credit hoặc pii_export (+30).",
        ),
        "tri_sigd_writes": ("The job writes data (+10).", "Job này ghi dữ liệu (+10)."),
        "tri_sigd_agent_endpoint": (
            "The endpoint runs an agent (+10).",
            "Endpoint này chạy một tác tử (+10).",
        ),
        "tri_sigd_genie_space": ("It is a Genie space (+10).", "Đây là không gian Genie (+10)."),
        "tri_sigd_app_agent": (
            "An agent endpoint stands behind the app (+10).",
            "Có endpoint tác tử phía sau app (+10).",
        ),
        "tri_sigd_unknown": (
            "Nothing is known about it yet (+5).",
            "Chưa biết gì về đối tượng này (+5).",
        ),
        "tri_sigd_scheduled": ("It runs on a schedule (+0).", "Nó chạy theo lịch (+0)."),
        "tri_sigd_no_owner": ("No owner group on record (+0).", "Chưa có nhóm sở hữu (+0)."),
        "tri_band_high": ("High (70 or more)", "Cao (từ 70)"),
        "tri_band_medium": ("Medium (40 to 69)", "Trung bình (40 đến 69)"),
        "tri_band_low": ("Low (under 40)", "Thấp (dưới 40)"),
        "tri_act_register_now": ("Register now", "Đăng ký ngay"),
        "tri_act_register_and_classify": ("Register and classify", "Đăng ký và phân loại"),
        "tri_act_register_review_vendor": (
            "Register and review the vendor",
            "Đăng ký và rà soát nhà cung cấp",
        ),
        "tri_act_register_when_convenient": (
            "Register when convenient",
            "Đăng ký khi thuận tiện",
        ),
        "tri_reason_register_now": ("The score is 70 or more.", "Điểm từ 70 trở lên."),
        "tri_reason_register_and_classify": (
            "It touches money, credit or customer data. Classify it under Decision 33.",
            "Nó chạm tới tiền, tín dụng hoặc dữ liệu khách hàng. Hãy phân loại theo Quyết định 33.",
        ),
        "tri_reason_register_review_vendor": (
            "It uses a model from an external provider. Review the vendor.",
            "Nó dùng mô hình của nhà cung cấp bên ngoài. Hãy rà soát nhà cung cấp.",
        ),
        "tri_reason_register_when_convenient": (
            "No strong signal. Register it in the next round.",
            "Không có tín hiệu mạnh. Đăng ký ở đợt sau.",
        ),
        "tri_d_app": ("Databricks App {name}", "Databricks App {name}"),
        "tri_d_endpoint": ("Serving endpoint {name}", "Endpoint phục vụ {name}"),
        "tri_d_genie_space": ("Genie space {name}", "Không gian Genie {name}"),
        "tri_d_job": ("Job {name}", "Job {name}"),
        "tri_d_group": (" in group {group}", " thuộc nhóm {group}"),
        "tri_d_calls": ("calls endpoint {e}", "gọi endpoint {e}"),
        "tri_d_provider": (" (external provider {p})", " (nhà cung cấp bên ngoài {p})"),
        "tri_d_uses_provider": ("uses external provider {p}", "dùng nhà cung cấp bên ngoài {p}"),
        "tri_d_tables": ("reaches customer tables ({n})", "truy cập bảng khách hàng ({n})"),
        "tri_d_money": (
            "calls money or credit tools ({n})",
            "gọi công cụ tiền hoặc tín dụng ({n})",
        ),
        "tri_d_writes": ("writes data", "ghi dữ liệu"),
    }
)
from supervisor.console.i18n_schema import SCH as _SCH  # noqa: E402  (WP-P3, prefix sch_)

_T.update(_SCH)
from supervisor.console.i18n_ux5_g4 import G4 as _G4  # noqa: E402  (UX5-G4, new keys, prefix g4_)

_T.update(_G4)
from supervisor.console.i18n_intake import IK as _IK  # noqa: E402  (WP-O1, prefix ik_)

_T.update(_IK)
from supervisor.console.i18n_facts import FK as _FK  # noqa: E402  (WP-O2, prefix fk_)

_T.update(_FK)
from supervisor.console.i18n_codeagent import CA as _CA  # noqa: E402  (source analysis agent, prefix ca_)

_T.update(_CA)
from supervisor.console.i18n_predeploy import PD as _PD  # noqa: E402  (WP-O3, prefix pd_)

_T.update(_PD)
from supervisor.console.i18n_attach import AT as _AT  # noqa: E402  (WP-O4, prefix at_)

_T.update(_AT)
from supervisor.console.i18n_postdeploy import PX as _PX  # noqa: E402  (WP-O5, prefix px_)

_T.update(_PX)
from supervisor.console.i18n_classify import CV as _CV  # noqa: E402  (WP-C1, prefix cv_)

_T.update(_CV)
from supervisor.console.i18n_guardian_factory import GF as _GF  # noqa: E402  (WP-G1, prefix gf_)

_T.update(_GF)

from supervisor.console.i18n_regkb_internal import RI as _RI  # noqa: E402  (WP-W3, prefix ri_)

_T.update(_RI)
from supervisor.console.i18n_regwatch import RW as _RW  # noqa: E402  (WP-W1, prefix rw_)

_T.update(_RW)
from supervisor.console.i18n_regkb_change import RC as _RC  # noqa: E402  (WP-W2, prefix rc_)

_T.update(_RC)
from supervisor.console.i18n_kbgraph import KG as _KG  # noqa: E402  (KBGRAPH_ENABLED, prefix kg_)

_T.update(_KG)
from supervisor.console.i18n_factory import FA as _FA  # noqa: E402  (WP-F2, prefix fa_)

_T.update(_FA)
from supervisor.console.i18n_portfolio import PF as _PF  # noqa: E402  (WP-C4, prefix pf_)

_T.update(_PF)
from supervisor.console.i18n_register3 import RG3 as _RG3  # noqa: E402  (WP-C3, prefix rg3_)

_T.update(_RG3)
from supervisor.console.i18n_factory_gate import FG as _FG  # noqa: E402  (WP-F3, prefix fg_)

_T.update(_FG)
from supervisor.console.i18n_ux5_g3 import NEW as _G3  # noqa: E402  (UX5 group G3, prefix g3_)

_T.update(_G3)


# --- UX5-F --- strings of the UX5 shell and macros (templates/_ux5.html); used with CONSOLE_UX5
_T.update(
    {
        "ux5_dev_chip": ("Dev identity", "Danh tính dev"),
        "ux5_about": ("About this page", "Về trang này"),
        "ux5_info": ("Information", "Thông tin"),
        "ux5_technical": ("Technical details", "Chi tiết kỹ thuật"),
        "ux5_shown_of": ("{shown} of {total} shown", "Hiển thị {shown} / {total}"),
        "ux5_view_all": ("View all", "Xem tất cả"),
        "ux5_page_of": ("Page {page} of {pages}", "Trang {page} / {pages}"),
        "ux5_prev": ("Previous", "Trước"),
        "ux5_next": ("Next", "Sau"),
        "ux5_gap": ("Gap", "Thiếu"),
        "ux5_partial": ("Partial", "Một phần"),
        "ux5_bank": ("Bank process", "Quy trình của ngân hàng"),
        "ux5_closed": ("Met", "Đạt"),
        "ux5_more": ("+{n} more", "+{n} nữa"),
    }
)

# --- UX5 G1 --- strings used only by the overview-family UX5 templates (prefix u5g1_)
from supervisor.console.i18n_ux5_g1 import NEW as _U5G1  # noqa: E402

_T.update(_U5G1)

# --- UX5 G5 / G6 --- new keys, merged here like every other package (templates use t('key'))
from supervisor.console.i18n_ux5_g5 import NEW as _U5G5  # noqa: E402

_T.update(_U5G5)
from supervisor.console.i18n_ux5_g6 import ALL as _U5G6  # noqa: E402

_T.update(_U5G6)

# --- UI audit batch 1 --- labels of the broken-link, count and placeholder fixes (prefix b1_)
from supervisor.console.i18n_ux_b1 import B1 as _B1  # noqa: E402

_T.update(_B1)

# --- UI audit batch 3 --- names, labels, raw ids, en/vi (prefixes lbl_ and b3_)
from supervisor.console.i18n_ux_b3 import CHANGED as _B3C  # noqa: E402
from supervisor.console.i18n_ux_b3 import NEW as _B3N  # noqa: E402

_T.update(_B3N)
_T.update(_B3C)

# --- W4 --- inventory run dashboard (prefix finv_)
from supervisor.console.i18n_finv import FINV as _FINV  # noqa: E402

_T.update(_FINV)
from supervisor.console.i18n_exec import EX as _EX  # noqa: E402  (ORCH_EXEC_FINDINGS, prefix exec_)

_T.update(_EX)
from supervisor.console.i18n_guardian_kit import GK as _GK  # noqa: E402  (GUARDIAN_KIT, prefix gk_)

_T.update(_GK)
from supervisor.console.i18n_stability import ST as _ST  # noqa: E402  (W8, prefix st_)

_T.update(_ST)
from supervisor.console.i18n_redteam import RT as _RT  # noqa: E402  (W7, REDTEAM_TAB, prefix rt_)

_T.update(_RT)
