"""WP41 (D27): the Agent page Tools tab answers 200 with an empty state and a hint for an agent
that has a registry row but no policy (onboarding) record; a policy in the served POLICY_DIR is
read, not only the repo folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import Console

HX = {"HX-Request": "true"}
GHOST = "gate-only-agent"


def _register(console: Console, agent_id: str) -> None:
    console.ctx.state.insert(
        "agent",
        {
            "agent_id": agent_id,
            "name": agent_id,
            "owner_team": "t",
            "owner_user": "u",
            "risk_tier": "high",
            "host_type": "python_inprocess",
            "plug_point": "gate_hook",
            "model_family": "qwen",
            "status": "active",
            "gate_state": "RUNNING",
            "created_at": console.ctx.clock.now(),
        },
    )


@pytest.fixture
def tools_on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "console_tools_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "tool_analytics_enabled", True)
    return console


def test_an_agent_with_no_policy_record_gets_200_and_a_hint(tools_on: Console) -> None:
    _register(tools_on, GHOST)
    for url, headers in (
        (f"/console/agents/{GHOST}/tab/tools", HX),
        (f"/console/agents/{GHOST}?tab=tools", {}),
    ):
        r = tools_on.get(url, headers=headers)
        assert r.status_code == 200, (url, r.text[:200])
        assert 'data-unknown-agent="1"' in r.text and "no record in the policy" in r.text
        assert 'class="tools-agent"' not in r.text  # no fake per-tool table


def test_the_hint_is_translated(tools_on: Console) -> None:
    _register(tools_on, GHOST)
    r = tools_on.get(f"/console/agents/{GHOST}?tab=tools&lang=vi")
    assert r.status_code == 200 and "chưa có trong chính sách" in r.text


def test_a_policy_agent_still_shows_its_tools(tools_on: Console) -> None:
    r = tools_on.get("/console/agents/payments/tab/tools", headers=HX)
    assert r.status_code == 200 and 'data-tools="1"' in r.text
    assert 'data-unknown-agent="1"' not in r.text


def test_the_analytics_tools_tab_still_refuses_an_unknown_agent(tools_on: Console) -> None:
    r = tools_on.get("/console/analytics?tab=tools&agent=" + GHOST)
    assert r.status_code == 400 and GHOST in r.text


def test_the_served_policy_dir_is_read(tmp_path: Path) -> None:
    """tools_suggest reads settings.policy_dir when no folder is passed (D13 residual): an agent
    that is only in the served folder is known, and unknown for the repo folder."""
    import datetime as dt
    import shutil

    import yaml

    from supervisor.adapters.factory import build_adapters
    from supervisor.analytics import tools, tools_suggest
    from supervisor.config import REPO_ROOT, load_settings
    from supervisor.jobs import bootstrap_schema

    pol = tmp_path / "pol"
    shutil.copytree(REPO_ROOT / "policies", pol)
    doc = yaml.safe_load((pol / "baseline.yaml").read_text(encoding="utf-8"))
    doc["agents"][GHOST] = {"name": GHOST, "owner_user": "u", "owner_team": "t"}
    (pol / "baseline.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    served = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "d", policy_dir=pol, tool_analytics_enabled=True
    )
    plain = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "d", tool_analytics_enabled=True
    )
    a = build_adapters(served)
    try:
        bootstrap_schema.run(served, a)
        day = dt.date(2026, 10, 21)
        out = tools_suggest.build_all(a.state, served, as_of=day, agent_id=GHOST, with_diff=False)
        assert [x["agent_id"] for x in out] == [GHOST]
        with pytest.raises(tools.AnalyticsError, match="unknown agent"):
            tools_suggest.build_all(a.state, plain, as_of=day, agent_id=GHOST, with_diff=False)
    finally:
        a.close()
