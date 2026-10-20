"""Outbound JSON over HTTP for the SIEM sink and the webhook notifier (WP21).

``HttpTransport`` adds the Authorization header (token from the bank vault via settings,
held as a plain str only inside this object, never logged, never in a repr) and an
``Idempotency-Key`` header taken from the payload. Errors are mapped for ``with_retry``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from supervisor.adapters.integrations import IntegrationError

Transport = Callable[[str, dict[str, Any], float], Mapping[str, Any]]


def idempotency_key(event_ids: Iterable[str]) -> str:
    """Same events in the same order -> same key (a retry or a replay is recognisable)."""
    h = hashlib.sha256("\n".join(event_ids).encode("utf-8")).hexdigest()
    return h[:32]


def post_json_mapped(
    url: str, payload: dict[str, Any], timeout_s: float, headers: Mapping[str, str]
) -> Mapping[str, Any]:
    """``post_json`` with its errors mapped to what ``with_retry`` understands: network
    errors, timeouts, 429 and 5xx become ConnectionError (retried); another 4xx becomes
    IntegrationError at once (a wrong URL or token will not fix itself)."""
    import httpx

    from supervisor.adapters.http_json import post_json

    try:
        return post_json(url, payload, timeout_s, headers=headers)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 429 or code >= 500:
            raise ConnectionError(f"HTTP {code}") from None
        raise IntegrationError(f"HTTP {code} from the receiver (not retried)") from None
    except httpx.HTTPError as exc:  # connect error, timeout, protocol error
        raise ConnectionError(type(exc).__name__) from None
    except ValueError:
        # 2xx with a body that is not a JSON object ("OK", an HTML page, a JSON list): the
        # receiver accepted the batch. Raising here would keep the cursor and resend the same
        # batch on every poll.
        return {}


class HttpTransport:
    """POST JSON with an Authorization header and an ``Idempotency-Key`` header.

    The token comes from the bank vault into ``SIEM_HTTP_TOKEN``; it is held as a SecretStr,
    sent only in the header, and never logged or written to the dead-letter file."""

    def __init__(self, token: str | None = None, scheme: str = "Bearer") -> None:
        self._token = token
        self.scheme = scheme

    def __call__(self, url: str, payload: dict[str, Any], timeout_s: float) -> Mapping[str, Any]:
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"{self.scheme} {self._token}"
        key = payload.get("idempotency_key")
        if key:
            headers["Idempotency-Key"] = str(key)
        return post_json_mapped(url, payload, timeout_s, headers)

    def __repr__(self) -> str:  # never show the token
        return f"HttpTransport(scheme={self.scheme!r}, token={'set' if self._token else 'unset'})"


__all__ = ["HttpTransport", "Transport", "idempotency_key", "post_json_mapped"]
