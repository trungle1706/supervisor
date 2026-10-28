# ruff: noqa: E501
"""Labels of the Attach panel (WP-O4), English and Vietnamese, prefix ``at_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

AT: dict[str, tuple[str, str]] = {
    "at_title": ("Attach", "Gắn kết"),
    "at_open_page": ("Open the Attach page", "Mở trang Gắn kết"),
    "at_hint": (
        "Where this agent plugs into the Supervisor and which guardians sit on that plug point. A circle is filled when the guardian has shown evidence in the last 7 days (a verdict, a finding, a monitor row or a pack result). A lock means the guardian is in the guardian floor and cannot be switched off. Read only: the Supervisor reads its own tables and does not call the agent.",
        "Nơi tác nhân này nối vào Supervisor và các công cụ bảo vệ nằm trên điểm nối đó. Vòng tròn được tô khi công cụ có bằng chứng trong 7 ngày qua (phán quyết, phát hiện, dòng giám sát hoặc kết quả gói). Ổ khóa nghĩa là công cụ thuộc mức sàn và không thể tắt. Chỉ đọc: Supervisor đọc bảng của chính nó và không gọi tác nhân.",
    ),
    "at_plug_is": ("Plug point in use:", "Điểm nối đang dùng:"),
    "at_plug_sdk": ("SDK (HttpGate)", "SDK (HttpGate)"),
    "at_plug_http_proxy": ("HTTP proxy", "Proxy HTTP"),
    "at_plug_mcp_gateway": ("MCP gateway", "Cổng MCP"),
    "at_plug_databricks_app": ("Databricks App environment", "Môi trường Databricks App"),
    "at_plug_unknown": ("not known", "chưa rõ"),
    "at_plugshort_sdk": ("SDK HttpGate", "SDK HttpGate"),
    "at_plugshort_http_proxy": ("HTTP proxy", "Proxy HTTP"),
    "at_plugshort_mcp_gateway": ("MCP gateway", "Cổng MCP"),
    "at_plugshort_databricks_app": ("Databricks App env", "Databricks App env"),
    "at_plugshort_unknown": ("plug point unknown", "chưa rõ điểm nối"),
    "at_by_agent_row": ("from the agent row", "từ dòng tác nhân"),
    "at_by_policy": ("from the policy file", "từ tệp chính sách"),
    "at_by_none": (
        "no agent row and no policy entry",
        "không có dòng tác nhân và không có mục chính sách",
    ),
    "at_state_unknown": ("state unknown", "chưa rõ trạng thái"),
    "at_checked": ("Read at", "Đọc lúc"),
    "at_svg_title": ("Wiring of {agent}", "Sơ đồ nối của {agent}"),
    "at_svg_desc": (
        "The agent, its plug point and the Supervisor gate, then four groups of guardians. {lit} of {n} guardians have evidence in the last 7 days.",
        "Tác nhân, điểm nối và cổng Supervisor, rồi bốn nhóm công cụ bảo vệ. {lit} trên {n} công cụ có bằng chứng trong 7 ngày qua.",
    ),
    "at_box_agent": ("agent", "tác nhân"),
    "at_box_plug": ("plug point", "điểm nối"),
    "at_box_gate": ("Supervisor gate", "Cổng Supervisor"),
    "at_grp_gate": ("Gate rules", "Luật cổng"),
    "at_grp_detectors": ("Detectors", "Bộ phát hiện"),
    "at_grp_judges": ("Judges", "Giám khảo"),
    "at_grp_monitors": ("Monitors and packs", "Giám sát và gói"),
    "at_no_evidence": ("no evidence yet", "chưa có bằng chứng"),
    "at_legend": (
        "Filled circle: evidence in the last 7 days. Outline: none yet. Dashed outline: switched off. Lock: guardian floor.",
        "Vòng tô: có bằng chứng trong 7 ngày qua. Vòng rỗng: chưa có. Nét đứt: đã tắt. Ổ khóa: mức sàn.",
    ),
    "at_c_guardian": ("Guardian", "Công cụ bảo vệ"),
    "at_c_state": ("State", "Trạng thái"),
    "at_c_last": ("Last evidence", "Bằng chứng gần nhất"),
    "at_c_count": ("Last 7 days", "7 ngày qua"),
    "at_floor": ("floor", "mức sàn"),
    "at_lit": ("evidence", "có bằng chứng"),
    "at_waiting": ("waiting", "đang chờ"),
    "at_off": ("off", "tắt"),
    "at_check": ("Check now", "Kiểm tra ngay"),
    "at_check_hint": (
        "Reads the gate state and the last evidence again from the Supervisor store. It does not call the agent.",
        "Đọc lại trạng thái cổng và bằng chứng gần nhất từ kho của Supervisor. Không gọi tác nhân.",
    ),
    "at_view_only": (
        "You may view this panel; Check now needs the edit right.",
        "Bạn chỉ xem được bảng này; Kiểm tra ngay cần quyền sửa.",
    ),
    "at_how": ("How to attach", "Cách gắn kết"),
    "at_how_hint_sdk": (
        "Set these in the environment of the agent process. The agent code reads them when it builds its HttpGate.",
        "Đặt các biến này trong môi trường của tiến trình tác nhân. Mã tác nhân đọc chúng khi tạo HttpGate.",
    ),
    "at_how_hint_http_proxy": (
        "Set these where the proxy runs, then point the agent at the proxy.",
        "Đặt các biến này nơi proxy chạy, rồi trỏ tác nhân vào proxy.",
    ),
    "at_how_hint_mcp_gateway": (
        "Start the MCP gateway beside the agent with these lines, then point the MCP client at the listener.",
        "Chạy cổng MCP cạnh tác nhân với các dòng này, rồi trỏ máy khách MCP vào cổng nghe.",
    ),
    "at_how_hint_databricks_app": (
        "Add these entries to the env list of the agent app.yaml.",
        "Thêm các mục này vào danh sách env của app.yaml của tác nhân.",
    ),
    "at_how_hint_unknown": (
        "The plug point is not known. These are the lines for the SDK; set the plug point on the agent row first.",
        "Chưa rõ điểm nối. Đây là các dòng cho SDK; hãy đặt điểm nối trên dòng tác nhân trước.",
    ),
    "at_copy": ("Copy", "Sao chép"),
    "at_principals": (
        "Principals listed for this agent in agent_identities.yaml:",
        "Chủ thể được liệt kê cho tác nhân này trong agent_identities.yaml:",
    ),
    "at_note_secret_hmac": (
        "The key is not shown here. Issue it with python -m supervisor.gateway.ingress_auth issue and give the agent the key file (SUPERVISOR_AGENT_KEY_FILE).",
        "Khóa không hiển thị ở đây. Cấp bằng python -m supervisor.gateway.ingress_auth issue và đưa tệp khóa cho tác nhân (SUPERVISOR_AGENT_KEY_FILE).",
    ),
    "at_note_secret_oauth": (
        "No secret is needed in the file: the app uses the OAuth token of its own service principal. Never set DATABRICKS_TOKEN.",
        "Không cần bí mật trong tệp: ứng dụng dùng token OAuth của service principal của chính nó. Không bao giờ đặt DATABRICKS_TOKEN.",
    ),
    "at_note_ingress_off": (
        "Ingress authentication is off in this instance (INGRESS_AUTH_ENABLED=0); the credential is not checked yet.",
        "Xác thực đầu vào đang tắt ở hệ thống này (INGRESS_AUTH_ENABLED=0); chưa kiểm tra thông tin xác thực.",
    ),
    "at_note_no_principal": (
        "No principal is listed for this agent in config/agent_identities.yaml. Add the service principal there, or the gate refuses the call (HTTP 403).",
        "Chưa có chủ thể nào cho tác nhân này trong config/agent_identities.yaml. Hãy thêm service principal vào đó, nếu không cổng sẽ từ chối (HTTP 403).",
    ),
    "at_note_proxy": (
        "SUPERVISOR_URL is the name the collectors and proxy hooks read.",
        "SUPERVISOR_URL là tên mà các bộ thu và hook của proxy đọc.",
    ),
    "at_note_mcp": (
        "One gateway process serves one agent and one upstream MCP server. Replace the FILL-ME values.",
        "Một tiến trình cổng phục vụ một tác nhân và một máy chủ MCP. Hãy thay các giá trị FILL-ME.",
    ),
    "at_note_unknown_plug": (
        "Neither the agent row nor the policy file names a plug point this view knows.",
        "Cả dòng tác nhân lẫn tệp chính sách đều không nêu điểm nối mà màn hình này biết.",
    ),
}
