"""Tools for the collections crew."""
import os
import sqlite3

import requests
from crewai.tools import BaseTool, tool
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("COLLECTIONS_DB", "collections.db")


class OverdueInput(BaseModel):
    min_days_overdue: int = Field(default=1, description="Only loans overdue at least this many days")


class TraCuuKhoanVayTool(BaseTool):
    name: str = "tra_cuu_khoan_vay"
    description: str = "List overdue loans with days overdue and outstanding balance."
    args_schema: type[BaseModel] = OverdueInput

    def _run(self, min_days_overdue: int = 1) -> str:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT customer_id, ho_ten, so_dien_thoai, overdue_days, outstanding_vnd "
            "FROM overdue_loans WHERE overdue_days >= ? ORDER BY overdue_days DESC",
            (min_days_overdue,),
        ).fetchall()
        conn.close()
        return "\n".join(f"{r[0]}|{r[1]}|{r[2]}|{r[3]}d|{r[4]}" for r in rows)


class GuiNhacNoSmsTool(BaseTool):
    name: str = "gui_nhac_no_sms"
    description: str = "Send an SMS payment reminder to a borrower."

    def _run(self, so_dien_thoai: str, noi_dung: str) -> str:
        resp = requests.post(
            "https://sms.example.vn/v1/messages",
            json={"to": so_dien_thoai, "text": noi_dung},
            timeout=10,
        )
        return "sent" if resp.ok else f"failed {resp.status_code}"


@tool("ghi_nhan_ke_hoach_tra_no")
def record_payment_plan(customer_id: str, installment_vnd: int, installments: int) -> str:
    """Record a new repayment schedule that replaces the original loan terms."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO payment_plans (customer_id, installment_vnd, installments, status) VALUES (?, ?, ?, 'active')",
        (customer_id, installment_vnd, installments),
    )
    conn.commit()
    conn.close()
    return f"plan stored for {customer_id}: {installments} x {installment_vnd}"
