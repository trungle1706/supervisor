# ruff: noqa: F811
"""WP-P2: several policy folders in POLICY_DIR and POST /gate/policy/reload."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor.config import REPO_ROOT, load_settings
from supervisor.gateway.policy import PolicyError, load_policy_dir, load_policy_dirs
from tests.console.conftest import Console, console, seeded  # noqa: F401  (fixtures)

FRAGMENT = """\
policy_version: 1
tools:
  search_policies: read_only
agents:
  kb_chatbot:
    name: Bank KB chatbot
    owner_user: kb-lead@example.invalid
    owner_team: Knowledge Team
    risk_tier: low
    initial_state: SHADOW
"""


def folder(tmp_path: Path, name: str, text: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "frag.yaml").write_text(text, encoding="utf-8")
    return d


def test_one_folder_is_exactly_as_before() -> None:
    base = REPO_ROOT / "policies"
    assert load_policy_dirs([base]).policy_hash == load_policy_dir(base).policy_hash


def test_two_folders_merge_and_the_hash_covers_both(tmp_path: Path) -> None:
    base = REPO_ROOT / "policies"
    extra = folder(tmp_path, "a1", FRAGMENT)
    merged = load_policy_dirs([base, extra])
    assert "kb_chatbot" in merged.doc.agents and "payments" in merged.doc.agents
    assert merged.policy_hash != load_policy_dir(base).policy_hash
    # order of folders does not change the merged document
    assert load_policy_dirs([extra, base]).policy_hash == merged.policy_hash


def test_later_folder_cannot_redefine_a_rule_id(tmp_path: Path) -> None:
    base = REPO_ROOT / "policies"
    one = load_policy_dir(base).doc.rules[0]
    text = FRAGMENT + (
        "rules:\n"
        f"  - id: {one.id}\n    version: 9\n    description: again\n    agent_scope: '*'\n"
        "    severity: low\n    action: log\n    risk_class: read_only\n    owner: x\n"
        "    when: {tool: {op: eq, value: search_policies}}\n"
    )
    bad = folder(tmp_path, "bad", text)
    with pytest.raises(PolicyError, match="cannot redefine a rule id"):
        load_policy_dirs([base, bad])


def test_empty_later_folder_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(PolicyError, match="no policy files"):
        load_policy_dirs([REPO_ROOT / "policies", tmp_path / "empty"])


def test_settings_split_policy_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("POLICY_DIR", f"{a}{os.pathsep}{b}")
    s = load_settings(data_dir=tmp_path / "d")
    assert s.policy_dir == a and s.policy_dir_extra == (b,)
    assert s.policy_dirs == (a, b)
    monkeypatch.setenv("POLICY_DIR", f"{a}{os.pathsep}{tmp_path / 'missing'}")
    with pytest.raises(Exception, match="not a folder"):
        load_settings(data_dir=tmp_path / "d")
    monkeypatch.setenv("POLICY_DIR", str(a))  # one folder as before
    s1 = load_settings(data_dir=tmp_path / "d")
    assert s1.policy_dirs == (a,) and s1.policy_dir_extra == ()


# --------------------------------------------------------------------------- reload

ADMIN = "admin.chi"


@pytest.fixture
def reload_env(console: Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setattr(console.ctx.settings, "agents_api_enabled", True)
    base = tmp_path / "base"
    shutil.copytree(REPO_ROOT / "policies", base)
    gw = console.runtime.gateway
    gw.policy_dirs = (base,)
    records: list[tuple[str, dict[str, Any]]] = []
    chain = console.runtime.chain
    orig = chain.record

    def spy(rtype: str, ref: str, payload: Any, **kw: Any) -> str:
        records.append((rtype, dict(payload)))
        return str(orig(rtype, ref, payload, **kw))

    monkeypatch.setattr(chain, "record", spy)
    yield console, base, records


def post(c: Console, user: str = ADMIN) -> Any:
    return c.client.post("/gate/policy/reload", headers={"X-Dev-User": user})


def test_reload_picks_up_a_new_folder_and_records_the_hash(reload_env: Any, tmp_path: Path) -> None:
    c, base, records = reload_env
    gw = c.runtime.gateway
    r = post(c)
    assert r.status_code == 200 and r.json()["changed"] is False
    old = gw.policy.current().policy_hash
    extra = folder(tmp_path, "a1", FRAGMENT)
    gw.policy_dirs = (base, extra)
    r = post(c)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True and body["old_policy_hash"] == old
    assert gw.policy.current().policy_hash == body["policy_hash"] != old
    assert "kb_chatbot" in gw.policy.current().doc.agents
    rec = [p for t, p in records if t == "policy_reload"][-1]
    assert rec["new_policy_hash"] == body["policy_hash"] and rec["folders"] == 2
    rows = [
        x
        for x in c.runtime.adapters.state.query("console_action", {})
        if x["permission"] == "policy.reload"
    ]
    assert len(rows) >= 4


def test_reload_error_keeps_the_old_policy(reload_env: Any, tmp_path: Path) -> None:
    c, base, _ = reload_env
    gw = c.runtime.gateway
    before = gw.policy.current().policy_hash
    gw.policy_dirs = (base, folder(tmp_path, "broken", "policy_version: [not valid"))
    r = post(c)
    assert r.status_code == 400 and "old policy stays" in r.json()["error"]
    assert gw.policy.current().policy_hash == before
    gw.policy_dirs = (base, folder(tmp_path, "unknown", "policy_version: 1\nbogus: 1\n"))
    assert post(c).status_code == 400
    assert gw.policy.current().policy_hash == before


def test_reload_is_admin_only_and_flagged(reload_env: Any) -> None:
    c, _, _ = reload_env
    assert post(c, "reviewer.an").status_code == 403
    c.ctx.settings.agents_api_enabled = False
    r = post(c)
    assert r.status_code == 400 and "AGENTS_API_ENABLED" in r.json()["error"]
