"""The connection of the URL fetch adapter (WP-D1): standard library only.

``HttpsTransport.request`` connects to an address that the guard already checked (so the name is
not resolved a second time: a DNS answer that changes between the check and the connection cannot
move the request inside), checks the certificate against the host name, sends one GET and reads at
most ``max_bytes``. It follows no redirect; the client does that, with the guard on every hop.
"""

from __future__ import annotations

import http.client
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: dict[str, str]  # lower case names
    body: bytes
    truncated: bool  # the body was longer than max_bytes


class Transport(Protocol):
    def request(
        self, host: str, ip: str, path: str, timeout_s: float, max_bytes: int
    ) -> TransportResponse: ...


class _Pinned(http.client.HTTPSConnection):
    """HTTPS to a fixed address; the certificate is checked for ``host``."""

    def __init__(self, host: str, ip: str, timeout_s: float, context: ssl.SSLContext) -> None:
        super().__init__(host, 443, timeout=timeout_s, context=context)
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class HttpsTransport:
    USER_AGENT = "supervisor-document-intake/1"

    def request(
        self, host: str, ip: str, path: str, timeout_s: float, max_bytes: int
    ) -> TransportResponse:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        conn = _Pinned(host, ip, timeout_s, context)
        deadline = time.monotonic() + timeout_s
        try:
            conn.request(
                "GET",
                path,
                headers={
                    "Host": host,
                    "User-Agent": self.USER_AGENT,
                    "Accept": "text/*, application/pdf, application/json, */*;q=0.1",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            resp = conn.getresponse()
            headers = {k.lower(): v for k, v in resp.getheaders()}
            chunks: list[bytes] = []
            size = 0
            truncated = False
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError
                chunk = resp.read(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    truncated = True
                    break
            body = b"".join(chunks)[:max_bytes]
            return TransportResponse(resp.status, headers, body, truncated)
        finally:
            conn.close()
