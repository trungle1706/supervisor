"""WP8: console pages with SUPERVISOR_MODE=databricks_app and fake SSO headers.

The store is SQLite here (Databricks code is unit-tested with fakes; live checks run with
RUN_DATABRICKS=1 from the WP10 kit). Identity comes only from the SSO headers.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supervisor.adapters.factory import build_adapters
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema

TOKEN = "eyFAKE-user-token-never-logged-0123456789"
REVIEWER = {"X-Forwarded-Email": "rev@bank.example", "X-Forwarded-Access-Token": TOKEN}
OWNER = {"X-Forwarded-Email": "lending-lead@example.invalid", "X-Forwarded-Access-Token": TOKEN}


@pytest.fixture
def dbx(tmp_path: Path) -> Iterator[tuple[TestClient, Any]]:
    from supervisor.adapters.auth import set_provider
    from supervisor.app import app
    from supervisor.console.context import build_context, set_context
    from supervisor.demo import replay as R
    from supervisor.gateway import wiring as gate_wiring
    from supervisor.wiring import build_runtime

    auth = tmp_path / "auth.yaml"
    auth.write_text(
        """
service_principal_id: app-sp-test
roles:
  reviewer: {users: [rev@bank.example, reviewer.an]}
  owner: {users: [lending-lead@example.invalid]}
  auditor: {users: [audit@bank.example]}
""",
        encoding="utf-8",
    )
    settings = load_settings(
        supervisor_mode="databricks_app",
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        auth_config_file=auth,
    )
    assert settings.effective_auth_kind == "databricks_app"
    a = build_adapters(settings)
    bootstrap_schema.run(settings, a)
    assert R.run_gated(settings, adapters=a).ok
    runtime = build_runtime(settings, adapters=a, policy_refresh_s=0.0)
    ctx = build_context(runtime)
    set_context(ctx)
    gate_wiring.set_gateway(runtime.gateway)
    try:
        yield TestClient(app, raise_server_exceptions=False), ctx
    finally:
        set_context(None)
        gate_wiring.set_gateway(None)
        set_provider(None)
        runtime.close()
        a.close()


def test_pages_render_with_sso_headers(
    dbx: tuple[TestClient, Any], caplog: pytest.LogCaptureFixture
) -> None:
    client, ctx = dbx
    assert ctx.provider.name == "databricks_app"
    with caplog.at_level(logging.DEBUG):
        for url in (
            "/console/",
            "/console/agents",
            "/console/metrics",
            "/console/export",
            "/console/inbox",
        ):
            r = client.get(url, headers=REVIEWER)
            assert r.status_code == 200, (url, r.text)
            assert "rev@bank.example" in r.text and "databricks_sso" in r.text
            assert TOKEN not in r.text
            assert "Dev identity" not in r.text and "Switch user" not in r.text
        case = ctx.cases.list_cases()[0]
        r = client.get(f"/console/cases/{case['case_id']}", headers=REVIEWER)
        assert r.status_code == 200 and TOKEN not in r.text
    assert TOKEN not in caplog.text


def test_sso_actions_record_identity_and_sp_is_read_only(dbx: tuple[TestClient, Any]) -> None:
    client, ctx = dbx
    hx = {"HX-Request": "true"}
    # no SSO header: the app service principal, read-only
    r = client.get("/console/")
    assert r.status_code == 200 and "app-sp-test" in r.text and "service principal" in r.text
    r = client.post("/console/agents/credit_prequal/pause", data={"reason": "x"}, headers=hx)
    assert r.status_code == 403 and "signed-in person" in r.text
    # the X-Dev-User header means nothing on the App
    r = client.post(
        "/console/agents/credit_prequal/pause",
        data={"reason": "x"},
        headers={**hx, "X-Dev-User": "admin.chi"},
    )
    assert r.status_code == 403
    r = client.post("/console/dev/user", data={"user": "admin.chi"}, headers=hx)
    assert r.status_code == 400
    # SSO reviewer pauses; reviewer + owner resume (two people)
    r = client.post(
        "/console/agents/credit_prequal/pause", data={"reason": "x"}, headers={**hx, **REVIEWER}
    )
    assert r.status_code == 200, r.text
    case = ctx.cases.list_cases()[0]
    r = client.post(
        f"/console/cases/{case['case_id']}/comment",
        data={"text": "checked", "row_version": case["row_version"]},
        headers={**hx, **REVIEWER},
    )
    assert r.status_code == 200, r.text
    ev = ctx.cases.events(case["case_id"])[-1]
    assert ev["actor"] == "rev@bank.example" and ev["auth_method"] == "databricks_sso"
    # the intake ran as the service principal (background identity, recorded as such)
    from .conftest import add_gate_block

    add_gate_block(ctx.runtime.adapters)
    r = client.post("/console/intake/run", headers={**hx, **REVIEWER})
    assert r.status_code == 200, r.text
    new = next(c for c in ctx.cases.list_cases() if "PAY-99" in c["summary"])
    first = ctx.cases.events(new["case_id"])[0]
    assert first["actor"] == "app-sp-test" and first["actor_kind"] == "service_principal"
    assert first["auth_method"] == "databricks_app_sp"
    r = client.post(
        "/console/agents/credit_prequal/resume", data={"reason": "ok"}, headers={**hx, **OWNER}
    )
    assert r.status_code == 200 and "needs the reviewer" in r.text, r.text


def test_shell_routes_with_sso_headers(dbx: tuple[TestClient, Any]) -> None:
    """WP-UX1: sidebar, search, list rows and the row drawer in databricks_app mode; the user
    menu offers no user switch and lists no user file."""
    client, ctx = dbx
    hx = {**REVIEWER, "HX-Request": "true"}
    page = client.get("/console/agents", headers=REVIEWER)
    assert page.status_code == 200 and '<aside class="side"' in page.text
    assert "dev-user" not in page.text and "/console/dev/user" not in page.text
    agent = ctx.state.query("agent")[0]["agent_id"]
    for url in (
        f"/console/search?q={agent[:4]}",
        "/console/agents/rows?sort=agent_id&dir=desc",
        f"/console/agents/{agent}/drawer?tab=policy",
        f"/console/agents/{agent}/drawer?tab=cases",
    ):
        r = client.get(url, headers=hx)
        assert r.status_code == 200, (url, r.text[:300])
        assert TOKEN not in r.text and "<html" not in r.text
