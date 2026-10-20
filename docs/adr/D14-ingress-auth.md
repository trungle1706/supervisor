# D14 - Ingress authentication for agents

Status: Accepted (WP20, 2026-10-20). Bank decisions listed under "Open".

## Context

`POST /gate/check`, `/v1/gate/check` and `/v1/traces` trusted the network position. Any caller that reached the port could ask the gate about, or write spans for, any agent id (BACKLOG, threat-model section 4). A bank security review rejects this (OWASP ASVS V2 authentication, V3 session/replay; NIST SP 800-63B replay and verifier guidance).

## Decision

- Flag `INGRESS_AUTH_ENABLED` (default off; off = the routes behave as before and a startup warning is logged outside `dev` mode).
- Two deterministic credential kinds (setting `INGRESS_CREDENTIAL_KIND`: `hmac`, `databricks_sp`, `both`, `auto`; `auto` = `databricks_sp` in `databricks_app` mode, `hmac` otherwise):
  1. HMAC-SHA256 per agent. Headers `X-Supervisor-Agent`, `X-Supervisor-Timestamp`, `X-Supervisor-Nonce`, `X-Supervisor-Signature: v1=<hex>`. Signed string: `v1`, agent, timestamp, nonce, METHOD, path, SHA-256(body), joined by newlines. Method and path are inside the string so a signature cannot move between routes. Window 300 s both ways; nonce single-use per agent for 2x window plus 5 s; nonce is stored only after the signature is valid. Compare with `hmac.compare_digest` for every active key, with a dummy key for an unknown agent (same work, same message).
  2. Databricks service-principal bearer (`Authorization: Bearer`, else `X-Forwarded-Access-Token`). The `IdentityVerifier` port returns the principal; the real adapter calls SCIM `Me` with the caller's own token and caches successes for `INGRESS_IDENTITY_CACHE_TTL_S` (keyed by token hash). `config/agent_identities.yaml` maps principal to the agent ids it may speak for. No wildcard. Unmapped principal = 403.
- Key store port with three backends: `file` (laptop, `config/agent_keys.yaml`, mode 600 enforced on POSIX), `env` (`INGRESS_AGENT_KEY_<ID>` and `_PREV`), `secret_scope` (Databricks secret scope / UC secret behind a `SecretReader` port; tested with a fake). `auto` = `file` on the laptop, `env` on the App.
- Rotation: at most two active keys per agent, `current` and `previous`. `previous` has an expiry (default 24 h, `INGRESS_KEY_OVERLAP_HOURS`); a third rotation drops the oldest. CLI: `python -m supervisor.gateway.ingress_auth issue|rotate|list`.
- Agent id binding: the authenticated identity carries a set of agent ids. `/gate/check`: the body `agent_id` must be in the set (else 403). `/v1/traces`: every span's agent id must be in the set, else the whole batch is refused with 403 and `X-Supervisor-Rejected: <n foreign spans>`; nothing is written.
- Rejections: 401 (no, malformed, stale, bad or replayed credential, unknown agent, bad token), 403 (valid credential, wrong agent or unmapped principal), 413 (body over the cap, read before the signature can be checked), 429 (nonce cache full). Never 500. Unknown agent and bad signature give the same public message. Each rejection: one `console_action` row (`permission=ingress.auth`, `outcome=denied`, `detail` = reason code, `before_hash` = SHA-256 of the body, actor = `unverified:<claimed agent id>`), plus `ingress_rejected` and `ingress_rejected_<reason>` in `/gate/metrics` counts. No new table.
- SDK: `HttpGate(credential=...)` signs the exact bytes it sends. A 401/403 answer fails closed with rule `GATE-AUTH` even for a `read_only` tool (a refused credential is a configuration fault, not an outage). `InProcessGate` is unchanged. The MCP proxy takes `--key-file` / `SUPERVISOR_AGENT_KEY(_FILE)` or `--bearer-token-env`.
- No model is involved anywhere (R1). No PII reaches the audit row (R2). No network call except SCIM `Me` to the configured workspace (R3).

## Alternatives rejected

- mTLS: needs a bank PKI and does not pass the Databricks Apps proxy. Kept as a bank option (the verifier port allows it later).
- A static bearer shared by all agents: no agent binding, no rotation per agent.
- JWT with a shared secret: adds a parser and algorithm choices for no gain over a fixed string-to-sign.
- Nonce cache in the database: one writer process already; a DB write per call would break the gate latency budget.

## Consequences

- The standard OTLP exporter cannot sign HMAC requests (static headers only). On the laptop use a signing sidecar or the SDK; on the App use a bearer token in `OTEL_EXPORTER_OTLP_HEADERS` (see `docs/ingress-auth.md`).
- Nonces are in memory: a restart inside the 5-minute window forgets them (documented residual risk).
- Rejection floods write audit rows; use network limits (BACKLOG).

## Open (bank decisions)

1. Key custody: file on the laptop, env or secret scope on the App, or the bank vault. The Databricks App rules say "no secret-scope resources"; `secret_scope` reads through the SDK at runtime and is not an App resource, but the owner must confirm it is allowed.
2. Whether Databricks Apps forwards the caller's `Authorization` header or only `X-Forwarded-Access-Token`; both are accepted, the live behaviour is not verified here.
3. Rotation period and overlap length (default 24 h).
