"""Read-only tools on customer data."""
import sqlite3

from registry import register_tool

DB_PATH = "khach_hang.db"


@register_tool("tra_cuu_ho_so_khach_hang")
def get_customer_profile(customer_id: str) -> dict:
    """Read the profile of one customer."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT ho_ten, so_dien_thoai, dia_chi FROM khach_hang WHERE customer_id = ?",
        (customer_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"error": "khong tim thay khach hang"}
    return {"ho_ten": row[0], "so_dien_thoai": row[1], "dia_chi": row[2]}
