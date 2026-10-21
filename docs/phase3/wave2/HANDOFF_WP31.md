# HANDOFF WP31: Transparency report

Branch `wp31-transparency`, built on `wp29-risk-register` (merged three times; final merge of head 5c0d887). No push, no merge to main. Flags off by default. Docs: `docs/transparency-report.md`. ADR: `docs/adr/D31-transparency-report.md` (D23 to D30 are taken elsewhere; D26 exists here).

## What was built

```
 read-only facts --> ReportBuilder (14 sections) --> allow-list per variant --> guard --> JSON
 (Facts + services)        |                                                              |
                           +--> "what this report does not show" (computed)               +--> HTML vi/en, PDF vi/en
                                                                                          +--> chain record + table rows
```

| Item | Where |
|---|---|
| Package: model, facts, builder, allow-lists + guard, display blocks, renderers, service, API, CLI, harness | `src/supervisor/transparency/` |
| Variants `regulator` (obligation ids cited), `customer` (plain sentences, no id/hash/rule/owner), `internal` (all + open BACKLOG rows naming the agent) | `allowlist.py` |
| HTML reuses the case-file page's style block (read from its template, no new CSS); PDF reuses `find_font`/`RenderResult`/`fpdf2`, no font download, HTML fallback with notice | `render.py` |
| Versions by content hash (time, version and chain head left out); files never overwritten; reads check the stored hash | `service.py` |
| Chain record `transparency_report` (agent lane): hashes, ints, fixed codes, diff to previous version (changed section ids) | `service.py` |
| Table `transparency_report` (append-only) in both DDLs, `schema/model.yaml`, notebook regenerated | schema |
| Routes `GET /v1/transparency`, `GET /v1/transparency/<agent>?variant=&format=&lang=&live=`, `POST /v1/transparency/<agent>/generate` | `transparency/api.py` |
| Console page `/console/transparency` (list, drawer, generate for reviewer and admin), Agent tab "Transparency", nav entry | `console/transparency_views.py`, 5 templates |
| Job `python -m supervisor.jobs.transparency`; scheduler job `transparency` (listed only when flag on) | `jobs/transparency.py`, `scheduler.py` |
| CLI `python -m supervisor.transparency build\|generate\|list` | `__main__.py` |
| WP30 hook: `ReportBuilder.register("controls", fn)` + `allowlist.set_spec(...)`; section says "not built" until then | `builder.py` |
| Harness: 54 golden scenarios (36 dev, 18 held-out), 24 adversarial probes, determinism, baseline | `harness.py`, `tests/fixtures/transparency/` |

## WP30 adapter (optional, not merged)

`transparency/controls_adapter.py` reads `ControlService.agent_compliance`, `obligation_coverage`, `uncovered_risks` and `TaskService.agent_summary` (signatures checked on branch `wp30-controls` with `git show`; I did not merge it) through lazy imports, gated by `CONTROLS_ENABLED`. Absent package: section "not built"; present and flag off: "flag off" (ref `CONTROLS_ENABLED`). The regulator allow-list already lists the fields (no owners); internal shows all. Shows integer bp, the product-versus-bank split and the note that bank-owned controls never read "working". `TaskService.agent_summary` is read as top-level plain values only (its exact shape is unverified), `export_json` and `preview` are not used. Test `tests/transparency/test_controls_adapter.py` runs with the package absent and with fake modules injected. Integrator after merging WP30: set `CONTROLS_ENABLED=1`, run the harness, check the `tasks` fields in the report, and add WP30 chain types (`control_change`, `control_status`, `task_change`, `task_resize`) nowhere (the report does not read them).

## Flags

`TRANSPARENCY_ENABLED=0` (routes answer HTTP 400 when off, job, CLI), `CONSOLE_TRANSPARENCY_ENABLED=0` (page and tab, needs the first), `SCHED_TRANSPARENCY_S=86400`, `TRANSPARENCY_DIR` (default `<data_dir>/transparency`), `TRANSPARENCY_BACKLOG_FILE` (`BACKLOG.md`). On Delta run `python -m supervisor.jobs.bootstrap_schema` (one new table).

## After the WP29 review messages

* `changed_since_evidence`: each risk row shows `evidence_reason` with the register's own label (`rk_reason_*`).
* The risk section states which links are evidence (rule; packs not scored by a judge; monitors `fairness`, `drift`, `multiagent`) and which are references (judge-scored packs unless `RISK_EVIDENCE_JUDGED_PACKS=1`, other monitors, matrix, case); per risk it prints the two counts.
* Actors: the report never prints a chain actor. A probe creates a risk by an email actor and checks the regulator and customer text for it. The regulator version prints no actor and no role of one (nothing from `risk_change` is read); the owner team is the only ownership shown.
* Golden fixtures: the generator (`tests/fixtures/transparency/generate.py`) did not change; its expected values did not depend on risk counts, so `--check` still passes. The baseline `baseline.json` was re-recorded after the final merge (results unchanged: 100% on both splits).

## Commands (and last lines)

```
uv sync --extra pdf        (fpdf2 is in uv.lock; the PDF tests need it and a system font, else they skip)
uv run python -m pytest -q
  3935 passed, 28 skipped, 1 warning in 591.87s (0:09:51)
uv run python -m ruff check          All checks passed!
uv run python -m ruff format --check  710 files already formatted
uv run python -m supervisor.transparency.harness
  [dev] n=36 accuracy=10000bp [9035, 10000] leaks=0    [held_out] n=18 accuracy=10000bp [8241, 10000] leaks=0
  [adversarial] 24/24 [8620, 10000]   [determinism] 10000bp   [OK] all GO
uv run python tests/fixtures/transparency/generate.py --check   (exit 0)
set TRANSPARENCY_ENABLED=1
python -m supervisor.transparency build payments --variant regulator --format html --lang vi --out out\tr
python -m supervisor.jobs.transparency
```

## Test counts

| | Passed | Skipped |
|---|---|---|
| Before: WP29 first head 316a039 (its handoff) | 3,829 | 29 |
| Before: WP29 final head 5c0d887 | not measured by me; the last full run on my branch before WP31 tests were counted shows the difference below | |
| After (this branch, final run, with the WP30 adapter) | **3,935** | 28 |

New tests: `tests/transparency/` (service 12, CLI and job 6, Delta 2, harness 9) and `tests/console/test_transparency.py` (4), plus the parametrised RBAC cases the existing matrix adds for the 7 new routes. Run 1 of the full suite showed 3 failures from my own changes (audit coverage list, an i18n pair equal in both languages, an `__import__` in a test); fixed. In a partial run that combined several console modules, 4 `console` fixture errors appeared once and did not repeat alone or in the full runs (I did not find the cause; likely test ordering).

## Harness result

Rubrics: "regulator inspector (SBV)" (Decision 33 class and obligation ids cited, every gap stated, hash to check) and "data protection officer" (nothing identifying in the customer version, planted PII masked, names not copied outward).

| Row | Result |
|---|---|
| Golden dev 36 / held-out 18 | 100%; Wilson 95% [90.4%, 100%] and [82.4%, 100%] |
| Customer leaks in golden | 0 |
| Adversarial 24 | 24 of 24 (PII in a case title, retired agent, agent with no inventory node, half the flags off, failed chain check, obligation id removed, oversized lists, Vietnamese name in a model card, stale previous version, bad customer allow-list, markup in a name, failing collector, float refused, PDF with no font, PDF with the network refused, existing file, long text, mock results, WP30 hook, chain actor, and others) |
| Determinism | same content hash always; same JSON and HTML bytes under a fixed clock |

Limits: expected values and code were written by the same author; the golden set shows the code does what the rubric says, not that the rubric is right. Mutation checks were not run by hand. Thresholds are ILLUSTRATIVE. The Wilson intervals are wide for n = 18.

## Files touched outside the package (all additive)

`src/supervisor/config.py` (block `# --- WP31 ---`, validator names, default dir), `app.py` (router), `core/rbac.py` (`transparency.view`, `transparency.generate`, 7 ROUTES entries), `adapters/auth/authz.py` (denied POST under `/v1/transparency` audited), `ops/openapi.py`, `console/context.py` (property `transparency`), `console/routes.py` (4 routes, flag entry), `console/nav.py`, `console/agent_detail.py` (tab), `console/i18n.py` (about 250 `tp_*` keys, EN and VI, one block), `console/templates/agent.html` and 5 new templates, `scheduler.py`, `jobs/transparency.py` (new), `schema/model.yaml`, both DDLs, `notebooks/bootstrap_and_smoke.py`, docs (`console.md` role matrix regenerated plus rows, `index.md`, `threat-model.md` 3.11, `transparency-report.md`, ADR D31), `README.md`, `CHANGELOG.md`, `BACKLOG.md`. Existing tests edited: `tests/test_rbac.py` (viewer set), `tests/console/test_agent_detail.py` (two flags), `tests/console/test_rbac_matrix.py` (JSON routes and audit coverage list). Not touched: `evidence/casefile/`, `risk/`, `inventory/`, gateway.

## Not done (BACKLOG has the rows)

Controls section (WP30 hook only); electronic signature of the file itself, PDF/A; files in a Volume or Delta; filters, sort and a version diff view on the page; publishing or delivering the customer version; legal review of Vietnamese wording; BACKLOG matching is by agent id and model family word only; no live Databricks run (Delta path tested with recorded statements and the DDL only).

## Open questions for the owner

1. May the customer version name the product? Now it uses generic wording per agent class (so no id can leak).
2. Which roles may hand on the customer version? Now every signed-in role reads it. Correction (review F8): my first text said that with `API_RBAC_ENABLED` off an unsigned caller acts as a read-only service principal. That is wrong: `needs()` always enforces on these routes. A service principal gets 403 (`transparency.view` is not in `NON_USER_OK`), no identity and no `default_user` gives 400, and in laptop dev mode `default_user` signs every unsigned call in. Test: `test_login_is_required_and_a_service_principal_cannot_read`.
3. Should the regulator version show the owner team, or a role only?
4. Names are kept out of the regulator and customer versions by omission because the masker misses names; accept, or add the NER extra first?
5. Commit trailers: the brief says `Claude Fable 5.1`, the session reminder says `Claude Sonnet 5.5`. My first commit carries Sonnet, the later ones Fable (I did not rewrite history). Pick one for the merge.
6. PDF needs `fpdf2` (optional extra, in `uv.lock`) and a local font; the bank laptop must have both for PDFs.

## Follow-ups after review

Review result: approved with follow-ups (REVIEW_WP31.md; the reviewer commits 1ae6d2e, 518aad8, 0e5fa65, 8516d02, 83881bc and 6a1098d are kept as they are). Closed in commit 44f7e2f (code and tests together, one commit):

| Finding | Fix | Tests |
|---|---|---|
| F11 agent id and the filesystem | `check_agent` refuses a leading or trailing dot and `..` anywhere (path separators, spaces and other characters were already outside the charset). `_dir()` also calls `check_agent`, resolves the path and refuses any folder outside `TRANSPARENCY_DIR` | `tests/transparency/test_followups.py`: 12 bad ids, 5 good ids, a registered agent named `a..b` is refused by generate and read |
| F12 failed row write | If the rows cannot be written after the chain record, the files are removed, a `transparency_report_failed` chain entry (ids, version, error class) is recorded and the error is raised; the next generate writes the same version again. If the chain record itself fails, the files are removed as before | Both orders: rows fail then the next generate works; chain fails then the next generate works |

F8 correction: question 2 above wrongly said that with `API_RBAC_ENABLED` off an unsigned caller acts as a read-only service principal. `needs()` always enforces on these routes. A service principal gets 403 (`transparency.view` is not in `NON_USER_OK`); no identity and no `default_user` gives 400; in laptop dev mode `default_user` signs every unsigned call in. Test: `test_login_is_required_and_a_service_principal_cannot_read`.

Last lines:
```
uv run python -m pytest -q -x        3986 passed, 28 skipped, 1 warning in 571.17s (0:09:31)
uv run python -m ruff check          All checks passed!
uv run python -m ruff format --check 718 files already formatted
uv run python -m supervisor.transparency.harness   [adversarial] 24/24 ... [determinism] 10000bp ... [OK] all GO
```
