"""WP21: Alerts list (WP-UX2: its own page, moved out of Metrics) and the audited,
operator-only acknowledge action."""

from __future__ import annotations

from typing import Any

from .conftest import Console

ALERT_ID = "c" * 32


def _row(console: Console, alert_id: str = ALERT_ID, **kw: Any) -> dict[str, Any]:
    now = console.ctx.clock.now()
    row = {
        "alert_id": alert_id, "ts": now, "dedupe_key": f"AL-BLOCK-BURST:{alert_id[:4]}",
        "rule_id": "AL-BLOCK-BURST", "rule_hash": "h" * 64, "severity": "high", "status": "open",
        "title": "Repeated gate blocks for one agent", "agent_id": "payments",
        "group_value": "payments", "window_s": 600, "window_count": 5, "threshold": 5,
        "first_ts": now, "last_ts": now, "suppressed_count": 2, "case_id": None,
        "chain_lane": "agent:payments", "chain_seq": 4, "entry_hash": "e" * 64, "refs": ["x"],
        "routes": ["inbox"], "route_status": {"inbox": "sent"},
    }  # fmt: skip
    row.update(kw)
    return console.ctx.state.insert("alert", row)


def _actions(console: Console) -> list[dict[str, Any]]:
    rows = console.ctx.tables.query("console_action", order_by=("ts",))
    return [r for r in rows if r["permission"] == "alert.ack"]


def test_alerts_page_shows_alert_counts_and_rows(console: Console) -> None:
    r = console.get("/console/alerts")  # WP-UX2: moved from /console/metrics
    assert r.status_code == 200 and 'id="alerts"' in r.text and "No alerts." in r.text
    _row(console)
    _row(console, "d" * 32, status="acknowledged", acknowledged_by="operator.khanh")
    r = console.get("/console/alerts")
    assert r.status_code == 200
    assert "1 open" in r.text and "1 acknowledged" in r.text
    # what the analyst needs on one row: rule, severity, agent, window counts, repeats, chain
    for needle in (
        "AL-BLOCK-BURST",
        "payments",
        "5/5 in 600 s",
        "agent:payments:4",
        "eeeeeeeeeeee",
    ):
        assert needle in r.text, needle
    assert f"/console/alerts/{ALERT_ID}/ack" in r.text
    assert f"/console/alerts/{'d' * 32}/ack" not in r.text  # no button once acknowledged
    assert console.get("/console/alerts?lang=vi").status_code == 200


def test_operator_acknowledges_and_it_is_audited(console: Console) -> None:
    row = _row(console)
    r = console.post(
        f"/console/alerts/{ALERT_ID}/ack", {"row_version": str(row["row_version"])},
        user="operator.khanh",
    )  # fmt: skip
    assert r.status_code == 200 and "0 open" in r.text and "operator.khanh" in r.text
    now = console.ctx.state.get("alert", {"alert_id": ALERT_ID})
    assert now is not None and now["status"] == "acknowledged"
    assert now["acknowledged_by"] == "operator.khanh" and now["acknowledged_at"] is not None
    rows = _actions(console)
    assert [x["outcome"] for x in rows] == ["attempted", "ok"]
    ok = rows[-1]
    assert ok["actor"] == "operator.khanh" and ok["target_kind"] == "alert"
    assert ok["target_id"] == ALERT_ID and ok["before_hash"] != ok["after_hash"]
    assert ok["request_id"]
    # the acknowledge is also on the evidence chain
    kinds = [e["record_type"] for e in console.ctx.tables.query("chain_entry")]
    assert "alert_ack" in kinds


def test_other_roles_are_refused_and_the_alert_is_untouched(console: Console) -> None:
    row = _row(console)
    for user in ("reviewer.an", "auditor.dung", "viewer.hoa", "approver.em"):
        r = console.post(
            f"/console/alerts/{ALERT_ID}/ack", {"row_version": str(row["row_version"])}, user=user
        )
        assert r.status_code == 403, (user, r.status_code)
    assert console.ctx.state.get("alert", {"alert_id": ALERT_ID})["status"] == "open"
    denied = [x for x in _actions(console) if x["outcome"] == "denied"]
    assert len(denied) == 4 and all(x["before_hash"] == x["after_hash"] for x in denied)
    # an admin may
    r = console.post(
        f"/console/alerts/{ALERT_ID}/ack", {"row_version": str(row["row_version"])},
        user="admin.chi",
    )  # fmt: skip
    assert r.status_code == 200


def test_user_errors_are_4xx_never_500(console: Console) -> None:
    row = _row(console)
    v = {"row_version": str(row["row_version"])}
    assert console.post("/console/alerts/nope/ack", v, user="operator.khanh").status_code == 400
    assert (
        console.post(f"/console/alerts/{ALERT_ID}/ack", {}, user="operator.khanh").status_code
        == 400
    )
    assert console.post("/console/alerts/bad id!/ack", v, user="operator.khanh").status_code == 400
    ok = console.post(f"/console/alerts/{ALERT_ID}/ack", v, user="operator.khanh")
    assert ok.status_code == 200
    again = console.post(f"/console/alerts/{ALERT_ID}/ack", v, user="operator.khanh")
    assert again.status_code == 400 and "only open alerts" in again.text
    stale = _row(console, "e" * 32)
    r = console.post(
        f"/console/alerts/{'e' * 32}/ack", {"row_version": str(stale["row_version"] + 5)},
        user="operator.khanh",
    )  # fmt: skip
    assert r.status_code in (400, 409)
