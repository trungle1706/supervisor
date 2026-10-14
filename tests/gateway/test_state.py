"""State machine: pause by one, resume by two, quarantine, concurrency, evidence."""

from __future__ import annotations

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters
from supervisor.core.errors import ConcurrencyError
from supervisor.gateway.engine import Gateway
from supervisor.gateway.state import TransitionError
from tests.gateway.conftest import MemoryEvidence
from tests.gateway.helpers import call

MONEY = dict(customer_id="C1", payee_id="P1", amount_minor=1000)


def test_pause_by_one_principal_denies_non_read_only(gateway: Gateway) -> None:
    res = gateway.states.pause("payments", "reviewer.an", "suspicious ticket")
    assert res["changed"] is True and res["state"] == "PAUSED"
    r = call(gateway, "payments", "internal_transfer", **MONEY)
    assert r["allow"] is False and r["reason"] == "agent paused"
    assert call(gateway, "payments", "get_customer", customer_id="C1")["allow"] is True
    # pausing again is a no-op
    assert gateway.states.pause("payments", "reviewer.binh")["changed"] is False


def test_resume_needs_owner_and_reviewer(gateway: Gateway, evidence: MemoryEvidence) -> None:
    gateway.states.pause("payments", "reviewer.an", "x")
    first = gateway.states.resume("payments", "reviewer.an", "checked")
    assert first["status"] == "pending" and first["needs"] == "owner"
    with pytest.raises(TransitionError, match="already approved"):
        gateway.states.resume("payments", "reviewer.an", "again")
    second_reviewer = gateway.states.resume("payments", "reviewer.binh", "me too")
    assert second_reviewer["status"] == "pending"  # two reviewers are not enough
    assert gateway.states.get_state("payments") == "PAUSED"
    done = gateway.states.resume("payments", "owner.payments", "ok")
    assert done["status"] == "resumed" and done["state"] == "RUNNING"
    assert call(gateway, "payments", "internal_transfer", **MONEY)["allow"] is True
    events = [p["event"] for p in evidence.of_type("gate_state_change")]
    assert events == ["pause", "resume"]
    resumed = evidence.of_type("gate_state_change")[-1]
    assert {resumed["approver_1"], resumed["approver_2"]} == {"reviewer.an", "owner.payments"}
    assert "ok" not in str(resumed)  # reasons enter the chain as hashes only


def test_resume_rejects_strangers_and_unpaused(gateway: Gateway) -> None:
    with pytest.raises(TransitionError, match="not paused"):
        gateway.states.resume("payments", "reviewer.an")
    gateway.states.pause("payments", "reviewer.an")
    with pytest.raises(TransitionError, match="may not approve"):
        gateway.states.resume("payments", "random.user")
    with pytest.raises(TransitionError, match="unknown agent"):
        gateway.states.pause("nobody", "reviewer.an")


def test_resume_approval_expires(gateway: Gateway, clock: FixedClock) -> None:
    gateway.states.pause("payments", "reviewer.an")
    gateway.states.resume("payments", "owner.payments")
    clock.advance(gateway.states.resume_window_s + 1)
    late = gateway.states.resume("payments", "reviewer.an")
    assert late["status"] == "pending"
    assert gateway.states.get_state("payments") == "PAUSED"


def test_resume_returns_to_shadow_when_paused_from_shadow(gateway: Gateway) -> None:
    gateway.states.set_mode("payments", "SHADOW", "admin.chi")
    gateway.states.pause("payments", "reviewer.an")
    gateway.states.resume("payments", "owner.payments")
    assert gateway.states.resume("payments", "reviewer.binh")["state"] == "SHADOW"


def test_quarantine_denies_everything_and_only_admin_releases(gateway: Gateway) -> None:
    gateway.states.quarantine("payments", "reviewer.an", "confirmed incident")
    r = call(gateway, "payments", "get_customer", customer_id="C1")
    assert r["allow"] is False and r["reason"] == "agent quarantined"
    with pytest.raises(TransitionError, match="QUARANTINED"):
        gateway.states.resume("payments", "owner.payments")
    with pytest.raises(TransitionError, match="not an admin"):
        gateway.states.release_quarantine("payments", "reviewer.an", "fixed")
    with pytest.raises(TransitionError, match="reason"):
        gateway.states.release_quarantine("payments", "admin.chi", "")
    res = gateway.states.release_quarantine("payments", "admin.chi", "root cause fixed")
    assert res["state"] == "PAUSED"
    # after release the normal two-person resume applies
    gateway.states.resume("payments", "owner.payments")
    assert gateway.states.resume("payments", "reviewer.binh")["state"] == "RUNNING"


def test_agent_row_mirrors_status(gateway: Gateway, adapters: Adapters) -> None:
    gateway.states.pause("payments", "reviewer.an")
    row = adapters.state.get("agent", {"agent_id": "payments"})
    assert row["gate_state"] == "PAUSED" and row["status"] == "paused"
    gateway.states.quarantine("payments", "reviewer.an")
    row = adapters.state.get("agent", {"agent_id": "payments"})
    assert row["gate_state"] == "QUARANTINED" and row["status"] == "paused"


def test_lost_race_is_retried_with_row_version(
    gateway: Gateway, adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway.states.describe("payments")
    gateway.states.set_mode("payments", "RUNNING", "admin.chi")  # creates the row
    real_update = adapters.state.update
    calls = {"n": 0}

    def flaky(table, key, changes, expected_version):  # type: ignore[no-untyped-def]
        if table == "agent" and calls["n"] == 0:
            calls["n"] += 1
            # another writer bumps the row first
            row = adapters.state.get("agent", key)
            real_update(table, key, {"name": "renamed"}, int(row["row_version"]))
            raise ConcurrencyError("lost race")
        return real_update(table, key, changes, expected_version)

    monkeypatch.setattr(adapters.state, "update", flaky)
    assert gateway.states.pause("payments", "reviewer.an")["changed"] is True
    row = adapters.state.get("agent", {"agent_id": "payments"})
    assert row["gate_state"] == "PAUSED" and row["name"] == "renamed"
    assert row["row_version"] >= 3


def test_race_that_never_settles_is_rejected(
    gateway: Gateway, adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway.states.set_mode("payments", "SHADOW", "admin.chi")

    def always(*_a, **_k):  # type: ignore[no-untyped-def]
        raise ConcurrencyError("lost race")

    monkeypatch.setattr(adapters.state, "update", always)
    with pytest.raises(TransitionError, match="concurrently"):
        gateway.states.pause("payments", "reviewer.an")
