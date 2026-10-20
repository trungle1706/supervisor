# HANDOFF WP29: Risk register

Branch `wp29-risk-register`, from tag `v0.3.0` (`3aed7f9`). Five commits. No push, no merge.
Flags are off by default. Docs: `docs/risk-register.md`. ADR: `docs/adr/D26-risk-register.md`.

## What was built

```
 inventory graph (WP24) --reuse--> risk/inherit.py --> agent level = max over reached risks
 Risk --link--> matrix row | gate rule | assurance pack | monitor | case
 gate verdicts + pack results + monitor status --> risk/evidence.py --> risk_evidence row + chain record
 evidence rule: residual = declared value ONLY while no control fails and >= 1 works; else inherent score
```

| Item | Where |
|---|---|
| Tables `risk`, `risk_link`, `risk_evidence` (append-only) | `schema/model.yaml`, both DDLs (generator current), notebook regenerated |
| Model, scoring (integers), bands (ILLUSTRATIVE, `config/risk.yaml`), validation | `src/supervisor/risk/model.py` |
| Inheritance (reuses `Graph.effective_risk`; no second SCC) | `risk/inherit.py` |
| Evidence collector and the rule | `risk/evidence.py` |
| Link target catalogue (rule, obligation, pack, monitor, case must exist today) | `risk/refs.py` |
| Service: CRUD, links, import, export, evidence pass, `agent_summary` | `risk/service.py` |
| Routes `/v1/risks` (list, get, create, update, link, evidence, by agent) | `risk/api.py` |
| Job `python -m supervisor.jobs.risk_evidence`; scheduler job `risk_evidence` (listed only when the flag is on) | `jobs/risk_evidence.py`, `scheduler.py` |
| CLI `python -m supervisor.risk list\|import\|score\|export` (ASCII, JSON and CSV) | `risk/__main__.py` |
| Console: Risks page, row drawer (Details, Links, Evidence trend), Agent tab "Risks" | `console/risks_views.py`, 4 templates, routes, nav, i18n EN and VI |
| 19 starter risks (6 payments, 6 credit decision = `credit_prequal`, 5 customer service, 2 on the shared endpoint `qwen3:4b`) | `config/risks/*.yaml` |
| Harness: 50 golden scenarios (30 dev, 20 held-out), 20 adversarial probes, starter consistency check, determinism, baseline | `risk/harness.py`, `tests/fixtures/risk/`, `tests/risk/test_harness.py` |
| RBAC: `risks.view` (all roles), `risks.edit` (reviewer, owner, admin); two `console_action` rows and a `risk_change` chain record per edit | `core/rbac.py`, `risk/api.py` |

Evidence counts, per linked control and per window (7 days, ending at the last full hour): gate rule hits (tier-0, non-advisory), non-mock pack verdicts, monitor status. SHADOW, RETIRED and unknown agents are excluded. Payloads hold integers, fixed reason codes and hashes only (R2). No judge is an input (R1). No network (R3).

## Flags and settings

| Variable | Default | Effect |
|---|---|---|
| `RISK_REGISTER_ENABLED` | `0` | `/v1/risks`, scheduler job, CLI. Off: routes answer HTTP 400, tables stay empty |
| `CONSOLE_RISKS_ENABLED` | `0` | Risks page and Agent tab (needs the first flag too) |
| `SCHED_RISK_EVIDENCE_S` | `21600` | Evidence pass interval |
| `RISK_EVIDENCE_WINDOW_DAYS` | `7` | Window length |
| `RISK_CONFIG`, `RISK_STARTER_DIR` | `config/risk.yaml`, `config/risks` | Thresholds and starter folder |

On Delta run `python -m supervisor.jobs.bootstrap_schema` first (three new tables).

## Commands (and last lines)

```
uv sync
uv run python -m pytest -q
  3829 passed, 29 skipped, 1 warning in 491.67s (0:08:11)
uv run python -m ruff check
  All checks passed!
uv run python -m ruff format --check
  684 files already formatted
uv run python -m supervisor.risk.harness
  [dev] n=30 accuracy=10000bp [8864, 10000] ...   [held_out] n=20 accuracy=10000bp [8388, 10000] ...
  [adversarial] 20/20 [8388, 10000] failed=[]      [starters] risks=19 links=85 problems=[]
  [determinism] 10000bp                            [OK] all GO
uv run python tests/fixtures/risk/generate.py --check      (exit 0 when golden.jsonl is current)
set RISK_REGISTER_ENABLED=1
python -m supervisor.risk import config\risks --source starter
python -m supervisor.risk list --agent payments --band critical
python -m supervisor.jobs.risk_evidence
```

## Test counts

| | Passed | Skipped |
|---|---|---|
| Before (v0.3.0; brief and CHANGELOG say 3,684 and 29; another agent measured 3,686 and 27) | 3,684 to 3,686 | 27 to 29 |
| After (this branch, last full run) | **3,829** | 29 |

New: 135 tests (`tests/risk/` 109, `tests/console/test_risks.py` 26), plus 10 parametrized cases that the existing RBAC matrix test adds by itself for the new routes. I did not get a clean own baseline run on v0.3.0: my first baseline log was overwritten by another agent, because all agents share one scratchpad directory and some used the same file name (`full1.txt`). My own final runs write `wp29_full_*.txt`. One full run showed `tests/integrations/test_integrations.py::test_chain_feed_writes_schema_events_once` failing; it passed alone 9 times and in the next two full runs. I think it is a flake (it greps the SIEM stream for 9 to 12 digit runs). I did not find the cause.

## Harness result (expert view: operational risk manager, internal auditor under the Three Lines model)

| Row | Result |
|---|---|
| Golden dev 30 and held-out 20 | 100%; Wilson 95% [88.6%, 100%] and [83.9%, 100%] (small n, wide interval) |
| Adversarial 20 | 20 of 20 |
| Starter consistency | 19 risks, 85 links, 0 problems (every rule, obligation, pack and monitor exists; rules are in scope for the agent) |
| Determinism | equal hash |
| Mutation check (done by hand, not committed) | a SHADOW agent counted as supervised, a shifted band threshold and an evidence rule that ignores failing controls were each caught |

The expected values of the golden set come from an independent reference implementation (`tests/fixtures/risk/generate.py`), but both were written by the same author. The scenarios show the code does what the rubric says; they do not show the rubric is right. Thresholds are ILLUSTRATIVE.

## Files touched outside the package (shared files, all additive)

| File | Change |
|---|---|
| `src/supervisor/config.py` | Block `# --- WP29 ---` (6 settings) and 2 path validators |
| `src/supervisor/app.py` | Import and `include_router(risk_router)` |
| `src/supervisor/core/rbac.py` | Permissions `risks.view`, `risks.edit`; 10 ROUTES entries |
| `src/supervisor/adapters/auth/audit.py` | Target kind `risk` (param `risk_id`, template `/v1/risks`, snapshot hash of risk plus links) |
| `src/supervisor/adapters/auth/authz.py` | A denied POST under `/v1/risks` is audited like `/console` |
| `src/supervisor/console/context.py` | Property `risks` (RiskService with the chain writer) |
| `src/supervisor/console/routes.py` | 3 GET routes, `_risks_off`, `_UX3_FLAGS` entry, imports |
| `src/supervisor/console/nav.py` | `PAGES["risks"]`, nav item in group Prove, code `RK` |
| `src/supervisor/console/agent_detail.py` | Tab `risks` (TABS, GATED, builder) |
| `src/supervisor/console/i18n.py`, `templates/agent.html` | Labels EN and VI (block placed before the WP-UX2 block); tab label |
| `src/supervisor/scheduler.py` | Job `risk_evidence`, listed only when the flag is on |
| `src/supervisor/ops/openapi.py` | `/v1/risks` counted as a human path |
| `schema/model.yaml`, `schema/ddl/*.sql`, `notebooks/bootstrap_and_smoke.py` | Tables; generated files |
| `docs/console.md` (role matrix regenerated, page row, flag row, tab), `docs/index.md`, `docs/threat-model.md` (3.10), `README.md`, `BACKLOG.md`, `CHANGELOG.md` (unreleased) | Docs |
| Existing tests changed | `tests/test_rbac.py` (viewer set now has `risks.view`), `tests/console/test_agent_detail.py` (two flags added to the all-on list), `tests/console/test_rbac_matrix.py` (`/v1/risks` answers JSON, `risk_id` path param) |

Not touched: `inventory/`, `advisory/compliance/`, `regkb/`, gateway, policies.

## Extension points for WP30 and WP31

* WP30 control catalogue: call `RiskService.add_link(risk_id, "rule"|"pack"|"monitor", target, actor)`; `RiskService.control_links(risk_id)` is the single read point of the evidence rule. A new link kind means a change to `LINK_KINDS`, `CONTROL_KINDS` and `Collector.count`.
* WP31 transparency report: read `RiskService.agent_summary(agent_id)` and `export_json()` (plain data with bands and the "illustrative" marker). No SQL needed.

## Not done (BACKLOG has the rows)

Console create and edit forms; four-eyes approval of a new or accepted risk; risk appetite object and signing; a synthetic gate probe so a rarely firing rule can prove it works; risk library and recommendations; merge mode and diff output for import; `tools/console_screenshots.py` does not capture the Risks page; no live Databricks run (Delta path is tested with the mirror fake and recorded statements only).

## Open questions for the owner

1. Real band thresholds and the meaning of each likelihood and impact step (risk appetite). Until then every surface says ILLUSTRATIVE.
2. Who may create, edit and accept a risk? Now: reviewer, owner, admin, one person alone. Do you want a second approver for `accept` and for a lowered declared residual?
3. Is the two-state evidence rule enough (declared value or inherent score)? A quiet rule (for example PAY-07) never lowers a score alone; the starter risks link a pack or monitor too. Do you want a canary probe through the gate instead?
4. "Credit memo" profile: I used the repo's `credit_prequal` agent (a credit decision profile). The credit memo agent is bank-internal code and was not read or copied. The bank imports its own file in the same format.
5. ADR number: I used D26 as you asked. D23 and D24 exist on other branches (verdict contract v2, MCP tool locking); D25 may too. Check for a clash at merge.
6. Evidence window (7 days) and number of working controls required (1): keep or change?
7. Gate state is read now, not at the time of each hit. If an agent moved from SHADOW to RUNNING inside the window, all hits count. Store the gate state with each verdict?
