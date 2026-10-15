"""Readiness score: seven areas, integer arithmetic only, published rubric.

    area            weight  points
    tracing           20    otel tracing found = 20; mlflow tracing only = 12; none = 0
    gate_coverage     30    30 * covered // gated (no gated tool = 30); gated = money, credit,
                          pii_export or a tool with a write side effect; covered = a gate in
                          the function or a central dispatch gate in the repo
    tool_inventory    15    15 * resolved // tools (no tool found = 0)
    money_args        10    10 * earned // (10 * money tools) (no money tool = 10)
    model_identity    10    10 * known family // LLM call sites (no call site = 10)
    manifest          10    a Supervisor-style agent manifest = 10, else 0
    hygiene            5    5 when no secret was redacted and no injection line was flagged

Every input comes from the Inventory (Discover) and from ``analysis.ToolFacts`` (an ``ast``
read of the tool definitions). No input comes from a language model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from supervisor.advisory.integration.analysis import ToolFacts, needs_gate
from supervisor.advisory.integration.models import AreaScore, Readiness
from supervisor.onboard.models import Inventory


@dataclass(frozen=True)
class RubricArea:
    id: str
    weight: int
    en: str
    vi: str


RUBRIC: tuple[RubricArea, ...] = (
    RubricArea(
        "tracing",
        20,
        "OpenTelemetry tracing found = 20; MLflow tracing only = 12; none = 0",
        "Có tracing OpenTelemetry = 20; chỉ có tracing MLflow = 12; không có = 0",
    ),
    RubricArea(
        "gate_coverage",
        30,
        "30 x (money, credit, pii_export and writing tools covered by a Supervisor gate in "
        "the function or a central dispatch gate) / (those tools); no such tool = 30",
        "30 x (công cụ money, credit, pii_export hoặc có ghi dữ liệu, đã có cổng Supervisor "
        "trong hàm hoặc cổng điều phối trung tâm) / (số công cụ đó); không có = 30",
    ),
    RubricArea(
        "tool_inventory",
        15,
        "15 x (tools whose implementing function was found) / (all tools); no tool found = 0",
        "15 x (công cụ tìm thấy hàm cài đặt) / (tất cả công cụ); không có công cụ = 0",
    ),
    RubricArea(
        "money_args",
        10,
        "per money tool: 5 for an amount argument not annotated float, 5 for a "
        "destination argument; no money tool = 10",
        "mỗi công cụ money: 5 nếu có tham số số tiền không khai báo float, 5 nếu có "
        "tham số đích; không có công cụ money = 10",
    ),
    RubricArea(
        "model_identity",
        10,
        "10 x (LLM call sites with a known model family) / (all call sites); no call site = 10",
        "10 x (điểm gọi LLM có họ mô hình rõ) / (tất cả điểm gọi); không có điểm gọi = 10",
    ),
    RubricArea(
        "manifest",
        10,
        "a Supervisor-style agent manifest is in the repo = 10, else 0",
        "Có manifest tác tử kiểu Supervisor trong repo = 10, nếu không = 0",
    ),
    RubricArea(
        "hygiene",
        5,
        "5 when no secret was redacted and no prompt-injection line was flagged",
        "5 khi không có bí mật bị che và không có dòng nghi tiêm lệnh nào bị gắn cờ",
    ),
)
WEIGHTS: dict[str, int] = {a.id: a.weight for a in RUBRIC}
assert sum(WEIGHTS.values()) == 100  # noqa: S101 - the published rubric adds up to 100


def _area(id_: str, points: int, inputs: dict[str, int], reason: str) -> AreaScore:
    return AreaScore(id=id_, weight=WEIGHTS[id_], points=points, inputs=inputs, reason=reason)


def score(inv: Inventory, facts: Mapping[str, ToolFacts] | None = None) -> Readiness:
    """Readiness of ``inv``. ``facts`` maps tool name to its static facts; a tool with no
    entry counts as 'not gated, amount as Discover declared it'."""
    facts = facts or {}
    areas: list[AreaScore] = []

    # tracing ----------------------------------------------------------------------
    otel, mlflow = "otel" in inv.tracing, "mlflow" in inv.tracing
    pts = 20 if otel else 12 if mlflow else 0
    reason = (
        "OpenTelemetry tracing found"
        if otel
        else "MLflow tracing only: spans do not reach the Supervisor recorder"
        if mlflow
        else "no tracing found"
    )
    areas.append(_area("tracing", pts, {"otel": int(otel), "mlflow": int(mlflow)}, reason))

    # gate_coverage ----------------------------------------------------------------
    gated = [t for t in inv.tools if needs_gate(t)]
    covered = sum(1 for t in gated if facts.get(t.name, ToolFacts()).gated)
    pts = 30 * covered // len(gated) if gated else 30
    via = next(
        (f.gate_via for t in gated if (f := facts.get(t.name)) and f.gated and f.gate_via), None
    )
    reason = (
        "no money, credit, pii_export or writing tool"
        if not gated
        else f"{covered} of {len(gated)} money, credit, pii_export or writing tools carry a gate"
        + (f" ({via})" if via else "")
    )
    areas.append(
        _area("gate_coverage", pts, {"gated_tools": len(gated), "covered": covered}, reason)
    )

    # tool_inventory ---------------------------------------------------------------
    resolved = sum(1 for t in inv.tools if t.definition is not None)
    pts = 15 * resolved // len(inv.tools) if inv.tools else 0
    reason = (
        "no tool found"
        if not inv.tools
        else f"{resolved} of {len(inv.tools)} tools have a definition found in code"
    )
    areas.append(
        _area("tool_inventory", pts, {"tools": len(inv.tools), "resolved": resolved}, reason)
    )

    # money_args -------------------------------------------------------------------
    money = [t for t in inv.tools if t.risk_class == "money"]
    earned = 0
    for t in money:
        f = facts.get(t.name, ToolFacts())
        amount = f.amount_arg or t.amount_arg
        if amount and not f.amount_float:
            earned += 5
        if t.destination_arg:
            earned += 5
    pts = 10 * earned // (10 * len(money)) if money else 10
    reason = (
        "no money tool"
        if not money
        else f"{earned} of {10 * len(money)} points: amount (not float) and destination arguments"
    )
    areas.append(_area("money_args", pts, {"money_tools": len(money), "earned": earned}, reason))

    # model_identity ---------------------------------------------------------------
    known = sum(1 for c in inv.llm_calls if c.family != "unknown")
    pts = 10 * known // len(inv.llm_calls) if inv.llm_calls else 10
    reason = (
        "no LLM call site"
        if not inv.llm_calls
        else f"{known} of {len(inv.llm_calls)} LLM call sites name a known model family"
    )
    areas.append(
        _area("model_identity", pts, {"call_sites": len(inv.llm_calls), "known": known}, reason)
    )

    # manifest ---------------------------------------------------------------------
    has_manifest = inv.manifest_file is not None
    areas.append(
        _area(
            "manifest",
            10 if has_manifest else 0,
            {"manifest": int(has_manifest)},
            "agent manifest found" if has_manifest else "no Supervisor-style agent manifest",
        )
    )

    # hygiene ----------------------------------------------------------------------
    secrets = secrets_count(inv)
    injected = len(inv.injection_refs)
    clean = secrets == 0 and injected == 0
    areas.append(
        _area(
            "hygiene",
            5 if clean else 0,
            {"secrets": secrets, "injection_lines": injected},
            "no secret and no flagged line"
            if clean
            else f"{secrets} secret(s) redacted, {injected} line(s) flagged as possible injection",
        )
    )
    return Readiness(total=sum(a.points for a in areas), areas=areas)


def secrets_count(inv: Inventory) -> int:
    """Secrets the scrubber redacted (the larger of the scrubber total and the marker lines)."""
    raw = inv.scrub.get("secrets_redacted", 0) if isinstance(inv.scrub, dict) else 0
    total = raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
    return max(total, len(inv.secret_refs))
