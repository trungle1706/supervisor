from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from supervisor_agents.common.tasks import final, tool
from supervisor_agents.common.tracing import make_tracer_provider
from supervisor_agents.common.world import BankWorld
from supervisor_agents.payments.agent import build_agent

T0 = datetime(2026, 10, 14, 5, 0, tzinfo=UTC)
PII_NAME = "Nguyễn Gia Tuấn"
PII_ACCOUNT = "602554736615"


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    a = build_adapters(settings, clock=FixedClock(T0))
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def masker() -> VnRegexMasker:
    return VnRegexMasker(b"test-key-1", "t1")


def payments_spans(capture_payloads: bool = True) -> Sequence[ReadableSpan]:
    """Run the payments agent once (mock LLM) and return its finished spans."""
    mem = InMemorySpanExporter()
    world = BankWorld.build()
    script = [
        tool("get_balance", account_id="ACC-0000000001"),
        tool(
            "add_payee",
            customer_id="CUS-000001",
            payee_name=PII_NAME,
            bank_code="VCB",
            account_number=PII_ACCOUNT,
        ),
        final(f"Da them nguoi nhan {PII_NAME}, so tai khoan {PII_ACCOUNT}."),
    ]
    chat = MockChat(scripts={"s": script})
    rt = build_agent(chat, world, tracer_provider=make_tracer_provider(mem), env="test")
    rt.capture_payloads = capture_payloads
    with chat.scenario("s"):
        rt.run(f"Them nguoi nhan {PII_NAME} tai khoan {PII_ACCOUNT}")
    return mem.get_finished_spans()
