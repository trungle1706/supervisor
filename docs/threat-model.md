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

### Trust boundary added by WP21 (SIEM export, alerts, webhook)

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

## 4. Known gaps (not controls yet)

| Gap | Effect | Planned answer |
|---|---|---|
| Cooperative enforcement | An agent that does not call the gate is not stopped. No credential brokering and no egress proxy in front of tools yet | Bank-side credential broker / egress allow-list (analysis 02, open question 5) |
| Dev signing key | The default key is a file under `DATA_DIR`, labelled `key_kind=dev` unless the setting `signer_key_managed` is true (env `SIGNER_KEY_MANAGED=1`). Whoever can read it can re-sign a rewritten chain | Bank KMS / HSM custody; pin the public key in the verifier; anchors to object-lock storage |
| Dev HMAC keys | Without `ARGS_HASH_KEY` / `MASK_HMAC_KEY` the dev keys are used (key id `dev`, visible in evidence) | Keys from the bank vault |
| No OTLP auth yet | `recorder/otlp_receiver.py` `authorize` is a placeholder; any caller that reaches the port can post spans (data only, never gate state) | Principal port on the receiver; network restriction |
| Gate routes have no caller auth | `/gate/check` trusts the network position (laptop binds 127.0.0.1; on the App, the platform's auth). Gate control routes (`pause`, `resume`, `quarantine`, `release`) need an authenticated Principal (laptop: `X-Dev-User` naming a user of the users file; App: SSO headers) and the role from the matrix, always; a body `principal` and a raw `X-Forwarded-User` are ignored | Per-agent credentials at the gate |
| Service-principal read fallback | On the App, a request without SSO headers runs as the App service principal with `service_principal_roles` (empty = read-only) | Keep empty; review in `config/auth.yaml` |
| Laptop operator has full local control | The SQLite file and key file are writable by the laptop user; the chain detects edits but cannot prevent them | Anchors off the laptop; Delta with no UPDATE / DELETE grants on the App |
| Policy deploy not on the chain | A policy change is visible through `policy_hash` in every gate decision, but the deploy itself is not a chain record | Policy PR + second approver (bank change process) |
| No rate limiting | Flooding the gate or console is not throttled | Platform limits; backlog |
| Mock judges in the demo | The demo judge is a keyword MockJudge; its numbers prove the protocol, not a model | Real judge model behind `JUDGE_*` settings, measured by the eval harness |

## 5. Kill switch

Pause is cheap: one rule, one console click or `POST /gate/pause`. Resume is hard: two
different people (owner + reviewer). Quarantine release needs an admin listed in the
policy. All three are real state changes on the gateway, recorded on the chain, and
never faked in the demo (`demo/inject.py` reads the state back from the store).
