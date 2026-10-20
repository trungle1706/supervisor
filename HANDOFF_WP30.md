# HANDOFF WP30: Control catalogue and task list

Branch `wp30-controls`, from `wp29-risk-register` (merged twice: the review head `222a170`, then the
final head `5c0d887`). No push, no merge into main. Flags are off by default.
Docs: `docs/controls.md`. ADR: `docs/adr/D30-control-catalogue-tasks.md` (D26 was the highest on this
branch; the prompt asked for D30).

## What was built

```
 obligation / risk --covers--> CONTROL <--evidence-- rule | pack | monitor (runtime)  detector | document (reference)
 status per control and agent = working | failing | no_data   (same collector as WP29: enforced_hit etc.)
 compliance bp per agent = working / in scope (integer; None when nothing is in scope)
 tasks: stage by stage, sized by max(WP29 band, Decision 33 class floor); the move is a task and a gate
 Launch: NO-GO while a required task of the stage is open (TASKS_LAUNCH_GATE_ENABLED)
```

| Item | Where |
|---|---|
| Tables `control`, `control_map`, `control_status` (append-only), `task`, `task_event` (append-only) | `schema/model.yaml`, both DDLs, notebook (generated, current) |
| Model, reference catalogue, evidence status, service, API, CLI | `src/supervisor/controls/` (`model`, `refs`, `evidence`, `service`, `api`, `__main__`, `harness`, `harness_env`) |
| Templates, sizing, state machine, service, API, CLI | `src/supervisor/tasks/`, `config/tasks.yaml` (ILLUSTRATIVE) |
| Starter catalogue: 28 controls (24 active, 4 draft) mapped to real obligation ids, the 19 WP29 starter risks, rules, packs, monitors, detectors | `config/controls/*.yaml` |
| `control` as a WP29 link kind | `risk/model.py` (`LINK_KINDS`, `CONTROL_KINDS`), `risk/evidence.py` (`Collector.control_sources`), `risk/refs.py` (catalogue), `risk/service.py` (`collector()`, `control_links()` adds the map fingerprint to the evidence basis) |
| Routes `/v1/controls...`, `/v1/tasks...` | RBAC `controls.view|edit`, `tasks.view|edit|approve`; audited like `/v1/risks` |
| Console pages `/console/controls`, `/console/tasks`; Agent tabs Controls and Tasks (existing components, no CSS) | `console/controls_views.py`, `tasks_views.py`, 8 templates, nav, i18n EN and VI |
| Jobs `python -m supervisor.jobs.control_status`, `python -m supervisor.jobs.task_due` | scheduler lists them only when `CONTROLS_ENABLED` |
| CLIs `python -m supervisor.controls list|import|status|export`, `python -m supervisor.tasks list|plan|generate|done|waive` | `--by USER` required for every write |
| Launch hook | `assurance/gates.py::task_launch_items`, `onboard/launch.py::_with_tasks`, `LaunchReport.tasks_enabled/task_reasons` |
| Harness: 50 golden (30 dev, 20 held-out), 24 adversarial probes, starter consistency, determinism, baseline | `controls/harness.py`, `tests/fixtures/controls/`, `tests/controls/test_harness.py` |

Rules applied from the WP29 review: only enforced hits (`enforced_hit` through `Collector.count`, no own filter); monitors `fairness`, `drift`, `multiagent` only; judge-scored packs are references unless `RISK_EVIDENCE_JUDGED_PACKS=1`; pack window 30 days (`CONTROLS_PACK_WINDOW_DAYS`) vs 7 for rules and monitors; a change to a control (status, agents, map) makes its stored status read `no_data / changed_since_evidence` and changes the evidence basis of linked risks; chain payloads carry `actor_ref` (keyed hash) only; the harness starter row fails an active product control with only reference sources.

## Flags and settings

| Variable | Default | Effect |
|---|---|---|
| `CONTROLS_ENABLED` | `0` | `/v1/controls`, `/v1/tasks`, scheduler jobs, CLIs. Off: routes answer 400, tables stay empty |
| `CONSOLE_CONTROLS_ENABLED` | `0` | Controls and Tasks pages and Agent tabs (needs the first flag) |
| `TASKS_LAUNCH_GATE_ENABLED` | `0` | Launch NO-GO while a required task of the stage is open (needs the first flag) |
| `SCHED_CONTROL_STATUS_S`, `SCHED_TASK_DUE_S` | `21600`, `3600` | Job intervals |
| `CONTROLS_PACK_WINDOW_DAYS` | `30` | Pack result window as control evidence |
| `CONTROLS_STARTER_DIR`, `TASKS_CONFIG` | `config/controls`, `config/tasks.yaml` | Paths |

On Delta run `python -m supervisor.jobs.bootstrap_schema` first (five new tables).

## Commands (last lines)

```
uv sync
uv run python -m pytest -q
  4027 passed, 29 skipped, 1 warning in 592.62s (0:09:52)       (WP29 final head merged; before my last doc/notebook touch-up)
uv run python -m ruff check            All checks passed!
uv run python -m ruff format --check   720 files already formatted
uv run python -m supervisor.controls.harness
  [dev] n=30 accuracy=10000bp [8864, 10000]   [held_out] n=20 accuracy=10000bp [8388, 10000]
  [adversarial] 24/24 [8620, 10000] failed=[]   [starters] controls=28 maps=165 risks_covered=19 obligations_covered=26 problems=[]
  [determinism] 10000bp   [OK] all GO
uv run python tests/fixtures/controls/generate.py --check     (exit 0)
set CONTROLS_ENABLED=1
python -m supervisor.risk import config\risks --by you --source starter
python -m supervisor.controls import config\controls --by you --source starter
python -m supervisor.jobs.control_status
python -m supervisor.tasks generate --agent payments --by you
```

## Test counts

| | Passed | Skipped |
|---|---|---|
| Before (WP29 head as first branched, per HANDOFF_WP29) | 3,829 | 29 |
| Before (WP29 final head, per its review: 3,881 plus later follow-ups) | about 3,881 or more | 29 |
| After (this branch) | **4,027** | 29 |

New in WP30: about 120 tests (`tests/controls/` 71 plus the review-semantics and harness tests, `tests/tasks/` 31, `tests/console/test_controls.py` 7, Delta 6, CLI/job/launch 9). Existing tests changed (additive): `tests/test_rbac.py` (viewer set), `tests/console/test_rbac_matrix.py` (new path params and JSON paths), `tests/console/test_agent_detail.py` (flag in the all-on list). A first full run failed once on the notebook being stale after a merge; regenerated (`python -m supervisor.databricks.notebook`).

## Harness result (rubrics: compliance officer, internal auditor under the Three Lines model)

Golden dev 30 and held-out 20: 100%, Wilson 95% [88.6%, 100%] and [83.9%, 100%] (small n, wide). Adversarial 24 of 24. Starters: 0 problems. Determinism equal hash. Mutation check by hand (mutate, run harness tests, revert): move gate disabled, a document counted as working, same-person waiver allowed: each caught by `tests/controls/test_harness.py`. The expected values come from an independent reference (`generate.py`) but the same author wrote both; the `plan` scenarios are tied to the illustrative `config/tasks.yaml` (baseline stores its hash).

## Files touched outside the packages (all additive)

`src/supervisor/config.py` (block `# --- WP30 ---`, 2 path validators); `app.py` (2 routers); `core/rbac.py` (5 permissions, routes); `adapters/auth/audit.py` and `authz.py` (target kinds `control`, `task`; denied POST audit for `/v1/controls`, `/v1/tasks`); `ops/openapi.py`; `console/context.py` (`controls`, `tasks`); `console/routes.py` (generic page registration for two pages); `console/nav.py`; `console/agent_detail.py`; `console/i18n.py` (block with noqa on long VI strings); `console/templates/agent.html`; `scheduler.py` (two jobs, only when on); `cases/service.py` (`NO_CLOCK_SOURCES` gets `task`); `onboard/launch.py`, `onboard/models.py`, `assurance/gates.py` (launch hook); WP29 files `risk/model.py`, `risk/evidence.py`, `risk/refs.py`, `risk/service.py` (the documented extension points only: link kind, `control_sources`, catalogue, evidence basis); `docs/console.md` (matrix regenerated, rows), `docs/index.md`, `docs/threat-model.md` (3.11), `README.md`, `BACKLOG.md`, `CHANGELOG.md`; `schema/*`, `notebooks/bootstrap_and_smoke.py`. Merge conflict met once, in `risk/service.py::collector()` (kept both the judged-pack argument and `control_sources`).

## Extension points for WP31 (transparency report)

`ControlService.agent_compliance(agent_id)` (controls in scope, status, bp, product and bank split), `obligation_coverage(agent_id)`, `export_json()`, `uncovered_risks()`; `TaskService.agent_summary(agent_id)`, `export_json()`, `preview(class, band)`; chain record types `control_change`, `control_status`, `task_change`, `task_resize`.

## Not done (BACKLOG rows added)

Four draft starters need a deterministic source; bank controls cannot show working (attestation record with a second person); the matrix applicability join (gaps list); console forms and a waiver inbox; four-eyes for control changes; re-evaluation triggers; "controls working" tile on the Compliance page (left to WP31); live Databricks run (mirror fake only).

## Open questions for the owner

1. Real task sets, levels, class floors and due times (`config/tasks.yaml` is a sketch). Who answers a waiver and a high-level stage move: now approver or admin.
2. Should an agent with no task list be NO-GO at launch? Now a note, to avoid blocking agents that predate WP30.
3. Pack window 30 days and "one working source is enough": keep?
4. How should bank-owned controls count in the figure? Now: in the figure, shown apart (`product_bp`, `bank_in_scope`), never working.
5. Starter controls draft until a source exists (oversight, chain, quality, groundedness): build deterministic monitors, or accept judge-scored packs with `RISK_EVIDENCE_JUDGED_PACKS=1`?
6. The CLI trusts `--by`; the task waiver answer exists only on the route. Is that enough for the bank, or should CLI writes need a signed identity?
7. ADR number D30 as asked; check for a clash at merge.
