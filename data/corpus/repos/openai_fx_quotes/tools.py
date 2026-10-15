"""Tool implementations for the FX assistant."""
import os
import uuid

import psycopg2
import requests

FX_BASE = "https://fx.nganhang.internal/api/v1"
TRANSFER_URL = "https://fx.nganhang.internal/api/v1/transfers"


def _conn():
    return psycopg2.connect(os.environ["TREASURY_DSN"])


def lay_ty_gia(base: str, quote: str) -> dict:
    """Look up the current FX rate."""
    resp = requests.get(f"{FX_BASE}/rates/{base}/{quote}", timeout=5)
    resp.raise_for_status()
    return resp.json()


def luu_bao_gia(customer_id: str, base: str, quote: str, amount: float, rate: float) -> dict:
    """Book a quote row for a customer."""
    quote_id = str(uuid.uuid4())
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO treasury.fx_quotes (quote_id, customer_id, base, quote, amount, rate) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (quote_id, customer_id, base, quote, amount, rate),
        )
    return {"quote_id": quote_id, "status": "booked"}


def thuc_hien_chuyen_tien(quote_id: str, so_tai_khoan: str, payee_name: str, amount: float) -> dict:
    """Execute the FX transfer to the beneficiary account."""
    payload = {
        "quote_id": quote_id,
        "so_tai_khoan": so_tai_khoan,
        "payee_name": payee_name,
        "amount": amount,
    }
    resp = requests.post(TRANSFER_URL, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()
