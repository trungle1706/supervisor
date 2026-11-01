# ruff: noqa: E501
"""Deterministic leads for the topic turns of the agent (the tool policy).

Each function is a fixed use of the read-only workspace tools (grep, outline, read): it picks the
lines a topic needs, so a small model is not asked to search a repo by itself. The text is repo
data: it is wrapped in nonce delimiters and injection lines are withheld before the model sees it.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence

from supervisor.onboard.codeagent.models import Finding
from supervisor.onboard.codeagent.workspace import WITHHELD_LINE, Workspace, _show, prose_lines
from supervisor.onboard.injection import find_injection

MAX_LEADS = 28
CODE_SUFFIX = (".py", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".sql")

RX_HITL = re.compile(
    r"(?i)approv|interrupt|sign_?off|double_?check|maker|checker|four_?eyes|confirm|review|"
    r"escalat|wait_for|human|officer|manager|second|queue|phe_?duyet|xac_?nhan"
)
RX_GUARD = re.compile(
    r"(?i)(\bif\b|\bassert\b|\braise\b|Field\(|validator|limits?\(|rate|allow|whitelist|permitted|"
    r"\bmax\w*|\bmin\w*|\bcap\b|\bnot in\b|\bin \{|\bin \[)[^\n]*(amount|limit|max|total|allow|"
    r"valid|len\(|country|currency|rate|range|<|>|\bnot in\b|\bin\b)"
)
RX_LOG = re.compile(
    r"(?i)\blogg?(er|ing)?\b|\.(info|debug|warning|warn|error|exception)\(|\bprint\(|"
    r"tracer|start_as_current_span|span\b|audit|mlflow\.\w*(autolog|trace)|opentelemetry|"
    r"RotatingFileHandler|FileHandler"
)
RX_SECRET = re.compile(
    r"(?i)environ|getenv|dotenv|secrets?\.|dbutils\.secrets|keyvault|vault|api[_-]?key|token|"
    r"password|passwd|credential|\[REDACTED"
)
RX_NET = re.compile(
    r"(?i)https?://|base_url|endpoint|\bhost\b|\burl\b|requests\.|httpx\.|urlopen|"
    r"\.post\(|\.get\(|\.put\(|\.delete\("
)
RX_FLOW = re.compile(
    r"(?i)\.execute\(|\bspark\.(sql|table)|read_sql|\.to_sql|requests\.|httpx\.|\bopen\(|"
    r"read_csv|to_csv|read_text|write_text|\.connect\(|session\.|\.query\(|saveAsTable|"
    r"\.put\(|\.post\(|\.delete\(|\.patch\("
)


def _enclosing(ws: Workspace) -> dict[str, list[tuple[int, int, str]]]:
    out: dict[str, list[tuple[int, int, str]]] = {}
    for f in ws.files:
        tree = ws.tree(f)
        if tree is None:
            continue
        spans = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                spans.append(
                    (
                        node.lineno,
                        getattr(node, "end_lineno", node.lineno) or node.lineno,
                        node.name,
                    )
                )
        out[f] = sorted(spans, key=lambda s: s[1] - s[0], reverse=True)
    return out


def _fn_at(spans: dict[str, list[tuple[int, int, str]]], f: str, line: int) -> str:
    best = ""
    for lo, hi, name in spans.get(f, []):
        if lo <= line <= hi:
            best = name  # the last (smallest) span that holds the line
    return best


def grep_lines(
    ws: Workspace,
    rx: re.Pattern[str],
    *,
    suffix: Sequence[str] = CODE_SUFFIX,
    limit: int = MAX_LEADS,
    with_fn: bool = False,
) -> str:
    spans = _enclosing(ws) if with_fn else {}
    rows: list[str] = []
    for f in ws.files:
        if not f.endswith(tuple(suffix)):
            continue
        pr = prose_lines(f, ws.lines[f])
        for i, text in enumerate(ws.lines[f], start=1):
            if i in pr or not text.strip() or len(text) > 400 or not rx.search(text):
                continue
            ws.seen.add(f)
            if find_injection(text):
                ws.withheld += 1
                shown = WITHHELD_LINE
            else:
                ws.read_lines.setdefault(f, set()).add(i)
                shown = _show(text.strip())
            fn = _fn_at(spans, f, i) if with_fn else ""
            rows.append(f"{f}:{i}{' [' + fn + ']' if fn else ''}: {shown}")
            if len(rows) >= limit:
                rows.append("[more lines cut]")
                return "\n".join(rows)
    return "\n".join(rows) or "(no matching line)"


def tool_sources(
    ws: Workspace, known: Sequence[Finding], per_tool: int = 22, total_chars: int = 3600
) -> str:
    """Source of each known tool (def to end, cut), then the other public functions as candidates."""
    out: list[str] = []
    used = 0
    seen_fn: set[tuple[str, int]] = set()
    for f in known:
        if f.kind != "tool":
            continue
        ev = f.evidence[0]
        tree = ws.tree(ev.file)
        node = None
        if tree is not None:
            for n in ast.walk(tree):
                if (
                    isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                    and n.lineno <= ev.line <= (getattr(n, "end_lineno", n.lineno) or n.lineno)
                    and (n.lineno == ev.line or ev.line in [d.lineno for d in n.decorator_list])
                ):
                    node = n
                    break
        if node is None:
            out.append(f"TOOL {f.name} defined at {ev.ref()} (body not parsed)")
            continue
        hi = min(
            getattr(node, "end_lineno", node.lineno) or node.lineno, node.lineno + per_tool - 1
        )
        seen_fn.add((ev.file, node.lineno))
        attrs = ", ".join(f"{k}={v}" for k, v in f.attrs.items())
        block = [f"TOOL {f.name} ({ev.file}:{node.lineno}) scanner says: {attrs}"]
        for i in range(node.lineno, hi + 1):
            block.append(
                f"{i}: {_show(ws.lines[ev.file][i - 1])}"
                if not find_injection(ws.lines[ev.file][i - 1])
                else f"{i}: {WITHHELD_LINE}"
            )
            ws.read_lines.setdefault(ev.file, set()).add(i)
        ws.opened.add(ev.file)
        text = "\n".join(block)
        if used + len(text) > total_chars:
            out.append(
                f"TOOL {f.name} ({ev.file}:{node.lineno}) scanner says: {attrs} [body cut: budget]"
            )
            continue
        used += len(text)
        out.append(text)
    cands: list[str] = []
    for fn in ws.files:
        tree = ws.tree(fn)
        if tree is None or fn.startswith(("test", "tests/")):
            continue
        for node in tree.body:
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and not node.name.startswith("_")
                and (fn, node.lineno) not in seen_fn
            ):
                args = ", ".join(a.arg for a in node.args.args)[:60]
                cands.append(f"{fn}:{node.lineno} def {node.name}({args})")
    if cands:
        out.append(
            "OTHER FUNCTIONS (a tool only if registered in a schema, dict, list or decorator):\n"
            + "\n".join(cands[:14])
        )
    return "\n\n".join(out) or "(no tool known)"
