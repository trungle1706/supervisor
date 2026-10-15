"""Approval helpers. Not wired into the agent yet (planned for the next release)."""

from __future__ import annotations


def request_human_approval(action: str, amount: int) -> bool:
    """Ask an officer to approve an action. Always returns False until the queue exists."""
    print(f"Pending approval: {action} amount={amount}")
    return False
