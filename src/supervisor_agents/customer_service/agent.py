"""Customer service agent: tickets, replies, fee waivers (capped), card disputes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opentelemetry.sdk.trace import TracerProvider

from supervisor.core.ports import ChatModel, GateHook
from supervisor_agents.common import build_runtime
from supervisor_agents.common.manifest import load_manifest
from supervisor_agents.common.runtime import AgentRuntime, ToolError, ToolRegistry
from supervisor_agents.common.world import BankWorld

AGENT_ID = "customer_service"


def _int_amount(args: Mapping[str, Any]) -> int:
    amount = args["amount_minor"]
    if type(amount) is not int or amount <= 0:
        raise ToolError("amount_minor must be a positive integer (VND)")
    return amount


def make_tools(world: BankWorld) -> ToolRegistry:
    limit = load_manifest(AGENT_ID).limits["waive_fee_max_minor"]
    reg = ToolRegistry()

    def lookup_customer(args: Mapping[str, Any]) -> dict[str, Any]:
        c = world.customers.get(args["customer_id"])
        if c is None:
            raise ToolError(f"customer {args['customer_id']} not found")
        initials = ".".join(p[0] for p in c.full_name.split()) + "."
        return {
            "customer_id": c.customer_id,
            "name_masked": initials,
            "segment": c.segment,
            "language": c.language,
            "province": c.province,
            "accounts": [
                {
                    "account_id": a.account_id,
                    "product": a.product,
                    "balance_minor": world.balances[a.account_id],
                }
                for a in world.customer_accounts(c.customer_id)
            ],
        }

    def read_ticket(args: Mapping[str, Any]) -> dict[str, Any]:
        t = world.tickets.get(args["ticket_id"])
        if t is None:
            raise ToolError(f"ticket {args['ticket_id']} not found")
        return {
            "ticket_id": t.ticket_id,
            "customer_id": t.customer_id,
            "subject": t.subject,
            "body": t.body,
        }

    def reply(args: Mapping[str, Any]) -> dict[str, Any]:
        if args["ticket_id"] not in world.tickets:
            raise ToolError(f"ticket {args['ticket_id']} not found")
        world.replies.append({"ticket_id": args["ticket_id"], "text": str(args["text"])})
        return {"sent": True}

    def waive_fee(args: Mapping[str, Any]) -> dict[str, Any]:
        amount = _int_amount(args)
        if args["account_id"] not in world.accounts:
            raise ToolError(f"account {args['account_id']} not found")
        if amount > limit:
            raise ToolError(f"waiver {amount} exceeds the per-waiver limit {limit}")
        world.waivers.append(
            {
                "account_id": args["account_id"],
                "fee_code": str(args["fee_code"]),
                "amount_minor": amount,
                "reason": str(args.get("reason", "")),
            }
        )
        return {"waived": True, "amount_minor": amount}

    def open_dispute(args: Mapping[str, Any]) -> dict[str, Any]:
        amount = _int_amount(args)
        if args["customer_id"] not in world.customers:
            raise ToolError(f"customer {args['customer_id']} not found")
        dispute_id = f"DSP-{len(world.disputes) + 1:05d}"
        world.disputes.append(
            {
                "dispute_id": dispute_id,
                "customer_id": args["customer_id"],
                "card_last4": str(args["card_last4"]),
                "amount_minor": amount,
            }
        )
        return {"dispute_id": dispute_id}

    for fn in (lookup_customer, read_ticket, reply, waive_fee, open_dispute):
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
