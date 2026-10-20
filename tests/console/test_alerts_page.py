"""WP-UX2: the Alerts page - tiles, filter bar, sort, pages, row drawer, Metrics summary tile.

The acknowledge action itself (RBAC, two console_action rows, alert_ack record) is covered by
``test_alerts_panel.py`` and ``test_audit_two_rows.py``."""

from __future__ import annotations

import re
import uuid
from typing import Any

from .conftest import Console
from .test_alerts_panel import ALERT_ID, _row

HX = {"HX-Request": "true"}


def _ids(html: str) -> list[str]:
    return re.findall(r'data-alert="([0-9a-f]{32})"', html)


def _seed(console: Console) -> dict[str, dict[str, Any]]:
    a = _row(console, "a" * 32, severity="critical", agent_id="payments", rule_id="AL-A")
    b = _row(console, "b" * 32, severity="low", agent_id="credit_prequal", rule_id="AL-B")
    c = _row(
        console, "c" * 32, status="acknowledged", acknowledged_by="operator.khanh", rule_id="AL-C"
    )
    d = _row(console, "d" * 32, status="closed", rule_id="AL-D")
    return {"a": a, "b": b, "c": c, "d": d}


def test_default_view_is_active_alerts_and_tiles_count_statuses(console: Console) -> None:
    _seed(console)
    r = console.get("/console/alerts")
    assert r.status_code == 200
    assert sorted(_ids(r.text)) == ["a" * 32, "b" * 32, "c" * 32]  # closed hidden by default
    assert 'class="tiles"' in r.text and "Active" in r.text
    closed = console.get("/console/alerts/rows?status=closed", headers=HX)
    assert _ids(closed.text) == ["d" * 32] and "<html" not in closed.text
    assert len(_ids(console.get("/console/alerts/rows?status=all").text)) == 4


def test_filters_sort_and_pages(console: Console) -> None:
    _seed(console)
    sev = console.get("/console/alerts/rows?severity=critical").text
    assert _ids(sev) == ["a" * 32]
    agent = console.get("/console/alerts/rows?agent=credit_prequal").text
    assert _ids(agent) == ["b" * 32]
    rule = console.get("/console/alerts/rows?rule=AL-C").text
    assert _ids(rule) == ["c" * 32]
    asc = _ids(console.get("/console/alerts/rows?sort=severity&dir=asc").text)
    desc = _ids(console.get("/console/alerts/rows?sort=severity&dir=desc").text)
    assert asc[0] == "b" * 32 and desc[0] == "a" * 32
    assert 'aria-sort="ascending"' in console.get("/console/alerts/rows?sort=rule_id&dir=asc").text
    odd = console.get("/console/alerts/rows?sort=__class__&dir=sideways")
    assert odd.status_code == 200  # unknown column and direction fall back
    for _ in range(25):  # a second page
        _row(console, uuid.uuid4().hex)
    p2 = console.get("/console/alerts/rows?page=2")
    assert p2.status_code == 200 and "page 2 of" in p2.text


def test_bad_input_is_400(console: Console) -> None:
    for q in (
        "status=nope",
        "severity=extreme",
        "agent=bad%24id",
        "rule=%3Cb%3E",
        "page=abc",
        "page=99",
        "page=0",
    ):
        r = console.get(f"/console/alerts/rows?{q}", headers=HX)
        assert r.status_code == 400, (q, r.status_code)
        r = console.get(f"/console/alerts?{q}")
        assert r.status_code == 400, (q, r.status_code)
    assert console.get("/console/alerts/nope/drawer", headers=HX).status_code == 400
    assert console.get("/console/alerts/bad%20id/drawer", headers=HX).status_code == 400
    assert console.get("/console/alerts?drawer=nope").status_code == 400


def test_drawer_and_no_js_fallback(console: Console) -> None:
    _seed(console)
    d = console.get(f"/console/alerts/{'a' * 32}/drawer", headers=HX)
    assert d.status_code == 200 and "<html" not in d.text
    assert 'id="drawer-title"' in d.text and "AL-A" in d.text and 'id="drawer-json"' in d.text
    assert f"/console/alerts/{'a' * 32}/ack" in d.text  # the same audited route
    ack = console.get(f"/console/alerts/{'c' * 32}/drawer", headers=HX)
    assert "/ack" not in ack.text and "operator.khanh" in ack.text
    full = console.get(f"/console/alerts?drawer={'a' * 32}")
    tail = full.text.split('id="drawer"', 1)[1]
    assert "AL-A" in tail and "hidden>" not in tail.split(">", 1)[0] + ">"


def test_ack_answer_keeps_filters_and_counts(console: Console) -> None:
    row = _row(console)
    r = console.post(
        f"/console/alerts/{ALERT_ID}/ack?severity=high&status=",
        {"row_version": str(row["row_version"])},
        user="operator.khanh",
    )
    assert r.status_code == 200 and "0 open" in r.text and "operator.khanh" in r.text
    assert 'id="alert-counts"' in r.text and "<html" not in r.text


def test_viewer_cannot_ack_from_the_page(console: Console) -> None:
    row = _row(console)
    r = console.post(
        f"/console/alerts/{ALERT_ID}/ack", {"row_version": str(row["row_version"])}, user="viewer.hoa"
    )
    assert r.status_code == 403
    assert len([x for x in console.ctx.tables.query("console_action") if x["outcome"] == "denied"]) == 1


def test_metrics_tab_keeps_a_summary_tile_that_links_here(console: Console) -> None:
    _seed(console)
    r = console.get("/console/analytics?tab=metrics")
    tile = r.text.split('id="alerts"', 1)[1].split("</a>", 1)[0]
    assert 'href="/console/alerts?lang=en"' in r.text and "2" in tile and "open" in tile
    assert "AL-A" not in r.text  # the rows are not on Metrics any more


def test_vietnamese_and_empty_state(console: Console) -> None:
    r = console.get("/console/alerts?lang=vi")
    assert r.status_code == 200 and "Cảnh báo" in r.text and "Không có cảnh báo" in r.text
