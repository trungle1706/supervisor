"""Request models of the remittance tool server."""
from pydantic import BaseModel, Field


class WatchlistRequest(BaseModel):
    full_name: str = Field(description="Beneficiary name as printed on the order")
    country: str = "KR"


class RemitRequest(BaseModel):
    customer_id: str
    payee_name: str
    beneficiary_account: str
    amount: int = Field(gt=0, description="Amount in minor units of the currency")
    currency: str = "USD"
    phone: str | None = None
    note: str = ""
