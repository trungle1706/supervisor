"""RepoReader (local_git), WorkspaceReader (fixtures, databricks_sdk with a fake) and
the sandbox git allow-list."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor import sandbox
from supervisor.adapters.repo import (
    BinaryFileSkipped,
    FileTooLarge,
    LocalGitRepoReader,
    RepoReadError,
)
from supervisor.adapters.workspace import FixtureWorkspaceReader
from supervisor.adapters.workspace.databricks_sdk import DatabricksWorkspaceReader
from supervisor.core.errors import SandboxError
from supervisor.core.ports import RepoReader, WorkspaceReader
from tests.conftest import REPO_ROOT


def _tree(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pkg" / "big.txt").write_text("y" * 5000, encoding="utf-8")
    (root / "pkg" / "blob.dat").write_bytes(b"ab\x00cd")
    (root / "img.png").write_bytes(b"\x89PNG")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "a.cpython-311.pyc").write_bytes(b"\x00")


def test_local_reader_lists_and_reads(tmp_path: Path) -> None:
    _tree(tmp_path)
    r = LocalGitRepoReader(tmp_path, max_file_bytes=1000)
    _r: RepoReader = r  # structural check (mypy); protocols are not runtime_checkable
    assert callable(_r.list_files) and callable(_r.read_text)
    files = r.list_files()
    assert files == ["pkg/a.py", "pkg/big.txt", "pkg/blob.dat"]
    assert r.skipped["img.png"] == "binary"
    assert r.list_files("**/*.py") == ["pkg/a.py"]
    assert r.read_text("pkg/a.py") == "x = 1\n"
    with pytest.raises(FileTooLarge):
        r.read_text("pkg/big.txt")
    with pytest.raises(BinaryFileSkipped):
        r.read_text("pkg/blob.dat")
    for bad in ("../etc/passwd", "/etc/passwd", "pkg/../../x", "nope.py"):
        with pytest.raises(RepoReadError):
            r.read_text(bad)


def test_local_reader_has_no_write_methods() -> None:
    names = {n for n in dir(LocalGitRepoReader) if not n.startswith("_")}
    assert not {n for n in names if any(w in n for w in ("write", "delete", "commit", "push"))}


@pytest.mark.skipif(os.name == "nt", reason="symlinks need admin rights on Windows")
def test_symlink_outside_root_is_skipped(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "link.txt").symlink_to(outside)
    r = LocalGitRepoReader(root)
    assert r.list_files() == []
    with pytest.raises(RepoReadError):
        r.read_text("link.txt")


def test_revision_in_git_tree() -> None:
    rev = LocalGitRepoReader(REPO_ROOT / "src" / "supervisor_agents" / "payments").revision()
    assert rev is not None and len(rev) == 40


def test_fixture_workspace_reader(tmp_path: Path) -> None:
    data = {
        "serving_endpoints": [{"name": "agent-llm", "model": "qwen3-4b", "family": "qwen"}],
        "tables": {"bank.core": ["transfers", "accounts"]},
        "apps": [{"name": "payments-app"}],
    }
    p = tmp_path / "ws.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    w = FixtureWorkspaceReader.from_file(p)
    _w: WorkspaceReader = w
    assert callable(_w.list_tables)
    assert w.list_serving_endpoints()[0]["name"] == "agent-llm"
    assert w.list_tables("bank", "core") == ["accounts", "transfers"]
    assert w.list_tables("bank", "other") == []
    assert w.list_apps() == [{"name": "payments-app"}]
    assert FixtureWorkspaceReader.empty().list_serving_endpoints() == []


class _FakeList:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.calls: list[dict[str, Any]] = []

    def list(self, **kw: Any) -> list[Any]:
        self.calls.append(kw)
        return list(self.items)


def test_databricks_reader_with_fake_client() -> None:
    ent = SimpleNamespace(foundation_model=SimpleNamespace(name="databricks-llama"))
    endpoint = SimpleNamespace(
        name="agent-llm",
        task="llm/v1/chat",
        state=SimpleNamespace(ready=SimpleNamespace(value="READY")),
        config=SimpleNamespace(served_entities=[ent]),
    )
    client = SimpleNamespace(
        apps=_FakeList([SimpleNamespace(name="payments-app", url="https://x", description="d")]),
        serving_endpoints=_FakeList([endpoint]),
        tables=_FakeList(
            [SimpleNamespace(full_name="bank.core.transfers", name="transfers")]
            + [SimpleNamespace(full_name=None, name="accounts")]
        ),
    )
    r = DatabricksWorkspaceReader(client, max_items=10)
    _w: WorkspaceReader = r
    assert callable(_w.list_serving_endpoints)
    eps = r.list_serving_endpoints()
    assert eps == [
        {
            "name": "agent-llm",
            "task": "llm/v1/chat",
            "state": "READY",
            "served": ["databricks-llama"],
            "entities": [{"kind": "foundation_model", "name": "databricks-llama"}],
            "agent": False,
        }
    ]
    assert r.list_tables("bank", "core") == ["bank.core.accounts", "bank.core.transfers"]
    assert client.tables.calls == [{"catalog_name": "bank", "schema_name": "core"}]
    assert r.list_apps()[0]["name"] == "payments-app"
    # The reader only lists: the fake has no other methods and none were needed.


@pytest.mark.skipif(os.environ.get("RUN_DATABRICKS") != "1", reason="set RUN_DATABRICKS=1")
def test_databricks_reader_live() -> None:  # pragma: no cover - live kit
    from supervisor.config import load_settings

    settings = load_settings()
    r = DatabricksWorkspaceReader.from_settings(settings)
    assert isinstance(r.list_serving_endpoints(), list)
    if settings.databricks_catalog and settings.databricks_schema:
        assert isinstance(
            r.list_tables(settings.databricks_catalog, settings.databricks_schema), list
        )


@pytest.mark.parametrize(
    "args", [["merge", "main"], ["push", "origin"], ["pull"], ["fetch"], ["rebase", "x"]]
)
def test_sandbox_git_refuses_merge_and_push(args: list[str], tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="not allowed"):
        sandbox.git(args, cwd=tmp_path)


@pytest.mark.parametrize(
    "args",
    [
        ["clone", "--upload-pack=touch /tmp/x", "a", "b"],
        ["clone", "--upload-p", "touch /tmp/x", "a", "b"],  # abbreviation
        ["clone", "-ccore.sshCommand=touch /tmp/x", "a", "b"],  # attached short form
        ["clone", "--config", "core.sshCommand=x", "a", "b"],
        ["clone", "--reference", "x", "a", "b"],
        ["clone", "--recurse-submodules", "a", "b"],
        ["clone", "--template=/tmp/t", "a", "b"],
        ["diff", "--output=/tmp/x"],
        ["show", "--output=/tmp/x", "HEAD"],
        ["add", "-u"],
    ],
)
def test_sandbox_git_refuses_unlisted_options(args: list[str], tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="option"):
        sandbox.git(args, cwd=tmp_path)


def test_sandbox_git_refuses_ext_transport(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="transport"):
        sandbox.git(["clone", "ext::sh -c touch% /tmp/pwned", str(tmp_path / "d")], cwd=tmp_path)


def test_sandbox_git_values_after_value_flags_are_data(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    assert sandbox.git(["init", "-q", "-b", "main", str(repo)], cwd=tmp_path).ok
    (repo / "f.txt").write_text("x", encoding="utf-8")
    assert sandbox.git(["add", "--all"], cwd=repo).ok
    res = sandbox.git(
        ["commit", "-q", "-m", "--not-an-option"], cwd=repo, identity=("T", "t@example.invalid")
    )
    assert res.ok, res.stderr


def test_sandbox_git_runs_allowed(tmp_path: Path) -> None:
    res = sandbox.git(["init", "-q", "-b", "main", str(tmp_path / "r")], cwd=tmp_path)
    assert res.ok, res.stderr
    assert sandbox.git(["status", "--porcelain"], cwd=tmp_path / "r").ok
