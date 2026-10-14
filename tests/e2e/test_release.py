"""WP11 release: git archive of a temp clone + requirements + uv.toml + HANDOFF + leak sweep.

The release is built from a fresh clone (committed files only), the zip is unpacked and
the demo runs from the unpacked tree. A planted .env and a planted workspace host make the
release fail with the offending paths.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from supervisor import release, sandbox
from tests.conftest import REPO_ROOT
from tests.test_no_secrets import PATTERNS


def _git(cwd: Path, *args: str) -> sandbox.RunResult:
    res = sandbox.run(
        ["git", "-c", "user.name=wp11-test", "-c", "user.email=wp11@example.invalid", *args],
        cwd=cwd,
        timeout_s=120,
    )
    assert res.ok, res.stderr
    return res


@pytest.fixture(scope="module")
def clone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("rel")
    _git(base, "clone", "--quiet", "--no-local", str(REPO_ROOT), "clone")
    return base / "clone"


@pytest.fixture(scope="module")
def built(clone: Path, tmp_path_factory: pytest.TempPathFactory) -> release.ReleaseReport:
    out = tmp_path_factory.mktemp("out")
    lines: list[str] = []
    rep = release.build_release(
        out,
        repo=clone,
        nexus=True,
        wheelhouse=True,
        echo=lines.append,
        wheel_fetcher=lambda _r, _d: (False, "no network on the test host"),
    )
    assert rep.ok, "\n".join(lines)
    assert all(line.isascii() for line in lines)
    return rep


def test_zip_contents(built: release.ReleaseReport) -> None:
    assert built.zip_path is not None and built.zip_path.is_file()
    names = set(built.entries)
    for want in (
        "supervisor/HANDOFF.md",
        "supervisor/uv.toml",
        "supervisor/requirements.txt",
        "supervisor/uv.lock",
        "supervisor/pyproject.toml",
        "supervisor/src/supervisor/cli.py",
        "supervisor/policies/baseline.yaml",
        "supervisor/.env.example",
    ):
        assert want in names, want
    assert all(n.startswith("supervisor/") for n in names)
    assert not any("/.git/" in n or n.endswith((".pyc", ".db")) for n in names)
    assert release.leak_sweep(built.zip_path) == []
    with zipfile.ZipFile(built.zip_path) as zf:
        uv_toml = zf.read("supervisor/uv.toml").decode()
        handoff = zf.read("supervisor/HANDOFF.md").decode()
    assert "nexus-dev.techcombank.com.vn/repository/pypi-common-proxy/simple/" in uv_toml
    for cmd in (
        "uv sync --python 3.11 --extra databricks",
        "uv run python -m supervisor.cli preflight",
        "uv run python -m supervisor.cli serve",
        "http://127.0.0.1:8000/console/",
        "uv run python -m supervisor.cli demo",
        "cd C:\\work\\supervisor",
    ):
        assert cmd in handoff, cmd
    assert handoff.isascii()
    assert any("[SKIP] wheelhouse" in line for line in built.lines)
    assert not any("wheelhouse/" in n for n in names)


def test_unpacked_release_runs_the_demo(built: release.ReleaseReport, tmp_path: Path) -> None:
    assert built.zip_path is not None
    with zipfile.ZipFile(built.zip_path) as zf:
        zf.extractall(tmp_path / "unz")
    root = tmp_path / "unz" / "supervisor"
    data = tmp_path / "demo-data"
    res = sandbox.run(
        [sandbox.python_executable(), "-m", "supervisor.cli", "demo", "--data-dir", str(data)],
        cwd=root,
        timeout_s=300,
        env={"PYTHONPATH": str(root / "src") + os.pathsep + str(root)},
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "[OK] demo run 1: PASS" in res.stdout
    assert res.stdout.isascii()


def test_leak_sweep_fails_the_release(clone: Path, tmp_path: Path) -> None:
    (clone / ".env").write_text("LLM_API_KEY=x\n", encoding="utf-8")
    host = "dbc-" + "1234abcd-ef01.cloud.databricks.com"
    (clone / "docs" / "notes.md").write_text(f"workspace {host}\n", encoding="utf-8")
    (clone / "data" / "local").mkdir(parents=True, exist_ok=True)
    (clone / "data" / "local" / "run.db").write_text("x", encoding="utf-8")
    _git(clone, "add", "-f", ".env", "docs/notes.md", "data/local/run.db")
    _git(clone, "commit", "-q", "-m", "plant leaks")
    lines: list[str] = []
    rep = release.build_release(tmp_path / "out", repo=clone, echo=lines.append)
    assert not rep.ok and rep.zip_path is None
    assert not list((tmp_path / "out").glob("*.zip"))  # nothing written
    text = "\n".join(lines)
    assert "supervisor/.env: .env file" in text
    assert "supervisor/docs/notes.md:1: databricks workspace host" in text
    assert "supervisor/data/local/run.db" in text
    assert "[FAIL] leak sweep: " in text


def test_stale_requirements_fail(tmp_path: Path) -> None:
    base = tmp_path / "c"
    _git(tmp_path, "clone", "--quiet", "--no-local", str(REPO_ROOT), "c")
    with (base / "requirements.txt").open("a", encoding="utf-8") as fh:
        fh.write("extra-package==1.0\n")
    _git(base, "commit", "-qam", "stale reqs")
    rep = release.build_release(tmp_path / "out", repo=base)
    assert not rep.ok and any("export-reqs" in line for line in rep.lines)


def test_uv_toml_is_gitignored_and_not_in_the_tree() -> None:
    assert not (REPO_ROOT / "uv.toml").exists()
    res = sandbox.run(["git", "check-ignore", "-q", "uv.toml"], cwd=REPO_ROOT)
    assert res.returncode == 0, "uv.toml must be git-ignored"
    tracked = sandbox.run(["git", "ls-files", "uv.toml", "**/uv.toml"], cwd=REPO_ROOT)
    assert tracked.ok and tracked.stdout.strip() == ""


def test_secret_patterns_match_the_no_secrets_test() -> None:
    assert {k: v.pattern for k, v in release.SECRET_PATTERNS.items()} == {
        k: v.pattern for k, v in PATTERNS.items()
    }


@pytest.mark.parametrize(
    "name,bad",
    [
        ("supervisor/.env", True),
        ("supervisor/.env.example", False),
        ("supervisor/sub/.env.local", True),
        ("supervisor/x/__pycache__/a.cpython-311.pyc", True),
        ("supervisor/.venv/lib/x.py", True),
        ("supervisor/models/qwen.gguf", True),
        ("supervisor/data/local/demo/supervisor.db", True),
        ("supervisor/keys/evidence_ed25519.pem", True),
        ("supervisor/runs/r1/out.json", True),
        ("supervisor/src/supervisor/cli.py", False),
        ("supervisor/data/fixtures/demo_replay/judge-DEMO-2.json", False),
    ],
)
def test_sweep_paths(name: str, bad: bool) -> None:
    assert bool(release.sweep_paths([name])) is bad


def test_sweep_text_allows_placeholders_and_the_guide() -> None:
    host = "dbc-" + "1234abcd-ef01"
    assert release.sweep_text("supervisor/docs/BANK_DEPLOY_GUIDE.md", host) == []
    assert release.sweep_text("supervisor/README.md", host)
    assert release.sweep_text("supervisor/x.md", "DATABRICKS_TOKEN=FILL-ME") == []
    pat = "dapi" + "0" * 32
    assert release.sweep_text("supervisor/x.py", f"t = '{pat}'")
