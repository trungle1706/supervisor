"""Plugin module. Which functions are tools is decided by tools.yaml."""
import requests


def raise_card_limit(card_number: str, new_limit: int, monthly_income: int) -> dict:
    """Raise the credit limit of a card when income allows it."""
    if new_limit > monthly_income * 3:
        return {"approved": False, "reason": "limit is above 3x income"}
    resp = requests.put(
        "https://core.nganhang.internal/api/v1/cards/limit",
        json={"card_number": card_number, "limit": new_limit},
        timeout=10,
    )
    return {"approved": resp.ok, "limit": new_limit}


def export_audit_dump(path: str) -> str:
    """Helper for operators. Not enabled in tools.yaml and not registered."""
    return f"dump written to {path}"
