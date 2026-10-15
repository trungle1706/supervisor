"""Judge validation report with a deterministic GO / NO_GO decision (WP19).

``python -m supervisor.judge.mrm validate --out DIR [--runs N] [--packs FILE]
[--model mock|settings] [--no-record | --no-store]``

Exit code: 0 GO, 1 NO_GO, 2 error (bad input, store failure, exception). ``--no-record``
reads the store but writes no row and no chain record. ``--no-store`` does not open the store
at all (nothing read, nothing written, no database file created); ``--out`` files are still
written.

Sections: golden set (held-out split is the validation number), judge-injection
resistance, challenger disagreement, N-run stability, judge-vs-human agreement,
assurance packs (``JudgeValidationInput``), decision, identity. Every number is an
integer (basis points or counts). Thresholds are illustrative (``MRM_*`` settings): the
bank's model-risk function sets the real ones. With the mock judge the plumbing is proven,
not a model.

Reproducibility: ``report_hash`` is the SHA-256 of the canonical report without
``report_hash``, ``validation_id`` and ``ts``. Same repo data + store + settings + runs
give the same hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from supervisor.config import Settings, load_settings
from supervisor.core.canonical import sha256_hex
from supervisor.core.errors import SupervisorError
from supervisor.core.ports import EvidenceSink, TableStore
from supervisor.judge.eval.datasets import build_eval_sets
from supervisor.judge.eval.harness import run_eval, run_once
from supervisor.judge.mockjudge import MockJudgeChat
from supervisor.judge.mrm._common import (
    MOCK_CHALLENGER_ID,
    ascii_safe,
    identity_for,
    parse_now,
    router_factory,
    utc_now,
)
from supervisor.judge.mrm.inputs import (
    EvalResultPacks,
    JudgeValidationInput,
    load_pack_results,
    validate_pack_rows,
)
from supervisor.judge.router import JudgeRouter

REPORT_VERSION = 1
SPLITS = ("heldout", "dev")
NON_HASHED = ("report_hash", "validation_id", "ts")


def _sampled(item_id: str, sample_bp: int) -> bool:
    h = int.from_bytes(hashlib.sha256(item_id.encode("utf-8")).digest()[:8], "big")
    return h % 10000 < sample_bp


def _int_fields(d: Any) -> dict[str, Any]:
    """Keep ints, strs and bools of a mapping (drops floats and nested values)."""
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if isinstance(v, int | str | bool) or v is None}


def _golden_section(held: dict[str, Any]) -> dict[str, Any]:
    return {
        "split": "heldout",
        "n": dict(held["n"]),
        "catch_rate_bp": held["catch_rate_bp"],
        "false_alarm_bp": held["false_alarm_bp"],
        "t1_catch_rate_bp": held["t1_catch_rate_bp"],
        "t1_false_alarm_bp": held["t1_false_alarm_bp"],
        "by_language": {lang: dict(held["by_language"][lang]) for lang in ("vi", "en")},
    }


def _challenger_section(
    settings: Settings, model: str, items: list[Any], primary: JudgeRouter
) -> dict[str, Any]:
    sample_bp = 10000
    if model == "settings":
        if primary.challenger is None:
            return {
                "status": "skipped",
                "note": "no challenger configured (JUDGE_CHALLENGER_MODEL)",
            }
        chats = {"t1": primary.challenger.chat, "t2": primary.t2.chat}
        label = primary.challenger.model_id
    else:
        chats = {
            "t1": MockJudgeChat(1, model_id=MOCK_CHALLENGER_ID),
            "t2": MockJudgeChat(2, model_id="mock-judge-t2-v1"),
        }
        label = MOCK_CHALLENGER_ID
    sample = [i for i in items if i.split == "heldout" and _sampled(i.id, sample_bp)]
    thr = settings.judge_t1_threshold_bp
    base = run_once(sample, primary, 0, thr)
    chal_router = JudgeRouter.from_settings(settings, chats=chats)
    chal = run_once(sample, chal_router, 0, thr)

    def flag(bp: int | None) -> bool:
        return bp is not None and bp >= thr

    diff = sum(1 for a, b in zip(base, chal, strict=True) if flag(a.t1_bp) != flag(b.t1_bp))
    n = len(sample)
    notes = ["challenger vs primary Tier 1 flag at the Tier 1 threshold, on the held-out sample"]
    if model != "settings":
        notes.append(
            "both judges are mocks with the same heuristic: disagreement 0 proves the "
            "plumbing, not model diversity"
        )
    return {
        "status": "ok" if n else "skipped",
        "challenger_model_id": label,
        "sample_bp": sample_bp,
        "n": n,
        "disagreements": diff,
        "disagreement_rate_bp": ((diff * 10000 + n // 2) // n) if n else None,
        "notes": notes,
    }


def _agreement_section(settings: Settings, tables: TableStore | None) -> dict[str, Any]:
    if tables is None:
        return {"status": "no_store"}
    try:
        from supervisor.judge.mrm.agreement import agreement_summary
    except ImportError:
        return {"status": "not_available"}
    try:
        raw = agreement_summary(tables, since=None, min_pairs=settings.mrm_min_agreement_pairs)
    except SupervisorError:
        raise
    except Exception as exc:  # store without the tables, etc.: missing evidence, not a crash
        return {"status": "no_store", "note": ascii_safe(f"agreement query failed: {exc}")}
    data = _int_fields(raw)
    pairs = data.get("pairs", data.get("n_pairs"))
    value = data.get("agree_bp", data.get("agreement_bp"))
    pairs = pairs if isinstance(pairs, int) else 0
    data["pairs"] = pairs
    data["agreement_bp"] = value if isinstance(value, int) else None
    data["status"] = "ok" if pairs >= settings.mrm_min_agreement_pairs else "insufficient_pairs"
    data["min_pairs"] = settings.mrm_min_agreement_pairs
    return data


def _check(name: str, value: int | None, threshold: int, op: str) -> dict[str, Any]:
    if value is None:
        passed = False
    elif op == ">=":
        passed = value >= threshold
    else:
        passed = value <= threshold
    return {
        "name": name,
        "value_bp": value,
        "threshold_bp": threshold,
        "op": op,
        "passed": passed,
    }


def run_validation(
    settings: Settings,
    *,
    runs: int = 3,
    packs: JudgeValidationInput | None = None,
    tables: TableStore | None = None,
    evidence: EvidenceSink | None = None,
    now: datetime | None = None,
    model: str = "mock",
    record: bool = True,
) -> dict[str, Any]:
    """Build the report. With ``record`` and a store / sink, write the table row and the
    evidence record (the report itself is the same either way)."""
    runs = max(1, int(runs))
    ts = utc_now(now)
    thr = settings.judge_t1_threshold_bp
    items = build_eval_sets()
    factory = router_factory(settings, model)
    report = run_eval(items, factory, runs=runs, threshold_bp=thr, splits=SPLITS, now=ts)
    held = report["metrics"]["heldout"]
    primary = factory()
    ident = identity_for(settings, primary)

    gullible = run_eval(
        items,
        router_factory(settings, "mock", gullible=True),
        runs=1,
        threshold_bp=thr,
        splits=("heldout",),
        now=ts,
    )["metrics"]["heldout"]
    chal = _challenger_section(settings, model, items, primary)
    agreement = _agreement_section(settings, tables)
    pack_source = "supplied"
    if packs is None and tables is not None:
        # Default source: WP17 assurance results stored for this judge (eval_result).
        stored = EvalResultPacks(tables, primary)
        if stored.results():
            packs, pack_source = stored, "eval_result"
    pack_rows = validate_pack_rows(packs.results()) if packs is not None else []
    packs_section: dict[str, Any] = (
        {"status": "ok", "source": pack_source, "rows": pack_rows}
        if packs is not None
        else {
            "status": "none_supplied",
            "note": "no eval_result rows for this judge; run WP17 judge packs: "
            "python -m supervisor.assurance run <pack> --target judge --judge settings",
        }
    )

    checks = [
        _check("heldout_catch", held["catch_rate_bp"], settings.mrm_min_catch_bp, ">="),
        _check(
            "heldout_false_alarm", held["false_alarm_bp"], settings.mrm_max_false_alarm_bp, "<="
        ),
    ]
    for lang in ("vi", "en"):
        checks.append(
            _check(
                f"catch_{lang}",
                held["by_language"][lang]["catch_rate_bp"],
                settings.mrm_min_lang_catch_bp,
                ">=",
            )
        )
    checks += [
        _check(
            "injection_detect",
            held["injection_detect_bp"],
            settings.mrm_min_injection_detect_bp,
            ">=",
        ),
        _check(
            "injection_lowered",
            held["injection_lowered_bp"],
            settings.mrm_max_injection_lowered_bp,
            "<=",
        ),
        _check("canary_leak", held["canary_leak_bp"], settings.mrm_max_canary_leak_bp, "<="),
    ]
    skipped: list[str] = []
    if chal["status"] == "ok":
        checks.append(
            _check(
                "challenger_disagreement",
                chal["disagreement_rate_bp"],
                settings.mrm_max_challenger_disagree_bp,
                "<=",
            )
        )
    else:
        skipped.append("challenger_disagreement")
    checks.append(
        _check(
            "stability_max_range",
            held["stability"]["max_range_bp"],
            settings.mrm_max_stability_range_bp,
            "<=",
        )
    )
    if agreement.get("status") == "ok":
        checks.append(
            _check(
                "judge_human_agreement",
                agreement["agreement_bp"],
                settings.mrm_min_agreement_bp,
                ">=",
            )
        )
    else:
        skipped.append("judge_human_agreement")
    for row in pack_rows:
        checks.append(
            {
                "name": f"pack:{row['pack_id']}:{row['metric']}",
                "value_bp": row["value_bp"],
                "threshold_bp": row["threshold_bp"],
                "op": row["op"],
                "passed": row["passed"],
            }
        )
    failed = [c["name"] for c in checks if not c["passed"]]
    decision = "GO" if not failed else "NO_GO"

    notes = [
        "Held-out split numbers are the validation numbers; dev is for prompt tuning only.",
        "Thresholds are illustrative (MRM_* settings); the bank sets the real ones.",
        "Tier 1 and Tier 2 thresholds are both taken as the Tier 1 threshold in the eval run.",
        "The mock judge is deterministic: stability variance 0 proves the plumbing. "
        "A real model run is needed for a real number.",
    ]
    if primary.is_mock:
        notes.append("MOCK judge: these numbers prove the harness and protocol, not a model.")
    if agreement.get("status") in ("no_store", "not_available", "insufficient_pairs"):
        notes.append(
            f"judge-vs-human agreement is not a check ({agreement['status']}); needs reviewer "
            f"labels from the bank (at least {settings.mrm_min_agreement_pairs} pairs)."
        )

    body: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "judge_id": ident.judge_id,
        "model_source": model,
        "is_mock": ident.is_mock,
        "runs": runs,
        "identity": ident.as_dict(),
        "thresholds": {
            "judge_t1_threshold_bp": settings.judge_t1_threshold_bp,
            "judge_t2_threshold_bp": settings.judge_t2_threshold_bp,
            "mrm_min_catch_bp": settings.mrm_min_catch_bp,
            "mrm_max_false_alarm_bp": settings.mrm_max_false_alarm_bp,
            "mrm_min_lang_catch_bp": settings.mrm_min_lang_catch_bp,
            "mrm_min_injection_detect_bp": settings.mrm_min_injection_detect_bp,
            "mrm_max_injection_lowered_bp": settings.mrm_max_injection_lowered_bp,
            "mrm_max_canary_leak_bp": settings.mrm_max_canary_leak_bp,
            "mrm_max_challenger_disagree_bp": settings.mrm_max_challenger_disagree_bp,
            "mrm_max_stability_range_bp": settings.mrm_max_stability_range_bp,
            "mrm_min_agreement_bp": settings.mrm_min_agreement_bp,
            "mrm_min_agreement_pairs": settings.mrm_min_agreement_pairs,
        },
        "heldout": dict(report["heldout"]),
        "golden": _golden_section(held),
        "injection": {
            "injection_detect_bp": held["injection_detect_bp"],
            "injection_move_rate_bp": held["injection_move_rate_bp"],
            "injection_lowered_bp": held["injection_lowered_bp"],
            "canary_leak_bp": held["canary_leak_bp"],
            "n_injection": held["n"]["injection"],
        },
        "guard_check_fooled_model": {
            "note": "mock judge that obeys instructions in the data; informational, not a gate",
            "canary_leak_bp": gullible["canary_leak_bp"],
            "injection_lowered_bp": gullible["injection_lowered_bp"],
            "injection_detect_bp": gullible["injection_detect_bp"],
        },
        "challenger": chal,
        "stability": {
            "runs": held["stability"]["runs"],
            "mean_variance_bp2": held["stability"]["mean_variance_bp2"],
            "max_range_bp": held["stability"]["max_range_bp"],
        },
        "agreement": agreement,
        "packs": packs_section,
        "checks": checks,
        "skipped_checks": skipped,
        "failed_checks": failed,
        "decision": decision,
        "passed": decision == "GO",
        "notes": notes,
    }
    body["report_hash"] = sha256_hex({k: v for k, v in body.items() if k not in NON_HASHED})
    # Unique per run: the same report re-run later (yearly re-test, retry) is a new record.
    body["validation_id"] = f"jval-{body['report_hash'][:16]}-{ts.strftime('%Y%m%dT%H%M%SZ')}"
    body["ts"] = ts.isoformat()
    if record:
        _record(settings, body, ts, tables, evidence)
    return body


def metrics_of(report: dict[str, Any]) -> dict[str, Any]:
    g = report["golden"]
    return {
        "catch_rate_bp": g["catch_rate_bp"],
        "false_alarm_bp": g["false_alarm_bp"],
        "catch_vi_bp": g["by_language"]["vi"]["catch_rate_bp"],
        "catch_en_bp": g["by_language"]["en"]["catch_rate_bp"],
        "injection_detect_bp": report["injection"]["injection_detect_bp"],
        "injection_lowered_bp": report["injection"]["injection_lowered_bp"],
        "canary_leak_bp": report["injection"]["canary_leak_bp"],
        "challenger_disagreement_bp": report["challenger"].get("disagreement_rate_bp"),
        "challenger_n": report["challenger"].get("n", 0),
        "stability_max_range_bp": report["stability"]["max_range_bp"],
        "agreement_bp": report["agreement"].get("agreement_bp"),
        "agreement_pairs": report["agreement"].get("pairs", 0),
        "heldout_n_items": report["heldout"]["n_items"],
    }


def _record(
    settings: Settings,
    report: dict[str, Any],
    ts: datetime,
    tables: TableStore | None,
    evidence: EvidenceSink | None,
) -> None:
    ident = report["identity"]
    metrics = metrics_of(report)
    # Table row first: if it fails (duplicate id, store error) no orphan chain entry.
    if tables is not None:
        tables.append(
            "model_validation",
            [
                {
                    "validation_id": report["validation_id"],
                    "ts": ts,
                    "judge_id": ident["judge_id"],
                    "model_version": ident["model_version"],
                    "prompt_hash": ident["prompt_hash"],
                    "rubric_version": ident["rubric_version"],
                    "mask_version": ident["mask_version"],
                    "golden_set_hash": ident["golden_set_hash"],
                    "is_mock": ident["is_mock"],
                    "decision": report["decision"],
                    "passed": report["passed"],
                    "runs": report["runs"],
                    "metrics": metrics,
                    "thresholds": report["thresholds"],
                    "failed_checks": report["failed_checks"],
                    "validator": settings.mrm_validator,
                    "report_hash": report["report_hash"],
                }
            ],
        )
    if evidence is not None:
        evidence.record(
            "judge_validation",
            report["validation_id"],
            {
                "judge_id": ident["judge_id"],
                "model_version": ident["model_version"],
                "prompt_hash": ident["prompt_hash"],
                "rubric_version": ident["rubric_version"],
                "mask_version": ident["mask_version"],
                "golden_set_hash": ident["golden_set_hash"],
                "is_mock": ident["is_mock"],
                "decision": report["decision"],
                "passed": report["passed"],
                "runs": report["runs"],
                "metrics": metrics,
                "failed_checks": report["failed_checks"],
                "report_hash": report["report_hash"],
            },
        )


def _fmt(v: int | None) -> str:
    return "-" if v is None else f"{v // 100}.{v % 100:02d}%"


def render_md(report: dict[str, Any]) -> str:
    ident = report["identity"]
    g = report["golden"]
    lines = [
        f"# Judge validation report {report['validation_id']}",
        "",
        f"Decision: **{report['decision']}**"
        + ("  (MOCK judge: plumbing only)" if report["is_mock"] else ""),
        "",
        f"- judge: {ident['judge_id']}",
        f"- model_version: {ident['model_version']}",
        f"- prompt_hash: {ident['prompt_hash']}",
        f"- rubric_version: {ident['rubric_version']}",
        f"- mask_version: {ident['mask_version']}",
        f"- golden_set_hash: {ident['golden_set_hash']}",
        f"- held-out digest: {report['heldout']['digest']} ({report['heldout']['n_items']} items)",
        f"- runs: {report['runs']}; ts: {report['ts']}",
        f"- report_hash: {report['report_hash']}",
        "",
        "## Summary (held-out split)",
        "",
        "| metric | value |",
        "|---|---|",
        f"| catch rate | {_fmt(g['catch_rate_bp'])} |",
        f"| false alarm | {_fmt(g['false_alarm_bp'])} |",
        f"| catch vi / en | {_fmt(g['by_language']['vi']['catch_rate_bp'])} / "
        f"{_fmt(g['by_language']['en']['catch_rate_bp'])} |",
        f"| false alarm vi / en | {_fmt(g['by_language']['vi']['false_alarm_bp'])} / "
        f"{_fmt(g['by_language']['en']['false_alarm_bp'])} |",
        f"| injection detected | {_fmt(report['injection']['injection_detect_bp'])} |",
        f"| injection lowered score | {_fmt(report['injection']['injection_lowered_bp'])} |",
        f"| canary leak | {_fmt(report['injection']['canary_leak_bp'])} |",
        f"| challenger disagreement | {_fmt(report['challenger'].get('disagreement_rate_bp'))} "
        f"(n={report['challenger'].get('n', 0)}) |",
        f"| stability max range | {report['stability']['max_range_bp']} bp over "
        f"{report['stability']['runs']} runs |",
        f"| judge-human agreement | {_fmt(report['agreement'].get('agreement_bp'))} "
        f"({report['agreement']['status']}) |",
        "",
        "Guard check under a fooled model (informational): canary leak "
        f"{_fmt(report['guard_check_fooled_model']['canary_leak_bp'])}, injection lowered "
        f"{_fmt(report['guard_check_fooled_model']['injection_lowered_bp'])}.",
        "",
        "## Checks",
        "",
        "| check | value | op | threshold | result |",
        "|---|---|---|---|---|",
    ]
    for c in report["checks"]:
        lines.append(
            f"| {c['name']} | {_fmt(c['value_bp'])} | {c['op']} | {_fmt(c['threshold_bp'])} | "
            f"{'PASS' if c['passed'] else 'FAIL'} |"
        )
    if report["skipped_checks"]:
        lines += ["", "Skipped: " + ", ".join(report["skipped_checks"])]
    lines += ["", "## Assurance packs", "", f"Status: {report['packs']['status']}"]
    lines += ["", "## Notes", ""] + [f"- {n}" for n in report["notes"]]
    return ascii_safe("\n".join(lines) + "\n")


def ascii_summary(report: dict[str, Any]) -> str:
    out = [f"decision {report['decision']} ({report['validation_id']})"]
    for c in report["checks"]:
        tag = "[OK]  " if c["passed"] else "[FAIL]"
        out.append(f"{tag} {c['name']}: {_fmt(c['value_bp'])} {c['op']} {_fmt(c['threshold_bp'])}")
    for name in report["skipped_checks"]:
        out.append(f"[SKIP] {name}")
    return ascii_safe("\n".join(out))


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m supervisor.judge.mrm validate")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--packs", type=Path, default=None)
    p.add_argument("--model", choices=("mock", "settings"), default="mock")
    p.add_argument("--no-record", action="store_true")
    p.add_argument(
        "--no-store",
        action="store_true",
        help="do not open or write the default store (only the --out files are written)",
    )
    p.add_argument("--now", default=None, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    try:
        now = parse_now(args.now)
        packs = load_pack_results(args.packs) if args.packs else None
        settings = load_settings()
        if args.no_store:
            args.no_record = True
            report = run_validation(
                settings, runs=args.runs, packs=packs, now=now, model=args.model, record=False
            )
        else:
            report = _run_with_store(settings, args, packs, now)
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        (out / "judge_validation.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        (out / "judge_validation.md").write_text(render_md(report), encoding="utf-8")
    except Exception as exc:  # any failure is exit 2, never a traceback or a false GO
        print(ascii_safe(f"[FAIL] judge validation: {exc}"))  # noqa: T201
        return 2
    print(ascii_summary(report))  # noqa: T201
    print(ascii_safe(f"[OK] validation written to {out} ({report['decision']})"))  # noqa: T201
    if not args.no_record:
        print("[OK] recorded: model_validation row + judge_validation evidence")  # noqa: T201
    return 0 if report["decision"] == "GO" else 1


def _run_with_store(
    settings: Settings, args: argparse.Namespace, packs: Any, now: datetime | None
) -> dict[str, Any]:
    kw: dict[str, Any] = {"runs": args.runs, "packs": packs, "now": now, "model": args.model}
    if not args.no_record:
        from supervisor.monitors.jobctx import standalone

        with standalone(settings) as (_, _, ctx):
            return run_validation(settings, tables=ctx.tables, evidence=ctx.evidence, **kw)
    from supervisor.adapters.factory import build_adapters
    from supervisor.jobs import bootstrap_schema

    adapters = build_adapters(settings)
    try:
        if adapters.executor.dialect == "sqlite":
            bootstrap_schema.run(settings, adapters)
        return run_validation(settings, tables=adapters.tables, record=False, **kw)
    finally:
        adapters.close()


if __name__ == "__main__":
    sys.exit(main())
