"""Advice = report + patches, built from the onboarding stages of one target repo.

``build_advice`` takes the stages that ``run_onboarding`` already computed. ``advise`` runs
Discover (with the secret scrubber), Understand and Plan itself. Advisory only: no git, no
write into the target.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.repo import LocalGitRepoReader, RepoReadError
from supervisor.advisory.integration.analysis import needs_gate
from supervisor.advisory.integration.models import (
    AssuranceItem,
    CatalogueItem,
    DataAccessFound,
    Found,
    FrameworkFound,
    GateSite,
    IntegrationReport,
    LlmCallFound,
    Needed,
    PatchRef,
    PiiFound,
    SemconvOp,
    SettingNeeded,
    ToolFound,
)
from supervisor.advisory.integration.narrative import make_narrative
from supervisor.advisory.integration.patches import (
    Patch,
    PatchPlan,
    decorator_text,
    env_block,
    is_mcp_server,
    plan_patches,
)
from supervisor.advisory.integration.scoring import score, secrets_count
from supervisor.catalogue import Catalogue, load_catalogue
from supervisor.core.ports import ChatModel
from supervisor.onboard.discover import discover
from supervisor.onboard.models import (
    AgentProfile,
    Inventory,
    MonitoringPlan,
    RemediationPlaybook,
)
from supervisor.onboard.plan import plan
from supervisor.onboard.scrub import Scrubber
from supervisor.onboard.understand import understand
from supervisor.recorder import semconv

_DEMOGRAPHIC_PII = frozenset(
    {
        "full_name",
        "customer_name",
        "ho_ten",
        "dob",
        "date_of_birth",
        "ngay_sinh",
        "income",
        "monthly_income",
        "salary",
        "thu_nhap",
        "address",
        "dia_chi",
    }
)
_SETTING_PURPOSE = {
    "SUPERVISOR_GATE_URL": "Where the gate hook sends tool checks (HTTP gate).",
    "SUPERVISOR_TRACING": "1 turns on the Supervisor tracer provider in the hook module.",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "OTLP base URL of the Supervisor recorder.",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "OTLP traces URL: the Supervisor /v1/traces route.",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "The recorder reads OTLP JSON only (http/json).",
    "OTEL_SERVICE_NAME": "Service name; use the agent id.",
}


@dataclass
class Advice:
    report: IntegrationReport
    patches: list[Patch]
    target: Path | None = None  # where the advice was made (never written to)


def patch_filename(index: int, patch: Patch) -> str:
    """``patches/NN-slug.patch`` (NN starts at 01)."""
    slug = "".join(c if c.isalnum() else "-" for c in patch.path.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"patches/{index:02d}-{slug[:60].strip('-')}.patch"


def _ref(ev: object) -> str | None:
    return f"{ev.file}:{ev.line}" if ev is not None else None  # type: ignore[attr-defined]


def _semconv(inv: Inventory) -> list[SemconvOp]:
    ops: list[SemconvOp] = []
    sup = list(semconv.SUPERVISOR_ATTRS)
    money = any(t.risk_class in ("money", "credit") for t in inv.tools)
    if not money:
        sup = [a for a in sup if a not in ("supervisor.amount_minor", "supervisor.currency")]
    ops.append(
        SemconvOp(
            operation="invoke_agent",
            attributes=[*semconv.EMIT["invoke_agent"], *sup],
            note="one span per agent run; service.name and gen_ai.agent.id = " + inv.agent_id,
        )
    )
    if inv.llm_calls:
        ops.append(SemconvOp(operation="chat", attributes=list(semconv.EMIT["chat"])))
    if inv.tools:
        ops.append(
            SemconvOp(
                operation="execute_tool",
                attributes=[*semconv.EMIT["execute_tool"], *sup],
                note="supervisor.args_hash is SHA-256 of the canonical arguments; "
                + (
                    "supervisor.amount_minor is an integer"
                    if money
                    else "no money or credit tool: no amount"
                ),
            )
        )
    return ops


def _test_plan(inv: Inventory) -> list[AssuranceItem]:
    llm = bool(inv.llm_calls)
    non_read = [t for t in inv.tools if t.risk_class != "read_only"]
    credit = any(t.risk_class == "credit" for t in inv.tools)
    pii = set(inv.pii_fields) | set(inv.pii_identifiers)
    rows: list[tuple[str, bool, str]] = [
        ("accuracy", llm or bool(inv.tools), "the agent answers or acts on customer requests"),
        (
            "hallucination",
            llm or "free_text_output" in inv.features,
            "the agent writes text with a language model",
        ),
        (
            "bias_fairness",
            credit or "decision_tool" in inv.features or bool(pii & _DEMOGRAPHIC_PII),
            "the agent records credit decisions or handles personal attributes",
        ),
        (
            "dependency_risk",
            llm
            or bool(inv.mcp_servers)
            or any(d.kind in ("http", "bank_api") for d in inv.data_access),
            "the agent depends on a model provider, an MCP server or an external API",
        ),
        (
            "adversarial_security",
            bool(non_read) or llm or bool(inv.injection_refs),
            "the agent has tools with side effects or reads untrusted text",
        ),
        (
            "robustness",
            bool(inv.tools) or bool(inv.data_access),
            "the agent calls tools and data sources that can fail",
        ),
    ]
    packs = assurance_packs()
    return [
        AssuranceItem(
            dimension=d,  # type: ignore[arg-type]
            reason=r,
            packs=packs.get(_PACK_DIMENSION.get(d, d), []),
            command=(
                f"python -m supervisor.assurance run {_PACK_DIMENSION.get(d, d)} "
                f"--target agent:{inv.agent_id} --repo <repo folder> --out out\\assurance"
            ),
        )
        for d, ok, r in rows
        if ok
    ]


# Our dimension names -> WP17 pack dimension names.
_PACK_DIMENSION = {"dependency_risk": "dependency", "adversarial_security": "security"}
PACKS_DIR = Path(__file__).resolve().parents[2] / "assurance" / "packs"


def assurance_packs(packs_dir: Path = PACKS_DIR) -> dict[str, list[str]]:
    """WP17 pack ids per pack dimension, only packs that can target an agent. Read as
    data (YAML id / dimension / targets); empty when the assurance packs are absent."""
    out: dict[str, list[str]] = {}
    if not packs_dir.is_dir():
        return out
    for f in sorted(packs_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(doc, dict) or "agent" not in (doc.get("targets") or []):
            continue
        pid, dim = doc.get("id"), doc.get("dimension")
        if isinstance(pid, str) and isinstance(dim, str):
            out.setdefault(dim, []).append(pid)
    return {k: sorted(v) for k, v in out.items()}


def _found(inv: Inventory, pplan: PatchPlan) -> Found:
    tools = []
    for t in inv.tools:
        f = pplan.facts[t.name]
        tools.append(
            ToolFound(
                name=t.name,
                risk_class=t.risk_class,
                risk_source=t.risk_source,
                side_effects=list(t.side_effects),
                amount_arg=f.amount_arg,
                destination_arg=t.destination_arg,
                defined_at=_ref(t.definition),
                shape=f.shape,  # type: ignore[arg-type]
                gated=f.gated,
            )
        )
    pii: dict[str, str] = {}
    for name, ev in sorted({**inv.pii_identifiers, **inv.pii_fields}.items()):
        pii.setdefault(name, f"{ev.file}:{ev.line}")
    return Found(
        framework=FrameworkFound(name=inv.framework, evidence=_ref(inv.framework_evidence)),
        llm_calls=[
            LlmCallFound(
                provider=c.provider,
                family=c.family,
                model=c.model,
                via=c.via,
                at=f"{c.evidence.file}:{c.evidence.line}",
            )
            for c in inv.llm_calls
        ],
        tools=tools,
        data_access=[
            DataAccessFound(
                kind=d.kind,
                direction=d.direction,
                target=d.target,
                at=f"{d.evidence.file}:{d.evidence.line}",
            )
            for d in inv.data_access
        ],
        pii_fields=[PiiFound(name=n, at=at) for n, at in pii.items()],
        tracing=sorted(inv.tracing),
        mcp_server=is_mcp_server(inv),
        secrets_count=secrets_count(inv),
        injection_refs=sorted({f"{e.file}:{e.line}" for e in inv.injection_refs}),
    )


def build_advice(
    target: Path,
    inv: Inventory,
    profile: AgentProfile,
    mp: MonitoringPlan,
    playbook: RemediationPlaybook,
    *,
    chat: ChatModel | None = None,
) -> Advice:
    target = Path(target)
    pplan = plan_patches(target, inv, profile, mp, playbook)
    sites = []
    for t in inv.tools:
        if not needs_gate(t):
            continue
        mode, note = pplan.gate_modes[t.name]
        sites.append(
            GateSite(
                tool=t.name,
                risk_class=t.risk_class,
                at=_ref(t.definition),
                decorator=decorator_text(inv, t),
                mode=mode,  # type: ignore[arg-type]
                note=note,
            )
        )
    needed = Needed(
        semconv=_semconv(inv),
        gate_sites=sites,
        mcp_proxy=pplan.mcp_proxy,
        policy_yaml=pplan.policy_yaml,
        catalogue=[
            CatalogueItem(id=c.id, name=c.name, kind=c.kind, lane=c.lane)
            for c in mp.capabilities
            if c.status == "on"
        ],
        settings=[
            SettingNeeded(key=k, purpose=_SETTING_PURPOSE.get(k, ""), example=v)
            for k, v in env_block(inv)
        ],
        test_plan=_test_plan(inv),
        manual=pplan.manual,
    )
    report = IntegrationReport(
        agent_id=inv.agent_id,
        name=inv.name,
        version=inv.version,
        framework=inv.framework,
        found=_found(inv, pplan),
        needed=needed,
        readiness=score(inv, pplan.facts),
        patches=[
            PatchRef(
                path=p.path,
                kind=p.kind,
                description=p.description,
                file=patch_filename(i, p),
            )
            for i, p in enumerate(pplan.patches, start=1)
        ],
    )
    report.narrative = make_narrative(report, chat)
    return Advice(report=report, patches=pplan.patches, target=target)


def advise(
    target: str | Path,
    *,
    chat: ChatModel | None = None,
    catalogue: Catalogue | None = None,
) -> Advice:
    """Run Discover, Understand and Plan on ``target`` and build the advice. Read-only.

    The Understand stage uses a mock model when ``chat`` is None, so the profile is
    deterministic; ``chat`` also writes the narrative (None: no narrative)."""
    root = Path(target)
    if not root.is_dir():
        raise RepoReadError(f"target folder does not exist: {root}")
    disc = discover(LocalGitRepoReader(root), scrubber=Scrubber())
    profile = understand(disc, chat if chat is not None else MockChat(model_id="mock-advisory-v1"))
    mp, playbook = plan(disc.inventory, profile, catalogue or load_catalogue())
    return build_advice(root, disc.inventory, profile, mp, playbook, chat=chat)
