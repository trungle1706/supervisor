"""HTTP surface of the credit toy service."""
from fastapi import FastAPI, HTTPException

from agent import build_agent

app = FastAPI(title="credit-toy")
AGENT = build_agent()
MEMOS: dict[str, str] = {}


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/memos")
def create_memo(customer_id: str) -> dict:
    result = AGENT.invoke({"messages": [{"role": "user", "content": f"Memo for {customer_id}"}]})
    MEMOS[customer_id] = result["messages"][-1].content
    return {"customer_id": customer_id}


@app.get("/memos/{customer_id}")
def get_memo(customer_id: str) -> dict:
    if customer_id not in MEMOS:
        raise HTTPException(status_code=404, detail="no memo")
    return {"memo": MEMOS[customer_id]}


@app.post("/memos/{customer_id}/review")
def review_memo(customer_id: str, approved: bool) -> dict:
    return {"customer_id": customer_id, "approved": approved}


@app.get("/cases")
def list_cases() -> list[str]:
    return sorted(MEMOS)
