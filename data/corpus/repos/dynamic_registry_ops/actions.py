"""Actions on the core system, wired by a plain dict."""
import requests

CORE = "https://core.nganhang.internal"


def freeze_account(account_number: str, reason: str) -> dict:
    """Freeze an account in the core system."""
    resp = requests.post(
        "https://core.nganhang.internal/api/v1/accounts/freeze",
        json={"account_number": account_number, "reason": reason},
        timeout=10,
    )
    return {"status": resp.status_code}


def unlock_account_report(account_number: str) -> dict:
    """Placeholder that is in no registry."""
    return {"account_number": account_number, "unlocked": False}


HANDLERS = {
    "dong_bang_tai_khoan": freeze_account,
}
