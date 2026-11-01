"""Manager sign-off through the internal approval service."""
import time

import requests

SIGNOFF_URL = "https://approvals.nganhang.internal/v1/signoff"


def manager_signoff(contract_id: str, action: str) -> bool:
    """Ask a manager to sign off an action and wait for the answer."""
    created = requests.post(SIGNOFF_URL, json={"contract": contract_id, "action": action}, timeout=10)
    ticket = created.json()["id"]
    for _ in range(120):
        state = requests.get(f"{SIGNOFF_URL}/{ticket}", timeout=10).json().get("state")
        if state in ("signed", "refused"):
            return state == "signed"
        time.sleep(5)
    return False
