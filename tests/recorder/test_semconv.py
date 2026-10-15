"""OpenTelemetry GenAI semantic conventions through the normaliser (WP15)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.recorder import semconv
from supervisor.recorder.capture import CapturePolicy
from supervisor.recorder.normalise import Normaliser, SpanData

T0 = 1_760_000_000_000_000_000


def _span(name: str, kind: str, attrs: dict[str, Any], status: str = "UNSET") -> SpanData:
    return SpanData(
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id=None,
        name=name,
        kind=kind,
        start_ns=T0,
        end_ns=T0 + 5_000_000,
        attributes=attrs,
        status_code=status,
    )


def _norm(span: SpanData, on: bool = True):
    n = Normaliser(None, CapturePolicy.digest_only(), "test", use_semconv=on)
    return n.normalise(span, "otlp")


CHAT = _span(
    "chat claude-x",
    "CLIENT",
    {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "anthropic",
        "gen_ai.request.model": "claude-x",
        "gen_ai.usage.input_tokens": 10,
        "gen_ai.usage.output_tokens": 3,
        "gen_ai.agent.id": "payments",
        "gen_ai.agent.version": "1.2.0",
    },
)
TOOL = _span(
    "execute_tool add_payee",
    "INTERNAL",
    {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": "add_payee",
        "gen_ai.tool.call.id": "c1",
        "gen_ai.agent.id": "payments",
        "error.type": "Timeout",
    },
)
INVOKE = _span(
    "invoke_agent payments",
    "INTERNAL",
    {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "payments"},
)


def test_chat_lands_in_columns() -> None:
    ev = _norm(CHAT).event
    assert (ev.event_type, ev.agent_id, ev.agent_version) == ("llm_call", "payments", "1.2.0")
    assert ev.latency_ms == 5 and ev.env == "test" and ev.tool_name is None


def test_execute_tool_lands_in_columns() -> None:
    ev = _norm(TOOL).event
    assert (ev.event_type, ev.tool_name, ev.agent_id) == ("tool_call", "add_payee", "payments")
    assert ev.status == "error"  # error.type


def test_invoke_agent_uses_agent_name() -> None:
    ev = _norm(INVOKE).event
    assert (ev.event_type, ev.agent_id) == ("message", "payments")


def test_operation_and_names_come_from_span_name() -> None:
    span = _span("execute_tool lookup_fx", "INTERNAL", {"gen_ai.agent.id": "fx"})
    ev = _norm(span).event
    assert (ev.event_type, ev.tool_name, ev.agent_id) == ("tool_call", "lookup_fx", "fx")
    view = semconv.apply({}, "CLIENT", "chat m1")
    assert view["gen_ai.operation.name"] == "chat" and view["gen_ai.request.model"] == "m1"
    view = semconv.apply({}, "CLIENT", "invoke_agent bot")
    assert view["gen_ai.agent.name"] == "bot"


def test_deprecated_names() -> None:
    attrs = {
        "gen_ai.system": "openai",
        "gen_ai.usage.prompt_tokens": 7,
        "gen_ai.usage.completion_tokens": 2,
        "gen_ai.agent.id": "old",
    }
    view = semconv.apply(attrs, "CLIENT", "chat gpt")
    assert view["gen_ai.provider.name"] == "openai"
    assert view["gen_ai.usage.input_tokens"] == 7 and view["gen_ai.usage.output_tokens"] == 2
    ev = _norm(_span("chat gpt", "CLIENT", attrs)).event
    assert (ev.event_type, ev.agent_id) == ("llm_call", "old")
    # current name present: the deprecated one does not replace it
    both = semconv.apply({"gen_ai.system": "a", "gen_ai.provider.name": "b"}, "", "")
    assert both["gen_ai.provider.name"] == "b"


def test_supervisor_names_win() -> None:
    span = _span(
        "execute_tool other",
        "INTERNAL",
        {
            "supervisor.agent_id": "mine",
            "gen_ai.agent.id": "theirs",
            "gen_ai.agent.name": "theirs2",
            "supervisor.agent_version": "9",
            "gen_ai.agent.version": "1",
            "supervisor.tool_name": "mytool",
            "gen_ai.tool.name": "theirtool",
            "supervisor.status": "ok",
            "error.type": "X",
            "supervisor.event_type": "message",
        },
    )
    ev = _norm(span).event
    assert (ev.agent_id, ev.agent_version, ev.tool_name) == ("mine", "9", "mytool")
    assert (ev.status, ev.event_type) == ("ok", "message")


def test_setting_off_equals_old_path() -> None:
    # old path ignored span-name inference, agent.name and agent.version, error.type
    assert _norm(INVOKE, on=False) is None  # only gen_ai.agent.name: no agent id
    ev_off = _norm(CHAT, on=False).event
    assert ev_off.agent_version is None and ev_off.event_type == "llm_call"
    ev_tool = _norm(TOOL, on=False).event
    assert ev_tool.status is None and ev_tool.tool_name == "add_payee"
    nameonly = _span("execute_tool lookup_fx", "INTERNAL", {"gen_ai.agent.id": "fx"})
    assert _norm(nameonly, on=False) is None  # no operation attribute, no tool: no event


def test_mapping_table_is_sound() -> None:
    keys = [row.semconv for row in semconv.MAPPING]
    assert len(keys) == len(set(keys))
    model = yaml.safe_load((Path(__file__).parents[2] / "schema" / "model.yaml").read_text())
    columns = set(model["tables"]["agent_event"]["columns"])
    for row in semconv.MAPPING:
        assert row.status in ("stable", "development", "deprecated")
        assert row.column is None or row.column in columns, row
    for ops, attrs in semconv.EMIT.items():
        assert ops in semconv.OPERATIONS and len(attrs) == len(set(attrs))
    assert set(semconv.EMIT) == {"chat", "execute_tool", "invoke_agent"}
    assert "supervisor.agent_id" in semconv.SUPERVISOR_ATTRS and semconv.spec_version


@pytest.mark.parametrize("on", [True, False])
def test_supervisor_only_span_is_unchanged_by_setting(on: bool) -> None:
    span = _span("llm", "CLIENT", {"supervisor.agent_id": "p", "supervisor.event_type": "llm_call"})
    ev = _norm(span, on=on).event
    assert (ev.agent_id, ev.event_type, ev.status) == ("p", "llm_call", None)


@pytest.mark.parametrize("on", [True, False])
def test_build_recorder_honours_setting(adapters: Any, on: bool) -> None:
    from supervisor.recorder.service import build_recorder

    settings = adapters.settings.model_copy(update={"recorder_semconv": on})
    rec = build_recorder(settings, adapters.tables, use_spool=False)
    assert rec.normaliser.use_semconv is on
