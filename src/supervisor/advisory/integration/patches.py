"""Patches: unified diffs a dev team can apply to its repo. Nothing is written to the target.

Built on ``supervisor.onboard.instrument`` (policy, hook module, builder codemod). New here:
the tool-gate codemod, which inserts a ``supervised_tool`` decorator directly above the
``def`` of each money / credit / pii_export tool, below any framework decorator (``@tool``,
``@mcp.tool()``, route decorators), so the framework registers the gated function.

Every patch is checked with ``patchcheck`` against the target, and every patched Python file
must parse, before it is returned. A patch that fails becomes a manual item with a note.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from supervisor.advisory.integration.analysis import (
    ToolFacts,
    analyse_tools,
    is_gated,
    needs_gate,
    read_text,
    write_effects,
)
from supervisor.advisory.integration.models import ManualItem, McpProxyNeeded
from supervisor.advisory.integration.patchcheck import PatchError, apply_patch, split_lines
from supervisor.onboard.injection import find_injection
from supervisor.onboard.instrument import (
    HOOK_MODULE,
    MARKER,
    ONBOARD_DIR,
    apply_codemod,
    render_hook_module,
    render_policy,
    select_entry_file,
)
from supervisor.onboard.models import (
    AgentProfile,
    Inventory,
    MonitoringPlan,
    RemediationPlaybook,
    ToolInfo,
)
from supervisor.onboard.scrub import scrub_text

MCP_ALTERNATIVE = (
    "Alternative to the MCP proxy patch: apply either the proxy (pattern C) or the "
    "decorators (pattern A), not both."
)
SDK_IMPORT = "from supervisor.gateway.sdk import supervised_tool"
GATE_URL_PLACEHOLDER = "http://FILL-ME-supervisor-host:8000"
ENV_FILE = ".env.example"
MCP_FILES = ("mcp.json", ".mcp.json")
MCP_FRAMEWORKS = frozenset({"fastmcp"})
MCP_NAMES = frozenset({"fastmcp", "mcp.server.fastmcp", "mcp.server"})


@dataclass(frozen=True)
class Patch:
    path: str  # repo-relative, posix
    kind: str  # hook_module | policy | tool_gate | builder_hook | settings | mcp_proxy
    description: str
    diff: str  # git-style unified diff
    covers: tuple[str, ...] = ()  # tools whose gate this patch adds


@dataclass
class PatchPlan:
    patches: list[Patch] = field(default_factory=list)
    gate_modes: dict[str, tuple[str, str]] = field(default_factory=dict)  # tool -> (mode, note)
    manual: list[ManualItem] = field(default_factory=list)
    mcp_proxy: McpProxyNeeded | None = None
    policy_yaml: str = ""
    facts: dict[str, ToolFacts] = field(default_factory=dict)


# --------------------------------------------------------------------------- diff


def _range(start: int, length: int) -> str:
    begin = start + 1
    if length == 1:
        return str(begin)
    if length == 0:
        begin -= 1
    return f"{begin},{length}"


def _row(tag: str, line: str) -> str:
    if line.endswith("\n"):
        return tag + line
    return tag + line + "\n\\ No newline at end of file\n"


def make_diff(path: str, old: str | None, new: str, context: int = 3) -> str:
    """Git-style unified diff. ``old`` None makes a new file. Line ends are kept as they are."""
    a = split_lines(old) if old is not None else []
    b = split_lines(new)
    head = [f"diff --git a/{path} b/{path}\n"]
    if old is None:
        head += ["new file mode 100644\n", "--- /dev/null\n", f"+++ b/{path}\n"]
    else:
        head += [f"--- a/{path}\n", f"+++ b/{path}\n"]
    body: list[str] = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for group in matcher.get_grouped_opcodes(context):
        i1, i2 = group[0][1], group[-1][2]
        j1, j2 = group[0][3], group[-1][4]
        body.append(f"@@ -{_range(i1, i2 - i1)} +{_range(j1, j2 - j1)} @@\n")
        for tag, a1, a2, b1, b2 in group:
            if tag == "equal":
                body += [_row(" ", x) for x in a[a1:a2]]
                continue
            if tag in ("replace", "delete"):
                body += [_row("-", x) for x in a[a1:a2]]
            if tag in ("replace", "insert"):
                body += [_row("+", x) for x in b[b1:b2]]
    return "".join(head + body)


def flagged_context(diff: str) -> bool:
    """True when a context or removed line holds a secret or possible injection text.

    Context lines are verbatim repo lines. A patch must not copy a secret or an injected
    instruction into a new file, so such a patch is not written."""
    for row in diff.splitlines():
        if row[:1] in (" ", "-") and not row.startswith("--- "):
            if scrub_text(row[1:]).total or find_injection(row[1:]):
                return True
    return False


def safe_diff(path: str, old: str | None, new: str) -> str:
    """``make_diff`` with 3 lines of context; 1 line when that keeps flagged lines out."""
    for n in (3, 1):
        diff = make_diff(path, old, new, n)
        if not flagged_context(diff):
            return diff
    return diff


# --------------------------------------------------------------------------- tool gates


def decorator_text(inv: Inventory, tool: ToolInfo) -> str:
    return (
        f"@supervised_tool({HOOK_MODULE}.AGENT_ID, {json.dumps(inv.version, ensure_ascii=False)}, "
        f"{json.dumps(tool.name, ensure_ascii=False)}, {json.dumps(tool.risk_class)}, "
        f"gate={HOOK_MODULE}.default_gate())"
    )


@dataclass(frozen=True)
class GateSpec:
    func: str
    decorator: str


def _imported(tree: ast.Module, module: str | None, name: str) -> bool:
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and (module is None or n.module == module):
            if any(a.name == name and a.asname is None for a in n.names):
                return True
        if module is None and isinstance(n, ast.Import):
            if any(a.name == name and a.asname is None for a in n.names):
                return True
    return False


def apply_tool_gates(
    source: str, specs: Sequence[GateSpec], *, hook_import: str
) -> tuple[str, list[str]]:
    """Insert each spec's decorator directly above its module-level ``def``.

    Returns (new source, names of the functions that were changed). Idempotent: a function
    that already carries ``supervised_tool`` is left alone; imports are added only when
    missing, marked with ``MARKER``. Raises ``SyntaxError`` if the source does not parse."""
    tree = ast.parse(source)
    nl = "\r\n" if "\r\n" in source else "\n"
    top = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    todo = [(top[s.func], s) for s in specs if s.func in top and not is_gated(top[s.func])]
    if not todo:
        return source, []
    lines = split_lines(source)
    for node, spec in sorted(todo, key=lambda x: -x[0].lineno):
        lines.insert(node.lineno - 1, spec.decorator + nl)
    first = min(min([d.lineno for d in n.decorator_list] + [n.lineno]) for n, _ in todo)
    before = [
        n.end_lineno or n.lineno
        for n in tree.body
        if isinstance(n, ast.Import | ast.ImportFrom) and (n.end_lineno or n.lineno) < first
    ]
    if before:
        at = max(before)
    elif (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        at = tree.body[0].end_lineno or tree.body[0].lineno
    else:
        at = 0
    add: list[str] = []
    if not _imported(tree, "supervisor.gateway.sdk", "supervised_tool"):
        add.append(f"{SDK_IMPORT}  {MARKER}{nl}")
    if not _imported(tree, None, HOOK_MODULE):
        add.append(f"{hook_import}  {MARKER}{nl}")
    if add:
        if at > 0 and not lines[at - 1].endswith("\n"):
            lines[at - 1] += nl
        lines[at:at] = add
    new = "".join(lines)
    ast.parse(new)
    return new, [n.name for n, _ in todo]


def hook_import_line(target: Path, file: str) -> str:
    """``import supervisor_onboard``, or the relative form when the target is a package."""
    if (target / "__init__.py").is_file():
        depth = file.count("/")
        return f"from {'.' * (depth + 1)} import {HOOK_MODULE}"
    return f"import {HOOK_MODULE}"


# --------------------------------------------------------------------------- settings, mcp


def env_block(inv: Inventory) -> list[tuple[str, str]]:
    return [
        ("SUPERVISOR_GATE_URL", GATE_URL_PLACEHOLDER),
        ("SUPERVISOR_TRACING", "1"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", GATE_URL_PLACEHOLDER),
        ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", f"{GATE_URL_PLACEHOLDER}/v1/traces"),
        ("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "http/json"),
        ("OTEL_SERVICE_NAME", inv.agent_id),
    ]


def is_mcp_server(inv: Inventory) -> bool:
    return inv.framework in MCP_FRAMEWORKS or any(m.name in MCP_NAMES for m in inv.mcp_servers)


def proxy_command(inv: Inventory, upstream: Sequence[str]) -> list[str]:
    return [
        "python",
        "-m",
        "supervisor.gateway.mcp_proxy",
        "--agent-id",
        inv.agent_id,
        "--agent-version",
        inv.version,
        "--gate-url",
        GATE_URL_PLACEHOLDER,
        "--",
        *upstream,
    ]


def _mcp_patch(target: Path, inv: Inventory, plan: PatchPlan) -> Patch | None:
    for name in MCP_FILES:
        text = read_text(target, name)
        if text is None:
            continue
        try:
            doc = json.loads(text)
        except ValueError:
            continue
        servers = doc.get("mcpServers") if isinstance(doc, dict) else None
        if not isinstance(servers, dict):
            continue
        changed: list[str] = []
        first: list[str] | None = None
        for sname, entry in servers.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
                continue
            args = entry.get("args")
            args = [str(a) for a in args] if isinstance(args, list) else []
            if "supervisor.gateway.mcp_proxy" in args:
                continue
            argv = proxy_command(inv, [entry["command"], *args])
            entry["command"], entry["args"] = argv[0], argv[1:]
            changed.append(sname)
            first = first or argv
        if not changed or first is None:
            continue
        new = json.dumps(doc, indent=2, ensure_ascii=False) + ("\n" if text.endswith("\n") else "")
        plan.mcp_proxy = McpProxyNeeded(
            config_path=name,
            command=first,
            note="the existing server entry now starts through the Supervisor proxy; "
            "replace FILL-ME-supervisor-host. " + MCP_ALTERNATIVE,
        )
        return Patch(
            name,
            "mcp_proxy",
            f"Start MCP server(s) {', '.join(changed)} through the Supervisor gate proxy. "
            + MCP_ALTERNATIVE,
            safe_diff(name, text, new),
        )
    # No usable client config: a new file next to the policy.
    server_file = next((t.definition.file for t in inv.tools if t.definition), None)
    upstream = ["python", server_file or "FILL-ME-server-file.py"]
    path = f"{ONBOARD_DIR}/mcp_proxy.json"
    argv = proxy_command(inv, upstream)
    doc = {"mcpServers": {inv.agent_id: {"command": argv[0], "args": argv[1:]}}}
    plan.mcp_proxy = McpProxyNeeded(
        config_path=path,
        command=argv,
        note="MCP client config that starts the server through the Supervisor proxy; "
        "merge it into the client config and replace FILL-ME values. " + MCP_ALTERNATIVE,
    )
    if (target / path).exists():
        return None
    return Patch(
        path,
        "mcp_proxy",
        "MCP client config that starts this server through the Supervisor gate proxy. "
        + MCP_ALTERNATIVE,
        make_diff(path, None, json.dumps(doc, indent=2, ensure_ascii=False) + "\n"),
    )


# --------------------------------------------------------------------------- plan


def _verify(target: Path, diff: str) -> str | None:
    """None when the diff applies exactly and every patched .py parses, else the reason."""
    try:
        for path, text in apply_patch(target, diff).items():
            if path.endswith(".py"):
                ast.parse(text)
    except (PatchError, SyntaxError, ValueError) as exc:
        return f"{type(exc).__name__}: {str(exc)[:160]}"
    if flagged_context(diff):
        return "lines next to the change hold a secret or possible injection text"
    return None


def _new_file(target: Path, path: str, text: str) -> str | None:
    return None if (target / path).exists() else make_diff(path, None, text)


def _ref_of(f: ToolFacts) -> str | None:
    return f"{f.file}:{f.line}" if f.file and f.line else None


def _manual_note(f: ToolFacts) -> str:
    if f.model_arg:
        return (
            f"route parameter '{f.model_arg}' is a request model: the gate cannot serialise it "
            f"and every call would fail closed; gate a plain-argument helper the route calls "
            f"(for example gated_{f.func})"
        )
    if f.shape == "class":
        return "tool class: call the gate in _run before the side effect"
    if f.shape == "method":
        return "method of a class: call the gate before the side effect"
    if f.shape == "nested_function":
        return "nested function: wrap it where the tool is registered, or use the builder hook"
    return "implementing function not found in code: wire the gate by hand"


def plan_patches(
    target: Path,
    inv: Inventory,
    profile: AgentProfile,
    mp: MonitoringPlan,
    playbook: RemediationPlaybook,
) -> PatchPlan:
    target = Path(target)
    plan = PatchPlan(facts=analyse_tools(target, inv))
    failed: dict[str, str] = {}  # patch path -> reason

    def add(patch: Patch | None) -> bool:
        if patch is None:
            return False
        reason = _verify(target, patch.diff)
        if reason is not None:
            failed[patch.path] = reason
            plan.manual.append(
                ManualItem(
                    what=f"patch {patch.path} was dropped",
                    note=f"it failed the self-check ({reason}); make the change by hand",
                )
            )
            return False
        plan.patches.append(patch)
        return True

    # policy
    try:
        plan.policy_yaml = render_policy(inv, profile, mp)
    except Exception as exc:  # noqa: BLE001 - a bad policy must not stop the report
        plan.manual.append(
            ManualItem(what="policy YAML", note=f"not generated: {type(exc).__name__}")
        )
    # hook module
    hook_path = f"{HOOK_MODULE}.py"
    hook_diff = _new_file(target, hook_path, render_hook_module(inv))
    if hook_diff:
        add(
            Patch(
                hook_path,
                "hook_module",
                "Hook module: default_gate() and default_tracer_provider() for this agent",
                hook_diff,
            )
        )
    if plan.policy_yaml:
        policy_path = f"{ONBOARD_DIR}/policy.yaml"
        diff = _new_file(target, policy_path, plan.policy_yaml)
        if diff:
            add(
                Patch(
                    policy_path,
                    "policy",
                    "Gateway policy for the agent, initial state SHADOW (nothing is blocked)",
                    diff,
                )
            )

    # builder codemod and tool decorators, one patch per file
    entry = select_entry_file(inv)
    texts: dict[str, str] = {}
    builder_note = ""
    builder_applied = False
    if entry:
        src = read_text(target, entry)
        if src is not None:
            try:
                new, applied, builder_note = apply_codemod(
                    src, import_line=hook_import_line(target, entry)
                )
            except SyntaxError:
                applied, new = False, src
            if applied:
                if "\r\n" in src:
                    new = re.sub(r"(?<!\r)\n", "\r\n", new)
                texts[entry] = new
                builder_applied = True
    gated_tools = [t for t in inv.tools if needs_gate(t)]
    mcp = is_mcp_server(inv)
    specs_by_file: dict[str, list[tuple[ToolInfo, GateSpec]]] = {}
    seen: set[tuple[str, str]] = set()
    for t in gated_tools:
        f = plan.facts[t.name]
        if f.gated or not f.top_level or f.file is None or f.func is None or f.model_arg:
            continue
        if (f.file, f.func) in seen:
            continue
        seen.add((f.file, f.func))
        specs_by_file.setdefault(f.file, []).append((t, GateSpec(f.func, decorator_text(inv, t))))
    covered_by: dict[str, str] = {}  # tool -> patch path
    for file in sorted(set(specs_by_file) | ({entry} if builder_applied and entry else set())):
        original = read_text(target, file)
        if original is None:
            continue
        current = texts.get(file, original)
        names: list[str] = []
        if file in specs_by_file:
            try:
                current, names = apply_tool_gates(
                    current,
                    [s for _, s in specs_by_file[file]],
                    hook_import=hook_import_line(target, file),
                )
            except SyntaxError:
                continue
        if current == original:
            continue
        tools = tuple(t.name for t, s in specs_by_file.get(file, []) if s.func in names)
        parts = []
        if tools:
            parts.append(f"gate {len(tools)} tool(s): {', '.join(tools)}")
        if file == entry and builder_applied:
            parts.append(f"builder default gate and tracer ({builder_note})")
        kind = "tool_gate" if tools else "builder_hook"
        if add(
            Patch(
                file,
                kind,
                "; ".join(parts).capitalize() + (f". {MCP_ALTERNATIVE}" if tools and mcp else ""),
                safe_diff(file, original, current),
                tools,
            )
        ):
            for name in tools:
                covered_by[name] = file

    # settings
    env_text = read_text(target, ENV_FILE)
    present = {
        m.group(1)
        for m in re.finditer(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", env_text or "")
    }
    rows = [(k, v) for k, v in env_block(inv) if k not in present]
    if rows:
        nl = "\r\n" if env_text and "\r\n" in env_text else "\n"
        block = nl.join(
            [
                "# --- Supervisor integration (generated by the integration advisor; review) ---",
                *[f"{k}={v}" for k, v in rows],
            ]
        )
        if env_text is None:
            new_env = block + nl
        else:
            new_env = (
                env_text + ("" if env_text.endswith("\n") or not env_text else nl) + block + nl
            )
        add(
            Patch(
                ENV_FILE,
                "settings",
                "Environment keys for the gate URL, tracing and the OTLP exporter",
                safe_diff(ENV_FILE, env_text, new_env),
            )
        )

    # MCP proxy
    if mcp:
        add(_mcp_patch(target, inv, plan))

    # gate modes for the report
    for t in gated_tools:
        f = plan.facts[t.name]
        if f.gated:
            plan.gate_modes[t.name] = ("already_gated", f.gate_via or "")
        elif t.name in covered_by:
            plan.gate_modes[t.name] = ("decorator", MCP_ALTERNATIVE if mcp else "")
        elif builder_applied and f.file == entry and not f.top_level and f.shape != "unresolved":
            plan.gate_modes[t.name] = (
                "builder_hook",
                "the builder default gate covers it; check that the runtime calls the gate "
                "for this tool",
            )
        else:
            note = _manual_note(f)
            if f.top_level and f.file in failed:
                note = f"patch for {f.file} failed the self-check; wire the gate by hand"
            plan.gate_modes[t.name] = ("manual", note)
            plan.manual.append(
                ManualItem(
                    what=f"wire the gate for tool {t.name}",
                    at=f"{f.file}:{f.line}" if f.file and f.line else None,
                    note=note,
                )
            )
    for t in gated_tools:
        if t.risk_class == "read_only":
            plan.manual.append(
                ManualItem(
                    what=f"confirm the risk class of tool {t.name}",
                    at=_ref_of(plan.facts[t.name]),
                    note=f"writes found ({', '.join(write_effects(t))}) but classed read_only; "
                    "read_only fails open when the gateway is down",
                )
            )
    for t in inv.tools:
        if t.risk_class != "money":
            continue
        f = plan.facts[t.name]
        if f.amount_arg != "amount_minor" or f.amount_float:
            plan.manual.append(
                ManualItem(
                    what=f"rename the amount argument of tool {t.name}",
                    at=f"{f.file}:{f.line}" if f.file and f.line else None,
                    note="rename to amount_minor: int (integer minor units) and update the "
                    "tool schema; the gateway reads limits and totals from amount_minor only",
                )
            )
    return plan


def build_patches(
    target: Path,
    inv: Inventory,
    profile: AgentProfile,
    mp: MonitoringPlan,
    playbook: RemediationPlaybook,
) -> list[Patch]:
    """The patches for the target, each already checked against it."""
    return plan_patches(target, inv, profile, mp, playbook).patches
