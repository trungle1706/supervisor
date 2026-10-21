# REVIEW WP31: Transparency report

Reviewer: Opus (data protection officer and SBV inspector view). Branch `wp31-transparency`, delta `git diff wp29-risk-register...HEAD`. No push, no merge, no history rewrite. Review commits: 1ae6d2e, 518aad8, 0e5fa65, 8516d02, 83881bc.

## Verdict

**APPROVED WITH FOLLOW-UPS.** The review found and fixed 2 High and 6 Medium findings on the branch. The follow-ups are Low and are listed below. They do not block the merge.

```
 before review                                after review
 regulator variant: raw fields leak  ---->    every text value masked + scrubbed (e-mail, phone, digit runs)
 chain record: generated_by = e-mail ---->    role or keyed ref act_...
 preview / live=1: no text check     ---->    text check on every path, both languages
 new builder field: no gate          ---->    allowlist.REVIEWED + failing test
 WP30 adapter: wrong import path     ---->    aligned with wp30-controls 9ba1f4f
```

## Findings

| Id | Severity | File:line (at review start) | What | Fix |
|---|---|---|---|---|
| F1 | High | `transparency/service.py:239` (`"generated_by": actor`) | The chain record held the raw actor id. A person id can be an e-mail. This breaks R2 (no PII in the chain). The planted e-mail was found in the `transparency_report` chain payload. | 1ae6d2e: `actor_ref()`; a product role (`system:`, `cli:`, `job:`) stays readable, a person is `act_` + keyed HMAC. Test `test_chain_record_names_no_person`. |
| F2 | High | `transparency/builder.py` `c_risks` (`"via": r.get("via")`), `c_compliance`, `c_cards`; `allowlist.py` `REGULATOR` (`True` sub-trees), `text_leaks` | The regulator variant showed planted e-mail, phone, CCCD, account number and an unregistered name in all formats and both languages. Paths: `risks.top[].via` (inventory node name, not masked), `compliance.d33_rows[].article_ref`, `compliance.gaps[].instrument_id`, `cards.agent_card.limits[].id/scope/ref`. The regulator guard knew only registered names; it had no pattern check. | 1ae6d2e: `via` masked; after the projection every text value of regulator and customer goes through the masker and `scrub_text` (e-mail, phone, digit runs of 9 to 19 or grouped); with no masker only one-word codes stay; guard refuses those patterns in both outer variants. Clean demo reports are unchanged (test). |
| F3 | Medium | `transparency/service.py` `preview`, `read` (preview branch), `report` | The second check on the rendered text ran only in `generate`. A preview, `live=1` or the console drawer skipped it. | 1ae6d2e: `check_text()` in `preview()` for both languages. Test `test_live_and_lang_cannot_skip_the_text_check`. |
| F4 | Medium | `transparency/allowlist.py` `REGULATOR` | 7 regulator sections are copied whole (`True`). A new builder field went out with no decision and no failing test. | 1ae6d2e: `field_paths()` + `REVIEWED` (208 paths); `test_every_field_the_builder_makes_was_reviewed` and `test_a_new_field_without_review_fails`. |
| F5 | Medium | `transparency/controls_adapter.py:35-86` | Mismatch with `wp30-controls`: `supervisor.controls` and `supervisor.tasks` do not export `ControlService` / `TaskService` (they are in `.service`). After the merge the section would say `source_error` (the tasks `AttributeError` was not caught). `uncovered_risks()` is register-wide, so the count included other agents. `agent_summary` top-level dump copied `agent_id`, `band_source` and dropped `counts`. The package was imported before the flag check. | 518aad8: `find_spec` for presence; import of `.service` modules only with `CONTROLS_ENABLED` on; count kept to the agent's risks; named task fields + `counts_<status>`. 3 new tests (flag off imports nothing, no service module, per-agent count). |
| F6 | Medium | `transparency/builder.py` `not_shown` | Sources that are off while their section shows were not listed: monitors off (5 by default), masking off, judge with no validation run. | 1ae6d2e: codes `monitors_off` (count, names except customer), `masking_off`, `judge_not_validated`; EN and VI labels. |
| F7 | Medium | `transparency/service.py:265` (row `generated_by`) | The append-only evidence row (1825-day retention, model says "no text") kept the readable actor. | 1ae6d2e: the row holds the same ref; the `console_action` audit row keeps the person. |
| F8 | Medium (docs) | `HANDOFF_WP31.md` question 2, `docs/transparency-report.md` | Claim "with `API_RBAC_ENABLED` off an unsigned caller acts as a read-only service principal" is wrong. `needs()` without `api=True` always enforces. A service principal gets 403 (`transparency.view` is not in `NON_USER_OK`). No identity and no `default_user` gives 400. In laptop dev mode `default_user` signs every unsigned call in. | 8516d02 docs; 0e5fa65 test `test_login_is_required_and_a_service_principal_cannot_read`. HANDOFF left as the author wrote it. |
| F9 | Low | `transparency/allowlist.py` (residual) | The regulator variant relies on the masker for person names in free text and config text fields. vn_regex catches names with diacritics only. | Open: BACKLOG row added (NER extra). |
| F10 | Low | `transparency/api.py` `generate` | `POST /v1/transparency/{agent}/generate` accepts the ambient identity (dev `default_user`, cookie), unlike the gate control routes. Same as `/v1/risks`. | Open (consistent with WP29; decide for all `/v1` writes). |
| F11 | Low | `transparency/model.py` `_ID` | The agent id regex allows `..`; `_dir()` joins it into a path. Only registered agents reach it. | Open: refuse `..` in `check_agent` or resolve and check the path. |
| F12 | Low | `transparency/service.py` `_generate_one` | The chain record is written before the rows. If the row append fails, the files stay and the next generate stops with "refusing to overwrite" until someone removes the folder. | Open. |
| F13 | Low | routes | With the flag off the routes exist and answer HTTP 400 (not "no routes"). Same pattern as WP29. Nav, tab and scheduler job are absent. | By design; scheduler test added 83881bc. |
| F14 | Info | tests | No test read the PDF text layer. | 1ae6d2e: `tests/transparency/pdftext.py` (stdlib zlib + ToUnicode CMap). |

## Leak seeding (planted values in every source)

Planted: Vietnamese names (`Nguyễn Thị Hồng Nhung` owner and MRM role, `Trần Văn Bảo` business owner, `Lê Minh Khôi` registered nowhere), CCCD `079203001234`, phone `0912345678`, two e-mails, account `19031234567890`, another agent id `credit_prequal`, rule `PAY-03`, a 64-hex hash, team `Khoi Ban Le Team Alpha`, a BACKLOG marker. Sources: agent row (name, owner team, owner, business owner), inventory node names and edge evidence refs, agent card (purpose, limit id, scope, pointer), matrix rows (article, instrument), judge card roles (settings), risk title, description, treatment note and owner, case title, BACKLOG row, an agent-lane chain payload, an assurance result. Policy rule descriptions and monitor binding text: the builder does not read rule descriptions; binding `gap` text holds tool names only and is scrubbed now. Masker on and masker off. Paths: preview (`live=1`) and signed. Script: scratch `seed_leaks.py`; the same seeding is now a test (`tests/transparency/test_review_leaks.py`).

| Variant | Forbidden | Before fixes | After fixes (vi, en x json, html, pdf; preview and signed; masker on and off) |
|---|---|---|---|
| customer | ids, rule ids, hashes, owners, persons, e-mails, phones, CCCD, accounts, team, BACKLOG | 0 hits (narrow allow-list) | 0 hits in 24 of 24 outputs |
| regulator | persons, e-mails, phones, CCCD, accounts | e-mail, phone, CCCD, account, unregistered name in json and html, both languages (PDF the same text); masker off: unregistered name | 0 hits in 24 of 24 outputs |
| internal | (bank only) | masked; BACKLOG rows shown | masked; BACKLOG rows shown (masker on); text dropped with masker off |
| chain record | person, e-mail | e-mail in `generated_by` | role or `act_` ref |

A failed chain check (`set_verify(False)` and a real verifier run on a changed chain row, scenario S3) is stated in all 3 variants, both languages, all 3 formats.

## Checklist (items 1 to 9)

| Item | Result |
|---|---|
| 1 Leakage | F1, F2, F7 fixed; seeding above |
| 2 Allow-lists, guard, `live=`, `lang=` | F3, F4 fixed; `live=1` writes no row, no chain entry, no file (service and route tests) |
| 3 Integrity | append-only triggers checked on SQLite (update and delete refused), Delta insert-only MERGE test; files `xb`; tampered file is HTTP 400 at the route (test), gone file 404; chain record carries json, html and pdf hashes and the diff; same facts twice = one version (existing test); `generated_by` is a role or ref (F1) |
| 4 Truthfulness | F6 fixed; retired, no inventory node, no matrix, mock judge, chain failed, removed obligation id all stated (author probes + S2, S4, S1) |
| 5 RBAC | generate is reviewer and admin, two audit rows; login required when auth is on (F8 test); service principal 403 |
| 6 Both modes | DDL parity and notebook tests green; bootstrap on a SQLite file made from the WP29 DDL adds the table, index and both triggers; flag off: no nav, no tab, no scheduler job (new test), routes HTTP 400; PDF falls back to HTML with a notice (author probe) |
| 7 WP30 adapter | F5 fixed against `git show wp30-controls:...` (read-only) |
| 8 Harness honesty | 5 own SBV inspector scenarios (`tests/transparency/test_inspector_scenarios.py`): S1 class and the six PL4 obligation ids traceable; S2 every off or mock source stated; S3 real verifier on a changed chain row; S4 retired agent without inventory node and matrix; S5 chain hashes equal the served bytes, tamper refused, v1 kept. Harness 24 probes pass; two runs give the same output; golden `--check` exit 0. Console modules run together 3 times: 572 passed each time, no fixture error |
| 9 Shared files | additive only; docs, ADR D31 amendment, threat model 3.11, BACKLOG (stale controls row replaced, names row added), CHANGELOG updated; HANDOFF and its commit trailers not rewritten |

## Commands and last lines

```
uv sync --extra pdf                                   Checked 49 packages (fpdf2 2.8.9, DejaVu fonts present)
uv run python -m pytest -q -x   (before review)       3935 passed, 28 skipped, 1 warning in 569.12s
uv run python -m pytest -q tests/console  (x3)        572 passed / 572 passed / 572 passed
uv run python -m pytest -q -x   (final, 83881bc)      3966 passed, 28 skipped, 1 warning in 571.37s
uv run python -m ruff check                           All checks passed!
uv run python -m ruff format --check                  717 files already formatted
uv run python -m supervisor.transparency.harness      [dev] n=36 10000bp [9035, 10000] leaks=0
                                                      [held_out] n=18 10000bp [8241, 10000] leaks=0
                                                      [adversarial] 24/24  [determinism] 10000bp  [OK] all GO
uv run python tests/fixtures/transparency/generate.py --check    exit 0
```

Final test count: 3,966 passed, 28 skipped (before review 3,935 passed, 28 skipped) (31 new review tests). Scratch logs: `wp31_review_*.txt` in the reviewer scratchpad.

## Owner questions: recommendations

| # | Question | Recommendation |
|---|---|---|
| 1 | May the customer version name the product? | Yes, but only a public name the bank approves, from a new manifest field (for example `customer_display_name`), never the agent id. Keep the generic wording until the field is set. The guard keeps checking ids. |
| 2 | Which roles may hand on the customer version? | Reading: every signed-in role (verified: login required, service principals 403). Handing on outside the bank: reviewer and admin, after a legal sign-off, as an audited action. Do not make the route public. |
| 3 | Owner team or role in the regulator version? | Owner team. An inspector asks for the accountable unit; a team is not a person. Add a check at registration that `owner_team` holds no person name or e-mail (the scrub now removes e-mails and phones). |
| 4 | Names by omission, or the NER extra first? | Accept omission plus the review scrub for the pilot and the regulator version. Add the NER extra before the customer version leaves the bank: config text fields and free text can hold names that vn_regex misses (no diacritics). |
| 5 | Commit trailers | Use `Claude Fable 5.1` (the binding team brief). Do not rewrite history; the integrator states the mixed trailer on the first commit in the merge commit message. All review commits carry Fable 5.1. |
| 6 | PDF needs `fpdf2` and a local font | Keep `fpdf2` as the optional extra (in `uv.lock`). On the bank laptop set `CASEFILE_PDF_FONT` to a Windows font with Vietnamese glyphs (for example `C:\Windows\Fonts\arial.ttf`); no download. HTML stays the fallback with its notice. |

## Integrator notes

* After the WP30 merge: set `CONTROLS_ENABLED=1`, run the harness and one live report; the adapter was tested with fakes shaped like `wp30-controls` 9ba1f4f.
* Content hashes change once after this review (new not-shown codes, scrub): the first job run after the merge makes one new version per agent and variant. This is expected.
