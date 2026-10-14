"""DoD: make the policy store / state store unavailable mid-test.

Money tools must be denied (fail closed); read-only tools pass with an alert (fail open).
"""

from __future__ import annotations

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.gateway.engine import Gateway
from tests.gateway.helpers import call

MONEY = dict(from_account_id="ACC-1", payee_id="P1", amount_minor=1000)


def _down(*_a: object, **_k: object) -> None:
    raise RuntimeError("store unavailable")


def _assert_fail_modes(gateway: Gateway, adapters: Adapters) -> None:
    money = call(gateway, "payments", "transfer", **MONEY)
    assert money["allow"] is False and money["action"] == "block"
    assert money["fail_mode"] == "closed" and "fail closed" in money["reason"]
    credit = call(gateway, "credit_prequal", "decide_prequal", application_id="A1")
    assert credit["allow"] is False and credit["fail_mode"] == "closed"
    pii = call(gateway, "payments", "add_payee", customer_id="C1")
    assert pii["allow"] is False
    unknown_tool = call(gateway, "payments", "brand_new_tool")
    assert unknown_tool["allow"] is False
    read = call(gateway, "payments", "get_balance", account_id="ACC-1")
    assert read["allow"] is True and read["action"] == "alert" and read["fail_mode"] == "open"
    labels = [
        v["label"] for v in adapters.tables.query("verdict", {"checker_id": "gate:fail_mode"})
    ]
    assert labels.count("fail_open") == 1 and labels.count("fail_closed") == 4


def test_policy_store_unavailable_mid_test(
    gateway: Gateway, adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert call(gateway, "payments", "transfer", **MONEY)["allow"] is True
    monkeypatch.setattr(adapters.state, "query", _down)  # rule table reads fail
    _assert_fail_modes(gateway, adapters)


def test_state_store_unavailable_mid_test(
    gateway: Gateway, adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert call(gateway, "payments", "get_balance", account_id="ACC-1")["allow"] is True
    monkeypatch.setattr(adapters.state, "get", _down)  # agent state reads fail
    _assert_fail_modes(gateway, adapters)


def test_policy_source_raises(
    gateway: Gateway, adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    call(gateway, "payments", "get_balance", account_id="ACC-1")
    monkeypatch.setattr(gateway.policy, "current", _down)
    _assert_fail_modes(gateway, adapters)


def test_no_policy_ever_loaded_is_closed_for_everything(
    adapters: Adapters, evidence, monkeypatch: pytest.MonkeyPatch, baseline
) -> None:
    from supervisor.gateway.policy import StorePolicyProvider

    g = Gateway(
        StorePolicyProvider(adapters.state),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
    )
    r = call(g, "payments", "get_balance", account_id="ACC-1")  # rule table empty
    assert r["allow"] is False and r["fail_mode"] == "closed"
    g.close()


def test_recovers_when_store_returns(
    gateway: Gateway, adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapters.state, "query", _down)
    assert call(gateway, "payments", "transfer", **MONEY)["allow"] is False
    monkeypatch.undo()
    assert call(gateway, "payments", "transfer", **MONEY)["allow"] is True
