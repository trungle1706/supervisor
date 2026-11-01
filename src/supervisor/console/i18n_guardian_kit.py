# ruff: noqa: E501
"""Labels of the "Connect your app to Guardian" block (GUARDIAN_KIT), English and Vietnamese,
prefix ``gk_``. Merged into ``i18n._T`` by one line in ``i18n.py``. Plain manager-level wording
(``scratchpad/copy/STYLE.md``): no flag names, no API paths. Code lines and file names are not text
and are never translated."""

from __future__ import annotations

GK: dict[str, tuple[str, str]] = {
    "gk_title": ("Connect your app to Guardian", "Kết nối ứng dụng của bạn với Guardian"),
    "gk_hint": (
        "Guardian protects a tool only when the tool asks it first. Add one line to each tool, then check your code.",
        "Guardian chỉ bảo vệ được công cụ nào hỏi Guardian trước khi chạy. Hãy thêm một dòng vào mỗi công cụ, rồi kiểm tra mã.",
    ),
    "gk_loading": ("Loading the status...", "Đang tải trạng thái..."),
    "gk_status": ("Guardian-ready", "Sẵn sàng với Guardian"),
    "gk_st_not_checked": ("Not checked", "Chưa kiểm tra"),
    "gk_st_not_ready": ("Not ready", "Chưa sẵn sàng"),
    "gk_st_partly_ready": (
        "Partly ready ({ok} of {total} tools)",
        "Sẵn sàng một phần ({ok}/{total} công cụ)",
    ),
    "gk_st_ready": ("Ready", "Sẵn sàng"),
    "gk_st_no_tools": ("No tools found", "Không thấy công cụ nào"),
    "gk_count": ("{ok} of {total} tools connected", "{ok}/{total} công cụ đã kết nối"),
    "gk_last": ("Last checked {when} by {who}.", "Kiểm tra lần cuối {when} bởi {who}."),
    "gk_never": ("Not checked yet.", "Chưa kiểm tra lần nào."),
    "gk_source_line": (
        "Checked: source upload {n} ({kind}).",
        "Đã kiểm tra: lần tải mã nguồn {n} ({kind}).",
    ),
    "gk_kind_upload": ("zip file", "tệp zip"),
    "gk_kind_git": ("GitHub", "GitHub"),
    "gk_kind_workspace": ("workspace", "workspace"),
    "gk_newer": (
        "A newer source (upload {n}) is not checked yet.",
        "Có mã nguồn mới hơn (lần tải {n}) chưa được kiểm tra.",
    ),
    "gk_btn_check_first": ("Check my code", "Kiểm tra mã của tôi"),
    "gk_btn_check": ("Check my code again", "Kiểm tra lại mã của tôi"),
    "gk_btn_git": ("Fetch the latest from GitHub", "Lấy mã mới nhất từ GitHub"),
    "gk_btn_upload": ("Upload newer source", "Tải mã nguồn mới hơn"),
    "gk_btn_source": ("Add source code", "Thêm mã nguồn"),
    "gk_no_source": (
        "No source code yet. Add it first, then check it.",
        "Chưa có mã nguồn. Hãy thêm mã nguồn trước, rồi kiểm tra.",
    ),
    "gk_view_only": (
        "You can view this status. A system editor runs the check.",
        "Bạn chỉ xem được trạng thái này. Người chỉnh sửa hệ thống chạy kiểm tra.",
    ),
    "gk_no_tools": (
        "The code has no tools. There is nothing to connect.",
        "Mã không có công cụ nào. Không có gì cần kết nối.",
    ),
    "gk_c_tool": ("Tool", "Công cụ"),
    "gk_c_risk": ("Risk class", "Loại rủi ro"),
    "gk_c_state": ("Status", "Trạng thái"),
    "gk_c_where": ("Where", "Vị trí"),
    "gk_rc_read_only": ("Read only", "Chỉ đọc"),
    "gk_rc_money": ("Moves money", "Chuyển tiền"),
    "gk_rc_credit": ("Credit", "Tín dụng"),
    "gk_rc_pii_export": ("Personal data", "Dữ liệu cá nhân"),
    "gk_ts_unknown": ("Not checked", "Chưa kiểm tra"),
    "gk_ts_connected": ("Connected", "Đã kết nối"),
    "gk_ts_missing": ("Missing", "Chưa có"),
    "gk_ts_wrong_name": ("Wrong name", "Sai tên"),
    "gk_ts_wrong_risk": ("Wrong risk class", "Sai loại rủi ro"),
    "gk_h_missing": ("Add the line above this tool.", "Thêm dòng này phía trên công cụ."),
    "gk_h_wrong_name": (
        "The line names {found}. Use {name}.",
        "Dòng này ghi {found}. Hãy ghi {name}.",
    ),
    "gk_h_wrong_risk": (
        "The line says {found}. Use {risk}.",
        "Dòng này ghi {found}. Hãy ghi {risk}.",
    ),
    "gk_extras": ("Also connected: {names}", "Cũng đã kết nối: {names}"),
    "gk_note_client_file_missing": (
        "Your code uses guardian_client.py, but the file is not in the stored source. Add it, then check again.",
        "Mã của bạn dùng guardian_client.py, nhưng tệp này chưa có trong mã nguồn đã lưu. Hãy thêm tệp, rồi kiểm tra lại.",
    ),
    "gk_note_unparsed": (
        "Some Python files could not be read. The check left them out.",
        "Một số tệp Python không đọc được. Kiểm tra đã bỏ qua các tệp này.",
    ),
    # --- the guide
    "gk_guide": ("How to connect", "Cách kết nối"),
    "gk_fw_line": ("Your code uses {framework}.", "Mã của bạn dùng {framework}."),
    "gk_fw_custom": (
        "Your code does not use a known framework.",
        "Mã của bạn không dùng framework quen thuộc nào.",
    ),
    "gk_who_dev": ("Developer", "Nhà phát triển"),
    "gk_who_admin": ("Administrator", "Quản trị viên"),
    "gk_s1_t": ("Add the file", "Thêm tệp"),
    "gk_s1_d": (
        "Download guardian_client.py. Put it in the same folder as your tools.",
        "Tải tệp guardian_client.py. Đặt tệp cùng thư mục với các công cụ của bạn.",
    ),
    "gk_s1_dir": ("Folder in your code: {dir}", "Thư mục trong mã của bạn: {dir}"),
    "gk_s2_t": ("Add one line above each tool", "Thêm một dòng phía trên mỗi công cụ"),
    "gk_s2_d": (
        "Add the import once at the top of the file. Then add one line above each tool.",
        "Thêm dòng import một lần ở đầu tệp. Sau đó thêm một dòng phía trên mỗi công cụ.",
    ),
    "gk_s2_decorator": (
        "Keep the line of your framework first. The Guardian line goes directly above def.",
        "Giữ dòng của framework ở trên cùng. Dòng Guardian đặt ngay phía trên def.",
    ),
    "gk_s2_function": (
        "Your tools are listed in a table or registry. Leave it as it is. Put the line on the function it points to.",
        "Các công cụ của bạn được khai báo trong một bảng hoặc danh sách. Giữ nguyên phần đó. Đặt dòng này trên hàm mà nó trỏ tới.",
    ),
    "gk_s2_wrapper": (
        "A web route cannot take the line. Put it on a small function with plain arguments, and call that function from the route.",
        "Route web không nhận được dòng này. Hãy đặt dòng trên một hàm nhỏ có tham số đơn giản, rồi gọi hàm đó từ route.",
    ),
    "gk_s2_example": ("Example with your tool {tool}:", "Ví dụ với công cụ {tool} của bạn:"),
    "gk_s2_all": ("The line for each of your tools:", "Dòng cho từng công cụ của bạn:"),
    "gk_s3_t": ("Set the Guardian address", "Đặt địa chỉ Guardian"),
    "gk_s3_d": (
        "Set this where your app starts.",
        "Đặt giá trị này ở nơi ứng dụng của bạn khởi động.",
    ),
    "gk_s4_t": ("Ask for one grant", "Xin cấp một quyền"),
    "gk_s4_hmac": (
        "The Guardian administrator issues a key for {agent}. Save it in a key file, and put the file path in the setting above.",
        "Quản trị viên Guardian cấp một khóa cho {agent}. Lưu khóa vào một tệp khóa, rồi ghi đường dẫn tệp vào phần cài đặt ở trên.",
    ),
    "gk_s4_oauth": (
        "Your workspace admin lets the service principal of your app act as {agent} in Guardian.",
        "Quản trị viên workspace cho phép service principal của ứng dụng hoạt động với tên {agent} trong Guardian.",
    ),
    "gk_s5_t": ("Deploy", "Triển khai"),
    "gk_s5_d": (
        "Deploy your app with the new file and the settings.",
        "Triển khai ứng dụng với tệp mới và các cài đặt trên.",
    ),
    "gk_s6_t": ("Check", "Kiểm tra"),
    "gk_s6_d": (
        "Press Check my code again on this page. The status turns Ready when every tool is connected.",
        "Bấm Kiểm tra lại mã của tôi trên trang này. Trạng thái chuyển sang Sẵn sàng khi mọi công cụ đã kết nối.",
    ),
    "gk_copy": ("Copy", "Sao chép"),
    "gk_copied": ("Copied", "Đã sao chép"),
    # --- the code file
    "gk_file_t": ("The code file", "Tệp mã"),
    "gk_file_d": (
        "One file. Standard library only, Python 3.11 or newer. Your app needs no other package.",
        "Một tệp duy nhất. Chỉ dùng thư viện chuẩn, Python 3.11 trở lên. Ứng dụng của bạn không cần gói nào khác.",
    ),
    "gk_file_safe": (
        "The file holds no key and no password.",
        "Tệp không chứa khóa hay mật khẩu.",
    ),
    "gk_download": ("Download guardian_client.py", "Tải guardian_client.py"),
    "gk_copy_file": ("Copy the file", "Sao chép tệp"),
    "gk_show_file": ("Show the file", "Xem tệp"),
}
