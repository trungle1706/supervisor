# ruff: noqa: E501
"""The deterministic findings: the same report fields, made by fixed rules only.

This is (a) the ground truth that the agent must not override, and (b) the "deterministic only"
column of the eval. It reuses ``Discover`` (``Inventory``) for framework, models, tools, data
access, tracing, approval refs, interrupt guards, secrets and routes, and adds AST rules for the
fields Discover does not link: tool -> sink, PII per tool, egress hosts, secret sources,
guardrails, log calls, entry points.

Each attribute carries a basis (``manifest``, ``ast``, ``name``). ``name`` means "guessed from a
name or from the absence of a match": the merge lets a verified agent claim replace it. ``ast``
and ``manifest`` are firm: a disagreement is listed and the deterministic value stays.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from supervisor.onboard.codeagent.models import Basis, Finding
from supervisor.onboard.codeagent.verify import finding_id, host_of
from supervisor.onboard.codeagent.workspace import Workspace, prose_lines
from supervisor.onboard.codefacts import PII_VOCAB
from supervisor.onboard.discover import Discovery
from supervisor.onboard.models import Evidence, Inventory, ToolInfo

MAX_EVIDENCE = 5
_URL = re.compile(r"https?://([A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}|localhost|127\.0\.0\.1)")
_ENV = re.compile(r"os\.environ|os\.getenv|getenv\(|load_dotenv|environ\.get")
_STORE = re.compile(r"(?i)dbutils\.secrets|keyvault|SecretClient|secretmanager|hvac|vault_client")
_PINNED = re.compile(r"(?<!\d)(\d{8})(?!\d)|\d{4}-\d{2}-\d{2}|-v\d|@\d")
_LOG_ATTRS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
_AMOUNT = re.compile(r"(?i)(amount|so_tien|total|limit|value|vnd|minor)")
_ALLOW = re.compile(r"(?i)(allow|whitelist|permitted|approved_|valid_|known_)")
_AUDIT = re.compile(r"(?i)audit|activity_log|event_log|log_table")
_ARGUMENT_LIMIT = re.compile(r"(?i)\b(max|cap|limit)\w*")


def _ev(ws: Workspace, file: str, line: int) -> Evidence:
    return Evidence.at(file, line, ws.lines[file][line - 1])


def _is_pinned(model: str | None) -> bool:
    return bool(model and _PINNED.search(model.lower()))


class _Collector:
    """Findings keyed by (kind, name); evidence lists are merged, attrs set once."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], Finding] = {}

    def add(
        self,
        kind: str,
        name: str,
        ev: Evidence | None,
        attrs: dict[str, str | bool] | None = None,
        basis: dict[str, Basis] | None = None,
        conf: int = 9500,
    ) -> None:
        if ev is None or not name:
            return
        key = (kind, name.strip().lower())
        cur = self.rows.get(key)
        if cur is not None:
            if all(e.ref() != ev.ref() for e in cur.evidence) and len(cur.evidence) < MAX_EVIDENCE:
                cur.evidence.append(ev)
            for k, v in (attrs or {}).items():
                if k not in cur.attrs:
                    cur.attrs[k] = v
                    cur.attr_basis[k] = (basis or {}).get(k, "ast")
            return
        a = dict(attrs or {})
        self.rows[key] = Finding(
            finding_id=finding_id(kind, name, ev.file, ev.line),
            kind=kind,  # type: ignore[arg-type]
            name=name.strip()[:200],
            attrs=a,
            attr_basis={k: (basis or {}).get(k, "ast") for k in a},
            evidence=[ev],
            source="deterministic",
            verified=True,
            confidence_bp=conf,
        )


def _functions(ws: Workspace) -> dict[str, list[tuple[str, ast.AST]]]:
    out: dict[str, list[tuple[str, ast.AST]]] = defaultdict(list)
    for f in ws.files:
        tree = ws.tree(f)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                out[node.name].append((f, node))
    return out


def _span(node: ast.AST) -> tuple[int, int]:
    return node.lineno, getattr(node, "end_lineno", None) or node.lineno  # type: ignore[attr-defined]


def _tool_node(
    tool: ToolInfo, funcs: dict[str, list[tuple[str, ast.AST]]]
) -> tuple[str, ast.AST] | None:
    ev = tool.definition or tool.manifest_entry
    if ev is None:
        return None
    for _name, rows in funcs.items():
        for f, node in rows:
            if f == ev.file and node.lineno <= ev.line <= _span(node)[1]:  # type: ignore[attr-defined]
                if node.lineno == ev.line or any(  # type: ignore[attr-defined]
                    d.lineno == ev.line for d in getattr(node, "decorator_list", [])
                ):
                    return f, node
    return None


def _reach(
    start: tuple[str, ast.AST], funcs: dict[str, list[tuple[str, ast.AST]]], depth: int = 2
) -> list[tuple[str, ast.AST]]:
    """The function and the repo functions it calls, up to ``depth`` hops."""
    seen = {(start[0], _span(start[1]))}
    out = [start]
    frontier = [start]
    for _ in range(depth):
        nxt: list[tuple[str, ast.AST]] = []
        for _f, node in frontier:
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                nm = (
                    fn.id
                    if isinstance(fn, ast.Name)
                    else fn.attr
                    if isinstance(fn, ast.Attribute)
                    else ""
                )
                for f2, n2 in funcs.get(nm, []):
                    key = (f2, _span(n2))
                    if key not in seen and isinstance(n2, ast.FunctionDef | ast.AsyncFunctionDef):
                        seen.add(key)
                        out.append((f2, n2))
                        nxt.append((f2, n2))
        frontier = nxt
    return out


def _identifiers(node: ast.AST) -> Iterable[tuple[str, int]]:
    """(identifier, line) of names, arguments, attribute names and string keys in a node."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            yield sub.id, sub.lineno
        elif isinstance(sub, ast.arg):
            yield sub.arg, sub.lineno
        elif isinstance(sub, ast.Attribute):
            yield sub.attr, sub.lineno
        elif isinstance(sub, ast.keyword) and sub.arg:
            yield sub.arg, getattr(sub, "lineno", getattr(node, "lineno", 0))
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and len(sub.value) < 400:
            val = sub.value
            if val in PII_VOCAB:
                yield val, sub.lineno
            elif " " in val and re.search(r"(?i)\b(select|insert|update|from|where)\b", val):
                for w in re.findall(r"[A-Za-z_]\w*", val):
                    if w in PII_VOCAB:
                        yield w, sub.lineno


def _effect(t: ToolInfo) -> tuple[str, Basis]:
    if t.risk_class == "money":
        return "money", "manifest" if t.risk_source == "manifest" else "name"
    if t.risk_class == "credit":
        return "credit", "manifest" if t.risk_source == "manifest" else "name"
    if t.side_effects:
        return "write", "ast"
    if t.risk_class == "pii_export":
        return "other", "name" if t.risk_source == "heuristic" else "manifest"
    return "read", "manifest" if t.risk_source == "manifest" else "name"


_DELETE_SQL = re.compile(r"(?i)^\s*delete\s+from\b")


def _deletes(reach: list[tuple[str, ast.AST]]) -> bool:
    """Does the tool, or a helper it calls, delete data (SQL DELETE, file removal, HTTP DELETE)?"""
    for _f, node in reach:
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, str)
                and _DELETE_SQL.search(sub.value)
            ):
                return True
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                owner = sub.func.value.id if isinstance(sub.func.value, ast.Name) else ""
                if (
                    sub.func.attr in ("remove", "unlink", "rmtree")
                    and owner in ("os", "shutil", "Path", "")
                ) or (
                    sub.func.attr == "delete"
                    and owner in ("requests", "httpx", "client", "session")
                ):
                    return True
    return False


def guards_of(
    ws: Workspace, disc: Discovery | None, approval_fn: str, tools: list[Finding]
) -> list[str]:
    """Tools whose body, or a helper they call (two hops), calls ``approval_fn``. The agent names the
    approval function; the rules decide which tools it guards."""
    funcs = _functions(ws)
    out: list[str] = []
    for t in tools:
        if t.kind != "tool" or t.name == approval_fn:
            continue
        ev = t.evidence[0]
        node = None
        for rows in funcs.values():
            for f, n in rows:
                if f == ev.file and (
                    n.lineno == ev.line
                    or any(d.lineno == ev.line for d in getattr(n, "decorator_list", []))
                ):
                    node = (f, n)
        if node is None:
            continue
        for _f, fn in _reach(node, funcs):
            if fn is node[1]:
                continue
            if getattr(fn, "name", "") == approval_fn:
                out.append(t.name)
                break
    return sorted(set(out))


def approval_name(ws: Workspace, f: Finding) -> str:
    """The name of the approval function that a hitl finding points at (its def, or the call)."""
    ev = f.evidence[0]
    tree = ws.tree(ev.file)
    if tree is None:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.lineno == ev.line:
            return node.name
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.lineno <= ev.line <= (
            node.end_lineno or node.lineno
        ):
            fn = node.func
            nm = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
            if re.search(
                r"(?i)approv|signoff|sign_off|check|confirm|review|interrupt|human|officer|manager|queue|wait",
                nm,
            ):
                return nm
    return ""


def deterministic_findings(disc: Discovery, ws: Workspace) -> list[Finding]:
    """All deterministic findings for the report (every one has file:line evidence)."""
    inv: Inventory = disc.inventory
    c = _Collector()
    funcs = _functions(ws)

    # -- framework, models ------------------------------------------------------------
    if inv.framework_evidence is not None and inv.framework not in ("", "unknown"):
        c.add("framework", inv.framework, inv.framework_evidence)
    for call in inv.llm_calls:
        name = call.model or "(model set by config)"
        c.add(
            "model",
            name,
            call.evidence,
            {
                "provider": call.provider,
                "family": call.family,
                "pinned": _is_pinned(call.model),
                "resolved": call.model is not None,
            },
        )

    # -- approval points (human in the loop) ----------------------------------------------
    approved_by_file: dict[str, list[Evidence]] = defaultdict(list)
    for ev in inv.human_approval_refs:
        approved_by_file[ev.file].append(ev)
    guards: dict[str, set[str]] = defaultdict(set)
    for f, refs in approved_by_file.items():
        for ref in refs[:MAX_EVIDENCE]:
            c.add("hitl", f"pre_approval:{f}", ref, {"mode": "pre_approval"})
    for where, names in inv.interrupt_guards.items():
        file, _, line = where.rpartition(":")
        if file in ws.lines and line.isdigit() and int(line) <= len(ws.lines[file]):
            c.add(
                "hitl",
                f"interrupt:{file}",
                _ev(ws, file, int(line)),
                {"mode": "interrupt", "guards": ",".join(names)},
            )
            guards["interrupt"].update(names)
    guarded = set(guards["interrupt"])
    approval_rx = re.compile(
        r"(?i)^(request|await|require|get|wait_for)_(human_|officer_|maker_checker_|four_eyes_)?"
        r"(approval|sign_?off)$|maker_checker|four_eyes|human_approval|officer_approval"
    )

    # -- tools, data flows, PII per tool -----------------------------------------------------
    for t in inv.tools:
        ev = t.definition or t.manifest_entry
        if ev is None or ev.file not in ws.lines:
            continue
        effect, eb = _effect(t)
        attrs: dict[str, str | bool] = {"effect": effect}
        basis: dict[str, Basis] = {"effect": eb}
        if effect in ("money", "credit"):
            attrs["irreversible"], basis["irreversible"] = True, eb
        elif effect == "read":
            attrs["irreversible"], basis["irreversible"] = False, "name"
        node0 = _tool_node(t, funcs)
        if node0 is not None:
            for _f2, n2 in _reach(node0, funcs):
                for sub in ast.walk(n2):
                    if isinstance(sub, ast.Call):
                        fn = sub.func
                        nm = (
                            fn.id
                            if isinstance(fn, ast.Name)
                            else fn.attr
                            if isinstance(fn, ast.Attribute)
                            else ""
                        )
                        if approval_rx.search(nm):
                            guarded.add(t.name)
        is_guarded = t.name in guarded
        attrs["approval"] = is_guarded
        basis["approval"] = "ast" if is_guarded else "name"
        if t.amount_arg:
            attrs["amount_arg"], basis["amount_arg"] = t.amount_arg, "ast"
        if t.destination_arg:
            attrs["destination_arg"], basis["destination_arg"] = t.destination_arg, "ast"
        node = _tool_node(t, funcs)
        if effect == "write" and node is not None and _deletes(_reach(node, funcs)):
            attrs["effect"], basis["effect"] = "delete", "ast"
            attrs["irreversible"], basis["irreversible"] = True, "ast"
        c.add("tool", t.name, ev, attrs, basis)
        if node is None:
            continue
        reach = _reach(node, funcs)
        for d in inv.data_access:
            for f2, n2 in reach:
                lo, hi = _span(n2)
                if d.evidence.file == f2 and lo <= d.evidence.line <= hi:
                    name = f"{t.name.lower()} {d.direction} {d.kind}"
                    c.add(
                        "data_flow",
                        name,
                        d.evidence,
                        {
                            "tool": t.name,
                            "direction": d.direction,
                            "sink": d.kind,
                            **({"target": d.target[:80]} if d.target else {}),
                        },
                    )
                    break
        seen_pii: set[str] = set()
        for ident, ln in _identifiers(node[1]):
            if ident in PII_VOCAB and ident not in seen_pii and node[0] in ws.lines:
                seen_pii.add(ident)
                c.add(
                    "pii",
                    f"{t.name.lower()}:{ident}",
                    _ev(ws, node[0], max(1, min(ln, len(ws.lines[node[0]])))),
                    {"tool": t.name},
                )
    called = sorted(guarded - guards["interrupt"])
    for (kind, _n), fnd in c.rows.items():
        if kind == "hitl" and fnd.attrs.get("mode") == "pre_approval" and called:
            fnd.attrs["guards"] = ",".join(called)
            fnd.attr_basis["guards"] = "ast"
    # repo level PII (the Discover vocabulary hits)
    for ident, ev in inv.pii_identifiers.items():
        c.add("pii", ident, ev)

    # -- entry points -----------------------------------------------------------------------
    for ep in inv.entrypoints:
        if ep.evidence is not None:
            c.add("entrypoint", f"http:{ep.evidence.file}", ep.evidence, {"entry": "http"})
    for f in ws.files:
        rows = ws.lines[f]
        tree = ws.tree(f)
        if f.endswith(".py") and rows and rows[0].strip() == "# Databricks notebook source":
            c.add("entrypoint", f"notebook:{f}", _ev(ws, f, 1), {"entry": "notebook"})
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, ast.If) and "__main__" in ast.dump(node.test):
                c.add("entrypoint", f"cli:{f}", _ev(ws, f, node.lineno), {"entry": "cli"})
            if isinstance(node, ast.ClassDef) and any(
                re.search(r"ChatAgent|ResponsesAgent|PythonModel", ast.dump(b)) for b in node.bases
            ):
                c.add("entrypoint", f"mlflow:{f}", _ev(ws, f, node.lineno), {"entry": "mlflow"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                nm = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
                )
                if nm in ("FastMCP", "Server") and inv.framework == "fastmcp":
                    c.add("entrypoint", f"mcp:{f}", _ev(ws, f, node.lineno), {"entry": "mcp"})

    # -- egress, secrets, guardrails, logging ---------------------------------------------------
    for f in ws.files:
        rows = ws.lines[f]
        pr = prose_lines(f, rows)
        if f.endswith((".md", ".txt")) or f == "requirements.txt":
            continue
        for i, text in enumerate(rows, start=1):
            if i in pr and f.endswith(".py"):
                continue
            for m in _URL.finditer(text):
                host = m.group(1).lower()
                if host in ("localhost", "127.0.0.1"):
                    continue
                internal = host.endswith(".nganhang.internal")
                c.add("egress", host, _ev(ws, f, i), {"internal": internal})
            if "[REDACTED:" in text:
                c.add("secret_handling", "hardcoded", _ev(ws, f, i), {"source": "hardcoded"})
            elif f.endswith(".py") and _ENV.search(text):
                c.add("secret_handling", "env", _ev(ws, f, i), {"source": "env"})
            if f.endswith(".py") and _STORE.search(text):
                c.add("secret_handling", "secret_store", _ev(ws, f, i), {"source": "secret_store"})
    for name in inv.tracing:
        t_ev = next((t.evidence for t in inv.traces if name in t.name.lower() and t.evidence), None)
        if t_ev is None and inv.traces and inv.traces[0].evidence:
            t_ev = inv.traces[0].evidence
        c.add("logging", f"trace_{name}", t_ev, {"sink": f"trace_{name}", "logs_pii": False})
    for d in inv.data_access:
        if d.direction == "write" and d.target and _AUDIT.search(d.target):
            c.add("logging", "audit_table", d.evidence, {"sink": "audit_table"})
    for f in ws.files:
        tree = ws.tree(f)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                _log_call(c, ws, f, node)
            if isinstance(node, ast.Compare):
                _guard_compare(c, ws, f, node)
        for t in inv.limits:
            for ref in t.code_refs[:2]:
                c.add("guardrail", "amount_limit", ref, {"guard": "amount_limit"})
    return list(c.rows.values())


def _log_call(c: _Collector, ws: Workspace, f: str, node: ast.Call) -> None:
    fn = node.func
    is_print = isinstance(fn, ast.Name) and fn.id == "print"
    is_log = (
        isinstance(fn, ast.Attribute)
        and fn.attr in _LOG_ATTRS
        and isinstance(fn.value, ast.Name)
        and fn.value.id.lower() in ("log", "logger", "logging", "_log", "_logger")
    )
    if not (is_print or is_log):
        return
    pii = False
    for arg in [*node.args, *(k.value for k in node.keywords)]:
        for ident, _ln in _identifiers(arg):
            if ident in PII_VOCAB:
                pii = True
    ev = _ev(ws, f, node.lineno)
    c.add("logging", "log", ev, {"sink": "log"})
    if pii:
        cur = c.rows[("logging", "log")]
        cur.attrs["logs_pii"] = True
        cur.attr_basis["logs_pii"] = "ast"
        if all(e.ref() != ev.ref() for e in cur.evidence[:1]) and cur.evidence[0].ref() != ev.ref():
            cur.evidence.insert(0, ev)
            del cur.evidence[MAX_EVIDENCE:]


def _guard_compare(c: _Collector, ws: Workspace, f: str, node: ast.Compare) -> None:
    names = [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]
    names += [n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)]
    if any(isinstance(op, ast.In | ast.NotIn) for op in node.ops) and any(
        _ALLOW.search(n) for n in names
    ):
        c.add("guardrail", "allowlist", _ev(ws, f, node.lineno), {"guard": "allowlist"})
    elif any(isinstance(op, ast.Gt | ast.GtE | ast.Lt | ast.LtE) for op in node.ops):
        has_amount = any(_AMOUNT.search(n) for n in names)
        has_bound = any(_ARGUMENT_LIMIT.search(n) for n in names) or any(
            isinstance(n, ast.Constant) and isinstance(n.value, int | float) and n.value > 1000
            for n in ast.walk(node)
        )
        if has_amount and has_bound:
            c.add("guardrail", "amount_limit", _ev(ws, f, node.lineno), {"guard": "amount_limit"})


def egress_hosts(findings: Iterable[Finding]) -> set[str]:
    return {f.name for f in findings if f.kind == "egress"}


__all__: list[Any] = ["deterministic_findings", "host_of", "egress_hosts"]
