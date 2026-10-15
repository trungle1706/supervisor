# Recorder (WP4)

The recorder turns agent activity into `agent_event` rows. Every input path goes through one
normaliser (`supervisor.recorder.normalise`), so the same span gives the same row.

```
in-process OTel span ---\
OTLP/HTTP JSON  ---------+--> SpanData --> Normaliser (capture level + Masker) --> EventWriter --> agent_event
proxy log JSONL --------/                                                       |               agent_event_raw (raw only)
                                                                                 +--> spool JSONL (store down) --> python -m supervisor.jobs.ingest
```

| Path | `source` | How |
|---|---|---|
| In-process | `otel` | `supervisor_agents.common.tracing.AgentEventExporter` |
| OTLP/HTTP | `otlp` | `POST /v1/traces`, `Content-Type: application/json` |
| Proxy log | `proxy` | `python -m supervisor.jobs.ingest --proxy-log <file>` |

## Capture levels

| Level | Stored in `agent_event` | Extra |
|---|---|---|
| `digest` | tool, args hash, amount (integer minor units), status. No text | - |
| `masked` | digest + args/result text after the Masker | `mask_version` (masker + key id) |
| `raw` | as masked | unmasked text in `agent_event_raw` (RESTRICTED, `access_class = restricted`) |

The agent manifest sets the level:

```yaml
capture:
  level: masked        # digest | masked | raw
  raw_allowed: false   # raw needs true
```

A span can ask for a lower level (`supervisor.capture_level`), never a higher one. With
`MASKER_KIND=none` every event is `digest`. Agents without a manifest get
`CAPTURE_DEFAULT_LEVEL` (`masked` or `digest`, never raw).

## Masking

`MASKER_KIND=vn_regex` (default). Recognisers: CCCD, CMND, phone (+84 / 0xx), tax code,
bank account, card (Luhn), e-mail, Vietnamese names (word lists, after an honorific or a
label), addresses. Each value becomes a token such as `<CCCD:ab12cd>`: the first 6 hex of
HMAC-SHA256(key, type + normalised value). The same customer gets the same token in every
event. Set the key in `.env`:

```
set MASK_HMAC_KEY=<long random value from the bank key store>
set MASK_KEY_ID=k2026q4
```

`vn_regex-2` also catches CCCD written with spaces, dots or dashes (`001 203 004 567`), grouped
account numbers after a cue word (`chuyen den 1903 4567 8901 23`) or of 13-19 digits, and PII with
invisible characters inside. **Masked output is normalised**: before matching, Unicode format
characters (zero-width space, soft hyphen, word joiner, BOM; category Cf) are removed and the text
is put through NFKC (full-width digits become ASCII, no-break space becomes a space, Unicode
dashes become `-`). `mask()` returns this normalised text with the PII replaced, so the recorded
`args_masked` can differ from the raw text in those characters. Amounts such as `1.500.000` or
`15.000.000đ`, dates and times are not masked: a dot-grouped or space-grouped number with 1-3
digits and then groups of exactly 3 is an amount, unless it has 12 digits (then it is a CCCD).

Without `MASK_HMAC_KEY` the dev key is used and `mask_version` is `vn_regex-2:dev`. A new
`MASK_KEY_ID` + key gives new tokens; `mask_version` on each row tells which key made it.
`MASKER_KIND=presidio` needs the optional `presidio` extra (off by default).

## OTLP/HTTP receiver

`POST /v1/traces` accepts the OTLP/HTTP JSON `ExportTraceServiceRequest` (ids as hex or
base64, 64-bit integers as strings or numbers, `Content-Encoding: gzip` allowed).

| Case | Answer |
|---|---|
| Valid batch | 200 `{}`; headers `X-Supervisor-Accepted`, `-Duplicates`, `-Ignored`, `-Spooled` |
| Protobuf or other content type | 415 with a message |
| Body > `OTLP_MAX_BODY_BYTES` (also after gunzip) | 400 |
| Spans > `OTLP_MAX_SPANS` | 400 |
| Bad JSON / bad OTLP shape | 400, nothing written |
| Store down | 200, rows go to the spool |

OpenTelemetry SDK settings for an agent:

```
set OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:8000/v1/traces
set OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json
```

Spans without an agent id (`supervisor.agent_id`, `gen_ai.agent.id` or resource
`supervisor.agent_id`) or without an event type are ignored.

## Proxy log format (black-box agents)

One JSON object per line, UTF-8:

```json
{"ts": "2026-10-14T05:00:00.120Z", "agent_id": "vendor_bot", "agent_version": "2.1",
 "request_id": "r-0001", "session_id": "s-77", "kind": "tool_call", "tool": "transfer",
 "args": {"to_account": "602554736615", "amount_minor": 5000000}, "result": {"ok": true},
 "status": "ok", "latency_ms": 85, "amount_minor": 5000000, "currency": "VND", "env": "uat"}
```

| Key | Required | Notes |
|---|---|---|
| `ts` | yes | RFC 3339 |
| `agent_id`, `request_id` | yes | `span_id` = hash of `request_id` |
| `kind` | yes | `tool_call`, `llm_call`, `message`, `handoff` |
| `session_id` | no | `trace_id` = hash of `session_id` (else of `request_id`) |
| `tool`, `args`, `result`, `status`, `agent_version`, `env`, `currency` | no | |
| `amount_minor`, `latency_ms` | no | integers only (a float is a bad line) |

Bad lines are reported with their line number and skipped. Fields the proxy cannot see:
parent span, caller agent, LLM prompt structure, gate decision, in-agent reasoning. The
reader writes one `trace_coverage` row per agent with `capability = reduced` and that list.

## Spool and ingest

When the store fails, the receiver (and any writer with a spool) appends to
`RECORDER_SPOOL_DIR` (default `<DATA_DIR>/spool`). Line kinds:

```json
{"kind": "rows", "agent_event": [...], "agent_event_raw": [...]}
{"kind": "otlp", "payload": {"resourceSpans": [...]}}
```

`rows` are already masked. An agent that cannot reach the receiver may write `otlp` lines.
Drain the spool:

```
python -m supervisor.jobs.ingest
python -m supervisor.jobs.ingest --proxy-log C:\logs\vendor_bot.jsonl
```

Ingest is idempotent by `event_id`. A fully stored file is renamed to `*.done`. On the
Databricks App `/tmp` is wiped at restart: keep `RECORDER_SPOOL_DIR` on a durable path.

## OpenTelemetry GenAI semantic conventions

The normaliser reads the OpenTelemetry GenAI names next to our own `supervisor.*` names
(`supervisor.recorder.semconv`). Spec read 2026-10-15: the conventions now live in
https://github.com/open-telemetry/semantic-conventions-genai (links name semconv v1.44.0);
all `gen_ai.*` attributes are `development`, `error.type` is `stable`.

Rules: a `supervisor.*` attribute always wins. Deprecated names (`gen_ai.system`,
`gen_ai.usage.prompt_tokens`, `gen_ai.usage.completion_tokens`) are read when the current
name is missing. A missing `gen_ai.operation.name` is taken from the span name prefix
(`chat {model}`, `execute_tool {tool}`, `invoke_agent {agent}`).

| Semconv attribute | agent_event column | Status | Note |
|---|---|---|---|
| `gen_ai.operation.name` | `event_type` | development | chat/text_completion/generate_content = llm_call; execute_tool = tool_call; invoke_agent/create_agent = message (handoff with a caller) |
| `gen_ai.agent.id` | `agent_id` | development | after `supervisor.agent_id` |
| `gen_ai.agent.name` | `agent_id` | development | last fallback |
| `gen_ai.agent.version` | `agent_version` | development | after `supervisor.agent_version` |
| `gen_ai.tool.name` | `tool_name` | development | also from the span name |
| `gen_ai.tool.call.arguments`, `gen_ai.input.messages` | `args_masked` | development | opt-in; masked by capture level; `args_hash` is computed |
| `gen_ai.tool.call.result`, `gen_ai.output.messages` | `result_masked` | development | opt-in; masked by capture level |
| `error.type` | `status` (`error`) | stable | unless `supervisor.status` is set |
| `gen_ai.provider.name` (`gen_ai.system`), `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens` / `output_tokens` (`prompt_tokens` / `completion_tokens`), `gen_ai.response.finish_reasons`, `gen_ai.conversation.id`, `gen_ai.tool.call.id`, `gen_ai.tool.type` | not mapped | development / deprecated | no column in `agent_event` |

Setting: `RECORDER_SEMCONV` (`recorder_semconv`, default on). Off = the older partial
fallbacks only (`gen_ai.agent.id`, `gen_ai.tool.name`, `gen_ai.operation.name`).
`semconv.EMIT` lists the attributes a team emits per span type; `semconv.SUPERVISOR_ATTRS`
lists our own extra attributes.
