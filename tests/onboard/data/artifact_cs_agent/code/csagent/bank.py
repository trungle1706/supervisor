"""In-process fake core banking with seeded SYNTHETIC Vietnamese customers (no real data).

All CCCD numbers, phone numbers and accounts below are made up. State lives in the process
memory (a Databricks App has no durable local disk); a restart reseeds.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

# (customer_id, full name, cccd, phone, address, segment)
_SEED_CUSTOMERS = [
    ("KH000101", "Nguyễn Thị Lan", "079301004512", "0901234567", "12 Lê Lợi, Quận 1, TP.HCM", "retail"),
    ("KH000102", "Trần Văn Minh", "001285009876", "0912345678", "45 Hàng Bài, Hoàn Kiếm, Hà Nội", "retail"),
    ("KH000103", "Lê Hoàng Anh", "048197003321", "0987654321", "7 Bạch Đằng, Hải Châu, Đà Nẵng", "priority"),
    ("KH000104", "Phạm Thu Hà", "092200007788", "0933445566", "88 Nguyễn Trãi, Ninh Kiều, Cần Thơ", "retail"),
    ("KH000105", "Võ Quốc Bảo", "075188002244", "0977112233", "3 Trần Phú, Biên Hòa, Đồng Nai", "retail"),
    ("KH000106", "Đặng Mai Phương", "031295006655", "0966778899", "21 Lạch Tray, Ngô Quyền, Hải Phòng", "priority"),
    ("KH000107", "Bùi Đức Thịnh", "056090001199", "0944556677", "15 Phan Chu Trinh, Nha Trang", "retail"),
    ("KH000108", "Hoàng Ngọc Diệp", "038302008833", "0922334455", "60 Lý Thường Kiệt, Thanh Hóa", "retail"),
]

# (fee_id, customer_id, account_id, fee_type, amount_minor VND, status)
_SEED_FEES = [
    ("FEE-2026-0001", "KH000101", "ACC-1001-01", "late_payment_card", 150000, "charged"),
    ("FEE-2026-0002", "KH000101", "ACC-1001-01", "sms_banking_monthly", 12000, "charged"),
    ("FEE-2026-0003", "KH000102", "ACC-1002-01", "below_min_balance", 50000, "charged"),
    ("FEE-2026-0004", "KH000103", "ACC-1003-01", "annual_card", 600000, "charged"),
    ("FEE-2026-0005", "KH000104", "ACC-1004-01", "late_payment_card", 200000, "charged"),
    ("FEE-2026-0006", "KH000105", "ACC-1005-01", "transfer_fee", 11000, "charged"),
    ("FEE-2026-0007", "KH000106", "ACC-1006-01", "annual_card", 1200000, "charged"),
    ("FEE-2026-0008", "KH000107", "ACC-1007-01", "below_min_balance", 50000, "charged"),
    ("FEE-2026-0009", "KH000108", "ACC-1008-01", "late_payment_card", 100000, "charged"),
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


class CoreBank:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.customers: dict[str, dict[str, Any]] = {}
        self.accounts: dict[str, dict[str, Any]] = {}
        self.fees: dict[str, dict[str, Any]] = {}
        self.tickets: list[dict[str, Any]] = []
        self.waivers: list[dict[str, Any]] = []
        self._seed()

    def _seed(self) -> None:
        for i, (cid, name, cccd, phone, addr, seg) in enumerate(_SEED_CUSTOMERS, start=1):
            acc = f"ACC-{1000 + i}-01"
            self.customers[cid] = {"customer_id": cid, "name": name, "cccd": cccd, "phone": phone,
                                   "address": addr, "segment": seg, "accounts": [acc]}
            self.accounts[acc] = {"account_id": acc, "customer_id": cid, "type": "current",
                                  "balance_minor": 5_000_000 * i + 1_250_000, "currency": "VND"}
        for fee_id, cid, acc, ftype, amt, status in _SEED_FEES:
            self.fees[fee_id] = {"fee_id": fee_id, "customer_id": cid, "account_id": acc,
                                 "fee_type": ftype, "amount_minor": amt, "status": status}

    # ---- reads
    def find_customer(self, customer_id: str | None, cccd: str | None) -> dict[str, Any] | None:
        with self._lock:
            c = None
            if customer_id:
                c = self.customers.get(customer_id.strip().upper())
            if c is None and cccd:
                want = "".join(ch for ch in cccd if ch.isdigit())
                c = next((x for x in self.customers.values() if x["cccd"] == want), None)
            if c is None:
                return None
            fees = [f for f in self.fees.values() if f["customer_id"] == c["customer_id"]]
            accs = [self.accounts[a] for a in c["accounts"]]
            return {**c, "account_details": [dict(a) for a in accs], "fees": [dict(f) for f in fees]}

    def get_fee(self, fee_id: str) -> dict[str, Any] | None:
        with self._lock:
            f = self.fees.get(fee_id)
            return dict(f) if f else None

    # ---- writes
    def create_ticket(self, customer_id: str, category: str, summary: str) -> dict[str, Any]:
        with self._lock:
            t = {"ticket_id": f"TCK-{len(self.tickets) + 1:05d}", "customer_id": customer_id,
                 "category": category, "summary": summary, "status": "open",
                 "created_at": _now()}
            self.tickets.append(t)
            return dict(t)

    def waive_fee(self, fee_id: str, account_id: str, amount_minor: int, reason: str,
                  approval_id: str) -> dict[str, Any]:
        with self._lock:
            f = self.fees.get(fee_id)
            if f is None:
                raise ValueError(f"unknown fee {fee_id}")
            if f["account_id"] != account_id:
                raise ValueError("fee does not belong to this account")
            if f["status"] != "charged":
                raise ValueError(f"fee is {f['status']}, not charged")
            if amount_minor != f["amount_minor"]:
                raise ValueError("amount must equal the fee amount")
            f["status"] = "waived"
            w = {"waiver_id": f"WVR-{len(self.waivers) + 1:05d}", "fee_id": fee_id,
                 "account_id": account_id, "amount_minor": amount_minor, "reason": reason,
                 "approval_id": approval_id, "created_at": _now()}
            self.waivers.append(w)
            return dict(w)


BANK = CoreBank()
