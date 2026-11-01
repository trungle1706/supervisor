"""Maker-checker control for settlements."""
import time

import requests

MAKER = "https://maker.nganhang.internal/v1/checks"


def double_check(batch_id: str, total_vnd: int) -> bool:
    """Ask a second officer to confirm the batch. Blocks until the answer or the timeout."""
    r = requests.post(MAKER, json={"batch": batch_id, "total": total_vnd}, timeout=10)
    check_id = r.json()["id"]
    for _ in range(360):
        answer = requests.get(f"{MAKER}/{check_id}", timeout=10).json().get("answer")
        if answer in ("yes", "no"):
            return answer == "yes"
        time.sleep(5)
    return False
