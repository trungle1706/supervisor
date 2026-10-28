"""WP-P3: `demo seed --databricks` writes the synthetic demo rows into the configured SQL
backend. Tested on SQLite (the Delta path uses the same services through the SQL port)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from supervisor.config import Settings
from supervisor.demo import __main__ as demo_main
from supervisor.demo import seed_backend
from supervisor.demo.session import demo_settings


def _rows(settings: Settings, table: str) -> list[dict[str, Any]]:
    from supervisor.adapters.factory import build_adapters

    a = build_adapters(settings)
    try:
        return a.state.query(table)
    finally:
        a.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    from supervisor.adapters.factory import build_adapters
    from supervisor.jobs import bootstrap_schema

    s = demo_settings(tmp_path / "data")
    a = build_adapters(s)
    try:
        bootstrap_schema.run(s, a)
    finally:
        a.close()
    return s


def test_seed_writes_marked_rows_and_is_idempotent(settings: Settings) -> None:
    lines: list[str] = []
    rep = seed_backend.seed_backend(settings, echo=lines.append)
    assert rep.ok, "\n".join(rep.lines)
    assert rep.systems == 3 and rep.systems_new == 3
    assert rep.cases == 3 and rep.cases_new == 3

    agents = {r["agent_id"] for r in _rows(settings, "agent")}
    assert {"demo-kb-chatbot", "demo-customer-service", "demo-payments-ops"} <= agents
    systems = [r["name"] for r in _rows(settings, "ai_system")]
    assert sorted(systems) == ["demo-customer-service", "demo-kb-chatbot", "demo-payments-ops"]
    cases = _rows(settings, "cases")
    assert len(cases) == 3 and all("[demo]" in c["summary"] for c in cases)
    links = _rows(settings, "case_link")
    assert {r["source_ref"] for r in links if r["source_kind"] == "monitor"} == {
        "demo-seed:demo-001",
        "demo-seed:demo-002",
        "demo-seed:demo-003",
    }

    again = seed_backend.seed_backend(settings, echo=lines.append)
    assert again.ok, "\n".join(again.lines)
    assert again.systems_new == 0 and again.cases_new == 0
    assert len(_rows(settings, "cases")) == 3
    assert len(_rows(settings, "ai_system")) == 3
    assert all(line.isascii() for line in lines)


def test_seed_text_is_synthetic_only() -> None:
    names = [m.system["name"] for m in seed_backend.SYSTEMS]
    assert all(n.startswith(seed_backend.DEMO_PREFIX) for n in names)
    assert all(m.agent_id.startswith(seed_backend.DEMO_PREFIX) for m in seed_backend.SYSTEMS)
    assert all(c[3].startswith("[demo]") for c in seed_backend.CASES)


def test_store_that_cannot_open_gives_fail_not_a_traceback(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_settings: Settings) -> None:
        raise RuntimeError("TABLE_OR_VIEW_NOT_FOUND agent")

    monkeypatch.setattr(seed_backend, "build_session", boom)
    lines: list[str] = []
    rep = seed_backend.seed_backend(settings, echo=lines.append)
    assert not rep.ok
    assert any(line.startswith("[FAIL]") and "bootstrap_schema" in line for line in lines)


def test_main_routes_seed_databricks(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(seed_backend, "main", lambda argv=None: seen.append(list(argv or [])) or 0)
    assert demo_main.main(["seed", "--databricks", "--data-dir", "x"]) == 0
    assert seen == [["--databricks", "--data-dir", "x"]]
