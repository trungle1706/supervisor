"""Máy chủ MCP tra cứu tài khoản và chuyển tiền cho khách hàng."""
import os
from datetime import datetime, timezone

import psycopg
from fastmcp import FastMCP
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer("tai_khoan.mcp")

mcp = FastMCP("tai-khoan")


def get_conn() -> psycopg.Connection:
    return psycopg.connect(os.environ["PG_DSN"])


@mcp.tool()
def get_balance(account_number: str) -> dict:
    """Return the current balance of one account."""
    with tracer.start_as_current_span("get_balance") as span:
        span.set_attribute("tool.name", "get_balance")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT balance, currency FROM core.accounts WHERE account_number = %s",
                (account_number,),
            )
            row = cur.fetchone()
        if row is None:
            return {"error": "account not found"}
        return {"account_number": account_number, "balance": int(row[0]), "currency": row[1]}


@mcp.tool()
def list_accounts(customer_id: str) -> list[dict]:
    """List the accounts that belong to a customer."""
    with tracer.start_as_current_span("list_accounts"):
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT account_id, account_number, product FROM core.accounts WHERE customer_id = %s",
                (customer_id,),
            )
            return [
                {"account_id": r[0], "account_number": r[1], "product": r[2]}
                for r in cur.fetchall()
            ]


@mcp.tool(name="tra_cuu_giao_dich")
def search_transactions(account_id: str, limit: int = 20) -> list[dict]:
    """Return the latest transactions of an account."""
    with tracer.start_as_current_span("tra_cuu_giao_dich") as span:
        span.set_attribute("tx.limit", limit)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT tx_id, amount, memo, booked_at FROM core.transactions "
                "WHERE account_id = %s ORDER BY booked_at DESC LIMIT %s",
                (account_id, limit),
            )
            return [
                {"tx_id": r[0], "amount": int(r[1]), "memo": r[2], "booked_at": str(r[3])}
                for r in cur.fetchall()
            ]


@mcp.tool()
def transfer_to_beneficiary(
    customer_id: str, from_account: str, to_account: str, amount: int, memo: str = ""
) -> dict:
    """Move money from a customer account to a saved beneficiary account."""
    with tracer.start_as_current_span("transfer_to_beneficiary") as span:
        span.set_attribute("transfer.amount", amount)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT full_name FROM core.beneficiaries "
                "WHERE customer_id = %s AND account_number = %s",
                (customer_id, to_account),
            )
            payee = cur.fetchone()
            if payee is None:
                return {"error": "beneficiary is not saved"}
            cur.execute(
                "UPDATE core.accounts SET balance = balance - %s WHERE account_number = %s",
                (amount, from_account),
            )
            cur.execute(
                "UPDATE core.accounts SET balance = balance + %s WHERE account_number = %s",
                (amount, to_account),
            )
            cur.execute(
                "INSERT INTO core.transfers (from_account, to_account, amount, memo, at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (from_account, to_account, amount, memo, datetime.now(timezone.utc)),
            )
            conn.commit()
        return {"status": "done", "to": payee[0], "amount": amount}


@mcp.resource("bank://products/catalog")
def product_catalog() -> str:
    """Static list of the account products. Not a tool."""
    return "Tai khoan thanh toan; Tai khoan tiet kiem; The ghi no"


if __name__ == "__main__":
    mcp.run()
