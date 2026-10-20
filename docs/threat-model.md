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
