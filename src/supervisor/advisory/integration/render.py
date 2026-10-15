"""Render the report as JSON, Markdown (en or vi) and one self-contained HTML page.

The text comes from the report only. Everything is escaped in HTML; the page loads nothing
from outside. The report holds file:line references and no repo excerpts, so there is no
"untrusted excerpt" block; the narrative is model output that was neutralised and is shown
with its source.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from supervisor.advisory.integration.advise import Advice, patch_filename
from supervisor.advisory.integration.models import IntegrationReport
from supervisor.advisory.integration.scoring import RUBRIC
from supervisor.onboard.instrument import check_dirs

# TODO(vi): the Vietnamese wording needs a review by a native speaker before bank use.
_T: dict[str, tuple[str, str]] = {
    "title": ("Integration report", "Báo cáo tích hợp"),
    "agent": ("Agent", "Tác tử"),
    "narrative": ("Summary", "Tóm tắt"),
    "narrative_note": (
        "Written by a language model from the facts below; it changes no score or finding.",
        "Do mô hình ngôn ngữ viết từ các dữ kiện bên dưới; không làm đổi điểm hay kết quả.",
    ),
    "source": ("source", "nguồn"),
    "readiness": ("Readiness", "Mức sẵn sàng"),
    "area": ("Area", "Hạng mục"),
    "weight": ("Weight", "Trọng số"),
    "points": ("Points", "Điểm"),
    "reason": ("Reason", "Lý do"),
    "rule": ("Rule", "Quy tắc"),
    "found": ("What we found", "Những gì tìm thấy"),
    "needed": ("What to add", "Cần bổ sung"),
    "patches": ("Patches", "Bản vá"),
    "framework": ("Framework", "Khung làm việc"),
    "tools": ("Tools", "Công cụ"),
    "tool": ("Tool", "Công cụ"),
    "risk": ("Risk class", "Nhóm rủi ro"),
    "side_effects": ("Side effects", "Tác động phụ"),
    "amount_arg": ("Amount arg", "Tham số số tiền"),
    "dest_arg": ("Destination arg", "Tham số đích"),
    "defined_at": ("Defined at", "Định nghĩa tại"),
    "gated": ("Gated", "Có cổng"),
    "llm_calls": ("LLM call sites", "Điểm gọi LLM"),
    "data_access": ("Data access", "Truy cập dữ liệu"),
    "pii": ("Personal data fields", "Trường dữ liệu cá nhân"),
    "tracing": ("Tracing", "Tracing"),
    "mcp": ("MCP server", "Máy chủ MCP"),
    "secrets": ("Secrets redacted", "Bí mật đã che"),
    "injection": (
        "Lines flagged as possible prompt injection (file:line only)",
        "Dòng nghi tiêm lệnh (chỉ file:dòng)",
    ),
    "gate_sites": ("Gate call sites", "Vị trí đặt cổng"),
    "mode": ("Mode", "Cách làm"),
    "decorator": ("Decorator", "Decorator"),
    "semconv": ("Span attributes to emit", "Thuộc tính span cần phát"),
    "operation": ("Operation", "Thao tác"),
    "settings": ("Settings (.env)", "Cài đặt (.env)"),
    "catalogue": ("Capabilities to enable", "Năng lực cần bật"),
    "test_plan": ("Assurance test plan", "Kế hoạch kiểm thử đảm bảo"),
    "manual": ("Do by hand", "Làm thủ công"),
    "policy": ("Policy YAML (starts in SHADOW)", "Chính sách YAML (bắt đầu ở SHADOW)"),
    "mcp_proxy": ("MCP proxy", "Proxy MCP"),
    "none": ("none", "không có"),
    "yes": ("yes", "có"),
    "no": ("no", "không"),
    "apply": (
        "Apply a patch with: git apply patches/NN-name.patch (review it first).",
        "Áp dụng bản vá bằng: git apply patches/NN-name.patch (xem lại trước).",
    ),
}


def _t(key: str, lang: str) -> str:
    en, vi = _T[key]
    return vi if lang == "vi" else en


def render_json(report: IntegrationReport) -> str:
    data = report.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


# A block is (kind, payload): h1 h2 text, p text, quote text, code text, ul [text],
# table (headers, rows).
Block = tuple[str, Any]


def _blocks(r: IntegrationReport, lang: str) -> list[Block]:
    t = lambda k: _t(k, lang)  # noqa: E731
    b: list[Block] = [
        ("h1", f"{t('title')}: {r.name} ({r.agent_id} {r.version})"),
        ("p", f"{t('framework')}: {r.framework}"),
    ]
    if r.narrative.text:
        b += [
            ("h2", t("narrative")),
            ("quote", r.narrative.text),
            ("p", f"{t('narrative_note')} ({t('source')}: {r.narrative.source})"),
        ]
    area_desc = {a.id: (a.vi if lang == "vi" else a.en) for a in RUBRIC}
    b += [
        ("h2", f"{t('readiness')}: {r.readiness.total} / 100"),
        (
            "table",
            (
                [t("area"), t("weight"), t("points"), t("reason"), t("rule")],
                [
                    [a.id, a.weight, a.points, a.reason, area_desc.get(a.id, "")]
                    for a in r.readiness.areas
                ],
            ),
        ),
    ]
    f = r.found
    yn = lambda v: t("yes") if v else t("no")  # noqa: E731
    b.append(("h2", t("found")))
    b.append(("p", f"{t('framework')}: {f.framework.name} ({f.framework.evidence or '-'})"))
    b.append(
        (
            "table",
            (
                [
                    t("tool"),
                    t("risk"),
                    t("side_effects"),
                    t("amount_arg"),
                    t("dest_arg"),
                    t("defined_at"),
                    t("gated"),
                ],
                [
                    [
                        x.name,
                        x.risk_class,
                        ", ".join(x.side_effects) or "-",
                        x.amount_arg or "-",
                        x.destination_arg or "-",
                        x.defined_at or "-",
                        yn(x.gated),
                    ]
                    for x in f.tools
                ],
            ),
        )
    )
    b.append(("h2", t("llm_calls")))
    b.append(
        (
            "table",
            (
                ["provider", "family", "model", "via", "at"],
                [[c.provider, c.family, c.model or "-", c.via, c.at] for c in f.llm_calls],
            ),
        )
    )
    b.append(("h2", t("data_access")))
    b.append(
        (
            "table",
            (
                ["kind", "direction", "target", "at"],
                [[d.kind, d.direction, d.target or "-", d.at] for d in f.data_access],
            ),
        )
    )
    b.append(
        (
            "ul",
            [
                f"{t('pii')}: " + (", ".join(f"{p.name} ({p.at})" for p in f.pii_fields) or "-"),
                f"{t('tracing')}: " + (", ".join(f.tracing) or t("none")),
                f"{t('mcp')}: {yn(f.mcp_server)}",
                f"{t('secrets')}: {f.secrets_count}",
                f"{t('injection')}: " + (", ".join(f.injection_refs) or t("none")),
            ],
        )
    )
    n = r.needed
    b.append(("h2", t("needed")))
    b.append(("h2", t("gate_sites")))
    b.append(
        (
            "table",
            (
                [t("tool"), t("risk"), t("defined_at"), t("mode"), t("decorator"), t("reason")],
                [
                    [g.tool, g.risk_class, g.at or "-", g.mode, g.decorator, g.note]
                    for g in n.gate_sites
                ],
            ),
        )
    )
    b.append(("h2", t("semconv")))
    b.append(
        (
            "table",
            (
                [t("operation"), "attributes", t("reason")],
                [[s.operation, ", ".join(s.attributes), s.note] for s in n.semconv],
            ),
        )
    )
    if n.mcp_proxy:
        b += [
            ("h2", t("mcp_proxy")),
            ("p", f"{n.mcp_proxy.config_path}: {n.mcp_proxy.note}"),
            ("code", " ".join(n.mcp_proxy.command)),
        ]
    b.append(("h2", t("settings")))
    b.append(
        (
            "table",
            (
                ["key", t("reason"), "example"],
                [[s.key, s.purpose, s.example] for s in n.settings],
            ),
        )
    )
    b.append(("h2", t("catalogue")))
    b.append(
        (
            "table",
            (
                ["id", "name", "kind", "lane"],
                [[c.id, c.name, c.kind, c.lane] for c in n.catalogue],
            ),
        )
    )
    b.append(("h2", t("test_plan")))
    b.append(("table", ([t("area"), t("reason")], [[a.dimension, a.reason] for a in n.test_plan])))
    b.append(("h2", t("manual")))
    b.append(("ul", [f"{m.what}{' (' + m.at + ')' if m.at else ''}: {m.note}" for m in n.manual]))
    if n.policy_yaml:
        b += [("h2", t("policy")), ("code", n.policy_yaml)]
    b.append(("h2", t("patches")))
    b.append(("p", t("apply")))
    b.append(
        (
            "table",
            (
                ["file", "path", "kind", t("reason")],
                [[p.file, p.path, p.kind, p.description] for p in r.patches],
            ),
        )
    )
    return b


def _md_cell(v: Any) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def render_md(report: IntegrationReport, lang: str = "en") -> str:
    out: list[str] = []
    for kind, data in _blocks(report, lang):
        if kind == "h1":
            out.append(f"# {data}\n")
        elif kind == "h2":
            out.append(f"## {data}\n")
        elif kind == "p":
            out.append(f"{data}\n")
        elif kind == "quote":
            out.append("\n".join(f"> {line}" for line in str(data).splitlines()) + "\n")
        elif kind == "code":
            out.append(f"```\n{str(data).rstrip()}\n```\n")
        elif kind == "ul":
            out.append("\n".join(f"- {x}" for x in data) + "\n" if data else "-\n")
        elif kind == "table":
            heads, rows = data
            if not rows:
                out.append("-\n")
                continue
            lines = ["| " + " | ".join(_md_cell(h) for h in heads) + " |"]
            lines.append("|" + "|".join("---" for _ in heads) + "|")
            lines += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in rows]
            out.append("\n".join(lines) + "\n")
    return "\n".join(out)


_CSS = """
:root{--bg:#fff;--fg:#1b1f24;--muted:#59636e;--line:#d0d7de;--accent:#0b5fff;--code:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;
--line:#30363d;--accent:#58a6ff;--code:#161b22}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;
max-width:1100px;padding:16px}
h1{font-size:1.5em}h2{font-size:1.2em;margin-top:1.6em;border-bottom:1px solid var(--line)}
table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
pre{background:var(--code);padding:12px;overflow-x:auto;border-radius:6px}
blockquote{border-left:4px solid var(--accent);margin:0;padding:4px 12px;color:var(--fg)}
.muted{color:var(--muted)}
""".strip()


def render_html(report: IntegrationReport, lang: str = "en") -> str:
    e = html.escape
    out: list[str] = []
    for kind, data in _blocks(report, lang):
        if kind == "h1":
            out.append(f"<h1>{e(data)}</h1>")
        elif kind == "h2":
            out.append(f"<h2>{e(data)}</h2>")
        elif kind == "p":
            out.append(f'<p class="muted">{e(data)}</p>')
        elif kind == "quote":
            out.append(f"<blockquote>{e(data)}</blockquote>")
        elif kind == "code":
            out.append(f"<pre><code>{e(str(data))}</code></pre>")
        elif kind == "ul":
            out.append("<ul>" + "".join(f"<li>{e(str(x))}</li>" for x in data) + "</ul>")
        elif kind == "table":
            heads, rows = data
            if not rows:
                out.append('<p class="muted">-</p>')
                continue
            head = "".join(f"<th>{e(str(h))}</th>" for h in heads)
            body = "".join(
                "<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in row) + "</tr>" for row in rows
            )
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
    return (
        '<!doctype html>\n<html lang="'
        + ("vi" if lang == "vi" else "en")
        + '"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(_t('title', lang))}: {e(report.agent_id)}</title>"
        f"<style>{_CSS}</style></head><body>" + "\n".join(out) + "</body></html>\n"
    )


def write_outputs(advice: Advice, out_dir: Path, *, target: Path | None = None) -> dict[str, Path]:
    """Write the JSON, Markdown and HTML report and ``patches/NN-<slug>.patch``.

    Refuses an ``out_dir`` inside ``target`` (nothing is ever written into the target)."""
    out = Path(out_dir).resolve()
    target = target or advice.target
    if target is not None:
        check_dirs(Path(target).resolve(), out)
    out.mkdir(parents=True, exist_ok=True)
    report = advice.report
    paths: dict[str, Path] = {}

    def put(name: str, text: str) -> None:
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        paths[name] = path

    put("integration_report.json", render_json(report))
    put("integration_report.md", render_md(report))
    put("integration_report.html", render_html(report))
    for i, patch in enumerate(advice.patches, start=1):
        put(patch_filename(i, patch), patch.diff)
    return paths
