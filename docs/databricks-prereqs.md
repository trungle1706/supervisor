# Databricks prerequisites (WP10)

What the owner must have before the Databricks part of Supervisor can run. Values are
never committed: write them only in your local `.env`, `databricks.yml` and `app.yaml`.

## 1. Checklist

| # | Item | Who gives it | How to check | Used by |
|---|---|---|---|---|
| 1 | Workspace URL (`https://<host>`) | You know it (browser address bar) | You can log in | `.env`, `databricks.yml` |
| 2 | Databricks CLI on the laptop, OAuth profile | You (`databricks auth login`) | `databricks auth profiles` shows the profile as valid | laptop, bundle deploy |
| 3 | SQL warehouse with `CAN_USE` for you | Workspace admin | SQL Warehouses page lists it; preflight `sql warehouse` and `warehouse reachable` are `[OK]` | Statement Execution API |
| 4 | Writable schema `catalog.schema` (USE CATALOG, USE SCHEMA, CREATE TABLE) | Schema owner | preflight `schema writable` is `[OK]` | all Supervisor tables |
| 5 | Existing model-serving endpoint, `CAN_QUERY` for you | Endpoint owner (you cannot create endpoints) | preflight `serving endpoint` is `[OK]` (READY) | App judges (`LLM_ENDPOINT`) |
| 6 | Unity Catalog Volume in that schema, READ VOLUME + WRITE VOLUME | Schema owner (`CREATE VOLUME` right) | preflight `volume writable` is `[OK]` with `LIVE_VOLUME_PATH` or `SPOOL_DIR` set | App data dir, spool, anchors |
| 7 | Right to create one Databricks App | Workspace admin | Compute > Apps > "Create app" is enabled | `databricks bundle deploy` |
| 8 | Optional: shared interactive cluster, attach right | Workspace admin | the cluster is RUNNING in Compute | `supervisor.jobs.cluster_run`, notebook |
| 9 | v0.5.0: read rights for the workspace scan v2 (serving endpoints, model versions, Genie spaces, jobs, Vector Search indexes, UC functions, UC connections) | Workspace admin, catalog owner | live test kit item 12 shows `[OK]` per call | `INVENTORY_SCAN_V2` (off until then) |
| 10 | v0.5.0, optional: a second existing serving endpoint for the guard model, `CAN_QUERY` | Endpoint owner | live test kit item 15 | `GUARD_MODEL_URL`, resource `guard-model-endpoint` (commented in `databricks.yml`) |
| 11 | v0.5.0: one service principal per candidate App, with `CAN USE` on the Supervisor App | Workspace admin | live test kit items 11 and 16 | `INGRESS_AUTH_ENABLED`, `config/agent_identities.yaml` |
| 12 | v0.5.0: owner rows for the workspace auto-record (`default_owner` in `config/governance.yaml`) | Second line | the scan counts `skipped_no_owner` while the owner is `FILL-ME` | `INVENTORY_AUTOREGISTER` (off) |

## 2. Grants for the App service principal

The App runs as its own service principal (the platform injects `DATABRICKS_CLIENT_ID` and
`DATABRICKS_CLIENT_SECRET`). After the first `databricks bundle deploy`, find its
application id:

```
databricks apps get supervisor-FILL-ME-username --profile FILL-ME-profile
```

Look for `service_principal_client_id`. Then:

| Grant | Who can run it | Command |
|---|---|---|
| `CAN_USE` on the warehouse, `CAN_QUERY` on the endpoint | Done by the bundle (resource bindings in `databricks.yml`) | `databricks bundle deploy` |
| `SELECT, MODIFY` on each Supervisor table | You (you own the tables you created) | `uv run python -m supervisor.jobs.bootstrap_schema --grant-to <application id>` |
| `USE CATALOG`, `USE SCHEMA` | Catalog / schema owner | `GRANT USE CATALOG ON CATALOG <catalog> TO \`<application id>\`` and `GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO \`<application id>\`` |
| `READ VOLUME, WRITE VOLUME` on the Volume | Volume owner | `GRANT READ VOLUME, WRITE VOLUME ON VOLUME <catalog>.<schema>.<volume> TO \`<application id>\`` |

The App does not create or migrate tables. You run `bootstrap_schema` from the laptop
after each upgrade (it adds new columns and never drops anything).

## 3. Identity summary

| Where | Identity | Auth |
|---|---|---|
| Laptop (CLI, preflight, bootstrap, live tests) | you | OAuth U2M, CLI profile (`DATABRICKS_AUTH_TYPE=databricks-cli`) |
| Databricks App, background tasks and scheduler | App service principal | OAuth M2M, injected by the platform |
| Databricks App, inside a user request | signed-in user (`X-Forwarded-Access-Token`, `user_api_scopes: [sql]`) | on-behalf-of (WP8 console) |
| Notebook and `cluster_run` | you | your Unity Catalog permissions |

Never a personal access token. Preflight fails when `DATABRICKS_TOKEN` is set.

## 4. Open items (not confirmed; tell us what you see)

| Item | Why it matters | How we will know |
|---|---|---|
| Private Link / workspace network path from the laptop | REST must reach the workspace through the TLS appliance | preflight `warehouse reachable` from the laptop |
| App runtime egress | We assume only the workspace's own APIs are reachable from the App | App logs after the first start; nothing in Supervisor needs more |
| App BUILD index (PyPI or Nexus only) | Seen both ways; decides `export-reqs --nexus` | App deploy log ("Could not find a version ...") |
| `/Volumes` mount inside the App container | Without a mount, the spool and anchors use the Files API (built in), and `DATA_DIR` falls back to the container disk (signing key and case files wiped on restart; a log line says so) | App log line `DATA_DIR ... is not mounted in this container` |
| App name prefix in `mode: development` | The dev target may prefix the name; names are at most 30 characters | `databricks bundle validate` output |
| Insert-only MERGE on `delta.appendOnly` tables | The app appends with MERGE to drop duplicates | live kit test 02 and notebook check 3 |
| Who owns `USE CATALOG` / `USE SCHEMA` grants for the App principal | The owner lacks CREATE SCHEMA and may lack GRANT on the schema | ask the schema owner |
| Delta retention 1825 days on evidence tables | Legal retention period; owner to confirm | notebook check 7 |
| SDK response shapes of the scan v2 sources (v0.5.0) | The reader code was written against the SDK documentation, not a live answer | live test kit item 12 |
| `pypdf` in the App BUILD (v0.5.0) | `requirements.txt` now includes the `documents` extra; BUILD must find it | App deploy log; live test kit item 14 |
| App to App calls through the Apps proxy (v0.5.0) | Which identity header a candidate App's service principal produces decides the ingress kind | live test kit items 11 and 16 |
| Playground in `databricks_app` mode (v0.5.0) | Closed unless `PLAYGROUND_ALLOW_APP=1`; kit item 14 needs it once | kit item 14 |
| Outbound egress for URL fetch (v0.5.0) | `URL_FETCH_ENABLED` stays `0` until the platform team names the domains the App may reach | ask the platform team |
