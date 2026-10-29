"""WP-W2: the changes pages, the diff and Apply change actions, the JSON API, the audit rows.

Off by default (HTTP 400 change_loop_off on every route). On: list, diff (fake gateway model),
the detail page with the old and new text side by side, Confirm of a draft on the drafts route,
Apply change behind a confirmation tick, the override file, the chain record, the permissions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.core import rbac
from supervisor.regkb import change
from supervisor.regkb.drafts import DraftStore
from tests.regkb.test_w2_change import (
    IID,
    QUOTE_5,
    FakeChat,
    draft_of,
    new_text_art5,
    write_package,
)

from .conftest import Console
from .test_rbac_matrix import app_routes

APPROVER = "approver.em"  # regkb.confirm
ADMIN = "admin.chi"  # regkb.confirm and regkb.watch
REVIEWER = "reviewer.an"  # regkb.view only
VIEWER = "viewer.hoa"
LIST = "/console/regkb/changes"
API = "/v1/regkb/changes"


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Console:
    for flag in ("regkb_change_loop", "lawagent_enabled", "governance_enabled"):
        monkeypatch.setattr(console.ctx.settings, flag, True)
    monkeypatch.setattr(console.ctx.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(
        change,
        "make_chat",
        lambda settings: FakeChat({5: [draft_of("risk_classification", QUOTE_5)]}),
    )
    return console


def data_dir(c: Console) -> Path:
    return Path(c.ctx.settings.data_dir)


def url(sha: str, tail: str = "", base: str = LIST) -> str:
    return f"{base}/{sha}/{IID}{tail}"


def diffed(c: Console) -> str:
    sha = write_package(data_dir(c), new_text_art5())
    r = post303(c, url(sha, "/diff"))
    assert r.status_code == 303, r.text[:300]
    return sha


def post303(c: Console, u: str, data: dict[str, str] | None = None, user: str = APPROVER) -> Any:
    return c.post(u, data, user=user, follow_redirects=False)


def chain_types(c: Console) -> list[str]:
    return [r["record_type"] for r in c.ctx.tables.query("chain_entry")]


def audit(c: Console, permission: str = "regkb.confirm") -> list[Any]:
    rows = [r for r in c.ctx.tables.query("console_action") if r["permission"] == permission]
    return sorted(rows, key=lambda r: r["ts"])


# ------------------------------------------------------------------------------ off path


def test_off_by_default_every_route_answers_400_with_the_code(
    console: Console, tmp_path: Path
) -> None:
    assert console.ctx.settings.regkb_change_loop is False
    sha = "a" * 64
    for u in (LIST, url(sha), API, url(sha, base=API)):
        r = console.get(u, user=ADMIN)
        assert r.status_code == 400 and "change_loop_off" in r.text, u
    for u in (
        url(sha, "/diff"),
        url(sha, "/apply"),
        url(sha, "/diff", API),
        url(sha, "/apply", API),
    ):
        r = console.post(u, user=ADMIN)
        assert r.status_code == 400 and "change_loop_off" in r.text, u
    assert not (Path(console.ctx.settings.data_dir) / "regkb" / "changes").exists()
    assert console.ctx.state.query("regkb_change") == []
    assert "regkb_change" not in chain_types(console)


def test_the_flag_alone_is_not_enough(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "regkb_change_loop", True)
    r = console.get(LIST, user=ADMIN)
    assert r.status_code == 400 and "LAWAGENT_ENABLED" in r.text and "GOVERNANCE_ENABLED" in r.text


def test_the_watch_page_has_no_diff_button_while_the_flag_is_off(
    console: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(console.ctx.settings, "regwatch_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "data_dir", tmp_path / "data")
    write_package(tmp_path / "data", new_text_art5())
    page = console.get("/console/regkb/watch", user=ADMIN)
    assert page.status_code == 200 and "data-w2-actions" not in page.text


def test_the_watch_page_offers_the_diff_when_the_flag_is_on(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "regwatch_enabled", True)
    sha = write_package(data_dir(on), new_text_art5())
    page = on.get("/console/regkb/watch", user=ADMIN)
    assert page.status_code == 200
    assert f'data-w2-actions="{sha}"' in page.text and 'data-act="diff"' in page.text
    assert f"/console/regkb/changes/{sha}/{IID}/diff" in page.text


# ------------------------------------------------------------------------------ the flow


def test_list_diff_detail_confirm_apply(on: Console) -> None:
    sha = write_package(data_dir(on), new_text_art5())
    page = on.get(LIST, user=VIEWER)
    assert page.status_code == 200 and IID in page.text and 'data-state="no_diff"' in page.text
    assert 'data-act="diff"' not in page.text  # a viewer cannot start the diff
    page = on.get(LIST, user=APPROVER)
    assert 'data-act="diff"' in page.text

    # diff: 303 to the detail page
    r = post303(on, url(sha, "/diff"))
    assert r.status_code == 303 and r.headers["location"] == f"/console/regkb/changes/{sha}/{IID}"
    detail = on.get(url(sha), user=APPROVER)
    assert detail.status_code == 200
    t = detail.text
    assert 'data-article="5"' in t and 'data-status="changed"' in t
    assert 'data-side="old"' in t and 'data-side="new"' in t and "chủ động" in t
    assert f'data-obligation="{IID}-A5.03-01"' in t and "article_changed" in t
    assert 'data-status="draft"' in t and "risk_classification" in t
    assert 'data-classification="1"' not in t  # Art. 5 is not a classification article
    assert 'data-act="apply"' in t and 'data-confirm="1"' in t
    assert 'data-act="apply"' not in on.get(url(sha), user=VIEWER).text

    # confirm the draft on the drafts route (the same buttons as on the drafts page)
    (d,) = DraftStore(on.ctx.state, on.ctx.clock).list(IID, "draft")
    c = on.post(
        f"/console/regkb/{IID}/drafts/{d['draft_id']}/confirm",
        {"row_version": d["row_version"]},
        user=APPROVER,
    )
    assert c.status_code == 200
    assert 'data-confirmed-drafts="1">1<' in on.get(url(sha), user=APPROVER).text

    # apply: refused without the tick, then done
    bad = on.post(url(sha, "/apply"), user=APPROVER)
    assert bad.status_code == 400 and "confirm_required" in bad.text
    assert not change.override_path(data_dir(on), IID).exists()
    ok = post303(on, url(sha, "/apply"), {"confirm": "yes"})
    assert ok.status_code == 303
    assert change.override_path(data_dir(on), IID).is_file()
    row = change.get_row(on.ctx.state, sha, IID)
    assert row is not None and row["status"] == "applied" and row["applied_by"] == APPROVER
    assert (row["obligations_added"], row["obligations_updated"]) == (0, 1)
    after = on.get(url(sha), user=APPROVER).text
    assert 'data-applied="1"' in after and 'data-act="apply"' not in after
    # a second apply is a 400
    again = on.post(url(sha, "/apply"), {"confirm": "yes"}, user=APPROVER)
    assert again.status_code == 400 and "already_applied" in again.text
    # the chain record has integers only and no user id
    assert chain_types(on).count("regkb_change") == 1
    # two audit rows per POST (attempted, then ok), with the person
    rows = audit(on)
    outcomes = [r["outcome"] for r in rows]
    assert outcomes.count("attempted") >= 3 and outcomes.count("ok") >= 2, outcomes
    assert all(APPROVER in str(r["actor"]) for r in rows if r["permission"] == "regkb.confirm")


def test_the_classification_notice_shows_on_the_page(on: Console) -> None:
    from tests.regkb.test_w2_change import new_text_art11

    sha = write_package(data_dir(on), new_text_art11(), tag="11")
    assert post303(on, url(sha, "/diff")).status_code == 303
    t = on.get(url(sha), user=APPROVER).text
    assert 'data-classification="1"' in t


def test_permissions(on: Console) -> None:
    sha = write_package(data_dir(on), new_text_art5())
    for user in (REVIEWER, VIEWER):
        assert on.get(LIST, user=user).status_code == 200
        assert on.post(url(sha, "/diff"), user=user).status_code == 403
        assert on.post(url(sha, "/apply"), {"confirm": "yes"}, user=user).status_code == 403
        assert on.post(url(sha, "/diff", API), user=user, htmx=False).status_code == 403
    assert on.ctx.state.query("regkb_change") == []


def test_refusals_are_400(on: Console) -> None:
    assert on.get(url("a" * 64), user=APPROVER).status_code == 400  # no diff yet
    assert "no_diff" in on.get(url("a" * 64), user=APPROVER).text
    r = on.post(url("a" * 64, "/diff"), user=APPROVER)
    assert r.status_code == 400 and "no_package" in r.text
    r = on.post(url("zz", "/diff"), user=APPROVER)
    assert r.status_code == 400 and "bad_package" in r.text
    r = on.post(url("a" * 64, "/apply"), {"confirm": "yes"}, user=APPROVER)
    assert r.status_code == 400 and "no_diff" in r.text


# ------------------------------------------------------------------------------ JSON API


def test_json_api(on: Console) -> None:
    sha = write_package(data_dir(on), new_text_art5())
    listed = on.get(API, user=VIEWER).json()
    assert [(i["instrument_id"], i["status"]) for i in listed["items"]] == [(IID, "no_diff")]
    assert listed["banner"].startswith("Not legal advice")
    r = on.client.post(
        url(sha, "/diff", API),
        json={"incoming": f"{IID}/2026-10-28/142-2026-nd-cp.txt"},
        headers={"X-Dev-User": APPROVER},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["changed"] == 1 and body["summary"]["drafts_made"] == 1
    assert all(
        isinstance(v, (int, bool, str)) and not isinstance(v, float)
        for v in body["summary"].values()
    )
    got = on.get(url(sha, base=API), user=VIEWER).json()
    assert (
        got["change"]["status"] == "diffed" and got["report"]["articles"][4]["status"] == "changed"
    )
    (d,) = got["drafts"]
    assert d["change_ref"] == f"{sha}:{d['article']}"
    bad = on.client.post(
        url(sha, "/diff", API), json={"incoming": "x/../y.txt"}, headers={"X-Dev-User": APPROVER}
    )
    assert bad.status_code == 400 and "bad_incoming" in bad.text
    store = DraftStore(on.ctx.state, on.ctx.clock)
    store.decide(d["draft_id"], "confirmed", APPROVER)
    ok = on.client.post(url(sha, "/apply", API), headers={"X-Dev-User": APPROVER})
    assert ok.status_code == 200, ok.text
    res = ok.json()
    assert res["obligations_updated"] == 1 and res["version_before"] != res["version_after"]
    listed = on.get(API, user=VIEWER).json()
    assert listed["items"][0]["status"] == "applied"
    assert json.dumps(listed)  # JSON-safe (no datetime left over)


# ------------------------------------------------------------------------------ rbac rows


def test_rbac_rows_and_every_route_is_in_the_table() -> None:
    expect = {
        ("GET", "/v1/regkb/changes"): "regkb.view",
        ("GET", "/v1/regkb/changes/{package_sha}/{instrument_id}"): "regkb.view",
        ("POST", "/v1/regkb/changes/{package_sha}/{instrument_id}/diff"): "regkb.confirm",
        ("POST", "/v1/regkb/changes/{package_sha}/{instrument_id}/apply"): "regkb.confirm",
        ("GET", "/console/regkb/changes"): "regkb.view",
        ("GET", "/console/regkb/changes/{package_sha}/{instrument_id}"): "regkb.view",
        ("POST", "/console/regkb/changes/{package_sha}/{instrument_id}/diff"): "regkb.confirm",
        ("POST", "/console/regkb/changes/{package_sha}/{instrument_id}/apply"): "regkb.confirm",
    }
    for key, perm in expect.items():
        assert rbac.ROUTES[key] == perm, key
    mounted = {(m, p) for m, p, _ in app_routes() if "/regkb/changes" in p}
    assert mounted == set(expect)
    # who may do what: the confirm role decides and applies; every console role reads
    for role in ("approver", "admin"):
        assert rbac.allowed([role], "regkb.confirm")
    for role in ("viewer", "reviewer", "auditor", "operator", "owner"):
        assert not rbac.allowed([role], "regkb.confirm")
        assert rbac.allowed([role], "regkb.view")


# ------------------------------------------------------------------------------ the banner


def test_my_overview_banner(on: Console) -> None:
    from supervisor.console import overview_v4

    now = on.ctx.clock.now()
    assert overview_v4._law_change(on.ctx, now) is None  # noqa: SLF001 - nothing imported
    sha = write_package(data_dir(on), new_text_art5())
    got = overview_v4._law_change(on.ctx, now)  # noqa: SLF001
    assert got == {"pending": 1, "applied": []}
    assert post303(on, url(sha, "/diff")).status_code == 303
    assert overview_v4._law_change(on.ctx, now) == {"pending": 1, "applied": []}  # noqa: SLF001
    (d,) = DraftStore(on.ctx.state, on.ctx.clock).list(IID, "draft")
    DraftStore(on.ctx.state, on.ctx.clock).decide(d["draft_id"], "confirmed", APPROVER)
    assert post303(on, url(sha, "/apply"), {"confirm": "yes"}).status_code == 303
    after = overview_v4._law_change(on.ctx, now)  # noqa: SLF001
    assert after is not None and after["pending"] == 0
    assert after["applied"][0]["instrument_id"] == IID and after["applied"][0]["systems"] == 0


def test_my_overview_banner_is_none_while_the_flag_is_off(console: Console) -> None:
    from supervisor.console import overview_v4

    assert overview_v4._law_change(console.ctx, console.ctx.clock.now()) is None  # noqa: SLF001
