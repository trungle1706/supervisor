# Demo runbook (stage)

Harness: `src/supervisor/demo/` (WP11). All data is synthetic. No network is needed.
Commands are Windows cmd, run from the unzipped `supervisor` folder.

## Honesty rules (say them, show them)

| Live, never faked | Scripted or recorded, and labelled |
|---|---|
| Gate block of the harmful tool call (real rule in `policies/`) | Agent LLM output: `[FIXTURE] agent LLM output is scripted (MockChat)` |
| Pause of the agent (read back from the store) | Judge: MockJudge when no model is set, `MOCK` in the terminal and in the console |
| Chain break found by the offline verifier | `[REPLAY]` lines: a recorded twin of a model step, only with `--replay` |
| Case opened by the same case service the console uses | `[DEMO]` lines: the runbook's two-person auto-resume |

The `[FIXTURE]` line under each incident header covers that incident block: the agent's
tool call is scripted, everything after it (gate, pause, case, chain) is live.
If a live control fails, the line is `[FAIL]`. There is no replay for the gate, the pause
or the tamper test.

## Before the day

| When | Do | Expect |
|---|---|---|
| T-7d | `uv run python -m supervisor.cli demo --loop 20 --quiet` | last line `[OK] demo loop: 20/20 runs passed` (build host: 6.7 s) |
| T-1d | `uv run python -m supervisor.cli demo seed` | `[OK] reset snapshot taken` |
| T-60m | `uv run python -m supervisor.cli demo` (one full run) | `[OK] demo run 1: PASS` |
| T-10m | `uv run python -m supervisor.cli demo serve` ; open http://127.0.0.1:8000/console/ ; browser zoom 125 % | `[OK] demo console on http://127.0.0.1:8000/console/` and the key help line |

`demo serve` runs the console and the demo keys in one process (the evidence chain has
one writer). Do not run `serve` at the same time.

Keys in the `demo serve` window: `1`-`4` inject, `t` tamper, `r` resume (two-person,
`[DEMO]` shortcut), `z` reset, `s` status, `q` quit.

## On stage (about 6 minutes)

| Time | Beat | Operator | Terminal shows | Presenter says | Console page |
|---|---|---|---|---|---|
| 0:00 | Normal day | (nothing) | | "Three agents ran a normal day: 56 tasks, every call checked by the gateway, no case." | Agents `/console/agents`: three RUNNING; Metrics `/console/metrics` |
| 0:30 | Incident 1: injected ticket | key `1` | `[OK] gate PAUSED payments tool call: rule PAY-07 (real rule match)` then `[OK] payments gate_state=PAUSED` | "A ticket told the agent to send money abroad. The tool is not approved. The gateway stopped the call before it ran and paused the agent. This is the real gate, not a slide." | Queue `/console/`: new critical case; Agents: payments PAUSED |
| 1:30 | Resume needs two people | Agents page: Resume as `reviewer.an`, then as the owner (Switch user) | | "Pause is one click. Resume needs two different people: owner and reviewer." | Agents: pending approval, then RUNNING |
| 2:15 | Incident 2: fee-waiver abuse | key `2` | `[OK] gate BLOCKED customer_service tool call: rule SVC-02`; judge lines with `MOCK` | "Each waiver is small. The rule counts them per account per day and blocks the third. The judge only advises; here it is a mock, and the screen says so." | Case page `/console/cases/<id>`: rule broken, judge finding with MOCK badge |
| 3:00 | Incident 3: credit without documents | key `3` | `[OK] gate BLOCKED credit_prequal tool call: rule CRD-01` | "The gateway asked the system of record: the income proof is missing. No approval." | Queue: high case |
| 3:30 | Incident 4: split payment | key `4` | `[OK] gate BLOCKED payments tool call: rule PAY-08`, `harm recorded: transfers +1` | "Two agents each sent 60 million to the same payee. Each is under the limit; together they are not. The first went through, the second is blocked." | Case page: caller agents in the timeline |
| 4:15 | Case workflow | Case page: Assign, Triage, Contain; Sign-off as two people | | "Every click is evidence, with the person's name and how they signed in." | Case, Sign-off |
| 5:00 | Tamper test | key `t` | `[OK] verify ORIGINAL: RESULT OK`, `tamper on the COPY only: ... PAY-08 -> PAY-09`, `[OK] verify TAMPERED copy: RESULT FAIL`, `verifier: FAIL lane agent:payments ...`, `[OK] verify ORIGINAL again: RESULT OK; live store unchanged` | "We change one character in a copy of the evidence and even fix the file checksums. The hash chain still finds it, offline, with the auditor's tool." | Metrics: Verify chain -> OK |
| 5:45 | Close | | | "Measured on this laptop, not a slide." | Metrics |

After the demo: key `z` (reset, about 1 s), then `q`. If a reset fails halfway (for
example a locked file on Windows), run it again: the snapshot is kept.

## Fallback triggers

| Symptom | Trigger | Action | What the screen says |
|---|---|---|---|
| Judge step not done after 20 s, or fails (real model configured) | `[FAIL] judge step judge-DEMO-2: ... Fallback: rerun with --replay` | Restart with `uv run python -m supervisor.cli demo serve --replay` (or `demo --replay`) | Every judge line starts with `[REPLAY]` and names the recording |
| `[FAIL] payments is PAUSED; the incident would be stopped by that state` | A paused agent was not resumed | Resume in the console (two people) or key `r` | `[DEMO]` on the shortcut |
| Any other `[FAIL]` on a gate, pause or tamper line | Real defect | Do not replay. Key `z`, retry once; else show the recorded video (level 4) | |
| Console page error | Browser | Refresh; the console answers HTTP 400 with a message, never 500 | |
| Laptop problem | | Second laptop with the same zip; or the recorded screen video | |

Fallback levels (analysis 04): 1 live; 2 `--replay` for model steps only; 3 laptop build
(this zip); 4 recorded screen video of a clean run; 5 concept video.

## Commands

| Need | Command |
|---|---|
| Full run (seed, 4 incidents, tamper, reset) | `uv run python -m supervisor.cli demo` |
| 20 runs with timing | `uv run python -m supervisor.cli demo --loop 20 --quiet` |
| One step | `uv run python -m supervisor.cli demo seed` / `demo inject 2 --auto-resume` / `demo tamper` / `demo reset` |
| Stage mode | `uv run python -m supervisor.cli demo serve [--replay] [--port 8000]` |
| Other data dir | add `--data-dir C:\work\demo-data` (default `data\local\demo`) |
| Re-record the judge twin | `uv run python -m supervisor.cli demo --record` |

Optional beats: `--onboard` runs the onboarding beat when WP9 (`supervisor.onboard`) is
in the build; otherwise the runbook prints `[SKIP]`. The drift and fairness beats belong
to WP7 (`supervisor.monitors`); the runbook prints `[SKIP]` for them.

## Known limits

- The MockJudge has no keyword for the invented "miễn phí trọn đời" policy, so on DEMO-2
  it logs the trace as benign (about 458 bp). The case still opens from rule SVC-02. A
  real judge model is expected to flag it; that is measured by the judge eval, not here.
- The 20-run test (`tests/e2e/test_demo_runbook.py`) asserts the three live controls in
  every run and prints the measured timing.
