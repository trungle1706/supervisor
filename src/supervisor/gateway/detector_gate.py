"""Gate side of the detector framework (WP37, ADR D23, docs/detectors.md).

``DetectorGate`` runs the registry for one gate call and folds the result into the verdict:

* ``prepare`` runs OUTSIDE the gate lock (a masker pass over a 2 KB payload costs a few ms) and
  never raises: an error becomes a ``PreDetect`` with ``error`` set.
* ``apply`` runs inside ``Gateway._evaluate`` after the deterministic decision exists. It may do
  exactly two things to that decision: turn an allow into a block with rule id
  ``GATE-DETECTOR-FAILED`` (a fail-closed detector could not look at a money, credit or
  pii_export call), and attach the dlp transform (``transformed_payload`` / ``transformed_args``).
  A finding never blocks or pauses (R1).

Everything stored or returned from here is masked text, ids and integers (R2).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from supervisor.core.detectors import (
    PARTS,
    PARTS_BY_DIRECTION,
    DetectorRegistry,
    Finding,
    RunResult,
    derive_status,
    detector_id,
)
from supervisor.detectors.config import ResolvedDetectors
from supervisor.gateway.policy import Policy

CORRELATION_HEADER = "X-Supervisor-Correlation-Id"
ID_PATTERN = r"^[A-Za-z0-9_.:@-]{1,128}$"
DEFAULT_FAIL_CLOSED_RISK = frozenset({"money", "credit", "pii_export"})
FAILED_RULE = "GATE-DETECTOR-FAILED"
# WP25 (ADR D27): the one pause a detector may cause. Only a detector listed here is allowed to
# turn a pause hint into a pause, and never on a tool whose risk class is outside the set below
# (a read_only tool cannot be paused by a finding). The detector itself also checks the classes it
# is configured with; this is the gate's own backstop.
CLASSIFIER_PAUSE_RULE = "GATE-CLASSIFIER-PAUSE"
PAUSE_CAPABLE_DETECTORS: frozenset[str] = frozenset({"injection_classifier"})
PAUSE_RISK_CLASSES: frozenset[str] = frozenset({"money", "credit", "pii_export"})


@dataclass(frozen=True)
class Req:
    """Per-call envelope: direction of the check and the ids that tie the records together."""

    direction: str = "input"
    correlation_id: str | None = None
    request_id: str | None = None


@dataclass
class PreDetect:
    """Result of the detector pass, computed before the gate lock is taken."""

    result: RunResult | None = None
    error: str | None = None  # exception class name only
    skipped: bool = False  # a policy rule asked for no detectors on this tool
    risk_class: str | None = None
    direction: str = "input"
    fail_closed_risk: frozenset[str] = DEFAULT_FAIL_CLOSED_RISK


@dataclass
class DetectorOutcome:
    """What ``apply`` computed; ``Decision`` keeps it for recording."""

    findings: list[Finding] = field(default_factory=list)  # fired
    not_executed: list[Finding] = field(default_factory=list)


def _ne_dict(f: Finding) -> dict[str, Any]:
    return {
        "detector_slug": f.detector_slug,
        "detector_id": f.detector_id,
        "reason": f.not_executed_reason,
        "detail": f.detail,
    }


class DetectorGate:
    def __init__(self, registry: DetectorRegistry, resolved: ResolvedDetectors) -> None:
        self.registry = registry
        self.resolved = resolved

    def check_policy(self, policy: Policy) -> list[str]:
        """Problems in the per-agent detector overrides of a policy (empty = fine). Used at
        start-up and by the policy provider on every reload (F11)."""
        problems: list[str] = []
        for agent_id, manifest in policy.doc.agents.items():
            if manifest.detectors is not None:
                problems += self.resolved.check_agent(agent_id, manifest.detectors)
        return problems

    # ------------------------------------------------------------------ before the lock

    def payload_view(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        risk_class: str | None,
        args: Mapping[str, Any],
        ctx: Mapping[str, Any],
        direction: str,
    ) -> dict[str, Any]:
        """The parts of the call a detector may read. ``tool_results`` and ``output`` come from
        the request context (documented in docs/api.md)."""
        view: dict[str, Any] = {
            "meta": {
                "agent_id": agent_id,
                "agent_version": str(agent_version),
                "tool_name": tool_name,
                "risk_class": risk_class,
            }
        }
        if direction == "input":
            view["args"] = dict(args)
            if ctx.get("tool_results") is not None:
                view["tool_results"] = ctx["tool_results"]
            # WP25: text of the called tool's description, and earlier calls of the same trace
            # (split attacks). Both are optional context keys; a detector reads them from meta.
            if isinstance(ctx.get("tool_description"), str):
                view["meta"]["tool_description"] = ctx["tool_description"]
            if ctx.get("prior_calls") is not None:
                view["meta"]["prior_calls"] = ctx["prior_calls"]
        elif ctx.get("output") is not None:
            view["output"] = ctx["output"]
        return view

    def prepare(
        self,
        policy: Policy,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        ctx: Mapping[str, Any],
        req: Req,
    ) -> PreDetect:
        pre = PreDetect(direction=req.direction)
        try:
            pre.risk_class = policy.risk_class(tool_name)
            run_cfg, skip_tools = self.resolved.for_agent(policy.agent_detectors(agent_id))
            pre.fail_closed_risk = run_cfg.fail_closed_risk_classes
            if tool_name in skip_tools:
                pre.skipped = True
                return pre
            protocol = ctx.get("protocol")
            pre.result = self.registry.run(
                self.payload_view(
                    agent_id, agent_version, tool_name, pre.risk_class, args, ctx, req.direction
                ),
                req.direction,
                run_cfg,
                protocol=protocol if protocol in ("llm", "mcp", "a2a") else "llm",
                risk_class=pre.risk_class,
            )
        except Exception as exc:  # noqa: BLE001 - the detector pass must never raise
            pre.result = None
            pre.error = type(exc).__name__
        return pre

    # ------------------------------------------------------------------ inside _evaluate

    def apply(
        self,
        d: Any,
        pre: PreDetect,
        req: Req,
        *,
        shadow: bool,
        builtin: bool,
        matched_actions: Iterable[str],
        hmac_fn: Callable[[Mapping[str, Any]], str],
    ) -> None:
        """Fill ``d.v2`` (the response fields) and ``d.det`` (what to record)."""
        direction = pre.direction
        out = DetectorOutcome()
        coverage: dict[str, Any]
        transformed: dict[str, Any] | None = None
        detectors_run: list[str] = []
        latency = 0
        failed: list[Finding] = []
        if pre.skipped:
            coverage = {
                "direction": direction,
                "inspected": [],
                "not_inspected": [{"part": p, "reason": "skipped_by_policy"} for p in PARTS],
                "chars": 0,
            }
        elif pre.result is None:
            err = Finding(
                detector_slug="*",
                detector_id="*",
                code="not_executed.execution_failed",
                not_executed_reason="execution_failed",
                detail=pre.error or "unknown",
            )
            out.not_executed.append(err)
            coverage = {
                "direction": direction,
                "inspected": [],
                "not_inspected": [
                    {"part": p, "reason": "execution_failed"} for p in PARTS_BY_DIRECTION[direction]
                ],
                "chars": 0,
            }
            if pre.risk_class in pre.fail_closed_risk:
                failed.append(err)
        else:
            res = pre.result
            out.findings = list(res.findings)
            out.not_executed = list(res.not_executed)
            coverage = dict(res.coverage)
            transformed = res.transformed_payload
            detectors_run = [detector_id(self.registry.get(s)) for s in res.evaluated]
            latency = res.latency_us
            failed = list(res.failed_closed)

        # 1. The one way a detector can stop a call: it could not look at a risky tool.
        if failed and d.allow and not shadow and not builtin:
            who = ", ".join(sorted({f"{f.detector_slug}:{f.not_executed_reason}" for f in failed}))
            d.allow, d.action, d.rule_id = False, "block", FAILED_RULE
            d.reason = f"{FAILED_RULE}: detector could not run ({who}): fail closed"
            d.fail_mode = "closed"
            transformed = None
            # A blocked call has no transformed arguments (WP24b filled them while it was allowed).
            d.transformed_args, d.args_hmac_transformed, d.redaction_count = None, None, 0
        # 1b. WP25: a pause-capable detector (the injection classifier) may turn an ALLOW into a
        # PAUSE, never a block, on a money / credit / pii_export tool. The detector set the hint
        # only above its frozen threshold and only for its configured classes. A human resumes.
        if (
            d.allow
            and not shadow
            and not builtin
            and direction == "input"
            and pre.risk_class in PAUSE_RISK_CLASSES
        ):
            pausers = [
                f
                for f in out.findings
                if f.action_hint == "pause" and f.detector_slug in PAUSE_CAPABLE_DETECTORS
            ]
            if pausers:
                top = max(pausers, key=lambda f: f.score_bp)
                d.allow, d.action, d.rule_id = False, "pause", CLASSIFIER_PAUSE_RULE
                d.reason = (
                    f"{CLASSIFIER_PAUSE_RULE}: {top.code} score {top.score_bp} bp at or above "
                    f"the pause threshold on a {pre.risk_class} tool (the classifier advises; a "
                    "human resumes)"
                )
                transformed = None
        # 2. The dlp transform: only on an allowed, non-shadow call (same rule as WP24b).
        if transformed and d.allow and not shadow and not builtin:
            d.transformed_payload = {k: transformed[k] for k in sorted(transformed)}
            if d.transformed_args is None and isinstance(transformed.get("args"), Mapping):
                d.transformed_args = dict(transformed["args"])
                d.args_hmac_transformed = hmac_fn(d.transformed_args)
                d.redaction_count = sum(
                    f.masked_count for f in out.findings if f.action_hint == "transform"
                )
        elif d.transformed_args is not None and d.transformed_payload is None:
            d.transformed_payload = {"args": d.transformed_args}  # WP24b redaction, same shape
        status = derive_status(
            allow=d.allow,
            action=d.action,
            findings=out.findings,
            has_transform=d.transformed_payload is not None,
            skipped=pre.skipped,
            matched_actions=matched_actions,
        )
        d.det = out
        d.v2 = {
            "status": status,
            "direction": direction,
            "findings": [f.to_dict() for f in out.findings],
            "not_executed": [_ne_dict(f) for f in out.not_executed],
            "coverage": coverage,
            "transformed_payload": d.transformed_payload,
            "request_id": req.request_id,
            "correlation_id": req.correlation_id,
            "detectors": detectors_run,
            "detector_latency_us": latency,
        }


def fallback_v2(d: Any, req: Req) -> None:
    """v2 fields for a decision made by the fail mode (the gate could not decide)."""
    d.v2 = {
        "status": "block" if not d.allow else "report",
        "direction": req.direction,
        "findings": [],
        "not_executed": [],
        "coverage": {
            "direction": req.direction,
            "inspected": [],
            "not_inspected": [
                {"part": p, "reason": "gate_failed"} for p in PARTS_BY_DIRECTION[req.direction]
            ],
            "chars": 0,
        },
        "transformed_payload": None,
        "request_id": req.request_id,
        "correlation_id": req.correlation_id,
        "detectors": [],
        "detector_latency_us": 0,
    }
    d.det = DetectorOutcome()


# ---------------------------------------------------------------------------- recording


def event_fields(d: Any) -> dict[str, Any]:
    """Extra ``agent_event`` columns (WP37). ``coverage_json`` holds parts and reasons only."""
    from supervisor.core.canonical import canonical_json

    v2 = d.v2
    return {
        "verdict_status": v2["status"],
        "correlation_id": v2["correlation_id"],
        "coverage_json": canonical_json(v2["coverage"]),
    }


def finding_rows(
    d: Any,
    now: Any,
    agent_id: str,
    tool_name: str,
    trace_id: str | None,
    new_id: Callable[[], str],
) -> list[dict[str, Any]]:
    """One ``finding`` row per fired finding and per detector that did not run. Entities and
    fragments are masked text (R2)."""
    from supervisor.core.canonical import canonical_json

    v2 = d.v2
    rows = []
    for f in [*d.det.findings, *d.det.not_executed]:
        rows.append(
            {
                "finding_id": new_id(),
                "ts": now,
                "event_id": d.decision_id,
                "request_id": v2["request_id"],
                "correlation_id": v2["correlation_id"],
                "trace_id": trace_id,
                "agent_id": agent_id,
                "tool_name": tool_name,
                "direction": v2["direction"],
                "detector_slug": f.detector_slug,
                "detector_id": f.detector_id,
                "code": f.code,
                "score_bp": f.score_bp,
                "threshold_bp": f.threshold_bp,
                "masked_count": f.masked_count,
                "action_hint": f.action_hint,
                "not_executed_reason": f.not_executed_reason,
                "preset": f.preset,
                "is_mock": f.is_mock,
                "verdict_status": v2["status"],
                "entities_masked": canonical_json([e.to_dict() for e in f.entities])
                if f.entities
                else None,
                "fragments_masked": canonical_json([x.to_dict() for x in f.fragments[:20]])
                if f.fragments
                else None,
            }
        )
    return rows


def chain_fields(d: Any) -> dict[str, Any]:
    """Keys added to the ``gate_decision`` chain record (WP37). Hashes, codes and integers; no
    text, no fragment, no entity token, no path (R2)."""
    v2 = d.v2
    cov = v2["coverage"]
    return {
        "status": v2["status"],
        "direction": v2["direction"],
        "request_id": v2["request_id"],
        "correlation_id": v2["correlation_id"],
        "finding_codes": sorted({f.code for f in d.det.findings}),
        "finding_hashes": sorted(f.digest() for f in d.det.findings),
        "not_executed": sorted(
            {f"{f.detector_slug}:{f.not_executed_reason}" for f in d.det.not_executed}
        ),
        "coverage": {
            "inspected": list(cov.get("inspected", [])),
            "not_inspected": [
                {"part": n["part"], "reason": n["reason"]} for n in cov.get("not_inspected", [])
            ],
        },
        "transformed": d.transformed_payload is not None,
        "detectors": list(v2["detectors"]),
    }
