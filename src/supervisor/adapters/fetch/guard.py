"""SSRF guard for the URL fetch adapter (WP-D1). Pure functions, no network.

A URL is fetched only when all of these hold:

* the scheme is ``https``, the port is 443 (or absent), and there is no user name or password;
* the host is not an address that points inside: private, loopback, link-local (this includes the
  cloud metadata address 169.254.169.254), shared (CGNAT, 100.64.0.0/10, which holds the Alibaba
  metadata address), multicast, reserved or unspecified. An IPv6 address that wraps an IPv4 one
  (``::ffff:a.b.c.d``, 6to4, Teredo, NAT64) is checked as the IPv4 address it wraps;
* the host is on the allow list (the host itself, or a sub-domain of a listed domain);
* every address the name resolves to (checked AFTER the DNS answer) is public.

The code of a refusal is ``url.ssrf_refused`` (the address or the shape of the URL is unsafe) or
``url.domain_blocked`` (a safe URL whose domain is not listed).
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

SSRF_REFUSED = "url.ssrf_refused"
DOMAIN_BLOCKED = "url.domain_blocked"
MAX_URL_CHARS = 2048
_NUMERIC_HOST = re.compile(r"^[0-9a-fx.]+$", re.I)

Resolver = Callable[[str], Sequence[str]]


class UrlRefused(Exception):
    """The URL must not be fetched. ``code`` is SSRF_REFUSED or DOMAIN_BLOCKED; ``detail`` is a
    fixed short phrase (never part of the URL)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ParsedUrl:
    host: str  # lower case, ASCII (IDNA), no trailing dot
    port: int
    path: str  # path and query, starts with "/"


def _embedded_v4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    out: list[ipaddress.IPv4Address] = []
    if ip.ipv4_mapped is not None:
        out.append(ip.ipv4_mapped)
    if ip.sixtofour is not None:
        out.append(ip.sixtofour)
    if ip.teredo is not None:
        out.extend(ip.teredo)
    if ip in ipaddress.ip_network("64:ff9b::/96"):  # NAT64: the last 32 bits are an IPv4 address
        out.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return out


def ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for an address on the public internet."""
    if isinstance(ip, ipaddress.IPv6Address):
        wrapped = _embedded_v4(ip)
        if wrapped:  # judged as the IPv4 address(es) it wraps
            return all(ip_is_public(v4) for v4 in wrapped)
    return bool(ip.is_global) and not (
        ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved
    )


def parse_ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address a host string stands for, or None when it is a name. Also reads the odd IPv4
    spellings (``2130706433``, ``0x7f.1``, ``127.1``) that a resolver would accept."""
    try:
        return ipaddress.ip_address(text.strip("[]"))
    except ValueError:
        pass
    if _NUMERIC_HOST.match(text):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(text))
        except OSError:
            return None
    return None


def parse_url(url: str) -> ParsedUrl:
    """Split and check the shape of a URL. Raises ``UrlRefused(SSRF_REFUSED)``."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS or not url.isprintable():
        raise UrlRefused(SSRF_REFUSED, "bad url")
    try:
        parts = urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise UrlRefused(SSRF_REFUSED, "bad url") from None
    if parts.scheme.lower() != "https":
        raise UrlRefused(SSRF_REFUSED, "https only")
    if parts.username is not None or parts.password is not None:
        raise UrlRefused(SSRF_REFUSED, "credentials in url")
    if not host:
        raise UrlRefused(SSRF_REFUSED, "no host")
    if port not in (None, 443):
        raise UrlRefused(SSRF_REFUSED, "port other than 443")
    host = host.rstrip(".").lower()
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise UrlRefused(SSRF_REFUSED, "bad host") from None
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return ParsedUrl(host, 443, path)


def domain_listed(host: str, allowlist: Iterable[str]) -> bool:
    """The host is a listed domain or a sub-domain of one."""
    return any(host == d or host.endswith("." + d) for d in allowlist)


def check_before_dns(url: str, allowlist: Iterable[str]) -> ParsedUrl:
    """Everything that can be decided without a DNS answer. A literal address that points inside
    is refused even when the domain is not listed (a probe is reported as a probe)."""
    parsed = parse_url(url)
    literal = parse_ip(parsed.host)
    if literal is not None and not ip_is_public(literal):
        raise UrlRefused(SSRF_REFUSED, "address points inside")
    if parsed.host == "localhost" or parsed.host.endswith((".localhost", ".local", ".internal")):
        raise UrlRefused(SSRF_REFUSED, "local name")
    if not domain_listed(parsed.host, allowlist):
        raise UrlRefused(DOMAIN_BLOCKED, "domain not in the allow list")
    return parsed


def check_resolved(addresses: Sequence[str]) -> list[str]:
    """The addresses a name resolved to. Every one must be public, or the fetch is refused (a
    name with one public and one private address is a rebinding trick). Returns them."""
    if not addresses:
        raise UrlRefused(SSRF_REFUSED, "name did not resolve")
    for text in addresses:
        ip = parse_ip(text)
        if ip is None or not ip_is_public(ip):
            raise UrlRefused(SSRF_REFUSED, "name resolves to an address inside")
    return list(dict.fromkeys(addresses))


def system_resolver(host: str) -> list[str]:
    """The addresses of ``host`` from the system resolver (the only DNS call of the adapter)."""
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return [str(i[4][0]).split("%", 1)[0] for i in infos]
