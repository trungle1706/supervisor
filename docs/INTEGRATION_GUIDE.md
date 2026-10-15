# Integration guide for bank development teams

This guide shows how to connect an AI agent to Supervisor. It is for the team that owns the
agent code. Read it before you run the integration advisor or ask for onboarding.

Short rules used in this guide:

- Supervisor blocks or pauses with deterministic rules at the gate. Judges only advise.
- No gate means no call. A tool with no reachable gate is blocked (read-only tools excepted).
- Money is an integer in minor units. VND has no minor unit, so 1 VND = 1. Never use float.
- Commands use Windows cmd syntax and `python -m`. Do not set `DATABRICKS_TOKEN`.

## 1. Pick an integration pattern

| Pattern | What you change | What Supervisor gets | Use it when |
|---|---|---|---|
| A. In-process SDK | One decorator per tool, one hook module | Gate check before every tool call; optional traces | You own the Python code. This is the default and the strongest control. |
| B. OTLP traces | Tracer provider and exporter only | Recorded events (what happened). No blocking. | You cannot change tool code yet, or you want evidence first. Also use it with A. |
| C. MCP proxy | The command that starts the MCP server | Gate check on every `tools/call` | The tools live in an MCP server you do not want to edit, or the agent is not Python. |

Pattern A and B together is the normal target: A gives the block, B gives the record.

### Pattern A: in-process SDK

```text
 model -> framework tool router -> [framework decorator] -> supervised_tool wrapper
                                                                |  gate.check(...)
                                                                v
                                            Supervisor /gate/check (HttpGate)
                                                                |
                                       allow -> tool body runs  |  block -> SupervisorBlocked
```

### Pattern B: OTLP export

```text
 agent (OpenTelemetry SDK) --protobuf--> OTel Collector --OTLP/HTTP JSON--> Supervisor POST /v1/traces
                                                                                  |
                                                                       recorder -> agent_event rows
```

The Supervisor receiver accepts `application/json` only. It answers 415 to protobuf. The
Python OTLP/HTTP exporter sends protobuf. So put an OpenTelemetry Collector between them
(section 4), or export JSON from your own exporter.

### Pattern C: MCP proxy

```text
 MCP client --stdio--> supervisor.gateway.mcp_proxy --stdio--> your MCP server
                              |  tools/call only
                              v
                     Supervisor /gate/check     (denied call is not forwarded;
                                                 client gets isError: true + reason)
```

Use the proxy (pattern C) or the decorators on the tools (pattern A), not both. A tool that
is gated in code and by the proxy is checked twice, so daily totals count its calls twice.
The advisor lists the decorator patches and the proxy patch as alternatives.

The proxy command, in cmd syntax:

```cmd
python -m supervisor.gateway.mcp_proxy --agent-id <agent_id> --agent-version <version> --gate-url http://127.0.0.1:8000 -- python server.py
```

In an MCP client file (corpus example: `data/corpus/repos/fastmcp_account_tools/mcp.json`,
which starts the server with `"command": "python", "args": ["-m", "server"]`), the proxy
replaces the command and the old command moves behind `--`:

```json
{
  "mcpServers": {
    "tai-khoan": {
      "command": "python",
      "args": ["-m", "supervisor.gateway.mcp_proxy",
               "--agent-id", "account_tools", "--agent-version", "1.0.0",
               "--gate-url", "http://127.0.0.1:8000",
               "--", "python", "-m", "server"],
      "env": { "PG_DSN": "${PG_DSN}" }
    }
  }
}
```

Limits of the proxy: it sees the tool name and arguments only. It has no risk class, so
every tool fails closed when the gate is unreachable, read-only tools too. Only `tools/call`
is gated; `initialize`, `tools/list`, notifications and `ping` pass through.

## 2. Code samples per framework

### 2.1 The one placement rule

```text
@<framework decorator>                  <- stays first (for example @tool, @mcp.tool())
@supervised_tool(AGENT_ID, "<version>", "<tool_name>", "<risk_class>",
                 gate=supervisor_onboard.default_gate())      <- DIRECTLY above def
def the_tool(...):
```

- The framework registers the gated function. `functools.wraps` keeps the signature and
  the docstring, so the tool schema does not change.
- `<tool_name>` is the name the model calls and the name in the policy `tools:` map. It is
  not always the Python function name. Each sample below says which name it uses.
- `<risk_class>` is one of `read_only`, `money`, `credit`, `pii_export`.
- Dispatch-dict and schema-list frameworks (openai, anthropic, MLflow) do not decorate the
  schema. Decorate the function that the dict points to.
- Async tools: `supervised_tool` supports `async def`. The gate call runs in a worker
  thread, so the event loop is not blocked. Use it the same way.
- Every sample imports the hook module that Onboard generates. If you do not have it yet,
  run the advisor (section 5); its patches create `supervisor_onboard.py`.

The hook module gives two functions:

| Function | Result |
|---|---|
| `supervisor_onboard.default_gate()` | An `HttpGate` when env `SUPERVISOR_GATE_URL` is set. Else `None` (then every gated call is blocked: no gate, no call). |
| `supervisor_onboard.default_tracer_provider()` | A tracer provider tagged with the agent id when env `SUPERVISOR_TRACING=1`. Else `None`. |

`default_gate()` runs when the module is imported. Set `SUPERVISOR_GATE_URL` before the
agent process starts:

```cmd
set SUPERVISOR_GATE_URL=http://127.0.0.1:8000
set SUPERVISOR_TRACING=1
```

### 2.2 Framework table

| Framework | How the corpus repo registers tools | Cited file | Gate tool name |
|---|---|---|---|
| LangGraph | `@tool` from `langchain_core.tools`; list passed to `ToolNode` | `data/corpus/repos/langgraph_loan_triage/tools.py` | function name |
| LangChain | `@tool("name")` from `langchain_core.tools` | `data/corpus/repos/langchain_card_support/tools.py` | the string in `@tool("...")` |
| LlamaIndex | plain function wrapped by `FunctionTool.from_defaults(fn=...)` | `data/corpus/repos/llamaindex_policy_qa/agent.py` (registration), `tools.py` (function) | `name=` if given, else function name |
| openai SDK | `TOOLS` schema list plus `DISPATCH` dict | `data/corpus/repos/openai_fx_quotes/agent.py` | schema name = `DISPATCH` key |
| anthropic SDK | `TOOLS` schema list plus `HANDLERS` dict | `data/corpus/repos/anthropic_dispute_helper/agent.py` | schema name = `HANDLERS` key |
| MLflow ChatAgent | `TOOL_SPECS` dict of `fn` and `spec` | `data/corpus/repos/mlflow_chatagent_savings/tools.py` | `TOOL_SPECS` key |
| FastMCP | `@mcp.tool()` or `@mcp.tool(name="...")` | `data/corpus/repos/fastmcp_account_tools/server.py` | `name=` if given, else function name |
| FastAPI tools | `@app.get(...)` / `@app.post(...)` routes | `data/corpus/repos/fastapi_toolserver_remit/server.py` | last path part, for example `send_remittance` |

### 2.3 LangGraph

Corpus: `langgraph_loan_triage/tools.py` registers `@tool` functions in `ALL_TOOLS`, and
`graph.py` builds `ToolNode(ALL_TOOLS)`. Nothing else changes in `graph.py`.

<!-- sample: langgraph_loan_triage/tools.py -->
<!-- registers: decorator:tool, def:record_preapproval_decision -->
```python
import supervisor_onboard
from langchain_core.tools import tool
from supervisor.gateway.sdk import supervised_tool
from supervisor_onboard import AGENT_ID


@tool
@supervised_tool(
    AGENT_ID,
    "1.0.0",
    "record_preapproval_decision",
    "credit",
    gate=supervisor_onboard.default_gate(),
)
def record_preapproval_decision(application_id: str, decision: str, approved_limit_vnd: int) -> str:
    """Record the pre-approval decision (approve, decline or refer) and the limit."""
    ...  # body unchanged
```

Tracing: the same repo has `tracing.py` with the OpenTelemetry setup (see 2.11).

### 2.4 LangChain

Corpus: `langchain_card_support/tools.py`. The tool `block_card` is registered as
`@tool("khoa_the_tam_thoi")`, so the model and the policy know it as `khoa_the_tam_thoi`.
Use that string as the gate tool name, not `block_card`.

<!-- sample: langchain_card_support/tools.py -->
<!-- registers: decorator:tool, def:block_card -->
```python
import supervisor_onboard
from langchain_core.tools import tool
from supervisor.gateway.sdk import supervised_tool
from supervisor_onboard import AGENT_ID


@tool("khoa_the_tam_thoi")
@supervised_tool(
    AGENT_ID,
    "1.0.0",
    "khoa_the_tam_thoi",
    "pii_export",
    gate=supervisor_onboard.default_gate(),
)
def block_card(card_id: str, card_number: str, reason: str) -> str:
    """Temporarily block a card. The customer can unlock it at a branch."""
    ...  # body unchanged
```

### 2.5 LlamaIndex

Corpus: the functions in `llamaindex_policy_qa/tools.py` are plain functions. They are
registered in `agent.py` with `FunctionTool.from_defaults(fn=tra_cuu_bieu_phi, name="tra_cuu_phi_the", ...)`.
Decorate the function in `tools.py`. `agent.py` does not change. The gate tool name is the
`name=` given to `from_defaults` (`tra_cuu_phi_the`).

<!-- sample: llamaindex_policy_qa/tools.py -->
<!-- registers: def:tra_cuu_bieu_phi -->
```python
import csv

import supervisor_onboard
from supervisor.gateway.sdk import supervised_tool
from supervisor_onboard import AGENT_ID


@supervised_tool(
    AGENT_ID,
    "1.0.0",
    "tra_cuu_phi_the",
    "read_only",
    gate=supervisor_onboard.default_gate(),
)
def tra_cuu_bieu_phi(loai_the: str) -> str:
    """Look up the annual fee of a card type in the local fee table."""
    ...  # body unchanged
```

This registration stays as it is in the corpus (shown so you can see that the gated
function is the one passed in `fn=`):

<!-- sample: llamaindex_policy_qa/agent.py -->
<!-- registers: call:FunctionTool.from_defaults -->
```python
from llama_index.core.tools import FunctionTool

from tools import tra_cuu_bieu_phi

fee_tool = FunctionTool.from_defaults(
    fn=tra_cuu_bieu_phi,
    name="tra_cuu_phi_the",
    description="Tra phi thuong nien theo loai the.",
)
```

### 2.6 openai SDK

Corpus: `openai_fx_quotes/agent.py` keeps a `TOOLS` schema list and a `DISPATCH` dict
(`schema name -> implementation`). The loop calls `DISPATCH[call.function.name](**args)`.
The schema name is the gate tool name. The names differ from the functions:
`chuyen_tien_ngoai_te` is implemented by `thuc_hien_chuyen_tien` in `tools.py`.

Decorate the implementing function in `tools.py`. The corpus function has `amount: float`.
Money must be an integer, and the gateway reads `amount_minor`. So the sample renames the
argument and types it `int`. Change the same name and type (`"type": "integer"`) in the
`TOOLS` schema, because the loop passes the model arguments as keywords.

<!-- sample: openai_fx_quotes/tools.py -->
<!-- registers: def:thuc_hien_chuyen_tien -->
```python
import supervisor_onboard
from supervisor.gateway.sdk import supervised_tool
from supervisor_onboard import AGENT_ID


@supervised_tool(
    AGENT_ID,
    "1.0.0",
    "chuyen_tien_ngoai_te",
    "money",
    gate=supervisor_onboard.default_gate(),
)
def thuc_hien_chuyen_tien(quote_id: str, so_tai_khoan: str, payee_name: str, amount_minor: int) -> dict:
    """Execute the FX transfer to the beneficiary account."""
    ...  # body unchanged, payload uses amount_minor
```

The dispatch dict in `agent.py` does not change:

<!-- sample: openai_fx_quotes/agent.py -->
<!-- registers: dict:DISPATCH -->
```python
from tools import lay_ty_gia, luu_bao_gia, thuc_hien_chuyen_tien

DISPATCH = {
    "lay_ty_gia": lay_ty_gia,
    "dat_bao_gia": luu_bao_gia,
    "chuyen_tien_ngoai_te": thuc_hien_chuyen_tien,
}
```

### 2.7 anthropic SDK

Corpus: `anthropic_dispute_helper/agent.py` keeps a `TOOLS` list (with `input_schema`) and a
`HANDLERS` dict. The loop calls `HANDLERS[block.name](**block.input)`. Decorate the handler
function in `actions.py`. The gate runs before the function body, so before the human
approval prompt inside `mo_khieu_nai`.

<!-- sample: anthropic_dispute_helper/actions.py -->
<!-- registers: def:mo_khieu_nai -->
```python
import supervisor_onboard
from supervisor.gateway.sdk import supervised_tool
from supervisor_onboard import AGENT_ID


@supervised_tool(
    AGENT_ID,
    "1.0.0",
    "mo_khieu_nai",
    "money",
    gate=supervisor_onboard.default_gate(),
)
def mo_khieu_nai(customer_id: str, transaction_id: str, reason: str) -> dict:
    """Open a dispute case."""
    ...  # body unchanged
```

<!-- sample: anthropic_dispute_helper/agent.py -->
<!-- registers: dict:HANDLERS -->
```python
from actions import doc_giao_dich, hoan_phi, mo_khieu_nai

HANDLERS = {"doc_giao_dich": doc_giao_dich, "mo_khieu_nai": mo_khieu_nai, "hoan_phi": hoan_phi}
```

### 2.8 MLflow ChatAgent

Corpus: `mlflow_chatagent_savings/tools.py` keeps `TOOL_SPECS = {name: {"fn": function, "spec": {...}}}`.
`SavingsAgent.__init__` in `agent.py` builds `self.tools = {name: t["fn"] for name, t in TOOL_SPECS.items()}`
and `predict` calls `self.tools[call["function"]["name"]](**args)`. Decorate the function
that `"fn"` points to. In a Databricks serving endpoint, set `SUPERVISOR_GATE_URL` in the
endpoint environment.

As in 2.6, rename the amount to `amount_minor` in the function and in the `spec`.

<!-- sample: mlflow_chatagent_savings/tools.py -->
<!-- registers: def:mo_tiet_kiem, dict:TOOL_SPECS -->
```python
import supervisor_onboard
from supervisor.gateway.sdk import supervised_tool
from supervisor_onboard import AGENT_ID


@supervised_tool(
    AGENT_ID,
    "1.0.0",
    "mo_tiet_kiem",
    "money",
    gate=supervisor_onboard.default_gate(),
)
def mo_tiet_kiem(customer_id: str, so_tai_khoan: str, amount_minor: int, term_months: int) -> dict:
    """Open a term deposit funded from the customer's own account."""
    ...  # body unchanged


TOOL_SPECS = {
    "mo_tiet_kiem": {
        "fn": mo_tiet_kiem,
        "spec": {
            "type": "function",
            "function": {
                "name": "mo_tiet_kiem",
                "description": "Open a term deposit from the customer's own account.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "so_tai_khoan": {"type": "string"},
                        "amount_minor": {"type": "integer"},
                        "term_months": {"type": "integer"},
                    },
                    "required": ["customer_id", "so_tai_khoan", "amount_minor", "term_months"],
                },
            },
        },
    },
}
```

### 2.9 FastMCP

Corpus: `fastmcp_account_tools/server.py` uses `@mcp.tool()` and, for a renamed tool,
`@mcp.tool(name="tra_cuu_giao_dich")`. The gate tool name is the `name=` value when there
is one, else the function name. FastMCP builds the schema from the signature, so the
renamed `amount_minor: int` shows in the schema.

<!-- sample: fastmcp_account_tools/server.py -->
<!-- registers: decorator:mcp.tool, def:transfer_to_beneficiary -->
```python
import supervisor_onboard
from fastmcp import FastMCP
from supervisor.gateway.sdk import supervised_tool
from supervisor_onboard import AGENT_ID

mcp = FastMCP("tai-khoan")


@mcp.tool()
@supervised_tool(
    AGENT_ID,
    "1.0.0",
    "transfer_to_beneficiary",
    "money",
    gate=supervisor_onboard.default_gate(),
)
def transfer_to_beneficiary(
    customer_id: str, from_account: str, to_account: str, amount_minor: int, memo: str = ""
) -> dict:
    """Move money from a customer account to a saved beneficiary account."""
    ...  # body unchanged
```

A blocked call raises `SupervisorBlocked`. FastMCP turns an exception in a tool into a
tool error for the model. If you prefer a clean text, catch it in a small wrapper and
return `{"error": "blocked_by_supervisor", "rule_id": exc.decision.get("rule_id")}`.

If you cannot edit this server, use pattern C (section 1) instead.

### 2.10 FastAPI tools

Corpus: `fastapi_toolserver_remit/server.py` registers each tool as a route:
`@app.get("/tools/quote_fee")`, `@app.post("/tools/send_remittance")`. The route
`send_remittance(req: RemitRequest)` takes a Pydantic model. The gate sends the arguments
as JSON, and a Pydantic object is not JSON. If you decorate that route directly, the gate
call fails and the tool is blocked every time (fail closed).

So gate a small function with plain arguments and call it from the route:

<!-- sample: fastapi_toolserver_remit/server.py -->
<!-- registers: decorator:app.post, def:send_remittance, call:HTTPException -->
```python
import requests
import supervisor_onboard
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from models import RemitRequest
from supervisor.gateway.sdk import SupervisorBlocked, supervised_tool
from supervisor_onboard import AGENT_ID

app = FastAPI(title="remit-toolserver")


@app.exception_handler(SupervisorBlocked)
async def supervisor_blocked_handler(request: Request, exc: SupervisorBlocked) -> JSONResponse:
    # SupervisorPaused is a subclass, so a paused agent also gets 403.
    return JSONResponse(
        status_code=403,
        content={
            "error": "blocked_by_supervisor",
            "rule_id": exc.decision.get("rule_id"),
            "reason": exc.decision.get("reason"),
        },
    )


@supervised_tool(
    AGENT_ID,
    "1.0.0",
    "send_remittance",
    "money",
    gate=supervisor_onboard.default_gate(),
)
def gated_send_remittance(
    customer_id: str,
    payee_name: str,
    beneficiary_account: str,
    amount_minor: int,
    currency: str,
) -> dict:
    resp = requests.post(
        "https://core.nganhang.internal/api/v1/remittances",
        json={
            "customer_id": customer_id,
            "payee_name": payee_name,
            "beneficiary_account": beneficiary_account,
            "amount": amount_minor,
            "currency": currency,
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="core rejected the remittance")
    return {"status": "sent", "reference": resp.json().get("reference")}


@app.post("/tools/send_remittance")
def send_remittance(req: RemitRequest) -> dict:
    """Send money abroad to the beneficiary account of the order."""
    return gated_send_remittance(
        customer_id=req.customer_id,
        payee_name=req.payee_name,
        beneficiary_account=req.beneficiary_account,
        amount_minor=req.amount,
        currency=req.currency,
    )
```

Notes:

- This is the one case where `@supervised_tool` is not on the function under the framework
  decorator. The reason is the Pydantic body. For routes that take plain query or path
  arguments (like `quote_fee(amount: int, currency: str = "USD")`), use the normal rule
  and put `@supervised_tool` directly under `@app.get(...)`.
- The exception handler maps a block or a pause to HTTP 403. Your client must treat 403 with
  `error: blocked_by_supervisor` as "do not retry".
- For an `async def` route, `supervised_tool` works unchanged.

### 2.11 Pattern B samples: tracing

Two parts. First, the tracer provider and the exporter. The corpus file
`langgraph_loan_triage/tracing.py` already has this shape. Point the endpoint to a
Collector (see section 4), which forwards JSON to `<supervisor>/v1/traces`.

<!-- sample: langgraph_loan_triage/tracing.py -->
<!-- registers: call:OTLPSpanExporter, call:TracerProvider, call:BatchSpanProcessor -->
```python
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_tracing(agent_id: str, agent_version: str) -> trace.Tracer:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": agent_id,
                "supervisor.agent_id": agent_id,
                "supervisor.agent_version": agent_version,
            }
        )
    )
    # OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://collector.bank.internal:4318/v1/traces
    exporter = OTLPSpanExporter(endpoint=os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"])
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(agent_id)
```

Second, one span per tool call with the attributes the recorder reads. The corpus file
`fastmcp_account_tools/server.py` already opens a span in each tool with
`tracer.start_as_current_span(...)` and `span.set_attribute(...)`. Add the `supervisor.*`
and `gen_ai.*` names:

<!-- sample: fastmcp_account_tools/server.py -->
<!-- registers: call:tracer.start_as_current_span, call:span.set_attribute -->
```python
from opentelemetry import trace

tracer = trace.get_tracer("tai_khoan.mcp")


def traced_transfer(customer_id: str, amount_minor: int) -> None:
    with tracer.start_as_current_span("execute_tool transfer_to_beneficiary") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", "transfer_to_beneficiary")
        span.set_attribute("supervisor.event_type", "tool_call")
        span.set_attribute("supervisor.tool_name", "transfer_to_beneficiary")
        span.set_attribute("supervisor.amount_minor", amount_minor)  # int, not float
        span.set_attribute("supervisor.currency", "VND")
```

A call that the gate blocks never reaches the tool body, so it makes no span there. The
gateway records its own decision for every check.

MLflow-only tracing counts 12 of 20 tracing points in the rubric (section 6), because the
recorder reads OpenTelemetry spans. Add the spans above next to the MLflow tracing.

### 2.12 Demo agents: how the repo wires the gate

The three demo agents (`src/supervisor_agents/payments`, `customer_service`,
`credit_prequal`) all use one builder shape. This is the shape the codemod looks for.

| Part | Demo agent | Your agent after the patch |
|---|---|---|
| Builder | `build_agent(chat, world, *, gate=None, tracer_provider=None, env="dev")` | A function with a `gate` parameter (and optionally `tracer_provider`) |
| Gate call | The agent runtime calls `gate.check(agent_id, agent_version, tool, args, context)` before each tool | `supervised_tool` calls the same method with the same five values |
| Default | `AllowAllHook` when no gate is passed (demo and test only) | `supervisor_onboard.default_gate()`; no gate means blocked |
| Tracing | The runtime opens an `execute_tool <name>` span with `supervisor.*` and `gen_ai.*` attributes | Your tracer provider plus the spans of 2.11 |

The patch for a builder function inserts these lines (marker `# supervisor-onboard: hook`):

```text
gate = gate if gate is not None else supervisor_onboard.default_gate()
tracer_provider = tracer_provider if tracer_provider is not None else supervisor_onboard.default_tracer_provider()
```

## 3. What the gate needs from a tool call

`POST <supervisor>/gate/check` takes this JSON. `HttpGate` and `InProcessGate` send it for
you. A custom client must send the same fields.

| Field | Rule |
|---|---|
| `agent_id` | The id in the Supervisor policy `agents:` map and in the manifest. |
| `agent_version` | The deployed version string, for example `1.0.0`. |
| `tool_name` | Exactly the name in the policy `tools:` map. A name that is not in the map is an unknown tool. |
| `args` | A JSON object (a dict). Plain values only: no Pydantic objects, no classes, no bytes. |
| `context` | Optional. `supervised_tool` sends `declared_risk_class`. |

What the rules read from `args`:

| Argument | Used for | Rule |
|---|---|---|
| `amount_minor` | Limits, daily and hourly totals (`sum`) | Integer minor units. A float or a string is not an amount: the limit rule cannot read it. `True` and `False` are not integers. |
| `currency` | Currency of the amount | Three upper-case letters, for example `VND`. |
| Destination and customer arguments | Rules named in the policy: `from_account_id`, `payee_id`, `customer_id`, `account_id` in `policies/baseline.yaml` | The name in your code must equal the name the rule reads. A rule can read any argument by name (`arg:`), and totals group by the `customer_arg` and `also_by` names in the rule. |
| `<source>_id` | Fact look-ups (`fact.<source>.<field>`) | The id must be a clean string with no spaces. A missing fact blocks the call. |

Amounts, in practice:

| Currency | Amount | Send as |
|---|---|---|
| VND | 50,000 VND | `amount_minor=50000` (no minor unit) |
| USD | 12.50 USD | `amount_minor=1250` (cents) |
| Any | an amount in a float | Convert at the edge. Do not pass float to the gate or to the policy. |

Fail modes when the gate is slow, down or answers badly (default timeout 2 seconds):

| Tool risk class | Gate unreachable | Rule id in the decision |
|---|---|---|
| `read_only` | Fails open: the call is allowed with an alert. | `GATE-UNREACHABLE` |
| `money`, `credit`, `pii_export` | Fails closed: the call is blocked. | `GATE-UNREACHABLE` |
| Any tool, no gate configured | Blocked. | `GATE-MISSING` |
| Any tool, gate code error in-process | Blocked. | `GATE-ERROR` |

`default_gate()` passes a map of tool name to risk class (`TOOL_RISK`) to `HttpGate`. That
map is how the SDK knows which tools may fail open. The MCP proxy has no map, so all its
tools fail closed.

Other behaviour to know:

- A paused agent raises `SupervisorPaused` (a subclass of `SupervisorBlocked`).
- `SupervisorBlocked.decision` holds `allow`, `action`, `rule_id`, `reason`.
- New agents start in `SHADOW`: rules are evaluated and recorded, nothing is blocked. The
  owner switches rules to enforced mode later, with two approvers.

## 4. What the recorder needs from a span

The recorder takes OTLP spans, turns each one into one `agent_event` row, and ignores spans
that have no agent id or no event type. It stores digests by default, not text.

How to send spans to Supervisor:

```cmd
set OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:8000/v1/traces
set OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json
```

Use these two settings for SDKs that can export JSON. The Python OTLP/HTTP exporter cannot:
it sends protobuf, and the receiver answers 415. For Python agents, send to a Collector
and let the Collector re-encode as JSON:

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  otlphttp/supervisor:
    traces_endpoint: http://<supervisor-host>:8000/v1/traces
    encoding: json
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp/supervisor]
```

(Check this Collector config against the bank's approved build. The `otlphttp` exporter with
`encoding: json` is in the standard distribution.)

Receiver answers: 200 for a valid batch (store down: rows are spooled, still 200); 415 for
protobuf; 400 for bad JSON, a body over `OTLP_MAX_BODY_BYTES`, or more spans than
`OTLP_MAX_SPANS`. `Content-Encoding: gzip` is accepted.

Generated from `supervisor.recorder.semconv` (`MAPPING`, `EMIT`, `SUPERVISOR_ATTRS`).
Spec version: semantic-conventions-genai (semconv v1.44.0 links), read 2026-10-15. Every `gen_ai.*` attribute is in *development* status
in that spec, so names can change. The setting `RECORDER_SEMCONV` (default on) turns this
mapping on. Our `supervisor.*` names always win over a `gen_ai.*` name. A deprecated name
is copied to the current name only when the current name is absent. The operation, tool,
agent and model are also read from the span name (`chat <model>`, `execute_tool <tool>`,
`invoke_agent <agent>`) when the attribute is missing.

### 4.0 GenAI attributes and the `agent_event` column they fill

| GenAI attribute | agent_event column | Status | Note |
|---|---|---|---|
| `gen_ai.operation.name` | `event_type` | development | chat/text_completion/generate_content -> llm_call; execute_tool -> tool_call; invoke_agent/create_agent -> message (handoff when a caller agent is set) |
| `gen_ai.agent.id` | `agent_id` | development | after supervisor.agent_id |
| `gen_ai.agent.name` | `agent_id` | development | last fallback, after the resource agent_id; span name 'invoke_agent {name}' gives it |
| `gen_ai.agent.version` | `agent_version` | development | after supervisor.agent_version |
| `gen_ai.tool.name` | `tool_name` | development | span name 'execute_tool {tool}' also gives it |
| `gen_ai.tool.call.arguments` | `args_masked` | development | opt-in; args_hash is computed, masked text follows the capture level |
| `gen_ai.tool.call.result` | `result_masked` | development | opt-in; masked text follows the capture level |
| `gen_ai.input.messages` | `args_masked` | development | opt-in; same path as arguments |
| `gen_ai.output.messages` | `result_masked` | development | opt-in; same path as result |
| `error.type` | `status` | stable | present -> status 'error' (unless supervisor.status) |
| `gen_ai.provider.name` | not mapped | development | not mapped (no column) |
| `gen_ai.system` | not mapped | deprecated | alias of gen_ai.provider.name; not mapped |
| `gen_ai.request.model` | not mapped | development | not mapped; with CLIENT kind it implies llm_call |
| `gen_ai.response.model` | not mapped | development | not mapped (no column) |
| `gen_ai.usage.input_tokens` | not mapped | development | not mapped (no column) |
| `gen_ai.usage.output_tokens` | not mapped | development | not mapped (no column) |
| `gen_ai.usage.prompt_tokens` | not mapped | deprecated | alias of input_tokens; not mapped |
| `gen_ai.usage.completion_tokens` | not mapped | deprecated | alias of output_tokens; not mapped |
| `gen_ai.response.finish_reasons` | not mapped | development | not mapped (no column) |
| `gen_ai.conversation.id` | not mapped | development | not mapped (trace_id groups events) |
| `gen_ai.tool.call.id` | not mapped | development | not mapped (span_id is the event key) |
| `gen_ai.tool.type` | not mapped | development | not mapped (no column) |

Not mapped to a column (the recorder keeps no column for them): `gen_ai.provider.name`, `gen_ai.system`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.prompt_tokens`, `gen_ai.usage.completion_tokens`, `gen_ai.response.finish_reasons`, `gen_ai.conversation.id`, `gen_ai.tool.call.id`, `gen_ai.tool.type`.

### 4.0.1 What to emit per span type

| Span type (`gen_ai.operation.name`) | Attributes to emit |
|---|---|
| `chat` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons`, `gen_ai.agent.id`, `gen_ai.conversation.id`, `error.type` |
| `execute_tool` | `gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.tool.type`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`, `gen_ai.agent.id`, `gen_ai.conversation.id`, `error.type` |
| `invoke_agent` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.agent.id`, `gen_ai.agent.name`, `gen_ai.agent.version`, `gen_ai.conversation.id`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `error.type` |

Also emit these `supervisor.*` attributes on every span:

| Attribute |
|---|
| `supervisor.agent_id` |
| `supervisor.agent_version` |
| `supervisor.caller_agent_id` |
| `supervisor.event_type` |
| `supervisor.args_hash` |
| `supervisor.amount_minor` |
| `supervisor.currency` |
| `supervisor.env` |

### 4.1 All attributes the recorder reads (including fallbacks)

| Row field | Supervisor name | OpenTelemetry GenAI name (fallback) | Notes |
|---|---|---|---|
| agent id | `supervisor.agent_id` | `gen_ai.agent.id`; resource attribute `supervisor.agent_id` | Needed. Without it the span is ignored. |
| agent version | `supervisor.agent_version` | none | |
| caller agent id | `supervisor.caller_agent_id` | none | Marks a handoff between agents. |
| event type | `supervisor.event_type` | from `gen_ai.operation.name` | One of `llm_call`, `tool_call`, `message`, `handoff`. Needed (explicit or inferred). |
| tool name | `supervisor.tool_name` | `gen_ai.tool.name` | Must match the policy `tools:` map. |
| tool arguments | `supervisor.args` | `gen_ai.tool.call.arguments`, `supervisor.message.text`, `gen_ai.input.messages` | Masked or dropped by the capture level. |
| tool result | `supervisor.result` | `gen_ai.tool.call.result`, `gen_ai.output.messages` | Masked or dropped by the capture level. |
| arguments hash | `supervisor.args_hash` | none | 64 hex characters (SHA-256 or HMAC-SHA-256 of the canonical arguments). |
| amount | `supervisor.amount_minor` | none | Integer attribute only. A float or a string is dropped. |
| currency | `supervisor.currency` | none | Three upper-case letters. |
| status | `supervisor.status` | span status `ERROR` gives `error` | |
| environment | `supervisor.env` | resource attribute `supervisor.env` | Default is the receiver default. |
| classification | `supervisor.classification` | none | |
| capture level | `supervisor.capture_level` | none | Can only ask for a lower level than the agent manifest allows. |
| trace and span ids | span ids | span ids | `event_id` is `<trace_id>-<span_id>`. The same span twice gives one row. |

Identifier values (agent id, version, tool, env, status) may use letters, digits and
`_ . : / @ + -`, up to 128 characters. Anything else is dropped.

### 4.2 Event type when `supervisor.event_type` is not set

| `gen_ai.operation.name` and other attributes | Event type |
|---|---|
| `execute_tool`, or any `gen_ai.tool.name` / `supervisor.tool_name` | `tool_call` |
| `chat`, `text_completion`, `generate_content`, `completion`; or span kind CLIENT with `gen_ai.request.model` | `llm_call` |
| `handoff`, or `invoke_agent` with `supervisor.caller_agent_id` | `handoff` |
| `invoke_agent`, `create_agent`, or `supervisor.message.role` | `message` |
| none of the above | span ignored |

Setting `supervisor.event_type` yourself is the safest choice.

## 5. Run the integration advisor

The advisor reads a repo (read-only), finds the tools and the gaps, scores readiness, and
writes patches. It never changes your repo. You review the patches and apply them yourself.

```cmd
cd C:\work\supervisor
uv run python -m supervisor.advisory.integration --target C:\path\to\repo --out out\integration\<name> --mock-llm
```

| Output in `--out` | Content |
|---|---|
| `integration_report.json` | Machine-readable findings and score |
| `integration_report.md` | The same for people |
| `integration_report.html` | The same, as one page |
| `patches\NN-*.patch` | One patch per change. Not applied. |

Apply a patch after review, from the target repo:

```cmd
cd C:\path\to\repo
git apply --check C:\work\supervisor\out\integration\<name>\patches\01-<name>.patch
git apply C:\work\supervisor\out\integration\<name>\patches\01-<name>.patch
```

`--mock-llm` uses no model: the narrative is a fixed text and is labelled `mock`. Without
it the model writes only the narrative. Every number and every patch comes from static
analysis and is the same on each run.

To measure how well the code analysis works on the labelled corpus, run the onboard eval
(method and gates in `docs/onboard-eval.md`):

```cmd
uv run python -m supervisor.onboard.eval --corpus data\corpus\repos --labels data\corpus\labels.yaml --report out\corpus-eval
```

Settings (environment variables or `.env`; all new features are off by default):

| Setting | Default | Effect |
|---|---|---|
| `CONSOLE_INTEGRATION_ENABLED` | off | Shows the "Integration" tab in the reviewer console. It reads reports from `INTEGRATION_REPORTS_DIR`. |
| `ONBOARD_ADVISOR_ENABLED` | off | Runs the advisor as a stage of onboarding. The report becomes an onboarding artefact. |
| `INTEGRATION_REPORTS_DIR` | `<data_dir>\integration` | Where the console looks for reports. |
| `RECORDER_SEMCONV` | on | Maps OpenTelemetry GenAI (`gen_ai.*`) attributes to `agent_event` columns. Off keeps the older partial mapping. See `docs/recorder.md`. |
| `SUPERVISOR_GATE_URL` | unset | Read by `supervisor_onboard.default_gate()` in your agent process. |
| `SUPERVISOR_TRACING` | unset | `1` makes `default_tracer_provider()` return a provider. |

## 6. Readiness rubric

The score is a number from 0 to 100. It is advisory. It does not approve or reject an
onboarding. It tells the team what to fix first.

| area | weight | points |
|---|---|---|
| tracing | 20 | OpenTelemetry tracing found = 20; MLflow tracing only = 12; none = 0 |
| gate_coverage | 30 | gated tools = risk class money, credit or pii_export, or any tool with a write side effect found in its body (db, http, bank API or file write, or an in-memory mutation); 30 * covered // gated, covered = the tool function already carries a Supervisor gate (`supervised_tool` or a `.check(` call on a gate inside the function), or the repo has a central dispatch gate (a `.check(` call on a name containing `gate` with at least 4 positional arguments, `safe_check(<gate>, ...)` with at least 5, or `build_runtime(..., gate=...)` / `AgentRuntime(..., gate=...)`), which covers every tool; no gated tools = 30 |
| tool_inventory | 15 | 15 * tools whose implementing function was found // all tools; no tools = 0 |
| money_args | 10 | per money tool 5 for an amount argument not typed float + 5 for a destination argument; 10 * earned // (10 * money tools); no money tools = 10 |
| model_identity | 10 | 10 * LLM call sites with a known model family // all; none = 10 |
| manifest | 10 | Supervisor agent manifest present = 10 |
| hygiene | 5 | no secret redacted and no injection line flagged = 5 |

Rules of the arithmetic: integers only, `//` rounds down, the total is the sum of the seven
areas (0 to 100). Every input comes from static analysis. The LLM writes only the narrative.

| Total | Band | Meaning |
|---|---|---|
| 80-100 | Ready for shadow onboarding | Start in SHADOW. Fix the open findings in parallel. |
| 50-79 | Needs the patches | Review and apply the patches, then run the advisor again. |
| 0-49 | Needs work first | Missing tracing, gates or tool inventory. Fix these before you ask for onboarding. |

The bands are advice. A score of 100 does not replace the checklist in section 8.

## 7. Assurance test plan dimensions

The advisor's test plan lists the dimensions below for each agent. Another work package
builds the test packs. This table says when a dimension normally applies.

| Dimension | Applies when |
|---|---|
| `accuracy` | Always. The agent answers or acts, so it needs tasks with known good outcomes. |
| `hallucination` | The agent writes free text to customers or staff, or answers from documents (retrieval). |
| `bias_fairness` | The agent's output affects a person: credit, pricing, limits, collections, complaints. |
| `dependency_risk` | The agent depends on an external model endpoint, an external API, or packages that can change under it. |
| `adversarial_security` | The agent reads untrusted text (emails, tickets, web pages, documents) or has tools that write or move money. |
| `robustness` | Always for agents with tools: typos, missing diacritics, long inputs, tool errors, repeated calls. |

## 8. Checklist before onboarding

The owner and a second approver sign. Do not start SHADOW with an open line.

| # | Check | Done |
|---|---|---|
| 1 | Owner named (user and team) in the manifest and in the policy `agents:` entry | [ ] |
| 2 | Second approver named. Every `FILL-ME-approver` is replaced by two real approvers | [ ] |
| 3 | Every `FILL-ME-...` value in the patches, policy and alert routes is replaced | [ ] |
| 4 | Every amount is an integer in minor units (VND: 1 VND = 1). No float anywhere on a money path | [ ] |
| 5 | Money tools use the argument names the rules read (`amount_minor`, destination, customer) | [ ] |
| 6 | Tool names in code, schema and the policy `tools:` map are identical (check renamed tools: `@tool("x")`, `name=`, dispatch keys) | [ ] |
| 7 | Every tool has the correct risk class. Money, credit and personal-data tools are not `read_only` | [ ] |
| 8 | Agent starts in `SHADOW`. Enforced mode is a separate, later step with two approvers | [ ] |
| 9 | `SUPERVISOR_GATE_URL` is set in the real process. A test call shows a gate decision | [ ] |
| 10 | Tracing reaches `/v1/traces`: a test call makes an `agent_event` row (check the response header `X-Supervisor-Accepted`) | [ ] |
| 11 | The gate failure behaviour was tested: stop the gateway, a money tool is blocked, a read-only tool still works | [ ] |
| 12 | No secrets in the repo (keys, tokens, passwords, connection strings). The advisor reports no redacted secret | [ ] |
| 13 | No text in the repo that speaks to an AI reader (the advisor reports no injection line) | [ ] |
| 14 | Patches were read line by line, applied by a person with `git apply`, and tested | [ ] |
| 15 | The agent model family is known and differs from the judge model family | [ ] |
| 16 | The readiness score is 50 or more and the open findings have an owner and a date | [ ] |
| 17 | The assurance dimensions that apply (section 7) are planned | [ ] |
| 18 | Decision 33 class discussed with risk and compliance. A pause is a control after the action. It is not human approval before the action | [ ] |

Owner: ____________________   Date: __________

Second approver: ____________________   Date: __________
