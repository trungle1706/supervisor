"""Read-only tools of the card limit advisor."""

from __future__ import annotations

import sqlite3

from langchain_core.tools import tool

DB_PATH = "cards.db"


@tool
def get_card_limit(card_number: str) -> dict:
    """Return the current limit and the used amount of a card."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT han_muc, da_su_dung FROM cards.the_tin_dung WHERE card_number = ?",
        (card_number,),
    ).fetchone()
    conn.close()
    return {"limit": row[0], "used": row[1]} if row else {}


@tool
def get_spending_summary(card_number: str, month: str) -> list[dict]:
    """Return spending per category for a card in a month (YYYY-MM)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT category, SUM(amount) FROM cards.giao_dich WHERE card_number = ? AND month = ? GROUP BY category",
        (card_number, month),
    )
    rows = [{"category": c, "total": t} for c, t in cur.fetchall()]
    conn.close()
    return rows
