# ruff: noqa: E501
"""UX5 text for the overview family (group G1): My overview, governance and supervisor overview,
gate decisions, workflows, inbox, search, health, My agents.

``NEW`` holds keys that only the UX5 templates use; ``i18n.py`` merges it (one line) so the
template key test sees them. ``UX5`` overrides existing keys (en, vi), listed in ``i18n_ux5.MODULES``."""

from __future__ import annotations

NEW: dict[str, tuple[str, str]] = {
    "u5g1_my_purpose": (
        "The state of the {n} AI systems in your scope.",
        "Tình trạng của {n} hệ thống AI trong phạm vi của bạn.",
    ),
    "u5g1_items_wait": ("{n} items wait for you", "{n} việc đang chờ bạn"),
    "u5g1_cases_open": ("{n} open cases", "{n} vụ việc đang mở"),
    "u5g1_clock_left": ("Report due in {d}", "Báo cáo còn {d} đến hạn"),
    "u5g1_clock_over": ("Report overdue by {d}", "Báo cáo quá hạn {d}"),
    "u5g1_attention": ("Needs attention", "Cần chú ý"),
    "u5g1_all_good": ("Nothing needs attention.", "Không có việc cần chú ý."),
    "u5g1_more_open": ("{n} more items are open.", "Còn {n} việc đang mở."),
    "u5g1_open_task": ("Open task", "Mở nhiệm vụ"),
    "u5g1_open_cases": ("Open cases", "Mở vụ việc"),
    "u5g1_open_candidates": ("Open candidates", "Mở ứng viên"),
    "u5g1_open_item": ("Open item", "Mở việc"),
    "u5g1_all_n": ("All {n}", "Tất cả {n}"),
    "u5g1_key_figures": ("Key figures", "Số liệu chính"),
    "u5g1_agents_running": ("Agents, {n} running", "Tác tử, {n} đang chạy"),
    "u5g1_systems_n": ("{n} systems", "{n} hệ thống"),
    "u5g1_risk_class": ("Risk class", "Phân loại rủi ro"),
    "u5g1_wait_approval": ("{n} wait for approval", "{n} chờ phê duyệt"),
    "u5g1_due_review": ("{n} due for review", "{n} đến hạn rà soát"),
    "u5g1_past_title": (
        "Risk assessments past their review date",
        "Đánh giá rủi ro quá hạn rà soát",
    ),
    "u5g1_past_none": (
        "No risk assessment is past its review date.",
        "Không có đánh giá rủi ro nào quá hạn rà soát.",
    ),
    # governance overview
    "u5g1_gov_purpose": ("Showing {n} of {total} systems.", "Hiển thị {n} / {total} hệ thống."),
    "u5g1_classified_tip": (
        "Classification rate: systems with a Decision 33 class set by a person, over systems in scope.",
        "Tỷ lệ phân loại: hệ thống có phân loại Quyết định 33 do người đặt, trên số hệ thống trong phạm vi.",
    ),
    "u5g1_not_measured": ("Not measured", "Chưa đo"),
    "u5g1_not_measured_line": (
        "Controls have not been assessed yet.",
        "Các biện pháp kiểm soát chưa được đánh giá.",
    ),
    "u5g1_ready_title": ("Control readiness by system", "Mức sẵn sàng kiểm soát theo hệ thống"),
    "u5g1_ready_none": (
        "No system has controls with evidence yet.",
        "Chưa có hệ thống nào có biện pháp kiểm soát kèm bằng chứng.",
    ),
    "u5g1_ready_fold": (
        "systems without controls (not shown)",
        "hệ thống chưa có biện pháp kiểm soát (không hiển thị)",
    ),
    "u5g1_policy_none": ("No compliance data yet.", "Chưa có dữ liệu tuân thủ."),
    "u5g1_policy_fold": (
        "systems without policy data (not shown)",
        "hệ thống chưa có dữ liệu chính sách (không hiển thị)",
    ),
    "u5g1_advisory": (
        "Advisory, not legal advice",
        "Chỉ mang tính tham khảo, không phải tư vấn pháp lý",
    ),
    "u5g1_advisory_tip": (
        "From the advisory compliance matrix. Not legal advice; bank counsel confirms.",
        "Từ ma trận tuân thủ mang tính tham khảo. Không phải tư vấn pháp lý; pháp chế ngân hàng xác nhận.",
    ),
    # supervisor overview
    "u5g1_sup_purpose": (
        "Runtime health of the {n} agents in scope.",
        "Tình trạng vận hành của {n} tác tử trong phạm vi.",
    ),
    "u5g1_sup_problem": (
        "Agents with stops or gaps",
        "Tác tử có chặn hoặc thiếu sót",
    ),
    "u5g1_sup_fold": (
        "agents with no blocks and full coverage (not listed)",
        "tác tử không bị chặn và đủ độ phủ (không liệt kê)",
    ),
    "u5g1_sup_all": ("All {n} agents", "Tất cả {n} tác tử"),
    "u5g1_chain_banner": (
        "Evidence chain not verified yet for {n} agents.",
        "Chuỗi bằng chứng chưa được xác minh cho {n} tác tử.",
    ),
    "u5g1_verify": ("Verify", "Xác minh"),
    "u5g1_no_problem": (
        "No agent has stops or coverage gaps.",
        "Không có tác tử nào bị chặn hoặc thiếu độ phủ.",
    ),
    # search
    "u5g1_search_count": (
        '{n} results for "{q}"',
        '{n} kết quả cho "{q}"',
    ),
    "u5g1_search_none": (
        'No results for "{q}". Try another word or a system id.',
        'Không có kết quả cho "{q}". Thử từ khác hoặc mã hệ thống.',
    ),
    "u5g1_search_hint": (
        "Type a name, id or case number in the search box.",
        "Nhập tên, mã hoặc số vụ việc vào ô tìm kiếm.",
    ),
    # health
    "u5g1_health_status": ("Status", "Trạng thái"),
    "u5g1_health_dev": ("Developer checks", "Kiểm tra cho nhà phát triển"),
    "u5g1_health_pre": (
        "Preflight: {fail} fail, {skip} skipped, {ok} ok",
        "Preflight: {fail} lỗi, {skip} bỏ qua, {ok} đạt",
    ),
    "u5g1_show_checks": ("Show checks", "Xem các kiểm tra"),
    "u5g1_mock_judges": ("Mock judges in use.", "Đang dùng judge mô phỏng."),
    # workflows
    "u5g1_wf_alerts": ("Alert rules ({n})", "Quy tắc cảnh báo ({n})"),
    "u5g1_every_min": ("Every minute", "Mỗi phút"),
    "u5g1_every_min_n": ("Every {n} minutes", "Mỗi {n} phút"),
    "u5g1_every_hour": ("Every hour", "Mỗi giờ"),
    "u5g1_every_hour_n": ("Every {n} hours", "Mỗi {n} giờ"),
    "u5g1_daily": ("Daily", "Hằng ngày"),
    "u5g1_on_event": ("On event", "Khi có sự kiện"),
    "u5g1_never_run": ("Never run", "Chưa chạy"),
    "u5g1_job_alerts": ("Alert check", "Kiểm tra cảnh báo"),
    "u5g1_job_anchor": ("Evidence anchoring", "Neo bằng chứng"),
    "u5g1_job_case_intake": ("Case intake", "Tiếp nhận vụ việc"),
    "u5g1_job_control_status": ("Control status", "Trạng thái kiểm soát"),
    "u5g1_job_decision_rollup": ("Decision roll-up", "Tổng hợp quyết định"),
    "u5g1_job_drift": ("Drift check", "Kiểm tra lệch"),
    "u5g1_job_fairness": ("Fairness check", "Kiểm tra công bằng"),
    "u5g1_job_governance_actions": ("Governance actions", "Hành động quản trị"),
    "u5g1_job_guardian_shadow": ("Guardian shadow run", "Chạy bóng guardian"),
    "u5g1_job_ingest": ("Trace ingest", "Nạp dấu vết"),
    "u5g1_job_judge_sweep": ("Judge sweep", "Quét bằng judge"),
    "u5g1_job_metrics": ("Metrics", "Chỉ số"),
    "u5g1_job_multiagent": ("Multi-agent check", "Kiểm tra đa tác tử"),
    "u5g1_job_notify": ("Notices", "Thông báo"),
    "u5g1_job_quality": ("Quality check", "Kiểm tra chất lượng"),
    "u5g1_job_retention": ("Retention", "Lưu giữ dữ liệu"),
    "u5g1_job_risk_evidence": ("Risk evidence", "Bằng chứng rủi ro"),
    "u5g1_job_session_monitor": ("Session monitor", "Giám sát phiên"),
    "u5g1_job_siem": ("SIEM export", "Xuất sang SIEM"),
    "u5g1_job_task_due": ("Task due dates", "Hạn nhiệm vụ"),
    "u5g1_job_tool_analytics": ("Tool analytics", "Phân tích công cụ"),
    "u5g1_job_scheduler": ("Scheduler", "Bộ lập lịch"),
    "u5g1_wf_jobs": ("Scheduled jobs", "Tác vụ định kỳ"),
    "u5g1_wf_approvals": ("Approvals and sinks", "Phê duyệt và đầu ra"),
    # decisions
    "u5g1_more_filters": ("More filters", "Thêm bộ lọc"),
    # inbox
    "u5g1_inbox_sent": ("Sent to {who}", "Gửi tới {who}"),
    "u5g1_inbox_details": ("Details", "Chi tiết"),
    "u5g1_inbox_about": (
        "Delivery to the bank's ITSM and pager is set in Settings > Integrations.",
        "Việc chuyển thông báo tới ITSM và pager của ngân hàng được đặt trong Cài đặt > Tích hợp.",
    ),
    "u5g1_inbox_line": ("{agent}: {kind}", "{agent}: {kind}"),
    # my agents
    "u5g1_agents_total_tip": (
        "Registered agents, agents the gate knows from policy only, and workspace candidates.",
        "Tác tử đã đăng ký, tác tử chỉ có trong chính sách và ứng viên trong workspace.",
    ),
}

UX5: dict[str, tuple[str, str]] = {
    "nv3_cover_master_off": (
        "Detectors are off, so no agent is covered.",
        "Bộ phát hiện đang tắt, nên chưa tác tử nào được phủ.",
    ),
    "nv3_na_inventory_off": ("Inventory is off.", "Kiểm kê đang tắt."),
    "nv3_na_controls_off": ("Controls are off.", "Kiểm soát đang tắt."),
    "nv3_na_risks_off": ("The risk register is off.", "Sổ rủi ro đang tắt."),
    "nv3_na_compliance_off": ("The compliance tab is off.", "Tab tuân thủ đang tắt."),
    "nv3_na_no_status": (
        "Controls have not been assessed yet.",
        "Các biện pháp kiểm soát chưa được đánh giá.",
    ),
    "decisions_purpose_v2": ("All gate decisions.", "Mọi quyết định của cổng."),
    "decisions_why_v2": (
        "Open a row to see the request, response and findings.",
        "Mở một dòng để xem yêu cầu, phản hồi và phát hiện.",
    ),
    "mya_purpose": (
        "Agents in your scope, with their gate state.",
        "Tác tử trong phạm vi của bạn, kèm trạng thái ở cổng.",
    ),
    "mya_tile_total": ("All, with candidates", "Tất cả, gồm ứng viên"),
    "mya_kind_policy_only": ("Known to gate only", "Chỉ cổng biết"),
    "mya_on_of": ("{n} of {m} on", "bật {n} / {m}"),
    "mya_ra_guardian": ("Turn on {slug}", "Bật {slug}"),
    "mya_ra_running": (
        "Move to Running (in shadow {days} days)",
        "Chuyển sang Running (đã ở shadow {days} ngày)",
    ),
    "health_lead": (
        "Health of this Supervisor installation.",
        "Tình trạng của bản cài đặt Supervisor này.",
    ),
    "health_why": ("Fix every FAIL before go-live.", "Sửa mọi lỗi FAIL trước khi vận hành thật."),
    "h_judge_mock": ("Mock judges in use.", "Đang dùng giám khảo giả lập."),
    "h_onboard_detail": (
        "Start form for onboarding runs.",
        "Biểu mẫu Bắt đầu cho các lần tiếp nhận.",
    ),
    "h_databricks_in_use": (
        "Live workspace checks run outside this page.",
        "Kiểm tra workspace trực tiếp chạy ngoài trang này.",
    ),
    "health_note": ("Secret values are never shown.", "Không bao giờ hiển thị giá trị bí mật."),
    "nv3_wf_lede": (
        "Automatic jobs and rules. Read only.",
        "Công việc và quy tắc tự động. Chỉ đọc.",
    ),
    "nv3_never": ("Never run", "Chưa chạy"),
    "inbox_purpose": (
        "Notices about cases: new, sign-off needed, closed.",
        "Thông báo về vụ việc: mới, cần phê duyệt, đã đóng.",
    ),
    "ov4_dim_intake": ("Intake complete", "Thông tin đầu vào đầy đủ"),
    "ov4_dim_class": ("Decision 33 class set", "Đã đặt phân loại Quyết định 33"),
    "ov4_dim_duties": ("Duties closed, average", "Nghĩa vụ đã đóng, trung bình"),
    "du_ov_line": ("{avg}%", "{avg}%"),
    "ov4_assess": ("Assessment progress", "Tiến độ đánh giá"),
    "ov4_risk_by_autonomy": ("Autonomy level", "Mức tự chủ"),
    "ov4_pipeline": ("Progress by step", "Tiến độ theo bước"),
    "ov4_pipeline_note": (
        "Counts overlap: one system can be in several steps.",
        "Các số liệu chồng nhau: một hệ thống có thể ở nhiều bước.",
    ),
    "ov4_t_cover": ("Agents with a guardian", "Tác tử có guardian"),
    "ov4_why_overdue_high": (
        "Overdue high-risk task: {arg}.",
        "Nhiệm vụ rủi ro cao quá hạn: {arg}.",
    ),
}
