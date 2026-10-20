"""WP-UX2: Cases, Inbox and Inventory lists on the list components; shared case tabs; headers.

Filter bar, sortable header with ``aria-sort``, pager, row drawer with a no-JS fallback; bad
input is a 400 message, never a 500. The old behaviours (actions, rows, texts) stay covered by
the existing screen tests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from supervisor.console import cases_list, inbox_list, inventory_views

from .conftest import Console

HX = {"HX-Request": "true"}


def _cases(html: str) -> list[str]:
    return re.findall(r'data-case="(CASE-[0-9A-F]+)"', html)


# ---------------------------------------------------------------------------- cases


def test_cases_page_uses_the_components(console: Console) -> None:
    r = console.get("/console/cases")
    assert r.status_code == 200
    assert 'class="crumbs"' in r.text and 'role="search"' in r.text  # crumbs, filter bar
    assert 'aria-sort="descending"' in r.text  # default sort: severity, critical first
    assert 'name="severity"' in r.text and 'name="agent"' in r.text and 'name="source"' in r.text
    assert 'class="pager"' in r.text and "Showing 1-4 of 4" in r.text
    assert 'hx-trigger="every 30s"' in r.text  # the poll is kept
    assert "Refresh cases" in r.text


def test_cases_sort_filter_and_unknown_column(console: Console) -> None:
    default = _cases(console.get("/console/queue/rows").text)
    assert len(default) == 4
    by_agent = _cases(console.get("/console/queue/rows?sort=agent_id&dir=asc").text)
    rows = {c: console.ctx.cases.get(c) for c in by_agent}
    agents = [rows[c]["agent_id"] for c in by_agent]
    assert agents == sorted(agents)
    asc = _cases(console.get("/console/queue/rows?sort=severity&dir=asc").text)
    assert asc[0] != default[0] or len({rows[c]["severity"] for c in default}) == 1
    odd = console.get("/console/queue/rows?sort=__class__&dir=sideways")
    assert odd.status_code == 200 and _cases(odd.text) == default  # falls back to the default
    one = console.get("/console/queue/rows?agent=payments&status=all")
    assert all(console.ctx.cases.get(c)["agent_id"] == "payments" for c in _cases(one.text))


def test_cases_pages_and_bad_page(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cases_list, "PAGE_SIZE", 2)
    first = _cases(console.get("/console/queue/rows").text)
    second = _cases(console.get("/console/queue/rows?page=2").text)
    assert len(first) == 2 and len(second) == 2 and not set(first) & set(second)
    assert "page 2 of 2" in console.get("/console/queue/rows?page=2").text
    for q in ("page=3", "page=abc", "page=0", "page=-1"):
        r = console.get(f"/console/queue/rows?{q}", headers=HX)
        assert r.status_code == 400, q


def test_cases_row_drawer_and_no_js_fallback(console: Console) -> None:
    cid = _cases(console.get("/console/cases").text)[0]
    d = console.get(f"/console/cases/{cid}/drawer", headers=HX)
    assert d.status_code == 200 and "<html" not in d.text and 'id="drawer-title"' in d.text
    assert cid in d.text and f"/console/cases/{cid}?lang=en" in d.text and "Copy JSON" in d.text
    full = console.get(f"/console/cases?drawer={cid}")
    tail = full.text.split('id="drawer"', 1)[1]
    assert cid in tail and "hidden>" not in tail.split(">", 1)[0] + ">"
    assert console.get("/console/cases/CASE-NOPE/drawer", headers=HX).status_code == 400
    assert console.get("/console/cases/bad%20id/drawer", headers=HX).status_code == 400
    assert console.get("/console/cases?drawer=bad%20id").status_code == 400


def test_case_page_tabs_use_the_shared_macro(console: Console) -> None:
    cid = _cases(console.get("/console/cases").text)[0]
    r = console.get(f"/console/cases/{cid}")
    assert r.text.count('role="tab"') == 5 and 'role="tablist"' in r.text
    assert 'aria-selected="true"' in r.text and 'tabindex="0"' in r.text
    assert 'class="crumbs"' in r.text and 'id="tab-body"' in r.text
    for tab in ("story", "rules", "transcript", "evidence", "casefile"):
        assert f'hx-get="/console/cases/{cid}/tab/{tab}?lang=en"' in r.text
        assert f'href="/console/cases/{cid}?tab={tab}&amp;lang=en"' in r.text


# ---------------------------------------------------------------------------- inbox


def _notice(console: Console, channel: str, subject: str) -> None:
    console.ctx.inbox.notify(channel, subject, "body")


def test_inbox_filters_sort_pages(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for i in range(3):
        _notice(console, "reviewers" if i < 2 else "approvers", f"subject {i}")
    r = console.get("/console/inbox")
    assert r.status_code == 200 and 'role="search"' in r.text and 'class="pager"' in r.text
    assert r.text.count("data-notice=") == 3
    appr = console.get("/console/inbox/rows?channel=approvers", headers=HX)
    assert appr.text.count("data-notice=") == 1 and "<html" not in appr.text
    unread = console.get("/console/inbox/rows?status=unread").text
    assert unread.count("data-notice=") == 3
    assert console.get("/console/inbox/rows?status=read").text.count("data-notice=") == 0
    asc = re.findall(r"subject (\d)", console.get("/console/inbox/rows?sort=ts&dir=asc").text)
    desc = re.findall(r"subject (\d)", console.get("/console/inbox/rows?sort=ts&dir=desc").text)
    assert asc == list(reversed(desc)) and len(asc) == 3
    assert console.get("/console/inbox/rows?sort=__class__").status_code == 200
    monkeypatch.setattr(inbox_list, "PAGE_SIZE", 2)
    assert console.get("/console/inbox/rows?page=2").text.count("data-notice=") == 1
    for q in ("status=nope", "channel=%3Cb%3E", "page=9", "page=abc"):
        assert console.get(f"/console/inbox/rows?{q}", headers=HX).status_code == 400, q


def test_inbox_mark_read_keeps_the_list(console: Console) -> None:
    _notice(console, "reviewers", "subject A")
    notice = console.ctx.inbox.list(status="unread")[0]
    r = console.post(
        f"/console/inbox/{notice['notice_id']}/read?status=unread",
        {"row_version": notice["row_version"]},
    )
    assert r.status_code == 200 and "<html" not in r.text
    assert "No notices" in r.text or 'data-status="read"' not in r.text  # filter keeps unread only


# ---------------------------------------------------------------------------- inventory


@pytest.fixture
def inv_console(console: Console, tmp_path: Path) -> Console:
    from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
    from supervisor.inventory.service import InventoryService
    from tests.conftest import REPO_ROOT

    allow = tmp_path / "allow.yaml"
    allow.write_text("apps:\n  - bi-portal\n", encoding="utf-8")
    s = console.ctx.settings
    s.inventory_enabled = True
    s.inventory_allowlist_file = allow
    svc = InventoryService.from_adapters(console.runtime.adapters)
    svc.fill_manifests()
    svc.refresh_workspace(
        FixtureWorkspaceReader.from_file(
            REPO_ROOT / "tests" / "fixtures" / "inventory" / "workspace_7.json"
        ),
        console.ctx.cases,
    )
    return console


def test_inventory_unmanaged_table_sorts_and_pages(
    inv_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = inv_console.get("/console/inventory")
    assert r.status_code == 200 and 'class="crumbs"' in r.text and 'id="um-list"' in r.text
    names = re.findall(r'<td class="mono">([a-z0-9-]+)</td>', r.text.split('id="um-list"', 1)[1])
    assert {"loan-bot-sandbox", "hr-chat-assistant", "adhoc-llama-endpoint"} <= set(names)
    desc = inv_console.get("/console/inventory/rows?sort=display_name&dir=desc", headers=HX)
    assert desc.status_code == 200 and "<html" not in desc.text
    got = re.findall(r'<td class="mono">([a-z0-9-]+)</td>', desc.text)
    assert got == sorted(got, reverse=True)
    monkeypatch.setattr(inventory_views, "UNMANAGED_PAGE", 2)
    assert "page 2 of 2" in inv_console.get("/console/inventory/rows?page=2").text
    for q in ("page=3", "page=abc", "agent=bad%24id"):
        assert inv_console.get(f"/console/inventory/rows?{q}", headers=HX).status_code == 400, q
    assert inv_console.get("/console/inventory/rows?sort=__class__").status_code == 200


def test_inventory_rows_off_by_default(console: Console) -> None:
    r = console.get("/console/inventory/rows", headers=HX)
    assert r.status_code == 400 and "INVENTORY_ENABLED" in r.text


# ---------------------------------------------------------------------------- headers, safety


PAGES = (
    "/console/cases",
    "/console/evidence",
    "/console/inbox",
    "/console/health",
    "/console/alerts",
    "/console/signoff",
    "/console/analytics",
    "/console/agents/payments",
)


@pytest.mark.parametrize("lang", ["en", "vi"])
def test_migrated_pages_have_crumbs_and_no_inline_script_or_external_url(
    console: Console, lang: str
) -> None:
    for path in PAGES:
        html: Any = console.get(f"{path}?lang={lang}").text
        assert 'class="crumbs"' in html, path
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), path
        assert not re.search(r"\son[a-z]+=\"", html), path
        assert not re.search(r"https?://", html, re.I), path
        assert 'aria-live="polite"' in html and 'class="skip"' in html, path


def test_top_nav_rollback_still_works_for_the_new_pages(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_nav", "top")
    for path in PAGES:
        r = console.get(path)
        assert r.status_code == 200 and '<header class="top">' in r.text, path
    assert "/console/analytics?lang=en" in console.get("/console/").text
