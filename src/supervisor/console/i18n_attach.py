# ruff: noqa: E501
"""Labels of the Attach panel (WP-O4), English and Vietnamese, prefix ``at_``. Merged into
``i18n._T`` by one line in ``i18n.py``. Synthetic UI text only."""

from __future__ import annotations

AT: dict[str, tuple[str, str]] = {
    "at_title": ("Attach", "Gắn kết"),
    "at_open_page": ("Open the Attach page", "Mở trang Gắn kết"),
    "at_hint": (
        "Shows how this agent connects to the gate and which guardians watch it. View only: Supervisor does not call the agent.",
        "Cho thấy tác tử nối vào cổng thế nào và bộ bảo vệ nào theo dõi nó. Chỉ để xem: Supervisor không gọi tác tử.",
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
    "at_plugshort_unknown": ("connection point unknown", "chưa rõ điểm kết nối"),
    "at_by_agent_row": ("from the agent settings", "từ cài đặt của tác tử"),
    "at_by_policy": ("from the policy file", "từ tệp chính sách"),
    "at_by_none": (
        "not set in the agent settings or the policy file",
        "chưa đặt trong cài đặt tác tử hay tệp chính sách",
    ),
    "at_state_unknown": ("state unknown", "chưa rõ trạng thái"),
    "at_checked": ("Checked at", "Kiểm tra lúc"),
    "at_svg_title": ("How {agent} is connected", "Cách {agent} được kết nối"),
    "at_svg_desc": (
        "The agent, its connection point and the Supervisor gate, then four groups of guardians. {lit} of {n} guardians have evidence in the last 7 days.",
        "Tác tử, điểm kết nối và cổng Supervisor, rồi bốn nhóm bộ bảo vệ. {lit} trên {n} bộ bảo vệ có bằng chứng trong 7 ngày qua.",
    ),
    "at_box_agent": ("agent", "tác tử"),
    "at_box_plug": ("connection point", "điểm kết nối"),
    "at_box_gate": ("Supervisor gate", "Cổng Supervisor"),
    "at_grp_gate": ("Gate rules", "Luật cổng"),
    "at_grp_detectors": ("Detectors", "Bộ phát hiện"),
    "at_grp_judges": ("Judges", "Giám khảo"),
    "at_grp_monitors": ("Monitors and automated checks", "Giám sát và kiểm tra tự động"),
    "at_no_evidence": ("no evidence yet", "chưa có bằng chứng"),
    "at_legend": (
        "Filled circle: evidence in the last 7 days. Outline: none yet. Dashed outline: switched off. Lock: required by policy.",
        "Vòng tô: có bằng chứng trong 7 ngày qua. Vòng rỗng: chưa có. Nét đứt: đã tắt. Ổ khóa: bắt buộc theo chính sách.",
    ),
    "at_c_guardian": ("Guardian", "Bộ bảo vệ"),
    "at_c_state": ("State", "Trạng thái"),
    "at_c_last": ("Last evidence", "Bằng chứng gần nhất"),
    "at_c_count": ("Last 7 days", "7 ngày qua"),
    "at_floor": ("required", "bắt buộc"),
    "at_lit": ("evidence", "có bằng chứng"),
    "at_waiting": ("waiting", "đang chờ"),
    "at_off": ("off", "tắt"),
    "at_check": ("Check now", "Kiểm tra ngay"),
    "at_check_hint": (
        "Refreshes the status. Does not call the agent.",
        "Làm mới trạng thái. Không gọi tác tử.",
    ),
    "at_view_only": (
        "You can view this panel. To use Check now, you need edit permission.",
        "Bạn xem được bảng này. Để dùng Kiểm tra ngay, bạn cần quyền sửa.",
    ),
    "at_how": ("How to attach", "Cách gắn kết"),
    "at_how_hint_sdk": (
        "Set these in the agent's environment. The agent code reads them when it creates its HttpGate.",
        "Đặt các biến này trong môi trường của tác tử. Mã tác tử đọc chúng khi tạo HttpGate.",
    ),
    "at_how_hint_http_proxy": (
        "Set these where the proxy runs, then point the agent at the proxy.",
        "Đặt các biến này nơi proxy chạy, rồi trỏ tác tử vào proxy.",
    ),
    "at_how_hint_mcp_gateway": (
        "Start the MCP gateway next to the agent with these lines, then point the MCP client at it.",
        "Chạy cổng MCP cạnh tác tử bằng các dòng này, rồi trỏ máy khách MCP vào cổng đó.",
    ),
    "at_how_hint_databricks_app": (
        "Add these entries to the env list in the agent's app.yaml.",
        "Thêm các mục này vào danh sách env trong app.yaml của tác tử.",
    ),
    "at_how_hint_unknown": (
        "The connection point is not known. These lines are for the SDK. Set the connection point in the agent settings first.",
        "Chưa rõ điểm kết nối. Các dòng này dành cho SDK. Hãy đặt điểm kết nối trong cài đặt tác tử trước.",
    ),
    "at_copy": ("Copy", "Sao chép"),
    "at_principals": (
        "Identities listed for this agent in agent_identities.yaml:",
        "Danh tính được liệt kê cho tác tử này trong agent_identities.yaml:",
    ),
    "at_note_secret_hmac": (
        "The key is not shown here. Issue it with python -m supervisor.gateway.ingress_auth issue and give the agent the key file (SUPERVISOR_AGENT_KEY_FILE).",
        "Khóa không hiển thị ở đây. Cấp bằng python -m supervisor.gateway.ingress_auth issue và đưa tệp khóa cho tác tử (SUPERVISOR_AGENT_KEY_FILE).",
    ),
    "at_note_secret_oauth": (
        "No secret is needed in the file: the app uses the OAuth token of its own service principal. Never set DATABRICKS_TOKEN.",
        "Không cần bí mật trong tệp: ứng dụng dùng token OAuth của service principal của chính nó. Không bao giờ đặt DATABRICKS_TOKEN.",
    ),
    "at_note_ingress_off": (
        "Agent sign-in is off here (INGRESS_AUTH_ENABLED=0), so the credential is not checked.",
        "Đăng nhập của tác tử đang tắt ở đây (INGRESS_AUTH_ENABLED=0) nên thông tin xác thực không được kiểm tra.",
    ),
    "at_note_no_principal": (
        "This agent is not listed in config/agent_identities.yaml. Add its service principal there, or the gate refuses its calls (HTTP 403).",
        "Tác tử này chưa có trong config/agent_identities.yaml. Hãy thêm service principal của nó vào đó, nếu không cổng sẽ từ chối lệnh gọi (HTTP 403).",
    ),
    "at_note_proxy": (
        "SUPERVISOR_URL is the name the collectors and proxy hooks read.",
        "SUPERVISOR_URL là tên mà các bộ thu và hook của proxy đọc.",
    ),
    "at_note_mcp": (
        "Each gateway serves one agent and one MCP server. Replace the FILL-ME values.",
        "Mỗi cổng phục vụ một tác tử và một máy chủ MCP. Hãy thay các giá trị FILL-ME.",
    ),
    "at_note_unknown_plug": (
        "Neither the agent settings nor the policy file give a connection point this page recognises.",
        "Cả cài đặt tác tử lẫn tệp chính sách đều không nêu điểm kết nối mà trang này nhận ra.",
    ),
}
