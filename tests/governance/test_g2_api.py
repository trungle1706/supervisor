"""WP-G2 API: assignments, obligations, guardian floor, explain, run, and the classification
routes (scope, 400 shapes, segregation, audit rows)."""

from __future__ import annotations

from typing import Any

from .conftest import Console, draft

REVIEWER = "reviewer.an"
ADMIN = "admin.chi"
OWNER_USER = "payops-lead@example.invalid"  # owns the demo agent "payments"
PAYOPS = "Payments Ops"
VIEWER = "viewer.hoa"


def req(c: Console, method: str, url: str, body: Any = None, user: str = REVIEWER) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def create(c: Console, user: str = REVIEWER, **over: Any) -> dict[str, Any]:
    r = req(c, "POST", "/v1/systems", draft(owner_user=user, **over), user)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


# ---- rules ------------------------------------------------------------------------------------


def test_create_runs_the_rules_and_the_routes_show_them(on: Console) -> None:
    s = create(on, user_segment="customer", personal_data="identifiable", money_movement=True)
    sid = s["system_id"]
    r = req(on, "GET", f"/v1/systems/{sid}/assignments")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(body["assignments"]) > 40
    row = next(a for a in body["assignments"] if a["ref_id"] == "CTL-PII-MASK")
    assert row["kind"] == "control" and row["rule_id"] == "AR-PDPL-CUSTOMER"
    assert row["rules"][0]["fields"] == ["personal_data", "user_segment"]
    floor = req(on, "GET", f"/v1/systems/{sid}/guardian-floor").json()
    assert floor == {
        "system_id": sid,
        "count": 2,
        "floor": [
            {"slug": "dlp_vn", "rules": ["AR-PDPL-CUSTOMER"]},
            {"slug": "injection_regex", "rules": ["AR-C53-MONEY"]},
        ],
    }
    obl = req(on, "GET", f"/v1/systems/{sid}/obligations").json()
    # every obligation of the instruments the rules fire for (the counts grow with RegKB)
    import yaml as _yaml

    ids = {str(o["obligation"]) for o in obl["obligations"]}
    seen = set()
    expected = 0
    for f in sorted(
        (__import__("pathlib").Path(__file__).resolve().parents[2] / "regulations" / "vn").glob(
            "*.yaml"
        )
    ):
        doc = _yaml.safe_load(f.read_text(encoding="utf-8"))
        rows = {str(r["id"]) for r in doc["obligations"]}
        if rows & ids:
            seen.add(doc["instrument"]["id"])
            expected += len(rows)
    assert len(seen) == 2
    assert obl["count"] == expected >= 88 and {o["source"] for o in obl["obligations"]} == {"rule"}
    text = req(on, "GET", f"/v1/systems/{sid}/rules/explain").json()["lines"]
    assert any("AR-C53-MONEY: FIRED" in ln for ln in text) and all(ln.isascii() for ln in text)


def test_inactive_rows_are_hidden_unless_asked_for(on: Console) -> None:
    sid = create(on, user_segment="customer", personal_data="identifiable")["system_id"]
    req(on, "PATCH", f"/v1/systems/{sid}", {"personal_data": "none"})
    act = req(on, "GET", f"/v1/systems/{sid}/assignments").json()
    every = req(on, "GET", f"/v1/systems/{sid}/assignments?all=1").json()
    assert every["count"] > act["count"] and any(not a["active"] for a in every["assignments"])
    assert req(on, "GET", f"/v1/systems/{sid}/guardian-floor").json()["floor"] == []


def test_run_route_and_audit_rows(on: Console) -> None:
    sid = create(on, personal_data="none")["system_id"]
    before = len(on.ctx.tables.query("console_action"))
    r = req(on, "POST", f"/v1/systems/{sid}/assignments/run")
    assert r.status_code == 200 and r.json()["trigger"] == "manual"
    assert r.json()["rules_fired"] == ["AR-BASELINE"]
    new = on.ctx.tables.query("console_action", order_by=("ts",))[before:]
    assert [x["outcome"] for x in new] == ["attempted", "ok"]
    assert {x["target_kind"] for x in new} == {"system"}


def test_rules_routes_scope_and_errors(on: Console) -> None:
    mine = create(on, user=OWNER_USER, name="Mine", owner_team=PAYOPS)["system_id"]
    other = create(on, name="Other", owner_team="risk-team")["system_id"]
    for url in ("assignments", "obligations", "guardian-floor", "rules/explain", "classification"):
        assert req(on, "GET", f"/v1/systems/{mine}/{url}", user=OWNER_USER).status_code == 200
        assert req(on, "GET", f"/v1/systems/{other}/{url}", user=OWNER_USER).status_code == 404, url
        assert req(on, "GET", f"/v1/systems/sys_nope/{url}").status_code == 404, url
        assert req(on, "GET", f"/v1/systems/bad%20id/{url}").status_code == 400, url
    assert (
        req(on, "POST", f"/v1/systems/{other}/assignments/run", user=OWNER_USER).status_code == 404
    )
    assert (
        req(on, "POST", f"/v1/systems/{other}/classification", user=OWNER_USER).status_code == 404
    )
    assert req(on, "POST", "/v1/systems/sys_nope/assignments/run").status_code == 404


def test_flag_off_with_routes_mounted_is_400(console: Console, mounted: None) -> None:
    for url in ("assignments", "guardian-floor", "classification"):
        r = req(console, "GET", f"/v1/systems/sys_x/{url}")
        assert r.status_code == 400 and "GOVERNANCE_ENABLED" in r.json()["error"], url


# ---- classification ---------------------------------------------------------------------------


def test_classification_flow_over_the_api(on: Console) -> None:
    sid = create(on, money_movement=True)["system_id"]
    url = f"/v1/systems/{sid}/classification"
    assert req(on, "GET", url).json()["draft"] is None
    r = req(on, "POST", url)
    assert r.status_code == 201
    d = r.json()
    assert d["outcome"] == "high_risk" and d["status"] == "draft"
    assert {a["id"] for a in d["answers"]} == {"Q-MONEY", "Q-CREDIT", "Q-PRE-APPROVAL", "Q-OTHER"}
    r = req(on, "PATCH", url, {"Q-OTHER": {"answer": "no", "justification": "Checked by hand."}})
    assert r.status_code == 200 and r.json()["outcome"] == "high_risk"
    r = req(on, "PATCH", url, {"answers": {"Q-CREDIT": {"answer": "no", "justification": ""}}})
    assert r.status_code == 200
    r = req(on, "POST", f"{url}/apply", {}, ADMIN)
    assert r.status_code == 200
    out = r.json()
    assert out["applied"]["outcome"] == "high_risk" and out["draft"] is None
    got = req(on, "GET", f"/v1/systems/{sid}").json()
    assert (
        got["decision33_class"] == "high_risk" and got["effective_risk"]["source"] == "classifier"
    )
    floor = req(on, "GET", f"/v1/systems/{sid}/guardian-floor").json()["floor"]
    assert {f["slug"] for f in floor} == {"dlp_vn", "injection_regex"}
    rows = on.ctx.tables.query("console_action", order_by=("ts",))
    assert sum(1 for x in rows if x["outcome"] == "ok" and x["permission"] == "systems.edit") >= 4


def test_classification_errors_are_400_with_a_message(on: Console) -> None:
    sid = create(on)["system_id"]
    url = f"/v1/systems/{sid}/classification"
    r = req(on, "PATCH", url, {"Q-OTHER": {"answer": "no"}})
    assert r.status_code == 400 and "no draft" in r.json()["error"]
    r = req(on, "POST", f"{url}/apply", {})
    assert r.status_code == 400 and "no draft" in r.json()["error"]
    req(on, "POST", url)
    for body in (
        {"Q-NOPE": {"answer": "no"}},
        {"Q-OTHER": {"answer": "perhaps"}},
        {"Q-OTHER": "no"},
        {},
        [1],
    ):
        r = req(on, "PATCH", url, body)
        assert r.status_code == 400 and r.json()["error"], body
    r = req(on, "POST", f"{url}/apply", {"confirm_ai_prefill": "yes"})
    assert r.status_code == 400 and "true or false" in r.json()["error"]
    r = req(on, "POST", f"{url}/apply", {})
    assert r.status_code == 400 and "not complete" in r.json()["error"]


def test_apply_refuses_the_reviewer_of_the_system(on: Console) -> None:
    sid = create(on, user=OWNER_USER, name="Mine", owner_team=PAYOPS, money_movement=True)[
        "system_id"
    ]
    r = req(on, "POST", f"/v1/systems/{sid}/team", {"user_id": REVIEWER, "team_role": "reviewer"})
    assert r.status_code == 200, r.text
    req(on, "POST", f"/v1/systems/{sid}/classification", user=OWNER_USER)
    r = req(on, "POST", f"/v1/systems/{sid}/classification/apply", {}, REVIEWER)
    assert r.status_code == 400
    assert r.json()["error"].startswith("segregation of duties:")
    assert req(on, "GET", f"/v1/systems/{sid}").json()["decision33_class"] == "unclassified"
    r = req(on, "POST", f"/v1/systems/{sid}/classification/apply", {}, ADMIN)
    assert r.status_code == 200


def test_viewer_cannot_draft_edit_or_apply(on: Console) -> None:
    sid = create(on)["system_id"]
    req(on, "POST", f"/v1/systems/{sid}/team", {"user_id": VIEWER, "team_role": "data_steward"})
    for method, suffix in (
        ("POST", "classification"),
        ("PATCH", "classification"),
        ("POST", "classification/apply"),
        ("POST", "assignments/run"),
    ):
        r = req(on, method, f"/v1/systems/{sid}/{suffix}", {}, VIEWER)
        assert r.status_code in (400, 403), (method, suffix, r.status_code)
    # the viewer role holds only systems.view: with RBAC on it is a clean 403
    on.ctx.settings.api_rbac_enabled = True
    try:
        for method, suffix in (("POST", "classification"), ("POST", "classification/apply")):
            assert req(on, method, f"/v1/systems/{sid}/{suffix}", {}, VIEWER).status_code == 403
        assert req(on, "GET", f"/v1/systems/{sid}/classification", user=VIEWER).status_code == 200
    finally:
        on.ctx.settings.api_rbac_enabled = False
