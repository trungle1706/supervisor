"""WP-O5 (phase 9): the agent log (``onboard_log``). Every hook writes a row with the right step and
by_kind, a hook that fails never fails the action, nothing is written with the flag off, and no
personal data reaches ``what`` or ``pointer`` (a Vietnamese name and a phone number are planted in
every input a hook can see)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from supervisor.onboard import agent_log, predeploy
from supervisor.onboard.facts import FactsService
from supervisor.onboard.intake import IntakeError, IntakeService
from supervisor.onboard.predeploy import PredeployService
from tests.onboard.test_facts import (
    AGENT,
    MANIFEST,
    NODE,
    FakeGatewayChat,
    make_zip,
)
from tests.onboard.test_predeploy import all_ok_executor, fake_target

NAME = "Nguyễn Văn Anh"  # planted: a Vietnamese name
PHONE = "0912345678"  # planted: a mobile number


@pytest.fixture(autouse=True)
def _no_leftover_runs() -> Iterator[None]:
    predeploy._RUNNING.clear()
    yield
    predeploy._RUNNING.clear()
    predeploy._THREADS.clear()


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        onboard_intake=True,
        onboard_facts=True,
        onboard_predeploy=True,
        onboard_postdeploy=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


def ctx_of(a: Adapters) -> Any:
    return SimpleNamespace(settings=a.settings, state=a.state, tables=a.tables, clock=a.clock)


def log_rows(a: Adapters, node: str = NODE) -> list[dict[str, Any]]:
    rows = [dict(r) for r in a.tables.query("onboard_log", {"node_id": node}, order_by=("at",))]
    return rows


def steps(a: Adapters, node: str = NODE) -> list[tuple[str, str]]:
    return [(r["step"], r["by_kind"]) for r in log_rows(a, node)]


# ------------------------------------------------------------------------------ the writer


def test_flag_defaults_off() -> None:
    assert load_settings(sql_backend="sqlite").onboard_postdeploy is False


def test_log_writes_one_row_with_every_column(adapters: Adapters) -> None:
    ok = agent_log.log(
        ctx_of(adapters), NODE, "intake", "a sentence", "report pdr_1", "person", "an", 3
    )
    assert ok is True
    (row,) = log_rows(adapters)
    assert row["step"] == "intake" and row["by_kind"] == "person" and row["actor"] == "an"
    assert (
        row["attempt_n"] == 3 and row["what"] == "a sentence" and row["pointer"] == "report pdr_1"
    )
    assert row["log_id"].startswith("olg_") and row["at"] is not None


def test_flag_off_writes_nothing(adapters: Adapters, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapters.settings, "onboard_postdeploy", False)
    assert agent_log.log(ctx_of(adapters), NODE, "scan", "x", "y", "rule", "rule") is False
    assert log_rows(adapters) == []
    # the services keep working and log nothing
    IntakeService(adapters.settings, adapters.state, adapters.clock, adapters.tables).submit_zip(
        NODE, make_zip({"manifest.yaml": MANIFEST, "agent.py": AGENT}), "s.zip", "reviewer.an"
    )
    assert log_rows(adapters) == []


def test_bad_step_or_by_kind_is_refused_without_raising(adapters: Adapters) -> None:
    c = ctx_of(adapters)
    assert agent_log.log(c, NODE, "nowhere", "x", "y", "rule", "rule") is False
    assert agent_log.log(c, NODE, "scan", "x", "y", "robot", "rule") is False
    assert log_rows(adapters) == []


def test_every_step_and_kind_the_schema_names_is_accepted(adapters: Adapters) -> None:
    c = ctx_of(adapters)
    for step in agent_log.STEPS:
        for kind in agent_log.BY_KINDS:
            assert agent_log.log(c, NODE, step, "x", "y", kind, "who") is True
    assert len(log_rows(adapters)) == len(agent_log.STEPS) * len(agent_log.BY_KINDS)


def test_text_is_cut_to_the_schema_limits(adapters: Adapters) -> None:
    agent_log.log(ctx_of(adapters), NODE, "scan", "w" * 900, "p" * 900, "rule", "a" * 900)
    (row,) = log_rows(adapters)
    assert len(row["what"]) <= 300 and len(row["pointer"]) <= 200 and len(row["actor"]) <= 120


def test_rows_cannot_be_changed_or_deleted(adapters: Adapters) -> None:
    agent_log.log(ctx_of(adapters), NODE, "scan", "x", "y", "rule", "rule")
    with pytest.raises(Exception):  # noqa: B017 - the SQLite trigger aborts the statement
        adapters.executor.execute("UPDATE onboard_log SET what = 'z'")


def test_rows_reader_returns_oldest_first_as_plain_dicts(adapters: Adapters) -> None:
    c = ctx_of(adapters)
    for i in range(3):
        agent_log.log(c, NODE, "scan", f"row {i}", "p", "rule", "rule")
    got = agent_log.rows(c, NODE)
    assert [r["what"] for r in got] == ["row 0", "row 1", "row 2"]
    assert isinstance(got[0]["at"], str) and got[0]["at"].endswith("Z")


def test_a_failing_write_returns_false_and_warns(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken:
        def append(self, table: str, rows: Any) -> int:
            raise RuntimeError("store down")

    c = SimpleNamespace(settings=adapters.settings, tables=Broken(), clock=adapters.clock)
    with caplog.at_level(logging.WARNING, logger="supervisor.onboard.agent_log"):
        assert agent_log.log(c, NODE, "scan", "x", "y", "rule", "rule") is False
    assert any("not written" in r.getMessage() for r in caplog.records)


def test_a_service_without_tables_logs_nothing(adapters: Adapters) -> None:
    svc = IntakeService(adapters.settings, adapters.state, adapters.clock)  # no tables
    n = svc.submit_zip(NODE, make_zip({"manifest.yaml": MANIFEST}), "s.zip", "an")["n"]
    assert n == 1 and log_rows(adapters) == []


# ------------------------------------------------------------------------------ the hooks


def test_intake_hook_stored_and_refused(adapters: Adapters) -> None:
    svc = IntakeService(adapters.settings, adapters.state, adapters.clock, adapters.tables)
    n = svc.submit_zip(
        NODE, make_zip({"manifest.yaml": MANIFEST, "agent.py": AGENT}), "s.zip", "an"
    )["n"]
    (row,) = log_rows(adapters)
    assert (row["step"], row["by_kind"], row["actor"], row["attempt_n"]) == (
        "intake",
        "person",
        "an",
        n,
    )
    assert "2 files" in row["what"] and row["pointer"] == "intake attempt 1"
    with pytest.raises(IntakeError):
        svc.submit_zip(NODE, b"this is not a zip", "bad.zip", "an")
    refused = log_rows(adapters)[-1]
    assert refused["step"] == "intake" and refused["by_kind"] == "person"
    assert "source refused" in refused["what"]


def test_facts_hook_start_and_end_with_the_dropped_count(adapters: Adapters) -> None:
    n = IntakeService(
        adapters.settings, adapters.state, adapters.clock, adapters.tables
    ).submit_zip(NODE, make_zip({"manifest.yaml": MANIFEST, "agent.py": AGENT}), "s.zip", "an")["n"]
    chat = FakeGatewayChat(
        [
            {
                "kind": "tool",
                "name": "waive_fee",
                "detail": "invented",
                "file": "agent.py",
                "line": 1,
                "quote": "this text is not in the file",
            }
        ]
    )
    FactsService(
        adapters.settings,
        adapters.state,
        adapters.clock,
        chat_factory=lambda: chat,
        tables=adapters.tables,
    ).build(NODE, n)
    got = [r for r in log_rows(adapters) if r["step"] == "facts"]
    assert len(got) == 2
    start, end = got
    assert start["by_kind"] == "rule" and "reading the stored source" in start["what"]
    assert end["by_kind"] == "model" and end["actor"] == "fake-gateway-v1"
    assert "claims dropped" in end["what"] and "1 claims dropped" in end["what"]
    assert end["attempt_n"] == n


def test_facts_hook_by_rule_when_no_model_was_used(adapters: Adapters) -> None:
    from supervisor.adapters.llm.mock import MockChat

    n = IntakeService(adapters.settings, adapters.state, adapters.clock).submit_zip(
        NODE, make_zip({"manifest.yaml": MANIFEST, "agent.py": AGENT}), "s.zip", "an"
    )["n"]
    FactsService(
        adapters.settings,
        adapters.state,
        adapters.clock,
        chat_factory=lambda: MockChat(),
        tables=adapters.tables,
    ).build(NODE, n)
    end = [r for r in log_rows(adapters) if r["step"] == "facts"][-1]
    assert end["by_kind"] == "rule" and end["actor"] == "rule"
    assert "0 claims dropped" in end["what"]


def test_predeploy_hook_start_and_verdict_by_rule(adapters: Adapters) -> None:
    n = IntakeService(adapters.settings, adapters.state, adapters.clock).submit_zip(
        NODE, make_zip({"manifest.yaml": MANIFEST, "agent.py": AGENT}), "s.zip", "an"
    )["n"]
    svc = PredeployService(
        adapters.settings,
        adapters.state,
        adapters.clock,
        executor=all_ok_executor("ok"),
        target_factory=fake_target,
        tables=adapters.tables,
    )
    rep = svc.start(NODE, n, "reviewer.an", background=False)
    got = [r for r in log_rows(adapters) if r["step"] == "predeploy"]
    assert [r["by_kind"] for r in got] == ["rule", "rule"]
    assert "started" in got[0]["what"] and got[0]["pointer"] == f"report {rep['report_id']}"
    assert got[1]["what"].startswith(f"verdict {rep['verdict']}")
    assert got[1]["attempt_n"] == n


def test_predeploy_takes_the_tables_of_its_context(adapters: Adapters) -> None:
    svc = PredeployService(adapters.settings, adapters.state, adapters.clock, ctx=ctx_of(adapters))
    assert svc.tables is adapters.tables


def test_a_hook_that_fails_does_not_fail_the_action(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*a: Any, **k: Any) -> int:
        raise RuntimeError("log store down")

    monkeypatch.setattr(adapters.tables, "append", boom)
    with caplog.at_level(logging.WARNING, logger="supervisor.onboard.agent_log"):
        svc = IntakeService(adapters.settings, adapters.state, adapters.clock, adapters.tables)
        n = svc.submit_zip(
            NODE, make_zip({"manifest.yaml": MANIFEST, "agent.py": AGENT}), "s.zip", "an"
        )["n"]
        assert n == 1  # the attempt was stored
        from supervisor.adapters.llm.mock import MockChat

        card = FactsService(
            adapters.settings,
            adapters.state,
            adapters.clock,
            chat_factory=lambda: MockChat(),
            tables=adapters.tables,
        ).build(NODE, n)
        assert card["total"] > 0  # the facts were built
        rep = PredeployService(
            adapters.settings,
            adapters.state,
            adapters.clock,
            executor=all_ok_executor("ok"),
            target_factory=fake_target,
            tables=adapters.tables,
        ).start(NODE, n, "an", background=False)
        assert rep["status"] == "done"  # the report finished
    assert any("not written" in r.getMessage() for r in caplog.records)


def test_scan_hook_logs_a_node_that_becomes_a_candidate(adapters: Adapters) -> None:
    from supervisor.inventory.model import Node
    from supervisor.inventory.service import InventoryService

    svc = InventoryService.from_adapters(adapters)
    assert svc.tables is adapters.tables
    node = Node(
        kind="system",
        name="fee-bot-app",
        display_name="fee-bot",
        status="unmanaged",
        attrs={"workspace_kind": "app"},
    )
    svc._log_candidate(node)  # noqa: SLF001
    (row,) = log_rows(adapters, node.node_id)
    assert (row["step"], row["by_kind"], row["actor"]) == ("scan", "rule", "rule")
    assert "app" in row["what"] and "fee-bot" not in row["what"]
    # a node that is no candidate kind writes nothing
    other = Node(kind="dataset", name="a.b.c", attrs={})
    svc._log_candidate(other)  # noqa: SLF001
    assert log_rows(adapters, other.node_id) == []


# ------------------------------------------------------------------------------ no personal data


def test_a_name_and_a_phone_number_never_reach_the_row(adapters: Adapters) -> None:
    """Direct: the writer masks personal data in ``what``, ``pointer`` and ``actor``."""
    agent_log.log(
        ctx_of(adapters),
        NODE,
        "intake",
        f"customer {NAME} called {PHONE} about the loan",
        f"file {NAME} {PHONE}",
        "person",
        f"{NAME} {PHONE}",
    )
    (row,) = log_rows(adapters)
    for col in ("what", "pointer", "actor"):
        assert PHONE not in row[col], col
        assert "Nguyễn Văn Anh" not in row[col] and "Văn Anh" not in row[col], col
    assert "[pii]" in row["what"]


def test_hooks_never_copy_inputs_that_carry_a_name_or_a_phone(adapters: Adapters) -> None:
    """Through the hooks: the file name, the zip content and the typed reason hold the planted
    values; none of them is in any log row."""
    entries = {
        "manifest.yaml": MANIFEST,
        "agent.py": AGENT + f"\n# owner: {NAME} {PHONE}\n",
        f"{NAME} {PHONE}.txt": "note",
    }
    svc = IntakeService(adapters.settings, adapters.state, adapters.clock, adapters.tables)
    n = svc.submit_zip(NODE, make_zip(entries), f"{NAME} {PHONE}.zip", "an")["n"]
    with pytest.raises(IntakeError):
        svc.submit_zip(NODE, b"not a zip", f"{NAME} {PHONE}.zip", "an")
    from supervisor.adapters.llm.mock import MockChat

    FactsService(
        adapters.settings,
        adapters.state,
        adapters.clock,
        chat_factory=lambda: MockChat(),
        tables=adapters.tables,
    ).build(NODE, n)
    PredeployService(
        adapters.settings,
        adapters.state,
        adapters.clock,
        executor=all_ok_executor("ok"),
        target_factory=fake_target,
        tables=adapters.tables,
    ).start(NODE, n, "an", background=False)
    rows = log_rows(adapters)
    assert len(rows) >= 6
    for row in rows:
        blob = " ".join(str(v) for v in row.values())
        assert PHONE not in blob and "Văn Anh" not in blob and "Nguyễn" not in blob, row["step"]


def test_state_and_attach_hooks_write_person_rows_without_the_reason(
    adapters: Adapters,
) -> None:
    """The two console hooks call ``agent_log.log`` with fixed sentences; see the console tests
    for the routes. Here: the sentences hold no typed text."""
    import inspect

    from supervisor.console import attach_routes, routes

    src = inspect.getsource(routes.agent_running)
    assert 'd.get("reason"' in src  # the reason is read for the state change only
    log_part = src.split("agent_log.log", 1)[1].split("if result.get", 1)[0]
    assert "reason" not in log_part
    assert "agent_log.log" in inspect.getsource(attach_routes.attach_check)
