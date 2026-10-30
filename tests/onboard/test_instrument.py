"""Instrument: branch in a temp clone (never main, never merged), codemod, artefacts."""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from supervisor import sandbox
from supervisor.core.errors import SandboxError
from supervisor.onboard.discover import Discovery
from supervisor.onboard.instrument import (
    MARKER,
    InstrumentError,
    apply_codemod,
    branch_name,
    instrument,
    render_pr_description,
    validate_policy,
)
from supervisor.onboard.models import AgentProfile
from supervisor.onboard.plan import plan
from tests.onboard.conftest import AGENTS_DIR


def _g(args: list[str], cwd: Path) -> str:
    res = sandbox.git(args, cwd=cwd, identity=("Test", "test@example.invalid"))
    assert res.ok, res.stderr
    return res.stdout.strip()


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    """A small git repo (main) with the payments agent copied into agents/payments."""
    repo = tmp_path / "src_repo"
    target = repo / "agents" / "payments"
    shutil.copytree(AGENTS_DIR / "payments", target, ignore=shutil.ignore_patterns("__pycache__"))
    _g(["init", "--quiet", "-b", "main", str(repo)], tmp_path)
    _g(["add", "--all"], repo)
    _g(["commit", "--quiet", "-m", "agent"], repo)
    return repo


def _run(
    target: Path,
    work: Path,
    discoveries: dict[str, Discovery],
    profiles: dict[str, AgentProfile],
):  # type: ignore[no-untyped-def]
    inv = discoveries["payments"].inventory
    prof = profiles["payments"]
    mp, pb = plan(inv, prof)
    return instrument(target, work, inv, prof, mp, pb), (inv, prof, mp)


def test_branch_in_clone_never_touches_main(
    source_repo: Path,
    tmp_path: Path,
    discoveries: dict[str, Discovery],
    profiles: dict[str, AgentProfile],
) -> None:
    main_before = _g(["rev-parse", "main"], source_repo)
    branches_before = _g(["branch", "--list"], source_repo)
    status_before = _g(["status", "--porcelain"], source_repo)
    (res, texts), (inv, prof, mp) = _run(
        source_repo / "agents" / "payments", tmp_path / "work", discoveries, profiles
    )
    # the source repository is untouched
    assert _g(["rev-parse", "main"], source_repo) == main_before
    assert _g(["branch", "--list"], source_repo) == branches_before
    assert _g(["status", "--porcelain"], source_repo) == status_before
    # the clone has the branch, one commit ahead of main, main unchanged
    clone = Path(res.work_repo)
    assert res.mode == "clone" and clone != source_repo
    assert res.branch == branch_name("payments") == "supervisor/onboard-payments"
    assert res.base_ref == "main" and res.base_sha == main_before
    assert _g(["rev-parse", "main"], clone) == main_before
    assert _g(["rev-parse", "--abbrev-ref", "HEAD"], clone) == res.branch
    log = _g(["log", "--format=%H", "main..HEAD"], clone).split()
    assert log == [res.commit_sha]
    assert res.merged is False
    files = set(_g(["show", "--name-only", "--format=", "HEAD"], clone).split())
    assert (
        files
        == set(res.files_changed)
        == {
            "agents/payments/agent.py",
            "agents/payments/supervisor_onboard.py",
            "agents/payments/supervisor_onboarding/policy.yaml",
            "agents/payments/supervisor_onboarding/dashboard.json",
            "agents/payments/supervisor_onboarding/alert_routes.yaml",
        }
    )
    # committed artefacts are valid
    policy_text = (clone / "agents/payments/supervisor_onboarding/policy.yaml").read_text(
        encoding="utf-8"
    )
    assert validate_policy(policy_text).policy_hash == res.policy_hash
    assert json.loads((clone / "agents/payments/supervisor_onboarding/dashboard.json").read_text())
    agent_py = (clone / "agents/payments/agent.py").read_text(encoding="utf-8")
    ast.parse(agent_py)
    assert MARKER in agent_py and "supervisor_onboard.default_gate()" in agent_py
    assert res.codemod_applied
    ast.parse(texts["supervisor_onboard.py"])
    # the PR description names the branch and the reviewer duties
    pr = render_pr_description(inv, prof, mp, res, {"decision": "GO"})
    assert res.branch in pr and "Never auto-merged" in pr and "FILL-ME-approver" in pr
    assert "without human inspection, approval or control before execution" in pr


def test_merge_and_push_are_refused_in_the_clone(
    source_repo: Path,
    tmp_path: Path,
    discoveries: dict[str, Discovery],
    profiles: dict[str, AgentProfile],
) -> None:
    (res, _), _ = _run(source_repo / "agents" / "payments", tmp_path / "w", discoveries, profiles)
    for args in (["merge", res.branch], ["push", "origin", res.branch], ["rebase", "main"]):
        with pytest.raises(SandboxError, match="not allowed"):
            sandbox.git(args, cwd=Path(res.work_repo))


def test_copy_mode_when_target_is_not_in_git(
    tmp_path: Path, discoveries: dict[str, Discovery], profiles: dict[str, AgentProfile]
) -> None:
    plain = tmp_path / "plain" / "payments"
    shutil.copytree(AGENTS_DIR / "payments", plain, ignore=shutil.ignore_patterns("__pycache__"))
    (res, _), _ = _run(plain, tmp_path / "w2", discoveries, profiles)
    assert res.mode == "copy" and res.base_ref == "main"
    assert not (plain / ".git").exists()
    assert not (plain / "supervisor_onboarding").exists()  # the original folder is unchanged
    assert _g(["rev-parse", "--abbrev-ref", "HEAD"], Path(res.work_repo)) == res.branch


def test_codemod_is_idempotent_and_safe() -> None:
    src = (
        '"""Doc."""\nimport os\n\n\n'
        "def build_agent(chat, world, *, gate=None, tracer_provider=None):\n"
        '    """Build."""\n    return (gate, tracer_provider)\n'
    )
    new, applied, _ = apply_codemod(src, import_line="import supervisor_onboard")
    assert applied
    tree = ast.parse(new)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    assert ast.get_docstring(fn) == "Build."
    assert new.index("import supervisor_onboard") < new.index("def build_agent")
    again, applied2, note = apply_codemod(new, import_line="import supervisor_onboard")
    assert again == new and not applied2 and "already" in note
    none, applied3, note3 = apply_codemod("def f(x):\n    return x\n", import_line="import m")
    assert not applied3 and "by hand" in note3


def test_copy_mode_skips_credential_files(
    tmp_path: Path, discoveries: dict[str, Discovery], profiles: dict[str, AgentProfile]
) -> None:
    plain = tmp_path / "plain2" / "payments"
    shutil.copytree(AGENTS_DIR / "payments", plain, ignore=shutil.ignore_patterns("__pycache__"))
    (plain / ".env").write_text("X=1\n", encoding="utf-8")
    (plain / "deploy.pem").write_text("not a real key\n", encoding="utf-8")
    (res, _), _ = _run(plain, tmp_path / "w3", discoveries, profiles)
    tracked = _g(["ls-files"], Path(res.work_repo)).split()
    assert ".env" not in tracked and "deploy.pem" not in tracked
    assert any("credential-like" in w for w in res.warnings)


def test_work_dir_inside_target_is_refused(
    source_repo: Path, discoveries: dict[str, Discovery], profiles: dict[str, AgentProfile]
) -> None:
    target = source_repo / "agents" / "payments"
    with pytest.raises(InstrumentError, match="inside the target"):
        _run(target, target, discoveries, profiles)
    with pytest.raises(InstrumentError, match="inside the target"):
        _run(target, target / "sub", discoveries, profiles)
    assert (target / "agent.py").is_file()


def test_dirty_target_is_reported(
    source_repo: Path,
    tmp_path: Path,
    discoveries: dict[str, Discovery],
    profiles: dict[str, AgentProfile],
) -> None:
    target = source_repo / "agents" / "payments"
    (target / "notes.txt").write_text("uncommitted\n", encoding="utf-8")
    (res, _), _ = _run(target, tmp_path / "w4", discoveries, profiles)
    assert any("uncommitted" in w for w in res.warnings)


def test_detached_checkout_base_ref_is_the_commit(tmp_path: Path) -> None:
    # CI checks out a tag (detached HEAD): the base must name the commit, not "HEAD", because
    # HEAD in the work clone moves to the onboarding branch.
    from supervisor.onboard.instrument import prepare_work_repo

    def g(*args: str) -> str:
        res = sandbox.git(list(args), cwd=src, identity=("t", "t@example.invalid"))
        assert res.ok, res.stderr
        return res.stdout.strip()

    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('hi')\n", encoding="utf-8")
    g("init", "-q")
    g("add", "--all")
    g("commit", "-q", "-m", "c1")
    head = g("rev-parse", "HEAD")
    (src / "app.py").write_text("print('later')\n", encoding="utf-8")
    g("add", "--all")
    g("commit", "-q", "-m", "c2")
    g("checkout", "-q", head)  # detached on c1; no branch points at it (like a tag checkout)
    assert g("rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    mode, repo, _target, base, _warnings = prepare_work_repo(src, tmp_path / "work")
    assert mode == "clone"
    assert base == head
    res = sandbox.git(["rev-parse", base], cwd=repo)
    assert res.ok and res.stdout.strip() == head
