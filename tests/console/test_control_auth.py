"""B1 + M5: gate control routes act only on an authenticated Principal.

``/gate/{pause,resume,quarantine,release}`` and the ``/v1`` aliases: no raw
``X-Forwarded-User``, no body ``principal``, no ``default_user``/cookie fallback, the role
matrix always enforced (``API_RBAC_ENABLED`` only gates the agent-facing routes).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.console.conftest import Console
from tests.console.test_databricks_mode import dbx  # noqa: F401 - fixture

BODY = {"agent_id": "payments", "reason": "t"}
VERBS = ("pause", "resume", "quarantine", "release")


def _post(c: Console, verb: str, user: str | None, body: dict[str, Any] | None = None, **h: str):
    headers = dict(h)
    if user:
        headers["X-Dev-User"] = user
    return c.client.post(f"/gate/{verb}", json=body or BODY, headers=headers)


def _state(c: Console) -> str:
    return c.runtime.gateway.states.get_state("payments")


def test_spoofed_forwarded_user_is_403_and_state_unchanged(console: Console) -> None:
    for verb in VERBS:
        r = _post(console, verb, None, **{"X-Forwarded-User": "admin.chi"})
        assert r.status_code == 403 and "error" in r.json(), verb
    assert _state(console) == "RUNNING"


def test_no_identity_does_not_fall_back_to_default_user(console: Console) -> None:
    assert console.ctx.provider.default_user  # the users file has one
    assert _post(console, "pause", None).status_code == 403
    console.client.cookies.set("sv_dev_user", "admin.chi")
    assert _post(console, "quarantine", None).status_code == 403
    console.client.cookies.clear()
    assert _state(console) == "RUNNING"


def test_body_principal_is_ignored(console: Console) -> None:
    body = {**BODY, "principal": "admin.chi"}
    assert _post(console, "quarantine", None, body).status_code == 403
    assert _post(console, "quarantine", "viewer.hoa", body).status_code == 403
    assert _state(console) == "RUNNING"
    # a valid header wins; the body name is not the actor
    r = _post(console, "pause", "reviewer.an", {**BODY, "principal": "admin.chi"})
    assert r.status_code == 200
    row = [x for x in console.ctx.tables.query("console_action") if x["outcome"] == "ok"][-1]
    assert row["actor"] == "reviewer.an"


@pytest.mark.parametrize("user", ["viewer.hoa", "operator.khanh", "nobody"])
def test_unprivileged_callers_get_403_on_every_control_route(console: Console, user: str) -> None:
    for verb in VERBS:
        assert _post(console, verb, user).status_code == 403, verb
    r = console.client.post("/v1/gate/quarantine", json=BODY, headers={"X-Dev-User": user})
    assert r.status_code == 403
    r = console.client.post(
        "/gate/release",
        json=BODY,
        headers={"X-Dev-User": "viewer.hoa", "X-Forwarded-User": "admin.chi"},
    )
    assert r.status_code == 403
    assert _state(console) == "RUNNING"


def test_identity_failure_audit_row(console: Console) -> None:
    _post(console, "pause", "nobody")
    (row,) = console.ctx.tables.query("console_action")
    assert row["outcome"] == "denied" and row["detail"] == "identity_unknown"
    assert row["actor"] == "nobody" and row["actor_kind"] == "unverified"


def test_admin_quarantine_release_and_reviewer_pause(console: Console) -> None:
    assert _post(console, "pause", "reviewer.an").status_code == 200
    r = _post(console, "quarantine", "admin.chi")
    assert r.status_code == 200 and r.json()["state"] == "QUARANTINED"
    r = console.client.post("/v1/gate/release", json=BODY, headers={"X-Dev-User": "admin.chi"})
    assert r.status_code == 200 and r.json()["state"] == "PAUSED"
    assert _post(console, "quarantine", "reviewer.an").status_code == 403  # reviewer: no


def test_two_person_resume_with_authenticated_users(console: Console) -> None:
    assert _post(console, "pause", "reviewer.an").status_code == 200
    owner = "payops-lead@example.invalid"
    r = _post(console, "resume", owner)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert _post(console, "resume", owner).status_code == 400  # same person twice
    r = _post(console, "resume", "reviewer.an")
    assert r.status_code == 200 and r.json()["status"] == "resumed"
    assert _state(console) == "RUNNING"


def test_state_change_evidence_carries_actor_kind_and_auth_method(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, dict[str, Any]]] = []
    sink = console.runtime.gateway.states.evidence
    real = sink.record

    def spy(record_type: str, ref: str, payload: Any) -> Any:
        seen.append((record_type, dict(payload)))
        return real(record_type, ref, payload)

    monkeypatch.setattr(sink, "record", spy)
    assert _post(console, "pause", "reviewer.an").status_code == 200
    (p,) = [p for t, p in seen if t == "gate_state_change"]
    assert p["principal"] == "reviewer.an"
    assert p["actor_kind"] == "user" and p["auth_method"] == "dev_header"
    # the console route passes them too
    seen.clear()
    assert console.post("/console/agents/payments/quarantine", {"reason": "t"}, user="admin.chi")
    (q,) = [p for t, p in seen if t == "gate_state_change"]
    assert q["actor_kind"] == "user" and q["auth_method"] == "dev_header"


def test_old_callers_without_actor_args_keep_the_old_payload(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []
    sink = console.runtime.gateway.states.evidence
    real = sink.record

    def spy(record_type: str, ref: str, payload: Any) -> Any:
        seen.append(dict(payload))
        return real(record_type, ref, payload)

    monkeypatch.setattr(sink, "record", spy)
    console.runtime.gateway.states.pause("payments", "reviewer.an", "t")
    assert "actor_kind" not in seen[0] and "auth_method" not in seen[0]


def test_check_works_without_identity_while_rbac_flag_is_off(console: Console) -> None:
    assert console.ctx.settings.api_rbac_enabled is False
    r = console.client.post(
        "/gate/check",
        json={
            "agent_id": "payments",
            "agent_version": "1",
            "tool_name": "get_balance",
            "args": {},
        },
    )
    assert r.status_code == 200


# ------------------------------------------------------------ databricks_app mode


def test_databricks_sso_admin_can_control_and_no_sso_is_403(
    dbx: tuple[TestClient, Any],  # noqa: F811
) -> None:
    client, ctx = dbx
    ctx.provider.role_users["admin"].add("boss@bank.example")
    body = {"agent_id": "credit_prequal", "reason": "t"}
    r = client.post("/gate/pause", json=body)
    assert r.status_code == 403 and "error" in r.json()
    r = client.post("/gate/pause", json=body, headers={"X-Dev-User": "admin.chi"})
    assert r.status_code == 403
    r = client.post(
        "/gate/quarantine", json=body, headers={"X-Forwarded-Email": "boss@bank.example"}
    )
    assert r.status_code == 200 and r.json()["state"] == "QUARANTINED"
    r = client.post(
        "/v1/gate/pause", json=body, headers={"X-Forwarded-Email": "nobody-role@bank.example"}
    )
    assert r.status_code == 403
