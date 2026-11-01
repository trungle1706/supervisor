"""Guardian kit (GUARDIAN_KIT): connect an app to Guardian, and check that it is connected.

Three parts, all deterministic (no model is called anywhere in this module):

* ``client_source``  the ONE file ``guardian_client.py`` for a use case. It is the template in
  ``adapters/guardian_client_template.py`` with the agent id, the version and the tool table
  (tool name -> risk class) baked in. Standard library only.
* ``guide``          the short how-to, tailored to the tools, the framework and the credential
  kind of the use case. Placement per framework follows ``docs/INTEGRATION_GUIDE.md`` section 2.
* ``check_files``    the code check. It reads the newest stored source tree with ``ast`` and says,
  for each tool of the use case, whether a Guardian line sits above it: ``connected``,
  ``missing``, ``wrong_name`` (the line names another tool) or ``wrong_risk`` (the line gives
  another risk class). It recognises this kit's ``supervised_tool("name")`` and the full SDK's
  ``supervised_tool(agent, version, "name", "risk", ...)``.

``GuardianKitService`` stores each check as one ``guardian_ready_check`` row plus one chain record
(ids, counts and hashes; never code text, never a value). The status of a use case is the newest
row: ``ready`` (every tool connected), ``partly_ready``, ``not_ready`` or ``no_tools``; it is
``not_checked`` when there is no row.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import SupervisorError
from supervisor.gateway.ingress_sign import AGENT_ID_RE
from supervisor.onboard import intake

RISK_CLASSES = ("read_only", "money", "credit", "pii_export")
STATUSES = ("not_checked", "not_ready", "partly_ready", "ready", "no_tools")
TOOL_STATES = ("connected", "missing", "wrong_name", "wrong_risk")
FILE_NAME = "guardian_client.py"
FLAG_TEXT = "guardian_kit_off: the Guardian kit is off (GUARDIAN_KIT=1 turns it on)"
TABLE = "guardian_ready_check"
CHAIN_TYPE = "guardian_ready_check"
IMPORT_LINE = "from guardian_client import supervised_tool"
_BAKED = re.compile(
    r"# ---- baked by Guardian: begin ----\n.*?# ---- baked by Guardian: end ----\n", re.S
)
_IDENT = re.compile(r"[^A-Za-z0-9_]")

# Where the Guardian line goes, by framework (docs/INTEGRATION_GUIDE.md section 2.1).
#   decorator  the framework decorator stays first; the Guardian line sits directly above ``def``
#   function   a registry (dict, FunctionTool, schema list) points to the function; decorate it
#   wrapper    a web route: gate a small function with plain arguments and call it from the route
PLACEMENT = {
    "langgraph": "decorator",
    "deepagents": "decorator",
    "langchain": "decorator",
    "crewai": "decorator",
    "fastmcp": "decorator",
    "llamaindex": "function",
    "openai_sdk": "function",
    "anthropic_sdk": "function",
    "databricks_agents": "function",
    "fastapi": "wrapper",
    "custom": "function",
}
FRAMEWORK_DECORATOR = {
    "langgraph": "@tool",
    "deepagents": "@tool",
    "langchain": "@tool",
    "crewai": "@tool",
    "fastmcp": "@mcp.tool()",
}


class KitError(SupervisorError):
    """A refused request. ``code`` is the stable machine word; the message starts with it."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def require_on(settings: Any) -> None:
    if not getattr(settings, "guardian_kit", False):
        raise KitError("guardian_kit_off", FLAG_TEXT.split(": ", 1)[1])


# ----------------------------------------------------------------------------- the code file


def valid_agent_id(value: str) -> bool:
    return bool(AGENT_ID_RE.match(value or ""))


def client_source(agent_id: str, version: str, tools: Mapping[str, str]) -> str:
    """The text of ``guardian_client.py`` with the agent id, version and tool table baked in."""
    template = (
        Path(__file__).parent.parent / "adapters" / "guardian_client_template.py"
    ).read_text(encoding="utf-8")
    who = agent_id if valid_agent_id(agent_id) else "FILL-ME-agent-id"
    ver = version if re.fullmatch(r"[A-Za-z0-9._+-]{1,40}", version or "") else "1.0.0"
    rows = "".join(
        f"    {json.dumps(name, ensure_ascii=True)}: {json.dumps(risk)},\n"
        for name, risk in sorted(tools.items())
        if risk in RISK_CLASSES
    )
    table = (
        "TOOLS: dict[str, str] = {\n" + rows + "}  # tool name -> risk class\n"
        if rows
        else ("TOOLS: dict[str, str] = {}  # tool name -> risk class\n")
    )
    baked = (
        "# ---- baked by Guardian: begin ----\n"
        f"AGENT_ID = {json.dumps(who)}\n"
        f"AGENT_VERSION = {json.dumps(ver)}\n"
        f"{table}"
        "# ---- baked by Guardian: end ----\n"
    )
    out, n = _BAKED.subn(lambda _m: baked, template, count=1)
    if n != 1:  # the template lost its markers: a code fault, not a user error
        raise KitError("template_broken", "the client template has no baked block")
    return out


# ----------------------------------------------------------------------------- the code check


@dataclass(frozen=True)
class ToolRef:
    """A tool the use case has (from the facts card or from Discover)."""

    name: str
    risk: str
    file: str = ""
    line: int | None = None


@dataclass(frozen=True)
class Gated:
    """A function that has a Guardian line above it."""

    file: str
    line: int
    func: str
    tool: str | None
    risk: str | None
    form: str  # kit | sdk


def _const(node: ast.AST | None, consts: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def _callee(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def scan_files(files: Mapping[str, str]) -> tuple[list[Gated], int]:
    """Every function with a ``supervised_tool(...)`` line above it, and the number of Python
    files that could not be read as Python."""
    found: list[Gated] = []
    unparsed = 0
    for path in sorted(files):
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(files[path], filename=path)
        except (SyntaxError, ValueError):
            unparsed += 1
            continue
        consts = {
            t.id: n.value.value
            for n in tree.body
            if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call) or _callee(deco.func) != "supervised_tool":
                    continue
                kw = {k.arg: k.value for k in deco.keywords if k.arg}
                pos = list(deco.args)
                if len(pos) >= 3 or "tool_name" in kw:  # the full SDK form
                    tool = _const(kw.get("tool_name") or (pos[2] if len(pos) > 2 else None), consts)
                    risk = _const(
                        kw.get("risk_class") or (pos[3] if len(pos) > 3 else None), consts
                    )
                    form = "sdk"
                else:  # this kit: supervised_tool("name") or supervised_tool("name", "risk")
                    tool = _const(kw.get("tool_name") or (pos[0] if pos else None), consts)
                    risk = _const(
                        kw.get("risk_class") or (pos[1] if len(pos) > 1 else None), consts
                    )
                    form = "kit"
                found.append(Gated(path, deco.lineno, node.name, tool, risk, form))
    return found, unparsed


def check_files(tools: Sequence[ToolRef], files: Mapping[str, str]) -> dict[str, Any]:
    """The result of the code check: a status, counts, one row per tool and notes. Pure."""
    gated, unparsed = scan_files(files)
    rows: list[dict[str, Any]] = []
    used: set[tuple[str, int]] = set()
    for t in tools:
        exact = [g for g in gated if g.tool == t.name]
        good = next((g for g in exact if g.risk in (None, t.risk)), None)
        by_func = next((g for g in gated if g.func == t.name and g.tool != t.name), None)
        row: dict[str, Any] = {
            "name": t.name,
            "risk": t.risk,
            "file": t.file,
            "line": t.line,
            "found_name": None,
            "found_risk": None,
        }
        if good is not None:
            row.update(state="connected", file=good.file, line=good.line)
            used.add((good.file, good.line))
        elif exact:
            g = exact[0]
            row.update(state="wrong_risk", file=g.file, line=g.line, found_risk=g.risk)
            used.add((g.file, g.line))
        elif by_func is not None:
            row.update(
                state="wrong_name",
                file=by_func.file,
                line=by_func.line,
                found_name=by_func.tool or "",
            )
            used.add((by_func.file, by_func.line))
        else:
            row["state"] = "missing"
        rows.append(row)
    ok = sum(1 for r in rows if r["state"] == "connected")
    total = len(rows)
    notes: list[str] = []
    kit_used = any(g.form == "kit" for g in gated if (g.file, g.line) in used)
    if kit_used and not any(p.rsplit("/", 1)[-1] == FILE_NAME for p in files):
        notes.append("client_file_missing")
    extras = sorted({g.tool for g in gated if g.tool and (g.file, g.line) not in used})
    if total == 0:
        status = "no_tools"
    elif ok == total and "client_file_missing" not in notes:
        status = "ready"
    elif ok == 0:
        status = "not_ready"
    else:
        status = "partly_ready"
    if unparsed:
        notes.append("unparsed_files")
    return {
        "status": status,
        "tools_total": total,
        "tools_ok": ok,
        "tools": rows,
        "extras": extras,
        "notes": notes,
        "unparsed": unparsed,
    }


# ----------------------------------------------------------------------------- the guide


def _ident(name: str) -> str:
    out = _IDENT.sub("_", name).strip("_") or "tool"
    return "t_" + out if out[0].isdigit() else out


def pick_example(tools: Sequence[ToolRef]) -> ToolRef | None:
    """The tool used in the examples: money first, then credit, personal data, then the rest."""
    for risk in ("money", "credit", "pii_export", "read_only"):
        for t in tools:
            if t.risk == risk:
                return t
    return None


def guide(
    *,
    agent_id: str,
    tools: Sequence[ToolRef],
    framework: str,
    credential: str,
    gate_url: str,
) -> dict[str, Any]:
    """The facts the how-to needs. The page turns the keys into words (EN and VI); the code
    lines are final here. Nothing secret is in it."""
    fw = framework if framework in PLACEMENT else "custom"
    placement = PLACEMENT[fw]
    ex = pick_example(tools)
    lines: list[dict[str, Any]] = []
    if ex is not None:
        lines.append({"text": IMPORT_LINE, "hot": True})
        if placement == "decorator":
            lines.append({"text": FRAMEWORK_DECORATOR.get(fw, "@tool"), "hot": False})
        lines.append({"text": f"@supervised_tool({json.dumps(ex.name)})", "hot": True})
        name = ("gated_" if placement == "wrapper" else "") + _ident(ex.name)
        lines.append({"text": f"def {name}(...):", "hot": False})
        lines.append({"text": "    ...  # your code stays as it is", "hot": False})
    who = agent_id if valid_agent_id(agent_id) else "FILL-ME-agent-id"
    if credential == "hmac":
        env = [
            f"set GUARDIAN_URL={gate_url}",
            "set GUARDIAN_AGENT_KEY_FILE=FILL-ME-path-to-key-file",
        ]
    else:
        env = [
            "env:",
            "  - name: GUARDIAN_URL",
            f'    value: "{gate_url}"',
        ]
    return {
        "agent_id": who,
        "framework": fw,
        "placement": placement,
        "credential": "hmac" if credential == "hmac" else "databricks_oauth",
        "example": None
        if ex is None
        else {"name": ex.name, "risk": ex.risk, "file": ex.file, "line": ex.line},
        "put_dir": (ex.file.rsplit("/", 1)[0] if ex is not None and "/" in ex.file else ""),
        "import_line": IMPORT_LINE,
        "tool_lines": [
            {"name": t.name, "risk": t.risk, "text": f"@supervised_tool({json.dumps(t.name)})"}
            for t in tools
        ],
        "snippet": lines,
        "env_lines": env,
        "file_name": FILE_NAME,
    }


# ----------------------------------------------------------------------------- the service


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def _risk_of(detail: str) -> str:
    m = re.search(r"risk_class=([a-z_]+)", detail or "")
    return m.group(1) if m else ""


# The framework of a stored attempt never changes (an attempt is never edited): keep the answer.
_FRAMEWORKS: dict[tuple[str, str, int], str] = {}


def _remember_framework(key: tuple[str, str, int], framework: str) -> None:
    if len(_FRAMEWORKS) >= 256:
        _FRAMEWORKS.clear()
    _FRAMEWORKS[key] = framework


class GuardianKitService:
    """Reads the stored source, runs the check, stores the result. ``chain`` is the evidence sink
    (None = no chain record, used by tests that do not need it)."""

    def __init__(self, settings: Any, state: Any, clock: Any, chain: Any = None) -> None:
        self.settings = settings
        self.state = state
        self.clock = clock
        self.chain = chain

    # ------------------------------------------------------------------ the source
    def _intake(self) -> intake.IntakeService:
        return intake.IntakeService(self.settings, self.state, self.clock)

    def tree_path(self, node_id: str, n: int) -> Path:
        return self._intake().tree_path(node_id, n)

    def attempts(self, node_id: str) -> list[dict[str, Any]]:
        """Stored attempts of the source key, newest first (a refused upload is left out)."""
        intake.check_node_id(node_id)
        return [a for a in self._intake().attempts(node_id) if a["status"] != "failed"]

    def tools_of(self, node_id: str, n: int | None) -> list[ToolRef]:
        """The tools of the use case: the active tool facts of the newest built facts card; when
        there is none, a Discover run on attempt ``n`` (rules only)."""
        rows = [
            dict(r)
            for r in self.state.query("onboard_facts", {"node_id": node_id})
            if _bool(r.get("active")) and r.get("kind") == "tool"
        ]
        if rows:
            latest = max(int(r["attempt_n"]) for r in rows)
            rows = [r for r in rows if int(r["attempt_n"]) == latest]
            out = [
                ToolRef(
                    str(r["name"]),
                    _risk_of(str(r.get("detail") or "")),
                    str(r.get("file") or ""),
                    int(r["line"]) if r.get("line") is not None else None,
                )
                for r in rows
            ]
            return sorted((t for t in out if t.risk in RISK_CLASSES), key=lambda t: t.name)
        if n is None:
            return []
        return self._discover(node_id, n)[0]

    def _discover(self, node_id: str, n: int) -> tuple[list[ToolRef], str]:
        from supervisor.adapters.repo import LocalGitRepoReader
        from supervisor.onboard.discover import discover

        tree = self._intake().tree_path(node_id, n)
        if not tree.is_dir():
            return [], "custom"
        disc = discover(LocalGitRepoReader(tree))
        inv = disc.inventory
        refs = [
            ToolRef(
                t.name,
                t.risk_class,
                t.definition.file if t.definition else "",
                t.definition.line if t.definition else None,
            )
            for t in inv.tools
        ]
        _remember_framework((str(self.settings.data_dir), node_id, n), inv.framework)
        return sorted(refs, key=lambda t: t.name), inv.framework

    def framework_of(self, node_id: str, n: int | None) -> str:
        if n is None:
            return "custom"
        key = (str(self.settings.data_dir), node_id, n)
        if key not in _FRAMEWORKS:
            self._discover(node_id, n)
        fw = _FRAMEWORKS.get(key, "custom")
        return fw if fw in PLACEMENT else "custom"

    def load_tree(self, node_id: str, n: int) -> dict[str, str]:
        tree = self._intake().tree_path(node_id, n)
        if not tree.is_dir():
            raise KitError(
                "tree_missing",
                f"the stored source of upload {n} is not on this server any more; upload again",
            )
        try:
            files, _ = intake.read_tree(tree, intake.max_bytes(self.settings))
        except intake.IntakeError as exc:
            raise KitError("source_unreadable", str(exc)) from None
        return files

    # ------------------------------------------------------------------ the stored checks
    def checks(self, system_id: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.state.query(TABLE, {"system_id": system_id})]
        rows.sort(key=lambda r: (str(r["checked_at"]), r["check_id"]), reverse=True)
        return [self._view(r) for r in rows]

    def latest(self, system_id: str) -> dict[str, Any] | None:
        got = self.checks(system_id)
        return got[0] if got else None

    @staticmethod
    def _view(row: Mapping[str, Any]) -> dict[str, Any]:
        at = row.get("checked_at")
        try:
            detail = json.loads(row.get("detail_json") or "{}")
        except ValueError:
            detail = {}
        return {
            "check_id": row["check_id"],
            "system_id": row["system_id"],
            "node_id": row["node_id"],
            "attempt_n": int(row["attempt_n"]),
            "status": row["status"],
            "tools_total": int(row["tools_total"]),
            "tools_ok": int(row["tools_ok"]),
            "checked_by": row["checked_by"],
            "checked_at": format_ts(at) if at is not None and not isinstance(at, str) else at,
            "detail": detail if isinstance(detail, dict) else {},
        }

    # ------------------------------------------------------------------ run a check
    def run_check(
        self,
        system_id: str,
        node_id: str,
        actor: str,
        *,
        fetch_git: bool = False,
    ) -> dict[str, Any]:
        """Check the newest stored source (after a fresh clone when ``fetch_git``) and store the
        result. Raises ``KitError`` (HTTP 400) when there is nothing to check."""
        intake.check_node_id(node_id)
        if not self.attempts(node_id):
            raise KitError(
                "no_source", "there is no stored source; add the code in the Source step first"
            )
        if fetch_git:
            self._fetch_git(node_id, actor)
        got = self.attempts(node_id)
        n = got[0]["n"]
        files = self.load_tree(node_id, n)
        tools = self.tools_of(node_id, n)
        result = check_files(tools, files)
        detail = {
            "tools": result["tools"],
            "extras": result["extras"],
            "notes": result["notes"],
            "unparsed": result["unparsed"],
            "framework": self.framework_of(node_id, n),
            "source_kind": got[0]["source_kind"],
        }
        text = json.dumps(detail, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        row = {
            "check_id": "gck_" + uuid.uuid4().hex[:24],
            "system_id": system_id,
            "node_id": node_id,
            "attempt_n": n,
            "status": result["status"],
            "tools_total": result["tools_total"],
            "tools_ok": result["tools_ok"],
            "checked_by": actor,
            "checked_at": self.clock.now(),
            "detail_json": text,
        }
        self.state.insert(TABLE, row)
        self._record(row, intake.tree_sha256(files), hashlib.sha256(text.encode()).hexdigest())
        return self._view(row)

    def _fetch_git(self, node_id: str, actor: str) -> None:
        git = next((a for a in self.attempts(node_id) if a["source_kind"] == "git"), None)
        if git is None:
            raise KitError("no_git_source", "the code did not come from a git address")
        self._intake().submit_git(node_id, str(git["source_ref"]), actor)

    def _record(self, row: Mapping[str, Any], tree_sha: str, detail_sha: str) -> None:
        """One chain record: ids, counts and hashes. No code text, no value, no person id."""
        if self.chain is None:
            return
        from supervisor.controls.model import actor_ref

        payload = {
            "system_id": row["system_id"],
            "node_id": row["node_id"],
            "attempt_n": int(row["attempt_n"]),
            "status": row["status"],
            "tools_total": int(row["tools_total"]),
            "tools_ok": int(row["tools_ok"]),
            "tree_sha256": tree_sha,
            "detail_sha256": detail_sha,
            "check_id": row["check_id"],
            "by_ref": actor_ref(self.settings, str(row["checked_by"]), "guardian-kit"),
        }
        sha256_hex(payload)  # raises on a float or a value the chain cannot hold, before the write
        try:
            self.chain.record(CHAIN_TYPE, f"system:{row['system_id']}", payload)
        except Exception:  # noqa: BLE001 - the row is stored; the chain is a second copy
            import logging

            logging.getLogger("supervisor.guardian_kit").exception("chain record failed")
