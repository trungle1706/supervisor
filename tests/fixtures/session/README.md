# tests/fixtures/session

`redteam_traces.jsonl` is a sample of the WP28 multi-turn red team `traces.jsonl` (branch
`wp28-redteam-multiturn`, template path, mock agent, seed 20261020, 2 trials per objective, both
languages): 47 conversations, 6 families, successful, failed and benign look-alike sessions. All
text is synthetic; long digit runs are masked by the WP28 writer. Source and licence: own,
labeller "synthetic". Used by `tests/monitors/test_session_redteam.py` and by the session harness
(`python -m supervisor.monitors.session_harness --redteam PATH`).
