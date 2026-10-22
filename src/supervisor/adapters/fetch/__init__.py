"""URL fetch adapter (WP-D1): the SSRF guard, the HTTPS transport and the fetcher."""

from supervisor.adapters.fetch.client import Fetched, Fetcher, FetchFailed
from supervisor.adapters.fetch.guard import (
    DOMAIN_BLOCKED,
    SSRF_REFUSED,
    UrlRefused,
    ip_is_public,
)

__all__ = [
    "DOMAIN_BLOCKED",
    "SSRF_REFUSED",
    "FetchFailed",
    "Fetched",
    "Fetcher",
    "UrlRefused",
    "ip_is_public",
]
