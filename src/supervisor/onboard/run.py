"""Orchestrator: run the six Onboard stages for one agent repository.

    python -m supervisor.onboard --target src/supervisor_agents/payments --out out\\payments

The Onboarding Agent (agent id ``onboarding_agent``) is registered in the configured
store and runs under Watch: its own tool calls (list, read, LLM, write, branch, red-team
sandbox) pass the real ``Gateway`` on ``self_policy.yaml``, become ``agent_event`` rows,
and its outputs are recorded on the evidence chain (lane ``agent:onboarding_agent``).

Artefacts in ``--out``: inventory.json, profile.json/md, plan.json/md, playbook.md,
policy.yaml, dashboard.json, alert_routes.yaml, pr_description.md, launch_report.json/md,
baseline.json, handover.json. The branch ``supervisor/onboard-<agent>`` is created in a
clone under ``--work-dir`` (default ``<out>/_work``); nothing is merged or pushed.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opentelemetry.trace import SpanKind

from supervisor.adapters.factory import Adapters, build_adapters, make_chat_model
from supervisor.adapters.repo import LocalGitRepoReader, RepoReadError
from supervisor.adapters.workspace import FixtureWorkspaceReader
from supervisor.catalogue import Catalogue, load_catalogue, write_coverage
from supervisor.config import Settings, load_settings
from supervisor.core.canonical import sha256_hex
from supervisor.core.ports import ChatModel, EvidenceSink, WorkspaceReader
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StaticPolicyProvider, load_policy_texts
from supervisor.onboard import render
from supervisor.onboard.agent import (
    AGENT_ID,
    AGENT_VERSION,
    SELF_POLICY,
    OnboardingAgent,
    WatchedRepoReader,
    self_manifest,
)
from supervisor.onboard.discover import discover
from supervisor.onboard.instrument import (
    branch_name,
    check_dirs,
    instrument,
    render_pr_description,
    validate_policy,
)
from supervisor.onboard.launch import Harness, launch
from supervisor.onboard.models import (
    AgentProfile,
    HandoverRecord,
    InstrumentResult,
    Inventory,
    LaunchReport,
    MonitoringPlan,
    RemediationPlaybook,
)
from supervisor.onboard.operate import handover
from supervisor.onboard.plan import plan
from supervisor.onboard.scrub import Scrubber
from supervisor.onboard.understand import SYSTEM_PROMPT, understand

ARTEFACTS = (
    "inventory.json",
    "profile.json",
    "profile.md",
    "plan.json",
    "plan.md",
    "playbook.md",
    "policy.yaml",
    "dashboard.json",
    "alert_routes.yaml",
    "pr_description.md",
    "launch_report.json",
    "launch_report.md",
    "baseline.json",
    "handover.json",
)
# WP14: written only when ONBOARD_COMPLIANCE_ENABLED=1 (not part of ARTEFACTS: off path unchanged)
COMPLIANCE_ARTEFACTS = (
    "compliance_matrix.json",
    "compliance_matrix.md",
    "compliance_matrix.html",
)


# Written only when assurance ran in Launch (ASSURANCE_LAUNCH_ENABLED); not in ARTEFACTS.
ASSURANCE_ARTEFACTS = ("assurance_report.md", "assurance_report.json")


@dataclass
class OnboardResult:
    run_id: str
    out_dir: Path
    inventory: Inventory
    profile: AgentProfile
    plan: MonitoringPlan
    playbook: RemediationPlaybook
    instrument: InstrumentResult
    launch: LaunchReport
    handover: HandoverRecord
    artefacts: dict[str, Path] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)


def _json(model: Any) -> str:
    data = model.model_dump(mode="json") if hasattr(model, "model_dump") else model
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _snapshot(ws: WorkspaceReader) -> FixtureWorkspaceReader:
    """Read the workspace once (inside one gated call) into a fixture reader."""
    data: dict[str, Any] = {"serving_endpoints": list(ws.list_serving_endpoints())}
    for name in ("list_apps", "lineage", "traces"):
        fn = getattr(ws, name, None)
        if callable(fn):
            key = "apps" if name == "list_apps" else name
            data[key] = list(fn())
    return FixtureWorkspaceReader(data)


def run_onboarding(
    target: str | Path,
    out_dir: str | Path,
    *,
    settings: Settings | None = None,
    adapters: Adapters | None = None,
    evidence: EvidenceSink | None = None,
    chat: ChatModel | None = None,
    workspace: WorkspaceReader | None = None,
    work_dir: str | Path | None = None,
    catalogue: Catalogue | None = None,
    harness: Harness | None = None,
    redteam: Sequence[Mapping[str, Any]] | None = None,
    echo: Callable[[str], None] | None = None,
) -> OnboardResult:
    target_path = Path(os.path.abspath(target))
    if not target_path.is_dir():
        raise RepoReadError(f"target folder does not exist: {target_path}")
    out = Path(os.path.abspath(out_dir))
    out.mkdir(parents=True, exist_ok=True)
    work = Path(os.path.abspath(work_dir)) if work_dir else out / "_work"
    check_dirs(target_path, out, work)
    lines: list[str] = []

    def say(line: str) -> None:
        lines.append(line)
        if echo is not None:
            echo(line)

    settings = settings or (adapters.settings if adapters else load_settings())
    owns = adapters is None
    adapters = adapters or build_adapters(settings)
    from supervisor.evidence.chain import build_chain_writer
    from supervisor.jobs import bootstrap_schema
    from supervisor.wiring import Runtime, register_agents
    from supervisor_agents.common import tracing

    chain = None
    gateway: Gateway | None = None
    provider = None
    try:
        if adapters.executor.dialect == "sqlite":
            bootstrap_schema.run(settings, adapters)
        tracing.set_args_hash_key(
            settings.args_hash_key.get_secret_value() if settings.args_hash_key else None
        )
        if evidence is None:
            chain = build_chain_writer(settings, adapters.tables, adapters.clock)
            evidence = chain
        self_policy = load_policy_texts(
            [(SELF_POLICY.name, SELF_POLICY.read_text(encoding="utf-8"))]
        )
        gateway = Gateway(
            StaticPolicyProvider(self_policy),
            adapters.tables,
            adapters.state,
            evidence,
            adapters.clock,
            args_hash_key=settings.args_hash_key.get_secret_value()
            if settings.args_hash_key
            else None,
            env=settings.supervisor_mode,
            state_cache_ttl_s=0,
        )
        chat = chat or make_chat_model(settings)
        runtime = Runtime(settings, adapters, self_policy, evidence, gateway, owns_adapters=False)  # type: ignore[arg-type]
        register_agents(
            runtime,
            [self_manifest(chat.family, chat.model_id)],
            prompt_hashes={AGENT_ID: sha256_hex(SYSTEM_PROMPT)},
        )
        say(f"[OK] registered {AGENT_ID}@{AGENT_VERSION} (runs under Watch, model {chat.model_id})")
        exporter = tracing.AgentEventExporter(adapters.tables, env=settings.supervisor_mode)
        provider = tracing.make_tracer_provider(exporter, service_name="supervisor-onboarding")
        run_id = uuid.uuid4().hex[:16]
        agent = OnboardingAgent(
            gateway,
            evidence,
            provider,
            adapters.clock,
            run_id=run_id,
            target_agent_id=target_path.name,
            env=settings.supervisor_mode,
        )
        tracer = provider.get_tracer("supervisor_onboard", AGENT_VERSION)
        with tracer.start_as_current_span(
            f"invoke_agent {AGENT_ID}",
            kind=SpanKind.INTERNAL,
            attributes={
                tracing.A_EVENT_TYPE: "message",
                tracing.A_AGENT_ID: AGENT_ID,
                tracing.A_AGENT_VERSION: AGENT_VERSION,
                tracing.A_ENV: settings.supervisor_mode,
                "gen_ai.operation.name": "invoke_agent",
                "supervisor.message.role": "user",
                tracing.A_ARGS_HASH: tracing.args_hash({"target": target_path.name}),
            },
        ) as root:
            result = _stages(
                agent,
                target_path,
                out,
                work,
                chat=chat,
                workspace=workspace,
                catalogue=catalogue,
                harness=harness,
                redteam=redteam,
                adapters=adapters,
                say=say,
            )
            root.set_attribute(tracing.A_STATUS, "ok")
        gateway.drain()
        result.lines = lines
        return result
    finally:
        if gateway is not None:
            gateway.close()
        if provider is not None:
            provider.shutdown()
        if chain is not None:
            chain.close()
        if owns:
            adapters.close()


def _compliance(
    inv: Inventory,
    profile: AgentProfile,
    mp: MonitoringPlan,
    texts: Mapping[str, str],
    chat: ChatModel,
    settings: Settings,
    write: Callable[[str, str, str], None],
    say: Callable[[str], None],
) -> None:
    from supervisor.advisory.compliance import from_onboard
    from supervisor.advisory.compliance.matrix import build_matrix
    from supervisor.advisory.compliance.render import to_html, to_json, to_markdown
    from supervisor.regkb import load_kb

    product = from_onboard(
        inv,
        profile,
        plan=mp,
        policy_texts=[("policy.yaml", texts["policy.yaml"])],
        basis="planned",
    )
    internal = Path(settings.regkb_internal_dir) if settings.regkb_internal_dir else None
    kb = load_kb(internal_dir=internal)
    matrix = build_matrix(kb, product, chat=chat)
    write("compliance_matrix.json", to_json(matrix), "comply")
    write("compliance_matrix.md", to_markdown(matrix), "comply")
    write("compliance_matrix.html", to_html(matrix), "comply")
    s = matrix.summary
    by = s["by_status"]
    say(
        f"[OK] compliance: {matrix.header.obligations} obligations, "
        f"{s['by_applies']['yes']} apply, {s['needs_answer']} need an answer, "
        f"{by['gap']} gap, {s['questions']} question(s), "
        f"Decision 33 {matrix.decision33.classification} (advisory; not legal advice)"
    )


def _stages(
    agent: OnboardingAgent,
    target: Path,
    out: Path,
    work: Path,
    *,
    chat: ChatModel,
    workspace: WorkspaceReader | None,
    catalogue: Catalogue | None,
    harness: Harness | None,
    redteam: Sequence[Mapping[str, Any]] | None,
    adapters: Adapters,
    say: Callable[[str], None],
) -> OnboardResult:
    paths: dict[str, Path] = {}

    def write(name: str, text: str, stage: str) -> None:
        paths[name] = agent.write_artifact(out, name, text, stage)

    # 1 Discover --------------------------------------------------------------------
    base_reader = LocalGitRepoReader(target)
    repo = WatchedRepoReader(base_reader, agent)
    ws = None
    if workspace is not None:
        ws = agent.call("list_workspace", {"kind": "snapshot"}, lambda: _snapshot(workspace))
    scrubber = Scrubber()
    disc = discover(repo, scrubber=scrubber, workspace=ws, revision=base_reader.revision())
    inv = disc.inventory
    agent.target_agent_id = inv.agent_id
    agent.record(
        "onboard_stage",
        f"{AGENT_ID}:{agent.run_id}:discover",
        {
            "stage": "discover",
            "files": len(inv.files),
            "tools": len(inv.tools),
            "prompts": len(inv.prompts),
            "secrets_redacted": scrubber.total,
        },
    )
    write("inventory.json", _json(inv), "discover")
    say(
        f"[OK] discover: {len(inv.files)} files, {len(inv.tools)} tools, "
        f"{len(inv.prompts)} prompts, {scrubber.total} secret(s) redacted"
    )

    # 2 Understand ------------------------------------------------------------------
    def llm_call(messages: Sequence[Mapping[str, str]], schema: Mapping[str, Any]) -> Any:
        chars = sum(len(m.get("content", "")) for m in messages)
        return agent.call(
            "call_llm",
            {"scrubbed": True, "chars": chars},
            lambda: chat.complete_json(messages, schema, 120.0),
        )

    profile = understand(disc, chat, llm_call=llm_call)
    agent.record(
        "onboard_stage",
        f"{AGENT_ID}:{agent.run_id}:understand",
        {
            "stage": "understand",
            "claims": len(profile.all_claims()),
            "decision33": profile.decision33.classification,
            "proposed_risk_tier": profile.proposed_risk_tier,
            "llm_mock": profile.llm.is_mock,
        },
    )
    write("profile.json", _json(profile), "understand")
    write("profile.md", render.profile_md(inv, profile), "understand")
    say(
        f"[OK] understand: Decision 33 {profile.decision33.classification} (proposal), "
        f"tier {profile.proposed_risk_tier}, {len(profile.weak_spots)} weak spot(s)"
    )

    # 3 Plan ------------------------------------------------------------------------
    mp, playbook = plan(inv, profile, catalogue or load_catalogue())
    write_coverage(adapters.state, mp.coverage)
    write("plan.json", _json(mp), "plan")
    write("plan.md", render.plan_md(mp), "plan")
    write("playbook.md", render.playbook_md(playbook), "plan")
    agent.record(
        "onboard_stage",
        f"{AGENT_ID}:{agent.run_id}:plan",
        {"stage": "plan", "capabilities_on": len(mp.on_ids), "rules": len(mp.rules)},
    )
    say(f"[OK] plan: {len(mp.on_ids)} capabilities on, {len(mp.rules)} rules")

    # 4 Instrument ------------------------------------------------------------------
    inst, texts = agent.call(
        "git_branch_commit",
        {"branch": branch_name(inv.agent_id), "files": 5},
        lambda: instrument(target, work, inv, profile, mp, playbook),
    )
    write("policy.yaml", texts["policy.yaml"], "instrument")
    write("dashboard.json", texts["dashboard.json"], "instrument")
    write("alert_routes.yaml", texts["alert_routes.yaml"], "instrument")
    say(
        f"[OK] instrument: branch {inst.branch} commit {inst.commit_sha[:12]} "
        f"({inst.mode}); never merged"
    )

    # 5 Launch ----------------------------------------------------------------------
    policy = validate_policy(texts["policy.yaml"])
    report = agent.call(
        "run_redteam_sandbox",
        {"agent": inv.agent_id, "mode": "shadow"},
        lambda: launch(policy, inv.agent_id, work, harness=harness, redteam=redteam),
    )
    write("launch_report.json", _json(report), "launch")
    write("launch_report.md", render.launch_md(report), "launch")
    write("baseline.json", _json(report.baseline), "launch")
    if report.assurance_enabled:
        write("assurance_report.md", render.assurance_md(report), "launch")
        write(
            "assurance_report.json",
            _json(
                {
                    "agent_id": report.agent_id,
                    "go": report.go,
                    "assurance_reasons": report.assurance_reasons,
                    "results": report.assurance,
                }
            ),
            "launch",
        )
    summary = {
        "decision": "GO" if report.go else "NO-GO",
        "catch_rate_bp": report.catch_rate_bp,
        "false_alarm_bp": report.false_alarm_bp,
        "rules_to_enforce_first": sum(
            1 for s in report.rule_switches if s.recommendation == "enforce"
        ),
    }
    write(
        "pr_description.md",
        render_pr_description(inv, profile, mp, inst, summary),
        "instrument",
    )
    say(
        f"[OK] launch report: {summary['decision']} catch {report.catch_rate_bp} bp, "
        f"false alarms {report.false_alarm_bp} bp ({report.rule_caught}/"
        f"{report.rule_expected} rule cases)"
    )

    # 5b Advise (WP15, off by default): integration report and patches, never applied --
    if adapters.settings.onboard_advisor_enabled:
        from supervisor.advisory.integration.advise import build_advice, patch_filename
        from supervisor.advisory.integration.render import render_html, render_json, render_md

        try:  # optional stage: a failure is reported, the run goes on
            advice = agent.call(
                "call_llm",  # narrative only; its input is the deterministic summary
                {"scrubbed": True, "stage": "advise"},
                lambda: build_advice(target, inv, profile, mp, playbook, chat=chat),
            )
        except Exception as exc:  # noqa: BLE001
            advice = None
            say(f"[SKIP] advise: {type(exc).__name__}: {str(exc)[:200]}")
        if advice is not None:
            write("integration_report.json", render_json(advice.report), "advise")
            write("integration_report.md", render_md(advice.report), "advise")
            write("integration_report.html", render_html(advice.report), "advise")
            for i, patch in enumerate(advice.patches, start=1):
                name = Path(patch_filename(i, patch)).name
                slug = name.split("-", 1)[-1].removesuffix(".patch")
                write(f"integration_patch_{i:02d}_{slug}.patch", patch.diff, "advise")
            say(
                f"[OK] advise: readiness {advice.report.readiness.total}/100, "
                f"{len(advice.patches)} patch(es) (never applied)"
            )

    # 5c Comply (WP14, off by default): advisory compliance matrix of the planned product --
    if adapters.settings.onboard_compliance_enabled:
        try:  # optional stage: a failure is reported, the run goes on
            _compliance(inv, profile, mp, texts, chat, adapters.settings, write, say)
        except Exception as exc:  # noqa: BLE001
            say(f"[SKIP] comply: {type(exc).__name__}: {str(exc)[:200]}")

    # 6 Operate ---------------------------------------------------------------------
    record = handover(inv, profile, mp, inst, report, agent.artefacts, run_id=agent.run_id)
    write("handover.json", _json(record), "operate")
    agent.record(
        "onboard_run",
        f"{AGENT_ID}:{agent.run_id}",
        {
            "stage": "operate",
            "go": report.go,
            "catch_rate_bp": report.catch_rate_bp,
            "false_alarm_bp": report.false_alarm_bp,
            "branch": inst.branch,
            "commit_sha": inst.commit_sha,
            "policy_hash": inst.policy_hash,
            "artefacts": len(agent.artefacts),
        },
    )
    say(f"[OK] operate: hand-over to Watch recorded ({len(agent.artefacts)} artefacts)")
    return OnboardResult(
        run_id=agent.run_id,
        out_dir=out,
        inventory=inv,
        profile=profile,
        plan=mp,
        playbook=playbook,
        instrument=inst,
        launch=report,
        handover=record,
        artefacts=paths,
    )
