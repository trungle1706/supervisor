"""WP-D1: the URL fetch adapter and its SSRF guard. A fake transport and a fake resolver; no socket
is opened (the fixture no_network of tests/conftest.py makes a real DNS or connect call fail)."""

from __future__ import annotations

import ipaddress
import socket
import ssl
import threading
import time
from typing import Any

import pytest

from supervisor.adapters.fetch import Fetcher, FetchFailed, UrlRefused, guard, ip_is_public
from supervisor.adapters.fetch import transport as transport_mod
from supervisor.adapters.fetch.transport import HttpsTransport, TransportResponse

pytestmark = pytest.mark.usefixtures("no_network")  # tests/conftest.py


class FakeTransport:
    def __init__(self, *responses: TransportResponse | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, str]] = []

    def request(
        self, host: str, ip: str, path: str, timeout_s: float, max_bytes: int
    ) -> TransportResponse:
        self.calls.append((host, ip, path))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def page(body: bytes = b"hello", ctype: str = "text/html; charset=utf-8", **kw: Any) -> Any:
    return TransportResponse(200, {"content-type": ctype}, body, kw.get("truncated", False))


def redirect(to: str, status: int = 302) -> Any:
    return TransportResponse(status, {"location": to}, b"", False)


def fetcher(*responses: Any, resolver: Any = None, **kw: Any) -> tuple[Fetcher, FakeTransport]:
    t = FakeTransport(*responses)
    f = Fetcher(
        ["example.com"], transport=t, resolver=resolver or (lambda h: ["93.184.216.34"]), **kw
    )
    return f, t


# ---------------------------------------------------------------------------- the guard


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.1",
        "169.254.169.254",  # AWS, GCP and Azure metadata
        "100.100.100.200",  # Alibaba metadata (shared address space)
        "0.0.0.0",  # noqa: S104 - a literal in a test list
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "fe80::1",
        "fd00:ec2::254",  # AWS IPv6 metadata
        "fec0::1",  # deprecated site-local
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "64:ff9b::7f00:1",  # NAT64 around 127.0.0.1
        "2002:7f00:1::",  # 6to4 around 127.0.0.1
    ],
)
def test_internal_addresses_are_not_public(ip: str) -> None:
    assert ip_is_public(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946"])
def test_public_addresses_are_public(ip: str) -> None:
    assert ip_is_public(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize(
    ("url", "detail"),
    [
        ("http://example.com/", "https only"),
        ("ftp://example.com/", "https only"),
        ("file:///etc/passwd", "https only"),
        ("https://user:pw@example.com/", "credentials in url"),
        ("https://example.com:8443/", "port other than 443"),
        ("https:///path", "no host"),
        ("", "bad url"),
        ("https://exa mple.com/", "bad url"),
    ],
)
def test_shape_of_the_url(url: str, detail: str) -> None:
    with pytest.raises(UrlRefused) as e:
        guard.parse_url(url)
    assert e.value.code == guard.SSRF_REFUSED and e.value.detail == detail


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://2130706433/",  # decimal 127.0.0.1
        "https://0x7f.1/",
        "https://127.1/",
        "https://[::1]/",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.0.0.5/admin",
        "https://[::ffff:127.0.0.1]/",
        "https://localhost/",
        "https://app.localhost/",
        "https://db.internal/",
        "https://printer.local/",
    ],
)
def test_a_literal_or_local_host_is_an_ssrf_refusal_even_off_the_list(url: str) -> None:
    f, t = fetcher()
    with pytest.raises(UrlRefused) as e:
        f.fetch(url)
    assert e.value.code == guard.SSRF_REFUSED
    assert t.calls == []  # nothing was sent


def test_a_domain_not_in_the_list_is_blocked_and_a_subdomain_is_allowed() -> None:
    f, t = fetcher(page())
    with pytest.raises(UrlRefused) as e:
        f.fetch("https://evil.test/x")
    assert e.value.code == guard.DOMAIN_BLOCKED
    with pytest.raises(UrlRefused):
        f.fetch("https://notexample.com/")  # a suffix match must be on a dot
    assert f.fetch("https://docs.EXAMPLE.com/a?b=1").data == b"hello"
    assert t.calls == [("docs.example.com", "93.184.216.34", "/a?b=1")]


# ---------------------------------------------------------------------------- DNS


def test_a_name_that_resolves_inside_is_refused_after_dns() -> None:
    for answer in (["10.0.0.7"], ["127.0.0.1"], ["169.254.169.254"], ["::1"]):
        f, t = fetcher(page(), resolver=lambda h, a=answer: a)
        with pytest.raises(UrlRefused) as e:
            f.fetch("https://example.com/")
        assert e.value.code == guard.SSRF_REFUSED and t.calls == []


def test_one_private_address_among_public_ones_refuses_the_name() -> None:
    f, t = fetcher(page(), resolver=lambda h: ["93.184.216.34", "10.0.0.7"])
    with pytest.raises(UrlRefused):
        f.fetch("https://example.com/")
    assert t.calls == []


def test_the_connection_goes_to_the_address_that_was_checked() -> None:
    answers = iter([["93.184.216.34"], ["10.0.0.7"]])  # a rebinding resolver
    f, t = fetcher(page(), resolver=lambda h: next(answers))
    assert f.fetch("https://example.com/").data == b"hello"
    assert t.calls[0][1] == "93.184.216.34"  # not resolved a second time


def test_a_dns_error_and_a_dns_timeout_are_failed_fetches_not_crashes() -> None:
    def oserror(host: str) -> list[str]:
        raise OSError("no such host")

    f, _ = fetcher(page(), resolver=oserror)
    with pytest.raises(FetchFailed) as e:
        f.fetch("https://example.com/")
    assert e.value.reason == "dns error"

    def slow(host: str) -> list[str]:
        time.sleep(0.6)
        return ["93.184.216.34"]

    f, _ = fetcher(page(), resolver=slow, timeout_s=0.1)
    with pytest.raises(FetchFailed) as e:
        f.fetch("https://example.com/")
    assert e.value.reason == "dns timeout"


# ---------------------------------------------------------------------------- the response


def test_content_type_and_body_come_back() -> None:
    f, _ = fetcher(page(b"%PDF-1.4", "Application/PDF; x=y"))
    got = f.fetch("https://example.com/a.pdf")
    assert got.media_type == "application/pdf" and got.data == b"%PDF-1.4"


def test_a_redirect_to_the_same_host_is_followed_and_checked_again() -> None:
    f, t = fetcher(redirect("/next"), redirect("https://example.com/final"), page(b"done"))
    assert f.fetch("https://example.com/start").data == b"done"
    assert [c[2] for c in t.calls] == ["/start", "/next", "/final"]


@pytest.mark.parametrize(
    "to",
    [
        "https://evil.test/",
        "https://sub.example.com/",
        "http://example.com/x",
        "https://127.0.0.1/",
    ],
)
def test_a_redirect_to_another_host_or_to_http_is_refused(to: str) -> None:
    f, t = fetcher(redirect(to), page())
    with pytest.raises(UrlRefused) as e:
        f.fetch("https://example.com/start")
    assert e.value.code == guard.SSRF_REFUSED
    assert len(t.calls) == 1  # the second request was never sent


def test_too_many_redirects_and_a_redirect_without_location() -> None:
    f, _ = fetcher(*[redirect("/a")] * 5)
    with pytest.raises(FetchFailed) as e:
        f.fetch("https://example.com/")
    assert e.value.reason == "too many redirects"
    f, _ = fetcher(TransportResponse(302, {}, b"", False))
    with pytest.raises(FetchFailed) as e:
        f.fetch("https://example.com/")
    assert e.value.reason == "redirect without location"


def test_error_status_cap_and_connection_failures() -> None:
    f, _ = fetcher(TransportResponse(404, {}, b"", False))
    with pytest.raises(FetchFailed) as e:
        f.fetch("https://example.com/")
    assert e.value.reason == "http status 404"
    f, _ = fetcher(page(b"x" * 10, truncated=True))
    with pytest.raises(FetchFailed) as e:
        f.fetch("https://example.com/")
    assert e.value.reason == "too large"
    f, t = fetcher(
        TimeoutError(), OSError("reset"), resolver=lambda h: ["93.184.216.34", "93.184.216.35"]
    )
    with pytest.raises(FetchFailed) as e:
        f.fetch("https://example.com/")
    assert e.value.reason == "connection failed" and len(t.calls) == 2  # tried both addresses


def test_the_second_address_is_used_when_the_first_fails() -> None:
    f, t = fetcher(
        OSError("down"), page(b"ok"), resolver=lambda h: ["93.184.216.34", "93.184.216.35"]
    )
    assert f.fetch("https://example.com/").data == b"ok"
    assert [c[1] for c in t.calls] == ["93.184.216.34", "93.184.216.35"]


def test_the_defaults_are_the_documented_limits() -> None:
    f = Fetcher(["example.com"])
    assert f.max_bytes == 1024 * 1024 and f.timeout_s == 3.0 and f.max_redirects == 3
    assert Fetcher([]).enabled is False and f.enabled is True


# ---------------------------------------------------------------------------- the real transport


def test_the_real_transport_connects_to_the_given_address_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[Any, ...]] = []

    def fake_connect(addr: tuple[str, int], timeout: float) -> Any:
        seen.append(addr)
        raise OSError("refused")

    monkeypatch.setattr(socket, "create_connection", fake_connect)
    with pytest.raises(OSError, match="refused"):
        HttpsTransport().request("example.com", "93.184.216.34", "/", 1.0, 1000)
    assert seen == [("93.184.216.34", 443)]  # the address, never the name


# ---------------------------------------------------------------------------- review fixes


def test_fullwidth_host_letters_normalise_to_the_listed_domain_and_are_fetched_as_such() -> None:
    f, t = fetcher(page())
    assert f.fetch("https://ｄocs.example.com/a").data == b"hello"  # fullwidth "d"
    assert t.calls == [
        ("docs.example.com", "93.184.216.34", "/a")
    ]  # the ASCII name goes on the wire
    with pytest.raises(UrlRefused) as e:  # a different name stays blocked
        f.fetch("https://ｅvil.test/")
    assert e.value.code == guard.DOMAIN_BLOCKED


def test_a_non_ascii_path_and_query_are_percent_encoded() -> None:
    p = guard.parse_url("https://docs.example.com/tài-liệu/hồ-sơ.pdf?q=Việt&x=1")
    assert p.path == "/t%C3%A0i-li%E1%BB%87u/h%E1%BB%93-s%C6%A1.pdf?q=Vi%E1%BB%87t&x=1"
    assert p.path.isascii()
    assert guard.parse_url("https://docs.example.com/a%20b?c=%C3%A0").path == "/a%20b?c=%C3%A0"


def _drip_server(sock: socket.socket, first: bytes, lines: int, gap: float) -> threading.Thread:
    def run() -> None:
        try:
            sock.recv(65536)
            sock.sendall(first)
            for i in range(lines):
                time.sleep(gap)
                sock.sendall(f"X-Pad-{i}: v\r\n".encode())
        except OSError:
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


class _SocketPairTransport(HttpsTransport):
    """The real request code over a socketpair instead of TLS."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def _connection(self, host: str, ip: str, timeout_s: float, deadline: float) -> Any:
        conn = transport_mod._Pinned(host, ip, timeout_s, ssl.create_default_context(), deadline)
        conn.sock = transport_mod._DeadlineSock(self._sock, deadline)  # type: ignore[assignment]
        return conn


def test_a_server_that_drips_one_header_line_at_a_time_is_cut_at_the_deadline() -> None:
    client, server = socket.socketpair()
    _drip_server(server, b"HTTP/1.1 200 OK\r\n", lines=60, gap=0.1)  # would last 6 s
    t0 = time.monotonic()
    with pytest.raises((TimeoutError, OSError)):
        _SocketPairTransport(client).request("example.com", "93.184.216.34", "/", 0.6, 1000)
    assert time.monotonic() - t0 < 1.2
    server.close()


def test_response_headers_over_the_cap_are_refused() -> None:
    client, server = socket.socketpair()
    big = b"HTTP/1.1 200 OK\r\n" + b"".join(
        b"X-Pad-%d: %s\r\n" % (i, b"v" * 300) for i in range(95)
    )
    _drip_server(server, big, lines=0, gap=0)
    with pytest.raises(OSError, match="headers too large"):
        _SocketPairTransport(client).request("example.com", "93.184.216.34", "/", 2.0, 1000)
    server.close()


def test_a_normal_response_over_the_socketpair_is_read() -> None:
    client, server = socket.socketpair()
    body = b"<p>hello</p>"
    head = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: %d\r\n\r\n" % len(body)
    _drip_server(server, head + body, lines=0, gap=0)
    got = _SocketPairTransport(client).request("example.com", "93.184.216.34", "/", 2.0, 1000)
    assert got.status == 200 and got.body == body and got.headers["content-type"] == "text/html"
    server.close()
