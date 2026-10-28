# ruff: noqa: E501
"""Scenario specs of the starter golden sets (WP-F5). Data only; ``tools/factory_golden_gen.py``
turns them into cases. Synthetic Vietnamese text: no real person, bank, account or document.

Per checklist item:  ``p`` = variants whose expected verdict is pass, ``f`` = fail, ``n`` =
not_applicable (only for items whose pass rule has an applicability clause). A variant is a list
of snippets; a snippet with ``ev=True`` is the evidence the case expects the agent to cite. The
``question`` cases are made by the generator: only neutral sources, nothing that decides the item.

Snippets (placeholders in {braces} are filled per case, see ``factory_golden_gen.fill``):
  R(key, value)                   a field of the system record
  D(text)                         a section of an internal document
  F(kind, name, detail, file, line, quote)   a fact of the facts card
  K(pack, state)                  a pack result; state is pass, fail or stale (older version only)
  G(inst, article, text)          a RegKB row
"""

from __future__ import annotations

from typing import Any

Snip = tuple[Any, ...]


def R(key: str, val: str, ev: bool = True) -> Snip:
    return ("r", key, val, ev)


def D(text: str, ev: bool = True) -> Snip:
    return ("d", text, ev)


def F(kind: str, name: str, detail: str, file: str, line: int, quote: str, ev: bool = True) -> Snip:
    return ("f", kind, name, detail, file, line, quote, ev)


def K(pack: str, state: str, ev: bool = True) -> Snip:
    return ("k", pack, state, ev)


def G(inst: str, art: str, text: str, ev: bool = True) -> Snip:
    return ("g", inst, art, text, ev)


def pack_item(pack: str) -> dict[str, list[list[Snip]]]:
    return {
        "p": [[K(pack, "pass")], [K(pack, "pass")]],
        "f": [[K(pack, "fail")], [K(pack, "stale")]],
    }


SPECS: dict[str, dict[str, list[list[Snip]]]] = {
    # ------------------------------------------------------------------ model risk
    "MR-01": {
        "p": [
            [R("model_id", "{model}"), R("model_version", "{ver}"), R("validation_date", "{date}")],
            [
                R(
                    "model_register",
                    "mô hình {model}, phiên bản {ver}, kiểm định lần cuối ngày {date} do {ind} thực hiện",
                )
            ],
        ],
        "f": [
            [R("model_id", "{model}"), R("model_version", "{ver}"), R("validation_date", "{old}")],
            [
                R("model_id", "{model}"),
                R("model_version", "(chưa ghi)"),
                R("validation_date", "(chưa có)"),
            ],
        ],
    },
    "MR-02": {
        "p": [
            [
                D(
                    "Báo cáo kiểm định mô hình {model}: kiểm định trước khi vận hành ngày {old}, kiểm định định kỳ ngày {date}; thay đổi lớn gần nhất đã được kiểm định lại."
                )
            ],
            [R("validation_history", "lần đầu {old}; định kỳ {date}; sau thay đổi lớn {date}")],
        ],
        "f": [
            [
                D(
                    "Báo cáo kiểm định mô hình {model}: chỉ có kiểm định trước khi vận hành ngày {old}; chưa có kiểm định định kỳ nào sau đó dù đã có thay đổi lớn ngày {date}."
                )
            ],
            [R("validation_history", "lần đầu {old}; chưa kiểm định lại")],
        ],
    },
    "MR-03": {
        "p": [
            [R("validator_unit", "{ind}"), R("developer_unit", "{dev}")],
            [
                D(
                    "Biên bản kiểm định: đơn vị kiểm định là {ind}, độc lập với {dev} (phát triển), đơn vị vận hành và nhà cung cấp mô hình."
                )
            ],
        ],
        "f": [
            [R("validator_unit", "{dev}"), R("developer_unit", "{dev}")],
            [
                D(
                    "Biên bản kiểm định: việc kiểm định do chính {dev} thực hiện, cũng là đơn vị phát triển và vận hành mô hình."
                )
            ],
        ],
    },
    "MR-04": {
        "p": [
            [
                D(
                    "Tài liệu phù hợp dữ liệu: bộ huấn luyện {ds} và bộ kiểm thử {ds2} đã được so sánh với phạm vi sử dụng; phân bố khớp với bài toán."
                )
            ],
            [
                R(
                    "data_fit_note",
                    "đã đối chiếu bộ {ds} với bộ {ds2} so với phạm vi sử dụng, kết luận phù hợp",
                )
            ],
        ],
        "f": [
            [
                D(
                    "Tài liệu phù hợp dữ liệu: bộ huấn luyện {ds} lấy từ giai đoạn trước đây, không khớp với khách hàng hiện nay; chưa có bộ kiểm thử riêng."
                )
            ],
            [R("data_fit_note", "chưa đối chiếu dữ liệu huấn luyện với phạm vi sử dụng")],
        ],
    },
    "MR-05": pack_item("truthfulqa_vi"),
    "MR-06": pack_item("perturbation_vi"),
    "MR-07": {
        "p": [
            [
                D(
                    "Mô tả khả năng giải thích: kết quả kèm ba yếu tố đầu vào ảnh hưởng nhiều nhất ({factor1}, {factor2}, {factor3}) và giải thích bằng ngôn ngữ thường cho người dùng."
                )
            ],
            [
                R(
                    "explainability",
                    "có; hiển thị ba yếu tố ảnh hưởng chính cho người dùng nghiệp vụ",
                )
            ],
        ],
        "f": [
            [
                D(
                    "Mô tả khả năng giải thích: mô hình là hộp đen, không có cách nào cho biết yếu tố đầu vào nào ảnh hưởng đến kết quả."
                )
            ],
            [R("explainability", "không có; người dùng chỉ thấy điểm số")],
        ],
    },
    "MR-08": {
        "p": [
            [
                R(
                    "fairness_monitor",
                    "bật; {n} lát cắt theo nhóm tuổi và khu vực, không lát cắt nào vượt ngưỡng",
                )
            ],
            [
                D(
                    "Báo cáo công bằng quý này: đã kiểm tra các lát cắt theo nhóm tuổi và khu vực; không có lát cắt thất bại."
                )
            ],
        ],
        "f": [
            [
                R(
                    "fairness_monitor",
                    "bật; lát cắt nhóm tuổi trên 60 vượt ngưỡng chênh lệch, trạng thái thất bại",
                )
            ],
            [
                D(
                    "Báo cáo công bằng quý này: lát cắt theo khu vực thất bại ở ngưỡng chênh lệch; chưa có biện pháp khắc phục."
                )
            ],
        ],
    },
    "MR-09": {
        "p": [
            [
                R(
                    "drift_monitor",
                    "bật; dải trôi {n} điểm cơ bản, ngưỡng cảnh báo đã đặt, hành động can thiệp: chuyển sang duyệt tay",
                )
            ],
            [
                F(
                    "claim",
                    "drift_band",
                    "dải trôi và ngưỡng cảnh báo đã cấu hình; hành động can thiệp: dừng và duyệt tay",
                    "monitor/drift.yaml",
                    8,
                    "alert_threshold: set",
                )
            ],
        ],
        "f": [
            [
                R(
                    "drift_monitor",
                    "bật nhưng chưa đặt ngưỡng cảnh báo và chưa có hành động can thiệp",
                )
            ],
            [R("drift_monitor", "chưa có")],
        ],
    },
    "MR-10": {
        "p": [
            [
                D(
                    "Hồ sơ mô hình của {vendor}: đã kiểm thử hộp đen trên dữ liệu của ngân hàng ngày {date}; kế hoạch dự phòng khi nhà cung cấp đổi mô hình: quay lại phiên bản đã ghim."
                )
            ],
            [R("vendor_model_tests", "kiểm thử hộp đen ngày {date}; kế hoạch dự phòng đã duyệt")],
        ],
        "f": [
            [
                D(
                    "Hồ sơ mô hình của {vendor}: chưa kiểm thử hộp đen trên dữ liệu của ngân hàng; chưa có kế hoạch dự phòng khi nhà cung cấp cập nhật mô hình."
                )
            ],
            [R("vendor_model_tests", "chưa kiểm thử; chưa có kế hoạch dự phòng")],
        ],
        "n": [
            [
                R(
                    "model_hosting",
                    "mô hình do ngân hàng tự xây dựng và tự vận hành, không dùng mô hình bên thứ ba",
                )
            ],
        ],
    },
    "MR-11": {
        "p": [
            [
                R(
                    "change_log",
                    "{ver}: ngày {date}, phạm vi ảnh hưởng: chấm điểm, kết quả kiểm thử: đạt",
                )
            ],
            [
                F(
                    "file",
                    "CHANGELOG.md",
                    "nhật ký thay đổi mô hình có phiên bản, ngày, phạm vi ảnh hưởng, kết quả kiểm thử",
                    "CHANGELOG.md",
                    3,
                    "## {ver} - {date}",
                )
            ],
        ],
        "f": [
            [
                R(
                    "change_log",
                    "chỉ có số phiên bản; không có ngày, phạm vi ảnh hưởng và kết quả kiểm thử",
                )
            ],
            [R("change_log", "không có nhật ký thay đổi")],
        ],
    },
    "MR-12": pack_item("paraphrase_consistency"),
    # ------------------------------------------------------------------ data governance
    "DG-01": {
        "p": [
            [
                F(
                    "dataset",
                    "{ds}",
                    "nguồn: hệ thống lõi, chủ sở hữu dữ liệu: {data_unit}",
                    "data/sources.yaml",
                    4,
                    "source: core_system",
                )
            ],
            [R("data_provenance", "{ds}: nguồn hệ thống lõi, chủ sở hữu {data_unit}")],
        ],
        "f": [
            [
                F(
                    "dataset",
                    "{ds}",
                    "nguồn: không rõ; chưa có chủ sở hữu",
                    "data/sources.yaml",
                    4,
                    "source: unknown",
                )
            ],
            [R("data_provenance", "{ds}: chưa ghi nguồn")],
        ],
    },
    "DG-02": {
        "p": [
            [
                D(
                    "Mô tả dữ liệu: bộ {ds} là dữ liệu tổng hợp, sinh bằng bộ sinh có hạt giống cố định; được gắn nhãn tổng hợp."
                )
            ],
            [
                R(
                    "synthetic_data",
                    "có; gắn nhãn tổng hợp, phương pháp sinh: bộ sinh có hạt giống cố định",
                )
            ],
        ],
        "f": [
            [
                D(
                    "Mô tả dữ liệu: bộ {ds} là dữ liệu tổng hợp nhưng không gắn nhãn tổng hợp và không nêu phương pháp sinh."
                )
            ],
            [R("synthetic_data", "có dùng dữ liệu tổng hợp; chưa gắn nhãn")],
        ],
        "n": [[R("synthetic_data", "không dùng dữ liệu tổng hợp")]],
    },
    "DG-03": {
        "p": [
            [
                R(
                    "input_log",
                    "nhật ký tiền xử lý đầu vào lưu tại kho nhật ký tập trung, giữ {n} ngày",
                )
            ],
            [
                F(
                    "file",
                    "preprocess_log.py",
                    "ghi nhật ký mỗi bước tiền xử lý dữ liệu đầu vào",
                    "pipeline/preprocess_log.py",
                    21,
                    "log_step(name, rows_in, rows_out)",
                )
            ],
        ],
        "f": [
            [R("input_log", "không ghi nhật ký tiền xử lý đầu vào")],
            [
                F(
                    "weak_spot",
                    "preprocess",
                    "bước tiền xử lý chạy không để lại dấu vết",
                    "pipeline/preprocess.py",
                    17,
                    "# TODO: log",
                )
            ],
        ],
    },
    "DG-04": {
        "p": [
            [
                D(
                    "Quy trình chất lượng dữ liệu: kiểm tra giá trị thiếu, trùng lặp và ngoài miền mỗi ngày; chủ sở hữu kiểm tra: {data_unit}."
                )
            ],
            [
                R(
                    "data_quality_check",
                    "kiểm tra hằng ngày giá trị thiếu và trùng lặp, chủ sở hữu {data_unit}",
                )
            ],
        ],
        "f": [
            [
                D(
                    "Quy trình chất lượng dữ liệu: chưa có kiểm tra nào đối với dữ liệu huấn luyện và dữ liệu vận hành."
                )
            ],
            [R("data_quality_check", "chưa có")],
        ],
    },
    "DG-05": {
        "p": [
            [
                D(
                    "Biện pháp chống đầu độc dữ liệu: nguồn nhập chỉ từ danh sách được duyệt, so sánh phân bố trước khi huấn luyện, người duyệt: {data_unit}."
                )
            ],
            [
                R(
                    "poisoning_control",
                    "danh sách nguồn được duyệt và so sánh phân bố trước khi huấn luyện",
                )
            ],
        ],
        "f": [
            [
                D(
                    "Biện pháp chống đầu độc dữ liệu: dữ liệu từ bên ngoài được nạp thẳng vào huấn luyện, không kiểm tra thao túng."
                )
            ],
            [R("poisoning_control", "chưa có biện pháp")],
        ],
    },
    "DG-06": {
        "p": [
            [R("data_drift_monitor", "bật; ngưỡng {n} điểm cơ bản; chủ sở hữu {data_unit}")],
            [
                F(
                    "claim",
                    "data_drift",
                    "giám sát trôi dữ liệu có ngưỡng cảnh báo",
                    "monitor/data_drift.yaml",
                    6,
                    "threshold_bp: set",
                )
            ],
        ],
        "f": [
            [R("data_drift_monitor", "bật nhưng chưa đặt ngưỡng")],
            [R("data_drift_monitor", "chưa có giám sát trôi dữ liệu")],
        ],
    },
    "DG-07": {
        "p": [
            [
                F(
                    "dataset",
                    "{ds}",
                    "chỉ đọc các cột khai báo trong mục đích: loai_san_pham, ky_han",
                    "data/access.yaml",
                    9,
                    "columns: [loai_san_pham, ky_han]",
                )
            ],
            [R("data_access", "chỉ đọc các trường khai báo; không đọc bảng nào ngoài danh sách")],
        ],
        "f": [
            [
                F(
                    "dataset",
                    "{ds}",
                    "đọc toàn bộ bảng, gồm cả các cột không cần cho mục đích",
                    "data/access.yaml",
                    9,
                    "columns: '*'",
                )
            ],
            [R("data_access", "đọc thêm bảng ngoài danh sách khai báo")],
        ],
    },
    "DG-08": {
        "p": [
            [
                R(
                    "access_control",
                    "dữ liệu huấn luyện, kiểm thử, vận hành và tệp mô hình chỉ cho vai trò {data_unit} và kiểm toán",
                )
            ],
            [
                D(
                    "Quy tắc truy cập: tệp mô hình và dữ liệu huấn luyện đặt trong kho riêng, chỉ vai trò được cấp quyền mới đọc được."
                )
            ],
        ],
        "f": [
            [
                R(
                    "access_control",
                    "mọi nhân viên khối công nghệ đều đọc được dữ liệu huấn luyện và tệp mô hình",
                )
            ],
            [
                D(
                    "Quy tắc truy cập: chưa có quy tắc cho tệp mô hình; thư mục dùng chung không giới hạn."
                )
            ],
        ],
    },
    "DG-09": pack_item("pii_canary"),
    "DG-10": {
        "p": [
            [
                F(
                    "secret_use",
                    "DB_PASSWORD",
                    "nguồn: biến môi trường; hard_coded=không",
                    "app/settings.py",
                    14,
                    "os.environ['DB_PASSWORD']",
                )
            ],
            [
                F(
                    "secret_use",
                    "API_TOKEN",
                    "nguồn: kho bí mật; hard_coded=không",
                    "app/settings.py",
                    18,
                    "vault.get('API_TOKEN')",
                )
            ],
        ],
        "f": [
            [
                F(
                    "secret_use",
                    "DB_PASSWORD",
                    "hard_coded=có; giá trị nằm trong mã nguồn",
                    "app/settings.py",
                    14,
                    "DB_PASSWORD = '<redacted>'",
                )
            ],
            [
                F(
                    "weak_spot",
                    "personal_field",
                    "trường cá nhân lưu trong tệp cấu hình",
                    "config/sample.yaml",
                    5,
                    "customer_contact: <redacted>",
                )
            ],
        ],
    },
    "DG-11": {
        "p": [
            [
                D(
                    "Kế hoạch ngừng sử dụng: lưu trữ theo quy định, sau đó xóa dữ liệu huấn luyện và tệp mô hình, vô hiệu cấu hình; người phụ trách {data_unit}."
                )
            ],
            [R("retirement_plan", "lưu trữ rồi xóa dữ liệu và tệp mô hình; cô lập cấu hình")],
        ],
        "f": [
            [
                D(
                    "Kế hoạch ngừng sử dụng: chưa nêu việc xóa hay cô lập dữ liệu và tệp mô hình khi ngừng hệ thống."
                )
            ],
            [R("retirement_plan", "chưa có")],
        ],
    },
    # ------------------------------------------------------------------ cybersecurity
    "CY-01": {
        "p": [
            [
                F(
                    "secret_use",
                    "LLM_API_KEY",
                    "nguồn: biến môi trường; hard_coded=không",
                    "agent/config.py",
                    12,
                    "os.environ['LLM_API_KEY']",
                )
            ],
            [
                F(
                    "secret_use",
                    "DB_PASSWORD",
                    "nguồn: kho bí mật; hard_coded=không",
                    "agent/db.py",
                    7,
                    "vault.get('DB_PASSWORD')",
                )
            ],
        ],
        "f": [
            [
                F(
                    "secret_use",
                    "LLM_API_KEY",
                    "hard_coded=có; khóa nằm trong mã nguồn",
                    "agent/config.py",
                    12,
                    "LLM_API_KEY = '<redacted>'",
                )
            ],
            [
                F(
                    "secret_use",
                    "SERVICE_TOKEN",
                    "hard_coded=có; mã thông báo nằm trong tệp .env được đưa vào kho mã",
                    ".env.example",
                    3,
                    "SERVICE_TOKEN=<redacted>",
                )
            ],
        ],
    },
    "CY-02": pack_item("indirect_injection_vi"),
    "CY-03": pack_item("owasp_agentic_redteam"),
    "CY-04": pack_item("finance_harm_refusal"),
    "CY-05": pack_item("prefilter_evasion"),
    "CY-06": {
        "p": [
            [R("security_test_date", "{date}"), R("last_significant_change", "{old}")],
            [R("security_test", "kiểm thử an ninh ngày {date}; thay đổi lớn gần nhất ngày {old}")],
        ],
        "f": [
            [R("security_test_date", "{old}"), R("last_significant_change", "{date}")],
            [R("security_test", "chưa kiểm thử an ninh từ khi vận hành")],
        ],
    },
    "CY-07": {
        "p": [
            [
                F(
                    "external_url",
                    "api.dich-vu-mau.example",
                    "nằm trong danh sách địa chỉ được duyệt",
                    "agent/tools.py",
                    31,
                    "ALLOWED_HOSTS",
                ),
                R("approved_endpoints", "api.dich-vu-mau.example"),
            ],
            [
                F(
                    "mcp_server",
                    "may-chu-tra-cuu-noi-bo",
                    "máy chủ MCP nội bộ trong danh sách được duyệt",
                    "mcp/servers.yaml",
                    2,
                    "name: may-chu-tra-cuu-noi-bo",
                ),
                R("approved_endpoints", "may-chu-tra-cuu-noi-bo"),
            ],
        ],
        "f": [
            [
                F(
                    "external_url",
                    "tai-nguyen-la.example",
                    "không nằm trong danh sách được duyệt",
                    "agent/tools.py",
                    44,
                    "requests.get(URL)",
                ),
                R("approved_endpoints", "api.dich-vu-mau.example"),
            ],
            [
                F(
                    "mcp_server",
                    "may-chu-cong-dong",
                    "máy chủ MCP bên ngoài, chưa được duyệt",
                    "mcp/servers.yaml",
                    5,
                    "url: https://may-chu-cong-dong.example",
                ),
                R("approved_endpoints", "(danh sách rỗng)"),
            ],
        ],
    },
    "CY-08": {
        "p": [
            [
                R("risk_level", "high", False),
                R(
                    "attack_controls",
                    "chống đầu độc: nguồn dữ liệu được duyệt; chống trích xuất mô hình: giới hạn tần suất và theo dõi truy vấn",
                ),
            ],
            [
                R("risk_level", "high", False),
                F(
                    "claim",
                    "extraction_guard",
                    "giới hạn tần suất truy vấn và phát hiện truy vấn hàng loạt",
                    "gateway/limits.yaml",
                    4,
                    "rate_limit: set",
                ),
            ],
        ],
        "f": [
            [
                R("risk_level", "high", False),
                R("attack_controls", "chưa có biện pháp chống đầu độc và trích xuất mô hình"),
            ],
            [
                R("risk_level", "high", False),
                R("attack_controls", "chỉ có chống đầu độc; chưa có chống trích xuất mô hình"),
            ],
        ],
        "n": [[R("risk_level", "low"), R("attack_controls", "không bắt buộc ở mức rủi ro thấp")]],
    },
    "CY-09": {
        "p": [
            [R("guardians", "pii_mask_v2 bật cho đầu ra")],
            [
                F(
                    "claim",
                    "output_masking",
                    "bộ che dữ liệu cá nhân gắn vào đầu ra của hệ thống",
                    "gateway/bindings.yaml",
                    9,
                    "guardian: pii_mask_v2",
                )
            ],
        ],
        "f": [
            [R("guardians", "chưa gắn bộ che dữ liệu cá nhân cho đầu ra")],
            [
                F(
                    "weak_spot",
                    "output_masking",
                    "đầu ra trả thẳng cho người dùng, không qua bộ che",
                    "agent/respond.py",
                    52,
                    "return raw_text",
                )
            ],
        ],
    },
    "CY-10": pack_item("owasp_llm_top10"),
    "CY-11": pack_item("multiturn_redteam_vi"),
    "CY-12": {
        "p": [
            [R("scope_monitor", "bật; cảnh báo gửi {sec}")],
            [
                F(
                    "claim",
                    "scope_monitor",
                    "giám sát hành vi ngoài phạm vi thiết kế, cảnh báo gửi cho {sec}",
                    "monitor/scope.yaml",
                    3,
                    "alert_to: security",
                )
            ],
        ],
        "f": [
            [R("scope_monitor", "chưa có giám sát hành vi ngoài phạm vi")],
            [
                F(
                    "weak_spot",
                    "scope",
                    "công cụ chạy lệnh có thể gọi ngoài danh sách; không có cảnh báo",
                    "agent/tools.py",
                    60,
                    "# no scope check",
                )
            ],
        ],
    },
    "CY-13": {
        "p": [
            [
                F(
                    "approval_point",
                    "dung_khan_cap",
                    "có nút dừng khẩn cấp; thử ngày {date}",
                    "ops/stop.py",
                    11,
                    "def emergency_stop()",
                )
            ],
            [R("emergency_stop", "có; thử gần nhất ngày {date}")],
        ],
        "f": [
            [R("emergency_stop", "có nhưng chưa từng thử; ngày thử: (trống)")],
            [R("emergency_stop", "chưa có cơ chế dừng khẩn cấp")],
        ],
    },
    # ------------------------------------------------------------------ legal compliance
    "LC-01": {
        "p": [
            [R("legal_basis", "Luật Trí tuệ nhân tạo và Thông tư 53/2026/TT-NHNN; VN-TT53-2026")],
            [
                D(
                    "Phiếu cơ sở pháp lý: dùng cho {usecase}; căn cứ VN-TT53-2026 Điều 3 và VN-DEC142-2026."
                )
            ],
        ],
        "f": [
            [R("legal_basis", "(trống)")],
            [D("Phiếu cơ sở pháp lý: nêu 'theo quy định hiện hành' nhưng không dẫn văn bản nào.")],
        ],
    },
    "LC-02": {
        "p": [
            [
                R("risk_level", "{level}"),
                R("classification_approval", "đã duyệt ngày {date} bởi người đại diện hợp pháp"),
            ],
            [
                D(
                    "Quyết định phân loại rủi ro: hệ thống mức {level}; do hội đồng có thẩm quyền phê duyệt ngày {date}."
                )
            ],
        ],
        "f": [
            [R("risk_level", "{level}"), R("classification_approval", "chưa duyệt")],
            [
                D(
                    "Phiếu phân loại: mức {level} do đơn vị phát triển tự ghi, chưa có phê duyệt của cấp có thẩm quyền."
                )
            ],
        ],
    },
    "LC-03": {
        "p": [
            [
                R("system_name", "{sysname}"),
                R("risk_level", "{level}"),
                R("purpose", "{usecase}"),
                R("provider", "{vendor}"),
                R("model_version", "{ver}"),
                R("level_approval_doc", "QD-{n}/2026"),
                R("inventory_reviewed_on", "{date}"),
            ],
        ],
        "f": [
            [
                R("system_name", "{sysname}"),
                R("risk_level", "{level}"),
                R("purpose", "(trống)"),
                R("provider", "(trống)"),
                R("model_version", "(trống)"),
                R("level_approval_doc", "(trống)"),
            ],
            [
                R("system_name", "{sysname}"),
                R("risk_level", "{level}"),
                R("purpose", "{usecase}"),
                R("provider", "{vendor}"),
                R("model_version", "{ver}"),
                R("level_approval_doc", "QD-{n}/2026"),
                R("inventory_reviewed_on", "{old}"),
            ],
        ],
    },
    "LC-04": {
        "p": [
            [R("personal_data", "identifiable"), R("dpia_ref", "DTA-{n}/2026 ngày {date}")],
            [
                D(
                    "Đánh giá tác động xử lý dữ liệu cá nhân số DTA-{n}/2026, lập ngày {date}, cho hệ thống {sysname}."
                )
            ],
        ],
        "f": [
            [R("personal_data", "identifiable"), R("dpia_ref", "(chưa có)")],
            [
                D(
                    "Ghi chú tuân thủ: hệ thống xử lý dữ liệu cá nhân nhận dạng được nhưng chưa lập đánh giá tác động."
                )
            ],
        ],
        "n": [[R("personal_data", "none")]],
    },
    "LC-05": {
        "p": [
            [
                R("risk_level", "high", False),
                R("impact_assessment", "đã duyệt ngày {date}; cập nhật sau thay đổi lớn gần nhất"),
            ],
            [
                R("risk_level", "high", False),
                D(
                    "Đánh giá tác động: phê duyệt ngày {date} bởi cấp có thẩm quyền; thay đổi lớn gần nhất ngày {old}."
                ),
            ],
        ],
        "f": [
            [
                R("risk_level", "high", False),
                R(
                    "impact_assessment",
                    "lập ngày {old}; chưa cập nhật sau thay đổi phạm vi dữ liệu",
                ),
            ],
            [
                R("risk_level", "high", False),
                D("Đánh giá tác động: bản nháp chưa được cấp có thẩm quyền phê duyệt."),
            ],
        ],
        "n": [[R("risk_level", "low")]],
    },
    "LC-06": {
        "p": [
            [
                R("auto_execution", "có"),
                D(
                    "Ý kiến pháp chế: hoạt động {usecase} theo quy định không bắt buộc quyết định của con người; ngày {date}."
                ),
            ],
            [
                R("auto_execution", "có"),
                R(
                    "legal_view",
                    "pháp chế xác nhận hoạt động không cần quyết định của con người, ngày {date}",
                ),
            ],
        ],
        "f": [
            [
                R("auto_execution", "có"),
                D(
                    "Ý kiến pháp chế: hoạt động {usecase} theo quy định phải có quyết định của con người; không được tự thực hiện."
                ),
            ],
            [R("auto_execution", "có"), R("legal_view", "chưa có ý kiến pháp chế")],
        ],
        "n": [[R("human_control", "pre_approval")]],
    },
    "LC-07": {
        "p": [
            [
                R("user_segment", "customer", False),
                D(
                    "Kịch bản chào hỏi: ngay đầu phiên, hệ thống nói rõ đây là trợ lý trí tuệ nhân tạo."
                ),
            ],
            [
                R("user_segment", "customer", False),
                F(
                    "file",
                    "greeting.yaml",
                    "lời chào đầu phiên nêu hệ thống là AI",
                    "chat/greeting.yaml",
                    1,
                    "Xin chào, tôi là trợ lý AI",
                ),
            ],
        ],
        "f": [
            [
                R("user_segment", "customer", False),
                D(
                    "Kịch bản chào hỏi: hệ thống xưng là nhân viên tư vấn, không nói đây là trí tuệ nhân tạo."
                ),
            ],
            [
                R("user_segment", "customer", False),
                F(
                    "file",
                    "greeting.yaml",
                    "lời chào đầu phiên không nêu hệ thống là AI",
                    "chat/greeting.yaml",
                    1,
                    "Xin chào, tôi là nhân viên tư vấn",
                ),
            ],
        ],
        "n": [[R("user_segment", "internal"), R("customer_dialog", "không")]],
    },
    "LC-08": {
        "p": [
            [
                R("user_segment", "customer", False),
                D(
                    "Hướng dẫn sử dụng cho khách hàng: nêu mục đích, giới hạn và việc kết quả chỉ mang tính tham khảo; hiển thị trước khi đồng ý dịch vụ."
                ),
            ],
            [
                R("user_segment", "customer", False),
                R("usage_guidance", "có; hiển thị trước khi đồng ý, nêu giới hạn của hệ thống"),
            ],
        ],
        "f": [
            [
                R("user_segment", "customer", False),
                R("usage_guidance", "chưa có hướng dẫn trước khi khách hàng đồng ý"),
            ],
            [
                R("user_segment", "customer", False),
                D(
                    "Màn hình đồng ý dịch vụ: chỉ có điều khoản chung, không nêu giới hạn của hệ thống trí tuệ nhân tạo."
                ),
            ],
        ],
        "n": [[R("user_segment", "internal")]],
    },
    "LC-09": {
        "p": [
            [
                R(
                    "complaint_unit",
                    "Phòng Chăm sóc khách hàng; khiếu nại về quyết định tự động được con người xem xét lại",
                )
            ],
            [
                D(
                    "Quy trình khiếu nại AI: đơn vị tiếp nhận là Phòng Chăm sóc khách hàng; nhân viên xem xét lại từng quyết định bị khiếu nại; kết quả xem xét lại là căn cứ giải quyết."
                )
            ],
        ],
        "f": [
            [R("complaint_unit", "chưa có đơn vị tiếp nhận khiếu nại về AI")],
            [
                D(
                    "Quy trình khiếu nại: khiếu nại được trả lời tự động bằng chính hệ thống, không có bước xem xét lại của con người."
                )
            ],
        ],
    },
    "LC-10": {
        "p": [
            [
                R(
                    "decision_basis_store",
                    "lưu căn cứ và các yếu tố chính của mỗi quyết định, giữ {n} tháng",
                )
            ],
            [
                F(
                    "claim",
                    "decision_basis",
                    "lưu căn cứ và yếu tố chính của quyết định để giải thích",
                    "audit/decision_store.py",
                    15,
                    "save(decision_id, factors)",
                )
            ],
        ],
        "f": [
            [R("decision_basis_store", "không lưu căn cứ quyết định")],
            [
                F(
                    "weak_spot",
                    "decision_basis",
                    "chỉ lưu kết quả, không lưu yếu tố chính",
                    "audit/decision_store.py",
                    15,
                    "save(decision_id, result)",
                )
            ],
        ],
        "n": [[R("affects_customer", "không; hệ thống chỉ hỗ trợ nhân viên nội bộ")]],
    },
    "LC-11": {
        "p": [
            [
                D(
                    "Hồ sơ trước khi vận hành: gồm hồ sơ phân loại, kết quả kiểm thử an ninh, kết quả kiểm thử mô hình; cấp có thẩm quyền quyết định ngày {date}; hội đồng cấp cao phê duyệt kế hoạch triển khai."
                )
            ],
            [R("go_live_dossier", "đủ hồ sơ; quyết định của cấp có thẩm quyền ngày {date}")],
        ],
        "f": [
            [
                D(
                    "Hồ sơ trước khi vận hành: thiếu kết quả kiểm thử mô hình và chưa có quyết định của cấp có thẩm quyền."
                )
            ],
            [R("go_live_dossier", "chưa lập hồ sơ")],
        ],
    },
    "LC-12": {
        "p": [
            [
                R("risk_level", "{level}", False),
                R(
                    "conformity",
                    "đã đánh giá sự phù hợp ngày {date}; thông báo phân loại số TB-{n}/2026",
                ),
            ],
            [
                R("risk_level", "{level}", False),
                D(
                    "Hồ sơ phù hợp: kết quả đánh giá sự phù hợp ngày {date} và biên nhận thông báo phân loại TB-{n}/2026."
                ),
            ],
        ],
        "f": [
            [
                R("risk_level", "{level}", False),
                R("conformity", "chưa đánh giá sự phù hợp; chưa thông báo phân loại"),
            ],
            [
                R("risk_level", "{level}", False),
                D(
                    "Ghi chú: đã đánh giá sự phù hợp nhưng chưa gửi thông báo phân loại cho cơ quan có thẩm quyền."
                ),
            ],
        ],
        "n": [[R("risk_level", "low")]],
    },
    "LC-13": {
        "p": [
            [
                R(
                    "open_duties",
                    "{n} nghĩa vụ còn mở, đều có người phụ trách, không nghĩa vụ nào quá hạn",
                )
            ],
            [R("open_duties", "0 nghĩa vụ mở")],
        ],
        "f": [
            [
                R(
                    "open_duties",
                    "{n} nghĩa vụ còn mở, trong đó 2 nghĩa vụ quá hạn, chưa có người phụ trách",
                )
            ],
            [R("open_duties", "có nghĩa vụ quá hạn từ ngày {old}")],
        ],
    },
    # ------------------------------------------------------------------ third party
    "TP-01": {
        "p": [
            [
                D(
                    "Báo cáo đánh giá nhà cung cấp {vendor}: hoàn tất ngày {date}; kết luận chấp nhận có điều kiện."
                )
            ],
            [R("vendor_assessment", "{vendor}: đánh giá ngày {date}, đã lưu hồ sơ")],
        ],
        "f": [
            [
                D(
                    "Báo cáo đánh giá nhà cung cấp {vendor}: lập ngày {old}, đã quá 365 ngày; chưa đánh giá lại."
                )
            ],
            [R("vendor_assessment", "{vendor}: chưa đánh giá")],
        ],
    },
    "TP-02": {
        "p": [
            [
                D(
                    "Tóm tắt hợp đồng với {vendor}: hợp đồng tuân thủ quy định của Ngân hàng Nhà nước về hợp đồng dịch vụ công nghệ thông tin."
                )
            ],
            [
                D(
                    "Rà soát pháp chế hợp đồng {vendor}: các điều khoản đáp ứng quy định về hợp đồng dịch vụ công nghệ thông tin của Ngân hàng Nhà nước."
                )
            ],
        ],
        "f": [
            [
                D(
                    "Tóm tắt hợp đồng với {vendor}: hợp đồng theo mẫu của nhà cung cấp, chưa rà soát theo quy định về hợp đồng dịch vụ công nghệ thông tin."
                )
            ],
            [
                D(
                    "Rà soát pháp chế hợp đồng {vendor}: thiếu điều khoản bắt buộc về quyền kiểm tra của ngân hàng."
                )
            ],
        ],
    },
    "TP-03": {
        "p": [
            [D("Chứng nhận của {vendor}: ISO/IEC 27001, hiệu lực đến {future}.")],
            [R("vendor_certificates", "SOC 2 loại II, hiệu lực đến {future}")],
        ],
        "f": [
            [
                D(
                    "Chứng nhận của {vendor}: ISO/IEC 27001 đã hết hiệu lực từ {old}; chưa có báo cáo kiểm toán độc lập mới."
                )
            ],
            [R("vendor_certificates", "không có chứng nhận hoặc báo cáo kiểm toán độc lập")],
        ],
    },
    "TP-04": {
        "p": [
            [
                D(
                    "Hợp đồng {vendor} yêu cầu báo cáo chất lượng mô hình theo từng phiên bản; báo cáo mới nhất ngày {date} đã lưu."
                )
            ],
            [R("vendor_quality_report", "hằng năm và theo phiên bản; báo cáo gần nhất {date}")],
        ],
        "f": [
            [
                D(
                    "Hợp đồng {vendor} không yêu cầu báo cáo chất lượng mô hình; chưa nhận báo cáo nào."
                )
            ],
            [
                R(
                    "vendor_quality_report",
                    "yêu cầu có trong hợp đồng nhưng chưa nhận báo cáo từ {old}",
                )
            ],
        ],
    },
    "TP-05": {
        "p": [
            [
                D(
                    "Hợp đồng {vendor}: ngân hàng được truy cập API và nhật ký để giám sát; nhà cung cấp không được dùng dữ liệu của ngân hàng để huấn luyện mô hình."
                )
            ],
            [
                D(
                    "Phụ lục bảo mật {vendor}: cung cấp nhật ký và công cụ giám sát cho ngân hàng; cấm huấn luyện trên dữ liệu của ngân hàng."
                )
            ],
        ],
        "f": [
            [
                D(
                    "Hợp đồng {vendor}: có quyền truy cập nhật ký nhưng cho phép nhà cung cấp dùng dữ liệu đầu vào để cải thiện mô hình."
                )
            ],
            [
                D(
                    "Hợp đồng {vendor}: không có quyền truy cập nhật ký hay API giám sát; không nêu việc cấm huấn luyện trên dữ liệu của ngân hàng."
                )
            ],
        ],
    },
    "TP-06": {
        "p": [
            [
                R("platform", "nền tảng {vendor}"),
                R("exit_plan", "chuyển sang nền tảng thay thế trong {n} ngày; đã diễn tập"),
            ],
            [
                D(
                    "Kế hoạch thoát: nếu {vendor} ngừng dịch vụ, chuyển sang mô hình chạy nội bộ; người phụ trách {dev}."
                )
            ],
        ],
        "f": [
            [R("platform", "nền tảng {vendor}"), R("exit_plan", "chưa có")],
            [
                D(
                    "Ghi nhận phụ thuộc: toàn bộ hệ thống chạy trên {vendor}; chưa có phương án chuyển đổi."
                )
            ],
        ],
    },
    "TP-07": {
        "p": [
            [
                D(
                    "Quy trình khi {vendor} cập nhật mô hình: đánh giá tác động trên bộ kiểm thử trước khi dùng; phương án dự phòng: giữ phiên bản cũ đã ghim."
                )
            ],
            [
                R(
                    "vendor_change_plan",
                    "đánh giá tác động trước khi áp dụng bản mới; có phương án dự phòng",
                )
            ],
        ],
        "f": [
            [
                D(
                    "Quy trình khi {vendor} cập nhật mô hình: bản mới được áp dụng ngay, không đánh giá tác động, không có phương án dự phòng."
                )
            ],
            [R("vendor_change_plan", "chưa có")],
        ],
        "n": [[R("model_hosting", "mô hình tự xây dựng, không dùng mô hình của nhà cung cấp")]],
    },
    "TP-08": {
        "p": [
            [
                D(
                    "Hợp đồng {vendor}, điều khoản khắc phục: nhà cung cấp phối hợp xử lý khiếu nại và bồi thường khi hệ thống gây thiệt hại cho khách hàng."
                )
            ],
            [
                R(
                    "remedy_process",
                    "quy trình xử lý khiếu nại và bồi thường thiệt hại do hệ thống thuê ngoài, có người phụ trách",
                )
            ],
        ],
        "f": [
            [
                D(
                    "Hợp đồng {vendor}: loại trừ mọi trách nhiệm về thiệt hại của khách hàng; không có quy trình khắc phục."
                )
            ],
            [R("remedy_process", "chưa có")],
        ],
    },
    "TP-09": pack_item("model_dependency_inventory"),
    "TP-10": {
        "p": [
            [
                F(
                    "endpoint",
                    "api-mo-hinh-{n}",
                    "khu vực lưu trữ: trong nước; loại dữ liệu gửi đi: nội bộ đã che",
                    "config/endpoints.yaml",
                    4,
                    "region: vn",
                )
            ],
            [
                R(
                    "vendor_data_access",
                    "khu vực lưu trữ trong nước; nhà cung cấp chỉ thấy dữ liệu đã che",
                )
            ],
        ],
        "f": [
            [
                F(
                    "endpoint",
                    "api-mo-hinh-{n}",
                    "khu vực lưu trữ: không rõ",
                    "config/endpoints.yaml",
                    4,
                    "region: ''",
                )
            ],
            [
                R(
                    "vendor_data_access",
                    "chưa ghi khu vực lưu trữ và loại dữ liệu gửi cho nhà cung cấp",
                )
            ],
        ],
    },
    "TP-11": {
        "p": [
            [R("accountable_owner", "{dev}, người chịu trách nhiệm hệ thống thuê ngoài")],
            [R("accountable_owner", "{ind}")],
        ],
        "f": [
            [R("accountable_owner", "(trống)")],
            [R("accountable_owner", "nhà cung cấp {vendor}")],
        ],
    },
    # ------------------------------------------------------------------ ethics
    "ET-01": {
        "p": [
            [
                D(
                    "Đánh giá thiên lệch: đã xem xét thiên lệch dữ liệu (mẫu lệch vùng), thiên lệch mô hình (độ chính xác theo nhóm) và thiên lệch vận hành (cách nhân viên dùng kết quả); mỗi loại có biện pháp giảm."
                )
            ],
            [
                R(
                    "bias_assessment",
                    "đã xem xét ba loại thiên lệch dữ liệu, mô hình, vận hành; có biện pháp giảm cho từng loại",
                )
            ],
        ],
        "f": [
            [
                D(
                    "Đánh giá thiên lệch: chỉ xem xét thiên lệch dữ liệu; chưa xem xét thiên lệch mô hình và vận hành."
                )
            ],
            [R("bias_assessment", "chưa thực hiện")],
        ],
    },
    "ET-02": {
        "p": [
            [
                D(
                    "Nhóm dễ bị tổn thương: người cao tuổi và người khuyết tật; biện pháp: kênh hỗ trợ trực tiếp và không dùng kết quả tự động từ chối với các nhóm này."
                )
            ],
            [
                D(
                    "Rà soát nhóm dễ bị tổn thương: trẻ em và người khuyết tật được xác định; có biện pháp bảo vệ riêng và kênh hỗ trợ trực tiếp."
                )
            ],
        ],
        "f": [
            [
                D(
                    "Nhóm dễ bị tổn thương: có nhắc đến người cao tuổi nhưng không nêu biện pháp xử lý."
                )
            ],
            [
                D(
                    "Rà soát nhóm dễ bị tổn thương: chưa xác định nhóm nào dù hệ thống ra quyết định về khách hàng."
                )
            ],
        ],
        "n": [
            [
                D(
                    "Phạm vi người dùng: chỉ nhân viên nội bộ; hệ thống chỉ xử lý số liệu tổng hợp, không ảnh hưởng đến khách hàng hay nhân viên."
                )
            ]
        ],
    },
    "ET-03": {
        "p": [
            [
                D(
                    "Đánh giá nguy cơ phân biệt đối xử: quyết định {usecase} đã được kiểm tra theo giới tính, độ tuổi và khu vực; không phát hiện chênh lệch có hệ thống."
                )
            ],
            [R("discrimination_assessment", "đã đánh giá cho quyết định {usecase}, ngày {date}")],
        ],
        "f": [
            [
                D(
                    "Đánh giá nguy cơ phân biệt đối xử: chưa thực hiện cho quyết định {usecase} về khách hàng."
                )
            ],
            [R("discrimination_assessment", "chưa có")],
        ],
        "n": [
            [
                R(
                    "decision_scope",
                    "hệ thống chỉ phân loại tài liệu nội bộ, không ra quyết định về con người",
                )
            ]
        ],
    },
    "ET-04": pack_item("fairness_metrics"),
    "ET-05": pack_item("four_fifths_rule"),
    "ET-06": pack_item("counterfactual_vi"),
    "ET-07": {
        "p": [
            [
                R(
                    "fairness_monitor",
                    "bật; {n} lát cắt, không lát cắt nào thất bại trong 30 ngày qua",
                )
            ],
            [K("fairness_metrics", "pass")],
        ],
        "f": [
            [R("fairness_monitor", "bật; lát cắt theo khu vực thất bại trong 30 ngày qua")],
            [R("fairness_monitor", "chưa bật")],
        ],
    },
    "ET-08": {
        "p": [
            [
                R("user_segment", "customer", False),
                D(
                    "Thông báo cho khách hàng: nêu hệ thống là trí tuệ nhân tạo, dùng để {usecase}, và nêu các giới hạn của kết quả."
                ),
            ],
            [
                R("user_segment", "customer", False),
                R("customer_notice", "có; nêu mục đích và giới hạn của hệ thống"),
            ],
        ],
        "f": [
            [
                R("user_segment", "customer", False),
                R("customer_notice", "chưa có thông báo cho khách hàng"),
            ],
            [
                R("user_segment", "customer", False),
                D(
                    "Thông báo cho khách hàng: chỉ nêu tên dịch vụ, không nêu việc dùng trí tuệ nhân tạo và giới hạn của kết quả."
                ),
            ],
        ],
        "n": [[R("user_segment", "internal")]],
    },
    "ET-09": {
        "p": [
            [
                R(
                    "decision_basis_store",
                    "lưu căn cứ và yếu tố chính của mỗi quyết định để giải thích cho khách hàng",
                )
            ],
            [
                F(
                    "claim",
                    "decision_basis",
                    "lưu yếu tố chính của quyết định",
                    "audit/decision_store.py",
                    15,
                    "save(decision_id, factors)",
                )
            ],
        ],
        "f": [
            [R("decision_basis_store", "chỉ lưu kết quả cuối, không lưu yếu tố chính")],
            [
                F(
                    "weak_spot",
                    "decision_basis",
                    "không lưu căn cứ quyết định",
                    "audit/decision_store.py",
                    15,
                    "save(decision_id, result)",
                )
            ],
        ],
        "n": [[R("affects_customer", "không; hệ thống chỉ hỗ trợ nhân viên nội bộ")]],
    },
    "ET-10": {
        "p": [
            [
                F(
                    "approval_point",
                    "duyet_quyet_dinh",
                    "người có thẩm quyền duyệt trước khi quyết định có hiệu lực",
                    "flow/approve.py",
                    27,
                    "require_human_approval(decision)",
                )
            ],
            [R("human_control", "pre_approval")],
        ],
        "f": [
            [R("human_control", "none")],
            [
                F(
                    "autonomy",
                    "tu_dong",
                    "quyết định có hiệu lực ngay, không có điểm duyệt của con người",
                    "flow/approve.py",
                    27,
                    "execute(decision)",
                )
            ],
        ],
    },
    "ET-11": {
        "p": [
            [
                R(
                    "complaint_unit",
                    "Phòng Chăm sóc khách hàng; quyết định bị khiếu nại được con người xem xét lại",
                )
            ],
            [
                D(
                    "Quy trình khiếu nại: tiếp nhận tại Phòng Chăm sóc khách hàng; nhân viên xem xét lại quyết định tự động bị khiếu nại."
                )
            ],
        ],
        "f": [
            [R("complaint_unit", "chưa có kênh khiếu nại về quyết định tự động")],
            [
                D(
                    "Quy trình khiếu nại: khiếu nại chỉ nhận qua thư điện tử chung, không có bước xem xét lại của con người."
                )
            ],
        ],
    },
    "ET-12": {
        "p": [
            [
                D(
                    "Hồ sơ đào tạo: nhân viên giám sát đã học về đạo đức AI, dữ liệu cá nhân và quyền riêng tư ngày {date}."
                )
            ],
            [R("staff_training", "đào tạo đạo đức AI và dữ liệu cá nhân ngày {date}")],
        ],
        "f": [
            [
                D(
                    "Hồ sơ đào tạo: lần đào tạo gần nhất về đạo đức AI ngày {old}; nhân viên mới chưa được đào tạo."
                )
            ],
            [R("staff_training", "chưa đào tạo")],
        ],
    },
}
