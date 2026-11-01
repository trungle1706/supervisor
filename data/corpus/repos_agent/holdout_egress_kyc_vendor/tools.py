"""Tools of the KYC assistant."""
import sqlite3

from review_queue import wait_for_reviewer
from vendor import verify

DB = "kyc.db"


def xac_minh_danh_tinh(so_cccd: str, ho_ten: str, ngay_sinh: str) -> dict:
    """Verify the identity document data with the outside vendor."""
    return verify(so_cccd, ho_ten, ngay_sinh)


def tra_cuu_trang_thai(customer_id: str) -> dict:
    """Read the KYC status of a customer."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT status FROM kyc_status WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    conn.close()
    return {"customer_id": customer_id, "status": row[0] if row else "none"}


def ghi_ket_qua_kyc(customer_id: str, status: str) -> dict:
    """Store the KYC result after a reviewer agrees."""
    if not wait_for_reviewer(customer_id, status):
        return {"stored": False}
    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT OR REPLACE INTO kyc_status (customer_id, status) VALUES (?, ?)", (customer_id, status)
    )
    conn.commit()
    conn.close()
    return {"stored": True}


TOOLS = [xac_minh_danh_tinh, tra_cuu_trang_thai, ghi_ket_qua_kyc]
