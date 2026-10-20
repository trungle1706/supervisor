"""WP38: the Integrations page as a collector catalogue (COLLECTORS_ENABLED)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supervisor.collectors import catalog
from supervisor.console import nav

from .conftest import Console

AGENT = "customer_service"


@pytest.fixture
def col(console: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Console:
    for flag in nav.PAGES.values():
        monkeypatch.setattr(console.ctx.settings, flag, True)
    monkeypatch.setattr(console.ctx.settings, "collectors_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "ingress_keys_file", tmp_path / "agent_keys.yaml")
    return console


def add(c: Console, agent: str = AGENT, template: str = "python_sdk", user: str = "admin.chi"):
    return c.post(f"/console/integrations/{agent}/connect", {"template": template}, user=user)


def test_flag_off_is_the_old_status_page(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_integrations_enabled", True)
    r = console.get("/console/integrations", user="viewer.hoa")
    assert r.status_code == 200 and 'data-row="siem"' in r.text and "col-pick" not in r.text
    assert (
        console.get(f"/console/integrations/agent/{AGENT}/drawer", user="viewer.hoa").status_code
        == 400
    )
    r = add(console)
    assert r.status_code == 400 and "COLLECTORS_ENABLED" in r.text


def test_catalogue_shows_cards_by_category_and_keeps_the_status_table(col: Console) -> None:
    r = col.get("/console/integrations", user="viewer.hoa")
    assert r.status_code == 200
    for tpl in catalog.TEMPLATES:
        assert f'data-template="{tpl.id}"' in r.text
    for cat in ("SDK", "Middleware", "Gateway and API", "MCP", "Developer tools"):
        assert f">{cat}<" in r.text
    assert 'data-row="siem"' in r.text  # the delivery table is still there
    assert "available after WP26" in r.text


def test_unavailable_template_has_no_add_button(col: Console) -> None:
    r = col.get(f"/console/integrations?agent={AGENT}", user="admin.chi")
    card = r.text.split('data-template="mcp_http_proxy"')[1].split("</div>")[0]
    assert "connect" not in card
    card2 = r.text.split('data-template="python_sdk"')[1].split("</div>")[0]
    assert f"/console/integrations/{AGENT}/connect" in card2


def test_add_issues_a_key_and_shows_it_once_with_the_real_url_and_agent(col: Console) -> None:
    r = add(col, template="langgraph_middleware")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "http://testserver" in r.text and AGENT in r.text
    assert "&lt;SUPERVISOR_URL&gt;" not in r.text and "<SUPERVISOR_URL>" not in r.text
    assert "&lt;AGENT_ID&gt;" not in r.text
    keys = col.ctx.settings.ingress_keys_file.read_text(encoding="utf-8")
    secret = next(
        line.split(":", 1)[1].strip()
        for line in keys.splitlines()
        if line.strip().startswith("secret:")
    )
    assert len(secret) == 64 and secret in r.text  # shown in this answer
    # not again: the page, the drawer and the audit log never show it
    for url in (
        "/console/integrations",
        f"/console/integrations/agent/{AGENT}/drawer?tab=credential",
        f"/console/integrations/agent/{AGENT}/drawer?tab=connection",
        f"/console/integrations/agent/{AGENT}/drawer?tab=policy",
        "/console/credentials",
        "/console/audit",
    ):
        assert secret not in col.get(url, user="admin.chi").text, url
    rows = json.dumps(col.ctx.tables.query("console_action", order_by=("ts",)), default=str)
    assert secret not in rows
    audit = [
        x for x in col.ctx.tables.query("console_action") if x["permission"] == "collectors.add"
    ]
    assert [x["outcome"] for x in sorted(audit, key=lambda x: x["ts"])] == ["attempted", "ok"]
    assert all(x["target_id"] == AGENT for x in audit)


def test_a_second_add_for_the_same_agent_is_refused(col: Console) -> None:
    assert add(col).status_code == 200
    r = add(col)
    assert r.status_code == 400 and "already has a key" in r.text and "rotate" in r.text
    page = col.get("/console/integrations", user="admin.chi").text
    options = page.split('id="col-agent"')[1].split("</select>")[0]
    assert f'value="{AGENT}"' not in options and 'value="payments"' in options


def test_who_may_add_follows_the_permission(col: Console) -> None:
    assert add(col, user="viewer.hoa").status_code == 403
    assert add(col, user="reviewer.an").status_code == 403
    assert add(col, user="operator.khanh").status_code == 200  # operator may, admin may


def test_bad_input_is_400_never_500(col: Console) -> None:
    assert add(col, template="no_such").status_code == 400
    assert add(col, template="mcp_http_proxy").status_code == 400
    assert add(col, agent="ghost-agent").status_code == 400
    assert (
        col.post(f"/console/integrations/{AGENT}/connect", {}, user="admin.chi").status_code == 400
    )
    r = col.post(
        f"/console/integrations/{AGENT}/connect", {"template": "rest"}, "admin.chi", htmx=False
    )
    assert r.status_code == 400  # console actions come from the page
    assert add(col, template="x" * 300).status_code == 400
    assert not col.ctx.settings.ingress_keys_file.exists()  # nothing was issued


def test_public_url_setting_is_used_and_checked(
    col: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(col.ctx.settings, "collectors_public_url", "https://sup.bank.example")
    assert "https://sup.bank.example/v1/gate/check" in add(col, template="rest").text
    monkeypatch.setattr(col.ctx.settings, "collectors_public_url", "https://x.example'; rm -rf /")
    r = add(col, agent="payments", template="rest")
    assert r.status_code == 400 and not col.ctx.settings.ingress_keys_file.read_text().count(
        "payments"
    )


def test_drawer_tabs(col: Console) -> None:
    add(col)
    conn = col.get(
        f"/console/integrations/agent/{AGENT}/drawer?tab=connection&template=fastapi_middleware",
        user="viewer.hoa",
    )
    assert (
        conn.status_code == 200 and "SupervisorASGIMiddleware" in conn.text and AGENT in conn.text
    )
    cred = col.get(
        f"/console/integrations/agent/{AGENT}/drawer?tab=credential", user="viewer.hoa"
    ).text
    assert "k-" in cred and "ingress_auth rotate" in cred and "secret is never shown again" in cred
    pol = col.get(f"/console/integrations/agent/{AGENT}/drawer?tab=policy", user="viewer.hoa").text
    assert "Policy mode" in pol and "enforce" in pol and "Rules in scope" in pol
    assert (
        col.get(
            f"/console/integrations/agent/{AGENT}/drawer?tab=nope", user="viewer.hoa"
        ).status_code
        == 400
    )
    assert col.get("/console/integrations/agent/ghost/drawer", user="viewer.hoa").status_code == 400


def test_page_opens_with_a_drawer_in_the_url_and_in_vietnamese(col: Console) -> None:
    r = col.get(f"/console/integrations?drawer={AGENT}&dtab=policy&lang=vi", user="viewer.hoa")
    assert r.status_code == 200 and 'id="drawer-title"' in r.text and "Chế độ chính sách" in r.text
    assert "Tác tử và khóa" in col.get("/console/integrations?lang=vi", user="viewer.hoa").text


def test_agent_table_shows_the_key_state_and_mode(col: Console) -> None:
    before = col.get("/console/integrations", user="viewer.hoa").text
    assert 'data-row="payments"' in before
    add(col, agent="payments")
    after = col.get("/console/integrations", user="viewer.hoa").text
    row = after.split('data-row="payments"')[1].split("</tr>")[0]
    assert "active" in row and "enforce" in row


def test_catalogue_text_has_placeholders_and_no_secret_and_is_closed_by_default() -> None:
    for tpl in catalog.TEMPLATES:
        if tpl.available:
            assert catalog.PLACEHOLDER_URL in tpl.snippet or tpl.id == "claude_code_hook"
            assert catalog.PLACEHOLDER_AGENT in tpl.snippet
        assert (
            "SUPERVISOR_AGENT_KEY" not in tpl.snippet
            or "=" not in tpl.snippet.split("SUPERVISOR_AGENT_KEY")[1][:2]
        )
        assert 'fail_mode="open"' not in tpl.snippet and "FAIL_MODE=open" not in tpl.snippet
    assert [t.id for t in catalog.TEMPLATES] == [
        "python_sdk",
        "langgraph_middleware",
        "fastapi_middleware",
        "rest",
        "mcp_stdio_proxy",
        "mcp_http_proxy",
        "litellm_guardrail",
        "claude_code_hook",
    ]
    assert {t.category for t in catalog.TEMPLATES} <= set(catalog.CATEGORIES)
    assert catalog.get("mcp_http_proxy").availability_note == "available after WP26"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("url", "agent"),
    [
        ("http://x.example", "bad id"),
        ("http://x.example", "a\nb"),
        ("javascript:alert(1)", "ok"),
        ("http://x.example/'`$(id)", "ok"),
        ("http://x.example\n", "ok"),
        ("", "ok"),
    ],
)
def test_fill_refuses_unsafe_values(url: str, agent: str) -> None:
    with pytest.raises(catalog.PlaceholderError):
        catalog.fill("curl <SUPERVISOR_URL> <AGENT_ID>", url, agent)


def test_fill_replaces_both_placeholders() -> None:
    out = catalog.fill("<SUPERVISOR_URL>/x <AGENT_ID>", "https://s.example/", "agent-1")
    assert out == "https://s.example/x agent-1"
