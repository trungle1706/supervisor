"""Ghi nhat ky kiem toan cho cac hanh dong tren the."""
import csv
from datetime import datetime, timezone

AUDIT_PATH = "audit/khoa_the.csv"


def ghi_nhat_ky(hanh_dong: str, card_number: str, customer_id: str, ly_do: str) -> None:
    """Them mot dong vao tep CSV kiem toan."""
    with open(AUDIT_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                datetime.now(timezone.utc).isoformat(),
                hanh_dong,
                card_number[-4:],
                customer_id,
                ly_do,
            ]
        )
