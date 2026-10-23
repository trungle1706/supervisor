# ruff: noqa: F811
"""WP-P2: session_id and consumer_id from the SDK, and the 'masked but not applied' signal."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest

from supervisor.gateway import sdk
from supervisor.gateway.sdk import HttpGate, InProcessGate, supervised_tool
from tests.gateway.test_inline_redaction import ARGS, _reset_sdk, gw_on, masker  # noqa: F401


class Spy:
    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answer = answer or {"allow": True, "action": "allow"}

    def check(self, agent_id: str, version: str, tool: str, args: Any, context: Any = None) -> Any:
        self.calls.append({"args": dict(args), "context": dict(context or {})})
        return self.answer


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    sdk._warned_not_applied.clear()
    sdk.set_session(None)
    yield
    sdk.set_session(None)


def test_context_variable_and_decorator_arguments() -> None:
    spy = Spy()

    @supervised_tool("a", "1", "t", "read_only", gate=spy)
    def t(q: str) -> str:
        return q

    t("x")
    assert "session_id" not in spy.calls[-1]["context"]  # nothing set: nothing sent
    with sdk.supervised_session("s-1", "web"):
        t("x")
    assert spy.calls[-1]["context"]["session_id"] == "s-1"
    assert spy.calls[-1]["context"]["consumer_id"] == "web"
    sdk.set_session("s-2")
    t("x")
    assert spy.calls[-1]["context"]["session_id"] == "s-2"

    @supervised_tool(
        "a",
        "1",
        "u",
        "read_only",
        gate=spy,
        session_id=lambda a: "sess-" + a["q"],
        consumer_id="app",
    )
    def u(q: str) -> str:
        return q

    u("z")
    assert spy.calls[-1]["context"]["session_id"] == "sess-z"
    assert spy.calls[-1]["context"]["consumer_id"] == "app"


def test_http_gate_sends_the_ids_in_the_context() -> None:
    sent: list[dict[str, Any]] = []

    def transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        sent.append(payload)
        return {"allow": True}

    g = HttpGate("http://x", transport=transport)
    g.check_v2("a", "1", "t", {}, {"k": 1}, session_id="s", consumer_id="c")
    assert sent[-1]["context"] == {"k": 1, "session_id": "s", "consumer_id": "c"}
    g.check_v2("a", "1", "t", {})
    assert sent[-1]["context"] is None


def test_not_applied_is_warned_once_and_told_to_the_gate(caplog: pytest.LogCaptureFixture) -> None:
    spy = Spy({"allow": True, "transformed_args": {"q": "<M>"}})

    @supervised_tool("agent_w", "1", "t", "pii_export", gate=spy)
    def t(q: str) -> str:
        return q

    with caplog.at_level(logging.WARNING, logger="supervisor.gateway.sdk"):
        assert t("raw") == "raw"  # inline redaction is off here: the original arguments go on
        t("raw")
    # the first request is the one of before WP-P2; once masked arguments came back unapplied,
    # the next requests of that agent tell the gate
    assert spy.calls[0]["context"] == {"declared_risk_class": "pii_export"}
    assert spy.calls[1]["context"]["redaction_applied"] is False
    warns = [r for r in caplog.records if "agent_w" in r.getMessage()]
    assert len(warns) == 1


def test_applied_sends_no_flag_and_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    sdk.set_inline_redaction(True)
    spy = Spy({"allow": True, "transformed_args": {"q": "<M>"}})

    @supervised_tool("agent_a", "1", "t", "pii_export", gate=spy)
    def t(q: str) -> str:
        return q

    with caplog.at_level(logging.WARNING, logger="supervisor.gateway.sdk"):
        assert t("raw") == "<M>"
    assert "redaction_applied" not in spy.calls[0]["context"]
    assert not [r for r in caplog.records if "agent_a" in r.getMessage()]


def test_gate_records_redaction_applied_false(gw_on: Any, evidence: Any) -> None:
    r = gw_on.check("payments", "1", "add_payee", ARGS, {"redaction_applied": False})
    assert r["transformed_args"] and r["redaction_applied"] is False
    assert evidence.of_type("gate_decision")[-1]["redaction_applied"] is False
    ok = gw_on.check("payments", "1", "add_payee", ARGS)
    assert "redaction_applied" not in ok
    assert "redaction_applied" not in evidence.of_type("gate_decision")[-1]
    # in-process gate passes the ids too
    ip = InProcessGate(gw_on)
    assert ip.check_v2("payments", "1", "get_balance", {"account_id": "A"}, session_id="s")["allow"]
