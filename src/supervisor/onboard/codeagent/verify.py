# ruff: noqa: E501
"""Deterministic check of the agent's claims.

The model proposes; this module decides. A claim is kept only when

1. its kind is known and the file exists in the stored tree;
2. the line is in range and the quoted text (at least ``MIN_QUOTE`` characters) is on that line;
3. the line is not prose (comment, docstring, Markdown): prose proves nothing about behaviour;
4. the line, the quote and the name are not a prompt injection (``onboard.injection``);
5. the attributes are known and inside the closed lists of ``ATTR_SPEC``;
6. a per-kind predicate holds: the claimed name or sink is visible on the evidence line.

A claim that fails is dropped and counted as ``Rejected`` (reason only, no model text).
``verify_report`` runs the same evidence test on a finished report, so the evidence validity rate
in the eval is measured on what the user sees, not on what the loop accepted.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.onboard.codeagent.models import (
    ATTR_SPEC,
    KINDS,
    Finding,
    Rejected,
    clean_attrs,
)
from supervisor.onboard.codeagent.workspace import Workspace, prose_lines
from supervisor.onboard.codefacts import PII_VOCAB
from supervisor.onboard.injection import WITHHELD, find_injection
from supervisor.onboard.models import Evidence
from supervisor.onboard.scrub import scrub_text

MIN_QUOTE = 5
REQUIRED: dict[str, tuple[str, ...]] = {
    "secret_handling": ("source",),
    "guardrail": ("guard",),
    "hitl": ("mode",),
    "logging": ("sink",),
    "data_flow": ("tool", "direction", "sink"),
    "entrypoint": ("entry",),
}
_APPROVAL = re.compile(
    r"(?i)approv|interrupt|checker|four_?eyes|sign_?off|review|human|officer|confirm|second|"
    r"queue|manual|escalat|pending|duyet|phe_?duyet|xac_?nhan"
)
_NOT_APPROVAL = re.compile(r"(?i)message|prompt|template|humanize")
_ENV = re.compile(r"(?i)environ|getenv|dotenv|load_dotenv|settings\.|config\[|os\.getenv")
_STORE = re.compile(
    r"(?i)secrets?\.get|dbutils\.secrets|vault|keyvault|secretmanager|secret_client|SecretClient"
)
_LOG = re.compile(
    r"(?i)\blog(ger|ging)?\b|\.(info|debug|warning|warn|error|exception)\(|print\(|\w*(log|trace|audit|emit|record)\w*\("
)
_TRACE_OTEL = re.compile(r"(?i)opentelemetry|otel|tracer|trace\.|span")
_TRACE_MLFLOW = re.compile(r"(?i)mlflow")
_AUDIT = re.compile(r"(?i)audit|log_table|activity_log|event_log|insert\s+into")
_HOST = re.compile(r"(?i)^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


MAIN_ATTR = {
    "guardrail": "guard",
    "secret_handling": "source",
    "logging": "sink",
    "hitl": "mode",
    "entrypoint": "entry",
}
_QUOTES = re.compile(r"[^0-9a-zA-Z]")


def _fold(text: str) -> str:
    """Case and quote marks do not matter for 'is this quote on that line'."""
    return _QUOTES.sub("", text).lower()  # letters and digits only


def _locate(rows: Sequence[str], line: int, quote: str) -> int:
    """The line (within 3 lines of the claimed one) that holds the quote; the claimed line if none."""
    q = _fold(quote)
    if q in _fold(norm(rows[line - 1])):
        return line
    for d in (1, -1, 2, -2, 3, -3):
        i = line + d
        if 0 < i <= len(rows) and q in _fold(norm(rows[i - 1])):
            return i
    return line


_AMOUNT_ARG = re.compile(r"(?i)amount|so_tien|vnd|total|minor|han_muc|limit|installment|sum|value")


def _params_at(ws: Workspace, file: str, line: int) -> set[str]:
    tree = ws.tree(file)
    if tree is None:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (
            node.lineno == line or line in [d.lineno for d in node.decorator_list]
        ):
            a = node.args
            return {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs]}
        if isinstance(node, ast.ClassDef) and node.lineno == line:
            return {
                x.arg
                for b in node.body
                if isinstance(b, ast.FunctionDef | ast.AsyncFunctionDef)
                and b.name in ("_run", "run", "__call__")
                for x in [*b.args.args, *b.args.kwonlyargs]
            }
    return set()


def _find_anywhere(ws: Workspace, quote: str) -> tuple[str, int] | None:
    """The one place in the repo whose line holds the quote (12+ letters and digits), else None."""
    q = _fold(quote)
    if len(q) < 12:
        return None
    hits: list[tuple[str, int]] = []
    for f in ws.files:
        for i, row in enumerate(ws.lines[f], start=1):
            if q in _fold(norm(row)):
                hits.append((f, i))
                if len(hits) > 1:
                    return None
    return hits[0] if hits else None


def norm(text: str) -> str:
    return " ".join(str(text).split())


def finding_id(kind: str, name: str, file: str, line: int) -> str:
    h = hashlib.sha256(f"{kind}\x00{name.lower()}\x00{file}\x00{line}".encode()).hexdigest()
    return "cf_" + h[:12]


def host_of(text: str) -> str:
    """Host name in a URL or a bare host; empty when there is none."""
    t = text.strip().lower()
    t = re.sub(r"^[a-z][a-z0-9+.-]*://", "", t)
    t = re.split(r"[/?#:\s]", t, maxsplit=1)[0]
    return t if _HOST.match(t) and "." in t else ""


def canonical_name(kind: str, name: str, attrs: Mapping[str, Any], file: str) -> str:
    """One spelling per claim, so the same fact from two sources has the same key."""
    if kind == "egress":
        return host_of(name) or name
    if kind == "data_flow":
        return f"{str(attrs.get('tool', '')).lower()} {attrs.get('direction')} {attrs.get('sink')}"
    if kind == "pii":
        tool = str(attrs.get("tool") or "").strip().lower()
        field = name.strip().lower().split(":")[-1]
        return f"{tool}:{field}" if tool else field
    if kind == "entrypoint":
        return f"{attrs.get('entry')}:{file}"
    if kind == "secret_handling":
        return str(attrs.get("source"))
    if kind == "guardrail":
        return str(attrs.get("guard"))
    if kind == "logging":
        return str(attrs.get("sink"))
    if kind == "hitl":
        return f"{attrs.get('mode')}:{file}"
    if kind in ("tool", "model", "framework"):
        return name.strip()
    return name


_GUARD_LINE: dict[str, re.Pattern[str]] = {
    "amount_limit": re.compile(
        r"(?i)(amount|limit|max|cap|total|vnd|minor|so_tien|quota).*([<>]|\bmin\(|\bmax\()|([<>]|\bmin\(|\bmax\().*(amount|limit|max|cap|total|vnd|minor|so_tien)"
    ),
    "allowlist": re.compile(
        r"(?i)\bnot in\b|\bin [\[{(A-Za-z_]|allow|whitelist|permitted|supported|known_|[A-Z_]{4,}\.get\("
    ),
    "input_validation": re.compile(
        r"(?i)valid|raise\b|Field\(|isinstance|\bassert\b|HTTPException|\bif\b.*(\bnot\b|is None|<|>|==|!=)|\b(gt|ge|lt|le)=|regex|pattern|return \{.?.?(error|status)"
    ),
    "output_filter": re.compile(
        r"(?i)filter|mask|redact|sanitiz|scrub|moderat|censor|\bpii\b|truncate|\[:\d+\]"
    ),
    "rate_limit": re.compile(
        r"(?i)rate[_ ]?limit|ratelimit|throttl|limiter|@limits|sleep\(|calls=|period=|per_(minute|second)"
    ),
    "content_filter": re.compile(
        r"(?i)moderat|toxic|safety|profan|blocklist|banned|content_filter|guardrail"
    ),
}


def predicate_ok(
    kind: str, name: str, attrs: Mapping[str, Any], window: str, line_text: str = ""
) -> bool:
    """Is the claim visible in the evidence text (the evidence line and 2 lines around it)?"""
    low = window.lower()
    if kind == "egress":
        host = host_of(name)
        return bool(host) and host in low
    if kind == "tool":
        return name.strip().lower().split("/")[-1] in low
    if kind == "pii":
        return name.strip().lower().split(":")[-1] in low
    if kind == "secret_handling":
        src = attrs.get("source")
        if src == "hardcoded":
            return "[redacted" in low or bool(
                re.search(r"(?i)(key|token|secret|password)\s*=", window)
            )
        if src == "env":
            return bool(_ENV.search(window))
        if src == "secret_store":
            return bool(_STORE.search(window))
        return False
    if kind == "hitl":
        return True  # decided by _is_call_line: code evidence, not a word in the text
    if kind == "logging":
        sink = attrs.get("sink")
        if sink == "log":
            return bool(_LOG.search(window))
        if sink == "trace_otel":
            return bool(_TRACE_OTEL.search(window))
        if sink == "trace_mlflow":
            return bool(_TRACE_MLFLOW.search(window))
        if sink == "audit_table":
            return bool(_AUDIT.search(window))
        return False
    if kind == "guardrail":
        rx = _GUARD_LINE.get(str(attrs.get("guard")))
        return bool(rx and rx.search(line_text or window))
    return True


def registered_as_tool(ws: Workspace, name: str, file: str, line: int) -> bool:
    """Is a function a tool the model can call? Only if the code registers it: a decorator on its
    def, its name as a string (schema, registry key, config list), or its name inside a list,
    tuple, dict or a tool-binding call. A function that is only called is not a tool."""
    n = name.strip().split("/")[-1]
    tree = ws.tree(file)
    if tree is not None:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and node.name == n
                and node.decorator_list
            ):
                return True
    for f in ws.files:
        t = ws.tree(f)
        if t is None:
            if f.endswith((".yaml", ".yml", ".json", ".toml")) and any(
                re.search(r"(?<![\w])" + re.escape(n) + r"(?![\w])", row) for row in ws.lines[f]
            ):
                return True
            continue
        for node in ast.walk(t):
            if isinstance(node, ast.Constant) and node.value == n:
                return True
            if isinstance(node, ast.List | ast.Tuple | ast.Set | ast.Dict):
                elts = node.values if isinstance(node, ast.Dict) else node.elts
                if any(isinstance(e, ast.Name) and e.id == n for e in elts):
                    return True
            if isinstance(node, ast.Call):
                fn = node.func
                fname = (
                    fn.id
                    if isinstance(fn, ast.Name)
                    else fn.attr
                    if isinstance(fn, ast.Attribute)
                    else ""
                )
                if re.search(r"(?i)tool|register|agent", fname) and any(
                    (isinstance(a, ast.Name) and a.id == n)
                    for a in [*node.args, *(k.value for k in node.keywords)]
                ):
                    return True
    return False


def check_claim(
    raw: Mapping[str, Any],
    ws: Workspace,
    *,
    prose: dict[str, set[int]] | None = None,
    known_tools: set[str] | None = None,
) -> tuple[Finding | None, Rejected | None, int]:
    """Verify one raw claim ``{kind, name, file, line, quote, attrs}``.

    Returns ``(finding, None, dropped_attrs)`` or ``(None, rejected, 0)``. ``finding.verified`` is
    True; the caller sets ``source``-specific confidence afterwards."""
    kind = str(raw.get("kind") or raw.get("k") or "")[:40]
    name = norm(raw.get("name") or raw.get("n") or "")[:200]
    file = str(raw.get("file") or raw.get("f") or "")[:300]
    try:
        line = int(raw.get("line") or raw.get("l") or 0)
    except (TypeError, ValueError):
        line = 0
    quote = norm(raw.get("quote") or raw.get("q") or "")

    def rej(reason: str) -> tuple[None, Rejected, int]:
        return (
            None,
            Rejected(
                kind=kind or "?",
                name=scrub_text(name).text[:120],
                file=file,
                line=line,
                reason=reason,  # type: ignore[arg-type]
            ),
            0,
        )

    if kind not in KINDS or not name:
        return rej("bad_kind")
    rows = ws.lines.get(file)
    if rows is None:
        return rej("no_file")
    if not 0 < line <= len(rows):
        return rej("line_out_of_range")
    if len(quote) < MIN_QUOTE or len(_fold(quote)) < MIN_QUOTE:
        return rej("quote_too_short")
    line = _locate(
        rows, line, quote
    )  # the model is often a line or two off; the quote must still hold
    text = rows[line - 1]
    if _fold(quote) not in _fold(norm(text)):
        where = _find_anywhere(ws, quote)  # the quote may sit in another file: it counts if unique
        if where is None:
            return rej("quote_not_on_line")
        file, line = where
        rows = ws.lines[file]
        text = rows[line - 1]
    if find_injection(text) or find_injection(quote) or find_injection(name):
        return rej("injection_text")
    if prose is not None:
        if file not in prose:
            prose[file] = prose_lines(file, rows)
        if line in prose[file]:
            return rej("evidence_is_prose")
    raw_attrs = dict(raw.get("attrs") or raw.get("a") or {})
    attrs, dropped = clean_attrs(kind, raw_attrs)
    main = MAIN_ATTR.get(kind)
    if (
        main
        and main not in attrs
        and norm(raw.get("name") or "").lower() in ATTR_SPEC[kind].get(main, ())
    ):
        attrs[main] = norm(raw["name"]).lower()  # the name carried the value: format repair only
    if kind == "guardrail" and "guard" not in attrs:
        for g in (
            "amount_limit",
            "rate_limit",
            "allowlist",
            "output_filter",
            "content_filter",
            "input_validation",
        ):
            if _GUARD_LINE[g].search(text):
                attrs["guard"] = g  # the line decides which guard it is
                break
        if "scope" not in attrs and norm(raw.get("name") or ""):
            attrs["scope"] = norm(raw["name"])[:80]
    if kind == "hitl" and "mode" not in attrs:
        attrs["mode"] = "interrupt" if "interrupt" in text.lower() else "pre_approval"
    if kind == "data_flow" and attrs.get("target"):
        host = host_of(str(attrs["target"]))
        if host.endswith(".nganhang.internal") and attrs.get("sink") == "http":
            attrs["sink"] = "bank_api"
        elif host and not host.endswith(".nganhang.internal") and attrs.get("sink") == "bank_api":
            attrs["sink"] = "http"
    if kind == "tool" and attrs.get("effect") not in ("money", "credit"):
        attrs.pop("amount_arg", None)
        attrs.pop("destination_arg", None)
    if kind == "tool" and attrs.get("amount_arg"):
        params = _params_at(ws, file, line)
        arg = str(attrs["amount_arg"]).strip()
        if arg not in params or not _AMOUNT_ARG.search(arg):
            attrs.pop("amount_arg")  # not a parameter of that function, or not a money amount
            dropped += 1
    if any(k not in attrs for k in REQUIRED.get(kind, ())):
        return rej("bad_attrs")
    window = "\n".join(rows[max(0, line - 3) : line + 2])
    if not predicate_ok(kind, name, attrs, window, text):
        return rej("claim_not_visible")
    if kind == "logging" and attrs.get("logs_pii") is True and not pii_in_call(ws, file, line):
        del attrs[
            "logs_pii"
        ]  # the log call shows no personal-data identifier: the claim is dropped
        dropped += 1
    if kind == "tool" and name.lower() not in (known_tools or set()):
        if not registered_as_tool(ws, name, file, line):
            return rej("not_a_tool")
    if kind == "hitl" and not _is_call_line(ws, file, line):
        return rej("not_an_approval_step")
    name = canonical_name(kind, name, attrs, file)
    ev = Evidence.at(file, line, text)
    f = Finding(
        finding_id=finding_id(kind, name, file, line),
        kind=kind,  # type: ignore[arg-type]
        name=scrub_text(name).text[:200],
        attrs={k: (scrub_text(v).text if isinstance(v, str) else v) for k, v in attrs.items()},
        attr_basis=dict.fromkeys(attrs, "agent"),
        evidence=[ev],
        source="agent",
        verified=True,
        confidence_bp=6000,
    )
    return f, None, dropped


def evidence_ok(ev: Evidence, ws: Workspace) -> bool:
    """The pointer of a report finding still holds against the stored tree."""
    text = ws.line(ev.file, ev.line)
    if text is None:
        return False
    if ev.quote == WITHHELD:
        return find_injection(text) is not None
    return ev.quote.strip() != "" and ev.quote.strip() in text


def verify_report(findings: Sequence[Finding], ws: Workspace) -> tuple[int, int]:
    """(findings whose every evidence verifies, findings). Used by the eval and the service."""
    ok = sum(1 for f in findings if all(evidence_ok(e, ws) for e in f.evidence))
    return ok, len(findings)


__all__ = [
    "ATTR_SPEC",
    "MIN_QUOTE",
    "check_claim",
    "evidence_ok",
    "finding_id",
    "host_of",
    "norm",
    "predicate_ok",
    "verify_report",
]


def _defs(ws: Workspace) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for f in ws.files:
        t = ws.tree(f)
        if t is None:
            continue
        for node in ast.walk(t):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                out.setdefault(node.name, node)
    return out


def _awaits_decision(fn: ast.AST) -> bool:
    """Does a function wait for an answer from outside: input(), a sleep in a polling loop, wait_for?"""
    loops = any(isinstance(n, ast.While | ast.For) for n in ast.walk(fn))
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if nm in ("input", "wait_for", "wait") or (nm == "sleep" and loops):
                return True
    return False


def _is_call_line(ws: Workspace, file: str, line: int) -> bool:
    """An approval step needs code evidence: a def, or a call, on that line of a function that either
    has an approval-like name or is a function of the repo that waits for an answer from outside
    (``input``, a sleep in a polling loop, ``wait_for``). A string assigned to a variable is not one,
    and neither is a call to a library function."""
    tree = ws.tree(file)
    if tree is None:
        return False
    defs = _defs(ws)
    for node in ast.walk(tree):
        lo = getattr(node, "lineno", 0)
        hi = getattr(node, "end_lineno", lo) or lo
        if not lo <= line <= hi:
            continue
        name = ""
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.lineno == line:
            name = node.name
        elif isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
        if not name:
            continue
        if _APPROVAL.search(name) and not _NOT_APPROVAL.search(name):
            return True
        target = defs.get(name)
        if target is not None and _awaits_decision(target):
            return True
    return False


def pii_in_call(ws: Workspace, file: str, line: int) -> bool:
    """Does a call that starts on this line name a personal-data identifier in its arguments?"""
    tree = ws.tree(file)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.lineno == line:
            seg = ast.get_source_segment("\n".join(ws.lines[file]), node) or ""
            words = set(re.findall(r"[A-Za-z_]\w*", seg))
            if words & PII_VOCAB:
                return True
    return False
