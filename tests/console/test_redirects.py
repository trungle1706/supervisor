"""WP-UX2: every moved console URL answers 303 to its new place and keeps the query string."""

from __future__ import annotations

import pytest

from .conftest import Console

# old URL -> where it goes (path and the parameters the redirect adds)
MOVED = {
    "/console/metrics": ("/console/analytics", {"tab": "metrics"}),
    "/console/tools": ("/console/analytics", {"tab": "tools"}),
}


def _query(location: str) -> dict[str, str]:
    from urllib.parse import parse_qsl, urlsplit

    return dict(parse_qsl(urlsplit(location).query))


@pytest.mark.parametrize("old", sorted(MOVED))
def test_old_url_answers_303_and_keeps_lang(console: Console, old: str) -> None:
    target, extra = MOVED[old]
    for lang in ("en", "vi"):
        r = console.get(f"{old}?lang={lang}", follow_redirects=False)
        assert r.status_code == 303, (old, r.status_code)
        loc = r.headers["location"]
        assert loc.startswith(target + "?"), loc
        q = _query(loc)
        assert q["lang"] == lang and all(q[k] == v for k, v in extra.items())


def test_tools_redirect_keeps_filters_and_sort(console: Console) -> None:
    r = console.get(
        "/console/tools?agent_id=payments&sort=calls&dir=desc&days=7", follow_redirects=False
    )
    assert r.status_code == 303
    q = _query(r.headers["location"])
    assert q == {
        "tab": "tools",
        "agent": "payments",  # the old name agent_id is renamed
        "sort": "calls",
        "dir": "desc",
        "days": "7",
    }


def test_redirect_passes_only_known_keys_and_keeps_its_tab(console: Console) -> None:
    """Review fix: the Location header holds only keys the Analytics page reads, values that
    match the id pattern, and the redirect's own tab (a caller cannot override it)."""
    r = console.get(
        "/console/metrics?tab=tools&next=https://evil.example&lang=vi&agent=a%0d%0aX:1"
        "&days=7&x=<script>",
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/console/analytics?")
    q = _query(loc)
    assert q == {"tab": "metrics", "lang": "vi", "agent": "a\r\nX:1", "days": "7"}
    assert "evil" not in loc and "script" not in loc and "\n" not in loc and "%0D%0A" in loc
    # the bad agent value is checked by the target page: 400, not silently dropped
    assert console.get(loc).status_code == 400


def test_redirect_target_renders_in_the_requested_language(console: Console) -> None:
    r = console.get("/console/metrics?lang=vi")
    assert r.status_code == 200 and "lang=vi" in str(r.url)
    assert "Chỉ số giám sát" in r.text  # the Oversight metrics tab, in Vietnamese


def test_old_metrics_alerts_bookmark_lands_on_the_alerts_tile(console: Console) -> None:
    """/console/metrics#alerts: the browser keeps the fragment, the tile has that id."""
    r = console.get("/console/metrics")
    assert r.status_code == 200 and 'id="alerts"' in r.text and "/console/alerts?lang=" in r.text


def test_redirect_routes_still_need_their_permission(console: Console) -> None:
    for old in MOVED:
        r = console.get(old, user="nobody.at.all", follow_redirects=False)
        assert r.status_code in (400, 403), (old, r.status_code)


def test_export_redirect_unchanged(console: Console) -> None:
    r = console.get("/console/export", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/console/evidence")
