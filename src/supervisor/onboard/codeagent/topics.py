# ruff: noqa: E501
"""The investigation topics of the agent: one card (what to report, how) and one fixed lead query each.

Phase 1 of a run goes through these in order. Each turn the model sees one topic card and the
leads that the deterministic policy fetched for it. Phase 2 lets the model use the tools freely
for the steps that are left (for example to follow a helper into another file).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from supervisor.onboard.codeagent import leads
from supervisor.onboard.codeagent.models import Finding
from supervisor.onboard.codeagent.workspace import Workspace


@dataclass(frozen=True)
class Topic:
    key: str
    kinds: tuple[str, ...]
    card: str
    label: str
    prefetch: Callable[[Workspace, Sequence[Finding]], str]


TOOLS_CARD = """\
TOPIC tools. For every tool report kind=tool: name = the name the model sees (function name, or the \
explicit name in a decorator or schema), file and line of its def, quote = the def line, attrs:
- effect: read (reads only) | write (changes a record) | money (moves money) | credit (credit decision, \
limit, restructure, write-off) | message (sends SMS, email, webhook) | delete
- irreversible: true for money, credit and delete and for a sent message, when the code has no undo
- amount_arg: name of the money amount parameter (only for money or credit tools)
Use the scanner's values unless the body shows a different effect. A function that is not in the \
scanner list is a tool only when it is registered as one (schema, dict, list, decorator)."""

OVERSIGHT_CARD = """\
TOPIC oversight. Report (1) kind=hitl for each step in code that makes a human decide before an \
action runs (an approval request that is awaited, an interrupt, a review queue wait, a second-officer \
check, whatever its name): name=approval, attrs mode=pre_approval|interrupt|review_queue, \
guards=comma list of the tools whose body or helpers call it; the quote is the line that calls or \
defines it. A function that exists but is never called by a tool guards nothing. A comment, README or \
text that says approval exists is NOT a step. (2) kind=guardrail for each check in code: guard=\
amount_limit | allowlist | input_validation | output_filter | rate_limit | content_filter \
(attrs.guard is required), scope=the tool name. A constant that no code compares is not a guardrail."""

OBSERVABILITY_CARD = """\
TOPIC logging and secrets. Report (1) kind=logging: sink=log (logging or print calls, also through a \
helper), trace_otel, trace_mlflow, audit_table (rows or files kept as an audit trail); logs_pii=true \
when a log or print call, or the helper it uses, writes personal data (name, phone, address, ID \
number, account or card number, income, customer id). (2) kind=secret_handling: source=hardcoded \
(a secret value in code or config, shown as [REDACTED]), env (an API key, token, password or DSN read \
from an environment variable), secret_store (a vault or secret scope). A path, a URL or a model \
name read from the environment is NOT a secret."""

NETWORK_CARD = """\
TOPIC network and data flows. Report (1) kind=egress: name = host name such as api.example.com (never the word http) of every http \
or https address the code calls; also hosts held in a config file or a constant. attrs internal=true \
for hosts ending .nganhang.internal. (2) kind=data_flow: for each tool, each data source or sink it \
reaches, also through the helper functions it calls: attrs tool, direction=read|write, \
sink=db|http|bank_api|file (bank_api = a *.nganhang.internal address), target. Give one finding per \
tool, direction and sink."""

TOPICS: tuple[Topic, ...] = (
    Topic(
        "tools",
        ("tool",),
        TOOLS_CARD,
        "tool sources",
        lambda ws, known: leads.tool_sources(ws, known),
    ),
    Topic(
        "oversight",
        ("hitl", "guardrail"),
        OVERSIGHT_CARD,
        "oversight leads",
        lambda ws, known: (
            "APPROVAL-LIKE LINES:\n"
            + leads.grep_lines(ws, leads.RX_HITL, suffix=(".py",), limit=18, with_fn=True)
            + "\n\nCHECK-LIKE LINES:\n"
            + leads.grep_lines(ws, leads.RX_GUARD, suffix=(".py",), limit=18, with_fn=True)
        ),
    ),
    Topic(
        "observability",
        ("logging", "secret_handling"),
        OBSERVABILITY_CARD,
        "logging and secret leads",
        lambda ws, known: (
            "LOG AND TRACE LINES:\n"
            + leads.grep_lines(ws, leads.RX_LOG, suffix=(".py",), limit=16, with_fn=True)
            + "\n\nSECRET-LIKE LINES:\n"
            + leads.grep_lines(ws, leads.RX_SECRET, limit=16, with_fn=True)
        ),
    ),
    Topic(
        "network",
        ("egress", "data_flow"),
        NETWORK_CARD,
        "network leads",
        lambda ws, known: (
            "ADDRESS LINES:\n"
            + leads.grep_lines(ws, leads.RX_NET, limit=18, with_fn=True)
            + "\n\nDATA ACCESS LINES:\n"
            + leads.grep_lines(ws, leads.RX_FLOW, suffix=(".py",), limit=20, with_fn=True)
        ),
    ),
)
