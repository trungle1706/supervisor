"""WP-UX4b: My overview and Governance overview count systems when GOVERNANCE_ENABLED is on, and
the Catalogues > Agents page gets its System column and the unlinked filter.

Every number is compared with the service it comes from. The agent-based path (governance off)
is tested in test_ux4b_off.py."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest

from supervisor.console import systems_overview
from tests.conftest import REPO_ROOT

from .conftest import Console, add_agent, draft

OWNER_USER = "payops-lead@example.invalid"
BIGNUM = r'data-num="{key}">\s*<h3>[^<]+</h3>\s*<div class="bignum"[^>]*>(\d+)'
FLAGS = (
    "console_nav_v3",
    "risk_register_enabled",
    "console_risks_enabled",
    "controls_enabled",
    "console_controls_enabled",
    "console_compliance_enabled",
)


@pytest.fixture
def v3(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for f in FLAGS:
        monkeypatch.setattr(on.ctx.settings, f, True)
    return on


def make(
    c: Console, name: str, user: str = "reviewer.an", team: str = "payments-team", **over: Any
) -> dict[str, Any]:
    return c.ctx.systems.register(draft(name=name, owner_user=user, owner_team=team, **over), user)


def main(html: str) -> str:
    return html.split('id="main"', 1)[1].split("</main>", 1)[0]


def num(html: str, key: str) -> int:
    m = re.search(BIGNUM.format(key=key), html)
    assert m, key
    return int(m.group(1))


def pct_title(html: str, key: str) -> tuple[int, int]:
    m = re.search(
        rf'data-num="{key}">.*?<div class="bignum" title="(\d+) bp">(\d+)%</div>', html, re.S
    )
    assert m, key
    return int(m.group(1)), int(m.group(2))


# ------------------------------------------------------------------ My overview


def test_my_overview_counts_systems_by_scope(v3: Console) -> None:
    a = make(v3, "Alpha")
    b = make(v3, "Beta")
    make(v3, "Gamma", user="other.person", team="risk-team")
    v3.ctx.systems.update_fields(a["system_id"], {"risk_level": "high"}, "x")
    v3.ctx.systems.update_fields(b["system_id"], {"risk_level": "medium"}, "x")

    html = main(v3.get("/console/?lang=en").text)  # the default scope is mine: owns two
    assert 'data-unit="systems"' in html and 'data-num="systems"' in html
    assert num(html, "systems") == 2
    assert "1 High · 1 Medium" in re.sub(r"\s+", " ", html)
    assert "Health of my systems" in html and "Alpha" in html and "Beta" in html
    assert "Gamma" not in html
    assert num(main(v3.get("/console/?scope=my&lang=en").text), "systems") == 2
    assert num(main(v3.get("/console/?scope=team&lang=en").text), "systems") == 2
    allv = main(v3.get("/console/?scope=all&lang=en").text)
    assert num(allv, "systems") == 3 and "Gamma" in allv
    r = v3.get("/console/?scope=zzz")
    assert r.status_code == 400 and "scope must be" in r.text


def test_my_overview_scope_follows_the_role_filter(v3: Console) -> None:
    make(v3, "Alpha")
    make(v3, "Owned by lead", user=OWNER_USER, team="Payments Ops")
    make(v3, "Hidden", user="other.person", team="risk-team")
    # the owner role sees its own team's systems only, even with scope all
    html = main(v3.get("/console/?scope=all&lang=en", user=OWNER_USER).text)
    assert num(html, "systems") == 1 and "Owned by lead" in html
    assert "Alpha" not in html and "Hidden" not in html


def test_my_overview_numbers_are_integers_or_not_available(v3: Console) -> None:
    make(v3, "Alpha")
    html = main(v3.get("/console/?scope=all&lang=en").text)
    for key in ("models", "cover", "actions"):
        assert f'data-num="{key}"' in html
    for big in re.findall(r'<div class="bignum"[^>]*>(.*?)</div>', html, re.S):
        text = re.sub(r"<[^>]+>", "", big).strip()
        assert re.fullmatch(r"\d+\+?|\d+ / \d+|\d+%|not available", text), text


def test_guardian_cover_counts_systems_with_all_agents_covered(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = v3.ctx.settings
    sid = make(v3, "Covered?")["system_id"]
    v3.ctx.systems.link(sid, "agent", "payments", "x")
    make(v3, "No agent yet")
    monkeypatch.setattr(s, "detectors_enabled", False)
    off = main(v3.get("/console/?scope=all&lang=en").text)
    assert re.search(r"0 / 1", off) and "DETECTORS_ENABLED=1" in off and "1 without an agent" in off
    assert "below floor" in off
    monkeypatch.setattr(s, "detectors_enabled", True)
    on = main(v3.get("/console/?scope=all&lang=en").text)
    # the mandatory detectors come from the file; the demo agents carry the same overrides as the
    # Supervisor overview shows
    from supervisor.console import overview_v3

    cov = overview_v3.cover_for(v3.ctx, [{"agent_id": "payments"}])
    assert f"{1 if cov['covered'] else 0} / 1" in on


def test_health_row_next_action_is_the_first_open_required_task(v3: Console) -> None:
    sid = make(v3, "With tasks")["system_id"]
    me = v3.ctx.provider.users["reviewer.an"]
    from supervisor.console import systems_wizard

    systems_wizard.open_tasks(v3.ctx, sid, "reviewer.an")
    html = main(v3.get("/console/?scope=all&lang=en").text)
    row = html.split("With tasks", 1)[1].split("</tr>", 1)[0]
    assert "Confirm the intake answers" in row or "Review the preliminary checks" in row
    assert systems_overview.actions(v3.ctx, me)["tasks"] == 2


def test_open_actions_include_stage_approvals_and_match_the_badge(v3: Console) -> None:
    a = make(v3, "Moving", user="reviewer.an")
    stage = next(
        s
        for s in ("validation", "design", "deployment", "operation")
        if v3.ctx.lifecycle.needs_approval(s)
    )
    v3.ctx.lifecycle.request(a["system_id"], stage, "reviewer.an")
    # an approver who is neither the owner nor the requester may answer it
    html = v3.get("/console/?lang=en", user="approver.em").text
    approver = v3.ctx.provider.users["approver.em"]
    assert systems_overview.actions(v3.ctx, approver)["stages"] == 1
    assert "Stage move" in html and "Moving" in html
    tile = num(main(html), "actions")
    side = html.split('<aside class="side side-v3"', 1)[1].split("</aside>", 1)[0]
    badge = re.search(r'My overview <span class="k (?:hot)?">(\d+)</span>', side)
    assert badge and int(badge.group(1)) == tile >= 1
    # the requester cannot answer their own request
    assert systems_overview.actions(v3.ctx, v3.ctx.provider.users["reviewer.an"])["stages"] == 0


def test_my_overview_vi(v3: Console) -> None:
    make(v3, "Alpha")
    html = v3.get("/console/?lang=vi").text
    assert "Hệ thống trong phạm vi" in html and "Tình trạng các hệ thống của tôi" in html


# ------------------------------------------------------------------ Governance overview


def test_governance_overview_classification_rate_is_a_basis_point_figure(v3: Console) -> None:
    a = make(v3, "Alpha")
    make(v3, "Beta")
    make(v3, "Gamma")
    row = v3.ctx.state.get("ai_system", {"system_id": a["system_id"]})  # a person applied it
    v3.ctx.state.update(
        "ai_system",
        {"system_id": a["system_id"]},
        {"decision33_class": "high_risk"},
        row["row_version"],
    )
    html = main(v3.get("/console/governance?scope=all&lang=en").text)
    assert num(html, "systems") == 3
    bp, pct = pct_title(html, "classified")
    assert bp == 1 * 10000 // 3 == 3333 and pct == 33
    assert "1 of 3 systems" in html
    assert "Aggregated over the systems you may view: 3 of 3." in html


def test_governance_overview_counts_stages_and_pending_approvals(v3: Console) -> None:
    a = make(v3, "Alpha")
    make(v3, "Beta")
    stage = next(
        s
        for s in ("validation", "design", "deployment", "operation")
        if v3.ctx.lifecycle.needs_approval(s)
    )
    v3.ctx.lifecycle.request(a["system_id"], stage, "reviewer.an")
    html = main(v3.get("/console/governance?scope=all&lang=en").text)
    table = re.search(r'data-table="stages">(.*?)</table>', html, re.S)
    assert table
    rows = re.findall(r"<tr><td>([^<]+)</td><td>(\d+)</td><td>([^<]+)</td>", table.group(1))
    assert rows == [("Initiation", "2", "1")]  # two systems, one waits for a stage approval


def test_governance_overview_controls_readiness_per_system(
    v3: Console,
) -> None:
    ctx = v3.ctx
    assert ctx.risks.import_path(REPO_ROOT / "config" / "risks", "t", source="starter").errors == []
    assert (
        ctx.controls.import_path(REPO_ROOT / "config" / "controls", "t", source="starter").errors
        == []
    )
    ctx.controls.run_status()
    sid = make(v3, "Controlled")["system_id"]
    ctx.systems.link(sid, "agent", "payments", "x")
    make(v3, "Bare")
    html = main(v3.get("/console/governance?scope=all&lang=en").text)
    from supervisor.console import overview_v3

    latest, _ = overview_v3._latest_status(ctx, {"payments"})
    working = sum(1 for v in latest.values() if v == "working")
    assert latest
    bp, pct = pct_title(html, "readiness")
    assert bp == working * 10000 // len(latest) and pct == bp // 100
    table = re.search(r'data-table="readiness">(.*?)</table>', html, re.S)
    assert table and "Controlled" in table.group(1)
    assert f"<td>{working}</td><td>{len(latest)}</td>" in table.group(1)
    assert "Bare" in table.group(1)  # a system with no agent is listed, with no figure


def test_governance_overview_readiness_not_available_when_controls_are_off(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v3.ctx.settings, "controls_enabled", False)
    make(v3, "Alpha")
    html = main(v3.get("/console/governance?scope=all&lang=en").text)
    assert html.count("not available") >= 2 and "CONTROLS_ENABLED=1" in html


def test_governance_overview_overdue_counts_required_tasks_of_systems(v3: Console) -> None:
    from supervisor.console import systems_wizard

    sid = make(v3, "Late one")["system_id"]
    make(v3, "Fine")
    systems_wizard.open_tasks(v3.ctx, sid, "reviewer.an")
    html = main(v3.get("/console/governance?scope=all&lang=en").text)
    assert num(html, "overdue") == 0
    past = v3.ctx.clock.now() - dt.timedelta(days=9)
    for t in v3.ctx.state.query("task", {"agent_id": sid}):
        v3.ctx.state.update("task", {"task_id": t["task_id"]}, {"due_at": past}, t["row_version"])
    html = main(v3.get("/console/governance?scope=all&lang=en").text)
    assert num(html, "overdue") == 2 and "oldest 9 d" in html


def test_governance_overview_policy_rows_match_the_matrix(v3: Console) -> None:
    from supervisor.console import compliance_view

    sid = make(v3, "Policy one")["system_id"]
    v3.ctx.systems.link(sid, "agent", "payments", "x")
    html = main(v3.get("/console/governance?scope=all&lang=en").text)
    m = compliance_view.matrix_for(v3.ctx.settings, "payments")
    yes = [r for r in m["rows"] if r["applies"] == "yes"]
    met = sum(1 for r in yes if r["status"] == "met")
    table = re.search(r'data-table="policy">(.*?)</table>', html, re.S)
    assert table and "Policy one" in table.group(1)
    assert f"<td>{len(yes)}</td><td>{met}</td>" in table.group(1)


def test_governance_overview_risk_posture_follows_the_linked_agents(v3: Console) -> None:
    ctx = v3.ctx
    ctx.risks.import_path(REPO_ROOT / "config" / "risks", "t", source="starter")
    sid = make(v3, "Risky")["system_id"]
    ctx.systems.link(sid, "agent", "payments", "x")
    with_link = main(v3.get("/console/governance?scope=all&lang=en").text)
    active = [r for r in ctx.risks.agent_summary("payments")["risks"] if r["status"] == "active"]
    assert active
    n = sum(
        int(x)
        for x in re.findall(
            r"<tr><td><span class=\"pill[^\"]*\">[^<]+</span></td><td>(\d+)</td>", with_link
        )
    )
    assert n == len(active)
    # an unlinked agent's risks do not count: the system is the unit
    ctx.systems.unlink(
        sid, next(c["component_id"] for c in ctx.systems.get(sid)["components"]), "x"
    )
    without = main(v3.get("/console/governance?scope=all&lang=en").text)
    assert "No active risk in scope." in without


def test_autonomy_breakdown_counts_systems_by_level(v3: Console) -> None:
    a = make(v3, "Alpha")
    make(v3, "Beta")
    html = main(v3.get("/console/governance?scope=all&lang=en").text)
    assert 'data-section="autonomy"' in html and "<td>L1 Assistive</td><td>2</td>" in html
    v3.ctx.systems.update_fields(
        a["system_id"], {"autonomy_level": "l3_tool_using_supervised"}, "x"
    )
    html = main(v3.get("/console/governance?scope=all&lang=en").text)
    sec = html.split('data-section="autonomy"')[1].split("</section>")[0]
    assert re.search(r"L3 Uses tools, supervised</td><td>1</td>", sec)
    assert "<td>L1 Assistive</td><td>1</td>" in sec


def test_governance_overview_scoping_and_vi(v3: Console) -> None:
    make(v3, "Visible", user=OWNER_USER, team="Payments Ops")
    make(v3, "Hidden", user="other.person", team="risk-team")
    html = main(v3.get("/console/governance?scope=all&lang=en", user=OWNER_USER).text)
    assert num(html, "systems") == 1
    assert "3 of 3" not in html and "1 of 1" in html.replace("systems", "")
    vi = v3.get("/console/governance?scope=all&lang=vi").text
    assert "Hệ thống theo giai đoạn" in vi and "Mức sẵn sàng kiểm soát theo hệ thống" in vi
    assert v3.get("/console/governance?scope=zzz").status_code == 400


# ------------------------------------------------------------------ Catalogues > Agents


def test_agents_page_has_a_system_column_and_an_unlinked_filter(v3: Console) -> None:
    sid = make(v3, "Linker")["system_id"]
    v3.ctx.systems.link(sid, "agent", "payments", "x")
    html = v3.get("/console/agents?lang=en").text
    assert html.count('data-col="system"') == 3  # one cell per demo agent
    row = html.split('data-row="payments"', 1)[1].split("</tr>", 1)[0]
    assert f'href="/console/systems/{sid}?lang=en"' in row and "Linker" in row
    other = html.split('data-row="credit_prequal"', 1)[1].split("</tr>", 1)[0]
    assert "unlinked" in other
    assert '<th scope="col">System</th>' in html and 'name="system"' in html
    # the filter
    unl = v3.get(
        "/console/agents/rows?system=unlinked&lang=en", headers={"HX-Request": "true"}
    ).text
    assert 'data-row="payments"' not in unl
    assert 'data-row="credit_prequal"' in unl and 'data-row="customer_service"' in unl
    lnk = v3.get("/console/agents/rows?system=linked&lang=en", headers={"HX-Request": "true"}).text
    assert 'data-row="payments"' in lnk and 'data-row="credit_prequal"' not in lnk
    # the filter stays in the pager and sort links
    assert "system=unlinked" in unl
    r = v3.get("/console/agents/rows?system=zzz", headers={"HX-Request": "true"})
    assert r.status_code == 400 and "system must be" in r.text


def test_agents_column_hides_systems_outside_the_scope(v3: Console) -> None:
    secret = make(v3, "Secret", user="other.person", team="risk-team")["system_id"]
    v3.ctx.systems.link(secret, "agent", "payments", "x")
    html = v3.get("/console/agents?lang=en", user="viewer.hoa").text
    row = html.split('data-row="payments"', 1)[1].split("</tr>", 1)[0]
    assert "Secret" not in row and secret not in row
    assert "linked (another team)" in row  # linked, so not in the unlinked filter, but not named
    unl = v3.get(
        "/console/agents/rows?system=unlinked", user="viewer.hoa", headers={"HX-Request": "true"}
    ).text
    assert 'data-row="payments"' not in unl


def test_agents_system_column_needs_both_flags(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v3.ctx.settings, "governance_enabled", False)
    assert 'data-col="system"' not in v3.get("/console/agents").text
    monkeypatch.setattr(v3.ctx.settings, "governance_enabled", True)
    monkeypatch.setattr(v3.ctx.settings, "console_nav_v3", False)
    assert 'data-col="system"' not in v3.get("/console/agents").text


def test_agents_system_column_vi(v3: Console) -> None:
    add_agent(v3.ctx.runtime.adapters, "free_agent")
    html = v3.get("/console/agents?lang=vi").text
    assert "chưa liên kết" in html and "Hệ thống" in html
