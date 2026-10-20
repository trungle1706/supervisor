"""WP-UX3 review: privacy checks across the new pages.

* A value planted only in the RESTRICTED raw table (``agent_event_raw.args_raw`` /
  ``result_raw``) never reaches any page, and no page even queries that table.
* The Playground never writes the typed arguments to a log record."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from supervisor.console import nav

from .conftest import Console
from .test_ux3_more import _event, _verdict

RAW = "RAWONLY-SENTINEL-7731"  # not personal data: the masker leaves it alone
PHONE = "0912345678"


@pytest.fixture
def ux(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in nav.PAGES.values():
        monkeypatch.setattr(console.ctx.settings, flag, True)
    return console


def _plant(ux: Console) -> tuple[str, str]:
    t = "trace-review-raw"
    tc = _event(ux, t, "r1", None, "tool_call", tool="transfer", level="raw", args="masked text")
    gate = _event(
        ux, t, "r2", "r1", "gate_decision", tool="transfer", level="raw",
        classification="block", status="denied",
    )  # fmt: skip
    _verdict(ux, t, gate, action="block", rule="PAY-02")
    rows = [
        {"event_id": eid, "ts": ux.ctx.clock.now(), "trace_id": t, "agent_id": "payments",
         "args_raw": f"{RAW} args", "result_raw": f"{RAW} result", "access_class": "restricted"}
        for eid in (tc, gate)
    ]  # fmt: skip
    ux.ctx.tables.append("agent_event_raw", rows)
    assert ux.ctx.tables.query("agent_event_raw", {"event_id": tc})  # planted
    return t, gate


def test_raw_column_value_never_reaches_a_page_and_the_raw_table_is_never_read(
    ux: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, gate = _plant(ux)
    read: list[str] = []
    real = ux.ctx.tables.query

    def spy(table: str, *a: Any, **kw: Any) -> Any:
        read.append(table)
        return real(table, *a, **kw)

    monkeypatch.setattr(ux.ctx.tables, "query", spy)
    urls = [
        "/console/decisions",
        f"/console/decisions?drawer={gate}&dtab=details",
        *(f"/console/decisions/{gate}/drawer?tab={x}" for x in ("details", "rules", "evidence")),
        "/console/traces",
        f"/console/traces/{t}",
        f"/console/traces/{t}/span/r1",
        f"/console/traces/{t}/span/r2",
        "/console/policies",
        "/console/audit",
        "/console/integrations",
    ]
    for url in urls:
        r = ux.get(url, user="admin.chi" if "audit" not in url else "auditor.dung")
        assert r.status_code == 200, url
        assert RAW not in r.text, url
    assert "agent_event_raw" not in read
    r = ux.get(f"/console/traces/{t}/span/r1")
    assert "masked text" in r.text  # the masked column is what a raw-level event shows


def test_playground_never_logs_the_typed_arguments(
    ux: Console, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    data = {
        "agent_id": "payments",
        "tool": "add_payee",
        "version": "1.0",
        "args": json.dumps({"name": "Tran Thi B", "phone": PHONE, "note": RAW}),
        "context": "{}",
    }
    assert ux.post("/console/playground/run", data, user="operator.khanh").status_code == 200
    bad = {**data, "args": json.dumps({"phone": PHONE})[:-1]}  # broken JSON: 400 path
    assert ux.post("/console/playground/run", bad, user="operator.khanh").status_code == 400
    text = caplog.text + json.dumps([r.__dict__ for r in caplog.records], default=str)
    assert PHONE not in text and RAW not in text and "Tran Thi B" not in text


def test_operator_header_role_is_operator_not_viewer(ux: Console) -> None:
    """Review WP-UX3: the header role pill showed "viewer" for an operator (main_role had no
    operator), which looked wrong on the Playground, where a viewer gets 403."""
    html = ux.get("/console/playground", user="operator.khanh").text
    assert '<span class="role">operator</span>' in html
    vi = ux.get("/console/playground?lang=vi", user="operator.khanh").text
    assert '<span class="role">vận hành</span>' in vi
