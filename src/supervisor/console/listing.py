"""Server-side paging and sorting for console list pages (WP-UX1).

Pure helpers, no I/O. A bad page number is a user error (HTTP 400 through the app handler),
never a 500; an unknown sort column falls back to the default (the column list is an allow-list,
so a query string can never pick an arbitrary field)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from supervisor.core.errors import SupervisorError

DEFAULT_SIZE = 25
MAX_SIZE = 100


class ListingError(SupervisorError):
    """Bad paging input (page out of range, not a number). HTTP 400."""


@dataclass(frozen=True)
class Page:
    items: list[Any]
    page: int  # 1-based
    pages: int  # at least 1
    total: int
    size: int

    @property
    def first(self) -> int:  # 1-based number of the first row shown, 0 when empty
        return 0 if self.total == 0 else (self.page - 1) * self.size + 1

    @property
    def last(self) -> int:
        return min(self.total, self.page * self.size)

    @property
    def prev(self) -> int | None:
        return self.page - 1 if self.page > 1 else None

    @property
    def next(self) -> int | None:
        return self.page + 1 if self.page < self.pages else None


def parse_int(raw: str | None, what: str, default: int, *, low: int = 1, high: int = 10**6) -> int:
    if raw in (None, ""):
        return default
    text = str(raw)
    if not (text.isascii() and text.isdigit() and len(text) < 8):
        raise ListingError(f"{what} must be a whole number")
    value = int(text)
    if not low <= value <= high:
        raise ListingError(f"{what} must be between {low} and {high}")
    return value


def paginate(rows: Sequence[Any], page: int = 1, size: int = DEFAULT_SIZE) -> Page:
    """One page of ``rows``. Page 1 of an empty list is valid; any other out-of-range page is
    a ListingError."""
    if size < 1 or size > MAX_SIZE:
        raise ListingError(f"page size must be between 1 and {MAX_SIZE}")
    total = len(rows)
    pages = max(1, math.ceil(total / size))
    if page < 1 or page > pages:
        raise ListingError(f"page {page} does not exist (1 to {pages})")
    start = (page - 1) * size
    return Page(list(rows[start : start + size]), page, pages, total, size)


def parse_sort(
    sort: str | None,
    direction: str | None,
    allowed: Iterable[str],
    default: str,
    default_dir: str = "asc",
) -> tuple[str, str]:
    """(column, 'asc'|'desc'). An unknown column gives the default column and direction; a
    known column with an unknown direction gives the default direction."""
    if sort not in tuple(allowed):
        return default, default_dir
    return str(sort), direction if direction in ("asc", "desc") else default_dir


def sort_rows(
    rows: Iterable[Mapping[str, Any]],
    column: str,
    direction: str,
    keys: Mapping[str, Callable[[Mapping[str, Any]], Any]] | None = None,
) -> list[Mapping[str, Any]]:
    """Stable sort by ``column``; ``keys`` maps a column to a key function (default: the field).
    Rows whose key is None go last in both directions."""
    key = (keys or {}).get(column) or (lambda r, c=column: r.get(c))
    items = list(rows)
    present = [r for r in items if key(r) is not None]
    absent = [r for r in items if key(r) is None]
    present.sort(key=key, reverse=direction == "desc")
    return present + absent


def query_string(params: Mapping[str, Any], **override: Any) -> str:
    """``a=1&b=2`` from the non-empty params with overrides applied (an override of None drops
    the key)."""
    merged = {**params, **override}
    return urlencode([(k, str(v)) for k, v in merged.items() if v not in (None, "")])
