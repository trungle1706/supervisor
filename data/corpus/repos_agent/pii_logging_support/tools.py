"""Support tools. Customer data is passed to the log helpers as it is."""
import sqlite3

import requests

from logsetup import audit, log_event

DB = "crm.db"


def tra_cuu_khach_hang(so_dien_thoai: str) -> dict:
    """Find a customer by phone number."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT customer_id, ho_ten, dia_chi FROM khach_hang WHERE so_dien_thoai = ?",
        (so_dien_thoai,),
    ).fetchone()
    conn.close()
    found = {"customer_id": row[0], "ho_ten": row[1], "dia_chi": row[2]} if row else {}
    log_event("lookup", so_dien_thoai=so_dien_thoai, ho_ten=found.get("ho_ten"))
    return found


def cap_nhat_dia_chi(customer_id: str, dia_chi: str) -> dict:
    """Update the address of a customer."""
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE khach_hang SET dia_chi = ? WHERE customer_id = ?", (dia_chi, customer_id))
    conn.commit()
    conn.close()
    audit("assistant", "update_address", {"customer_id": customer_id, "dia_chi": dia_chi})
    return {"updated": True}


def gui_otp(so_dien_thoai: str) -> dict:
    """Send a one-time code to the phone number."""
    print(f"sending otp to {so_dien_thoai}")
    resp = requests.post(
        "https://sms.example.vn/v1/otp", json={"to": so_dien_thoai}, timeout=10
    )
    return {"sent": resp.ok}


HANDLERS = {
    "tra_cuu_khach_hang": tra_cuu_khach_hang,
    "cap_nhat_dia_chi": cap_nhat_dia_chi,
    "gui_otp": gui_otp,
}
