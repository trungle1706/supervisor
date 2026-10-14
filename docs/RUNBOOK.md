# Supervisor runbook (Windows 11, cmd)

This runbook is for the bank user on a Windows 11 laptop. All commands use `cmd`. Run them in the repo folder. Always use `uv run python -m ...`. Do not use the console-script `.exe` files: AppLocker blocks them.

Placeholders that start with `FILL-ME-` are values you must set. Never put a real token in any file.

## 1. Prerequisites

| Item | Needed | Check |
|---|---|---|
| Python 3.11 | Yes | `python --version` |
| uv | Yes | `uv --version` |
| Nexus `uv.toml` from the hand-off zip | Yes | File is in the repo folder, next to `pyproject.toml` |
| Ollama for Windows | Optional (local LLM) | `ollama --version` |
| Databricks CLI | Optional (Databricks mode) | `databricks --version` |

The hand-off zip puts `uv.toml` in the repo folder. It points uv at Nexus. Run every `uv` command from that folder, or uv does not find it. Do not commit `uv.toml` (it is in `.gitignore`).

(TODO WP11: the `release` command adds `uv.toml` to the zip.)

## 2. Install

```
cd /d %USERPROFILE%\supervisor
uv sync --python 3.11
```

If uv reports `UnknownIssuer`, use the Windows certificate store:

```
uv sync --python 3.11 --native-tls
```

For Databricks mode, add the extra:

```
uv sync --python 3.11 --extra databricks
```

## 3. Configure

Create your `.env` file:

```
copy .env.example .env
notepad .env
```

Notepad warning: in "Save as", set "Save as type" to "All files". If not, Notepad saves `.env.txt` and the settings are ignored.

| Variable | Value | Note |
|---|---|---|
| `SSL_OS_TRUSTSTORE` | `1` | Use the Windows trust store. Needed behind TLS inspection. |
| `SUPERVISOR_MODE` | `laptop` or `databricks_app` or `dev` | Default is `laptop`. |
| `DATA_DIR` | Absolute path, for example `C:\Users\FILL-ME-user\supervisor-data` | Holds SQLite, keys and exports. |
| `LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | Must be loopback. A remote URL fails at start unless `LLM_ALLOW_REMOTE=1`. |

Do not set `DATABRICKS_TOKEN`. Supervisor uses OAuth only. Preflight fails if the variable is set.

(TODO WP1: full list of variables from `Settings`.)

## 4. Preflight

```
uv run python -m supervisor.cli preflight
```

| Mark | Meaning | Action |
|---|---|---|
| `[OK]` | Check passed | None |
| `[FAIL]` | Check failed. Exit code is not 0. | Fix it. See section 9. |
| `[SKIP]` | Feature is not configured, so not checked | None, unless you want that feature |

(TODO WP10: list every preflight check: trust store, no PAT, profile valid, warehouse reachable, endpoint READY.)

## 5. Run locally

```
uv run python -m supervisor.cli serve
```

Open `http://127.0.0.1:8000/healthz` in a browser. It must answer OK. Stop the server with Ctrl+C.

(TODO WP8: console URL and first login with the dev users file.)

## 6. Databricks login

```
databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile
databricks auth profiles
```

A browser window opens for SSO. The refresh token expires fast. Run the login again when you see "invalid refresh token".

## 7. Databricks App deploy

1. Copy `databricks.yml`. Edit the `FILL-ME-...` values in your local copy only: workspace host, SQL warehouse id, serving endpoint, catalog, schema, app name suffix. Do not commit real values.
2. Export the requirements file:

```
uv run python -m supervisor.cli export-reqs
```

3. Validate, deploy, run:

```
databricks bundle validate -t dev --profile FILL-ME-profile
databricks bundle deploy -t dev --profile FILL-ME-profile
databricks bundle run supervisor -t dev --profile FILL-ME-profile
```

4. Create the tables in your schema (once):

```
uv run python -m supervisor.jobs.bootstrap_schema
```

(TODO WP10: bootstrap arguments, app URL, permission grants for the app service principal.)

## 8. Tests

```
uv run python -m pytest
```

Live Databricks tests are skipped unless you opt in:

```
set RUN_DATABRICKS=1
uv run python -m pytest
set RUN_DATABRICKS=
```

(TODO WP10: live test kit details and how to send results back.)

## 9. Symptom, cause, fix

| Symptom | Cause | Fix |
|---|---|---|
| "Access is denied (os error 5)" | AppLocker blocks the `.exe` stub | Use `uv run python -m <module>` |
| uv tries to download Python and fails with `UnknownIssuer` | Python 3.11 not found locally | Install Python 3.11. Run `uv sync --python 3.11` |
| `uv sync` cannot resolve any package | Nexus `uv.toml` missing | Put `uv.toml` in the repo folder and run uv from there (section 1) |
| `CERTIFICATE_VERIFY_FAILED` or SDK hangs for 5 minutes | Process does not use the OS trust store | `set SSL_OS_TRUSTSTORE=1` or set it in `.env` |
| `RemoteDisconnected` on `/sql/1.0/warehouses/...` | Thrift connector used through the proxy | Supervisor uses REST. Do not install the thrift connector path. Report the traceback |
| Preflight FAIL: DATABRICKS_TOKEN set | A PAT is in the environment | `set DATABRICKS_TOKEN=` then remove it from user environment variables and `.env` |
| App crashes at start and tries to sync | Start command uses `uv run` | Start command must be `python -m uvicorn`. Re-run `export-reqs` and deploy |
| `jobs/runs/submit` refused: "does not support jobs workload" | Shared cluster is interactive only | Do not use Jobs. Jobs run in-process (APScheduler) |
| WinError 267 or `.venv/bin/python: No such file or directory` | Relative path given to a child process | Set `DATA_DIR` to an absolute path. Report the traceback |
| Console page hangs after a click | A 500 error, htmx drops it | Look at the server log. User errors must be HTTP 400. Report the log |
| "invalid refresh token" or "cannot configure default credentials" | SSO token expired | `databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile` |
| `TABLE_OR_VIEW_NOT_FOUND` | Wrong workspace host, or tables not created | Check the host in `.env` and the profile. Run `uv run python -m supervisor.jobs.bootstrap_schema` |

(TODO WP10: add rows from live deploy results.)

## 10. Cheat sheet

```
cd /d %USERPROFILE%\supervisor
uv sync --python 3.11
uv run python -m supervisor.cli preflight
uv run python -m supervisor.cli serve
uv run python -m supervisor.cli export-reqs
uv run python -m supervisor.jobs.bootstrap_schema
uv run python -m pytest
databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile
databricks bundle validate -t dev --profile FILL-ME-profile
databricks bundle deploy -t dev --profile FILL-ME-profile
databricks bundle run supervisor -t dev --profile FILL-ME-profile
set DATABRICKS_TOKEN=
```

(TODO WP11: `demo`, `verify` and `release` commands.)
