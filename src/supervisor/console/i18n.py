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
    "kept_args": ("Arguments passed unmasked", "Tham số được chuyển không che"),
    "kept_args_hint": (
        "The policy keeps these arguments as sent (a lookup key). Records, chain and findings "
        "still hold them masked.",
        "Chính sách giữ nguyên các tham số này (khóa tra cứu). "
        "Bản ghi, chuỗi và phát hiện vẫn che chúng.",
    ),
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
    # ---- WP1b-B monitor status on the Metrics page
    "monitor_status": ("Monitor status", "Trạng thái bộ giám sát"),
    "monitor_status_purpose": (
        "Each monitor says what it did for each agent. 'not applicable' names the missing "
        "binding; 'no data' means the binding exists but nothing was computed yet.",
        "Mỗi bộ giám sát cho biết nó đã làm gì với từng tác tử. 'không áp dụng' nêu cấu hình "
        "còn thiếu; 'chưa có dữ liệu' nghĩa là đã cấu hình nhưng chưa tính được gì.",
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
        "Alerts raised by the rules in config/alerts.yaml. An operator acknowledges an alert; "
        "the action is audited.",
        "Cảnh báo do các quy tắc trong config/alerts.yaml tạo ra. Người vận hành xác nhận cảnh "
        "báo; hành động được ghi nhật ký.",
    ),
    "alerts_open": ("open", "đang mở"),
    "alerts_ack": ("acknowledged", "đã xác nhận"),
    "alert_ack_btn": ("Acknowledge", "Xác nhận"),
    "alert_rule": ("Rule", "Quy tắc"),
    "alert_window": ("Window", "Cửa sổ"),
    "alert_repeats": ("Repeats", "Lặp lại"),
    "alert_chain": ("Chain", "Chuỗi"),
    "no_alerts": ("No alerts.", "Không có cảnh báo."),
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
    # ---- WP14 compliance advisor tab
    "nav_compliance": ("Compliance", "Tuân thủ"),
    "cp_title": ("Compliance advisor", "Cố vấn tuân thủ"),
    "cp_purpose": (
        "See which legal duties apply to each agent and which Supervisor controls cover them.",
        "Xem nghĩa vụ pháp lý nào áp dụng cho từng tác tử và biện pháp nào của Supervisor đáp ứng.",
    ),
    "cp_why": (
        "Every status names a control and a product fact. A fact we do not know becomes a "
        "question, never a guess.",
        "Mỗi trạng thái nêu rõ biện pháp kiểm soát và dữ kiện sản phẩm. Dữ kiện chưa biết "
        "trở thành câu hỏi, không bao giờ là phỏng đoán.",
    ),
    "cp_advisory": ("Advisory only", "Chỉ mang tính tham khảo"),
    "cp_disclaimer": (
        "Not legal advice. Bank counsel must confirm.",
        "Không phải tư vấn pháp lý. Cần pháp chế ngân hàng xác nhận.",
    ),
    "cp_off": (
        "The Compliance tab is off by default. Set CONSOLE_COMPLIANCE_ENABLED=1 and restart "
        "the console to turn it on. From the command line:",
        "Thẻ Tuân thủ đang tắt theo mặc định. Đặt CONSOLE_COMPLIANCE_ENABLED=1 rồi khởi động "
        "lại bảng điều khiển để bật. Từ dòng lệnh:",
    ),
    "cp_no_agents": ("No compliance matrix yet.", "Chưa có ma trận tuân thủ nào."),
    "cp_source_demo": ("demo agent", "tác tử demo"),
    "cp_source_onboard": ("onboarded product", "sản phẩm đã tiếp nhận"),
    "cp_applies_yes": ("Apply", "Áp dụng"),
    "cp_needs_answer": ("Need an answer", "Cần trả lời"),
    "cp_questions": ("Open questions", "Câu hỏi còn mở"),
    "cp_threshold_gaps": ("Threshold gaps", "Hạn mức vượt trần"),
    "cp_d33": ("Decision 33 (suggestion)", "Quyết định 33 (gợi ý)"),
    "cp_open": ("Open matrix", "Mở ma trận"),
    "cp_back": ("All agents", "Tất cả tác tử"),
    "cp_counts": ("Rows that apply, by status", "Dòng áp dụng, theo trạng thái"),
    "cp_filters": ("Filters", "Bộ lọc"),
    "cp_instrument": ("Instrument", "Văn bản"),
    "cp_duty": ("Duty", "Nhiệm vụ"),
    "cp_applies": ("Applies", "Áp dụng"),
    "cp_any": ("any", "tất cả"),
    "cp_apply_filter": ("Apply filter", "Lọc"),
    "cp_showing": ("Showing {n} of {m} rows", "Hiển thị {n} trên {m} dòng"),
    "cp_col_obligation": ("Obligation", "Nghĩa vụ"),
    "cp_col_article": ("Article", "Điều"),
    "cp_col_summary": ("Summary", "Tóm tắt"),
    "cp_col_reason": ("Reason", "Lý do"),
    "cp_thresholds": ("Threshold findings", "Kết quả kiểm tra hạn mức"),
    "cp_col_limit": ("Limit (VND)", "Hạn mức (VND)"),
    "cp_col_cap": ("Cap (VND)", "Trần (VND)"),
    "cp_col_verdict": ("Verdict", "Kết luận"),
    "cp_none": ("none", "không có"),
    "cp_questions_list": ("Open questions", "Câu hỏi còn mở"),
    "cp_decides": ("decides {n} obligation(s)", "quyết định {n} nghĩa vụ"),
    "cp_d33_lines": ("Decision 33 reasoning", "Lập luận theo Quyết định 33"),
    "cp_ob_title": ("Obligation", "Nghĩa vụ"),
    "cp_text_vi": ("Text (Vietnamese)", "Nội dung (tiếng Việt)"),
    "cp_summary_en": ("Summary (English)", "Tóm tắt (tiếng Anh)"),
    "cp_no_text_vi": (
        "No Vietnamese text in RegKB for this obligation.",
        "RegKB chưa có nội dung tiếng Việt cho nghĩa vụ này.",
    ),
    "cp_instrument_line": ("Instrument", "Văn bản"),
    "cp_sources": ("Sources", "Nguồn"),
    "cp_controls": ("Controls that cover it", "Biện pháp kiểm soát"),
    "cp_coverage": ("coverage", "mức độ"),
    "cp_this_product": ("This product", "Sản phẩm này"),
    "cp_status_reason": ("Why this status", "Vì sao có trạng thái này"),
    "cp_evidence_needed": ("Evidence needed", "Bằng chứng cần có"),
    "cp_mock_hidden": (
        "A narrative, if the file holds one, is not shown here.",
        "Phần diễn giải (nếu có trong tệp) không hiển thị ở đây.",
    ),
    "cp_file_links": ("Files of this run", "Tệp của lần chạy này"),
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
        "What it takes to bring an agent under Watch.",
        "Điều cần để đưa tác tử vào giám sát.",
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
    "nav_tools": ("Tools", "Công cụ"),
    "tl_purpose": (
        "Gate decisions per agent and tool: calls, outcomes, latency, and which allowed tools "
        "were never used. Review each allowed tool against its use or a documented exception.",
        "Quyết định của cổng theo tác tử và công cụ: số lần gọi, kết quả, độ trễ, và công cụ "
        "được phép nhưng chưa từng dùng. Mỗi công cụ được phép cần có lý do sử dụng hoặc ngoại "
        "lệ được ghi nhận.",
    ),
    "tl_why": (
        "Least privilege (NIST SP 800-53 AC-6). The suggestion is a diff for a person to review. "
        "Nothing is applied from this screen.",
        "Đặc quyền tối thiểu (NIST SP 800-53 AC-6). Đề xuất chỉ là bản diff để người xem xét. "
        "Không có gì được áp dụng từ màn hình này.",
    ),
    "tl_window": ("Window", "Khoảng thời gian"),
    "tl_tool": ("Tool", "Công cụ"),
    "tl_risk": ("Risk", "Rủi ro"),
    "tl_status": ("Status", "Trạng thái"),
    "tl_calls": ("Calls", "Số lần gọi"),
    "tl_allow": ("Allow", "Cho phép"),
    "tl_block": ("Block", "Chặn"),
    "tl_pause": ("Pause", "Tạm dừng"),
    "tl_err": ("Err", "Lỗi"),
    "tl_p50": ("p50 us", "p50 us"),
    "tl_p95": ("p95 us (worst day)", "p95 us (ngày tệ nhất)"),
    "tl_users": ("Users/day max", "Người dùng/ngày tối đa"),
    "tl_last": ("Last seen", "Lần cuối"),
    "tl_declared_from": ("declared from", "khai báo từ"),
    "tl_st_used": ("used", "đã dùng"),
    "tl_st_unused": ("unused", "chưa dùng"),
    "tl_st_undeclared": ("not declared", "chưa khai báo"),
    "tl_st_exception": ("exception", "ngoại lệ"),
    "tl_conf_ok": ("data ok", "dữ liệu đủ"),
    "tl_conf_low": ("low history", "ít dữ liệu"),
    "tl_conf_no_data": ("no data", "chưa có dữ liệu"),
    "tl_suggest": ("Least-privilege suggestion", "Đề xuất đặc quyền tối thiểu"),
    "tl_remove": ("Remove (unused, risky first)", "Gỡ bỏ (chưa dùng, rủi ro trước)"),
    "tl_none": ("No unused tool in this window.", "Không có công cụ chưa dùng trong khoảng này."),
    "tl_undeclared": ("Called but not declared", "Đã gọi nhưng chưa khai báo"),
    "tl_warning": ("Warning", "Cảnh báo"),
    "tl_not_applied": (
        "Suggestion only. Nothing was changed. Apply it through the policy change path "
        "(docs/tool-analytics.md).",
        "Chỉ là đề xuất. Chưa có gì bị thay đổi. Áp dụng qua quy trình thay đổi chính sách "
        "(docs/tool-analytics.md).",
    ),
    "tl_download": ("Download diff", "Tải bản diff"),
    "tl_download_owner": (
        "Only the agent owner can download the diff.",
        "Chỉ chủ sở hữu tác tử được tải bản diff.",
    ),
    "tl_nodata": (
        "No usage data yet. Run:",
        "Chưa có dữ liệu sử dụng. Hãy chạy:",
    ),
    # ---- WP24 inventory
    "nav_inventory": ("Inventory", "Kiểm kê"),
    "inv_purpose": (
        "What each agent runs on: model endpoints, tools, MCP servers, datasets and hosting, "
        "each with its evidence. Risk passes up from tools and endpoints to the agent.",
        "Mỗi tác tử chạy trên gì: điểm cuối mô hình, công cụ, máy chủ MCP, dữ liệu và nơi "
        "lưu trữ, kèm bằng chứng. Mức rủi ro đi lên từ công cụ và điểm cuối tới tác tử.",
    ),
    "inv_why": (
        "Unmanaged items run in the workspace but no Supervisor manifest covers them (shadow "
        "AI). Each opens one low-severity case. Decision 33 class is set by people only.",
        "Mục chưa quản lý chạy trong workspace nhưng chưa có bản kê khai Supervisor (AI ngầm). "
        "Mỗi mục mở một hồ sơ mức thấp. Phân loại Quyết định 33 chỉ do con người đặt.",
    ),
    "inv_agent": ("Agent", "Tác tử"),
    "inv_tree": ("Subgraph (indented tree)", "Đồ thị con (cây thụt lề)"),
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
    "pager_label": ("Pages", "Phân trang"),
    "pager_showing": ("Showing {a}-{b} of {n}", "Hiển thị {a}-{b} trên {n}"),
    "pager_prev": ("Previous", "Trước"),
    "pager_next": ("Next", "Sau"),
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
    "agent_controls": ("Lifecycle and controls", "Vòng đời và điều khiển"),
    "agent_controls_hint": (
        "Pause, resume and quarantine are on the agent page: open a row, then the agent page.",
        "Tạm dừng, tiếp tục và cách ly nằm ở trang tác tử: mở một dòng, rồi mở trang tác tử.",
    ),
    "no_agents_filtered": (
        "No agent matches these filters.",
        "Không có tác tử nào khớp bộ lọc này.",
    ),
    "no_rules": ("No rule in scope", "Không có quy tắc áp dụng"),
    "no_rules_line": (
        "No deployed rule names this agent.",
        "Chưa có quy tắc nào được triển khai cho tác tử này.",
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
    "soon_pill": ("Coming in WP-UX3", "Sắp có ở WP-UX3"),
    "soon_line": ("This page is coming in WP-UX3.", "Trang này sẽ có ở WP-UX3."),
    "soon_why": (
        "The menu entry is here so the structure is final. No data is lost; it is recorded.",
        "Mục menu đã có để cấu trúc được chốt. Không mất dữ liệu: dữ liệu đã được ghi sẵn.",
    ),
    "see_all": ("See all", "Xem tất cả"),
    "span_tree": ("Span tree", "Cây span"),
    "span_unparented": ("Spans without a parent", "Span không có span cha"),
    "span_cut": ("loop cut", "đã cắt vòng lặp"),
    "span_capped": ("Showing the first {n} spans only.", "Chỉ hiển thị {n} span đầu tiên."),
    "span_none": ("No span in this trace", "Dấu vết này không có span"),
    "no_decisions_line": (
        "Decisions appear here when an agent calls the gate.",
        "Quyết định sẽ hiện ở đây khi tác tử gọi cổng.",
    ),
    # --- WP-UX3: new pages
    "nav_playground": ("Playground", "Chạy thử"),
    "rule_col": ("Rule", "Quy tắc"),
    "actor": ("Actor", "Người thực hiện"),
    "actor_kind": ("Actor kind", "Loại người thực hiện"),
    "agent_scope": ("Agent scope", "Phạm vi tác tử"),
    "amount_vnd": ("Amount (VND)", "Số tiền (VND)"),
    "approvals": ("Approvals", "Phê duyệt"),
    "arg_keys": ("Argument keys", "Khóa đối số"),
    "args_hash": ("Arguments hash", "Băm đối số"),
    "args_masked": ("Arguments (masked)", "Đối số (đã che)"),
    "result_masked": ("Result (masked)", "Kết quả (đã che)"),
    "advisory": ("advisory", "chỉ tư vấn"),
    "caller_agent": ("Caller agent", "Tác tử gọi"),
    "capture_level": ("Capture level", "Mức ghi nhận"),
    "chain_seq": ("Chain seq", "Số thứ tự chuỗi"),
    "description": ("Description", "Mô tả"),
    "effective_from": ("Effective from", "Hiệu lực từ"),
    "entry_hash": ("Entry hash", "Băm mục"),
    "payload_hash": ("Payload hash", "Băm nội dung"),
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
        "Only the newest 20,000 records were read; older ones are not counted.",
        "Chỉ đọc 20.000 bản ghi mới nhất; bản ghi cũ hơn không được tính.",
    ),
    "span_id": ("Span id", "Mã span"),
    "target": ("Target", "Đối tượng"),
    "this_row": ("this row", "dòng này"),
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
    "outcome_attempted": ("attempted", "đã thử"),
    "outcome_ok": ("ok", "thành công"),
    "outcome_denied": ("denied", "bị từ chối"),
    "outcome_error": ("error", "lỗi"),
    "decisions_purpose": (
        "Every allow, block, pause and alert the gate decided, newest first.",
        "Mọi quyết định cho phép, chặn, tạm dừng và cảnh báo của cổng, mới nhất trước.",
    ),
    "decisions_why": (
        "Open a row to see the rule hits, the evidence position and the case it opened. "
        "Arguments are never shown, only a keyed hash.",
        "Mở một dòng để xem quy tắc đã khớp, vị trí bằng chứng và vụ việc đã mở. Đối số "
        "không bao giờ hiển thị, chỉ có mã băm có khóa.",
    ),
    "no_rule_hits": ("No rule matched", "Không có quy tắc nào khớp"),
    "no_rule_hits_line": (
        "The call matched no rule, so it was allowed by default.",
        "Lệnh gọi không khớp quy tắc nào nên được cho phép mặc định.",
    ),
    "no_chain_entry": ("No evidence entry found", "Không tìm thấy mục bằng chứng"),
    "no_chain_entry_line": (
        "The decision is not in the chain yet, or the evidence sink was a buffer.",
        "Quyết định chưa có trong chuỗi, hoặc nơi ghi bằng chứng chỉ là bộ đệm.",
    ),
    "traces_purpose": (
        "One row per trace: the agent, when it started, how many spans and what the checks said.",
        "Mỗi dòng là một dấu vết: tác tử, thời điểm bắt đầu, số span và kết luận của các kiểm tra.",
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
        "Change the filters, or wait for agent events.",
        "Đổi bộ lọc, hoặc chờ sự kiện của tác tử.",
    ),
    "trace_title": ("Trace", "Dấu vết"),
    "copy_id": ("Copy id", "Sao chép mã"),
    "n_spans": ("{n} spans", "{n} span"),
    "span_detail": ("Selected span", "Span đã chọn"),
    "tree_legend": (
        "P pause, B block, A alert, J judge verdict (advisory).",
        "P tạm dừng, B chặn, A cảnh báo, J kết luận của giám khảo (chỉ tư vấn).",
    ),
    "trace_capped": (
        "Large trace: some spans are not drawn (+{n} more).",
        "Dấu vết lớn: một số span không được vẽ (+{n} nữa).",
    ),
    "plus_more": ("+{n} more spans", "+{n} span nữa"),
    "event_word": ("Event", "Sự kiện"),
    "parent_span": ("Parent span", "Span cha"),
    "digest_only": (
        "Digest level: this event stores no text, only hashes and numbers.",
        "Mức digest: sự kiện này không lưu văn bản, chỉ có mã băm và số.",
    ),
    "no_verdicts_span": (
        "No verdict is attached to this span.",
        "Span này không có kết luận đính kèm.",
    ),
    "src_tier0": ("Gate rule", "Quy tắc cổng"),
    "src_tier0b": ("Tier 0b finding", "Phát hiện Tier 0b"),
    "no_span": ("No span selected", "Chưa chọn span"),
    "no_span_line": ("Pick a span in the tree.", "Chọn một span trong cây."),
    "dry_run_pill": ("dry run, nothing recorded", "chạy thử, không ghi nhận"),
    "playground_purpose": (
        "Ask the gate what it would decide for a call, without making the call.",
        "Hỏi cổng xem sẽ quyết định thế nào cho một lệnh gọi, mà không thực hiện lệnh gọi.",
    ),
    "playground_why": (
        "Nothing is written: no verdict, no evidence, no agent state change, no metric. "
        "Rules that count calls over time are not evaluated.",
        "Không ghi gì: không kết luận, không bằng chứng, không đổi trạng thái tác tử, "
        "không số liệu. Quy tắc đếm lệnh gọi theo thời gian không được đánh giá.",
    ),
    "pg_inputs": ("Call to check", "Lệnh gọi cần kiểm tra"),
    "pg_args": ("Arguments (JSON object)", "Đối số (đối tượng JSON)"),
    "pg_context": ("Context (JSON object)", "Ngữ cảnh (đối tượng JSON)"),
    "pg_note": (
        "Use synthetic data. The arguments are not stored; the audit log keeps only a keyed hash.",
        "Dùng dữ liệu giả lập. Đối số không được lưu; nhật ký kiểm toán chỉ giữ mã băm có khóa.",
    ),
    "pg_check": ("Check (dry run)", "Kiểm tra (chạy thử)"),
    "pg_result": ("Result", "Kết quả"),
    "pg_empty": ("No result yet", "Chưa có kết quả"),
    "pg_empty_line": ("Fill the form and press Check.", "Điền biểu mẫu và nhấn Kiểm tra."),
    "pg_error": ("The check failed", "Kiểm tra không thành công"),
    "pg_would_pause": ("would pause the agent", "sẽ tạm dừng tác tử"),
    "pg_allow": ("Call allowed", "Lệnh gọi được phép"),
    "pg_state_unchanged": (
        "The agent state was not changed. This answer is not in the evidence chain.",
        "Trạng thái tác tử không bị đổi. Câu trả lời này không có trong chuỗi bằng chứng.",
    ),
    "pg_rule_hits": ("Rule hits", "Quy tắc đã khớp"),
    "pg_not_evaluated": (
        "Not evaluated in a dry run (they count calls over time)",
        "Không đánh giá khi chạy thử (các quy tắc đếm lệnh gọi theo thời gian)",
    ),
    "pg_transformed": ("Transformed arguments", "Đối số sau khi biến đổi"),
    "pg_preview_line": (
        "Masked preview of the arguments: what the evidence would hold ({n} value(s) changed).",
        "Xem trước đối số đã che: nội dung bằng chứng sẽ lưu ({n} giá trị đã đổi).",
    ),
    "pg_no_masker": (
        "No masker is configured, so no argument text is shown.",
        "Chưa cấu hình bộ che, nên không hiển thị văn bản đối số.",
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
    "no_policy": ("No policy deployed", "Chưa triển khai chính sách"),
    "no_policy_line": (
        "Deploy a policy file to the rule table.",
        "Triển khai tệp chính sách vào bảng quy tắc.",
    ),
    "no_rules_filtered": ("No rule matches the filters.", "Không có quy tắc nào khớp bộ lọc."),
    "catalogue_caps": ("Catalogue capabilities", "Năng lực trong danh mục"),
    "catalogue_none": (
        "No gate-rule capability in the catalogue applies to this risk class.",
        "Không có năng lực quy tắc cổng nào trong danh mục áp dụng cho nhóm rủi ro này.",
    ),
    "credentials_purpose": (
        "Which agents hold an ingress key, and which service principals may speak for "
        "which agents.",
        "Tác tử nào có khóa đầu vào, và service principal nào được nói thay cho tác tử nào.",
    ),
    "credentials_why": (
        "Metadata only. A secret value is never shown or stored here.",
        "Chỉ có siêu dữ liệu. Giá trị bí mật không bao giờ hiển thị hay lưu ở đây.",
    ),
    "ingress_off": (
        "INGRESS_AUTH_ENABLED is off: the gate accepts calls without an agent credential.",
        "INGRESS_AUTH_ENABLED đang tắt: cổng nhận lệnh gọi không cần thông tin xác thực "
        "của tác tử.",
    ),
    "cred_kind": ("Credential kind", "Loại thông tin xác thực"),
    "cred_store": ("Key store", "Nơi lưu khóa"),
    "cred_agents_nokey": ("Agents without an active key", "Tác tử chưa có khóa hiệu lực"),
    "cred_store_error": ("Cannot read", "Không đọc được"),
    "cred_keys": ("Agent keys", "Khóa của tác tử"),
    "cred_identities": ("Identity map", "Bảng ánh xạ danh tính"),
    "cred_rotate": ("Issue or rotate a key", "Cấp hoặc đổi khóa"),
    "cred_rotate_line": (
        "Keys are issued and rotated on the command line, so a new secret never passes "
        "through the browser.",
        "Khóa được cấp và đổi bằng dòng lệnh, để bí mật mới không đi qua trình duyệt.",
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
    "no_keys": ("No key found", "Không có khóa"),
    "no_keys_line": ("Issue a key with the command below.", "Cấp khóa bằng lệnh bên dưới."),
    "principal": ("Principal", "Principal"),
    "no_identities": ("No identity mapped", "Chưa ánh xạ danh tính"),
    "no_identities_line": (
        "Add principals to the identities file.",
        "Thêm principal vào tệp danh tính.",
    ),
    "users_purpose": (
        "Who holds which role, and what each role may do.",
        "Ai giữ vai trò nào, và mỗi vai trò được làm gì.",
    ),
    "users_why": (
        "Read-only. Roles change in the config file under Git.",
        "Chỉ đọc. Vai trò đổi trong tệp cấu hình trên Git.",
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
    "no_users": ("No user configured", "Chưa cấu hình người dùng"),
    "no_users_line": (
        "Add users to the users file or to the role map.",
        "Thêm người dùng vào tệp người dùng hoặc bảng vai trò.",
    ),
    "audit_purpose": (
        "Every action taken in the console: who, what, on which target, and the result.",
        "Mọi thao tác trong bảng điều khiển: ai, làm gì, trên đối tượng nào, và kết quả.",
    ),
    "audit_why": (
        "Read-only and append-only. Each action has an attempt row and an outcome row.",
        "Chỉ đọc và chỉ thêm. Mỗi thao tác có một dòng thử và một dòng kết quả.",
    ),
    "before_hash": ("Hash before", "Băm trước"),
    "after_hash": ("Hash after", "Băm sau"),
    "hash_changed": ("Target changed", "Đối tượng đã đổi"),
    "same_request": ("Rows of the same request", "Các dòng cùng yêu cầu"),
    "no_audit": ("No audit row matches", "Không có dòng kiểm toán nào khớp"),
    "no_audit_line": (
        "Change the filters, or take an action in the console.",
        "Đổi bộ lọc, hoặc thực hiện một thao tác trong bảng điều khiển.",
    ),
    "integrations_purpose": (
        "Status of the outbound links: SIEM, webhook, pager, ITSM and SCIM.",
        "Trạng thái các kết nối đi ra: SIEM, webhook, pager, ITSM và SCIM.",
    ),
    "integrations_why": (
        "Read-only. Secrets and full URLs are never shown.",
        "Chỉ đọc. Bí mật và URL đầy đủ không bao giờ hiển thị.",
    ),
    "integrations_note": (
        "Pager, ITSM and SCIM are stubs with in-memory fakes until the bank connects them.",
        "Pager, ITSM và SCIM là bản mô phỏng trong bộ nhớ cho đến khi ngân hàng kết nối.",
    ),
    "integration_word": ("Integration", "Tích hợp"),
    "configured": ("Configured", "Đã cấu hình"),
    "enabled": ("Enabled", "Đã bật"),
    "last_delivery": ("Last delivery", "Lần gửi cuối"),
    "dead_letter": ("Dead letters", "Thư chết"),
    "stub_fake": ("stub (fake)", "mô phỏng"),
    "integ_siem": ("SIEM sink", "Đích SIEM"),
    "integ_webhook": ("Webhook notifier", "Webhook thông báo"),
    "integ_pager": ("Pager", "Pager"),
    "integ_itsm": ("ITSM", "ITSM"),
    "integ_scim": ("SCIM", "SCIM"),
    "integ_lanes": ("{n} lane cursor(s)", "{n} con trỏ làn"),
    "integ_queued": ("{n} queued", "{n} đang chờ"),
}


# --- WP29: risk register (Risks page, drawer, Risks tab on the Agent page) ---
_T.update(
    {
        "nav_risks": ("Risks", "Rủi ro"),
        "atab_risks": ("Risks", "Rủi ro"),
        "dtab_links": ("Links", "Liên kết"),
        "rk_purpose": (
            "The risk register: what can go wrong, how big it is, which controls hold it down.",
            "Sổ đăng ký rủi ro: điều gì có thể sai, lớn đến đâu, kiểm soát nào giữ nó ở mức thấp.",
        ),
        "rk_why": (
            "A mitigated risk keeps its lower residual score only while its linked controls "
            "show working evidence.",
            "Rủi ro được giảm nhẹ chỉ giữ điểm dư thấp khi các kiểm soát liên kết còn bằng chứng "
            "hoạt động.",
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
            "{n} mitigated risk(s) have no working control evidence yet; "
            "their residual score equals the inherent score.",
            "{n} rủi ro giảm nhẹ chưa có bằng chứng kiểm soát hoạt động; điểm dư bằng điểm gốc.",
        ),
        "rk_cat_money_movement": ("Money movement", "Di chuyển tiền"),
        "rk_cat_credit_decision": ("Credit decision", "Quyết định tín dụng"),
        "rk_cat_pii": ("Personal data", "Dữ liệu cá nhân"),
        "rk_cat_injection": ("Injection", "Tiêm lệnh"),
        "rk_cat_model_behaviour": ("Model behaviour", "Hành vi mô hình"),
        "rk_cat_availability": ("Availability", "Tính sẵn sàng"),
        "rk_cat_third_party": ("Third party", "Bên thứ ba"),
        "rk_st_draft": ("Draft", "Nháp"),
        "rk_st_active": ("Active", "Đang áp dụng"),
        "rk_st_retired": ("Retired", "Đã gỡ"),
        "rk_treat_avoid": ("Avoid", "Tránh"),
        "rk_treat_mitigate": ("Mitigate", "Giảm nhẹ"),
        "rk_treat_accept": ("Accept", "Chấp nhận"),
        "rk_treat_transfer": ("Transfer", "Chuyển giao"),
        "rk_col_risk": ("Risk", "Rủi ro"),
        "rk_col_category": ("Category", "Nhóm"),
        "rk_col_agents": ("Applies to", "Áp dụng cho"),
        "rk_col_inherent": ("Inherent", "Gốc"),
        "rk_col_residual": ("Residual", "Dư"),
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
            "no control showed activity",
            "chưa kiểm soát nào hoạt động",
        ),
        "rk_reason_no_links": ("no control linked", "chưa liên kết kiểm soát"),
        "rk_reason_no_supervised_agent": ("no supervised agent", "chưa có tác tử được giám sát"),
        "rk_reason_treatment_declared": ("residual as declared", "điểm dư như đã khai báo"),
        "rk_reason_stale_evidence": ("evidence is too old", "bằng chứng đã cũ"),
        "rk_reason_no_evidence_yet": ("evidence job has not run", "chưa chạy công việc bằng chứng"),
        "rk_reason_changed_since_evidence": (
            "risk or its controls changed since the last evidence pass",
            "rủi ro hoặc kiểm soát đã đổi sau lần lấy bằng chứng gần nhất",
        ),
        "rk_score_val": ("{s} ({l} x {i})", "{s} ({l} x {i})"),
        "rk_marginal": ("Marginal risk (AI)", "Rủi ro biên (AI)"),
        "rk_treatment_note": ("Treatment note", "Ghi chú xử lý"),
        "rk_declared": ("Residual as declared", "Điểm dư đã khai báo"),
        "rk_applies_to": ("Applies to agents", "Áp dụng cho tác tử"),
        "rk_anchor": ("Sits on", "Gắn với"),
        "rk_lnk_matrix": ("Compliance matrix rows", "Dòng ma trận tuân thủ"),
        "rk_lnk_rule": ("Gate rules", "Quy tắc cổng"),
        "rk_lnk_pack": ("Assurance packs", "Gói đánh giá"),
        "rk_lnk_monitor": ("Monitors", "Bộ giám sát"),
        "rk_lnk_case": ("Cases", "Vụ việc"),
        "rk_no_links": ("No links", "Chưa có liên kết"),
        "rk_trend": ("Residual score by window", "Điểm dư theo kỳ"),
        "rk_window_end": ("Window end", "Cuối kỳ"),
        "rk_rule_hits": ("Rule hits", "Lượt kích hoạt quy tắc"),
        "rk_rules_missing": ("Rules missing", "Quy tắc không còn"),
        "rk_pack_ok": ("Packs ok", "Gói đạt"),
        "rk_pack_fail": ("Packs failed", "Gói lỗi"),
        "rk_mon_ok": ("Monitors ok", "Bộ giám sát ổn"),
        "rk_ctl_working": ("Working", "Hoạt động"),
        "rk_ctl_failing": ("Failing", "Lỗi"),
        "rk_ctl_idle": ("Idle", "Chưa hoạt động"),
        "rk_agents_n": ("Agents", "Tác tử"),
        "rk_agents_excl": ("Excluded", "Bị loại"),
        "rk_no_trend": (
            "No evidence rows yet. python -m supervisor.jobs.risk_evidence writes them.",
            "Chưa có dòng bằng chứng. python -m supervisor.jobs.risk_evidence sẽ tạo.",
        ),
        "rk_level": ("Register level", "Mức trong sổ rủi ro"),
        "rk_via": ("via", "qua"),
        "rk_own": ("own", "riêng"),
        "rk_inherited": ("inherited", "thừa hưởng"),
        "rk_tab_none": (
            "No active risk reaches this agent.",
            "Không có rủi ro đang áp dụng nào chạm tới tác tử này.",
        ),
        "rk_tab_off": (
            "The risk register is off (RISK_REGISTER_ENABLED=1 turns it on).",
            "Sổ rủi ro đang tắt (đặt RISK_REGISTER_ENABLED=1 để bật).",
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
        "rk_lnk_control": ("Catalogue controls", "Kiểm soát trong danh mục"),
        "ct_purpose": (
            "The control catalogue: what the bank and the product do, what each control covers, and whether it works.",  # noqa: E501
            "Danh mục kiểm soát: ngân hàng và sản phẩm làm gì, mỗi kiểm soát bao phủ gì, và nó có hoạt động không.",  # noqa: E501
        ),
        "ct_why": (
            "One control covers many obligations and risks. It works only when runtime facts show it: a rule that fired, a real pack that passed, a monitor that is ok.",  # noqa: E501
            "Một kiểm soát bao phủ nhiều nghĩa vụ và rủi ro. Nó chỉ hoạt động khi dữ liệu chạy thật cho thấy: quy tắc đã kích hoạt, gói thật đã đạt, bộ giám sát ổn.",  # noqa: E501
        ),
        "ct_edit_note": (
            "Read only. Edit through /v1/controls or python -m supervisor.controls import.",
            "Chỉ đọc. Sửa qua /v1/controls hoặc python -m supervisor.controls import.",
        ),
        "ct_tile_active": ("Active", "Đang áp dụng"),
        "ct_tile_product": ("By the product", "Do sản phẩm"),
        "ct_tile_bank": ("By the bank", "Do ngân hàng"),
        "ct_failing_line": (
            "{n} active control(s) fail for at least one agent.",
            "{n} kiểm soát đang áp dụng bị lỗi với ít nhất một tác tử.",
        ),
        "ct_uncovered_line": (
            "{n} active risk(s) have no control.",
            "{n} rủi ro đang áp dụng chưa có kiểm soát.",
        ),
        "ct_col_control": ("Control", "Kiểm soát"),
        "ct_col_type": ("Type", "Loại"),
        "ct_col_by": ("Implemented by", "Thực hiện bởi"),
        "ct_col_covers": ("Obligations / risks", "Nghĩa vụ / rủi ro"),
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
        "ct_map_matrix": ("Obligations (matrix rows)", "Nghĩa vụ (dòng ma trận)"),
        "ct_map_risk": ("Risks", "Rủi ro"),
        "ct_map_rule": ("Gate rules", "Quy tắc cổng"),
        "ct_map_pack": ("Assurance packs", "Gói đánh giá"),
        "ct_map_monitor": ("Monitors", "Bộ giám sát"),
        "ct_map_detector": ("Detectors (reference)", "Bộ phát hiện (tham chiếu)"),
        "ct_map_document": ("Documents (reference)", "Tài liệu (tham chiếu)"),
        "ct_no_map": ("Nothing mapped", "Chưa ánh xạ gì"),
        "ct_status_by_agent": ("Status by agent", "Trạng thái theo tác tử"),
        "ct_refs": ("References", "Tham chiếu"),
        "ct_no_status": (
            "No status yet. python -m supervisor.jobs.control_status writes it.",
            "Chưa có trạng thái. python -m supervisor.jobs.control_status sẽ tạo.",
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
        "ct_reason_stale": ("too old", "đã cũ"),
        "ct_reason_bank_owned": (
            "bank process, not observed",
            "quy trình của ngân hàng, không quan sát được",
        ),
        "ct_reason_changed_since_evidence": (
            "changed since the evidence",
            "đã đổi sau khi có bằng chứng",
        ),
        "ct_tab_off": (
            "The control catalogue is off (CONTROLS_ENABLED=1 turns it on).",
            "Danh mục kiểm soát đang tắt (đặt CONTROLS_ENABLED=1 để bật).",
        ),
        "ct_tab_none": (
            "No control is in scope for this agent.",
            "Không có kiểm soát nào áp dụng cho tác tử này.",
        ),
        "ct_compliance": ("Controls with working evidence", "Kiểm soát có bằng chứng hoạt động"),
        "ct_none_in_scope": (
            "No control in scope: no figure.",
            "Không có kiểm soát: chưa có số liệu.",
        ),
        "ct_in_scope": ("in scope", "áp dụng"),
        "ct_product_line": (
            "Product controls: {n} in scope, {bp} bp working. Bank-owned controls in scope: {b} (they never show working).",  # noqa: E501
            "Kiểm soát của sản phẩm: {n} áp dụng, {bp} bp hoạt động. Kiểm soát của ngân hàng: {b} (không bao giờ hiện là hoạt động).",  # noqa: E501
        ),
        "ct_obligations": ("Obligations", "Nghĩa vụ"),
        "ct_open_page": ("Open the Controls page", "Mở trang Kiểm soát"),
        "tk_purpose": (
            "The task list: a right-sized set of tasks for each agent and lifecycle stage.",
            "Danh sách nhiệm vụ: bộ nhiệm vụ vừa đủ cho mỗi tác tử và giai đoạn vòng đời.",
        ),
        "tk_why": (
            "The set depends on the Decision 33 class and the risk level. A required task of the current stage blocks the move to the next stage and the launch GO.",  # noqa: E501
            "Bộ nhiệm vụ phụ thuộc phân loại Quyết định 33 và mức rủi ro. Nhiệm vụ bắt buộc của giai đoạn hiện tại chặn việc chuyển giai đoạn và GO khi ra mắt.",  # noqa: E501
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
        "tk_tile_waiver": ("Waiver waiting", "Chờ người thứ hai"),
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
        "tk_st_waived": ("waived", "miễn"),
        "tk_required": ("required", "bắt buộc"),
        "tk_optional": ("optional", "tùy chọn"),
        "tk_waive_pending": ("waiver waiting", "chờ miễn"),
        "tk_no_tasks": ("No tasks", "Chưa có nhiệm vụ"),
        "tk_no_match": ("No task matches the filters.", "Không có nhiệm vụ khớp bộ lọc."),
        "tk_no_tasks_line": (
            "python -m supervisor.tasks generate --agent <id> --user <name> makes the list of an agent.",  # noqa: E501
            "python -m supervisor.tasks generate --agent <id> --user <name> tạo danh sách cho tác tử.",  # noqa: E501
        ),
        "tk_dtab_history": ("History", "Lịch sử"),
        "tk_level": ("Sized for (level, class)", "Cỡ bộ nhiệm vụ (mức, phân loại)"),
        "tk_evidence": ("Evidence", "Bằng chứng"),
        "tk_done_by": ("Done by", "Hoàn thành bởi"),
        "tk_waive_reason": ("Waiver reason", "Lý do miễn"),
        "tk_waive_by": ("Waiver (asked, approved)", "Miễn (đề nghị, duyệt)"),
        "tk_action": ("Action", "Hành động"),
        "tk_actor": ("Person", "Người"),
        "tk_no_history": ("No events.", "Chưa có sự kiện."),
        "tk_tab_off": (
            "The task list is off (CONTROLS_ENABLED=1 turns it on).",
            "Danh sách nhiệm vụ đang tắt (đặt CONTROLS_ENABLED=1 để bật).",
        ),
        "tk_tab_none": (
            "No task list for this agent yet.",
            "Tác tử này chưa có danh sách nhiệm vụ.",
        ),
        "tk_stage_now": ("Stage", "Giai đoạn"),
        "tk_sizing": (
            "Sized for class {cls}, band {band} ({src}): level {level}.",
            "Cỡ theo phân loại {cls}, mức {band} ({src}): cấp {level}.",
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
            "One agent: its state, the one action that fits, its rules, tools, traces and cases.",
            "Một tác tử: trạng thái, một hành động phù hợp, quy tắc, công cụ, dấu vết và vụ việc.",
        ),
        "agent_why": (
            "Pause is one click for any reviewer. Resume needs two different people.",
            "Tạm dừng chỉ cần một cú nhấp của người rà soát. Tiếp tục cần hai người khác nhau.",
        ),
        "open_agent_page": ("Open the agent page", "Mở trang tác tử"),
        "gate_24h": ("Gate, last 24 hours", "Cổng, 24 giờ qua"),
        "gate_checked": ("Calls checked", "Lệnh gọi đã kiểm tra"),
        "gate_blocked": ("Blocked", "Bị chặn"),
        "gate_paused": ("Paused", "Bị tạm dừng"),
        "gate_median": ("Median latency", "Độ trễ trung vị"),
        "policy_rules": ("Rules in scope", "Quy tắc áp dụng"),
        "policy_shadow_note": (
            "Shadow: rules are checked and recorded, but nothing is stopped.",
            "Chế độ bóng: quy tắc được kiểm tra và ghi lại, nhưng không chặn gì.",
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
            "Read only. Rules change in the policy files, by pull request.",
            "Chỉ đọc. Quy tắc được đổi trong tệp chính sách, qua pull request.",
        ),
        "tl_in_analytics": (
            "Open this agent in Analytics",
            "Mở tác tử này trong trang Phân tích",
        ),
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
        "no_traces": ("No trace yet", "Chưa có dấu vết"),
        "no_traces_line": (
            "Traces appear here when this agent sends events.",
            "Dấu vết hiện ở đây khi tác tử này gửi sự kiện.",
        ),
        "as_no_agent_results": ("No assurance result", "Chưa có kết quả đảm bảo"),
        "as_no_agent_results_line": (
            "No run has this agent as its target.",
            "Chưa có lần chạy nào nhắm vào tác tử này.",
        ),
        "alerts_why": (
            "An alert is a rule over the evidence. Acknowledging it is a decision of one person, "
            "and it is recorded.",
            "Cảnh báo là một quy tắc chạy trên bằng chứng. Xác nhận là quyết định của một người "
            "và được ghi lại.",
        ),
        "alerts_active": ("Active", "Đang hoạt động"),
        "alerts_st_open": ("Open", "Đang mở"),
        "alerts_st_acknowledged": ("Acknowledged", "Đã xác nhận"),
        "alerts_st_closed": ("Closed", "Đã đóng"),
        "no_alerts_line": (
            "No alert matches these filters.",
            "Không có cảnh báo nào khớp bộ lọc này.",
        ),
        "alert_first": ("First seen", "Lần đầu"),
        "alert_last": ("Last seen", "Lần cuối"),
        "alert_entry_hash": ("Chain entry hash", "Mã băm mục chuỗi"),
        "alert_rule_hash": ("Rule hash", "Mã băm quy tắc"),
        "alert_routes": ("Delivery", "Kênh gửi"),
        "alert_acked_by": ("Acknowledged by", "Người xác nhận"),
        "so_purpose": (
            "High and critical cases that wait for a signature.",
            "Vụ việc mức cao và nghiêm trọng đang chờ chữ ký.",
        ),
        "so_signatures": ("Signatures (of 2)", "Chữ ký (trên 2)"),
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
            "One range and one agent apply to every tab. Numbers are counts, not scores.",
            "Một khoảng thời gian và một tác tử áp dụng cho mọi tab. Số liệu là số đếm, "
            "không phải điểm.",
        ),
        "an_tab_gate": ("Gate", "Cổng"),
        "an_tab_tools": ("Tools", "Công cụ"),
        "an_tab_metrics": ("Oversight metrics", "Chỉ số giám sát"),
        "an_tab_latency": ("Latency", "Độ trễ"),
        "an_range": ("Range", "Khoảng thời gian"),
        "an_range_default": ("default", "mặc định"),
        "an_days": ("{n} days", "{n} ngày"),
        "an_capped": (
            "scan limit reached: older events are not counted",
            "đã chạm giới hạn quét: sự kiện cũ hơn không được tính",
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
            "Window: every stored day, {a} .. {b}",
            "Khoảng: mọi ngày đã lưu, {a} .. {b}",
        ),
        "an_window_stored_none": (
            "Window: every stored day (none yet)",
            "Khoảng: mọi ngày đã lưu (chưa có)",
        ),
        "an_window_live": (
            "Window: live counters since this process started",
            "Khoảng: bộ đếm trực tiếp từ lúc tiến trình này khởi động",
        ),
        "so_sig_n": ("{n}/2 signatures", "{n}/2 chữ ký"),
        "alert_window_val": ("{n}/{max} in {s} s", "{n}/{max} trong {s} giây"),
        "an_latency_note": (
            "Live counters of this process since it started.",
            "Bộ đếm trực tiếp của tiến trình này từ lúc khởi động.",
        ),
        "open_case": ("Open the case", "Mở vụ việc"),
        "inbox_st_unread": ("Unread", "Chưa đọc"),
        "inbox_st_read": ("Read", "Đã đọc"),
        "inbox_st_queued": ("Queued", "Đang chờ gửi"),
        "cp_no_matrix": ("No compliance matrix", "Chưa có ma trận tuân thủ"),
        "cp_no_matrix_line": (
            "This agent has no matrix yet. Build one with the advisor command.",
            "Tác tử này chưa có ma trận. Hãy tạo bằng lệnh của cố vấn.",
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
            "Add issues the first key of the agent. The key is shown once; Supervisor cannot "
            "show it again.",
            "Thêm sẽ cấp khóa đầu tiên của tác tử. Khóa chỉ hiện một lần; Supervisor không thể "
            "hiện lại.",
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
        "col_consumers": ("Consumers", "Bên dùng"),
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
            "The key store is {store}. Supervisor could not save the key. Do this first:",
            "Kho khóa là {store}. Supervisor không thể lưu khóa. Hãy làm bước này trước:",
        ),
        "col_ingress_off": (
            "Ingress authentication is off (INGRESS_AUTH_ENABLED=0). The key is not checked yet. "
            "Turn it on before production.",
            "Xác thực đầu vào đang tắt (INGRESS_AUTH_ENABLED=0). Khóa chưa được kiểm tra. "
            "Hãy bật trước khi chạy thật.",
        ),
        "col_template": ("Way to attach", "Cách gắn"),
        "dtab_connection": ("Connection", "Kết nối"),
        "dtab_credential": ("Credential", "Thông tin xác thực"),
        "dtab_binding": ("Policy binding", "Gắn chính sách"),
        "col_cred_note": (
            "Only the key id, state and dates are shown. The secret is never shown again.",
            "Chỉ hiện mã khóa, trạng thái và ngày. Bí mật không bao giờ hiện lại.",
        ),
        "col_rotate": ("Rotate the key on the command line", "Đổi khóa bằng dòng lệnh"),
        "col_no_keys_agent": (
            "This agent has no active key. Use Add on the catalogue.",
            "Tác tử này chưa có khóa đang dùng. Dùng Thêm trong danh mục.",
        ),
        "col_bind_mode": ("Policy mode", "Chế độ chính sách"),
        "col_bind_preset": ("Detector preset", "Mức nhạy của bộ dò"),
        "col_bind_disabled": ("Rules switched off", "Quy tắc đã tắt"),
        "col_bind_rules": ("Rules in scope", "Quy tắc áp dụng"),
        "col_bind_consumers": ("Consumer overrides", "Cấu hình riêng theo bên dùng"),
        "col_bind_none": (
            "No consumer override. Every caller gets the agent settings.",
            "Không có cấu hình riêng. Mọi bên gọi dùng cấu hình của tác tử.",
        ),
        "col_bind_note": (
            "The policy lives in git. To change mode or consumers, edit the policy file and "
            "review it like any other change.",
            "Chính sách nằm trong git. Muốn đổi chế độ hoặc bên dùng, hãy sửa tệp chính sách "
            "và duyệt như mọi thay đổi khác.",
        ),
        "col_bind_enable": ("switch on", "bật"),
        "col_bind_disable": ("switch off", "tắt"),
        "col_bind_unavailable": (
            "The policy could not be read.",
            "Không đọc được chính sách.",
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
            "These fill the context of the check.",
            "Các thuộc tính này được điền vào ngữ cảnh của lần kiểm tra.",
        ),
        "pg_consumer": ("Consumer id", "Mã bên dùng"),
        "pg_direction": ("Direction", "Hướng"),
        "pg_dir_input": ("input (what the agent sends)", "input (agent gửi đi)"),
        "pg_dir_output": ("output (what a tool returned)", "output (công cụ trả về)"),
        "pg_tool_class": ("Declared tool class", "Loại công cụ khai báo"),
        "pg_result_mode": ("Policy mode", "Chế độ chính sách"),
        "pg_observed": ("Observed decision", "Quyết định đã quan sát"),
        "pg_observed_line": (
            "In observe mode this decision would have stopped the call. The call is allowed.",
            "Ở chế độ quan sát, quyết định này lẽ ra đã chặn lệnh gọi. Lệnh gọi vẫn được phép.",
        ),
        "pg_consumer_ignored": (
            "The consumer id has no entry for this agent: the agent settings were used.",
            "Mã bên dùng không có cấu hình riêng cho tác tử này: đã dùng cấu hình của tác tử.",
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
            "Advisory only. This is a working aid, not legal advice; bank counsel must confirm.",
            "Chỉ mang tính tham khảo. Đây là công cụ hỗ trợ, không phải tư vấn pháp lý; "
            "bộ phận pháp chế của ngân hàng phải xác nhận.",
        ),
        "tp_d33_rows": ("Decision 33 obligations", "Nghĩa vụ theo Quyết định 33"),
        "tp_d33_missing": (
            "These Decision 33 obligation ids are cited by the classification but are missing "
            "from the matrix: {ids}",
            "Các mã nghĩa vụ của Quyết định 33 được phần phân loại nêu nhưng không có trong ma "
            "trận: {ids}",
        ),
        "tp_gaps": (
            "Open items in the matrix (partial, gap or needs an answer)",
            "Mục còn mở trong ma trận (một phần, thiếu hoặc cần trả lời)",
        ),
        "tp_agent_card": ("Agent card", "Thẻ tác tử"),
        "tp_judge_card": (
            "Judge model card (Supervisor's own judge, not this agent's model)",
            "Thẻ mô hình của bộ đánh giá (bộ đánh giá của Supervisor, không phải mô hình của "
            "tác tử)",
        ),
        "tp_controls_empty": (
            "No controls data in this build.",
            "Bản này chưa có dữ liệu kiểm soát.",
        ),
        "tp_backlog_none": (
            "No open backlog item names this agent.",
            "Không có hạng mục tồn đọng nào nêu tên tác tử này.",
        ),
        "tp_ns_none": ("Nothing to add.", "Không có gì bổ sung."),
        "tp_verify_failed": (
            "The offline check of the evidence chain FAILED. Treat the records of this agent as "
            "not proven until the cause is found.",
            "Kiểm tra ngoại tuyến chuỗi bằng chứng KHÔNG ĐẠT. Chưa coi các bản ghi của tác tử "
            "này là đã được chứng minh cho đến khi tìm ra nguyên nhân.",
        ),
        # section titles
        "tp_s_identity": ("Identity and ownership", "Danh tính và trách nhiệm"),
        "tp_s_classification": ("Classification (Decision 33)", "Phân loại (Quyết định 33)"),
        "tp_s_inventory": ("Components (inventory)", "Thành phần (kiểm kê)"),
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
        "tp_f_host": ("Host / plug point", "Nơi chạy / điểm gắn"),
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
        "tp_f_obligations": ("Obligation ids", "Mã nghĩa vụ"),
        "tp_f_own_risk": ("Own risk level", "Mức rủi ro riêng"),
        "tp_f_eff_risk": ("Effective risk level", "Mức rủi ro hiệu lực"),
        "tp_f_nodes": ("Nodes in the graph", "Số nút trong đồ thị"),
        "tp_f_group": ("Link", "Liên kết"),
        "tp_f_component": ("Component", "Thành phần"),
        "tp_f_source": ("Source", "Nguồn"),
        "tp_f_evidence_ref": ("Evidence (file:line)", "Bằng chứng (tệp:dòng)"),
        "tp_f_matrix_source": ("Matrix source", "Nguồn của ma trận"),
        "tp_f_as_of": ("As of", "Tính đến ngày"),
        "tp_f_regkb": ("Regulation base version", "Phiên bản cơ sở quy định"),
        "tp_f_obl_total": ("Obligations in the matrix", "Số nghĩa vụ trong ma trận"),
        "tp_f_by_status": ("By status", "Theo trạng thái"),
        "tp_f_by_applies": ("By applicability", "Theo mức áp dụng"),
        "tp_f_questions": ("Open questions", "Câu hỏi còn mở"),
        "tp_f_thr_gaps": ("Threshold gaps", "Khoảng trống ngưỡng"),
        "tp_f_thr_exceeds": ("Limits above a cap", "Hạn mức vượt trần"),
        "tp_f_obligation": ("Obligation", "Nghĩa vụ"),
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
        "tp_f_packs": ("Packs run", "Số gói đã chạy"),
        "tp_f_mock_n": ("Mock results", "Kết quả giả lập"),
        "tp_f_pack": ("Pack", "Gói"),
        "tp_f_day": ("Day", "Ngày"),
        "tp_f_items": ("Items", "Số mục"),
        "tp_f_validations": ("Validation runs", "Số lần thẩm định"),
        "tp_f_latest_decision": ("Latest decision", "Quyết định gần nhất"),
        "tp_f_required": ("Validation required to judge", "Bắt buộc thẩm định mới được đánh giá"),
        "tp_f_decision": ("Decision", "Quyết định"),
        "tp_f_masking_on": ("Masking on", "Đang che dữ liệu"),
        "tp_f_masker": ("Masker", "Bộ che dữ liệu"),
        "tp_f_capture": ("Capture level", "Mức ghi nhận"),
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
            "Only rule links, packs not scored by a judge model and these monitors count as "
            "evidence: "
            "{m}. Judge-scored packs (unless the owner allows them), other monitor links, matrix "
            "links and case links are references and never lower a score.",
            "Chỉ liên kết quy tắc, gói không do mô hình đánh giá chấm và các bộ giám sát sau "
            "được tính là bằng chứng: {m}. Gói do mô hình đánh giá chấm (trừ khi chủ sở hữu cho "
            "phép), liên kết bộ giám sát khác, ma trận và vụ việc chỉ là tham chiếu và không bao "
            "giờ làm giảm điểm.",
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
            "Controls the bank owns cannot be observed by the product, so they never read "
            "working. Read the figure above with that in mind: it is not a statement that the "
            "bank is non-compliant.",
            "Kiểm soát do ngân hàng sở hữu không thể được sản phẩm quan sát nên không bao giờ "
            "hiển thị là hoạt động. Hãy đọc tỷ lệ trên với lưu ý đó: đây không phải khẳng định "
            "ngân hàng không tuân thủ.",
        ),
        "tp_f_risk": ("Risk", "Rủi ro"),
        "tp_f_category": ("Category", "Nhóm"),
        "tp_f_evidence": ("Evidence", "Bằng chứng"),
        "tp_f_via": ("Reached via", "Đến qua"),
        "tp_f_owner": ("Owner", "Người phụ trách"),
        "tp_f_lane": ("Chain lane", "Làn chuỗi"),
        "tp_f_entries": ("Entries", "Số bản ghi"),
        "tp_f_head": ("Head hash", "Mã băm đầu chuỗi"),
        "tp_f_root_key": ("Signing key (kind / id)", "Khóa ký (loại / mã)"),
        "tp_f_anchored": ("Anchored outside the database", "Đã neo ra ngoài cơ sở dữ liệu"),
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
            "Masking of personal data is not switched on for the monitoring records.",
            "Việc che dữ liệu cá nhân chưa được bật cho hồ sơ giám sát.",
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
            "We keep a register of risks for this assistant: {n} tracked, highest remaining "
            "level: {level}.",
            "Chúng tôi lập sổ rủi ro cho trợ lý này: {n} rủi ro được theo dõi, mức còn lại cao "
            "nhất: {level}.",
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
        "tp_meta_schema": ("Data model version", "Phiên bản mô hình dữ liệu"),
        "tp_meta_content": ("Content hash", "Mã băm nội dung"),
        "tp_status_signed": ("signed into the evidence chain", "đã ký vào chuỗi bằng chứng"),
        "tp_status_preview": (
            "PREVIEW: not yet signed into the evidence chain",
            "XEM TRƯỚC: chưa ký vào chuỗi bằng chứng",
        ),
        "tp_footer": (
            "The sha256 of the JSON file and of each rendered file is recorded in the evidence "
            "chain (record_type transparency_report). Not legal advice.",
            "Mã băm SHA-256 của tệp JSON và của từng tệp hiển thị được ghi vào chuỗi bằng chứng "
            "(record_type transparency_report). Không phải tư vấn pháp lý.",
        ),
        "tp_footer_c": ("Not legal advice.", "Không phải tư vấn pháp lý."),
        # console page and Agent tab
        "tp_purpose": (
            "One report per agent, built from facts the system already holds, in three versions.",
            "Mỗi tác tử một báo cáo, tạo từ các dữ kiện hệ thống đã có, gồm ba phiên bản.",
        ),
        "tp_why": (
            "A regulator, a customer and the bank each see only the fields their version allows.",
            "Cơ quan quản lý, khách hàng và ngân hàng chỉ thấy các trường mà phiên bản của họ "
            "cho phép.",
        ),
        "tp_col_agent": ("Agent", "Tác tử"),
        "tp_col_variant": ("Version", "Phiên bản"),
        "tp_col_last": ("Last report", "Báo cáo gần nhất"),
        "tp_col_ver": ("No.", "Số"),
        "tp_col_files": ("Files", "Tệp"),
        "tp_col_state": ("State", "Tình trạng"),
        "tp_generate": ("Generate", "Tạo báo cáo"),
        "tp_generate_all": ("Generate all versions", "Tạo mọi phiên bản"),
        "tp_never": ("never", "chưa có"),
        "tp_preview_line": ("Preview of the current facts", "Xem trước theo dữ kiện hiện tại"),
        "tp_unchanged": (
            "Nothing changed since version {v}: no new version was made.",
            "Không có gì thay đổi từ phiên bản {v}: không tạo phiên bản mới.",
        ),
        "tp_generated": (
            "Report version {v} made and signed into the chain.",
            "Đã tạo báo cáo phiên bản {v} và ký vào chuỗi.",
        ),
        "tp_download": ("Download", "Tải về"),
        "tp_open_page": ("Open the Transparency page", "Mở trang Minh bạch"),
        "tp_tab_off": (
            "Transparency reports are off for this installation.",
            "Báo cáo minh bạch đang tắt trong bản cài đặt này.",
        ),
        "tp_no_pdf": (
            "PDF files need the optional fpdf2 package and a local Unicode font; without them "
            "only JSON and HTML are made.",
            "Tệp PDF cần gói tùy chọn fpdf2 và phông Unicode trên máy; nếu thiếu thì chỉ tạo "
            "JSON và HTML.",
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
            "Open a row for the masked request, the response, each finding and the latency split.",
            "Mở một dòng để xem yêu cầu đã che, phản hồi, từng phát hiện và cách chia độ trễ.",
        ),
        "detection_code": ("Detection code", "Mã phát hiện"),
        "not_evaluated": ("Not evaluated", "Chưa được đánh giá"),
        "ne_only": ("Not evaluated only", "Chỉ chưa được đánh giá"),
        "consumer": ("Consumer", "Ứng dụng gọi"),
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
        "ne_payload_too_large": ("payload too large", "dữ liệu quá lớn"),
        "ne_content_uninspectable": ("content could not be read", "không đọc được nội dung"),
        "ne_timed_out": ("a detector timed out", "một bộ phát hiện quá thời gian"),
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
        "part_args": ("Arguments", "Tham số"),
        "part_tool_results": ("Tool results", "Kết quả công cụ"),
        "part_output": ("Output", "Đầu ra"),
        "request_note": (
            "Masked text from the recorder. The gate stores only a keyed hash of the arguments.",
            "Văn bản đã che từ bộ ghi. Cổng chỉ lưu mã băm có khóa của tham số.",
        ),
        "no_request_text": ("No request text", "Không có văn bản yêu cầu"),
        "no_request_text_line": (
            "No masked text is stored for this call, or no masker is set.",
            "Không có văn bản đã che cho lệnh gọi này, hoặc chưa cấu hình bộ che.",
        ),
        "masked_record": ("Masked record (JSON)", "Bản ghi đã che (JSON)"),
        "decision": ("Decision", "Quyết định"),
        "allowed": ("allowed", "được phép"),
        "denied": ("denied", "bị từ chối"),
        "transformed_payload": ("Payload after masking", "Dữ liệu sau khi che"),
        "transformed_note": (
            "Rebuilt from the masked record; the gate does not store the transformed payload.",
            "Dựng lại từ bản ghi đã che; cổng không lưu dữ liệu đã biến đổi.",
        ),
        "no_transform": ("The payload was not changed.", "Dữ liệu không bị thay đổi."),
        "detector": ("Detector", "Bộ phát hiện"),
        "code": ("Code", "Mã"),
        "entities": ("Entities and fragments (masked)", "Thực thể và đoạn (đã che)"),
        "action_hint": ("Action hint", "Gợi ý hành động"),
        "leaf_precision": ("whole text", "toàn văn bản"),
        "no_detections": ("No findings", "Không có phát hiện"),
        "no_detections_line": (
            "No detector fired on this decision.",
            "Không bộ phát hiện nào kích hoạt cho quyết định này.",
        ),
        "located_fragments": ("Fragments in the masked text", "Đoạn trong văn bản đã che"),
        "unlocated_fragments": ("Fragments not located", "Đoạn không định vị được"),
        "lat_total": ("Latency total", "Tổng độ trễ"),
        "lat_rules": ("Rules", "Quy tắc"),
        "lat_detectors": ("Detectors", "Bộ phát hiện"),
        "lat_overhead": ("Overhead", "Thời gian còn lại"),
        "open_trace_span": ("Open the trace span", "Mở đoạn dấu vết"),
        "same_correlation": ("{n} decisions share this id", "{n} quyết định cùng mã này"),
        "open_alert": ("Open alert", "Mở cảnh báo"),
        "an_tab_detectors": ("Detectors", "Bộ phát hiện"),
        "dd_requests": ("Requests", "Yêu cầu"),
        "dd_none": ("No rows in this window.", "Không có dòng nào trong khoảng này."),
        "dd_empty": ("No rollup rows yet", "Chưa có dữ liệu tổng hợp"),
        "dd_empty_line": (
            "Run python -m supervisor.jobs.decision_rollup (the scheduler does it every hour).",
            "Chạy python -m supervisor.jobs.decision_rollup (bộ lập lịch chạy mỗi giờ).",
        ),
        "dd_series": ("Gate outcomes by day", "Kết quả của cổng theo ngày"),
        "dd_per_agent": ("Per agent", "Theo tác tử"),
        "dd_per_consumer": ("Per application", "Theo ứng dụng"),
        "dd_per_rule": ("Per rule", "Theo quy tắc"),
        "dd_per_detector": ("Per detector and code", "Theo bộ phát hiện và mã"),
        "det_latency": ("Detector latency", "Độ trễ bộ phát hiện"),
        "det_runs": ("Runs", "Lượt chạy"),
        "det_verdict": ("Harness verdict", "Kết luận kiểm thử"),
        "det_adversarial": ("adversarial recall", "độ phủ đối kháng"),
        "det_approx": (
            "Over several days p50 is the weighted mean of daily p50; p95 is the highest "
            "daily p95. GO (indicative): the point value passes, the 95 percent interval "
            "does not prove it.",
            "Nhiều ngày: p50 là trung bình có trọng số của p50 từng ngày; p95 là p95 cao "
            "nhất của một ngày. GO (indicative): giá trị điểm đạt, khoảng tin cậy 95 phần "
            "trăm chưa chứng minh.",
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
            "The harness verdict is read from a report file; none is recorded. Run "
            "python -m supervisor.detectors.harness --json DATA_DIR/eval/detectors_report.json",
            "Kết luận kiểm thử được đọc từ tệp báo cáo; chưa có tệp. Chạy "
            "python -m supervisor.detectors.harness --json DATA_DIR/eval/detectors_report.json",
        ),
        "dd_series_note": (
            "Counts decisions by verdict status (block before pause). The Blocked and Paused tiles "
            "above count the stopping rule (pause before block), so a call that matched both is "
            "Paused there and Block here.",
            "Đếm quyết định theo trạng thái phán quyết (chặn trước tạm dừng). Ô Đã chặn và Tạm "
            "dừng ở trên đếm theo quy tắc dừng (tạm dừng trước chặn), nên một lệnh khớp cả hai "
            "là Tạm dừng ở trên và Chặn ở đây.",
        ),
        "findings_chip": ("{n} findings", "{n} phát hiện"),
        "open_decision": ("Open the gate decision", "Mở quyết định của cổng"),
        "export_csv": ("Export CSV", "Xuất CSV"),
        "export_hint": (
            "Masked columns only, at most {n} rows.",
            "Chỉ các cột đã che, tối đa {n} dòng.",
        ),
        "export_done": (
            "CSV built: {n} rows, {cols} columns.",
            "Đã tạo CSV: {n} dòng, {cols} cột.",
        ),
        "export_once": (
            "The link works once, for you only, for 15 minutes.",
            "Liên kết chỉ dùng được một lần, chỉ cho bạn, trong 15 phút.",
        ),
    }
)


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
