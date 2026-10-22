# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-S1 API and console: the two routes, scope, the floor lock, audit rows, and the switches
on the Catalog page (EN and VI)."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.core import rbac

from .conftest import Console, draft, mounted, on  # noqa: F401  (fixtures)

REVIEWER = "reviewer.an"
READER = "auditor.dung"  # sees every system, holds systems.view and not systems.edit
OWNER_USER = "payops-lead@example.invalid"  # owns the demo agent "payments"
PAYOPS = "Payments Ops"


@pytest.fixture
def gon(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    """Governance on, bindings on, the S1 routers mounted (by ``on``), the Catalog page on."""
    for flag in ("guardian_bindings_enabled", "console_catalog_enabled", "detectors_enabled"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    monkeypatch.setattr(on.ctx.settings, "judge_enabled", True)
    return on


def req(c: Console, method: str, url: str, body: Any = None, user: str = REVIEWER) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def create(c: Console, user: str = REVIEWER, **over: Any) -> str:
    r = req(
        c,
        "POST",
        "/v1/systems",
        draft(**{"owner_user": user, "personal_data": "none", **over}),
        user,
    )
    assert r.status_code == 201, r.text
    return str(r.json()["system_id"])


def test_get_and_put(gon: Console) -> None:
    sid = create(gon)
    r = req(gon, "GET", f"/v1/systems/{sid}/guardians")
    assert r.status_code == 200
    body = r.json()
    assert body["never_bindable"] == ["policy_rules"] and body["count"] == len(body["guardians"])
    row = next(g for g in body["guardians"] if g["slug"] == "injection_regex")
    assert row["state"] == "on" and row["default"] and row["instance_on"] and row["effective"]
    put = req(
        gon,
        "PUT",
        f"/v1/systems/{sid}/guardians/injection_regex",
        {"state": "off", "reason": "assistant answers in plain text only"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["state"] == "off" and put.json()["set_by"] == REVIEWER
    assert put.json()["effective"] is False
    again = req(gon, "GET", f"/v1/systems/{sid}/guardians").json()["guardians"]
    assert next(g for g in again if g["slug"] == "injection_regex")["state"] == "off"
    rec = [
        r
        for r in gon.ctx.tables.query("console_action")
        if r["path"].endswith("/guardians/injection_regex")
    ]
    assert [x["outcome"] for x in sorted(rec, key=lambda x: x["ts"])] == ["attempted", "ok"]


def test_the_floor_is_a_lock_and_a_400(gon: Console) -> None:
    sid = create(gon, user_segment="customer", personal_data="identifiable")
    guardians = req(gon, "GET", f"/v1/systems/{sid}/guardians").json()["guardians"]
    dlp = next(g for g in guardians if g["slug"] == "dlp_vn")
    assert dlp["locked"] and dlp["floor_rules"] == ["AR-PDPL-CUSTOMER"] and dlp["effective"]
    r = req(gon, "PUT", f"/v1/systems/{sid}/guardians/dlp_vn", {"state": "off"})
    assert r.status_code == 400 and "guardian floor" in r.json()["error"]
    assert (
        req(gon, "PUT", f"/v1/systems/{sid}/guardians/dlp_vn", {"state": "on"}).status_code == 200
    )


def test_400s_never_500(gon: Console) -> None:
    sid = create(gon)
    url = f"/v1/systems/{sid}/guardians"
    cases = [
        (f"{url}/policy_rules", {"state": "off"}, "never bindable"),
        (f"{url}/nope", {"state": "off"}, "unknown feature slug"),
        (f"{url}/dlp_vn", {"state": "perhaps"}, "state must be one of on, off"),
        (f"{url}/dlp_vn", {}, "state must be one of on, off"),
        (f"{url}/dlp_vn", {"state": "off", "reason": 5}, "reason"),
        (f"{url}/dlp_vn", [1], "JSON object"),
    ]
    for u, body, msg in cases:
        r = req(gon, "PUT", u, body)
        assert r.status_code == 400 and msg in r.json()["error"], (u, body, r.text)
    bad = gon.client.put(f"{url}/dlp_vn", content=b"{not json", headers={"X-Dev-User": REVIEWER})
    assert bad.status_code == 400
    assert (
        req(gon, "PUT", "/v1/systems/nosuch/guardians/dlp_vn", {"state": "off"}).status_code == 404
    )
    assert req(gon, "GET", "/v1/systems/nosuch/guardians").status_code == 404
    req(gon, "POST", f"/v1/systems/{sid}/archive")
    r = req(gon, "PUT", f"{url}/dlp_vn", {"state": "off"})
    assert r.status_code == 400 and "archived" in r.json()["error"]


def test_scope_and_roles(gon: Console) -> None:
    mine = create(gon, user=OWNER_USER, name="Mine", owner_team=PAYOPS)
    other = create(gon, name="Other", owner_team="risk-team")
    ok = req(gon, "PUT", f"/v1/systems/{mine}/guardians/dlp_vn", {"state": "off"}, OWNER_USER)
    assert ok.status_code == 200
    assert req(gon, "GET", f"/v1/systems/{mine}/guardians", user=OWNER_USER).status_code == 200
    for method, body in (("GET", None), ("PUT", {"state": "off"})):
        r = req(
            gon,
            method,
            f"/v1/systems/{other}/guardians" + ("" if method == "GET" else "/dlp_vn"),
            body,
            OWNER_USER,
        )
        assert r.status_code == 404, (method, r.text)
    # a viewer reads (systems.view) and cannot write (systems.edit)
    assert rbac.allowed(frozenset({"auditor"}), "systems.view")
    assert not rbac.allowed(frozenset({"auditor"}), "systems.edit")
    assert (
        req(gon, "PUT", f"/v1/systems/{mine}/guardians/dlp_vn", {"state": "on"}, READER).status_code
        == 403
    )


def test_every_route_is_in_the_matrix(gon: Console) -> None:
    from tests.console.test_rbac_matrix import app_routes

    mine = {(m, p) for m, p, _ in app_routes() if "/systems/" in p and "/guardians" in p}
    assert mine == {
        ("GET", "/v1/systems/{system_id}/guardians"),
        ("PUT", "/v1/systems/{system_id}/guardians/{slug}"),
        ("POST", "/console/systems/{system_id}/guardians/{slug}"),
    }
    for method, path in mine:
        assert rbac.route_entry(method, path) is not None


# ---------------------------------------------------------------------------- the Catalog page
def page(c: Console, system: str | None = None, lang: str = "en", user: str = REVIEWER) -> Any:
    q = f"?lang={lang}" + (f"&system={system}" if system else "")
    return c.get(f"/console/catalog{q}", user=user)


def test_the_catalog_has_a_picker_and_no_switches_until_a_system_is_chosen(gon: Console) -> None:
    sid = create(gon, name="Picker test")
    html = page(gon).text
    assert 'id="gb-system"' in html and sid in html
    assert "/guardians/" not in html
    html = page(gon, sid).text
    assert f"/console/systems/{sid}/guardians/injection_regex" in html
    assert f"/console/systems/{sid}/guardians/judge_t2_sample" in html
    assert "Gate rules block or pause" in html  # policy_rules: a line, no switch
    assert "/guardians/policy_rules" not in html


def test_the_switch_posts_audits_and_redirects_back(gon: Console) -> None:
    sid = create(gon)
    r = gon.client.post(
        f"/console/systems/{sid}/guardians/injection_regex?lang=en",
        data={"state": "off"},
        headers={"X-Dev-User": REVIEWER, "Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert (
        r.status_code == 303 and r.headers["location"] == f"/console/catalog?system={sid}&lang=en"
    )
    assert gon.ctx.guardians.get(sid)["guardians"][0]["slug"]
    html = page(gon, sid).text
    assert "Off for this system" in html and "Switch on" in html
    h = gon.post(f"/console/systems/{sid}/guardians/injection_regex", {"state": "on"})
    assert h.status_code == 200 and h.headers["HX-Redirect"].endswith(f"system={sid}")
    rows = [x for x in gon.ctx.tables.query("console_action") if "/guardians/" in x["path"]]
    assert sorted(x["outcome"] for x in rows) == ["attempted", "attempted", "ok", "ok"]
    bad = gon.post(f"/console/systems/{sid}/guardians/dlp_vn", {"state": "banana"})
    assert bad.status_code == 400 and "state must be one of" in bad.text


def test_the_floor_shows_a_lock_and_no_button(gon: Console) -> None:
    sid = create(gon, user_segment="customer", personal_data="identifiable")
    html = page(gon, sid).text
    assert "Required by rules AR-PDPL-CUSTOMER; cannot be switched off" in html
    assert 'aria-label="Locked"' in html
    assert f"/console/systems/{sid}/guardians/dlp_vn" not in html  # a floor feature has no form
    assert f"/console/systems/{sid}/guardians/injection_regex" in html
    vi = page(gon, sid, "vi").text
    assert "Bắt buộc theo quy tắc AR-PDPL-CUSTOMER" in vi and "Chọn một hệ thống" in vi


def test_a_feature_the_instance_has_off_has_no_switch(
    gon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = create(gon)
    monkeypatch.setattr(gon.ctx.settings, "session_monitor_enabled", False)
    html = page(gon, sid).text
    assert "Off in this instance" in html
    assert f"/console/systems/{sid}/guardians/session_monitor" not in html


def test_a_person_without_edit_sees_state_and_no_button(gon: Console) -> None:
    sid = create(gon, user=OWNER_USER, name="Mine", owner_team=PAYOPS)
    assert not rbac.allowed(frozenset({"auditor"}), "systems.edit")
    html = page(gon, sid, user=READER).text
    assert "On for this system" in html and "/guardians/injection_regex" not in html
    assert "You need the right to edit this system" in html


def test_the_catalog_only_lists_systems_in_scope(gon: Console) -> None:
    mine = create(gon, user=OWNER_USER, name="Mine", owner_team=PAYOPS)
    other = create(gon, name="Other", owner_team="risk-team")
    html = page(gon, user=OWNER_USER).text
    assert mine in html and other not in html
    r = page(gon, other, user=OWNER_USER)
    assert r.status_code == 404
    assert page(gon, "bad id!").status_code == 400


def test_the_guardians_tab_lists_locked_and_off_features_and_links_to_the_catalog(
    gon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gon.ctx.settings, "console_nav_v3", True)  # the tab is a v3 tab
    sid = create(gon, user_segment="customer", personal_data="identifiable")
    req(gon, "PUT", f"/v1/systems/{sid}/guardians/injection_regex", {"state": "off"})
    html = gon.get(f"/console/systems/{sid}?tab=guardians&lang=en").text
    assert 'data-section="system-guardians-bindings"' in html
    assert "<code>dlp_vn</code>" in html and "<code>injection_regex</code>" in html
    assert f"/console/catalog?system={sid}" in html
    assert "Công tắc bảo vệ" in gon.get(f"/console/systems/{sid}?tab=guardians&lang=vi").text
    monkeypatch.setattr(gon.ctx.settings, "guardian_bindings_enabled", False)
    off = gon.get(f"/console/systems/{sid}?tab=guardians&lang=en").text
    assert "system-guardians-bindings" not in off
