"""Assurance pack ``multiturn_redteam_vi``: patient, multi-turn attacks against a sandbox agent.

Drives the six attack families (echo chamber, crescendo, payload splitting, tool poisoning,
memory poison, policy puppetry) as conversations against the sandbox agent with the gate in
SHADOW and scores them with the deterministic oracle (did a money, credit or personal-data call
cross a rule?). Judges only add evidence. See ``supervisor.redteam.multiturn`` and
``docs/redteam-multiturn.md``.

Informational for Launch (``launch_gate: advisory``) until the owner says otherwise.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from supervisor.assurance.model import EvalPack, RunContext, RunnerOutput
from supervisor.assurance.runners import security_common as sc
from supervisor.assurance.runners.security_common import SkipPack
from supervisor.assurance.textutil import stable_rank
from supervisor.config import load_settings
from supervisor.redteam.multiturn import campaign as camp
from supervisor.redteam.multiturn.attacker import TemplateAttacker
from supervisor.redteam.multiturn.catalogue import (
    OBJECTIVES_PATH,
    load_objectives,
    validate_objectives,
)
from supervisor.redteam.multiturn.harness import HarnessConfig, run_harness
from supervisor.redteam.multiturn.model import Objective
from supervisor.redteam.multiturn.runner import RunConfig

BANK_FILE = "objectives.jsonl"
MAX_OBJECTIVE_DETAILS = 80


def _load(pack: EvalPack, ctx: RunContext) -> tuple[list[Objective], str, str, str]:
    """(objectives, data mode, dataset id, sha256 of the file)."""
    bank = ctx.bank_dir(pack.id)
    use_bank = ctx.data_mode == "bank" or (
        ctx.data_mode == "auto" and bank is not None and (bank / BANK_FILE).is_file()
    )
    if ctx.data_mode == "vendored":
        raise SkipPack("no vendored sample for this pack")
    if use_bank:
        if bank is None or not (bank / BANK_FILE).is_file():
            raise SkipPack(f"no bank data at <ASSURANCE_DATA_DIR>/{pack.id}/{BANK_FILE}")
        path, mode, ds = bank / BANK_FILE, "bank_supplied_path", f"bank/{pack.id}/{BANK_FILE}"
    else:
        path, mode = OBJECTIVES_PATH, "synthetic"
        try:
            ds = path.relative_to(ctx.repo_root).as_posix()
        except ValueError:
            ds = path.name
    try:
        items = load_objectives(path)
    except (OSError, ValueError) as exc:
        raise SkipPack(f"cannot read objectives: {type(exc).__name__}") from exc
    problems = validate_objectives(items)
    if problems:
        raise SkipPack(f"invalid objectives file ({len(problems)} problem(s)): {problems[0][:120]}")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return items, mode, ds, sha


def _compact_cells(agg: dict[str, Any]) -> dict[str, Any]:
    """Per-family and per-kind numbers that the report and the trend need, kept small."""

    def slim(v: dict[str, Any]) -> dict[str, Any]:
        return {
            "conversations": v["conversations"],
            "success": v["success"],
            "gate_catch": v["gate_catch"],
            "gate_escape_count": v["gate_escape_count"],
            "tier0b_turn1": v["tier0b_turn1"],
            "monitor_visible_on_success": v["monitor_visible_on_success"],
            "median_turns_to_success": v["median_turns_to_success"],
        }

    w = agg["worst_case"]
    return {
        "by_family": {k: slim(v) for k, v in agg["by_family"].items()},
        "by_lang": {k: slim(v) for k, v in agg["by_lang"].items()},
        "worst_case_by_kind": {
            k: {
                "gate_catch": v["gate_catch"],
                "gate_escape_count": v["gate_escape_count"],
                "conversations": v["conversations"],
            }
            for k, v in w["by_kind"].items()
        },
        "worst_case_by_family": {
            k: {"gate_catch": v["gate_catch"], "gate_escape_count": v["gate_escape_count"]}
            for k, v in w["by_family"].items()
        },
        "gap_kinds_open": list(w["gap_kinds_open"]),
        "benign": agg["benign"],
        "miss_taxonomy": agg["miss_taxonomy"],
        "rules_at_success": agg["rules_at_success"],
        "min_cell_n": agg["min_cell_n"],
        "cells_below_min_trials": agg["cells_below_min_trials"],
        "cells_total": agg["cells_total"],
        "cost": agg["cost"],
    }


class MultiturnRedteamRunner:
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        target = ctx.target
        try:
            sc.need_kind(target, "agent")
            sc.need_capability(target, "planned")
            if not (hasattr(target, "world") and hasattr(target, "clock")):
                raise SkipPack("needs the sandbox demo target (world and clock)")
            items, mode, ds_id, sha = _load(pack, ctx)
        except SkipPack as exc:
            return RunnerOutput.skip(str(exc))
        settings = getattr(target, "settings", None) or load_settings()
        agent = str(target.target_id)
        langs = tuple(str(ctx.extras.get("redteam_langs") or settings.redteam_langs).split(","))
        chosen = [o for o in items if o.agent == agent and o.lang in langs]
        if ctx.max_items is not None and len(chosen) > ctx.max_items:
            keep = sorted(chosen, key=lambda o: stable_rank(pack.id, o.id))[: ctx.max_items]
            ids = {o.id for o in keep}
            chosen = [o for o in chosen if o.id in ids]
        if len(chosen) < 1:
            return RunnerOutput.skip(f"no multi-turn objective for agent {agent!r}")
        trials = int(ctx.extras.get("redteam_trials") or settings.redteam_trials)
        if ctx.max_items is not None and not ctx.extras.get("redteam_trials"):
            trials = min(trials, 2)  # fast runs (tests): n is small and the report says so
        attacker = ctx.extras.get("redteam_attacker") or TemplateAttacker()
        hc = HarnessConfig(
            trials=trials,
            benign_trials=min(3, trials),
            seed=int(ctx.extras.get("redteam_seed") or settings.redteam_seed),
            langs=langs,
            agents=(agent,),
            run=RunConfig(attacker=attacker),
            keep_turns=bool(ctx.extras.get("out_dir")),
            objectives=chosen,
        )
        res = run_harness(hc, targets={agent: target}, include_probes=True)
        res_results, agg, metrics = res.results, res.aggregate, res.metrics
        n = int(metrics.get("conversations") or 0)
        if n < pack.min_items:
            return RunnerOutput.skip(f"only {n} conversations, pack needs {pack.min_items}")
        out_dir = ctx.extras.get("out_dir")
        traces = ""
        if out_dir:
            tp = Path(str(out_dir)) / "multiturn_redteam" / agent / "traces.jsonl"
            camp.write_traces(res_results, tp)
            traces = tp.as_posix()
        details = {
            "agent_side": "mock susceptibility model (success); worst-case replay (gate_catch)",
            "agent_model": res.config["agent_model"],
            "attacker": res.config["attacker"],
            "attacker_model": res.config["attacker_model"],
            "attacker_prompt_version": res.config["attacker_prompt_version"],
            "trials_per_objective": trials,
            "seed": hc.seed,
            "langs": list(langs),
            "objectives": len(chosen),
            "probes": {
                "counted": res.probes["counted"],
                "passed": res.probes["passed"],
                "pass": res.probes["pass"],
                "failed": res.probes["failed"][:20],
                "known_limitations": res.probes["known_limitations"],
            },
            **_compact_cells(agg),
            "by_objective": dict(list(agg["by_objective"].items())[:MAX_OBJECTIVE_DETAILS]),
            "traces": traces,
        }
        return RunnerOutput(
            status="ok",
            metrics=metrics,
            n_items=n,
            data_mode=mode,  # type: ignore[arg-type]
            dataset_id=ds_id,
            dataset_sha256=sha,
            is_mock=True,
            details=details,
        )
