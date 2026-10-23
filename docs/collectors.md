# Collectors: attach any agent to Supervisor (WP38)

A collector is a way to put the gate in front of an agent. The Integrations page of the console
is the catalogue (flag `COLLECTORS_ENABLED=1`). Off, the page is the delivery status page of
v0.3.0. All text and code of the catalogue is ours (`src/supervisor/collectors/catalog.py`).

## 1. The catalogue

| Id | Category | What it is | Code |
|---|---|---|---|
| `python_sdk` | sdk | `HttpGate` and `@supervised_tool` | `supervisor.gateway.sdk` |
| `langgraph_middleware` | middleware | wraps each tool call of a LangGraph or deepagents agent | `supervisor.gateway.adapters.langgraph` |
| `fastapi_middleware` | middleware | checks the inbound request and the response of an app | `supervisor.gateway.adapters.fastapi_mw` |
| `rest` | gateway | one `POST /v1/gate/check` from any language | `supervisor.gateway.routes` |
| `mcp_stdio_proxy` | mcp | the existing stdio proxy | `supervisor.gateway.mcp_proxy` |
| `mcp_http_proxy` | mcp | "available after WP26" (card shown, Add disabled) | - |
| `litellm_guardrail` | gateway | custom guardrail for a LiteLLM proxy | `supervisor.gateway.adapters.litellm_guardrail` |
| `claude_code_hook` | ide | `PreToolUse` hook, exit code 2 refuses | `supervisor.gateway.adapters.claude_code_hook` |

LangGraph, LangChain, deepagents and LiteLLM are **not dependencies** of Supervisor. The adapters
do not import them at module level. `as_agent_middleware()` and `build_litellm_guardrail()` import
the framework when called; the tests use fake request and response objects. You install the
framework in the agent environment as before.

## 2. The console flow

1. Pick an agent without a key (the select on top of the page).
2. Press **Add** on a card. This is the WP20 issue flow: a new secret, a key record in the key
   store (file store: written with mode 600). Permission `collectors.add` (roles `admin` and
   `operator`). With the env or secret-scope store the server cannot write the key: the page
   shows what to set and the secret once.
3. The answer shows the setup steps and the snippet with the real base URL and the agent id
   filled in, and the key **once** (`Cache-Control: no-store`). The secret is never in the audit
   log (the row has the agent id, the template id and the key id) and never on any later page.
4. A detail drawer per agent: **Connection** (steps and code for any template), **Credential**
   (key id, state, dates; rotation is the command line `python -m supervisor.gateway.ingress_auth
   rotate <agent>`), **Policy binding** (mode, detector preset, switched-off rules, consumer
   overrides, as in the policy file; the policy stays in git).

An agent that already has a key gets "already has a key; rotate it". The base URL comes from
`COLLECTORS_PUBLIC_URL` or the address the console was opened with; it is checked (http or https,
plain URL characters) before it is put in a snippet.

## 3. What every adapter does

All four new adapters share `GateClient` (`gateway/adapters/common.py`):

* Sends `direction` (`input` before the tool, `output` after), `context.output`, `session_id`,
  `consumer_id`, `declared_risk_class`, and the header `X-Supervisor-Correlation-Id`. The adapter
  makes the correlation id; the gate makes one when the header is missing. One id covers the input
  and the output check of a call.
* Cleans ids: a consumer id, session id or correlation id that is not 1 to 128 characters of
  `A-Za-z0-9_.:@-` is dropped (consumer, session) or replaced (correlation id). A tool name with
  other characters is mapped to a safe name plus an 8 character hash; register the mapped name
  in the policy.
* Size cap (256 KB by default). Over the cap on a closed call: local block
  `SDK-PAYLOAD-TOO-LARGE`, the gate is not called. A payload that cannot be serialised (too deep)
  counts as too large.
* **Fail mode closed by default.** If the gate cannot answer (timeout, 429, 5xx, unreachable) or
  answers something that is not a verdict, the call stops. `fail_mode="open"` lets a call run
  only when the gate is unreachable, and only for tools that are not money, credit or pii_export.
  A refused credential (401, 403) is `GATE-AUTH` and is never opened. Tools declared in
  `risk_classes` as money, credit or pii_export are always closed.
* Block raises `SupervisorBlocked`, pause raises `SupervisorPaused` (a subclass), both with
  `.decision` (rule id, reason, correlation id). Arguments are not in the message.
* Applies `transformed_payload`: the whole `args` (or `output`) is replaced, never merged by key
  (the masker also masks dict keys). A `transform` status without values is a block
  (`SDK-TRANSFORM-UNAPPLIED`). `skip` and `report` mean the call goes on; if the masker redacted
  a skipped call the status is `transform`. Masked values are applied whenever they are in an
  allowed answer, also from an older gate that sends `transformed_args` with no `status`
  (WP38 review). Values that cannot be applied (a `transformed_payload` that is not an object,
  LiteLLM values without `messages`, ASGI values without `body` or `text`) are a block.
  `apply_transform=False` (LangGraph) is ignored for money, credit and pii_export tools.
* An `allow: true` answer that also says `block` or `pause` (in `action` or `status`), or has an
  action or status this client does not know, is a block (`SDK-ANSWER-CONTRADICTS`). The observe
  answer (`action: log`, `status: report`, `observed_decision`) passes.
* A `timed_out` entry in `not_executed` is for the log; the adapter does not fail open on it.

### LangGraph and deepagents

```python
guard = SupervisorToolMiddleware(HttpGate(url, credential=cred), "agent-id", "1",
                                 risk_classes={"transfer": "money"})
agent = create_agent(model, tools, middleware=[guard.as_agent_middleware()])
# ToolNode(tools, wrap_tool_call=guard.wrap_tool_call)  for plain LangGraph
```
`on_block="message"` turns a block (not a pause) into an error tool message the model can read.
`session_id` defaults to the run's `thread_id`.

**Tool results (WP41, D23).** The stock middleware used to send none, so the gate answered
`tool_results: not_provided` and the indirect-injection path never saw a document. Now an input
check carries `context.tool_results`: the last 3 tool messages of the run state
(`request.state["messages"]`), oldest first, each cut to 16384 bytes (the detectors'
`max_scan_bytes`, so what is sent is what can be read). Options of `SupervisorToolMiddleware`:
`send_tool_results=True` (default; `False` sends none), `tool_results_count=3` (0 to 10),
`tool_result_max_bytes=16384`. They are sent the way `context.output` is: as they are to the gate,
which masks every text it stores (R2); the adapter logs nothing and keeps nothing. They count in
`max_payload_bytes` (a payload above it is the usual local refusal). A state the adapter cannot
read means no key, never an error. The output check (`direction=output`) is unchanged.

### FastAPI (any ASGI app)

Input phase: the body is `args` of the tool `http_inbound`. Output phase: the response is held
back, checked, then sent; a block (403), a pause or outage (503), or a response above the cap
(502, in both fail modes: the part above the cap is not kept, so a cut response is never sent)
replaces it, so nothing of a refused response leaves the process. Binary responses are not
inspected. A request above the cap is 413.

### LiteLLM

`async_pre_call_hook` sends `messages`; `async_post_call_success_hook` sends the answer text.
Streaming answers are not checked.

### Claude Code hook

Settings from the environment (`SUPERVISOR_URL`, `SUPERVISOR_AGENT_ID`, key, `SUPERVISOR_FAIL_MODE`,
`SUPERVISOR_CLOSED_TOOLS`). Exit 0 allow, exit 2 refuse with one ASCII line on stderr. A masked
input is printed as the assistant's `updatedInput` answer. The hook sends with `urllib` (standard
library), so a developer laptop needs the Supervisor package and nothing else; `SUPERVISOR_URL`
must be `http://` or `https://`.

### File attachments (WP-D1, `DOCUMENT_INTAKE_ENABLED`)

The Python SDK, the LangGraph middleware and the FastAPI middleware send the files a user attached
as `context.documents` of the input check, **only while `DOCUMENT_INTAKE_ENABLED=1` is set in the
agent process** (the same name as the gateway flag; `attachments.set_document_intake(True)` does
the same in code). With the switch off nothing is built or sent and the request is the one the
adapter sent before. The two flags must match. Client on, gateway off: the gateway answers HTTP 400, and the adapter's
fail mode decides (a read-only tool may go on with its documents **unscanned**; money, credit and
pii_export tools stop). Client off, gateway on: no document is sent, so none is scanned, and the
gateway sees nothing wrong. Set `DOCUMENT_INTAKE_ENABLED` on both sides and check one decision for
`documents` in the answer.

| Adapter | What is sent |
|---|---|
| SDK `supervised_tool(..., documents_arg="files")` | The value of that parameter (bytes, `(name, bytes)` pairs, `pathlib.Path` objects, or document dicts) as `context.documents`; the parameter is left out of `args` |
| `GateClient.check(..., documents=[...])` | The same, for any adapter built on `GateClient` |
| LangGraph `SupervisorToolMiddleware` | The file, document and image blocks of the newest human message (LangChain standard blocks, Anthropic `document` blocks, OpenAI `image_url` data URLs). `send_documents=False` turns it off; `documents_getter=fn(request)` replaces the search |
| FastAPI `SupervisorASGIMiddleware` | A `multipart/form-data` request: files become documents, text fields become `args.form`. JSON and other bodies are sent as before |

The helper `gateway/adapters/attachments.py` is standard library only. It reads a file from disk
only for a `pathlib.Path` the caller passes. It sends at most 11 documents and cuts a file to
2 MB + 1 byte, so the gate can report `document.limit_exceeded` and nothing larger leaves the
process. An output check carries no document. A masked list (`transformed_payload.documents`) is
in the answer on a `pii_export` tool; forwarding the original files after a `transform` answer is
the caller's mistake to avoid.

## 4. Evaluation

`python -m supervisor.collectors.harness` (also `--check`, `--record`, `--record-answers`,
`--md`). Contract: 4 adapters x 9 statuses (allow, report, transform, pause, block, skip, 401, 429,
timeout) x 4 settings (money or read_only, closed or open) = 144 cases against a real `HttpGate`
replaying answers of a real gateway (`data/eval/collectors/gate_answers.json`). 26 adversarial
probes. Overhead p50 and p95 per adapter. Thresholds are ILLUSTRATIVE. Rubric, baseline and
result: `docs/collectors-validation-report.md`, `data/eval/collectors/`.

## Session id, consumer id and the two redaction switches (WP-P2)

### Session monitor from `@supervised_tool`

An agent does not need its own `GateHook` wrapper to take part in the session monitor. The decorator sends `context.session_id` and `context.consumer_id` when it has them:

```python
from supervisor.gateway.sdk import supervised_tool, supervised_session, set_session

@supervised_tool("kb_chatbot", "1", "search_policies", "read_only",
                  session_id=lambda args: args.get("sid"), consumer_id="web")  # text or a function
def search_policies(query, sid=None): ...

with supervised_session("sess-123", "web"):   # or set_session(...) once per request
    search_policies("limit")
```

A decorator argument wins over the context variable. With neither, nothing is sent and the monitor derives the id from agent, consumer and day. `HttpGate.check_v2` and `InProcessGate.check_v2` also take `session_id=` and `consumer_id=` and put them in `context`.

### Inline redaction: two switches

| Side | Switch | What it does |
|---|---|---|
| Gate (Supervisor server) | `INLINE_REDACTION_ENABLED=1`, or `DETECTORS_ENABLED=1` with `dlp_vn` in `transform` mode (also in SHADOW) | The gate answers with `transformed_args` (the masked arguments) |
| Agent process (SDK, collector, MCP proxy) | `INLINE_REDACTION_ENABLED=1` in the agent environment (or `set_inline_redaction(True)`) | The SDK replaces the arguments with `transformed_args` before the tool runs |

Both must be on. If the gate masks and the agent side is off, the tool gets the original arguments. To make this visible, the SDK sends `context.redaction_applied: false` on `pii_export` tools when its switch is off (other tool classes keep their old context). The gate then adds `redaction_applied: false` to the answer and to the `gate_decision` chain record (only when it masked; otherwise the answer is unchanged), and the SDK logs one warning per agent when it receives `transformed_args` it does not apply.
