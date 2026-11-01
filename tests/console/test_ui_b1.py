# ruff: noqa: F811
"""UI audit batch 1 (docs/ui/redundancy-audit.md): broken links, counts that disagree, placeholders.

UI-190 incident ids, UI-001/091 links to pages that are off, UI-040/062/350 one definition of a
count, UI-041/061 no block or tab for a feature that is off, UI-063 "No run yet", UI-092 inventory
link, UI-110 limits table, UI-184 case file placeholder, UI-183 case counts. The whole-console link
check is in ``test_ui_links.py``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from supervisor.evidence.casefile import builder as cfb
from supervisor.governance.incidents import IncidentService
from supervisor.tasks.service import overdue_required
from tests.governance.conftest import draft, mounted, on, restore_app  # noqa: F401  (fixtures)

from .conftest import Console
from .test_c4_portfolio import pf, pfall, seeded_pf  # noqa: F401  (fixtures)


@pytest.fixture
def ux(seeded_pf: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(seeded_pf.ctx.settings, "console_ux5", True)
    return seeded_pf


def _num(html: str, key: str) -> int:
    m = re.search(rf'data-num="{key}"[^>]*>\s*<b[^>]*>(?:<a[^>]*>)?(\d+)', html)
    assert m, f"no figure {key}"
    return int(m.group(1))


def _late_task(c: Console, owner: str, n: int, *, required: bool = True) -> None:
    import datetime as dt

    c.ctx.state.insert(
        "task",
        {
            "task_id": f"tsk_b1_{owner}_{n}",
            "agent_id": owner,
            "template_id": f"B1-{n}",
            "kind": "task",
            "stage": "initiation",
            "target_stage": None,
            "title": f"Late task {n}",
            "owner_role": "owner",
            "required": required,
            "status": "open",
            "due_at": c.ctx.clock.now() - dt.timedelta(days=3),
            "evidence_kind": "none",
            "evidence_ref": None,
            "level": "low",
            "d33_class": "unclassified",
            "waive_reason": None,
            "waive_requested_by": None,
            "waive_approved_by": None,
            "done_by": None,
            "done_at": None,
            "created_at": c.ctx.clock.now() - dt.timedelta(days=30),
            "created_by": "test",
        },
    )


# ------------------------------------------------------------------ UI-190 incidents


def _incident(i: str, **over: Any) -> dict[str, Any]:
    import datetime as dt

    return {
        "incident_id": i,
        "system_id": None,
        "agent_id": "-",
        "kind": "alert",
        "severity": "low",
        "title": "Alert raised",
        "event_ref": f"alert:{i}",
        "root_cause": None,
        "affected_scope": None,
        "status": "open",
        "opened_at": dt.datetime(2026, 10, 20, tzinfo=dt.UTC),
        "closed_at": None,
        "closed_by": None,
        "case_id": None,
        **over,
    }


def test_incident_get_accepts_every_id_the_list_shows(seeded: Any) -> None:
    """The showcase writes ``shw_inc_NNN``; ``get`` refused them ("does not exist") although the
    list showed them, so every Details button ended in HTTP 400."""
    a = seeded.adapters
    svc = IncidentService(a.state, a.clock, a.settings)
    for i in ("shw_inc_001", "shw_inc_012", "inc_" + "ab" * 12):
        a.state.insert("incident", _incident(i))
    listed = [r["incident_id"] for r in svc.list_incidents(None, {"status": "all"})]
    assert sorted(listed) == ["inc_" + "ab" * 12, "shw_inc_001", "shw_inc_012"]
    for i in listed:
        assert svc.get(i)["incident_id"] == i


@pytest.mark.parametrize("bad", ["", "shw_inc_", "shw_inc_1; drop", "inc_zz", "../x", "x" * 80])
def test_incident_get_still_refuses_other_ids(seeded: Any, bad: str) -> None:
    from supervisor.core.errors import NotFoundError

    svc = IncidentService(seeded.adapters.state, seeded.adapters.clock, seeded.adapters.settings)
    with pytest.raises(NotFoundError):
        svc.get(bad)


# ------------------------------------------------------------------ UI-040/UI-350 one count


def test_overdue_required_is_one_definition() -> None:
    rows = [
        {"agent_id": "A", "overdue": True, "required": True},
        {"agent_id": "a", "overdue": True, "required": True},  # compared case-insensitively
        {"agent_id": "A", "overdue": True, "required": False},  # optional: not counted
        {"agent_id": "A", "overdue": False, "required": True},  # not late
        {"agent_id": "B", "overdue": True, "required": True},  # another owner
    ]
    assert len(overdue_required(rows, {"A"})) == 2
    assert overdue_required(rows, set()) == []


def test_home_governance_and_kpis_count_the_same_overdue_tasks_with_controls_off(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.governance import kpis

    c = ux
    assert not c.ctx.settings.controls_enabled  # the production value
    sid = next(iter(c.ids.values()))  # type: ignore[attr-defined]
    for n in range(3):
        _late_task(c, sid, n)
    _late_task(c, sid, 9, required=False)
    home = c.get("/console/?scope=all", user="admin.chi")
    gov = c.get("/console/governance?scope=all", user="admin.chi")
    assert home.status_code == 200 and gov.status_code == 200
    assert _num(home.text, "due") == 3
    assert _num(gov.text, "overdue") == 3
    me = c.ctx.provider.users["admin.chi"]
    kp = kpis.compute(c.ctx, me, cache=False)
    assert kp["speed"]["overdue_tasks"] == 3 and "overdue_tasks" not in kp["unavailable"]
    assert "Controls are off" not in gov.text.split("Governance KPIs")[0]


def test_home_banner_counts_more_items_without_the_head(ux: Console) -> None:
    """UI-002: when the head of the banner is a task or a candidate it is not one of the open
    items (cases + actions), so "N more" is all of them; for a case it is all but the head."""
    from supervisor.console import overview_v4

    c = ux
    me = c.ctx.provider.users["admin.chi"]
    d = overview_v4.my_overview(c.ctx, me, "all", c.ctx.clock.now(), {})
    b = d["banner"]
    head_is_counted = b["why"] in ("ov4_why_critical", "ov4_why_high_case", "ov4_why_actions")
    assert b["more"] == max(b["open_items"] - (1 if head_is_counted else 0), 0)
    assert b["open_items"] == d["actions_n"] + d["cases_n"]
    h = c.get("/console/?scope=all", user="admin.chi").text
    if b["more"]:
        assert re.search(rf"{b['more']} more items? (is|are) open", h)
        assert f"All {d['cases_n']} open cases" in h


# ------------------------------------------------------------------ UI-041 no block when off


def test_governance_overview_has_no_block_for_a_feature_that_is_off(ux: Console) -> None:
    s = ux.ctx.settings
    assert not s.controls_enabled and not s.risk_register_enabled
    h = ux.get("/console/governance?scope=all", user="admin.chi").text
    assert "Control readiness by system" not in h and 'data-section="readiness"' not in h
    assert "Risk overview" not in h
    assert 'data-num="readiness"' not in h
    assert not re.search(r"/console/(risks|controls|tasks)[?\"]", h)


def test_governance_overview_shows_the_blocks_when_the_features_are_on(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = ux.ctx.settings
    for f in ("controls_enabled", "risk_register_enabled", "console_controls_enabled"):
        monkeypatch.setattr(s, f, True)
    h = ux.get("/console/governance?scope=all", user="admin.chi").text
    assert 'data-section="readiness"' in h and "Risk overview" in h


# ------------------------------------------------------------------ UI-001 links to pages off


def test_home_past_review_link_is_the_systems_list_while_risks_is_off(ux: Console) -> None:
    h = ux.get("/console/?scope=all", user="admin.chi").text
    assert not re.search(r"/console/risks[?\"]", h)
    assert 'href="/console/systems?lang=en"' in h


def test_home_past_review_link_is_the_risks_page_when_it_is_on(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ux.ctx.settings, "console_risks_enabled", True)
    h = ux.get("/console/?scope=all", user="admin.chi").text
    assert "/console/risks?lang=en" in h


def test_banner_target_never_points_at_a_page_that_is_off() -> None:
    from supervisor.console.overview_v4 import _banner_target

    late = [{"agent_id": "sys1", "level": "high"}, {"agent_id": "agent9", "level": "low"}]
    assert _banner_target("ov4_why_overdue_high", late, [], True, False, {"sys1"}) == (
        "/console/systems/sys1?tab=tasks",
        "task",
    )
    # an owner that is an agent, not a system: no system page for it
    assert _banner_target("ov4_why_overdue", late[1:], [], True, False, {"sys1"}) == (
        "/console/systems",
        "task",
    )
    assert (
        _banner_target("ov4_why_overdue", late[1:], [], False, False, set())[0] == "/console/cases"
    )
    assert (
        _banner_target("ov4_why_overdue", late[1:], [], False, True, set())[0] == "/console/tasks"
    )


def test_mcp_empty_state_has_no_integrations_link_while_the_page_is_off(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = ux.ctx.settings
    monkeypatch.setattr(s, "inventory_enabled", True)
    monkeypatch.setattr(s, "console_catalog_enabled", True)
    r = ux.get("/console/catalogues?tab=mcp", user="admin.chi")
    assert r.status_code == 200 and "/console/integrations" not in r.text
    monkeypatch.setattr(s, "console_integrations_enabled", True)
    r2 = ux.get("/console/catalogues?tab=mcp", user="admin.chi")
    if "g4-empty" in r2.text:
        assert "/console/integrations" in r2.text


# ------------------------------------------------------------------ UI-061 tabs of the system


def test_system_tabs_leave_out_a_feature_that_is_off(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = next(iter(ux.ids.values()))  # type: ignore[attr-defined]
    s = ux.ctx.settings
    monkeypatch.setattr(s, "console_nav_v3", True)
    h = ux.get(f"/console/systems/{sid}", user="admin.chi").text
    assert 'data-tab="risks"' not in h and 'data-tab="controls"' not in h
    assert 'data-tab="overview"' in h and 'data-tab="tasks"' in h
    # a direct URL still opens the tab, as before (no 5xx, no 403)
    assert ux.get(f"/console/systems/{sid}?tab=risks", user="admin.chi").status_code == 200
    for f in ("risk_register_enabled", "controls_enabled"):
        monkeypatch.setattr(s, f, True)
    h = ux.get(f"/console/systems/{sid}", user="admin.chi").text
    assert 'data-tab="risks"' in h and 'data-tab="controls"' in h


# ------------------------------------------------------------------ UI-062 badges


def test_tasks_badge_counts_the_open_tasks_the_tab_lists(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = next(iter(ux.ids.values()))  # type: ignore[attr-defined]
    monkeypatch.setattr(ux.ctx.settings, "console_nav_v3", True)
    for n in range(3):
        _late_task(ux, sid, n)
    ux.ctx.state.insert(  # a duty task is on the Duties tab, not counted here
        "task",
        {
            **ux.ctx.state.get("task", {"task_id": f"tsk_b1_{sid}_0"}),
            "task_id": "tsk_b1_duty",
            "template_id": "DUTY-X-1",
        },
    )
    h = ux.get(f"/console/systems/{sid}?tab=tasks", user="admin.chi").text
    m = re.search(r'data-tab="tasks".*?<span class="k"[^>]*>(\d+)</span>', h, re.S)
    assert m and int(m.group(1)) == 3
    assert 'title="Open tasks' in h


# ------------------------------------------------------------------ UI-063 No run yet


def test_risk_assessment_says_when_statuses_were_set_instead_of_no_run_yet(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    for f in ("onboard_orchestrator",):
        monkeypatch.setattr(ux.ctx.settings, f, True)
    sid = ux.ids["prohibited"]  # type: ignore[attr-defined]  # has statuses set by a person
    h = ux.get(f"/console/systems/{sid}?tab=riskdim", user="admin.chi").text
    assert (
        "No assessment yet." not in h
        and "No risk assessment run yet. Statuses last updated on" in h
    )
    bare = ux.ids["bare"]  # type: ignore[attr-defined]
    h2 = ux.get(f"/console/systems/{bare}?tab=riskdim", user="admin.chi").text
    assert 'data-orch="none"' in h2


# ------------------------------------------------------------------ UI-110 limits table


def _matrix(thresholds: list[dict[str, Any]]) -> dict[str, Any]:
    return {"thresholds": thresholds}


def _th(limit_id: str, period: str, vnd: int, verdict: str, suffix: str = "") -> dict[str, Any]:
    return {
        "id": f"TH-X-{limit_id}{suffix}",
        "limit_id": limit_id,
        "period": period,
        "limit_vnd": vnd,
        "cap_vnd": 100_000_000,
        "verdict": verdict,
        "reason": "r",
    }


def test_limits_table_drops_the_repeated_effective_row_and_names_manifest_keys() -> None:
    from supervisor.console import compliance_ux5, i18n

    t = i18n.translator("en", ux5=True)
    rows = compliance_ux5.thresholds(
        _matrix(
            [
                _th("PAY-02", "per_transaction", 100_000_000, "at_cap"),
                _th("PAY-03", "daily", 150_000_000, "exceeds"),
                _th("daily_transfer_max_minor", "daily", 300_000_000, "exceeds"),
                _th("PAY-03", "daily", 150_000_000, "exceeds", "-effective"),  # repeats row 2
                _th("transfer_max_minor", "per_transaction", 100_000_000, "at_cap"),
            ]
        ),
        t,
    )
    labels = [r["label"] for r in rows]
    assert len(rows) == 4 and len(set(labels)) == 4
    assert labels[0].startswith("PAY-02") and labels[1].startswith("PAY-03")
    joined = " ".join(labels) + " ".join(r["why"] for r in rows)
    assert "daily transfer max minor" not in joined and "_minor" not in joined
    assert labels[2].startswith("Agent setting") and rows[2]["key"] == "daily_transfer_max_minor"


# ------------------------------------------------------------------ UI-184 case file placeholder


def test_casefile_display_never_shows_the_placeholder() -> None:
    neutral = cfb.NOT_CONFIGURED_D33
    assert "FILL-ME" not in neutral
    for raw in ("", "   ", None, "FILL-ME", "FILL-ME: Decision 33 classification (bank counsel)"):
        assert cfb.decision33_display(raw) == neutral
    assert cfb.decision33_display("High risk (Appendix 2)") == "High risk (Appendix 2)"
    assert cfb.basis_label("calendar_days") == "calendar days"


def test_casefile_html_and_pdf_text_have_no_placeholder_or_token(console: Console) -> None:
    case = console.ctx.cases.list_cases()[0]
    cid = case["case_id"]
    settings = console.ctx.settings
    assert settings.casefile_decision33_text.startswith("FILL-ME")  # the default
    r = console.get(f"/console/cases/{cid}/casefile.html", user="admin.chi")
    assert r.status_code == 200
    assert "FILL-ME" not in r.text and "calendar_days" not in r.text
    assert cfb.NOT_CONFIGURED_D33 in r.text
    tab = console.get(f"/console/cases/{cid}?tab=casefile", user="admin.chi").text
    assert "calendar_days" not in tab and "FILL-ME" not in tab


# ------------------------------------------------------------------ UI-183 case counts


def test_story_stops_equal_the_hard_rule_rows(console: Console) -> None:
    from supervisor.console import case_ux5

    rows = [
        {"tier": 0, "action": "block", "ts": 1},
        {"tier": 0, "action": "pause", "ts": 2},
        {"tier": 1, "action": "block", "ts": 3},  # a judge: advises, not a hard stop
    ]
    assert case_ux5.build({"verdict_rows": rows})["stops"] == 2
    assert case_ux5.build({"verdict_rows": [], "head": {"joined": 0}})["stops"] == 0


# ------------------------------------------------------------------ UI-092 inventory


def test_inventory_agent_page_link_only_for_a_registered_agent(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.console import inventory_views

    s = on.ctx.settings
    monkeypatch.setattr(s, "inventory_enabled", True)
    data = inventory_views.page(on.ctx, None)
    assert "agent_registered" in data
    assert data["agent_registered"] == (
        data["agent"] in {a["agent_id"] for a in on.ctx.state.query("agent")}
    )


# ------------------------------------------------------------------ labels exist in both languages


def test_new_labels_exist_in_en_and_vi() -> None:
    from supervisor.console import i18n, i18n_ux_b1

    for key, (en, vi) in i18n_ux_b1.B1.items():
        assert en.strip() and vi.strip() and i18n._T[key] == (en, vi)
        assert re.findall(r"\{\w+\}", en) == re.findall(r"\{\w+\}", vi), key
    src = Path(__file__).resolve().parents[2] / "src" / "supervisor" / "console" / "templates"
    used = set()
    for f in src.glob("*.html"):
        used |= set(re.findall(r"t\('(b1_\w+?)'", f.read_text(encoding="utf-8")))
        used |= set(re.findall(r"t\('(b1_badge_)' ~", f.read_text(encoding="utf-8")))
    for key in used:
        assert key in i18n_ux_b1.B1 or key == "b1_badge_"
    assert {"b1_badge_tasks", "b1_badge_duties"} <= set(i18n_ux_b1.B1)
