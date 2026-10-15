"""The product questionnaire (``product.yaml``) of the compliance advisor (WP14).

One table (``FIELDS``) drives the validator, the JSON Schema (``product.schema.json``) and the
commented template (``product.example.yaml``). Blank = unknown = an open question. ``[]`` is a
real answer ("none"), not a blank. Money is an integer number of VND (no floats, no booleans).

    python -m supervisor.advisory.compliance.questionnaire --write   # refresh both files

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from supervisor.advisory.compliance.model import (
    AGENT_CLASSES,
    AUTONOMY,
    CUSTOMER_TYPES,
    DATA_CLASSES,
    MODEL_HOSTING,
    ROLES,
    Question,
)
from supervisor.regkb.loader import REPO_ROOT

__all__ = [
    "CONTROL_FIELDS",
    "FIELDS",
    "QUESTIONS",
    "QuestionnaireError",
    "load_answers_file",
    "make_question",
    "questionnaire_schema",
    "schema_json",
    "template_yaml",
    "validate_answers",
]

PACKAGE_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = PACKAGE_DIR / "product.schema.json"
EXAMPLE_FILE = PACKAGE_DIR / "product.example.yaml"
MAX_FILE_BYTES = 1_000_000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class QuestionnaireError(ValueError):
    """The answers are invalid. ``problems`` lists every problem (not only the first)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class QField:
    name: str
    type: str  # string | text | bool | int | date | enum | enum_list
    enum: tuple[str, ...]
    help_en: str
    help_vi: str
    maps_to: str  # ProductProfile field (or controls.<name>)


_TX_LINES_EN = (
    "Circular 53/2026 Art. 4(2)(a) calls a payment high value when an individual customer pays "
    "more than 10,000,000 VND per transaction or more than 20,000,000 VND per day, or an "
    "organisation pays more than 50,000,000 VND per transaction or more than 100,000,000 VND "
    "per day."
)
_TX_LINES_VI = (
    "Thông tư 53/2026 Điều 4(2)(a): giao dịch giá trị cao là khách hàng cá nhân trên "
    "10.000.000 đồng một giao dịch hoặc trên 20.000.000 đồng một ngày; tổ chức trên "
    "50.000.000 đồng một giao dịch hoặc trên 100.000.000 đồng một ngày."
)

FIELDS: tuple[QField, ...] = (
    QField(
        "product_id",
        "string",
        (),
        "Required. Short stable id of the product (letters, digits, dot, dash, underscore).",
        "Bắt buộc. Mã ngắn, ổn định của sản phẩm (chữ, số, dấu chấm, gạch).",
        "product_id",
    ),
    QField(
        "name",
        "string",
        (),
        "Required. Product name.",
        "Bắt buộc. Tên sản phẩm.",
        "name",
    ),
    QField(
        "version",
        "string",
        (),
        "Product version, for example 1.0.0.",
        "Phiên bản sản phẩm, ví dụ 1.0.0.",
        "version",
    ),
    QField(
        "owner_team",
        "string",
        (),
        "Team that owns the product.",
        "Đơn vị sở hữu sản phẩm.",
        "owner_team",
    ),
    QField(
        "purpose",
        "text",
        (),
        "What the product does, in one or two sentences.",
        "Sản phẩm làm gì, trong một hai câu.",
        "purpose",
    ),
    QField(
        "agent_classes",
        "enum_list",
        AGENT_CLASSES,
        "All classes that fit the product. payment: it moves money. credit_decision: it "
        "scores or decides credit. customer_facing: it talks to customers. internal_tool: "
        "staff use only. Blank = unknown; [] = none.",
        "Mọi loại phù hợp. payment: chuyển tiền. credit_decision: chấm điểm hoặc quyết định "
        "tín dụng. customer_facing: giao tiếp với khách hàng. internal_tool: chỉ nhân viên "
        "dùng. Để trống = chưa biết; [] = không có.",
        "agent_classes",
    ),
    QField(
        "data_classes",
        "enum_list",
        DATA_CLASSES,
        "All data classes the product handles. Blank = unknown; [] = none.",
        "Mọi loại dữ liệu sản phẩm xử lý. Để trống = chưa biết; [] = không có.",
        "data_classes",
    ),
    QField(
        "autonomy",
        "enum",
        AUTONOMY,
        "advisory: only suggests. acts_with_approval: acts after a human approves. "
        "acts_autonomously: acts without a human step.",
        "advisory: chỉ gợi ý. acts_with_approval: hành động sau khi người duyệt. "
        "acts_autonomously: tự hành động, không có bước người duyệt.",
        "autonomy",
    ),
    QField(
        "cross_border",
        "bool",
        (),
        "true if data or the model call leaves Vietnam.",
        "true nếu dữ liệu hoặc lệnh gọi mô hình ra khỏi Việt Nam.",
        "cross_border",
    ),
    QField(
        "model_hosting",
        "enum",
        MODEL_HOSTING,
        "Where the AI model runs.",
        "Nơi mô hình AI chạy.",
        "model_hosting",
    ),
    QField(
        "roles",
        "enum_list",
        ROLES,
        "deployer: the bank runs it. provider: the bank also builds or sells it. Blank = unknown.",
        "deployer: ngân hàng vận hành. provider: ngân hàng cũng phát triển hoặc cung cấp. "
        "Để trống = chưa biết.",
        "roles",
    ),
    QField(
        "customer_facing",
        "bool",
        (),
        "true if customers use the product directly.",
        "true nếu khách hàng dùng trực tiếp sản phẩm.",
        "customer_facing",
    ),
    QField(
        "decisions_affecting_customers",
        "bool",
        (),
        "true if the product makes or shapes decisions that affect customers.",
        "true nếu sản phẩm đưa ra hoặc định hướng quyết định ảnh hưởng đến khách hàng.",
        "decisions_affecting_customers",
    ),
    QField(
        "customer_types",
        "enum_list",
        CUSTOMER_TYPES,
        "Who the customers are: individual, organisation, or both. The Decision 33 and "
        "Circular 53 money lines differ by type. Blank = unknown.",
        "Khách hàng là ai: individual (cá nhân), organisation (tổ chức) hoặc cả hai. Ngưỡng "
        "tiền theo Quyết định 33 và Thông tư 53 khác nhau theo loại. Để trống = chưa biết.",
        "customer_types",
    ),
    QField(
        "executes_payments",
        "bool",
        (),
        "true if the product itself creates and executes payments.",
        "true nếu sản phẩm tự tạo và thực hiện giao dịch thanh toán.",
        "executes_payments",
    ),
    QField(
        "human_approval_before_execution",
        "bool",
        (),
        "true if a human inspects or approves each payment before it runs. A pause after the "
        "payment ran does not count.",
        "true nếu có người kiểm tra hoặc phê duyệt từng giao dịch trước khi thực hiện. Tạm "
        "dừng sau khi giao dịch đã chạy thì không tính.",
        "human_approval_before_execution",
    ),
    QField(
        "credit_decisions",
        "bool",
        (),
        "true if the product decides or records credit decisions (approve, reject, disburse).",
        "true nếu sản phẩm quyết định hoặc ghi nhận quyết định tín dụng (duyệt, từ chối, giải "
        "ngân).",
        "credit_decisions",
    ),
    QField(
        "independent_credit_approval",
        "bool",
        (),
        "true if a credit officer approves independently before the decision takes effect.",
        "true nếu cán bộ tín dụng phê duyệt độc lập trước khi quyết định có hiệu lực.",
        "independent_credit_approval",
    ),
    QField(
        "max_transaction_vnd",
        "int",
        (),
        "Largest single payment the product can execute, whole VND (integer). " + _TX_LINES_EN,
        "Giao dịch lớn nhất mà sản phẩm có thể thực hiện, đồng (số nguyên). " + _TX_LINES_VI,
        "max_transaction_vnd",
    ),
    QField(
        "max_daily_vnd",
        "int",
        (),
        "Largest total per customer per day, whole VND (integer). "
        + _TX_LINES_EN
        + " Art. 5(1)(g)(ii) caps a day at 100,000,000 VND for an individual and 500,000,000 "
        "VND for an organisation.",
        "Tổng lớn nhất mỗi khách hàng mỗi ngày, đồng (số nguyên). "
        + _TX_LINES_VI
        + " Điều 5(1)(g)(ii) giới hạn một ngày ở mức 100.000.000 đồng với cá nhân và "
        "500.000.000 đồng với tổ chức.",
        "max_daily_vnd",
    ),
    QField(
        "max_credit_vnd",
        "int",
        (),
        "Largest credit amount the product can process, whole VND (integer). Circular 53/2026 "
        "Art. 4(2)(b): credit of 50,000,000 VND or more is high value.",
        "Khoản tín dụng lớn nhất sản phẩm có thể xử lý, đồng (số nguyên). Thông tư 53/2026 "
        "Điều 4(2)(b): tín dụng từ 50.000.000 đồng trở lên là giá trị cao.",
        "max_credit_vnd",
    ),
    QField(
        "in_operation_since",
        "date",
        (),
        "Date the product went live (YYYY-MM-DD). It decides which transition date of "
        "Circular 53 Art. 24 and AI Law Art. 35 applies.",
        "Ngày sản phẩm đưa vào vận hành (YYYY-MM-DD). Ngày này quyết định mốc chuyển tiếp "
        "nào của Thông tư 53 Điều 24 và Luật AI Điều 35 áp dụng.",
        "in_operation_since",
    ),
)

CONTROL_FIELDS: tuple[QField, ...] = (
    QField(
        "supervised",
        "bool",
        (),
        "true if the product is registered with Supervisor (gateway, recorder, evidence chain).",
        "true nếu sản phẩm đã đăng ký với Supervisor (cổng, ghi nhận, chuỗi bằng chứng).",
        "controls.supervised",
    ),
    QField(
        "catalogue",
        "string_list",
        (),
        "Ids of Supervisor catalogue capabilities that are on (for example single_limit).",
        "Mã các năng lực trong danh mục Supervisor đang bật (ví dụ single_limit).",
        "controls.catalogue_on",
    ),
    QField(
        "rules",
        "rule_list",
        (),
        "Gate rules the product has: a list of {id, description}.",
        "Các quy tắc cổng của sản phẩm: danh sách {id, description}.",
        "controls.rules",
    ),
    QField(
        "policy_files",
        "string_list",
        (),
        "Policy YAML files (paths relative to this file) to read rule ids and limits from.",
        "Tệp chính sách YAML (đường dẫn tương đối so với tệp này) để đọc mã quy tắc và hạn mức.",
        "controls.policy_files",
    ),
    QField(
        "monitors",
        "enum_list",
        (),
        "Monitors that run for the product (names from regulations/schema/controls.yaml).",
        "Các bộ giám sát đang chạy cho sản phẩm (tên trong regulations/schema/controls.yaml).",
        "controls.monitors",
    ),
    QField(
        "evidence",
        "enum_list",
        (),
        "Evidence artefacts the product produces beyond the standard ones.",
        "Các bằng chứng sản phẩm tạo ra ngoài các bằng chứng chuẩn.",
        "controls.evidence",
    ),
)

_FIELD = {f.name: f for f in FIELDS}
_CONTROL_FIELD = {f.name: f for f in CONTROL_FIELDS}
_TEXT_LIMITS = {"string": 200, "text": 2000}

# One question per fact: (English, Vietnamese). The matrix, thresholds and Decision 33 reuse them.
QUESTIONS: dict[str, tuple[str, str]] = {
    "agent_classes": (
        "Which agent classes fit the product (payment, credit_decision, customer_facing, "
        "internal_tool)? Code shows only some of them.",
        "Sản phẩm thuộc những loại tác tử nào (payment, credit_decision, customer_facing, "
        "internal_tool)? Mã nguồn chỉ cho thấy một phần.",
    ),
    "data_classes": (
        "Which data classes does the product handle (personal, sensitive_personal, financial, "
        "biometric, core_data, important_data)?",
        "Sản phẩm xử lý những loại dữ liệu nào (personal, sensitive_personal, financial, "
        "biometric, core_data, important_data)?",
    ),
    "autonomy": (
        "How autonomous is the product (advisory, acts_with_approval, acts_autonomously)?",
        "Sản phẩm tự chủ đến mức nào (advisory, acts_with_approval, acts_autonomously)?",
    ),
    "cross_border": (
        "Does data or the model call leave Vietnam?",
        "Dữ liệu hoặc lệnh gọi mô hình có ra khỏi Việt Nam không?",
    ),
    "model_hosting": (
        "Where does the AI model run (on_prem, domestic_cloud, foreign_cloud)?",
        "Mô hình AI chạy ở đâu (on_prem, domestic_cloud, foreign_cloud)?",
    ),
    "roles": (
        "Is the bank only the deployer, or also the provider of this AI system?",
        "Ngân hàng chỉ là bên triển khai hay cũng là bên cung cấp hệ thống AI này?",
    ),
    "customer_facing": (
        "Do customers use the product directly?",
        "Khách hàng có dùng trực tiếp sản phẩm không?",
    ),
    "decisions_affecting_customers": (
        "Does the product make or shape decisions that affect customers?",
        "Sản phẩm có đưa ra hoặc định hướng quyết định ảnh hưởng đến khách hàng không?",
    ),
    "customer_types": (
        "Does the product serve individual customers, organisations, or both?",
        "Sản phẩm phục vụ khách hàng cá nhân, tổ chức, hay cả hai?",
    ),
    "executes_payments": (
        "Does the product itself create and execute payments?",
        "Sản phẩm có tự tạo và thực hiện giao dịch thanh toán không?",
    ),
    "human_approval_before_execution": (
        "Does a human inspect or approve each payment before it executes?",
        "Có người kiểm tra hoặc phê duyệt từng giao dịch trước khi thực hiện không?",
    ),
    "credit_decisions": (
        "Does the product decide or record credit decisions?",
        "Sản phẩm có quyết định hoặc ghi nhận quyết định tín dụng không?",
    ),
    "independent_credit_approval": (
        "Does a credit officer approve independently before a credit decision takes effect?",
        "Cán bộ tín dụng có phê duyệt độc lập trước khi quyết định tín dụng có hiệu lực không?",
    ),
    "max_transaction_vnd": (
        "What is the largest single payment the product can execute (whole VND)?",
        "Giao dịch lớn nhất sản phẩm có thể thực hiện là bao nhiêu (đồng)?",
    ),
    "max_daily_vnd": (
        "What is the largest total per customer per day the product can execute (whole VND)?",
        "Tổng lớn nhất mỗi khách hàng mỗi ngày sản phẩm có thể thực hiện là bao nhiêu (đồng)?",
    ),
    "max_credit_vnd": (
        "What is the largest credit amount the product can process (whole VND)?",
        "Khoản tín dụng lớn nhất sản phẩm có thể xử lý là bao nhiêu (đồng)?",
    ),
    "in_operation_since": (
        "On what date did the product go live?",
        "Sản phẩm đưa vào vận hành từ ngày nào?",
    ),
    "controls": (
        "Which Supervisor controls (catalogue, rules, monitors, evidence) does the product "
        "have? Nothing is known yet.",
        "Sản phẩm có những kiểm soát Supervisor nào (danh mục, quy tắc, giám sát, bằng chứng)? "
        "Hiện chưa có thông tin.",
    ),
    "limits": (
        "Which money limits are set for the product?",
        "Sản phẩm được đặt những hạn mức tiền nào?",
    ),
}


def make_question(fact: str, obligation_ids: tuple[str, ...] = (), why: str = "") -> Question:
    """The one Question for a fact (id ``Q-<fact>``), with the obligations it would decide."""
    en, vi = QUESTIONS.get(fact, (f"Please state {fact}.", f"Vui lòng cho biết {fact}."))
    return Question(
        id=f"Q-{fact}",
        fact=fact,
        text_en=en,
        text_vi=vi,
        obligation_ids=tuple(sorted(set(obligation_ids))),
        why=why,
    )


# ----------------------------------------------------------------------------- validation


def _controls_names() -> tuple[tuple[str, ...], tuple[str, ...]]:
    spec = yaml.safe_load(
        (REPO_ROOT / "regulations" / "schema" / "controls.yaml").read_text("utf-8")
    )
    return tuple(sorted(spec["monitors"])), tuple(sorted(spec["evidence"]))


def _catalogue_ids() -> tuple[str, ...]:
    from supervisor.catalogue import load_catalogue

    return tuple(load_catalogue().ids())


def _check_value(f: QField, value: Any, where: str, enum: tuple[str, ...], out: list[str]) -> Any:
    """Return the normalised value or ``None`` after adding problems to ``out``."""
    n = len(out)
    if f.type in ("string", "text"):
        if not isinstance(value, str) or not value.strip():
            out.append(f"{where}: must be a non-empty text")
        elif len(value) > _TEXT_LIMITS[f.type]:
            out.append(f"{where}: longer than {_TEXT_LIMITS[f.type]} characters")
        else:
            return value.strip()
    elif f.type == "bool":
        if type(value) is not bool:
            out.append(f"{where}: must be true or false")
        else:
            return value
    elif f.type == "int":
        if type(value) is not int:
            out.append(f"{where}: must be a whole number of VND (no decimals, no true/false)")
        elif value < 0:
            out.append(f"{where}: must not be negative")
        else:
            return value
    elif f.type == "date":
        if isinstance(value, dt.datetime):
            out.append(f"{where}: must be a date YYYY-MM-DD")
        elif isinstance(value, dt.date):
            return value.isoformat()
        elif isinstance(value, str):
            try:
                return dt.date.fromisoformat(value).isoformat()
            except ValueError:
                out.append(f"{where}: must be a date YYYY-MM-DD")
        else:
            out.append(f"{where}: must be a date YYYY-MM-DD")
    elif f.type == "enum":
        if value not in enum:
            out.append(f"{where}: must be one of {', '.join(enum)}")
        else:
            return value
    elif f.type in ("enum_list", "string_list"):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            out.append(f"{where}: must be a list of text values")
        else:
            bad = [v for v in value if enum and v not in enum]
            if bad:
                out.append(
                    f"{where}: unknown value {', '.join(map(repr, bad))}; use {', '.join(enum)}"
                )
            elif f.name == "policy_files" and any(
                Path(v).is_absolute() or ".." in Path(v).parts for v in value
            ):
                out.append(f"{where}: paths must be relative and stay below this file")
            else:
                return list(dict.fromkeys(value))
    elif f.type == "rule_list":
        if not isinstance(value, list):
            out.append(f"{where}: must be a list of {{id, description}}")
        else:
            rules: list[dict[str, str]] = []
            for i, item in enumerate(value):
                if (
                    not isinstance(item, Mapping)
                    or not isinstance(item.get("id"), str)
                    or not item["id"].strip()
                    or set(item) - {"id", "description"}
                    or not isinstance(item.get("description", ""), str)
                ):
                    out.append(f"{where}[{i}]: needs id (text) and optional description (text)")
                else:
                    rules.append(
                        {"id": item["id"].strip(), "description": item.get("description", "")}
                    )
            if len(out) == n:
                return rules
    return None


def validate_answers(data: Any, *, require_identity: bool = False) -> dict[str, Any]:
    """Validate answers against the vocabularies and return a clean dict (blank values dropped).

    Raises ``QuestionnaireError`` listing every problem. ``require_identity`` demands
    ``product_id`` and ``name`` (a full product.yaml); an answers overlay does not need them.
    """
    if not isinstance(data, Mapping):
        raise QuestionnaireError(["the answers must be a mapping of field names to values"])
    out: dict[str, Any] = {}
    problems: list[str] = []
    for key in data:
        if key not in _FIELD and key != "controls":
            problems.append(f"{key}: unknown field")
    for f in FIELDS:
        value = data.get(f.name)
        if value is None:
            if require_identity and f.name in ("product_id", "name"):
                problems.append(f"{f.name}: required")
            continue
        norm = _check_value(f, value, f.name, f.enum, problems)
        if norm is not None:
            if f.name == "product_id" and not _ID_RE.match(norm):
                problems.append("product_id: use letters, digits, dot, dash, underscore (max 64)")
            else:
                out[f.name] = norm
    ctl = data.get("controls")
    if ctl is not None:
        if not isinstance(ctl, Mapping):
            problems.append("controls: must be a mapping")
        else:
            monitors, evidence = _controls_names()
            enums = {"monitors": monitors, "evidence": evidence, "catalogue": _catalogue_ids()}
            clean: dict[str, Any] = {}
            for key in ctl:
                if key not in _CONTROL_FIELD:
                    problems.append(f"controls.{key}: unknown field")
            for f in CONTROL_FIELDS:
                value = ctl.get(f.name)
                if value is None:
                    continue
                norm = _check_value(f, value, f"controls.{f.name}", enums.get(f.name, ()), problems)
                if norm is not None:
                    clean[f.name] = norm
            if clean:
                out["controls"] = clean
    if problems:
        raise QuestionnaireError(problems)
    return out


def load_answers_file(path: Path) -> dict[str, Any]:
    """Read a YAML (or JSON) answers file. Errors become ``QuestionnaireError``."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise QuestionnaireError([f"{path.name}: file is larger than {MAX_FILE_BYTES} bytes"])
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise QuestionnaireError(
            [f"{path.name}: cannot read the file ({type(exc).__name__})"]
        ) from None
    except yaml.YAMLError:
        raise QuestionnaireError([f"{path.name}: not valid YAML"]) from None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise QuestionnaireError([f"{path.name}: must be a mapping of field names to values"])
    return data


# ----------------------------------------------------------------------------- schema, template


def _schema_of(f: QField, enums: Mapping[str, tuple[str, ...]]) -> dict[str, Any]:
    desc = f"{f.help_en} / {f.help_vi}"
    enum = enums.get(f.name, f.enum)
    s: dict[str, Any]
    if f.type in ("string", "text"):
        s = {"type": ["string", "null"], "maxLength": _TEXT_LIMITS[f.type]}
    elif f.type == "bool":
        s = {"type": ["boolean", "null"]}
    elif f.type == "int":
        s = {"type": ["integer", "null"], "minimum": 0}
    elif f.type == "date":
        s = {"type": ["string", "null"], "format": "date"}
    elif f.type == "enum":
        s = {"enum": [*enum, None]}
    elif f.type in ("enum_list", "string_list"):
        item: dict[str, Any] = {"enum": list(enum)} if enum else {"type": "string"}
        s = {"type": ["array", "null"], "items": item, "uniqueItems": True}
    else:  # rule_list
        s = {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "required": ["id"],
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}, "description": {"type": "string"}},
            },
        }
    s["description"] = desc
    return s


def questionnaire_schema() -> dict[str, Any]:
    """JSON Schema 2020-12 of product.yaml. Descriptions are "English / Vietnamese"."""
    monitors, evidence = _controls_names()
    enums = {"monitors": monitors, "evidence": evidence}
    props = {f.name: _schema_of(f, {}) for f in FIELDS}
    props["controls"] = {
        "type": ["object", "null"],
        "additionalProperties": False,
        "description": (
            "Supervisor controls the product has. If this block is absent the advisor treats "
            "the controls as unknown and asks / Các kiểm soát Supervisor của sản phẩm. Nếu "
            "không có khối này, công cụ coi là chưa biết và đặt câu hỏi."
        ),
        "properties": {f.name: _schema_of(f, enums) for f in CONTROL_FIELDS},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Supervisor compliance advisor: product questionnaire / Phiếu thông tin sản phẩm",
        "type": "object",
        "required": ["product_id", "name"],
        "additionalProperties": False,
        "properties": props,
    }


def schema_json() -> str:
    """The exact text of ``product.schema.json``."""
    return json.dumps(questionnaire_schema(), indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def template_yaml() -> str:
    """Commented product.yaml. Every optional field is blank (= unknown = a question)."""
    lines = [
        "# Product questionnaire for the Supervisor compliance advisor.",
        "# Phiếu thông tin sản phẩm cho công cụ tư vấn tuân thủ của Supervisor.",
        "# Blank = unknown: the advisor asks a question. [] = a real answer 'none'.",
        "# Để trống = chưa biết: công cụ sẽ đặt câu hỏi. [] = câu trả lời 'không có'.",
        "# Money: whole VND, no decimals. Not legal advice; bank counsel must confirm.",
        "",
    ]
    examples = {"product_id": "my-product", "name": "My product"}

    def emit(f: QField, indent: str) -> None:
        lines.append(f"{indent}# {f.help_en}")
        lines.append(f"{indent}# {f.help_vi}")
        if f.enum:
            lines.append(f"{indent}# Allowed / Giá trị hợp lệ: {', '.join(f.enum)}")
        lines.append(f"{indent}{f.name}:{' ' + examples[f.name] if f.name in examples else ''}")
        lines.append("")

    for f in FIELDS:
        emit(f, "")
    lines.append("# Supervisor controls the product has / Các kiểm soát Supervisor của sản phẩm.")
    lines.append("# Leave the whole block out if unknown / Bỏ cả khối nếu chưa biết.")
    lines.append("controls:")
    for f in CONTROL_FIELDS:
        emit(f, "  ")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--write"]:
        print("usage: python -m supervisor.advisory.compliance.questionnaire --write")  # noqa: T201
        return 2
    SCHEMA_FILE.write_text(schema_json(), encoding="utf-8")
    EXAMPLE_FILE.write_text(template_yaml(), encoding="utf-8")
    print(f"[OK] wrote {SCHEMA_FILE.name} and {EXAMPLE_FILE.name}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
