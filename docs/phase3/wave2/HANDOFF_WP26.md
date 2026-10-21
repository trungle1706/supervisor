# HANDOFF WP26: HTTP MCP gateway with tool locking

Branch `wp26-mcp-http` (off tag v0.3.0). Four local commits, nothing pushed or merged. Flag
`MCP_HTTP_ENABLED` default off. Docs: `docs/mcp-gateway.md`, ADR `docs/adr/D24-mcp-http-tool-locking.md`.

## 1. What was built

| Part | Where |
|---|---|
| Streamable-HTTP MCP proxy `python -m supervisor.gateway.mcp_http --upstream URL --agent ID --listen 127.0.0.1:PORT`. Subclass of `McpGateProxy`: same gate path, evidence, `--key-file` signing, transformed args (`deny_response` factored out of `mcp_proxy.py`, behaviour unchanged). POST, JSON and SSE answers, pagination, `Mcp-Session-Id` pass-through, DELETE, batches, 202 for notifications. Refuses to start with the flag off (exit 2). Loopback only, Host and Origin checks, 4 MiB cap, optional inbound bearer, NODELAY. | `gateway/mcp_http.py` |
| Upstream client: one pooled `httpx.Client` per upstream, SSE parser, own lock session. The only httpx use (adapters). | `adapters/mcp_upstream.py`, `PooledJson` in `adapters/http_json.py` |
| Tool locking: byte-exact hash of name, description, input schema, annotations (+ title, output schema); list hash; diff with schema notes; report-only scan (tier0b patterns + EN/VI phrase list, hidden Unicode, markup, look-alike names, duplicate names, split-field seams, `_meta`-type fields); scorer hook `register_description_scorer` for WP25. | `gateway/mcp_lock.py` |
| Lock service: new table `mcp_tool_manifest` (both DDLs, `schema/model.yaml`, generator and Delta notebook current), new/changed tool hidden, `MCP-TOOL-UNREVIEWED`, two-person approval bound to the observed hash, removed tool logged, chain records `mcp_tool_lock_change`, `mcp_tool_approval`, `mcp_manifest_seeded`, `mcp_tool_blocked`, case `mcp_tool_review` (medium, high if suspicious, no incident clock), inventory node hook. | `gateway/mcp_lock_service.py` |
| Review: CLI `python -m supervisor.gateway.mcp_http tools list|diff|propose|approve` (direct, or `--supervisor-url` over routes); routes `GET /v1/mcp/tools`, `/diff`, `POST /propose`, `/approve` (RBAC `mcp.tools.view|propose|approve`, explicit identity), agent ingress `POST /observe`, `/blocked`. | `mcp_tools/api.py`, `core/rbac.py` |
| Trust-on-first-use: `--trust-on-first-use --by NAME`, ASCII warning, who recorded in the chain and in the row, ignored once the server is known. | `mcp_http.py` |
| Harness `python -m supervisor.gateway.mcp_http_harness` (all nine brief points), golden set, 33 probes, baseline, regression test. | `gateway/mcp_http_harness.py`, `tests/fixtures/mcp_http/`, `tests/gateway/test_mcp_http_harness.py` |
| Docs: mcp-gateway.md, ADR D24, integration guide pattern C (HTTP), latency.md section, threat model paragraph and gap row, README rows, BACKLOG (9 entries), CHANGELOG (Unreleased), inventory.md, index.md, console.md role matrix. | `docs/`, root files |

Design choice you may not expect: the proxy talks to the Supervisor app over HTTP
(`/v1/mcp/tools/observe`) instead of opening the database. The chain has one writer (the app); the
proxy needs no DB credentials; laptop and Databricks work the same. The lock refusal is a chain
record, not a gate decision, so the gate response schema is untouched (WP37).

## 2. Flags

| Flag | Default | Effect |
|---|---|---|
| `MCP_HTTP_ENABLED` | 0 | routes answer 400 with the flag name when off; the proxy and the `tools` CLI refuse to run |
| `MCP_TOOL_LOCK` | 1 | inside the proxy (`--no-tool-lock` = gate only) |
| `MCP_LOCK_REFRESH_S` | 60 | lifetime of a tool-list view on the `tools/call` path |

## 3. Commands and last lines

```text
uv sync
uv run python -m pytest -q -x            ->  3785 passed, 29 skipped, 1 warning in 477.85s
uv run python -m ruff check              ->  All checks passed!
uv run python -m ruff format --check     ->  675 files already formatted
uv run python -m supervisor.gateway.mcp_http_harness --gate-server -n 500 --repeats 3
                                         ->  OVERALL: GO
uv run python -m supervisor.gateway.mcp_http_harness --no-latency        (6 s)  ->  OVERALL: GO
uv run python -m supervisor.gateway.mcp_http_harness --backend databricks_fake --split probe --no-latency
uv run python tests/fixtures/mcp_http/build_golden.py --check            ->  [OK] fixtures are current
```

Tests: before 3,684 passed, 29 skipped (v0.3.0 per the brief; my own baseline run was disturbed by a DDL edit
and not repeated). After: 3,785 passed, 29 skipped, so +101. 97 of them are in the five new files:
`tests/gateway/test_mcp_lock.py` (45), `test_mcp_http.py` (26), `test_mcp_http_cli.py` (5),
`test_mcp_http_harness.py` (14), `tests/console/test_mcp_tools_api.py` (7); the rest are parametrised RBAC matrix
cases for the new routes. Both modes: SQLite and `databricks_fake` (lock unit test and harness probe parity).

## 4. Harness results (rubric: application security engineer reviewing third-party MCP servers)

Mock upstream (in-process fake server). Thresholds ILLUSTRATIVE. Wilson 95% in the report.

| Metric | Templates 110 items | Held-out 36 | Probes 33 | Threshold |
|---|---|---|---|---|
| Drift catch | 10000 bp (84/84) | 10000 (26/26) | 9642 (27/28) | 10000 / 8500 |
| Lock false alarm | 0 (0/400) | 0 (0/139) | 0 (0/9) | 0 |
| Poisoning catch (scan) | 10000 (52/52) | 10000 (17/17) | 8260 (19/23) | 9000 / 8000 / 7500 |
| Scan false alarm | 0 (0/432) | 0 (0/148) | 714 (1/14) | 500 / 2000 |
| Removed tool logged | 10000 (10/10) | (1/1) | (2/2) | 10000 |
| Held call refused / leaked upstream | 194/194 / 0 | 62/62 / 0 | 37/38 / 0 | 10000 / 0 |

Verdict GO. Honest reading: templates are saturated (I wrote both the scan and the phrase banks; dev and
held-out banks differ, but this is one author). The probes are the real row. Documented limits, each a
`known_gap` probe: base64 (X-20), ROT13 (X-21), leetspeak (X-22), poison in a field the hash does not cover
(X-26: lock does not hold it, scan marks it), and a false alarm on "system prompt" in an LLM-ops tool (X-30).
Latency per `tools/call`, keep-alive, p50 / p95: direct 0.18 / 0.29 ms; proxy + lock + stub gate 1.3 / 1.5; real
gate in process 3.2 / 4.4; real gate over HTTP kept-alive (default) 5.9 / 7.2; same with a new gate connection
per call (as `mcp_proxy`) 11.3 / 20.2. Lock alone: 15 us. Delta of the default path over direct: +5.7 ms p50,
+6.9 ms p95.

## 5. Files touched outside the WP26 package (shared files, minimal edits)

`schema/model.yaml`, `schema/ddl/sqlite.sql`, `schema/ddl/databricks.sql`, `notebooks/bootstrap_and_smoke.py`
(generated DDL), `src/supervisor/config.py` (block `# --- WP26 ---`), `src/supervisor/app.py` (one router),
`src/supervisor/core/rbac.py` (3 permissions, 6 routes), `src/supervisor/ops/openapi.py` (2 ingress paths, human
path prefix), `src/supervisor/cases/service.py` (`NO_CLOCK_SOURCES` + `mcp_tool_review`),
`src/supervisor/gateway/mcp_proxy.py` (`deny_response` extracted, same output), `src/supervisor/adapters/http_json.py`
(`get_json`, `PooledJson`), `pyproject.toml` (E501 ignore for the harness and its fixtures),
`tests/test_ingress_contract.py` (the two new ingress routes pinned on purpose; rate-limit exempt set unchanged),
`tests/test_rbac.py` (viewer and operator sets), `tests/console/test_rbac_matrix.py` (JSON-API prefix
`/v1/mcp/`), `docs/console.md` (role matrix regenerated), `docs/INTEGRATION_GUIDE.md`, `docs/latency.md`,
`docs/threat-model.md`, `docs/inventory.md`, `docs/index.md`, `README.md`, `BACKLOG.md`, `CHANGELOG.md`.
No new dependency (httpx and uvicorn were already in `uv.lock`). Not touched: console pages (the Agent page
Tools-tab link was skipped, WP39 owns it), the gate engine, the gate response schema.

## 6. Not done (also in BACKLOG)

OAuth to upstream servers (static bearer from an env var works; wave 4); GET stream and `Last-Event-ID`;
console view and approve buttons (WP39); scan blind spots above and the WP25 score (hook exists, no model);
per-server approver lists; closing the review case when the tool is locked; `mcp_proxy` still opens a gate
connection per call (pass `PooledJson` there: small, outside WP26); the CLI without `--supervisor-url` must run
with the app stopped (single chain writer); no live test against a real remote MCP server (all upstreams are
the MOCK fake); no TLS cost measured.

## 7. Review notes and deviations

* ADR number D24 as assigned (D22 is the highest on main; D23 left to another package).
* Commit trailers: the first commit carries "Claude Sonnet 5.5" (the session default), later ones "Claude Fable 5.1"
  as the brief says. I did not rewrite history to unify them.
* A whitespace-only change is drift on purpose (the older `mcp_tool_manifest_drift` assurance pack collapses
  whitespace; the two hashes are different and not meant to be compared).
* Two defects found on the way: a socket passed to uvicorn needs `TCP_NODELAY` (40 ms stalls on kept-alive
  connections; fixed in the harness and the listener); port 0 can land in 55000-59999, so every listener of this WP
  draws from 20000-29999.
* Neighbouring area, not fixed: `HttpGate` opens a new connection per call (BACKLOG).

## 8. Open questions for the owner

1. Is a one-person trust-on-first-use acceptable for the bank, or must the seed also need a second person?
2. Should a `suspicious` tool need an `approver`-role second approval (today the matrix is the same for all)?
3. Hash the whole tool object (closes the `_meta` blind spot, may add alarms on volatile fields)?
4. Refresh window default 60 s: one call can pass after a change inside the window. Tighten to 1 s (one extra
   upstream list per second) for money tools?
5. Close or comment the `mcp_tool_review` case automatically when the tool is locked?
6. Port policy for the proxy listeners in production (one per application, who assigns the ports)?
7. Does the bank want `OAuth` to the upstream servers before the pilot (wave 4 today)?

## Follow-ups after review

Reviewer commits (6194e0a, 3674064, 3bfbd5e, 2ff5281, a82ee23) kept as they are. Four items closed on top, history not rewritten.

| Item | Commit | What changed |
|---|---|---|
| F13 | a3ad754 | Both proxies forward `tools/call` params as `name`, `arguments` (or masked args) and `_meta.progressToken` only. `resources/read`, `resources/templates/list`, `prompts/get`, `completion/complete` go through the gate as `mcp.resources.read` etc. (context `mcp_method`); a refusal is JSON-RPC error -32000 with `error.data.rule_id`. The policy must list them (read_only) to allow them. Tests: `tests/gateway/test_mcp_proxy_params.py` (stdio, real gate) and `test_mcp_http.py` (HTTP). |
| F12 | 2b5f5e4 | `/observe` and `/blocked` return 403 when the server was registered by another agent. `MCP_SERVER_AGENTS` (`server=a|b;...`) shares a server. Deviation: the policy has no per-agent MCP server list, so the registering agent (server row) plus this setting is the rule. Test in `tests/console/test_mcp_tools_api.py`. |
| F14 | e8192e7 | `HttpUpstream` flags `notifications/tools/list_changed`; the proxy drops its lock view and re-lists on the next call. Test: change inside a 3600 s window is caught after the notification. |
| F15 | c7f8165 | 56 new hand-written probes (89 in total): 28 poison variants, 23 drift variants, 5 benign sets (40 tools). Probe n: drift 79, poison 51, scan negatives 73. New measured misses kept as `known_gap`: X-41 (forward-conversation phrase), X-58 (markdown heading, the line-start rule is lost by normalisation), X-65..X-68 (base64, hex, ROT13, leetspeak), plus false alarm X-121 ("Bo qua cac dong" in a CSV tool). Scan rules not tuned on probes. |

Harness (`--no-latency`): OVERALL GO. Template and held-out numbers unchanged. Probe row now: drift 9873 bp (78/79), poison 8039 bp (41/51, Wilson 6754-8899), scan false alarm 273 bp (2/73), held call refused 93/94, leaked 0. `baseline.json` was re-recorded only because the probe set grew (n and k of the probe row changed).

Checks (log `wp26_followup_full.txt` in the scratchpad):
```text
uv run python -m pytest -q -x          -> 3819 passed, 29 skipped, 1 warning in 481.20s
uv run python -m ruff check            -> All checks passed!
uv run python -m ruff format --check   -> 680 files already formatted
```
New test count: 3,819 (was 3,785 before the review; +34 from reviewer and follow-ups). Follow-up commits: a3ad754, 2b5f5e4, e8192e7, c7f8165, cc43754 (docs, BACKLOG: the three closed rows removed). No .env created.
