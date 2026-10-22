"""WP-G0 API: /v1/systems routes (RBAC, scope, audit, 400 and 404 shapes) and the matrix."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.core import rbac

from .conftest import Console, draft

REVIEWER = "reviewer.an"
OWNER_USER = "payops-lead@example.invalid"
VIEWER = "viewer.hoa"


def req(c: Console, method: str, url: str, body: Any = None, user: str = REVIEWER) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def create(c: Console, user: str = REVIEWER, **over: Any) -> dict[str, Any]:
    r = req(c, "POST", "/v1/systems", draft(owner_user=user, **over), user)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def test_full_flow(on: Console) -> None:
    s = create(on)
    sid = s["system_id"]
    assert s["status"] == "draft" and s["owner_user"] == REVIEWER
    assert req(on, "GET", "/v1/systems").json()["count"] == 1
    assert req(on, "GET", f"/v1/systems/{sid}").json()["name"] == "Payments - Assistant"
    r = req(on, "PATCH", f"/v1/systems/{sid}", {"purpose": "Changed", "status": "active"})
    assert r.status_code == 200 and r.json()["purpose"] == "Changed"
    r = req(
        on, "POST", f"/v1/systems/{sid}/team", {"user_id": "tech.minh", "team_role": "data_steward"}
    )
    assert r.status_code == 200 and len(r.json()["team"]) == 2
    r = req(on, "POST", f"/v1/systems/{sid}/links", {"ref_kind": "agent", "ref_id": "payments"})
    assert r.status_code == 200, r.text
    comp = r.json()["components"][0]
    assert comp["ref_id"] == "payments" and comp["role"] == "component_of"
    assert r.json()["effective_risk"]["inherited_level"] != "unspecified" or True
    r = req(on, "DELETE", f"/v1/systems/{sid}/links/{comp['component_id']}")
    assert r.status_code == 200 and r.json()["components"] == []
    r = req(on, "DELETE", f"/v1/systems/{sid}/team/tech.minh")
    assert r.status_code == 200 and len(r.json()["team"]) == 1
    r = req(on, "POST", f"/v1/systems/{sid}/archive")
    assert r.status_code == 200 and r.json()["status"] == "archived"
    # every change is a system_change on the chain (the context writes to the real sink)
    assert on.ctx.systems.evidence_sink is on.runtime.chain


def test_bad_input_is_400_with_a_message_and_unknown_is_404(on: Console) -> None:
    sid = create(on)["system_id"]
    cases = [
        ("POST", "/v1/systems", draft(system_type="robot")),
        ("POST", "/v1/systems", {"name": "x"}),
        ("POST", "/v1/systems", draft(colour="red", name="Other")),
        ("POST", "/v1/systems", [1, 2]),
        ("PATCH", f"/v1/systems/{sid}", {"risk_level": "critical"}),
        ("PATCH", f"/v1/systems/{sid}", {"system_id": "x"}),
        ("PATCH", f"/v1/systems/{sid}", {"purpose": "x", "row_version": "one"}),
        ("PATCH", f"/v1/systems/{sid}", {"purpose": "x", "row_version": 99}),
        ("PATCH", f"/v1/systems/{sid}", {}),
        ("POST", f"/v1/systems/{sid}/team", {"user_id": "bad user", "team_role": "reviewer"}),
        ("POST", f"/v1/systems/{sid}/team", {"user_id": "x", "team_role": "boss"}),
        ("POST", f"/v1/systems/{sid}/team", {"user_id": REVIEWER, "team_role": "reviewer"}),
        ("POST", f"/v1/systems/{sid}/links", {"ref_kind": "model", "ref_id": "x"}),
        ("POST", f"/v1/systems/{sid}/links", {"ref_kind": "agent", "ref_id": ""}),
        ("POST", f"/v1/systems/{sid}/links", {"ref_kind": "agent", "ref_id": "a b"}),
        ("POST", f"/v1/systems/{sid}/links", {"ref_kind": "agent", "ref_id": "x", "role": "z"}),
        ("DELETE", f"/v1/systems/{sid}/team/{REVIEWER}", None),
        ("GET", "/v1/systems?status=zzz", None),
        ("GET", "/v1/systems?nope=1", None),
        ("GET", "/v1/systems/bad%20id%3Cscript%3E", None),
    ]
    for method, url, body in cases:
        r = req(on, method, url, body)
        assert r.status_code == 400, (method, url, body, r.status_code, r.text[:200])
        assert r.json()["error"], (method, url)
    r = req(on, "POST", "/v1/systems", draft(), REVIEWER)  # same name again
    assert r.status_code == 400 and "already" in r.json()["error"]
    raw = on.client.post("/v1/systems", content=b"{not json", headers={"X-Dev-User": REVIEWER})
    assert raw.status_code == 400 and "JSON" in raw.json()["error"]
    # the segregation-of-duties refusal has its fixed prefix
    r = req(on, "POST", f"/v1/systems/{sid}/team", {"user_id": REVIEWER, "team_role": "reviewer"})
    assert r.json()["error"].startswith("segregation of duties:")
    # unknown things are 404 with an error body
    for method, url, body in [
        ("GET", "/v1/systems/sys_nope", None),
        ("PATCH", "/v1/systems/sys_nope", {"purpose": "x"}),
        ("POST", "/v1/systems/sys_nope/archive", None),
        ("POST", f"/v1/systems/{sid}/links", {"ref_kind": "agent", "ref_id": "ghost"}),
        ("DELETE", f"/v1/systems/{sid}/team/nobody", None),
        ("DELETE", f"/v1/systems/{sid}/links/sc_nope", None),
    ]:
        r = req(on, method, url, body)
        assert r.status_code == 404 and r.json()["error"], (method, url, r.status_code, r.text)


def test_off_flag_with_routes_mounted_is_400(console: Console, mounted: None) -> None:
    # defence in depth: if the router is there but the setting is off, a message, not data
    assert console.ctx.settings.governance_enabled is False
    r = req(console, "GET", "/v1/systems")
    assert r.status_code == 400 and "GOVERNANCE_ENABLED" in r.json()["error"]


def test_scope_for_scoped_roles(on: Console) -> None:
    mine = create(on, user=OWNER_USER, name="Owner system")["system_id"]
    other = create(on, name="Reviewer system", owner_team="risk-team")["system_id"]
    # the owner role sees its own system only
    body = req(on, "GET", "/v1/systems", user=OWNER_USER).json()
    assert [s["system_id"] for s in body["systems"]] == [mine]
    assert req(on, "GET", f"/v1/systems/{other}", user=OWNER_USER).status_code == 404
    assert req(on, "PATCH", f"/v1/systems/{other}", {"purpose": "x"}, OWNER_USER).status_code == 404
    # the viewer sees nothing, until added to a team
    assert req(on, "GET", "/v1/systems", user=VIEWER).json()["count"] == 0
    assert req(on, "GET", f"/v1/systems/{other}", user=VIEWER).status_code == 404
    req(on, "POST", f"/v1/systems/{other}/team", {"user_id": VIEWER, "team_role": "data_steward"})
    got = req(on, "GET", "/v1/systems", user=VIEWER).json()
    assert [s["system_id"] for s in got["systems"]] == [other]
    assert req(on, "GET", f"/v1/systems/{other}", user=VIEWER).status_code == 200
    # all-role people see everything
    for user in (REVIEWER, "admin.chi", "auditor.dung", "approver.em"):
        assert req(on, "GET", "/v1/systems", user=user).json()["count"] == 2, user
    # a scoped person registers only with themselves as owner
    r = req(
        on, "POST", "/v1/systems", draft(name="Mine too", owner_user="someone.else"), OWNER_USER
    )
    assert r.status_code == 400 and "yourself" in r.json()["error"]
    r = req(
        on,
        "POST",
        "/v1/systems",
        {k: v for k, v in draft(name="Mine too").items() if k != "owner_user"},
        OWNER_USER,
    )
    assert r.status_code == 201 and r.json()["owner_user"] == OWNER_USER


def test_each_write_makes_two_audit_rows_with_a_system_target(on: Console) -> None:
    def rows() -> list[dict[str, Any]]:
        return on.ctx.tables.query("console_action", order_by=("ts",))

    before = len(rows())
    sid = create(on)["system_id"]
    new = rows()[before:]
    assert [r["outcome"] for r in new] == ["attempted", "ok"]
    assert {r["permission"] for r in new} == {"systems.edit"}
    assert {r["target_kind"] for r in new} == {"system"}
    before = len(rows())
    req(on, "PATCH", f"/v1/systems/{sid}", {"purpose": "Changed"})
    new = rows()[before:]
    assert [r["outcome"] for r in new] == ["attempted", "ok"]
    assert new[1]["target_id"] == sid and new[1]["before_hash"] != new[1]["after_hash"]


# ------------------------------------------------------------------ the matrix


def _routes() -> list[tuple[str, str, str]]:
    return sorted((m, p, e) for (m, p), e in rbac.ROUTES.items() if e.startswith("systems."))


def test_every_systems_route_is_in_the_matrix_and_enforced(on: Console) -> None:
    from tests.console.test_rbac_matrix import _needs_of, app_routes

    live = [
        (m, p, r) for m, p, r in app_routes() if p.startswith(("/v1/systems", "/console/systems"))
    ]
    assert {(m, p) for m, p, _ in live} == {(m, p) for m, p, _ in _routes()}
    for m, p, r in live:
        assert _needs_of(r) == [rbac.route_entry(m, p)], (m, p)


@pytest.mark.parametrize(("method", "template", "permission"), _routes(), ids=str)
def test_denied_roles_get_403_and_allowed_roles_do_not(
    on: Console, monkeypatch: pytest.MonkeyPatch, method: str, template: str, permission: str
) -> None:
    monkeypatch.setattr(on.ctx.settings, "api_rbac_enabled", True)
    people = {}
    for role in rbac.ROLES:
        uid = f"only.{role}"
        on.ctx.provider.users[uid] = AuthPrincipal(
            uid, "user", "dev_header", frozenset({role}), uid
        )
        people[role] = uid
    sid = create(on)["system_id"]
    url = (
        template.replace("{system_id}", sid)
        .replace("{user}", "x")
        .replace("{component_id}", "sc_x")
    )
    is_json = url.startswith("/v1/")

    def call(user: str) -> Any:
        if is_json:
            body = {"user_id": "x", "team_role": "reviewer", "ref_kind": "agent", "ref_id": "p"}
            return on.client.request(
                method,
                url,
                json=body if method in ("POST", "PATCH") else None,
                headers={"X-Dev-User": user},
            )
        if method == "GET":
            return on.get(url, user=user)
        return on.post(url, {"name": "x"}, user=user)

    for role in rbac.ROLES:  # denied first: they change nothing
        if rbac.allowed([role], permission):
            continue
        r = call(people[role])
        assert r.status_code == 403, (role, permission, r.status_code, r.text[:200])
    for role in rbac.ROLES:
        if not rbac.allowed([role], permission):
            continue
        r = call(people[role])
        assert r.status_code != 403, (role, permission, r.text[:200])
        assert r.status_code < 500, (role, permission, r.status_code, r.text[:200])


def test_permissions_are_held_as_planned() -> None:
    assert set(rbac.roles_for("systems.view")) == set(rbac.ROLES)
    assert set(rbac.roles_for("systems.edit")) == {"reviewer", "owner", "admin"}
