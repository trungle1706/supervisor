# ruff: noqa: E501
"""Run the source analysis on a stored tree and build the report.

    report, run = analyse_tree(tree_path, chat, cfg, node_id="cand-1", attempt_n=1)

The deterministic stage (Discover + the AST rules of ``baseline``) always runs. The agent runs
only when a real model is given (a mock model leaves the report deterministic and says so, unless
``exercise_mock`` is set for tests). The agent's findings are verified, merged, and re-verified
against the stored tree before the report is returned.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.core.ports import ChatModel
from supervisor.onboard.codeagent import prompts
from supervisor.onboard.codeagent.agent import AgentConfig, AgentRun, SourceAnalysisAgent
from supervisor.onboard.codeagent.baseline import (
    approval_name,
    deterministic_findings,
    guards_of,
)
from supervisor.onboard.codeagent.merge import merge
from supervisor.onboard.codeagent.models import (
    SCHEMA_VERSION,
    CodeAnalysisReport,
    Coverage,
    Finding,
    ModelInfo,
    Rejected,
    RunStats,
)
from supervisor.onboard.codeagent.verify import verify_report
from supervisor.onboard.codeagent.workspace import Workspace
from supervisor.onboard.discover import Discovery, discover

assert SCHEMA_VERSION == 1


def tree_digest(ws: Workspace) -> str:
    h = hashlib.sha256()
    for name in ws.files:
        h.update(
            name.encode("utf-8") + b"\x00" + "\n".join(ws.lines[name]).encode("utf-8") + b"\x00"
        )
    return h.hexdigest()


def analyse_tree(
    tree: str | Path,
    chat: ChatModel | None,
    cfg: AgentConfig | None = None,
    *,
    node_id: str = "node",
    attempt_n: int = 1,
    exercise_mock: bool = False,
    use_agent: bool = True,
    ws: Workspace | None = None,
    disc: Discovery | None = None,
    det: list[Finding] | None = None,
    api_shape: str = "",
    on_step: Callable[[int, int], None] | None = None,
) -> tuple[CodeAnalysisReport, AgentRun]:
    cfg = cfg or AgentConfig()
    ws = ws or Workspace.from_tree(tree)
    disc = disc or discover(LocalGitRepoReader(Path(tree)))
    det = det if det is not None else deterministic_findings(disc, ws)
    notes: list[str] = []
    run = AgentRun()
    real = chat is not None and (not chat.is_mock or exercise_mock)
    if use_agent and real:
        assert chat is not None
        run = SourceAnalysisAgent(chat, cfg).run(ws, det, on_step)
        mode = "agent"
    else:
        mode = "deterministic"
        run.stop_reason = "off"
        notes.append(
            "no real model configured: deterministic findings only"
            if use_agent
            else "agent switched off for this run: deterministic findings only"
        )
    agent_findings = [f for f in run.findings if f.verified]
    tool_rows = [f for f in [*det, *agent_findings] if f.kind == "tool"]
    for h in agent_findings:  # the agent names the approval function; the rules say what it guards
        if h.kind == "hitl":
            fn = approval_name(ws, h)
            h.attrs["guards"] = ",".join(guards_of(ws, disc, fn, tool_rows)) if fn else ""
            h.attr_basis["guards"] = "ast"
    # an approval step that no tool reaches guards nothing; only a graph interrupt may stand alone
    dropped_h = [
        h
        for h in agent_findings
        if h.kind == "hitl" and not h.attrs.get("guards") and h.attrs.get("mode") != "interrupt"
    ]
    agent_findings = [h for h in agent_findings if h not in dropped_h]
    run.rejected.extend(
        Rejected(
            kind="hitl",
            name=h.name[:120],
            file=h.evidence[0].file,
            line=h.evidence[0].line,
            reason="bad_attrs",
        )
        for h in dropped_h
    )
    merged, disagreements = merge(det, agent_findings)
    ok, total = verify_report(merged, ws)
    if ok != total:
        notes.append(f"{total - ok} finding(s) failed the final evidence check and were dropped")
        merged = [f for f in merged if all(_still(ws, e) for e in f.evidence)]
    code_files = [f for f in ws.files if f.endswith((".py", ".yaml", ".yml", ".toml", ".json"))]
    coverage = Coverage(
        files_total=len(code_files),
        files_read=len([f for f in code_files if f in ws.opened]),
        files_seen=len([f for f in code_files if f in ws.seen or f in ws.opened]),
        lines_total=ws.total_lines(),
        lines_read=ws.lines_read(),
        skipped=dict(sorted(ws.skipped.items())),
    )
    stats = RunStats(
        steps=run.steps,
        llm_calls=run.llm_calls,
        tokens_estimated=run.tokens,
        seconds=round(run.seconds, 2),
        stop_reason=run.stop_reason,  # type: ignore[arg-type]
        tool_calls=dict(run.tool_calls),
        tool_errors=run.tool_errors,
        injection_lines_withheld=ws.withheld,
        proposed=run.proposed,
        kept=len(agent_findings),
        rejected=len(run.rejected),
    )
    conf, bp = _confidence(mode, coverage, stats)
    report = CodeAnalysisReport(
        node_id=node_id,
        attempt_n=attempt_n,
        tree_sha256=tree_digest(ws),
        mode=mode,  # type: ignore[arg-type]
        model=(
            ModelInfo(
                model_id=chat.model_id,
                family=chat.family,
                is_mock=bool(chat.is_mock),
                api_shape=api_shape,
            )
            if chat is not None and mode == "agent"
            else None
        ),
        summary=_summary(merged, disagreements_n=len(disagreements)),
        findings=merged,
        disagreements=disagreements,
        rejected=run.rejected[:60],
        coverage=coverage,
        stats=stats,
        confidence=conf,  # type: ignore[arg-type]
        confidence_bp=bp,
        notes=[
            *notes,
            f"prompt {prompts.PROMPT_VERSION}",
            f"verifier {prompts.VERIFY_VERSION}",
            *run.notes,
        ],
    )
    return report, run


def _still(ws: Workspace, ev: object) -> bool:
    from supervisor.onboard.codeagent.verify import evidence_ok

    return evidence_ok(ev, ws)  # type: ignore[arg-type]


def _confidence(mode: str, cov: Coverage, stats: RunStats) -> tuple[str, int]:
    if mode != "agent":
        return "medium", 5000
    read = cov.files_read / cov.files_total if cov.files_total else 1.0
    kept_ratio = stats.kept / stats.proposed if stats.proposed else 1.0
    done = 1.0 if stats.stop_reason == "finished" else 0.0
    bp = int(10000 * (0.5 * read + 0.3 * kept_ratio + 0.2 * done))
    if done and read >= 0.9 and kept_ratio >= 0.65:
        return "high", bp
    if read >= 0.6 and kept_ratio >= 0.4:
        return "medium", bp
    return "low", bp


def _summary(findings: list[Finding], *, disagreements_n: int) -> str:
    def n(kind: str) -> int:
        return len([f for f in findings if f.kind == kind])

    tools = [f for f in findings if f.kind == "tool"]
    irrev = [f.name for f in tools if f.attrs.get("irreversible") is True]
    unguarded = [
        f.name
        for f in tools
        if f.attrs.get("irreversible") is True and f.attrs.get("approval") is not True
    ]
    agent_n = len([f for f in findings if f.source == "agent"])
    text = (
        f"{len(tools)} tool(s), {len(irrev)} irreversible, {len(unguarded)} irreversible without approval; "
        f"{n('egress')} host(s) contacted; {n('data_flow')} data flow(s); {n('hitl')} approval step(s); "
        f"{n('guardrail')} guardrail(s); {agent_n} finding(s) added by the agent; "
        f"{disagreements_n} disagreement(s)."
    )
    return text[:600]
