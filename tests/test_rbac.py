"""WP18: the role matrix (pure) and its docs table."""

from __future__ import annotations

import re

import pytest

from supervisor.adapters.auth.base import ROLES as AUTH_ROLES
from supervisor.cases import service
from supervisor.config import REPO_ROOT
from supervisor.core import rbac

# Phase-1 grants, copied from the code before WP18. A role allowed then stays allowed.
PHASE1 = {
    "case.assign": ("reviewer", "admin"),
    "case.itsm": ("reviewer", "admin"),
    "case.transition": ("reviewer", "admin"),
    "intake.run": ("reviewer", "admin"),
    "case.comment": ("reviewer", "approver", "owner", "admin"),
    "case.signoff": ("reviewer", "approver", "admin"),
    "agent.pause": ("reviewer", "approver", "owner", "admin"),
    "agent.resume": ("reviewer", "owner", "admin"),
    "agent.quarantine": ("admin",),
    "agent.release": ("admin",),
    "evidence.export": ("auditor", "reviewer", "approver", "admin"),
    "evidence.download": ("auditor", "reviewer", "approver", "admin"),
    "onboard.start": ("reviewer", "owner", "admin"),
    "console.view": ("reviewer", "approver", "owner", "auditor", "admin"),
    "case.verify": ("reviewer", "approver", "owner", "auditor", "admin"),
    "chain.verify": ("reviewer", "approver", "owner", "auditor", "admin"),
    "inbox.read": ("reviewer", "approver", "owner", "auditor", "admin"),
    "health.view": ("reviewer", "approver", "owner", "auditor", "admin"),
    "metrics.view": ("reviewer", "approver", "owner", "auditor", "admin"),
    "onboard.view": ("reviewer", "approver", "owner", "auditor", "admin"),
}


def test_roles_are_the_matrix_roles() -> None:
    assert AUTH_ROLES is rbac.ROLES
    assert set(rbac.ROLES) == {
        "viewer",
        "reviewer",
        "approver",
        "owner",
        "admin",
        "auditor",
        "operator",
    }


@pytest.mark.parametrize(("permission", "roles"), sorted(PHASE1.items()))
def test_phase1_grants_are_kept(permission: str, roles: tuple[str, ...]) -> None:
    for role in roles:
        assert rbac.allowed([role], permission), (role, permission)


def test_new_roles() -> None:
    viewer = {p for p in rbac.PERMISSIONS if rbac.allowed(["viewer"], p)}
    assert viewer == {
        "console.view",
        "health.view",
        "metrics.view",
        "onboard.view",
        "compliance.view",
        "inventory.view",  # WP24
        "gate.read",
        "tools.view",  # WP22
        "mcp.tools.view",  # WP26
        # WP-UX3: read-only pages for everyone
        "decisions.view",
        "traces.view",
        "policies.view",
        "integrations.view",
        "risks.view",  # WP29: the register is readable by every role
        "controls.view",  # WP30: the catalogue and the task list are readable by every role
        "tasks.view",
        "transparency.view",  # WP31: the report is readable by every role
        "systems.view",  # WP-G0: every role reads (a scoped role sees its own systems)
        "incidents.view",  # WP-G5: every role reads; the list is scoped like systems
    }
    operator = {p for p in rbac.PERMISSIONS if rbac.allowed(["operator"], p)}
    assert operator == viewer | {
        "intake.run",
        "chain.verify",
        "alert.ack",
        "playground.run",
        "mcp.tools.propose",  # WP26
        "collectors.add",  # WP38: admin and operator may add a collector
        "session.view",  # WP27
    }
    auditor = {p for p in rbac.PERMISSIONS if rbac.allowed(["auditor"], p)}
    assert {"evidence.export", "evidence.download", "chain.verify", "console.view"} <= auditor
    assert not auditor & {"case.assign", "case.signoff", "agent.pause", "intake.run"}


def test_unknown_permission_and_empty_roles_are_denied() -> None:
    assert not rbac.allowed(["admin"], "nope.nothing")
    assert not rbac.allowed([], "console.view")


def test_service_tuples_come_from_the_matrix() -> None:
    assert service.WORKFLOW_ROLES == ("reviewer", "admin")
    assert service.COMMENT_ROLES == ("reviewer", "approver", "owner", "admin")
    assert service.SIGN_ROLES == ("reviewer", "approver", "admin")


def test_every_route_permission_exists() -> None:
    for (method, path), entry in rbac.ROUTES.items():
        assert method in ("GET", "POST", "PATCH", "DELETE"), (method, path)  # PATCH, DELETE: WP-G0
        if entry in rbac.MARKERS:
            continue
        if "{" in entry:  # agent.{action}
            for action in ("pause", "resume", "quarantine", "release"):
                assert rbac.resolve_permission(entry, {"action": action}) in rbac.PERMISSIONS
        else:
            assert entry in rbac.PERMISSIONS, (method, path, entry)


def test_v1_gate_alias_is_looked_up_like_gate() -> None:
    assert rbac.route_entry("POST", "/v1/gate/pause") == "agent.pause"
    assert rbac.route_entry("GET", "/v1/gate/agents/{agent_id}/state") == "gate.read"
    assert rbac.route_entry("POST", "/v1/traces") == rbac.AGENT


def test_docs_table_equals_matrix_markdown() -> None:
    text = (REPO_ROOT / "docs" / "console.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- ROLE-MATRIX:BEGIN -->\n(.*?)<!-- ROLE-MATRIX:END -->", text, flags=re.S)
    assert m, "docs/console.md has no ROLE-MATRIX block"
    assert m.group(1) == rbac.matrix_markdown()
