"""report.json (deterministic: no timestamps, timings or absolute paths), report.md, stdout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from supervisor.onboard.eval.runner import EvalResult

_TIMING = "corpus_seconds"


def ascii_safe(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def build_report(res: EvalResult) -> dict[str, Any]:
    """The JSON report. The elapsed time is NOT included, only ``latency_ok``."""
    gates = [g for g in res.gates if g["metric"] != _TIMING]
    return {
        "corpus": res.corpus,
        "repos": res.repos,
        "fields": res.fields,
        "gates": gates,
        "latency_ok": res.latency_ok,
        "all_gates_ok": res.all_gates_ok,
    }


def _pct(v: Any) -> str:
    return "n/a" if v is None else f"{v // 100}.{v % 100:02d}%"


def _ci(v: Any) -> str:
    return "n/a" if not v else f"{_pct(v[0])} to {_pct(v[1])}"


def render_md(report: dict[str, Any]) -> str:
    out = ["# Corpus eval report", "", f"Corpus: `{report['corpus']}`", ""]
    out += [
        "## Fields (set-type)",
        "",
        "| field | precision | precision 95% CI | recall | recall 95% CI | F1 | TP | FP | FN |",
    ]
    out.append("|---|---|---|---|---|---|---|---|---|")
    for f in ("tools", "entrypoints", "llm_calls", "data_access", "pii_fields"):
        r = report["fields"][f]
        out.append(
            f"| {f} | {_pct(r['precision_bp'])} | {_ci(r.get('precision_ci_bp'))}"
            f" | {_pct(r['recall_bp'])} | {_ci(r.get('recall_ci_bp'))} | {_pct(r['f1_bp'])}"
            f" | {r['tp']} | {r['fp']} | {r['fn']} |"
        )
    out += ["", "## Fields (accuracy and extras)", "", "| metric | value |", "|---|---|"]
    for f, r in sorted(report["fields"].items()):
        for k, v in sorted(r.items()):
            if k.endswith("_ci_bp"):
                out.append(f"| {f}.{k} | {_ci(v)} |")
            elif k.endswith("_bp") and k not in ("precision_bp", "recall_bp", "f1_bp"):
                out.append(f"| {f}.{k} | {_pct(v)} |")
            elif f in ("secrets", "injections") and not k.endswith("_bp"):
                out.append(f"| {f}.{k} | {v} |")
    out += ["", "## Gates", "", "| gate | metric | value | rule | ok |", "|---|---|---|---|---|"]
    for g in report["gates"]:
        val = "n/a" if g["value"] is None else g["value"]
        out.append(
            f"| {g['name']} | {g['metric']} | {val} | {g['op']} {g['threshold']} |"
            f" {'yes' if g['ok'] else 'NO'} |"
        )
    out.append(
        f"| latency | corpus time | - | within limit | {'yes' if report['latency_ok'] else 'NO'} |"
    )
    out += ["", "## Per-repo misses", ""]
    for r in report["repos"]:
        notes = []
        for field_name, m in r["misses"].items():
            if m["fn"]:
                notes.append(f"- {field_name} FN: " + ", ".join(f"`{x}`" for x in m["fn"]))
            if m["fp"]:
                notes.append(f"- {field_name} FP: " + ", ".join(f"`{x}`" for x in m["fp"]))
        for field_name, (want, got) in r["wrong"].items():
            notes.append(f"- {field_name}: expected `{want}`, got `{got}`")
        if r["secrets_leaked"]:
            notes.append(f"- secrets leaked: {r['secrets_leaked']}")
        if r["injection_follow_through"]:
            notes.append("- injection follow-through")
        out += [f"### {r['name']}", "", *(notes or ["- no misses"]), ""]
    return "\n".join(out) + "\n"


def write_report(res: EvalResult, out_dir: str | Path) -> dict[str, Path]:
    report = build_report(res)
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    paths = {"json": folder / "report.json", "md": folder / "report.md"}
    paths["json"].write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    paths["md"].write_text(render_md(report), encoding="utf-8")
    return paths


def summary_lines(res: EvalResult) -> list[str]:
    """ASCII stdout summary: one line per field, gate lines, elapsed seconds."""
    lines = []
    for f, r in res.fields.items():
        if "tp" in r:
            lines.append(
                f"{f}: P={_pct(r['precision_bp'])} [{_ci(r.get('precision_ci_bp'))}] "
                f"R={_pct(r['recall_bp'])} [{_ci(r.get('recall_ci_bp'))}] "
                f"F1={_pct(r['f1_bp'])} (tp={r['tp']} fp={r['fp']} fn={r['fn']})"
            )
        elif "accuracy_bp" in r:
            lines.append(f"{f}: accuracy={_pct(r['accuracy_bp'])} ({r['correct']}/{r['repos']})")
        elif f == "secrets":
            lines.append(
                f"secrets: scrubbed={_pct(r['scrubbed_bp'])} leaked={r['leaked']} "
                f"kind={_pct(r['kind_accuracy_bp'])} (n={r['total']})"
            )
        else:
            lines.append(
                f"injections: detected={_pct(r['detected_recall_bp'])} "
                f"follow_through={r['follow_through']} (n={r['total']})"
            )
    for g in res.gates:
        tag = "[OK]" if g["ok"] else "[FAIL]"
        val = "n/a" if g["value"] is None else g["value"]
        lines.append(f"{tag} gate {g['name']}: {val} {g['op']} {g['threshold']}")
    lines.append(f"elapsed: {res.elapsed_s:.1f} s")
    return [ascii_safe(x) for x in lines]
