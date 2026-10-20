# Ingress authentication (WP20)

Per-agent credentials on the three agent-facing write routes: `POST /gate/check`, `POST /v1/gate/check`, `POST /v1/traces`. Decision record: `docs/adr/D14-ingress-auth.md`. Threat model: `docs/threat-model.md`, section "Ingress authentication".

Default: **off** (`INGRESS_AUTH_ENABLED=0`). Off means the routes accept every caller, as before; the app logs one warning line at startup when `SUPERVISOR_MODE` is not `dev`.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `INGRESS_AUTH_ENABLED` | `0` | Turn the check on |
| `INGRESS_CREDENTIAL_KIND` | `auto` | `hmac`, `databricks_sp`, `both`. `auto` = `databricks_sp` in `databricks_app` mode, `hmac` otherwise |
| `INGRESS_KEY_STORE` | `auto` | `file`, `env`, `secret_scope`. `auto` = `file` on the laptop, `env` on the App |
| `INGRESS_KEYS_FILE` | `config/agent_keys.yaml` | HMAC key file (git-ignored, chmod 600) |
| `INGRESS_IDENTITIES_FILE` | `config/agent_identities.yaml` | principal to agent ids |
| `INGRESS_SECRET_SCOPE` | empty | scope name for `secret_scope` |
| `INGRESS_REPLAY_WINDOW_S` | `300` | timestamp window and nonce lifetime base |
| `INGRESS_MAX_HEADER_BYTES` | `512` | cap for each credential header (bearer: 4096) |
| `INGRESS_IDENTITY_CACHE_TTL_S` | `300` | SCIM `Me` result cache |
| `INGRESS_KEY_CACHE_TTL_S` | `60` | secret scope read cache |
| `INGRESS_KEY_OVERLAP_HOURS` | `24` | life of the previous key after a rotation |

## Sequence (plain text)

```
HMAC credential
agent SDK                         Supervisor app (ingress_gate / authorize)          gate / recorder
   | body = JSON bytes                    |                                              |
   | ts = now, nonce = random             |                                              |
   | sig = HMAC(key, v1,agent,ts,nonce,   |                                              |
   |            METHOD,path,sha256(body)) |                                              |
   |--- POST path + X-Supervisor-* ------>|                                              |
   |                                      | 1 header sizes / shape      -> 401           |
   |                                      | 2 |now - ts| <= 300 s      -> 401 stale      |
   |                                      | 3 keys(agent): current+previous              |
   |                                      |   none -> dummy compare     -> 401 (same text)|
   |                                      | 4 compare_digest per key    -> 401 bad_sig    |
   |                                      | 5 nonce unused (agent,nonce)-> 401 replayed   |
   |                                      | 6 body agent_id / span ids in {agent}        |
   |                                      |   else                      -> 403            |
   |                                      |--- check / ingest ------------------------->|
   |<-------------- 200 decision ---------|<---------------------------------------------|
   (every 4xx above: one console_action row with the body hash, +1 in /gate/metrics)

Databricks service-principal credential
agent (App / job)     Supervisor app        IdentityVerifier (SCIM Me, cached)   agent_identities.yaml
   |-- Bearer token ---->|                              |                                |
   |                     |-- verify(token) ------------>| (cache hit: no call)           |
   |                     |<-- principal ----------------|                                |
   |                     |-- agents_for(principal) ---------------------------------->  |
   |                     |   none -> 403; body agent_id / span ids not in list -> 403    |
   |<---- 200 -----------|
```

## Laptop setup (HMAC, file key store)

```
set INGRESS_AUTH_ENABLED=1
python -m supervisor.gateway.ingress_auth issue customer_service --out-key-file C:\secure\customer_service.key
```

* The command writes `config/agent_keys.yaml` (mode 600 on Linux/macOS; on Windows restrict the folder with NTFS permissions) and writes the secret to the key file for the agent. It prints no secret when `--out-key-file` is given.
* Agent side: `set SUPERVISOR_AGENT_KEY_FILE=C:\secure\customer_service.key` (first line is the secret), or `SUPERVISOR_AGENT_KEY`. Then:

```python
from supervisor.gateway.ingress_sign import credential_from_env
from supervisor.gateway.sdk import HttpGate, set_default_gate

set_default_gate(HttpGate("http://127.0.0.1:8000", credential=credential_from_env("customer_service")))
```

* MCP proxy: add `--key-file C:\secure\customer_service.key` (or set the env vars above).
* Rotate: `python -m supervisor.gateway.ingress_auth rotate customer_service --out-key-file ...`. The old key stays valid for `INGRESS_KEY_OVERLAP_HOURS` (or `--overlap-hours N`); give the agent the new key inside that time. Run `list` to see key ids, states and expiry (never secrets).
* OTLP spans with HMAC: the standard OTel exporter sends static headers and cannot sign. Use a signing sidecar (build the request with `IngressCredential.headers_for("POST", "/v1/traces", body)`) or send traces through the SDK. See BACKLOG.

## Databricks App setup (service principal bearer)

1. Create a service principal per agent app or job (workspace admin UI or SCIM). Note its **application id**. Give it permission to open the Supervisor App (CAN USE).
2. Map it to its agent ids in `config/agent_identities.yaml` (edit in your local copy, never commit real ids):

```yaml
principals:
  - principal: FILL-ME-service-principal-application-id
    agents: [FILL-ME-agent-id]
```

3. `app.yaml` env lines of the Supervisor App (the platform injects the host and the App's own OAuth client; never set `DATABRICKS_TOKEN`):

```yaml
  - name: INGRESS_AUTH_ENABLED
    value: "1"
  - name: INGRESS_CREDENTIAL_KIND
    value: "databricks_sp"          # default in databricks_app mode
  - name: INGRESS_IDENTITIES_FILE
    value: "config/agent_identities.yaml"
```

4. The agent sends its own OAuth access token: `HttpGate(url, credential=IngressCredential("customer_service", bearer=get_token))` where `get_token` returns a fresh token from the agent's Databricks SDK config. For OTLP use `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>` and refresh it before it expires.
5. HMAC on the App (optional, `INGRESS_CREDENTIAL_KIND=both` or `hmac`): keep the secret in a secret scope that holds `agent-<id>-current`, `agent-<id>-previous` and `agent-<id>-previous-expires`, and set `INGRESS_KEY_STORE=secret_scope` and `INGRESS_SECRET_SCOPE=FILL-ME-scope`; or use env vars `INGRESS_AGENT_KEY_<ID>` (`<ID>` = agent id upper case, other chars to `_`) and `_PREV`, `_PREV_EXPIRES`. `python -m supervisor.gateway.ingress_auth rotate <id>` prints the names and the new secret once. The secret scope reader (`DatabricksSecretReader`) is not tested against a live workspace; tests use a fake. The App rules say "no secret-scope resources": the reader uses the SDK at runtime and is not an App resource, but confirm this with the platform team (ADR D14, Open 1).

## What a caller sees

| Case | HTTP | `detail` in audit |
|---|---|---|
| No credential | 401 | `missing_credential` |
| Malformed or oversized header, bad timestamp or nonce shape | 401 | `malformed_credential`, `header_too_large` |
| Timestamp outside the window | 401 | `stale_timestamp` |
| Unknown agent, wrong signature (same message) | 401 | `unknown_agent`, `bad_signature` |
| Nonce already used | 401 | `replayed_nonce` |
| Bad bearer token / identity service refused | 401 | `invalid_token` |
| Key store error, verifier not configured | 401 | `key_store_unavailable`, `auth_unavailable` |
| Body or span agent id not allowed for the credential | 403 | `agent_mismatch`, `span_agent_mismatch` (header `X-Supervisor-Rejected` = foreign spans) |
| Principal not in `agent_identities.yaml` | 403 | `unknown_principal` |
| Body above the size cap (checked before the signature) | 413 | `body_too_large` |
| Nonce cache full | 429 | `nonce_cache_full` |

Audit row: table `console_action`, `permission=ingress.auth`, `outcome=denied`, `actor=unverified:<claimed agent id>`, `before_hash` = SHA-256 of the body (never the body). Counts: `GET /gate/metrics` -> `counts.ingress_rejected`, `ingress_rejected_<reason>`, `ingress_accepted`.

## Review rubric (application-security engineer, ASVS v4 ch. 2 and 3, NIST SP 800-63B)

| Check | Where it is proven |
|---|---|
| Verifier uses HMAC-SHA256 with 256-bit keys, minimum 32 chars | `tests/gateway/test_ingress_verifier.py` (short and FILL-ME keys never valid) |
| Constant-time compare, no early exit, dummy compare for unknown agent | `test_compare_is_constant_time` |
| Replay: inside window (nonce), outside window (timestamp), cache lost | `test_replay_*` |
| Clock skew both directions at the window edge | `test_clock_skew_both_directions` |
| Rotation overlap, expiry, two keys at most | `test_rotation_*`, `test_only_two_keys_stay_active` |
| No account enumeration | `test_bad_signature_and_unknown_agent_look_the_same_to_the_caller` |
| Agent-id spoofing (body vs header, signature vs header) | `tests/gateway/test_ingress_routes.py` |
| Oversized, duplicated, malformed headers: 4xx, never 500 | `test_oversized_headers_*`, `test_malformed_headers_*` |
| Every ingress route is covered | `tests/test_ingress_contract.py` |
| SDK client to app to gate decision, laptop and databricks_fake | `tests/e2e/test_ingress_auth_e2e.py` |

## Limits

Nonces live in memory (one process, one worker). Rejection floods write audit rows. A compromised agent that holds its own key can still lie about its own calls. The OTel exporter cannot sign HMAC. See `BACKLOG.md`.
