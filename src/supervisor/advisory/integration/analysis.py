"""Static facts about the tools of a target repo that the Inventory does not hold.

Read-only. For each tool the Inventory knows where the implementing function is
(``definition``: file and the ``def`` line). This module parses that file with ``ast`` and
reports the shape of the definition (module function, nested function, method, class),
whether it already carries a Supervisor gate, and the amount argument with its annotation.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, replace
from pathlib import Path

from supervisor.onboard.models import Inventory, ToolInfo

GATED_CLASSES = frozenset({"money", "credit", "pii_export"})
AMOUNT_RE = re.compile(r"(?i)(^amount|_minor$|_vnd$|^so_tien|amount$)")
_FLOAT_RE = re.compile(r"\bfloat\b")


@dataclass(frozen=True)
class ToolFacts:
    """What static analysis found about one tool. Defaults mean 'nothing found'."""

    shape: str = "unresolved"  # function | nested_function | method | class | unresolved
    file: str | None = None
    func: str | None = None  # name of the def (for the codemod)
    line: int | None = None  # line of the ``def`` keyword (or ``class``)
    col: int = 0
    gated: bool = False
    amount_arg: str | None = None  # effective amount argument (declared or by name)
    amount_float: bool = False  # the amount argument is annotated float
    gate_via: str | None = None  # why gated is True when the function has no gate itself
    model_arg: str | None = None  # route parameter that is not a plain value (request model)

    @property
    def top_level(self) -> bool:
        return self.shape == "function"


def read_text(target: Path, rel: str) -> str | None:
    """Text of a repo file (newlines kept), or None when it is missing or outside the root."""
    try:
        root = target.resolve()
        path = (root / rel).resolve()
        path.relative_to(root)
        return path.read_bytes().decode("utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _last_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def has_gate_decorator(node: ast.AST) -> bool:
    decos = getattr(node, "decorator_list", [])
    return any(_last_name(d) == "supervised_tool" for d in decos)


def has_gate_call(node: ast.AST) -> bool:
    """A ``<something with gate in its name>.check(...)`` call inside the node."""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "check"
            and "gate" in ast.unparse(sub.func.value).lower()
        ):
            return True
    return False


def is_gated(node: ast.AST) -> bool:
    return has_gate_decorator(node) or has_gate_call(node)


def amount_arg_of(tool: ToolInfo) -> str | None:
    """The amount argument: the one Discover declared, else the first argument whose name
    looks like an amount (``amount``, ``*_minor``, ``*_vnd``, ``so_tien``)."""
    if tool.amount_arg:
        return tool.amount_arg
    return next((a for a in sorted(tool.args) if AMOUNT_RE.search(a)), None)


def _annotation_of(node: ast.AST, arg: str) -> str | None:
    if isinstance(node, ast.ClassDef):
        for st in node.body:
            if isinstance(st, ast.AnnAssign) and getattr(st.target, "id", None) == arg:
                return ast.unparse(st.annotation)
        return None
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    a = node.args
    for x in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
        if x.arg == arg:
            return ast.unparse(x.annotation) if x.annotation is not None else None
    return None


_PLAIN = frozenset(
    {"str", "int", "float", "bool", "bytes", "None", "Optional", "list", "dict", "tuple", "set"}
    | {"List", "Dict", "Tuple", "Set", "Any", "Literal", "Decimal", "date", "datetime"}
)
_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


def route_model_arg(node: ast.AST) -> str | None:
    """For a web route (``@app.post(...)``): the first parameter whose annotation is not a
    plain value type (a Pydantic request model, ``Request``). The gate cannot serialise it."""
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    if not any(
        isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and d.func.attr in _ROUTE_METHODS
        for d in node.decorator_list
    ):
        return None
    a = node.args
    for x in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
        if x.annotation is None or x.arg in ("self", "cls"):
            continue
        names = {n.id for n in ast.walk(x.annotation) if isinstance(n, ast.Name)}
        if names - _PLAIN:
            return x.arg
    return None


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    out: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[id(child)] = parent
    return out


def tool_facts(target: Path, tool: ToolInfo, trees: dict[str, ast.Module | None]) -> ToolFacts:
    amount = amount_arg_of(tool)
    declared_float = amount is not None and tool.args.get(amount, "").strip().lower() == "float"
    ev = tool.definition
    if ev is None:
        return ToolFacts(amount_arg=amount, amount_float=declared_float)
    if ev.file not in trees:
        text = read_text(target, ev.file)
        try:
            trees[ev.file] = ast.parse(text) if text is not None else None
        except SyntaxError:
            trees[ev.file] = None
    tree = trees[ev.file]
    if tree is None:
        return ToolFacts(file=ev.file, amount_arg=amount, amount_float=declared_float)
    node = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and n.lineno == ev.line
        ),
        None,
    )
    if node is None:
        return ToolFacts(file=ev.file, amount_arg=amount, amount_float=declared_float)
    parent = _parents(tree).get(id(node))
    if isinstance(node, ast.ClassDef):
        shape = "class"
    elif parent is tree:
        shape = "function"
    elif isinstance(parent, ast.ClassDef):
        shape = "method"
    else:
        shape = "nested_function"
    annotation = _annotation_of(node, amount) if amount else None
    is_float = bool(_FLOAT_RE.search(annotation)) if annotation is not None else declared_float
    return ToolFacts(
        shape=shape,
        file=ev.file,
        func=node.name,
        line=node.lineno,
        col=node.col_offset,
        gated=is_gated(node),
        amount_arg=amount,
        amount_float=is_float,
        model_arg=route_model_arg(node),
    )


def write_effects(tool: ToolInfo) -> list[str]:
    """Writes found in the tool body (db, http, bank API, file) and in-memory mutations."""
    return [*tool.side_effects, *(f"mutates {m}" for m in tool.mutates)]


def needs_gate(tool: ToolInfo) -> bool:
    """A tool the gate must see: money, credit or pii_export, or any tool that writes."""
    return tool.risk_class in GATED_CLASSES or bool(write_effects(tool))


_RUNTIME_BUILDERS = frozenset({"build_runtime", "AgentRuntime"})


def central_gate(target: Path, inv: Inventory) -> str | None:
    """``file:line`` of a central dispatch gate, or None.

    Narrow, by ``ast``: (a) a call ``<name with 'gate'>.check(a, b, c, d, ...)`` with at
    least 4 positional arguments (agent id, version, tool, args), or ``safe_check(<gate>, ...)``
    with at least 5; or (b) the call ``build_runtime(...)`` / ``AgentRuntime(...)`` with a
    ``gate=`` keyword, which hands the gate to the Supervisor agent runtime whose dispatcher
    checks every tool call (the demo agents; that dispatcher lives outside the agent folder)."""
    for file in sorted(f for f in inv.files if f.endswith(".py")):
        text = read_text(target, file)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for call in sorted(
            (n for n in ast.walk(tree) if isinstance(n, ast.Call)), key=lambda n: n.lineno
        ):
            name = _last_name(call)
            if (
                isinstance(call.func, ast.Attribute)
                and name == "check"
                and "gate" in ast.unparse(call.func.value).lower()
                and len(call.args) >= 4
            ):
                return f"{file}:{call.lineno}"
            if (
                name == "safe_check"
                and len(call.args) >= 5
                and "gate" in ast.unparse(call.args[0]).lower()
            ):
                return f"{file}:{call.lineno}"
            if name in _RUNTIME_BUILDERS and any(k.arg == "gate" for k in call.keywords):
                return f"{file}:{call.lineno}"
    return None


def analyse_tools(target: Path, inv: Inventory) -> dict[str, ToolFacts]:
    trees: dict[str, ast.Module | None] = {}
    facts = {t.name: tool_facts(target, t, trees) for t in inv.tools}
    central = central_gate(target, inv)
    if central is not None:
        via = f"central dispatch gate at {central}"
        facts = {
            k: v if v.gated else replace(v, gated=True, gate_via=via) for k, v in facts.items()
        }
    return facts
