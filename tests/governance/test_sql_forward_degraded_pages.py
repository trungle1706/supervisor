"""WP-P5: the degraded console (SP without grant) renders Systems, and refuses every write."""

from __future__ import annotations

from fastapi.testclient import TestClient

from supervisor.console import context as cc
from supervisor.console.degraded_guard import DegradedWriteGuard
from tests.console.test_sql_forward_degraded import HDR, TOKEN, degraded  # noqa: F401

HX = {"HX-Request": "true"}


def test_systems_page_renders_degraded(degraded: TestClient, mounted: None) -> None:  # noqa: F811
    r = degraded.get("/console/systems", headers=HDR)
    assert r.status_code == 200, r.text[:300]
    assert TOKEN not in r.text


def test_writes_are_refused_while_degraded(degraded: TestClient, mounted: None) -> None:  # noqa: F811
    from supervisor.app import app

    guarded = TestClient(DegradedWriteGuard(app), raise_server_exceptions=False)
    assert guarded.get("/console/systems", headers=HDR).status_code == 200
    ctx = cc.peek_context()
    assert ctx is not None and ctx.degraded_until
    before = len(ctx.state.query("ai_system"))
    form = {"name": "X", "owner_team": "t", "purpose": "p" * 30, "system_type": "assistant"}
    for url in ("/console/systems", "/console/incidents/inc_1/action", "/v1/systems"):
        r = guarded.post(url, data=form, headers={**HDR, **HX})
        assert r.status_code == 400, (url, r.status_code)
        assert "writes are disabled" in r.text
    assert len(ctx.state.query("ai_system")) == before
    assert guarded.get("/console/", headers=HDR).status_code == 200
