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
    "sbv_clock": (
        "SBV 24 h report (deprecated: not in Circular 53)",
        "Báo cáo NHNN 24 giờ (không còn dùng: không có trong Thông tư 53)",
    ),
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
    "transcript": ("Masked transcript excerpt", "Trích đoạn hội thoại (đã che)"),
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
    # ---- WP12 agents
    "agents_purpose": (
        "Every agent the bank runs, where it is in its life, and whether Supervisor can stop it.",
        "Mọi tác tử ngân hàng đang chạy, đang ở giai đoạn nào, và Supervisor có thể dừng nó không.",
    ),
    "agents_why": (
        "Pause is one click by any reviewer. Resume needs two people: the agent's owner and a "
        "reviewer. Quarantine is for admins.",
        "Tạm dừng: một người duyệt bấm một lần. Mở lại cần hai người: chủ sở hữu tác tử và một "
        "người duyệt. Cách ly dành cho quản trị viên.",
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
    "proposal": ("proposal", "đề xuất"),
    "model_family": ("model family", "họ mô hình"),
    "judge_family": ("judge family", "họ giám khảo"),
    "lifecycle": ("Lifecycle", "Vòng đời"),
    "stage_discover": ("Discover", "Khám phá"),
    "stage_understand": ("Understand", "Hiểu"),
    "stage_plan": ("Plan", "Lập kế hoạch"),
    "stage_instrument": ("Instrument", "Gắn giám sát"),
    "stage_launch": ("Launch", "Ra mắt"),
    "stage_operate": ("Operate", "Vận hành"),
    "stage_note_shadow": ("shadow mode", "chế độ bóng"),
    "stage_note_enforced": ("enforced", "đang thực thi"),
    "cov_src_capabilities": (
        "{detail} monitoring capabilities on (Onboard plan)",
        "{detail} năng lực giám sát đang bật (kế hoạch tiếp nhận)",
    ),
    "cov_src_metric": (
        "share of tool calls that passed the gate (daily metric {detail})",
        "tỷ lệ lệnh gọi công cụ đi qua cổng (chỉ số ngày {detail})",
    ),
    "cov_src_events": (
        "{detail} recent tool calls passed the gate",
        "{detail} lệnh gọi công cụ gần đây đã đi qua cổng",
    ),
    "cov_src_none": ("no traffic yet: coverage not measured", "chưa có lưu lượng: chưa đo"),
    "cov_planned": (
        "{p} of {n} monitoring capabilities planned by Onboard (not merged yet)",
        "{p}/{n} năng lực giám sát đã lên kế hoạch (chưa hợp nhất)",
    ),
    "cov_missing": ("trace path cannot see: {items}", "đường vết không thấy: {items}"),
    "tools_summary": ("{n} tools · {m} money-moving", "{n} công cụ · {m} di chuyển tiền"),
    "fail_mode_is": ("fail mode {mode}", "khi lỗi: {mode}"),
    "fail_closed": ("closed", "đóng (chặn)"),
    "fail_open": ("open", "mở (cho qua)"),
    "fail_mixed": ("mixed", "hỗn hợp"),
    "fail_-": ("-", "-"),
    "open_cases_n": ("{n} open case(s)", "{n} vụ việc đang mở"),
    "pause_now": ("Pause now", "Tạm dừng ngay"),
    "pause_rule": (
        "One click by any reviewer. Takes effect at the agent's next tool call.",
        "Một người duyệt bấm một lần. Có hiệu lực ở lệnh gọi công cụ tiếp theo.",
    ),
    "approve_resume": ("Approve resume", "Đồng ý mở lại"),
    "second_approval": ("Give the second approval", "Phê duyệt lần hai"),
    "approved_by": ("Approved by {who} ({role}).", "{who} ({role}) đã đồng ý."),
    "waiting_for": ("Waiting for the {role}.", "Đang chờ {role}."),
    "resume_rule_short": (
        "Needs the agent owner and a reviewer, two different people.",
        "Cần chủ sở hữu tác tử và một người duyệt, là hai người khác nhau.",
    ),
    "you_are_role": ("You are the {role}.", "Bạn là {role}."),
    "you_approved": (
        "You approved; the other person must approve.",
        "Bạn đã đồng ý; cần người còn lại.",
    ),
    "you_cannot_resume": (
        "You are not the owner or a policy reviewer, so you cannot approve.",
        "Bạn không phải chủ sở hữu hay người duyệt trong chính sách, nên không thể đồng ý.",
    ),
    "release_rule": (
        "Only an admin listed in the policy can release a quarantine. A reason is required.",
        "Chỉ quản trị viên trong chính sách được gỡ cách ly. Bắt buộc ghi lý do.",
    ),
    "quarantine_rule": (
        "Admin only. Stops every call until an admin releases it.",
        "Chỉ quản trị viên. Chặn mọi lệnh gọi cho đến khi quản trị viên gỡ.",
    ),
    "reason_required": ("Reason (required)", "Lý do (bắt buộc)"),
    "no_agents": (
        "No agent is registered yet. Use Onboard to bring the first agent under supervision.",
        "Chưa có tác tử nào. Dùng Tiếp nhận để đưa tác tử đầu tiên vào giám sát.",
    ),
    # ---- WP12 cases
    "archive": ("Archive", "Lưu trữ"),
    "cases_purpose": (
        "Each case is one thing that needs a human decision. Rules, judges and monitors open "
        "cases. People triage, contain and close them.",
        "Mỗi vụ việc là một việc cần con người quyết định. Quy tắc, giám khảo AI và bộ giám "
        "sát mở vụ việc. Con người phân loại, ngăn chặn và đóng vụ việc.",
    ),
    "cases_why": (
        "The clocks come from the draft SBV circular: report within 24 hours, remediate within "
        "5 days.",
        "Các mốc thời gian theo dự thảo thông tư NHNN: báo cáo trong 24 giờ, khắc phục trong "
        "5 ngày.",
    ),
    "cases_note": (
        "Closed cases move to the archive with their case file. The list refreshes every 30 s.",
        "Vụ việc đã đóng chuyển vào lưu trữ cùng hồ sơ. Danh sách tự làm mới mỗi 30 giây.",
    ),
    "opened_by": ("Opened by", "Mở bởi"),
    "src_gate": ("gate", "cổng"),
    "src_judge": ("judge", "giám khảo"),
    "src_monitor": ("monitor", "giám sát"),
    "src_manual": ("person", "con người"),
    "joined_n": ("+{n} more stop(s) joined", "+{n} lần chặn khác gộp vào"),
    "hl_pause": (
        "{agent} paused: {what} was stopped before it ran",
        "{agent} bị tạm dừng: {what} đã bị chặn trước khi chạy",
    ),
    "hl_block": (
        "{agent}: {what} was blocked before it ran",
        "{agent}: {what} đã bị chặn trước khi chạy",
    ),
    "what_money": ("a money-moving call ({tool})", "một thao tác di chuyển tiền ({tool})"),
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
    "opened_by_judge": ("opened by a judge", "mở bởi giám khảo AI"),
    "opened_by_monitor": ("opened by a monitor", "mở bởi bộ giám sát"),
    "opened_by_manual": ("opened by a person", "mở bởi con người"),
    "case_line_pause": (
        "Rule {rule} ({desc}) paused the agent before the call reached the bank system.",
        "Quy tắc {rule} ({desc}) đã tạm dừng tác tử trước khi lệnh gọi tới hệ thống ngân hàng.",
    ),
    "case_line_block": (
        "Rule {rule} ({desc}) blocked the call before it reached the bank system.",
        "Quy tắc {rule} ({desc}) đã chặn lệnh gọi trước khi tới hệ thống ngân hàng.",
    ),
    "case_line_amount": ("Amount: {amount} {cur}.", "Số tiền: {amount} {cur}."),
    "case_line_latency": ("Detect-to-stop {ms} ms.", "Phát hiện đến chặn: {ms} ms."),
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
    "chain_lane": ("Chain lane", "Làn chuỗi"),
    "head": ("head", "đầu chuỗi"),
    "verify_again": ("Verify again", "Kiểm tra lại"),
    "casefile_btn": ("Case file", "Hồ sơ vụ việc"),
    "your_decision": ("Your decision", "Quyết định của bạn"),
    "need_two": (
        "To close a {sev} case, two different people must sign off, and one must be an approver.",
        "Để đóng vụ việc mức {sev}, cần hai người khác nhau phê duyệt, trong đó một người là "
        "người phê duyệt.",
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
    "contain_btn": ("Contain · keep agent paused", "Ngăn chặn · giữ tác tử tạm dừng"),
    "contain_btn_running": ("Contain · record what was done", "Ngăn chặn · ghi lại đã làm gì"),
    "contain_note": (
        "What was done to contain it (required)",
        "Đã làm gì để ngăn chặn (bắt buộc)",
    ),
    "agent_now": ("Agent {agent} is {state} now.", "Tác tử {agent} hiện đang {state}."),
    "pause_on_agents": ("Pause it on Agents →", "Tạm dừng ở trang Tác tử →"),
    "close_needs_two": ("Close (needs 2 sign-offs)", "Đóng (cần 2 phê duyệt)"),
    "close_why_open": ("Triage the case first.", "Cần phân loại vụ việc trước."),
    "close_why_two": (
        "{n} of 2 sign-offs so far. Two different people, one an approver.",
        "Đã có {n}/2 phê duyệt. Hai người khác nhau, một người là người phê duyệt.",
    ),
    "close_why_role": (
        "Only a reviewer or an admin can close a case.",
        "Chỉ người duyệt hoặc quản trị viên được đóng vụ việc.",
    ),
    "close_from_triaged": (
        "Before containment, only a false alarm can be closed.",
        "Trước khi ngăn chặn, chỉ báo động nhầm mới được đóng.",
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
        "Link a ticket to keep the bank ITSM in step with this case.",
        "Liên kết phiếu để đồng bộ ITSM của ngân hàng với vụ việc này.",
    ),
    "st_planned": ("Agent asked to run {tool}.", "Tác tử yêu cầu chạy {tool}."),
    "st_amount": ("Amount {amount} {cur}.", "Số tiền {amount} {cur}."),
    "st_read": ("Agent read data with {tool}.", "Tác tử đọc dữ liệu bằng {tool}."),
    "st_called": (
        "Agent called {tool} (allowed by the gate).",
        "Tác tử gọi {tool} (cổng cho phép).",
    ),
    "st_rule_pause": (
        "Rule {rule} matched: {desc}. Action: pause. The call did not run.",
        "Quy tắc {rule} khớp: {desc}. Hành động: tạm dừng. Lệnh gọi không được chạy.",
    ),
    "st_rule_block": (
        "Rule {rule} matched: {desc}. Action: block. The call did not run.",
        "Quy tắc {rule} khớp: {desc}. Hành động: chặn. Lệnh gọi không được chạy.",
    ),
    "st_latency": ("Detect-to-stop {ms} ms.", "Phát hiện đến chặn {ms} ms."),
    "st_t0b": (
        "Tier 0b screen: {why} → alert (advisory).",
        "Sàng lọc 0b: {why} → cảnh báo (tham khảo).",
    ),
    "st_judge": (
        "Tier {tier} judge: {label} → {action} (advisory).",
        "Giám khảo cấp {tier}: {label} → {action} (tham khảo).",
    ),
    "ev_open": (
        "Case opened by {who}. Reviewers notified in the inbox.",
        "{who} mở vụ việc. Người duyệt được báo trong hộp thư.",
    ),
    "ev_assign": ("{who} assigned the case.", "{who} đã giao vụ việc."),
    "ev_triage": ("{who} marked the case triaged.", "{who} đánh dấu vụ việc đã phân loại."),
    "ev_contain": ("{who} recorded the containment.", "{who} ghi nhận biện pháp ngăn chặn."),
    "ev_comment": ("{who} commented.", "{who} đã bình luận."),
    "ev_itsm": ("{who} linked an ITSM ticket.", "{who} liên kết phiếu ITSM."),
    "ev_join": ("Another stop joined this case.", "Một lần chặn khác được gộp vào vụ việc."),
    "ev_raise": ("{who} raised the severity.", "{who} nâng mức độ nghiêm trọng."),
    "ev_close": ("{who} closed the case ({detail}).", "{who} đóng vụ việc ({detail})."),
    "ev_other": ("{who}: {action}", "{who}: {action}"),
    "st_signoff": ("{who} signed off: {decision}.", "{who} phê duyệt: {decision}."),
    "st_waiting": ("Waiting for a person: {next}.", "Đang chờ con người: {next}."),
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
    "no_verdicts": ("No rule or judge verdict linked yet.", "Chưa có kết luận nào được liên kết."),
    "rules_tab_why": (
        "Only deterministic rules block or pause. AI judges read the rest and only advise.",
        "Chỉ quy tắc cố định mới chặn hoặc tạm dừng. Giám khảo AI đọc phần còn lại và chỉ tư vấn.",
    ),
    "verdict_details": ("Every check on this case", "Mọi lần kiểm tra của vụ việc"),
    "checker": ("Checker", "Bộ kiểm tra"),
    "label": ("Label", "Nhãn"),
    "score_bp": ("Score (0-10000)", "Điểm (0-10000)"),
    "more_lines": ("{n} more lines in the Transcript tab", "còn {n} dòng ở thẻ Hội thoại"),
    "no_transcript": (
        "No agent events are recorded for this case's trace.",
        "Không có sự kiện nào của tác tử cho vết của vụ việc này.",
    ),
    "masking_note": (
        "Personal data is masked at capture. Raw text never enters the chain or reaches the "
        "judges.",
        "Dữ liệu cá nhân được che ngay khi ghi nhận. Văn bản gốc không bao giờ vào chuỗi hay "
        "tới giám khảo.",
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
    "key_dev": ("dev key", "khóa dev"),
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
        "A view only. The audit pack writes the files and records their hashes on the chain.",
        "Chỉ để xem. Gói kiểm toán ghi tệp và lưu mã băm của chúng lên chuỗi.",
    ),
    "signoff_purpose": (
        "Sign the statement as yourself. It is stored word for word and recorded on the chain.",
        "Ký lời xác nhận với tư cách của chính bạn. Lời xác nhận được lưu nguyên văn và ghi "
        "lên chuỗi.",
    ),
    "no_signoffs": ("No sign-off yet.", "Chưa có phê duyệt."),
    "go_close": ("Go to the case to close it", "Về vụ việc để đóng"),
    "signoff_recorded": ("Sign-off recorded.", "Đã ghi nhận phê duyệt."),
    # ---- WP12 evidence
    "ev_purpose_lead": (
        "Every decision Supervisor makes, and every action a person takes, is written to a "
        "hash chain.",
        "Mọi quyết định của Supervisor và mọi thao tác của con người đều được ghi vào chuỗi băm.",
    ),
    "ev_purpose_rest": (
        "Edit one byte anywhere and the verifier says where.",
        "Sửa một byte ở bất kỳ đâu, công cụ kiểm tra sẽ chỉ ra vị trí.",
    ),
    "ev_why": (
        "Lane heads are committed by a signed root and anchored to write-once storage. You can "
        "verify an export on a laptop with no network.",
        "Đầu các làn được chốt bằng một gốc có chữ ký và neo vào kho chỉ-ghi-một-lần. Có thể "
        "kiểm tra bản xuất trên máy tính không có mạng.",
    ),
    "lanes_sub": ("{n} agent lane(s) + 1 root lane", "{n} làn tác tử + 1 làn gốc"),
    "anchor_target_worm": ("write-once folder", "thư mục chỉ-ghi-một-lần"),
    "anchor_target_uc": ("UC Volume", "UC Volume"),
    "not_anchored_why": (
        "No anchor yet. The anchor job writes one "
        "(scheduler, or python -m supervisor.jobs.anchor).",
        "Chưa có lần neo. Tác vụ neo sẽ ghi (bộ lập lịch, hoặc python -m supervisor.jobs.anchor).",
    ),
    "signed_n": ("{n} signed", "{n} đã ký"),
    "ok_word": ("ok", "ổn"),
    "no_chain": ("The chain is empty.", "Chuỗi đang trống."),
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
    "export_chain": ("Export chain", "Xuất chuỗi"),
    "working": ("working…", "đang xử lý…"),
    "chain_exported": ("Chain exported", "Đã xuất chuỗi"),
    "pack_built": ("Audit pack built ({n} case files)", "Đã tạo gói kiểm toán ({n} hồ sơ)"),
    "offline_verify": ("offline verify", "kiểm tra ngoại tuyến"),
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
    "no_packs": ("Nothing exported yet.", "Chưa xuất gì."),
    # ---- WP12 onboard
    "onboard_title": ("Onboard an agent", "Tiếp nhận một tác tử"),
    "ob_purpose_lead": (
        "Bring a new or existing agent under supervision in six steps.",
        "Đưa một tác tử mới hoặc đang chạy vào giám sát qua sáu bước.",
    ),
    "ob_purpose_rest": (
        "Supervisor reads the code and traces, proposes rules, and opens a pull request. "
        "People approve every step.",
        "Supervisor đọc mã nguồn và vết hoạt động, đề xuất quy tắc và mở pull request. Con "
        "người duyệt từng bước.",
    ),
    "ob_why": (
        "Nothing is merged automatically. The onboarding agent itself runs under Watch.",
        "Không có gì được hợp nhất tự động. Bản thân tác tử tiếp nhận cũng chạy dưới giám sát.",
    ),
    "ws_discover": (
        "Find the repo, prompts, tools, tables, traces.",
        "Tìm repo, prompt, công cụ, bảng dữ liệu, vết hoạt động.",
    ),
    "ws_understand": (
        "Risk profile with file:line evidence. Decision 33 class.",
        "Hồ sơ rủi ro có bằng chứng tệp:dòng. Phân loại QĐ 33.",
    ),
    "ws_plan": (
        "Pick checks from the catalogue. Thresholds. Cost.",
        "Chọn kiểm tra từ danh mục. Ngưỡng. Chi phí.",
    ),
    "ws_instrument": (
        "Rules YAML, tracing hook, dashboard → pull request.",
        "YAML quy tắc, móc ghi vết, bảng theo dõi → pull request.",
    ),
    "ws_launch": (
        "Red-team pack in a sandbox. Baseline. Go / no-go.",
        "Bộ tấn công thử trong sandbox. Mốc chuẩn. Quyết định đi / dừng.",
    ),
    "ws_operate": ("Hand over to Watch.", "Bàn giao cho Giám sát."),
    "start": ("Start", "Bắt đầu"),
    "repo_path": (
        "Agent folder (inside a git repo; relative to the Supervisor folder)",
        "Thư mục tác tử (trong repo git; tính từ thư mục Supervisor)",
    ),
    "discover_btn": ("Discover", "Khám phá"),
    "start_hint": (
        "Read-only access. Secrets are scrubbed before any model reads the code. About a "
        "minute for a small repo. Without a reachable model the run uses the mock (labelled).",
        "Chỉ đọc. Bí mật được xóa trước khi mô hình đọc mã. Khoảng một phút với repo nhỏ. "
        "Khi không có mô hình, lần chạy dùng bản giả lập (có nhãn).",
    ),
    "onboard_off": (
        "Starting a run from the console is off by default (CONSOLE_ONBOARD_ENABLED=1 turns it "
        "on). From the command line:",
        "Chạy từ bảng điều khiển đang tắt theo mặc định (CONSOLE_ONBOARD_ENABLED=1 để bật). "
        "Từ dòng lệnh:",
    ),
    "ob_running": ("running: {agent}", "đang chạy: {agent}"),
    "ob_done": ("finished: {agent}", "đã xong: {agent}"),
    "ob_failed": ("failed: {agent}", "thất bại: {agent}"),
    "ob_started": ("started by {who} at {time}", "{who} bắt đầu lúc {time}"),
    "last_run": ("Last run · {agent}", "Lần chạy gần nhất · {agent}"),
    "ob_profile": ("Profile", "Hồ sơ"),
    "ob_plan": ("Plan", "Kế hoạch"),
    "ob_launch": ("Launch report", "Báo cáo ra mắt"),
    "high_risk": ("high-risk", "rủi ro cao"),
    "not_high_risk": ("not high-risk", "không rủi ro cao"),
    "human_gate": ("Human approval step in code", "Bước con người duyệt trong mã"),
    "yes": ("yes", "có"),
    "no": ("no", "không"),
    "proposed_risk": ("Proposed risk tier", "Mức rủi ro đề xuất"),
    "no_human_gate_hint": (
        "A pause is not pre-execution approval. The agent needs its own approval step.",
        "Tạm dừng không thay cho phê duyệt trước khi thực thi. Tác tử cần bước duyệt riêng.",
    ),
    "caps_selected": ("{on} of {n} capabilities on", "{on}/{n} năng lực được bật"),
    "rules_proposed": (
        "{n} rules proposed, {s} block or pause (need two approvers)",
        "{n} quy tắc đề xuất, {s} chặn hoặc tạm dừng (cần hai người duyệt)",
    ),
    "judges_planned": ("Judges", "Giám khảo"),
    "caught_n": ("{c} / {e} red-team cases caught", "bắt được {c} / {e} tình huống tấn công"),
    "false_alarms": (
        "false alarms {p}% ({f} of {b} benign)",
        "báo động nhầm {p}% ({f} trên {b} tình huống lành)",
    ),
    "branch": ("branch", "nhánh"),
    "launch_mock_note": (
        "profile written with the mock model; rules and red-team results are real",
        "hồ sơ viết bằng mô hình giả lập; quy tắc và kết quả tấn công thử là thật",
    ),
    "not_yet": ("Not written yet.", "Chưa có."),
    "artefacts": ("Artefacts", "Tệp kết quả"),
    "no_runs": (
        "No onboarding run yet. Start one above, or run python -m supervisor.onboard.",
        "Chưa có lần tiếp nhận nào. Bắt đầu ở trên, hoặc chạy python -m supervisor.onboard.",
    ),
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
        "People sign in with the workspace SSO; every action records the auth method.",
        "Người dùng đăng nhập bằng SSO của workspace; mọi thao tác ghi lại cách đăng nhập.",
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
        "Dev key on this machine. Bank key custody decision pending (HSM / KMS).",
        "Khóa dev trên máy này. Đang chờ quyết định lưu giữ khóa của ngân hàng (HSM / KMS).",
    ),
    "h_key_managed": ("Key managed by the bank.", "Khóa do ngân hàng quản lý."),
    "h_anchor": ("Anchor target", "Nơi neo"),
    "h_no_anchor": (
        "No anchor written yet (the anchor job runs on the scheduler).",
        "Chưa có lần neo (tác vụ neo chạy theo bộ lập lịch).",
    ),
    "h_databricks": ("Databricks", "Databricks"),
    "h_databricks_in_use": (
        "Live workspace checks create a probe table: run python -m supervisor.preflight.",
        "Kiểm tra workspace trực tiếp tạo bảng thử: chạy python -m supervisor.preflight.",
    ),
    "h_databricks_off": (
        "Not configured on this machine (no OAuth profile, SQLite store).",
        "Chưa cấu hình trên máy này (không có hồ sơ OAuth, dùng SQLite).",
    ),
    "h_onboard": ("Onboard from the console", "Tiếp nhận từ bảng điều khiển"),
    "h_onboard_detail": (
        "CONSOLE_ONBOARD_ENABLED turns the Start form on (off by default).",
        "CONSOLE_ONBOARD_ENABLED bật biểu mẫu Bắt đầu (mặc định tắt).",
    ),
    "preflight_checks": ("Preflight checks", "Kiểm tra preflight"),
    "n_failed": ("{n} failed", "{n} lỗi"),
    "all_pass": ("no failure", "không có lỗi"),
    "health_note": (
        "Secret values are never shown. The command line gives the same list: "
        "python -m supervisor.cli preflight.",
        "Không bao giờ hiển thị giá trị bí mật. Dòng lệnh cho cùng danh sách: "
        "python -m supervisor.cli preflight.",
    ),
    "health_note_dbx": (
        "The Databricks checks (sign-in, warehouse, schema, serving endpoint, Volume) run only "
        "from the command line because they write probes.",
        "Các kiểm tra Databricks (đăng nhập, warehouse, schema, endpoint, Volume) chỉ chạy từ "
        "dòng lệnh vì chúng ghi dữ liệu thử.",
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
    "metrics_purpose": (
        "Daily oversight numbers per agent: coverage, time to detect, time to a human, judge "
        "quality.",
        "Số liệu giám sát hằng ngày theo tác tử: độ bao phủ, thời gian phát hiện, thời gian "
        "tới con người, chất lượng giám khảo.",
    ),
    "metrics_why": (
        "These are the numbers a risk committee asks for. Definitions: docs/metrics.md.",
        "Đây là số liệu hội đồng rủi ro cần. Định nghĩa: docs/metrics.md.",
    ),
    "day": ("Day", "Ngày"),
    "all_rows": ("All rows ({n})", "Tất cả các dòng ({n})"),
    "flow_open": ("open", "mở"),
    "flow_triaged": ("triaged", "đã phân loại"),
    "flow_contained": ("contained", "đã ngăn chặn"),
    "flow_closed": ("closed", "đã đóng"),
    "next_triaged": ("triage", "phân loại"),
    "next_contained": ("contain", "ngăn chặn"),
    "next_closed": ("sign-off and close", "phê duyệt và đóng"),
    "itsm_ph": ("e.g. INC0012345", "ví dụ INC0012345"),
    "demo_note": (
        "Demo data: the agents' replies are scripted and the customers are synthetic. The "
        "gate decisions, the pause and the chain are real.",
        "Dữ liệu demo: câu trả lời của tác tử theo kịch bản và khách hàng là giả lập. Quyết "
        "định của cổng, việc tạm dừng và chuỗi bằng chứng là thật.",
    ),
    # ---- WP17 assurance
    "nav_assurance": ("Assurance", "Đảm bảo chất lượng"),
    "as_purpose": (
        "Results of the assurance eval packs: accuracy, hallucination, bias, dependency, "
        "security and robustness tests run on agents, traces and the judge.",
        "Kết quả các gói kiểm thử đảm bảo: độ chính xác, ảo giác, thiên vị, phụ thuộc, "
        "bảo mật và độ bền, chạy trên tác tử, dấu vết và giám khảo AI.",
    ),
    "as_why": (
        "Thresholds are illustrative until the bank sets its own. A skipped pack is never a pass.",
        "Ngưỡng chỉ mang tính minh họa cho đến khi ngân hàng đặt ngưỡng riêng. Gói bị bỏ qua "
        "không bao giờ được tính là đạt.",
    ),
    "as_run": ("Run", "Lần chạy"),
    "as_target": ("Target", "Đối tượng"),
    "as_counts": ("Results", "Kết quả"),
    "as_kind": ("Label", "Nhãn"),
    "as_selector": ("selector", "bộ chọn"),
    "as_no_runs": (
        "No assurance run yet. Run:",
        "Chưa có lần chạy nào. Hãy chạy:",
    ),
    "as_all_runs": ("All runs", "Tất cả lần chạy"),
    "as_mock_note": (
        "MOCK: at least one result comes from a mock model or target. The numbers prove the "
        "harness, not a real model.",
        "MÔ PHỎNG: ít nhất một kết quả đến từ mô hình hoặc đối tượng giả lập. Số liệu chỉ "
        "chứng minh bộ kiểm thử, không phải mô hình thật.",
    ),
    "as_pack": ("Pack", "Gói"),
    "as_dimension": ("Dimension", "Khía cạnh"),
    "as_metrics": ("Metrics vs thresholds", "Chỉ số so với ngưỡng"),
    "as_data": ("Data", "Dữ liệu"),
    "as_reasons": ("Reasons", "Lý do"),
    "as_gate": ("launch gate", "cổng ra mắt"),
    "as_judge_gate": ("judge gate", "cổng giám khảo"),
    "as_no_chain": ("not on chain", "chưa ghi chuỗi"),
    "as_no_results": ("No results in this run.", "Lần chạy này chưa có kết quả."),
    "as_illustrative": (
        "Thresholds are illustrative defaults until the bank sets its own.",
        "Ngưỡng là giá trị minh họa cho đến khi ngân hàng đặt ngưỡng riêng.",
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
