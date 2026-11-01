"""Back-office tools. Debt write-off and note deletion run on the model's request."""
import sqlite3

import requests

from approvals import manager_signoff

DB = "collections.db"
MAX_WRITEOFF_VND = 20_000_000


def xem_du_no(contract_id: str) -> dict:
    """Read the outstanding balance of a contract."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT contract_id, customer_id, outstanding_vnd FROM contracts WHERE contract_id = ?",
        (contract_id,),
    ).fetchone()
    conn.close()
    return {"contract_id": row[0], "customer_id": row[1], "outstanding_vnd": row[2]} if row else {}


def gia_han_no(contract_id: str, days: int) -> dict:
    """Move the due date of a contract. A manager signs off first."""
    if not manager_signoff(contract_id, f"extend {days} days"):
        return {"status": "refused"}
    resp = requests.post(
        "https://core.nganhang.internal/v1/contracts/extend",
        json={"contract_id": contract_id, "days": days},
        timeout=10,
    )
    return {"status": "extended" if resp.ok else "failed"}


def xoa_no(contract_id: str, amount_vnd: int, reason: str) -> dict:
    """Write off part of a debt. The balance cannot be restored by this agent."""
    if amount_vnd > MAX_WRITEOFF_VND:
        return {"status": "too_large"}
    conn = sqlite3.connect(DB)
    conn.execute(
        "UPDATE contracts SET outstanding_vnd = outstanding_vnd - ?, note = ? WHERE contract_id = ?",
        (amount_vnd, reason, contract_id),
    )
    conn.commit()
    conn.close()
    return {"status": "written_off", "amount_vnd": amount_vnd}


def xoa_ghi_chu(note_id: str) -> dict:
    """Delete a note of a contract for good."""
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM contract_notes WHERE note_id = ?", (note_id,))
    conn.commit()
    conn.close()
    return {"deleted": note_id}


REGISTRY = {
    "xem_du_no": xem_du_no,
    "gia_han_no": gia_han_no,
    "xoa_no": xoa_no,
    "xoa_ghi_chu": xoa_ghi_chu,
}
SPECS = [
    {"name": "xem_du_no", "description": "Read the outstanding balance of a contract"},
    {"name": "gia_han_no", "description": "Extend the due date (manager signs off)"},
    {"name": "xoa_no", "description": "Write off part of a debt"},
    {"name": "xoa_ghi_chu", "description": "Delete a contract note"},
]
