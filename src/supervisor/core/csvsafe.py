"""CSV export helpers (audit D8). One formula-injection rule for every export."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Any

# A spreadsheet reads a cell that starts with one of these as a formula.
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: Any, *, flatten_controls: bool = False) -> str:
    """Text of one cell that is safe to open in a spreadsheet.

    None becomes empty text. A cell that starts with ``= + - @ TAB CR`` gets a leading quote.
    With ``flatten_controls`` every control character (code below 32, and 127) becomes a space
    first; the formula test is made on the text before that change.
    """
    text = "" if value is None else str(value)
    lead = "'" if text[:1] in FORMULA_STARTS else ""
    if flatten_controls:
        text = "".join(" " if (ord(c) < 32 or ord(c) == 127) else c for c in text)
    return lead + text


def write_csv(
    header: Sequence[Any],
    rows: Iterable[Sequence[Any]],
    eol: str = "\n",
    *,
    flatten_controls: bool = False,
) -> str:
    """CSV text: the header as it is, every body cell through ``csv_cell``."""
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator=eol)
    w.writerow(header)
    for row in rows:
        w.writerow([csv_cell(v, flatten_controls=flatten_controls) for v in row])
    return buf.getvalue()
