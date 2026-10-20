"""Tiny JSON-over-HTTP client (the only place httpx is used for the gate SDK)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx


def post_json(
    url: str,
    payload: dict[str, Any],
    timeout_s: float,
    *,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """POST ``payload`` as JSON and return the JSON object. Raises on timeout or non-2xx.

    ``headers`` (WP21: Authorization, Idempotency-Key for the SIEM and webhook sends) are
    sent as given; the caller keeps tokens out of logs."""
    resp = httpx.post(url, json=payload, timeout=timeout_s, headers=dict(headers or {}))
    resp.raise_for_status()
    if not resp.content:  # many collectors answer 200/202 with an empty body
        return {}
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("gateway returned a non-object response")
    return data
