"""W6 (GUARDIAN_KIT): the code file, the guide and the Guardian-ready code check.

Pure tests: no network and no model. The check runs on three synthetic trees (none, partial,
full) and on the framework samples of ``data/corpus/repos`` (a Guardian line is added above each
tool the way the guide says, then the check must say Ready)."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.core.canonical import canonical_bytes
from supervisor.onboard import guardian_kit as gk
from supervisor.onboard.discover import discover
from tests.conftest import REPO_ROOT

TOOLS = [
    gk.ToolRef("reconcile", "read_only", "code/tools.py", 10),
    gk.ToolRef("add_payee", "pii_export", "code/tools.py", 20),
    gk.ToolRef("transfer", "money", "code/tools.py", 30),
]
PLAIN = '''"""Tools."""


def reconcile(statement_id: str) -> dict:
    return {}


def add_payee(name: str, account: str) -> dict:
    return {}


async def transfer(payee_id: str, amount_minor: int) -> dict:
    return {}
'''


def tree(**extra: str) -> dict[str, str]:
    return {"code/tools.py": PLAIN, **extra}


def decorated(*lines: str, source: str = PLAIN) -> str:
    """PLAIN with a line above each def: ``lines`` in order of the defs."""
    out: list[str] = []
    todo = list(lines)
    for ln in source.splitlines():
        if ln.startswith(("def ", "async def ")) and todo:
            out.append(todo.pop(0))
        out.append(ln)
    return "\n".join(out) + "\n"


def load(tmp_path: Path, text: str, name: str = "guardian_client") -> ModuleType:
    """Import generated text as a module (written to a file first: no exec, no eval)."""
    path = tmp_path / f"{name}.py"
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------ the code file


def test_client_source_is_valid_python_and_bakes_the_use_case(tmp_path: Path) -> None:
    text = gk.client_source("payment-ops-copilot", "1.2.0", {t.name: t.risk for t in TOOLS})
    ast.parse(text)
    mod = load(tmp_path, text)
    assert mod.AGENT_ID == "payment-ops-copilot" and mod.AGENT_VERSION == "1.2.0"
    assert mod.TOOLS == {"add_payee": "pii_export", "reconcile": "read_only", "transfer": "money"}
    assert text.count("baked by Guardian: begin") == 1


def test_client_source_refuses_a_bad_id_and_unknown_risk(tmp_path: Path) -> None:
    text = gk.client_source("bad id with spaces", "1 0", {"a": "money", "b": "unknown_class"})
    mod = load(tmp_path, text)
    assert mod.AGENT_ID == "FILL-ME-agent-id" and mod.AGENT_VERSION == "1.0.0"
    assert mod.TOOLS == {"a": "money"}


def test_client_source_is_standard_library_only() -> None:
    text = gk.client_source("a1", "1", {})
    imported = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    # databricks.sdk is imported inside a function and only when it is there
    assert "supervisor" not in imported and "httpx" not in imported and "requests" not in imported
    import sys

    stdlib = set(sys.stdlib_module_names)
    assert imported - stdlib <= {"databricks"}
    top_level = {
        n.module.split(".")[0]
        for n in ast.parse(text).body
        if isinstance(n, ast.ImportFrom) and n.module and n.level == 0
    }
    assert "databricks" not in top_level
    assert "__future__" in top_level


def test_client_source_holds_no_secret_and_no_exec() -> None:
    text = gk.client_source("a1", "1", {"x": "money"})
    for banned in ("exec(", "eval(", "compile(", "subprocess", "os.system", "__import__"):
        assert banned not in text
    assert "Bearer " in text  # the header name is there ...
    assert "token =" not in text and "password" not in text.lower()  # ... a token never is


def test_client_template_and_generated_file_differ_only_in_the_baked_block() -> None:
    template = (REPO_ROOT / "src/supervisor/adapters/guardian_client_template.py").read_text(
        "utf-8"
    )
    text = gk.client_source("a1", "1", {"x": "money"})
    head = template.split("# ---- baked by Guardian: begin ----")[0]
    tail = template.split("# ---- baked by Guardian: end ----\n")[1]
    assert text.startswith(head) and text.endswith(tail)


# ------------------------------------------------------------------------------ the check: scan


def test_scan_reads_both_forms_and_constants() -> None:
    src = (
        "from guardian_client import supervised_tool\n"
        "from supervisor.gateway.sdk import supervised_tool as sdk_tool\n"
        'NAME = "transfer"\n'
        "AID = 'a1'\n"
        "class K:\n"
        '    @supervised_tool("reconcile")\n'
        "    def reconcile(self): ...\n"
        '@supervised_tool(NAME, "money")\n'
        "def transfer(): ...\n"
        '@supervised_tool(AID, "1.0.0", "add_payee", "pii_export", gate=None)\n'
        "async def add_payee(): ...\n"
        '@supervised_tool(AID, "1.0.0", tool_name="x", risk_class="read_only")\n'
        "def other(): ...\n"
        "@unrelated\n"
        "def nope(): ...\n"
    )
    found, bad = scan_one(src)
    assert bad == 0
    got = {(g.func, g.tool, g.risk, g.form) for g in found}
    assert got == {
        ("reconcile", "reconcile", None, "kit"),
        ("transfer", "transfer", "money", "kit"),
        ("add_payee", "add_payee", "pii_export", "sdk"),
        ("other", "x", "read_only", "sdk"),
    }


def scan_one(src: str) -> tuple[list[gk.Gated], int]:
    return gk.scan_files({"a.py": src})


def test_scan_survives_a_file_that_is_not_python() -> None:
    found, bad = gk.scan_files({"a.py": "def (:\n", "b.py": "x = 1\n", "c.md": "# hi"})
    assert found == [] and bad == 1


# ------------------------------------------------------------------------------ the check: trees


def test_tree_with_no_line_is_not_ready() -> None:
    r = gk.check_files(TOOLS, tree())
    assert r["status"] == "not_ready" and (r["tools_ok"], r["tools_total"]) == (0, 3)
    assert [x["state"] for x in r["tools"]] == ["missing"] * 3


def test_partial_tree_is_partly_ready_with_the_missing_tool_named() -> None:
    files = tree()
    files["code/tools.py"] = decorated('@supervised_tool("reconcile")')
    r = gk.check_files(TOOLS, files)
    assert r["status"] == "partly_ready" and r["tools_ok"] == 1
    states = {x["name"]: x["state"] for x in r["tools"]}
    assert states == {"reconcile": "connected", "add_payee": "missing", "transfer": "missing"}
    row = next(x for x in r["tools"] if x["name"] == "reconcile")
    assert row["file"] == "code/tools.py" and isinstance(row["line"], int)


def test_full_tree_is_ready_only_with_the_client_file() -> None:
    lines = [
        '@supervised_tool("reconcile")',
        '@supervised_tool("add_payee")',
        '@supervised_tool("transfer")',
    ]
    files = tree()
    files["code/tools.py"] = decorated(*lines)
    r = gk.check_files(TOOLS, files)
    assert r["status"] == "partly_ready" and r["notes"] == ["client_file_missing"]
    files["code/guardian_client.py"] = gk.client_source("a1", "1", {})
    r = gk.check_files(TOOLS, files)
    assert r["status"] == "ready" and r["tools_ok"] == 3 and r["notes"] == []


def test_full_tree_with_the_full_sdk_form_is_ready_without_the_client_file() -> None:
    sdk = [
        '@supervised_tool(AID, "1.0.0", "reconcile", "read_only", gate=g)',
        '@supervised_tool(AID, "1.0.0", "add_payee", "pii_export", gate=g)',
        '@supervised_tool(AID, "1.0.0", "transfer", "money", gate=g)',
    ]
    r = gk.check_files(TOOLS, {"code/tools.py": decorated(*sdk)})
    assert r["status"] == "ready" and r["notes"] == []


def test_wrong_name_and_wrong_risk_are_told_apart() -> None:
    lines = [
        '@supervised_tool("reconcile")',
        '@supervised_tool("add_payees")',  # the function is add_payee, the line names add_payees
        '@supervised_tool("transfer", "read_only")',  # the tool is money
    ]
    files = {"code/tools.py": decorated(*lines), "code/guardian_client.py": "x = 1\n"}
    r = gk.check_files(TOOLS, files)
    by = {x["name"]: x for x in r["tools"]}
    assert (
        by["add_payee"]["state"] == "wrong_name" and by["add_payee"]["found_name"] == "add_payees"
    )
    assert by["transfer"]["state"] == "wrong_risk" and by["transfer"]["found_risk"] == "read_only"
    assert r["status"] == "partly_ready" and r["tools_ok"] == 1
    assert "add_payees" not in r["extras"]  # it was matched to a tool (wrongly named), not extra


def test_a_line_for_a_tool_the_code_scan_did_not_list_is_an_extra() -> None:
    files = {
        "a.py": (
            '@supervised_tool("transfer")\ndef f(): ...\n@supervised_tool("zzz")\ndef g(): ...\n'
        )
    }
    r = gk.check_files([gk.ToolRef("transfer", "money", "a.py", 2)], files)
    assert r["extras"] == ["zzz"] and r["tools_ok"] == 1


def test_no_tools_is_its_own_status() -> None:
    r = gk.check_files([], tree())
    assert r["status"] == "no_tools" and r["tools_total"] == 0


def test_unreadable_python_file_is_noted_and_left_out() -> None:
    r = gk.check_files(TOOLS, {**tree(), "broken.py": "def ("})
    assert "unparsed_files" in r["notes"] and r["unparsed"] == 1


def test_check_result_is_canonical_json_with_integers_only() -> None:
    r = gk.check_files(TOOLS, tree())
    json.dumps(r)
    canonical_bytes({"counts": [r["tools_total"], r["tools_ok"]]})


# ------------------------------------------------------------------------------ the guide


def test_guide_follows_the_framework_and_the_credential() -> None:
    g = gk.guide(
        agent_id="a1", tools=TOOLS, framework="langgraph", credential="hmac", gate_url="https://g"
    )
    assert g["placement"] == "decorator" and g["example"]["name"] == "transfer"  # money first
    texts = [ln["text"] for ln in g["snippet"]]
    assert texts[0] == gk.IMPORT_LINE and "@tool" in texts
    assert (
        texts.index("@tool")
        < texts.index('@supervised_tool("transfer")')
        < texts.index("def transfer(...):")
    )
    assert g["env_lines"][0] == "set GUARDIAN_URL=https://g" and g["credential"] == "hmac"
    assert [t["text"] for t in g["tool_lines"]] == [f'@supervised_tool("{t.name}")' for t in TOOLS]
    assert g["put_dir"] == "code"
    oauth = gk.guide(
        agent_id="a1",
        tools=TOOLS,
        framework="fastapi",
        credential="databricks_oauth",
        gate_url="https://g",
    )
    assert oauth["placement"] == "wrapper" and oauth["env_lines"][0] == "env:"
    assert any(ln["text"].startswith("def gated_") for ln in oauth["snippet"])
    assert (
        gk.guide(agent_id="", tools=[], framework="zzz", credential="hmac", gate_url="u")["example"]
        is None
    )


def test_guide_has_no_secret() -> None:
    g = gk.guide(
        agent_id="a1", tools=TOOLS, framework="custom", credential="hmac", gate_url="https://g"
    )
    blob = json.dumps(g)
    assert "FILL-ME-path-to-key-file" in blob and "Bearer" not in blob


# ------------------------------------------------------------------------------ framework samples
SAMPLES = [
    "langgraph_loan_triage",
    "fastmcp_account_tools",
    "openai_fx_quotes",
    "anthropic_dispute_helper",
    "mlflow_chatagent_savings",
    "langchain_card_support",
    "crewai_collections",
    "fastapi_toolserver_remit",
]


def add_lines(
    files: dict[str, str], tools: list[gk.ToolRef], only: int | None = None
) -> dict[str, str]:
    """Put ``@supervised_tool("name")`` directly above the def of each tool (the guide's rule)."""
    out = dict(files)
    by_file: dict[str, list[gk.ToolRef]] = {}
    for t in tools[:only]:
        by_file.setdefault(t.file, []).append(t)
    for path, refs in by_file.items():
        lines = out[path].splitlines()
        for t in sorted(refs, key=lambda x: x.line or 0, reverse=True):
            i = (t.line or 1) - 1
            while not lines[i].lstrip().startswith(("def ", "async def ")):
                i += 1
                assert i - (t.line or 1) < 8, f"no def near {path}:{t.line}"
            indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
            lines.insert(i, f'{indent}@supervised_tool("{t.name}")')
        out[path] = "\n".join(lines) + "\n"
    return out


@pytest.mark.parametrize("name", SAMPLES)
def test_corpus_sample_goes_from_not_ready_to_ready(name: str) -> None:
    root = REPO_ROOT / "data" / "corpus" / "repos" / name
    inv = discover(LocalGitRepoReader(root)).inventory
    tools = [
        gk.ToolRef(t.name, t.risk_class, t.definition.file, t.definition.line)
        for t in inv.tools
        if t.definition is not None
    ]
    assert tools, name
    files = {p.relative_to(root).as_posix(): p.read_text("utf-8") for p in root.rglob("*.py")}
    before = gk.check_files(tools, files)
    assert before["status"] == "not_ready", (name, before["tools"])
    if len(tools) > 1:
        half = gk.check_files(tools, add_lines(files, tools, only=1))
        assert half["status"] == "partly_ready" and half["tools_ok"] == 1, (name, half["tools"])
    patched = add_lines(files, tools)
    for text in patched.values():
        ast.parse(text)  # the line never breaks the file
    no_file = gk.check_files(tools, patched)
    assert no_file["notes"] == ["client_file_missing"]
    after = gk.check_files(
        tools, {**patched, "guardian_client.py": gk.client_source("a1", "1", {})}
    )
    assert after["status"] == "ready" and after["tools_ok"] == len(tools), (name, after["tools"])


@pytest.mark.parametrize("name", SAMPLES)
def test_corpus_sample_framework_has_a_placement(name: str) -> None:
    inv = discover(LocalGitRepoReader(REPO_ROOT / "data" / "corpus" / "repos" / name)).inventory
    assert inv.framework in gk.PLACEMENT


def test_every_known_framework_has_a_placement_and_a_label() -> None:
    from supervisor.console.guardian_kit_routes import FRAMEWORK_LABEL
    from supervisor.onboard.codefacts import _FRAMEWORKS

    for fw, _prefixes in _FRAMEWORKS:
        assert fw in gk.PLACEMENT, fw
        assert fw in FRAMEWORK_LABEL, fw
    assert gk.PLACEMENT["custom"] == "function"


def test_off_path_setting_default_is_off() -> None:
    from supervisor.config import Settings

    s: Any = Settings(_env_file=None)
    assert s.guardian_kit is False
    with pytest.raises(gk.KitError) as exc:
        gk.require_on(s)
    assert exc.value.code == "guardian_kit_off" and "GUARDIAN_KIT=1" in str(exc.value)
