"""May chu MCP cho nghiep vu the: tra trang thai va khoa the."""
import os

import httpx
from mcp.server.fastmcp import FastMCP

from audit import ghi_nhat_ky

CARDS_API = "https://cards.nganhang.internal/api/v2"

mcp = FastMCP("the-ngan-hang")


def _headers() -> dict:
    return {"X-Service-Token": os.environ["CARDS_SERVICE_TOKEN"]}


@mcp.tool()
def tra_trang_thai_the(card_number: str) -> dict:
    """Tra cuu trang thai cua the theo card_number (da che)."""
    resp = httpx.get(
        f"{CARDS_API}/cards/{card_number}/status",
        headers=_headers(),
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def khoa_the(card_number: str, customer_id: str, ly_do: str) -> dict:
    """Khoa the ngay lap tuc theo yeu cau cua khach hang."""
    resp = httpx.post(
        f"{CARDS_API}/cards/{card_number}/freeze",
        json={"ly_do": ly_do},
        headers=_headers(),
        timeout=10.0,
    )
    resp.raise_for_status()
    ghi_nhat_ky("freeze", card_number, customer_id, ly_do)
    return {"trang_thai": "da_khoa", "card_number": card_number}


if __name__ == "__main__":
    mcp.run(transport="stdio")
