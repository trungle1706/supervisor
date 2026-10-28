"""WP-O3 (phase 9): the Pre-deploy tab and panel (ONBOARD_PREDEPLOY) and the predeploy API.

Off path first: no tab, every route answers 400 ``predeploy_off``, nothing is written. Then the tab,
the panel with its items and pointers, the polling fragment while a run is going, Run again (htmx
only), the two audit rows per POST and the roles. The pack engine below is a scripted stand-in
(unit test only, owner decision 2); the facts step and the readiness advisor are the real ones."""

from __future__ import annotations

import io
import json
import threading
import zipfile
from collections.abc import Sequence
from typing import Any

import pytest

from supervisor.console import predeploy_routes
from supervisor.onboard import predeploy
from supervisor.onboard.facts import FactsService
from tests.onboard.test_predeploy import result

from .conftest import Console

HX = {"HX-Request": "true"}
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
MANIFEST = """id: payments
name: Payments helper
version: 0.1.0
owner: team-demo
description: Looks up synthetic payment fees.
model_id: qwen3.8-27b-int4
tools:
  - name: get_fee
    risk_class: read_only
  - name: refund_fee
    risk_class: money
"""
AGENT = f"""import httpx
KEY = "{AWS_KEY}"
def get_fee(account_id):
    return spark.sql("SELECT fee FROM main.synthetic.fees WHERE account_id = 1")
def refund_fee(account_id, amount_minor, payee_id):
    spark.sql("INSERT INTO main.synthetic.refunds VALUES (1)")
    return httpx.post("https://llm.example.invalid/v1/chat/completions", json={{}})
"""


class _Target:
    kind = "agent"
    is_mock = False

    def close(self) -> None:
        return None


def ok_executor(packs: Sequence[Any], *a: Any, **k: Any) -> list[Any]:
    return [result(p.id, "ok") for p in packs]


def zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in entries.items():
            zf.writestr(name, text)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clean_runs() -> Any:
    predeploy._RUNNING.clear()
    yield
    for th in list(predeploy._THREADS.values()):
        th.join(30)
    predeploy._RUNNING.clear()
    predeploy._THREADS.clear()


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in ("onboard_intake", "onboard_facts", "onboard_predeploy"):
        monkeypatch.setattr(console.ctx.settings, flag, True)
    holder: dict[str, Any] = {"executor": ok_executor}

    def service(ctx: Any) -> predeploy.PredeployService:
        return predeploy.PredeployService(
            ctx.settings,
            ctx.state,
            ctx.clock,
            ctx=ctx,
            executor=lambda *a, **k: holder["executor"](*a, **k),
            target_factory=lambda *a, **k: _Target(),
        )

    monkeypatch.setattr(predeploy_routes, "service", service)
    console.holder = holder  # type: ignore[attr-defined]
    return console


def upload(c: Console, node: str = "payments") -> None:
    r = c.client.post(
        f"/console/intake/{node}",
        files={
            "file": (
                "s.zip",
                zip_bytes({"manifest.yaml": MANIFEST, "agent.py": AGENT}),
                "application/zip",
            )
        },
        headers={"X-Dev-User": "reviewer.an", **HX},
    )
    assert r.status_code == 200, r.text


def build_facts(c: Console, node: str = "payments") -> None:
    FactsService(c.ctx.settings, c.ctx.state, c.ctx.clock).build(node, 1)


def run_again(c: Console, node: str = "payments", user: str = "reviewer.an") -> Any:
    return c.client.post(f"/console/predeploy/{node}", headers={"X-Dev-User": user, **HX})


def finish(c: Console, node: str = "payments") -> None:
    th = predeploy._THREADS.get(node)
    if th is not None:
        th.join(60)


def actions(c: Console, path: str) -> list[dict]:
    return [r for r in c.ctx.tables.query("console_action", order_by=("ts",)) if r["path"] == path]


# ------------------------------------------------------------------------------ off path


def test_flag_defaults_off(console: Console) -> None:
    assert console.ctx.settings.onboard_predeploy is False


def test_off_no_tab_and_every_route_is_400_predeploy_off(console: Console) -> None:
    page = console.get("/console/agents/payments")
    assert page.status_code == 200 and 'data-tab="predeploy"' not in page.text
    for url in ("/console/agents/payments?tab=predeploy", "/console/agents/payments/tab/predeploy"):
        r = console.get(url)
        assert r.status_code == 400 and "ONBOARD_PREDEPLOY=1" in r.text
    assert console.get("/console/predeploy/payments").status_code == 400
    r = run_again(console)
    assert r.status_code == 400 and "ONBOARD_PREDEPLOY=1" in r.text
    h = {"X-Dev-User": "reviewer.an"}
    api = console.client.get("/v1/predeploy/payments", headers=h)
    assert api.status_code == 400 and "predeploy_off" in api.json()["error"]
    api = console.client.post("/v1/predeploy/payments/1", headers=h)
    assert api.status_code == 400 and "predeploy_off" in api.json()["error"]
    assert console.ctx.state.query("predeploy_report") == []


def test_off_with_facts_on_leaves_the_facts_tab_as_before(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "onboard_facts", True)
    page = console.get("/console/agents/payments")
    assert 'data-tab="facts"' in page.text and 'data-tab="predeploy"' not in page.text


# ------------------------------------------------------------------------------ the panel


def test_tab_is_there_and_empty_before_a_report_exists(on: Console) -> None:
    page = on.get("/console/agents/payments?tab=predeploy")
    assert page.status_code == 200
    assert 'data-tab="predeploy"' in page.text and 'data-section="predeploy"' in page.text
    assert 'data-empty="predeploy"' in page.text
    assert 'hx-post="/console/predeploy/payments"' in page.text
    assert 'data-polling="1"' not in page.text
    frag = on.get("/console/agents/payments/tab/predeploy")
    assert frag.status_code == 200 and "<html" not in frag.text
    assert 'id="predeploy-panel"' in frag.text


def test_run_again_without_a_source_is_400(on: Console) -> None:
    r = run_again(on)
    assert r.status_code == 400 and "no_attempt" in r.text
    assert on.ctx.state.query("predeploy_report") == []


def test_run_again_starts_a_run_and_the_panel_shows_verdict_items_and_pointers(
    on: Console,
) -> None:
    upload(on)
    build_facts(on)
    r = run_again(on)
    assert r.status_code == 200, r.text
    assert 'id="predeploy-panel"' in r.text and "assessment of attempt 1 started" in r.text
    finish(on)
    html = on.get("/console/predeploy/payments", headers=HX).text
    assert 'data-verdict="questions"' in html  # the duties question is open (flag off)
    for section in ("facts", "readiness", "packs", "multiturn", "duties"):
        assert f'data-section-name="{section}"' in html
    assert 'data-item="duties:not_run"' in html and "duties: not run" in html
    assert 'data-pointer="1"' in html and "agent.py:" in html  # a weak spot with its pointer
    assert "pack prefilter_evasion" in html or "pack pii_canary" in html
    assert 'data-polling="1"' not in html  # finished: no more polling
    assert AWS_KEY not in html
    # the full page without htmx
    page = on.get("/console/predeploy/payments?lang=en")
    assert (
        page.status_code == 200 and "<html" in page.text and 'data-verdict="questions"' in page.text
    )


def test_a_required_pack_that_fails_gives_no_go_on_the_panel(on: Console) -> None:
    upload(on)
    build_facts(on)
    on.holder["executor"] = lambda packs, *a, **k: [  # type: ignore[attr-defined]
        result(p.id, "fail" if p.id == "pii_canary" else "ok", reasons=["unmasked_pii_count=3"])
        for p in packs
    ]
    run_again(on)
    finish(on)
    html = on.get("/console/predeploy/payments", headers=HX).text
    assert 'data-verdict="no_go"' in html and "NO-GO" in html
    assert 'data-item="pack:pii_canary"' in html and "unmasked_pii_count=3" in html


def test_while_running_the_panel_polls_itself_every_3_seconds(on: Console) -> None:
    upload(on)
    build_facts(on)
    gate, entered = threading.Event(), threading.Event()

    def slow(packs: Sequence[Any], *a: Any, **k: Any) -> list[Any]:
        entered.set()
        assert gate.wait(60)
        return ok_executor(packs)

    on.holder["executor"] = slow  # type: ignore[attr-defined]
    r = run_again(on)
    assert r.status_code == 200
    assert 'data-polling="1"' in r.text and 'hx-trigger="every 3s"' in r.text
    assert 'hx-get="/console/predeploy/payments' in r.text and "data-running" in r.text
    assert entered.wait(60)
    poll = on.get("/console/predeploy/payments", headers=HX).text
    assert 'hx-trigger="every 3s"' in poll and "<html" not in poll
    assert "disabled" in poll  # Run again cannot be pressed twice
    again = run_again(on)  # a second start while running
    assert again.status_code == 400 and "already_running" in again.text
    api = on.client.post("/v1/predeploy/payments/1", headers={"X-Dev-User": "reviewer.an"})
    assert api.status_code == 400 and "already_running" in api.json()["error"]
    gate.set()
    finish(on)
    done = on.get("/console/predeploy/payments", headers=HX).text
    assert "every 3s" not in done and "data-verdict=" in done


def test_two_audit_rows_per_post_console_and_api(on: Console) -> None:
    upload(on)
    build_facts(on)
    run_again(on)
    finish(on)
    rows = actions(on, "/console/predeploy/payments")
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert {r["permission"] for r in rows} == {"systems.edit"}
    assert rows[1]["target_kind"] == "node" and rows[1]["target_id"] == "payments"
    assert rows[1]["after_hash"] != rows[1]["before_hash"]
    assert rows[1]["detail"].startswith("attempt=1 report=pdr_")
    h = {"X-Dev-User": "reviewer.an"}
    api = on.client.post("/v1/predeploy/payments/1", headers=h)
    assert api.status_code == 202
    body = api.json()
    assert body["attempt_n"] == 1 and body["verdict"] in ("none", "questions", "go", "no_go")
    finish(on)
    assert [r["outcome"] for r in actions(on, "/v1/predeploy/payments/1")] == ["attempted", "ok"]
    got = on.client.get("/v1/predeploy/payments", headers=h).json()
    assert got["report_id"] == body["report_id"] and got["status"] == "done"
    assert {g["section"] for g in got["groups"]} == {
        "facts",
        "readiness",
        "packs",
        "multiturn",
        "duties",
    }
    assert all(i["pointer"] for i in got["items"])


def test_api_get_without_a_report_and_refusals_are_400_not_500(on: Console) -> None:
    h = {"X-Dev-User": "reviewer.an"}
    none = on.client.get("/v1/predeploy/payments", headers=h)
    assert none.status_code == 200 and none.json()["verdict"] == "none"
    r = on.client.post("/v1/predeploy/payments/9", headers=h)
    assert r.status_code == 400 and "no_attempt" in r.json()["error"]
    upload(on)
    assert on.client.post("/v1/predeploy/payments/9", headers=h).status_code == 400
    assert on.client.post("/v1/predeploy/bad id/1", headers=h).status_code in (400, 404)
    assert [x["outcome"] for x in actions(on, "/v1/predeploy/payments/9")][-1] == "error"


def test_console_post_without_htmx_is_refused(on: Console) -> None:
    upload(on)
    r = on.client.post("/console/predeploy/payments", headers={"X-Dev-User": "reviewer.an"})
    assert r.status_code == 400 and on.ctx.state.query("predeploy_report") == []


def test_a_newer_attempt_asks_for_run_again(on: Console) -> None:
    upload(on)
    build_facts(on)
    run_again(on)
    finish(on)
    upload(on)
    html = on.get("/console/predeploy/payments", headers=HX).text
    assert 'data-newer="1"' in html and "attempt 2 is newer: press Run again" in html


# ------------------------------------------------------------------------------ roles


def test_view_only_role_sees_the_report_but_not_the_button(on: Console) -> None:
    upload(on)
    build_facts(on)
    run_again(on)
    finish(on)
    page = on.get("/console/agents/payments/tab/predeploy", user="auditor.dung")
    assert page.status_code == 200 and "data-item=" in page.text
    assert 'hx-post="/console/predeploy/payments"' not in page.text
    api = on.client.get("/v1/predeploy/payments", headers={"X-Dev-User": "auditor.dung"})
    assert api.status_code == 200


def test_start_needs_systems_edit(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    upload(on)
    monkeypatch.setattr(on.ctx.settings, "api_rbac_enabled", True)
    r = run_again(on, user="auditor.dung")
    assert r.status_code == 403 and "needs role" in r.text
    api = on.client.post("/v1/predeploy/payments/1", headers={"X-Dev-User": "auditor.dung"})
    assert api.status_code == 403
    assert on.ctx.state.query("predeploy_report") == []


def test_rbac_routes_are_in_the_table() -> None:
    from supervisor.core.rbac import ROUTES

    assert ROUTES[("GET", "/v1/predeploy/{node_id}")] == "systems.view"
    assert ROUTES[("POST", "/v1/predeploy/{node_id}/{n}")] == "systems.edit"
    assert ROUTES[("GET", "/console/predeploy/{node_id}")] == "systems.view"
    assert ROUTES[("POST", "/console/predeploy/{node_id}")] == "systems.edit"


# ------------------------------------------------------------------------------ secrets, labels


def test_planted_secret_is_in_no_page_row_or_audit_row(on: Console) -> None:
    upload(on)
    build_facts(on)
    run_again(on)
    finish(on)
    dump = json.dumps([dict(x) for x in on.ctx.state.query("predeploy_report")], default=str)
    dump += json.dumps([dict(x) for x in on.ctx.tables.query("console_action")], default=str)
    dump += on.client.get("/v1/predeploy/payments", headers={"X-Dev-User": "reviewer.an"}).text
    assert AWS_KEY not in dump


def test_vi_labels_exist(on: Console) -> None:
    upload(on)
    build_facts(on)
    run_again(on)
    finish(on)
    html = on.get("/console/agents/payments/tab/predeploy?lang=vi").text
    assert "Trước triển khai" in html and "Chạy lại" in html and "Kết luận" in html
    assert "Nghĩa vụ" in html
