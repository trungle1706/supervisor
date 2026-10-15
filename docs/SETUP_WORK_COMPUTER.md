# Set up Supervisor on a Techcombank work computer

Windows 11, cmd only, no admin rights, Python 3.11, packages from Nexus, no internet at runtime.
Every command below is cmd syntax. Run them from the `supervisor` folder unless stated.

## A. Get the code onto the laptop

Pick the route that works at your desk:

| Route | When | How |
|---|---|---|
| 1 · GitHub clone | the laptop can reach github.com | `git clone https://github.com/<owner>/supervisor.git` then `cd /d supervisor` |
| 2 · Release zip | no GitHub from the laptop (the usual case) | download `supervisor-<version>-<sha>.zip` from the GitHub Releases page on a machine that can, move it through the approved channel, unzip to `C:\work\supervisor` |

The zip already contains `uv.toml` (Nexus index), `requirements.txt` and `HANDOFF.md`. A clone does not contain `uv.toml`: create it in the repo folder with this content (it is git-ignored):

```
[[index]]
url = "https://nexus-dev.techcombank.com.vn/repository/pypi-common-proxy/simple/"
default = true

allow-insecure-host = ["nexus-dev.techcombank.com.vn"]
```

## B. Install

```
cd /d C:\work\supervisor
uv sync --python 3.11 --extra databricks
```

If uv reports `UnknownIssuer`, add `--native-tls`. If uv is missing, install it from Nexus or ask IT; version 0.12 or later.

## C. Configure

```
copy .env.example .env
notepad .env
```

In Notepad choose "All files" when saving, or it becomes `.env.txt`. Minimum to change for the laptop:

```
SUPERVISOR_MODE=laptop
SSL_OS_TRUSTSTORE=1
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen3:4b
```

Leave `LLM_BASE_URL` empty to run with the mock judge (no model needed). Never put `DATABRICKS_TOKEN` anywhere: the preflight refuses to run.

## D. Check, then start

```
uv run python -m supervisor.cli preflight
uv run python -m supervisor.cli serve
```

Open http://127.0.0.1:8000/console/ in the browser. Pick a user in the top-right menu (dev identity, demo only).

## E. See it work (demo)

```
uv run python -m supervisor.cli demo seed
uv run python -m supervisor.cli demo inject 1
uv run python -m supervisor.cli demo inject 2
uv run python -m supervisor.cli demo inject 3
uv run python -m supervisor.cli demo inject 4
uv run python -m supervisor.cli demo tamper
uv run python -m supervisor.cli demo reset
```

Or the whole sequence in one go, 20 times: `uv run python -m supervisor.cli demo --loop 20`.
Serve the demo store: `set DATA_DIR=data\local\demo` then `uv run python -m supervisor.cli serve`.

## F. Local judge model (optional)

Install Ollama for Windows. Register the GGUF with a Modelfile (`FROM <path>`, `PARAMETER num_ctx 16384`). Before starting Ollama: `set OLLAMA_KEEP_ALIVE=-1`. The model name in `.env` must equal a name in `ollama list`. Expect tens of seconds per call on CPU; `LLM_TIMEOUT_S=1800` is safe.

## G. Databricks (when you are ready)

Follow `docs/RUNBOOK.md` sections 5 to 9: `databricks auth login --host https://<workspace> --profile tcb`, fill the `FILL-ME` values in `.env`, `databricks.yml` and `app.yaml` in your local copy only, then:

```
uv run python -m supervisor.cli preflight
set RUN_DATABRICKS=1
uv run python -m pytest tests\live tests\contract -v
databricks bundle validate -t dev --profile tcb
databricks bundle deploy -t dev --profile tcb
databricks bundle run supervisor_app -t dev --profile tcb
```

Send back: `preflight` output, the file under `data\local\live-results\`, the notebook results table, and the first 50 lines of the App log. Do not paste tokens or hosts into chat; the outputs are written so they contain none.

## H. If something fails

`docs/RUNBOOK.md` has a symptom → cause → fix table for every failure seen at the bank so far (AppLocker, TLS, Nexus, thrift, PAT, split network). Paste the `[FAIL]` line and the traceback; that is enough.
