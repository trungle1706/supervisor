"""Text reports for a run: one-line CLI rows, Markdown and JSON.

The Markdown is plain English. TODO(vi): Vietnamese headings; the console i18n catalogue
(``supervisor.console.i18n``) can supply them when the console shows assurance results.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.assurance.model import PackResult
from supervisor.assurance.results import RunSummary, dumps_results, summary_to_dict

STATUS_TAG = {
    "ok": "[OK]",
    "warn": "[WARN]",
    "fail": "[FAIL]",
    "skip": "[SKIP]",
    "error": "[ERROR]",
}
ILLUSTRATIVE_NOTE = "Thresholds are illustrative defaults until the bank sets its own."
MOCK_NOTE = (
    "MOCK RUN: at least one result comes from a mock model or a mock target. The numbers "
    "prove the harness and the supervision stack, not a real model."
)


def ascii_text(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _limit(thr: Mapping[str, Any] | None) -> str:
    if not thr:
        return ""
    op = ">=" if thr.get("direction", "higher_better") == "higher_better" else "<="
    return f"(go{op}{thr['go']})"


def metric_cell(name: str, value: int | None, thr: Mapping[str, Any] | None) -> str:
    shown = "-" if value is None else str(value)
    text = f"{name}={shown}"
    lim = _limit(thr)
    return f"{text} {lim}" if lim else text


def metric_cells(
    r: PackResult, thresholds: Mapping[str, Mapping[str, Any]], *, key_only: bool
) -> list[str]:
    thr = thresholds.get(r.pack_id, {})
    names = [m for m in r.metrics if m in thr] if key_only else list(r.metrics)
    if key_only and not names:
        names = list(r.metrics)[:3]
    return [metric_cell(m, r.metrics.get(m), thr.get(m)) for m in names]


def result_line(r: PackResult, thresholds: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> str:
    """``[OK]   pack_id  dimension  target  metric=value (go>=x) ...`` (ASCII)."""
    tag = STATUS_TAG.get(r.status, f"[{r.status.upper()}]")
    parts = [f"{tag:<7}", r.pack_id, r.dimension, f"{r.target_kind}:{r.target_id}"]
    cells = metric_cells(r, thresholds, key_only=True)
    if r.status in ("skip", "error") and r.reasons:
        cells = [r.reasons[0]]
    elif r.is_mock:
        cells.append("mock")
    return ascii_text("  ".join(parts + cells))


def summary_line(s: RunSummary) -> str:
    c = s.counts
    return (
        f"run {s.run_id}: {sum(c.values())} results: ok {c.get('ok', 0)}, warn {c.get('warn', 0)}, "
        f"fail {c.get('fail', 0)}, skip {c.get('skip', 0)}, error {c.get('error', 0)}"
        + (" [MOCK]" if s.is_mock else "")
    )


def _cell(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def render_markdown(s: RunSummary) -> str:
    lines = [
        "# Assurance eval report",
        "",
        f"- Run id: `{s.run_id}`",
        f"- Started: {s.started_at.isoformat(timespec='seconds')}",
        f"- Finished: {s.finished_at.isoformat(timespec='seconds')}",
        f"- Selector: `{s.selector or 'all'}`",
        f"- Targets: {', '.join(f'`{k}:{i}`' for k, i in s.targets) or '(none)'}",
        "- Counts: "
        + ", ".join(f"{k} {s.counts.get(k, 0)}" for k in ("ok", "warn", "fail", "skip", "error")),
        "",
    ]
    if s.is_mock:
        lines += [f"> **{MOCK_NOTE}**", ""]
    for note in s.notes:
        lines += [f"- Note: {_cell(note)}"]
    if s.notes:
        lines.append("")
    for kind, tid in s.targets:
        rows = [r for r in s.results if (r.target_kind, r.target_id) == (kind, tid)]
        mock = " (mock)" if any(r.is_mock for r in rows) else ""
        lines += [
            f"## Target `{kind}:{tid}`{mock}",
            "",
            "| Pack | Dimension | Status | Metrics vs thresholds | Data mode | Items |",
            "|---|---|---|---|---|---|",
        ]
        for r in rows:
            if r.status == "skip":
                continue
            cells = "; ".join(metric_cells(r, s.thresholds, key_only=False))
            if r.status == "error":
                cells = "; ".join(r.reasons)
            lines.append(
                f"| {_cell(r.pack_id)} | {r.dimension} | {STATUS_TAG[r.status]} | "
                f"{_cell(cells) or '-'} | {_cell(r.data_mode) or '-'} | {r.n_items} |"
            )
        problems = [r for r in rows if r.status in ("warn", "fail")]
        if problems:
            lines += ["", "Why:"]
            for r in problems:
                lines += [f"- `{r.pack_id}`: " + _cell("; ".join(r.reasons))]
        skipped = [r for r in rows if r.status == "skip"]
        if skipped:
            lines += ["", "Skipped packs (never counted as passed):", ""]
            for r in skipped:
                lines.append(f"- `{r.pack_id}` ({r.dimension}): {_cell('; '.join(r.reasons))}")
        lines.append("")
    lines += [ILLUSTRATIVE_NOTE, ""]
    return "\n".join(lines)


def render_json(s: RunSummary) -> str:
    return dumps_results(summary_to_dict(s))
