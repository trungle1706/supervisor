# MCP server, skills and KPIs (WP-G6)

Status: built, off by default (`MCP_SERVER_ENABLED=1`). Code: `src/supervisor/mcp_server/`,
`src/supervisor/governance/kpis.py`. Skills: `docs/skills/`. Plan: `docs/phase4/BUILD_PLAN_PHASE4.md`
section 4.7. Reasons: `ADOPTION_PLAN.md` sections 10 and 12 (agent-first, KPIs).

Pipelines and AI assistants work through the platform the way people do in the console, and the
server enforces the same rules. The rules are in the server, not in a prompt. This page is for
operators, second line and developers who connect an assistant.

## 1. What it is

```text
 assistant / pipeline                         Supervisor app (one process)
 (signs every request)                  +------------------------------------------+
        |  POST /mcp  JSON-RPC 2.0      |  auth: WP20 HMAC + mcp_app row           |
        |  X-Supervisor-Agent = app id  |   pending  -> initialize, ping only      |
        |  ... Signature                |   blocked  -> 403                        |
        +------------------------------>|   approved -> tools of its scopes        |
                                        |  tool = the same service as the API:     |
                                        |   scope (SystemService.scope_for),       |
                                        |   console permission of the app roles,   |
                                        |   confirm: true for a write, 2 audit rows|
                                        +------------------------------------------+
```

| Part | What |
|---|---|
| Transport | `POST /mcp`, streamable HTTP, JSON-RPC 2.0: `initialize`, `tools/list`, `tools/call`, `ping`. One JSON answer per request, a batch gets an array. No `GET` stream, no session. The JSON-RPC error shape is the one of the WP26 proxy (`gateway/mcp_proxy.error_response`). |
| Process | Mounted by the main app, or alone with `python -m supervisor.mcp_server` (section 6). |
| Connected apps | Table `mcp_app`. An app is `pending` until an admin approves it. |
| Tools | Three groups: governance (read and draft-write), library (read), supervisor (read). |
| Skills | Five Markdown files under `docs/skills/`. |
| KPIs | `GET /v1/kpis`, the MCP tool `kpis` and the Governance overview read one function. |

## 2. Settings

| Setting | Default | Meaning |
|---|---|---|
| `MCP_SERVER_ENABLED` | `0` | Mounts `POST /mcp`, `GET /v1/mcp/apps`, `POST /v1/mcp/apps/{id}/approve`, `/block` and `GET /v1/kpis`; adds the KPI block to the Governance overview. Off: nothing is mounted, no `mcp_app` row is read or written, the overview is as before, the command line prints `[SKIP]`. |
| `MCP_SERVER_HOST` / `MCP_SERVER_PORT` | `127.0.0.1` / `8765` | For `python -m supervisor.mcp_server` only. |
| `GOVERNANCE_ENABLED` | `0` | The governance tools and KPIs need it (they work on AI systems). Without it they answer with a message that names the flag. The library tools do not need it. |
| `RISK_REGISTER_ENABLED`, `CONTROLS_ENABLED`, `TRANSPARENCY_ENABLED`, `GOVERNANCE_ACTIONS_ENABLED` | `0` | The tool or the KPI that reads that part answers "off" and names the flag. |
| `INGRESS_KEYS_FILE`, `INGRESS_KEY_STORE`, `INGRESS_REPLAY_WINDOW_S`, `INGRESS_KEY_OVERLAP_HOURS` | see `docs/ingress-auth.md` | The key store and the signature window are the WP20 ones. The MCP server always requires the credential; it does not need `INGRESS_AUTH_ENABLED`. |

Windows cmd: `set MCP_SERVER_ENABLED=1` and `set GOVERNANCE_ENABLED=1`.

## 3. Connected apps and approval

An app is a row of `mcp_app`: `app_id` (`mcp-` and a slug of the name), `name`, `scopes`, `roles`,
`created_by`, `approved_by`, `status` (`pending`, `approved`, `blocked`), `key_hash` (SHA-256 of the
current secret; the secret itself is in the WP20 key store under the app id).

```text
python -m supervisor.mcp_server app issue "Nightly register job" --scopes governance.read,governance.write,library.read --roles reviewer --by ops.lan --out-key-file C:\secure\nightly.key
python -m supervisor.mcp_server app list
python -m supervisor.mcp_server app approve mcp-nightly-register-job --by admin.chi
python -m supervisor.mcp_server app block mcp-nightly-register-job --by admin.chi
python -m supervisor.mcp_server app rotate mcp-nightly-register-job --by ops.lan --out-key-file C:\secure\nightly.key
```

* `issue` makes the row (`pending`), stores the key in the file key store (or prints what to set
  for the `env` and `secret_scope` stores), and shows the secret once. With `--out-key-file` it
  writes the secret to that file (mode 600) and prints nothing secret. `--roles` may name
  `viewer`, `owner` and `reviewer`; any other role needs `--by` to be an admin of the users file.
* **Two people.** The person who issued an app cannot approve it. At the command line
  `approve --by` must also be an id with the role `admin` in the users file (`USERS_FILE`);
  on the route the permission `mcp.apps` is admin only.
* An app key is a WP20 key with an id that starts with `mcp-`. The agent ingress (`/gate/check`,
  `/v1/traces`) refuses every id with that prefix, so an app key never signs a gate call.
* `approve` and `block` are also routes for a signed-in **admin**: `POST /v1/mcp/apps/{id}/approve`
  and `/block` (permission `mcp.apps`). A service principal cannot approve. `GET /v1/mcp/apps`
  lists the apps without the key hash.
* A blocked app is refused at once (HTTP 403). A pending app can `initialize` and `ping`; every
  other call answers `-32001` until an admin approves. `first_connected_at` records the first
  signed request.
* `roles` are the console roles the app acts with (never `admin`). The app is
  `mcp:<app id>` in every audit row, `service_principal` kind. Its view of the AI systems is
  scoped like a person's (`SystemService.scope_for`): an app with the role `viewer` sees only the
  systems where an admin added `mcp:<app id>` to the team (`POST /v1/systems/{id}/team`); roles
  `reviewer`, `approver`, `auditor` see all systems.
* The secret is a WP20 key: rotate with `app rotate`; the old key works for
  `INGRESS_KEY_OVERLAP_HOURS`.

### Sign a request

Same format as the agent SDK (`docs/ingress-auth.md`): the agent id header is the **app id**, the
signature covers method, path and body hash.

```python
import json, urllib.request
from supervisor.gateway.ingress_sign import credential_from_env

cred = credential_from_env("mcp-nightly-register-job", key_file=r"C:\secure\nightly.key")
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/mcp", data=body, method="POST",
    headers={"Content-Type": "application/json", **cred.headers_for("POST", "/mcp", body)})
print(urllib.request.urlopen(req).read().decode())
```

| Refusal | HTTP | Audit `detail` |
|---|---|---|
| No credential, bad shape, stale timestamp, unknown app, wrong signature, replayed nonce | 401 | WP20 reason codes (`missing_credential`, `stale_timestamp`, `unknown_agent`, `bad_signature`, `replayed_nonce`, ...) |
| Blocked app | 403 | `app_blocked` |
| Body over 256 KB | 413 | none |
| Body that is not JSON, empty batch, more than 50 messages | 400 | none |

Every 4xx above writes one `console_action` row: permission `mcp.auth`, outcome `denied`, actor
`unverified:<claimed app id>`, `before_hash` = SHA-256 of the body (never the body; empty when the
refusal came from the headers alone, because the body is then never read). An unknown
app and a wrong signature give the same answer. There is no rate limit (as for the agent ingress).

## 4. Tools

Every answer is JSON in `content[0].text` and in `structuredContent`. Ids and enums; text is the
masked text the console shows. People appear as ids, never as names. Rates are basis points.
Lists take `limit` (1 to 200, default 50).

An error is a JSON-RPC error with HTTP 200 (`-32602` invalid input or a refused change,
`-32001` app not approved, `-32002` scope not granted, `-32003` role cannot do this,
`-32004` not found or not in scope, `-32010` audit store unavailable, `-32011` result too large,
`-32603` server error with the class name only). Never a 500.

### 4.1 Governance (`governance.read`, `governance.write`)

| Tool | Writes | Needs (console permission of the app roles) | What it does |
|---|---|---|---|
| `list_entities(kind, filters, limit)` | no | none beyond scope | `kind`: `system`, `risk`, `control`, `incident`, `review`. For systems the filters of `GET /v1/systems`. Risks and incidents are limited to the agents in scope. |
| `get_entity(kind, id)` | no | none beyond scope | One entity; for `review` the id is the review id. An id outside the scope is `-32004`, like a missing one. |
| `list_tasks(system_id)` | no | none beyond scope | Lifecycle tasks of the system and of its linked agents. |
| `transparency_report(system_id, variant)` | no | none beyond scope | Latest signed report or a preview for each linked agent. Text in the report goes through the masker. |
| `kpis()` | no | none beyond scope | The KPI document of section 5. |
| `register_system(draft)` | draft | `systems.edit` | Registers a system: status `draft`, stage `initiation`, class `unclassified`. Same validation and scoping as `POST /v1/systems`. The draft cannot carry `decision33_class`, `risk_level`, `risk_level_source`, `risk_justification`, `business_impact`, `autonomy_level`, `status` or `lifecycle_stage`. The app is the owner of its draft: `owner_user` is left out or is `mcp:<app id>`, for every app (a person takes the ownership over in the console). |
| `link_component(system_id, ref_kind, ref_id, role)` | yes | `systems.edit` | Links an agent or an inventory node. A repeat is a no-op. |
| `propose_risk(system_id, agent_id, ...)` | draft | `risks.edit` | Creates a risk row with status `draft`, never `active`. The agent must be linked to the system. `treatment: accept` is not in the schema and the service refuses it. |
| `complete_task(task_id, evidence_ref)` | yes | `tasks.edit` | Marks a task done. Only a task of a system in scope whose `owner_role` is a role of the app; a lifecycle move and an approver task are refused. The task service applies its own rules (evidence for control and pack tasks). |
| `classification_draft(system_id)` | draft | `systems.edit` | Makes the Decision 33 draft from the rules. It never changes the class of the system. Making a draft again resets its answers, so the tool refuses when an open draft was made by a person, or has an answer that a person set: it returns that draft (`refused: true`, `written: false`) and changes nothing. |

### 4.2 Library (`library.read`)

`regulations(jurisdiction)`, `obligations(query, instrument_id, limit)`, `starter_risks`,
`starter_controls`, `guardian_catalog`, `assignment_rules`. Read only; no tool writes the library.
Regulation answers repeat "Not legal advice. Bank counsel must confirm."

### 4.3 Supervisor (`supervisor.read`)

| Tool | What it does |
|---|---|
| `gate_state(agent_id)` | State (`RUNNING`, `SHADOW`, `PAUSED`, `QUARANTINED`) and the role and time of each approval of a pending resume (not who gave it). |
| `decisions(agent_id, since, limit)` | Newest gate decisions: tool, outcome, rule id, masked rationale. The masked arguments and results of the call are left out. |
| `findings(agent_id, since, limit)` | Detector findings, masked entities and fragments, scores in basis points. |
| `chain_verify(agent_id)` | **A write.** Verifies the evidence lane offline (the check of the console). It commits the chain root and records a `chain_verify` entry, so it takes `confirm`, leaves two audit rows, is announced with `readOnlyHint: false`, and one app may call it once per 60 s. Scope `supervisor.read`; needs the console permission `chain.verify`. |
| `pack_results(agent_id, limit)` | Newest assurance pack result per pack; mock runs are labelled. |

The app sees an agent only when a person with its roles would see it in the console
(`SystemService.agents_in_scope`). Others answer `-32004`.

### 4.4 Rules that the server enforces

* **Confirm before write.** Every write tool takes `confirm`. Without `confirm: true` it validates
  and returns `{"written": false, "confirm_required": true, "planned_change": {...}}` and writes
  nothing, not even an audit row. `confirm` must be `true` or `false`.
* **Draft only.** Systems are drafts in initiation, unclassified. Risks are drafts. Classification
  is a draft. Nothing a tool writes is active, applied or approved.
* **No decision tool.** The registry refuses, at registration, any name that has one of these
  words: accept, approve, apply, lower, downgrade, close, resolve, pause, resume, halt, suspend,
  quarantine, release, retire, disable, off, waive, certify, authorize, promote, advance,
  activate, decide, set, classify, signoff; and the phrases for a risk level, an incident close,
  a guardian off. The 21 tools that exist are named in `ALLOWED_NAMES` (a new tool with such a word
  needs a reviewed change). The message points at the console.
  `tests/mcp_server/test_refused.py` enumerates the tools and runs a list of more than 130 probe
  names.
* **Same rules as people.** A write needs the scope in the app row **and** the console
  permission that a person would need, given the roles of the app. Segregation of duties,
  validation, scoping and chain records are those of the services.
* **Audit.** A confirmed write makes two `console_action` rows with one request id: `attempted`
  before the change (if this row cannot be written, nothing is done) and the outcome after (`ok`,
  `denied` or `error`), with the hash of the target row before and after. Actor `mcp:<app id>`,
  roles of the app, method `MCP`, path `/mcp/tools/<tool>`. A refused write (scope or role) leaves
  one `denied` row. The chain records of the services (`system_change`, `risk_change`,
  `task_change`, ...) carry a keyed hash of the actor as for a person.
* **Reads are audited.** Every answered read leaves one `ok` row (permission `mcp.read`, path
  `/mcp/tools/<tool>`, the id read as target). If the row cannot be written the answer still goes
  out and the failure is logged (a write never works that way).
* **Results.** Ids and enums as stored. Every free-text field passes through the repo masker
  (`MASKER_KIND`) before it leaves: system name, purpose, owner team, justification, tags and link
  evidence; risk title, description, notes and owner; task, control, review and incident
  titles and text; the text of a transparency report; the plan echoed by a write tool. With
  `MASKER_KIND=none` those fields come back empty. A hash is not text and is left as it is.
  A test seeds a name, an e-mail, a CCCD and a phone number into each field and checks that no
  tool returns them.

## 5. KPIs

`GET /v1/kpis` (permission `console.view`, every role; scoped like G0: a viewer sees the
systems they are on). The same function feeds the MCP tool `kpis` and the **Governance overview**
(block "Governance KPIs", EN and VI, only with `MCP_SERVER_ENABLED=1`). All figures are integers;
a rate is basis points; a figure that cannot be computed is `null` and `unavailable` has a reason.

| Group | Key | Meaning |
|---|---|---|
| coverage | `assets_by_kind` | Agents in scope plus inventory nodes by kind (all nodes for a role that sees all systems; otherwise the nodes linked to the systems in scope) |
| | `systems_by_risk`, `systems_by_stage` | Counts by effective risk level and lifecycle stage |
| | `classification_rate_bp` | Systems with a class other than `unclassified` |
| | `policy_coverage_bp` | Systems with at least one obligation assigned by the rules |
| quality | `risk_treatment_coverage_bp` | Active risks in scope with at least one active control |
| | `acceptable_residual_bp` | Active risks in scope with a residual band `low` or `medium` |
| | `control_readiness_bp` (+ `_n`, `_of`) | Controls with `working` evidence over controls with a status, for the agents of the systems |
| | `implementation_per_policy_bp`, `implementation_by_system` | Obligations that apply to a system and are met (working evidence of the controls that hold them) |
| speed | `avg_days_per_stage` | Whole days from the request of a stage approval to the move that used it, by the stage left |
| | `overdue_tasks` | Required tasks past due, for the systems and their agents |
| | `inheritance_rate_bp` | Systems whose effective risk level comes from a linked part |
| | `automation` | `rule_runs` (chain records), `events`, `events_done`, `actions_ok`, `actions_failed`, `action_success_bp` (governance events) |

`generated_at` is the time of the call. `compute` keeps its answer for 30 s for the same person,
scope and settings (the caller gets a copy), so a KPI page does not rescan the store at each load.
Reads are bounded: rule runs count the newest 5000 chain entries and report `rule_runs_capped`
and `unavailable["rule_runs"] = "capped"` when the cap is hit; `governance_event`, `stage_approval`,
`system_component` and `inventory_node` read at most 20000 rows each and add
`unavailable["<table>_capped"]`. A governance event counts only for a system in scope (an event
of no system counts for nobody). If the function fails, the Governance overview shows the KPI
block with every figure "not available" (reason `error`) and logs the failure; the page never
answers with an error. The plan names `rule_run` and `governance_action`
records: there is no table of rule runs, so the figures come from the chain entries `rule_run` and
the `actions` of `governance_event`.

## 6. Run it

* Main app: set `MCP_SERVER_ENABLED=1`; `/mcp` is on the same port as the console. The Databricks
  App needs no other setting; the signature covers the path the client uses.
* Alone: `python -m supervisor.mcp_server [serve] [--host H] [--port P]` builds the runtime and
  serves only `POST /mcp` (one worker). Do not run it next to the main app on the same store: the
  evidence chain has one writer. Binding to a host other than loopback prints a warning: the
  traffic is signed, not encrypted; put TLS in front.
* `python -m supervisor.mcp_server tools` lists the registered tools (name, scope, read or write).

## 7. Skills

Markdown files for an assistant, in `docs/skills/`. Each names the tools it uses and the rule
"the server decides; confirm before write; never classify by yourself".

| Skill | For |
|---|---|
| `vn-system-registration` | Register a system as a draft with its owners and agents |
| `d33-prep` | Prepare the Decision 33 draft and explain it; a person applies it |
| `risk-triage` | Find risks without a control; propose draft risks |
| `transparency-report` | Read and explain a transparency report for one reader |
| `gov-report` | Periodic governance report from the KPIs |

A test (`tests/mcp_server/test_skills.py`) checks that every tool a skill names exists and that no
skill names a refused tool.

## 8. Limits and open questions

* **Signing.** The credential is the WP20 HMAC signature. An off-the-shelf MCP client (Claude
  Desktop, Claude Code, Copilot Studio) cannot sign a request by itself; it needs a small signing
  proxy or a client that takes a header hook. OAuth 2.1 or OIDC, as in Saidot, is later work
  (ingress auth has the same gap: `docs/ingress-auth.md`, BACKLOG).
* **One process.** The nonce cache is in memory (as for the agent ingress): `--workers 1`.
* **Audit flood.** Each refused request writes one audit row; `INGRESS_AUDIT_THROTTLE_S` does not
  apply to `mcp.auth` rows (open question for the bank).
* **Approval.** An admin approves in the API or at the command line. A console page for apps is
  not built; the text of such a page would need EN and VI.
* **`chain_verify`** is a write (section 4.3); it also writes a scratch export, like the console button.
* **Task ownership.** A task has an `owner_role`, not an owner person; "owned by the app" means
  the role is one of the app's roles.
* **Free text in.** `register_system` and `propose_risk` store the text that the client wrote
  (purpose, title) as it is; only the text that leaves is masked. The client must not put
  personal data in it.

## 9. Tests

`tests/mcp_server/`: `test_off_path.py` (first), `test_auth.py`, `test_protocol.py`,
`test_refused.py`, `test_tools_governance.py`, `test_tools_library_supervisor.py`,
`test_pii_and_scope.py`, `test_kpis.py`, `test_cli.py`, `test_skills.py`, `test_rbac.py`, `test_review_fixes.py` (masking sweep,
`chain_verify`, KPI bounds and cache, read audit, CLI rules).
