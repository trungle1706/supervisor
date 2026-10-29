# Testing (WP-T1)

How to run the suite fast, how CI runs it, and where the time went. Numbers were measured on the
shared 16-core development host (load average 15 to 19 from other jobs), so they are upper bounds.

## Commands

| Need | Command |
|---|---|
| Daily run (skips `slow`) | `PYTHONPATH=src SUPERVISOR_ENV_FILE=/dev/null .venv/bin/python -m pytest tests -q -p no:cacheprovider -m "not slow" -n 6` (`make test-fast`) |
| Full run, before a release | same without `-m "not slow"` (`make test-full`) |
| CI (dedicated runner) | `... pytest tests -q -p no:cacheprovider -n auto --junitxml=reports/junit.xml` |
| Only what a change can affect | `pytest --testmon -n 0` (see below) |
| Explicit list (fallback) | `pytest tests/<package> ...` for the packages you touched |
| One test, debugging | `pytest path::test -n 0` (no workers, plain traceback) |

* `-n 6` is the default for this host: it also runs production containers, so do not use `-n auto`
  here. `-n auto` is for CI and for a free machine.
* Results by run (8,942 tests): before WP-T1 about 70 minutes serial; after, see the table below.
* The `slow` marker is set in `tests/conftest.py` (`SLOW_PATH_PREFIXES`, `SLOW_FILE_PARTS`,
  `SLOW_NODEIDS`), not in each file, so a new test in these places is covered with no edit. Slow
  means: harness runs, end to end, perf, and the long assurance and redteam files. To make one more
  test slow, add its node id there.
* Do not mix `tests/test_schema.py` or `tests/test_o*_schema.py` with console or governance tests
  in one *serial* command (fixture artifact). With xdist each worker has its own process; the full
  run with `-n 6` and `-n auto` passed with them together.

## Release rule

A release tag (`vX.Y.Z`) needs a green run of the `tests` workflow
(`.github/workflows/tests.yml`) on the commit that is tagged. The workflow runs on pull requests,
on pushes to `main` and on tags `v*`. It uses no secret and must never get one: the suite is
offline (`SUPERVISOR_ENV_FILE=/dev/null`). Steps: `uv sync --frozen`, `ruff check`,
`python -m schema.generate --check`, `python -m supervisor.databricks.notebook --check`, the full
suite with `-n auto`, upload of the junit report.

## testmon

`pytest-testmon` is a dev dependency. It records which source files each test ran and re-runs only
the tests whose code changed.

```
pytest --testmon -n 0 -p no:cacheprovider   # first run builds .testmondata (about as slow as a full run)
pytest --testmon -n 0                       # later runs: only tests touched by your diff
```

Notes: testmon does not combine with xdist (`-n 0`). `.testmondata` is local and ignored by git; do
not copy it between worktrees. It does not see changes in non-Python files (YAML policies, DDL,
templates) reliably: when you change those, use the explicit targeted list of packages. The
explicit list stays the fallback and the rule for review before a commit
(see "Test scope per commit" in the hub rules).

## What makes the suite xdist-safe

* No fixed ports, files or `DATA_DIR`: every test works in its own `tmp_path` (the autouse
  `_clean_env` fixture in `tests/conftest.py` sets `DATA_DIR` and `SUPERVISOR_ENV_FILE` per test).
* Global state is per process. `tests/governance/conftest.py::mounted` adds routers to the global
  `app` and `restore_app` takes them off; each xdist worker is its own process with its own `app`.
* Caches (below) are module-level dicts, one per process. Nothing is shared between workers.

## Where the time went (measured before the change)

Subset `tests/console tests/governance tests/regkb tests/factory tests/detectors` (4,494 tests),
`-n 6`, `--durations`. Wall time 722 s. The top entries, with the cause and what was done:

| Time | Phase | Test or fixture | Cause | Action |
|---|---|---|---|---|
| 24.6 s | call | console `test_detectors_tab_reads_the_recorded_report` and `..._latency_and_the_indicative_marker` | `harness.run()` of the detectors, once per test | cached per process (`tests/_cache.py`) |
| 23.4 s | setup | console `test_wp39_harness` module fixture | activity harness | marked `slow` (file name has `harness`) |
| 22.6 s | call | detectors `test_injection_classifier_harness` | harness run | marked `slow` |
| 15 to 23 s | call | regkb `test_w2_change` (5 tests) and console `test_w2_change` (4) | RegKB load (24 MB of files) repeated | RegKB load cached by file content hash; files marked `slow` |
| 11.8 s | call | regkb `test_cli_refuses_a_mock_model...` | RegKB load, CLI | cache; marked `slow` |
| 10 s | call | console `test_grid_is_capped_at_50_rows`, `test_export_of_50000_rows_is_capped` | bulk data | marked `slow` |
| 3 to 5 s | setup | every test that uses `seeded` or `console` | `adapters` fixture: schema bootstrap (0.6 s alone) plus demo replay (0.9 s alone) per test; slower under load | seed once per process, copy per test (`tests/_seed.py`) |
| 91 s x 2 | call | databricks `test_real_factory_sends_bearer`, `..._close_hook_closes_session` (seen in the full run) | the SDK `Config(host=...)` asks an invalid host for OIDC metadata and retries a failing DNS lookup for 90 s | `_resolve_host_metadata` stubbed in a session fixture (`tests/conftest.py`) |
| 53 s | call | monitors `test_harness_is_deterministic_and_go` | harness | `slow` |
| 43 s | call | assurance `test_launch_runs_agent_packs_with_its_own_policy` | long launch | `slow` (file) |

Totals from the junit report of the first full run (after the first changes): 3,446 s of test time
over 6 workers; console 547 s, governance 506 s, gateway 230 s, detectors 214 s, databricks 187 s
(of which 183 s the host lookup), redteam 158 s, regkb 155 s, monitors 149 s, assurance 143 s,
onboard 143 s, e2e 111 s. Setup of the 243 fixtures over 1 s: 484 s; calls over 1 s: 1,350 s.

## What was done

1. `pytest-xdist` and `pytest-testmon` added to the dev group only (runtime unchanged; `uv.lock`
   updated; `requirements.txt` is unchanged and `tests/test_requirements_current.py` passes).
2. `tests/_seed.py`: the SQLite store is built once per process (bare, and with the demo replay);
   `adapters`, `gadapters` and `seeded` give each test a file copy in its own `tmp_path`. The
   fixture names and the behaviour are the same.
3. `tests/_cache.py`: RegKB load cached per process, key = sha256 of every file the loader reads
   plus the date. Tests that write overrides (`test_w2_change.py`, both) also clear it. The detector
   harness report used by the console tab tests is cached per process.
4. Databricks host lookup stubbed (session fixture).
5. `slow` marker via `tests/conftest.py`.
6. Flaky test fixed: see below.

## The flaky test

`tests/detectors/test_documents_gate.py::test_m1_on_pii_export_the_cut_document_fails_closed_but_the_call_is_scored`
failed under load. Cause: the gate gives each detector `limits.timeout_ms` (500 ms) of wall clock.
The test sends a 342,000-character document; on a busy host `dlp_vn` needed more than 500 ms and
was reported `timed_out` instead of `payload_too_large`, so the assertion on the reason
(`detail == "documents"`) failed. The test checks the cut, not the speed. Fix: the test builds
its gate from the committed config with `timeout_ms` raised to 60,000 (the maximum the config
accepts), so the deadline cannot be reached. The product code and the 500 ms default are not
changed; other tests that check the deadline are not affected.

## Results

| Run | Tests | Before | After |
|---|---|---|---|
| Full suite, serial | 8,942 | about 70 min | not repeated |
| Full suite, `-n 6` | 8,942 | not measured | 9 min 28 s (567 s of pytest time) |
| `-m "not slow"`, `-n 6` | 8,534 (408 deselected) | not measured | 7 min 36 s (455 s) |
| Subset (console, governance, regkb, factory, detectors), `-n 6` | 4,494 | 12 min 2 s | 4 min 44 s |
