# HANDOFF WP20 - Ingress auth

Branch: worktree-agent-a038a49e4b494fc59 (from main bf3a23a). Not pushed, not merged.

## Built

Per-agent credentials on `POST /gate/check`, `/v1/gate/check`, `/v1/traces`. Flag `INGRESS_AUTH_ENABLED`, default OFF (off path = old behaviour, tested; startup logs one warning line outside `dev` mode).

- HMAC-SHA256 credential: headers `X-Supervisor-Agent`, `-Timestamp`, `-Nonce`, `-Signature: v1=<hex>`; signed string binds agent, timestamp, nonce, method, path, body hash. 5 min window (setting), single-use nonce cache (memory), `hmac.compare_digest` over every active key, dummy compare for unknown agent.
- Databricks service-principal bearer: `IdentityVerifier` port; real `ScimMeIdentityVerifier` (SCIM `Me`, success cache with TTL setting, keyed by token hash); `FakeIdentityVerifier` for tests; mapping in `config/agent_identities.yaml` (FILL-ME sample). Mode `databricks_app` defaults to this kind.
- Key stores: file (chmod 600 enforced on POSIX), env, secret scope (`SecretReader` port, fake in tests; a thin real `DatabricksSecretReader` exists but is not run live).
- Rejections: 401 / 403 (also 413 body cap, 429 nonce cache full), never 500. Audit row per rejection in `console_action` (`permission=ingress.auth`, `before_hash`=body SHA-256, no body). Counts `ingress_rejected`, `ingress_rejected_<reason>`, `ingress_accepted` in `/gate/metrics`. No new table, so no DDL / model.yaml change.
- Agent binding: `/gate/check` body `agent_id` must be one the credential speaks for; `/v1/traces` batch with any foreign span is refused whole, 403, `X-Supervisor-Rejected: <n>`.
- SDK: `HttpGate(credential=IngressCredential, signed_transport=...)`; 401/403 fails closed `GATE-AUTH` even for read_only tools. `InProcessGate` untouched. MCP proxy: `--key-file`, `--bearer-token-env`, env `SUPERVISOR_AGENT_KEY(_FILE)`.
- Rotation: two active keys (current + previous with expiry, default 24 h). CLI (ASCII): `python -m supervisor.gateway.ingress_auth issue|rotate|list <agent_id> [--keys-file P] [--out-key-file P] [--overlap-hours N]`.
- Docs: `docs/ingress-auth.md` (sequence diagram, laptop and App setup, rubric table), `docs/adr/D14-ingress-auth.md`, threat-model paragraph and gap rows, README row, `docs/index.md`, BACKLOG rows.

## Flags / settings (config.py block `# --- WP20 ---`)
`INGRESS_AUTH_ENABLED`, `INGRESS_CREDENTIAL_KIND` (auto|hmac|databricks_sp|both), `INGRESS_KEY_STORE` (auto|file|env|secret_scope), `INGRESS_KEYS_FILE`, `INGRESS_IDENTITIES_FILE`, `INGRESS_SECRET_SCOPE`, `INGRESS_REPLAY_WINDOW_S`, `INGRESS_MAX_HEADER_BYTES`, `INGRESS_IDENTITY_CACHE_TTL_S`, `INGRESS_KEY_CACHE_TTL_S`, `INGRESS_KEY_OVERLAP_HOURS`. Server env keys for the env store: `INGRESS_AGENT_KEY_<ID>`, `_PREV`, `_PREV_EXPIRES`.

## Tests
Before: 2791 (v0.2.0 baseline). After: 2879 passed, 28 skipped (full suite, `uv run python -m pytest -q`); ruff check and format clean. New files: `tests/gateway/test_ingress_verifier.py` (48: timing-safe compare, replay in/out of window, clock skew, rotation overlap, header spoof/oversize/duplicate/malformed, stores, identity cache), `tests/gateway/test_ingress_routes.py` (14), `tests/recorder/test_ingress_traces.py` (9), `tests/gateway/test_ingress_cli_config.py` (12: CLI, defaults, startup warning, SDK, MCP), `tests/test_ingress_contract.py` (5: every AGENT route has the guard, route set pinned, grep of POST routes, rate-limit exempt set), `tests/e2e/test_ingress_auth_e2e.py` (laptop HMAC, databricks_fake bearer: SDK -> app -> real gateway decision).
Expert rubric (appsec engineer, ASVS v4 ch. 2-3, NIST 800-63B) is in the verifier test docstring and `docs/ingress-auth.md`. Note: the harness standard (golden sets, Wilson intervals) does not apply: no model or classifier is involved.
"databricks_fake" e2e uses SQLite for the gate store: the Delta fake is statement-scripted and WP20 adds no table. The mode (`databricks_app`), identity kind and fake identity verifier are exercised.

## Not done / limits
- OTLP exporters cannot sign HMAC (static headers); use bearer on the App, sidecar or SDK on the laptop (BACKLOG).
- Nonce cache in memory, one process; restart inside the window forgets nonces.
- Rejection flood writes one audit row each (no throttle).
- Real SCIM `Me` and `DatabricksSecretReader` not run against a live workspace. Add to the live kit.
- mTLS, bank vault store, console view of keys: not built.

## Open questions for the owner
1. Key custody: file / env / secret scope / bank vault. App rules say "no secret-scope resources": is an SDK runtime read of a secret scope allowed?
2. Does the Databricks Apps proxy forward the caller's `Authorization` header, or only `X-Forwarded-Access-Token`? Both are accepted; unverified live.
3. Rotation overlap (24 h default) and key lifetime policy.
4. Turn the flag on by default for the bank deployment? (Phase-2 decision "agent ingress credentials" is settled by this WP: per-agent HMAC or SP bearer.)

## Files touched
New: `src/supervisor/gateway/ingress_auth.py`, `src/supervisor/gateway/ingress_sign.py`, `src/supervisor/adapters/auth/agent_creds.py`, `src/supervisor/adapters/auth/agent_creds_identity.py`, `config/agent_identities.yaml`, `config/agent_keys.sample.yaml`, `docs/ingress-auth.md`, `docs/adr/D14-ingress-auth.md`, six test files above, this file.
Shared files, minimal additive edits: `src/supervisor/config.py` (WP20 block, two validator path entries, defaults in `_rules`, two properties), `src/supervisor/app.py` (import, startup check, `IngressRejected` handler), `src/supervisor/gateway/routes.py` (one dependency on `/check`), `src/supervisor/gateway/wiring.py` (`peek_gateway`), `src/supervisor/gateway/sdk.py` (credential + `SignedTransport`), `src/supervisor/gateway/mcp_proxy.py` (flags + `make_credential`), `src/supervisor/adapters/http_json.py` (`post_bytes`), `src/supervisor/recorder/otlp_receiver.py` (`authorize` now async, span check), `.gitignore` (`config/agent_keys.yaml`), `README.md`, `BACKLOG.md`, `docs/index.md`, `docs/threat-model.md`.
No new dependency. Merge hints: WP24b also edits `gateway/routes.py` and `engine.py`; my route edit is one line on `@router.post("/check")`. Commit trailers use the model line from the session system reminder (Claude Sonnet 5.5), not the "Fable 5.1" line in the brief.

## Self-review notes
R1-R3 hold (no model, no PII in audit/log, only SCIM Me to the configured host). No `exec`/`subprocess`. CLI ASCII (tested). Uses Starlette's private `request._body` to keep the body readable after signature check (covered by the e2e and route tests; revisit on a Starlette upgrade).

## Review follow-up (after REVIEW_WP20.md)

Tests: 2906 passed, 28 skipped (was 2879 at first handoff, 2888 after the Opus review fixes; +18 in `tests/gateway/test_ingress_followup.py`, a few existing tests adjusted). Ruff check and format clean.

| Item | Done |
|---|---|
| F8 | Claimed agent id checked before any secret-scope read (agent registry via gateway state, cached) and, for bearer, against `agent_identities.yaml` before any SCIM call. SCIM semaphore (`INGRESS_SCIM_MAX_CONCURRENT`, 4; waiters get 401 after 5 s). Refused tokens cached `INGRESS_IDENTITY_NEGATIVE_TTL_S` (30). HMAC always does two compares (F12). |
| F9 | `INGRESS_AUDIT_THROTTLE_S` (default 0 = audit all). Key (reason, client ip or claimed agent), 10k-key bounded map, `ingress_audit_suppressed` in `/gate/metrics`, next row carries `;suppressed=n`. Owner decision documented. |
| F10 | Per-agent nonce cap `INGRESS_NONCE_CAP_PER_AGENT` (20000) plus global cap; ordered dict, expired entries dropped from the front (O(1) amortised), no full scan. |
| F11 | `IngressVerifier.precheck(headers)` runs before the body is buffered (sizes, shape, timestamp, claimed agent). Header-stage audit rows have an empty `before_hash`. |
| Proxy kind | New `databricks_proxy` (X-Forwarded-Email, else X-Forwarded-User, mapped by `agent_identities.yaml`, case-insensitive for e-mails). Default in `databricks_app` mode; ignored with an error log outside it (header could be typed). `all` = hmac + sp + proxy. Bearer stays as `databricks_sp`. |
| Docs | `docs/ingress-auth.md` (preconditions: `--workers 1`, throttle decision, revocation delay, unsigned query string; live-kit check 1 = which headers reach the app), `docs/live-test-kit.md` item 11, ADR D14 follow-up section and open items. |

New settings: `INGRESS_SCIM_MAX_CONCURRENT`, `INGRESS_IDENTITY_NEGATIVE_TTL_S`, `INGRESS_AUDIT_THROTTLE_S`, `INGRESS_NONCE_CAP_PER_AGENT`; `INGRESS_CREDENTIAL_KIND` gains `databricks_proxy` and `all`.
Behaviour changes: `databricks_app` default kind is now `databricks_proxy` (was `databricks_sp`); e2e test selects `databricks_sp` explicitly. Files also touched: `adapters/auth/agent_creds_identity.py`, `docs/live-test-kit.md`.
Commit trailer: this follow-up uses the Fable 5.1 trailer from the brief.
