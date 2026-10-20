"""WP39 fixtures: a console over a gate that writes verdict v2 rows (DETECTORS_ENABLED=1)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema

from .conftest import Console

PLANTED = {
    "name": "NGUYEN VAN THU",
    "phone": "0912345678",
    "cccd": "001203004567",
    "email": "thu.nguyen@example.com",
}
PLANTED_ARGS = {
    "customer_id": "C-1",
    "payee_name": PLANTED["name"],
    "cccd": PLANTED["cccd"],
    "note": f"so dien thoai {PLANTED['phone']}",
}
CORR = "corr-planted-0001"


@pytest.fixture
def v2adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        detectors_enabled=True,
        console_decisions_v2=True,
        console_decisions_enabled=True,
        console_traces_enabled=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


def plant(console: Console) -> dict[str, str]:
    """Planted personal data through the real gate: arguments, tool results, output, plus the
    recorder events (masked text) of the same trace, and a case title with personal data."""
    rt = console.runtime
    gw = rt.gateway
    tables = console.ctx.tables
    masker = __import__("supervisor.adapters.factory", fromlist=["make_masker"]).make_masker(
        console.ctx.settings
    )
    now = console.ctx.clock.now()
    trace = "trace-planted-0001"
    span = "span-planted-0001"
    ctx = {"trace_id": trace, "span_id": span, "consumer_id": "app-mobile"}
    a = gw.check(
        "payments",
        "1.0.0",
        "add_payee",
        PLANTED_ARGS,
        ctx,
        correlation_id=CORR,
        request_id="req-planted-01",
    )
    b = gw.check(
        "payments",
        "1.0.0",
        "get_balance",
        {"account_id": "A-1"},
        {
            **ctx,
            "span_id": "span-planted-0002",
            "tool_results": [{"row": f"khach {PLANTED['name']} {PLANTED['phone']}"}],
        },
        correlation_id=CORR,
        request_id="req-planted-02",
    )
    c = gw.check(
        "payments",
        "1.0.0",
        "get_balance",
        {},
        {
            **ctx,
            "span_id": "span-planted-0003",
            "output": f"Gui {PLANTED['name']}, CCCD {PLANTED['cccd']}, mail {PLANTED['email']}",
        },
        direction="output",
        correlation_id=CORR,
        request_id="req-planted-03",
    )
    masked_args = masker.mask(json.dumps(PLANTED_ARGS, ensure_ascii=False))
    tables.append(
        "agent_event",
        [
            {
                "event_id": uuid.uuid4().hex,
                "ts": now,
                "trace_id": trace,
                "span_id": span,
                "agent_id": "payments",
                "event_type": "tool_call",
                "tool_name": "add_payee",
                "args_masked": masked_args,
                "result_masked": masker.mask(f"ok {PLANTED['name']}"),
                "env": "test",
                "source": "otel",
                "capture_level": "masked",
            }
        ],
    )
    return {
        "trace": trace,
        "span": span,
        "a": a["decision_id"],
        "b": b["decision_id"],
        "c": c["decision_id"],
    }


@pytest.fixture
def v2console(v2adapters: Adapters) -> Iterator[Console]:
    from fastapi.testclient import TestClient

    from supervisor.adapters.auth import set_provider
    from supervisor.app import app
    from supervisor.console.context import build_context, set_context
    from supervisor.demo import replay as R
    from supervisor.gateway import wiring as gate_wiring
    from supervisor.wiring import build_runtime

    report = R.run_gated(v2adapters.settings, adapters=v2adapters)
    assert report.ok, "\n".join(report.lines)
    runtime = build_runtime(v2adapters.settings, adapters=v2adapters, policy_refresh_s=0.0)
    ctx = build_context(runtime)
    set_context(ctx)
    gate_wiring.set_gateway(runtime.gateway)
    try:
        yield Console(TestClient(app, raise_server_exceptions=False), runtime, ctx)
    finally:
        set_context(None)
        gate_wiring.set_gateway(None)
        set_provider(None)
        runtime.close()


__all__ = ["CORR", "PLANTED", "PLANTED_ARGS", "plant", "v2adapters", "v2console"]
_ = Any
