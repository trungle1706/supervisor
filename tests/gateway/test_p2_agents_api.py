# ruff: noqa: F811
"""WP-P2: POST /v1/agents, GET /v1/agents/{id}, and the gate mode route (SHADOW <-> RUNNING)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from supervisor.core import rbac
from tests.console.conftest import Console, console, seeded  # noqa: F401  (fixtures)

REVIEWER = "reviewer.an"
REVIEWER2 = "reviewer.binh"  # reviewer and approver
APPROVER = "approver.em"
OWNER = "payops-lead@example.invalid"
ADMIN = "admin.chi"
VIEWER = "viewer.hoa"

BODY = {
    "agent_id": "kb_chatbot",
    "name": "Bank KB chatbot",
    "owner_team": "Knowledge Team",
    "owner_user": "kb-lead@example.invalid",
    "risk_tier": "low",
    "host_type": "app",
    "plug_point": "sdk",
    "model_family": "qwen",
}


@pytest.fixture
def mounted() -> Iterator[None]:
    from supervisor.app import app
    from supervisor.gateway.agents_routes import router
    from tests.governance.conftest import restore_app

    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(router)
    try:
        yield
    finally:
        restore_app(app, saved, lifespan)


@pytest.fixture
def on(console: Console, mounted: None, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "agents_api_enabled", True)
    return console


@pytest.fixture
def records(on: Console, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, Any]]]:
    out: list[tuple[str, str, dict[str, Any]]] = []
    chain = on.runtime.chain
    orig = chain.record

    def spy(rtype: str, ref: str, payload: Any, **kw: Any) -> str:
        out.append((rtype, ref, dict(payload)))
        return str(orig(rtype, ref, payload, **kw))

    monkeypatch.setattr(chain, "record", spy)
    return out


def call(c: Console, method: str, url: str, body: Any = None, user: str = REVIEWER) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def audit_rows(c: Console, permission: str) -> list[dict[str, Any]]:
    return [
        r
        for r in c.runtime.adapters.state.query("console_action", {})
        if r["permission"] == permission
    ]


# --------------------------------------------------------------------------- off path


def test_flag_default_is_off_and_matrix_has_the_routes() -> None:
    from supervisor.config import load_settings

    assert load_settings().agents_api_enabled is False
    assert rbac.route_entry("POST", "/v1/agents") == "agents.edit"
    assert rbac.roles_for("agents.edit") == ("reviewer", "owner", "admin")
    assert rbac.route_entry("POST", "/gate/agents/{agent_id}/state") == "agent.mode"


def test_agents_route_is_not_mounted_with_the_flag_off(console: Console) -> None:
    assert call(console, "POST", "/v1/agents", BODY).status_code == 404


# --------------------------------------------------------------------------- registration


def test_create_update_get(on: Console, records: list[Any]) -> None:
    r = call(on, "POST", "/v1/agents", BODY)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["gate_state"] == "SHADOW" and row["status"] == "shadow"
    assert row["owner_team"] == "Knowledge Team"
    got = call(on, "GET", "/v1/agents/kb_chatbot", user=VIEWER)
    assert got.status_code == 200 and got.json()["model_family"] == "qwen"
    # update: only descriptive fields change; the state stays
    r2 = call(on, "POST", "/v1/agents", {**BODY, "risk_tier": "medium", "name": "KB bot"})
    assert r2.status_code == 200 and r2.json()["risk_tier"] == "medium"
    assert r2.json()["gate_state"] == "SHADOW"
    # same body again: no change, no new chain record
    n = len([x for x in records if x[0] == "agent_change"])
    assert (
        call(
            on, "POST", "/v1/agents", {**BODY, "risk_tier": "medium", "name": "KB bot"}
        ).status_code
        == 200
    )
    assert len([x for x in records if x[0] == "agent_change"]) == n
    changes = [p for t, _, p in records if t == "agent_change"]
    assert [c["action"] for c in changes] == ["created", "updated"]
    assert changes[1]["changed_fields"] == ["name", "risk_tier"]
    flat = repr(changes)
    for secret in ("Bank KB chatbot", "Knowledge Team", "kb-lead", "KB bot"):
        assert secret not in flat  # ids and enums only
    assert on.runtime.gateway.states.get_state("kb_chatbot") == "SHADOW"
    # two audit rows per write (attempted + outcome), three writes
    assert len(audit_rows(on, "agents.edit")) == 6


def test_unknown_agent_is_404(on: Console) -> None:
    assert call(on, "GET", "/v1/agents/nobody").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "agent_id": "bad id!"},
        {**BODY, "agent_id": "inventory"},
        {**BODY, "risk_tier": "extreme"},
        {**BODY, "name": ""},
        {**BODY, "extra": "x"},
        {**BODY, "owner_team": 5},
        {**BODY, "host_type": "a b"},
        {k: v for k, v in BODY.items() if k != "owner_user"},
        [],
    ],
)
def test_bad_input_is_400(on: Console, body: Any) -> None:
    r = call(on, "POST", "/v1/agents", body)
    assert r.status_code == 400 and r.json()["error"]


def test_invalid_json_is_400(on: Console) -> None:
    r = on.client.post(
        "/v1/agents",
        content=b"{nope",
        headers={"X-Dev-User": REVIEWER, "Content-Type": "application/json"},
    )
    assert r.status_code == 400


@pytest.mark.parametrize(
    ("user", "status"),
    [(REVIEWER, 201), (OWNER, 201), (ADMIN, 201), (VIEWER, 403), (APPROVER, 403)],
)
def test_roles(on: Console, user: str, status: int) -> None:
    assert call(on, "POST", "/v1/agents", BODY, user=user).status_code == status


def test_retired_agent_cannot_change(on: Console) -> None:
    call(on, "POST", "/v1/agents", BODY)
    on.runtime.gateway.states.retire("kb_chatbot", ADMIN, "done")
    r = call(on, "POST", "/v1/agents", {**BODY, "name": "x"})
    assert r.status_code == 400 and "RETIRED" in r.json()["error"]


# --------------------------------------------------------------------------- gate mode


def mode(c: Console, to: str, user: str, reason: str = "go live", agent: str = "kb_chatbot") -> Any:
    return call(c, "POST", f"/gate/agents/{agent}/state", {"to": to, "reason": reason}, user=user)


def test_mode_off_without_the_flag(console: Console) -> None:
    r = mode(console, "RUNNING", REVIEWER, agent="payments")
    assert r.status_code == 400 and "AGENTS_API_ENABLED" in r.json()["error"]


def test_shadow_to_running_needs_two_persons(on: Console, records: list[Any]) -> None:
    call(on, "POST", "/v1/agents", BODY)
    r1 = mode(on, "RUNNING", OWNER)  # the requester (owner role)
    assert r1.status_code == 200 and r1.json()["status"] == "pending"
    assert on.runtime.gateway.states.get_state("kb_chatbot") == "SHADOW"
    same = mode(on, "RUNNING", OWNER)  # the same person again
    assert same.status_code == 400
    r2 = mode(on, "RUNNING", APPROVER)
    assert r2.status_code == 200, r2.text
    assert r2.json()["state"] == "RUNNING" and r2.json()["approvers"] == [OWNER, APPROVER]
    assert on.runtime.gateway.states.get_state("kb_chatbot") == "RUNNING"
    types = [t for t, _, _ in records]
    assert "gate_resume_requested" in types
    change = [p for t, _, p in records if t == "gate_state_change"][-1]
    assert change["from_state"] == "SHADOW" and change["to_state"] == "RUNNING"
    assert change["approver_1"] == OWNER and change["approver_2"] == APPROVER
    assert "go live" not in repr(records)  # reasons go to the chain as a hash
    assert len(audit_rows(on, "agent.mode")) >= 4


def test_second_person_must_be_reviewer_or_approver(on: Console) -> None:
    call(on, "POST", "/v1/agents", BODY)
    assert mode(on, "RUNNING", REVIEWER).json()["status"] == "pending"
    r = mode(on, "RUNNING", OWNER)  # owner may request but not approve
    assert r.status_code == 400 and "reviewer or approver" in r.json()["error"]
    assert on.runtime.gateway.states.get_state("kb_chatbot") == "SHADOW"
    assert mode(on, "RUNNING", REVIEWER2).json()["state"] == "RUNNING"


def test_running_to_shadow_is_one_person(on: Console) -> None:
    call(on, "POST", "/v1/agents", BODY)
    mode(on, "RUNNING", REVIEWER)
    mode(on, "RUNNING", REVIEWER2)
    assert mode(on, "SHADOW", APPROVER).status_code == 403  # approver lacks systems.edit
    r = mode(on, "SHADOW", REVIEWER)
    assert r.status_code == 200 and r.json()["state"] == "SHADOW"


def test_mode_bad_input_and_states(on: Console) -> None:
    call(on, "POST", "/v1/agents", BODY)
    assert mode(on, "PAUSED", REVIEWER).status_code == 400
    assert call(on, "POST", "/gate/agents/kb_chatbot/state", {"reason": "x"}).status_code == 400
    assert mode(on, "RUNNING", REVIEWER, agent="nobody").status_code == 400
    assert mode(on, "RUNNING", VIEWER).status_code == 403
    assert mode(on, "SHADOW", REVIEWER).json()["changed"] is False
    on.runtime.gateway.states.pause("kb_chatbot", REVIEWER, "x")
    assert mode(on, "RUNNING", REVIEWER).status_code == 400
