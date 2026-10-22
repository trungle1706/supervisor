"""WP-G1 API: approvals, stage, reviews (RBAC, scope, audit rows, 400 and 404 shapes)."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.core import rbac

from .conftest import Console, draft

REVIEWER = "reviewer.an"  # reviewer
APPROVER = "approver.em"  # approver
BOTH = "reviewer.binh"  # reviewer and approver
ADMIN = "admin.chi"
OWNER_USER = "payops-lead@example.invalid"  # owner role
PAYOPS = "Payments Ops"
VIEWER = "viewer.hoa"


def req(c: Console, method: str, url: str, body: Any = None, user: str = REVIEWER) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def make(c: Console, user: str = OWNER_USER, **over: Any) -> str:
    body = draft(owner_user=user, **{"owner_team": PAYOPS, **over})
    r = req(c, "POST", "/v1/systems", body, user)
    assert r.status_code == 201, r.text
    return str(r.json()["system_id"])


def test_stage_flow_over_the_api(on: Console) -> None:
    sid = make(on)
    base = f"/v1/systems/{sid}"
    # the owner moves to design directly; deployment needs an approval
    r = req(on, "POST", f"{base}/stage", {"to_stage": "design"}, OWNER_USER)
    assert r.status_code == 200 and r.json()["lifecycle_stage"] == "design"
    r = req(on, "POST", f"{base}/stage", {"to_stage": "deployment"}, OWNER_USER)
    assert r.status_code == 400 and "approved stage approval" in r.json()["error"]
    r = req(on, "POST", f"{base}/approvals", {"to_stage": "deployment"}, OWNER_USER)
    assert r.status_code == 201, r.text
    ap = r.json()
    assert ap["status"] == "pending" and ap["requested_by"] == OWNER_USER
    listed = req(on, "GET", f"{base}/approvals", user=OWNER_USER).json()
    assert [a["approval_id"] for a in listed["approvals"]] == [ap["approval_id"]]
    # the owner cannot answer it, an approver can
    url = f"{base}/approvals/{ap['approval_id']}/decide"
    r = req(on, "POST", url, {"decision": "approve"}, OWNER_USER)
    assert r.status_code == 400 and "only a reviewer or oversight manager" in r.json()["error"]
    r = req(on, "POST", url, {"decision": "approve", "reason": "ok"}, APPROVER)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = req(on, "POST", f"{base}/stage", {"to_stage": "deployment"}, OWNER_USER)
    assert r.status_code == 200 and r.json()["lifecycle_stage"] == "deployment"
    # PATCH cannot move the stage
    r = req(on, "PATCH", base, {"lifecycle_stage": "operation"}, REVIEWER)
    assert r.status_code == 400 and "/stage" in r.json()["error"]
    kinds = [e["kind"] for e in on.ctx.state.query("outbound_event")]
    assert sorted(kinds) == ["stage_approved", "system_registered"]
    chain = on.ctx.tables.query("chain_entry", {"record_type": "stage_change"})
    assert len(chain) == 4  # move, request, approve, move


def test_segregation_of_duties_over_the_api(on: Console) -> None:
    sid = make(on, user=BOTH, owner_team="risk-team")  # an approver who owns the system
    base = f"/v1/systems/{sid}"
    ap = req(on, "POST", f"{base}/approvals", {"to_stage": "operation"}, BOTH).json()
    r = req(
        on, "POST", f"{base}/approvals/{ap['approval_id']}/decide", {"decision": "approve"}, BOTH
    )
    assert r.status_code == 400 and r.json()["error"].startswith("segregation of duties:")
    # a requester who holds the approver role cannot answer their own request
    sid2 = make(on, name="Second")
    ap2 = req(on, "POST", f"/v1/systems/{sid2}/approvals", {"to_stage": "deployment"}, BOTH).json()
    r = req(
        on,
        "POST",
        f"/v1/systems/{sid2}/approvals/{ap2['approval_id']}/decide",
        {"decision": "approve"},
        BOTH,
    )
    assert r.status_code == 400 and r.json()["error"].startswith("segregation of duties:")
    # a team reviewer (global role reviewer) may answer; the response is the approval
    req(
        on,
        "POST",
        f"/v1/systems/{sid2}/team",
        {"user_id": REVIEWER, "team_role": "reviewer"},
        ADMIN,
    )
    r = req(
        on,
        "POST",
        f"/v1/systems/{sid2}/approvals/{ap2['approval_id']}/decide",
        {"decision": "reject", "reason": "Not yet"},
        REVIEWER,
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_bad_input_is_400_and_unknown_is_404(on: Console) -> None:
    sid = make(on)
    base = f"/v1/systems/{sid}"
    ap = req(on, "POST", f"{base}/approvals", {"to_stage": "deployment"}, OWNER_USER).json()
    rv = req(
        on,
        "POST",
        f"{base}/reviews",
        {"kind": "internal", "title": "T", "reviewer_user": REVIEWER},
        REVIEWER,
    ).json()
    cases = [
        ("POST", f"{base}/approvals", {"to_stage": "launch"}),
        ("POST", f"{base}/approvals", {}),
        ("POST", f"{base}/approvals", [1]),
        ("POST", f"{base}/approvals", {"to_stage": "deployment"}),  # a second pending one
        ("POST", f"{base}/approvals", {"to_stage": "design"}),
        ("POST", f"{base}/approvals/{ap['approval_id']}/decide", {"decision": "maybe"}),
        ("POST", f"{base}/approvals/{ap['approval_id']}/decide", {"decision": "reject"}),
        ("POST", f"{base}/stage", {"to_stage": "x"}),
        ("POST", f"{base}/stage", {}),
        ("POST", f"{base}/stage", {"to_stage": "initiation"}),
        ("POST", f"{base}/reviews", {"kind": "x", "title": "T", "reviewer_user": "a"}),
        ("POST", f"{base}/reviews", {"title": "T"}),
        (
            "POST",
            f"{base}/reviews",
            {"kind": "internal", "title": "T", "reviewer_user": OWNER_USER},
        ),
        ("PATCH", f"{base}/reviews/{rv['review_id']}", {}),
        ("PATCH", f"{base}/reviews/{rv['review_id']}", {"title": "x", "row_version": "one"}),
        ("PATCH", f"{base}/reviews/{rv['review_id']}", {"title": "x", "row_version": 99}),
        ("PATCH", f"{base}/reviews/{rv['review_id']}", {"status": "completed"}),
        ("POST", f"{base}/reviews/{rv['review_id']}/reopen", {"reason": "x"}),  # not completed
        ("POST", f"{base}/reviews/{rv['review_id']}/complete", None),  # not the reviewer: admin
    ]
    for method, url, body in cases:
        # an admin may do everything; a reviewer who is not the named one may not complete
        r = req(on, method, url, body, BOTH if url.endswith("/complete") else ADMIN)
        assert r.status_code == 400, (method, url, body, r.status_code, r.text[:200])
        assert r.json()["error"], (method, url)
    raw = on.client.post(f"{base}/stage", content=b"{nope", headers={"X-Dev-User": OWNER_USER})
    assert raw.status_code == 400 and "JSON" in raw.json()["error"]
    for method, url, body, user in [
        ("GET", "/v1/systems/sys_nope/approvals", None, REVIEWER),
        ("POST", "/v1/systems/sys_nope/approvals", {"to_stage": "deployment"}, REVIEWER),
        ("POST", "/v1/systems/sys_nope/stage", {"to_stage": "design"}, REVIEWER),
        ("GET", "/v1/systems/sys_nope/reviews", None, REVIEWER),
        ("POST", "/v1/systems/sys_nope/reviews", {"kind": "internal"}, REVIEWER),
        ("POST", f"{base}/approvals/ap_nope/decide", {"decision": "approve"}, APPROVER),
        ("PATCH", f"{base}/reviews/rv_nope", {"title": "x"}, REVIEWER),
        ("POST", f"{base}/reviews/rv_nope/complete", None, REVIEWER),
        ("POST", f"{base}/reviews/rv_nope/reopen", {"reason": "x"}, REVIEWER),
    ]:
        r = req(on, method, url, body, user)
        assert r.status_code == 404 and r.json()["error"], (method, url, r.status_code, r.text)


def test_review_flow_over_the_api(on: Console) -> None:
    sid = make(on)
    base = f"/v1/systems/{sid}/reviews"
    body = {
        "kind": "conformity",
        "title": "Conformity check",
        "reviewer_user": REVIEWER,
        "scope": [{"kind": "system", "id": sid}],
        "window_start": "2026-02-01T00:00:00Z",
    }
    r = req(on, "POST", base, body, REVIEWER)
    assert r.status_code == 201, r.text
    rid = r.json()["review_id"]
    assert req(on, "GET", base, user=OWNER_USER).json()["count"] == 1  # the owner can read
    r = req(on, "PATCH", f"{base}/{rid}", {"status": "in_progress"}, REVIEWER)
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    r = req(on, "POST", f"{base}/{rid}/complete", None, ADMIN)  # an admin may complete
    assert r.status_code == 200 and r.json()["locked"] is True
    r = req(on, "PATCH", f"{base}/{rid}", {"title": "Changed"}, REVIEWER)
    assert r.status_code == 400 and "locked" in r.json()["error"]
    r = req(on, "POST", f"{base}/{rid}/reopen", {}, REVIEWER)
    assert r.status_code == 400 and "reason" in r.json()["error"]
    r = req(on, "POST", f"{base}/{rid}/reopen", {"reason": "More evidence"}, REVIEWER)
    assert r.status_code == 200 and r.json()["status"] == "reopened"
    r = req(on, "PATCH", f"{base}/{rid}", {"title": "Changed"}, REVIEWER)
    assert r.status_code == 200 and r.json()["title"] == "Changed"
    kinds = [e["kind"] for e in on.ctx.state.query("outbound_event")]
    assert "review_completed" in kinds
    assert len(on.ctx.tables.query("chain_entry", {"record_type": "review_change"})) == 5


def test_scope_hides_approvals_and_reviews_of_other_teams(on: Console) -> None:
    secret = make(on, user=REVIEWER, name="Secret", owner_team="risk-team")
    for method, url, body in [
        ("GET", f"/v1/systems/{secret}/approvals", None),
        ("POST", f"/v1/systems/{secret}/approvals", {"to_stage": "deployment"}),
        ("POST", f"/v1/systems/{secret}/stage", {"to_stage": "design"}),
        ("GET", f"/v1/systems/{secret}/reviews", None),
    ]:
        assert req(on, method, url, body, OWNER_USER).status_code == 404, url
    ap = req(on, "POST", f"/v1/systems/{secret}/approvals", {"to_stage": "deployment"}).json()
    r = req(
        on,
        "POST",
        f"/v1/systems/{secret}/approvals/{ap['approval_id']}/decide",
        {"decision": "approve"},
        OWNER_USER,
    )
    assert r.status_code == 404
    # a viewer in the team reads, and may not write
    req(
        on,
        "POST",
        f"/v1/systems/{secret}/team",
        {"user_id": VIEWER, "team_role": "data_steward"},
        ADMIN,
    )
    assert req(on, "GET", f"/v1/systems/{secret}/approvals", user=VIEWER).status_code == 200
    assert req(on, "GET", f"/v1/systems/{secret}/reviews", user=VIEWER).status_code == 200


def test_each_write_makes_two_audit_rows(on: Console) -> None:
    def rows() -> list[dict[str, Any]]:
        return on.ctx.tables.query("console_action", order_by=("ts",))

    sid = make(on)
    base = f"/v1/systems/{sid}"
    before = len(rows())
    ap = req(on, "POST", f"{base}/approvals", {"to_stage": "deployment"}, OWNER_USER).json()
    new = rows()[before:]
    assert [r["outcome"] for r in new] == ["attempted", "ok"]
    assert {r["permission"] for r in new} == {"systems.edit"}
    assert {r["target_kind"] for r in new} == {"system"} and new[1]["target_id"] == sid
    before = len(rows())
    req(
        on,
        "POST",
        f"{base}/approvals/{ap['approval_id']}/decide",
        {"decision": "approve"},
        APPROVER,
    )
    new = rows()[before:]
    assert [r["outcome"] for r in new] == ["attempted", "ok"]
    assert {r["permission"] for r in new} == {"systems.approve"}
    before = len(rows())
    req(
        on,
        "POST",
        f"{base}/reviews",
        {"kind": "internal", "title": "T", "reviewer_user": REVIEWER},
        REVIEWER,
    )
    new = rows()[before:]
    assert [r["outcome"] for r in new] == ["attempted", "ok"]
    assert {r["permission"] for r in new} == {"systems.review"}
    # a refused call is audited as an error, not as ok
    before = len(rows())
    req(on, "POST", f"{base}/stage", {"to_stage": "operation"}, OWNER_USER)
    new = rows()[before:]
    assert [r["outcome"] for r in new][0] == "attempted" and new[-1]["outcome"] != "ok"


def test_permissions_are_held_as_planned() -> None:
    assert set(rbac.roles_for("systems.approve")) == {"approver", "reviewer", "owner", "admin"}
    assert set(rbac.roles_for("systems.review")) == {"reviewer", "approver", "admin"}


@pytest.mark.parametrize("role", [r for r in rbac.ROLES if not rbac.allowed([r], "systems.review")])
def test_roles_without_review_permission_get_403(on: Console, role: str) -> None:
    sid = make(on)
    on.ctx.settings.api_rbac_enabled = True
    from supervisor.adapters.auth.base import AuthPrincipal

    uid = f"only.{role}"
    on.ctx.provider.users[uid] = AuthPrincipal(uid, "user", "dev_header", frozenset({role}), uid)
    r = req(on, "POST", f"/v1/systems/{sid}/reviews", {"kind": "internal"}, uid)
    assert r.status_code == 403
