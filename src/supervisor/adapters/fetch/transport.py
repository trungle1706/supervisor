"""The connection of the URL fetch adapter (WP-D1): standard library only.

``HttpsTransport.request`` connects to an address that the guard already checked (so the name is
not resolved a second time: a DNS answer that changes between the check and the connection cannot
move the request inside), checks the certificate against the host name, sends one GET and reads at
most ``max_bytes``. It follows no redirect; the client does that, with the guard on every hop.
"""

from __future__ import annotations

import http.client
import io
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Protocol


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


HEADER_CAP_BYTES = 16 * 1024  # response headers: at most this much (plus one buffered read)
_READ_CHUNK = 8192


class _DeadlineRaw(io.RawIOBase):
    """Reads a socket with the time left before EVERY read, so a server that sends one byte or
    one header line at a time cannot keep the request alive past the deadline. Before the headers
    are complete it also stops after HEADER_CAP_BYTES."""

    def __init__(self, sock: socket.socket, deadline: float) -> None:
        super().__init__()
        self._sock = sock
        self._deadline = deadline
        self._total = 0
        self.headers_done = False

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        left = self._deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("deadline")
        self._sock.settimeout(left)
        n = self._sock.recv_into(buffer)
        self._total += n
        if not self.headers_done and self._total > HEADER_CAP_BYTES + _READ_CHUNK:
            raise OSError("response headers too large")
        return n


class _DeadlineSock:
    """The socket http.client sees: sends and reads obey one deadline."""

    def __init__(self, sock: socket.socket, deadline: float) -> None:
        self._sock = sock
        self._deadline = deadline
        self.raw: _DeadlineRaw | None = None

    def sendall(self, data: Any) -> None:
        left = self._deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("deadline")
        self._sock.settimeout(left)
        self._sock.sendall(data)

    def makefile(self, mode: str = "rb", buffering: int | None = None, **kw: Any) -> Any:
        self.raw = _DeadlineRaw(self._sock, self._deadline)
        return io.BufferedReader(self.raw, _READ_CHUNK)

    def close(self) -> None:
        self._sock.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sock, name)


class _Pinned(http.client.HTTPSConnection):
    """HTTPS to a fixed address; the certificate is checked for ``host``."""

    def __init__(
        self, host: str, ip: str, timeout_s: float, context: ssl.SSLContext, deadline: float
    ) -> None:
        super().__init__(host, 443, timeout=timeout_s, context=context)
        self._ip = ip
        self._deadline = deadline

    def connect(self) -> None:
        left = max(0.05, self._deadline - time.monotonic())
        sock = socket.create_connection((self._ip, 443), left)
        sock.settimeout(max(0.05, self._deadline - time.monotonic()))
        tls = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]
        self.sock = _DeadlineSock(tls, self._deadline)  # type: ignore[assignment]


class HttpsTransport:
    USER_AGENT = "supervisor-document-intake/1"

    def _connection(self, host: str, ip: str, timeout_s: float, deadline: float) -> _Pinned:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return _Pinned(host, ip, timeout_s, context, deadline)

    def request(
        self, host: str, ip: str, path: str, timeout_s: float, max_bytes: int
    ) -> TransportResponse:
        deadline = time.monotonic() + timeout_s
        conn = self._connection(host, ip, timeout_s, deadline)
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
            raw = getattr(conn.sock, "raw", None)
            if raw is not None:
                raw.headers_done = True
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
