"""WP-P5: the Systems page renders in the degraded console (SP without grant)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.console.test_sql_forward_degraded import HDR, TOKEN, degraded  # noqa: F401


def test_systems_page_renders_degraded(degraded: TestClient, mounted: None) -> None:  # noqa: F811
    r = degraded.get("/console/systems", headers=HDR)
    assert r.status_code == 200, r.text[:300]
    assert TOKEN not in r.text
