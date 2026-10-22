"""WP-G6 role matrix with the routes mounted (the base matrix test skips flag-mounted routes):
every new route is in ROUTES with the right permission, and each role gets what it should."""

from __future__ import annotations

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.core import rbac
from tests.console.test_rbac_matrix import _needs_of, app_routes

from .conftest import Rig

MINE = ("/mcp", "/v1/mcp/apps", "/v1/kpis")


def test_every_new_route_is_in_the_matrix_with_its_dependency(rig: Rig) -> None:
    found = [(m, p, r) for m, p, r in app_routes() if p.startswith(MINE)]
    assert {(m, p) for m, p, _ in found} == {
        ("POST", "/mcp"),
        ("GET", "/v1/mcp/apps"),
        ("POST", "/v1/mcp/apps/{app_id}/approve"),
        ("POST", "/v1/mcp/apps/{app_id}/block"),
        ("GET", "/v1/kpis"),
    }
    for method, path, route in found:
        entry = rbac.route_entry(method, path)
        assert entry is not None, (method, path)
        if entry in rbac.MARKERS:
            assert path == "/mcp" and entry == rbac.AGENT
        else:
            assert _needs_of(route) == [entry], (method, path)


def test_the_permission_is_admin_only_and_kpis_is_for_everyone() -> None:
    assert rbac.roles_for("mcp.apps") == ("admin",)
    assert rbac.roles_for("console.view") == rbac.ROLES


@pytest.mark.parametrize("role", rbac.ROLES)
def test_each_role_gets_what_it_should(rig: Rig, role: str) -> None:
    uid = f"only.{role}"
    rig.ctx.provider.users[uid] = AuthPrincipal(uid, "user", "dev_header", frozenset({role}), uid)
    cred = rig.new_app(approved=False)
    c = rig.console.client
    h = {"X-Dev-User": uid}
    listing = c.get("/v1/mcp/apps", headers=h)
    approve = c.post(f"/v1/mcp/apps/{cred.app_id}/approve", headers=h)
    kpis = c.get("/v1/kpis", headers=h)
    assert kpis.status_code == 200
    if role == "admin":
        assert listing.status_code == 200 and approve.status_code == 200
    else:
        assert listing.status_code == 403 and approve.status_code == 403
        assert rig.apps.get(cred.app_id)["status"] == "pending"
        assert "needs role admin" in approve.json()["error"]


def test_a_service_principal_cannot_decide_about_an_app(rig: Rig) -> None:
    """The routes need a signed-in person: the app's own credential does not open them."""
    cred = rig.new_app(approved=False)
    body = b"{}"
    r = rig.console.client.post(
        f"/v1/mcp/apps/{cred.app_id}/approve",
        content=body,
        headers=cred.sign(body, f"/v1/mcp/apps/{cred.app_id}/approve"),
    )
    assert r.status_code in (400, 401, 403)
    assert rig.apps.get(cred.app_id)["status"] == "pending"
