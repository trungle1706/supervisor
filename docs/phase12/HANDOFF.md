# Handoff: continue the phase 12 build in a new session

For a new Claude session (cloud or local) that takes over the hub role when the current session
stops (for example out of credit). Everything a new session needs is in this repository on
GitHub (`trungle1706/supervisor`, branch `main`). Written 2026-10-28.

## 1. Where we are

* Released: v0.8.0 (phases 8, 9, 10). Tag and GitHub Release exist.
* Plan in progress: `docs/phase12/BUILD_PLAN_PHASE12.md` (phase 12A/B/C and phase 11). Owner
  decisions are in its section 0. Research notes in `docs/phase12/research/`.
* Design pages the owner approved (private artifacts of the owner; the plan file carries their
  content): the phase 12 plan page and the agent factory design page.
* State on 2026-10-29 (check `git log --oneline main` and `git branch -r | grep worktree-agent`):
  * Wave 1 merged: WP-F1 (90e7d8e), WP-C2, WP-C1 (c8dd9e5), WP-W0 (9f5e708); fixes 770d726, a781aab.
  * Wave 2 merged: WP-F4 (orchestrator), WP-G1 (guardian definitions), WP-W3 (internal documents),
    WP-F2 (factory UI and helper agents); fixes 7697618. Schema: 77 tables. RegKB: 39 instruments,
    618 obligations.
  * Wave 3 part one merged 2026-10-29: WP-C4 (portfolio, nav), WP-G2 (guardian benchmark),
    WP-C3 (nine-step workflow), WP-F3 (gate and promotion); fix 93dfdae. Schema: 79 tables.
  * Wave 3 part two merged 2026-10-29: WP-F5 (starter agents), WP-W1 (watcher and update
    package), WP-G4 (smart guardian), WP-G3 (shadow and promotion); main 322cd05. Schema: 83
    tables. Full suite after part one: 8,663 passed, 0 failed.
  * Last worker started 2026-10-29: WP-W2 (change to re-evaluation). After its merge: full
    suite, then release v0.9.0.
  * Merge lesson: every WP appends a table and a CHANGELOG entry, so a merge conflicts in
    schema/model.yaml, the two DDL files, the notebook and CHANGELOG.md. Keep both appends, take
    either side of the generated files, then regenerate; add new /v1/systems routers to the
    `mounted` fixture in tests/governance/conftest.py and new flag-mounted prefixes to
    FLAG_MOUNTED in tests/console/test_rbac_matrix.py; regenerate the ROLE-MATRIX block in
    docs/console.md with `rbac.matrix_markdown()` when permissions change. Check that the LAST
    column of the last table before a conflict region survived the merge (git drops it twice now).
* Next waves: see section 5 of the build plan ("Order and merge").

## 2. How the hub works

* One Sonnet worker per WP, in its own git worktree and branch, briefed with: `CLAUDE.md`, the WP
  section of the build plan, the research note it needs, the modules to read, what to deliver,
  the test command, the commit trailer. The worker runs targeted tests only and hands back a
  report (branch, commit, files, tests, open questions).
* The hub reviews the diff (`git diff --stat main..<branch>`, the risky files in full), merges
  with `git merge --no-ff`, runs the WP tests plus `tests/test_architecture.py` and
  `tests/test_no_secrets.py` on main, `ruff check src tests`, pushes.
* Schema merges: two WPs may both append tables to `schema/model.yaml`. Keep both appends, then
  `python -m schema.generate` and `python -m supervisor.databricks.notebook`, both with `--check`
  after. Never hand-merge the DDL files.
* Full suite once per release: `PYTHONPATH=src SUPERVISOR_ENV_FILE=/dev/null .venv/bin/python -m
  pytest tests -q -p no:cacheprovider` (about 60 minutes, 7,600+ tests). One known load-only
  failure: `tests/detectors/test_documents_gate.py::test_m1_...` passes alone.
* Do not mix `tests/test_schema.py` or `tests/test_o*_schema.py` with console or governance
  tests in one pytest command (fixture artifact); run them apart.
* Commit trailer on every commit:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: <the session URL>`.

## 3. Review checklist per WP (the house rules, from `CLAUDE.md`)

1. Flag off by default; an off-path test exists; routes answer 400 `<flag>_off`.
2. HTTP 400 never 500 on bad input.
3. Only deterministic rules block or pause; a model drafts or advises.
4. Evidence chain and reports: no personal data, no floats (integers and enums only).
5. No `exec`, `eval`, `subprocess` outside `sandbox.py`; dev-host tools under `tools/` only.
6. Synthetic Vietnamese data only; `FILL-ME` placeholders for workspace values; no secret,
   token or `.env` content in any file or log.
7. Schema change by appending to `schema/model.yaml` and regenerating.
8. Docs updated (`docs/<feature>.md`), `CHANGELOG.md` entry under `## Unreleased`, i18n keys
   for new UI strings, `app.yaml` commented flag entry.

## 4. Release steps (when a wave closes)

1. Bump `src/supervisor/__init__.py` `__version__`; rename `## Unreleased` in `CHANGELOG.md` to
   `## vX.Y.Z (<scope>) - <date>`.
2. Full suite; commit; `git tag -a vX.Y.Z`; push main and the tag.
3. `python -m supervisor.cli release --bundles --out ~/supervisor-release/vX.Y.Z --ref vX.Y.Z`
   builds the laptop and Databricks zips. The Databricks zip needs the offline wheels folder
   added (see `docs/deploy/LAUNCH_DATABRICKS.md`). Render the bootstrap SQL from
   `schema/ddl/databricks.sql` with the catalog and schema values.
4. The owner creates the GitHub Release with `gh release create` (a session cannot).
5. The filled config (real workspace values) is made only on the owner's machine and never
   committed.

## 5. Things only the owner's machine has

* Local worktrees of running workers: `/home/trung/supervisor/.claude/worktrees/agent-<id>`.
  To put their branches on GitHub so a cloud session can merge them, the owner runs on the
  machine:
  `cd ~/supervisor && for b in $(git branch --list "worktree-agent-*" | tr -d ' *'); do git push -q origin "$b" && echo "pushed $b"; done`
  (pushes every worker branch, including old ones; harmless).
* The demo console on port 8130 (env `~/supervisor-testbed/phase3/console/phase8.env`) and the
  Cloudflare quick tunnel; the testbed candidates under `~/supervisor-testbed/candidates/`; the
  release folders under `~/supervisor-release/`; the Databricks CLI profile `sb`.
* Real model keys in `~/supervisor/.env` (never read, copied or printed by a session).
* The session memory file for local sessions:
  `~/.claude/projects/-home-trung/memory/project-platform-direction.md`.

## 6. What a cloud session can and cannot do

* Can: read the plan, brief workers, review and merge branches that are on GitHub, run targeted
  tests and the full suite (install with `uv sync --frozen` or `pip install -e .[dev]` from
  `pyproject.toml`; Python 3.11), write docs, tag releases.
* Cannot: reach the owner's machine, the Databricks workspace, the demo console, or the real
  model gateway. Model-using features run in tests with the mock adapter only; a live check waits
  for a local session.

## 7. Next actions in order

1. Merge the WP-W2 branch on GitHub with the merge lesson above.
2. Nothing else to start in phase 12; the plan's section 5 is complete after W2.
3. Full suite, then release v0.9.0 (section 4).
4. Report to the owner in the controlled style (short sentences, tables, diagrams; see the
   owner's `ste-communication` skill note in the memory file when local).
