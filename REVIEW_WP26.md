# REVIEW WP26: HTTP MCP gateway with tool locking

Reviewer: Opus (security review, bank view). Branch `wp26-mcp-http`, worktree
`agent-af09d805020e5271e`. Base `v0.3.0`; the author's head was `5b33bf1`. Nothing pushed,
merged or rewritten.

## 1. Verdict

**APPROVED WITH FOLLOW-UPS** for integration.

I found three High and five Medium defects. I fixed all of them on the branch and added tests.
Two of the High findings let a hostile remote MCP server or a machine credential get past the
lock. The open items are Low or are owner decisions (section 6).

| Result | Before review | After review |
|---|---|---|
| `pytest -q -x` | 3,785 passed, 29 skipped | 3,811 passed, 29 skipped (+26) |
| `ruff check` / `ruff format --check` | pass / pass | pass / pass |
| Harness `--no-latency` | OVERALL: GO | OVERALL: GO (same numbers) |

## 2. Findings

Line numbers are at the author's head `5b33bf1`.

| ID | Sev | File:line | What | Fix |
|---|---|---|---|---|
| F1 | High | `adapters/mcp_upstream.py:235` | **Lock bypass by a hostile server.** `request()` put every upstream event-stream message whose id was not the request id into `extras`, and the listener sends `extras` to the client AHEAD of the answer. A server can send `{"id": <client id>, "result": {"tools": [hidden, poisoned tool]}}` in the stream of the proxy's own `tools/list`. The client then gets two answers with its id, and the first one is the unfiltered list, so the model reads the poisoned description. I confirmed this on the original code: the test gets 2 answers. | 3674064: only messages that have a `method` (server requests and notifications) are passed on. Test `test_f1_hostile_sse_upstream_cannot_answer_the_clients_tools_list` |
| F2 | High | `gateway/mcp_lock_service.py:564` | **RBAC bypass of the two-person rule.** `done = len(ap)+1 >= 2` did not look at the role. Two operators (only `mcp.tools.propose`) could lock a tool with `propose` twice, and `propose` after an approver also locked it. ADR D24 decision 3 says the second approval needs `mcp.tools.approve`. | 6194e0a: `propose` never completes the lock (400 "use approve, not propose"). Tests `test_f2_*` (2) |
| F3 | High | `mcp_tools/api.py:128` | **A machine credential could seed a server as approved.** `/observe` accepted `trust_on_first_use_by` from any caller that passes agent ingress. With `INGRESS_AUTH_ENABLED=0` (laptop default) that is any local caller. Any agent credential could pre-seed a server id that is not known yet (the id comes from the URL and is easy to guess) with the poisoned definitions and a human name it claims. The real proxy then finds the tools "approved". The chain wrote the claimed name as if a person did it. | 6194e0a: new app flag `MCP_TOFU_INGRESS` (default 0). When it is off, the route gives 400 and the proxy fails closed. When it is on, the chain record `mcp_manifest_seeded` adds `via` (for example `ingress:hmac:payments`). The local (DB) path is unchanged. Tests `test_f3_*` (2) |
| F4 | Medium | `gateway/mcp_http.py:386` | `--allow-non-loopback` without `--listen-token-env` started an open proxy on the network, which also carries the upstream token. The ADR and the doc say both are necessary. | 3674064: refused with `ValueError`. Test `test_f4_*` |
| F5 | Medium | `mcp_lock_service.py:541,551`, `api.py:65` | An approval matched a 12-hex-character PREFIX of the observed hash (48 bits). A server that controls the definition can brute-force a poisoned definition with the same prefix that the reviewer copied, and swap it in between "look" and "approve". | 6194e0a: the full 64-hex hash is necessary (`hmac.compare_digest`). The CLI `list` prints the full hash. Docs updated. Test `test_f5_*` |
| F6 | Medium | `gateway/mcp_http.py:324` | `tools/list` with `"id": null` was not filtered (the check was `id is not None`). The upstream reply went to the client unfiltered. | 3674064: filter when `"id" in message`. Test `test_f6_*` |
| F7 | Medium | `tests/gateway/test_mcp_http.py` | Fail-mode proof was missing. No test showed that money, credit or PII-export tools fail closed when the Supervisor app is down, when `/observe` returns 4xx or 5xx, when httpx raises, or when the view is stale and the upstream is down. | 3674064: `test_failmode_*` (3 tests, 14 cases). Section 3 |
| F8 | Medium | `gateway/mcp_http.py:290` | Found by the new F7 test. The proxy trusted the shape of the lock view: `name in view["visible"]` with a STRING `visible` is a substring test, so `"transfer" in "transfer"` passed. A wrong answer from the app (or a proxy in front of it) failed OPEN. | 3674064: the view is checked (a list of strings, a mapping); otherwise `MCP-LOCK-UNAVAILABLE`. `visible` is held as a `frozenset` |
| F9 | Low | `mcp_lock_service.py:182` | A tool named `*` had the same key as the server row (`manifest_id(server,'*')`). This corrupted the server row (an insert collision was silently ignored). It was not callable. | 6194e0a: refused (fail closed). Test `test_f9_*` |
| F10 | Low | `gateway/mcp_http.py:541` | A deeply nested body (`[[[[...` up to 4 MiB) raised `RecursionError` out of the handler, and the connection was dropped with no answer. | 3674064: 400 parse error. Test `test_f10_*` |
| F11 | Low | `gateway/mcp_http.py:208` | `self._seq += 1` is not atomic across listener threads, so lock request ids could repeat on one session. | 3674064: `itertools.count`. Test `test_lock_ids_do_not_repeat_across_threads` |
| F12 | Low | `mcp_tools/api.py:119` | `/observe` does not bind `server_id` to the agent. Any valid agent credential can re-list another application's server: tools flip to `changed` or `removed` until the real proxy lists again, and this writes extra chain records and cases. It is not a bypass, because approval stays bound to the hash. | open (BACKLOG): per-server agent allowlist |
| F13 | Low | `gateway/mcp_proxy.py:111` (inherited) | Only `params.name` and `params.arguments` go to the gate. Other keys in `params` (for example `_meta`) and the other methods (`resources/read`, `prompts/get`) go upstream with no gate check. A model rarely controls `_meta`, but a compromised client does. The stdio proxy has the same gap. | open: recommend stripping `params` to `name`, `arguments` and `_meta.progressToken` in both proxies |
| F14 | Low | `gateway/mcp_http.py` | The proxy ignores `notifications/tools/list_changed`. If the view were invalidated on it, most of the 60 s window would close for honest servers. | open (BACKLOG), see owner question 4 |
| F15 | Low | harness probes | The probe rows have n below the brief's 50 (drift 28, poison 23, benign 14). The Wilson lower bounds are wide (poison 6286 bp). The n is reported honestly but no reason is given. | open (BACKLOG) |
| F16 | Low | `tests/gateway/test_mcp_lock.py:364`, harness | The "databricks_fake" coverage uses the WP23 marshalling fake (SQLite SQL text with Delta value marshalling). The Delta `MERGE` and `UPDATE` text for `mcp_tool_manifest` never runs against `FakeStatementExecution`. The store code is generic and other tables cover it, and the DDL is generated and checked. | open (BACKLOG): a scripted `DatabricksRestExecutor` test like `tests/inventory/test_databricks_mode.py` |
| F18 | Low | `gateway/mcp_http_harness.py` | With `--gate-server` the harness prints one `httpx` INFO line per gate call (about 2,500 lines), which hides the report. The "lock alone 15 us" figure is within noise (my run: -104 us). | open: set the `httpx` logger to WARNING in the harness; report the lock cost as "below noise" |
| F17 | Low | dev auth | On the laptop (`AUTH_KIND=dev_header`) and in the direct CLI, `--by` / `X-Dev-User` is not an identity. One person can approve twice under two names. This is the ADR D04 laptop posture. On Databricks the SSO principal is used. | open: document; no code change |

Things I checked that are correct: the lock runs before the gate, also for notifications and
for each item of a batch. A non-string or missing tool name gets a JSON-RPC error from the
inherited path and is never forwarded. Names match exactly (case and Unicode variants are
other tools, so they are hidden). Duplicate names hash as a group. Pagination is always
followed in full (`MAX_PAGES`). A new hash drops the earlier approvals. A stale-hash
approval is refused. Same-person approval is refused case-insensitively. The lock session is
reopened once. The 60 s window is documented and tested. Both the gate and the lock fail
closed (`GATE-UNREACHABLE`, `GATE-AUTH`, `MCP-LOCK-UNAVAILABLE`). `/observe` and `/blocked`
bind the body `agent_id` to the credential through `ingress_gate` (403), and the single-use
nonce stops a replay (401). I added tests for both. The chain payloads hold only hashes, ASCII
names, finding kinds, principals and rule ids. I found no description or argument text in a
chain or log write (`grep` of `_chain(`, `log.`, `record(`). The PII path is the inherited
`McpGateProxy` path, so the masking and `--inline-redaction` are the same as on stdio. Host and
Origin are checked, the body cap is 4 MiB (411 without a length), the bearer check uses
`compare_digest`, there is no access log, the CLI is ASCII, the bind is loopback, and the test
ports come from 20000-29999. Shared-file edits (handoff section 5): rbac (3 permissions,
operator gets only `propose`), the ingress contract pins and `MCP_RATE_LIMITED`,
`NO_CLOCK_SOURCES`, the `deny_response` extraction (byte-identical output), the openapi
human prefix (ingress is checked first), and the E501 ignore (only the harness and its
fixtures) are all minimal and correct. Delta DDL = SQLite DDL = `model.yaml` (generated,
`test_schema` checks them). Flags: `MCP_HTTP_ENABLED=0`, `MCP_TOFU_INGRESS=0`.

## 3. Fail-mode results (new tests, all pass)

| Condition | Tools | Result | Reached upstream | Test |
|---|---|---|---|---|
| Supervisor app down (gate on a dead port, pooled client), lock view approves | transfer, approve_credit, export_customer_pii | `GATE-UNREACHABLE`, isError | no | `test_failmode_supervisor_app_down_blocks_money_credit_and_pii_tools` (3) |
| `/observe` answers 500, 503, 400, 403 | all three | `MCP-LOCK-UNAVAILABLE` | no (and no gate call) | `test_failmode_observe_route_errors_fail_closed` |
| httpx `ConnectError`, `ReadTimeout` | all three | `MCP-LOCK-UNAVAILABLE` | no | same |
| 200 with `{}` or with a wrong shape (`"visible": "transfer"`) | all three | `MCP-LOCK-UNAVAILABLE` (it was a fail-OPEN, F8) | no | same |
| A view that names other tools only | all three | `MCP-TOOL-UNREVIEWED` | no | same |
| Stale view (31 s > 30 s) and the upstream down | transfer (approved before) | `MCP-LOCK-UNAVAILABLE`, the gate is not asked | no | `test_failmode_stale_view_and_upstream_down_blocks_an_approved_tool` |
| Lock service raises (author's test) | get_balance | `MCP-LOCK-UNAVAILABLE` | no | `test_lock_service_failure_fails_closed` |
| Upstream down at start (author's test) | - | list: -32603; call: `MCP-LOCK-UNAVAILABLE` | - | `test_upstream_down_is_an_error_not_a_hang` |

## 4. Commits added by the review

| Commit | Content |
|---|---|
| 6194e0a | F2, F3, F5, F9: lock service, routes, flag `MCP_TOFU_INGRESS`, route tests `tests/console/test_mcp_tools_review.py` (ingress binding, replay, TOFU), existing tests moved to the full hash |
| 3674064 | F1, F4, F6, F7, F8, F10, F11: proxy and upstream client, `inject` hook in the MOCK fake server, `tests/gateway/test_mcp_http_review.py` |
| 3bfbd5e | Docs: mcp-gateway.md, ADR D24, README, CHANGELOG, BACKLOG (4 new rows), threat model, integration guide |
| (this commit) | This report |

New tests: 26 (22 in `tests/gateway/test_mcp_http_review.py`, 4 in `tests/console/test_mcp_tools_review.py`); 5 existing tests changed only from a hash prefix to the full hash.

## 5. Commands run (last lines)

```text
uv run python -m pytest -q -x            (before)  3785 passed, 29 skipped, 1 warning in 484.10s
uv run python -m pytest -q -x            (after)   3811 passed, 29 skipped, 1 warning in 505.87s
uv run python -m ruff check                        All checks passed!
uv run python -m ruff format --check               678 files already formatted
uv run python -m supervisor.gateway.mcp_http_harness --no-latency          OVERALL: GO   (2.7 s)
uv run python -m supervisor.gateway.mcp_http_harness --gate-server -n 300 --repeats 1
  direct 174/314 us; proxy+lock+stub gate 1069/1570; real gate in process 3330/4608;
  gate over HTTP new connection 11323/20242; kept-alive (default) 5923/8736 (p50/p95)
  overhead of the default path over direct: p50 5749 us, p95 8422 us      OVERALL: GO
```

Harness honesty: the template rows are saturated (10000 bp, one author for both the scan and
the banks), and the handoff says so. The probe row is the real signal: drift 9642 bp (27/28,
Wilson 8228-9937), poison 8260 bp (19/23, 6286-9303), scan false alarm 714 bp (1/14). The
five `known_gap` probes (X-20 base64, X-21 ROT13, X-22 leetspeak, X-26 unhashed field, X-30
"system prompt" look-alike) are asserted to STAY misses, so a silent "fix" that games them
would show. The regression test compares each metric with `baseline.json` (date and commit
inside) and fails on a drop. The `databricks_fake` probe run gives the same numbers (test).
Latency: see section 5. The order and size match the handoff (direct well under 1 ms, proxy
plus stub gate about 1 ms, gate over HTTP kept-alive a few ms, a new gate connection per call
about twice that). This is one process on loopback, so it is not a production figure.

## 6. Owner questions (handoff section 8): recommendations

| # | Question | Recommendation |
|---|---|---|
| 1 | One-person trust on first use? | Not for production. Keep `MCP_TOFU_INGRESS=0` on the Databricks App. Replace the proxy-side seed with a human route `POST /v1/mcp/tools/seed` (`mcp.tools.approve`, authenticated principal, bound to the observed LIST hash), and make it two-person for servers that expose money, credit or PII-export tools. Allow one-person TOFU on the laptop pilot only. |
| 2 | Suspicious tool needs an `approver` role? | Yes. When `suspicious` is true, require that the locking approval comes from `approver`, `owner` or `admin` (not only `reviewer`), and that the case is high. The cost is low and it matches the sign-off pattern. |
| 3 | Hash the whole tool object? | Yes, with a short denylist of known volatile keys (start with `_meta.progressToken` and any vendor timestamp key found on the pilot servers). Measure the alarm rate on the pilot servers for one week before you switch. This closes X-26. |
| 4 | Refresh window 60 s? | Make it per risk: for money, credit and PII-export tools, re-list before EVERY call (or 1 s), and invalidate the view on `notifications/tools/list_changed` (F14). Keep 60 s for read-only tools. The extra cost is one upstream `tools/list` per sensitive call. |
| 5 | Close the review case on lock? | Auto-comment, do not auto-close: write the approvers and the locked hash on the case. Closing a high case stays a human two-person act. |
| 6 | Port policy? | One committed registry (`config/mcp_proxies.yaml`: application, agent id, upstream, port) under change control. Use 20000-29999 and keep away from the hosted ranges. Preflight refuses duplicates. The platform team assigns the ports. |
| 7 | OAuth to upstream before the pilot? | Only for third-party or internet servers. For bank-internal servers behind the API gateway, a static token from a secret (rotated) is acceptable for the pilot if mTLS or a network allowlist is also used. |

## 7. Not changed (outside WP26 or design)

F12 to F17 are recorded above and in BACKLOG. I did not touch the stdio proxy (F13), the gate
engine, or the console.
