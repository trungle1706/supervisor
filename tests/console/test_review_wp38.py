"""WP38 review (Opus): console checks for the observe period and the Add route."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from supervisor.console import nav

from .conftest import Console


@pytest.fixture
def ux(console: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Console:
    for flag in nav.PAGES.values():
        monkeypatch.setattr(console.ctx.settings, flag, True)
    monkeypatch.setattr(console.ctx.settings, "collectors_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "ingress_keys_file", tmp_path / "agent_keys.yaml")
    return console


def test_decision_drawer_shows_the_observed_decision(ux: Console) -> None:
    html = ux.get("/console/decisions/rows?action=pause").text
    eid = re.findall(r'data-row="([0-9a-f]+)"', html)[0]
    before = ux.get(f"/console/decisions/{eid}/drawer?tab=details").text
    assert "Observed decision" not in before  # an enforced decision: no new line
    (ev,) = ux.ctx.tables.query("agent_event", {"event_id": eid})
    ux.ctx.tables.append(
        "verdict",
        [
            {
                "verdict_id": uuid.uuid4().hex,
                "ts": ev["ts"],
                "trace_id": ev["trace_id"],
                "event_id": eid,
                "agent_id": ev["agent_id"],
                "tier": 0,
                "checker_id": "tier0a",
                "model_id": None,
                "model_family": None,
                "is_mock": False,
                "advisory": False,
                "score": None,
                "label": "observe_would_block",
                "action": "log",
                "rule_id": "PAY-06",
                "rationale_masked": "test",
                "latency_ms": 0,
                "policy_hash": "x",
            }
        ],
    )
    d = ux.get(f"/console/decisions/{eid}/drawer?tab=details").text
    assert "Observed decision" in d and "block PAY-06" in d


def test_add_route_refuses_get_and_cross_site_posts(ux: Console) -> None:
    url = "/console/integrations/customer_service/connect"
    assert ux.get(url, user="admin.chi").status_code in (404, 405)
    r = ux.post(url, {"template": "rest"}, "admin.chi", htmx=False)
    assert r.status_code == 400
    assert not ux.ctx.settings.ingress_keys_file.exists()  # nothing was issued
