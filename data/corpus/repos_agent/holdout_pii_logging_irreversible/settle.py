"""Payout tools. Merchant data goes to the log helpers as it is."""
import logging
import sqlite3

import requests

from controls import double_check

log = logging.getLogger("settle")
DB = "payouts.db"


def _trace(msg: str, rec: dict) -> None:
    log.info("%s %s", msg, rec)


def settle_batch(batch_id: str, total_vnd: int, ngan_hang_nhan: str) -> dict:
    """Pay out a batch of merchant payouts to the receiving bank. Cannot be taken back."""
    if total_vnd <= 0 or total_vnd > 2_000_000_000:
        raise ValueError("total out of range")
    if not double_check(batch_id, total_vnd):
        return {"status": "not_confirmed"}
    resp = requests.post(
        "https://core.nganhang.internal/v1/settlements",
        json={"batch": batch_id, "total": total_vnd, "bank": ngan_hang_nhan},
        timeout=30,
    )
    return {"status": "settled" if resp.ok else "failed"}


def rollback_note(note_id: str) -> dict:
    """Mark a draft payout note as cancelled (it can be set again)."""
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE payout_notes SET cancelled = 1 WHERE note_id = ?", (note_id,))
    conn.commit()
    conn.close()
    return {"cancelled": note_id}


def notify_merchant(merchant: dict, text: str) -> dict:
    """Send an SMS to the merchant contact."""
    log.warning("sms to %s", merchant["so_dien_thoai"])
    _trace("sms", {"merchant": merchant, "text": text})
    resp = requests.post(
        "https://sms.vendor-y.example.vn/send",
        json={"to": merchant["so_dien_thoai"], "text": text},
        timeout=10,
    )
    return {"sent": resp.ok}
