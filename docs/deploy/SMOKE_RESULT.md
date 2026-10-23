# Launch smoke test: result

`tools/smoke_launch.py` starts the app on a free port with a temporary data folder, opens the
console, registers an AI system through `POST /v1/systems`, runs a Playground dry-run check,
verifies the evidence chain, stops the app and removes the folder. Standard library only; no bash.

| Item | Value |
|---|---|
| Date | 2026-10-23 |
| Host | Linux 6.8.0-147-generic (the Supervisor build host) |
| Python | 3.11.17 (the version the project pins) |
| Code | v0.5.0 branch of WP-P1, run on commit 89f1231 (later commits change only tests and docs) |
| Command | `uv run python tools/smoke_launch.py` (on the laptop: `.venv\Scripts\python.exe tools\smoke_launch.py`) |
| Exit code | 0 |
| Windows | NOT run. The script uses `sys.executable`, `pathlib`, `urllib` and `sandbox.start`; it has no shell and no POSIX call. The first Windows run is the test. Note: on Windows the app stops with `terminate()`, which is a hard stop, so the line `app stopped (exit N)` shows another code and the chain is not sealed with a closing root. This does not change the step results |

## Output

```
[OK] python 3.11.17 on linux; app on http://127.0.0.1:45015; data /tmp/supervisor-smoke-0h4hk01x
[OK] app started (pid 3916023)
[OK] healthz answers 200
[OK] console page opens (/console/)
[OK] AI system registered and read back (sys_cc3f1deca1cb9fff)
[OK] playground dry-run check answered (nothing recorded)
[OK] evidence chain verifies
[OK] app stopped (exit -15)
[OK] smoke test passed
```

The port, pid and folder change on every run. `exit -15` is SIGTERM on Linux: uvicorn shut down
cleanly (the app log shows "Application shutdown complete").

## What a failure looks like

Each failed step prints `[FAIL] <step>: HTTP <status> <first 160 characters>`, the run goes on to
the next step, the last 25 lines of the app log are printed after the stop, and the exit code is 1.
If `/healthz` never answers, the later steps are skipped. Tests of the helpers and one real run:
`tests/unit/test_smoke_launch.py`.
