# Demo replay twins (fixtures)

Recorded outputs of demo steps that call a model. `python -m supervisor.cli demo --replay`
shows a twin only when the live step fails or is not done after 20 s, and prefixes every
line with `[REPLAY]`.

| File | Step | Recorded from |
|---|---|---|
| `judge-DEMO-2.json` | Advisory judge on the DEMO-2 attack trace | `demo --record` with the MockJudge (no model configured) |

Rules:

- Only `judge-*` and `onboard-*` steps can have a twin (`supervisor/demo/fallback.py`).
  The gate block, the pause and the chain break always run live; there is no twin for them.
- Every twin carries `label`, `recorded_at` and `source`. All data is synthetic.
- Re-record after a judge or prompt change: `python -m supervisor.cli demo --record`.
- An onboarding twin (`onboard-credit_prequal.json`) can be recorded once WP9 is in the build.
