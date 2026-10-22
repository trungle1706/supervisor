"""``WorkspaceReader`` from a JSON fixture (offline laptop, tests, demos).

Fixture layout (all keys optional)::

    {
      "apps": [{"name": "...", "url": "...", "description": "..."}],
      "serving_endpoints": [{"name": "...", "model": "...", "family": "...", "task": "..."}],
      "registered_models": [{"name": "catalog.schema.model", "owner": "..."}],
      "tables": {"catalog.schema": ["table_a", "table_b"]},
      "model_versions": [{"model": "cat.sch.m", "version": "3", "aliases": ["champion"]}],
      "genie_spaces": [{"name": "Credit Q&A", "tables": ["cat.sch.t"]}],
      "jobs": [{"name": "nightly", "tasks": [{"key": "t1", "kind": "notebook", "values": ["ep"]}]}],
      "vector_indexes": [{"name": "cat.sch.idx", "source_table": "cat.sch.t"}],
      "functions": {"catalog.schema": ["catalog.schema.fn"]},
      "connections": [{"name": "mcp_conn", "type": "HTTP", "mcp": true}],
      "lineage": [{"agent": "payments", "table": "cat.sch.t", "direction": "read"}],
      "traces": [{"agent": "payments", "source": "mlflow", "count": 120}]
    }

Fixture values are untrusted text like repo text; Discover scrubs them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MAX_FIXTURE_BYTES = 2_000_000


class FixtureWorkspaceReader:
    """Implements ``core.ports.WorkspaceReader`` (plus apps, lineage and traces)."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        if not isinstance(data, Mapping):
            raise ValueError("workspace fixture must be a JSON object")
        self.data = dict(data)

    @classmethod
    def from_file(cls, path: str | Path) -> FixtureWorkspaceReader:
        p = Path(path)
        if p.stat().st_size > MAX_FIXTURE_BYTES:
            raise ValueError(f"{p.name}: fixture larger than {MAX_FIXTURE_BYTES} bytes")
        return cls(json.loads(p.read_text(encoding="utf-8")))

    @classmethod
    def empty(cls) -> FixtureWorkspaceReader:
        return cls({})

    def list_apps(self) -> Sequence[Mapping[str, Any]]:
        return [dict(a) for a in self.data.get("apps", [])]

    def list_serving_endpoints(self) -> Sequence[Mapping[str, Any]]:
        return [dict(e) for e in self.data.get("serving_endpoints", [])]

    def list_registered_models(self) -> Sequence[Mapping[str, Any]]:
        return [dict(m) for m in self.data.get("registered_models", [])]

    def list_tables(self, catalog: str, schema: str) -> Sequence[str]:
        return sorted(str(t) for t in self.data.get("tables", {}).get(f"{catalog}.{schema}", []))

    def list_schemas(self) -> Sequence[str]:
        return sorted(self.data.get("tables", {}))

    def lineage(self) -> Sequence[Mapping[str, Any]]:
        return [dict(x) for x in self.data.get("lineage", [])]

    def traces(self) -> Sequence[Mapping[str, Any]]:
        return [dict(x) for x in self.data.get("traces", [])]

    # WP-G3 scan sources v2 (same shapes as DatabricksWorkspaceReader)
    def list_model_versions(self) -> list[dict[str, Any]]:
        return [dict(x) for x in self.data.get("model_versions", [])]

    def list_genie_spaces(self) -> list[dict[str, Any]]:
        return [dict(x) for x in self.data.get("genie_spaces", [])]

    def list_jobs(self) -> list[dict[str, Any]]:
        return [dict(x) for x in self.data.get("jobs", [])]

    def list_vector_indexes(self) -> list[dict[str, Any]]:
        return [dict(x) for x in self.data.get("vector_indexes", [])]

    def list_functions(self, catalog: str, schema: str) -> list[str]:
        return sorted(str(f) for f in self.data.get("functions", {}).get(f"{catalog}.{schema}", []))

    def list_connections(self) -> list[dict[str, Any]]:
        return [dict(x) for x in self.data.get("connections", [])]
