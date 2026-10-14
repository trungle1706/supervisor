"""Tiny JSON-over-HTTP client (the only place httpx is used for the gate SDK)."""

from __future__ import annotations

from typing import Any

import httpx


def post_json(url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    """POST ``payload`` as JSON and return the JSON object. Raises on timeout or non-2xx."""
    resp = httpx.post(url, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("gateway returned a non-object response")
    return data
