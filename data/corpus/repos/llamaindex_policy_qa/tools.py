"""Read-only helper functions exposed to the agent."""
import csv
from datetime import date, timedelta


def tra_cuu_bieu_phi(loai_the: str) -> str:
    """Look up the annual fee of a card type in the local fee table."""
    with open("data/bieu_phi.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["loai_the"].lower() == loai_the.lower():
                return f"Phi thuong nien the {loai_the}: {row['phi_thuong_nien']} VND"
    return "Khong tim thay loai the nay."


def tinh_ngay_hieu_luc(ngay_ban_hanh: str, so_ngay: int) -> str:
    """Return the date a policy takes effect, from the issue date (YYYY-MM-DD)."""
    issued = date.fromisoformat(ngay_ban_hanh)
    return (issued + timedelta(days=so_ngay)).isoformat()
