"""UX5 list helpers (CONSOLE_UX5): bound a list, page it, fold identical rows.

Pure functions; page packages call them in the view code and hand the result to the macros in
``templates/_ux5.html``. See docs/console-ux5.md."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from typing import Any, TypeVar

T = TypeVar("T")

PAGE_SIZE = 25


def top(rows: Sequence[T], n: int = 5) -> list[T]:
    """The first ``n`` rows of a summary list (n clamped to >= 0)."""
    return list(rows[: max(0, int(n))])


def page_slice(rows: Sequence[T], page: Any = 1, size: int = PAGE_SIZE) -> tuple[list[T], int, int]:
    """``(rows_on_page, page, pages)``. ``page`` comes straight from the query string: junk or
    out-of-range values are clamped to ``1..pages``. An empty list is one empty page."""
    size = max(1, int(size))
    pages = max(1, -(-len(rows) // size))
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    p = min(max(p, 1), pages)
    return list(rows[(p - 1) * size : p * size]), p, pages


def fold_identical(
    rows: Sequence[T], key: Callable[[T], Hashable], min_run: int = 3
) -> list[tuple[str, Any]]:
    """Collapse runs of rows with an equal ``key`` into ``("fold", (n, first_row))`` entries.

    Runs shorter than ``min_run`` stay as ``("row", row)``. Order is kept. Use for "153 agents:
    no findings" style lines (the macro ``fold(n, text)`` draws the fold)."""
    out: list[tuple[str, Any]] = []
    i = 0
    while i < len(rows):
        j = i + 1
        k = key(rows[i])
        while j < len(rows) and key(rows[j]) == k:
            j += 1
        if j - i >= min_run:
            out.append(("fold", (j - i, rows[i])))
        else:
            out.extend(("row", r) for r in rows[i:j])
        i = j
    return out
