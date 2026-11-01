"""Executive findings of a risk assessment (``ORCH_EXEC_FINDINGS``, default off).

A stored ``assessment_report_v1`` lists checks ("Required test pii_canary has not been run yet.").
A manager needs more: what it means for the bank, why it matters, what to do and who acts. This
module turns the report and the facts of the code scan into a few executive findings per risk type
and stores them next to the report as ``<dimension>.exec.json`` (``executive_v1``).

Layer A (``observations``, ``build``) is deterministic and has no network. It reads the facts_v1
export of the code scan and the system record (field NAMES and file:line only, never a value) and
the findings of the report. A test that has not been run is an open point, never a claim about the
code. Layer B (``rewrite``, ``ORCH_EXEC_LLM``) lets the system model reword headline, impact and
bottom line in executive English and Vietnamese. It is advisory: a reworded line is kept only when
it adds no number, name, file or absolute claim that Layer A did not have; it never changes the
key, the status, the severity or the rating. Any failure leaves the Layer A text.

Not legal advice. Bank counsel confirms.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from supervisor.governance import risk_dimensions as rd

log = logging.getLogger(__name__)

VERSION = 1
MAX_ITEMS = 6
CALL_TIMEOUT_S = 30.0
OWNERS = ("system_owner", "risk_team", "security", "data_owner", "legal", "model_validation")
RATINGS = ("high", "medium", "low", "clear", "open")
SEVERITIES = ("high", "medium", "low")
STATUSES = ("fail", "open", "pass")
_SEV_RANK = {"high": 0, "medium": 1, "low": 2}
_STATUS_RANK = {"fail": 0, "open": 1, "pass": 2}
MAX_TEXT = 900  # one line of executive text, after masking

# Keys of the executive findings (KEYS.md). The first ten come from the facts of the code scan.
FACT_KEYS = (
    "money_tool_no_gate",
    "declared_control_mismatch",
    "personal_data_fields",
    "personal_data_mismatch",
    "pii_export_tool",
    "model_unknown",
    "no_tracing",
    "hardcoded_secret",
    "external_endpoint",
    "risk_level_mismatch",
)
REPORT_KEYS = ("tests_missing", "tests_failed")
# Keys that mean "no evidence yet", not "the code shows a problem". They never raise the rating.
GAP_KEYS = frozenset({"tests_missing", "depends_open", "person_decides"})
# A key that says the same as another key in the same risk type is folded into it.
FOLDED_INTO = {"declared_control_mismatch": "money_tool_no_gate"}

IDENTITY_FIELDS = frozenset(
    {
        "cccd",
        "cmnd",
        "passport",
        "national_id",
        "id_number",
        "citizen_id",
        "identity_number",
        "tax_id",
        "tax_code",
        "so_cccd",
        "so_cmnd",
    }
)


def _t(en: str, vi: str) -> dict[str, str]:
    return {"en": en, "vi": vi}


# ------------------------------------------------------------------------------ catalogue
# What each automated test of config/risk_dimensions.yaml checks, in business words.
# id -> (name_en, name_vi, covers_en, covers_vi, owner)
TESTS: dict[str, tuple[str, str, str, str, str]] = {
    "truthfulqa_vi": (
        "truthfulness",
        "tính trung thực",
        "whether the model repeats common false beliefs in Vietnamese",
        "mô hình có lặp lại những điều sai phổ biến bằng tiếng Việt hay không",
        "model_validation",
    ),
    "perturbation_vi": (
        "robustness",
        "độ ổn định",
        "whether small changes in the wording change the answer",
        "thay đổi nhỏ trong cách diễn đạt có làm đổi câu trả lời hay không",
        "model_validation",
    ),
    "paraphrase_consistency": (
        "consistency",
        "tính nhất quán",
        "whether the same question in other words gets the same answer",
        "cùng một câu hỏi diễn đạt khác có nhận được cùng một câu trả lời hay không",
        "model_validation",
    ),
    "simpleqa_vi": (
        "factual accuracy",
        "độ chính xác thực tế",
        "whether short factual questions get correct answers",
        "các câu hỏi thực tế ngắn có được trả lời đúng hay không",
        "model_validation",
    ),
    "pii_canary": (
        "personal-data leak",
        "rò rỉ dữ liệu cá nhân",
        "whether the agent leaks planted personal data in its answers or traces",
        "tác tử có làm lộ dữ liệu cá nhân cài sẵn trong câu trả lời hoặc nhật ký hay không",
        "data_owner",
    ),
    "owasp_agentic_redteam": (
        "agent attack",
        "tấn công tác tử",
        "whether attacks on an agent with tools, such as a hijacked goal or a misused tool, work",
        "tấn công vào tác tử có công cụ (đổi mục tiêu, lạm dụng công cụ) có thành công không",
        "security",
    ),
    "indirect_injection_vi": (
        "hidden instruction",
        "chỉ thị ẩn",
        "whether instructions hidden in documents or tool results can take control of the agent",
        "chỉ thị ẩn trong tài liệu hoặc kết quả công cụ có chiếm quyền điều khiển tác tử không",
        "security",
    ),
    "finance_harm_refusal": (
        "harmful request",
        "yêu cầu gây hại",
        "whether the agent refuses harmful finance requests, such as help with fraud",
        "tác tử có từ chối các yêu cầu tài chính gây hại, như hỗ trợ gian lận, hay không",
        "security",
    ),
    "prefilter_evasion": (
        "filter evasion",
        "vượt bộ lọc",
        "whether disguised input gets past the input filter",
        "đầu vào được ngụy trang có qua được bộ lọc đầu vào không",
        "security",
    ),
    "owasp_llm_top10": (
        "common attacks",
        "tấn công phổ biến",
        "the ten most common attacks on applications built on language models",
        "mười kiểu tấn công phổ biến nhất vào ứng dụng xây trên mô hình ngôn ngữ",
        "security",
    ),
    "multiturn_redteam_vi": (
        "multi-turn attack",
        "tấn công nhiều lượt",
        "whether an attacker can wear the agent down over several turns",
        "kẻ tấn công có thể làm tác tử nhượng bộ qua nhiều lượt hội thoại hay không",
        "security",
    ),
    "fairness_metrics": (
        "fairness measures",
        "chỉ số công bằng",
        "whether outcomes differ across customer groups",
        "kết quả có khác nhau giữa các nhóm khách hàng hay không",
        "model_validation",
    ),
    "four_fifths_rule": (
        "four-fifths rule",
        "quy tắc bốn phần năm",
        "whether one customer group gets clearly fewer favourable outcomes than another",
        "một nhóm khách hàng có nhận được ít kết quả thuận lợi hơn rõ rệt so với nhóm khác không",
        "model_validation",
    ),
    "counterfactual_vi": (
        "same-case comparison",
        "so sánh cùng hồ sơ",
        "whether changing only a protected trait, such as gender or region, changes the decision",
        "chỉ đổi một đặc điểm được bảo vệ (giới tính, vùng miền) có làm đổi quyết định không",
        "model_validation",
    ),
    "fairness": (
        "fairness monitor",
        "giám sát công bằng",
        "the live comparison of outcomes across customer groups",
        "so sánh kết quả giữa các nhóm khách hàng khi hệ thống đang chạy",
        "model_validation",
    ),
    "model_dependency_inventory": (
        "model dependency",
        "phụ thuộc mô hình",
        "which models and vendors the agent depends on",
        "tác tử phụ thuộc vào những mô hình và nhà cung cấp nào",
        "risk_team",
    ),
    "licence_allowlist": (
        "licence",
        "giấy phép phần mềm",
        "whether every library has a licence the bank allows",
        "mọi thư viện có giấy phép mà ngân hàng cho phép hay không",
        "security",
    ),
    "pin_hash_check": (
        "version pin",
        "cố định phiên bản",
        "whether libraries are pinned to exact, verified versions",
        "các thư viện có được cố định theo phiên bản chính xác đã xác minh hay không",
        "security",
    ),
    "mcp_tool_manifest_drift": (
        "tool list change",
        "thay đổi danh sách công cụ",
        "whether the tools an agent can call changed after approval",
        "các công cụ tác tử có thể gọi có bị thay đổi sau khi được duyệt hay không",
        "security",
    ),
    "sbom_cyclonedx": (
        "software parts list",
        "danh mục thành phần phần mềm",
        "a complete list of the software parts the system is built from",
        "danh sách đầy đủ các thành phần phần mềm tạo nên hệ thống",
        "security",
    ),
    "osv_offline": (
        "known flaw",
        "lỗ hổng đã biết",
        "whether any library has a known security flaw",
        "có thư viện nào mang lỗ hổng bảo mật đã biết hay không",
        "security",
    ),
}

# Default owner of a test group by risk type (when the tests name no single owner).
DIM_OWNER = {
    "model": "model_validation",
    "data_governance": "data_owner",
    "cybersecurity": "security",
    "legal_compliance": "legal",
    "ethics": "model_validation",
    "third_party": "risk_team",
    "supply_chain": "security",
    "reputation": "risk_team",
}

# Short risk type names for the text of findings (EN from the config label, VI from the config).
_SHORT_EN = {
    "model": "Model",
    "data_governance": "Data governance",
    "cybersecurity": "Cybersecurity",
    "legal_compliance": "Legal compliance",
    "ethics": "Ethics",
    "third_party": "Third-party",
    "supply_chain": "Supply chain",
    "reputation": "Reputation",
}


def _labels() -> dict[str, tuple[str, str]]:
    try:
        return {
            d.id: (_SHORT_EN.get(d.id, d.label_en), d.label_vi) for d in rd.load_config().dimensions
        }
    except Exception:  # noqa: BLE001 - the text still reads without the config
        return {k: (v, v) for k, v in _SHORT_EN.items()}


def _required_ids(dim_id: str) -> dict[str, bool]:
    """pack/monitor id -> required, from config/risk_dimensions.yaml (``measured_by``)."""
    try:
        return {m.id: bool(m.required) for m in rd.load_config().get(dim_id).measured_by}
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------------------------ small helpers


def _n(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _detail(detail: Any) -> dict[str, str]:
    """``risk_class=money; approved=yes; reversibility: ...`` -> {"risk_class": "money", ...}."""
    out: dict[str, str] = {}
    for part in str(detail or "").split(";"):
        part = part.strip()
        m = re.match(r"^([a-z_]+)\s*[=:]\s*(.*)$", part)
        if m:
            out.setdefault(m.group(1), m.group(2).strip())
    return out


def _ref(row: Mapping[str, Any]) -> str:
    f, ln = row.get("file"), row.get("line")
    return f"{f}:{ln}" if f and ln else ""


def _refs(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for r in rows:
        x = _ref(r)
        if x and x not in out:
            out.append(x)
    return out[:8]


def _join(names: Sequence[str], cap: int = 6) -> str:
    names = [n for n in names if n]
    if len(names) <= cap:
        return ", ".join(names)
    return ", ".join(names[:cap]) + f" +{len(names) - cap}"


def _facts_rows(facts: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    rows = (facts or {}).get("facts") or []
    return [r for r in rows if isinstance(r, Mapping)]


def _item(
    key: str,
    severity: str,
    status: str,
    headline: dict[str, str],
    impact: dict[str, str],
    action: dict[str, str],
    owner: str,
    dims: Sequence[str],
    fact_refs: Sequence[str] = (),
    owner_by_dim: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "severity": severity,
        "status": status,
        "headline": headline,
        "impact": impact,
        "action": action,
        "owner": owner,
        "finding_ids": [],
        "fact_refs": list(fact_refs),
        "dims": list(dims),
        "owner_by_dim": dict(owner_by_dim or {}),
    }


# ------------------------------------------------------------------------------ Layer A: facts

_PD_FIELD = re.compile(r"Handles personal data field '([^']{1,80})'")
_NO_GATE = re.compile(r"no human approval step in code:\s*(.+)$", re.IGNORECASE)
_LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0", "")  # noqa: S104 - a host to skip


def _pd_fields(rows: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[Mapping[str, Any]]]:
    names: list[str] = []
    used: list[Mapping[str, Any]] = []
    for r in rows:
        if r.get("kind") != "claim":
            continue
        m = _PD_FIELD.search(str(r.get("name") or ""))
        if m:
            if m.group(1) not in names:
                names.append(m.group(1))
            used.append(r)
    return names, used


def _ungated(rows: Sequence[Mapping[str, Any]]) -> tuple[bool, list[str], list[Mapping[str, Any]]]:
    """(the facts show a side-effect tool with no human approval step in code, the tools named
    by the autonomy fact, the facts that say so)."""
    tools: list[str] = []
    used: list[Mapping[str, Any]] = []
    flag = False
    for r in rows:
        if r.get("kind") == "autonomy":
            m = _NO_GATE.search(str(r.get("detail") or ""))
            if m:
                flag = True
                used.append(r)
                for t in re.split(r"[,\s]+", m.group(1).strip().rstrip(".")):
                    if t and t not in tools:
                        tools.append(t)
        elif r.get("kind") == "decision33" and "human_gate_in_code=False" in str(
            r.get("detail") or ""
        ):
            flag = True
            used.append(r)
    return flag, tools, used


def _level_words(level: str) -> tuple[str, str]:
    if level in ("", "unspecified", "None"):
        return "not set", "chưa đặt"
    vi = {"low": "thấp", "medium": "trung bình", "high": "cao", "prohibited": "bị cấm"}
    return level, vi.get(level, level)


def observations(
    facts: Mapping[str, Any] | None, system: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """The fact keys of KEYS.md that fire for this code scan and this system record. Each item has
    the executive_v1 item fields plus ``dims`` (the risk types it belongs to) and ``owner_by_dim``.
    Field names and file:line only; no value of the code or of the data ever enters the text."""
    rows = _facts_rows(facts)
    sysrec: Mapping[str, Any] = system or {}
    out: list[dict[str, Any]] = []
    if not rows:
        return out
    human = str(sysrec.get("human_control") or "")
    gate_missing, gate_tools, gate_rows = _ungated(rows)
    tool_rows = [r for r in rows if r.get("kind") == "tool"]

    # money_tool_no_gate
    money = [r for r in tool_rows if _detail(r.get("detail")).get("risk_class") == "money"]
    if money and gate_missing:
        named = [r for r in money if str(r.get("name")) in gate_tools] or money
        names = [str(r.get("name")) for r in named]
        tl = _join(names, 4)
        irrev = any("not reversible" in str(r.get("detail") or "") for r in named)
        reg_en = (
            ", although the registration says every action is approved first"
            if human == "pre_approval"
            else ""
        )
        reg_vi = (
            ", dù hồ sơ đăng ký ghi rằng mọi hành động đều được phê duyệt trước"
            if human == "pre_approval"
            else ""
        )
        out.append(
            _item(
                "money_tool_no_gate",
                "high",
                "fail",
                _t(
                    f"The agent can send payments ({tl}) and the code has no approval step "
                    f"before it{reg_en}.",
                    f"Tác tử có thể chuyển tiền ({tl}) và trong mã không có bước phê duyệt "
                    f"trước khi chuyển{reg_vi}.",
                ),
                _t(
                    "A wrong or manipulated instruction could move money with no person checking "
                    "it first."
                    + (" The agent cannot take a payment back." if irrev else "")
                    + " The scan reads the code only, so a control outside the code is possible "
                    "but not shown.",
                    "Một chỉ thị sai hoặc bị lợi dụng có thể chuyển tiền mà không ai kiểm tra "
                    "trước."
                    + (" Tác tử không thể thu hồi khoản đã chuyển." if irrev else "")
                    + " Việc quét chỉ đọc mã, nên có thể có kiểm soát nằm ngoài mã nhưng chưa "
                    "được chứng minh.",
                ),
                _t(
                    "Add an approval step before the payment tool, or show the control that "
                    "exists outside the code. Then scan again.",
                    "Thêm bước phê duyệt trước công cụ thanh toán, hoặc chứng minh kiểm soát nằm "
                    "ngoài mã. Sau đó quét lại.",
                ),
                "system_owner",
                ("cybersecurity", "ethics", "legal_compliance"),
                _refs([*named, *gate_rows]),
            )
        )

    # declared_control_mismatch
    if human in ("pre_approval", "post_review") and gate_missing:
        ctl_en = "approval before action" if human == "pre_approval" else "review after action"
        ctl_vi = (
            "phê duyệt trước khi hành động" if human == "pre_approval" else "rà soát sau hành động"
        )
        before_en = f" before {_join(gate_tools, 4)}" if gate_tools else ""
        before_vi = f" trước {_join(gate_tools, 4)}" if gate_tools else ""
        out.append(
            _item(
                "declared_control_mismatch",
                "high",
                "fail",
                _t(
                    f"The registration says a person controls the agent ({ctl_en}), but the "
                    f"code scan found no human approval step{before_en}.",
                    f"Hồ sơ đăng ký ghi có người kiểm soát tác tử ({ctl_vi}), nhưng quét mã "
                    f"không thấy bước phê duyệt của con người{before_vi}.",
                ),
                _t(
                    "Approval and duties are based on the registration. If it is wrong, the "
                    "classification and the controls may be wrong too.",
                    "Quyết định phê duyệt và nghĩa vụ dựa trên hồ sơ đăng ký. Nếu hồ sơ sai, "
                    "phân loại và các biện pháp kiểm soát cũng có thể sai.",
                ),
                _t(
                    "Add the approval step in the code, or correct the registration. Then scan "
                    "again.",
                    "Thêm bước phê duyệt vào mã, hoặc sửa hồ sơ đăng ký. Sau đó quét lại.",
                ),
                "system_owner",
                ("legal_compliance", "ethics"),
                _refs(gate_rows),
            )
        )

    # personal_data_fields and personal_data_mismatch
    fields, field_rows = _pd_fields(rows)
    if fields:
        ident = sorted(f for f in fields if f.lower() in IDENTITY_FIELDS)
        fl = _join(fields, 6)
        n = len(fields)
        idn_en = f", including identity numbers ({_join(ident, 3)})" if ident else ""
        idn_vi = f", trong đó có số định danh ({_join(ident, 3)})" if ident else ""
        out.append(
            _item(
                "personal_data_fields",
                "high" if ident else "medium",
                "open",
                _t(
                    f"The code handles {n} personal data {_n(n, 'field', 'fields')}: {fl}{idn_en}.",
                    f"Mã xử lý {n} trường dữ liệu cá nhân: {fl}{idn_vi}.",
                ),
                _t(
                    "Personal data needs a legal basis, limited access and masking in logs "
                    "(Decree 13). A leaked identity number can be used to impersonate a "
                    "customer.",
                    "Dữ liệu cá nhân cần có cơ sở pháp lý, giới hạn quyền truy cập và che khi "
                    "ghi nhật ký (Nghị định 13). Số định danh bị lộ có thể bị dùng để mạo danh "
                    "khách hàng.",
                ),
                _t(
                    "Confirm each field is needed, masked in logs and limited by role. Run the "
                    "personal-data leak test.",
                    "Xác nhận từng trường thật sự cần, được che trong nhật ký và giới hạn theo "
                    "vai trò. Chạy bài kiểm tra rò rỉ dữ liệu cá nhân.",
                ),
                "data_owner",
                ("data_governance",),
                _refs(field_rows),
            )
        )
        if str(sysrec.get("personal_data") or "") == "none":
            out.append(
                _item(
                    "personal_data_mismatch",
                    "high",
                    "fail",
                    _t(
                        f"The registration says the agent uses no personal data, but the code "
                        f"handles {n} personal data {_n(n, 'field', 'fields')} "
                        f"({_join(fields, 4)}).",
                        f"Hồ sơ đăng ký ghi tác tử không dùng dữ liệu cá nhân, nhưng mã xử lý "
                        f"{n} trường dữ liệu cá nhân ({_join(fields, 4)}).",
                    ),
                    _t(
                        "Personal data brings extra duties and a stricter classification. A "
                        "wrong registration hides them.",
                        "Dữ liệu cá nhân kéo theo thêm nghĩa vụ và phân loại chặt hơn. Hồ sơ "
                        "đăng ký sai sẽ che mất các nghĩa vụ này.",
                    ),
                    _t(
                        "Correct the personal data answer in the registration, then check the "
                        "duties again.",
                        "Sửa câu trả lời về dữ liệu cá nhân trong hồ sơ đăng ký, rồi kiểm tra "
                        "lại các nghĩa vụ.",
                    ),
                    "data_owner",
                    ("data_governance", "legal_compliance"),
                    _refs(field_rows),
                    {"legal_compliance": "legal"},
                )
            )

    # pii_export_tool
    pii = [r for r in tool_rows if _detail(r.get("detail")).get("risk_class") == "pii_export"]
    if pii:
        names = [str(r.get("name")) for r in pii]
        irrev = any("cannot be recalled" in str(r.get("detail") or "") for r in pii)
        out.append(
            _item(
                "pii_export_tool",
                "medium",
                "open",
                _t(
                    f"The {_n(len(names), 'tool', 'tools')} {_join(names, 4)} can store or send "
                    f"personal data out of the system"
                    + ("; once sent, it cannot be recalled" if irrev else "")
                    + ".",
                    f"{_n(len(names), 'Công cụ', 'Các công cụ')} {_join(names, 4)} có thể lưu "
                    f"hoặc gửi dữ liệu cá nhân ra ngoài hệ thống"
                    + ("; đã gửi thì không thể thu hồi" if irrev else "")
                    + ".",
                ),
                _t(
                    "A mistake or an attack on this tool puts customer data outside the bank's "
                    "control.",
                    "Một lỗi hoặc một cuộc tấn công vào công cụ này đưa dữ liệu khách hàng ra "
                    "ngoài tầm kiểm soát của ngân hàng.",
                ),
                _t(
                    "Limit who and what can call the tool, mask the data it sends and log each "
                    "use.",
                    "Giới hạn ai và hệ thống nào được gọi công cụ, che dữ liệu nó gửi đi và ghi "
                    "nhật ký mỗi lần dùng.",
                ),
                "data_owner",
                ("data_governance", "cybersecurity"),
                _refs(pii),
                {"cybersecurity": "security"},
            )
        )

    # model_unknown
    unknown = [
        r
        for r in rows
        if r.get("kind") in ("model", "endpoint")
        and _detail(r.get("detail")).get("family") == "unknown"
    ]
    if unknown:
        names = []
        for r in unknown:
            nm = str(r.get("name") or "")
            if nm and nm.lower() != "unknown" and nm not in names:
                names.append(nm)
        paren_en = f" ({_join(names, 3)})" if names else ""
        out.append(
            _item(
                "model_unknown",
                "medium",
                "open",
                _t(
                    f"The scan cannot tell which model family the agent uses{paren_en}.",
                    f"Quét mã không xác định được họ mô hình mà tác tử sử dụng{paren_en}.",
                ),
                _t(
                    "Without the model name and provider, the bank cannot check where data goes, "
                    "which tests apply or who is accountable.",
                    "Không biết tên mô hình và nhà cung cấp, ngân hàng không kiểm tra được dữ "
                    "liệu đi đâu, cần chạy bài kiểm tra nào và ai chịu trách nhiệm.",
                ),
                _t(
                    "Record the model name, provider and version in the registration.",
                    "Ghi tên mô hình, nhà cung cấp và phiên bản vào hồ sơ đăng ký.",
                ),
                "model_validation",
                ("model", "supply_chain", "third_party"),
                _refs(unknown),
                {"third_party": "risk_team", "supply_chain": "risk_team"},
            )
        )

    # no_tracing
    trace = [
        r
        for r in rows
        if r.get("kind") == "weak_spot" and "no tracing found" in str(r.get("name") or "").lower()
    ]
    if trace:
        out.append(
            _item(
                "no_tracing",
                "medium",
                "open",
                _t(
                    "The agent keeps no trace of what it does (no OpenTelemetry or MLflow use "
                    "found in the code).",
                    "Tác tử không lưu vết những gì nó làm (không thấy mã dùng OpenTelemetry "
                    "hay MLflow).",
                ),
                _t(
                    "After an incident, the bank cannot replay what the agent did or why. "
                    "Monitoring in production needs this trace.",
                    "Sau sự cố, ngân hàng không thể dựng lại tác tử đã làm gì và vì sao. Giám "
                    "sát khi vận hành cần có vết này.",
                ),
                _t(
                    "Add the tracing hook from the onboarding pull request.",
                    "Thêm đoạn ghi vết từ pull request của quy trình đưa vào quản lý.",
                ),
                "system_owner",
                ("model", "cybersecurity"),
                _refs(trace),
            )
        )

    # hardcoded_secret
    secrets = [r for r in rows if r.get("kind") == "secret_use"]
    if secrets:
        kinds: list[str] = []
        for r in secrets:
            nm = str(r.get("name") or "secret")
            if nm not in kinds:
                kinds.append(nm)
        out.append(
            _item(
                "hardcoded_secret",
                "high",
                "fail",
                _t(
                    f"A secret ({_join(kinds, 3)}) is written in the code or in a file.",
                    f"Có một bí mật ({_join(kinds, 3)}) được ghi thẳng trong mã hoặc trong tệp.",
                ),
                _t(
                    "Anyone who can read the code can use it. A leaked key can open bank "
                    "systems or data.",
                    "Ai đọc được mã đều dùng được nó. Một khóa bị lộ có thể mở ra hệ thống hoặc "
                    "dữ liệu của ngân hàng.",
                ),
                _t(
                    "Remove it from the code, use a secret store and replace the key.",
                    "Gỡ khỏi mã, dùng kho bí mật và đổi khóa mới.",
                ),
                "security",
                ("cybersecurity",),
                _refs(secrets),
            )
        )

    # external_endpoint
    hosts: list[str] = []
    ext: list[Mapping[str, Any]] = []
    for r in rows:
        if r.get("kind") != "external_url":
            continue
        name = str(r.get("name") or "")
        if "FILL-ME" in name.upper():
            continue
        try:
            host = urlparse(name).hostname or ""
        except ValueError:
            continue
        if host in _LOOPBACK or host.endswith(".localhost"):
            continue
        ext.append(r)
        if host not in hosts:
            hosts.append(host)
    if ext:
        out.append(
            _item(
                "external_endpoint",
                "medium",
                "open",
                _t(
                    f"The code calls {_n(len(hosts), 'an outside address', 'outside addresses')} "
                    f"({_join(hosts, 3)}).",
                    f"Mã gọi tới địa chỉ bên ngoài ({_join(hosts, 3)}).",
                ),
                _t(
                    "Data can leave the bank's network. The other side may see or keep it.",
                    "Dữ liệu có thể rời khỏi mạng của ngân hàng. Bên kia có thể xem hoặc giữ lại "
                    "dữ liệu đó.",
                ),
                _t(
                    "Confirm who runs it, which data goes there and that a contract and an exit "
                    "plan exist.",
                    "Xác nhận ai vận hành, dữ liệu nào được gửi đi, và đã có hợp đồng cùng kế "
                    "hoạch thoát.",
                ),
                "security",
                ("third_party", "cybersecurity"),
                _refs(ext),
                {"third_party": "risk_team"},
            )
        )

    # risk_level_mismatch
    high = [r for r in rows if r.get("kind") == "decision33" and r.get("name") == "high_risk"]
    level = str(sysrec.get("risk_level") or "unspecified")
    if high and level != "high":
        en, vi = _level_words(level)
        out.append(
            _item(
                "risk_level_mismatch",
                "medium",
                "open",
                _t(
                    f"The code scan points to high risk under Decision 33, but the registered "
                    f"risk level is {en}.",
                    f"Quét mã cho thấy rủi ro cao theo Quyết định 33, nhưng mức rủi ro đã đăng "
                    f"ký là {vi}.",
                ),
                _t(
                    "A lower level than the evidence shows can skip duties, approvals and checks "
                    "that a high-risk system needs. The scan only proposes; counsel confirms.",
                    "Mức thấp hơn so với bằng chứng có thể bỏ sót nghĩa vụ, phê duyệt và kiểm "
                    "tra mà hệ thống rủi ro cao cần có. Quét mã chỉ đề xuất; pháp chế xác nhận.",
                ),
                _t(
                    "Review the classification with legal counsel and update the risk level.",
                    "Rà soát phân loại cùng pháp chế và cập nhật mức rủi ro.",
                ),
                "legal",
                ("legal_compliance",),
                _refs(high),
            )
        )
    return out


# ------------------------------------------------------------------------------ Layer A: report


def _state_of(rationale: str) -> str:
    low = rationale.lower()
    if "out of date" in low or "stale" in low:
        return "stale"
    if "weak" in low:
        return "weak"
    return "missing"


def _test_names(ids: Sequence[str], lang: int) -> list[str]:
    return [TESTS[i][lang] if i in TESTS else i for i in ids]


def _test_item(
    dim_id: str, ids: list[str], failed: bool, states: Sequence[str], fids: list[str]
) -> dict[str, Any]:
    n = len(ids)
    names_en = _join(_test_names(ids, 0), 5)
    names_vi = _join(_test_names(ids, 1), 5)
    covers_en = "; ".join(TESTS[i][2] for i in ids[:3] if i in TESTS)
    covers_vi = "; ".join(TESTS[i][3] for i in ids[:3] if i in TESTS)
    owners = [TESTS[i][4] for i in ids if i in TESTS]
    owner = max(set(owners), key=owners.count) if owners else DIM_OWNER.get(dim_id, "risk_team")
    if failed:
        it = _item(
            "tests_failed",
            "high",
            "fail",
            _t(
                f"{n} required {_n(n, 'test', 'tests')} failed ({names_en}).",
                f"{n} bài kiểm tra bắt buộc không đạt ({names_vi}).",
            ),
            _t(
                "The agent did not meet the bar of the test."
                + (f" The test checks {covers_en}." if covers_en else "")
                + " This risk type cannot be passed until it is fixed.",
                "Tác tử chưa đạt yêu cầu của bài kiểm tra."
                + (f" Bài kiểm tra xem xét {covers_vi}." if covers_vi else "")
                + " Loại rủi ro này chưa thể đạt cho tới khi được khắc phục.",
            ),
            _t(
                "Open the test result, fix the cause and run the test again.",
                "Mở kết quả kiểm tra, khắc phục nguyên nhân và chạy lại bài kiểm tra.",
            ),
            owner,
            (dim_id,),
        )
    else:
        stale_only = all(s == "stale" for s in states)
        verb_vi = "đã quá hạn" if stale_only else "chưa được chạy"
        it = _item(
            "tests_missing",
            "medium",
            "open",
            _t(
                f"{n} required {_n(n, 'test has', 'tests have')} "
                + ("no current result" if stale_only else "not been run yet")
                + f" ({names_en}).",
                f"{n} bài kiểm tra bắt buộc {verb_vi} ({names_vi}).",
            ),
            _t(
                "There is no test evidence either way. This does not mean the agent is unsafe; "
                "it means the bank cannot show that it is safe, so this risk type cannot be "
                "passed." + (f" The tests check {covers_en}." if covers_en else ""),
                "Chưa có bằng chứng kiểm tra theo hướng nào. Điều này không có nghĩa tác tử "
                "không an toàn; nó có nghĩa ngân hàng chưa chứng minh được là an toàn, nên loại "
                "rủi ro này chưa thể đạt."
                + (f" Các bài kiểm tra xem xét {covers_vi}." if covers_vi else ""),
            ),
            _t(
                "Run the missing tests for this AI system, then run the assessment again.",
                "Chạy các bài kiểm tra còn thiếu cho hệ thống AI này, rồi chạy lại đánh giá.",
            ),
            owner,
            (dim_id,),
        )
    it["finding_ids"] = fids
    return it


def _reads_items(
    dim_id: str, failed: list[tuple[str, str]], opened: list[tuple[str, str]]
) -> list[dict[str, Any]]:
    labels = _labels()
    owner = "legal" if dim_id == "legal_compliance" else "risk_team"
    out: list[dict[str, Any]] = []
    for rows, status, key in ((failed, "fail", "depends_failed"), (opened, "open", "depends_open")):
        if not rows:
            continue
        dims = [r[0] for r in rows]
        n = len(dims)
        en = _join([labels.get(d, (d, d))[0].lower() for d in dims], 8)
        vi = _join([labels.get(d, (d, d))[1] for d in dims], 8)
        what_vi = "không đạt" if status == "fail" else "vẫn còn mở"
        it = _item(
            key,
            "high" if status == "fail" else "medium",
            status,
            _t(
                f"This risk type depends on {n} other risk {_n(n, 'type', 'types')} that "
                f"{'failed' if status == 'fail' else _n(n, 'is', 'are') + ' still open'} ({en}).",
                f"Loại rủi ro này phụ thuộc vào {n} loại rủi ro khác {what_vi} ({vi}).",
            ),
            _t(
                "Its result is built from the other types, so it cannot be passed before they "
                "are closed.",
                "Kết quả của loại này được tổng hợp từ các loại khác, nên chưa thể đạt trước khi "
                "các loại đó được xử lý xong.",
            ),
            _t(
                "Close the other risk types first, then decide this one at the Duties step.",
                "Xử lý xong các loại rủi ro khác trước, rồi quyết định loại này ở bước Nghĩa vụ.",
            ),
            owner,
            (dim_id,),
        )
        it["finding_ids"] = [r[1] for r in rows]
        out.append(it)
    return out


def _person_item(dim_id: str, fid: str) -> dict[str, Any]:
    it = _item(
        "person_decides",
        "low",
        "open",
        _t(
            "No automated test covers this risk type. A person decides it.",
            "Không có kiểm tra tự động nào bao phủ loại rủi ro này. Một người sẽ quyết định.",
        ),
        _t(
            "The result depends on a person's judgement; no tool can pass this type alone.",
            "Kết quả phụ thuộc vào đánh giá của con người; không công cụ nào tự đạt được loại này.",
        ),
        _t(
            "Review the duties of this AI system and record the decision.",
            "Rà soát các nghĩa vụ của hệ thống AI này và ghi lại quyết định.",
        ),
        "legal" if dim_id == "legal_compliance" else "risk_team",
        (dim_id,),
    )
    it["finding_ids"] = [fid]
    return it


def _norm_text(v: Any) -> dict[str, str] | None:
    if (
        isinstance(v, Mapping)
        and isinstance(v.get("en"), str)
        and isinstance(v.get("vi"), str)
        and v["en"].strip()
        and v["vi"].strip()
    ):
        return {"en": v["en"], "vi": v["vi"]}
    return None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:48] or "check"


def _evidence_refs(finding: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for e in finding.get("evidence") or []:
        if isinstance(e, Mapping) and e.get("file") and e.get("line"):
            out.append(f"{e['file']}:{e['line']}")
    return out[:8]


def _agent_item(
    dim_id: str, finding: Mapping[str, Any], check: Mapping[str, Any] | None
) -> dict[str, Any]:
    """An executive item for the finding of a factory agent: the ``executive`` block of the
    checklist item when it has one, else a generic text from the agent's own rationale."""
    cid = str(finding.get("checklist_id") or "check")
    verdict = str(finding.get("verdict"))
    fail = verdict == "fail"
    sev = str((check or {}).get("severity") or "medium")
    if sev not in SEVERITIES:
        sev = "medium"
    block = (check or {}).get("executive")
    rationale = " ".join(str(finding.get("rationale") or "").split())[:240]
    owner = DIM_OWNER.get(dim_id, "risk_team")
    if isinstance(block, Mapping):
        key = str(block.get("key") or "")
        head = _norm_text(block.get("headline_fail" if fail else "headline_open"))
        impact = _norm_text(block.get("impact"))
        action = _norm_text(block.get("action"))
        bowner = str(block.get("owner") or "")
        if key and head and impact and action:
            it = _item(
                key,
                sev,
                "fail" if fail else "open",
                head,
                impact,
                action,
                bowner if bowner in OWNERS else owner,
                (dim_id,),
                _evidence_refs(finding),
            )
            it["finding_ids"] = [str(finding.get("finding_id"))]
            return it
    it = _item(
        f"check_{_slug(cid)}",
        sev,
        "fail" if fail else "open",
        _t(
            rationale or f"Check {cid} did not pass.",
            f"Kiểm tra {cid} {'không đạt' if fail else 'chưa có kết luận'}"
            + (f": {rationale}" if rationale else "."),
        ),
        _t(
            "This check did not pass, so the risk type cannot be passed."
            if fail
            else "The agent could not answer this check from the evidence it had, so the risk "
            "type stays open.",
            "Kiểm tra này không đạt, nên loại rủi ro chưa thể đạt."
            if fail
            else "Tác tử chưa trả lời được kiểm tra này từ bằng chứng hiện có, nên loại rủi ro "
            "vẫn còn mở.",
        ),
        _t(
            "A person reviews the evidence and decides.",
            "Một người xem lại bằng chứng và quyết định.",
        ),
        owner,
        (dim_id,),
        _evidence_refs(finding),
    )
    it["finding_ids"] = [str(finding.get("finding_id"))]
    return it


def _merge(a: dict[str, Any], b: dict[str, Any]) -> None:
    """Fold item ``b`` into ``a`` (same key): the worse status and severity, all ids and refs.
    The text of ``a`` (the one made from the facts) stays."""
    if _STATUS_RANK[b["status"]] < _STATUS_RANK[a["status"]]:
        a["status"] = b["status"]
    if _SEV_RANK[b["severity"]] < _SEV_RANK[a["severity"]]:
        a["severity"] = b["severity"]
    for k in ("finding_ids", "fact_refs"):
        for x in b[k]:
            if x not in a[k]:
                a[k].append(x)


def _rating(items: Sequence[Mapping[str, Any]], gaps: set[str], has_findings: bool) -> str:
    sev = [
        i["severity"]
        for i in items
        if i["status"] == "fail" or (i["status"] == "open" and i["key"] not in gaps)
    ]
    if sev:
        return min(sev, key=lambda s: _SEV_RANK[s])
    if items:
        return "open"
    return "clear" if has_findings else "open"


def _bottom_line(
    rating: str, items: Sequence[Mapping[str, Any]], has_findings: bool, passed: int
) -> dict[str, str]:
    if not items:
        if has_findings and passed:
            return _t(
                "No problem found: every check that ran passed.",
                "Không thấy vấn đề: mọi kiểm tra đã chạy đều đạt.",
            )
        if has_findings:
            return _t(
                "No check applies to this risk type.",
                "Không có kiểm tra nào áp dụng cho loại rủi ro này.",
            )
        return _t(
            "There is no result for this risk type yet.",
            "Chưa có kết quả cho loại rủi ro này.",
        )
    top = items[0]
    more = len(items) - 1
    en = top["headline"]["en"].rstrip(".")
    vi = top["headline"]["vi"].rstrip(".")
    if more:
        en += f"; {more} more {_n(more, 'point needs', 'points need')} attention"
        vi += f"; còn {more} điểm khác cần chú ý"
    del rating
    return _t(en + ".", vi + ".")


def _mask(text: str) -> str:
    from supervisor.onboard import agent_log

    return agent_log.clean(text, MAX_TEXT)


def _mask_text(d: Mapping[str, str]) -> dict[str, str]:
    return {"en": _mask(d["en"]), "vi": _mask(d["vi"])}


def build(
    dim_id: str,
    report: Mapping[str, Any],
    facts: Mapping[str, Any] | None,
    system: Mapping[str, Any] | None,
    definition: Mapping[str, Any] | None = None,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """The ``executive_v1`` document of one risk type (Layer A: pure, deterministic, no network).
    Merges the observations of the code scan that belong to the type with the findings of the
    report, drops the duplicates by key, ranks by status then severity and keeps at most six."""
    findings = [f for f in (report.get("findings") or []) if isinstance(f, Mapping)]
    checks: dict[str, Mapping[str, Any]] = {}
    for c in (definition or {}).get("checklist") or []:
        if isinstance(c, Mapping) and c.get("id"):
            checks[str(c["id"])] = c

    cands: list[dict[str, Any]] = []
    for o in observations(facts, system):
        if dim_id in o["dims"]:
            o = dict(o)
            o["owner"] = (o.pop("owner_by_dim", {}) or {}).get(dim_id, o["owner"])
            o.pop("dims", None)
            cands.append(o)

    missing: list[str] = []
    missing_f: list[str] = []
    states: list[str] = []
    failed: list[str] = []
    failed_f: list[str] = []
    reads_fail: list[tuple[str, str]] = []
    reads_open: list[tuple[str, str]] = []
    person: str | None = None
    required = _required_ids(dim_id)
    passed = 0
    for f in findings:
        verdict = str(f.get("verdict"))
        cid = str(f.get("checklist_id") or "")
        fid = str(f.get("finding_id") or cid)
        if verdict == "pass":
            passed += 1
            continue
        if verdict not in ("fail", "question"):
            continue
        kind, _, rest = cid.partition(":")
        bkey = str(((checks.get(cid) or {}).get("executive") or {}).get("key") or "")
        if bkey.startswith("pack_") and verdict in ("fail", "question"):
            # a factory item that reads one test result joins the one tests line of the type
            kind, rest = "pack", bkey[len("pack_") :]
        if kind not in ("pack", "monitor", "reads", "person"):
            cands.append(_agent_item(dim_id, f, checks.get(cid)))
        elif kind in ("pack", "monitor"):
            if required and not required.get(rest, True) and verdict == "question":
                continue
            if verdict == "fail":
                failed.append(rest)
                failed_f.append(fid)
            else:
                missing.append(rest)
                missing_f.append(fid)
                states.append(_state_of(str(f.get("rationale") or "")))
        elif kind == "reads":
            (reads_fail if verdict == "fail" else reads_open).append((rest, fid))
        elif kind == "person":
            person = fid
    if failed:
        cands.append(_test_item(dim_id, failed, True, [], failed_f))
    if missing:
        cands.append(_test_item(dim_id, missing, False, states, missing_f))
    cands.extend(_reads_items(dim_id, reads_fail, reads_open))
    if person is not None:
        cands.append(_person_item(dim_id, person))

    # de-duplicate by key (the first item, made from the facts, keeps its text)
    by_key: dict[str, dict[str, Any]] = {}
    for it in cands:
        if it["key"] in by_key:
            _merge(by_key[it["key"]], it)
        else:
            by_key[it["key"]] = it
    for src, dst in FOLDED_INTO.items():
        if src in by_key and dst in by_key:
            _merge(by_key[dst], by_key.pop(src))
    gaps = {
        k
        for k in by_key
        if k in GAP_KEYS or (k.startswith("check_") and by_key[k]["status"] == "open")
    }
    ranked = sorted(
        enumerate(by_key.values()),
        key=lambda p: (_STATUS_RANK[p[1]["status"]], _SEV_RANK[p[1]["severity"]], p[0]),
    )
    items = [it for _, it in ranked][:MAX_ITEMS]
    rating = _rating(items, gaps, bool(findings))
    bottom = _bottom_line(rating, items, bool(findings), passed)
    out_items = []
    for it in items:
        out_items.append(
            {
                "key": it["key"],
                "severity": it["severity"],
                "status": it["status"],
                "headline": _mask_text(it["headline"]),
                "impact": _mask_text(it["impact"]),
                "action": _mask_text(it["action"]),
                "owner": it["owner"] if it["owner"] in OWNERS else "risk_team",
                "finding_ids": [str(x)[:64] for x in it["finding_ids"]][:40],
                "fact_refs": [str(x)[:320] for x in it["fact_refs"]][:8],
            }
        )
    return {
        "version": VERSION,
        "dimension_id": dim_id,
        "rating": rating,
        "bottom_line": _mask_text(bottom),
        "items": out_items,
        "writer": "rules",
        "created_at": str(now or report.get("created_at") or ""),
    }


# ------------------------------------------------------------------------------ Layer B

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_TOKEN = re.compile(r"[A-Za-z_][\w./-]*[\w]|[A-Za-z_]")
_QUOTED = re.compile(r"'([^']{1,80})'|\"([^\"]{1,80})\"|`([^`]{1,80})`")
_NAMELIKE = re.compile(r"_|/|\.[A-Za-z]{1,5}$|\d|[a-z][A-Z]")
# Absolute claims that Layer A does not make; a rewrite may not add one.
_BANNED = (
    "illegal",
    "unlawful",
    "breach",
    "violat",
    "non-complian",
    "noncomplian",
    "guarantee",
    "definitely",
    "certainly",
    "proves",
    "bất hợp pháp",
    "vi phạm",
    "chắc chắn",
    "đảm bảo tuyệt đối",
)


def _facts_in(text: str) -> set[str]:
    """Numbers, quoted spans and name-like tokens (ids, files, names with digits)."""
    out = set(_NUM.findall(text))
    for m in _QUOTED.finditer(text):
        out.add(next(g for g in m.groups() if g).lower())
    for tok in _TOKEN.findall(text):
        t = tok.strip(".,;:()'\"`")
        if len(t) > 2 and _NAMELIKE.search(t) and not _NUM.fullmatch(t):
            out.add(t.lower())
    return out


def _item_text(it: Mapping[str, Any]) -> list[str]:
    parts: list[str] = [it["key"]]
    for k in ("headline", "impact", "action"):
        parts += [it[k]["en"], it[k]["vi"]]
    return parts


def _allowed_text(doc: Mapping[str, Any], item: Mapping[str, Any] | None = None) -> str:
    """The Layer A text a reworded line may draw its numbers and names from: the text of its own
    item, or for the bottom line the bottom line and the text of all items."""
    if item is not None:
        return "\n".join(_item_text(item))
    parts: list[str] = [doc["bottom_line"]["en"], doc["bottom_line"]["vi"]]
    for it in doc["items"]:
        parts += _item_text(it)
    return "\n".join(parts)


def line_ok(new: Any, old_line: str, allowed_text: str) -> bool:
    """True when a reworded line may replace the Layer A line: a non-empty single line that adds
    no number, quoted id, name or file that Layer A text lacks and no absolute claim."""
    if not isinstance(new, str):
        return False
    s = " ".join(new.split())
    if not s or len(s) > MAX_TEXT or "\n" in new.strip():
        return False
    allowed = _facts_in(allowed_text)
    if not _facts_in(s) <= allowed:
        return False
    low, base = s.lower(), (allowed_text + old_line).lower()
    return not any(b in low and b not in base for b in _BANNED)


_SYSTEM_PROMPT = (
    "You rewrite assessment findings for a senior manager at a Vietnamese bank. For each item "
    "you get an English and a Vietnamese headline and impact, and a bottom line. Rewrite them in "
    "short executive language: the headline says what was found, the impact says what it means "
    "for the bank. Rules: keep every key; keep every number, identifier, field name and file "
    "name exactly; add none; add no new fact, cause or claim; a test that was not run is not a "
    "proof of a weakness; do not use words that call something illegal or a breach; one sentence "
    "of at most 30 words per line; plain business words, no jargon; write the Vietnamese as a "
    "Vietnamese bank manager would write it, not word by word. Do not mention these rules."
)


def _schema(keys: Sequence[str]) -> dict[str, Any]:
    pair = {
        "type": "object",
        "additionalProperties": False,
        "required": ["en", "vi"],
        "properties": {"en": {"type": "string"}, "vi": {"type": "string"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["bottom_line", "items"],
        "properties": {
            "bottom_line": pair,
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["key", "headline", "impact"],
                    "properties": {
                        "key": {"type": "string", "enum": list(keys)},
                        "headline": pair,
                        "impact": pair,
                    },
                },
            },
        },
    }


def rewrite(
    doc: Mapping[str, Any], model: Any, timeout_s: float = CALL_TIMEOUT_S
) -> dict[str, Any]:
    """Layer B: one structured call that rewords the headline, impact and bottom line of ``doc``.
    Returns a new document; ``doc`` itself when the call fails or nothing passes the check.
    Never changes a key, a status, a severity, an owner, an action or the rating."""
    out = json.loads(json.dumps(doc))
    if not out.get("items"):
        return out
    keys = [it["key"] for it in out["items"]]
    payload = {
        "bottom_line": out["bottom_line"],
        "items": [
            {"key": it["key"], "headline": it["headline"], "impact": it["impact"]}
            for it in out["items"]
        ],
    }
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        reply = model.complete_json(messages, _schema(keys), timeout_s)
    except Exception as exc:  # noqa: BLE001 - any failure leaves the Layer A text
        log.info("executive rewrite failed: %s", type(exc).__name__)
        return out
    if not isinstance(reply, Mapping):
        return out
    changed = 0

    def take(target: dict[str, str], new: Any, allowed: str) -> None:
        nonlocal changed
        if not isinstance(new, Mapping):
            return
        for lang in ("en", "vi"):
            cand = new.get(lang)
            if line_ok(cand, target[lang], allowed):
                text = _mask(" ".join(str(cand).split()))
                if text and text != target[lang]:
                    target[lang] = text
                    changed += 1

    take(out["bottom_line"], reply.get("bottom_line"), _allowed_text(out))
    by_key = {it["key"]: it for it in out["items"]}
    seen: set[str] = set()
    for r in reply.get("items") or []:
        if not isinstance(r, Mapping) or r.get("key") not in by_key or r["key"] in seen:
            continue
        seen.add(str(r["key"]))
        allowed = _allowed_text(out, by_key[r["key"]])
        take(by_key[r["key"]]["headline"], r.get("headline"), allowed)
        take(by_key[r["key"]]["impact"], r.get("impact"), allowed)
    if changed:
        out["writer"] = "mock" if getattr(model, "is_mock", False) else f"ai:{model.model_id}"
    return out


# ------------------------------------------------------------------------------ storage


def _path(dir_path: Path | str, dim_id: str) -> Path:
    if dim_id not in rd.DIMENSION_IDS:
        raise ValueError(f"unknown risk type: {dim_id[:40]}")
    return Path(dir_path) / f"{dim_id}.exec.json"


def write(dir_path: Path | str, doc: Mapping[str, Any]) -> str:
    """Store ``doc`` as ``<dir>/<dimension_id>.exec.json`` (sorted keys); returns the path."""
    path = _path(dir_path, str(doc["dimension_id"]))
    raw = json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)
    return str(path)


def valid(doc: Any) -> bool:
    """True for a document of the executive_v1 shape (what the console may show)."""
    if not isinstance(doc, Mapping) or doc.get("version") != VERSION:
        return False
    if doc.get("rating") not in RATINGS or _norm_text(doc.get("bottom_line")) is None:
        return False
    if not isinstance(doc.get("writer"), str) or not isinstance(doc.get("items"), list):
        return False
    for it in doc["items"]:
        if not isinstance(it, Mapping) or it.get("severity") not in SEVERITIES:
            return False
        if it.get("status") not in STATUSES or not isinstance(it.get("key"), str):
            return False
        if not all(_norm_text(it.get(k)) for k in ("headline", "impact", "action")):
            return False
    return True


def read(dir_path: Path | str, dim_id: str) -> dict[str, Any] | None:
    """The stored document of a risk type, or ``None`` (no file, unreadable, or not valid)."""
    try:
        doc = json.loads(_path(dir_path, dim_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if valid(doc) and doc.get("dimension_id") == dim_id else None


# ------------------------------------------------------------------------------ the hook


def enabled(settings: Any) -> bool:
    return bool(getattr(settings, "orch_exec_findings", False))


def after_report(
    ctx: Any,
    system: Mapping[str, Any],
    facts: Mapping[str, Any] | None,
    dim_id: str,
    report: Mapping[str, Any],
    out_dir: Path,
    definition: Mapping[str, Any] | None = None,
) -> None:
    """Called by the orchestrator after a report is stored. Off: does nothing. On: builds the
    executive findings (Layer A), optionally rewrites them (Layer B) and stores the sidecar.
    Never raises: a failure here must not fail the run."""
    settings = ctx.settings
    if not enabled(settings):
        return
    try:
        doc = build(dim_id, report, facts, system, definition)
        if getattr(settings, "orch_exec_llm", False) and getattr(settings, "llm_base_url", ""):
            try:
                from supervisor.adapters.factory import make_chat_model

                doc = rewrite(doc, make_chat_model(settings))
            except Exception as exc:  # noqa: BLE001 - Layer A text stays
                log.info("executive rewrite skipped: %s", type(exc).__name__)
        write(out_dir, doc)
    except Exception as exc:  # noqa: BLE001 - never fail the run
        log.warning("executive findings not stored for %s: %s", dim_id, type(exc).__name__)


__all__ = [
    "FACT_KEYS",
    "REPORT_KEYS",
    "TESTS",
    "after_report",
    "build",
    "enabled",
    "line_ok",
    "observations",
    "read",
    "rewrite",
    "valid",
    "write",
]
