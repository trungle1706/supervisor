"""The Onboarding Agent as a watched agent (agent id ``onboarding_agent``).

Every tool call (list the repo, read a file, call the LLM, write an artefact, commit the
branch, run the red-team sandbox) goes through a ``GateHook`` before it runs and is a
GenAI tool span exported to ``agent_event``. Each artefact and stage summary is recorded
through an ``EvidenceSink`` (the agent's own lane on the chain). A blocked call raises
``OnboardBlocked``; the run stops there. The agent's policy is ``self_policy.yaml``.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind

from supervisor.core.canonical import format_ts
from supervisor.core.errors import SupervisorError
from supervisor.core.ports import Clock, EvidenceSink, GateHook, RepoReader
from supervisor_agents.common import tracing as T
from supervisor_agents.common.gate import safe_check
from supervisor_agents.common.manifest import AgentManifest, parse_manifest

AGENT_ID = "onboarding_agent"
AGENT_VERSION = "1.0.0"
SELF_POLICY = Path(__file__).resolve().parent / "self_policy.yaml"
TOOL_RISK = {
    "list_repo_tree": "read_only",
    "read_file": "read_only",
    "list_workspace": "read_only",
    "call_llm": "read_only",
    "run_redteam_sandbox": "read_only",
    "write_artifact": "pii_export",
    "git_branch_commit": "pii_export",
}

R = TypeVar("R")


class OnboardBlocked(SupervisorError):
    """The gate refused one of the Onboarding Agent's own tool calls."""

    def __init__(self, tool: str, decision: Mapping[str, Any]) -> None:
        self.tool = tool
        self.decision = dict(decision)
        super().__init__(
            f"gate {decision.get('action')} on onboarding_agent.{tool} "
            f"({decision.get('rule_id')}): {decision.get('reason')}"
        )


def self_manifest(model_family: str, model_id: str) -> AgentManifest:
    """Registry manifest of the Onboarding Agent (same shape as the demo agents)."""
    return parse_manifest(
        {
            "id": AGENT_ID,
            "name": "Supervisor Onboarding Agent",
            "version": AGENT_VERSION,
            "owner": "Supervisor Platform",
            "owner_user": "platform-lead@example.invalid",
            "risk_tier": "medium",
            "model_family": model_family,
            "model_id": model_id,
            "host_type": "python_inprocess",
            "plug_point": "gate_hook",
            "description": "Reads an agent repository read-only and prepares an onboarding "
            "pull request; never merges.",
            "tools": [
                {"name": name, "risk_class": rc, "description": name, "args": {}}
                for name, rc in TOOL_RISK.items()
            ],
        }
    )


class OnboardingAgent:
    """Tool router for the Onboarding Agent: gate first, span always, evidence for outputs."""

    def __init__(
        self,
        gate: GateHook,
        evidence: EvidenceSink,
        tracer_provider: TracerProvider,
        clock: Clock,
        *,
        run_id: str,
        target_agent_id: str,
        env: str = "dev",
    ) -> None:
        self.gate = gate
        self.evidence = evidence
        self.provider = tracer_provider
        self.tracer = tracer_provider.get_tracer("supervisor_onboard", AGENT_VERSION)
        self.clock = clock
        self.run_id = run_id
        self.target_agent_id = target_agent_id
        self.env = env
        self.calls: list[dict[str, Any]] = []
        self.artefacts: dict[str, str] = {}

    # -- tool calls ---------------------------------------------------------------
    def call(self, tool: str, args: Mapping[str, Any], fn: Callable[[], R]) -> R:
        """Gate ``tool`` with ``args`` (small, digest-only on spans), then run ``fn``."""
        risk = TOOL_RISK.get(tool)
        attrs: dict[str, Any] = {
            T.A_EVENT_TYPE: "tool_call",
            T.A_AGENT_ID: AGENT_ID,
            T.A_AGENT_VERSION: AGENT_VERSION,
            T.A_ENV: self.env,
            "gen_ai.agent.id": AGENT_ID,
            "gen_ai.agent.name": "Supervisor Onboarding Agent",
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool,
            "gen_ai.tool.type": "function",
            T.A_TOOL: tool,
            T.A_ARGS_HASH: T.args_hash(dict(args)),
            T.A_RISK: risk or "unregistered",
        }
        with self.tracer.start_as_current_span(
            f"execute_tool {tool}", kind=SpanKind.INTERNAL, attributes=attrs
        ) as span:
            ctx = {
                "trace_id": f"{span.get_span_context().trace_id:032x}",
                "risk_class": risk,
                "run_id": self.run_id,
                "target_agent_id": self.target_agent_id,
                "env": self.env,
            }
            decision = safe_check(self.gate, AGENT_ID, AGENT_VERSION, tool, args, ctx, risk)
            span.set_attribute(T.A_GATE_ALLOW, bool(decision["allow"]))
            span.set_attribute(T.A_GATE_ACTION, decision["action"])
            span.set_attribute(T.A_GATE_RULE, decision["rule_id"] or "")
            span.set_attribute(T.A_GATE_REASON, str(decision["reason"])[:200])
            span.set_attribute(T.A_GATE_LATENCY, int(decision["latency_ms"] or 0))
            self.calls.append({"tool": tool, "decision": dict(decision)})
            if not decision["allow"]:
                span.set_attribute(
                    T.A_STATUS, "paused" if decision["action"] == "pause" else "blocked"
                )
                raise OnboardBlocked(tool, decision)
            t0 = time.monotonic()
            try:
                out = fn()
            except Exception:
                span.set_attribute(T.A_STATUS, "error")
                raise
            span.set_attribute(T.A_STATUS, "ok")
            span.set_attribute("supervisor.tool.duration_ms", int((time.monotonic() - t0) * 1000))
            return out

    # -- evidence -------------------------------------------------------------------
    def record(self, record_type: str, ref: str, payload: Mapping[str, Any]) -> str:
        body = {
            "agent_id": AGENT_ID,
            "run_id": self.run_id,
            "target_agent_id": self.target_agent_id,
            "ts": format_ts(self.clock.now()),
            **payload,
        }
        return self.evidence.record(record_type, ref, body)

    def write_artifact(self, out_dir: Path, name: str, text: str, stage: str) -> Path:
        """Gate, write ``out_dir/name`` and record its hash on the chain."""
        data = text.encode("utf-8")

        def _write() -> Path:
            if "/" in name or "\\" in name or name.startswith("."):
                raise SupervisorError(f"artefact name must be a plain file name: {name!r}")
            path = out_dir / name
            path.write_bytes(data)
            return path

        path = self.call("write_artifact", {"name": name, "bytes": len(data)}, _write)
        digest = hashlib.sha256(data).hexdigest()
        self.artefacts[name] = digest
        self.record(
            "onboard_artifact",
            f"{AGENT_ID}:{self.run_id}:{name}",
            {"stage": stage, "name": name, "sha256": digest, "bytes": len(data)},
        )
        return path


class WatchedRepoReader:
    """``RepoReader`` whose every list/read goes through the Onboarding Agent's gate."""

    def __init__(self, inner: RepoReader, agent: OnboardingAgent) -> None:
        self.inner = inner
        self.agent = agent
        self.root = getattr(inner, "root", None)

    @property
    def skipped(self) -> dict[str, str]:
        return dict(getattr(self.inner, "skipped", {}) or {})

    def list_files(self, pattern: str = "**/*") -> Sequence[str]:
        return self.agent.call(
            "list_repo_tree", {"pattern": pattern}, lambda: self.inner.list_files(pattern)
        )

    def read_text(self, path: str, max_bytes: int = 1_000_000) -> str:
        return self.agent.call(
            "read_file",
            {"path_sha256": hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]},
            lambda: self.inner.read_text(path, max_bytes),
        )
