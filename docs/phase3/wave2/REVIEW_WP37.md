# REVIEW WP37: Verdict contract v2 and detector framework

Reviewer: Opus (bank security reviewer and model-risk validator view). Branch
`wp37-verdict-detectors`, reviewed at `a84351a`, review fixes `ca15ce3..0982989` (5 commits, all
additive). Nothing pushed, merged or rewritten. No `.env` created.

## 1. Verdict

**APPROVED WITH FOLLOW-UPS.** Two High findings (R1 and availability) and three Medium findings
were fixed on the branch, with tests that fail without the fix. The open items are Low and have
BACKLOG rows or an owner question.

## 2. Findings

| Id | Sev | File:line (after fix) | What | Fix |
|---|---|---|---|---|
| F1 | High | `src/supervisor/core/detectors.py:588`, `:748-754`; `src/supervisor/detectors/config.py:147` | R1. `judge_advisory` could fail closed: `fail_closed: true` in `config/detectors.yaml` was honoured, so a judge outage made a money, credit or pii_export call `GATE-DETECTOR-FAILED`. The handoff and docs said it was excluded; only the shipped YAML value prevented it, and the test used `fail_closed=False` | `ca15ce3`: `DetectorRegistry.may_fail_closed` returns False for category `advisory` (also in the `*` content-uninspectable path); the loader clamps it and logs a warning |
| F2 | High | `src/supervisor/core/detectors.py:95` (`_call_bounded`), `:694-706` | A hung detector ran on the gate worker. The money answer still came back at the 2 s `HARD_TIMEOUT_S` (fail mode), but the worker stayed held: after 8 hung calls every decision for every agent fell to the fail mode, and fail-open tools lost rule evaluation. Measured: 6 money calls on 2 workers took 12.0 s | `ca15ce3`: each detector call runs in a daemon thread with a `limits.timeout_ms` deadline; `timed_out` (detail `deadline`). At most 32 calls in flight; with no free slot the detector is not started and is `timed_out` (`no free detector slot`). Same test now: 6 calls well under 1 s each, `GATE-DETECTOR-FAILED` on money, read_only allowed |
| F3 | Medium | `src/supervisor/detectors/dlp_vn.py:58` | R2. The dlp transform masked values only. A name used as a dict key went in clear to the pii_export tool in `transformed_payload` and `transformed_args` (probe: `{"by_name": {"NGUYEN VAN THU": ...}}`) | `c32a488`: `_mask_tree` masks string keys too |
| F4 | Medium | `tests/detectors/test_persistence.py:54` | The "no raw text in the Delta statement" check read the SQL text only. Values travel as typed parameters, so the check could not fail | `f40cf8c`: new test sends the finding, agent_event and verdict rows of a nested and an output-direction call through the Delta fake and searches every call's parameters |
| F5 | Medium | `src/supervisor/wiring.py:184-196`; `src/supervisor/preflight.py:244` | A bad `config/detectors.yaml` gave a chained traceback, and the message could hold non-ASCII text; preflight did not check the file | `475d1ba`: one ASCII line that names `DETECTORS_CONFIG`, no chained cause; preflight `[FAIL] detectors` (no line with the flag off). Note: `app.py` lifespan still logs the build failure with `log.exception` (existing behaviour for every config error; `app.py` not touched) |
| F6 | Low | `src/supervisor/core/detectors.py:794` | `derive_status` returned `skip` for a `skip_tools` call that WP24b redacted, so the status hid a changed payload | `ca15ce3`: transform wins over skip. **Contract semantics change, see section 3** |
| F7 | Low | `src/supervisor/gateway/detector_gate.py:211` | A `GATE-DETECTOR-FAILED` block kept the WP24b `transformed_args` in the answer and the records | `c32a488`: cleared on that block |
| F8 | Low | `config/detectors.yaml`, `docs/adr/D23...md:77`, `docs/detectors.md`, `CHANGELOG.md` | Config comment named `/v1/detectors` (route is `/v1/gate/detectors`); docs described the old timeout; no CHANGELOG line under Unreleased | `0982989` |
| F9 | Low | `tests/detectors/` | Missing tests: R1 matrix over every hint and risk class, credit tool, skip with transform, SQLite additive migration of the WP37 columns, nested PII, output-direction PII in SIEM / OCSF / logs | `f40cf8c` (16 tests in `tests/detectors/test_review_wp37.py`) |
| F10 | Low | `src/supervisor/core/detectors.py:477` (`walk_leaves`) | Detectors read string leaves only: a phone or CCCD sent as a JSON number is not detected (the stored `args_masked` is still masked) | open, BACKLOG row added |
| F11 | Low | `src/supervisor/wiring.py:190` | Agent overrides are checked at start-up only; after a policy reload a bad override shows as `invalid_config` and fails closed on money / credit / pii_export (safe, but surprising) | open, BACKLOG row added |
| F12 | Low | `src/supervisor/recorder/normalise.py:566` | The recorder copies span attribute `supervisor.gate.correlation_id` into `agent_event.correlation_id` with the flag off too. Any OTLP sender can set it; the value is sanitised by `_ident`; the gate path and the fingerprint are not affected | open (recommend: only when `DETECTORS_ENABLED=1`; WP38 owns the SDK side) |
| F13 | Low | `src/supervisor/detectors/harness.py:55`, `data/eval/detectors/` | Harness honesty: thresholds, golden set and harness came in one commit (`991a808`), so "thresholds before the run" cannot be shown from git (the claim is plausible: no threshold changed after). Adversarial n is small (dlp 12 positives, injection 17, judge 3) and dlp adversarial recall 5000 bp sits exactly on its threshold (Wilson about [2540, 7460]): weak evidence | open: owner should read the adversarial GO rows as indicative only |
| F14 | Low | `src/supervisor/gateway/detector_gate.py:128` | `skip_tools` may name a money or credit tool; that also switches off `GATE-DETECTOR-FAILED` for it. It is a policy value (git, deploy), but it has no extra approval | open, owner question 6 |

Checks that passed without change:

* R1 by reading and by test: the only decision changes are `GATE-DETECTOR-FAILED` (allowed, non-shadow, non-builtin call; fail-closed detector; risk class in the list) and the dlp transform on an allowed call. Hints `pause` / `block` count as `report`. Matrix test: a detector firing at 10000 bp with each hint on read_only, money, pii_export, credit and an unknown agent leaves `allow`, `action`, `rule_id` exactly as flag off. Precedence: block > pause > transform > report > allow; skip never hides a block or a pause (tested, including skip plus a deterministic block and a pause rule plus a block rule).
* R2: answer, `finding`, `agent_event`, `verdict`, chain payloads, SIEM / OCSF events, logs (DEBUG capture) and Delta parameters hold no raw name, phone, CCCD or e-mail for PII nested 4 levels deep in `args`, in `context.tool_results`, and in an output-direction object. Fragments are tokens on the masked text; exception text is never copied. The judge prompt is masked by `judge/prompts/build.py`.
* Flag off byte for byte: the fingerprint test passes on the branch and on a fresh `git archive v0.3.0` export (outside the worktree) with the same test file: the recorded value comes from v0.3.0 code. `direction: output` with the flag off is HTTP 400 (`tests/detectors/test_routes.py:107`). SDK and MCP proxy tests pass unchanged in the full suite.
* Fail mode and timing: the gate's `HARD_TIMEOUT_S` (2 s) was respected before the fix too (the detector pass runs inside `_decide` on the gate pool); F2 was about holding workers.
* Settings and policy: per-agent precedence matches `detectors/config.py` docstring and `docs/detectors.md` section 3; `policy_hash` unchanged without the override and changed with it (test).
* Both modes: DDL parity is enforced by `tests/test_schema.py` and the notebook test; `bootstrap_schema` adds the three columns and the `finding` table to a v0.3.0-like SQLite file and keeps the old row (new test).
* Harness: baseline file with date and commit, `--check` passes, `compare` fails on a drop (test), Wilson intervals, adversarial probes as a separate row, MockJudge numbers labelled "prove the harness only".
* Shared files: `engine.py` edits are additive and behind `detector_gate is not None`; `_evaluate` has two callers, both in `engine.py`, both updated; `check` / `evaluate_only` take new keyword-only arguments, so positional callers (SDK, MCP proxy, console Playground) are unchanged. `routes.py`, `policy.py`, both `wiring.py`, `rbac.py`, `models.py`, `normalise.py`, `runtime.py`, `tracing.py`, `siem.py`, `pyproject.toml`, `tests/test_retention.py`: minimal and correct.

## 3. Did the contract change?

**Yes, four small semantic changes; no field added, removed or renamed.** WP25, WP38 and WP27
authors: read this.

| Change | Before | After | Who cares |
|---|---|---|---|
| `status` for a `skip_tools` call that WP24b redacted | `skip` | `transform` | WP38 (SDK reads `status`), WP39 |
| Detector category `advisory` and `fail_closed` | honoured from YAML | always false (warning logged) | **WP25**: do not give the classifier category `advisory` if it must fail closed on money tools |
| `timed_out` entries | only after the detector returned | also on a deadline miss (`detail: deadline`) or no free slot (`detail: no free detector slot`) | WP39 console, WP21 alert "Detector failed open" |
| dlp `transformed_payload` / `transformed_args` | dict keys as sent | string dict keys masked (shape: key names may change) | WP38 SDK, MCP proxy |

`Detector` protocol, `Finding`, `RunConfig`, `RunResult`, the HTTP fields and the table columns are unchanged.

## 4. Commands (last lines)

```
$ uv run python -m pytest -q -x -p no:cacheprovider          # before the fixes (a84351a)
3800 passed, 29 skipped, 1 warning in 499.97s (0:08:19)
$ uv run python -m pytest -q -x -p no:cacheprovider          # after the fixes (0982989)
3816 passed, 29 skipped, 1 warning in 486.30s (0:08:06)
$ uv run python -m ruff check
All checks passed!
$ uv run python -m ruff format --check
683 files already formatted
$ uv run python -m supervisor.detectors.harness --check
OVERALL: GO
[OK] no drop below the baseline
$ (v0.3.0 export) python -m pytest tests/detectors/test_flag_off_fingerprint.py
1 passed in 0.16s
$ hung-detector test with the bound patched out
AssertionError: 12.008734421018744 < 6.0   (with the bound: passes)
```

Final test count: 3816 passed, 29 skipped (131 in `tests/detectors/`: 115 from the author, 16 from the review).
The one warning is present before the fixes too.

## 5. Owner questions: recommendation per question

| # | Question | Recommendation |
|---|---|---|
| 1 | `verdict_status` on `agent_event` or a separate `gate_decision` table | Keep `verdict_status` on `agent_event`. One decision row, no copy to keep in step, nullable for old rows. Rename only if WP39 needs it |
| 2 | Real judge inline | No, not inline. Keep `judge_advisory` off in the hot path; add an async path that attaches the finding later by `correlation_id`. An inline real judge needs an MRM record and a latency budget first |
| 3 | Presets and `urgent_transfer` at `balanced` | Accept as illustrative defaults for 1.0.0. Keep `urgent_transfer` below `balanced` (it fires at `strict`); changing it needs a version bump. Revisit with bank data in WP25; in the meantime an alert rule on the code is cheaper than a lower threshold |
| 4 | Which risk classes fail closed | Keep money, credit, pii_export. Do not add read_only: a detector outage would block every read. Handle personal data in read_only outputs with an output-direction report plus the WP39 "PII leaked" alert |
| 5 | Correlation id from the SDK | Yes: the SDK generates it before the span starts (WP38); the gate keeps generating one when the header is missing |
| 6 | `skip` as a rule action | Yes, later, with two approvers like block and pause. Until then: refuse `skip_tools` for money, credit and pii_export tools in the policy loader (F14), so a skip can never switch off fail-closed protection |
| 7 | `finding` retention class `masked` | Confirm: same days as `agent_event.args_masked` (same kind of data: masked tokens and fragments) |

## 6. Files changed by the review

`src/supervisor/core/detectors.py`, `src/supervisor/detectors/config.py`,
`src/supervisor/detectors/dlp_vn.py`, `src/supervisor/gateway/detector_gate.py`,
`src/supervisor/wiring.py`, `src/supervisor/preflight.py` (shared: one new check, only with the
flag on), `tests/detectors/test_review_wp37.py` (new), `docs/detectors.md`,
`docs/adr/D23-verdict-contract-v2.md`, `BACKLOG.md`, `CHANGELOG.md`, `config/detectors.yaml`
(comments only), `REVIEW_WP37.md` (this file).
