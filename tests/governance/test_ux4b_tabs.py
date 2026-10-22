"""WP-UX4b: the governance tabs of the system page (Risks, Controls, Policies, Guardians, Reports).

Every figure on a tab is compared with the service it comes from. Scoping, EN and VI, the flags
that switch a source off, and the optional neighbours (WP-G2, WP-G5) that are not merged here."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.console import compliance_view, systems_tabs
from tests.conftest import REPO_ROOT

from .conftest import Console, draft

HX = {"HX-Request": "true"}
ORDER = [
    "overview",
    "components",
    "rules",
    "classification",
    "risks",
    "controls",
    "policies",
    "guardians",
    "tasks",
    "reviews",
    "reports",
]
OWNER_USER = "payops-lead@example.invalid"
FLAGS = (
    "console_nav_v3",
    "risk_register_enabled",
    "console_risks_enabled",
    "controls_enabled",
    "console_controls_enabled",
    "console_compliance_enabled",
    "transparency_enabled",
    "console_transparency_enabled",
)


@pytest.fixture
def v3(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for f in FLAGS:
        monkeypatch.setattr(on.ctx.settings, f, True)
    return on


@pytest.fixture
def seeded_registers(v3: Console) -> Console:
    ctx = v3.ctx
    assert ctx.risks.import_path(REPO_ROOT / "config" / "risks", "t", source="starter").errors == []
    res = ctx.controls.import_path(REPO_ROOT / "config" / "controls", "t", source="starter")
    assert res.errors == []
    ctx.controls.run_status()
    return v3


def system(c: Console, name: str = "Tabs system", agents: tuple[str, ...] = ("payments",)) -> str:
    out = c.ctx.systems.register(draft(name=name, owner_user="reviewer.an"), "reviewer.an")
    for a in agents:
        c.ctx.systems.link(out["system_id"], "agent", a, "reviewer.an")
    return str(out["system_id"])


def page(c: Console, sid: str, tab: str, lang: str = "en", user: str = "reviewer.an") -> str:
    r = c.get(f"/console/systems/{sid}?tab={tab}&lang={lang}", user=user)
    assert r.status_code == 200, (tab, r.status_code, r.text[:300])
    return str(r.text)


def body(html: str) -> str:
    return html.split('id="tab-body"', 1)[1].split("</main>", 1)[0]


# ------------------------------------------------------------------ the strip


def test_strip_has_the_spec_order_and_every_tab_answers_200(seeded_registers: Console) -> None:
    sid = system(seeded_registers)
    html = page(seeded_registers, sid, "overview")
    assert re.findall(r'role="tab" data-tab="(\w+)"', html) == ORDER
    for tab in ORDER:
        for lang in ("en", "vi"):
            assert page(seeded_registers, sid, tab, lang)
    part = seeded_registers.get(f"/console/systems/{sid}?tab=risks", headers=HX)
    assert part.status_code == 200 and 'id="system-risks"' in part.text


def test_unknown_tab_is_400_and_a_hidden_system_looks_missing(seeded_registers: Console) -> None:
    sid = system(seeded_registers)
    r = seeded_registers.get(f"/console/systems/{sid}?tab=zzz")
    assert r.status_code == 400 and "unknown tab" in r.text
    r = seeded_registers.get("/console/systems/sys_nope?tab=risks")
    assert r.status_code == 400 and "does not exist" in r.text


def test_tab_needs_the_permission_of_its_page(
    seeded_registers: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = system(seeded_registers)
    monkeypatch.setattr(systems_tabs, "may", lambda me, perm: perm != "risks.view")
    html = page(seeded_registers, sid, "overview")
    assert "risks" not in re.findall(r'role="tab" data-tab="(\w+)"', html)
    r = seeded_registers.get(f"/console/systems/{sid}?tab=risks")
    assert r.status_code == 403 and "risks tab" in r.text


# ------------------------------------------------------------------ scoping


def test_a_scoped_user_cannot_open_the_tabs_of_another_team(seeded_registers: Console) -> None:
    c = seeded_registers
    secret = c.ctx.systems.register(
        draft(name="Secret", owner_user="reviewer.an", owner_team="risk-team"), "reviewer.an"
    )["system_id"]
    for tab in ORDER:
        r = c.get(f"/console/systems/{secret}?tab={tab}", user=OWNER_USER)
        assert r.status_code == 400 and "does not exist" in r.text, tab
        r = c.get(f"/console/systems/{secret}?tab={tab}", user="viewer.hoa")
        assert r.status_code == 400, tab
    mine = c.ctx.systems.register(
        draft(name="Mine", owner_user=OWNER_USER, owner_team="Payments Ops"), OWNER_USER
    )["system_id"]
    for tab in ORDER:
        assert page(c, mine, tab, user=OWNER_USER)


# ------------------------------------------------------------------ Risks


def test_risks_tab_lists_what_the_register_says_for_the_agent(seeded_registers: Console) -> None:
    c = seeded_registers
    sid = system(c)
    summary = c.ctx.risks.agent_summary("payments")
    assert summary["risks"], "the starter risks reach the payments agent"
    html = body(page(c, sid, "risks"))
    shown = set(re.findall(r"drawer=(RSK[\w.-]+)&amp;lang", html))
    assert shown == {r["risk_id"] for r in summary["risks"] if r["status"] != "retired"}
    # the inherited-from column carries the anchor and own or inherited
    for r in summary["risks"]:
        assert r["via"] in html
    assert "inherited" in html or "own" in html
    active = [r for r in summary["risks"] if r["status"] == "active"]
    assert f"{len(active)} active risks" in html
    # the count on the tab label
    assert re.search(
        r'data-tab="risks".*?<span class="k">(\d+)</span>', page(c, sid, "risks"), re.S
    )


def test_risks_tab_with_no_agent_is_empty_not_invented(seeded_registers: Console) -> None:
    sid = system(seeded_registers, name="Bare", agents=())
    html = body(page(seeded_registers, sid, "risks"))
    assert "No active risk reaches this system" in html and 'id="system-risks"' not in html


def test_risks_tab_off_says_why(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v3.ctx.settings, "risk_register_enabled", False)
    html = body(page(v3, system(v3), "risks"))
    assert "not available" in html and "RISK_REGISTER_ENABLED=1" in html


# ------------------------------------------------------------------ Controls


def test_controls_tab_figure_is_the_service_figure(seeded_registers: Console) -> None:
    c = seeded_registers
    sid = system(c, agents=("payments", "credit_prequal"))
    comps = [c.ctx.controls.agent_compliance(a) for a in ("payments", "credit_prequal")]
    working = sum(x["working"] for x in comps)
    in_scope = sum(x["in_scope"] for x in comps)
    assert in_scope > 0
    html = body(page(c, sid, "controls"))
    bp = working * 10000 // in_scope
    m = re.search(
        r'data-num="system-controls-bp">(\d+)%</span> <span class="muted">\((\d+) bp\)', html
    )
    assert m and int(m.group(2)) == bp and int(m.group(1)) == bp // 100
    rows = re.findall(r'<tr class="row">', html)
    assert len(rows) == in_scope
    for x in comps:
        for ctl in x["controls"]:
            assert ctl["control_id"] in html


def test_controls_tab_single_agent_matches_the_agent_tab(seeded_registers: Console) -> None:
    c = seeded_registers
    sid = system(c)
    comp = c.ctx.controls.agent_compliance("payments")
    html = body(page(c, sid, "controls"))
    assert f"({comp['compliance_bp']} bp)" in html


def test_controls_tab_off_and_no_agents(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = system(v3, agents=())
    assert "linked" in body(page(v3, sid, "controls")).lower()
    monkeypatch.setattr(v3.ctx.settings, "controls_enabled", False)
    html = body(page(v3, system(v3, name="Other"), "controls"))
    assert "not available" in html and "CONTROLS_ENABLED=1" in html


# ------------------------------------------------------------------ Policies


def test_policies_tab_adds_up_the_matrix_of_the_agent(v3: Console) -> None:
    sid = system(v3)
    m = compliance_view.matrix_for(v3.ctx.settings, "payments")
    yes = [r for r in m["rows"] if r["applies"] == "yes"]
    met = sum(1 for r in yes if r["status"] == "met")
    gap = sum(1 for r in yes if r["status"] == "gap")
    html = body(page(v3, sid, "policies"))
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert f"Obligations that apply {len(yes)} · Met {met} · Gap {gap}" in flat
    bp = met * 10000 // len(yes)
    assert f"({bp} bp)" in flat
    # per instrument rows add up to the totals
    rows = re.findall(
        r'<tr class="row">\s*<td><span class="mono">[^<]+</span>.*?</td>\s*<td class="n">(\d+)</td>'
        r'<td class="n">(\d+)</td><td class="n">(\d+)</td><td class="n">(\d+)</td>',
        html,
        re.S,
    )
    assert sum(int(r[0]) for r in rows) == len(yes)
    assert sum(int(r[1]) for r in rows) == met
    assert sum(int(r[3]) for r in rows) == gap
    # a gap links to the obligation page
    if gap:
        assert "/console/compliance/payments/obligation/" in html
    assert "Advisory only" in html


def test_policies_tab_lists_an_agent_with_no_matrix_apart(v3: Console) -> None:
    from tests.governance.conftest import add_agent

    add_agent(v3.ctx.runtime.adapters, "lonely_agent")
    sid = system(v3, agents=("payments", "lonely_agent"))
    html = body(page(v3, sid, "policies"))
    assert "Agents with no matrix" in html and "lonely_agent" in html
    only = system(v3, name="Only lonely", agents=("lonely_agent",))
    html = body(page(v3, only, "policies"))
    assert "not available" in html and "No linked agent has a compliance matrix" in html


def test_policies_tab_off_says_why(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v3.ctx.settings, "console_compliance_enabled", False)
    html = body(page(v3, system(v3), "policies"))
    assert "not available" in html and "CONSOLE_COMPLIANCE_ENABLED=1" in html


# ------------------------------------------------------------------ Guardians


def test_guardians_tab_reads_the_detector_file_and_the_flags(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = system(v3)
    s = v3.ctx.settings
    monkeypatch.setattr(s, "detectors_enabled", False)
    off = body(page(v3, sid, "guardians"))
    assert "DETECTORS_ENABLED=1" in off and "below floor" in off
    monkeypatch.setattr(s, "detectors_enabled", True)
    on = body(page(v3, sid, "guardians"))
    assert "<code>dlp_vn</code>" in on and "DETECTORS_ENABLED=1" not in on
    assert "Read only" in on
    # the same source as the Supervisor overview
    from supervisor.console import overview_v3

    slugs, _ = overview_v3.mandatory_detectors(v3.ctx)
    for slug in slugs:
        assert f"<code>{slug}</code>" in on


def test_guardians_tab_labels_the_mock_judge(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = system(v3)
    s = v3.ctx.settings
    monkeypatch.setattr(s, "judge_enabled", True)
    monkeypatch.setattr(s, "judge_t1_model", "")
    assert '<span class="pill warn">mock</span>' in body(page(v3, sid, "guardians"))
    monkeypatch.setattr(s, "judge_enabled", False)
    assert ">mock<" not in body(page(v3, sid, "guardians"))


def test_guardians_floor_is_what_the_rules_engine_reads(v3: Console) -> None:
    out = v3.ctx.systems.register(
        draft(
            name="Floor system",
            owner_user="reviewer.an",
            user_segment="customer",
            personal_data="identifiable",
        ),
        "reviewer.an",
    )
    sid = out["system_id"]
    floor = v3.ctx.rules.guardian_floor(sid)
    assert floor and floor[0]["slug"] == "dlp_vn"
    html = body(page(v3, sid, "guardians"))
    section = html.split("Mandatory guardian floor")[1].split("</section>")[0]
    for f in floor:
        assert f"<code>{f['slug']}</code>" in section
        assert ", ".join(f["rules"]) in section


def test_guardians_floor_not_available_when_the_service_cannot_be_read() -> None:
    from types import SimpleNamespace

    def boom(system_id: str) -> Any:
        raise RuntimeError("no table")

    rows, na = systems_tabs.guardian_floor(
        SimpleNamespace(rules=SimpleNamespace(guardian_floor=boom)), {"system_id": "sys_x"}
    )
    assert rows is None and na == "ux4b_na_no_rules"


def test_policies_tab_counts_the_obligations_assigned_by_rules(v3: Console) -> None:
    sid = system(v3)
    n = len(v3.ctx.rules.obligations(sid))
    html = body(page(v3, sid, "policies"))
    assert f"{n} obligations assigned by rules" in html


# ------------------------------------------------------------------ Reports


def test_reports_tab_variants_chain_and_pack(seeded_registers: Console) -> None:
    c = seeded_registers
    sid = system(c, agents=("payments", "credit_prequal"))
    html = body(page(c, sid, "reports"))
    for a in ("payments", "credit_prequal"):
        for v in ("regulator", "customer", "internal"):
            assert f"/v1/transparency/{a}?variant={v}&amp;format=pdf" in html
    assert html.count("<tr>") >= 6
    assert "agent:payments" in html and "agent:credit_prequal" in html
    assert "not verified" in html.lower()
    assert "/console/evidence" in html
    # a scoped reader sees no global pack count or file name
    assert ".zip" not in html and "packs on this server" not in html
    # a verified lane shows its state
    c.ctx.last_verify["agent:payments"] = {
        "ok": True,
        "ts": c.ctx.clock.now(),
        "lane": "agent:payments",
        "lines": [],
    }
    assert 'class="pill ok"' in body(page(c, sid, "reports"))


def test_reports_tab_lists_the_incidents_of_the_system(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from supervisor.governance.event_sources import GovernanceEvent

    sid = system(v3)
    other = system(v3, name="Other system")
    html = body(page(v3, sid, "reports"))
    assert "Incidents" in html and "not available" in html
    assert "GOVERNANCE_ACTIONS_ENABLED=1" in html  # the flag of WP-G5 is off
    monkeypatch.setattr(v3.ctx.settings, "governance_actions_enabled", True)
    at = datetime(2026, 10, 22, 11, 0, tzinfo=UTC)
    ev = GovernanceEvent("alert", "high", "payments", "alert:al_1", at, sid, rule_id="AL-X")
    row, _ = v3.ctx.incidents.open_from_event(ev)
    v3.ctx.incidents.open_from_event(
        GovernanceEvent("alert", "high", "payments", "alert:al_2", at, other, rule_id="AL-X")
    )
    iid = row["incident_id"]
    html = body(page(v3, sid, "reports"))
    assert 'id="system-incidents"' in html and iid in html and "alert:al_2" not in html
    assert f"/console/incidents?drawer={iid}&amp;status=all" in html  # the drawer of the tab
    assert "No incident" not in html
    n = re.search(
        r'data-tab="reports".*?<span class="k">(\d+)</span>', page(v3, sid, "reports"), re.S
    )
    assert n  # the count of the label is the rows of the tab (agents)
    vi = body(page(v3, sid, "reports", "vi"))
    assert iid in vi and "Mới" in vi  # status translated
    en = body(page(v3, sid, "reports"))
    assert "Open" in en and "high" in en.lower()
    empty = body(page(v3, system(v3, name="Quiet"), "reports"))
    assert "inc_" not in empty and "system-incidents" not in empty


def test_reports_tab_transparency_off(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v3.ctx.settings, "transparency_enabled", False)
    html = body(page(v3, system(v3), "reports"))
    assert "TRANSPARENCY_ENABLED=1" in html


# ------------------------------------------------------------------ labels


def test_vi_tabs_render_vietnamese(seeded_registers: Console) -> None:
    sid = system(seeded_registers)
    vi = page(seeded_registers, sid, "risks", "vi")
    assert "Rủi ro" in vi and "Thừa hưởng từ" in vi
    assert "Báo cáo" in page(seeded_registers, sid, "reports", "vi")
