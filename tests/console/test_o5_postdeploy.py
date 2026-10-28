"""WP-O5 (phase 9): the Post-deploy tab and panel (ONBOARD_POSTDEPLOY), the JSON route, the agent
log timeline, the link from the Request RUNNING panel and the hooks of the two console actions.

Off path first: no tab, every route answers 400 ``postdeploy_off``, no log row is written."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest

from supervisor.console import agent_guardians
from supervisor.core.schema import load_model

from .conftest import Console

HX = {"HX-Request": "true"}
MODEL = load_model()
NAME = "Nguyễn Văn Anh"
PHONE = "0912345678"


def row(table: str, **values: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "string": "x",
        "text": "x",
        "int": 0,
        "bool": False,
        "json": "{}",
        "money": 0,
        "date": dt.date(2026, 10, 1),
        "timestamp": dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    }
    out: dict[str, Any] = {}
    for col in MODEL.table(table).columns:
        if col.name in values:
            out[col.name] = values[col.name]
        elif col.nullable:
            out[col.name] = None
        else:
            out[col.name] = defaults[col.type.rstrip("?")]
    return out


def add(c: Console, table: str, **values: Any) -> None:
    full = row(table, **values)
    if MODEL.table(table).kind == "state":
        c.ctx.state.insert(table, full)
    else:
        c.ctx.tables.append(table, [full])


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "onboard_postdeploy", True)
    return console


def panel(c: Console, node: str = "payments", user: str = "reviewer.an", q: str = "") -> Any:
    return c.get(f"/console/postdeploy/{node}{q}", user=user, headers=HX)


def log_rows(c: Console, **where: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in c.ctx.tables.query("onboard_log", where or None, order_by=("at",))]


# ------------------------------------------------------------------------------ off path


def test_flag_defaults_off(console: Console) -> None:
    assert console.ctx.settings.onboard_postdeploy is False


def test_off_no_tab_and_every_route_is_400_postdeploy_off(console: Console) -> None:
    page = console.get("/console/agents/payments")
    assert page.status_code == 200 and 'data-tab="postdeploy"' not in page.text
    for url in (
        "/console/agents/payments?tab=postdeploy",
        "/console/agents/payments/tab/postdeploy",
    ):
        r = console.get(url)
        assert r.status_code == 400 and "ONBOARD_POSTDEPLOY=1" in r.text
    for url in ("/console/postdeploy/payments", "/v1/postdeploy/payments"):
        r = console.get(url)
        assert r.status_code == 400 and "postdeploy_off" in r.text, url


def test_off_the_two_console_actions_write_no_log_row(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "onboard_attach_view", True)
    monkeypatch.setattr(console.ctx.settings, "console_state_actions", True)
    console.ctx.gateway.states.set_mode("payments", "SHADOW", "admin.chi")
    r = console.post("/console/attach/payments/check")
    assert r.status_code == 200
    r = console.post("/console/agents/payments/running/request", {"reason": "go live"})
    assert r.status_code == 200
    assert log_rows(console) == []


def test_off_the_running_panel_has_no_link(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_state_actions", True)
    console.ctx.gateway.states.set_mode("payments", "SHADOW", "admin.chi")
    html = console.get("/console/agents/payments").text
    assert 'data-section="mode"' in html and "data-postdeploy-link" not in html


# ------------------------------------------------------------------------------ the tab


def test_tab_is_there_when_on_and_comes_after_attach(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    for flag in ("onboard_intake", "onboard_facts", "onboard_predeploy", "onboard_attach_view"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    page = on.get("/console/agents/payments?tab=postdeploy")
    assert page.status_code == 200
    assert 'data-tab="postdeploy"' in page.text and 'data-section="postdeploy"' in page.text
    tabs = re.findall(r'data-tab="([a-z_]+)"', page.text)
    assert tabs.index("attach") + 1 == tabs.index("postdeploy")
    frag = on.get("/console/agents/payments/tab/postdeploy")
    assert frag.status_code == 200 and "<html" not in frag.text
    assert 'id="postdeploy-panel"' in frag.text


def test_full_page_without_htmx_and_fragment_with(on: Console) -> None:
    full = on.get("/console/postdeploy/payments")
    assert full.status_code == 200 and "<html" in full.text and 'id="postdeploy-panel"' in full.text
    frag = panel(on)
    assert frag.status_code == 200 and "<html" not in frag.text


def test_bad_node_id_and_bad_days_are_400(on: Console) -> None:
    r = on.get("/console/postdeploy/bad%20id")
    assert r.status_code == 400 and "bad_node_id" in r.text
    for q in ("?days=0", "?days=91", "?days=abc"):
        r = panel(on, q=q)
        assert r.status_code == 400 and "bad_days" in r.text, q
        r = on.get(f"/v1/postdeploy/payments{q}")
        assert r.status_code == 400 and "bad_days" in r.text, q


def test_the_panel_shows_the_window_in_days(on: Console) -> None:
    assert 'data-section="postdeploy"' in panel(on, q="?days=30").text
    assert ">30d<" in panel(on, q="?days=30").text and ">7d<" in panel(on).text


# ------------------------------------------------------------------------------ the figures


def test_gate_numbers_are_the_ones_of_the_guardians_tab(on: Console) -> None:
    since = on.ctx.clock.now() - dt.timedelta(days=7)
    want = agent_guardians._gate_results(on.ctx, "payments", since)
    html = panel(on).text
    for key in ("checks", "allowed", "blocked", "paused", "would_block"):
        assert f'data-num="{key}">{want[key]}<' in html, key
    assert want["checks"] > 0  # the seeded demo replay has gate decisions


def test_mock_judge_verdicts_are_counted_apart_and_labelled(on: Console) -> None:
    now = on.ctx.clock.now()
    for i, (mock, label) in enumerate([(False, "fraud"), (True, "fraud"), (True, "benign")]):
        add(
            on,
            "verdict",
            verdict_id=f"vpx{i}".ljust(32, "0"),
            ts=now - dt.timedelta(minutes=i + 1),
            agent_id="newjudge",
            tier=2,
            label=label,
            action="alert",
            is_mock=mock,
            advisory=True,
        )
    html = panel(on, node="newjudge").text
    cell = re.search(r'<tr class="row" data-tier="2">(.*?)</tr>', html, re.S)
    assert cell
    nums = re.findall(r'<td class="n">(\d+)', cell.group(1))
    assert nums == ["1", "1", "2", "2"]  # real, real flagged, mock, mock flagged
    assert "MOCK" in cell.group(1)


def test_incidents_packs_and_drift_show(on: Console) -> None:
    now = on.ctx.clock.now()
    add(on, "incident", incident_id="inc_px1", agent_id="px", status="open", opened_at=now)
    add(
        on,
        "eval_result",
        run_id="runpx1",
        ts=now,
        pack_id="pii_leak",
        target_kind="traces",
        target_id="px",
        status="ok",
        n_items=9,
    )
    add(
        on,
        "oversight_metric",
        metric_date=now.date(),
        agent_id="px",
        computed_at=now,
        monitor_status='{"drift": {"status": "ok", "n": 5}}',
    )
    html = panel(on, node="px").text
    assert 'data-num="open">1<' in html
    assert 'data-pack="pii_leak"' in html
    assert re.search(r'data-monitor="drift".*?ok', html, re.S)
    assert re.search(r'data-monitor="session".*?no status yet', html, re.S)


def test_pre_deploy_verdict_on_the_left_when_that_flag_is_on(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert 'data-empty="predeploy-off"' in panel(on).text
    monkeypatch.setattr(on.ctx.settings, "onboard_predeploy", True)
    assert 'data-empty="predeploy"' in panel(on).text
    now = on.ctx.clock.now()
    add(
        on,
        "predeploy_report",
        report_id="pdr_px1",
        node_id="px",
        attempt_n=1,
        status="done",
        verdict="no_go",
        started_at=now,
        finished_at=now,
        items_total=1,
        items_fail=1,
        summary="verdict no_go: 1 items",
        items='[{"section": "packs", "id": "pack:x", "status": "fail",'
        ' "text": "pack x: fail", "pointer": "pack x"}]',
        created_by="an",
        created_at=now,
    )
    html = panel(on, node="px").text
    left = html.split('data-col="before"', 1)[1].split('data-col="after"', 1)[0]
    assert 'data-verdict="no_go"' in left and "pack x: fail" in left


def test_the_json_route_has_the_three_parts_and_no_float(on: Console) -> None:
    r = on.get("/v1/postdeploy/payments")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"node_id", "assessment", "predeploy", "agent_log"}
    assert body["assessment"]["agent_id"] == "payments" and body["predeploy"] is None

    def floats(v: Any) -> list[float]:
        if isinstance(v, float):
            return [v]
        if isinstance(v, dict):
            return [x for i in v.values() for x in floats(i)]
        if isinstance(v, list):
            return [x for i in v for x in floats(i)]
        return []

    assert floats(body) == []


# ------------------------------------------------------------------------------ the agent log


def test_agent_log_timeline_plan_read_found_suggest_with_pills(on: Console) -> None:
    from supervisor.onboard import agent_log

    c = on.ctx
    for step, kind, actor in [
        ("scan", "rule", "rule"),
        ("intake", "person", "an"),
        ("facts", "model", "qwen-x"),
        ("predeploy", "rule", "rule"),
        ("state", "person", "an"),
    ]:
        agent_log.log(c, "pxlog", step, f"{step} happened", f"ptr {step}", kind, actor)
    html = panel(on, node="pxlog").text
    block = html.split('data-block="agent-log"', 1)[1]
    items = re.findall(r'<li data-step="(\w+)" data-phase="(\w+)" data-by="(\w+)"', block)
    assert items == [
        ("scan", "plan", "rule"),
        ("intake", "read", "person"),
        ("facts", "read", "model"),
        ("predeploy", "found", "rule"),
        ("state", "suggest", "person"),
    ]
    assert 'data-pointer="1">ptr facts' in block
    # the same rows are in the timeline of the node as agent_log events, newest first
    assert html.count('data-kind="agent_log"') == 5
    body = on.get("/v1/postdeploy/pxlog").json()
    assert [r["step"] for r in body["agent_log"]] == [
        "scan",
        "intake",
        "facts",
        "predeploy",
        "state",
    ]
    assert body["agent_log"][2]["phase"] == "read"


def test_empty_log_says_so(on: Console) -> None:
    assert 'data-empty="agent-log"' in panel(on, node="nothing").text


# ------------------------------------------------------------------------------ hooks


def test_attach_check_now_writes_a_person_row(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "onboard_attach_view", True)
    r = on.post("/console/attach/payments/check", user="reviewer.an")
    assert r.status_code == 200
    (got,) = log_rows(on, node_id="payments", step="attach")
    assert (got["by_kind"], got["actor"]) == ("person", "reviewer.an")
    assert "guardians have evidence" in got["what"]


def test_request_and_approve_running_write_person_rows_without_the_reason(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "console_state_actions", True)
    on.ctx.gateway.states.set_mode("payments", "SHADOW", "admin.chi")
    reason = f"{NAME} {PHONE} asked for it"
    r = on.post("/console/agents/payments/running/request", {"reason": reason}, user="reviewer.an")
    assert r.status_code == 200, r.text
    r = on.post(
        "/console/agents/payments/running/approve", {"reason": reason}, user="reviewer.binh"
    )
    assert r.status_code == 200, r.text
    got = log_rows(on, node_id="payments", step="state")
    assert [(g["by_kind"], g["actor"]) for g in got] == [
        ("person", "reviewer.an"),
        ("person", "reviewer.binh"),
    ]
    assert [g["what"] for g in got] == ["RUNNING requested", "RUNNING approved"]
    assert all(PHONE not in str(g) and "Văn Anh" not in str(g) for g in got)


def test_a_refused_running_step_writes_no_row(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "console_state_actions", True)
    on.ctx.gateway.states.set_mode("payments", "SHADOW", "admin.chi")
    r = on.post("/console/agents/payments/running/approve", {"reason": "x"}, user="reviewer.an")
    assert r.status_code == 400 and "no_request" in r.text
    assert log_rows(on, step="state") == []


def test_a_log_failure_does_not_fail_check_now(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "onboard_attach_view", True)

    def boom(table: str, rows: Any) -> int:
        if table == "onboard_log":
            raise RuntimeError("down")
        return real(table, rows)

    real = on.ctx.tables.append
    monkeypatch.setattr(on.ctx.tables, "append", boom)
    assert on.post("/console/attach/payments/check").status_code == 200


# ------------------------------------------------------------------------------ RUNNING link


def test_running_panel_links_to_the_postdeploy_tab(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "console_state_actions", True)
    on.ctx.gateway.states.set_mode("payments", "SHADOW", "admin.chi")
    html = on.get("/console/agents/payments").text
    card = html.split('data-agent="payments"', 1)[1].split("</article>", 1)[0]
    assert "data-postdeploy-link" in card
    assert "/console/agents/payments?tab=postdeploy" in card
    assert "Review the post-deploy assessment first" in card
    link = re.search(r'href="(/console/agents/payments\?tab=postdeploy[^"]*)"', card)
    assert link
    page = on.get(link.group(1).replace("&amp;", "&"))
    assert page.status_code == 200 and 'data-section="postdeploy"' in page.text


# ------------------------------------------------------------------------------ roles


def test_every_role_may_view(on: Console) -> None:
    for user in ("viewer.hoa", "auditor.dung", "approver.em", "reviewer.an", "admin.chi"):
        assert panel(on, user=user).status_code == 200, user
        assert on.get("/v1/postdeploy/payments", user=user).status_code == 200, user


def test_the_page_is_read_only(on: Console) -> None:
    before = len(on.ctx.tables.query("console_action"))
    assert panel(on).status_code == 200
    assert len(on.ctx.tables.query("console_action")) == before
    assert "<form" not in panel(on).text


def test_routes_are_in_the_permission_table() -> None:
    from supervisor.core import rbac

    assert rbac.ROUTES[("GET", "/console/postdeploy/{node_id}")] == "systems.view"
    assert rbac.ROUTES[("GET", "/v1/postdeploy/{node_id}")] == "systems.view"
