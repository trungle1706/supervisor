"""Tools for the transfer assistant. Every transfer passes a maker-checker approval."""

from __future__ import annotations

import time

import requests

APPROVALS = "https://approvals.nganhang.internal/v1/requests"


def request_human_approval(action: str, details: dict, timeout_s: int = 600) -> bool:
    """Open an approval request for a second officer and wait for the answer."""
    created = requests.post(
        "https://approvals.nganhang.internal/v1/requests",
        json={"action": action, "details": details},
        timeout=10,
    )
    request_id = created.json()["id"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = requests.get(f"{APPROVALS}/{request_id}", timeout=10)
        state = status.json().get("state")
        if state in ("approved", "rejected"):
            return state == "approved"
        time.sleep(5)
    return False


def get_balance(account_number: str) -> dict:
    """Read the balance of an account."""
    url = f"https://core.nganhang.internal/v1/accounts/{account_number}/balance"
    resp = requests.get(url, timeout=10)
    return resp.json()


def make_transfer(account_number: str, payee_id: str, amount: int, memo: str = "") -> dict:
    """Transfer money from an account to a payee, after approval."""
    details = {"from": account_number, "payee_id": payee_id, "amount": amount, "memo": memo}
    if not request_human_approval("transfer", details):
        return {"status": "not_approved"}
    resp = requests.post("https://core.nganhang.internal/v1/transfers", json=details, timeout=15)
    return resp.json()


TOOLS = {
    "get_balance": get_balance,
    "make_transfer": make_transfer,
}

TOOL_SPECS = [
    {"name": "get_balance", "description": "Read an account balance"},
    {"name": "make_transfer", "description": "Transfer money to a payee (second officer approves)"},
]
