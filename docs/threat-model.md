# Threat model: the Supervisor itself

Scope: this repository as built (WP0 to WP11). Source of the attacker list: analysis 02
section 3.6. Each control below names the file that implements it; a control that is
designed but not built is listed under **Known gaps**, not as a control. Date 2026-10-14.

## 1. Assets

| Asset | Where | Why it matters |
|---|---|---|
| Gate decision path | `src/supervisor/gateway/engine.py`, `policies/*.yaml` | Blocks or pauses money, credit and PII actions |
| Agent gate state (RUNNING / PAUSED / QUARANTINED) | `agent` table, `src/supervisor/gateway/state.py` | Pause is the kill switch |
| Evidence chain | `chain_entry`, `chain_payload`, `chain_signature`, `anchor` tables; `src/supervisor/evidence/` | Proof for the regulator and the audit |
| Signing key of the chain heads | `<DATA_DIR>/keys/` or `SUPERVISOR_SIGNING_KEY` env (`evidence/signer.py`) | Whoever holds it can sign a rewritten chain |
| Case files, sign-offs | `cases`, `case_event`, `signoff` tables; `src/supervisor/cases/service.py` | Human decisions, exported verbatim |
| Policy and thresholds | `policies/`, `rule` table | Weak policy = no control |
| Masking and args HMAC keys | `MASK_HMAC_KEY`, `ARGS_HASH_KEY` | Pseudonymisation of PII in evidence |
| Synthetic data only | `src/supervisor/data/` | No real customer data in this repo |

## 2. Trust boundaries

```
 agents --(tool call)--> GATEWAY --(rule result)--> agent    [B1 agent / gateway]
 agents --(spans)------> recorder / OTLP receiver             [B2 telemetry in]
 traces --(masked text)-> JUDGE models (advice only)          [B3 judge / model]
 gateway, cases ------> CHAIN WRITER (single writer) -> store  [B4 evidence write]
 browser (reviewer) ---> CONSOLE (SSO headers or dev header)   [B5 human / console]
 Databricks App SP ---> SQL warehouse, serving endpoint        [B6 platform identity]
 laptop user ---------> SQLite file, key file, CLI             [B7 local operator]
```

| Boundary | Who is on each side | Trust rule |
|---|---|---|
| B1 Agents / gateway | Agent code (not trusted) / Supervisor | The gate decides from rules and facts, not from what the agent claims about itself |
| B2 Telemetry | Agents and collectors / recorder | Spans are data; they never change gate state |
| B3 Judges | Model endpoint / Supervisor | Model output is untrusted text; it can only advise |
| B4 Chain writer | Supervisor process / store | One writer per store; append only |
| B5 Console users | Reviewers, approvers, owners, auditors, admins / Supervisor | Identity from the workspace SSO headers on the App; roles from `config/auth.yaml` |
| B6 App service principal | Databricks platform / Supervisor | OAuth only; no PAT; read-only when no user is signed in |
| B7 Laptop user | The person who runs the laptop build | Full control of local files (see gaps) |

## 3. Attackers and controls

### 3.1 Malicious or hijacked agent

Goal: run a harmful tool call, or switch supervision off.

| Control | Code |
|---|---|
| Deterministic Tier 0 rules (allow-list, limits, stateful windows, required facts) decide; fail closed for money, credit and PII export | `gateway/engine.py`, `gateway/policy.py`, `policies/baseline.yaml` |
| 2 s hard timeout; a rule error or timeout applies the rule's fail mode, not "allow" | `gateway/engine.py` (`HARD_TIMEOUT_S`, `fail_mode`) |
| Agent SDK fails closed when the gate is unreachable (except read-only tools marked fail open) | `gateway/sdk.py` (`HttpGate._fallback`) |
| Facts come from the system of record, not from the tool arguments | `gateway/facts.py`, `fact.*` predicates in `gateway/engine.py` |
| A rule can pause the agent; resume needs two different people (owner + reviewer) within a window | `gateway/state.py` (`resume`), ADR D04 |
| Tool arguments enter evidence as HMAC only (`args_hmac`, key id recorded) | `core/args_hmac.py` |
| Hand-offs record the calling agent (`caller_agent_id`) so a split across agents is visible | `gateway/engine.py`; rule `PAY-08` |

### 3.2 Prompt injection through tickets, e-mails or documents

Goal: make an agent act, or make a judge say "safe".

| Control | Code |
|---|---|
| The gate does not read model text; injected instructions cannot change a rule result | `gateway/engine.py` |
| Tier 0b screen for PII patterns and injection markers (alert, async) | `gateway/tier0b.py` |
| Judge prompts wrap trace text in a nonce-delimited data block, escape it, and plant a canary; a canary echo marks the output invalid | `judge/prompts/build.py`, `judge/runner.py` |
| Injection markers set a score floor so a fooled judge cannot clear the trace | `judge/runner.py` (`marker_floor_bp`), `judge/service.py` |
| Text is masked before any judge sees it | `judge/masking.py`, `adapters/masking/vn_regex.py` |

### 3.3 Judge manipulation

Goal: a judge clears a harmful trace, or a judge is used to block or unblock.

| Control | Code |
|---|---|
| Judges only advise: a tier 1/2 verdict must be `advisory`, actions are log / alert / open_case / raise_severity; the judge never calls the gate | `core/models.py` (`Verdict`), `judge/service.py` |
| Judge model family must differ from the agent family, checked at startup | `judge/router.py` (`FamilyConflictError`) |
| Tier 1 and Tier 2 disagreement goes to a human, not to the more lenient tier | `judge/service.py` (`_decide`) |
| Mock judges are labelled `mock` in every verdict and in the console | `judge/mockjudge.py`, `is_mock` column, console `MOCK` badge |
| Remote model endpoints are refused unless `LLM_ALLOW_REMOTE=1` | `config.py` (`is_loopback_url`) |

### 3.4 Compromised reviewer (or a single insider)

Goal: close a real incident as a false alarm, resume a paused agent alone, or hide it.

| Control | Code |
|---|---|
| High and critical cases need two approvals by two different people, at least one approver | `cases/service.py` (`sign_off`, `TWO_PERSON_SEVERITIES`) |
| Workflow actions are accepted from signed-in people only, never from a system or service principal | `cases/service.py` (`require`) |
| Two-person resume, enforced by the gateway state machine and the console | `gateway/state.py`, `console/routes.py` |
| Every action writes `case_event` with actor, actor kind and auth method, and an evidence record | `cases/service.py` (`_event`) |
| Stale page edits are refused (`row_version`), never silently overwritten | `cases/service.py` |
| Console POSTs require `HX-Request: true` (CSRF guard) | `console/routes.py` |
| `AUTH_KIND=dev_header` is refused in `SUPERVISOR_MODE=databricks_app` | `config.py` (`_rules`) |

### 3.5 Chain writer compromise or evidence tampering

Goal: edit or delete evidence after the fact.

| Control | Code |
|---|---|
| Hash chain per lane plus a root lane; root entries signed with Ed25519 | `evidence/chain.py`, `evidence/signer.py` |
| Append-only triggers on chain and other evidence tables (SQLite DDL) | `schema/ddl/sqlite.sql` (`trg_chain_entry_no_update`, ...) |
| Single writer: a second writer on the same lane gets `ChainConflictError`, the chain never forks silently | `evidence/chain.py` |
| Offline verifier with a pinned public key; finds the first broken entry | `evidence/verify.py`, `python -m supervisor.cli verify --pubkey` |
| Anchors of signed heads to a separate target (`worm_dir` / UC volume) | `evidence/anchor.py`, `jobs/anchor.py` |
| No floats and no raw PII in chain payloads (masker on every string) | `evidence/chain.py`, `core/canonical.py` |
| Demo proof: one byte flipped in an export copy is caught | `demo/tamper.py`, `tests/demo/test_harness.py` |

### 3.6 Supply chain and secrets

| Control | Code |
|---|---|
| Locked dependencies (`uv.lock`), `requirements.txt` exported from the lock and tested | `tests/test_requirements_current.py` |
| No secrets or real workspace ids committed; `FILL-ME` placeholders | `tests/test_no_secrets.py` |
| Hand-off zip built from `git archive HEAD`, then leak-swept; the release fails on any hit | `src/supervisor/release.py` |
| No `exec`, `eval`, `compile` or `subprocess` outside one module (AST test) | `src/supervisor/sandbox.py`, `tests/test_architecture.py` |
| No PAT: preflight and settings refuse `DATABRICKS_TOKEN` | `config.py`, `preflight.py` |

### 3.7 Tool analytics and least-privilege suggestions (WP22)

New read surface: `GET /v1/analytics/tools` and the console Tools page show per-tool usage; the
owner can download a suggested policy diff. The rollup stores counts only (distinct callers and
users are counted from HMAC hashes, never stored), so it adds no personal data. The risk is
a wrong suggestion, not a leak: a diff that removes a needed tool would stop a business flow,
and a diff that is applied blindly would weaken review. Controls: nothing is applied by code
(a test hashes `policies/` and the manifests); the diff raises the rule version, so it must pass
the two-approver policy PR; no data or too little history means nothing is proposed;
documented exceptions carry an approver and an expiry; tools called but not declared are only
flagged, never added. The suggestion cannot add a permission, so a poisoned usage log cannot
widen an agent's access; it can only make a removal proposal look wrong, which a reviewer sees
in the table.

### 3.8 Trust boundary added by WP21 (SIEM export, alerts, webhook)

Supervisor can now open outbound connections: the SIEM `http` sink and the webhook notifier
(both off by default, URL and token are `FILL-ME` values from the bank vault). Controls: only
ids, enums, counts and hashes are sent (a fixed field list builds every event and alert; tests
plant free text and a phone number and assert they never appear); the token is a `SecretStr`,
sent only in the `Authorization` header and never logged or written to the dead-letter file;
sends are bounded (3 attempts, 10 s timeout) and a failure never blocks a gate decision, a case
action or the alert row; a failed batch waits in a local dead-letter file with an idempotency key
for replay. The receiver is trusted by the bank, not by us: a wrong URL sends metadata (agent
ids, rule ids, counts) to the wrong place, so the URL is a reviewed setting. Alert rules are
YAML read with `safe_load` and validated, never evaluated as code. Acknowledging an alert needs
a signed-in person with `alert.ack` and is audited. Alerts do not act on agents (R1), so a
forged alert cannot pause or block anything.

### 3.9 Console pages added by WP-UX3 (Playground, Credentials, Audit log, ...)

The Playground (`POST /console/playground/run`, role `operator` and up, flag off by default, a
second flag on the App) lets a person send arbitrary JSON to the gate's evaluation. Risks and
controls: (1) side effects, removed by construction (`Gateway.evaluate_only` shares the decision
function and writes nothing; a byte-for-byte test, ADR D22); (2) personal data typed into the
form, never echoed or stored (the audit row keeps a keyed HMAC, not the input; the answer shows a
masked preview); (3) abuse as a load or ReDoS vector, bounded by 16 KB and 4 KB input caps, a
nesting limit, strict JSON object checks, the gate's own 2 s timeout, and the existing rule
regex limits (D11). The Credentials page reads only key id, state and expiry, never a secret
(a test plants a secret and checks the page and headers), and an unreadable key store shows the
error class only. The Traces page shows only masked columns and passes them through the masker
again; a `digest` event shows no text, and no masker means no text. Every new page is read-only,
behind its own permission and flag, and every filter value is checked against an allow-list or a
strict pattern (bad input is HTTP 400); filters reach the store only as named parameters.

### 3.10 Detector findings (WP37, ADR D23)

Trust boundary: the verdict that the gate returns to the agent and stores. With
`DETECTORS_ENABLED=1` the answer, the `finding` table, the `agent_event` columns, the chain record
and the SIEM event carry detector results. The risk is that a finding repeats the data it found:
a phone number in an entity, a name in a fragment, a key that is a name in a path. Controls:
entities hold pseudonym tokens only; fragments are located on MASKED text (the masker runs first,
offsets index the masked text, the excerpt is a masked substring, the raw text is never copied);
a path shows dict keys that are plain identifiers and `*` for any other key; an exception message
is never copied (only the class name); the chain gets finding codes, counts, coverage reasons and
SHA-256 digests, never text; the harness checks every answer for a raw sensitive string
(`leak_items` must be 0). The second risk is a detector that can stop a payment. A finding never
blocks or pauses (a `pause` or `block` hint counts as `report`); only the rule `GATE-DETECTOR-FAILED`
blocks, when a fail-closed detector could not look at a money, credit or pii_export call, and the
Tier 1 judge detector can never trigger it. It does not stop: a payload an attacker shapes so that
no detector matches (the adversarial probes in the validation report list the known misses), a
finding that is kept past its retention class in a copy outside the store, or an operator who
edits `config/detectors.yaml` to disable a detector (the file is in change control).

### 3.10 Multi-turn red team and its LLM attacker (WP28, ADR D25)

Trust boundary: with `--attacker llm` (manual, never scheduled) the text of an attacker turn goes to the configured LLM endpoint (`LLM_BASE_URL`, model `REDTEAM_ATTACKER_MODEL`, temperature 0, at most 60 conversations per run). Before the call every id, amount, tool name and digit string is replaced by a `<<Tn>>` placeholder and restored afterwards, so no personal-data shape and no identifier leaves the process, and a reply that drops or invents a placeholder is discarded. The model only rephrases: the calls, their order and the deterministic oracle are fixed in code, so a hostile or wrong reply cannot turn a failure into a pass, cannot add a tool call and cannot reach the gate. The sandbox agents, the policy, the store and the chain are private to the run; the nightly job writes aggregates only (integers) to the chain. The optional evidence judge sends a transcript with digit runs masked and its verdict never changes a result (R1).

### 3.10 Risk register (WP29, ADR D26)

The register adds a write path for people (`POST /v1/risks/...`, flag `RISK_REGISTER_ENABLED`, off by
default) and a job that reads gate verdicts, assurance results and monitor status. Threats and
controls: (1) **a person lowers a risk score without proof**: the stored residual is only a claim; the
product shows the declared value only while the linked controls are `working` in the last window,
so editing the number does not change what the page shows, and every edit writes two
`console_action` rows and a `risk_change` chain record with the actor; (2) **fake evidence**: the
job reads tier-0 gate verdicts, non-mock assurance rows and monitor status only (no judge, no
classifier, no text from a user), ignores SHADOW, retired and unknown agents and mock results, and
a removed rule or a failed pack counts against the risk; a person with write access to the
verdict or `eval_result` tables could still plant rows (those tables are append-only and chained;
the register adds no new write path to them); (3) **injection through free text**: titles and notes
are stored and shown as text (templates escape them), exports start a cell with `'` when it begins
with `=`, `+`, `-` or `@`, ids and link targets must match a strict pattern and a link must point at
something that exists, and no SQL is built from input (named parameters only); (4) **personal data**:
the register holds risk descriptions written by staff; the chain payloads hold integers, codes and
hashes only, and the evidence row has no text column; a person must not write customer data into a
description. Not covered: a reviewer, owner or admin who creates a false `accept` risk with a
justification note (there is no four-eyes step yet, see BACKLOG) and who is the only check on their own
scoring.

### 3.11 Collectors, consumer ids and the Add flow (WP38, ADR D28)

Trust boundary: values that a framework or a caller supplies (tool name, consumer id, session id,
correlation id, headers of an inbound request) and the console action that issues an agent key.
Controls: the adapters drop or replace any id that is not 1 to 128 characters of `A-Za-z0-9_.:@-`
(no header injection, no 400 from the route), map tool names to safe names, cap payload size and fail
closed on every malformed answer; the gate ignores an invalid or unknown consumer id and then applies
the agent's own settings, and a consumer cannot switch off a money, credit or pii_export block or
pause rule, cannot set observe mode on an agent with money rules, and its detector override never
applies to a money, credit or pii_export tool; observe lifts nothing on those tools unless the agent
has two `observe_approvals` (WP38 review). An `allow: true` answer that contradicts itself fails
closed in the adapters.
The consumer id is asserted by the caller: a compromised agent can name a lenient consumer such as
an observe-mode channel, so the mode and the consumer id are in every decision, chain record and SIEM
event, and overrides are changed only through the reviewed policy file. The Add action passes the new
secret through the browser once (`Cache-Control: no-store`); the audit row has the agent id, template
id and key id only; the page needs `collectors.add` (admin, operator) and an htmx request; the base
URL put in snippets is validated. Observe mode lets calls that rules would stop go through; it is a
per-agent policy value in git and shows in the Policy binding tab. It does not stop: a person who
can edit the policy file or read the key file.

### 3.11 Session monitor (WP27, ADR D29)

Trust boundary: the conversation id and the turn text that a caller sends in the gate context. The
risks: (1) personal data in a session id, or turn text kept somewhere. The id is limited to
`A-Za-z0-9_.:-` (no `@`) and is a technical id by contract; the turn text is read in memory, reduced
to flags, a keyed 4-byte shingle sketch and keyed identifier hashes, and dropped; cases, the chain
and `session_json` hold tools, classes, amounts, flags, finding codes and hashes only; the consumer
id is stored as a keyed 6-byte hash; the harness scans cases, chain records and event columns for
the raw text (`leak_items` must be 0). (2) A caller who makes the monitor stop a payment: only the
deterministic rule `GATE-SESSION-PAUSE` blocks, only when the policy lists the tool class in
`pause_scope`, only for that session, and only from a score over integer thresholds; a forged
`session_id` can pause only the forger's own session, but a caller who sends someone else's session
id could add turns to it (the gate cannot tell; ingress auth identifies the agent, not the user).
(3) A detector outage must not raise the score: a timed-out detector is no finding and a
`GATE-DETECTOR-FAILED` block is no refusal. (4) The `consumer_id` is asserted by the calling agent;
ingress auth (WP20) verifies the agent, not the customer. A faulty or compromised agent can split
one person over two ids (no cross-agent link) or add a cross-agent hit to someone else's session
(one hit, 1300 bp: no case and no pause alone). A call with neither a session id nor a consumer id
is in no session, so anonymous customers are never merged into one pause. It does not stop: an attacker who rotates the session id,
spreads steps over more than the window, obfuscates the phrases, or paraphrases a planted fact (see
the probes and BACKLOG).

### 3.11 Transparency report (WP31)

The report crosses the trust boundary on purpose: its customer and regulator versions leave the bank. Controls: explicit allow-lists per variant (a field not listed is not copied); a second check that refuses a customer or regulator report holding an agent id, rule or obligation id, hash, owner field or a person name read from the raw sources, applied to the data and to the rendered text of both languages; free text masked or dropped (never raw); no personal data and no text in the chain (hashes, counts and fixed codes only); files never overwritten and checked against the hash on every read; HTML autoescaped with no script and no external asset; routes behind the sign-in with `transparency.generate` limited to reviewer and admin and audited. After the projection every text value of the outer versions is masked again and scrubbed of e-mail, phone and long digit runs (fields copied as they are included), and the guard refuses those patterns; the chain record and the append-only row name a person only as a keyed hash. Residual risk: names the masker misses can appear in the internal version, and in a free-text or config text field of the regulator version when the masker misses them (vn_regex catches Vietnamese names with diacritics, not every name) (BACKLOG).

### 3.11 Console activity pages and the CSV export (WP39, ADR D32)

The Decisions drawer, the Traces pages and the Analytics tabs show text of calls that carried
personal data. Controls: the gate stores no arguments (a keyed hash only); the Request tab is
rebuilt from recorder events at capture level `masked` and masked again before it is shown (no
masker or `digest` level: no text); finding text, entity tokens and reasons are masked again on
the way out, so a faulty detector row does not leak; ids from stored rows are escaped in HTML,
percent-encoded in links and neutralised in CSV (leading quote for `=`, `+`, `-`, `@`; control
characters removed); filter and deep-link values must match an id pattern (HTTP 400, never a
header or a query to the store). The CSV export is an allow-list of 18 columns of ids, codes,
enums and integers, capped at `CONSOLE_EXPORT_MAX_ROWS`, for auditor and admin only, and written
as an audited action (two `console_action` rows). `tests/console/test_wp39_decisions.py` and
`python -m supervisor.console.activity_harness` plant a name, a phone number, an ID number and an
e-mail in arguments, tool results, an output, a case title and a verdict text, and fail on any
page or export that shows one. WP39 review: the download link is bound to the user and to 15
minutes (HMAC with a key held in the process), the file is served once and deleted, and stale
files are removed on every export; caller-given ids (correlation, request, consumer) that hold
personal data are replaced or dropped at the gate and hidden on every page, so an e-mail used as
an id does not reach the chain, the SIEM event or the CSV.

## 4. Known gaps (not controls yet)

| Gap | Effect | Planned answer |
|---|---|---|
| Cooperative enforcement | An agent that does not call the gate is not stopped. No credential brokering and no egress proxy in front of tools yet | Bank-side credential broker / egress allow-list (analysis 02, open question 5) |
| Dev signing key | The default key is a file under `DATA_DIR`, labelled `key_kind=dev` unless the setting `signer_key_managed` is true (env `SIGNER_KEY_MANAGED=1`). Whoever can read it can re-sign a rewritten chain | Bank KMS / HSM custody; pin the public key in the verifier; anchors to object-lock storage |
| Dev HMAC keys | Without `ARGS_HASH_KEY` / `MASK_HMAC_KEY` the dev keys are used (key id `dev`, visible in evidence) | Keys from the bank vault |
| OTLP auth off by default | `recorder/otlp_receiver.py` `authorize` accepts every caller unless `INGRESS_AUTH_ENABLED=1` (WP20, see "Ingress authentication" below) | Turn the flag on; network restriction |
| Gate check has no caller auth by default | `/gate/check` trusts the network position unless `INGRESS_AUTH_ENABLED=1` (WP20) (laptop binds 127.0.0.1; on the App, the platform's auth). Gate control routes (`pause`, `resume`, `quarantine`, `release`) need an authenticated Principal (laptop: `X-Dev-User` naming a user of the users file; App: SSO headers) and the role from the matrix, always; a body `principal` and a raw `X-Forwarded-User` are ignored | Turn on `INGRESS_AUTH_ENABLED` (ADR D14) |
| Service-principal read fallback | On the App, a request without SSO headers runs as the App service principal with `service_principal_roles` (empty = read-only) | Keep empty; review in `config/auth.yaml` |
| Laptop operator has full local control | The SQLite file and key file are writable by the laptop user; the chain detects edits but cannot prevent them | Anchors off the laptop; Delta with no UPDATE / DELETE grants on the App |
| Policy deploy not on the chain | A policy change is visible through `policy_hash` in every gate decision, but the deploy itself is not a chain record | Policy PR + second approver (bank change process) |
| No rate limiting | Flooding the gate or console is not throttled | Platform limits; backlog |
| Inline redaction is cooperative and one-sided (WP24b) | The gate answer carries masked `transformed_args`; an agent or proxy that ignores it still sends the original arguments to the tool. The server flag and the SDK / proxy flag must both be on. The values never enter the chain (hashes only), but masked copies travel in the gate response over the same trust boundary as the arguments | Credential broker / egress proxy that applies the redaction itself (see the cooperative enforcement gap) |
| Inventory reads workspace metadata (WP24) | With `INVENTORY_ENABLED=1` the app lists Apps, serving endpoints, registered models and UC table names (read only, OAuth identity of the app). Object names are untrusted text: the console escapes them, CSV export guards formula cells, case summaries pass the masker, and nothing from the workspace reaches an LLM prompt. Shadow-AI cases are flags for a person; the scan never pauses or blocks. The check is only as complete as the app identity's visibility: an App the service principal cannot list is not seen | Grant the app principal list rights on Apps and serving endpoints; review the allow-list file in change control |
| Remote MCP servers (WP26) | A third-party server controls its tool list. Without `MCP_HTTP_ENABLED` and the HTTP proxy, a remote server's descriptions reach the model unchecked; with the proxy, a new or changed tool is held for two people. The lock does not read intent: it protects against change, not against a hostile first version that two reviewers approve | Review the diff and the scan findings; keep the list small; WP25 classifier score |
| Mock judges in the demo | The demo judge is a keyword MockJudge; its numbers prove the protocol, not a model | Real judge model behind `JUDGE_*` settings, measured by the eval harness |

### Judge family and served config (WP1b-A, ADR D21)

Trust boundary B3 (judge / model) and the operator settings. The judge family was a free-text
declaration; a qwen judge could be declared as another family and watch a qwen agent. The family
is now derived from the model id and, with `JUDGE_FAMILY_PROBE=1`, the endpoint metadata; a
disagreeing declaration stops startup unless `JUDGE_FAMILY_OVERRIDE_TEST_ONLY=1`, which
`databricks_app` mode refuses, and every verdict row, chain record, the model card and the
validation report carry `family_source`; `mrm validate` gives NO_GO for a declared source. The
transition flag `JUDGE_FAMILY_STRICT=0` accepts a declaration only for an id with no family
(custom endpoint names) and records `declared-unverified`. A model id that lies about its weights is caught only
by the probe, and only on endpoints that report them. `POLICY_DIR` and `FACT_SOURCE` are operator
settings: `callable:` imports a module named in the environment, which runs its code, so the
module must sit under a package prefix in `FACT_CALLABLE_ALLOW_PREFIX` (default `supervisor.`;
the bank adds its own package); one changed variable cannot load `os` or a planted module. And `sqlite:` opens the file read-only with queries from a map that must be one `SELECT`
with a bound key (no SQL built from agent input). A fact error returns no record, so the rule
fails by its fail mode. They do not defend against an operator who can edit the settings.

### Ingress authentication (WP20, ADR D14)

Trust boundary: the agent-facing write routes `POST /gate/check`, `/v1/gate/check` and `/v1/traces`. With `INGRESS_AUTH_ENABLED=1` each call carries a per-agent credential: an HMAC-SHA256 signature over (agent id, timestamp, nonce, method, path, body hash) with a 5-minute window and a single-use nonce, or a Databricks service-principal bearer token checked through SCIM `Me` and mapped to an allow-list of agent ids. This stops a caller that only has network access from posting gate checks or spans for an agent id it does not own, from replaying a captured request, and from spoofing the agent id in the body (the body id must be one the credential speaks for; a trace batch with a foreign span is refused whole). Every refusal is a 401 or 403, is counted in `/gate/metrics` and writes a `console_action` row with the body hash only. It does not stop: a stolen agent key (rotation limits the window; keep keys in the secret scope), a compromised agent process that holds its own key (it can still lie about its own tool calls: the gate stays cooperative), flooding by a caller that has no key (each refusal writes an audit row; use network or platform limits), or replay across a restart inside the 5-minute window (the nonce cache is in memory, one process). Default is off, so the two gap rows above stay true until the bank turns it on.

### HTTP MCP gateway and tool locking (WP26, ADR D24)

Trust boundary added: the remote MCP server (a third party, over HTTP) and the proxy listener on the agent host. Threats: (1) a rug pull, where an approved tool's description or schema changes after review; (2) tool poisoning, where a description or schema holds instructions for the model (including hidden Unicode, look-alike names, text split across fields, Vietnamese and English); (3) a new tool that shadows an old one; (4) a web page that talks to the loopback listener (DNS rebinding); (5) a caller on the host network that uses the proxy to reach the upstream with its token. Controls: every tool is hashed byte exact and compared with the locked manifest on every `tools/list`, at `initialize`, and at `tools/call` after `MCP_LOCK_REFRESH_S`; a new or changed tool is hidden and refused (`MCP-TOOL-UNREVIEWED`) until two different people approve the same hash; the lock fails closed when the Supervisor or the upstream is unreachable; a deterministic scan marks suspicious tools for the reviewer (report only); the listener binds loopback, checks Host and Origin, caps the body, and can require a bearer token; descriptions never enter the chain (hashes, names and finding kinds only); every lock change, approval, seed and refusal is a chain record. It does not stop: a hostile tool that two reviewers approve, a change inside the refresh window (one call), a change in a field outside the hash (`_meta`), encoded instructions (base64, ROT13, leetspeak), trust-on-first-use abuse by whoever starts the proxy (the name is claimed, not verified; over the agent ingress the app accepts a seed only with `MCP_TOFU_INGRESS=1`, default off, and records the sending credential), or a compromised agent host that bypasses the proxy and calls the server directly (cooperative enforcement, as in the gap table above). The upstream bearer token lives in an environment variable of the proxy process and is sent only to the upstream URL.

## 5. Kill switch

Pause is cheap: one rule, one console click or `POST /gate/pause`. Resume is hard: two
different people (owner + reviewer). Quarantine release needs an admin listed in the
policy. All three are real state changes on the gateway, recorded on the chain, and
never faked in the demo (`demo/inject.py` reads the state back from the store).

### 3.11 Control catalogue and task list (WP30, ADR D30)

The catalogue adds write paths for people (`POST /v1/controls/...`, `POST /v1/tasks/...`, flag
`CONTROLS_ENABLED`, off by default), two jobs and a launch NO-GO source. Threats and controls: (1)
**a person marks a control working without proof**: status is computed from enforced gate hits, real
packs and deterministic monitors, never typed, and a document or a detector slug never counts; (2)
**a control is changed after it showed working**: its status and the evidence of the risks that link
it stop counting until the next pass (`changed_since_evidence`); (3) **one person waives a required
task alone**: a waiver needs a reason and a different signed-in approver or admin, the move itself
cannot be waived, and an integrity query finds a forged row; (4) **a stage is skipped**: the
lifecycle move is refused while a required task is open, and Launch is NO-GO; (5) **the chain leaks
text**: payloads hold ids, integers, codes and hashes, and reasons only as a hash. Reasons are stored
as text in the task row (do not type personal data). The CLI trusts the operator on the host (as the
other CLIs do); the second person of a waiver can answer only through the authenticated route.
Review additions: (6) **the first line closes a second-line task**: a reviewer, approver, auditor
or admin task needs that role (or admin); (7) **a downgrade relaxes the list**: sizing keeps the
highest level and every class the agent had, so a move keeps its stage approval and no stage is
skipped; (8) **Launch passes on an unknown**: no task list, a stage before deployment, an
unreadable list or the gate flag on with CONTROLS_ENABLED off are each NO-GO; (9) **a bank process
shows working because a product rule fired**: a bank-owned control is always `bank_owned`.

### 3.11 Injection classifier (WP25, ADR D27)

The classifier reads text from three untrusted places: tool arguments, tool results and tool
descriptions. The text is only turned into hashed numbers and a score; it is not stored, sent to a
model or logged, and a finding carries fragments of MASKED text (R2). The trust boundary change is one
new way to stop a call: a score at or above the frozen pause threshold on a money or credit tool pauses
the agent (`GATE-CLASSIFIER-PAUSE`), never blocks it, and a human resumes with two people (R1). An
attacker who learns the model could craft text that stays under the threshold (evasion; see the
validation report for the measured recall) or craft benign-looking text that triggers pauses (a
denial-of-service on one agent; the pause is per agent and visible as a case). The weight file is
pinned by SHA-256 in the model card; the loader refuses a changed file, so the model cannot be swapped
silently. Training data are synthetic; the model is not a replacement for the rules.

The classifier keeps two small in-process caches (feature ids per text window, word classes per token). They are keyed by a 16-byte
BLAKE2b digest of the text and hold only integers, so text of a call (names, account digits) does not stay in process memory after the call (WP25c, review G5).
