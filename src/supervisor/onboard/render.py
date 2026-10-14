"""Markdown renderings of the stage outputs (for people; the JSON files are the record)."""

from __future__ import annotations

from supervisor.onboard.models import (
    AgentProfile,
    Claim,
    Inventory,
    LaunchReport,
    MonitoringPlan,
    RemediationPlaybook,
)


def _refs(c: Claim) -> str:
    return ", ".join(f"`{e.ref()}`" for e in c.evidence[:3])


def profile_md(inv: Inventory, p: AgentProfile) -> str:
    out = [
        f"# Agent profile: {p.name} (`{p.agent_id}` {p.version})",
        "",
        f"- Owner: {p.owner_team}",
        f"- Purpose: {p.purpose.claim} ({_refs(p.purpose)})",
        f"- Proposed risk tier: **{p.proposed_risk_tier}** (declared: "
        f"{p.declared_risk_tier or 'none'}) - {p.risk_tier_reason.claim}",
        f"- Decision 33 (proposal): **{p.decision33.classification}**; human gate in code: "
        f"{p.decision33.human_gate_in_code}",
        f"- LLM: {p.llm.model_id} (mock={p.llm.is_mock}) - {p.llm.note}",
        f"- Secret scrubber: {inv.scrub.get('secrets_redacted', 0)} redacted in "
        f"{inv.scrub.get('files_with_secrets', 0)} file(s) (counts only)",
        "",
        f"> {p.decision33.wording_caveat}",
        "",
    ]
    for e in p.decision33.entries:
        refs = ", ".join(f"`{ev.ref()}`" for ev in e.evidence[:4])
        out.append(f"- Decision 33 {e.entry}: triggered={e.triggered}. {e.reason} ({refs})")
    sections = [
        ("Capabilities", p.capabilities),
        ("Reversibility", p.reversibility),
        ("Personal data", p.personal_data),
        ("Weak spots", p.weak_spots),
    ]
    for title, claims in sections:
        out += ["", f"## {title}", ""]
        out += [f"- {c.claim} ({_refs(c)})" for c in claims] or ["- none found"]
    out += ["", "## Inventory", ""]
    out.append(f"- Files scanned: {len(inv.files)}; skipped: {len(inv.skipped)}")
    out.append(
        "- Prompts: " + ", ".join(f"{x.kind} `{x.evidence.ref()}`" for x in inv.prompts[:12])
    )
    out.append("- Model endpoints: " + (", ".join(e.name for e in inv.model_endpoints) or "none"))
    out.append("- MCP servers: " + (", ".join(m.name for m in inv.mcp_servers) or "none"))
    out.append(
        "- Tables: " + (", ".join(f"{t.name} ({t.direction})" for t in inv.tables) or "none")
    )
    out.append("- Tracing: " + (", ".join(f"{t.name}" for t in inv.traces) or "none"))
    out.append("- Features: " + ", ".join(inv.features))
    return "\n".join(out) + "\n"


def plan_md(mp: MonitoringPlan) -> str:
    out = [f"# Monitoring plan: `{mp.agent_id}`", "", "## Capabilities", ""]
    out += ["| Capability | Kind | Lane | Status | Reason |", "|---|---|---|---|---|"]
    for c in mp.capabilities:
        out.append(f"| {c.id} | {c.kind} | {c.lane} | {c.status} | {c.reason or ''} |")
    out += ["", "## Rules", "", "| Rule | Capability | Action | Severity |", "|---|---|---|---|"]
    for r in mp.rules:
        out.append(
            f"| {r.rule_id} | {r.capability_id} | {r.spec['action']} | {r.spec['severity']} |"
        )
    out += ["", "## Thresholds (integers)", ""]
    out += [f"- {k}: {v}" for k, v in sorted(mp.thresholds.items())]
    out += ["", "## Judges", ""]
    out += [
        f"- {j.id}: sample {j.sample_bp} bp, threshold {j.threshold_bp} bp, model family "
        f"must differ from {j.family_must_differ_from}"
        for j in mp.judges
    ] or ["- none"]
    out += ["", "## Slices", "", "- " + (", ".join(mp.slices) or "none")]
    c = mp.cost
    out += [
        "",
        "## Cost estimate (design estimate, integers)",
        "",
        f"- events per day assumed: {c.events_per_day_assumed}",
        f"- LLM tokens per day: {c.llm_tokens_per_day}",
        f"- compute ms per day: {c.compute_ms_per_day}",
        f"- storage bytes per day: {c.storage_bytes_per_day}",
    ]
    return "\n".join(out) + "\n"


def playbook_md(pb: RemediationPlaybook) -> str:
    out = [f"# Remediation playbook: `{pb.agent_id}`", "", pb.resume_rule, ""]
    for e in pb.entries:
        out += [
            f"## {e.trigger} ({e.kind}, {e.action}, {e.severity}, SLA {e.sla_minutes} min)",
            "",
            f"First responder: {e.first_responder}",
            "",
        ]
        out += [f"{i}. {s}" for i, s in enumerate(e.steps, start=1)]
        out.append("")
    return "\n".join(out)


def launch_md(r: LaunchReport) -> str:
    out = [
        f"# Launch report: `{r.agent_id}` - {'GO' if r.go else 'NO-GO'}",
        "",
        f"- Mode: {r.mode} (sandbox); LLM: mock={r.llm_is_mock}",
        f"- Policy hash: `{r.policy_hash[:16]}`",
        f"- Red-team: {r.rule_caught}/{r.rule_expected} rule cases caught "
        f"({r.catch_rate_bp} bp, target >= {r.min_catch_rate_bp} bp)",
        f"- False alarms: {r.benign_flagged}/{r.benign_cases} benign cases "
        f"({r.false_alarm_bp} bp, target <= {r.max_false_alarm_bp} bp)",
        f"- Judge or drift cases (not scored by rules): {r.judge_or_drift_cases}; "
        f"text-only cases: {r.text_only_cases}",
        "",
        "## Reasons",
        "",
    ]
    out += [f"- {x}" for x in r.reasons]
    out += ["", "## Integration checks", ""]
    out += [f"- [{'OK' if c.ok else 'FAIL'}] {c.name}: {c.detail}" for c in r.integration_checks]
    out += [
        "",
        "## Enforcement switch list (rule by rule)",
        "",
        "| Rule | Action | Caught | False alarms | Recommendation | Why |",
        "|---|---|---|---|---|---|",
    ]
    for s in r.rule_switches:
        out.append(
            f"| {s.rule_id} | {s.action} | {s.true_positives} | {s.false_positives} | "
            f"{s.recommendation} | {s.reason} |"
        )
    out += ["", "## Missed and false-alarm cases", ""]
    bad = [c for c in r.cases if c.outcome in ("missed", "false_alarm")]
    out += [f"- {c.case_id} {c.outcome} ({c.vector}) rules={c.rules}" for c in bad] or ["- none"]
    b = r.baseline
    if b:
        out += [
            "",
            "## Baseline (for drift)",
            "",
            f"- runs: {b.get('runs')}, tool calls: {b.get('tool_calls')}",
            f"- tool mix (bp): {b.get('tool_mix_bp')}",
        ]
    return "\n".join(out) + "\n"
