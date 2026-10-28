"""WP-O1 (phase 9): candidate source intake. Zip rules, the scrub before storage, attempt numbers,
the git host allow-list, the stub for a workspace folder and the flag off path."""

from __future__ import annotations

import ast
import io
import json
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor import sandbox
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from supervisor.onboard import intake
from supervisor.onboard.intake import IntakeError, IntakeService

NODE = "inv_0123456789abcdef"
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"  # built at run time: the secret scan of the repo stays quiet
PASSWORD = "S3cr3t-Value!"
DB_PASSWORD = "Hunter2pass"


def make_zip(entries: dict[str, bytes | str], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            zf.writestr(info, "../../etc/passwd")
    return buf.getvalue()


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        onboard_intake=True,
        onboard_git_hosts="git.example.invalid",
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def svc(adapters: Adapters) -> IntakeService:
    return IntakeService(adapters.settings, adapters.state, adapters.clock)


def stored(svc: IntakeService, n: int) -> dict[str, str]:
    root = svc.tree_path(NODE, n)
    return {
        p.relative_to(root).as_posix(): p.read_text("utf-8") for p in root.rglob("*") if p.is_file()
    }


# --------------------------------------------------------------------------------- the zip


def test_zip_accepted_and_stored_under_data_dir(svc: IntakeService, adapters: Adapters) -> None:
    data = make_zip(
        {
            "agent/main.py": "print('hello')\n",
            "agent/config.yaml": "model: demo\n",
            "README.md": "# demo\n",
            ".env.example": "API_URL=https://example.invalid\n",
            "sql/q.sql": "select 1;\n",
        }
    )
    a = svc.submit_zip(NODE, data, "demo.zip", "reviewer.an")
    assert (a["n"], a["status"], a["file_count"], a["source_kind"]) == (1, "scrubbed", 5, "upload")
    assert a["source_ref"] == "demo.zip" and a["created_by"] == "reviewer.an"
    assert len(a["sha256"]) == 64 and a["size_bytes"] == len(data)
    root = Path(adapters.settings.data_dir) / "intake" / NODE / "1"
    assert (root / "agent" / "main.py").read_text() == "print('hello')\n"
    assert (root / ".env.example").is_file()


def test_oversize_zip_rejected_with_code_and_a_failed_attempt(adapters: Adapters) -> None:
    s = load_settings(
        sql_backend="sqlite",
        data_dir=adapters.settings.data_dir,
        llm_base_url="",
        onboard_intake=True,
        onboard_intake_max_mb=1,
    )
    svc = IntakeService(s, adapters.state, adapters.clock)
    big = make_zip({"a.txt": "x" * 100}) + b"\0" * (1024 * 1024)
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, big, "big.zip", "u")
    assert ei.value.code == "too_large" and str(ei.value).startswith("too_large:")
    rows = svc.attempts(NODE)
    assert [(r["n"], r["status"]) for r in rows] == [(1, "failed")]
    assert not svc.tree_path(NODE, 1).exists()


def test_zip_bomb_is_refused_by_unpacked_size(adapters: Adapters) -> None:
    s = load_settings(
        sql_backend="sqlite",
        data_dir=adapters.settings.data_dir,
        llm_base_url="",
        onboard_intake=True,
        onboard_intake_max_mb=1,
    )
    svc = IntakeService(s, adapters.state, adapters.clock)
    data = make_zip({f"f{i}.txt": "a" * 600_000 for i in range(3)})
    assert len(data) < 1024 * 1024
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, data, "bomb.zip", "u")
    assert ei.value.code == "too_large"


@pytest.mark.parametrize(
    "name",
    ["../evil.py", "a/../../evil.py", "/etc/passwd.txt", "C:/x.py", "a\\b.py", "a//b.py", "./a.py"],
)
def test_bad_path_rejected(svc: IntakeService, name: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo(name), "x = 1\n")
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, buf.getvalue(), "z.zip", "u")
    assert ei.value.code == "bad_path"
    assert not (svc.root / "evil.py").exists()


def test_symlink_rejected(svc: IntakeService) -> None:
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, make_zip({"a.py": "x=1\n"}, symlink="link.py"), "z.zip", "u")
    assert ei.value.code == "symlink"


def test_binary_and_other_types_rejected(svc: IntakeService) -> None:
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, make_zip({"model.bin": b"\x00\x01\x02"}), "z.zip", "u")
    assert ei.value.code == "file_type_not_allowed"
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, make_zip({"a.py": b"\x00\x01\x02\xff"}), "z.zip", "u")
    assert ei.value.code == "binary_file"
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, make_zip({"a.py": b"\xff\xfe\xfa"}), "z.zip", "u")
    assert ei.value.code == "binary_file"
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, make_zip({".env": "A=1\n"}), "z.zip", "u")
    assert ei.value.code == "file_type_not_allowed"
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, b"not a zip", "z.zip", "u")
    assert ei.value.code == "not_zip"
    assert all(r["status"] == "failed" for r in svc.attempts(NODE))


def test_one_bad_file_stores_nothing(svc: IntakeService) -> None:
    with pytest.raises(IntakeError):
        svc.submit_zip(NODE, make_zip({"ok.py": "x=1\n", "logo.png": "x"}), "z.zip", "u")
    assert not (svc.root / NODE).exists() or not any((svc.root / NODE).glob("[0-9]*"))


def test_ipynb_keeps_code_cells_only_as_py(svc: IntakeService) -> None:
    nb = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Title that must not stay\n"]},
            {
                "cell_type": "code",
                "source": ["import os\n", "%pip install x\n", "x = 1\n"],
                "outputs": [{"text": ["OUTPUT-MUST-NOT-STAY"]}],
            },
            {"cell_type": "code", "source": "y = 2"},
        ],
        "metadata": {},
        "nbformat": 4,
    }
    a = svc.submit_zip(NODE, make_zip({"work/flow.ipynb": json.dumps(nb)}), "nb.zip", "u")
    files = stored(svc, a["n"])
    assert list(files) == ["work/flow.py"]
    text = files["work/flow.py"]
    assert "import os" in text and "y = 2" in text and "# %pip install x" in text
    assert "Title that must not stay" not in text and "OUTPUT-MUST-NOT-STAY" not in text
    ast.parse(text)  # the stored text is parseable Python


def test_bad_notebook_rejected(svc: IntakeService) -> None:
    with pytest.raises(IntakeError) as ei:
        svc.submit_zip(NODE, make_zip({"a.ipynb": "{not json"}), "z.zip", "u")
    assert ei.value.code == "bad_notebook"


# --------------------------------------------------------------------------------- the scrub


def test_planted_secret_never_lands_in_the_stored_tree_or_the_row(
    svc: IntakeService, adapters: Adapters
) -> None:
    nb = {
        "cells": [{"cell_type": "code", "source": [f"KEY = '{AWS_KEY}'\n"]}],
        "metadata": {},
        "nbformat": 4,
    }
    data = make_zip(
        {
            "app/settings.py": f"password = '{PASSWORD}'\nAWS = '{AWS_KEY}'\n",
            "app/db.yaml": f"url: postgresql://admin:{DB_PASSWORD}@db.example.invalid:5432/x\n",
            "app/nb.ipynb": json.dumps(nb),
            "app/ok.py": "x = 1\n",
        }
    )
    a = svc.submit_zip(NODE, data, "planted.zip", "reviewer.an")
    assert a["status"] == "scrubbed" and a["file_count"] == 4
    for needle in (AWS_KEY, PASSWORD, DB_PASSWORD):
        for path in Path(adapters.settings.data_dir).rglob("*"):
            if path.is_file() and path.suffix not in (".db", ".sqlite", ".sqlite3"):
                assert needle not in path.read_text("utf-8", errors="ignore"), (needle, path)
        assert needle not in json.dumps(a)
        assert needle not in json.dumps(svc.attempts(NODE))
    files = stored(svc, 1)
    assert "[REDACTED:" in files["app/settings.py"] and "[REDACTED:" in files["app/nb.py"]
    assert files["app/ok.py"] == "x = 1\n"
    assert "redacted=" in a["detail"] and "redacted=0" not in a["detail"]
    # line numbers stay valid after the scrub (the scrubber keeps line breaks)
    assert files["app/settings.py"].count("\n") == 2


def test_the_stored_tree_is_written_by_the_scrubber_not_the_raw_bytes(
    svc: IntakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = intake.Scrubber.scrub

    def spy(self: Any, text: str, source: str = "<text>") -> str:
        seen.append(source)
        return real(self, text, source)

    monkeypatch.setattr(intake.Scrubber, "scrub", spy)
    svc.submit_zip(NODE, make_zip({"a.py": "x=1\n", "b.md": "hi\n"}), "z.zip", "u")
    assert sorted(seen) == ["a.py", "b.md"]


def test_a_secret_in_the_file_name_does_not_reach_the_row(svc: IntakeService) -> None:
    a = svc.submit_zip(NODE, make_zip({"a.py": "x=1\n"}), f"{AWS_KEY}.zip", "u")
    assert AWS_KEY not in a["source_ref"]


# --------------------------------------------------------------------------------- numbering


def test_attempt_numbering_reupload_keeps_old_attempts(svc: IntakeService) -> None:
    a1 = svc.submit_zip(NODE, make_zip({"a.py": "v = 1\n"}), "one.zip", "u")
    a2 = svc.submit_zip(NODE, make_zip({"a.py": "v = 2\n"}), "two.zip", "u")
    with pytest.raises(IntakeError):
        svc.submit_zip(NODE, b"junk", "bad.zip", "u")
    a4 = svc.submit_zip(NODE, make_zip({"a.py": "v = 4\n"}), "four.zip", "u")
    assert (a1["n"], a2["n"], a4["n"]) == (1, 2, 4)  # the failed attempt used number 3
    assert [r["n"] for r in svc.attempts(NODE)] == [4, 3, 2, 1]
    assert stored(svc, 1)["a.py"] == "v = 1\n" and stored(svc, 2)["a.py"] == "v = 2\n"
    other = svc.submit_zip("inv_other", make_zip({"a.py": "w = 1\n"}), "o.zip", "u")
    assert other["n"] == 1


def test_node_ids_with_odd_characters_get_safe_unique_folders(svc: IntakeService) -> None:
    assert intake.node_dir_name("agent-1") == "agent-1"
    d1, d2 = intake.node_dir_name("a:b"), intake.node_dir_name("a_b")
    assert d1 != d2 and ":" not in d1 and "/" not in d1
    assert intake.node_dir_name("..").startswith("node-") or ".." not in intake.node_dir_name("..")
    for bad in ("", "..", ".", "a/b", "a b", "x" * 200):
        with pytest.raises(IntakeError) as ei:
            svc.attempts(bad)
        assert ei.value.code == "bad_node_id"


# --------------------------------------------------------------------------------- git


def test_git_host_not_allowed(svc: IntakeService) -> None:
    for url, code in (
        ("https://evil.example.invalid/org/repo", "git_host_not_allowed"),
        ("http://git.example.invalid/org/repo", "git_url_invalid"),
        ("git@git.example.invalid:org/repo.git", "git_url_invalid"),
        ("file:///etc", "git_url_invalid"),
        ("https://user:pw@git.example.invalid/org/repo", "url_has_credentials"),
        ("https://git.example.invalid:8443/org/repo", "git_url_invalid"),
        ("https://git.example.invalid/org/repo?x=1", "git_url_invalid"),
        ("https://git.example.invalid/../repo", "git_url_invalid"),
        ("ext::sh -c id", "git_url_invalid"),
        ("", "git_url_invalid"),
    ):
        with pytest.raises(IntakeError) as ei:
            svc.submit_git(NODE, url, "u")
        assert ei.value.code == code, (url, ei.value.code)
    assert svc.attempts(NODE) == []  # a refused request is not an attempt


def test_git_off_when_no_host_is_configured(adapters: Adapters) -> None:
    s = load_settings(
        sql_backend="sqlite",
        data_dir=adapters.settings.data_dir,
        llm_base_url="",
        onboard_intake=True,
    )
    svc = IntakeService(s, adapters.state, adapters.clock)
    with pytest.raises(IntakeError) as ei:
        svc.submit_git(NODE, "https://git.example.invalid/org/repo", "u")
    assert ei.value.code == "git_off"


def _fake_clone(files: dict[str, bytes | None]) -> Callable[..., sandbox.RunResult]:
    def clone(url: str, dest: str | Path, *, timeout_s: float = 120.0) -> sandbox.RunResult:
        root = Path(dest)
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if data is None:
                path.symlink_to("/etc/passwd")
            else:
                path.write_bytes(data)
        return sandbox.RunResult(("git", "clone", url), 0, "", "")

    return clone


def test_git_clone_is_scrubbed_and_other_files_are_skipped(
    svc: IntakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        intake.sandbox,
        "git_clone_https",
        _fake_clone(
            {
                "src/app.py": f"password = '{PASSWORD}'\n".encode(),
                "src/data.bin": b"\x00\x01",
                "logo.png": b"\x89PNG",
                ".git/config": b"[core]\n",
                "link.py": None,
            }
        ),
    )
    a = svc.submit_git(NODE, "https://git.example.invalid/org/repo/", "u")
    assert (a["n"], a["source_kind"], a["status"], a["file_count"]) == (1, "git", "scrubbed", 1)
    assert a["source_ref"] == "https://git.example.invalid/org/repo"
    assert "skipped=" in a["detail"]
    files = stored(svc, 1)
    assert list(files) == ["src/app.py"] and PASSWORD not in files["src/app.py"]
    assert not list((svc.root / NODE).glob(".clone-*"))  # the clone folder is removed


def test_git_clone_failure_is_a_failed_attempt(
    svc: IntakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(url: str, dest: str | Path, *, timeout_s: float = 120.0) -> sandbox.RunResult:
        return sandbox.RunResult(("git",), 128, "", f"fatal: {url} {AWS_KEY}")

    monkeypatch.setattr(intake.sandbox, "git_clone_https", boom)
    with pytest.raises(IntakeError) as ei:
        svc.submit_git(NODE, "https://git.example.invalid/org/repo", "u")
    assert ei.value.code == "clone_failed" and AWS_KEY not in str(ei.value)
    assert [(r["n"], r["status"]) for r in svc.attempts(NODE)] == [(1, "failed")]


def test_sandbox_clone_argv_is_https_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kw: Any) -> sandbox.RunResult:
        calls.append(argv)
        return sandbox.RunResult(tuple(argv), 0, "", "")

    monkeypatch.setattr(sandbox, "run", fake_run)
    sandbox.git_clone_https("https://git.example.invalid/org/repo", tmp_path / "x" / "repo")
    argv = calls[0]
    assert "protocol.https.allow=always" in argv and "protocol.allow=never" in argv
    assert argv[argv.index("clone") + 1 :][:5] == [
        "--quiet",
        "--depth",
        "1",
        "--single-branch",
        "--no-tags",
    ]
    assert argv[-2] == "https://git.example.invalid/org/repo" and argv[-3] == "--"
    for bad in ("http://x/y", "file:///x", "ext::sh", "-uhttps://x"):
        with pytest.raises(Exception, match="https"):
            sandbox.git_clone_https(bad, tmp_path / "y")


# --------------------------------------------------------------------------------- stub, flag


def test_workspace_is_a_stub_naming_wp_o1c(svc: IntakeService) -> None:
    with pytest.raises(IntakeError) as ei:
        svc.submit_workspace(NODE, "/Workspace/Users/x/agent", "u")
    assert ei.value.code == "not_built" and "WP-O1c" in str(ei.value)


def test_flag_off_is_an_error_and_writes_nothing(adapters: Adapters) -> None:
    s = load_settings(sql_backend="sqlite", data_dir=adapters.settings.data_dir, llm_base_url="")
    assert s.onboard_intake is False and s.onboard_intake_max_mb == 20 and s.onboard_git_hosts == ""
    svc = IntakeService(s, adapters.state, adapters.clock)
    for call in (
        lambda: svc.submit_zip(NODE, make_zip({"a.py": "x=1\n"}), "z.zip", "u"),
        lambda: svc.submit_git(NODE, "https://git.example.invalid/o/r", "u"),
        lambda: svc.submit_workspace(NODE, "/Workspace/x", "u"),
    ):
        with pytest.raises(IntakeError) as ei:
            call()
        assert ei.value.code == "intake_off" and "ONBOARD_INTAKE=1" in str(ei.value)
    assert svc.attempts(NODE) == []
    assert not (Path(s.data_dir) / "intake").exists()
