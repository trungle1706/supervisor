"""FakeStatementExecution: a recorded stand-in for ``WorkspaceClient.statement_execution``.

Responses are plain dicts in the REST API JSON shape (as returned by
``POST /api/2.0/sql/statements``) and are parsed with the SDK's own ``from_dict``,
so the adapter code under test sees real SDK objects. Used by unit tests here;
the live test kit (RUN_DATABRICKS=1) uses the real client.
"""

from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from databricks.sdk.service.sql import ResultData, StatementResponse

_ids = itertools.count(1)


@dataclass
class Script:
    """Responses for one statement: first from execute, the rest from polling."""

    match: str | None
    responses: list[dict[str, Any]]
    chunks: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass
class Call:
    method: str
    kwargs: dict[str, Any]


class FakeStatementExecution:
    def __init__(self) -> None:
        self._scripts: deque[Script] = deque()
        self._live: dict[str, Script] = {}
        self.calls: list[Call] = []
        self.cancelled: list[str] = []

    # -------------------------------------------------------------- scripting
    def add(
        self,
        responses: dict[str, Any] | list[dict[str, Any]],
        *,
        match: str | None = None,
        chunks: dict[int, dict[str, Any]] | None = None,
    ) -> FakeStatementExecution:
        if isinstance(responses, dict):
            responses = [responses]
        self._scripts.append(Script(match, list(responses), dict(chunks or {})))
        return self

    def add_rows(
        self,
        columns: list[tuple[str, str]],
        rows: list[list[str | None]],
        *,
        chunk_size: int = 0,
        match: str | None = None,
        pending_polls: int = 0,
    ) -> FakeStatementExecution:
        final, chunks = succeeded(columns, rows, chunk_size=chunk_size)
        self.add([pending()] * pending_polls + [final], match=match, chunks=chunks)
        return self

    # -------------------------------------------------------------- SDK API
    def execute_statement(
        self, statement: str, warehouse_id: str, **kwargs: Any
    ) -> StatementResponse:
        self.calls.append(
            Call(
                "execute_statement",
                {"statement": statement, "warehouse_id": warehouse_id, **kwargs},
            )
        )
        script = self._take(statement)
        sid = f"fake-{next(_ids):04d}"
        self._live[sid] = script
        return self._next(sid)

    def get_statement(self, statement_id: str) -> StatementResponse:
        self.calls.append(Call("get_statement", {"statement_id": statement_id}))
        return self._next(statement_id)

    def get_statement_result_chunk_n(self, statement_id: str, chunk_index: int) -> ResultData:
        self.calls.append(
            Call(
                "get_statement_result_chunk_n",
                {"statement_id": statement_id, "chunk_index": chunk_index},
            )
        )
        return ResultData.from_dict(self._live[statement_id].chunks[chunk_index])

    def cancel_execution(self, statement_id: str) -> None:
        self.calls.append(Call("cancel_execution", {"statement_id": statement_id}))
        self.cancelled.append(statement_id)

    # -------------------------------------------------------------- internals
    def _take(self, statement: str) -> Script:
        for i, s in enumerate(self._scripts):
            if s.match is None or s.match in statement:
                del self._scripts[i]
                return s
        raise AssertionError(f"FakeStatementExecution: no scripted response for: {statement[:120]}")

    def _next(self, sid: str) -> StatementResponse:
        script = self._live[sid]
        body = script.responses.pop(0) if len(script.responses) > 1 else script.responses[0]
        return StatementResponse.from_dict({**body, "statement_id": sid})

    @property
    def statements(self) -> list[str]:
        return [c.kwargs["statement"] for c in self.calls if c.method == "execute_statement"]

    def remaining(self) -> int:
        return len(self._scripts)


# ------------------------------------------------------------------ builders


def pending(state: str = "RUNNING") -> dict[str, Any]:
    return {"status": {"state": state}}


def failed(message: str, sql_state: str | None = None, state: str = "FAILED") -> dict[str, Any]:
    status: dict[str, Any] = {
        "state": state,
        "error": {"message": message, "error_code": "BAD_REQUEST"},
    }
    if sql_state:
        status["sql_state"] = sql_state
    return {"status": status}


def succeeded(
    columns: list[tuple[str, str]], rows: list[list[str | None]], *, chunk_size: int = 0
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """Return (final response, extra chunks by index). All values must be strings or None."""
    for r in rows:
        for v in r:
            assert v is None or isinstance(v, str), "the REST API returns strings only"
    size = chunk_size or max(len(rows), 1)
    parts = [rows[i : i + size] for i in range(0, len(rows), size)] or [[]]
    chunk_dicts = []
    offset = 0
    for idx, part in enumerate(parts):
        d: dict[str, Any] = {
            "chunk_index": idx,
            "row_offset": offset,
            "row_count": len(part),
            "data_array": part,
        }
        if idx + 1 < len(parts):
            d["next_chunk_index"] = idx + 1
        chunk_dicts.append(d)
        offset += len(part)
    manifest = {
        "format": "JSON_ARRAY",
        "schema": {
            "column_count": len(columns),
            "columns": [
                {"name": n, "type_name": t, "type_text": t, "position": i}
                for i, (n, t) in enumerate(columns)
            ],
        },
        "total_chunk_count": len(parts),
        "total_row_count": len(rows),
        "chunks": [
            {
                "chunk_index": c["chunk_index"],
                "row_offset": c["row_offset"],
                "row_count": c["row_count"],
            }
            for c in chunk_dicts
        ],
    }
    final = {"status": {"state": "SUCCEEDED"}, "manifest": manifest, "result": chunk_dicts[0]}
    return final, {c["chunk_index"]: c for c in chunk_dicts[1:]}


def dml_result(affected: int) -> dict[str, Any]:
    final, _ = succeeded(
        [("num_affected_rows", "LONG"), ("num_inserted_rows", "LONG")],
        [[str(affected), str(affected)]],
    )
    return final
