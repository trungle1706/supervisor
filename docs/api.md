# API versioning policy

## Paths

| Area | Path | Kind |
|---|---|---|
| Gate (agents) | `POST /v1/gate/check` | JSON API, agent ingress |
| Analytics (read) | `GET /v1/analytics/tools?agent_id=&days=&view=daily` or `summary` (flag `TOOL_ANALYTICS_ENABLED`; `docs/tool-analytics.md`) | JSON API |
| Gate (detector catalogue) | `GET /v1/gate/detectors` (flag `DETECTORS_ENABLED`; `docs/detectors.md`) | JSON API |
| Gate (people) | `POST /v1/gate/pause`, `resume`, `quarantine`, `release`; `GET /v1/gate/agents/{id}/state`, `/v1/gate/metrics` | JSON API |
| Traces | `POST /v1/traces` (OTLP/HTTP JSON) | JSON API, agent ingress |
| Console | `/console/...` | UI for people, not an API; no stability promise |
| Ops | `/health`, `/ready`, `/healthz`, `/version` | Probes; unversioned |

- JSON API routes live under `/v1`.
- `/gate/...` (no prefix) is the old path. It still works and runs the same code. It is
  marked `deprecated` in `/openapi.json` only. New clients use `/v1/gate/...`.
- The OpenAPI document is at `/openapi.json`. Tags: `gate`, `traces`, `console`, `ops`.
  The interactive `/docs` and `/redoc` pages are off (WP18): they load JavaScript from a
  CDN, which the offline rule forbids and the CSP blocks. Open `/openapi.json` in any
  OpenAPI viewer the bank allows.

## Security schemes in the document

| Scheme | Header | Use |
|---|---|---|
| `devHeader` | `X-Dev-User` | Laptop only. Not a real identity (ADR D04). |
| `databricksSSO` | `X-Forwarded-Email` | Set by the Databricks App proxy. |

`/gate` control routes (pause, resume, quarantine, release) always require an identity (laptop: `X-Dev-User` header with a known user, no default user; App: SSO headers) and the role; a missing or unknown identity is 403. The body field `principal` is ignored.

They apply to the routes where people act (gate control and read routes, console).
`/v1/gate/check` and `/v1/traces` are agent ingress and need no human identity.

## Breaking changes

A breaking change (removed field, changed meaning, new required field) gets a new prefix
`/v2`. Rules:

1. `/v1` and `/v2` run side by side for at least one release.
2. The `/v1` routes are marked `deprecated` in the schema in that release, with the
   removal release named in the release notes.
3. Adding an optional field or a new route is not breaking and stays in `/v1`.

## Verdict contract v2 on `POST /v1/gate/check` (WP37, flag `DETECTORS_ENABLED`)

Off (default): the request and the answer are as in v0.3.0. On: the answer keeps every old field
(`allow`, `action`, `rule_id`, `reason`, `matched_rules`, `transformed_args`, ...) and adds the
fields below. Adding fields is not a breaking change; `/v1` stays.

Request additions (all optional):

| Field or header | Meaning |
|---|---|
| `direction` | `input` (default) or `output`. `output` checks what a tool returned; the text is in `context.output`. No rule is evaluated and no window changes. With the flag off, `output` is HTTP 400 |
| `context.tool_results` | Input side: the tool results that fed this call (text, list or object). Scanned for indirect injection |
| `context.consumer_id` | WP39: the calling application, a plain id (letters, digits, `._:@-`, up to 128). Stored on the decision (`agent_event.consumer_id`, only with the flag on) and shown in the console (column, filter, Analytics table). Not used by any rule. Anything else is ignored |
| `context.protocol` | `llm` (default), `mcp` or `a2a`. A detector that does not list the protocol is skipped |
| header `X-Supervisor-Correlation-Id` | Your id (1 to 128 characters of `A-Za-z0-9_.:@-`). Another value is HTTP 400. Missing: the gate generates one. Echoed in the response header |

Answer additions:

| Field | Type | Meaning |
|---|---|---|
| `status` | `allow` `report` `transform` `pause` `block` `skip` | Precedence block > pause > transform > report > allow; `skip` only from a policy value (`docs/detectors.md` section 4) |
| `findings[]` | list | `detector_slug`, `detector_id`, `code`, `score_bp`, `threshold_bp`, `entities` (masked), `fragments` (located on masked text), `masked_count`, `action_hint`, `not_executed_reason` (null), `preset`, `mock` |
| `not_executed[]` | list | `detector_slug`, `detector_id`, `reason` (`execution_failed`, `invalid_config`, `payload_too_large`, `content_uninspectable`, `not_applicable_for_direction`, `timed_out`), `detail` |
| `coverage` | object | `direction`, `inspected` (parts), `not_inspected` (`part`, `reason`), `chars` |
| `transformed_payload` | object or null | The payload parts after the dlp transform, for example `{"args": {...}}`. `transformed_args` carries the same arguments for the SDK and the MCP proxy |
| `request_id`, `correlation_id` | string | Ids that tie the answer to the decision row, the findings, the chain record and the trace span |
| `direction`, `detectors`, `detector_latency_us` | | Direction checked, ids of the detectors that ran, time spent in detectors |

A failed fail-closed detector on a money, credit or pii_export tool gives `allow: false`,
`action: block`, `rule_id: GATE-DETECTOR-FAILED`, `status: block`.

```json
{"allow": true, "action": "allow", "rule_id": null, "status": "transform",
 "findings": [{"detector_slug": "dlp_vn", "code": "pii.phone", "score_bp": 9500,
   "threshold_bp": 8000, "entities": [{"type": "PHONE", "token": "<PHONE:e65362>", "count": 1}],
   "fragments": [{"part": "args", "path": "$.note", "start": 61, "end": 75,
                  "text": "<PHONE:e65362>", "precision": "span"}],
   "masked_count": 1, "action_hint": "transform"}],
 "not_executed": [], "coverage": {"direction": "input", "inspected": ["args"],
   "not_inspected": [{"part": "tool_results", "reason": "not_provided"},
                     {"part": "output", "reason": "not_applicable_for_direction"}], "chars": 75},
 "transformed_payload": {"args": {"note": "... <PHONE:e65362>"}},
 "request_id": "...", "correlation_id": "..."}
```

`GET /v1/gate/detectors` returns the catalogue from code (needs `gate.read` when `API_RBAC_ENABLED`
is on): slug, sides, protocols, presets and the settings schema of each detector.

## WP38 additions (policy mode and consumer)

`context.consumer_id` (1 to 128 characters of `A-Za-z0-9_.:@-`) selects `agents.<id>.consumers.<id>`
in the policy. An agent that uses `mode`, `rules` or `consumers` in the policy gets these extra fields
in the answer (agents that do not, get none):

| Field | Meaning |
|---|---|
| `mode` | `enforce` or `observe` after the consumer override |
| `consumer_id` | the consumer whose override was applied |
| `consumer_ignored` | `true` when an id was sent but is invalid or has no entry |
| `observed_decision` | in observe mode, the decision that became a report: `allow` (false), `action`, `rule_id`, `reason` |
| `status` | `report` when observe turned a block or pause into a report (also without detectors) |

In observe mode `allow` is `true` and `action` is `log`. Details: `docs/policy.md`. The SDK adds
`HttpGate.check_v2(..., direction=, correlation_id=)` (header `X-Supervisor-Correlation-Id`).
