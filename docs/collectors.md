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
  a skipped call the status is `transform`.
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

### FastAPI (any ASGI app)

Input phase: the body is `args` of the tool `http_inbound`. Output phase: the response is held
back, checked, then sent; a block (403), a pause or outage (503), or a response above the cap
(502) replaces it, so nothing of a refused response leaves the process. Binary responses are not
inspected. A request above the cap is 413.

### LiteLLM

`async_pre_call_hook` sends `messages`; `async_post_call_success_hook` sends the answer text.
Streaming answers are not checked.

### Claude Code hook

Settings from the environment (`SUPERVISOR_URL`, `SUPERVISOR_AGENT_ID`, key, `SUPERVISOR_FAIL_MODE`,
`SUPERVISOR_CLOSED_TOOLS`). Exit 0 allow, exit 2 refuse with one ASCII line on stderr. A masked
input is printed as the assistant's `updatedInput` answer.

## 4. Evaluation

`python -m supervisor.collectors.harness` (also `--check`, `--record`, `--record-answers`,
`--md`). Contract: 4 adapters x 9 statuses (allow, report, transform, pause, block, skip, 401, 429,
timeout) x 4 settings (money or read_only, closed or open) = 144 cases against a real `HttpGate`
replaying answers of a real gateway (`data/eval/collectors/gate_answers.json`). 26 adversarial
probes. Overhead p50 and p95 per adapter. Thresholds are ILLUSTRATIVE. Rubric, baseline and
result: `docs/collectors-validation-report.md`, `data/eval/collectors/`.
