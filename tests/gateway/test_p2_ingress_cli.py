"""WP-P2: ``ingress_auth issue`` loads only the settings it needs and honours INGRESS_KEYS_FILE."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.config import REPO_ROOT, load_settings
from supervisor.core.errors import ConfigError
from supervisor.gateway import ingress_auth


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("SUPERVISOR_ENV_FILE", raising=False)
    monkeypatch.setenv("JUDGE_T1_BASE_URL", "http://judge.example.invalid:9/v1")  # not loopback
    keys = tmp_path / "outside" / "keys.yaml"
    keys.parent.mkdir()
    monkeypatch.setenv("INGRESS_KEYS_FILE", str(keys))
    return keys


def test_the_full_settings_do_fail_on_this_environment(env: Path) -> None:
    with pytest.raises(ConfigError, match="loopback"):
        load_settings()


def test_issue_and_list_ignore_unrelated_settings_and_write_outside_the_repo(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_keys = REPO_ROOT / "config" / "agent_keys.yaml"
    before = repo_keys.read_bytes() if repo_keys.exists() else None
    assert ingress_auth.main(["issue", "cand_a1"]) == 0
    out = capsys.readouterr().out
    assert "[OK] key issued for cand_a1" in out and str(env) in out  # the full path is printed
    assert env.is_file() and "cand_a1" in env.read_text(encoding="utf-8")
    assert (repo_keys.read_bytes() if repo_keys.exists() else None) == before
    assert ingress_auth.main(["list"]) == 0
    assert str(env) in capsys.readouterr().out
    assert ingress_auth.main(["issue", "cand_a1"]) == 1  # already has keys
    assert ingress_auth.main(["rotate", "cand_a1"]) == 0


def test_default_path_is_still_the_repo_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INGRESS_KEYS_FILE", raising=False)
    monkeypatch.delenv("SUPERVISOR_ENV_FILE", raising=False)
    s = ingress_auth.key_cli_settings()
    assert (
        s.ingress_keys_file in (REPO_ROOT / "config" / "agent_keys.yaml",)
        or s.ingress_keys_file.is_absolute()
    )
