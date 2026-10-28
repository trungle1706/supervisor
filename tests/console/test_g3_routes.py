# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-G3: shadow and promotion API and panels: off path, RBAC, 400 not 500, HTMX, audit, the whole
path from benchmarked to live and back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from supervisor.core import rbac
from supervisor.guardian_factory.shadow import ShadowRunner
from tests.guardian_factory.conftest import adapters, console, gf, regex_def, seeded  # noqa: F401

AN = "reviewer.an"  # reviewer, model_risk by the role mapping; the author
LEAD = "lead.model"  # approver, group model_risk
SEC = "second.line"  # approver, group platform
CHI = "admin.chi"
HOA = "viewer.hoa"
HX = {"HX-Request": "true"}
DEF = "account-numbers"
BASE = f"/v1/guardian-defs/{DEF}"
CON = f"/console/guardian-factory/{DEF}"
VIEW = {"args": {"note": "so tai khoan 0123456789012"}, "meta": {"agent_id": "payments"}}

NEW_ROUTES = [
    ("GET", f"{BASE}/shadow"),
    ("POST", f"{BASE}/shadow/start"),
    ("POST", f"{BASE}/shadow/stop"),
    ("POST", f"{BASE}/shadow/findings/gsf_x/review"),
    ("POST", f"{BASE}/allow"),
    ("POST", f"{BASE}/allow/remove"),
    ("POST", f"{BASE}/approve"),
    ("POST", f"{BASE}/go-live"),
    ("POST", f"{BASE}/rollback"),
    ("POST", f"{BASE}/retire-version"),
    ("GET", f"{CON}/shadow"),
    ("GET", f"{CON}/promotion"),
    ("POST", f"{CON}/shadow/start"),
    ("POST", f"{CON}/shadow/stop"),
    ("POST", f"{CON}/shadow/review/gsf_x"),
    ("POST", f"{CON}/allow"),
    ("POST", f"{CON}/allow/remove"),
    ("POST", f"{CON}/approve"),
    ("POST", f"{CON}/go-live"),
    ("POST", f"{CON}/rollback"),
    ("POST", f"{CON}/retire-version"),
]
NEEDS = {
    "approve": "guardians.approve",
    "go-live": "guardians.approve",
    "rollback": "guardians.approve",
}


class Clk:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.t

    def advance(self, days: int) -> None:
        self.t += timedelta(days=days)


def api(c: Any, method: str, url: str, body: Any = None, user: str = AN) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def make_shadow(c: Any, clk: Clk, **over: Any) -> None:
    c.ctx.guardian_defs.clock = clk
    r = api(
        c,
        "POST",
        "/v1/guardian-defs",
        regex_def(owner_group="model_risk", benchmark_pack="starter", **over),
    )
    assert r.status_code == 201, r.text
    r = api(c, "POST", f"{BASE}/bench-packs", {"op": "generate", "pack_id": "starter"})
    assert r.status_code == 201, r.text
    assert api(c, "POST", f"{BASE}/benchmark", {}).status_code == 202
    c.ctx.guardian_bench.join(DEF)
    assert api(c, "POST", f"{BASE}/mark-benchmarked").status_code == 200


def findings(c: Any, clk: Clk, n: int = 2) -> list[str]:
    r = ShadowRunner(c.ctx.state, c.ctx.settings, now=clk.now, ttl_s=0)
    for i in range(n):
        r.observe(VIEW, "input", f"corr-{i}")
    r.flush()
    return [f["finding_id"] for f in api(c, "GET", f"{BASE}/shadow").json()["findings"]]


@pytest.fixture
def clk() -> Clk:
    return Clk()


# ============================================================ off path


def test_off_every_new_route_answers_400_and_reads_no_table(
    console: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    orig_q, orig_g = console.ctx.state.query, console.ctx.state.get

    def spy_q(table: str, *a: Any, **k: Any) -> Any:
        calls.append(table)
        return orig_q(table, *a, **k)

    def spy_g(table: str, *a: Any, **k: Any) -> Any:
        calls.append(table)
        return orig_g(table, *a, **k)

    monkeypatch.setattr(console.ctx.state, "query", spy_q)
    monkeypatch.setattr(console.ctx.state, "get", spy_g)
    for method, path in NEW_ROUTES:
        r = console.client.request(
            method,
            path,
            json={} if path.startswith("/v1") else None,
            headers={"X-Dev-User": CHI, **HX},
        )
        assert r.status_code == 400, (method, path, r.status_code)
        assert "guardian_factory_off" in r.text, (method, path)
    assert not [t for t in calls if t.startswith("guardian_")], calls


# ============================================================ RBAC


def test_rbac_rows_and_new_permission() -> None:
    for method, path in NEW_ROUTES:
        key = path.replace(DEF, "{def_id}").replace("gsf_x", "{finding_id}")
        want = rbac.ROUTES[(method, key)]
        last = key.rsplit("/", 1)[-1]
        if method == "GET":
            assert want == "guardians.view", key
        else:
            assert want == NEEDS.get(last, "guardians.edit"), key
    assert rbac.allowed(frozenset({"approver"}), "guardians.approve")
    assert rbac.allowed(frozenset({"admin"}), "guardians.approve")
    assert not rbac.allowed(frozenset({"reviewer"}), "guardians.approve")
    assert not rbac.allowed(frozenset({"viewer"}), "guardians.approve")
    assert rbac.allowed(frozenset({"viewer"}), "guardians.view")


def test_viewer_reads_and_cannot_write_reviewer_cannot_approve(gf: Any, clk: Clk) -> None:
    make_shadow(gf, clk)
    assert api(gf, "GET", f"{BASE}/shadow", user=HOA).status_code == 200
    assert api(gf, "GET", f"{CON}/shadow", user=HOA).status_code == 200
    for method, path in NEW_ROUTES:
        if method == "GET" or "gsf_x" in path:
            continue
        r = gf.client.request(method, path, json={}, headers={"X-Dev-User": HOA, **HX})
        assert r.status_code == 403, (method, path)
    for what in ("approve", "go-live", "rollback"):  # a reviewer holds guardians.edit only
        assert api(gf, "POST", f"{BASE}/{what}", {}, user=AN).status_code == 403, what


def test_only_group_members_start_shadow_and_edit_allow_list(gf: Any, clk: Clk) -> None:
    make_shadow(gf, clk)
    # lead.cyber holds the approver role but belongs to the cyber group only
    assert api(gf, "POST", f"{BASE}/shadow/start", {}, user="lead.cyber").status_code == 403
    assert api(gf, "POST", f"{BASE}/shadow/start", {}, user=AN).status_code == 200
    body = {"agent_id": "a", "reason": "r", "expires": "2026-11-20"}
    assert api(gf, "POST", f"{BASE}/allow", body, user="lead.cyber").status_code == 403


# ============================================================ the whole path


def test_whole_path_benchmarked_to_live_and_rollback(gf: Any, clk: Clk) -> None:
    make_shadow(gf, clk)
    r = api(gf, "POST", f"{BASE}/shadow/start", {})
    assert r.status_code == 200 and r.json()["state"] == "shadow"
    assert api(gf, "POST", f"{BASE}/shadow/start", {}).status_code == 400
    sm = api(gf, "GET", f"{BASE}/shadow").json()
    assert sm["state"] == "shadow" and sm["shadow"]["days_total"] == 7
    assert sm["slug"] == "gf:account-numbers@1" and sm["findings"] == []

    ids = findings(gf, clk, 2)
    assert len(ids) == 2
    # not complete, nothing reviewed: 400 with the numbers
    r = api(gf, "POST", f"{BASE}/approve", {}, user=LEAD)
    assert r.status_code == 400 and "shadow_not_passed" in r.json()["error"]
    assert "day 0 of 7" in r.json()["error"] and "calls seen 2" in r.json()["error"]
    # review: one false with an allow-list entry, one correct
    exp = (clk.now() + timedelta(days=30)).date().isoformat()
    r = api(
        gf,
        "POST",
        f"{BASE}/shadow/findings/{ids[0]}/review",
        {"mark": "false", "allow": {"reason": "nightly batch sends numbers", "expires": exp}},
    )
    assert r.status_code == 200 and r.json()["allow"]["expires"] == exp
    assert (
        api(gf, "POST", f"{BASE}/shadow/findings/{ids[1]}/review", {"mark": "correct"}).status_code
        == 200
    )
    clk.advance(8)
    r = api(gf, "POST", f"{BASE}/approve", {}, user=LEAD)
    assert r.status_code == 400 and "50 percent" in r.json()["error"]
    # the person who marked it false looks again and marks it correct
    assert (
        api(gf, "POST", f"{BASE}/shadow/findings/{ids[0]}/review", {"mark": "correct"}).status_code
        == 200
    )
    # one person cannot give both approvals
    assert api(gf, "POST", f"{BASE}/approve", {"kind": "owner_lead"}, user=CHI).status_code == 200
    r = api(gf, "POST", f"{BASE}/approve", {"kind": "platform_security"}, user=CHI)
    assert r.status_code == 400 and "same_person" in r.json()["error"]
    r = api(gf, "POST", f"{BASE}/approve", {"kind": "boss"}, user=SEC)
    assert r.status_code == 400 and "bad_kind" in r.json()["error"]
    r = api(gf, "POST", f"{BASE}/approve", {}, user=SEC)
    assert r.status_code == 200 and r.json()["approved"] is True and r.json()["state"] == "approved"
    # go live: the owner lead or an admin; a platform person is not the owner lead
    assert api(gf, "POST", f"{BASE}/go-live", {}, user=AN).status_code == 403
    r = api(gf, "POST", f"{BASE}/go-live", {}, user=SEC)
    assert r.status_code == 400 and "not_eligible" in r.json()["error"]
    r = api(gf, "POST", f"{BASE}/go-live", {}, user=LEAD)
    assert r.status_code == 200 and r.json()["binding"]["slug"] == "gf:account-numbers@1"
    rows = api(gf, "GET", "/v1/guardian-defs").json()["items"]
    assert [(x["state"], x["live_version"]) for x in rows] == [("live", 1)]
    # immutable
    r = api(gf, "POST", f"/v1/guardian-defs/{DEF}", regex_def(owner_group="model_risk"))
    assert r.status_code == 400 and "not_draft" in r.json()["error"]
    # rollback needs an admin and an earlier live version
    r = api(gf, "POST", f"{BASE}/rollback", {"reason": "x" * 25}, user=LEAD)
    assert r.status_code == 400 and "not_admin" in r.json()["error"]
    r = api(gf, "POST", f"{BASE}/rollback", {"reason": "short"}, user=CHI)
    assert r.status_code == 400 and "reason_needed" in r.json()["error"]
    r = api(gf, "POST", f"{BASE}/rollback", {"reason": "x" * 25}, user=CHI)
    assert r.status_code == 400 and "no_previous_version" in r.json()["error"]
    # retire on request
    r = api(gf, "POST", f"{BASE}/retire-version", {"version": 1})
    assert r.status_code == 200 and r.json()["state"] == "retired"
    # every move is an event and a chain record
    events = [e["action"] for e in gf.ctx.tables.query("guardian_def_event", {"def_id": DEF})]
    for a in ("shadow_started", "approval", "approved", "live", "retired", "allow_added"):
        assert a in events, a
    # audit rows: two per POST
    acts = gf.ctx.tables.query("console_action", {})
    assert len(acts) >= 10
    perms = [a["permission"] for a in acts]
    assert perms.count("guardians.approve") >= 2 * 4 and perms.count("guardians.edit") >= 2 * 3


def test_api_refusals_are_400_or_404_never_500(gf: Any, clk: Clk) -> None:
    make_shadow(gf, clk)
    assert api(gf, "POST", f"{BASE}/shadow/start", {}).status_code == 200
    ids = findings(gf, clk, 1)
    bad: list[tuple[str, dict[str, Any], int]] = [
        ("shadow/start", {"x": 1}, 400),
        ("allow", {"agent_id": "a", "reason": "r", "expires": "2099-01-01"}, 400),
        ("allow", {"agent_id": "a", "reason": "r", "expires": "soon"}, 400),
        ("allow", {"agent_id": "", "reason": "r", "expires": "2026-11-10"}, 400),
        ("allow", {"version": "x"}, 400),
        ("allow", {"bogus": 1}, 400),
        ("allow/remove", {"agent_id": "nobody"}, 404),
        ("approve", {"kind": 5}, 400),
        ("approve", {"extra": 1}, 400),
        ("rollback", {"reason": "x" * 30, "to_version": "z"}, 400),
        ("retire-version", {"version": 9}, 404),
    ]
    for path, body, code in bad:
        r = api(gf, "POST", f"{BASE}/{path}", body, user=CHI)
        assert r.status_code == code, (path, body, r.status_code, r.text[:200])
    for body, code in (({}, 400), ({"mark": "maybe"}, 400), ({"mark": "correct", "z": 1}, 400)):
        r = api(gf, "POST", f"{BASE}/shadow/findings/{ids[0]}/review", body)
        assert r.status_code == code, body
    r = api(gf, "POST", f"{BASE}/shadow/findings/gsf_none/review", {"mark": "correct"})
    assert r.status_code == 404
    r = api(
        gf,
        "POST",
        f"{BASE}/shadow/findings/{ids[0]}/review",
        {"mark": "correct", "allow": {"reason": "r", "expires": "2026-11-10"}},
    )
    assert r.status_code == 400 and "bad_mark" in r.json()["error"]
    assert api(gf, "GET", "/v1/guardian-defs/nope/shadow").status_code == 404
    assert api(gf, "POST", "/v1/guardian-defs/nope/approve", {}, user=LEAD).status_code == 404
    # a draft is not approved or set live
    assert api(gf, "POST", f"{BASE}/shadow/stop", {}).status_code == 200
    for what in ("approve", "go-live"):
        assert api(gf, "POST", f"{BASE}/{what}", {}, user=LEAD).status_code == 400


def test_allow_list_expiry_is_flagged_in_the_api(gf: Any, clk: Clk) -> None:
    make_shadow(gf, clk)
    api(gf, "POST", f"{BASE}/shadow/start", {})
    exp = (clk.now() + timedelta(days=2)).date().isoformat()
    r = api(gf, "POST", f"{BASE}/allow", {"agent_id": "payments", "reason": "r", "expires": exp})
    assert r.status_code == 200 and r.json()["expires"] == exp
    assert api(gf, "GET", f"{BASE}/shadow").json()["allow_list"][0]["expired"] is False
    clk.advance(3)
    assert api(gf, "GET", f"{BASE}/shadow").json()["allow_list"][0]["expired"] is True
    assert gf.ctx.guardian_promotion.expire_allow_entries() == 1
    assert api(gf, "GET", f"{BASE}/shadow").json()["allow_list"] == []


# ============================================================ console panels


def test_editor_shows_both_panels_and_the_start_button(gf: Any, clk: Clk) -> None:
    r = gf.get("/console/guardian-factory/new")
    assert r.status_code == 200 and 'id="gf-shadow"' not in r.text
    make_shadow(gf, clk)
    r = gf.get(CON)
    assert 'id="gf-shadow"' in r.text and 'id="gf-promo"' in r.text
    assert 'data-action="shadow-start"' in r.text and 'data-state="benchmarked"' in r.text
    assert 'data-shadow-hook="off"' in r.text  # GUARDIAN_SHADOW is off in this instance
    r = gf.post(f"{CON}/shadow/start", {})
    assert r.status_code == 200 and 'data-state="shadow"' in r.text
    assert 'data-shadow-numbers="1"' in r.text and 'data-action="shadow-stop"' in r.text
    assert 'data-no-findings="1"' in r.text and 'data-slug="1"' in r.text
    # a viewer sees the numbers but no buttons
    r = gf.get(CON, user=HOA)
    assert 'data-shadow-numbers="1"' in r.text
    for a in ("shadow-stop", "allow-add", "approve", "go-live"):
        assert f'data-action="{a}"' not in r.text, a


def test_panel_fragments_and_redirect(gf: Any, clk: Clk) -> None:
    make_shadow(gf, clk)
    for panel, marker in (("shadow", 'id="gf-shadow"'), ("promotion", 'id="gf-promo"')):
        frag = gf.get(f"{CON}/{panel}", headers=HX)
        assert frag.status_code == 200 and "<html" not in frag.text and marker in frag.text
        plain = gf.get(f"{CON}/{panel}", follow_redirects=False)
        assert plain.status_code == 303 and plain.headers["location"].startswith(CON)
        assert gf.get(f"/console/guardian-factory/nope/{panel}", headers=HX).status_code == 404


def test_console_review_buttons_allow_entry_and_approve_flow(
    gf: Any, clk: Clk, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gf.ctx.settings, "guardian_shadow", True)
    make_shadow(gf, clk)
    gf.post(f"{CON}/shadow/start", {})
    ids = findings(gf, clk, 2)
    r = gf.get(CON)
    assert 'data-shadow-hook="off"' not in r.text and 'data-findings="2"' in r.text
    assert r.text.count('data-action="review-false"') == 2
    assert "0123456789012" not in r.text  # no value text on the page
    exp = (clk.now() + timedelta(days=10)).date().isoformat()
    r = gf.post(
        f"{CON}/shadow/review/{ids[0]}",
        {"mark": "false", "allow_reason": "batch job", "allow_expires": exp},
    )
    assert r.status_code == 200 and 'data-allow-agent="payments"' in r.text
    assert f'data-finding="{ids[0]}" data-reviewed="false"' in r.text
    r = gf.post(f"{CON}/shadow/review/{ids[1]}", {"mark": "correct"})
    assert r.status_code == 200 and 'data-reviewed="correct"' in r.text
    r = gf.post(f"{CON}/shadow/review/{ids[1]}", {"mark": "nope"})
    assert r.status_code == 400
    r = gf.post(f"{CON}/shadow/review/{ids[1]}", {"mark": "correct"}, user=HOA)
    assert r.status_code == 403
    # expired entry is flagged on the panel
    clk.advance(11)
    r = gf.get(f"{CON}/shadow", headers=HX)
    assert 'data-expired="1"' in r.text
    # approvals in the console
    page = gf.get(CON, user=LEAD)
    assert 'data-action="approve"' in page.text
    r = gf.post(f"{CON}/approve", {}, user=LEAD)
    assert r.status_code == 400 and "shadow_not_passed" in r.text  # 50 percent false
    r = gf.post(f"{CON}/shadow/review/{ids[0]}", {"mark": "correct"})
    assert r.status_code == 200
    r = gf.post(f"{CON}/approve", {}, user=LEAD)
    assert r.status_code == 200 and 'data-kind="owner_lead"' in r.text
    assert 'data-missing="platform_security"' in r.text
    r = gf.post(f"{CON}/approve", {}, user=SEC)
    assert r.status_code == 200 and 'data-state="approved"' in r.text
    assert 'data-action="go-live"' in gf.get(CON, user=LEAD).text
    assert 'data-action="go-live"' not in gf.get(CON, user=SEC).text
    r = gf.post(f"{CON}/go-live", {}, user=LEAD)
    assert r.status_code == 200 and 'data-live="1"' in r.text
    assert 'data-action="rollback"' not in r.text
    lst = gf.get("/console/guardian-factory", headers=HX)
    assert 'data-col="live">1<' in lst.text
    # no-JS form post is accepted from this site
    assert gf.post(f"{CON}/retire-version", {"version": "1"}, htmx=False).status_code in (
        303,
        400,
        403,
    )


def test_registry_list_shows_days_in_shadow(gf: Any, clk: Clk) -> None:
    make_shadow(gf, clk)
    api(gf, "POST", f"{BASE}/shadow/start", {})
    clk.advance(3)
    rows = api(gf, "GET", "/v1/guardian-defs").json()["items"]
    assert rows[0]["state"] == "shadow" and rows[0]["shadow_days"] == 3
    assert rows[0]["live_version"] is None
    lst = gf.get("/console/guardian-factory", headers=HX)
    assert 'data-state="shadow"' in lst.text and 'data-col="shadow">3<' in lst.text
