"""WP-G5 API and console: /v1/incidents, the Incidents tab, the Reports tab of the system page.
Scope, RBAC, audit rows, 400 and 404 shapes, EN and VI."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from supervisor.governance.actions_model import GovernanceEvent
from supervisor.governance.incidents import TITLES

from .conftest import Console, draft

REVIEWER = "reviewer.an"
OWNER_USER = "payops-lead@example.invalid"  # owns the demo agent "payments", team "Payments Ops"
VIEWER = "viewer.hoa"
HX = {"HX-Request": "true"}
AT = datetime(2026, 10, 22, 11, 0, tzinfo=UTC)


@pytest.fixture
def g5(console: Console, monkeypatch: pytest.MonkeyPatch) -> Iterator[Console]:
    """Mount the routers as app.py does with the flags on, switch the flags on, take it all off."""
    from supervisor.app import app
    from supervisor.console.incidents_routes import router as incidents_console
    from supervisor.console.systems_routes import router as systems_console
    from supervisor.governance.incident_routes import router as incidents_api
    from supervisor.governance.routes import router as systems_api

    saved = list(app.router.routes)
    for r in (systems_api, systems_console, incidents_api, incidents_console):
        app.include_router(r)
    for flag in ("governance_enabled", "console_systems_enabled", "governance_actions_enabled"):
        monkeypatch.setattr(console.ctx.settings, flag, True)
    try:
        yield console
    finally:
        app.router.routes[:] = saved
        app.openapi_schema = None


def req(c: Console, method: str, url: str, body: Any = None, user: str = REVIEWER) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def make(
    c: Console,
    ref: str = "alert:al_1",
    agent: str = "payments",
    system: str | None = None,
    kind: str = "alert",
    severity: str = "high",
    rule: str = "AL-QUARANTINE",
) -> str:
    ev = GovernanceEvent(kind, severity, agent, ref, AT, system, rule_id=rule)
    row, _ = c.ctx.incidents.open_from_event(ev)
    return str(row["incident_id"])


def system(
    c: Console, name: str = "Payments - Assistant", user: str = REVIEWER, **over: Any
) -> str:
    return str(c.ctx.systems.register(draft(name=name, owner_user=user, **over), user)["system_id"])


def audit_rows(c: Console, permission: str) -> list[dict[str, Any]]:
    return [dict(r) for r in c.ctx.tables.query("console_action", {"permission": permission})]


# ------------------------------------------------------------------------------ the API


def test_list_get_and_transition(g5: Console) -> None:
    sid = system(g5)
    iid = make(g5, system=sid)
    body = req(g5, "GET", "/v1/incidents").json()
    assert body["count"] == 1
    inc = body["incidents"][0]
    assert inc["incident_id"] == iid and inc["status"] == "open" and inc["system_id"] == sid
    assert inc["next"] == ["investigating", "resolved", "closed"]
    assert inc["title"] == "Alert AL-QUARANTINE raised"
    assert req(g5, "GET", f"/v1/incidents/{iid}").json()["incident_id"] == iid

    r = req(g5, "POST", f"/v1/incidents/{iid}/transition", {"status": "investigating"})
    assert r.status_code == 200 and r.json()["status"] == "investigating"
    r = req(
        g5,
        "POST",
        f"/v1/incidents/{iid}/transition",
        {"status": "closed", "root_cause": "A key in a prompt", "affected_scope": "one agent"},
    )
    out = r.json()
    assert r.status_code == 200 and out["status"] == "closed" and out["closed_by"] == REVIEWER
    assert out["root_cause"] == "A key in a prompt"
    # a closed incident is out of the default list, and in the "all" list
    assert req(g5, "GET", "/v1/incidents").json()["count"] == 0
    assert req(g5, "GET", "/v1/incidents?status=all").json()["count"] == 1
    assert req(g5, "GET", "/v1/incidents?status=closed").json()["count"] == 1
    # the chain holds the create and both moves
    actions = [p["action"] for p in _chain(g5, "incident_change")]
    assert actions == ["create", "transition", "transition"]


def _chain(c: Console, record_type: str) -> list[dict[str, Any]]:
    import json

    out = []
    for e in c.ctx.tables.query(
        "chain_entry", {"record_type": record_type}, order_by=("ts", "seq")
    ):
        p = c.ctx.tables.query("chain_payload", {"lane": e["lane"], "seq": e["seq"]})
        out.append(json.loads(p[0]["payload"]))
    return out


def test_filters(g5: Console) -> None:
    make(g5, "alert:a1", severity="critical")
    make(g5, "verdict:v1", kind="gate_stop", severity="medium", rule="")
    make(g5, "alert:a2", agent="other-agent", severity="low")
    assert req(g5, "GET", "/v1/incidents?severity=critical").json()["count"] == 1
    assert req(g5, "GET", "/v1/incidents?kind=gate_stop").json()["count"] == 1
    assert req(g5, "GET", "/v1/incidents?agent=other-agent").json()["count"] == 1
    assert req(g5, "GET", "/v1/incidents?q=VERDICT").json()["count"] == 1


def test_bad_input_is_400_with_a_message_and_unknown_is_404(g5: Console) -> None:
    iid = make(g5)
    bad = [
        ("GET", "/v1/incidents?status=zzz", None),
        ("GET", "/v1/incidents?severity=huge", None),
        ("GET", "/v1/incidents?kind=nope", None),
        ("GET", "/v1/incidents?nope=1", None),
        ("POST", f"/v1/incidents/{iid}/transition", {"status": "open"}),
        ("POST", f"/v1/incidents/{iid}/transition", {"status": "nonsense"}),
        ("POST", f"/v1/incidents/{iid}/transition", {}),
        ("POST", f"/v1/incidents/{iid}/transition", {"status": "closed", "row_version": "one"}),
        ("POST", f"/v1/incidents/{iid}/transition", {"status": "closed", "row_version": 99}),
        ("POST", f"/v1/incidents/{iid}/transition", {"status": "closed", "root_cause": 5}),
        ("POST", f"/v1/incidents/{iid}/transition", {"status": "closed", "root_cause": "x" * 1001}),
        ("POST", f"/v1/incidents/{iid}/transition", [1, 2]),
    ]
    for method, url, body in bad:
        r = req(g5, method, url, body)
        assert r.status_code == 400, (method, url, body, r.status_code, r.text[:200])
        assert r.json().get("error") or r.json().get("detail"), (url, r.text[:200])
    for url in ("/v1/incidents/inc_000000000000000000000000", "/v1/incidents/bad%20id%3Cb%3E"):
        assert req(g5, "GET", url).status_code == 404
    r = req(
        g5, "POST", "/v1/incidents/inc_000000000000000000000000/transition", {"status": "closed"}
    )
    assert r.status_code == 404
    # still open after all of that
    assert req(g5, "GET", f"/v1/incidents/{iid}").json()["status"] == "open"
    r = req(g5, "POST", f"/v1/incidents/{iid}/transition", {"status": "closed"})
    assert r.status_code == 200
    r = req(g5, "POST", f"/v1/incidents/{iid}/transition", {"status": "investigating"})
    assert r.status_code == 400 and "closed" in r.text


def test_there_is_no_route_that_creates_an_incident(g5: Console) -> None:
    for method, url in (
        ("POST", "/v1/incidents"),
        ("PUT", "/v1/incidents"),
        ("POST", "/console/incidents"),
    ):
        r = req(g5, method, url, {"kind": "alert", "agent_id": "payments", "severity": "low"})
        assert r.status_code in (404, 405), (method, url, r.status_code)
    paths = {(m, r.path) for r in g5.client.app.router.routes for m in getattr(r, "methods", ())}
    assert not [
        p for p in paths if p[0] != "GET" and "incidents" in p[1] and "transition" not in p[1]
    ]


def test_rbac_viewer_reads_but_cannot_move(g5: Console) -> None:
    iid = make(g5)
    assert req(g5, "GET", "/v1/incidents", user=VIEWER).status_code == 200
    r = req(g5, "POST", f"/v1/incidents/{iid}/transition", {"status": "closed"}, user=VIEWER)
    assert r.status_code == 403
    assert req(g5, "GET", f"/v1/incidents/{iid}").json()["status"] == "open"
    assert r.status_code == 403  # the route gate answers before any change or audit row
    assert audit_rows(g5, "incidents.transition") == []


def test_a_transition_writes_two_audit_rows(g5: Console) -> None:
    iid = make(g5)
    before = len(audit_rows(g5, "incidents.transition"))
    r = req(g5, "POST", f"/v1/incidents/{iid}/transition", {"status": "investigating"})
    assert r.status_code == 200
    rows = audit_rows(g5, "incidents.transition")[before:]
    assert sorted(a["outcome"] for a in rows) == ["attempted", "ok"]
    assert {a["target_kind"] for a in rows} == {"incident"} and {a["target_id"] for a in rows} == {
        iid
    }
    ok = next(a for a in rows if a["outcome"] == "ok")
    assert ok["before_hash"] != ok["after_hash"] and ok["detail"] == "incident_investigating"


def test_scope_a_scoped_person_sees_only_their_systems_and_agents(g5: Console) -> None:
    mine = system(g5, "Mine", user=OWNER_USER, owner_team="Payments Ops")
    other = system(g5, "Not mine", user=REVIEWER, owner_team="risk-team")
    i_mine = make(g5, "alert:m", system=mine)
    i_other = make(g5, "alert:o", agent="risk-bot", system=other)
    i_agent = make(g5, "alert:a", agent="payments", system=None)  # no system: by agent
    i_hidden = make(g5, "alert:h", agent="risk-bot", system=None)
    ids = {
        i["incident_id"]
        for i in req(g5, "GET", "/v1/incidents", user=OWNER_USER).json()["incidents"]
    }
    assert ids == {i_mine, i_agent}
    for hidden in (i_other, i_hidden):
        assert req(g5, "GET", f"/v1/incidents/{hidden}", user=OWNER_USER).status_code == 404
        r = req(
            g5, "POST", f"/v1/incidents/{hidden}/transition", {"status": "closed"}, user=OWNER_USER
        )
        assert r.status_code == 404
    assert (
        req(
            g5,
            "POST",
            f"/v1/incidents/{i_mine}/transition",
            {"status": "investigating"},
            user=OWNER_USER,
        ).status_code
        == 200
    )
    # a reviewer sees all
    all_ids = {i["incident_id"] for i in req(g5, "GET", "/v1/incidents").json()["incidents"]}
    assert all_ids == {i_mine, i_other, i_agent, i_hidden}
    # the incident is hidden from the owner's own list of the other system
    assert req(g5, "GET", f"/v1/incidents?system={other}", user=OWNER_USER).json()["count"] == 0


def test_the_api_needs_both_flags(g5: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g5.ctx.settings, "governance_enabled", False)
    r = req(g5, "GET", "/v1/incidents")
    assert r.status_code == 400 and "GOVERNANCE_ENABLED" in r.text
    monkeypatch.setattr(g5.ctx.settings, "governance_enabled", True)
    monkeypatch.setattr(g5.ctx.settings, "governance_actions_enabled", False)
    r = req(g5, "GET", "/v1/incidents")
    assert r.status_code == 400 and "GOVERNANCE_ACTIONS_ENABLED" in r.text


# ------------------------------------------------------------------------------ the console


def test_incidents_tab_lists_filters_and_opens_the_drawer(g5: Console) -> None:
    a = make(g5, "alert:a1", severity="critical")
    b = make(g5, "verdict:v1", kind="gate_stop", severity="medium", rule="")
    html = g5.get("/console/incidents?lang=en").text
    assert "Incidents" in html and a in html and b in html
    assert "Alert" in html and "Gate stop on a risky tool" in html
    rows = g5.get("/console/incidents/rows?severity=critical", headers=HX).text
    assert a in rows and b not in rows
    rows = g5.get("/console/incidents/rows?kind=gate_stop&status=all", headers=HX).text
    assert b in rows and a not in rows
    for q in ("sort=severity&dir=desc", "sort=agent", "sort=bogus", "page=1"):
        assert g5.get(f"/console/incidents/rows?{q}", headers=HX).status_code == 200, q
    drawer = g5.get(f"/console/incidents/{a}/drawer", headers=HX)
    assert drawer.status_code == 200 and "Alert AL-QUARANTINE raised" in drawer.text
    assert 'name="status"' in drawer.text  # the reviewer may move it
    fallback = g5.get(f"/console/incidents?drawer={a}")
    assert fallback.status_code == 200 and "Alert AL-QUARANTINE raised" in fallback.text
    auditor = g5.get(f"/console/incidents/{a}/drawer", user="auditor.dung", headers=HX)
    assert auditor.status_code == 200 and 'name="status"' not in auditor.text  # reads, cannot move
    # a viewer is a scoped role: with no team and no agent the incident is not theirs to open
    assert g5.get(f"/console/incidents/{a}/drawer", user=VIEWER, headers=HX).status_code == 400


def test_incidents_tab_bad_input_is_400(g5: Console) -> None:
    for q in (
        "status=zzz",
        "severity=huge",
        "kind=nope",
        "agent=a%20b",
        "page=0",
        "page=abc",
        "page=99",
    ):
        r = g5.get(f"/console/incidents?{q}")
        assert r.status_code == 400, (q, r.status_code)
    assert (
        g5.get("/console/incidents/inc_000000000000000000000000/drawer", headers=HX).status_code
        == 400
    )


def test_incidents_tab_in_english_and_vietnamese_with_every_kind_translated(g5: Console) -> None:
    iid = make(g5)
    en = g5.get("/console/incidents?lang=en").text
    vi = g5.get("/console/incidents?lang=vi").text
    assert "Incidents" in en and "Sự cố" in vi and iid in vi
    assert "Cảnh báo" in vi and "Mới" in vi
    from supervisor.console import i18n

    table = i18n.table()
    for k in TITLES:
        assert table[f"inc_kind_{k}"][0] and table[f"inc_kind_{k}"][1]
    for s in ("open", "investigating", "resolved", "closed"):
        assert table[f"inc_st_{s}"][0] != table[f"inc_st_{s}"][1]


def test_console_transition_is_audited_and_returns_the_list(g5: Console) -> None:
    iid = make(g5)
    row = g5.ctx.state.get("incident", {"incident_id": iid})
    before = len(audit_rows(g5, "incidents.transition"))
    r = g5.post(
        f"/console/incidents/{iid}/transition",
        {
            "status": "investigating",
            "root_cause": "Under review",
            "row_version": row["row_version"],
        },
    )
    assert r.status_code == 200 and iid in r.text
    assert g5.ctx.state.get("incident", {"incident_id": iid})["status"] == "investigating"
    assert sorted(a["outcome"] for a in audit_rows(g5, "incidents.transition")[before:]) == [
        "attempted",
        "ok",
    ]
    denied = g5.post(
        f"/console/incidents/{iid}/transition",
        {"status": "closed", "row_version": "2"},
        user=VIEWER,
    )
    assert denied.status_code == 403
    bad = g5.post(f"/console/incidents/{iid}/transition", {"status": "closed"})  # no row_version
    assert bad.status_code == 400


def test_nav_has_the_incidents_item_and_the_tab(g5: Console) -> None:
    html = g5.get("/console/?lang=en").text
    assert 'href="/console/incidents?lang=en"' in html
    g5.ctx.settings.console_nav_v3 = True
    v3 = g5.get("/console/cases?lang=en").text
    assert "/console/incidents" in v3
    assert g5.get("/console/incidents?lang=en").status_code == 200


def test_the_reports_tab_of_the_system_page_lists_its_incidents(g5: Console) -> None:
    sid = system(g5)
    other = system(g5, "Other system", owner_team="risk-team")
    iid = make(g5, "alert:s1", system=sid)
    make(g5, "alert:s2", system=other)
    page = g5.get(f"/console/systems/{sid}?tab=reports&lang=en")
    assert page.status_code == 200
    body = re.sub(r"\s+", " ", page.text)
    assert iid in body and "Reports" in body
    assert "alert:s2" not in body and other not in body.replace("Other system", "")
    vi = g5.get(f"/console/systems/{sid}?tab=reports&lang=vi")
    assert vi.status_code == 200 and "Báo cáo" in vi.text and iid in vi.text
    assert g5.get(f"/console/systems/{sid}?tab=overview").status_code == 200
    assert g5.get(f"/console/systems/{sid}?tab=nope").status_code == 400
    # a scoped person cannot open the reports of a system that is not theirs
    assert g5.get(f"/console/systems/{other}?tab=reports", user=OWNER_USER).status_code == 400


def test_the_reports_tab_is_absent_when_the_flag_is_off(
    g5: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = system(g5)
    monkeypatch.setattr(g5.ctx.settings, "governance_actions_enabled", False)
    assert g5.get(f"/console/systems/{sid}?tab=reports").status_code == 400
    assert "tab=reports" not in g5.get(f"/console/systems/{sid}").text
