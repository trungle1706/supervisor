"""Tools the triage model can call."""
import os
import sqlite3

from langchain_core.tools import tool

DB_PATH = os.environ.get("LOAN_DB_PATH", "loans.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@tool
def read_loan_application(application_id: str) -> dict:
    """Read one loan application from the loan_applications table."""
    conn = _connect()
    row = conn.execute(
        "SELECT application_id, customer_id, ho_ten, monthly_income, requested_amount, term_months "
        "FROM loan_applications WHERE application_id = ?",
        (application_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return {"error": "application not found"}
    return dict(row)


@tool
def get_bureau_score(customer_id: str) -> dict:
    """Return the latest bureau score band for a customer."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT score, band FROM bureau_scores WHERE customer_id = ? ORDER BY scored_at DESC LIMIT 1",
        (customer_id,),
    )
    row = cur.fetchone()
    conn.close()
    return {"score": row[0], "band": row[1]} if row else {"score": None, "band": "unknown"}


@tool
def record_preapproval_decision(application_id: str, decision: str, approved_limit_vnd: int) -> str:
    """Record the pre-approval decision (approve, decline or refer) and the limit."""
    if decision not in {"approve", "decline", "refer"}:
        return "invalid decision"
    conn = _connect()
    conn.execute(
        "UPDATE loan_applications SET decision = ?, approved_limit = ? WHERE application_id = ?",
        (decision, approved_limit_vnd, application_id),
    )
    conn.commit()
    conn.close()
    return f"decision {decision} stored for {application_id}"


ALL_TOOLS = [read_loan_application, get_bureau_score, record_preapproval_decision]
