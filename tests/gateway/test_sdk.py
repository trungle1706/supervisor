"""Agent SDK: supervised_tool decorator, InProcessGate, HttpGate."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from supervisor.gateway import sdk, wiring
from supervisor.gateway.engine import Gateway
from supervisor.gateway.routes import router
from supervisor.gateway.sdk import (
    HttpGate,
    InProcessGate,
    SupervisorBlocked,
    SupervisorPaused,
    supervised_tool,
)


@pytest.fixture(autouse=True)
def _reset_default_gate() -> Iterator[None]:
    sdk.set_default_gate(None)
    yield
    sdk.set_default_gate(None)


def test_allowed_call_runs(gateway: Gateway) -> None:
    @supervised_tool("customer_service", "1", "get_ticket", "read_only", InProcessGate(gateway))
    def get_ticket(ticket_id: str) -> str:
        return f"ticket {ticket_id}"

    assert get_ticket("T1") == "ticket T1"


def test_blocked_call_does_not_run(gateway: Gateway) -> None:
    ran: list[int] = []

    @supervised_tool("customer_service", "1", "waive_fee", "money", InProcessGate(gateway))
    def waive_fee(customer_id: str, amount_minor: int) -> None:
        ran.append(amount_minor)

    with pytest.raises(SupervisorBlocked) as ei:
        waive_fee("C1", 900000)
    assert ei.value.decision["rule_id"] == "SVC-01"
    assert not isinstance(ei.value, SupervisorPaused)
    assert ran == []


def test_pause_rule_raises_paused(gateway: Gateway) -> None:
    ran: list[int] = []

    @supervised_tool("customer_service", "1", "ext_transfer_api", "money", InProcessGate(gateway))
    def ext(amount_minor: int) -> None:
        ran.append(1)

    with pytest.raises(SupervisorPaused):
        ext(5)
    assert ran == []

    gateway.states.pause("payments", "owner.payments", "test")

    @supervised_tool("payments", "1", "internal_transfer", "money", InProcessGate(gateway))
    def transfer(amount_minor: int) -> None:
        ran.append(2)

    with pytest.raises(SupervisorPaused):
        transfer(1)
    assert ran == []


def test_no_gate_fails_closed() -> None:
    ran: list[int] = []

    @supervised_tool("payments", "1", "get_account_balance", "read_only")
    def bal() -> None:
        ran.append(1)

    with pytest.raises(SupervisorBlocked):
        bal()
    assert ran == []


def test_default_gate_and_async(gateway: Gateway) -> None:
    sdk.set_default_gate(InProcessGate(gateway))

    @supervised_tool("customer_service", "1", "get_ticket", "read_only")
    async def get_ticket(ticket_id: str) -> str:
        return ticket_id

    @supervised_tool("customer_service", "1", "waive_fee", "money")
    async def waive(customer_id: str, amount_minor: int) -> str:
        return "done"

    async def main() -> None:
        assert await get_ticket("T9") == "T9"
        with pytest.raises(SupervisorBlocked):
            await waive("C1", 900000)

    asyncio.run(main())


def test_in_process_gate_never_raises() -> None:
    class Boom:
        def check(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise RuntimeError("x")

    d = InProcessGate(Boom()).check("a", "1", "t", {})
    assert d["allow"] is False and isinstance(d["latency_ms"], int)


def test_http_gate_via_test_client(gateway: Gateway) -> None:
    app = FastAPI()
    app.include_router(router)
    wiring.set_gateway(gateway)
    try:
        client = TestClient(app)

        def transport(url: str, payload: dict[str, Any], timeout_s: float) -> Mapping[str, Any]:
            assert url == "http://gw/gate/check"
            r = client.post("/gate/check", json=payload)
            r.raise_for_status()
            return r.json()  # type: ignore[no-any-return]

        gate = HttpGate("http://gw/", transport=transport)

        @supervised_tool("customer_service", "1", "get_ticket", "read_only", gate)
        def get_ticket(ticket_id: str) -> str:
            return ticket_id

        @supervised_tool("customer_service", "1", "waive_fee", "money", gate)
        def waive(customer_id: str, amount_minor: int) -> str:
            return "done"

        assert get_ticket("T1") == "T1"
        with pytest.raises(SupervisorBlocked):
            waive("C1", 900000)
    finally:
        wiring.set_gateway(None)


@pytest.mark.parametrize("mode", ["sleep", "raise"])
def test_http_gate_timeout_fail_modes(mode: str) -> None:
    def transport(url: str, payload: dict[str, Any], timeout_s: float) -> Mapping[str, Any]:
        if mode == "sleep":
            time.sleep(timeout_s * 4)
        raise TimeoutError("slow")

    gate = HttpGate(
        "http://gw", timeout_s=0.05, transport=transport, fail_modes={"get_ticket": "read_only"}
    )
    money = gate.check("payments", "1", "internal_transfer", {"amount_minor": 1})
    assert money["allow"] is False and money["action"] == "block"
    assert money["rule_id"] == "GATE-UNREACHABLE"
    assert isinstance(money["latency_ms"], int)
    read = gate.check("payments", "1", "get_ticket", {})
    assert read["allow"] is True and read["action"] == "alert"

    @supervised_tool("payments", "1", "internal_transfer", "money", gate)
    def transfer(amount_minor: int) -> None:
        raise AssertionError("must not run")

    with pytest.raises(SupervisorBlocked):
        transfer(1)
