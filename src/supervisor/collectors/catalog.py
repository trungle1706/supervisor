"""Collector catalogue (WP38, ADR D28, docs/collectors.md): the ways to attach an agent.

A template is a card in the Integrations page. It has an id, a category, a short description, the
setup steps and a code snippet. The text is ours. The snippet holds two placeholders that the
console fills AFTER the credential exists:

* ``<SUPERVISOR_URL>``  the real base URL of this Supervisor;
* ``<AGENT_ID>``        the agent the credential was issued for.

The credential secret is never put in a snippet. Every snippet reads it from the environment
(``SUPERVISOR_AGENT_KEY`` or ``SUPERVISOR_AGENT_KEY_FILE``) and the console shows the secret once,
next to the steps. ``fail_mode`` is closed in every snippet.

Pure data and two small functions; no import of the server stack. The catalogue is served from
code, like the detector catalogue (WP37).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PLACEHOLDER_URL = "<SUPERVISOR_URL>"
PLACEHOLDER_AGENT = "<AGENT_ID>"
CATEGORIES = ("sdk", "middleware", "gateway", "mcp", "ide")
_AGENT_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}\Z")
# A base URL goes into code the person pastes: only characters that cannot break out of a string.
_URL_RE = re.compile(r"^https?://[A-Za-z0-9._~:/\[\]@%+-]{1,300}\Z")


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    category: str
    description: str
    steps: tuple[str, ...]
    snippet: str
    language: str = "python"
    available: bool = True
    availability_note: str = ""  # shown on the card when ``available`` is false
    module: str = ""  # the code that implements it (docs and tests)
    optional_deps: tuple[str, ...] = field(default_factory=tuple)  # NOT dependencies of Supervisor

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "steps": list(self.steps),
            "snippet": self.snippet,
            "language": self.language,
            "available": self.available,
            "availability_note": self.availability_note,
            "module": self.module,
            "optional_deps": list(self.optional_deps),
        }


_KEY_STEP = (
    "Give the agent process the secret shown once on this page: set SUPERVISOR_AGENT_KEY, or "
    "write it to a file with mode 600 and set SUPERVISOR_AGENT_KEY_FILE. Do not put it in code."
)
_POLICY_STEP = (
    "Make sure the tools of the agent are in the policy file (tools section) and the agent is "
    "in the agents section. Start with mode: observe for the agent if you want to watch first."
)

TEMPLATES: tuple[Template, ...] = (
    Template(
        id="python_sdk",
        name="Python SDK",
        category="sdk",
        description=(
            "Wrap each tool function of a Python agent. The gate is asked before the tool runs, "
            "and the call stops if the answer is block or pause."
        ),
        steps=(
            "Install Supervisor in the agent environment (it is the same package).",
            _KEY_STEP,
            "Create the gate once, at start up, and decorate each tool as in the snippet.",
            "Run one allowed call and one call the policy blocks. Look at both in Decisions.",
            _POLICY_STEP,
        ),
        snippet="""import os
from supervisor.gateway.ingress_sign import credential_from_env
from supervisor.gateway.sdk import HttpGate, SupervisorBlocked, supervised_tool, set_default_gate

AGENT_ID = "<AGENT_ID>"
set_default_gate(HttpGate("<SUPERVISOR_URL>", timeout_s=2.0,
                          credential=credential_from_env(AGENT_ID)))

@supervised_tool(AGENT_ID, "1", "transfer", "money")   # tool name and risk class as in the policy
def transfer(from_account_id: str, payee_id: str, amount_minor: int) -> str:
    ...

try:
    transfer("ACC-1", "PAYEE-9", 1000)
except SupervisorBlocked as stop:                      # SupervisorPaused is a subclass
    print(stop.decision["rule_id"], stop.decision["reason"])
""",
        module="supervisor.gateway.sdk",
    ),
    Template(
        id="langgraph_middleware",
        name="LangGraph and deepagents middleware",
        category="middleware",
        description=(
            "A middleware that wraps every tool call of a LangGraph or deepagents agent. It "
            "checks the arguments before and the output after, uses masked values when the "
            "gate returns them, and raises a typed exception on a pause."
        ),
        steps=(
            "Install Supervisor in the agent environment. LangGraph or LangChain must already be "
            "installed there; Supervisor does not install them.",
            _KEY_STEP,
            "Create the middleware and give it to the agent as in the snippet.",
            "Set consumer_id to the end user or channel if you want per-consumer policy.",
            "Catch SupervisorPaused where the agent answers the user, and show the reference id.",
            _POLICY_STEP,
        ),
        snippet="""from supervisor.gateway.ingress_sign import credential_from_env
from supervisor.gateway.sdk import HttpGate, SupervisorPaused
from supervisor.gateway.adapters.langgraph import SupervisorToolMiddleware

AGENT_ID = "<AGENT_ID>"
gate = HttpGate("<SUPERVISOR_URL>", timeout_s=2.0, credential=credential_from_env(AGENT_ID))
guard = SupervisorToolMiddleware(
    gate, AGENT_ID, "1",
    fail_mode="closed",                       # the default; money tools are closed even if "open"
    risk_classes={"transfer": "money"},
    consumer_id=lambda request: "web-banking",
)

agent = create_agent(model, tools, middleware=[guard.as_agent_middleware()])
# create_deep_agent(..., middleware=[guard.as_agent_middleware()]) works the same way.
# A plain ToolNode:  ToolNode(tools, wrap_tool_call=guard.wrap_tool_call)

try:
    agent.invoke({"messages": [("user", "pay 10,000 VND to Lan")]})
except SupervisorPaused as stop:
    print("Paused. Reference:", stop.decision["correlation_id"])
""",
        module="supervisor.gateway.adapters.langgraph",
        optional_deps=("langchain", "langgraph"),
    ),
    Template(
        id="fastapi_middleware",
        name="FastAPI middleware",
        category="middleware",
        description=(
            "Checks the traffic that reaches an agent application: the user request on the way "
            "in and the response on the way out. A blocked response never leaves the process."
        ),
        steps=(
            "Install Supervisor in the application environment.",
            _KEY_STEP,
            "Register a tool named http_inbound in the policy tools section (usually read_only).",
            "Add the middleware as in the snippet. Send the end user id in the X-Consumer-Id "
            "header.",
            "Note: a streamed response is held back until it has been checked.",
        ),
        snippet="""from fastapi import FastAPI
from supervisor.gateway.ingress_sign import credential_from_env
from supervisor.gateway.sdk import HttpGate
from supervisor.gateway.adapters.fastapi_mw import SupervisorASGIMiddleware

AGENT_ID = "<AGENT_ID>"
app = FastAPI()
app.add_middleware(
    SupervisorASGIMiddleware,
    gate=HttpGate("<SUPERVISOR_URL>", timeout_s=2.0, credential=credential_from_env(AGENT_ID)),
    agent_id=AGENT_ID,
    agent_version="1",
    fail_mode="closed",
)
""",
        module="supervisor.gateway.adapters.fastapi_mw",
        optional_deps=("fastapi",),
    ),
    Template(
        id="rest",
        name="REST call",
        category="gateway",
        description=(
            "Call the gate over HTTP from any language. One POST per tool call; the answer says "
            "allow, report, transform, pause, block or skip."
        ),
        steps=(
            _KEY_STEP,
            "With ingress authentication on, sign the request (see docs/ingress-auth.md); "
            "the Python SDK does this for you.",
            "Send the correlation id header so the call can be found in Decisions and Traces.",
            "Stop the tool call unless allow is true. Use transformed_payload when it is there.",
        ),
        snippet="""curl -sS -X POST "<SUPERVISOR_URL>/v1/gate/check" \\
  -H "Content-Type: application/json" \\
  -H "X-Supervisor-Correlation-Id: $(uuidgen | tr -d -)" \\
  -d '{
    "agent_id": "<AGENT_ID>",
    "agent_version": "1",
    "tool_name": "transfer",
    "args": {"from_account_id": "ACC-1", "payee_id": "PAYEE-9", "amount_minor": 1000},
    "context": {"consumer_id": "web-banking", "session_id": "chat-42"},
    "direction": "input"
  }'
# direction "output" checks what a tool returned: put the text in context.output
""",
        language="bash",
        module="supervisor.gateway.routes",
    ),
    Template(
        id="mcp_stdio_proxy",
        name="MCP proxy (stdio)",
        category="mcp",
        description=(
            "Put the gate in front of any MCP server that runs as a local process. Each "
            "tools/call goes through the gate first; a refused call is not forwarded."
        ),
        steps=(
            "Install Supervisor on the machine that starts the MCP server.",
            _KEY_STEP,
            "Register the tools of the MCP server in the policy tools section.",
            "Replace the server command of the MCP client with the proxy command in the snippet.",
        ),
        snippet="""python -m supervisor.gateway.mcp_proxy \\
  --agent-id <AGENT_ID> --agent-version 1 \\
  --gate-url <SUPERVISOR_URL> \\
  --key-file /secure/path/agent.key \\
  -- python -m your_mcp_server
""",
        language="bash",
        module="supervisor.gateway.mcp_proxy",
    ),
    Template(
        id="mcp_http_proxy",
        name="MCP proxy (HTTP)",
        category="mcp",
        description=(
            "The same gate for MCP servers that run over HTTP, with tool locking on the tool list."
        ),
        steps=(
            "This template is a placeholder until the HTTP MCP gateway (WP26) is merged.",
            "Then: register the server, lock its tool list, point the client to the proxy URL.",
        ),
        snippet="""# available after WP26
# MCP client -> <SUPERVISOR_URL>/mcp/<AGENT_ID>  -> your MCP server
""",
        language="text",
        available=False,
        availability_note="available after WP26",
        module="supervisor.gateway.mcp_http",
    ),
    Template(
        id="litellm_guardrail",
        name="LiteLLM guardrail",
        category="gateway",
        description=(
            "A custom guardrail for a LiteLLM proxy. Every model request is checked before it "
            "goes to the model, and every answer before it goes back to the caller."
        ),
        steps=(
            "Install Supervisor next to the LiteLLM proxy. LiteLLM must already be installed; "
            "Supervisor does not install it.",
            _KEY_STEP,
            "Register a tool named llm_request in the policy tools section.",
            "Create the guardrail in a small module and name it in the LiteLLM proxy config.",
            "Streaming answers are not checked: use a non-streaming route for money flows.",
        ),
        snippet="""# supervisor_guardrail.py
# name this module as a custom guardrail in the LiteLLM proxy config
from supervisor.gateway.ingress_sign import credential_from_env
from supervisor.gateway.sdk import HttpGate
from supervisor.gateway.adapters.litellm_guardrail import build_litellm_guardrail

AGENT_ID = "<AGENT_ID>"
supervisor_guardrail = build_litellm_guardrail(
    HttpGate("<SUPERVISOR_URL>", timeout_s=2.0, credential=credential_from_env(AGENT_ID)),
    AGENT_ID, "1",
    guardrail_name="supervisor",
    fail_mode="closed",
)
""",
        module="supervisor.gateway.adapters.litellm_guardrail",
        optional_deps=("litellm",),
    ),
    Template(
        id="claude_code_hook",
        name="Claude Code hook",
        category="ide",
        description=(
            "A PreToolUse hook for a developer's coding assistant. It asks the gate before each "
            "tool call and stops the call (exit code 2) on a block, a pause or an outage."
        ),
        steps=(
            "Install Supervisor on the developer machine, or ship it with the managed image.",
            "Set SUPERVISOR_URL, SUPERVISOR_AGENT_ID and the key (SUPERVISOR_AGENT_KEY_FILE) in "
            "the environment of the assistant.",
            "Add the hook to the assistant settings as in the snippet. Keep SUPERVISOR_FAIL_MODE "
            "unset (closed).",
            "Register the assistant tool names (for example Bash) in the policy tools section.",
        ),
        snippet="""# .claude/settings.json
# environment: SUPERVISOR_URL=<SUPERVISOR_URL>  SUPERVISOR_AGENT_ID=<AGENT_ID>
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {"type": "command", "command": "python -m supervisor.gateway.adapters.claude_code_hook"}
        ]
      }
    ]
  }
}
""",
        language="json",
        module="supervisor.gateway.adapters.claude_code_hook",
    ),
)

_BY_ID = {t.id: t for t in TEMPLATES}


def get(template_id: str) -> Template | None:
    return _BY_ID.get(template_id)


def by_category() -> list[tuple[str, list[Template]]]:
    """The templates grouped in the order of ``CATEGORIES`` (empty groups left out)."""
    return [
        (c, [t for t in TEMPLATES if t.category == c])
        for c in CATEGORIES
        if any(t.category == c for t in TEMPLATES)
    ]


class PlaceholderError(ValueError):
    """The URL or the agent id given for substitution is not safe to put in a snippet."""


def fill(text: str, supervisor_url: str, agent_id: str) -> str:
    """``text`` with the two placeholders replaced. The values are checked first, so a value
    cannot add a quote, a newline or a shell character to the snippet the person will paste."""
    if not _AGENT_RE.match(agent_id or ""):
        raise PlaceholderError("agent id must match [A-Za-z0-9_.:@-]{1,128}")
    url = (supervisor_url or "").rstrip("/")
    if not _URL_RE.match(url):
        raise PlaceholderError("base URL must be http(s) with plain URL characters")
    return text.replace(PLACEHOLDER_URL, url).replace(PLACEHOLDER_AGENT, agent_id)


def filled(template: Template, supervisor_url: str, agent_id: str) -> dict[str, Any]:
    """The template as a dict with the placeholders replaced in the snippet and the steps."""
    out = template.as_dict()
    out["snippet"] = fill(template.snippet, supervisor_url, agent_id)
    out["steps"] = [fill(s, supervisor_url, agent_id) for s in template.steps]
    return out


def catalogue() -> list[dict[str, Any]]:
    """All templates as dicts (placeholders still in place)."""
    return [t.as_dict() for t in TEMPLATES]
