"""Case intake never runs on a GET; it runs from the scheduler, the job, or the explicit POST."""

from __future__ import annotations

from typing import Any

from supervisor.jobs import case_intake

from .conftest import Console, add_gate_block


def _counts(console: Console) -> tuple[int, int]:
    t = console.runtime.adapters.tables
    return len(t.query("cases", {})), len(t.query("case_link", {}))


def test_queue_get_writes_nothing(console: Console) -> None:
    add_gate_block(console.runtime.adapters)
    before = _counts(console)
    for url in ("/console/", "/console/queue/rows", "/console/queue/rows?status=all"):
        assert console.get(url).status_code == 200
    assert _counts(console) == before


def test_post_intake_creates_cases(console: Console) -> None:
    add_gate_block(console.runtime.adapters)
    before = _counts(console)
    r = console.post("/console/intake/run")
    assert r.status_code == 200, r.text
    assert "PAY-99" in r.text
    assert _counts(console)[0] == before[0] + 1


def test_post_intake_needs_htmx_and_role(console: Console) -> None:
    assert console.post("/console/intake/run", htmx=False).status_code == 400
    r = console.post("/console/intake/run", user="viewer.x")
    assert r.status_code in (400, 403), r.text
    assert r.status_code != 500


def test_job_run_creates_cases(console: Console) -> None:
    add_gate_block(console.runtime.adapters)
    before = _counts(console)[0]
    opened: Any = case_intake.run(console.ctx.cases)
    assert len(opened) == 1
    assert _counts(console)[0] == before + 1
