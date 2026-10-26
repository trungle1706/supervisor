# Supervisor runbook (Windows 11, cmd)

This runbook is for the bank user on a Windows 11 laptop. All commands use `cmd`. Run them
in the repo folder. Always use `uv run python -m ...`. Do not use the console-script `.exe`
files: AppLocker blocks them ("Access is denied (os error 5)").

Values that start with `FILL-ME-` are values you must set in your local copy. Never put a
real token in any file. Never send back files that hold your real values unless we ask.

Do the steps in this order. The cheat sheet is in section 13.

| Step | Section | Needed for |
|---|---|---|
| 1 | Install | everything |
| 2 | Configure `.env` | everything |
| 3 | Databricks login | Databricks mode, deploy, live kit |
| 4 | Preflight | everything |
| 5 | Run locally | laptop mode |
| 6 | Local LLM (Ollama) | real judges on the laptop (optional) |
| 7 | Create the tables in your schema | Databricks mode, App |
| 8 | Deploy the Databricks App | App |
| 9 | Live test kit | when we ask |
| 10 | Send results back | when something fails |

Prerequisites (workspace, warehouse, schema, serving endpoint, Volume, App rights) are in
`docs\databricks-prereqs.md`.

## 1. Install

| Item | Needed | Check |
|---|---|---|
| Python 3.11 | Yes | `python --version` |
| uv | Yes | `uv --version` |
| `uv.toml` (Nexus) from the hand-off zip | Yes | the file is in the repo folder, next to `pyproject.toml` |
| Databricks CLI | Databricks mode | `databricks --version` |
| Ollama for Windows | Optional | `ollama --version` |

`uv.toml` comes only in the hand-off zip. It is not in git. It points uv at Nexus. Run every
`uv` command from the folder that holds it, or uv does not find it.

```
cd /d %USERPROFILE%\supervisor
uv sync --python 3.11 --extra databricks
```

If uv reports `UnknownIssuer`, use the Windows certificate store:

```
uv sync --python 3.11 --extra databricks --native-tls
```

Laptop mode without Databricks needs no extra: `uv sync --python 3.11`.

## 2. Configure `.env`

```
copy .env.example .env
notepad .env
```

Notepad warning: in "Save as", set "Save as type" to "All files". If not, Notepad saves
`.env.txt` and the settings are ignored. The same applies to `Modelfile`.

Supervisor reads `.env` from the repo folder (not from the current folder). Relative paths
are resolved against the repo folder, once, at start.

| Variable | Value | Note |
|---|---|---|
| `SUPERVISOR_MODE` | `laptop` | `databricks_app` is set by `app.yaml` on the App only |
| `DATA_DIR` | `data\local` or `C:\Users\FILL-ME-user\supervisor-data` | SQLite file, keys, case files, exports |
| `SSL_OS_TRUSTSTORE` | `1` | the bank TLS appliance re-signs HTTPS |
| `SQL_BACKEND` | `auto` (SQLite) or `databricks_rest` | `databricks_rest` = tables in your schema |
| `DATABRICKS_HOST` | `https://FILL-ME-workspace-host` | shown in every Databricks error |
| `DATABRICKS_CONFIG_PROFILE` | `FILL-ME-profile` | the name you use in `databricks auth login` |
| `DATABRICKS_AUTH_TYPE` | `databricks-cli` | uses the CLI OAuth token cache |
| `DATABRICKS_WAREHOUSE_NAME` | `FILL-ME-warehouse-name` | resolved to an id at start |
| `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA` | your writable schema | all Supervisor tables go here |
| `DATABRICKS_RETRY_TIMEOUT_S` | `90` (60 to 120) | SDK retry cap |
| `DATABRICKS_STATEMENT_DEADLINE_S` | `120` | a cold warehouse needs about 30 s |
| `GATE_DECISION_TIMEOUT_S` | `20` (code default `2`) | one gate decision, store reads included; the agent SDK timeout (`SUPERVISOR_TIMEOUT_S` in the candidates) must be larger |
| `POLICY_REFRESH_S` | `60` (code default `5`) | how often the gate re-reads the deployed policy from the store |
| `STATE_CACHE_TTL_S` | `30` (code default `1`) | how long the gate keeps an agent's state before it re-reads the `agent` row |
| `GATE_RECORD_ASYNC` | `1` (code default off) | answer the agent as soon as the decision is final; the verdict, event and chain writes (three store round trips) finish afterwards |
| `LLM_ENDPOINT` | `FILL-ME-serving-endpoint-name` | preflight checks it is READY |
| `DATABRICKS_CLUSTER_NAME` | optional | shared cluster for `cluster_run` |
| `LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | must be loopback. Empty = mock judges |
| `LLM_MODEL`, `LLM_TIMEOUT_S` | the `ollama list` name, `1800` | CPU models are slow |

Do not set `DATABRICKS_TOKEN`. Supervisor uses OAuth only. Preflight and every command fail
if the variable is set (in the shell or in `.env`).

## 3. Databricks login

```
databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile
databricks auth profiles
```

A browser window opens for SSO. The bank refresh token expires fast. Run the login again
when you see "invalid refresh token" or "cannot configure default credentials".

## 4. Preflight

```
uv run python -m supervisor.cli preflight
```

| Mark | Meaning | Action |
|---|---|---|
| `[OK]` | check passed | none |
| `[FAIL]` | check failed; exit code is 1 | do the `fix:` command on the same line |
| `[SKIP]` | feature not configured, so not checked | none, unless you need that feature |

| Check | Passes when | Fix printed on FAIL |
|---|---|---|
| `python` | Python 3.11 or later | `uv sync --python 3.11` |
| `no DATABRICKS_TOKEN` | the variable is not set | `set DATABRICKS_TOKEN=` |
| `truststore` | `SSL_OS_TRUSTSTORE=1` and the OS store is injected | start with `uv run python -m ...` |
| `config` | `.env` loads; LLM URL is loopback | fix `.env` |
| `paths absolute` | every path is absolute | report as a bug |
| `databricks extra` | `databricks-sdk` installed | `uv sync --python 3.11 --extra databricks` |
| `databricks auth` | CLI profile set (laptop) or service principal (App) | set `DATABRICKS_CONFIG_PROFILE` |
| `databricks profile` | profile is in `%USERPROFILE%\.databrickscfg` | `databricks auth login ...` |
| `oauth token (CLI)` | `databricks auth token --profile` works (token never shown) | `databricks auth login ...` |
| `databricks sign-in` | the SDK knows who you are | `databricks auth login ...` |
| `retry caps` | SDK retry cap 60 to 120 s | `DATABRICKS_RETRY_TIMEOUT_S=90` |
| `sql warehouse` | the name resolves to an id | check the exact name and `CAN_USE` |
| `warehouse reachable` | `SELECT 1` answers within the deadline | start the warehouse; check `SSL_OS_TRUSTSTORE=1` |
| `schema writable` | a probe table is created and dropped | ask the schema owner for `CREATE TABLE` |
| `serving endpoint` | the endpoint exists and is READY | check the name; ask the endpoint owner |
| `volume writable` | a probe file is written and deleted (Volume paths only) | create the volume; grant `WRITE VOLUME` |

To save the output for us: `uv run python -m supervisor.cli preflight > preflight.txt`

## 5. Run locally

```
uv run python -m supervisor.cli serve
```

Open `http://127.0.0.1:8000/healthz` in a browser. It must answer `{"status":"ok"}`. Stop the
server with Ctrl+C.

## 6. Local LLM (Ollama, CPU)

1. Before Ollama starts, keep the model loaded between calls. Quit Ollama from the tray, then:

```
setx OLLAMA_KEEP_ALIVE -1
```

   Open a new cmd window (setx applies to new windows) and start Ollama again.

2. Make a file named `Modelfile` (Notepad: "All files") in `%USERPROFILE%\models` with:

```
FROM C:\Users\FILL-ME-user\models\FILL-ME-model-file.gguf
PARAMETER num_ctx 16384
```

3. Register and check the model name:

```
cd /d %USERPROFILE%\models
ollama create qwen3-4b-local -f Modelfile
ollama list
```

4. In `.env`: `LLM_MODEL=` the exact name from `ollama list` (for example `qwen3-4b-local:latest`), `LLM_TIMEOUT_S=1800`. If replies are cut off, set `PARAMETER num_ctx 32768` and run `ollama create` again.

## 7. Create the tables in your schema

Set `SQL_BACKEND=databricks_rest` in `.env`, then:

```
uv run python -m supervisor.jobs.bootstrap_schema --plan
uv run python -m supervisor.jobs.bootstrap_schema
```

`--plan` reads the live schema and prints what it would change. Without `--plan` it creates
missing tables, adds missing columns (never drops), and sets the Delta append-only and
retention properties. Run it again after every Supervisor upgrade. `[WARN]` lines list
columns that differ; nothing is removed.

After the App exists (section 8), let its service principal use the tables:

```
uv run python -m supervisor.jobs.bootstrap_schema --grant-to FILL-ME-app-service-principal-id
```

## 8. Deploy the Databricks App

1. Fill the placeholders INLINE in your local copy (Notepad, "All files"). Do not commit them. Do not send these files back with real values.

| File | Placeholder | Where to find the value |
|---|---|---|
| `databricks.yml` | `FILL-ME-workspace-host` | the host part of the workspace URL |
| `databricks.yml` | `FILL-ME-warehouse-id` | `databricks warehouses list --profile FILL-ME-profile` |
| `databricks.yml` | `FILL-ME-serving-endpoint-name` | `databricks serving-endpoints list --profile FILL-ME-profile` |
| `databricks.yml` | `FILL-ME-username` (3 places) | your user name, lowercase letters, digits and `-`; the app name must be 30 characters or less |
| `databricks.yml` | `FILL-ME-user-email` | prod target only |
| `app.yaml` | `FILL-ME-catalog`, `FILL-ME-schema` | your writable schema |
| `app.yaml` | `FILL-ME-volume` | the Volume for data, spool and anchors |

2. Export the requirements file (the App installs it at BUILD; the runtime has no package index):

```
uv run python -m supervisor.cli export-reqs
```

   If the App BUILD log says it cannot find packages, turn on the Nexus lines in your local copy:

```
uv run python -m supervisor.cli export-reqs --nexus FILL-ME-nexus-host
```

3. Validate, deploy, run:

```
databricks bundle validate -t dev --profile FILL-ME-profile
databricks bundle deploy -t dev --profile FILL-ME-profile
databricks bundle run supervisor -t dev --profile FILL-ME-profile
```

   `validate` fails while any `FILL-ME` value is left. `run` prints the App URL. For prod use `-t prod`.

4. Signing key on the Volume (once, before the first run). In `app.yaml` set `SIGNER_KIND` to `uc_volume` and `SIGNER_KEY_PATH` to `/Volumes/FILL-ME-catalog/FILL-ME-schema/FILL-ME-volume/supervisor/keys/evidence_ed25519.pem`. Create the folder, give the App service principal READ VOLUME and WRITE VOLUME, and run preflight:

```
databricks fs mkdir dbfs:/Volumes/FILL-ME-catalog/FILL-ME-schema/FILL-ME-volume/supervisor/keys --profile FILL-ME-profile
uv run python -m supervisor.preflight
```

   `[OK] signer key` means the key exists or can be created. The App creates it at first start and reuses it after every restart. `[FAIL] signer key storage` means the key path is on the container disk: fix `SIGNER_KEY_PATH`. If you must change the key on purpose, set `SIGNER_ALLOW_ROTATION=1` for one start (a `key_rotation` entry is recorded), then remove it. Without it the writer refuses to start when the key differs from the last signed root.

5. Grants: see `docs\databricks-prereqs.md` section 2 and section 7 above.

6. Logs: workspace > Compute > Apps > your app > Logs.

The App runs one process with one worker (`--workers 1`): the evidence chain has one writer.
It reads `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` from the
platform. Its LLM is the bound serving endpoint at `https://<host>/serving-endpoints`
(the workspace's own endpoint, so it is not AI egress). `/tmp` is wiped on restart:
durable files go to the Volume in `app.yaml`, tables to your schema.

## 9. Live test kit

v0.5.0 adds items 13 to 16 (MCP and KPIs, document intake, guard model, candidate App): `docs\live-test-kit.md` section 6. The whole Databricks route in one page: `docs\deploy\LAUNCH_DATABRICKS.md`.

See `docs\live-test-kit.md`. Short form:

```
set RUN_DATABRICKS=1
uv run python -m pytest tests\live tests\contract -v
set RUN_DATABRICKS=
```

## 10. Send results back

| Problem | Send |
|---|---|
| Preflight FAIL | `preflight.txt` (section 4) |
| Live test kit | newest `data\local\live-results\live-*.txt` |
| Notebook | the results table from the last cell |
| A command fails | the full cmd output from the command to the end (a screenshot is fine) |
| App fails | the last 50 lines of the App log, and the `bundle deploy` output |

Never send `.env`, `uv.toml` with credentials, tokens, or `databricks auth token` output.

## 11. Ordered checklist

1. `uv sync --python 3.11 --extra databricks` (add `--native-tls` on `UnknownIssuer`).
2. `copy .env.example .env`, fill it (section 2).
3. `databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile`.
4. `uv run python -m supervisor.cli preflight`: no `[FAIL]`.
5. `uv run python -m supervisor.cli serve`, open `/healthz`.
6. `uv run python -m supervisor.jobs.bootstrap_schema` (with `SQL_BACKEND=databricks_rest`).
7. Fill `databricks.yml` and `app.yaml`, `export-reqs`, `bundle validate`, `deploy`, `run`.
8. `bootstrap_schema --grant-to <App service principal id>`; schema owner grants USE CATALOG / USE SCHEMA / Volume.
9. Live kit when asked; send the results file.

## 12. Symptom, cause, fix

| Symptom | Cause | Fix |
|---|---|---|
| Deploy fails: 404 `Endpoint with name ... does not exist` | The model is a Unity Catalog model service (AI Gateway), not a classic serving endpoint, so the `llm-endpoint` resource cannot bind it | Remove the `llm-endpoint` resource and use the gateway form in `app.yaml` (`LLM_BASE_URL=.../ai-gateway/mlflow/v1`, `LLM_MODEL=<catalog>.<schema>.<name>`, `LLM_API_SHAPE=responses`); grant the App service principal EXECUTE on the model service |
| Judge 403 with `LLM_USER_TOKEN_FORWARD=1` (verdict label `judge_unavailable`) | The scope for the model service is missing in `user_api_scopes`, or the signed-in user has no grant on the model service | Add the serving scope in `databricks.yml` (try `serving.serving-endpoints`), redeploy, sign in again so the token carries it; else ask the workspace admin which scope the AI Gateway needs. The gate is not affected: judges only advise |
| `TABLE_OR_VIEW_NOT_FOUND` or `PERMISSION_DENIED` with `identity=service_principal` while the signed-in user can query the schema | The App service principal has no grant on the catalog schema yet | Ask the catalog owner for the grant (preferred). Sandbox switch until then: `SQL_USER_TOKEN_FORWARD=1` in `app.yaml` (console SQL runs as the user, errors show `identity=user_forwarded`). Without the grant the console renders reads as the user, but the gateway and the evidence chain are unavailable: gate calls and every action that writes evidence answer HTTP 400 "gateway unavailable: the App service principal has no SQL grant yet". The chain always writes as the service principal. Remove the switch once the grant exists |
| "Access is denied (os error 5)" | AppLocker blocks the `.exe` stub | `uv run python -m <module>` |
| uv downloads Python and fails with `UnknownIssuer` | Python 3.11 not found locally | install Python 3.11; `uv sync --python 3.11` |
| `uv sync` cannot resolve any package | Nexus `uv.toml` missing | put `uv.toml` in the repo folder; run uv from there |
| `uv sync` reports `UnknownIssuer` with `uv.toml` present | uv does not trust the bank CA | add `--native-tls` |
| `CERTIFICATE_VERIFY_FAILED`, or the SDK hangs about 5 minutes | Python does not use the OS trust store | `SSL_OS_TRUSTSTORE=1` in `.env`; preflight `truststore` must be `[OK]` |
| `RemoteDisconnected` / `Connection aborted` on `/sql/1.0/warehouses/...` | thrift connector through the TLS appliance | Supervisor uses REST; report the traceback |
| Preflight FAIL `no DATABRICKS_TOKEN` | a PAT is in the environment | `set DATABRICKS_TOKEN=`; remove it from user environment variables and `.env` |
| "invalid refresh token" / "cannot configure default credentials" | SSO token expired | `databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile` |
| `TABLE_OR_VIEW_NOT_FOUND` | wrong workspace host, or tables not created | check `DATABRICKS_HOST` and the profile; `uv run python -m supervisor.jobs.bootstrap_schema` |
| Preflight FAIL `sql warehouse` "not found" | name differs or no `CAN_USE` | copy the exact name from the SQL Warehouses page |
| Preflight FAIL `warehouse reachable` timed out | cold warehouse (about 30 s) or stopped | start it in the UI; run preflight again |
| Preflight FAIL `schema writable` "PERMISSION_DENIED" | no `CREATE TABLE` on the schema | ask the schema owner |
| Preflight FAIL `serving endpoint` NOT_READY | endpoint scaled to zero or updating | wait; check the Serving page |
| `AppendOnlyError` "delta.appendOnly" on UPDATE/DELETE | evidence tables are append-only by design | none; report if it happens in normal use |
| `bundle validate` error on a `FILL-ME` value | placeholder left | fill it inline (section 8) |
| `bundle validate` "name ... must be at most 30 characters" | app name too long (dev prefix included) | shorten the `FILL-ME-username` part |
| App BUILD "Could not find a version that satisfies ..." | BUILD has no PyPI access | `export-reqs --nexus FILL-ME-nexus-host`, deploy again |
| App crashes at start and tries to sync | start command uses `uv run` | `app.yaml` must use `python -m uvicorn` |
| App log `DATA_DIR /Volumes/... is not mounted in this container` | the App has no `/Volumes` mount | the spool, anchors and the signing key (`SIGNER_KIND=uc_volume`) use the Files API; case files are on the container disk (wiped on restart). Check the Volume grants; if it stays, tell us (open item) |
| App log `PERMISSION_DENIED` on a `/Volumes/...` path | App service principal has no Volume grant | owner grants `READ VOLUME, WRITE VOLUME` (`docs\databricks-prereqs.md` section 2) |
| App log `PERMISSION_DENIED` on a Supervisor table | App service principal has no grant | `bootstrap_schema --grant-to <id>`; owner grants USE CATALOG / USE SCHEMA |
| `jobs/runs/submit` refused: "does not support jobs workload" | shared cluster is interactive only | use `supervisor.jobs.cluster_run` (execution contexts) |
| `cluster_run`: cluster is TERMINATED | the shared cluster is stopped | start it in Compute; run again |
| WinError 267 or `.venv/bin/python: No such file or directory` | relative path given to a child process | set `DATA_DIR` to an absolute path; report the traceback |
| Console page hangs after a click | a 500 error; htmx drops it | look at the server log; report it |
| `.env` changes have no effect | Notepad saved `.env.txt` | "Save as type: All files" |
| Ollama replies are cut off | `num_ctx` too small | `PARAMETER num_ctx 32768`; `ollama create` again |
| First LLM call takes minutes every time | model unloaded between calls | `setx OLLAMA_KEEP_ALIVE -1`, restart Ollama |

## 13. Cheat sheet

```
cd /d %USERPROFILE%\supervisor
uv sync --python 3.11 --extra databricks
uv sync --python 3.11 --extra databricks --native-tls
uv run python -m supervisor.cli preflight
uv run python -m supervisor.cli preflight > preflight.txt
uv run python -m supervisor.cli serve
databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile
uv run python -m supervisor.jobs.bootstrap_schema --plan
uv run python -m supervisor.jobs.bootstrap_schema
uv run python -m supervisor.jobs.bootstrap_schema --grant-to FILL-ME-app-service-principal-id
uv run python -m supervisor.cli export-reqs
uv run python -m supervisor.cli export-reqs --nexus FILL-ME-nexus-host
databricks bundle validate -t dev --profile FILL-ME-profile
databricks bundle deploy -t dev --profile FILL-ME-profile
databricks bundle run supervisor -t dev --profile FILL-ME-profile
databricks apps get supervisor-FILL-ME-username --profile FILL-ME-profile
uv run python -m supervisor.jobs.cluster_run notebooks\bootstrap_and_smoke.py --param CATALOG=FILL-ME-catalog --param SCHEMA=FILL-ME-schema
set RUN_DATABRICKS=1
uv run python -m pytest tests\live tests\contract -v
set RUN_DATABRICKS=
uv run python -m pytest
set DATABRICKS_TOKEN=
setx OLLAMA_KEEP_ALIVE -1
ollama list
```


## 14. Operations: logs, health, headers, limits

Settings are environment variables or lines in `.env`. Restart the app after a change.

| Topic | Setting (default) | What it does |
|---|---|---|
| Log level | `LOG_LEVEL` (`INFO`) | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| Log format | `LOG_FORMAT` (`text`) | `json` = one JSON object per line: `ts`, `level`, `logger`, `msg`, `request_id`, `principal_id`, and `exc_type` / `exc` on errors |
| Log file | `LOG_FILE` (off) | Absolute path. Rotating UTF-8 file. `LOG_FILE_MAX_BYTES` (10000000), `LOG_FILE_BACKUPS` (3) |
| Request id | `REQUEST_ID_HEADER` (`X-Request-ID`) | Accepted from the caller if it matches `^[A-Za-z0-9._-]{8,128}$`, else generated. Always echoed in the response |
| Security headers | `SECURITY_HEADERS_ENABLED` (`true`) | CSP, X-Frame-Options, nosniff, Referrer-Policy; `Cache-Control: no-store` on console pages |
| HSTS | `HSTS_ENABLED` (`false`) | Turn on only behind TLS |
| Body limit | `MAX_REQUEST_BYTES` (`10000000`, `0` = off) | Answer 413 with a message above the limit. OTLP and form limits stay |
| Rate limit | `RATE_LIMIT_ENABLED` (`false`), `RATE_LIMIT_PER_MINUTE` (120), `RATE_LIMIT_BURST` (30) | Token bucket per user on POST/PUT/PATCH/DELETE; answer 429 with `Retry-After` |

```
set LOG_FORMAT=json
set LOG_FILE=C:\supervisor\logs\supervisor.log
set RATE_LIMIT_ENABLED=true
python -m supervisor.cli serve
```

Every log message passes a PII scrubber (phone, CCCD/CMND, account number, e-mail, names become `[PHONE]`, `[CCCD]`, and so on). The `principal_id` field is the actor id and is not scrubbed.

Probes (no sign-in, no secrets in the body):

* `GET /health` returns 200 `{"status":"ok","version":...}` while the process runs. `GET /healthz` is unchanged.
* `GET /ready` returns 200 `{"ready":true,"checks":{...}}` when the runtime is built, the store answers and the evidence signer is loaded. It returns 503 with `"failed":[names]` otherwise. 503 is for probes and load balancers, not for people. The `scheduler` check shows `running`, `off` or `not-leader` and does not fail the probe.

If the runtime build fails at startup, `/ready` stays 503 until the first gateway call builds it again. This is correct for a probe: the app cannot decide yet.

Rate limit scope: the key is `X-Forwarded-Email`, else the dev user (`X-Dev-User` or `sv_dev_user` cookie), else the client IP. `POST /gate/check`, `POST /v1/gate/check` and `POST /v1/traces` are not limited: agent traffic is governed by the gateway (fail mode), and a human limit there would turn a busy agent into a gate outage. The key is read before sign-in. On the Databricks App the proxy sets `X-Forwarded-Email`, so the key is the real user. On a laptop a caller can change the header, so the limit is a throttle there, not a control.

The interactive `/docs` and `/redoc` pages are off: they load JavaScript from a CDN. The API schema is at `/openapi.json` (see `docs/api.md`).

Default-on changes in this release (a pure addition, each can be turned off):

1. Security headers on every response (`SECURITY_HEADERS_ENABLED=false` removes them). The CSP allows only same-origin scripts; inline `style=` is allowed. Vendored htmx and `console.js` work unchanged.
2. A request id header on every response (`X-Request-ID`).
3. A 10 MB request body limit (`MAX_REQUEST_BYTES=0` removes it).
4. Log scrubbing of PII in every log line.

## Retention (PDPL)

Personal-data columns are set to NULL after their retention time. Rows, hashes and the evidence chain stay, and the chain still verifies (ADR D13). The job is off by default.

| Class | Columns | Setting (default) |
|---|---|---|
| raw | `agent_event_raw.args_raw`, `result_raw` | `RETENTION_RAW_DAYS` (90) |
| masked | `agent_event` args/result, `verdict.rationale_masked`, `case_event.comment_masked` | `RETENTION_MASKED_DAYS` (365) |
| notice | `notice.body` | `RETENTION_NOTICE_DAYS` (365) |

```
set RETENTION_ENABLED=1
set RETENTION_DRY_RUN=1
python -m supervisor.jobs.retention
set RETENTION_DRY_RUN=0
python -m supervisor.jobs.retention
```

* Always run with `RETENTION_DRY_RUN=1` first. Redaction cannot be undone: back up first.
* The app scheduler runs the job every `SCHED_RETENTION_S` (86400) seconds when `RETENTION_ENABLED=1`. Run the command by hand only when the app is stopped (one chain writer).
* After an upgrade, run `python -m supervisor.jobs.bootstrap_schema` once. It replaces the old append-only triggers. If you skip it, the job prints `[FAIL]` and names this command.
* On Databricks the append-only tables are count-only (`[SKIP] Delta appendOnly: needs bank decision`). Only `notice` is changed.
* Each run adds a `retention_run` entry to the evidence chain (counts and cutoffs, no personal data).

## Backup, restore, support bundle

All commands run from the repo folder, with the app settings in `.env`. Paths are examples.

### Support bundle (send this to support, not the logs)

```
python -m supervisor.cli support-bundle --out C:\supervisor-support\bundle1
```

* Writes `settings.json` (secrets shown only as `***set***`), `preflight.txt`, `schema.json`, `chain.json` (lane heads, no payloads), `logs.txt` (last 500 lines of `LOG_FILE`, PII masked, secrets scrubbed), `env.json`, `manifest.json` (sha256 of each file) and `support-bundle-<time>.zip`.
* Options: `--log-lines N` (default 500), `--force` (use a non-empty folder), `--network` (also run the Databricks and LLM preflight checks; the default skips them, so the command never hangs on the network).
* The bundle never creates a missing store and never prints environment variables. Open the zip and read `settings.json` once before you send it.

### Backup (SQLite mode)

```
python -m supervisor.cli backup --out C:\supervisor-backup\2026-10-15
python -m supervisor.cli backup --out C:\supervisor-backup\2026-10-15 --include-key
```

* The app may run: the copy uses the SQLite online backup. The folder gets `supervisor.db`, `manifest.json` (time, version, schema hash, sha256, table row counts, chain lane heads) and the `anchors` folder when `ANCHOR_KIND=worm_dir`.
* The signing key is copied only with `--include-key`. A folder with the key must be stored as a secret. Without the flag, back up `SIGNER_KEY_PATH` yourself to the bank secret store.
* In App mode the command prints `[FAIL] backup is for SQLite mode; use export-delta` and exits 1.

### Restore

```
python -m supervisor.cli restore --from C:\supervisor-backup\2026-10-15
python -m supervisor.cli restore --from C:\supervisor-backup\2026-10-15 --force
python -m supervisor.cli restore --from C:\supervisor-backup\2026-10-15 --pubkey C:\secure\notary.pem
python -m supervisor.cli restore --from C:\supervisor-backup\2026-10-15 --allow-key-change
```

* Stop the app first. The command checks the manifest and the sha256, refuses a backup with a newer schema than the code, and refuses to overwrite an existing store unless `--force`. With `--force` the old file is moved to `<name>.pre-restore-<time>`, never deleted.
* The command first copies the backup to a temporary file beside the target and verifies that copy. Only if every check passes does it move the old store aside and swap the copy in. On any failure the live store is not touched and the temporary file is removed.
* The sha256 in `manifest.json` only detects accidental damage. It is not an authenticity check (the manifest sits next to the data). Authenticity comes from the chain check, which is pinned to the public key of the current signer (`SIGNER_KIND` / `SIGNER_KEY_PATH`). A chain signed by another key is refused.
* `--pubkey FILE` pins a key you give (PEM, for example exported from the bank secret store) instead of the current signer's key. Use it on a new machine that has no signing key yet; if no key can be found, restore refuses unless you pass `--pubkey` (or `--allow-key-change`).
* `--allow-key-change` accepts a backup signed by a different key. It prints a `[WARN] WARNING:` line with both key fingerprints and still checks the chain with the backup's own key. That proves the chain is consistent, not who made it. Use it only for a known key change (key rotation, new deployment) and record the reason.
* The signing key file in the backup (`--include-key`) is installed only if the target has no key, the file is a regular file (not a symlink) and its public key is the pinned key. Otherwise restore prints a `[WARN]`, skips it, and you restore the key from the secret store. Symlinks in the backup `anchors` folder are skipped too.
* A backup with no chain entries is refused (`signed roots: none verified`): an empty store has nothing to restore; bootstrap instead.
* The manifest `db_file` must be a bare file name; paths, `..`, drive letters and absolute paths are refused.
* The chain check prints `[OK] evidence chain verifies` or `[FAIL]`. An older backup prints a warning: run `python -m supervisor.jobs.bootstrap_schema` (it adds columns only).

### Delta export (App mode)

```
python -m supervisor.cli export-delta --out C:\supervisor-export\2026-10-15
python -m supervisor.cli export-delta --out C:\supervisor-export\2026-10-15 --tables chain_entry,chain_payload
```

* One read-only `SELECT` per table through the Statement Execution API. Output: `<table>.jsonl` and `manifest.json` (row counts, sha256, schema hash, workspace host). It also works on SQLite (same code).
* Run it from the laptop with the CLI OAuth profile (`databricks auth login --host <host> --profile <name>`, then `set DATABRICKS_CONFIG_PROFILE=<name>`), or from a notebook. Large tables take time: export one table at a time with `--tables`.
* Restoring Delta is a task for the bank DBA. Use the Delta features: time travel (`RESTORE TABLE ... TO VERSION AS OF`) and `DEEP CLONE`. History is kept for `delta.logRetentionDuration` (set from `EVIDENCE_RETENTION_DAYS` for evidence tables): confirm that value covers the recovery window you need. The JSONL export is a second copy outside Delta, not a restore tool.

### DR drill (SQLite mode, about 15 minutes)

1. `python -m supervisor.cli backup --out C:\drill\backup --include-key`
2. Point a new data folder: `set DATA_DIR=C:\drill\restore-data`. `SQLITE_PATH` and `SIGNER_KEY_PATH` must not be set in `.env` (comment them out): their defaults follow `DATA_DIR`
3. `python -m supervisor.cli restore --from C:\drill\backup --pubkey C:\secure\notary.pem` (the new data folder has no signing key, so pin the notary public key; `--allow-key-change` is the weaker choice). Expect `[OK] evidence chain verifies`.
4. Compare counts: the `table_counts` in `C:\drill\backup\manifest.json` against a new backup of the restored store (`backup --out C:\drill\check`, then compare the two `table_counts`). They must be equal.
5. Start the app on the restored data (`python -m supervisor.cli serve`), open `/health`, then stop it. Delete `C:\drill` (it holds a key copy).
6. Write down the elapsed time (measured RTO) and the age of the backup (RPO).

| Target | Value |
|---|---|
| RPO (maximum data loss) | FILL-ME: bank decision |
| RTO (maximum time to recover) | FILL-ME: bank decision |
| Backup schedule and retention | FILL-ME: bank decision |
| Backup storage location (and who holds the signing key copy) | FILL-ME: bank decision |
