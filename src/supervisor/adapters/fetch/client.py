"""URL fetch adapter (WP-D1). Used only when URL_FETCH_ENABLED=1 and URL_FETCH_ALLOWLIST names a
domain. The one place in the product that reads a page from the internet.

``Fetcher.fetch(url)`` returns the bytes and the media type, or raises:

* ``UrlRefused`` (guard.py): ``url.ssrf_refused`` or ``url.domain_blocked``. Nothing was sent;
* ``FetchFailed(reason)``: the page could not be read (timeout, error status, too large, bad
  redirect). The caller reports the document as uninspectable with that reason.

Rules: HTTPS only; the address is checked after DNS and the connection goes to the address that
was checked; at most 3 redirects and only to the same host (each hop passes the guard again);
1 MB cap; 3 s for the whole fetch. The transport and the resolver are injected, so the tests use
fakes and open no socket.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urljoin

from supervisor.adapters.fetch.guard import (
    SSRF_REFUSED,
    ParsedUrl,
    Resolver,
    UrlRefused,
    check_before_dns,
    check_resolved,
    parse_url,
    system_resolver,
)
from supervisor.adapters.fetch.transport import HttpsTransport, Transport, TransportResponse
from supervisor.core.bounded import BoundedSlots, NoSlot

log = logging.getLogger(__name__)
MAX_BYTES = 1024 * 1024
TIMEOUT_S = 3.0
MAX_REDIRECTS = 3
_DNS_SLOTS = BoundedSlots(8)


class FetchFailed(Exception):
    """The page could not be read. ``reason`` is a fixed short phrase."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Fetched:
    data: bytes
    media_type: str  # from Content-Type, lower case, without parameters ("" when absent)


class Fetcher:
    def __init__(
        self,
        allowlist: Iterable[str],
        *,
        transport: Transport | None = None,
        resolver: Resolver | None = None,
        max_bytes: int = MAX_BYTES,
        timeout_s: float = TIMEOUT_S,
        max_redirects: int = MAX_REDIRECTS,
    ) -> None:
        self.allowlist = tuple(d.lower() for d in allowlist)
        self.transport: Transport = transport or HttpsTransport()
        self.resolver: Resolver = resolver or system_resolver
        self.max_bytes = max_bytes
        self.timeout_s = timeout_s
        self.max_redirects = max_redirects

    @property
    def enabled(self) -> bool:
        return bool(self.allowlist)

    def _resolve(self, host: str, left_s: float) -> list[str]:
        try:
            found = _DNS_SLOTS.call(lambda: self.resolver(host), max(0.05, left_s), "fetch-dns")
        except (TimeoutError, NoSlot):
            raise FetchFailed("dns timeout") from None
        except OSError:
            raise FetchFailed("dns error") from None
        return check_resolved(list(found))

    def _get(self, parsed: ParsedUrl, addresses: list[str], deadline: float) -> TransportResponse:
        for ip in addresses:
            left = deadline - time.monotonic()
            if left <= 0:
                raise FetchFailed("timeout")
            try:
                return self.transport.request(parsed.host, ip, parsed.path, left, self.max_bytes)
            except Exception as exc:  # noqa: BLE001 - socket, TLS or transport error: next address
                log.debug("fetch connect failed: %s", type(exc).__name__)
        raise FetchFailed("connection failed")

    def fetch(self, url: str, timeout_s: float | None = None) -> Fetched:
        """Fetch ``url`` in at most ``timeout_s`` (and never more than the adapter's own limit)."""
        deadline = time.monotonic() + min(self.timeout_s, timeout_s or self.timeout_s)
        parsed = check_before_dns(url, self.allowlist)
        origin = parsed.host
        for _hop in range(self.max_redirects + 1):
            addresses = self._resolve(parsed.host, deadline - time.monotonic())
            resp = self._get(parsed, addresses, deadline)
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    raise FetchFailed("redirect without location")
                nxt = parse_url(urljoin(f"https://{parsed.host}{parsed.path}", location))
                if nxt.host != origin:
                    raise UrlRefused(SSRF_REFUSED, "redirect to another host")
                parsed = nxt
                continue
            if resp.status != 200:
                raise FetchFailed(f"http status {resp.status}")
            if resp.truncated:
                raise FetchFailed("too large")
            ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            return Fetched(resp.body, ctype)
        raise FetchFailed("too many redirects")
