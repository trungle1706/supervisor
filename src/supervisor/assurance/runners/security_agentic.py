"""Security packs on the supervision stack: red-team replay, ATLAS coverage, judge injection."""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from supervisor.assurance.model import EvalPack, RunContext, RunnerOutput, not_applicable_reason
from supervisor.assurance.runners import security_common as sc
from supervisor.assurance.runners.security_common import SkipPack
from supervisor.assurance.taxonomy import ATLAS, ATLAS_NAMES
from supervisor.assurance.textutil import bp, sha256_lines, stable_rank

REDTEAM_DIR = Path("agents") / "redteam"
REDTEAM_FILES = ("incidents.jsonl", "incidents_wp17.jsonl")
PACKS_DIR = Path(__file__).resolve().parent.parent / "packs"
MAX_REPLAY_CHARS = 2000  # same cut as the launch replay


# --------------------------------------------------------------------------- red-team replay


def _asi_id(case: dict[str, Any]) -> str:
    label = str(case["taxonomy"]["owasp_agentic"])
    return label.split(" ", 1)[0] if label != "none" else "none"


class AgenticRedteamRunner:
    """Replay the 145-case red-team pack (+ WP17 extension) like ``onboard.launch`` does."""

    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        target = ctx.target
        try:
            sc.need_kind(target, "agent")
            sc.need_capability(target, "planned")
            if ctx.data_mode == "vendored":
                raise SkipPack("no vendored sample for this pack")
            cases, mode, ds_id = self._load(pack, ctx)
        except SkipPack as exc:
            return RunnerOutput.skip(str(exc))
        tid = str(target.target_id)
        applicable: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for case in cases:
            planned = [
                {"tool": c["tool"], "args": dict(c.get("args") or {})}
                for c in (case.get("input", {}).get("planned_tool_calls") or [])
                if c.get("agent") == tid
            ]
            if case.get("agent") == tid or (case.get("agent") == "multi" and planned):
                applicable.append((case, planned))
        if ctx.max_items is not None and len(applicable) > ctx.max_items:
            keep = sorted(applicable, key=lambda cp: stable_rank(pack.id, cp[0]["id"]))
            ids = {cp[0]["id"] for cp in keep[: ctx.max_items]}
            applicable = [cp for cp in applicable if cp[0]["id"] in ids]
        if not applicable:
            return RunnerOutput.skip(
                not_applicable_reason(
                    f"no red-team case is written for agent {tid!r}",
                    "supply cases (<ASSURANCE_DATA_DIR>/owasp_agentic_redteam)",
                )
            )
        if len(applicable) < pack.min_items:
            return RunnerOutput.skip(
                f"only {len(applicable)} red-team cases fit {tid!r}, pack needs {pack.min_items}"
            )
        rule_n = caught = benign_n = false_alarm = info = 0
        by_asi: dict[str, list[bool]] = defaultdict(list)
        missed: list[str] = []
        flagged_benign: list[str] = []
        for case, planned in applicable:
            expected = str(case.get("expected_detection"))
            if not planned:
                info += 1
                continue
            reply = target.run_planned(str(case["input"]["content"])[:MAX_REPLAY_CHARS], planned)
            stopped = bool(reply.gate_would_stop)
            if expected == "rule":
                rule_n += 1
                caught += 1 if stopped else 0
                by_asi[_asi_id(case)].append(stopped)
                if not stopped:
                    missed.append(case["id"])
            elif expected == "none-benign":
                benign_n += 1
                false_alarm += 1 if stopped else 0
                if stopped:
                    flagged_benign.append(case["id"])
            else:
                info += 1
        lines = [sc.item_line(c) for c, _ in applicable]
        return RunnerOutput(
            status="ok",
            metrics={
                "catch_rate_bp": bp(caught, rule_n),
                "false_alarm_bp": bp(false_alarm, benign_n),
                "cases_applicable": len(applicable),
            },
            n_items=len(applicable),
            data_mode=mode,  # type: ignore[arg-type]
            dataset_id=ds_id,
            dataset_sha256=sha256_lines(lines),
            is_mock=bool(getattr(target, "is_mock", False)),
            details={
                "rule_cases": rule_n,
                "benign_cases": benign_n,
                "info_cases": info,
                "catch_by_asi": sc.group_stats(by_asi),
                "missed_case_ids": missed[:40],
                "false_alarm_case_ids": flagged_benign[:40],
            },
        )

    @staticmethod
    def _load(pack: EvalPack, ctx: RunContext) -> tuple[list[dict[str, Any]], str, str]:
        bank = ctx.bank_dir(pack.id)
        use_bank = ctx.data_mode == "bank" or (
            ctx.data_mode == "auto" and bank is not None and (bank / REDTEAM_FILES[0]).is_file()
        )
        if use_bank:
            if bank is None or not (bank / REDTEAM_FILES[0]).is_file():
                raise SkipPack(f"no bank data at <ASSURANCE_DATA_DIR>/{pack.id}/{REDTEAM_FILES[0]}")
            folder, mode, ds = bank, "bank_supplied_path", f"bank/{pack.id}"
        else:
            folder, mode, ds = ctx.repo_root / REDTEAM_DIR, "synthetic", REDTEAM_DIR.as_posix()
        cases: list[dict[str, Any]] = []
        for name in REDTEAM_FILES:
            path = folder / name
            if path.is_file():
                cases += sc.load_jsonl(path)
        if not cases:
            raise SkipPack(f"no red-team cases at {folder}")
        return cases, mode, ds


# --------------------------------------------------------------------------- ATLAS coverage


def load_manifests(directory: Path) -> tuple[list[EvalPack], int]:
    """Every valid manifest in ``directory`` and the number of files that did not validate."""
    packs: list[EvalPack] = []
    bad = 0
    for path in sorted(directory.glob("*.yaml")):
        try:
            packs.append(EvalPack.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))))
        except (yaml.YAMLError, ValidationError, UnicodeDecodeError, TypeError):
            bad += 1
    return packs, bad


class AtlasCoverageRunner:
    """Coverage check only: it does not call the agent. Which ATLAS techniques do the packs
    and the security probe sets reference? A technique counts as covered when a manifest
    ``maps_to.atlas`` or a probe tag names it, or names one of its sub-techniques."""

    PROBE_FILES = (
        "owasp_llm_top10",
        "garak_probe_families",
        "indirect_injection_vi",
        "finance_harm_refusal",
        "pii_canary",
    )

    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        packs, bad = load_manifests(PACKS_DIR)
        vocab = sorted(ATLAS)
        if len(vocab) < pack.min_items:
            return RunnerOutput.skip("ATLAS vocabulary is too small")
        tags: set[str] = set()
        by_pack: dict[str, list[str]] = {}
        for p in packs:
            ids = sorted(p.maps_to.atlas)
            by_pack[p.id] = ids
            tags.update(ids)
        unmapped = 0
        probes_seen = 0
        syn = ctx.repo_root / sc.SYNTHETIC_DIR
        for name in self.PROBE_FILES:
            path = syn / f"{name}.jsonl"
            if not path.is_file():
                continue
            for item in sc.load_jsonl(path):
                if item.get("kind") == "benign":
                    continue  # utility / near-miss controls are not attacks
                probes_seen += 1
                ids = [t for t in item.get("atlas") or [] if t in ATLAS]
                if ids:
                    tags.update(ids)
                else:
                    unmapped += 1
        covered = set()
        for t in tags:
            covered.add(t)
            if t.count(".") > 1:
                covered.add(t.rsplit(".", 1)[0])
        covered &= ATLAS
        uncovered = sorted(ATLAS - covered)
        return RunnerOutput(
            status="ok",
            metrics={
                "atlas_techniques_covered": len(covered),
                "atlas_coverage_bp": bp(len(covered), len(ATLAS)),
                "unmapped_security_probes": unmapped,
            },
            n_items=len(vocab),
            data_mode="synthetic",
            dataset_id="manifests:src/supervisor/assurance/packs + probe tags",
            dataset_sha256=sha256_lines(
                [f"{k}:{','.join(v)}" for k, v in sorted(by_pack.items())]
                + [f"{i}={ATLAS_NAMES[i]}" for i in vocab]
            ),
            is_mock=bool(getattr(ctx.target, "is_mock", False)),
            details={
                "check_only": "does not call the agent",
                "packs_read": len(packs),
                "manifests_invalid": bad,
                "probes_read": probes_seen,
                "uncovered": uncovered,
                "covered_by_pack": {k: v for k, v in sorted(by_pack.items()) if v},
            },
        )


# --------------------------------------------------------------------------- judge injection


class JudgeInjectionRunner:
    """Judge-targeted attacks via the judge eval harness (``runs=1``, all items one split)."""

    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        target = ctx.target
        try:
            sc.need_kind(target, "judge")
        except SkipPack as exc:
            return RunnerOutput.skip(str(exc))
        factory = target.router_factory()
        if factory is None:
            return RunnerOutput.skip("judge target has no router factory")
        from supervisor.judge.eval import build_eval_sets, run_eval
        from supervisor.judge.eval.datasets import INJECTION_PATH

        items = build_eval_sets()
        inj = [i for i in items if i.set == "injection"]
        if ctx.max_items is not None and len(inj) > ctx.max_items:
            inj = sorted(inj, key=lambda i: stable_rank(pack.id, i.id))[: ctx.max_items]
        if len(inj) < pack.min_items:
            return RunnerOutput.skip(
                f"only {len(inj)} injection items, pack needs {pack.min_items}"
            )
        base_ids = {i.base_id for i in inj}
        inj_ids = {i.id for i in inj}
        selected = [
            dataclasses.replace(i, split="all")
            for i in items
            if i.id in inj_ids or i.id in base_ids
        ]
        report = run_eval(selected, factory, runs=1, splits=("all",))
        m = report["metrics"]["all"]
        lines = [ln for ln in INJECTION_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return RunnerOutput(
            status="ok",
            metrics={
                "injection_move_bp": m["injection_move_rate_bp"],
                "injection_lowered_bp": m["injection_lowered_bp"],
                "canary_leak_bp": m["canary_leak_bp"],
                "injection_detect_bp": m["injection_detect_bp"],
            },
            n_items=len(inj),
            data_mode="synthetic",
            dataset_id="data/golden/judge_injection_templates.jsonl",
            dataset_sha256=sha256_lines(lines),
            is_mock=bool(report["mock"]),
            details={
                "threshold_bp": report["threshold_bp"],
                "move_bp": report["move_bp"],
                "models": {k: str(v) for k, v in report["models"].items()},
                "harness": "supervisor.judge.eval.run_eval, runs=1",
            },
        )
