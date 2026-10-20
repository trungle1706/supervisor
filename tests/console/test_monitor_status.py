"""WP1b-B: the Metrics page shows each monitor status, not_applicable with its reason."""

from __future__ import annotations

import datetime as dt

from .conftest import Console


def test_metrics_page_shows_not_applicable_with_reason(console: Console) -> None:
    ctx = console.ctx
    ctx.state.insert(
        "oversight_metric",
        {
            "metric_date": dt.date(2026, 10, 10),
            "agent_id": "lookup_agent",
            "computed_at": ctx.clock.now(),
            "monitor_status": {
                "quality": {
                    "status": "not_applicable",
                    "code": "no_binding",
                    "reason": "no reply tool bound and none derivable",
                },
                "drift": {"status": "no_data", "code": "collecting_baseline", "reason": "w"},
                "fairness": {"status": "ok", "n": 120},
            },
        },
    )
    r = console.get("/console/metrics")
    assert r.status_code == 200
    assert 'id="monitor-status"' in r.text and 'data-agent="lookup_agent"' in r.text
    assert "not applicable" in r.text and "no reply tool bound and none derivable" in r.text
    assert "n=120" in r.text
    assert "monitor_status" not in r.text.split('id="monitor-status"')[1].split("</section>")[1]
