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
* Wave 1 state (check `git log --oneline main` and the open branches):
  * WP-F1 factory schemas: **merged** (90e7d8e).
  * WP-C1 classification tree, WP-C2 risk dimensions, WP-W0 regulations completeness: workers
    were running in local worktrees when this file was written. Their branches are named
    `worktree-agent-<id>`. If the branches are on GitHub (`git branch -r | grep worktree-agent`)
    review and merge them (section 3). If they are not on GitHub, the work exists only on the
    owner's machine; the owner pushes them with the command in section 5, or the WP is rebuilt
    from its brief.
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

1. Merge any wave 1 branch on GitHub (C1, C2, W0). Resolve the double append in
   `schema/model.yaml` by keeping both tables and regenerating.
2. Start wave 2 from the build plan: WP-F2 (factory UI, helper agents), then WP-F3 (gate and
   promotion, with the simulation review and the sample batch of owner decision 5), WP-F4
   (orchestrator), WP-G1 → G2 → G3 (guardian factory), WP-W3 (internal documents through the
   gateway). Brief each worker as section 2 says.
3. Wave 3: WP-C3, WP-C4, WP-F5, WP-G4, WP-W1 → W2. Then release v0.9.0.
4. Report to the owner in the controlled style (short sentences, tables, diagrams; see the
   owner's `ste-communication` skill note in the memory file when local).
