"""WP8: metrics panel (tolerant of new columns, integer sparklines), inbox, webhook stub."""

from __future__ import annotations

import datetime as dt
import re
import socket
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.adapters.notify import (
    InboxNotifier,
    NoticeError,
    WebhookNotifierStub,
    build_notifier,
)
from supervisor.console import views

from .conftest import Console, add_gate_block


def test_sparkline_is_integer_svg_scaled_to_range() -> None:
    svg = str(views.sparkline([views.to_int(x) for x in (0.10, 0.25, None, 0.40)]))
    pts = re.findall(r'points="([^"]+)"', svg)[0].split()
    assert len(pts) == 3 and all(re.fullmatch(r"\d+,\d+", p) for p in pts)
    ys = [int(p.split(",")[1]) for p in pts]
    assert ys[0] == max(ys) and ys[-1] == min(ys)  # low value at the bottom
    assert "trend 1000 to 4000" in svg
    assert str(views.sparkline([None, None])) == ""
    flat = str(views.sparkline([5, 5]))
    assert "1,12" in flat


def test_metric_columns_tolerate_extra_columns() -> None:
    rows = [
        {"metric_date": dt.date(2026, 10, 1), "agent_id": "a", "coverage": 0.5, "computed_at": 1},
        {"metric_date": dt.date(2026, 10, 2), "agent_id": "a", "new_wp7_metric_bp": 1200},
    ]
    assert views.metric_columns(rows) == ["coverage", "new_wp7_metric_bp"]
    assert views.metric_cell("coverage", 0.5) == "50.0%"
    assert views.metric_cell("ttd_ms", 120) == "120 ms"
    assert views.metric_cell("chain_ok", True) == "OK"


def test_countdown_colours() -> None:
    now = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)
    h = dt.timedelta(hours=1)
    assert views.countdown(now + 20 * h, now)["cls"] == ""
    assert views.countdown(now + 10 * h, now)["cls"] == "c50"
    assert views.countdown(now + 2 * h, now)["cls"] == "c80"
    late = views.countdown(now - 3 * h, now)
    assert late["cls"] == "c100" and late["overdue"] and late["text"] == "03:00"


def test_metrics_page_with_rows(console: Console) -> None:
    state, clock = console.ctx.state, console.ctx.clock
    for i, cov in enumerate((0.6, 0.7, 0.9)):
        state.insert(
            "oversight_metric",
            {
                "metric_date": dt.date(2026, 10, 10 + i),
                "agent_id": "payments",
                "coverage": cov,
                "ttd_ms": 100 + i,
                "tth_s": 60,
                "catch_rate": 0.95 if i == 2 else None,
                "false_alarm_rate": 0.03 if i == 2 else None,
                "chain_ok": True,
                "computed_at": clock.now(),
            },
        )
    r = console.get("/console/metrics")
    assert r.status_code == 200
    assert "90.0%" in r.text and "102 ms" in r.text and '<svg class="spark"' in r.text
    assert "catch_rate" in r.text and "95.0%" in r.text


def test_inbox_mark_read(console: Console) -> None:
    add_gate_block(console.runtime.adapters)
    console.post("/console/intake/run")
    notice = console.ctx.inbox.list(status="unread")[0]
    r = console.post(
        f"/console/inbox/{notice['notice_id']}/read", {"row_version": notice["row_version"]}
    )
    assert r.status_code == 200 and 'data-status="read"' in r.text
    r = console.post(
        f"/console/inbox/{notice['notice_id']}/read", {"row_version": notice["row_version"]}
    )
    assert r.status_code == 400 and "only unread" in r.text


def test_webhook_stub_off_by_default_and_never_sends(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifier, inbox = build_notifier(adapters.settings, adapters.state, adapters.clock)
    assert not any(isinstance(t, WebhookNotifierStub) for t in notifier.targets)
    notifier.notify("reviewers", "s", "b")
    assert [n["channel"] for n in inbox.list()] == ["reviewers"]

    def refuse(*_a: Any, **_k: Any) -> None:
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "create_connection", refuse)
    on = adapters.settings.model_copy(
        update={"notify_webhook_enabled": True, "notify_webhook_url": "FILL-ME"}
    )
    notifier, inbox = build_notifier(on, adapters.state, adapters.clock)
    notifier.notify("approvers", "s2", "b2")
    queued = inbox.list(status="queued")
    assert [n["channel"] for n in queued] == ["webhook:approvers"]


def test_inbox_errors(adapters: Adapters) -> None:
    inbox = InboxNotifier(adapters.state, adapters.clock)
    with pytest.raises(NoticeError):
        inbox.mark_read("nope", "reviewer.an", 1)
