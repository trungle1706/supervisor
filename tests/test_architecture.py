"""AST rules from CLAUDE.md.

1. Outside ``supervisor/adapters`` no module imports databricks, pyspark, sqlite3,
   httpx or openai (ports and adapters).
2. No exec / eval / compile / subprocess / os.system / os.popen / os.spawn* / os.exec*
   anywhere outside ``src/supervisor/sandbox.py`` (src, schema and tests are scanned).
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.conftest import REPO_ROOT

SRC = REPO_ROOT / "src" / "supervisor"
SANDBOX = SRC / "sandbox.py"
FORBIDDEN_IMPORTS = {"databricks", "pyspark", "sqlite3", "httpx", "openai"}
FORBIDDEN_CALLS = {"exec", "eval", "compile", "__import__"}
FORBIDDEN_MODULES = {"subprocess", "pty", "multiprocessing"}
FORBIDDEN_OS_ATTRS = ("system", "popen", "spawn", "exec", "fork", "posix_spawn", "startfile")


def _py_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(p for p in root.rglob("*.py") if ".venv" not in p.parts)
    return sorted(files)


def _imports(tree: ast.AST) -> list[tuple[str, int]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((a.name, node.lineno) for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.module, node.lineno))
        elif isinstance(node, ast.Call):
            # importlib.import_module("x") with a literal
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "import_module" and node.args and isinstance(node.args[0], ast.Constant):
                out.append((str(node.args[0].value), node.lineno))
    return out


def test_core_and_domain_do_not_import_io_libraries() -> None:
    offenders = []
    for path in _py_files(SRC):
        if (SRC / "adapters") in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for mod, line in _imports(tree):
            if mod.split(".")[0] in FORBIDDEN_IMPORTS:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line} imports {mod}")
    assert offenders == [], "\n".join(offenders)


def test_no_exec_eval_subprocess_outside_sandbox() -> None:
    offenders = []
    roots = [REPO_ROOT / "src", REPO_ROOT / "schema", REPO_ROOT / "tests"]
    for path in _py_files(*[r for r in roots if r.exists()]):
        if path == SANDBOX:
            continue
        rel = path.relative_to(REPO_ROOT)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for mod, line in _imports(tree):
            if mod.split(".")[0] in FORBIDDEN_MODULES:
                offenders.append(f"{rel}:{line} imports {mod}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id in FORBIDDEN_CALLS:
                offenders.append(f"{rel}:{node.lineno} calls {f.id}()")
            if (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id == "os"
                and f.attr.startswith(FORBIDDEN_OS_ATTRS)
            ):
                offenders.append(f"{rel}:{node.lineno} calls os.{f.attr}()")
            if (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id == "builtins"
                and f.attr in FORBIDDEN_CALLS
            ):
                offenders.append(f"{rel}:{node.lineno} calls builtins.{f.attr}()")
    assert offenders == [], "\n".join(offenders)


def test_rule_catches_violations() -> None:
    """The scanner itself must flag a planted violation."""
    tree = ast.parse("import subprocess\nimport databricks.sdk\neval('1')\n")
    mods = {m.split(".")[0] for m, _ in _imports(tree)}
    assert {"subprocess", "databricks"} <= mods
    calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert "eval" in calls


def test_entry_points_bootstrap_first() -> None:
    """cli, app and every job call bootstrap() before other work."""
    targets = [SRC / "cli.py", SRC / "app.py", *sorted((SRC / "jobs").glob("[!_]*.py"))]
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        body = [n for n in tree.body if not isinstance(n, ast.Expr | ast.ImportFrom | ast.Import)]
        first_call = next(
            (n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)),
            None,
        )
        assert first_call is not None, f"{path.name}: no module-level bootstrap() call"
        assert getattr(first_call.value.func, "id", "") == "bootstrap", path.name
        assert body == [] or body[0].lineno > first_call.lineno, path.name
