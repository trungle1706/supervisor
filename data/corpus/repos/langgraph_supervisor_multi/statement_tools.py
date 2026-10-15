"""Statement tool: writes a CSV file for the customer."""

from __future__ import annotations

import csv
import sqlite3

from langchain_core.tools import tool

DB_PATH = "cards.db"


@tool
def export_statement(account_number: str, month: str) -> str:
    """Export the statement of an account for a month to a CSV file and return its path."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT ngay, noi_dung, so_tien FROM cards.sao_ke WHERE account_number = ? AND month = ?",
        (account_number, month),
    )
    rows = cur.fetchall()
    conn.close()
    path = f"exports/{account_number}_{month}.csv"
    with open(f"exports/{account_number}_{month}.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ngay", "noi_dung", "so_tien"])
        writer.writerows(rows)
    return path
