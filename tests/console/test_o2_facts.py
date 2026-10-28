"""WP-O2 (phase 9): the Facts tab and panel (ONBOARD_FACTS) and the facts API.

Off path first: no tab, every route answers 400 with the flag name, nothing is written. Then the
agent tab, the Re-read button, the two audit rows per POST, the roles and the labels. The product
path with no model configured uses a labelled mock; one test swaps the gateway model for a scripted
stand-in (unit test only, owner decision 2)."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest

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


def zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in entries.items():
            zf.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "onboard_intake", True)
    monkeypatch.setattr(console.ctx.settings, "onboard_facts", True)
    return console


def upload(c: Console, node: str = "payments", entries: dict[str, str] | None = None) -> None:
    r = c.client.post(
        f"/console/intake/{node}",
        files={
            "file": (
                "s.zip",
                zip_bytes(entries or {"manifest.yaml": MANIFEST, "agent.py": AGENT}),
                "application/zip",
            )
        },
        headers={"X-Dev-User": "reviewer.an", **HX},
    )
    assert r.status_code == 200, r.text


def reread(c: Console, node: str = "payments", user: str = "reviewer.an") -> Any:
    return c.client.post(f"/console/facts/{node}", headers={"X-Dev-User": user, **HX})


def actions(c: Console, path: str) -> list[dict]:
    return [r for r in c.ctx.tables.query("console_action", order_by=("ts",)) if r["path"] == path]


# ------------------------------------------------------------------------------ off path


def test_flag_defaults_off(console: Console) -> None:
    assert console.ctx.settings.onboard_facts is False


def test_off_no_tab_and_every_route_is_400_with_the_flag_name(console: Console) -> None:
    page = console.get("/console/agents/payments")
    assert page.status_code == 200 and 'data-tab="facts"' not in page.text
    for url in ("/console/agents/payments?tab=facts", "/console/agents/payments/tab/facts"):
        r = console.get(url)
        assert r.status_code == 400 and "ONBOARD_FACTS=1" in r.text
    assert console.get("/console/facts/payments").status_code == 400
    r = reread(console)
    assert r.status_code == 400 and "ONBOARD_FACTS=1" in r.text
    h = {"X-Dev-User": "reviewer.an"}
    api = console.client.get("/v1/facts/payments", headers=h)
    assert api.status_code == 400 and "facts_off" in api.json()["error"]
    api = console.client.post("/v1/facts/payments/1", headers=h)
    assert api.status_code == 400 and "facts_off" in api.json()["error"]
    assert console.ctx.state.query("onboard_facts") == []


def test_off_with_intake_on_leaves_the_source_tab_as_before(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "onboard_intake", True)
    page = console.get("/console/agents/payments")
    assert 'data-tab="source"' in page.text and 'data-tab="facts"' not in page.text


# ------------------------------------------------------------------------------ the panel


def test_tab_is_there_and_empty_before_a_source_exists(on: Console) -> None:
    page = on.get("/console/agents/payments?tab=facts")
    assert page.status_code == 200
    assert 'data-tab="facts"' in page.text and 'data-section="facts"' in page.text
    assert 'data-empty="facts"' in page.text and 'hx-post="/console/facts/payments"' in page.text
    frag = on.get("/console/agents/payments/tab/facts")
    assert frag.status_code == 200 and "<html" not in frag.text and 'id="facts-panel"' in frag.text


def test_reread_without_a_source_is_400(on: Console) -> None:
    r = reread(on)
    assert r.status_code == 400 and "no_attempt" in r.text
    assert on.ctx.state.query("onboard_facts") == []


def test_reread_builds_the_card_grouped_with_pointers_and_a_dropped_line(on: Console) -> None:
    upload(on)
    r = reread(on)
    assert r.status_code == 200, r.text
    html = r.text
    for kind in ("tool", "dataset", "model", "weak_spot", "secret_use", "autonomy"):
        assert f'data-kind="{kind}"' in html, kind
    assert "refund_fee" in html and "main.synthetic.refunds" in html
    assert 'data-pointer="1"' in html and "agent.py:" in html and "manifest.yaml:" in html
    assert 'data-dropped="0"' in html and "0 claims dropped (no evidence)" in html
    assert 'data-facts-attempt="1"' in html and "Read from source attempt 1." in html
    assert 'data-action="reread"' in html and "Re-read" in html
    assert 'data-mock="1"' in html and "mock" in html  # no real model in the test setup
    assert AWS_KEY not in html and "[REDACTED:aws_access_key]" in html
    # the tab and the full page show the same card
    tab = on.get("/console/agents/payments?tab=facts")
    assert "refund_fee" in tab.text and "data-fact=" in tab.text
    full = on.get("/console/facts/payments")
    assert full.status_code == 200 and "<html" in full.text and "refund_fee" in full.text


def test_reread_shows_the_dropped_count_and_the_model_rows(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Scripted:
        family, model_id, is_mock = "fake", "fake-gateway-v1", False

        def complete_json(self, messages: Any, schema: Any, timeout_s: float) -> dict:
            return {
                "claims": [
                    {
                        "claim": "refund_fee has no amount check",
                        "category": "weak_spot",
                        "file": "agent.py",
                        "line": 5,
                        "quote": "def refund_fee(account_id",
                    },
                    {"claim": "No evidence at all", "category": "weak_spot"},
                    {
                        "claim": "Wrong quote",
                        "category": "weak_spot",
                        "file": "agent.py",
                        "line": 2,
                        "quote": "nothing like this on the line",
                    },
                ]
            }

    monkeypatch.setattr("supervisor.adapters.factory.make_chat_model", lambda settings: Scripted())
    upload(on)
    html = reread(on).text
    assert 'data-dropped="2"' in html and "2 claims dropped (no evidence)" in html
    assert 'data-mock="1"' not in html and "model: fake-gateway-v1" in html
    assert "refund_fee has no amount check" in html


def test_a_newer_attempt_asks_for_a_reread(on: Console) -> None:
    upload(on)
    reread(on)
    upload(on, entries={"agent.py": "x = 1\n"})
    html = on.get("/console/agents/payments/tab/facts").text
    assert 'data-newer="1"' in html and "attempt 2 is newer: press Re-read" in html
    html = reread(on).text
    assert 'data-newer="1"' not in html and 'data-facts-attempt="2"' in html


def test_two_audit_rows_per_post_console_and_api(on: Console) -> None:
    upload(on)
    reread(on)
    rows = actions(on, "/console/facts/payments")
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert {r["permission"] for r in rows} == {"systems.edit"}
    assert rows[1]["target_kind"] == "node" and rows[1]["target_id"] == "payments"
    assert rows[1]["after_hash"] != rows[1]["before_hash"]
    assert rows[1]["detail"].startswith("attempt=1 facts=")
    h = {"X-Dev-User": "reviewer.an"}
    api = on.client.post("/v1/facts/payments/1", headers=h)
    assert api.status_code == 201
    body = api.json()
    assert "rows" not in body and body["attempt_n"] == 1 and body["total"] > 5
    assert [r["outcome"] for r in actions(on, "/v1/facts/payments/1")] == ["attempted", "ok"]
    got = on.client.get("/v1/facts/payments", headers=h).json()
    assert got["attempt_n"] == 1 and {g["kind"] for g in got["groups"]} >= {"tool", "dataset"}
    assert all(r["file"] and r["line"] and r["quote"] for g in got["groups"] for r in g["rows"])


def test_api_refusals_are_400_not_500(on: Console) -> None:
    h = {"X-Dev-User": "reviewer.an"}
    r = on.client.post("/v1/facts/payments/9", headers=h)
    assert r.status_code == 400 and "no_attempt" in r.json()["error"]
    upload(on)
    assert on.client.post("/v1/facts/payments/9", headers=h).status_code == 400
    assert on.client.post("/v1/facts/bad id/1", headers=h).status_code in (400, 404)
    assert [x["outcome"] for x in actions(on, "/v1/facts/payments/9")][-1] == "error"


def test_console_post_without_htmx_is_refused(on: Console) -> None:
    upload(on)
    r = on.client.post("/console/facts/payments", headers={"X-Dev-User": "reviewer.an"})
    assert r.status_code == 400 and on.ctx.state.query("onboard_facts") == []


# ------------------------------------------------------------------------------ roles


def test_view_only_role_sees_the_card_but_not_the_button(on: Console) -> None:
    upload(on)
    reread(on)
    page = on.get("/console/agents/payments/tab/facts", user="auditor.dung")
    assert page.status_code == 200 and "data-fact=" in page.text
    assert 'hx-post="/console/facts/payments"' not in page.text
    api = on.client.get("/v1/facts/payments", headers={"X-Dev-User": "auditor.dung"})
    assert api.status_code == 200


def test_build_needs_systems_edit(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    upload(on)
    monkeypatch.setattr(on.ctx.settings, "api_rbac_enabled", True)
    r = reread(on, user="auditor.dung")
    assert r.status_code == 403 and "needs role" in r.text
    api = on.client.post("/v1/facts/payments/1", headers={"X-Dev-User": "auditor.dung"})
    assert api.status_code == 403
    assert on.ctx.state.query("onboard_facts") == []


# ------------------------------------------------------------------------------ secrets, labels


def test_planted_secret_is_in_no_page_row_or_audit_row(on: Console) -> None:
    upload(on)
    html = reread(on).text
    dump = json.dumps([dict(x) for x in on.ctx.state.query("onboard_facts")], default=str)
    dump += json.dumps([dict(x) for x in on.ctx.tables.query("console_action")], default=str)
    dump += on.client.get("/v1/facts/payments", headers={"X-Dev-User": "reviewer.an"}).text
    assert AWS_KEY not in html and AWS_KEY not in dump


def test_vi_labels_exist(on: Console) -> None:
    upload(on)
    reread(on)
    html = on.get("/console/agents/payments/tab/facts?lang=vi").text
    assert "Dữ kiện" in html and "Đọc lại" in html and "khẳng định bị loại" in html
    assert "Công cụ" in html
