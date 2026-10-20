"""WP31: /v1/transparency routes (RBAC, audit, errors), the Transparency page, drawer and tab.

Both flags are off by default (HTTP 400 with the flag name, no nav entry). Every role reads;
reviewer and admin generate; a generate writes two console_action rows and the chain record."""

from __future__ import annotations

import json

import pytest

from supervisor.inventory.service import InventoryService

from .conftest import Console

HX = {"HX-Request": "true"}


@pytest.fixture
def tp_on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    s = console.ctx.settings
    for flag in ("transparency_enabled", "console_transparency_enabled", "inventory_enabled"):
        monkeypatch.setattr(s, flag, True)
    InventoryService.from_adapters(console.runtime.adapters).fill_manifests()
    return console


def test_off_by_default(console: Console) -> None:
    s = console.ctx.settings
    assert s.transparency_enabled is False and s.console_transparency_enabled is False
    for url in ("/v1/transparency", "/v1/transparency/payments"):
        r = console.get(url)
        assert r.status_code == 400 and "TRANSPARENCY_ENABLED" in r.json()["error"], url
    r = console.get("/console/transparency")
    assert r.status_code == 400 and "CONSOLE_TRANSPARENCY_ENABLED" in r.text
    assert "/console/transparency" not in console.get("/console/").text
    assert console.get("/console/agents/payments/tab/transparency", headers=HX).status_code == 400


def test_generate_then_read_every_format(tp_on: Console) -> None:
    r = tp_on.client.post(
        "/v1/transparency/payments/generate", json={}, headers={"X-Dev-User": "reviewer.an"}
    )
    assert r.status_code == 200, r.text
    assert {x["status"] for x in r.json()["results"]} == {"made"}
    j = tp_on.get("/v1/transparency/payments?variant=regulator&format=json")
    assert j.status_code == 200 and j.headers["x-report-status"] == "signed"
    body = json.loads(j.text)
    assert body["agent_id"] == "payments" and body["report_version"] == 1
    assert j.headers["x-report-sha256"] == __import__("hashlib").sha256(j.content).hexdigest()
    h = tp_on.get("/v1/transparency/payments?variant=customer&format=html&lang=vi")
    assert h.status_code == 200 and "text/html" in h.headers["content-type"]
    assert "payments" not in h.text.replace("executes_payments", "")
    p = tp_on.get("/v1/transparency/payments?variant=internal&format=pdf&lang=en")
    assert p.status_code == 200 and p.content.startswith(b"%PDF")
    audit = [
        r
        for r in tp_on.ctx.tables.query("console_action", order_by=("ts",))
        if r["permission"] == "transparency.generate"
    ]
    assert [a["outcome"] for a in audit] == ["attempted", "ok"]


def test_rbac_and_bad_input(tp_on: Console) -> None:
    viewer = "viewer.hoa"
    assert tp_on.get("/v1/transparency/payments?variant=customer", user=viewer).status_code == 200
    denied = tp_on.client.post(
        "/v1/transparency/payments/generate", json={}, headers={"X-Dev-User": viewer}
    )
    assert denied.status_code == 403
    assert tp_on.get("/v1/transparency/payments?variant=everyone").status_code == 400
    assert tp_on.get("/v1/transparency/payments?format=docx").status_code == 400
    assert tp_on.get("/v1/transparency/payments?lang=fr").status_code == 400
    assert tp_on.get("/v1/transparency/no_such_agent").status_code == 404
    bad = tp_on.client.post(
        "/v1/transparency/payments/generate",
        content=b"[1]",
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert bad.status_code == 400


def test_page_drawer_generate_button_and_tab(tp_on: Console) -> None:
    page = tp_on.get("/console/transparency")
    assert page.status_code == 200 and "payments" in page.text
    assert "/console/transparency" in tp_on.get("/console/").text
    assert "Generate" in page.text  # reviewer sees the button
    assert "Generate" not in tp_on.get("/console/transparency", user="viewer.hoa").text
    d = tp_on.get("/console/transparency/payments/drawer?variant=regulator", headers=HX)
    assert d.status_code == 200 and "VN-QD33-2026" in d.text
    assert (
        tp_on.get("/console/transparency/payments/drawer?variant=x", headers=HX).status_code == 400
    )
    assert tp_on.get("/console/transparency?drawer=payments&variant=customer").status_code == 200
    gen = tp_on.post("/console/transparency/payments/generate")
    assert gen.status_code == 200 and "v1" in gen.text
    again = tp_on.post("/console/transparency/payments/generate")
    assert again.status_code == 200 and "Nothing changed" in again.text
    assert (
        tp_on.post("/console/transparency/payments/generate", user="viewer.hoa").status_code == 403
    )
    tab = tp_on.get("/console/agents/payments/tab/transparency", headers=HX)
    assert tab.status_code == 200 and "v1" in tab.text
    vi = tp_on.get("/console/transparency?lang=vi")
    assert "Minh bạch" in vi.text
