"""Monitor packs (WP17): the live quality and fairness monitors as eval pack runners.

One result table holds everything: the groundedness scorer and the fairness slices run by
the monitors (WP7) are also reported as packs, over the recorded traces of one agent.
The monitors' own computations are called, not copied:

* :class:`GroundednessMonitorRunner` - ``supervisor.monitors.quality.QualityScorer`` over the
  ``reply`` tool calls in ``TraceTarget.events()``. The scorer model is a labelled mock
  (:class:`MockQualityChat`, a number-overlap heuristic) unless ``ctx.extras["chat"]`` gives
  a real ``ChatModel``.
* :class:`FairnessMonitorRunner` - ``supervisor.monitors.fairness.compute`` over the decision
  records of the agent's decision tool calls, using the same attribute lookup and config
  (``config/fairness.yaml``) as the fairness job. ``ctx.extras["fairness_config"]`` (a
  ``FairnessConfig``) overrides the file (tests).

Neither runner decides pass or fail; the engine compares the integer metrics to the
manifest thresholds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.adapters.clock import FixedClock, SystemClock
from supervisor.adapters.llm.mock import MockChat
from supervisor.assurance import textutil
from supervisor.assurance.model import EvalPack, RunContext, RunnerOutput
from supervisor.config import load_settings
from supervisor.monitors.fairness import (
    BLOCKED_STATUSES,
    EventDecisionSource,
    FairnessConfig,
    FairnessRecord,
    build_source,
    compute,
    subject_hash,
)
from supervisor.monitors.quality import QualityScorer, is_customer_reply

LOW_GROUNDEDNESS_BP = 7000
_TOOL_RESULTS = re.compile(r"<<<TOOL_RESULTS>>>\n(.*?)\n<<<END_TOOL_RESULTS>>>", re.S)
_REPLY = re.compile(r"<<<REPLY>>>\n(.*?)\n<<<END_REPLY>>>", re.S)


class MockQualityChat(MockChat):
    """Labelled mock scorer: groundedness = share of the numbers in the reply that appear in
    the tool results (10000 when the reply states no number). Deterministic, no model."""

    def __init__(self) -> None:
        super().__init__(seed=0, family="mock", model_id="mock-quality-overlap-v1")

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        res = _TOOL_RESULTS.search(user)
        rep = _REPLY.search(user)
        evidence = textutil.numbers(res.group(1)) if res else set()
        claimed = textutil.numbers(rep.group(1)) if rep else set()
        unsupported = sorted(claimed - evidence)
        grounded = textutil.bp(len(claimed) - len(unsupported), len(claimed))
        out = {
            "groundedness_bp": 10000 if grounded is None else grounded,
            "guideline_bp": 9000,
            "issues": [f"number {n} not in tool results" for n in unsupported[:5]],
        }
        self.calls.append({"scenario": None, "n_messages": len(messages), "response": out})
        return out


def _capped_events(
    events: Sequence[Mapping[str, Any]], max_items: int | None
) -> tuple[list[Mapping[str, Any]], int]:
    """Events with at most ``max_items`` replies kept (first by event order)."""
    replies = [e for e in events if is_customer_reply(e)]
    if max_items is None or len(replies) <= max_items:
        return list(events), len(replies)
    drop = {id(e) for e in replies[max_items:]}
    return [e for e in events if id(e) not in drop], max_items


class GroundednessMonitorRunner:
    """Pack ``groundedness_monitor`` (target: traces)."""

    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        target = ctx.target
        if getattr(target, "kind", None) != "traces":
            return RunnerOutput.skip("groundedness monitor needs a traces target")
        kept, n_replies = _capped_events(target.events(), ctx.max_items)
        if n_replies == 0:
            return RunnerOutput.skip(f"no customer replies in the traces of {target.target_id}")
        chat = ctx.extras.get("chat") or MockQualityChat()
        clock = FixedClock(ctx.now) if ctx.now is not None else SystemClock()
        scorer = QualityScorer(chat, clock, sample_bp=10000)
        results = scorer.sweep(kept)
        scores = [r.groundedness_bp for r in results if r.groundedness_bp is not None]
        if not scores:
            return RunnerOutput.skip(
                f"{len(results)} replies, none scored (scorer errors: "
                f"{sorted({r.error or '-' for r in results})})",
                is_mock=bool(chat.is_mock),
            )
        low = sum(1 for s in scores if s < LOW_GROUNDEDNESS_BP)
        ids = sorted(r.event_id for r in results)
        return RunnerOutput(
            status="ok",
            metrics={
                "mean_groundedness_bp": textutil.mean_int(scores),
                "min_groundedness_bp": min(scores),
                "low_groundedness_bp": textutil.bp(low, len(scores)),
                "replies_scored": len(scores),
            },
            n_items=len(scores),
            data_mode="synthetic",
            dataset_id=f"traces:{target.target_id}",
            dataset_sha256=textutil.sha256_lines(ids),
            is_mock=bool(chat.is_mock) or bool(getattr(target, "is_mock", False)),
            details={
                "scorer_model": str(chat.model_id),
                "low_below_bp": LOW_GROUNDEDNESS_BP,
                "scorer_errors": len(results) - len(scores),
            },
        )


# --------------------------------------------------------------------------- fairness


def _records_from_events(
    src: EventDecisionSource, events: Sequence[Mapping[str, Any]], agent_id: str
) -> list[FairnessRecord]:
    """Same parsing as ``EventDecisionSource.records`` but over given events (no SQL):
    the latest decision per hashed subject, attributes from the source's lookup."""
    cfg = src.cfg
    latest: dict[str, FairnessRecord] = {}
    for r in events:
        if (
            r.get("agent_id") != agent_id
            or r.get("event_type") != "tool_call"
            or r.get("tool_name") != cfg.decision_tool
        ):
            continue
        try:
            args = json.loads(r.get("args_masked") or "")
        except ValueError:
            continue
        if not isinstance(args, Mapping):
            continue
        sid, decision = args.get(cfg.subject_arg), args.get(cfg.decision_arg)
        if not isinstance(sid, str) or not isinstance(decision, str):
            continue
        h = subject_hash(src.key, sid)
        attrs = src.lookup.attributes(h)
        if attrs is None:
            continue
        latest[h] = FairnessRecord(
            h, attrs, decision in cfg.approve_values, str(r.get("status")) in BLOCKED_STATUSES
        )
    return list(latest.values())


class FairnessMonitorRunner:
    """Pack ``fairness_monitor`` (target: traces)."""

    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        target = ctx.target
        if getattr(target, "kind", None) != "traces":
            return RunnerOutput.skip("fairness monitor needs a traces target")
        settings = load_settings()
        cfg = ctx.extras.get("fairness_config")
        if not isinstance(cfg, FairnessConfig):
            cfg = FairnessConfig.load(settings.fairness_config)
        src = build_source(None, cfg, settings.mask_key[0])  # type: ignore[arg-type]
        if not isinstance(src, EventDecisionSource):
            return RunnerOutput.skip("fairness attribute_source is none: no attributes to slice")
        records = _records_from_events(src, target.events(), str(target.target_id))
        if ctx.max_items is not None:
            records = records[: ctx.max_items]
        if not records:
            return RunnerOutput.skip(
                f"no {cfg.decision_tool} decisions with known attributes for {target.target_id}"
            )
        report = compute(records, cfg.active_attributes, min_cell_n=cfg.min_cell_n)
        shown = sum(1 for a in report.attributes.values() for c in a.cells if not c.suppressed)
        gap = report.max_approval_gap_bp
        if gap is None:
            return RunnerOutput.skip(
                f"not enough decisions: {len(records)} records, fewer than 2 cells reach "
                f"n={cfg.min_cell_n} for any attribute (small cells are suppressed)"
            )
        return RunnerOutput(
            status="ok",
            metrics={
                "max_approval_gap_bp": gap,
                "cells_reported": shown,
                "decisions_n": len(records),
            },
            n_items=len(records),
            data_mode="synthetic",
            dataset_id=f"traces:{target.target_id}",
            dataset_sha256=textutil.sha256_lines(sorted(r.subject_hash for r in records)),
            is_mock=bool(getattr(target, "is_mock", False)),
            details={
                "method": report.method,
                "min_cell_n": cfg.min_cell_n,
                "approval_gap_bp": {
                    a.attribute: a.approval_gap_bp
                    for a in report.attributes.values()
                    if a.approval_gap_bp is not None
                },
            },
        )
