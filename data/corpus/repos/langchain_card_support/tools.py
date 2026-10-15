"""Card support tools. All calls go to the internal card API."""
import os

import requests
from langchain_core.tools import tool

BASE_URL = "https://cards.nganhang.internal/v1"
TIMEOUT = 10


def _headers() -> dict:
    return {"Authorization": "Bearer " + os.environ["CARD_API_TOKEN"]}


@tool
def tra_cuu_the(customer_id: str) -> list:
    """List the cards (masked) that belong to a customer."""
    resp = requests.get(
        "https://cards.nganhang.internal/v1/cards",
        params={"customer_id": customer_id},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["cards"]


@tool
def lay_han_muc_the(card_id: str) -> dict:
    """Get the credit limit and the remaining limit of a card."""
    resp = requests.get(
        f"https://cards.nganhang.internal/v1/cards/{card_id}/limit",
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


@tool("khoa_the_tam_thoi")
def block_card(card_id: str, card_number: str, reason: str) -> str:
    """Temporarily block a card. The customer can unlock it at a branch."""
    resp = requests.post(
        f"https://cards.nganhang.internal/v1/cards/{card_id}/block",
        json={"card_number": card_number, "reason": reason, "temporary": True},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return "Da khoa the tam thoi."


TOOLS = [tra_cuu_the, lay_han_muc_the, block_card]
