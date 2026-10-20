"""WP-UX3: the new pages render in both languages, sit behind their flag and their permission,
list/sort/filter/page correctly and show masked data only."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.console import nav, readmodels

from .conftest import Console

PAGE_URLS = {
    "decisions": "/console/decisions",
    "traces": "/console/traces",
    "playground": "/console/playground",
    "policies": "/console/policies",
    "credentials": "/console/credentials",
    "users": "/console/users",
    "audit": "/console/audit",
    "integrations": "/console/integrations",
}
# who may open each page (one user that holds the permission)
USER_FOR = {
    "decisions": "reviewer.an",
    "traces": "reviewer.an",
    "playground": "operator.khanh",
    "policies": "viewer.hoa",
    "credentials": "admin.chi",
    "users": "admin.chi",
    "audit": "auditor.dung",
    "integrations": "viewer.hoa",
}


@pytest.fixture
def ux(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in nav.PAGES.values():
        monkeypatch.setattr(console.ctx.settings, flag, True)
    return console


def _items(html: str) -> list[str]:
    return re.findall(r'<a href="([^"]+)" class="[^"]*"', html.split('<aside class="side"')[1])


# ------------------------------------------------------------------ flags


@pytest.mark.parametrize("page", sorted(PAGE_URLS))
def test_flag_off_is_400_and_has_no_nav_entry(console: Console, page: str) -> None:
    r = console.get(PAGE_URLS[page], user=USER_FOR[page])
    assert r.status_code == 400 and "is off" in r.text
    hrefs = _items(console.get("/console/").text)
    assert not any(h.startswith(PAGE_URLS[page]) for h in hrefs)


def test_each_flag_is_its_own(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_decisions_enabled", True)
    assert console.get("/console/decisions").status_code == 200
    for page in PAGE_URLS:
        if page != "decisions":
            assert console.get(PAGE_URLS[page], user=USER_FOR[page]).status_code == 400
    hrefs = _items(console.get("/console/").text)
    assert any(h.startswith("/console/decisions") for h in hrefs)
    assert not any(h.startswith("/console/traces") for h in hrefs)


def test_playground_needs_the_app_flag_in_databricks_mode(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ux.get("/console/playground", user="operator.khanh").status_code == 200
    monkeypatch.setattr(ux.ctx.settings, "supervisor_mode", "databricks_app")
    r = ux.get("/console/playground", user="operator.khanh")
    assert r.status_code == 400 and "PLAYGROUND_ALLOW_APP" in r.text
    assert readmodels.ux3_pages(ux.ctx.settings)["playground"] is False
    monkeypatch.setattr(ux.ctx.settings, "playground_allow_app", True)
    assert readmodels.ux3_pages(ux.ctx.settings)["playground"] is True


def test_flags_default_off() -> None:
    from supervisor.config import Settings

    s = Settings()
    for flag in nav.PAGES.values():
        assert getattr(s, flag) is False, flag
    assert s.playground_allow_app is False


# ------------------------------------------------------------------ render, both languages


@pytest.mark.parametrize("lang", ["en", "vi"])
@pytest.mark.parametrize("page", sorted(PAGE_URLS))
def test_every_page_renders(ux: Console, page: str, lang: str) -> None:
    r = ux.get(f"{PAGE_URLS[page]}?lang={lang}", user=USER_FOR[page])
    assert r.status_code == 200, r.text[:400]
    assert '<body class="nav-side">' in r.text and "<h1>" in r.text
    side = r.text.split('<aside class="side"')[1].split("</aside>")[0]
    assert re.search(r'class="active"[^>]*aria-current="page"', side), page
    # no raw i18n key leaks through (a missing label would show as its key)
    assert not re.search(r">(nav_|pg_|cred_|users_|audit_|integ_)[a-z_]+<", r.text)


def test_sidebar_links_the_real_pages(ux: Console) -> None:
    hrefs = _items(ux.get("/console/").text)
    for page, url in PAGE_URLS.items():
        assert any(h.startswith(url) for h in hrefs), page
    assert not any(h.startswith("/console/soon/") for h in hrefs)


def test_soon_placeholder_still_works_for_a_page_that_is_off(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_nav_placeholders", True)
    monkeypatch.setattr(console.ctx.settings, "console_decisions_enabled", True)
    hrefs = _items(console.get("/console/").text)
    assert any(h.startswith("/console/decisions") for h in hrefs)  # real page wins
    assert any(h.startswith("/console/soon/traces") for h in hrefs)  # off: placeholder


# ------------------------------------------------------------------ permissions


@pytest.mark.parametrize(
    ("page", "denied"),
    [
        ("credentials", ["viewer.hoa", "reviewer.an", "auditor.dung", "operator.khanh"]),
        ("users", ["viewer.hoa", "reviewer.an", "auditor.dung", "operator.khanh"]),
        ("audit", ["viewer.hoa", "reviewer.an", "operator.khanh"]),
        ("playground", ["viewer.hoa", "auditor.dung"]),
    ],
)
def test_denied_roles_get_403(ux: Console, page: str, denied: list[str]) -> None:
    for user in denied:
        r = ux.get(PAGE_URLS[page], user=user)
        assert r.status_code == 403 and "needs role" in r.text, (page, user)


@pytest.mark.parametrize(
    ("page", "allowed"),
    [
        ("credentials", ["admin.chi", "payops-lead@example.invalid"]),
        ("users", ["admin.chi"]),
        ("audit", ["admin.chi", "auditor.dung"]),
        (
            "playground",
            ["operator.khanh", "reviewer.an", "admin.chi", "payops-lead@example.invalid"],
        ),
        ("decisions", ["viewer.hoa", "auditor.dung"]),
        ("traces", ["viewer.hoa"]),
        ("policies", ["viewer.hoa"]),
        ("integrations", ["viewer.hoa"]),
    ],
)
def test_allowed_roles_get_200(ux: Console, page: str, allowed: list[str]) -> None:
    for user in allowed:
        assert ux.get(PAGE_URLS[page], user=user).status_code == 200, (page, user)


# ------------------------------------------------------------------ gate decisions


def _decisions(ux: Console, qs: str = "") -> Any:
    return ux.get(f"/console/decisions/rows?{qs}" if qs else "/console/decisions/rows")


def test_decisions_list_filters_and_tiles(ux: Console) -> None:
    html = ux.get("/console/decisions").text
    assert 'class="tile on"' in html and "decisions-tbl" in html
    all_rows = set(re.findall(r'data-row="([0-9a-f]+)"', _decisions(ux, "page=1").text))
    assert all_rows  # the demo replay made decisions
    blocked = _decisions(ux, "action=block").text
    assert "act_block" not in blocked and ">block<" in blocked.lower() or "Block" in blocked
    assert 'data-row="' in blocked
    paused = _decisions(ux, "action=pause").text
    assert "PAY-07" in paused
    by_rule = _decisions(ux, "rule=PAY-07").text
    assert "PAY-07" in by_rule
    none = _decisions(ux, "agent=payments&tool=no_such_tool").text
    assert 'data-row="' not in none and "emptystate" in none


def test_decisions_sort_and_unknown_column_falls_back(ux: Console) -> None:
    a = _decisions(ux, "sort=ts&dir=asc").text
    d = _decisions(ux, "sort=ts&dir=desc").text
    assert 'aria-sort="ascending"' in a and 'aria-sort="descending"' in d
    first_a = re.findall(r'data-row="([0-9a-f]+)"', a)
    first_d = re.findall(r'data-row="([0-9a-f]+)"', d)
    assert first_a != first_d or len(first_a) <= 1
    fallback = _decisions(ux, "sort=tool_name;drop").text  # unknown column: default order
    assert 'aria-sort="descending"' in fallback


@pytest.mark.parametrize(
    "qs",
    [
        "action=nope",
        "agent=a%20b%3Bdrop",
        "range=century",
        "page=abc",
        "page=999",
        "rule=" + "A" * 200,
        "trace=%3Cscript%3E",
    ],
)
def test_decisions_bad_input_is_400_never_500(ux: Console, qs: str) -> None:
    assert _decisions(ux, qs).status_code == 400


def test_decisions_drawer_shows_hashes_not_arguments(ux: Console) -> None:
    ids = re.findall(r'data-row="([0-9a-f]+)"', _decisions(ux, "action=pause").text)
    assert ids
    eid = ids[0]
    for tab in ("details", "rules", "evidence"):
        r = ux.get(f"/console/decisions/{eid}/drawer?tab={tab}")
        assert r.status_code == 200, (tab, r.text[:300])
    d = ux.get(f"/console/decisions/{eid}/drawer?tab=details").text
    assert "drawer-json" in d and "args_hash" in d and "latency_us" in d
    assert "PAY-07" in ux.get(f"/console/decisions/{eid}/drawer?tab=rules").text
    ev = ux.get(f"/console/decisions/{eid}/drawer?tab=evidence").text
    assert "Chain lane" in ev or "chain" in ev.lower()
    # no-JS fallback: the same drawer rendered with the page
    page = ux.get(f"/console/decisions?drawer={eid}&dtab=rules")
    assert page.status_code == 200 and 'id="drawer-title"' in page.text
    assert ux.get(f"/console/decisions/{eid}/drawer?tab=nope").status_code == 400
    assert ux.get("/console/decisions/deadbeef/drawer").status_code == 400
    assert ux.get("/console/decisions/a%20b/drawer").status_code in (400, 404)


def test_decisions_masked_only(ux: Console) -> None:
    """A phone number planted in the raw args never reaches the page: the gate stores a keyed
    hash and hashed key values only."""
    phone = "0912345678"
    ux.runtime.gateway.check(
        "payments", "1.0", "lookup_account", {"account_id": "A-1", "note": phone}, {}
    )
    ux.runtime.gateway.drain()
    for url in ("/console/decisions", "/console/decisions/rows?sort=ts&dir=desc"):
        assert phone not in ux.get(url).text
    ids = re.findall(r'data-row="([0-9a-f]+)"', _decisions(ux, "tool=lookup_account").text)
    for eid in ids[:3]:
        for tab in ("details", "rules", "evidence"):
            assert phone not in ux.get(f"/console/decisions/{eid}/drawer?tab={tab}").text


def test_decisions_paging(ux: Console) -> None:
    html = _decisions(ux).text
    assert "pager" in html
    assert _decisions(ux, "page=1&sort=agent_id&dir=asc").status_code == 200
