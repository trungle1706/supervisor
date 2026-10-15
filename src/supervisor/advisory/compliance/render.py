"""Render the obligations matrix as JSON, Markdown and HTML (WP14).

* JSON: sorted keys, indent 2, stable for the same input.
* Markdown and HTML: bilingual headings and status words ("English / Tieng Viet"); the
  obligation text stays in its source language; the disclaimer is at top and bottom.
* HTML is self-contained (inline CSS, no script, no external file) and escapes every value.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

from supervisor.advisory.compliance.i18n import both
from supervisor.advisory.compliance.model import (
    STATUSES,
    DateItem,
    MatrixRow,
    ObligationMatrix,
    to_plain,
)
from supervisor.regkb import DISCLAIMER

FILES = ("compliance_matrix.json", "compliance_matrix.md", "compliance_matrix.html")


def to_json(m: ObligationMatrix) -> str:
    return json.dumps(to_plain(m), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


# ----------------------------------------------------------------------------- document model


@dataclass
class _Block:
    kind: str  # h | p | kv | table | list | details | note
    level: int = 0
    text: str = ""
    items: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


def _status_word(status: str) -> str:
    return both(f"status.{status}")


def _applies_word(applies: str) -> str:
    return both(f"applies.{applies}")


def _date_text(item: DateItem | None, label_key: str | None = None) -> str:
    if item is None:
        return ""
    label = both(label_key) if label_key else item.label
    return f"{label}: {item.date or 'unknown'} ({item.verification})"


def _dates(row: MatrixRow) -> list[str]:
    d = row.deadline
    out: list[str] = []
    for item, key in (
        (d.effective, "effective"),
        (d.article_effective, None),
        (d.compliance_deadline, "compliance_deadline"),
    ):
        if item is not None:
            if key is None:
                out.append(
                    f"{both('article_effective')}: {item.label}: "
                    f"{item.date or 'unknown'} ({item.verification})"
                )
            else:
                out.append(_date_text(item, key))
    out.extend(_date_text(t) for t in d.transitions)
    return out


def _controls(row: MatrixRow) -> list[str]:
    out = []
    for c in row.controls:
        if c.present is None:
            state = both("process")
        else:
            state = both("present") if c.present else both("absent")
        ptr = f" [{c.pointer.kind}:{c.pointer.ref}]" if c.pointer else ""
        out.append(f"{c.kind}:{c.id} ({c.coverage}) {state}{ptr}")
    return out


def _build(m: ObligationMatrix) -> list[_Block]:
    h = m.header
    b: list[_Block] = []
    b.append(_Block("h", 1, f"{both('title')}: {h.product_name}"))
    b.append(_Block("note", text=DISCLAIMER))
    b.append(_Block("p", text=h.advisory_note))
    b.append(_Block("h", 2, both("header")))
    b.append(
        _Block(
            "kv",
            pairs=[
                (both("product"), f"{h.product_name} ({h.product_id})"),
                (both("source"), h.product_source),
                (both("kb_version"), h.regkb_version),
                (both("instruments"), str(h.instruments)),
                (both("obligations"), str(h.obligations)),
                (
                    both("internal_rules"),
                    (both("yes") + ": " + ", ".join(h.internal_instruments))
                    if h.internal_rules
                    else both("no"),
                ),
                (both("as_of"), h.as_of),
                (both("generated_at"), h.generated_at),
            ],
        )
    )
    s = m.summary
    b.append(_Block("h", 2, both("summary")))
    b.append(
        _Block(
            "table",
            headers=[both("by_status"), both("col.count")],
            rows=[[_status_word(k), str(s["by_status"].get(k, 0))] for k in STATUSES],
        )
    )
    b.append(
        _Block(
            "table",
            headers=[both("by_applies"), both("col.count")],
            rows=[[_applies_word(k), str(v)] for k, v in sorted(s["by_applies"].items())],
        )
    )
    b.append(
        _Block(
            "kv",
            pairs=[
                (both("needs_answer_rows"), str(s["needs_answer"])),
                (both("open_questions"), str(s["questions"])),
                (both("threshold_gaps"), str(s["threshold_gaps"])),
            ],
        )
    )
    if m.narrative is not None:
        n = m.narrative
        tags = [both("advisory_label")] + ([both("mock_label")] if n.is_mock else [])
        b.append(_Block("h", 2, f"{both('narrative')} [{'; '.join(tags)}]"))
        b.append(_Block("p", text=n.text))
        b.append(_Block("p", text=f"model: {n.model_id}"))
    d = m.decision33
    b.append(_Block("h", 2, both("decision33")))
    b.append(_Block("p", text=both(f"d33.{d.classification}")))
    items = list(d.lines)
    for e in d.entries:
        state = (
            both("d33.unknown")
            if e.triggered is None
            else both("d33.triggered" if e.triggered else "d33.not_triggered")
        )
        items.append(f"{e.entry}: {state}")
        items.extend(f"  {ln}" for ln in e.lines)
    b.append(_Block("list", items=items))
    b.append(_Block("p", text=f"{both('caveat')}: {d.caveat}"))
    b.append(_Block("h", 2, both("thresholds")))
    if m.thresholds:
        b.append(
            _Block(
                "table",
                headers=[
                    both("col.id"),
                    both("col.limit"),
                    both("col.cap"),
                    both("col.verdict"),
                    both("col.reason"),
                ],
                rows=[
                    [
                        f.id,
                        f"{f.limit_id}: {f.limit_vnd if f.limit_vnd is not None else '-'}",
                        f"{f.cap_vnd} ({f.customer_type})",
                        both(f"verdict.{f.verdict}"),
                        f.reason,
                    ]
                    for f in m.thresholds
                ],
            )
        )
    else:
        b.append(_Block("p", text=both("no_items")))
    b.append(_Block("h", 2, both("questions")))
    if m.questions:
        b.append(
            _Block(
                "table",
                headers=[both("col.id"), both("col.question"), both("col.decides")],
                rows=[
                    [
                        q.id,
                        f"{q.text_en} / {q.text_vi}",
                        ", ".join(q.obligation_ids),
                    ]
                    for q in m.questions
                ],
            )
        )
    else:
        b.append(_Block("p", text=both("no_items")))
    b.append(_Block("h", 2, both("rows")))
    b.append(_Block("p", text=both("section_note")))
    shown = [r for r in m.rows if r.applies != "no"]
    shown.sort(key=lambda r: (r.applies != "yes", r.obligation_id))
    b.append(
        _Block(
            "table",
            headers=[
                both("col.obligation"),
                both("col.article"),
                both("col.summary"),
                both("col.applies"),
                both("col.status"),
                both("col.reason"),
                both("col.controls"),
                both("col.evidence"),
                both("col.dates"),
                both("col.questions"),
            ],
            rows=[
                [
                    r.obligation_id,
                    f"{r.instrument_number} {r.article_ref}",
                    r.summary_en,
                    _applies_word(r.applies),
                    _status_word(r.status),
                    r.status_reason,
                    "\n".join(_controls(r)),
                    "\n".join(
                        [f"{p.kind}:{p.ref}" for p in r.evidence_pointers]
                        + [
                            f"eval_result pack {a} (test evidence, not read)"
                            for a in r.assurance_packs
                        ]
                    ),
                    "\n".join(_dates(r)),
                    ", ".join(r.question_ids),
                ]
                for r in shown
            ],
        )
    )
    na = [r.obligation_id for r in m.rows if r.applies == "no"]
    b.append(
        _Block(
            "details",
            text=f"{both('not_applicable_list')} ({len(na)})",
            items=na,
        )
    )
    b.append(_Block("note", text=DISCLAIMER))
    return b


# ----------------------------------------------------------------------------- markdown


def _md(text: str) -> str:
    # untrusted text (internal rules): no raw HTML, no markdown links
    for a, b in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("[", "\\["), ("]", "\\]")):
        text = text.replace(a, b)
    return text.replace("|", "\\|").replace("\n", "<br>")


def to_markdown(m: ObligationMatrix) -> str:
    out: list[str] = []
    for blk in _build(m):
        if blk.kind == "h":
            out.append("#" * blk.level + " " + blk.text)
        elif blk.kind == "note":
            out.append(f"> **{blk.text}**")
        elif blk.kind == "p":
            out.append(blk.text)
        elif blk.kind == "kv":
            out.append("\n".join(f"- **{k}**: {v}" for k, v in blk.pairs))
        elif blk.kind == "list":
            out.append(
                "\n".join(
                    f"- {i}" if not i.startswith("  ") else f"  - {i.strip()}" for i in blk.items
                )
            )
        elif blk.kind == "table":
            lines = ["| " + " | ".join(_md(h) for h in blk.headers) + " |"]
            lines.append("|" + "|".join("---" for _ in blk.headers) + "|")
            lines.extend("| " + " | ".join(_md(c) for c in r) + " |" for r in blk.rows)
            out.append("\n".join(lines))
        elif blk.kind == "details":
            out.append(f"**{blk.text}**: " + (", ".join(blk.items) or both("no_items")))
    return "\n\n".join(out) + "\n"


# ----------------------------------------------------------------------------- html

_CSS = """
:root{--bg:#fff;--fg:#1b1f24;--muted:#57606a;--line:#d0d7de;--warn:#fff8c5;--head:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9da7b3;
--line:#30363d;--warn:#3b2f00;--head:#161b22}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
main{max-width:1400px;margin:0 auto}
h1,h2{line-height:1.2}
.note{background:var(--warn);border:1px solid var(--line);padding:8px 12px;font-weight:600}
table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border:1px solid var(--line);padding:4px 8px;vertical-align:top;text-align:left}
th{background:var(--head)}
.wrap{overflow-x:auto}
.cell{white-space:pre-line}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px}
dt{color:var(--muted)}
dd{margin:0}
"""


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def to_html(m: ObligationMatrix) -> str:
    parts: list[str] = []
    for blk in _build(m):
        if blk.kind == "h":
            parts.append(f"<h{blk.level}>{_e(blk.text)}</h{blk.level}>")
        elif blk.kind == "note":
            parts.append(f'<p class="note">{_e(blk.text)}</p>')
        elif blk.kind == "p":
            parts.append(f"<p>{_e(blk.text)}</p>")
        elif blk.kind == "kv":
            parts.append(
                "<dl>"
                + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in blk.pairs)
                + "</dl>"
            )
        elif blk.kind == "list":
            parts.append("<ul>" + "".join(f"<li>{_e(i.strip())}</li>" for i in blk.items) + "</ul>")
        elif blk.kind == "table":
            head = "".join(f"<th>{_e(h)}</th>" for h in blk.headers)
            body = "".join(
                "<tr>" + "".join(f'<td class="cell">{_e(c)}</td>' for c in r) + "</tr>"
                for r in blk.rows
            )
            parts.append(
                f'<div class="wrap"><table><thead><tr>{head}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>"
            )
        elif blk.kind == "details":
            body = ", ".join(_e(i) for i in blk.items) or _e(both("no_items"))
            parts.append(f"<details><summary>{_e(blk.text)}</summary><p>{body}</p></details>")
    title = _e(f"{both('title')}: {m.header.product_name}")
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{_CSS}</style></head><body><main>"
        + "\n".join(parts)
        + "</main></body></html>\n"
    )


def write_all(m: ObligationMatrix, out_dir: Path | str) -> dict[str, Path]:
    """Write compliance_matrix.json / .md / .html into ``out_dir`` (created if missing)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    texts = {"json": to_json(m), "md": to_markdown(m), "html": to_html(m)}
    paths = {
        "json": out / FILES[0],
        "md": out / FILES[1],
        "html": out / FILES[2],
    }
    for key, path in paths.items():
        path.write_text(texts[key], encoding="utf-8", newline="\n")
    return paths
