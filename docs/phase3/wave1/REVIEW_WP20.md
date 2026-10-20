# REVIEW WP20 - Ingress authentication

Reviewer: Opus (appsec + senior Python). Branch `worktree-agent-a038a49e4b494fc59`, base main bf3a23a.
Reviewed: HANDOFF_WP20.md and the full `git diff main...HEAD` (2 author commits). Review fixes: 7 small commits on the branch. Nothing pushed or merged, and no history rewritten.

## Verdict: APPROVE WITH FIXES

The design is sound. The canonical string is unambiguous, the compare is constant-time over every key with a dummy key for an unknown agent, a nonce is stored only after the signature is valid, the window and nonce TTL match, the flag is off by default, and the contract test pins the ingress routes. I found one real authorization bypass and several "500 / event-loop" defects and fixed them on the branch. The remaining items are DoS hardening and Databricks Apps assumptions. They do not block a merge with the flag off by default, but they must be closed before the bank turns the flag on in `databricks_app` mode.

## Findings

| # | Sev | File:line | Issue | Action |
|---|---|---|---|---|
| F1 | **High** | `recorder/otlp_receiver.py` (span check, was l.127) | Span agent binding bypass. With `RECORDER_SEMCONV=1` (the default), a span named `invoke_agent <id>` gets its agent id from the span name through `semconv.apply`. The receiver ran `agent_id_of` on the raw span, saw `None` and skipped it. So a credential for agent A could write events for agent B. I reproduced it: HTTP 200, events stored. | **Fixed** b2e8e3a: the check now uses the same semconv view as `Normaliser.normalise`. It fails closed when the recorder has no normaliser. Test `test_span_named_for_another_agent_is_refused`. |
| F2 | Medium | `adapters/auth/agent_creds.py` `FileKeyStore._load` | A key file with the wrong YAML shape (`agents:` as a list, an agent as a list) raised `AttributeError` in the verifier, which gave HTTP 500. | **Fixed** 66aed82: these shapes raise `KeyStoreError` (401 `key_store_unavailable`). Any other exception from the verifier now gives an audited 401 `auth_unavailable`. Tests added. |
| F3 | Medium | `gateway/ingress_auth.py` `record_reject` | The audit row was written synchronously inside async code. In `databricks_app` mode that is a SQL statement over HTTP for each rejection, on the event loop. An unauthenticated flood therefore stalled every request, valid gate checks too. | **Fixed** 11a3b8e: the write runs in the thread pool. `reject_later` and `check_span_agents` are now async. |
| F4 | Medium | `adapters/auth/agent_creds_identity.py` `scim_me` | `WorkspaceClient` used the SDK default timeouts (60 s per call, up to 300 s of retries). A slow or down workspace held one thread-pool worker per bearer request for minutes, so the pool could run out. | **Fixed** 6fc9a0e: 10 s HTTP, 15 s retry. Test added. This is below the CLAUDE.md guideline of 60-120 s on purpose, because the call is on the request path. The owner can raise it. |
| F5 | Low | `gateway/ingress_sign.py:39-41` | The regexes end with `$`, which also matches before a trailing `\n`. So `agent\n` passed `AGENT_ID_RE`, and a newline could get into the string to sign. h11 rejects such header values today. | **Fixed** 013a3f9: anchored with `\Z`. Tests for agent, nonce and signature. |
| F6 | Low | `gateway/ingress_auth.py` `authenticate` | My F2 catch-all also turned the body-limit middleware's 413 (chunked body) into a 401. | **Fixed** c02359a: only the verifier call is wrapped. Test for the chunked 413. |
| F7 | Low | `gateway/ingress_auth.py` `_write_client_file` | An existing `--out-key-file` kept its old mode (for example 644) until after the secret was written. | **Fixed** c23ba1c: `fchmod 600` runs before the write. |
| F8 | Medium | `ingress_auth.py` `_hmac` + `SecretScopeKeyStore` | Pre-auth amplification. With a fresh timestamp and a random agent id, every request causes 2-3 secret-scope API calls before any secret is checked, and random ids are never cached. The cache also clears at 4096 entries, which drops the cached keys of real agents. The bearer path has the same problem: every bad token is one SCIM call, because failures are not cached. | **Recorded.** Proposal: check the agent id against the known agent registry (manifests) before the key lookup, or read the scope key list once and cache it. Limit concurrent SCIM calls with a semaphore. |
| F9 | Medium | `ops/middleware.py:38` `RATE_LIMIT_EXEMPT` + `record_reject` | Audit-row flood. The ingress routes are exempt from the rate limit, so every unauthenticated request writes one `console_action` row (one Delta statement on the App). | **Recorded.** Cheap throttle: in `IngressGuard` keep `{(reason, client_ip or claimed): last_write}` (bounded to 10k entries). Write at most 1 row per key per N s (setting `INGRESS_AUDIT_THROTTLE_S`, bank chooses 0 or 10). Count the rows not written in `ingress_audit_suppressed`, and write the suppressed count in `detail` of the next row. Or rate-limit only rejected calls per client IP. Owner decision: audit completeness against DoS. |
| F10 | Low | `ingress_auth.py` `NonceCache` | The cap of 200k entries is global, not per agent. One compromised agent that holds a valid key can fill the cache, and then every agent gets 429 for up to 10 min. When the cache is full, each insert also scans the full dict under the lock. Memory is bounded at about 60 MB. | **Recorded.** Add a per-agent cap (for example 20k) and prune only on a timer. |
| F11 | Low | `ingress_auth.py` `_read_capped` | Up to `MAX_REQUEST_BYTES` (10 MB) is buffered per unauthenticated request before the header shape, timestamp and agent are checked. | **Recorded.** Do the header-only checks before the body is read. |
| F12 | Info | `_hmac` | Timing: an agent with 2 active keys does 2 HMACs, and an unknown agent does 1. The key-store lookup time also differs, and a secret-scope miss is a network call. This can show whether an agent id exists, and the network noise is much larger than the HMAC difference. | Accepted. Fix with F8: always compute 2 HMACs. |
| F13 | Info | `ScimMeIdentityVerifier` | A revoked token stays valid for up to `INGRESS_IDENTITY_CACHE_TTL_S` (300 s). A workspace outage gives 401, and the SDK then fails closed (`GATE-AUTH`) even for read-only tools. | Document. The owner must decide whether an identity outage gives 401 or 503. |
| F14 | Info | `ingress_sign.py` | The query string is not signed. No ingress route reads query parameters today. | Document. Sign `path?query` if a route ever reads a query parameter. |
| F15 | Info | `FileKeyStore` | The mode check runs only when the file mtime changes. A `chmod 644` changes ctime, not mtime, so it is not seen until the next edit. | Accepted. |
| F16 | Info | HANDOFF | The author's commits carry a Sonnet `Co-Authored-By` trailer, not the Fable line from the brief. | The integrator must not rewrite history. Only note it. |

Checked and OK: the canonical form has fixed-charset fields and a fixed-length body hash, and the path is fixed by the route match, so two different requests cannot share a string to sign. Method and path are bound. Duplicate or oversized credential headers give 401. Duplicate JSON keys parse the same way in the guard and in the route (last key wins, in both). `CheckRequest` has `extra=forbid`, and no other body field names an agent. The bearer token is never logged or cached raw (the cache uses a SHA-256 key). Public messages merge `unknown_agent`, `bad_signature` and the token errors into one message. `stale_timestamp` and `replayed_nonce` reveal nothing secret. The claimed agent in logs is checked against the regex first, so log injection is not possible. The use of `request._body` matches Starlette 1.8.0: `stream()` yields `_body` when it is set. If a future Starlette version changes this, the route reads fail with `RuntimeError("Stream consumed")` (500). The route and e2e tests catch that, so pin it or re-check on upgrade. The App runs `--workers 1`, so the in-memory nonce cache is valid there. With more workers or replicas, the same nonce can be replayed on another worker. This must be documented as a precondition, and D14 should say so.

## Rules

| Rule | Status |
|---|---|
| R1 (no model blocks) | OK, deterministic only |
| R2 (no PII in evidence or prompt) | OK, the audit row holds the body hash only (tested with a PII marker) |
| R3 (offline) | OK, only SCIM `Me` and the secrets API to the configured workspace. Note: `WorkspaceClient` also fetches `/.well-known/databricks-config` from the same host on each new client, so each SCIM verify makes 2 HTTP calls. |
| Defaults off | OK, `INGRESS_AUTH_ENABLED=0`, off-path tested, warning at startup |
| No 500 | OK after F2, F6 |
| ASCII CLI | OK (tested). The CLI prints the secret when `--out-key-file` is missing ("shown once"). Make the docs recommend `--out-key-file`. |
| Both modes | OK, laptop HMAC and `databricks_app` + fake verifier e2e. The Delta fake is not used for the gate store (no new table). This is acceptable. |
| No new deps, no secrets | OK, FILL-ME only, `config/agent_keys.yaml` git-ignored |
| Docs / ADR | Good: sequence diagram, settings table, rubric, open questions. Missing: the `--workers 1` precondition (F10 note), the token cache revocation delay (F13), the unsigned query string (F14). |

## Databricks Apps fit (verified vs assumed)

| Item | Status |
|---|---|
| The SDK sends `Authorization: Bearer <SP OAuth token>` to the App URL | Code verified (unit/e2e with a fake verifier) |
| The Apps proxy authenticates the caller before the app sees the request | **Assumed** (platform behaviour) |
| The proxy forwards `Authorization` to the app process | **Assumed, likely false.** My understanding is that the proxy consumes it and sets `X-Forwarded-User/-Email/-Preferred-Username`. `X-Forwarded-Access-Token` is present only when user authorization (on-behalf-of) is turned on for the App, and its scopes must allow SCIM `Me`. Not verified live. |
| SCIM `Me` with an OAuth SP token through `auth_type="pat"` | Assumed to work (the token is sent as a plain Bearer). Not run live. |
| Recommendation | Add a `databricks_proxy` credential kind that maps the proxy-set `X-Forwarded-User` (already trusted by the console auth on the App) to agent ids. This needs no token and no SCIM call. Keep SCIM for the laptop or a non-App front. Put "which headers reach the app" in the live kit as the first check. |

## Tests

| Run | Result |
|---|---|
| Base (handoff) | 2879 passed, 28 skipped |
| After review fixes, `uv run python -m pytest -q -x` | **2888 passed, 28 skipped** (+9 review tests), 291 s |
| `tests/e2e/test_ingress_auth_e2e.py` alone | 2 passed |
| `ruff check .` / `ruff format --check .` | clean |

## Residual risks (in order)

1. The App bearer path depends on how the proxy forwards headers, and this is not verified (see above). With the flag on in `databricks_app` mode, every agent may get 401 until this is checked.
2. Unauthenticated amplification (F8) and audit flood (F9): the ingress routes have no rate limit.
3. Nonce cache: one process only, lost on restart, cap shared by all agents (F10).
4. A compromised agent with its own key can still lie about its own calls (by design: the gate is cooperative).

## Merge notes for the integrator

- Conflict-prone shared files: `src/supervisor/config.py` (WP20 block plus 2 validator path entries plus defaults in `_rules` plus 2 properties; the last two are not in the end-of-class block), `src/supervisor/app.py` (import, startup check, exception handler), `src/supervisor/gateway/routes.py` (one line on `/check`, which WP24b also edits), `src/supervisor/gateway/sdk.py`, `src/supervisor/gateway/wiring.py` (`peek_gateway`), `src/supervisor/recorder/otlp_receiver.py` (`authorize` is now async, plus the `_span_agent` helper from this review), `src/supervisor/ops/middleware.py` is NOT touched but `tests/test_ingress_contract.py` pins `RATE_LIMIT_EXEMPT`, `docs/threat-model.md`, `README.md`, `BACKLOG.md`, `docs/index.md`.
- `tests/test_ingress_contract.py` pins the AGENT route set. Any wave-1 WP that adds a machine-ingress route (WP21 SIEM, WP24 inventory) must add the guard and update `PINNED`.
- `check_span_agents` and `IngressGuard.reject_later` / `record_reject` are now `async`. Any new caller must `await` them.
- No DDL or `schema/model.yaml` change.
