"""WP-UX3 read models on the Delta path (databricks_fake) give the same answers as on SQLite.

The fake cannot run SQL. ``MirrorFake`` answers each statement the store sends by running the
same statement (backticks and the catalog prefix removed) on the SQLite test store and returning
the rows as strings, as the Statement Execution API does. So the read models run through the
real ``DatabricksRestExecutor`` and ``SqlTableStore`` / ``SqlStateStore`` code, with Delta-dialect
statements and string-typed results, and the answers must equal the SQLite answers."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from databricks.sdk.service.sql import StatementResponse

from supervisor.adapters.sql.databricks_fake import FakeStatementExecution, succeeded
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.console import (
    audit_view,
    credentials_view,
    decisions,
    integrations_view,
    nav,
    policies_view,
    traces,
)
from supervisor.core.schema import load_model

from .conftest import Console
from .test_ux3_more import _event, _verdict


def _s(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, dt.datetime):
        return v.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(v)


class MirrorFake(FakeStatementExecution):
    """Answers a statement from the SQLite store behind ``inner`` (an SqlExecutor)."""

    def __init__(self, inner: Any) -> None:
        super().__init__()
        self.inner = inner

    def execute_statement(self, statement: str, warehouse_id: str, **kwargs: Any) -> Any:
        from supervisor.adapters.sql.databricks_fake import Call

        self.calls.append(Call("execute_statement", {"statement": statement, **kwargs}))
        sql = statement.replace("`c`.`s`.", "").replace("`", '"')
        params = {p.name: p.value for p in (kwargs.get("parameters") or [])}
        rows = self.inner.query(sql, params)
        names = list(rows[0]) if rows else self._columns(sql)
        final, _ = succeeded(
            [(n, "STRING") for n in names], [[_s(r[n]) for n in names] for r in rows]
        )
        return StatementResponse.from_dict({**final, "statement_id": f"mirror-{uuid.uuid4().hex}"})

    @staticmethod
    def _columns(sql: str) -> list[str]:
        m = re.match(r"SELECT (.+?) FROM", sql)
        return [c.strip() for c in m.group(1).split(",")] if m else []


@pytest.fixture
def pair(console: Console, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, MirrorFake]:
    for flag in nav.PAGES.values():
        monkeypatch.setattr(console.ctx.settings, flag, True)
    # something in every table the pages read: a small trace with a stop, a judge verdict
    t = "trace-delta"
    _event(console, t, "p1", None, "message", args="hello")
    tc = _event(console, t, "p2", "p1", "tool_call", tool="transfer", args="x")
    gate = _event(console, t, "p3", "p2", "gate_decision", tool="transfer", classification="block")
    _verdict(console, t, gate)
    _verdict(console, t, tc, tier=1, checker="judge:t1", action="log", advisory=True, mock=True)
    console.get("/console/")
    sqlite_ctx = console.ctx
    fake = MirrorFake(sqlite_ctx.runtime.adapters.executor)
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    model = load_model()
    delta_ctx = SimpleNamespace(
        settings=sqlite_ctx.settings,
        clock=sqlite_ctx.clock,
        tables=SqlTableStore(ex, model),
        state=SqlStateStore(ex, sqlite_ctx.clock, model),
        provider=sqlite_ctx.provider,
        gateway=sqlite_ctx.gateway,
    )
    return sqlite_ctx, delta_ctx, fake


def _strip(view: dict[str, Any]) -> dict[str, Any]:
    page = view["page"]
    return {
        "items": page.items,
        "total": page.total,
        "tiles": view.get("tiles"),
        "sort": (view["sort_col"], view["sort_dir"]),
    }


def test_decisions_equal_on_both_backends(pair: Any) -> None:
    sq, de, fake = pair
    for query in (
        {},
        {"action": "block"},
        {"agent": "payments", "sort": "action"},
        {"rule": "PAY-07"},
    ):
        a, b = decisions.list_view(sq, query), decisions.list_view(de, query)
        assert _strip(a) == _strip(b), query
    assert any("`c`.`s`.`agent_event`" in s for s in fake.statements)  # Delta dialect was used
    eid = decisions.list_view(sq, {"action": "block"})["page"].items[0]["event_id"]
    da, db = (
        decisions.drawer_view(sq, eid, "details", {}),
        decisions.drawer_view(de, eid, "rules", {}),
    )
    assert da["json_text"] == db["json_text"] and da["rules"] == db["rules"]


def test_traces_equal_on_both_backends(pair: Any) -> None:
    sq, de, _ = pair
    for query in ({}, {"status": "blocked"}, {"agent": "payments"}):
        a, b = traces.list_view(sq, query), traces.list_view(de, query)
        assert _strip(a) == _strip(b), query
    a, b = traces.trace_detail(sq, "trace-delta"), traces.trace_detail(de, "trace-delta")
    for key in ("head", "extra", "selected_id"):
        assert a[key] == b[key], key

    def names(d: dict[str, Any]) -> list[tuple[Any, ...]]:
        return [(n["span_id"], n["depth"], n["name"], n["stop"], n["judge"]) for n in d["nodes"]]

    assert names(a) == names(b) and names(a)[2][3] == "block"


def test_policies_equal_on_both_backends(pair: Any) -> None:
    sq, de, _ = pair
    for query in ({}, {"action": "pause"}, {"risk": "money", "sort": "severity", "dir": "desc"}):
        a, b = policies_view.list_view(sq, query), policies_view.list_view(de, query)
        assert _strip(a) == _strip(b), query
        assert a["versions"] == b["versions"] and a["tools"] == b["tools"]
    da = policies_view.drawer_view(sq, "PAY-02", "versions", {})
    db = policies_view.drawer_view(de, "PAY-02", "versions", {})
    assert da["history"] == db["history"] and da["yaml_text"] == db["yaml_text"]


def test_audit_equal_on_both_backends(pair: Any) -> None:
    sq, de, _ = pair
    case = next(c for c in sq.cases.list_cases() if "PAY-07" in c["summary"])
    from .conftest import Console as _C  # noqa: F401 - keep the import local to the data setup

    sq.tables.append(
        "console_action",
        [
            {
                "action_id": uuid.uuid4().hex,
                "ts": sq.clock.now(),
                "request_id": "req-1",
                "actor": "reviewer.an",
                "actor_kind": "user",
                "auth_method": "dev_header",
                "roles": ["reviewer"],
                "permission": "case.comment",
                "method": "POST",
                "path": "/x",
                "target_kind": "case",
                "target_id": case["case_id"],
                "outcome": "ok",
                "before_hash": "a" * 64,
                "after_hash": "b" * 64,
            }
        ],
    )
    for query in ({}, {"actor": "reviewer.an"}, {"outcome": "ok", "target": "CASE"}):
        a, b = audit_view.list_view(sq, query), audit_view.list_view(de, query)
        assert _strip(a) == _strip(b), query
        assert a["page"].total >= 1
    aid = audit_view.list_view(sq, {"actor": "reviewer.an"})["page"].items[0]["action_id"]
    assert audit_view.drawer_view(sq, aid, {}) == audit_view.drawer_view(de, aid, {})


def test_credentials_and_integrations_read_the_state_on_delta(pair: Any) -> None:
    sq, de, _ = pair
    a, b = credentials_view.page(sq), credentials_view.page(de)
    assert a["no_key_agents"] == b["no_key_agents"] and a["kind"] == b["kind"]
    ia, ib = integrations_view.page(sq), integrations_view.page(de)
    assert [r["key"] for r in ia["rows"]] == [r["key"] for r in ib["rows"]]
    assert [r["enabled"] for r in ia["rows"]] == [r["enabled"] for r in ib["rows"]]
