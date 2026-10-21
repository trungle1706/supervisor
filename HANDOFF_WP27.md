# HANDOFF WP27: Multi-turn session monitor

Branch `wp27-session-monitor` (built on `wp37-verdict-detectors`; the final WP37 head `bfc6e09` is
merged). Flag `SESSION_MONITOR_ENABLED`, default off. Nothing pushed, nothing merged to main, no
history rewritten. Author: Sonnet 5.5 engineer.

## 1. What was built

| Part | Where |
|---|---|
| Pure engine: nine integer signals (findings, refusals, expand, drift, money, near_dup, timing, cross_agent, memory), policy weights (sum 10000, validation error otherwise), case rule (K hits, score threshold, solo signals), pause rule, masked timeline, `daily_cap_minor` from the policy aggregate rule, WP28 adapter `from_redteam_trace`, `first_trip` | `src/supervisor/monitors/session.py` |
| Actions: case `session_escalation` (medium, high with a money/credit tool, no incident clock, masked timeline in the summary), `session_control` pause, two-person resume, cool-down expiry, chain records | `monitors/session_actions.py` |
| Gate hook: identity (`session_id` / derived, `session_source`), features before the lock, `GATE-SESSION-PAUSE` built-in block (not in SHADOW), observe after the decision, late Tier 0b codes, cold-start warm-up, background pause refresh | `gateway/session_gate.py`, additive edits in `gateway/engine.py`, `gateway/state.py` (`approver_role`, `on_resume` hook) |
| Batch path and job (`python -m supervisor.jobs.session_monitor`, scheduler job `session_monitor`, `SCHED_SESSION_S`), `monitor_status` key `session` | `monitors/session_batch.py`, `jobs/session_monitor.py`, `monitors/status.py`, `scheduler.py` |
| Route `GET /v1/sessions/<id>`, `POST /v1/sessions/<id>/resume`; permission `session.view`; alert `AL-SESSION-ESCALATION` (`case_type` added to the `case` alert source) | `monitors/session_api.py`, `core/rbac.py`, `alerts/`, `config/alerts.yaml` |
| Storage: `agent_event.session_id`, `session_source`, `session_json` (nullable); table `session_control`; both DDLs, `model.yaml`, notebook regenerated; span attribute `supervisor.session_id` / `gen_ai.conversation.id` -> `session_id` | `schema/`, `recorder/`, `core/models.py`, `supervisor_agents/common/` |
| Policy: `agents.<id>.monitors.session` (window, k, cooldown, thresholds, pause_scope, weights, solo_signals, cap_minor, enabled); `policy_hash` unchanged without it; `policies/schema.json` regenerated | `core/monitor_bindings.py`, `gateway/policy.py` |
| Harness (all nine brief points), golden sets 120 dev + 120 held-out + 25 probes, baseline, regression pytest | `monitors/session_harness.py`, `session_golden.py`, `data/eval/session/`, `tests/monitors/test_session_harness.py` |
| Docs: `docs/session-monitor.md`, `docs/session-monitor-validation-report.md`, `docs/monitors.md`, ADR `docs/adr/D29-session-monitor.md` (highest on branch was D23; D24-D28 are other packages), README, BACKLOG (11 rows), CHANGELOG, threat model 3.11, `docs/index.md`, `docs/console.md` | |

## 2. Decisions I took (please check)

1. **Text never reaches storage.** `agent_event` has no text, so the text features (phrase flags, keyed shingle sketch, keyed identifier hashes) are computed at the gate from `context.turn_text` and stored as `agent_event.session_json`. The batch path replays those. Callers must send `turn_text` (WP38) or the text signals are 0.
2. **Nine signals, not eight.** Added `memory` (state signal) after the WP28 finding; it may open a case alone (`solo_signals`, default `[memory]`). Set `solo_signals: []` to require K hits.
3. **PII-shaped codes (`pii*`) never count** in `findings`. A `GATE-DETECTOR-FAILED` block is not a refusal and a timed-out detector is not a finding (WP37 review). Probe: score with a hanging detector 0 vs 173 without (delta must be 0 or lower).
4. **Sketch on masked arguments:** computed after the decision from `transformed_args` when the dlp transform produced some (WP37 review F3).
5. **Pause lift:** the two-person resume reuses the agent rule (`approver_role`); a completed agent resume also lifts that agent's session pauses.
6. **Bug found and fixed:** Tier 0b can finish before `observe` stores the turn; late codes are parked and applied, and a late code re-assesses the window.
7. **Operating point** K=3, case 2500 bp, pause 4000 bp, window 1800 s, cool-down 3600 s: chosen on dev only (`--tune`), ILLUSTRATIVE. I did read WP28 sample texts to extend the generic phrase lists (authority, standing instruction), so the WP28 numbers below are not blind.
8. Correlation id: not used by the monitor (read from the decision if ever needed).
9. Edits to existing tests (minimal): `tests/monitors/test_scheduler.py` (job list), `tests/test_rbac.py` (operator gets `session.view`), `tests/console/test_rbac_matrix.py` (JSON `/v1/` routes handled like `/gate`), `tests/alerts/*` (9 rules), `tests/detectors/fingerprint.py` (my three NULL columns are ignored like the WP37 ones).

## 3. Flags and commands

| | |
|---|---|
| Flags | `SESSION_MONITOR_ENABLED=1` (0), `SCHED_SESSION_S` (300), `SESSION_WINDOW_S` (1800), `SESSION_K` (3), `SESSION_COOLDOWN_S` (3600) |
| Harness | `python -m supervisor.monitors.session_harness` (`--help`, `--tune`, `--check`, `--record --commit SHA --date D`, `--redteam [PATH]`, `--md PATH`, `--json PATH`, `--regenerate`) |
| Job | `python -m supervisor.jobs.session_monitor` |
| Delta | run `python -m supervisor.jobs.bootstrap_schema` (table `session_control`, three columns) |

## 4. Harness result (real gateway, in-request path, K=3 / 2500 bp / pause 4000 bp; ILLUSTRATIVE)

| Metric | dev | held-out |
|---|---|---|
| Attack catch (n=60) | 9333 bp [8407-9738] | 9500 bp [8629-9829] |
| Early catch (before the last money call) | 6500 | 5833 |
| False alarm on benign (n=60) | 0 bp [0-602] | 0 bp [0-602] |
| Turns to detection p50 / p90 | 6 / 8 | 6 / 8 |
| Money moved before detection (p50 of attempted) | 3333 bp | 3333 bp |
| Added latency per decision p50 / p95 / p99 | 100 / 168 / 211 us | 99 / 160 / 198 us |
| Leak items, duplicate cases | 0, 0 | 0, 0 |

Per family (catch bp, n=12 each, Wilson about 7574-10000 at 12/12): echo chamber 10000, crescendo
10000, cross-agent split 10000, memory poison 10000 (both splits); payload split 6666 dev
[3906-8619] and 7500 held-out [4676-9111]. Misses are `below_k(best_hits=2)`.

Adversarial probes outside the templates (25: 15 attacks, 10 benign): attack recall 6666 bp
[4171-8483], false alarm 0 bp [0-2776], expectation matched 25 of 25. Named misses: window expired
(2), session id churn, two consumer ids, memory paraphrase. Overall: **GO** (every metric; the
adversarial and per-family intervals are wide).

WP28 fixture (47 conversations, `tests/fixtures/session/redteam_traces.jsonl`, 24 successful, 12
benign): caught 5833 bp; echo chamber 4/4, memory poison 4/4, crescendo 3/4, payload split 2/4,
policy puppetry 1/4, tool poisoning 0/4; false alarm 0 of 12. On the full local WP28 run (247 dev
and 108 held-out successful, 252 and 108 benign) K=3 / 2500 bp catches 3036 / 3796 bp with 0
false alarms; memory poison 91 / 100 percent (their counters: 4 percent).

## 5. Recommended values for WP28's trend (from the harness)

| Profile | K | `case_threshold_bp` | `pause_threshold_bp` | Result |
|---|---|---|---|---|
| Quiet (default, recommended) | 3 | 2500 | 4000 | synthetic held-out catch 9500 bp, 0 of 60 false alarms; WP28 held-out (blind, 422 successful) catch 4099 bp, 0 of 108 false alarms (reviewer's table) |
| Sensitive | 3 | 1500 | 4000 | synthetic held-out catch 10000 bp, 14 of 60 false alarms [1443-3544]; WP28 held-out (blind) catch 7132 bp, 4 of 108 false alarms (reviewer's table; the earlier row used K=2 numbers) |

Weights: findings 1800, refusals 900, expand 1300, drift 800, money 1300, near_dup 800, timing 400,
cross_agent 1300, memory 1400 (sum 10000). Hit at 5000 bp. Window 1800 s, cool-down 3600 s.
K=2 is not recommended (28-37 percent false alarms on synthetic benign sessions).

## 6. Trace format expected from WP28 (named for the integrator)

`agents/redteam/multiturn/` (branch `wp28-redteam-multiturn`) writes `traces.jsonl`
(`python -m supervisor.redteam.multiturn run`). The adapter `supervisor.monitors.session.from_redteam_trace`
reads: `objective_id, trial, family, agent, lang, benign, success, success_turn, split` and per turn
`i, text, tier0b[], planted_tier0b[], cues{}, asked_calls, executed[{tool, amount_minor, status}],
refused, gate_would_stop[], ts`. WP28 can replay its own trace with `first_trip(sid, turns, cfg, cap)`
or run `python -m supervisor.monitors.session_harness --redteam PATH`.

## 7. Tests

| | Count |
|---|---|
| Before (WP37 head, per its handoff) | 3,800 passed, 29 skipped (WP37 review added about 30 more) |
| After (this branch, full suite, WP37 final head merged) | 3,897 passed, 29 skipped |
| New | 66 in `tests/monitors/test_session.py` (36), `test_session_api.py` (10), `test_session_harness.py` (20) |

Both modes: SQLite laptop, `databricks_app` mode (SQLite stand-in via `build_runtime`), and the
Delta statements for `agent_event` and `session_control` on the recorded fake executor.

```
$ uv sync
$ uv run python -m pytest -q -p no:cacheprovider
3897 passed, 29 skipped, 1 warning in 562.66s (0:09:22)
$ uv run python -m ruff check
All checks passed!
$ uv run python -m ruff format --check
700 files already formatted
$ uv run python -m supervisor.monitors.session_harness --check
[OK] no drop below the baseline
$ uv run python -m schema.generate / uv run python -m supervisor.databricks.notebook   (regenerated)
```

## 8. Files touched outside the package

`config.py`, `app.py`, `scheduler.py`, `wiring.py`, `gateway/{engine,state,policy,wiring}.py`,
`core/{models,monitor_bindings,rbac}.py`, `alerts/{rules,signals}.py`, `config/alerts.yaml`,
`monitors/status.py`, `recorder/{normalise,semconv}.py`, `supervisor_agents/common/{runtime,tracing}.py`,
`schema/model.yaml`, both DDLs, `notebooks/bootstrap_and_smoke.py`, `policies/schema.json`,
docs (`console.md`, `monitors.md`, `index.md`, `threat-model.md`), `README.md`, `BACKLOG.md`,
`CHANGELOG.md`, and the five existing test files listed in decision 9. The merge conflicts with the
WP37 final head (`recorder/normalise.py`, `gateway/wiring.py`) were resolved by keeping both sides.

## 9. Open questions for the owner

1. Operating point: quiet (0 false alarms, lower WP28 catch) or sensitive (K=3, 1500 bp, about 4 percent false alarms)? The bank's false alarm budget decides.
2. May `memory` open a case alone (`solo_signals`)? No false alarm seen, but real traffic is unknown.
3. Should the pause stay off by default for money tools at go-live (current default), and who owns `pause_scope` in the policy (Payments Ops)?
4. `session_id` and `consumer_id`: WP38 collectors must send them (and `turn_text`); is a verified consumer id available from ingress auth?
5. Is a 30-minute window right, or do you want a second daily window (slow attacks are a known miss)?

## 10. Self-review notes

R1: only `GATE-SESSION-PAUSE` blocks (policy opt-in, integers). R2: no text stored, consumer and tokens keyed-hashed, leak scan 0. R3: no network. No new dependency. Errors are 400/404, never 500. ASCII CLI. Defaults off with a fingerprint test. Not done: console page (WP39), slow-attack window, id-churn defence (BACKLOG).
