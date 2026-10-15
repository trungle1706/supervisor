"""Tool server: fee quote, watch list check and outgoing remittance."""
import requests
from fastapi import FastAPI, HTTPException

from models import RemitRequest, WatchlistRequest

app = FastAPI(title="remit-toolserver")

FEE_RATE_BP = {"USD": 25, "EUR": 30, "KRW": 20}


@app.get("/tools/quote_fee")
def quote_fee(amount: int, currency: str = "USD") -> dict:
    """Quote the fee of a remittance. Reads nothing outside the process."""
    rate = FEE_RATE_BP.get(currency)
    if rate is None:
        raise HTTPException(status_code=400, detail="currency is not supported")
    fee = max(amount * rate // 10000, 150000)
    return {"amount": amount, "currency": currency, "fee": fee}


@app.post("/tools/check_watchlist")
def check_watchlist(req: WatchlistRequest) -> dict:
    """Look for the beneficiary name in the local watch list file."""
    wanted = req.full_name.strip().lower()
    with open("watchlist.txt", encoding="utf-8") as fh:
        entries = [line.strip().lower() for line in fh if line.strip()]
    return {"full_name": req.full_name, "hit": wanted in entries}


@app.post("/tools/send_remittance")
def send_remittance(req: RemitRequest) -> dict:
    """Send money abroad to the beneficiary account of the order."""
    resp = requests.post(
        "https://core.nganhang.internal/api/v1/remittances",
        json={
            "customer_id": req.customer_id,
            "payee_name": req.payee_name,
            "beneficiary_account": req.beneficiary_account,
            "amount": req.amount,
            "currency": req.currency,
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="core rejected the remittance")
    return {"status": "sent", "reference": resp.json().get("reference")}
