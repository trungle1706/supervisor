"""WP-L3: duties in the risk register and gap tasks (RISK_DUTIES).

Off path first (no tab, routes answer 400 risk_duties_off, no overview dimension), then the
Duties tab (filters, paging), Close (catalogue control, manual control, bad ids), Waive (reason,
owner rule), Re-evaluate, the gap closure score, the My overview dimension, the risk line and the
sweep. The rows are written straight into ``obligation_status`` from real RegKB obligation ids,
except the Re-evaluate tests, which run the real matrix."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import pytest

from supervisor.config import load_settings
from supervisor.console import overview_v4
from supervisor.core import rbac
from supervisor.core.errors import ConfigError
from supervisor.governance import duties_gap as dg
from supervisor.governance.register_v2 import duties as dut

from .conftest import Console, draft

BANNER = "Not legal advice. Bank counsel must confirm."
CREATOR = "reviewer.an"  # reviewer: systems.edit and systems.approve; creates the system
OWNER = "payops-lead@example.invalid"  # owner role: systems.edit and systems.approve
SECOND = "approver.em"  # approver: systems.approve, no systems.edit
VIEWER = "viewer.hoa"
NOW = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)
EVIDENCE = "DOC-2026-114 section 3"
REASON = "The vendor report already covers this duty for now."


@pytest.fixture
def dty(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(on.ctx.settings, "risk_duties", True)
    monkeypatch.setattr(on.ctx.settings, "risk_register_enabled", True)
    return on


def _system(c: Console, owner: str = CREATOR, **over: Any) -> str:
    s = c.ctx.systems.register(draft(owner_user=owner, **over), CREATOR)
    return str(s["system_id"])


def _ids(c: Console, instrument: str, n: int) -> list[str]:
    kb = dg.kb_of(c.ctx)
    return sorted(o.id for o in kb.obligations_of(instrument))[:n]


def _seed(
    c: Console,
    sid: str,
    instrument: str,
    n: int,
    *,
    coverage: str = "none",
    applies: str = "yes",
    status: str = "open",
    owner: str = CREATOR,
    due: dt.date | None = None,
    skip: int = 0,
) -> list[str]:
    out = []
    for oid in sorted(o.id for o in dg.kb_of(c.ctx).obligations_of(instrument))[skip : skip + n]:
        c.ctx.state.insert(
            "obligation_status",
            {
                "status_id": dut.status_id(sid, oid),
                "system_id": sid,
                "obligation_id": oid,
                "instrument_id": instrument,
                "applies": applies,
                "coverage": coverage if applies == "yes" else "unknown",
                "status": status,
                "owner_user": owner,
                "due_date": due,
                "closing_control": None,
                "note": f"{BANNER} seeded",
                "created_at": NOW,
            },
        )
        out.append(oid)
    return out


def _row(c: Console, sid: str, oid: str) -> dict[str, Any]:
    r = c.ctx.state.get("obligation_status", {"status_id": dut.status_id(sid, oid)})
    assert r is not None
    return dict(r)


def _control(c: Console, cid: str = "CTL-DUTY-1", status: str = "active") -> str:
    c.ctx.state.insert(
        "control",
        {
            "control_id": cid,
            "title": "Synthetic control",
            "objective": "Holds a synthetic duty down.",
            "control_type": "preventive",
            "implemented_by": "product",
            "owner": "owner.lan",
            "status": status,
            "review_date": None,
            "scope_agents": '["*"]',
            "source": "manual",
            "created_at": NOW,
            "created_by": "owner.lan",
        },
    )
    return cid


def _url(sid: str, tail: str) -> str:
    return f"/console/systems/{sid}/duties/{tail}"


def _tab(c: Console, sid: str, query: str = "", user: str = CREATOR) -> Any:
    return c.get(f"/console/systems/{sid}?tab=duties&lang=en{query}", user=user)


def _audit(c: Console) -> list[dict[str, Any]]:
    return [dict(r) for r in c.ctx.tables.query("console_action", order_by=("ts",))]


def _risk(c: Console, sid: str) -> dict[str, Any] | None:
    r = c.ctx.state.get("risk", {"risk_id": dg.risk_id_of(sid)})
    return dict(r) if r is not None else None


# ------------------------------------------------------------------ the flag and the off path


def test_flags_are_off_by_default() -> None:
    s = load_settings(llm_base_url="")
    assert s.risk_duties is False and s.risk_duties_sweep_s == 0
    assert dg.enabled(s) is False


def test_sweep_interval_is_off_or_300_or_more() -> None:
    assert load_settings(llm_base_url="", risk_duties_sweep_s=300).risk_duties_sweep_s == 300
    with pytest.raises(ConfigError, match="RISK_DUTIES_SWEEP_S"):
        load_settings(llm_base_url="", risk_duties_sweep_s=60)


def test_flag_needs_governance_and_systems_page(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "risk_duties", True)
    assert dg.enabled(console.ctx.settings) is False  # the other two flags are off here
    monkeypatch.setattr(console.ctx.settings, "governance_enabled", True)
    assert dg.enabled(console.ctx.settings) is False
    monkeypatch.setattr(console.ctx.settings, "console_systems_enabled", True)
    assert dg.enabled(console.ctx.settings) is True


def test_flag_off_no_tab_and_every_route_is_400(on: Console) -> None:
    sid = _system(on)
    _seed(on, sid, "VN-DEC142-2026", 2)
    html = on.get(f"/console/systems/{sid}?lang=en").text
    assert "tab=duties" not in html and 'data-du="pill"' not in html
    r = _tab(on, sid)
    assert r.status_code == 400  # an unknown tab, not a 403 and not a 500
    oid = _ids(on, "VN-DEC142-2026", 1)[0]
    sid_row = dut.status_id(sid, oid)
    for tail, form in (
        ("close", {"status_id": sid_row, "closing_control": "x", "evidence_ref": "y"}),
        ("waive", {"status_id": sid_row, "reason": REASON}),
        ("reevaluate", {}),
    ):
        r = on.post(_url(sid, tail), form, user=CREATOR)
        assert r.status_code == 400, tail
        assert "risk_duties_off" in r.text and "RISK_DUTIES" in r.text, tail
    assert _row(on, sid, oid)["status"] == "open"
    assert _risk(on, sid) is None


def test_flag_off_overview_has_no_duties_dimension(on: Console) -> None:
    sid = _system(on)
    _seed(on, sid, "VN-DEC142-2026", 2)
    on.ctx.settings.console_overview_v4 = True
    me = _me(on)
    d = overview_v4.my_overview(on.ctx, me, "all", NOW, {})
    assert [x["key"] for x in d["assess"]] == list(overview_v4.DIMENSIONS)


def _me(c: Console, user: str = CREATOR) -> Any:
    from .conftest import person

    return person(user, "reviewer")


def test_rbac_rows_exist() -> None:
    assert rbac.route_entry("POST", "/console/systems/{system_id}/duties/close") == "systems.edit"
    assert (
        rbac.route_entry("POST", "/console/systems/{system_id}/duties/waive") == "systems.approve"
    )
    assert (
        rbac.route_entry("POST", "/console/systems/{system_id}/duties/reevaluate") == "systems.edit"
    )


# ------------------------------------------------------------------ score arithmetic


def _r(applies: str, status: str) -> dict[str, str]:
    return {"applies": applies, "status": status}


def test_score_arithmetic() -> None:
    assert dg.score([])["pct"] is None
    assert dg.score([_r("yes", "waived")])["pct"] is None  # a waived row is not in the figure
    assert dg.score([_r("needs_answer", "open")])["pct"] is None
    assert dg.score([_r("yes", "open")])["pct"] == 0
    assert dg.score([_r("yes", "closed")])["pct"] == 100
    one_third = [_r("yes", "closed"), _r("yes", "open"), _r("yes", "open")]
    assert dg.score(one_third)["pct"] == 33  # an integer, rounded down
    mixed = [*one_third, _r("yes", "waived"), _r("needs_answer", "open"), _r("no", "closed")]
    s = dg.score(mixed)
    assert (s["open"], s["closed"], s["waived"], s["pct"]) == (2, 1, 1, 33)
    assert isinstance(dg.score(mixed)["pct"], int)


def test_score_on_the_page_and_in_the_header(dty: Console) -> None:
    sid = _system(dty)
    assert 'data-du="pill"' not in dty.get(f"/console/systems/{sid}?lang=en").text  # no rows
    assert "No duty of this system applies yet" in _tab(dty, sid).text
    _seed(dty, sid, "VN-DEC142-2026", 3)
    _seed(dty, sid, "VN-TT53-2026", 1, status="closed")
    html = dty.get(f"/console/systems/{sid}?lang=en").text
    assert 'data-du="pill"' in html and "Duties closed 25%" in html
    tab = _tab(dty, sid).text
    assert "<b>25%</b>" in tab and "(1 of 4)" in tab
    assert BANNER in tab


# ------------------------------------------------------------------ the tab: filters and paging


def test_tab_groups_rows_and_filters(dty: Console) -> None:
    sid = _system(dty)
    _seed(dty, sid, "VN-DEC142-2026", 3)
    _seed(dty, sid, "VN-DEC142-2026", 2, coverage="partial", skip=3)
    _seed(dty, sid, "INTL-NISTRMF-2023", 2, status="closed")
    _seed(dty, sid, "INTL-NISTRMF-2023", 1, status="waived", skip=2)
    _seed(dty, sid, "VN-TT53-2026", 2, applies="needs_answer")
    html = _tab(dty, sid).text  # default filter: open
    assert 'data-table="duties"' in html and "tab=duties" in html
    groups = re.findall(r'data-group="([^"]+)"', html)
    assert groups == ["VN-DEC142-2026|none", "VN-DEC142-2026|partial"]  # none before partial
    assert re.findall(r'data-status="(\w+)"', html) == ["open"] * 5
    for head in ("Obligation and article", "Duty", "Applies", "Coverage", "Owner", "Due"):
        assert f">{head}</th>" in html
    assert "Closing control" in html
    want = {"open": 5, "closed": 2, "waived": 1, "needs_answer": 2, "all": 10}
    for f, n in want.items():
        h = _tab(dty, sid, f"&f={f}").text
        assert h.count("data-obligation=") == n, f
    assert set(re.findall(r'data-status="(\w+)"', _tab(dty, sid, "&f=closed").text)) == {"closed"}
    assert "Open" in html and re.search(r'data-filter="closed"[^>]*>Closed <span[^>]*>2<', html)
    for bad in ("&f=bogus", "&p=0", "&p=x", "&p=9"):
        assert _tab(dty, sid, bad).status_code == 400, bad


def test_tab_pages_100_rows(dty: Console) -> None:
    sid = _system(dty)
    _seed(dty, sid, "VN-TT53-2026", 53)
    _seed(dty, sid, "VN-PDPL-2025", 35)
    _seed(dty, sid, "VN-AI-2025", 32)
    p1 = _tab(dty, sid, "&f=open").text
    assert p1.count("data-obligation=") == dg.PAGE_SIZE == 100
    p2 = _tab(dty, sid, "&f=open&p=2").text
    assert p2.count("data-obligation=") == 20
    assert not set(re.findall(r'data-obligation="([^"]+)"', p1)) & set(
        re.findall(r'data-obligation="([^"]+)"', p2)
    )
    assert "page 2 of 2" in p2


def test_tab_buttons_follow_the_role(dty: Console) -> None:
    sid = _system(dty, owner=OWNER)
    _seed(dty, sid, "VN-DEC142-2026", 1, owner=OWNER)
    edit = _tab(dty, sid, user=CREATOR).text  # reviewer: edit and approve
    assert 'data-act="duty-close"' in edit and 'data-act="duty-waive"' in edit
    assert 'data-act="duty-reevaluate"' in edit
    own = _tab(dty, sid, user=OWNER).text  # the owner may close but is not offered Waive
    assert 'data-act="duty-close"' in own and 'data-act="duty-waive"' not in own
    assert 'data-du="owner-note"' in own
    appr = _tab(dty, sid, user=SECOND).text  # approver: waive only
    assert 'data-act="duty-waive"' in appr and 'data-act="duty-close"' not in appr
    assert 'data-act="duty-reevaluate"' not in appr
    dty.ctx.systems.add_member(sid, VIEWER, "technical_specialist", CREATOR)  # in scope, view only
    view = _tab(dty, sid, user=VIEWER).text
    assert 'data-act="duty-' not in view and "data-obligation=" in view


def test_tab_in_nav_v3_order(dty: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dty.ctx.settings, "console_nav_v3", True)
    sid = _system(dty)
    _seed(dty, sid, "VN-DEC142-2026", 2)
    html = dty.get(f"/console/systems/{sid}?tab=duties&lang=en").text
    assert 'data-table="duties"' in html


# ------------------------------------------------------------------ close


def test_close_with_a_catalogue_control(dty: Console) -> None:
    sid = _system(dty)
    oid, other = _seed(dty, sid, "VN-DEC142-2026", 2)
    cid = _control(dty)
    r = dty.post(
        _url(sid, "close"),
        {"status_id": dut.status_id(sid, oid), "closing_control": cid, "evidence_ref": EVIDENCE},
        user=CREATOR,
    )
    assert r.status_code == 200, r.text[:300]
    row = _row(dty, sid, oid)
    assert row["status"] == "closed" and row["closing_control"] == cid
    assert EVIDENCE in row["note"] and row["note"].startswith(BANNER)
    assert _row(dty, sid, other)["status"] == "open"
    assert "Duty closed." in r.text and 'data-table="duties"' in r.text
    # two audit rows (attempted, ok); the typed text is only a hash
    rows = [a for a in _audit(dty) if a["path"] == _url(sid, "close")]
    assert [a["outcome"] for a in rows] == ["attempted", "ok"]
    assert rows[1]["detail"].startswith("duty_close open>closed n=1 text_sha=")
    assert EVIDENCE not in str(rows) and rows[1]["before_hash"] != rows[1]["after_hash"]
    # the same row again: it is not open any more
    r = dty.post(
        _url(sid, "close"),
        {"status_id": dut.status_id(sid, oid), "closing_control": cid, "evidence_ref": EVIDENCE},
        user=CREATOR,
    )
    assert r.status_code == 400 and "not_open" in r.text


def test_close_with_a_manual_control(dty: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _system(dty)
    a, b = _seed(dty, sid, "VN-DEC142-2026", 2)
    # a bank process of controls.yaml
    r = dty.post(
        _url(sid, "close"),
        {
            "status_id": dut.status_id(sid, a),
            "closing_control": "manual:legal_review",
            "evidence_ref": EVIDENCE,
        },
        user=CREATOR,
    )
    assert r.status_code == 200, r.text[:300]
    assert _row(dty, sid, a)["closing_control"] == "manual:legal_review"
    # an internal obligation of a bank rule file (regulations/internal)
    folder = Path(dty.ctx.settings.data_dir) / "internal"
    folder.mkdir(parents=True, exist_ok=True)
    example = Path(__file__).resolve().parents[2] / "regulations" / "internal"
    (folder / "example-ai-use-policy.yaml").write_text(
        (example / "example-ai-use-policy.yaml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(dty.ctx.settings, "regkb_internal_dir", str(folder))
    r = dty.post(
        _url(sid, "close"),
        {
            "status_id": dut.status_id(sid, b),
            "closing_control": "manual:INT-EXAMPLE-AIPOL-S4-01",
            "evidence_ref": EVIDENCE,
        },
        user=CREATOR,
    )
    assert r.status_code == 200, r.text[:300]
    assert _row(dty, sid, b)["closing_control"] == "manual:INT-EXAMPLE-AIPOL-S4-01"


def test_close_refusals_are_400_and_change_nothing(dty: Console) -> None:
    sid = _system(dty)
    oid, other = _seed(dty, sid, "VN-DEC142-2026", 2)
    _seed(dty, sid, "VN-TT53-2026", 1, applies="needs_answer")
    cid = _control(dty)
    _control(dty, "CTL-OLD", status="retired")
    sid_row = dut.status_id(sid, oid)
    good = {"status_id": sid_row, "closing_control": cid, "evidence_ref": EVIDENCE}
    bad: list[tuple[dict[str, str], str]] = [
        ({**good, "closing_control": "NO-SUCH-CONTROL"}, "bad_control"),
        ({**good, "closing_control": "CTL-OLD"}, "bad_control"),  # retired
        ({**good, "closing_control": "manual:nope"}, "bad_control"),
        ({**good, "closing_control": "manual:"}, "bad_control"),
        ({**good, "closing_control": "bad id; drop"}, "bad_control"),
        ({**good, "closing_control": ""}, "control_required"),
        ({**good, "evidence_ref": ""}, "evidence_required"),
        ({**good, "evidence_ref": "x" * 201}, "evidence_required"),
        ({**good, "evidence_ref": "a\x00b"}, "evidence_required"),
        ({**good, "status_id": "os_nope"}, "duty_not_found"),
        ({"closing_control": cid, "evidence_ref": EVIDENCE}, "target_required"),
        ({**good, "group": "VN-DEC142-2026|none"}, "target_required"),
        ({**good, "status_id": "", "group": "VN-DEC142-2026|full"}, "bad_group"),
        ({**good, "status_id": "", "group": "VN-AI-2025|none"}, "nothing_to_do"),
        (
            {**good, "status_id": dut.status_id(sid, _ids(dty, "VN-TT53-2026", 1)[0])},
            "needs_answer",
        ),
    ]
    for form, code in bad:
        r = dty.post(_url(sid, "close"), form, user=CREATOR)
        assert r.status_code == 400 and code in r.text, (code, r.status_code, r.text[:200])
    assert _row(dty, sid, oid)["status"] == "open" and _row(dty, sid, other)["status"] == "open"
    ok = dty.post(_url(sid, "close"), {**good, "evidence_ref": "x" * 200}, user=CREATOR)
    assert ok.status_code == 200  # 200 characters is the limit
    # roles: an approver has no systems.edit, a viewer has neither
    for who in (SECOND, VIEWER):
        r = dty.post(_url(sid, "close"), {**good, "status_id": dut.status_id(sid, other)}, user=who)
        assert r.status_code == 403, who
    assert _row(dty, sid, other)["status"] == "open"


def test_close_a_group_and_the_risk_line_closes(dty: Console) -> None:
    sid = _system(dty)
    _seed(dty, sid, "VN-DEC142-2026", 3)
    _seed(dty, sid, "INTL-NISTRMF-2023", 2, coverage="partial")
    cid = _control(dty)
    assert dg.sync_risk(dty.ctx, dty.ctx.systems.get(sid), CREATOR) == "opened"
    line = _risk(dty, sid)
    assert line is not None and line["status"] == "active" and line["category"] == "duties_gap"

    def close(group: str) -> Any:
        return dty.post(
            _url(sid, "close"),
            {"group": group, "closing_control": cid, "evidence_ref": EVIDENCE},
            user=CREATOR,
        )

    assert close("VN-DEC142-2026|none").status_code == 200
    rows = dg.rows_of(dty.ctx.state, sid)
    assert [r["status"] for r in rows if r["instrument_id"] == "VN-DEC142-2026"] == ["closed"] * 3
    mid = _risk(dty, sid)
    assert mid is not None and mid["status"] == "active"  # one group is still open
    assert close("INTL-NISTRMF-2023|partial").status_code == 200
    end = _risk(dty, sid)
    assert end is not None and end["status"] == "retired"  # every group is closed
    assert dg.score(dg.rows_of(dty.ctx.state, sid))["pct"] == 100
    assert close("INTL-NISTRMF-2023|partial").status_code == 400  # nothing open any more


# ------------------------------------------------------------------ waive


def test_waive_rules(dty: Console) -> None:
    sid = _system(dty, owner=OWNER)
    a, b, c = _seed(dty, sid, "VN-DEC142-2026", 3, owner=OWNER)
    row = dut.status_id(sid, a)
    url = _url(sid, "waive")
    # a short reason
    r = dty.post(url, {"status_id": row, "reason": "too short"}, user=SECOND)
    assert r.status_code == 400 and "reason_too_short" in r.text
    r = dty.post(url, {"status_id": row, "reason": "x" * 19}, user=SECOND)
    assert r.status_code == 400
    # the system owner (the person on owner_user) cannot waive, whatever the role holds
    r = dty.post(url, {"status_id": row, "reason": REASON}, user=OWNER)
    assert r.status_code == 400 and "owner_cannot_waive" in r.text
    assert _row(dty, sid, a)["status"] == "open"
    # a viewer has no systems.approve
    assert dty.post(url, {"status_id": row, "reason": REASON}, user=VIEWER).status_code == 403
    # a second person with systems.approve can
    r = dty.post(url, {"status_id": row, "reason": "y" * 20}, user=SECOND)
    assert r.status_code == 200, r.text[:300]
    waived = _row(dty, sid, a)
    assert waived["status"] == "waived" and "y" * 20 in waived["note"]
    assert waived["note"].startswith(BANNER) and SECOND in waived["note"]
    rows = [x for x in _audit(dty) if x["path"] == url and x["outcome"] == "ok"]
    assert len(rows) == 1 and rows[0]["detail"].startswith("duty_waive open>waived n=1 text_sha=")
    assert "y" * 20 not in str(rows)
    # a group waive; waived rows are out of the score
    r = dty.post(url, {"group": "VN-DEC142-2026|none", "reason": REASON}, user=SECOND)
    assert r.status_code == 200
    assert {_row(dty, sid, x)["status"] for x in (a, b, c)} == {"waived"}
    assert dg.score(dg.rows_of(dty.ctx.state, sid))["pct"] is None
    # the owner is also refused on the owner's own team role
    again = dty.post(url, {"status_id": row, "reason": REASON}, user=SECOND)
    assert again.status_code == 400 and "not_open" in again.text


def test_team_system_owner_cannot_waive_either(dty: Console) -> None:
    sid = _system(dty, owner=OWNER)
    a = _seed(dty, sid, "VN-DEC142-2026", 1, owner=OWNER)[0]
    system = dty.ctx.systems.get(sid)
    assert dg._is_owner(system, OWNER) and dg._is_owner(system, OWNER.upper())  # noqa: SLF001
    assert not dg._is_owner(system, SECOND)  # noqa: SLF001
    dty.ctx.systems.add_member(sid, SECOND, "system_owner", CREATOR)  # a second owner on the team
    r = dty.post(
        _url(sid, "waive"), {"status_id": dut.status_id(sid, a), "reason": REASON}, user=SECOND
    )
    assert r.status_code == 400 and "owner_cannot_waive" in r.text
    assert _row(dty, sid, a)["status"] == "open"


# ------------------------------------------------------------------ re-evaluate


def test_reevaluate_updates_rows_and_keeps_counts(dty: Console) -> None:
    sid = _system(dty)
    first = dty.post(_url(sid, "reevaluate"), {}, user=CREATOR)
    assert first.status_code == 200, first.text[:300]
    rows = dg.rows_of(dty.ctx.state, sid)
    assert len(rows) > 100  # the matrix rows that apply or need an answer
    assert {r["applies"] for r in rows} <= {"yes", "needs_answer"}
    assert any(r["applies"] == "yes" and r["coverage"] in ("partial", "none") for r in rows)
    system = dty.ctx.systems.get(sid)
    # a second run on the same answers changes nothing
    again = dg.reevaluate(dty.ctx, CREATOR, system)
    assert again["updated"] == 0 and again["added"] == 0
    assert again["rows_before"] == again["rows_after"] == len(rows)
    # damage the rows, close one, keep one that no longer applies
    yes = [r for r in rows if r["applies"] == "yes"]
    tampered = yes[0]
    dty.ctx.state.update(
        "obligation_status",
        {"status_id": tampered["status_id"]},
        {"applies": "needs_answer", "coverage": "unknown", "due_date": None},
        int(tampered["row_version"]),
    )
    closed = yes[1]
    dty.ctx.state.update(
        "obligation_status",
        {"status_id": closed["status_id"]},
        {"status": "closed", "closing_control": "manual:legal_review", "coverage": "full"},
        int(closed["row_version"]),
    )
    n = len(rows)
    out = dg.reevaluate(dty.ctx, CREATOR, system)
    assert out["updated"] >= 2 and out["became_yes"] >= 1 and out["added"] == 0
    assert out["rows_after"] == n  # nothing is added and nothing is deleted
    healed = _row(dty, sid, tampered["obligation_id"])
    assert healed["applies"] == "yes" and healed["coverage"] == tampered["coverage"]
    assert healed["due_date"] is not None  # a needs_answer row that becomes yes gets a due date
    kept = _row(dty, sid, closed["obligation_id"])
    assert kept["status"] == "closed" and kept["closing_control"] == "manual:legal_review"
    assert kept["coverage"] == closed["coverage"]  # coverage is re-derived, status is kept
    # a duty that stops applying keeps its row, marked no (coverage unknown); nothing is deleted
    import dataclasses
    from types import SimpleNamespace

    real = dut.matrix_of(dty.ctx, dg.pseudo_draft(dty.ctx, system)[0])
    gone = yes[2]["obligation_id"]
    fake = SimpleNamespace(
        rows=[
            dataclasses.replace(r, applies="no") if r.obligation_id == gone else r
            for r in real.rows
        ]
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(dut, "matrix_of", lambda ctx, d: fake)
        dg.reevaluate(dty.ctx, CREATOR, system)
    row = _row(dty, sid, gone)
    assert row["applies"] == "no" and row["coverage"] == "unknown" and row["status"] == "open"
    assert len(dg.rows_of(dty.ctx.state, sid)) == n
    assert dg.score(dg.rows_of(dty.ctx.state, sid))["open"] == dg.score(rows)["open"] - 2
    audit = [a for a in _audit(dty) if a["path"] == _url(sid, "reevaluate")]
    assert [a["outcome"] for a in audit] == ["attempted", "ok"]
    assert audit[1]["detail"].startswith("duty_reevaluate rows=")


def test_reevaluate_uses_the_stored_answers_and_facts(dty: Console) -> None:
    sid = _system(dty, autonomy_level="unspecified")
    system = dty.ctx.systems.get(sid)
    d0, used0 = dg.pseudo_draft(dty.ctx, system)
    assert used0 == 0 and d0["data"]["v"]["autonomy_level"] == "unspecified"
    node = "inv_facts_node"
    dty.ctx.state.insert(
        "onboard_facts",
        {
            "fact_id": "f1",
            "node_id": node,
            "attempt_n": 1,
            "kind": "autonomy",
            "name": "L2",
            "detail": "tool calls with approval",
            "file": "app.py",
            "line": 3,
            "quote": "interrupt",
            "source": "rule",
            "model_id": None,
            "dropped_claims": None,
            "active": True,
            "created_at": NOW,
        },
    )
    linked = {**system, "components": [{"ref_kind": "node", "ref_id": node, "active": True}]}
    d1, used1 = dg.pseudo_draft(dty.ctx, linked)
    assert used1 == 1 and d1["data"]["v"]["autonomy_level"] == "l2_workflow_step"
    # a system that already has a level keeps it
    lvl = {**linked, "autonomy_level": "l1_assistive"}
    d2, used2 = dg.pseudo_draft(dty.ctx, lvl)
    assert used2 == 0 and d2["data"]["v"]["autonomy_level"] == "l1_assistive"


# ------------------------------------------------------------------ My overview


def test_overview_duties_dimension(dty: Console) -> None:
    dty.ctx.settings.console_overview_v4 = True
    a = _system(dty, name="Payments - Assistant A")
    b = _system(dty, name="Payments - Assistant B")
    _system(dty, name="Payments - Assistant C")  # no duty rows: not in the dimension
    _seed(dty, a, "VN-DEC142-2026", 4)
    _seed(dty, a, "VN-TT53-2026", 4, status="closed")  # 50%
    _seed(dty, b, "VN-DEC142-2026", 1, coverage="full")
    _seed(dty, b, "VN-TT53-2026", 3, status="closed", skip=1)  # 75%, group none is closed
    d = overview_v4.my_overview(dty.ctx, _me(dty), "all", NOW, {})
    dims = {x["key"]: x for x in d["assess"]}
    row = dims["duties"]
    assert row["of"] == 2 and row["avg"] == 62 and row["open_systems"] == 1
    assert row["done"] == 1 and row["bp"] == 6200
    assert [x["key"] for x in d["assess"]][-1] == "duties"
    assert list(overview_v4.DIMENSIONS) == [x["key"] for x in d["assess"]][:-1]


def test_overview_dimension_without_rows(dty: Console) -> None:
    dty.ctx.settings.console_overview_v4 = True
    _system(dty)
    d = overview_v4.my_overview(dty.ctx, _me(dty), "all", NOW, {})
    row = {x["key"]: x for x in d["assess"]}["duties"]
    assert row["of"] == 0 and row["avg"] is None and row["bp"] is None


# ------------------------------------------------------------------ the risk line


def test_risk_points() -> None:
    assert dg.risk_points([]) == (2, 2)
    assert dg.risk_points([(True, "none")]) == (2, 5)  # binding VN, no coverage
    assert dg.risk_points([(True, "partial")]) == (2, 4)
    assert dg.risk_points([(False, "none")]) == (2, 3)  # international reference framework
    assert dg.risk_points([(False, "partial")]) == (2, 2)
    # the highest-risk instrument sets the impact, the count sets the likelihood
    mix = [(False, "none"), (True, "partial"), (False, "partial")]
    assert dg.risk_points(mix) == (3, 4)
    assert dg.risk_points([(True, "none")] * 7)[0] == 4
    assert dg.risk_points([(True, "none")] * 12) == (5, 5)
    for n in range(0, 20):
        lk, im = dg.risk_points([(bool(i % 2), "none") for i in range(n)])
        assert 1 <= lk <= 5 and 1 <= im <= 5


def test_risk_line_opens_updates_and_closes(dty: Console) -> None:
    sid = _system(dty)
    system = dty.ctx.systems.get(sid)
    assert dg.sync_risk(dty.ctx, system, CREATOR) == "none"  # no rows, no line
    _seed(dty, sid, "INTL-NISTRMF-2023", 3, coverage="partial")
    assert dg.sync_risk(dty.ctx, system, CREATOR) == "opened"
    line = _risk(dty, sid)
    assert line is not None
    assert line["category"] == "duties_gap" and line["status"] == "active"
    assert line["source"] == "duties" and line["treatment"] == "mitigate"
    assert (line["inherent_likelihood"], line["inherent_impact"]) == (2, 2)  # 1 group, reference
    assert BANNER in line["description"] and line["owner"] == CREATOR
    assert line["risk_id"].startswith("RSK-DUTY-") and len(line["risk_id"]) <= 64
    links = dty.ctx.risks.links(line["risk_id"])
    assert links and all(x["kind"] == "matrix" for x in links)  # refs, never controls
    assert dg.sync_risk(dty.ctx, system, CREATOR) == "unchanged"
    # a binding VN instrument with no coverage raises the score
    _seed(dty, sid, "VN-DEC142-2026", 2)
    assert dg.sync_risk(dty.ctx, system, CREATOR) == "updated"
    line = _risk(dty, sid)
    assert line is not None and (line["inherent_likelihood"], line["inherent_impact"]) == (2, 5)
    got = dty.ctx.risks.get(line["risk_id"])
    assert got["inherent_score"] == 10 and got["inherent_band"] == "high"
    assert got["evidence_reason"] in ("no_evidence_yet", "no_links")
    # one line per system, even after more syncs
    assert len([r for r in dty.ctx.state.query("risk") if r["category"] == "duties_gap"]) == 1
    # every group closed: the line is retired; a new open group opens it again
    for r in dg.rows_of(dty.ctx.state, sid):
        dty.ctx.state.update(
            "obligation_status",
            {"status_id": r["status_id"]},
            {"status": "closed"},
            int(r["row_version"]),
        )
    assert dg.sync_risk(dty.ctx, system, CREATOR) == "closed"
    gone = _risk(dty, sid)
    assert gone is not None and gone["status"] == "retired"
    assert dg.sync_risk(dty.ctx, system, CREATOR) == "none"
    _seed(dty, sid, "VN-TT53-2026", 1)
    assert dg.sync_risk(dty.ctx, system, CREATOR) == "updated"
    back = _risk(dty, sid)
    assert back is not None and back["status"] == "active"


def test_risk_line_is_per_system_and_thresholds_stay_illustrative(dty: Console) -> None:
    one, two = _system(dty, name="Sys one"), _system(dty, name="Sys two")
    _seed(dty, one, "VN-DEC142-2026", 1)
    _seed(dty, two, "VN-DEC142-2026", 1)
    for s in (one, two):
        assert dg.sync_risk(dty.ctx, dty.ctx.systems.get(s), CREATOR) == "opened"
    assert dg.risk_id_of(one) != dg.risk_id_of(two)
    assert dty.ctx.risks.cfg.thresholds.illustrative is True


# ------------------------------------------------------------------ the sweep


class _Clock:
    def __init__(self, now: dt.datetime) -> None:
        self._now = now

    def now(self) -> dt.datetime:
        return self._now


def test_sweep_is_idempotent_per_week(dty: Console) -> None:
    sid = _system(dty)
    soon = (NOW + dt.timedelta(days=10)).date()
    far = (NOW + dt.timedelta(days=200)).date()
    _seed(dty, sid, "VN-DEC142-2026", 2, due=soon)
    _seed(dty, sid, "INTL-NISTRMF-2023", 2, due=far)
    other = _system(dty, name="Sys quiet")
    _seed(dty, other, "INTL-NISTRMF-2023", 2, due=far)
    clock = _Clock(NOW)
    out = dg.sweep(dty.ctx.state, clock, dty.ctx.tasks, dty.ctx.settings)
    assert out["tasks"] == 1 and out["systems"] == 1 and out["rows"] == 2
    tasks = [t for t in dty.ctx.state.query("task") if t["template_id"].startswith("DUTY-DUE-")]
    assert len(tasks) == 1
    t = tasks[0]
    assert t["agent_id"] == sid and t["template_id"] == "DUTY-DUE-2026W44"
    assert t["owner_role"] == "owner" and not t["required"] and t["status"] == "open"
    assert BANNER in t["evidence_ref"] and "2 duties are due within 30 days" in t["title"]
    # the same week: nothing new
    again = dg.sweep(dty.ctx.state, clock, dty.ctx.tasks, dty.ctx.settings)
    assert again["tasks"] == 0 and again["systems"] == 1
    assert (
        len([x for x in dty.ctx.state.query("task") if x["template_id"].startswith("DUTY-DUE")])
        == 1
    )
    # the next week: one new task
    nxt = dg.sweep(
        dty.ctx.state, _Clock(NOW + dt.timedelta(days=7)), dty.ctx.tasks, dty.ctx.settings
    )
    assert nxt["tasks"] == 1
    ids = {
        x["template_id"]
        for x in dty.ctx.state.query("task")
        if x["template_id"].startswith("DUTY-DUE")
    }
    assert ids == {"DUTY-DUE-2026W44", "DUTY-DUE-2026W45"}
    # closed rows are not reminded
    for r in dg.rows_of(dty.ctx.state, sid):
        if r["instrument_id"] == "VN-DEC142-2026":
            dty.ctx.state.update(
                "obligation_status",
                {"status_id": r["status_id"]},
                {"status": "closed"},
                int(r["row_version"]),
            )
    later = dg.sweep(
        dty.ctx.state, _Clock(NOW + dt.timedelta(days=14)), dty.ctx.tasks, dty.ctx.settings
    )
    assert later["tasks"] == 0 and later["systems"] == 0


def test_sweep_moves_the_due_date_to_the_effective_date(dty: Console) -> None:
    sid = _system(dty)
    oid = _seed(dty, sid, "VN-TT53-2026", 1, due=dt.date(2030, 1, 1))[0]
    assert dg.due_for(dg.kb_of(dty.ctx), oid, NOW.date()) == dt.date(2026, 11, 15)
    out = dg.sweep(dty.ctx.state, _Clock(NOW), dty.ctx.tasks, dty.ctx.settings)
    assert out["due_updated"] == 1 and out["tasks"] == 1  # 2026-11-15 is within 30 days
    assert dg.as_date(_row(dty, sid, oid)["due_date"]) == dt.date(2026, 11, 15)
    # an effective date in the past is not used: the row keeps the date it has
    old = _seed(dty, sid, "VN-DEC142-2026", 1, due=dt.date(2026, 5, 1))[0]
    assert dg.due_for(dg.kb_of(dty.ctx), old, NOW.date()) is None
    dg.sweep(dty.ctx.state, _Clock(NOW), dty.ctx.tasks, dty.ctx.settings)
    assert dg.as_date(_row(dty, sid, old)["due_date"]) == dt.date(2026, 5, 1)


def test_sweep_job_is_listed_only_when_it_can_run(
    dty: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.jobs import duties_sweep

    s = dty.ctx.settings
    assert duties_sweep.enabled(s) is False  # RISK_DUTIES_SWEEP_S is 0
    monkeypatch.setattr(s, "risk_duties_sweep_s", 300)
    assert duties_sweep.enabled(s) is True
    monkeypatch.setattr(s, "risk_duties", False)
    assert duties_sweep.enabled(s) is False
    monkeypatch.setattr(s, "risk_duties", True)
    out = duties_sweep.run(_job_ctx(dty), s)
    assert out == {"systems": 0, "tasks": 0, "rows": 0, "due_updated": 0}


def _job_ctx(c: Console) -> Any:
    from supervisor.monitors.common import MonitorContext

    return MonitorContext.from_adapters(c.runtime.adapters, c.runtime.chain)


# ------------------------------------------------------------------ the register workflow


def test_register_submit_opens_the_risk_line(dty: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    from .test_l2_duties_step import draft_to_duties
    from .test_n3_register import ME, step, submit

    for flag in ("console_register_v2", "console_nav_v3", "agents_api_enabled"):
        monkeypatch.setattr(dty.ctx.settings, flag, True)
    monkeypatch.setattr(dty.ctx.settings, "console_register_duties", True)
    did = draft_to_duties(dty)
    for n, form in ((4, {}), (5, {}), (6, {"bind_form": "1"})):
        assert step(dty, did, n, form).status_code == 200
    assert submit(dty, did).status_code == 200
    lines = [r for r in dty.ctx.state.query("risk") if r["category"] == "duties_gap"]
    assert len(lines) == 1 and lines[0]["status"] == "active" and lines[0]["owner"] == ME
    sid = next(iter({r["system_id"] for r in dty.ctx.state.query("obligation_status")}))
    assert lines[0]["risk_id"] == dg.risk_id_of(sid)
    assert dg.score(dg.rows_of(dty.ctx.state, sid))["pct"] == 0
    # Re-evaluate finds the submitted draft by the system id and reads its answers
    stored = dg.stored_draft(dty.ctx, sid)
    assert stored is not None and stored["draft_id"] == did
    n0 = len(dg.rows_of(dty.ctx.state, sid))
    out = dg.reevaluate(dty.ctx, ME, dty.ctx.systems.get(sid))
    assert out["added"] == 0 and out["updated"] == 0  # the answers did not change
    assert out["rows_before"] == out["rows_after"] == n0 > 100


def test_register_submit_without_the_flag_opens_no_risk_line(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_l2_duties_step import draft_to_duties
    from .test_n3_register import step, submit

    for flag in ("console_register_v2", "console_nav_v3", "agents_api_enabled"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    monkeypatch.setattr(on.ctx.settings, "console_register_duties", True)
    did = draft_to_duties(on)
    for n, form in ((4, {}), (5, {}), (6, {"bind_form": "1"})):
        assert step(on, did, n, form).status_code == 200
    assert submit(on, did).status_code == 200
    assert on.ctx.state.query("obligation_status")  # the L2 rows are there ...
    assert [r for r in on.ctx.state.query("risk") if r["category"] == "duties_gap"] == []


# ------------------------------------------------------------------ labels


def test_every_label_exists_in_both_languages(dty: Console) -> None:
    from supervisor.console.i18n import table

    root = Path(__file__).resolve().parents[2] / "src" / "supervisor" / "console"
    text = (root / "templates" / "_system_duties.html").read_text(encoding="utf-8")
    text += (root / "templates" / "system.html").read_text(encoding="utf-8")
    text += (root / "templates" / "ov_my_v4.html").read_text(encoding="utf-8")
    text += (root / "systems_routes.py").read_text(encoding="utf-8")
    used = {k for k in re.findall(r"""['"](du_[a-z_]+)['"]""", text) if not k.endswith("_")}
    used |= {f"du_f_{f}" for f in dg.FILTERS}
    used |= {f"du_cov_{c}" for c in ("none", "partial", "full", "unknown")}
    used |= {f"du_ap_{a}" for a in ("yes", "no", "needs_answer")}
    used |= {f"du_st_{a}" for a in ("open", "closed", "waived")}
    t = table()
    missing = sorted(k for k in used if k not in t or not all(t[k]))
    assert not missing, missing  # an English and a Vietnamese text for every key
    sid = _system(dty)
    _seed(dty, sid, "VN-DEC142-2026", 1)
    vi = dty.get(f"/console/systems/{sid}?tab=duties&lang=vi").text
    assert "Nghĩa vụ" in vi and BANNER in vi
