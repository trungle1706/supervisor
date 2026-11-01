# ruff: noqa: E501
"""Read-only tools over the stored, scrubbed intake tree.

The agent never touches the file system. ``Workspace`` is built once from text that the intake
step already scrubbed (and scrubs again). A tool call is a lookup in an in-memory dict: there is
no path join, no ``open``, no process. A path that is not a key is an error, so ``..``, absolute
paths and symlinks cannot reach anything. Candidate code is parsed with ``ast`` and never run.

Tools (all answer text, at most ``MAX_OBS_CHARS`` characters):

    list_files(prefix)            files with line counts
    read_file(path, start, end)   numbered lines, at most ``MAX_READ_LINES`` per call
    grep(pattern, path)           regex over lines, at most ``MAX_GREP_HITS`` hits
    ast_outline(path)             imports, classes, functions with decorators, entry guards
    find_references(symbol)       def / call / import / attribute uses of a name

A line that looks like a prompt injection (``onboard.injection``) is shown as a placeholder.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.adapters.repo.local_git import RepoReadError
from supervisor.onboard.injection import find_injection
from supervisor.onboard.scrub import Scrubber

MAX_READ_LINES = 70
MAX_GREP_HITS = 25
MAX_REF_HITS = 25
MAX_OUTLINE_LINES = 70
MAX_OBS_CHARS = 3200
MAX_LINE_CHARS = 200
MAX_PATTERN = 120
WITHHELD_LINE = "[line withheld: possible prompt injection]"
_DELIM = re.compile(r"(<{2,}|>{2,})")
_NESTED_QUANT = re.compile(r"\([^)]*[+*][^)]*\)[+*{]")
TEXT_SUFFIXES = (
    ".py",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".md",
    ".txt",
    ".cfg",
    ".ini",
    ".sql",
    ".ipynb",
    ".example",
)


class ToolError(Exception):
    """A tool call that cannot be answered. The text goes back to the model."""


def clean_path(path: str) -> str:
    """Normal form of a repo path: posix, no leading ``./``. Anything else stays and fails the lookup."""
    p = str(path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def _show(line: str) -> str:
    text = _DELIM.sub(lambda m: " ".join(m.group(0)), line.rstrip())
    return text if len(text) <= MAX_LINE_CHARS else text[:MAX_LINE_CHARS] + " ..."


@dataclass
class Workspace:
    """Scrubbed text of every file, immutable after construction."""

    lines: dict[str, tuple[str, ...]]
    skipped: dict[str, str] = field(default_factory=dict)
    read_lines: dict[str, set[int]] = field(default_factory=dict)  # per file, lines shown
    opened: set[str] = field(default_factory=set)  # read_file / ast_outline
    seen: set[str] = field(default_factory=set)  # also grep / reference hits
    withheld: int = 0
    _trees: dict[str, ast.Module | None] = field(default_factory=dict)

    # ------------------------------------------------------------------ build
    @classmethod
    def from_tree(cls, root: str | Path, *, scrubber: Scrubber | None = None) -> Workspace:
        """Read a stored tree (already scrubbed by the intake step; scrubbed again here)."""
        scrubber = scrubber or Scrubber()
        reader = LocalGitRepoReader(root)
        rows: dict[str, tuple[str, ...]] = {}
        for rel in reader.list_files("**/*"):
            if not rel.lower().endswith(TEXT_SUFFIXES):
                continue
            try:
                text = reader.read_text(rel)
            except RepoReadError:
                continue
            rows[rel] = tuple(scrubber.scrub(text, source=rel).splitlines())
        return cls(lines=rows, skipped=dict(getattr(reader, "skipped", {}) or {}))

    @classmethod
    def from_lines(cls, lines: Mapping[str, Sequence[str]]) -> Workspace:
        return cls(lines={k: tuple(v) for k, v in lines.items()})

    # ------------------------------------------------------------------ numbers
    @property
    def files(self) -> list[str]:
        return sorted(self.lines)

    def total_lines(self) -> int:
        return sum(len(v) for v in self.lines.values())

    def lines_read(self) -> int:
        return sum(len(v) for v in self.read_lines.values())

    def line(self, file: str, line: int) -> str | None:
        rows = self.lines.get(file)
        if rows is None or not 0 < line <= len(rows):
            return None
        return rows[line - 1]

    def tree(self, file: str) -> ast.Module | None:
        if file not in self._trees:
            tree: ast.Module | None = None
            if file.endswith(".py"):
                try:
                    tree = ast.parse("\n".join(self.lines.get(file, ())))
                except (SyntaxError, ValueError, RecursionError):
                    tree = None
            self._trees[file] = tree
        return self._trees[file]

    # ------------------------------------------------------------------ tools
    def call(self, tool: str, args: Mapping[str, object]) -> str:
        """Run one tool. Raises ``ToolError`` with a short reason."""
        if tool == "list_files":
            out = self.list_files(str(args.get("path") or ""))
        elif tool == "read_file":
            out = self.read_file(
                str(args.get("path") or ""), _int(args.get("start"), 1), _int(args.get("end"), 0)
            )
        elif tool == "grep":
            out = self.grep(str(args.get("pattern") or ""), str(args.get("path") or ""))
        elif tool == "ast_outline":
            out = self.ast_outline(str(args.get("path") or ""))
        elif tool == "find_references":
            out = self.find_references(str(args.get("symbol") or ""))
        else:
            raise ToolError(f"unknown tool {tool!r}")
        return out if len(out) <= MAX_OBS_CHARS else out[:MAX_OBS_CHARS] + "\n[cut]"

    def resolve(self, path: str) -> str:
        """The key of a stored file for a model- or user-given path, else ``ToolError``."""
        return self._file(path)

    def _file(self, path: str) -> str:
        p = clean_path(path)
        if p not in self.lines:
            near = [f for f in self.lines if f.endswith("/" + p) or f.rsplit("/", 1)[-1] == p]
            hint = f" (did you mean {near[0]}?)" if near else ""
            raise ToolError(f"no such file: {p[:80]}{hint}")
        return p

    def _shown(self, file: str, line_no: int, text: str) -> str:
        if find_injection(text):
            self.withheld += 1
            return WITHHELD_LINE
        self.read_lines.setdefault(file, set()).add(line_no)
        return _show(text)

    def list_files(self, prefix: str = "") -> str:
        pre = clean_path(prefix)
        rows = [f"{f} ({len(v)} lines)" for f, v in sorted(self.lines.items()) if f.startswith(pre)]
        if not rows:
            raise ToolError("no file under that prefix")
        return "\n".join(rows[:80])

    def read_file(self, path: str, start: int = 1, end: int = 0) -> str:
        f = self._file(path)
        rows = self.lines[f]
        start = max(1, start)
        end = end if end >= start else start + MAX_READ_LINES - 1
        end = min(end, start + MAX_READ_LINES - 1, len(rows))
        if start > len(rows):
            raise ToolError(f"{f} has {len(rows)} lines")
        self.opened.add(f)
        self.seen.add(f)
        out = [f"{f} lines {start}-{end} of {len(rows)}"]
        out += [f"{i}: {self._shown(f, i, rows[i - 1])}" for i in range(start, end + 1)]
        if end < len(rows):
            out.append(f"[more: read_file {f} start={end + 1}]")
        return "\n".join(out)

    def grep(self, pattern: str, path: str = "") -> str:
        if not pattern or len(pattern) > MAX_PATTERN:
            raise ToolError(f"pattern must be 1 to {MAX_PATTERN} characters")
        if _NESTED_QUANT.search(pattern):
            raise ToolError("pattern refused: nested repetition")
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            raise ToolError("pattern is not a valid regular expression") from None
        pre = clean_path(path)
        hits: list[str] = []
        for f in sorted(self.lines):
            if pre and not f.startswith(pre) and f != pre:
                continue
            for i, text in enumerate(self.lines[f], start=1):
                if len(text) <= 400 and rx.search(text):
                    self.seen.add(f)
                    hits.append(f"{f}:{i}: {self._shown(f, i, text)}")
                    if len(hits) >= MAX_GREP_HITS:
                        return "\n".join(hits) + "\n[more hits cut]"
        if not hits:
            return "no match"
        return "\n".join(hits)

    def ast_outline(self, path: str) -> str:
        f = self._file(path)
        self.opened.add(f)
        self.seen.add(f)
        rows = self.lines[f]
        if not f.endswith(".py"):
            head = [f"{i}: {self._shown(f, i, t)}" for i, t in enumerate(rows[:25], start=1)]
            return f"{f} is not Python ({len(rows)} lines); first lines:\n" + "\n".join(head)
        tree = self.tree(f)
        if tree is None:
            return f"{f}: not valid Python 3 (syntax error); use read_file"
        out = [f"{f} ({len(rows)} lines)"]
        for node in tree.body:
            out.extend(_outline(node, 0))
        text = "\n".join(out[:MAX_OUTLINE_LINES])
        return text + ("\n[outline cut]" if len(out) > MAX_OUTLINE_LINES else "")

    def find_references(self, symbol: str) -> str:
        sym = (symbol or "").strip()
        if not re.fullmatch(r"[A-Za-z_][\w.]{0,80}", sym):
            raise ToolError("symbol must be a name such as make_transfer or client.post")
        last = sym.rsplit(".", 1)[-1]
        hits: list[str] = []
        for f in sorted(self.lines):
            tree = self.tree(f)
            rows = self.lines[f]
            if tree is None:
                rx = re.compile(r"\b" + re.escape(last) + r"\b")
                for i, text in enumerate(rows, start=1):
                    if rx.search(text) and len(hits) < MAX_REF_HITS:
                        self.seen.add(f)
                        hits.append(f"{f}:{i}: text: {self._shown(f, i, text)}")
                continue
            for node in ast.walk(tree):
                kind = _ref_kind(node, last)
                if kind and len(hits) < MAX_REF_HITS:
                    ln = getattr(node, "lineno", 0)
                    self.seen.add(f)
                    hits.append(f"{f}:{ln}: {kind}: {self._shown(f, ln, rows[ln - 1])}")
        hits = sorted(set(hits), key=_hit_key)
        return "\n".join(hits) if hits else "no reference"


def _hit_key(h: str) -> tuple[str, int]:
    f, _, rest = h.partition(":")
    return f, int(rest.split(":", 1)[0] or 0)


def _int(v: object, default: int) -> int:
    try:
        return int(v)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return default


def _outline(node: ast.AST, depth: int) -> list[str]:
    pad = "  " * depth
    if isinstance(node, ast.Import):
        return [f"{node.lineno}: {pad}import " + ", ".join(a.name for a in node.names)]
    if isinstance(node, ast.ImportFrom):
        names = ", ".join(a.name for a in node.names)[:80]
        return [f"{node.lineno}: {pad}from {node.module or '.'} import {names}"]
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        decos = "".join(f" @{_name(d)}" for d in node.decorator_list)
        args = ", ".join(a.arg for a in node.args.args)[:80]
        kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        out = [f"{node.lineno}: {pad}{kw} {node.name}({args}){decos}"]
        if depth == 0:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    out.extend(_outline(sub, depth + 1))
        return out
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(_name(b) for b in node.bases)[:60]
        out = [f"{node.lineno}: {pad}class {node.name}({bases})"]
        for sub in node.body:
            if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                out.extend(_outline(sub, depth + 1))
        return out
    if isinstance(node, ast.Assign) and depth == 0:
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if names:
            return [f"{node.lineno}: {pad}{', '.join(names)} = ..."]
    if isinstance(node, ast.If) and depth == 0 and "__main__" in ast.dump(node.test):
        return [f"{node.lineno}: {pad}if __name__ == '__main__'"]
    return []


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _name(node.func) + "()"
    return "?"


def _ref_kind(node: ast.AST, name: str) -> str:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
        return "def"
    if isinstance(node, ast.ClassDef) and node.name == name:
        return "class"
    if isinstance(node, ast.Call):
        f = node.func
        if (isinstance(f, ast.Name) and f.id == name) or (
            isinstance(f, ast.Attribute) and f.attr == name
        ):
            return "call"
    if isinstance(node, ast.ImportFrom) and any(a.name == name for a in node.names):
        return "import"
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == name:
        return "string"
    return ""


# --------------------------------------------------------------------------- prose lines


def prose_lines(file: str, rows: Sequence[str]) -> set[int]:
    """Lines (1-based) of a Python file that hold only prose: comments, docstrings, plain string
    statements, blank lines. Evidence on such a line proves nothing about behaviour. For a file
    that is not Python the set is empty (YAML keys and JSON values are data, not prose), except
    Markdown and text files where every line is prose."""
    if file.endswith((".md", ".txt")):
        return set(range(1, len(rows) + 1))
    if not file.endswith(".py"):
        return set()
    text = "\n".join(rows)
    prose: set[int] = set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                prose.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    code_lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in (tokenize.NAME, tokenize.OP, tokenize.NUMBER, tokenize.STRING):
                code_lines.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return prose
    return {i for i in range(1, len(rows) + 1) if i not in code_lines} | prose
