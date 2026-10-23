"""The three tools of the customer service agent (all run against the in-process fake bank)."""
from __future__ import annotations

import json
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from . import approvals
from .bank import BANK


@tool
def lookup_customer_profile(customer_id: str = "", cccd: str = "") -> str:
    """Look up a customer profile, accounts and charged fees. Give the customer_id (KH......)
    or the 12 digit CCCD number."""
    c = BANK.find_customer(customer_id or None, cccd or None)
    if c is None:
        return "NOT_FOUND: no customer matches. Ask for the customer id or the CCCD number."
    view = {k: c[k] for k in ("customer_id", "name", "segment", "accounts")}
    view["account_details"] = c["account_details"]
    view["fees"] = c["fees"]
    return json.dumps(view, ensure_ascii=False)


@tool
def create_ticket(customer_id: str, category: str, summary: str) -> str:
    """Open a service ticket for a customer. category: fee_dispute, card, account, other."""
    if not customer_id or not summary:
        return "ERROR: customer_id and summary are required."
    return json.dumps(BANK.create_ticket(customer_id, category or "other", summary[:500]),
                      ensure_ascii=False)


@tool
def waive_fee(
    fee_id: str,
    account_id: str,
    amount_minor: int,
    reason: str,
    approval_id: str = "",
) -> str:
    """Waive (refund) one charged fee. amount_minor is the fee amount in VND (integer). A human
    approver must approve before this runs; the system asks for it, do not ask the user."""
    try:
        approvals.consume(approval_id, fee_id, account_id, amount_minor)
        w = BANK.waive_fee(fee_id, account_id, amount_minor, reason, approval_id)
    except (PermissionError, ValueError) as exc:
        return f"ERROR: {exc}"
    return json.dumps(w, ensure_ascii=False)


SAFE_TOOLS = [lookup_customer_profile, create_ticket]
SENSITIVE_TOOLS = [waive_fee]
RISK_CLASSES = {"lookup_customer_profile": "pii_export", "create_ticket": "read_only", "waive_fee": "money"}


HIDDEN_FROM_MODEL = {"waive_fee": {"approval_id"}}


def model_tool_specs() -> list[dict]:
    """OpenAI tool specs shown to the model. `approval_id` is left out: it is written by the
    approval step in code (agent.with_approval), never by the model."""
    specs = []
    for t in SAFE_TOOLS + SENSITIVE_TOOLS:
        spec = convert_to_openai_tool(t)
        fn = spec["function"]
        for hidden in HIDDEN_FROM_MODEL.get(t.name, ()):
            fn["parameters"]["properties"].pop(hidden, None)
            if hidden in fn["parameters"].get("required", []):
                fn["parameters"]["required"].remove(hidden)
        specs.append(spec)
    return specs
