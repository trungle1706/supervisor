# API versioning policy

## Paths

| Area | Path | Kind |
|---|---|---|
| Gate (agents) | `POST /v1/gate/check` | JSON API, agent ingress |
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
