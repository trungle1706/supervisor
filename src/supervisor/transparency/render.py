"""Render a report as JSON, HTML or PDF (WP31), through the case-file code.

* JSON: canonical text of the data model (sorted keys, UTF-8, no floats).
* HTML: one self-contained page; the style block is the case-file page's own (read from its
  template, so there is no new CSS and one place to change it).
* PDF: the case-file PDF writer's pieces (``find_font``, ``RenderResult``, optional ``fpdf2``,
  no font download, no network); with no ``fpdf2`` or no local Unicode font the answer is the
  HTML file with a notice, as for a case file.

The HTML and the PDF are written from the same display blocks (``blocks.py``).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from supervisor.console.i18n import translator
from supervisor.evidence.casefile.render_html import _TEMPLATE_DIR as CASEFILE_TEMPLATES
from supervisor.evidence.casefile.render_pdf import RenderResult, find_font
from supervisor.transparency.blocks import to_blocks
from supervisor.transparency.model import check_lang

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STYLE = re.compile(r"<style>.*?</style>", re.S)


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader([str(_TEMPLATE_DIR), str(CASEFILE_TEMPLATES)]),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def case_file_style() -> str:
    """The ``<style>`` block of the case-file page."""
    env = _env()
    source = env.loader.get_source(env, "casefile.html.j2")[0]  # type: ignore[union-attr]
    m = _STYLE.search(source)
    return m.group(0) if m else ""


def render_json(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def document(report: dict[str, Any], lang: str) -> dict[str, Any]:
    """Title, meta rows, display sections and footer of the report in one language."""
    check_lang(lang)
    t = translator(lang)
    variant = report["variant"]
    status = report.get("status", "preview")
    meta = [
        (t("tp_meta_version"), report["report_version"]),
        (t("tp_meta_generated"), report["generated_at"]),
    ]
    if status == "signed":
        meta.append((t("tp_meta_status"), t("tp_status_signed")))
    if variant != "customer":
        meta.insert(0, (t("tp_f_agent_id"), report.get("agent_id")))
        meta.append((t("tp_meta_schema"), report["schema_version"]))
    return {
        "lang": lang,
        "title": t(f"tp_title_{variant}"),
        "meta": meta,
        "preview": t("tp_status_preview") if status != "signed" else "",
        "sections": to_blocks(report, lang),
        "footer": t("tp_footer_c") if variant == "customer" else t("tp_footer"),
    }


def render_html(report: dict[str, Any], lang: str) -> bytes:
    doc = document(report, lang)
    return (
        _env()
        .get_template("transparency.html.j2")
        .render(style=case_file_style(), **doc)
        .encode("utf-8")
    )


def lines(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """(kind, text) pairs for the PDF; kind is h1, h2, h3 or p."""
    out: list[tuple[str, str]] = [("h1", doc["title"])]
    out += [("p", f"{a}: {b}") for a, b in doc["meta"]]
    if doc["preview"]:
        out.append(("p", doc["preview"]))
    for s in doc["sections"]:
        out.append(("h2", s["title"]))
        for b in s["blocks"]:
            if b["k"] == "kv":
                out += [("p", f"{a}: {'-' if v is None else v}") for a, v in b["rows"]]
            elif b["k"] == "table":
                out.append(("p", " | ".join(b["head"])))
                out += [
                    ("p", " | ".join("-" if c is None else str(c) for c in row))
                    for row in b["rows"]
                ]
            elif b["k"] == "ul":
                out += [("p", f"- {i}") for i in b["li"]]
            else:
                out.append(("h3" if b.get("cls") == "h3" else "p", b["text"]))
    out.append(("h2", ""))
    out.append(("p", doc["footer"]))
    return out


def plain_text(report: dict[str, Any], lang: str) -> str:
    """All visible text of the document (used to check what a variant shows)."""
    return "\n".join(text for _, text in lines(document(report, lang)))


def render_pdf(report: dict[str, Any], lang: str, *, font_path: Path | None = None) -> RenderResult:
    doc = document(report, lang)

    def fallback(reason: str) -> RenderResult:
        return RenderResult(
            fmt="html",
            data=render_html(report, lang),
            notice=f"PDF not produced: {reason}; HTML returned instead",
        )

    try:
        from fpdf import FPDF
    except ImportError:
        return fallback("fpdf2 is not installed (pip install supervisor[pdf])")
    font = find_font(font_path)
    if font is None:
        return fallback("no Unicode TTF font found (set CASEFILE_PDF_FONT)")
    pdf: Any = FPDF(format="A4")
    stamp = dt.datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00"))
    pdf.set_creation_date(stamp)
    pdf.set_title(doc["title"])
    pdf.add_font("tp", fname=str(font))
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    for kind, text in lines(doc):
        size = {"h1": 16, "h2": 12, "h3": 10, "p": 9}[kind]
        pdf.set_font("tp", size=size)
        if kind in ("h1", "h2"):
            pdf.ln(2)
        if text:
            pdf.multi_cell(0, size * 0.5 + 2, text, new_x="LMARGIN", new_y="NEXT")
    return RenderResult(fmt="pdf", data=bytes(pdf.output()), notice=None)
