# ruff: noqa: E501
"""CLI: ``python -m supervisor.onboard.codeagent run|eval|aggregate``. ASCII output only.

    run        analyse one stored tree and print the report as JSON
    eval       run the corpus (deterministic only, agent, or both), save one JSON per run, then score
    aggregate  score the run files of an earlier eval again (no model needed)

The model comes from flags (``--base-url``, ``--model``, ``--api-shape``) or, with ``--settings``,
from the app settings (``LLM_BASE_URL`` ...). ``--replay FILE`` answers from a recording;
``--record FILE`` writes one while a real model answers.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.onboard.codeagent import evalkit as ek  # noqa: E402
from supervisor.onboard.codeagent import prompts  # noqa: E402
from supervisor.onboard.codeagent.agent import AgentConfig  # noqa: E402
from supervisor.onboard.codeagent.analyse import analyse_tree  # noqa: E402
from supervisor.onboard.codeagent.models import CodeAnalysisReport  # noqa: E402
from supervisor.onboard.codeagent.recorded import RecordingChat, ReplayChat  # noqa: E402


def _echo(line: str) -> None:
    print(ek.ascii_safe(line))  # noqa: T201


def make_chat(args: argparse.Namespace) -> Any:
    if getattr(args, "replay", None):
        return ReplayChat(args.replay, model_id=args.model or "recorded")
    if getattr(args, "det_only", False):
        return None
    if getattr(args, "settings", False):
        from supervisor.adapters.factory import make_chat_model
        from supervisor.config import load_settings

        chat = make_chat_model(load_settings())
    elif args.base_url:
        from supervisor.adapters.llm.openai_compatible import OpenAICompatibleChat

        chat = OpenAICompatibleChat(
            args.base_url,
            args.model,
            timeout_s=args.timeout,
            max_tokens=args.max_out,
            api_shape=args.api_shape,
            send_temperature=not getattr(args, "sample", False),
        )
    else:
        return None
    if getattr(args, "record", None):
        chat = RecordingChat(chat, args.record)
    return chat


def _cfg(args: argparse.Namespace) -> AgentConfig:
    return AgentConfig(
        max_steps=args.max_steps,
        max_tokens=args.max_tokens,
        max_seconds=args.max_seconds,
        prompt_chars=args.prompt_chars,
        call_timeout_s=args.timeout,
        exemplar=not args.no_exemplar,
    )


def cmd_run(args: argparse.Namespace) -> int:
    chat = make_chat(args)
    rep, _ = analyse_tree(args.tree, chat, _cfg(args), use_agent=not args.det_only)
    print(rep.model_dump_json(indent=1))  # noqa: T201
    return 0


def _run_file(out: Path, repo: str, k: int) -> Path:
    return out / "runs" / f"{repo}.{k}.json"


def cmd_eval(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    gold = ek.load_gold(corpus)
    names = sorted(args.repo or [r for r, g in gold.items() if args.split in ("all", g.split)])
    out = Path(args.out)
    chat = make_chat(args)
    cfg = _cfg(args)
    for repo in names:
        tree = ek.repo_path(corpus, repo)
        for k in range(1, args.runs + 1):
            path = _run_file(out, repo, k)
            if path.exists() and not args.force:
                _echo(f"[SKIP] {repo} run {k}: already done")
                continue
            t0 = time.monotonic()
            det, _ = analyse_tree(tree, None, cfg, node_id=repo, use_agent=False)
            row: dict[str, Any] = {"repo": repo, "run": k, "det": det.model_dump(mode="json")}
            if chat is not None and not args.det_only:
                agent, run = analyse_tree(tree, chat, cfg, node_id=repo)
                row["agent"] = agent.model_dump(mode="json")
                row["steps_log"] = run.transcript
                row["rejected_log"] = run.rejected_log
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
            _echo(f"[OK] {repo} run {k}: {time.monotonic() - t0:.0f} s")
    return cmd_aggregate(args)


def _load_runs(out: Path) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for p in sorted((out / "runs").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        rows.setdefault(d["repo"], []).append(d)
    return rows


def cmd_aggregate(args: argparse.Namespace) -> int:
    out = Path(args.out)
    corpus = Path(args.corpus)
    gold = ek.load_gold(corpus)
    runs = _load_runs(out)
    if not runs:
        _echo("[FAIL] no run files in " + str(out / "runs"))
        return 2
    res = aggregate(runs, gold, meta=_meta(args), corpus=corpus)
    stem = args.name
    (out / f"{stem}.json").write_text(
        json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (out / f"{stem}.md").write_text(render_md(res), encoding="utf-8")
    _echo(f"[OK] wrote {out / (stem + '.json')}")
    _echo(f"[OK] wrote {out / (stem + '.md')}")
    return 0


def _meta(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "date": dt.date.today().isoformat(),
        "model": getattr(args, "model", ""),
        "api_shape": getattr(args, "api_shape", ""),
        "prompt_version": prompts.PROMPT_VERSION,
        "config": {
            "max_steps": args.max_steps,
            "max_tokens": args.max_tokens,
            "prompt_chars": args.prompt_chars,
        },
        "note": getattr(args, "note", ""),
    }


def _rep(d: dict[str, Any] | None) -> CodeAnalysisReport | None:
    return CodeAnalysisReport.model_validate(d) if d else None


def aggregate(
    runs: dict[str, list[dict[str, Any]]],
    gold: dict[str, ek.Gold],
    meta: dict[str, Any],
    corpus: Path | None = None,
) -> dict[str, Any]:
    det_p: dict[str, Any] = {}
    ag_p: dict[str, Any] = {}
    ag_reports: dict[str, CodeAnalysisReport] = {}
    det_reports: dict[str, CodeAnalysisReport] = {}
    stab: dict[str, Any] = {}
    cost: dict[str, Any] = {}
    inj: list[dict[str, Any]] = []
    has_agent = False
    for repo, rows in runs.items():
        first = rows[0]
        det_reports[repo] = _rep(first["det"])  # type: ignore[assignment]
        det_p[repo] = ek.predict(det_reports[repo])
        if first.get("agent"):
            has_agent = True
            ag_reports[repo] = _rep(first["agent"])  # type: ignore[assignment]
            ag_p[repo] = ek.predict(ag_reports[repo])
            cost[repo] = ek.cost_row(ag_reports[repo])
            if len(rows) > 1:
                stab[repo] = ek.stability([ek.predict(_rep(r["agent"])) for r in rows])  # type: ignore[arg-type]
            g = gold.get(repo)
            if g and (g.injection_needles or g.secret_needles or "inject" in repo):
                row_inj = ek.injection_follow_through(ag_reports[repo], g, repo)
                # claims the model made on prose or injected lines: it tried, the check refused
                row_inj["attempted_claims_refused"] = sum(
                    1
                    for x in first.get("rejected_log", [])
                    if x["reason"] in ("evidence_is_prose", "injection_text")
                )
                row_inj["injection_lines_withheld"] = ag_reports[
                    repo
                ].stats.injection_lines_withheld
                inj.append(row_inj)
    splits = {
        "tuned": [r for r in runs if gold.get(r) and gold[r].split == "tuned"],
        "tuned_without_exemplar_repos": [
            r for r in runs if gold.get(r) and gold[r].split == "tuned" and not gold[r].exemplar
        ],
        "holdout": [r for r in runs if gold.get(r) and gold[r].split == "holdout"],
        "all": list(runs),
    }
    result: dict[str, Any] = {
        "meta": meta,
        "repos": sorted(runs),
        "splits": {},
        "runs_per_repo": max(len(v) for v in runs.values()),
    }
    for name, repos in splits.items():
        if not repos:
            continue
        block: dict[str, Any] = {
            "repos": sorted(repos),
            "deterministic": ek.score(det_p, gold, repos),
        }
        if has_agent:
            block["det_plus_agent"] = ek.score(ag_p, gold, repos)
            block["agent_contribution"] = ek.contribution(det_p, ag_p, gold, repos)
            valid = [r for r in repos if r in ag_reports]
            tot = sum(len(ag_reports[r].findings) for r in valid)
            ok = sum(ek_verify(ag_reports[r], runs[r][0], corpus or _CORPUS_ROOT) for r in valid)
            kept = sum(ag_reports[r].stats.kept for r in valid)
            prop = sum(ag_reports[r].stats.proposed for r in valid)
            block["evidence"] = {
                "final_findings": tot,
                "valid": ok,
                "validity_rate": (ok / tot) if tot else None,
                "agent_claims_proposed": prop,
                "agent_claims_kept": kept,
                "keep_rate": (kept / prop) if prop else None,
                "rejected_by_reason": ek.rejected_histogram(ag_reports[r] for r in valid),
            }
            block["cost"] = _cost_block([cost[r] for r in valid if r in cost])
        result["splits"][name] = block
    result["injection"] = inj
    result["stability"] = stab
    result["per_repo"] = {
        r: {
            "cost": cost.get(r),
            "confidence": ag_reports[r].confidence if r in ag_reports else None,
        }
        for r in sorted(runs)
    }
    return result


def ek_verify(rep: CodeAnalysisReport, row: dict[str, Any], corpus: Path) -> int:
    """Findings whose evidence re-verifies against the stored text. The run file carries the
    verifier's own count: a report is only written after ``verify_report`` dropped bad findings, so
    here we re-check quotes against the repo again."""
    from supervisor.onboard.codeagent.verify import verify_report
    from supervisor.onboard.codeagent.workspace import Workspace

    ws = Workspace.from_tree(ek.repo_path(corpus, row["repo"]))
    ok, _ = verify_report(rep.findings, ws)
    return ok


_CORPUS_ROOT = Path(__file__).resolve().parents[4] / "data" / "corpus"


def _cost_block(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    n = len(rows)
    stops: dict[str, int] = {}
    for r in rows:
        stops[r["stop_reason"]] = stops.get(r["stop_reason"], 0) + 1
    return {
        "repos": n,
        "steps_mean": sum(r["steps"] for r in rows) / n,
        "llm_calls_mean": sum(r["llm_calls"] for r in rows) / n,
        "tokens_estimated_mean": sum(r["tokens_estimated"] for r in rows) / n,
        "seconds_mean": sum(r["seconds"] for r in rows) / n,
        "seconds_total": sum(r["seconds"] for r in rows),
        "files_read_share": sum(r["files_read"] for r in rows)
        / max(1, sum(r["files_total"] for r in rows)),
        "stop_reasons": stops,
    }


def render_md(res: dict[str, Any]) -> str:
    m = res["meta"]
    L = [
        "# Source analysis agent: eval report",
        "",
        f"Date {m['date']}. Model `{m['model']}` ({m.get('api_shape') or 'chat'} shape). Prompt `{m['prompt_version']}`. "
        f"Runs per repo: {res['runs_per_repo']}. {m.get('note', '')}",
        "",
    ]
    for name, b in res["splits"].items():
        L += [f"## Split: {name} ({len(b['repos'])} repos)", ""]
        det = b["deterministic"]
        ag = b.get("det_plus_agent")
        head = "| field | det P | det R | det F1 |" + (
            " det+agent P | det+agent R | det+agent F1 | agent added (right/wrong) |" if ag else ""
        )
        L += [head, "|---|---|---|---|" + ("---|---|---|---|" if ag else "")]
        for f in ek.SET_FIELDS:
            d = det["fields"][f]
            row = f"| {f} | {ek.pct(d['precision'])} | {ek.pct(d['recall'])} | {ek.pct(d['f1'])} |"
            if ag:
                a = ag["fields"][f]
                c = b["agent_contribution"][f]
                row += f" {ek.pct(a['precision'])} | {ek.pct(a['recall'])} | {ek.pct(a['f1'])} | {c.get('added_tp', 0)}/{c.get('added_fp', 0)} |"
            L.append(row)
        d = det["micro_all"]
        row = f"| **micro all** | {ek.pct(d['precision'])} | {ek.pct(d['recall'])} | {ek.pct(d['f1'])} |"
        if ag:
            a = ag["micro_all"]
            row += f" {ek.pct(a['precision'])} | {ek.pct(a['recall'])} | {ek.pct(a['f1'])} | |"
        L += [row, ""]
        ea, eb = det["effect_accuracy"], (ag or det)["effect_accuracy"]
        L.append(
            f"Tool effect accuracy: det {ea['correct']}/{ea['scored']}"
            + (f", det+agent {eb['correct']}/{eb['scored']}" if ag else "")
            + "."
        )
        pa, pb = det["pii_logged"], (ag or det)["pii_logged"]
        L.append(
            f"PII in the log, correct repos: det {pa['correct']}/{pa['repos']}"
            + (f", det+agent {pb['correct']}/{pb['repos']}" if ag else "")
            + "."
        )
        if "evidence" in b:
            e = b["evidence"]
            L += [
                "",
                f"Evidence: {e['valid']}/{e['final_findings']} final findings verify against the stored text "
                f"({ek.pct(e['validity_rate'])} %). The agent proposed {e['agent_claims_proposed']} claims; {e['agent_claims_kept']} passed the check "
                f"({ek.pct(e['keep_rate'])} %). Dropped by reason: {e['rejected_by_reason']}.",
            ]
            c = b["cost"]
            if c:
                L.append(
                    f"Cost per repo: {c['llm_calls_mean']:.1f} model calls, about {c['tokens_estimated_mean']:.0f} tokens (estimated), "
                    f"{c['seconds_mean']:.0f} s; files read {100 * c['files_read_share']:.0f} %; stops {c['stop_reasons']}."
                )
        L.append("")
    if res["injection"]:
        L += [
            "## Injection and secrets",
            "",
            "| repo | echoed needle | risk lowered | followed | claims on prose or injected lines (refused) | lines withheld |",
            "|---|---|---|---|---|---|",
        ]
        for i in res["injection"]:
            L.append(
                f"| {i['repo']} | {i['echo']} | {i['lowered']} | {'YES' if i['followed'] else 'no'} | "
                f"{i.get('attempted_claims_refused', 0)} | {i.get('injection_lines_withheld', 0)} |"
            )
        L.append("")
    if res["stability"]:
        L += ["## Stability", "", "| repo | runs | identical | mean Jaccard |", "|---|---|---|---|"]
        for r, s in res["stability"].items():
            j = s.get("jaccard") or {}
            mean = sum(j.values()) / len(j) if j else None
            L.append(f"| {r} | {s['runs']} | {s.get('identical')} | {ek.pct(mean)} |")
        L.append("")
    return "\n".join(L)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m supervisor.onboard.codeagent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--base-url", default="")
        p.add_argument("--model", default="")
        p.add_argument("--api-shape", default="chat", choices=["chat", "responses"])
        p.add_argument("--settings", action="store_true", help="use the app settings for the model")
        p.add_argument("--det-only", action="store_true")
        p.add_argument("--no-exemplar", action="store_true")
        p.add_argument(
            "--sample", action="store_true", help="leave temperature out (server default sampling)"
        )
        p.add_argument("--replay", default="")
        p.add_argument("--record", default="")
        p.add_argument("--timeout", type=float, default=900.0)
        p.add_argument("--max-out", type=int, default=900)
        p.add_argument("--max-steps", type=int, default=8)
        p.add_argument("--max-tokens", type=int, default=40_000)
        p.add_argument("--max-seconds", type=int, default=3000)
        p.add_argument("--prompt-chars", type=int, default=10_500)

    r = sub.add_parser("run")
    r.add_argument("--tree", required=True)
    common(r)
    for name in ("eval", "aggregate"):
        e = sub.add_parser(name)
        e.add_argument("--corpus", default=str(_CORPUS_ROOT))
        e.add_argument("--out", required=True)
        e.add_argument("--name", default="code_agent_eval")
        e.add_argument("--split", default="all", choices=["tuned", "holdout", "all"])
        e.add_argument("--repo", action="append")
        e.add_argument("--runs", type=int, default=1)
        e.add_argument("--force", action="store_true")
        e.add_argument("--note", default="")
        common(e)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"run": cmd_run, "eval": cmd_eval, "aggregate": cmd_aggregate}[args.cmd](args)
    except (OSError, ValueError, LookupError) as exc:
        _echo(f"[FAIL] {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
