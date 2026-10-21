"""OpenTelemetry GenAI semantic conventions -> recorder attributes. Pure, no I/O.

Spec read on 2026-10-15. The GenAI conventions moved out of the main semantic-conventions
site (https://opentelemetry.io/docs/specs/semconv/gen-ai/ now only points onward) to
https://github.com/open-telemetry/semantic-conventions-genai (docs/gen-ai/gen-ai-spans.md,
gen-ai-agent-spans.md, client-inference.md; links there name semantic conventions v1.44.0).
Status in that spec: every ``gen_ai.*`` attribute is *development*; ``error.type`` and
``server.*`` are *stable*. ``gen_ai.system``, ``gen_ai.usage.prompt_tokens`` and
``gen_ai.usage.completion_tokens`` are deprecated names from older spec versions (the new
pages do not list them); the recorder still reads them as aliases.

Rules (``apply``):

* our own ``supervisor.*`` attribute always wins over a ``gen_ai.*`` one;
* deprecated names are copied to the current name only when the current name is absent;
* ``gen_ai.operation.name`` is inferred from the span name prefix when it is missing
  (``chat gpt-x``, ``execute_tool lookup``, ``invoke_agent payments``);
* the tool name / agent name / model that the span name carries fill ``gen_ai.tool.name`` /
  ``gen_ai.agent.name`` / ``gen_ai.request.model`` when those are missing.

Span names and kinds: ``chat {model}`` CLIENT (INTERNAL if in-process), ``execute_tool
{tool}`` INTERNAL, ``invoke_agent {agent}`` CLIENT (remote) or INTERNAL (same process),
``create_agent {agent}`` CLIENT.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

spec_version = "semantic-conventions-genai (semconv v1.44.0 links), read 2026-10-15"

OPERATIONS = (
    "chat",
    "text_completion",
    "generate_content",
    "embeddings",
    "execute_tool",
    "invoke_agent",
    "create_agent",
    "invoke_workflow",
    "plan",
    "retrieval",
)

A_OP = "gen_ai.operation.name"
A_PROVIDER = "gen_ai.provider.name"
A_SYSTEM = "gen_ai.system"  # deprecated -> gen_ai.provider.name
A_IN_TOK = "gen_ai.usage.input_tokens"
A_OUT_TOK = "gen_ai.usage.output_tokens"
A_TOOL_NAME = "gen_ai.tool.name"
A_AGENT_NAME = "gen_ai.agent.name"
A_MODEL = "gen_ai.request.model"

# deprecated name -> current name
DEPRECATED_ALIASES: dict[str, str] = {
    A_SYSTEM: A_PROVIDER,
    "gen_ai.usage.prompt_tokens": A_IN_TOK,
    "gen_ai.usage.completion_tokens": A_OUT_TOK,
}


class Row(NamedTuple):
    semconv: str  # attribute name in the spec
    column: str | None  # agent_event column; None = not mapped (no column)
    status: str  # stable | development | deprecated
    note: str


MAPPING: tuple[Row, ...] = (
    Row(
        A_OP,
        "event_type",
        "development",
        "chat/text_completion/generate_content -> llm_call; execute_tool -> tool_call; "
        "invoke_agent/create_agent -> message (handoff when a caller agent is set)",
    ),
    Row("gen_ai.agent.id", "agent_id", "development", "after supervisor.agent_id"),
    Row(
        A_AGENT_NAME,
        "agent_id",
        "development",
        "last fallback, after the resource agent_id; span name 'invoke_agent {name}' gives it",
    ),
    Row("gen_ai.agent.version", "agent_version", "development", "after supervisor.agent_version"),
    Row(A_TOOL_NAME, "tool_name", "development", "span name 'execute_tool {tool}' also gives it"),
    Row(
        "gen_ai.tool.call.arguments",
        "args_masked",
        "development",
        "opt-in; args_hash is computed, masked text follows the capture level",
    ),
    Row(
        "gen_ai.tool.call.result",
        "result_masked",
        "development",
        "opt-in; masked text follows the capture level",
    ),
    Row("gen_ai.input.messages", "args_masked", "development", "opt-in; same path as arguments"),
    Row("gen_ai.output.messages", "result_masked", "development", "opt-in; same path as result"),
    Row("error.type", "status", "stable", "present -> status 'error' (unless supervisor.status)"),
    Row(A_PROVIDER, None, "development", "not mapped (no column)"),
    Row(A_SYSTEM, None, "deprecated", "alias of gen_ai.provider.name; not mapped"),
    Row(A_MODEL, None, "development", "not mapped; with CLIENT kind it implies llm_call"),
    Row("gen_ai.response.model", None, "development", "not mapped (no column)"),
    Row(A_IN_TOK, None, "development", "not mapped (no column)"),
    Row(A_OUT_TOK, None, "development", "not mapped (no column)"),
    Row("gen_ai.usage.prompt_tokens", None, "deprecated", "alias of input_tokens; not mapped"),
    Row("gen_ai.usage.completion_tokens", None, "deprecated", "alias of output_tokens; not mapped"),
    Row("gen_ai.response.finish_reasons", None, "development", "not mapped (no column)"),
    Row(
        "gen_ai.conversation.id",
        "session_id",
        "development",
        "after supervisor.session_id; session_source = span (WP27)",
    ),
    Row("gen_ai.tool.call.id", None, "development", "not mapped (span_id is the event key)"),
    Row("gen_ai.tool.type", None, "development", "not mapped (no column)"),
)

# What a team must emit per span type (required + recommended that the recorder maps).
EMIT: dict[str, tuple[str, ...]] = {
    "chat": (
        A_OP,
        A_PROVIDER,
        A_MODEL,
        "gen_ai.response.model",
        A_IN_TOK,
        A_OUT_TOK,
        "gen_ai.response.finish_reasons",
        "gen_ai.agent.id",
        "gen_ai.conversation.id",
        "error.type",
    ),
    "execute_tool": (
        A_OP,
        A_TOOL_NAME,
        "gen_ai.tool.call.id",
        "gen_ai.tool.type",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "gen_ai.agent.id",
        "gen_ai.conversation.id",
        "error.type",
    ),
    "invoke_agent": (
        A_OP,
        A_PROVIDER,
        "gen_ai.agent.id",
        A_AGENT_NAME,
        "gen_ai.agent.version",
        "gen_ai.conversation.id",
        A_MODEL,
        A_IN_TOK,
        A_OUT_TOK,
        "error.type",
    ),
}

# Our own attributes the recorder needs next to the gen_ai.* ones.
SUPERVISOR_ATTRS: tuple[str, ...] = (
    "supervisor.agent_id",
    "supervisor.agent_version",
    "supervisor.caller_agent_id",
    "supervisor.event_type",
    "supervisor.args_hash",
    "supervisor.amount_minor",
    "supervisor.currency",
    "supervisor.env",
)


def operation_from_name(name: str) -> str | None:
    """Operation from the span name prefix (``chat gpt-x`` -> ``chat``), else None."""
    head = name.strip().split(" ", 1)[0] if name else ""
    return head if head in OPERATIONS else None


def _missing(attrs: Mapping[str, Any], key: str) -> bool:
    return attrs.get(key) in (None, "")


def apply(attrs: Mapping[str, Any], kind: str, name: str) -> dict[str, Any]:
    """Normalised view of span attributes. Never overwrites an attribute that is present;
    ``supervisor.*`` names are never touched, so they always win downstream."""
    out = dict(attrs)
    for old, new in DEPRECATED_ALIASES.items():
        if old in out and _missing(out, new):
            out[new] = out[old]
    op = out.get(A_OP)
    text = name.strip() if name else ""
    if _missing(out, A_OP):
        op = operation_from_name(text)
        if op:
            out[A_OP] = op
    rest = text.split(" ", 1)[1].strip() if op and text.startswith(f"{op} ") else ""
    if rest:
        if op == "execute_tool" and _missing(out, A_TOOL_NAME):
            out[A_TOOL_NAME] = rest.split(" ", 1)[0]
        elif op in ("invoke_agent", "create_agent") and _missing(out, A_AGENT_NAME):
            out[A_AGENT_NAME] = rest
        elif op in ("chat", "text_completion", "generate_content") and _missing(out, A_MODEL):
            out[A_MODEL] = rest
    if not _missing(out, "error.type") and _missing(out, "supervisor.status"):
        out["supervisor.status"] = "error"
    return out
