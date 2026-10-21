"""WP20 contract: every agent-ingress route enforces the ingress guard.

Like the RBAC coverage test: walk the real app's routes. A route that the role matrix marks
``AGENT`` (machine ingress) must carry a dependency flagged ``_supervisor_ingress_guard``. The
set of ingress routes is pinned, so a new ingress route cannot be added without a decision.
A grep of the sources makes sure no module declares an ingress route outside the walk.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from supervisor.core import rbac
from supervisor.gateway.ingress_auth import INGRESS_ATTR
from tests.conftest import REPO_ROOT
from tests.console.test_rbac_matrix import app_routes

PINNED = {
    ("POST", "/gate/check"),
    ("POST", "/v1/gate/check"),
    ("POST", "/v1/traces"),
    ("POST", "/v1/mcp/tools/observe"),  # WP26: HTTP MCP proxy reports a tools/list
    ("POST", "/v1/mcp/tools/blocked"),  # WP26: HTTP MCP proxy reports a refused call
}
MCP_RATE_LIMITED = {"/v1/mcp/tools/observe", "/v1/mcp/tools/blocked"}  # signed, but not exempt


def _deps(dependant: Any) -> Iterator[Any]:
    for d in getattr(dependant, "dependencies", ()):
        yield d
        yield from _deps(d)


def _guarded(route: Any) -> bool:
    return any(
        d.call is not None and getattr(d.call, INGRESS_ATTR, False)
        for d in _deps(getattr(route, "dependant", None))
    )


def test_every_agent_route_has_the_ingress_guard() -> None:
    agent = [(m, p, r) for m, p, r in app_routes() if rbac.route_entry(m, p) == rbac.AGENT]
    assert agent, "no AGENT routes found: the walk is broken"
    missing = [f"{m} {p}" for m, p, r in agent if not _guarded(r)]
    assert not missing, f"ingress routes without the ingress guard dependency: {missing}"


def test_ingress_route_set_is_pinned() -> None:
    found = {(m, p) for m, p, _ in app_routes() if rbac.route_entry(m, p) == rbac.AGENT}
    assert found == PINNED, "ingress routes changed: add the guard and update PINNED on purpose"


def test_no_other_route_claims_the_guard() -> None:
    """The guard marks machine ingress only; a console or human-control route must not use it."""
    wrong = [
        f"{m} {p}"
        for m, p, r in app_routes()
        if _guarded(r) and rbac.route_entry(m, p) != rbac.AGENT
    ]
    assert not wrong, wrong


def test_no_unlisted_post_route_in_the_agent_packages() -> None:
    """Grep: POST routes declared under gateway/ and recorder/ are the pinned ingress routes
    or human control routes (which have an RBAC permission), nothing else."""
    pat = re.compile(r'@\w+\.post\(\s*"([^"]+)"')
    human = {"/pause", "/resume", "/quarantine", "/release"}
    for pkg in ("gateway", "recorder"):
        for path in (REPO_ROOT / "src" / "supervisor" / pkg).rglob("*.py"):
            for route in pat.findall(path.read_text(encoding="utf-8")):
                assert route in human | {"/check", "/v1/traces"}, (path.name, route)


def test_rate_limit_exempt_set_matches_the_ingress_routes() -> None:
    from supervisor.ops.middleware import RATE_LIMIT_EXEMPT

    assert RATE_LIMIT_EXEMPT == {p for _, p in PINNED} - MCP_RATE_LIMITED
