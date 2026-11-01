"""Human review: a task goes to the KYC review queue and the caller waits for the reviewer."""
import time

import requests

QUEUE = "https://review.nganhang.internal/v1/tasks"


def wait_for_reviewer(customer_id: str, proposed: str, timeout_s: int = 1800) -> bool:
    """Put the proposed status in the queue; True when a reviewer accepts it."""
    task = requests.post(QUEUE, json={"customer": customer_id, "proposed": proposed}, timeout=10)
    task_id = task.json()["task_id"]
    waited = 0
    while waited < timeout_s:
        state = requests.get(f"{QUEUE}/{task_id}", timeout=10).json().get("state")
        if state in ("accepted", "rejected"):
            return state == "accepted"
        time.sleep(10)
        waited += 10
    return False
