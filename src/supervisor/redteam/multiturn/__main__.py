"""CLI: python -m supervisor.redteam.multiturn <command>

    run          drive the conversations, write results.json, report.md and traces.jsonl
    probes       run the 39 probes that the templates do not generate
    list         list the objectives
    build-data   write (or --check) data/eval/multiturn_redteam/{objectives,probes}.jsonl
    baseline     compare to (or --write) data/eval/multiturn_redteam/baseline_template.json
    validate     dev and held-out runs with GO / NO-GO per metric (validation report)

Output is ASCII. Exit 0 when nothing is NO-GO, 1 when a metric is NO-GO, 2 for a usage error.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from pathlib import Path  # noqa: E402

from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.redteam.multiturn import harness as H  # noqa: E402
from supervisor.redteam.multiturn.catalogue import (  # noqa: E402
    DATA_DIR,
    OBJECTIVES_PATH,
    build_objectives,
    dumps_objectives,
    load_objectives,
)
from supervisor.redteam.multiturn.model import AGENTS, FAMILIES  # noqa: E402
from supervisor.redteam.multiturn.probes import (  # noqa: E402
    PROBES_PATH,
    build_probes_jsonl,
    evaluate_probes,
)
from supervisor.redteam.multiturn.runner import RunConfig  # noqa: E402
from supervisor.redteam.multiturn.samples import (  # noqa: E402
    SAMPLES_PATH,
    build_samples_jsonl,
)

LLM_CAP = 60


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _out(text: str = "") -> None:
    print(_ascii(text))  # noqa: T201


def manifest_text() -> str:
    objs = dumps_objectives(build_objectives())
    probes = build_probes_jsonl()
    manifest = {
        "capability": "multiturn_redteam",
        "wp": "WP28",
        "files": {
            "objectives.jsonl": {
                "items": objs.count("\n"),
                "sha256": hashlib.sha256(objs.encode("utf-8")).hexdigest(),
            },
            "probes.jsonl": {
                "items": probes.count("\n"),
                "sha256": hashlib.sha256(probes.encode("utf-8")).hexdigest(),
            },
        },
        "source": "own",
        "licence": "own (Apache-2.0 like the repo)",
        "labeller": "expert rubric",
        "label_note": "every objective is an attack (label attack); benign controls are generated "
        "from each objective's benign_steps",
        "splits": "pair level; ordinals 3, 6, 9 of each family are heldout (30 percent); "
        "tune on dev only",
        "data": "synthetic; no real names, accounts or customers",
    }
    return json.dumps(manifest, indent=1, sort_keys=True) + "\n"


def build_data(check: bool) -> int:
    targets = {
        OBJECTIVES_PATH: dumps_objectives(build_objectives()),
        PROBES_PATH: build_probes_jsonl(),
        DATA_DIR / "MANIFEST.json": manifest_text(),
        SAMPLES_PATH: build_samples_jsonl(),
    }
    stale = []
    for path, text in targets.items():
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            _out(f"[OK] wrote {path}")
    if stale:
        _out(f"[FAIL] stale data files: {', '.join(stale)} (run build-data)")
        return 1
    if check:
        _out("[OK] data files are current")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m supervisor.redteam.multiturn",
        description="Multi-turn Vietnamese red team against the sandbox agents (gate in SHADOW).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run a campaign and write the report")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--trials", type=int, default=8, help="trials per objective (default 8)")
    run.add_argument("--worst-trials", type=int, help="worst-case trials (default = trials)")
    run.add_argument("--benign-trials", type=int, default=3)
    run.add_argument("--seed", type=int, default=20261020)
    run.add_argument("--lang", choices=("vi", "en", "both"), default="vi")
    run.add_argument("--split", choices=("dev", "heldout", "all"), default="all")
    run.add_argument("--agent", choices=AGENTS, action="append")
    run.add_argument("--family", choices=FAMILIES, action="append")
    run.add_argument("--attacker", choices=("template", "llm"), default="template")
    run.add_argument("--judge", choices=("none", "mock"), default="none")
    run.add_argument("--max-conversations", type=int, help="cap on attack conversations")
    run.add_argument("--no-traces", action="store_true")
    sub.add_parser("probes", help="run the adversarial probes")
    ls = sub.add_parser("list", help="list objectives")
    ls.add_argument("--family", choices=FAMILIES)
    ls.add_argument("--lang", choices=("vi", "en"))
    bd = sub.add_parser("build-data", help="write or check the data files")
    bd.add_argument("--check", action="store_true")
    bl = sub.add_parser("baseline", help="compare to (or --write) the recorded regression baseline")
    bl.add_argument("--write", action="store_true")
    val = sub.add_parser("validate", help="dev + held-out runs and verdicts")
    val.add_argument("--out", type=Path, required=True)
    val.add_argument("--trials", type=int, default=50)
    val.add_argument("--seed", type=int, default=20261020)
    return p


def _cmd_run(a: argparse.Namespace) -> int:
    from supervisor.config import load_settings

    settings = load_settings()
    langs = ("vi", "en") if a.lang == "both" else (a.lang,)
    attacker = None
    cap = a.max_conversations
    if a.attacker == "llm":
        attacker = H.settings_attacker(settings)
        if attacker.kind != "llm":
            _out("[FAIL] --attacker llm needs REDTEAM_ATTACKER_MODEL (and LLM_BASE_URL)")
            return 2
        cap = min(cap or LLM_CAP, LLM_CAP, settings.redteam_llm_max_conversations)
        _out(f"[INFO] LLM attacker {attacker.model_id}: capped at {cap} attack conversations")
    base = RunConfig()
    if attacker is not None:
        base.attacker = attacker
    if a.judge == "mock":
        from supervisor.redteam.multiturn.evidence_judge import HeuristicEvidenceJudge

        base.judge, base.judge_max = HeuristicEvidenceJudge(), 10**6
    hc = H.HarnessConfig(
        trials=a.trials,
        worst_trials=0 if attacker is not None else a.worst_trials,
        benign_trials=a.benign_trials,
        seed=a.seed,
        langs=langs,
        split=a.split,
        agents=tuple(a.agent or AGENTS),
        families=tuple(a.family or FAMILIES),
        run=base,
        max_attack_conversations=cap,
    )
    res = H.run_harness(hc, work_dir=a.out / "work")
    if attacker is not None:
        # an unreachable endpoint or bad model id silently falls back to the templates; say so
        cost = res.aggregate["cost"]
        tried, fell = int(cost.get("llm_turns", 0)), int(cost.get("llm_fallback_turns", 0))
        note = f"LLM attacker: {fell} of {tried} rephrase attempts fell back to the template text"
        res.notes.append(note)
        _out(f"[{'WARN' if fell else 'INFO'}] {note}")
    files = H.write_outputs(res, a.out, traces=not a.no_traces)
    m = res.metrics
    _out(
        f"[OK] conversations={m['conversations']} attack_success_bp={m['attack_success_bp']} "
        f"gate_catch_bp={m['gate_catch_bp']} unexpected_escapes={m['unexpected_escape_count']} "
        f"known_gaps_open={m['known_gap_open_count']} false_alarm_bp={m['false_alarm_bp']} "
        f"probe_pass_bp={m['probe_pass_bp']} [MOCK agent]"
    )
    for f in files:
        _out(f"[OK] wrote {f}")
    return 1 if "NO-GO" in res.verdicts.values() else 0


def _cmd_probes() -> int:
    r = evaluate_probes()
    _out(f"[OK] probes {r['probes']} counted {r['counted']} passed {r['passed']} {r['pass']}")
    for f in r["failed"]:
        _out(f"[FAIL] {f['id']} {f['tag']} {f['class']}")
    for pid in r["known_limitations"]:
        _out(f"[INFO] known limitation {pid}")
    return 1 if r["failed"] else 0


def _cmd_list(a: argparse.Namespace) -> int:
    n = 0
    for o in load_objectives():
        if (a.family and o.family != a.family) or (a.lang and o.lang != a.lang):
            continue
        n += 1
        _out(f"{o.id:16s} {o.split:8s} {o.agent:17s} {o.kind:26s} gap={o.gap_class or '-'}")
    _out(f"{n} objective(s)")
    return 0


def _cmd_baseline(a: argparse.Namespace) -> int:
    res = H.run_harness(H.regression_config())
    if a.write:
        H.BASELINE_PATH.write_text(
            json.dumps(H.baseline_record(res), indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        _out(f"[OK] wrote {H.BASELINE_PATH}")
        return 0
    base = json.loads(H.BASELINE_PATH.read_text(encoding="utf-8"))
    problems = H.compare_to_baseline(H.metrics_for_baseline(res), base)
    for p in problems:
        _out(f"[FAIL] {p}")
    if not problems:
        _out("[OK] no regression against the recorded baseline")
    return 1 if problems else 0


def _cmd_validate(a: argparse.Namespace) -> int:
    worst = 0
    a.out.mkdir(parents=True, exist_ok=True)
    for split in ("dev", "heldout"):
        hc = H.HarnessConfig(
            trials=a.trials, seed=a.seed, langs=("vi", "en"), split=split, keep_turns=False
        )
        res = H.run_harness(hc, work_dir=a.out / "work" / split)
        H.write_outputs(res, a.out / split, traces=False)
        _out(
            f"== {split}: " + ", ".join(f"{k}={v}" for k, v in res.verdicts.items() if v != "INFO")
        )
        if split == "heldout" and "NO-GO" in res.verdicts.values():
            worst = 1
    return worst


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "run":
            return _cmd_run(args)
        if args.cmd == "probes":
            return _cmd_probes()
        if args.cmd == "list":
            return _cmd_list(args)
        if args.cmd == "build-data":
            return build_data(args.check)
        if args.cmd == "baseline":
            return _cmd_baseline(args)
        return _cmd_validate(args)
    except (SupervisorError, ValueError, OSError) as exc:
        _out(f"[FAIL] {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
