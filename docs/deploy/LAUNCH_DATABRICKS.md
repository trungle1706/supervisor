# Launch Supervisor v0.5.0 on the Databricks App sandbox

For the owner. Windows `cmd` only. OAuth only: never set or paste `DATABRICKS_TOKEN`. One App,
one process, one worker. The SQL runs through the Statement Execution API. Per-workspace values
are `FILL-ME-...` placeholders: fill them INLINE in your local copy and never send the files back
with real values. Read `docs\BANK_DEPLOY_GUIDE.md` (hard constraints) and `docs\databricks-prereqs.md`
(what you need) first.

Nothing in this package has run on a live workspace. Every command below was checked against the
repository files, the `databricks` CLI help text that the earlier runbook used, and unit tests with
fakes. The first live run is the test. Report every deviation with the exact `[FAIL]` line.

## 1. The picture

```
 laptop (you, OAuth profile)                      workspace
 +---------------------------+   bundle deploy   +-------------------------------------+
 | unzip databricks bundle   | ----------------> | App: supervisor-<user>   (port 8000)|
 | fill FILL-ME in app.yaml  |                   |   console, gate, MCP, KPIs          |
 | bootstrap_schema          | -- SQL (REST) --> | Delta tables in catalog.schema      |
 | live test kit             |                   | Volume: signer key, spool, anchors  |
 +---------------------------+                   | Serving endpoint (judges, optional  |
                                                 |   guard model): CAN_QUERY           |
                                                 +-------------------------------------+
                                                        ^   ^   ^   OAuth (service principal)
                                          candidate Apps (3, separate): call /v1/gate/check
```

## 2. What you need (short form of `docs\databricks-prereqs.md`)

| # | Item | Check |
|---|---|---|
| 1 | Workspace URL, Databricks CLI, an OAuth profile | `databricks auth profiles` shows the profile valid |
| 2 | SQL warehouse, `CAN_USE` | `databricks warehouses list --profile FILL-ME-profile` |
| 3 | Writable schema `catalog.schema` (USE CATALOG, USE SCHEMA, CREATE TABLE) | preflight `schema writable` is `[OK]` |
| 4 | A Unity Catalog Volume in that schema (READ VOLUME, WRITE VOLUME) | preflight `volume writable` is `[OK]` |
| 5 | An existing model-serving endpoint for the judges, `CAN_QUERY` (you cannot create one) | `databricks serving-endpoints list --profile FILL-ME-profile` |
| 6 | Right to create Databricks Apps | Compute, Apps, "Create app" is enabled |
| 7 | Python 3.11 and the packages on the laptop for the schema job and the live kit | `docs\deploy\LAUNCH_LAPTOP.md` sections 1 to 5 (same bundle family) |

## 3. Unpack and fill in

```
cd /d C:\work
tar -xf supervisor-databricks-0.5.0-<sha>.zip
cd /d C:\work\supervisor
```

(`tar` is part of Windows 11. Any unzip tool works. Check `SHA256SUMS.txt` with
`certutil -hashfile <zip> SHA256`.) Use Notepad with "All files" so no `.txt` is added.

| File | Placeholder | Value |
|---|---|---|
| `databricks.yml` | `FILL-ME-workspace-host` | host part of the workspace URL (2 places) |
| `databricks.yml` | `FILL-ME-warehouse-id` | from `warehouses list` |
| `databricks.yml` | `FILL-ME-serving-endpoint-name` | the judge endpoint (item 5) |
| `databricks.yml` | `FILL-ME-username` (3 places) | lowercase letters, digits, `-`; the App name is at most 30 characters |
| `databricks.yml` | `FILL-ME-user-email` | `prod` target only |
| `app.yaml` | `FILL-ME-catalog`, `FILL-ME-schema`, `FILL-ME-volume` | your schema and Volume (5 lines) |
| `app.yaml` | `INVENTORY_SCAN_SCHEMAS` = `FILL-ME-catalog.FILL-ME-schema` | schemas whose tables and functions the scan lists; keep the shape `catalog.schema,catalog.schema` |
| `app.yaml` | `URL_FETCH_ALLOWLIST` = `FILL-ME-allowed-domain` | only used when `URL_FETCH_ENABLED` is `1`; the App has no internet by default, so leave it |
| `app.yaml` | `GUARD_MODEL_*` (commented) | only if you serve a guard model (section 7) |
| `config\governance.yaml` | `default_owner` | only for the workspace auto-record (section 8) |

`requirements.txt` is already in the bundle (exported from `uv.lock`, with `pypdf` for PDF intake).
If the App BUILD log says it cannot find packages, regenerate it with the bank Nexus lines on, in
your local copy only (needs `uv`): `uv run python -m supervisor.cli export-reqs --nexus FILL-ME-nexus-host`.

## 4. Tables

Set `SQL_BACKEND=databricks_rest` and the `DATABRICKS_*` lines in a local `.env` (copy `.env.example`,
the Databricks block), log in, then plan and create. v0.5.0 adds tables (AI systems, team, components,
approvals, reviews, outbound events, classifications, bindings, incidents, MCP apps). Run this after
every upgrade; it never drops anything.

```
databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile
.venv\Scripts\python.exe -m supervisor.cli preflight
.venv\Scripts\python.exe -m supervisor.jobs.bootstrap_schema --plan
.venv\Scripts\python.exe -m supervisor.jobs.bootstrap_schema
```

## 5. Validate, deploy, run

```
databricks bundle validate -t dev --profile FILL-ME-profile
databricks bundle deploy   -t dev --profile FILL-ME-profile
databricks bundle run supervisor -t dev --profile FILL-ME-profile
```

`validate` fails while any `FILL-ME` value is left in `databricks.yml`. `run` prints the App URL.
Logs: Compute, Apps, your app, Logs. After the first deploy, find the App service principal:

```
databricks apps get supervisor-FILL-ME-username --profile FILL-ME-profile
```

Look for `service_principal_client_id`.

## 6. Grants, Volume, warehouse

| What | Who | How |
|---|---|---|
| `CAN_USE` on the warehouse, `CAN_QUERY` on the judge endpoint | the bundle | `databricks.yml` resources `sql-warehouse`, `llm-endpoint` |
| `SELECT, MODIFY` on each Supervisor table | you | `.venv\Scripts\python.exe -m supervisor.jobs.bootstrap_schema --grant-to <service_principal_client_id>` |
| `USE CATALOG`, `USE SCHEMA` | catalog and schema owner | `GRANT USE CATALOG ON CATALOG <catalog> TO \`<id>\`` and `GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO \`<id>\`` |
| `READ VOLUME, WRITE VOLUME` | Volume owner | `GRANT READ VOLUME, WRITE VOLUME ON VOLUME <catalog>.<schema>.<volume> TO \`<id>\`` |
| Signing key folder (once, before the first run) | you | `databricks fs mkdir dbfs:/Volumes/<catalog>/<schema>/<volume>/supervisor/keys --profile FILL-ME-profile` |

`app.yaml` already sets `DATA_DIR`, `SIGNER_KEY_PATH`, `SPOOL_DIR` and `ANCHOR_PATH` under the Volume
(`/tmp` is wiped on restart). The App creates the signing key at first start and reuses it. If the
log says `DATA_DIR ... is not mounted in this container`, the Volume is not mounted: spool and anchors
use the Files API, and case files are lost on restart. Report it (open item in `docs\databricks-prereqs.md`).
The warehouse is a bound resource (`valueFrom: sql-warehouse`); the SQL runs as the App service
principal, and for a signed-in user through `X-Forwarded-Access-Token` (scope `sql`).

## 7. The judge model and the guard model

| Model | Setting | What to do |
|---|---|---|
| Judges (advise only, never block) | `LLM_ENDPOINT` from the bound resource `llm-endpoint`; the client calls `https://<host>/serving-endpoints` with the App OAuth | Use an existing endpoint. Without one the judges are the labelled `mock`. The judge model family must differ from the agent model family |
| Judges on a Unity Catalog model service (AI Gateway) | In `app.yaml` uncomment `LLM_BASE_URL=https://FILL-ME-workspace-host/ai-gateway/mlflow/v1`, `LLM_MODEL=FILL-ME-catalog.FILL-ME-schema.FILL-ME-model-service`, `LLM_API_SHAPE=responses`; remove the `llm-endpoint` resource in `databricks.yml` and the `LLM_ENDPOINT` binding | The App service principal needs EXECUTE (or the equivalent) on the model service in Unity Catalog. The client posts to `/responses` with the App OAuth token. Set `LLM_API_SHAPE=chat` if the gateway only accepts `/chat/completions` |
| Judges call the model service as the signed-in user (sandbox only) | In `app.yaml` uncomment `LLM_USER_TOKEN_FORWARD=1`; in `databricks.yml` uncomment the serving scope under `user_api_scopes` (try `serving.serving-endpoints`; the exact gateway scope is not confirmed, ask the workspace admin if refused) | Use only when the App service principal cannot get a grant on the model service. Judge calls then run under the user's identity, only for requests that carry `X-Forwarded-Access-Token`; scheduler sweeps and jobs use the App service principal. Verdicts show `auth: user_forwarded`. Needs `SUPERVISOR_MODE=databricks_app` and a workspace `LLM_BASE_URL`. Off by default |
| Guard model (phase 5, off) | `GUARD_MODEL_ADAPTER=auto`; `GUARD_MODEL_URL`, `_NAME`, `_VERSION` commented in `app.yaml` | NO-GO until a real model run (`docs\guard-model-decision.md`). To try one: serve a classifier or chat model, uncomment the `guard-model-endpoint` resource in `databricks.yml`, set the three lines in `app.yaml`, run `python -m supervisor.detectors.guard_harness` from the laptop with `GUARD_MODEL_URL` set, and send the report back. In `databricks_app` mode a workspace serving URL uses the App identity (no key) |

The detector `guard_model` stays `enabled: false` in `config\detectors.yaml` until the model card
approval names the model id and version. Changing that file is a decision for the second line.

## 8. The phase 4 and 5 switches in `app.yaml`

All are off in the code. The file turns on what the sandbox story needs. To switch one off, set
its value to `"0"` and redeploy.

| Variable | Shipped | What it does | Needs |
|---|---|---|---|
| `GOVERNANCE_ENABLED` | `1` | AI systems, rules, Decision 33, lifecycle (`docs\governance.md`) | tables from section 4 |
| `CONSOLE_SYSTEMS_ENABLED`, `CONSOLE_NAV_SECTIONS`, `CONSOLE_NAV_V3`, `CONSOLE_CATALOG_ENABLED` | `1` | the governance pages and the two-section sidebar | `GOVERNANCE_ENABLED` |
| `INVENTORY_ENABLED` | `1` | risk of a system inherits from linked agents, tools, data | |
| `GOVERNANCE_ACTIONS_ENABLED` | `1` | events map to incident, notify, raise risk, re-evaluate, review | `GOVERNANCE_ENABLED` |
| `GUARDIAN_BINDINGS_ENABLED` | `1` | per-system guardian switches with the floor | |
| `MCP_SERVER_ENABLED` | `1` | `POST /mcp` and `GET /v1/kpis` on port 8000 | |
| `WEBHOOKS_ENABLED`, `CLASSIFIER_AI_PREFILL` | `0` | webhook stub; AI answers for open classification questions | |
| `TRANSPARENCY_ENABLED` | `1` | transparency report | |
| `INVENTORY_SCAN_V2` | `0` | scan v2: serving endpoints, model versions, Genie spaces, jobs, Vector Search, UC functions, UC connections | live kit item 12 passes first |
| `INVENTORY_AUTOREGISTER` | `0` | drafts an AI system for an unmanaged App, agent endpoint or Genie space | `GOVERNANCE_ENABLED`, owner in `config\governance.yaml` (no draft while the owner is `FILL-ME`) |
| `DETECTORS_ENABLED` | `1` | the detector layer | |
| `DOCUMENT_INTAKE_ENABLED` | `1` | `context.documents`: PDF, DOCX, text, CSV; no OCR | `pypdf` (in `requirements.txt`) |
| `URL_FETCH_ENABLED` | `0` | URL fetch behind an allow list and an SSRF guard | App egress to the domains; unknown, so off |
| `GUARD_MODEL_*` | adapter `auto` (mock) | see section 7 | |

Console identity in the App is the SSO header set by the Apps proxy; the dev header of the laptop
does not exist here. Roles come from the role map in `config\auth.yaml` (replace its `FILL-ME`
values in your local copy; no real names are committed). Give yourself `admin` and `reviewer`
first, or the Register form is closed to you.

## 9. The first hour in the App

1. Open the App URL. Sign in with SSO. The console loads.
2. `GET <app url>/healthz` is `{"status":"ok"...}`.
3. Governance, Systems, Register. The three candidate systems are registered here with the form or
   with `POST /v1/systems`; the fields are the ones in `supervisor.manifest.yaml` (see
   `docs\deploy\LAUNCH_LAPTOP.md` section 8). `demo seed-systems` is for the laptop SQLite demo only.
4. Link each system to its agent id (tab Components) after the candidate App has called the gate once
   (the agent is registered by the first call or by onboarding).
5. Run the live test kit (section 11).

## 10. The three candidate agents as separate Apps

Each candidate agent (`~/supervisor-testbed/candidates/<name>/`, built by work packages A1 to A3)
is its own App, with its own `app.yaml` and `databricks.yml`, and it calls this App over HTTPS.
The candidate bundles come from the A work packages; this section is what they need from the
Supervisor side. Not run live.

```
 candidate App (service principal SP-A)  --- OAuth bearer --->  Supervisor App
   POST /v1/gate/check  (before every tool call)                 identity = X-Forwarded-User
   OTLP traces  POST /v1/traces                                  maps to agent ids in
                                                                 config\agent_identities.yaml
```

| Step | Who | What |
|---|---|---|
| 1 | you | Deploy each candidate from its own folder: `databricks bundle deploy -t dev --profile FILL-ME-profile`, then `bundle run`. App names: lowercase, digits, `-`, 30 characters at most |
| 2 | you | In the candidate `app.yaml` set `SUPERVISOR_URL` to `https://FILL-ME-supervisor-app-url` and the serving endpoint resource for its own LLM (a different model family from the judge) |
| 3 | you | Compute, Apps, Supervisor App, Permissions: add each candidate service principal with `CAN USE` |
| 4 | you | In your local copy of `config\agent_identities.yaml` map each service principal (the `X-Forwarded-User` value) to its agent id; redeploy the Supervisor App |
| 5 | you | In the Supervisor `app.yaml` uncomment `INGRESS_AUTH_ENABLED=1`, `INGRESS_CREDENTIAL_KIND=databricks_proxy`, `INGRESS_IDENTITIES_FILE`; redeploy. Do this after live kit item 11 has shown which headers arrive |
| 6 | you | Deploy each candidate policy fragment (`policies\<agent>.yaml`) with the policy folder of the Supervisor App; until then the gate state of the agent is `SHADOW` |
| 7 | you | Open a candidate App, ask it something that calls a tool. In the Supervisor console: Supervisor, Activity shows the call; Governance, Systems, the system, shows the agent |
| 8 | you | Make a call the policy blocks (the candidate README lists one). The Supervisor console shows the block, a case, an incident |

The agent code uses the Supervisor SDK: `HttpGate(url, credential=IngressCredential(bearer=get_token))`
(`docs\ingress-auth.md` step 4). Keep the bearer fresh; it expires.

## 11. Live test kit, extended for phase 4 and 5

Run the kit as in `docs\live-test-kit.md` (items 1 to 12: SQL, append-only Delta, Volume, preflight,
serving endpoint, ingress headers, scan v2). v0.5.0 adds four items (13 to 16). The kit text has the
exact steps and the expected result of each.

| # | Check | Where |
|---|---|---|
| 11 | Which identity headers reach the App (first, before ingress auth) | kit section 1, item 11 |
| 12 | Scan v2: one `[OK]` or `[FAIL]` per read-only call with your role | `uv run python -m pytest tests\live -k test_12 -v` |
| 13 | MCP server and KPIs on the deployed App | kit section 6, item 13 |
| 14 | Document intake on the deployed App (PDF, DOCX, scan refused) | kit section 6, item 14 |
| 15 | Guard model endpoint (only if you serve one) | kit section 6, item 15 |
| 16 | A candidate App reaches the Supervisor App and is checked | kit section 6, item 16 |

## 12. What to send back

`preflight` output; the file under `data\local\live-results\`; the lines of items 12 to 16;
the first 50 lines of the App log (host names are not in it; check before you send); every
`[FAIL]` or deviation. No tokens: Supervisor removes anything that looks like one, but read the
files before you send them.

## 13. If something fails

| Symptom | Fix |
|---|---|
| `bundle validate` says a value is `FILL-ME` | fill it inline (section 3) |
| App BUILD: "Could not find a version" | regenerate `requirements.txt` with `--nexus` (section 3) |
| App starts, console shows no governance pages | `GOVERNANCE_ENABLED` and `CONSOLE_SYSTEMS_ENABLED` are `1` in `app.yaml`; redeploy; run `bootstrap_schema` |
| `GET /v1/systems` answers 400 `AI systems are off` | same flag |
| Registration refused: `a new system is unclassified` | the class is set only by applying a classification |
| Tables missing columns after an upgrade | `bootstrap_schema` again (it adds columns, never drops) |
| 401 from a candidate to the gate | ingress mapping (section 10 step 4) or `CAN USE` (step 3) |
| Anything else | `docs\RUNBOOK.md` section 12 (symptom, cause, fix) |
