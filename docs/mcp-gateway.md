# HTTP MCP gateway with tool locking (WP26)

Status: built, off by default. ADR: `docs/adr/D24-mcp-http-tool-locking.md`. Code:
`src/supervisor/gateway/mcp_http.py` (proxy, review CLI), `mcp_lock.py` (hash, scan),
`mcp_lock_service.py` (store, approval, chain, cases), `src/supervisor/mcp_tools/api.py`
(routes), `adapters/mcp_upstream.py` (HTTP client), `gateway/mcp_http_harness.py` (evaluation).

Bank MCP servers will be remote streamable-HTTP servers. This gateway puts the same
deterministic gate in front of them as the stdio proxy does, and it locks the tool list: a new
or changed tool is hidden and cannot be called until two different people approve it.

## 1. Flags

| Flag | Default | Meaning |
|---|---|---|
| `MCP_HTTP_ENABLED` | `0` | `1` turns on the `/v1/mcp/tools` routes (otherwise HTTP 400 with the flag name) and lets the proxy process start (it refuses to start with `[SKIP]` and exit code 2 otherwise). |
| `MCP_TOOL_LOCK` | `1` | Inside the proxy: hold new or changed tools. `0` (or `--no-tool-lock`) gives the gate only. |
| `MCP_LOCK_REFRESH_S` | `60` | How long the proxy trusts one view of the server's tool list before it lists the server again. |
| `MCP_SERVER_AGENTS` | empty | App side. Extra agents allowed on a server another agent registered (`server=agentA|agentB;...`); others get 403. |
| `MCP_TOFU_INGRESS` | `0` | App side. `1` lets a proxy that talks to the app (`/v1/mcp/tools/observe`) use `--trust-on-first-use`. Off: the app answers 400 and the proxy fails closed. |
| `INVENTORY_ENABLED` | `0` | With `1`, the first sight of a server registers an `mcp_server` inventory node and a `uses` edge from the agent. |

## 2. How it fits

```text
 agent (MCP client)                                              remote MCP server
        | POST http://127.0.0.1:PORT/mcp                                  ^
        v                                                                 | POST (kept-alive,
 +----------------------- python -m supervisor.gateway.mcp_http ---------+  SSE or JSON back)
 |  initialize     -> forward, then lock the manifest                      |
 |  tools/list     -> list ALL pages upstream, hash, compare, HIDE new/changed tools
 |  tools/call     -> 1. lock check   (hidden or unknown tool -> MCP-TOOL-UNREVIEWED)
 |                    2. gate check   (the same McpGateProxy path as stdio; signed with --key-file)
 |                    3. forward with the gate's transformed args (inline redaction, if on)
 +-------------------------------------------------------------------------+
        | POST /v1/gate/check            | POST /v1/mcp/tools/observe, /blocked
        v                                v
   Supervisor app (rules, chain)    Supervisor app (mcp_tool_manifest, chain, case mcp_tool_review)
```

One listener per application: the process serves one agent id and one upstream server. Run one
process per application. A denied call is never forwarded. The client gets a normal MCP tool
error (`isError: true`, text `blocked by supervisor: <rule>: <reason>`, and
`result._meta.supervisor`), the same shape as the stdio proxy.

## 3. Start the proxy

Windows cmd:

```cmd
set MCP_HTTP_ENABLED=1
python -m supervisor.gateway.mcp_http --upstream https://mcp.bank.example/mcp --agent credit_agent ^
  --listen 127.0.0.1:9701 --gate-url http://127.0.0.1:8000 --key-file C:\secure\credit_agent.key
```

The agent's MCP client then points at `http://127.0.0.1:9701/mcp`.

| Option | Meaning |
|---|---|
| `--upstream URL` | The remote MCP endpoint (required). |
| `--agent ID`, `--agent-version V` | Agent id the gate judges these calls for; version default `mcp-http-1`. |
| `--listen HOST:PORT` | Default `127.0.0.1:9701`. A non-loopback host needs `--allow-non-loopback` and `--listen-token-env`. Choose a port the host does not use for another service. |
| `--path /mcp` | Endpoint path of the listener. |
| `--gate-url`, `--key-file`, `--bearer-token-env` | Same as the stdio proxy; the gate calls and the lock calls are signed for the agent (WP20, `docs/ingress-auth.md`). |
| `--server-name NAME` | Lock id of the server. Default: from the URL (`host:port_path`, no scheme, credentials or query). Use the name of the `mcp_servers` entry in the agent manifest to merge with the inventory. |
| `--upstream-bearer-env NAME` | Environment variable with a static bearer token for the upstream server. OAuth is wave 4. |
| `--listen-token-env NAME` | Require `Authorization: Bearer <value>` on the listener. |
| `--allow-origin ORIGIN` | Extra allowed `Origin`. Loopback origins are allowed; others get 403 (DNS rebinding). |
| `--refresh-s N` | Lock view lifetime (default `MCP_LOCK_REFRESH_S`). |
| `--no-tool-lock` | Gate only. |
| `--trust-on-first-use --by NAME` | Seed the first manifest (section 5). |
| `--inline-redaction` | Forward the gate's masked arguments (also `INLINE_REDACTION_ENABLED=1`). |
| `--timeout-s N` | Upstream read timeout (default 30). |

Transport rules: one POST per JSON-RPC message; the answer is JSON or an event stream; a
notification gets 202; JSON-RPC batches work; `Mcp-Session-Id` and `MCP-Protocol-Version` are
passed through; `DELETE` ends an upstream session. If the upstream sends server messages before
the response (an event stream), the client gets an event stream with them and the response.
Only server requests and notifications (messages with a `method`) are passed on: a response
with another id is dropped, so a hostile server cannot answer the client's `tools/list` ahead of
the filtered answer. A lock view that is not a list of tool names fails closed. Not
offered: the optional `GET` stream for server-initiated messages (405) and stream resumption.

The proxy keeps one `httpx` client per upstream and one for the Supervisor, so both hops reuse
their connections.

### Params and data methods (both proxies)

* A gated `tools/call` is forwarded with `name`, `arguments` (or the gate's masked arguments) and
  `_meta.progressToken` only. Other `params` keys, such as a smuggled `_meta` field, are dropped
  because the gate never judged them.
* `resources/read`, `resources/templates/list`, `prompts/get` and `completion/complete` reach data,
  so they go through the gate as the tools `mcp.resources.read`, `mcp.resources.templates.list`,
  `mcp.prompts.get`, `mcp.completion.complete` with the request params as arguments and the context
  field `mcp_method`. List them in the agent's policy (class `read_only`) to allow them. If the gate
  refuses one (or is unreachable), the client gets JSON-RPC error `-32000`, text
  `blocked by supervisor: <rule>: <reason>` and `error.data.rule_id`. `resources/list`, `prompts/list`
  and `tools/list` still pass (tools/list is filtered by the lock).
* The upstream notification `notifications/tools/list_changed` drops the lock view at once; the next
  `tools/call` lists the server again, so an honest change announced by the server is seen without
  waiting for `MCP_LOCK_REFRESH_S`. A server that does not announce its changes still has the window.
* `MCP_SERVER_AGENTS` (app side, default empty): `/v1/mcp/tools/observe` and `/blocked` accept an agent
  only for a server it registered first, or a new server. Another agent gets HTTP 403. To let a second
  agent share a server: `MCP_SERVER_AGENTS=credit-mcp.bank.example_mcp=agent_b|agent_c;other=agent_d`.

## 4. What the lock does

For each tool the proxy hashes: name, description, input schema, annotations (and title, output
schema when present). The hash is byte exact over canonical JSON. A tool list is also hashed as a
whole (order free). Compare with `mcp_tool_manifest`:

| Observed | Status | Agent sees it | `tools/call` | Chain record |
|---|---|---|---|---|
| hash equals the locked hash | `approved` | yes | gate, then forward | none |
| tool never approved | `new` | no | `MCP-TOOL-UNREVIEWED` | `mcp_tool_lock_change` (new) |
| approved before, hash differs | `changed` | no | `MCP-TOOL-UNREVIEWED` | `mcp_tool_lock_change` (changed) |
| changed back to the locked hash | `approved` | yes | gate | `mcp_tool_lock_change` (restored) |
| no longer listed | `removed` | no | refused (not in manifest) | `mcp_tool_lock_change` (removed) |
| two tools with one name | `changed`/`new` | no | refused | scan `duplicate_name` |

Other rules:

* `tools/list` always lists the whole server (every page), hashes it, records it and returns
  only the approved tools, without `nextCursor`.
* A `tools/call` uses the cached view if it is younger than `MCP_LOCK_REFRESH_S`; otherwise it
  lists the server first (on the proxy's own upstream session). A tool changed inside the
  window can be called once: keep the window short for sensitive servers.
* Fail closed: if the lock service or the upstream cannot be reached, `tools/list` returns a
  JSON-RPC error and `tools/call` returns `MCP-LOCK-UNAVAILABLE`.
* The refusal is written to the chain as `mcp_tool_blocked` (tool name, rule). It is not a gate
  decision; the gate response schema is unchanged.
* Descriptions never enter the chain, only hashes, names and finding kinds. The diff view
  shows the stored definitions (ASCII-escaped).

## 5. Seed the first manifest

Without a seed the first listing holds every tool and opens one review case. Two ways:

1. Review each tool (section 6). Safe, slow for a big server.
2. `--trust-on-first-use --by alice` on the first start. The proxy prints this to stderr:

```text
[WARN] --trust-on-first-use: every tool the upstream server lists NOW is locked as approved
without a second reviewer. Run it once, on a server you trust at this moment, and record the
review elsewhere. It is ignored when the server is already known.
```

The chain gets `mcp_manifest_seeded` with `seeded_by`, the list hash and the tool count; each
tool row carries `seeded_by`. It works only while the server has no manifest rows. It is a
human act claimed by the process owner, signed with the agent's key; the Supervisor cannot
check the name, so keep the start command in change control. When the proxy talks to the app
over HTTP (the normal case), the app accepts the seed only with `MCP_TOFU_INGRESS=1` (default
off: an agent credential, or anyone while `INGRESS_AUTH_ENABLED=0`, could otherwise seed any
server under any name). Turn it on for the first start only. The chain record names the
credential that sent the seed (`via`, for example `ingress:hmac:credit_agent`).

## 6. Review: list, diff, propose, approve

CLI (the app must be stopped, because the chain has one writer; or add `--supervisor-url` to use
the routes on a laptop):

```cmd
python -m supervisor.gateway.mcp_http tools list credit-mcp.bank.example_mcp
python -m supervisor.gateway.mcp_http tools diff credit-mcp.bank.example_mcp get_balance
python -m supervisor.gateway.mcp_http tools propose credit-mcp.bank.example_mcp get_balance --by khanh --hash <64-hex hash from diff>
python -m supervisor.gateway.mcp_http tools approve credit-mcp.bank.example_mcp get_balance --by an    --hash <64-hex hash from diff>
```

`--hash` is the full observed hash from `list` or `diff` (64 hex characters; a prefix is
refused, because a short prefix can be matched by a crafted definition). It binds your
approval to what you read: if the server changed the tool since, the approval is refused with
"the tool changed since you reviewed it". Output is ASCII; non-ASCII text in a definition is
shown as `\uXXXX`.

Routes (permission in brackets; the person is the authenticated principal, never a body field):

| Route | Permission | Roles |
|---|---|---|
| `GET /v1/mcp/tools?server_id=` | `mcp.tools.view` | every role |
| `GET /v1/mcp/tools/diff?server_id=&tool=` | `mcp.tools.view` | every role |
| `POST /v1/mcp/tools/propose` `{server_id, tool, observed_hash}` | `mcp.tools.propose` | reviewer, approver, owner, admin, operator |
| `POST /v1/mcp/tools/approve` (same body) | `mcp.tools.approve` | reviewer, approver, owner, admin |
| `POST /v1/mcp/tools/observe` | agent ingress (signed) | the proxy |
| `POST /v1/mcp/tools/blocked` | agent ingress (signed) | the proxy |

The rule: two DIFFERENT people (case-insensitive) approve the SAME observed hash. The first
may be an operator (`propose`), the second must hold `mcp.tools.approve` and use `approve`:
`propose` never completes the lock, even when it would be the second approval. Errors are HTTP 400
with a message ("already approved this change; a second, different person must approve", "the
tool changed since you reviewed it", "the tool is already approved"). Every approval and every
lock is a chain record with the principals.

A case `mcp_tool_review` opens by itself for each new or changed tool (one per tool and
observed hash; one per server for a first listing): medium, or high when the scan marks the
tool suspicious. It has no incident clock. Close it in the normal case flow; closing it does
not change the lock.

## 7. Poisoning scan (report only)

`mcp_lock.scan_tool` is deterministic. It reads the name, description, schema keys and values,
annotations, title, output schema and fields outside the hash, after Tier 0b normalisation
(NFKC, zero-width and bidi characters dropped, Cyrillic and Greek look-alikes folded, case and
diacritics removed, telex decoded). Finding kinds:

| Kind | Looks for |
|---|---|
| `injection_phrase` | The Tier 0b injection patterns ("ignore previous instructions", "bo qua huong dan", "system prompt", chat tags). |
| `instruction_phrase_en` / `_vi` | "ignore the above", "do not tell the user", "before using this tool ... read/send", "send ... to an external server", `~/.ssh`, `/etc/passwd`; Vietnamese "bo qua", "dung noi voi nguoi dung", "truoc khi dung cong cu nay", "gui toi" + a URL or address. |
| `prompt_markup` | `<IMPORTANT>`, `<system>`, HTML comments, `[SYSTEM]`, chat template tokens, code fences named `system`. |
| `hidden_unicode` | Zero-width, bidi, tag, private-use and control characters. |
| `name_nonstandard` | A tool name outside `A-Za-z0-9_.:-` (homoglyphs, trailing blanks). |
| `duplicate_name` | Two tools with one name. |
| `oversized_description` | A description over 4000 characters. |

A phrase split across two fields ("ignore" in the description, "previous instructions" in an
annotation) is found at the seam. A finding is `{kind, field, count}`; no matched text is stored.
The tool gets `suspicious = true` in the manifest and in the case. The scan does not block: the
lock does. The hook for the WP25 classifier is `mcp_lock.register_description_scorer(fn)`;
`fn(text) -> bp` is stored as `scan.score_bp` and never changes `suspicious`.

Known limits (probes X-20 to X-22, X-26, X-30): base64, ROT13 and leetspeak pass; a field that
the hash does not cover can change without drift; an LLM-ops tool whose description says
"system prompt" is marked suspicious (the reviewer decides).

## 8. Evaluation (harness)

```cmd
python -m supervisor.gateway.mcp_http_harness                 quality + latency, GO / NO-GO
python -m supervisor.gateway.mcp_http_harness --no-latency    quality only (CI, 6 s)
python -m supervisor.gateway.mcp_http_harness --gate-server   add the arm with the real gate over HTTP
python -m supervisor.gateway.mcp_http_harness --backend databricks_fake --split probe
python -m supervisor.gateway.mcp_http_harness --no-latency --record      rewrite baseline.json
```

Rubric: an application security engineer who reviews third-party MCP servers. Golden set:
`tests/fixtures/mcp_http/` (110 template items, dev and held-out; 33 probes outside the
templates; every item has source, licence, labeller). The upstream is a labelled MOCK (an
in-process fake server). The lock, the proxy, the store and the chain writer sink are the real
code. Thresholds are ILLUSTRATIVE.

Result at the commit recorded in `tests/fixtures/mcp_http/baseline.json` (SQLite):

| Metric | Templates (n) | Held-out (n) | Probes (n) | Threshold |
|---|---|---|---|---|
| Drift catch (tool changed, hidden) | 10000 bp (84/84) | 10000 bp (26/26) | 9642 bp (27/28) | templates 10000, probes 8500 |
| Lock false alarm (unchanged tool hidden) | 0 bp (0/400) | 0 bp (0/139) | 0 bp (0/9) | 0 |
| Poisoning catch (scan marks it) | 10000 bp (52/52) | 10000 bp (17/17) | 8260 bp (19/23) | 9000 / 8000 / 7500 |
| Scan false alarm | 0 bp (0/432) | 0 bp (0/148) | 714 bp (1/14) | 500 / 500 / 2000 |
| Removed tool logged | 10000 bp (10/10) | 10000 bp (1/1) | 10000 bp (2/2) | 10000 |
| Held tool called, refused by the lock | 10000 bp (194/194) | 10000 bp (62/62) | 9736 bp (37/38) | 10000 |
| Hidden tool reached the server | 0 | 0 | 0 | 0 |

Wilson 95% intervals are in the report (`--json`). The held-out poison phrases are a different
bank than the dev ones, and the scan was written against the dev bank only; all the same, the
template numbers say little about attackers: the probes are the honest row. Failure taxonomy of
the probes: 4 poison misses (`base64`, `rot13`, `leetspeak`, `unhashed_field`), 1 drift miss
(`unhashed_field`), 1 false alarm (`benign_lookalike`: the phrase "system prompt" of an LLM-ops
tool). All five are marked `known_gap` in `probes.json`. The overall verdict is GO against the
illustrative thresholds, with these limits written down. The regression test
`tests/gateway/test_mcp_http_harness.py` fails when any of these numbers falls below the
baseline. No model is used, so there is no model card; the WP25 classifier will need one.

## 9. Latency

Method of `tools/bench_latency.py` (monotonic clock, integer microseconds, warm-up discarded,
nearest-rank percentiles, three repeats, median of repeats), closed loop over one kept-alive
connection, one `tools/call` of `get_balance` that the gate allows. Loopback, one Python
process for the client, the proxy, the fake upstream and the gate, so they share the
interpreter lock. Full table and what is not measured: `docs/latency.md`, section "HTTP MCP
proxy".

| Path | p50 | p95 |
|---|---|---|
| client straight to the (mock) server | 0.18 ms | 0.29 ms |
| through the proxy, lock on, stub gate | 1.3 ms | 1.5 ms |
| through the proxy, lock on, real gate in process | 3.2 ms | 4.4 ms |
| through the proxy, lock on, real gate over HTTP, kept-alive (default) | 5.9 ms | 7.2 ms |
| same, a new gate connection per call (what `mcp_proxy` does) | 11.3 ms | 20.2 ms |

Delta against going straight to the server: +5.7 ms at p50 and +6.9 ms at p95 for the default
path, inside the illustrative budget (15 ms and 50 ms). The lock itself costs 15 us per call
(cached view).

## 10. Operating notes

* One chain writer: the app. The proxy never writes the chain; it asks the app. The review CLI
  without `--supervisor-url` opens its own runtime and must run while the app is stopped
  (the same rule as `python -m supervisor.jobs.inventory`).
* Rotate the upstream token and the agent key outside this tool. Neither is written to the
  chain or to logs; the proxy has no access log.
* A server rename (new URL) is a new server: its tools start as `new`. Use `--server-name` to
  keep the lock when a URL changes on purpose.
* Both stores are covered by tests: SQLite and `databricks_fake` (SQLite behind the REST
  marshalling code, labelled MOCK). On Delta, run `python -m supervisor.jobs.bootstrap_schema`
  once; the table is `mcp_tool_manifest`.
