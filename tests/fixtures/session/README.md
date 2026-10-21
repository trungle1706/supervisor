# tests/fixtures/session

`redteam_traces.jsonl` is a sample of the WP28 multi-turn red team `traces.jsonl` (branch
`wp28-redteam-multiturn`, template path, mock agent, seed 20261020, 2 trials per objective, both
languages): 47 conversations, 6 families, successful, failed and benign look-alike sessions. All
text is synthetic; long digit runs are masked by the WP28 writer. Source and licence: own,
labeller "synthetic". Used by `tests/monitors/test_session_harness.py` and by the session harness
(`python -m supervisor.monitors.session_harness --redteam PATH`).

Reproduce (review WP27): in a checkout of `wp28-redteam-multiturn`, run
`python -m supervisor.redteam.multiturn run --trials 2 --lang both --attacker template --judge none --seed 20261020 --out <dir>`
and take a sample of `<dir>/traces.jsonl` (the fixture keeps 47 rows: four successful and up to two
failed attacks per family, two benign look-alikes per family). The WP28 run is
deterministic for one seed; the sample selection is by hand, so the file is the record. It is mostly
the WP28 **dev** split, which the author of the monitor read: it is not a blind set. The blind check
is the WP28 held-out split (`--split heldout`), reported in `docs/session-monitor-validation-report.md`.
