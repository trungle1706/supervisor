# D24: HTTP MCP gateway and tool locking

Status: accepted for WP26 (phase 3, wave 2). Flag `MCP_HTTP_ENABLED`, off by default. Inside the
proxy `MCP_TOOL_LOCK` is on by default.

The number is D24 because the work package owner reserved it. D22 is the last ADR on `main`;
D23 is left for another wave 2 package.

## Context

Bank MCP servers will be remote streamable-HTTP servers, not child processes. The stdio proxy
(`gateway/mcp_proxy.py`) cannot sit in front of them. Two risks come with a remote server that
the stdio proxy never had:

1. The tool list is data from a third party, read by the model on every session. A server (or
   whoever controls it) can change a description or a schema after review ("rug pull") or
   hide instructions in it ("tool poisoning"). The gate sees only the call, not the list.
2. A remote server is a new trust boundary: a network hop, a token, an HTTP listener.

## Decisions

1. **One proxy core.** `McpHttpGateProxy` extends `McpGateProxy`. The `tools/call` path
   (validation, gate check, transformed arguments, denial shape) is inherited unchanged. Only
   the transport (a stdlib listener, a pooled `httpx` upstream in `adapters/mcp_upstream.py`)
   and the lock are new. A denial looks the same to the client as in the stdio proxy
   (`deny_response`).
2. **The lock is deterministic and runs before the gate.** Each tool is hashed (SHA-256 over
   canonical JSON of name, description, input schema, annotations, plus title and output
   schema when present). The hash is byte exact: a whitespace edit is drift. A tool is
   `approved` only when its observed hash equals the hash two different people approved. A new
   or changed tool is hidden from `tools/list` and refused on `tools/call` with rule
   `MCP-TOOL-UNREVIEWED`, before the gate is asked. A removed tool is logged. The refusal is a
   chain record (`mcp_tool_blocked`), not a gate decision: the gate API and its response schema
   stay as they are (WP37 owns them).
3. **Two-person approval, same pattern as resume and sign-off.** Two DIFFERENT people approve
   the SAME observed hash; an approval names the hash the reviewer saw (a change between look
   and approve is refused; the full 64-character hash is required); a new hash drops the
   approvals so far. The first approval can come from an operator (`mcp.tools.propose`), the
   second needs `mcp.tools.approve` (`propose` never completes the lock). The acting
   person is the authenticated principal (`control=True`: explicit identity, no cookie).
4. **State lives in one table, `mcp_tool_manifest`** (both DDLs, `schema/model.yaml`): one row
   per server and tool, plus a server row (`tool_name = '*'`) with the whole-list hash. It has
   the locked and the observed definition so a diff needs no second source. A re-listing that
   changes nothing writes nothing.
5. **The chain gets hashes and names, never descriptions.** Records: `mcp_tool_lock_change`
   (new, changed, restored, removed, seeded), `mcp_tool_approval`, `mcp_manifest_seeded`,
   `mcp_tool_blocked`. Lane: the observing agent. Tool names are ASCII-escaped. Finding kinds
   are listed, matched text is not (R2).
6. **The poisoning scan is report only (R1).** It marks a tool `suspicious` and the review case
   `high` instead of `medium`. It never blocks; the lock blocks. It reads description,
   schema keys and values, annotations, title, output schema and the fields the hash does not
   cover, normalised like Tier 0b (NFKC, zero-width characters, Latin look-alikes, no
   diacritics, telex), and checks the seams between fields for split phrases.
   `register_description_scorer` is the named hook for the WP25 classifier: an integer score in
   basis points stored as `score_bp`, never part of `suspicious`.
7. **The proxy talks to the Supervisor over HTTP, not to the database.** `POST
   /v1/mcp/tools/observe` and `/blocked` are agent ingress (WP20 signing). The chain has one
   writer (the app), the proxy needs no database credentials, and it works the same on the
   laptop and on Databricks. The review CLI writes directly (app stopped) or calls the same
   routes with `--supervisor-url`.
8. **Trust on first use is explicit.** Without a seed, the first listing holds every tool.
   `--trust-on-first-use --by NAME` locks the current list as approved with no second person,
   prints an ASCII warning, records who ran it in the chain, and is ignored when the server is
   already known. Over the agent ingress the app accepts it only with `MCP_TOFU_INGRESS=1`
   (default off, review WP26 F3) and records the sending credential (`via`).
9. **A review case opens by itself.** Type `mcp_tool_review` (case source kind), medium, high
   when suspicious, one per tool and observed hash (one per server for the first listing). It
   carries no incident clock (`NO_CLOCK_SOURCES`, like the inventory flag cases).
10. **The listener is closed by default.** Loopback only (a non-loopback bind needs
    `--allow-non-loopback` and an inbound bearer), Host and Origin checked (DNS rebinding), body
    capped at 4 MiB, no GET stream. One listener serves one application.
11. **Inventory link.** With `INVENTORY_ENABLED=1` the first sight of a server registers an
    `mcp_server` node (evidence source `manual`) and a `uses` edge from the agent. A failure
    there never touches the lock.

## Consequences

* A new or changed tool is unusable until two people act. This is a cost, by design: a bank
  that wants speed seeds with trust on first use and reviews changes only.
* The lock view is cached for `MCP_LOCK_REFRESH_S` (60 s). A change between two refreshes can
  be called once in that window. `tools/list` is always checked against the live list; set the
  refresh to 1 for a tighter bound (one extra upstream list per second per proxy).
* The hash covers what the model reads. A field outside the hash (for example `_meta`) can
  change without drift; the scan still reads it. Probe X-26 keeps this limit visible.
* The scan is not a classifier: base64, ROT13 and leetspeak pass it (probes X-20 to X-22), and
  an LLM-ops tool that mentions a "system prompt" is marked (X-30). The lock is why this is
  acceptable; WP25 adds a score on top.
* One more table, six routes under `/v1/mcp/tools`, three RBAC permissions, two pinned ingress
  routes (the contract test lists them on purpose).

## Open

1. OAuth to the upstream server (a static bearer token from the environment works now): wave 4.
2. The GET stream (server to client messages outside a request) and `Last-Event-ID` resumption.
3. `HttpGate` still opens a connection per call in the stdio proxy; the HTTP proxy passes a
   pooled client (see `docs/mcp-gateway.md`, latency).
4. Who may approve which server (per-server approver lists) is not modelled; the role matrix
   decides.
5. Decision of the owner: should a tool whose scan marks it suspicious need an `approver` role
   on the second approval? Today the role matrix is the same for all tools.
