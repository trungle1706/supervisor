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


def post_json_status(
    url: str,
    payload: dict[str, Any],
    timeout_s: float,
    *,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, Any]:
    """POST ``payload`` as JSON; return ``(status, parsed JSON or None)``. Never follows a
    redirect (a header with a token must not leave the host that was checked), never raises for
    a non-2xx status. A timeout raises ``TimeoutError`` and any other transport problem raises
    ``ConnectionError``; both carry only the error class, never the URL or a header (WP-O3b)."""
    try:
        resp = httpx.post(
            url,
            json=payload,
            timeout=timeout_s,
            headers=dict(headers or {}),
            follow_redirects=False,
        )
    except httpx.TimeoutException as exc:
        raise TimeoutError("the request timed out") from exc
    except httpx.HTTPError as exc:
        raise ConnectionError(f"the request failed ({type(exc).__name__})") from None
    try:
        data = resp.json() if resp.content else None
    except ValueError:
        data = None
    return resp.status_code, data


def post_bytes(url: str, body: bytes, headers: dict[str, str], timeout_s: float) -> dict[str, Any]:
    """POST the exact ``body`` bytes (a signed request must be sent as signed). Raises on
    timeout or non-2xx; the HTTP error keeps ``.response`` so callers can read the status."""
    resp = httpx.post(url, content=body, headers=headers, timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("gateway returned a non-object response")
    return data


def get_json(
    url: str, timeout_s: float, *, headers: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """GET and return the JSON object (human CLI against the app's routes). Raises on non-2xx."""
    resp = httpx.get(url, timeout=timeout_s, headers=dict(headers or {}))
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("server returned a non-object response")
    return data


class PooledJson:
    """JSON POST client that keeps its connections (WP26: the HTTP MCP proxy talks to the gate
    on every tools/call; a new connection per call cost about 8 ms in the stdio proxy).

    ``post_json`` and ``post_bytes`` have the signatures ``HttpGate`` expects for its
    ``transport`` and ``signed_transport`` arguments."""

    def __init__(self) -> None:
        self._client = httpx.Client(limits=httpx.Limits(max_keepalive_connections=20))

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        timeout_s: float,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        resp = self._client.post(url, json=payload, timeout=timeout_s, headers=dict(headers or {}))
        return _object(resp)

    def post_bytes(
        self, url: str, body: bytes, headers: Mapping[str, str], timeout_s: float
    ) -> dict[str, Any]:
        resp = self._client.post(url, content=body, headers=dict(headers), timeout=timeout_s)
        return _object(resp)

    def close(self) -> None:
        self._client.close()


def _object(resp: httpx.Response) -> dict[str, Any]:
    resp.raise_for_status()
    if not resp.content:
        return {}
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("server returned a non-object response")
    return data
