"""Side-effecting and read tools, with a human approval gate."""
import os
import uuid

import psycopg2


def _conn():
    return psycopg2.connect(os.environ["CARDS_DSN"])


def request_human_approval(action: str, details: dict) -> bool:
    """Block until a supervisor approves or rejects the action in the review queue."""
    ticket = str(uuid.uuid4())
    print(f"Waiting for approval of {action}: {details} (ticket {ticket})")
    answer = input("Approve? [y/N] ")
    return answer.strip().lower() == "y"


def doc_giao_dich(transaction_id: str) -> dict:
    """Read one card transaction."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT transaction_id, card_number, amount, merchant FROM cards.transactions "
            "WHERE transaction_id = %s",
            (transaction_id,),
        )
        row = cur.fetchone()
    return dict(zip(["transaction_id", "card_number", "amount", "merchant"], row or []))


def mo_khieu_nai(customer_id: str, transaction_id: str, reason: str) -> dict:
    """Open a dispute case."""
    if not request_human_approval("open_dispute", {"transaction_id": transaction_id}):
        return {"status": "rejected_by_supervisor"}
    case_id = "DSP-" + uuid.uuid4().hex[:8]
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cards.disputes (case_id, customer_id, transaction_id, reason) "
            "VALUES (%s, %s, %s, %s)",
            (case_id, customer_id, transaction_id, reason),
        )
    return {"case_id": case_id, "status": "opened"}


def hoan_phi(customer_id: str, fee_id: str) -> dict:
    """Refund a fee to the customer's own account (no destination chosen here)."""
    if not request_human_approval("refund_fee", {"fee_id": fee_id}):
        return {"status": "rejected_by_supervisor"}
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE cards.fees SET refunded = TRUE WHERE fee_id = %s AND customer_id = %s",
            (fee_id, customer_id),
        )
    return {"fee_id": fee_id, "status": "refunded"}
