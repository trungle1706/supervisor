"""WP24: Inventory page and /v1/inventory routes (flag-gated, read-only, RBAC viewer)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.inventory.service import InventoryService
from tests.conftest import REPO_ROOT

WORKSPACE_7 = REPO_ROOT / "tests" / "fixtures" / "inventory" / "workspace_7.json"


@pytest.fixture
def inv_console(console: Any, tmp_path: Path) -> Any:
    allow = tmp_path / "allow.yaml"
    allow.write_text("apps:\n  - bi-portal\n", encoding="utf-8")
    s = console.ctx.settings
    s.inventory_enabled = True
    s.inventory_allowlist_file = allow
    svc = InventoryService.from_adapters(console.runtime.adapters)
    svc.fill_manifests()
    svc.refresh_workspace(FixtureWorkspaceReader.from_file(WORKSPACE_7), console.ctx.cases)
    return console


def test_off_by_default(console: Any) -> None:
    assert console.ctx.settings.inventory_enabled is False
    for url in ("/console/inventory", "/v1/inventory/payments", "/v1/inventory/unmanaged"):
        r = console.get(url)
        assert r.status_code == 400, url
        assert "INVENTORY_ENABLED" in r.text
    assert "/console/inventory" not in console.get("/console/").text  # no nav entry


def test_json_agent_subgraph(inv_console: Any) -> None:
    r = inv_console.get("/v1/inventory/payments", user="viewer.hoa")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == "payments"
    kinds = {n["kind"] for n in body["nodes"]}
    assert {"system", "tool", "model_endpoint", "model", "supplier"} <= kinds
    assert "tool:ext_transfer_api risk=critical" in body["tree"]
    assert all(e["evidence_ref"] for e in body["edges"])


def test_json_unmanaged(inv_console: Any) -> None:
    r = inv_console.get("/v1/inventory/unmanaged", user="viewer.hoa")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert {i["display_name"] for i in body["items"]} == {
        "loan-bot-sandbox",
        "hr-chat-assistant",
        "adhoc-llama-endpoint",
    }
    assert all(i["case_id"] for i in body["items"])


def test_unknown_and_bad_ids_are_4xx(inv_console: Any) -> None:
    assert inv_console.get("/v1/inventory/no_such_agent", user="viewer.hoa").status_code == 404
    r = inv_console.get("/v1/inventory/bad%20id%3Cscript%3E", user="viewer.hoa")
    assert r.status_code == 400 and "error" in r.json()


def test_unknown_user_is_refused(inv_console: Any) -> None:
    r = inv_console.get("/v1/inventory/unmanaged", user="nobody.at.all")
    assert r.status_code in (400, 403)


def test_page_shows_tree_table_count_and_nav(inv_console: Any) -> None:
    r = inv_console.get("/console/inventory?agent=payments")
    assert r.status_code == 200, r.text
    t = r.text
    assert "Unmanaged items" in t and "hr-chat-assistant" in t and "bi-portal" not in t
    assert "tool:ext_transfer_api" in t and "manifest.yaml:" in t
    assert "/console/inventory" in inv_console.get("/console/").text  # nav entry with the count
    assert inv_console.get("/console/inventory?agent=nope").status_code == 400
    assert inv_console.get("/console/inventory?lang=vi").status_code == 200


def test_page_without_agents_is_an_empty_state(console: Any) -> None:
    console.ctx.settings.inventory_enabled = True
    r = console.get("/console/inventory")
    assert r.status_code == 200 and "python -m supervisor.jobs.inventory" in r.text


def test_shadow_case_page_renders_for_the_pseudo_agent(inv_console: Any) -> None:
    """Review: the shadow-AI case belongs to pseudo agent ``inventory`` (no agent row); its
    case page and the case list must still render (no 5xx)."""
    item = inv_console.get("/v1/inventory/unmanaged", user="viewer.hoa").json()["items"][0]
    for user in ("viewer.hoa", None):
        kw = {"user": user} if user else {}
        r = inv_console.get(f"/console/cases/{item['case_id']}", **kw)
        assert r.status_code == 200, r.text[:300]
        assert "Shadow AI" in r.text
    assert inv_console.get("/console/cases").status_code == 200
    assert "report-sent" not in r.text  # no mark-report-sent button on a clockless case
