# ruff: noqa: E501
"""Labels of the Stability tab (W8, STABILITY_TAB), English and Vietnamese, prefix ``st_``.

Merged into ``i18n._T`` by one line in ``i18n.py``. Wording follows the copy style: plain business
words, no setting names, no metric codes. Synthetic UI text only."""

from __future__ import annotations

ST: dict[str, tuple[str, str]] = {
    # --- tab and page
    "st_tab": ("Stability", "Độ ổn định"),
    "st_title": ("Stability after go-live", "Độ ổn định sau khi vận hành"),
    "st_intro": (
        "How steady this AI use case is since it went live. This page only shows; it never changes anything.",
        "Mức ổn định của trường hợp sử dụng AI kể từ khi vận hành. Trang này chỉ hiển thị, không thay đổi gì.",
    ),
    "st_agent": ("Agent", "Tác tử"),
    "st_open_agent": ("Open agent page", "Mở trang tác tử"),
    "st_from_agent": ("Open the Stability view", "Mở trang Độ ổn định"),
    "st_from_agent_hint": (
        "See how steady this agent is over time.",
        "Xem tác tử này ổn định đến đâu theo thời gian.",
    ),
    # --- verdict
    "st_v_stable": ("Stable", "Ổn định"),
    "st_v_watch": ("Watch", "Cần theo dõi"),
    "st_v_unstable": ("Unstable", "Không ổn định"),
    "st_v_nodata": ("Not enough data yet", "Chưa đủ dữ liệu"),
    "st_rule": (
        "Unstable: a drift case is open, or a measure stays outside its normal range for {m} windows in a row. Watch: a measure is outside its range in the latest window, or the conversation monitor raised an alert. Stable: every measure is inside its range. One window is {win}.",
        "Không ổn định: có vụ việc lệch chuẩn đang mở, hoặc một chỉ số nằm ngoài khoảng bình thường {m} khung liên tiếp. Cần theo dõi: một chỉ số ngoài khoảng ở khung gần nhất, hoặc bộ giám sát hội thoại đã cảnh báo. Ổn định: mọi chỉ số đều trong khoảng. Mỗi khung dài {win}.",
    ),
    "st_why_ok": (
        "Every measure is inside its normal range ({n} checked).",
        "Mọi chỉ số đều trong khoảng bình thường (đã kiểm tra {n}).",
    ),
    "st_why_range": (
        "Outside the normal range in the latest window: {names}.",
        "Ngoài khoảng bình thường ở khung gần nhất: {names}.",
    ),
    "st_why_session": (
        "The conversation monitor raised an alert in the last {m} windows.",
        "Bộ giám sát hội thoại đã cảnh báo trong {m} khung gần nhất.",
    ),
    "st_why_streak": (
        "Outside the normal range for {m} windows in a row: {names}.",
        "Ngoài khoảng bình thường {m} khung liên tiếp: {names}.",
    ),
    "st_why_case": (
        "A drift case is open for this agent. Review it in the list below.",
        "Đang có vụ việc lệch chuẩn của tác tử này. Hãy xem trong danh sách bên dưới.",
    ),
    "st_why_nobase": (
        "The normal range is not set yet. It is built from the first {count} {unit} of calls.",
        "Chưa có khoảng bình thường. Khoảng này được xây từ {count} {unit} đầu tiên của các lượt gọi.",
    ),
    "st_why_collecting": (
        "Building the normal range: {have_count} {have_unit} of {count} {unit} collected.",
        "Đang xây khoảng bình thường: đã thu {have_count} {have_unit} trên {count} {unit}.",
    ),
    "st_why_quiet": (
        "Too few calls in the latest windows to judge. A window needs at least {min_n} calls.",
        "Quá ít lượt gọi trong các khung gần nhất để đánh giá. Mỗi khung cần ít nhất {min_n} lượt.",
    ),
    "st_why_waiting": (
        "The agent is live and has sent no calls yet. The normal range starts after the first {count} {unit} of calls.",
        "Tác tử đã vận hành nhưng chưa có lượt gọi nào. Khoảng bình thường bắt đầu sau {count} {unit} đầu tiên của các lượt gọi.",
    ),
    "st_why_notlive": (
        "This agent is not live yet. This page fills in once it is deployed and receives calls. The normal range starts after the first {count} {unit}.",
        "Tác tử này chưa vận hành. Trang này sẽ có số liệu khi tác tử được triển khai và nhận lượt gọi. Khoảng bình thường bắt đầu sau {count} {unit} đầu tiên.",
    ),
    "st_why_noagent": (
        "No agent is linked to this AI system yet. Link the agent in the registration flow, then come back.",
        "Hệ thống AI này chưa gắn tác tử nào. Hãy gắn tác tử trong quy trình đăng ký rồi quay lại.",
    ),
    "st_empty_title": ("Nothing to show yet", "Chưa có gì để hiển thị"),
    "st_empty_will": (
        "Once calls arrive you will see calls, stopped calls, payment amounts, tool mix, response time, judge scores and conversation alerts here, each with its normal range.",
        "Khi có lượt gọi, bạn sẽ thấy ở đây số lượt gọi, lượt bị chặn, số tiền thanh toán, cơ cấu công cụ, thời gian phản hồi, điểm bộ chấm và cảnh báo hội thoại, mỗi mục kèm khoảng bình thường.",
    ),
    # --- time units
    "st_u_minute_one": ("minute", "phút"),
    "st_u_minute_many": ("minutes", "phút"),
    "st_u_hour_one": ("hour", "giờ"),
    "st_u_hour_many": ("hours", "giờ"),
    "st_u_day_one": ("day", "ngày"),
    "st_u_day_many": ("days", "ngày"),
    "st_u_second_one": ("second", "giây"),
    "st_u_second_many": ("seconds", "giây"),
    # --- time range and live
    "st_range": ("Time range", "Khoảng thời gian"),
    "st_view_hour": ("Last hour", "1 giờ qua"),
    "st_view_day": ("Last 24 hours", "24 giờ qua"),
    "st_view_week": ("Last 7 days", "7 ngày qua"),
    "st_view_live": ("Live", "Trực tiếp"),
    "st_by_live": ("{s}-second windows", "khung {s} giây"),
    "st_u_window_one": ("window", "khung"),
    "st_u_window_many": ("windows", "khung"),
    "st_by_hour": ("by minute", "theo phút"),
    "st_by_day": ("by hour", "theo giờ"),
    "st_by_week": ("by day", "theo ngày"),
    "st_live": ("Live: updates every {n} seconds", "Trực tiếp: cập nhật mỗi {n} giây"),
    "st_live_paused": ("Updates paused", "Đã tạm dừng cập nhật"),
    "st_live_pause": ("Pause updates", "Tạm dừng cập nhật"),
    "st_live_resume": ("Resume updates", "Tiếp tục cập nhật"),
    "st_updated": ("Updated {time}", "Cập nhật lúc {time}"),
    # --- charts
    "st_c_calls": ("Calls", "Lượt gọi"),
    "st_c_stopped": ("Stopped calls", "Lượt gọi bị chặn"),
    "st_c_amount": ("Payment amounts", "Số tiền thanh toán"),
    "st_c_mix": ("Tool mix", "Cơ cấu công cụ"),
    "st_c_latency": ("Response time", "Thời gian phản hồi"),
    "st_c_judge": ("Judge suspicion score", "Điểm nghi ngờ của bộ chấm"),
    "st_c_session": ("Conversation alerts", "Cảnh báo hội thoại"),
    "st_h_calls": (
        "Calls through the guardian in each window.",
        "Số lượt gọi qua bộ bảo vệ trong mỗi khung.",
    ),
    "st_h_stopped": (
        "Share of calls that were blocked or paused.",
        "Tỷ lệ lượt gọi bị chặn hoặc tạm dừng.",
    ),
    "st_h_amount": (
        "Typical amount and large amounts of payments.",
        "Số tiền thông thường và số tiền lớn của các khoản thanh toán.",
    ),
    "st_h_mix": (
        "Share of each tool among all calls.",
        "Tỷ trọng của từng công cụ trong tất cả lượt gọi.",
    ),
    "st_h_latency": (
        "Typical time and slow calls.",
        "Thời gian thông thường và các lượt gọi chậm.",
    ),
    "st_h_judge": (
        "How suspicious the automated judge finds the calls. Judges advise only.",
        "Mức độ nghi ngờ mà bộ chấm tự động đánh giá. Bộ chấm chỉ tư vấn.",
    ),
    "st_h_session": (
        "Alerts from the monitor that watches whole conversations.",
        "Cảnh báo từ bộ giám sát theo dõi cả cuộc hội thoại.",
    ),
    "st_m_calls": ("Calls", "Lượt gọi"),
    "st_m_stopped": ("Stopped calls", "Lượt gọi bị chặn"),
    "st_m_block_rate_bp": ("Stopped calls", "Lượt gọi bị chặn"),
    "st_m_amount_p50": ("Typical amount", "Số tiền thông thường"),
    "st_m_amount_p90": ("Large amounts", "Số tiền lớn"),
    "st_m_tool": ("Share of {tool}", "Tỷ trọng {tool}"),
    "st_m_mix": ("Tool mix", "Cơ cấu công cụ"),
    "st_m_latency_p50_ms": ("Typical response time", "Thời gian phản hồi thông thường"),
    "st_m_latency_p90_ms": ("Slow responses", "Phản hồi chậm"),
    "st_m_lat_p50": ("Typical response time", "Thời gian phản hồi thông thường"),
    "st_m_lat_p90": ("Slow responses", "Phản hồi chậm"),
    "st_m_gate_p50": (
        "Typical guardian check time",
        "Thời gian kiểm tra thông thường của bộ bảo vệ",
    ),
    "st_m_gate_p90": ("Slow guardian checks", "Các lượt kiểm tra chậm của bộ bảo vệ"),
    "st_m_judge_p50_bp": ("Typical judge score", "Điểm bộ chấm thông thường"),
    "st_m_judge_p90_bp": ("High judge scores", "Điểm bộ chấm cao"),
    "st_m_judge_p50": ("Typical judge score", "Điểm bộ chấm thông thường"),
    "st_m_judge_p90": ("High judge scores", "Điểm bộ chấm cao"),
    "st_m_alerts": ("Conversation alerts", "Cảnh báo hội thoại"),
    "st_sent_stay": (
        "{name} stayed inside the normal range.",
        "{name} vẫn nằm trong khoảng bình thường.",
    ),
    "st_sent_up": (
        "{name} rose from {a} to {b} in the last {n} {unit}.",
        "{name} tăng từ {a} lên {b} trong {n} {unit} gần nhất.",
    ),
    "st_sent_down": (
        "{name} fell from {a} to {b} in the last {n} {unit}.",
        "{name} giảm từ {a} xuống {b} trong {n} {unit} gần nhất.",
    ),
    "st_sent_none": (
        "Not enough calls to draw this chart yet.",
        "Chưa đủ lượt gọi để vẽ biểu đồ này.",
    ),
    "st_sent_plain": (
        "{name}: {b} now, {a} at the start of this period.",
        "{name}: hiện {b}, đầu giai đoạn là {a}.",
    ),
    "st_sent_alerts_n": (
        "{b} conversation alerts in this period.",
        "{b} cảnh báo hội thoại trong giai đoạn này.",
    ),
    "st_sent_alerts_0": (
        "No conversation alerts in this period.",
        "Không có cảnh báo hội thoại trong giai đoạn này.",
    ),
    "st_sent_alerts_off": (
        "The conversation monitor is not switched on.",
        "Bộ giám sát hội thoại chưa được bật.",
    ),
    "st_sent_mock": (
        "These scores come from a mock judge. They never decide the verdict.",
        "Các điểm này đến từ bộ chấm giả lập. Chúng không bao giờ quyết định kết luận.",
    ),
    "st_note_gate_latency": (
        "The agent does not report its own response time. This is the time the guardian took to check each call. It has no normal range.",
        "Tác tử không báo thời gian phản hồi của mình. Đây là thời gian bộ bảo vệ kiểm tra mỗi lượt gọi. Chưa có khoảng bình thường cho chỉ số này.",
    ),
    "st_note_band": (
        "The shaded normal range is set for windows of {win}. Choose the matching time range to see it.",
        "Khoảng bình thường được đặt cho khung {win}. Hãy chọn khoảng thời gian tương ứng để xem.",
    ),
    "st_trunc": (
        "Based on the latest {n} calls. Older calls are not shown.",
        "Dựa trên {n} lượt gọi gần nhất. Các lượt cũ hơn không được hiển thị.",
    ),
    "st_nodata": ("No data in this period yet", "Chưa có dữ liệu trong giai đoạn này"),
    "st_mock": ("Mock judge", "Bộ chấm giả lập"),
    "st_mock_chip": ("mock", "giả lập"),
    "st_lg_band": ("Normal range", "Khoảng bình thường"),
    "st_lg_breach": ("Outside the range", "Ngoài khoảng"),
    "st_lg_open": ("Window still open", "Khung chưa kết thúc"),
    "st_lg_p90": ("dashed line", "nét đứt"),
    "st_table": ("Table of numbers", "Bảng số liệu"),
    "st_col_time": ("Time", "Thời gian"),
    "st_chart_label": ("Chart: {name}", "Biểu đồ: {name}"),
    # --- what changed
    "st_changed": ("What changed", "Có gì thay đổi"),
    "st_changed_none": (
        "Nothing has changed in the last 14 days.",
        "Không có thay đổi nào trong 14 ngày qua.",
    ),
    "st_ev_case_drift": ("Drift case opened", "Đã mở vụ việc lệch chuẩn"),
    "st_ev_case_session": ("Conversation alert case opened", "Đã mở vụ việc cảnh báo hội thoại"),
    "st_ev_case": ("Case opened", "Đã mở vụ việc"),
    "st_ev_pause": ("Agent paused", "Tác tử bị tạm dừng"),
    "st_ev_pause_n": ("Agent paused {n} times", "Tác tử bị tạm dừng {n} lần"),
    "st_ev_quarantine_n": ("Agent isolated {n} times", "Tác tử bị cách ly {n} lần"),
    "st_ev_quarantine": ("Agent isolated", "Tác tử bị cách ly"),
    "st_ev_incident": ("Incident opened: {title}", "Đã mở sự cố: {title}"),
    "st_ev_baseline": ("Normal range set ({n} measures)", "Đã đặt khoảng bình thường ({n} chỉ số)"),
    "st_ev_guardian": ("Guardian {slug}: {state}", "Bộ bảo vệ {slug}: {state}"),
    "st_ev_open": ("Open", "Mở"),
}
