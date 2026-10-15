"""WP19 (ADR D03 amendment): RETIRED is one-way, from PAUSED or SHADOW, admin only."""

from __future__ import annotations

import pytest

from supervisor.gateway.engine import Gateway
from supervisor.gateway.state import TransitionError
from tests.gateway.conftest import MemoryEvidence
from tests.gateway.helpers import call

MONEY = dict(from_account_id="ACC-1", payee_id="P1", amount_minor=1000)
ADMIN = "admin.chi"


def test_paused_to_retired_blocks_every_call(gateway: Gateway, evidence: MemoryEvidence) -> None:
    gateway.states.pause("payments", "reviewer.an", "x")
    res = gateway.states.retire("payments", ADMIN, "end of life")
    assert res["changed"] is True and res["state"] == "RETIRED" and res["from"] == "PAUSED"
    row = gateway.states.state.get("agent", {"agent_id": "payments"})
    assert row["gate_state"] == "RETIRED" and row["status"] == "retired"
    for tool, args in (("transfer", MONEY), ("get_balance", {"account_id": "ACC-1"})):
        r = call(gateway, "payments", tool, **args)
        assert r["allow"] is False and r["reason"] == "agent retired"
    last = evidence.of_type("gate_state_change")[-1]
    assert (last["event"], last["from_state"], last["to_state"]) == ("retire", "PAUSED", "RETIRED")


def test_shadow_to_retired(gateway: Gateway) -> None:
    gateway.states.set_mode("payments", "SHADOW", "reviewer.an")
    assert gateway.states.retire("payments", ADMIN, "gone")["from"] == "SHADOW"


def test_running_and_quarantined_must_move_first(gateway: Gateway) -> None:
    with pytest.raises(TransitionError, match="pause it first"):
        gateway.states.retire("payments", ADMIN, "x")
    gateway.states.quarantine("payments", ADMIN, "bad")
    with pytest.raises(TransitionError, match="release it first"):
        gateway.states.retire("payments", ADMIN, "x")
    gateway.states.release_quarantine("payments", ADMIN, "ok")
    assert gateway.states.retire("payments", ADMIN, "x")["state"] == "RETIRED"


def test_only_admin_and_reason_required(gateway: Gateway) -> None:
    gateway.states.pause("payments", "reviewer.an")
    with pytest.raises(TransitionError, match="not an admin"):
        gateway.states.retire("payments", "reviewer.an", "x")
    with pytest.raises(TransitionError, match="reason"):
        gateway.states.retire("payments", ADMIN, " ")
    with pytest.raises(TransitionError, match="unknown agent"):
        gateway.states.retire("nobody", ADMIN, "x")


def test_nothing_leaves_retired(gateway: Gateway) -> None:
    gateway.states.pause("payments", "reviewer.an")
    gateway.states.retire("payments", ADMIN, "x")
    st = gateway.states
    with pytest.raises(TransitionError, match="RETIRED"):
        st.resume("payments", "reviewer.an")
    with pytest.raises(TransitionError):
        st.set_mode("payments", "RUNNING", "reviewer.an")
    with pytest.raises(TransitionError):
        st.quarantine("payments", ADMIN)
    with pytest.raises(TransitionError):
        st.pause("payments", "reviewer.an")
    with pytest.raises(TransitionError):
        st.release_quarantine("payments", ADMIN, "x")
    assert st.retire("payments", ADMIN, "again")["changed"] is False  # idempotent no-op
    assert st.get_state("payments") == "RETIRED"


def test_retire_payload_carries_actor_when_given(
    gateway: Gateway, evidence: MemoryEvidence
) -> None:
    gateway.states.pause("payments", "reviewer.an", "stop")
    gateway.states.retire(
        "payments", ADMIN, "bye", auth_method="onboard_retire", actor_kind="system"
    )
    last = evidence.of_type("gate_state_change")[-1]
    assert (last["auth_method"], last["actor_kind"]) == ("onboard_retire", "system")
