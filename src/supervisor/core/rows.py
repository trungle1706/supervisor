"""Row value helpers (audit D14)."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from supervisor.core.canonical import format_ts


def json_value(value: Any, default: Any) -> Any:
    """A JSON column as a Python value. None gives ``default``; a list or dict passes through;
    text is parsed; text that is not JSON (or any other type) gives ``default``."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def plain(value: Any) -> Any:
    """JSON-friendly copy: datetimes as RFC 3339 text, dates as ISO text, containers walked."""
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dt.datetime):
        return format_ts(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def rows_by(
    store: Any,
    table: str,
    key_col: str,
    keys: Iterable[Any],
    *,
    columns: Sequence[str] | None = None,
    where: Mapping[str, Any] | None = None,
    order_by: Sequence[str] = (),
    per_key_limit: int | None = None,
) -> dict[Any, list[dict[str, Any]]]:
    """The rows of many keys grouped by key, in few statements.

    Uses ``query_by`` of the SQL table store. A store without it (a test double) is read with one
    ``query`` per key, as the code did before. A key with no rows maps to an empty list.
    """
    uniq = list(dict.fromkeys(keys))
    batch = getattr(store, "query_by", None)
    if batch is not None:
        return batch(  # type: ignore[no-any-return]
            table,
            key_col,
            uniq,
            columns=columns,
            where=where,
            order_by=order_by,
            per_key_limit=per_key_limit,
        )
    out: dict[Any, list[dict[str, Any]]] = {}
    for k in uniq:
        rows = store.query(table, {**(where or {}), key_col: k}, order_by, per_key_limit)
        out[k] = [{c: r[c] for c in columns} for r in rows] if columns else list(rows)
    return out
