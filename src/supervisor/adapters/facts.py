"""Fact sources built from settings (``FACT_SOURCE``, D13).

``FACT_SOURCE`` is ``<kind>:<target>``:

* empty (default)           no fact source: a rule that reads ``fact.<source>.<field>`` fails
                            closed, as before;
* ``callable:pkg.mod:name`` an importable factory ``name(settings) -> FactSource`` (the
                            existing in-process ``MappingFactSource`` is built this way);
* ``sqlite:/abs/file.db``   a SQLite file opened READ-ONLY, looked up with the queries in the
                            query map ``FACT_QUERY_MAP`` (YAML, below).

Query map (``FACT_QUERY_MAP``), one entry per fact source name used in the policy::

    sources:
      application:                       # rule path fact.application.<field>
        query: "SELECT documents_complete, status FROM applications WHERE application_id = ?"
        bool_fields: [documents_complete]   # 0/1 columns returned as true/false

The key is the tool argument ``<source>_id`` and is bound as the one ``?`` parameter: it is
never pasted into the SQL. The query must be one ``SELECT``; floats are not allowed by the
gateway (cast to an integer or text in the query). A database error, an unknown source or no
row all return None, which the gateway turns into a rule error (the rule's fail mode applies:
closed for money, credit and PII export).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from supervisor.core.errors import ConfigError
from supervisor.gateway.facts import FactSource

log = logging.getLogger("supervisor.facts")

KINDS = ("callable", "sqlite")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def split_fact_source(value: str) -> tuple[str, str]:
    """``("sqlite", "/abs/file.db")`` from ``sqlite:/abs/file.db``. Raises ValueError."""
    kind, sep, target = value.strip().partition(":")
    if not sep or kind not in KINDS or not target.strip():
        raise ValueError(
            f"FACT_SOURCE must be <kind>:<target> with kind one of {', '.join(KINDS)} "
            "(sqlite:/abs/path.db or callable:pkg.mod:factory), got "
            f"{value.split(':', 1)[0]!r}"
        )
    return kind, target.strip()


def load_query_map(path: Path) -> dict[str, dict[str, Any]]:
    """Validate the query map. Raises ConfigError with the problem (shown to the operator)."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"FACT_QUERY_MAP {path}: cannot read ({type(exc).__name__})") from exc
    sources = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(sources, dict) or not sources:
        raise ConfigError(f"FACT_QUERY_MAP {path}: needs a non-empty 'sources' mapping")
    out: dict[str, dict[str, Any]] = {}
    for name, spec in sources.items():
        if not isinstance(name, str) or not _NAME.match(name):
            raise ConfigError(f"FACT_QUERY_MAP: source name {name!r} must match {_NAME.pattern}")
        query = spec.get("query") if isinstance(spec, dict) else None
        if not isinstance(query, str) or not query.strip():
            raise ConfigError(f"FACT_QUERY_MAP: source {name!r} needs a 'query' string")
        q = query.strip().rstrip(";").strip()
        if not re.match(r"(?is)^select\s", q) or ";" in q or q.count("?") != 1:
            raise ConfigError(
                f"FACT_QUERY_MAP: source {name!r}: the query must be ONE SELECT with exactly "
                "one '?' for the key"
            )
        flags = spec.get("bool_fields", [])
        if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
            raise ConfigError(f"FACT_QUERY_MAP: source {name!r}: bool_fields must be a list")
        out[name] = {"query": q, "bool_fields": frozenset(flags)}
    return out


class SqliteFactSource:
    """``FactSource`` over a SQLite file opened read-only (``mode=ro`` and ``query_only``)."""

    def __init__(self, db_path: Path, queries: Mapping[str, Mapping[str, Any]]) -> None:
        path = Path(db_path)
        if not path.is_file():
            raise ConfigError(f"FACT_SOURCE sqlite file not found: {path}")
        self.queries = {k: dict(v) for k, v in queries.items()}
        uri = f"file:{quote(str(path.resolve()))}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=2.0)
        self._conn.execute("PRAGMA query_only = ON")
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def get(self, source: str, key: str) -> Mapping[str, Any] | None:
        spec = self.queries.get(source)
        if spec is None:
            return None
        try:
            with self._lock:
                row = self._conn.execute(spec["query"], (key,)).fetchone()
        except sqlite3.Error as exc:
            log.warning("fact source %s: %s", source, type(exc).__name__)
            return None
        if row is None:
            return None
        flags = spec["bool_fields"]
        return {
            k: (bool(row[k]) if k in flags and row[k] is not None else row[k]) for k in row.keys()
        }  # noqa: SIM118

    def close(self) -> None:
        self._conn.close()


def make_fact_source(settings: Any) -> FactSource | None:
    """The configured fact source, or None (the default: no fact source)."""
    spec = (settings.fact_source or "").strip()
    if not spec:
        return None
    kind, target = split_fact_source(spec)
    if kind == "sqlite":
        if settings.fact_query_map is None:
            raise ConfigError(
                "FACT_SOURCE=sqlite:... needs FACT_QUERY_MAP (see docs/fact-sources.md)"
            )
        return SqliteFactSource(Path(target), load_query_map(settings.fact_query_map))
    import importlib

    module, _, attr = target.partition(":")
    if not module or not attr:
        raise ConfigError("FACT_SOURCE=callable:<module>:<factory> needs both parts")
    try:
        factory = getattr(importlib.import_module(module), attr)
        source = factory(settings)
    except Exception as exc:  # noqa: BLE001 - shown to the operator at startup
        raise ConfigError(f"FACT_SOURCE callable {target}: {type(exc).__name__}: {exc}") from exc
    if not hasattr(source, "get"):
        raise ConfigError(f"FACT_SOURCE callable {target} did not return a FactSource")
    return source  # type: ignore[no-any-return]
