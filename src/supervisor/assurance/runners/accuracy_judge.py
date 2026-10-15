"""Judge golden-set runner (WP17): the existing judge eval harness as an assurance pack.

Numbers come straight from ``supervisor.judge.eval.run_eval`` (held-out split): the runner
only chooses the items and reads the report, it recomputes nothing.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from supervisor.assurance.model import EvalPack, RunContext, RunnerOutput
from supervisor.assurance.textutil import sha256_lines, stable_rank
from supervisor.core.models import AgentEvent
from supervisor.judge.eval import build_eval_sets, run_eval
from supervisor.judge.eval.datasets import EVAL_T0, EvalItem

GOLDEN_FILE = "golden_set.jsonl"


def _label_positive(row: dict[str, Any]) -> bool | None:
    """Adjudicated label if present; else the reviewers' label when both agree; else None
    (an unadjudicated disagreement is not a usable ground truth)."""
    labels = row.get("labels") or {}
    adj = labels.get("adjudicated")
    if isinstance(adj, dict) and isinstance(adj.get("violation"), bool):
        return adj["violation"]
    r1, r2 = labels.get("reviewer_1") or {}, labels.get("reviewer_2") or {}
    if isinstance(r1.get("violation"), bool) and r1.get("violation") == r2.get("violation"):
        return bool(r1["violation"])
    return None


def golden_rows_to_items(rows: list[dict[str, Any]]) -> tuple[list[EvalItem], int]:
    """Rows in the ``data/golden/golden_set.jsonl`` format -> harness items. Returns the
    items and the number of rows dropped (no usable label or malformed events)."""
    items: list[EvalItem] = []
    dropped = 0
    for row in rows:
        positive = _label_positive(row)
        try:
            gid = str(row["id"])
            agent = str(row["agent_id"])
            events = []
            for i, e in enumerate(row["events"]):
                amount = e.get("amount_minor")
                events.append(
                    AgentEvent(
                        event_id=f"{gid}-e{i}",
                        ts=EVAL_T0 + timedelta(seconds=i),
                        trace_id=f"eval-{gid}",
                        span_id=f"{gid}-s{i}",
                        agent_id=e.get("agent_id") or agent,
                        agent_version="eval",
                        caller_agent_id=e.get("caller_agent_id"),
                        event_type=e["event_type"],
                        tool_name=e.get("tool_name"),
                        args_masked=e.get("args_masked"),
                        result_masked=e.get("result_masked"),
                        amount_minor=amount,
                        currency=(e.get("currency") or "VND") if amount is not None else None,
                        env="eval",
                        source="proxy",
                    )
                )
            if positive is None or not events:
                raise ValueError("unusable")
            items.append(
                EvalItem(
                    id=gid,
                    set="planted" if positive else "benign",
                    split="heldout" if row.get("split") == "heldout" else "dev",
                    language=str(row.get("language", "vi")),
                    agent_id=agent,
                    positive=positive,
                    events=tuple(events),
                    stratum=f"golden:{row.get('risk_category', 'unknown')}",
                    meta={"vector": str(row.get("risk_category", "unknown"))},
                )
            )
        except (KeyError, TypeError, ValueError):
            dropped += 1
    return items, dropped


def _read_golden(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open(encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
    return out


class JudgeGoldenSetRunner:
    """Judge validation on the golden set (held-out split of the judge eval harness).

    synthetic: ``build_eval_sets()`` (planted incidents, benign incidents and synthetic
    benign traces, judge-injection items) plus the example rows of ``data/golden``.
    bank_supplied_path: ``<ASSURANCE_DATA_DIR>/judge_golden_set/golden_set.jsonl`` in the
    ``data/golden/golden_set.schema.json`` format (the bank's reviewed labels).
    Metrics: catch_rate_bp (planted flagged / planted), false_alarm_bp (benign flagged /
    benign), both on the held-out split, from the harness report."""

    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        tgt = ctx.target
        if getattr(tgt, "kind", None) != "judge":
            return RunnerOutput.skip(f"target kind {getattr(tgt, 'kind', None)!r} is not a judge")
        factory = tgt.router_factory()
        if factory is None:
            return RunnerOutput.skip("judge target has no router factory")
        mode = ctx.data_mode
        bank = ctx.bank_dir(pack.id)
        dropped = 0
        if mode == "vendored":
            return RunnerOutput.skip("no vendored sample is shipped")
        if mode == "bank" or (mode == "auto" and bank is not None):
            if bank is None:
                return RunnerOutput.skip(f"no bank data at {ctx.data_root}/{pack.id}")
            try:
                items, dropped = golden_rows_to_items(_read_golden(bank / GOLDEN_FILE))
            except (OSError, ValueError) as exc:
                return RunnerOutput.skip(f"bank golden set not readable: {type(exc).__name__}")
            used, ds_id = "bank_supplied_path", f"bank:{pack.id}"
        else:
            items = build_eval_sets(
                ctx.repo_root / "agents" / "redteam" / "incidents.jsonl",
                ctx.repo_root / "data" / "golden" / "judge_injection_templates.jsonl",
            )
            golden = ctx.repo_root / "data" / "golden" / GOLDEN_FILE
            if golden.is_file():
                extra, dropped = golden_rows_to_items(_read_golden(golden))
                items += extra
            used, ds_id = "synthetic", f"synthetic:{pack.id}:v{pack.version}"
        held = [i for i in items if i.split == "heldout"]
        if len(held) < pack.min_items:
            return RunnerOutput.skip(
                f"only {len(held)} held-out items, need {pack.min_items}",
                data_mode=used,  # type: ignore[arg-type]
                dataset_id=ds_id,
            )
        if ctx.max_items is not None:
            keep = sorted(held, key=lambda i: stable_rank(str(ctx.seed), i.id))[: ctx.max_items]
            ids = {i.id for i in keep}
            items = [i for i in items if i.split == "heldout" and i.id in ids]
        runs = int(ctx.extras.get("judge_runs", 1))
        report = run_eval(items, factory, runs=runs, splits=("heldout",))
        m = report["metrics"]["heldout"]
        sha = sha256_lines(sorted(i.id for i in items if i.split == "heldout"))
        details = {
            "runs": runs,
            "harness_mock": bool(report.get("mock")),
            "heldout_digest": report["heldout"]["digest"],
            "n_planted": m["n"]["planted"],
            "n_benign": m["n"]["benign"],
            "n_injection": m["n"]["injection"],
            "dropped_rows": dropped,
            "by_language": m["by_language"],
            "prompt_version": report.get("prompt_version"),
        }
        metrics = {
            "catch_rate_bp": m["catch_rate_bp"],
            "false_alarm_bp": m["false_alarm_bp"],
            "n_heldout_items": m["n"]["planted"] + m["n"]["benign"] + m["n"]["injection"],
        }
        n_items = sum(1 for i in items if i.split == "heldout")
        return RunnerOutput(
            status="ok",
            metrics=metrics,
            n_items=n_items,
            data_mode=used,  # type: ignore[arg-type]
            dataset_id=ds_id,
            dataset_sha256=sha,
            is_mock=bool(getattr(tgt, "is_mock", False)),
            details=details,
        )
