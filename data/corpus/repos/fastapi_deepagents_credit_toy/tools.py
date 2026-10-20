"""Tools of the credit toy agent. Data is synthetic."""
import json
import sqlite3
from pathlib import Path

from langchain_core.tools import tool

DB = "credit_toy.db"
POLICY_DIR = Path("policy")


@tool
def read_facility(customer_id: str) -> dict:
    """Read the requested facility of a borrower."""
    con = sqlite3.connect(DB)
    row = con.execute(
        "SELECT amount_minor, tenor_months FROM facilities WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    return {"customer_id": customer_id, "amount_minor": row[0], "tenor_months": row[1]}


@tool
def fetch_financials(customer_id: str, year: int) -> dict:
    """Fetch the yearly income statement of a borrower."""
    con = sqlite3.connect(DB)
    row = con.execute(
        "SELECT revenue_minor, net_income FROM financials WHERE customer_id = ? AND year = ?",
        (customer_id, year),
    ).fetchone()
    return {"revenue_minor": row[0], "net_income": row[1]}


@tool
def compute_dscr(net_operating_income_minor: int, debt_service_minor: int) -> int:
    """Debt service coverage ratio in basis points."""
    return net_operating_income_minor * 10000 // max(debt_service_minor, 1)


@tool
def search_policy(query: str) -> str:
    """Find the credit policy paragraph that matches the query."""
    hits = []
    for path in POLICY_DIR.glob("*.txt"):
        text = path.read_text(encoding="utf-8")
        if query.lower() in text.lower():
            hits.append(text[:400])
    return "\n".join(hits)


@tool
def draft_section(title: str, body: str) -> str:
    """Format one memo section."""
    return f"## {title}\n\n{body}\n"


@tool
def save_memo_draft(customer_id: str, memo_text: str) -> str:
    """Save the memo draft for the credit officer to review."""
    con = sqlite3.connect(DB)
    con.execute(
        "INSERT INTO memo_drafts (customer_id, body) VALUES (?, ?)", (customer_id, memo_text)
    )
    con.commit()
    return json.dumps({"saved": True})
