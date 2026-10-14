"""Stage 6 Operate: the hand-over record from Onboard to Watch (pure function)."""

from __future__ import annotations

from collections.abc import Mapping

from supervisor.onboard.models import (
    AgentProfile,
    HandoverRecord,
    InstrumentResult,
    Inventory,
    LaunchReport,
    MonitoringPlan,
)


def handover(
    inv: Inventory,
    profile: AgentProfile,
    mp: MonitoringPlan,
    inst: InstrumentResult,
    report: LaunchReport,
    artefacts: Mapping[str, str],
    *,
    run_id: str,
) -> HandoverRecord:
    enforce = [s.rule_id for s in report.rule_switches if s.recommendation == "enforce"]
    shadow = [s.rule_id for s in report.rule_switches if s.recommendation == "stay_shadow"]
    steps = [
        f"Owner ({inv.owner_team}) and a second approver review branch {inst.branch} and "
        "replace every FILL-ME value; a human merges (the Onboarding Agent never merges).",
        "Deploy the merged policy; the agent starts in SHADOW.",
    ]
    if report.go:
        steps.append(
            "Switch the rules in enforce_first to enforced mode one by one; watch the "
            "dashboard for a day between switches."
        )
    else:
        steps.append(
            "Launch is NO-GO: fix the reasons in the launch report and re-run onboarding "
            "before any rule is enforced."
        )
    steps += [
        "Keep rules in keep_in_shadow until their false alarms are fixed.",
        "Confirm the risk tier and the Decision 33 classification with risk and legal; "
        "a pause is not pre-execution human approval.",
        "Watch takes over: cases, metrics and audit packs come from the evidence chain.",
    ]
    return HandoverRecord(
        agent_id=inv.agent_id,
        run_id=run_id,
        onboarded_by="onboarding_agent",
        owner_team=inv.owner_team,
        owner_user=inv.owner_user,
        enforce_first=enforce,
        keep_in_shadow=shadow,
        capabilities_on=mp.on_ids,
        decision33_classification=profile.decision33.classification,
        proposed_risk_tier=profile.proposed_risk_tier,
        branch=inst.branch,
        commit_sha=inst.commit_sha,
        go=report.go,
        artefacts=dict(sorted(artefacts.items())),
        next_steps=steps,
    )
