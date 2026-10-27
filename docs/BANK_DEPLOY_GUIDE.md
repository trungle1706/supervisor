# Deploying at Techcombank: what a coding agent must know

**Audience:** a coding agent building a new Python app that must run in two places:

1. on a TCB work laptop (self-host);
2. as a Databricks App on the bank's workspace.

**Where this comes from:** the MRM AI Validation workbench, which runs in both places. Everything below was found the hard way, mostly as live failures on the bank laptop or the bank workspace. Treat it as constraints, not suggestions. Where something is a *project choice* rather than an environment fact, it is marked **[house rule]**; check with the user whether it applies to the new app.

Drop this file into the new repo (or paste it into `AGENTS.md` / `CLAUDE.md`) and read it before writing any deployment, networking, subprocess or Databricks code.

---

## 0. The ten things that break first

| # | Rule | What happens if you ignore it |
|---|---|---|
| 1 | Launch everything as `python -m <module>` (`uv run python -m uvicorn …`, `uv run python -m pytest`). | AppLocker blocks the venv's `.exe` stubs: "Access is denied (os error 5)". |
| 2 | Python **3.11** must work. Don't require 3.12. | uv tries to download an interpreter from GitHub through the TLS proxy and fails with `UnknownIssuer`. |
| 3 | Packages come from **Nexus**, never PyPI, on the laptop. | `uv sync` can't resolve anything. |
| 4 | Every Python process that talks to Databricks injects the **OS trust store** (`truststore`). | `CERTIFICATE_VERIFY_FAILED`, or a 5-minute SDK retry hang. |
| 5 | Databricks SQL from the laptop goes over the **REST Statement Execution API**, not the thrift connector. | `RemoteDisconnected` on every query to `/sql/1.0/warehouses/…`. |
| 6 | **OAuth only** (`databricks auth login`). No PATs, ever. | Bank rule violation; preflight should hard-fail on `DATABRICKS_TOKEN`. |
| 7 | The Databricks App runtime has **no package index**. Dependencies install at BUILD from `requirements.txt`; the start command is plain `python -m uvicorn`, not `uv run`. | The app crashes at startup trying to sync. |
| 8 | The shared cluster is **interactive-only**. Use the Command Execution API (execution contexts), not Jobs. | `jobs/runs/submit` is refused: "does not support jobs workload". |
| 9 | Resolve every path to an **absolute** path before handing it to a child process or a different cwd. | WinError 267 on Windows. On the App: `.venv/bin/python: No such file or directory`. |
| 10 | User-visible errors return HTTP **400** with a message, never 500, if the UI uses htmx. | htmx silently drops 500 responses, so the UI just hangs (seen several times). |

---

## 1. Target environments at a glance

| | Bank laptop (self-host) | Databricks App |
|---|---|---|
| OS / shell | Windows 11, **cmd** (no bash, no `.sh`), no admin rights, AppLocker | Linux container |
| Python | 3.11 (local install) | platform-provided |
| Packages | Nexus via `uv.toml` | `requirements.txt` installed during the App **BUILD** phase |
| Network | transparent TLS inspection; thrift to Databricks dropped | BUILD and runtime are **split networks**; the runtime reaches no package index |
| LLM | Ollama for Windows, **CPU-only**, small Qwen (4B), `127.0.0.1:11434` | Databricks model-serving endpoint |
| Databricks auth | CLI OAuth profile (U2M), acting as the user | platform-injected service principal (M2M); optional on-behalf-of user token |
| Storage | local files and SQLite | `/tmp` only, **wiped on every restart** |
| Port | anything on `127.0.0.1` | **8000** on `0.0.0.0` |

Design for both from day one: **one codebase, the environment chosen by config only** (env vars / `.env`). Never fork code paths per deployment beyond an adapter factory.

---

## 2. Bank laptop (Windows, self-host)

### 2.1 Packaging and install

- Ship a `uv.toml` **only in the zip/hand-off bundle** (not committed to the repo):

  ```toml
  [[index]]
  url = "https://nexus-dev.techcombank.com.vn/repository/pypi-common-proxy/simple/"
  default = true

  allow-insecure-host = ["nexus-dev.techcombank.com.vn"]
  ```

  The user must run `uv` from the folder that contains it.
- Install: `uv sync --python 3.11`. If uv still reports `UnknownIssuer`, add `--native-tls` (use the Windows cert store).
- Every dependency must exist on Nexus as a wheel for **Windows + Python 3.11**. Avoid packages that need a compiler or a Rust/C build step at install time.
- Optional extras (e.g. a `databricks` extra) are fine. If a feature needs one, say so in the error message ("run `uv sync --extra databricks`").
- `torch`, CUDA and anything GPU-bound are effectively unavailable. The laptop is CPU-only.

### 2.2 Launching

- Always `uv run python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`, and `uv run python -m pytest`. Never `uv run uvicorn` or `uv run pytest`: AppLocker blocks those `.exe` stubs.
- All instructions you write for the user are **cmd** syntax: `set VAR=value`, `cd /d`, backslashes, `%APPDATA%`. No `$(…)`, `export`, `rm`, `cp` or `printf`.
- Warn about Notepad: it saves `Modelfile` / `.env` as `Modelfile.txt` / `.env.txt` unless the user picks "All files".

### 2.3 Windows code pitfalls (all of these were live bugs)

- **Relative paths.** `DATA_DIR=./runs` resolved against a child process's cwd broke runs (WinError 267). Worse, it silently disabled a security hook, because `PYTHONPATH` pointed at the wrong place. Call `Path(x).resolve()` once at config load and pass absolute paths everywhere.
- **File locking.** `os.replace` / rename can fail with `PermissionError [WinError 5]` when antivirus or another handle holds the file. Wrap atomic-rename writes in a short retry loop.
- **`sys.executable` may be relative.** That is the case on the Databricks App, and the same class of bug applies on Windows. Resolve it with `os.path.abspath`, *not* `realpath`: `realpath` follows the venv symlink to the base interpreter and loses the venv's packages.
- **No `unshare`, no POSIX signals, no `fork`.** Any process sandboxing must have a Windows path. Ours uses a Python-level socket stub via `sitecustomize` and audit hooks.
- **`ctypes` on Windows** resolves `kernel32.GetLastError` at import time, and numpy, pandas and sklearn all import ctypes. If you add an audit hook that blocks `ctypes.dlopen`, exempt exactly that pair, or no numeric code runs.
- **Jupyter/IPython in a child process** need `JUPYTER_*`, `IPYTHONDIR` and `APPDATA` pointed at writable pre-created dirs, and the full Windows environment passed through (`SYSTEMROOT` etc.). Otherwise kernels fail to start.
- **Console output:** keep CLI/preflight output ASCII (`[OK]` / `[FAIL]`). The cmd console code page may not be UTF-8.
- **Patching in tests:** to simulate Windows on Linux, patch a module-level `_IS_WINDOWS` flag, not `os.name`. Patching `os.name` makes `pathlib` produce `WindowsPath` objects that crash on POSIX.

### 2.4 Local LLM (Ollama, CPU)

- Endpoint `http://127.0.0.1:11434/v1` (OpenAI-compatible). The model name must equal an `ollama list` name. The user registers a GGUF with a `Modelfile` (`FROM <path>`, `PARAMETER num_ctx 16384`; raise it to 32768 if output is cut off).
- **It is slow.** A 4B model on CPU takes tens of seconds to several minutes per call. Make the per-call timeout configurable (we needed `LLM_TIMEOUT_S=1800`), and tell the user to set `OLLAMA_KEEP_ALIVE=-1` before starting Ollama so the model stays loaded between calls.
- Run long LLM work as **background tasks with visible progress**. Provide a "reset / retry" for steps stuck in `running`, and recover interrupted tasks at startup; the user *will* close the laptop lid.
- Request structured output with `response_format: {"type":"json_schema", …}`. Ollama enforces the grammar, so `<think>` blocks can't leak into JSON. The llama.cpp-only switch `chat_template_kwargs.enable_thinking=false` does **not** work on Ollama.
- Small models fail in predictable ways. Guard against each:
  - **Truncation.** Detect `finish_reason == "length"` and show a clear "reply was cut off" message; don't retry blindly.
  - **Repetition loops.** Cap output with `max_tokens` (we use 8192) and allow one retry with an anti-repetition instruction.
  - **Prose inside code.** Run `ast.parse` on any generated Python before executing it, with one audited repair attempt.
  - **Unterminated JSON strings in large payloads.** Don't ask the model to echo big code blobs back inside JSON; assemble them in app code.
- Token log-probabilities (`/api/chat` with `logprobs`) need **Ollama ≥ 0.12**.
- **[house rule] Zero AI egress:** the LLM base URL must be loopback. Validate this at startup and refuse anything else.

---

## 3. Bank network (affects the laptop and anything that leaves it)

- **Transparent TLS inspection.** There is no proxy setting (`netsh` shows none); an appliance re-signs HTTPS. Browsers and the Go-based `databricks` CLI trust the Windows cert store; Python's `certifi` does not. Fix it at app startup, before any HTTPS client is created:

  ```python
  if os.environ.get("SSL_OS_TRUSTSTORE") == "1":
      import truststore
      truststore.inject_into_ssl()
  ```

  Do the same at the top of **every** entry point that talks to Databricks: the app, preflight script, live tests and helper CLIs.
- **The appliance drops the Databricks SQL connector's thrift protocol** mid-stream (`RemoteDisconnected` / `Connection aborted`), while REST calls to the same workspace succeed. Use the **Statement Execution API** (`POST /api/2.0/sql/statements` via `databricks-sdk`) as the transport, selectable by config (`DATABRICKS_SQL_TRANSPORT=rest`). Note:
  - values arrive as **strings**; cast before doing arithmetic;
  - follow result chunks for large results;
  - set an explicit wait/deadline (we use about 120 s); a cold warehouse takes about 30 s for the first query.
- **Cap SDK retry budgets.** The SDK and connector defaults retry low-level failures for 5–15 minutes, so the app looks frozen. Cap them at 60–120 s, passing the cap inside the SDK `Config`, not as a `WorkspaceClient(...)` kwarg.
- No internet from the laptop runtime. Code that downloads anything (datasets, models, NLTK data, tiktoken files, HF hub, CDN JS/CSS) fails. **Vendor static assets** (htmx, CSS, fonts) into the repo.

---

## 4. Databricks: auth, workspace, data

### 4.1 Auth

- **OAuth only.**
  - On the laptop: `databricks auth login --host https://<host> --profile <name>`. The app then uses `DATABRICKS_AUTH_TYPE=databricks-cli` + `DATABRICKS_CONFIG_PROFILE=<name>` and shares the CLI's token cache, acting **as the signed-in user**.
  - On the App: the platform injects `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` (service principal).
- Never read, accept or document `DATABRICKS_TOKEN`. Preflight should **fail** if it is set.
- **Bank SSO refresh tokens expire quickly.** "invalid refresh token" / "cannot configure default credentials" means the user must re-run `databricks auth login`. Surface that exact command in the error message.
- The bank has **several `dbc-…` workspaces**. Tables created in one are invisible from another (`TABLE_OR_VIEW_NOT_FOUND`). Make the host explicit in config and show it in error messages.

### 4.2 Known compute and namespaces (as of 2026-10)

- Workspace `FILL-ME-workspace-host.cloud.databricks.com` (AWS-hosted).
- SQL warehouse `FILL-ME-warehouse-name`.
- Shared all-purpose cluster `FILL-ME-shared-cluster-name`: Unity Catalog shared access mode, **interactive workloads only**.
- Writable schema for this user: `FILL-ME-catalog.FILL-ME-schema`. The user lacks `CREATE SCHEMA` rights; grants are table-level inside existing schemas.
- Configure compute **by name** and resolve name → id at startup, as the user. Don't hard-code ids into committed files.
- **[house rule] Read-only data access:**
  - exactly one `SELECT` statement per query, parsed and checked **in-process before any connection opens** (we use `sqlglot`);
  - `standardized_priv.bpa.*` is a denied namespace, for metadata (`DESCRIBE`) too;
  - table names in config are validated at boot as plain `catalog.schema.table`;
  - the only remote write is an audit-mirror table in the user's own schema.

### 4.3 Running code on the cluster

- `jobs/runs/submit` is **refused** on the shared cluster. Use the **Command Execution API**:
  - create one execution context;
  - send one command per cell, so state carries over between cells;
  - stop at the first error;
  - always destroy the context in `finally`;
  - enforce an overall deadline across commands.
- No widgets or `dbutils.notebook.exit` in command mode. Inline parameters into the code. To return a result, **print a sentinel line** (e.g. `MYAPP-EXIT-JSON: {...}`) and parse stdout; the runner may reset `sys.stdout` between commands, so print to the live stdout.
- Large results: write a table into the user's schema (`spark.table` / `saveAsTable`) and read it back with SQL, rather than printing them.
- Code runs **as the user**, with their Unity Catalog permissions. That is the security boundary the bank accepts; don't build a parallel permission system on top.

---

## 5. Databricks App deployment

### 5.1 Bundle pattern proven in-bank

- `databricks.yml` (Asset Bundle):
  - the app resource with `source_code_path: ./`;
  - `resources` bindings for `sql_warehouse` (`CAN_USE`) and `serving_endpoint` (`CAN_QUERY`);
  - `user_api_scopes: [sql]` if you need on-behalf-of user SQL;
  - `dev` (default, `mode: development`) and `prod` targets, with a distinct app `name` for prod.
- **Per-workspace values go inline in the user's local copy** (warehouse id, endpoint name). Use no bundle `variables`, no `--var` flags and no secret-scope resources: that is the pattern that actually deploys at TCB. Commit placeholders (`FILL-ME-…`) and add a test that the committed files contain no real ids or secrets.
- Suffix the app name with the username (`myapp-<user>`) to avoid collisions in the workspace.
- `app.yaml`:

  ```yaml
  command: [python, -m, uvicorn, app.main:app, --host, "0.0.0.0", --port, "8000"]
  env:
    - name: PYTHONPATH
      value: "src"            # src-layout import without installing the project
    - name: LLM_BASE_URL      # AI Gateway model service (WP-L1), no bundle resource
      value: "https://FILL-ME-workspace-host/ai-gateway/mlflow/v1"
    - name: DATABRICKS_WAREHOUSE_ID
      valueFrom: sql-warehouse
  ```

- Deploy with `databricks bundle validate -t dev --profile <p>`, then `bundle deploy`, then `bundle run <app_key>`.

### 5.2 Dependencies: the split network

- The runtime container reaches **no** package index, so `uv run` at startup fails. Generate `requirements.txt` from the lockfile:

  ```bash
  uv export --no-dev --extra databricks --no-hashes --no-emit-project -o requirements.txt
  ```

  The platform installs it during **BUILD**. Keep it regenerated whenever `uv.lock` changes; a test comparing the two is cheap.
- Whether BUILD reaches public PyPI or only Nexus was **observed both ways at different times**. If BUILD fails to resolve packages, put these at the top of `requirements.txt`:

  ```
  --index-url https://nexus-dev.techcombank.com.vn/repository/pypi-common-group/simple/
  --trusted-host nexus-dev.techcombank.com.vn
  ```

  Note this is `pypi-common-group`; the laptop's `uv.toml` uses `pypi-common-proxy`.

### 5.3 Runtime behaviour

- **`/tmp` is ephemeral:** files and SQLite databases there are wiped on restart or redeploy. For anything that must survive, use a Unity Catalog Volume or Delta table, or state plainly in the UI that the instance is a demo.
- The app sits behind workspace SSO. The signed-in user arrives in headers, including `X-Forwarded-Access-Token` when `user_api_scopes` is set.
  - Use that token only **inside the request** and open a fresh, uncached client per call.
  - Never log it.
  - Fall back to the service principal when the header is absent: local runs, and **background tasks, which have no request and therefore no user token**.
  - Record in your audit trail which identity ran each action.
- `sys.executable` is a **relative** `.venv/bin/python` on the App. Make it absolute before spawning anything with a different cwd.
- The App's runtime egress is restricted too; assume only the workspace's own APIs are reachable.

---

## 6. Bank control conventions worth copying

**[house rule]** where noted; confirm with the user which apply.

- **Secrets:** nothing real in git: no `.env`, workspace ids, endpoint names or passwords. Hand-off zips are built with `git archive HEAD` and then leak-swept for `.env`, `*.db`, `.venv`, `__pycache__`, model files and run data.
- **New features default off**, and the off state behaves exactly like before. Test the off path explicitly.
- **No `exec`, `eval`, `compile` or `subprocess` outside one sandbox module** [house rule]. An AST-scanning test enforces it, so use `ast.parse` for syntax checks.
- **Audit trail:** append-only, hash-chained, recording who did what with which identity. Never record tokens.
- **AI output is advisory** [house rule]: the model produces observations, and a human makes decisions. Export the human's text verbatim.
- **Preflight script:** one command the user runs on the laptop that checks:
  - config load and the trust-store injection;
  - the Databricks extra installed, and no PAT set;
  - the CLI profile exists and OAuth is valid;
  - the warehouse is reachable; the serving endpoint exists and is READY.

  Print `[OK] / [FAIL] / [SKIP]` with the exact fix command, never secret values, and exit non-zero on any failure. This saves more round-trips than anything else.

---

## 7. Working with the user across the air gap

You (the agent) cannot reach the bank laptop or workspace. The user relays results by hand.

- Code that touches Databricks can only be **unit-tested with fakes** on your side. Say so explicitly and ship a **live test kit**:
  - opt-in tests gated on an env var (e.g. `RUN_DATABRICKS=1`), skipped otherwise;
  - a Databricks source-format notebook (`# Databricks notebook source` / `# COMMAND ----------`) that creates synthetic mock tables in the user's schema;
  - a runbook with the cmd commands and a symptom → cause → fix table.
- Make errors **self-diagnosing**: name the failing host, table, transport and identity, plus the fix. The user will paste you a screenshot or a traceback; make that enough.
- Hand-offs: if one or two files changed, send just those files with their paths; otherwise send a zip with `uv.toml` added.
- Instructions for the user: cmd syntax, one ordered checklist, and a cheat sheet at the end.
