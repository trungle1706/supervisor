# Live test kit (Databricks, run by the owner)

The Supervisor team cannot reach the bank workspace. Everything that talks to Databricks
is unit-tested here with fakes. This kit runs the same code against the real workspace.
You run it on the bank laptop and send back the results file. All commands are Windows
`cmd`. Run them in the repo folder.

## 1. What it checks

| # | Test (`tests\live\test_live_kit.py`) | Question it answers |
|---|---|---|
| 01 | Statement Execution round trip | Does a TIMESTAMP parameter `2026-10-14T05:00:00.123456Z` come back with microseconds and UTC? |
| 02 | Insert-only MERGE on a `delta.appendOnly=true` table | Is `MERGE ... WHEN NOT MATCHED THEN INSERT` allowed, and does a repeat insert 0 rows? |
| 03 | UPDATE / DELETE on an append-only table | Are both refused, and does Supervisor report `AppendOnlyError`? |
| 04 | Migration | Does `ALTER TABLE ... ADD COLUMNS` and `SET TBLPROPERTIES` work on an append-only table with rows? Is a second run a no-op? |
| 05 | `UcVolumeAnchor` | Does a put to the Volume work, and is a second put to the same name refused? (needs `LIVE_VOLUME_PATH`) |
| 06 | Volume spool | Can the recorder spool write, stage and delete files on the Volume? (needs `LIVE_VOLUME_PATH`) |
| 07 | Preflight end to end | Do all preflight checks pass with your `.env`? |
| 08 | Serving endpoint (optional) | Does the endpoint answer an OpenAI-compatible JSON request? (needs `LLM_ENDPOINT`) |
| 09 | Command Execution runner (optional) | Does one execution context run cells, return the sentinel line and get destroyed? (needs `DATABRICKS_CLUSTER_NAME`) |
| 10 | Environment summary | Prints settings that matter (no secrets) |
| 11 | Ingress headers (WP20, manual, do this first) | Which identity headers reach the App: `X-Forwarded-User` / `X-Forwarded-Email` / `X-Forwarded-Access-Token` / `Authorization`, for a service-principal caller and a user caller? Decides the ingress credential kind (`docs/ingress-auth.md`, "Databricks App setup") |
| 12 | Inventory scan v2 (WP-G3) | Does each read-only call of the scan sources v2 work with your role: serving endpoints (entities, agent flag), model versions, Genie spaces, jobs, Vector Search indexes, UC functions (needs `INVENTORY_SCAN_SCHEMAS`), UC connections (MCP flag)? One `[OK]` or `[FAIL]` line per call; send the lines back |

The command below also runs the SQL contract tests (`tests\contract`) against your
workspace: the same tests that pass on SQLite here.

Every table the kit makes has the prefix `lv_<8 hex>_` and is dropped at the end. The
Volume files are deleted at the end. Nothing touches tables without the prefix.

## 2. Before you start

1. Install and configure as in `docs\RUNBOOK.md` sections 1 to 4. Preflight must show no `[FAIL]` for the Databricks lines you need.
2. In `.env` set (FILL-ME values replaced): `DATABRICKS_HOST`, `DATABRICKS_CONFIG_PROFILE`, `DATABRICKS_AUTH_TYPE=databricks-cli`, `DATABRICKS_WAREHOUSE_NAME`, `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA`, `SSL_OS_TRUSTSTORE=1`.
3. Optional, in `.env`: `LIVE_VOLUME_PATH=/Volumes/<catalog>/<schema>/<volume>/supervisor-live`, `LLM_ENDPOINT=<endpoint name>`, `DATABRICKS_CLUSTER_NAME=<shared cluster name>`.
4. Log in again if the last login was more than about one hour ago:

```
databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile
```

## 3. Run

```
cd /d %USERPROFILE%\supervisor
set RUN_DATABRICKS=1
uv run python -m pytest tests\live tests\contract -v
set RUN_DATABRICKS=
```

The last line names the results file, for example
`[OK] live results written to C:\Users\you\supervisor\data\local\live-results\live-20261014T053000Z.txt`.

## 4. Notebook (second path, inside the workspace)

`notebooks\bootstrap_and_smoke.py` is a Databricks source-format notebook. It creates the
tables (prefix `smoke_` by default), inserts synthetic rows and runs the same checks with
Spark. Use it when the laptop cannot reach the warehouse.

1. In the workspace: Workspace > your folder > Import > File > select `notebooks\bootstrap_and_smoke.py`.
2. Open it. In the `SUPERVISOR-PARAMS` cell, replace `FILL-ME-catalog` and `FILL-ME-schema`.
3. Attach a cluster (the shared cluster or a SQL-capable one). Click Run all.
4. The last cell prints a table of `[OK]` / `[FAIL]` lines and one `SUPERVISOR-EXIT-JSON:` line.

From the laptop (Command Execution API, no Jobs) you can run the same notebook:

```
uv run python -m supervisor.jobs.cluster_run notebooks\bootstrap_and_smoke.py --param CATALOG=FILL-ME-catalog --param SCHEMA=FILL-ME-schema --param DROP_AFTER=true
```

Each `--param NAME=VALUE` overrides one default of the parameter cell. It needs
`DATABRICKS_CLUSTER_NAME` in `.env` (or `--cluster-name`), and the cluster must be RUNNING.

## 5. What to send back

| Send | Where it is |
|---|---|
| The results file | `data\local\live-results\live-<time>.txt` (newest file) |
| The last 30 lines of the pytest output, if the results file is missing | the cmd window |
| The notebook results table or the `SUPERVISOR-EXIT-JSON:` line | last cell output |
| The preflight output | `uv run python -m supervisor.cli preflight > preflight.txt` then send `preflight.txt` |

The files contain no tokens (Supervisor removes anything that looks like one). They do
contain the workspace host, warehouse name and schema name: send them only through the
bank channel you normally use with us.
