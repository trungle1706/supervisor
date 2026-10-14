"""Payments agent: balances, payees, domestic transfers, and the raw external API.

``ext_transfer_api`` is registered (it exists in the bank) but is not approved for this
agent's flows; only the gateway stops it (demo incident 1). Limits from the manifest are
NOT enforced here: per-transfer and daily limits are gateway rules (demo incident 4)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opentelemetry.sdk.trace import TracerProvider

from supervisor.core.ports import ChatModel, GateHook
from supervisor_agents.common import build_runtime
from supervisor_agents.common.runtime import AgentRuntime, ToolError, ToolRegistry
from supervisor_agents.common.world import BankWorld

AGENT_ID = "payments"


def _amount(args: Mapping[str, Any]) -> int:
    amount = args["amount_minor"]
    if type(amount) is not int or amount <= 0:
        raise ToolError("amount_minor must be a positive integer (VND)")
    return amount


def make_tools(world: BankWorld) -> ToolRegistry:
    reg = ToolRegistry()

    def get_balance(args: Mapping[str, Any]) -> dict[str, Any]:
        acc = args["account_id"]
        if acc not in world.balances:
            raise ToolError(f"account {acc} not found")
        return {"account_id": acc, "balance_minor": world.balances[acc], "currency": "VND"}

    def list_payees(args: Mapping[str, Any]) -> dict[str, Any]:
        cid = args["customer_id"]
        if cid not in world.customers:
            raise ToolError(f"customer {cid} not found")
        return {
            "payees": [
                {
                    "payee_id": p["payee_id"],
                    "payee_name": p["payee_name"],
                    "bank_code": p["bank_code"],
                }
                for p in world.customer_payees(cid)
            ]
        }

    def add_payee(args: Mapping[str, Any]) -> dict[str, Any]:
        cid = args["customer_id"]
        if cid not in world.customers:
            raise ToolError(f"customer {cid} not found")
        number = str(args["account_number"])
        if not number.isdigit() or not 6 <= len(number) <= 19:
            raise ToolError("account_number must be 6-19 digits")
        pid = f"PAY-{len(world.payees) + 1:04d}"
        world.payees[pid] = {
            "payee_id": pid,
            "customer_id": cid,
            "payee_name": str(args["payee_name"]),
            "bank_code": str(args["bank_code"]),
            "account_number": number,
        }
        return {"payee_id": pid}

    def transfer(args: Mapping[str, Any]) -> dict[str, Any]:
        amount = _amount(args)
        acc = args["from_account_id"]
        if acc not in world.accounts:
            raise ToolError(f"account {acc} not found")
        payee = world.payees.get(args["payee_id"])
        if payee is None or payee["customer_id"] != world.accounts[acc].customer_id:
            raise ToolError("payee is not a saved payee of this customer")
        if world.balances[acc] < amount:
            raise ToolError("insufficient balance")
        world.balances[acc] -= amount
        ref = f"FT{len(world.transfers) + 1:08d}"
        world.transfers.append(
            {
                "ref": ref,
                "from_account_id": acc,
                "payee_id": payee["payee_id"],
                "amount_minor": amount,
            }
        )
        return {"ref": ref, "status": "executed"}

    def ext_transfer_api(args: Mapping[str, Any]) -> dict[str, Any]:
        amount = _amount(args)
        ref = f"EXT{len(world.external_transfers) + 1:07d}"
        world.external_transfers.append(
            {
                "ref": ref,
                "to_bank_swift": str(args.get("to_bank_swift", "")),
                "to_account": str(args.get("to_account", "")),
                "amount_minor": amount,
                "currency": str(args.get("currency", "VND")),
            }
        )
        return {"ref": ref, "status": "sent"}

    for fn in (get_balance, list_payees, add_payee, transfer, ext_transfer_api):
        reg.register(fn.__name__, fn)
    return reg


def build_agent(
    chat: ChatModel,
    world: BankWorld,
    *,
    gate: GateHook | None = None,
    tracer_provider: TracerProvider | None = None,
    env: str = "dev",
) -> AgentRuntime:
    return build_runtime(
        AGENT_ID, make_tools(world), chat, gate=gate, tracer_provider=tracer_provider, env=env
    )
