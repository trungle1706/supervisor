# REVIEW WP39: Activity and analytics parity, nine alert use cases

Reviewer: Opus (as a data protection officer and a SOC analyst on call). Branch `wp39-activity-parity`,
delta `wp37-verdict-detectors...HEAD`. No push, no merge, no history rewrite. WP38 read only, with `git show`.

**Verdict: APPROVED WITH FOLLOW-UPS.** I fixed every High and Medium finding on the branch (7 commits, `38812eb`..`bd64cc4`).
The follow-ups are Low items and integrator notes (section 4).

## 1. Findings

| id | sev | file:line | what | fix |
|---|---|---|---|---|
| F1 | High | `gateway/routes.py:97`, `gateway/engine.py` `_req`, `detector_gate.py` consumer id | The caller gives the correlation id (header), the request id (`X-Request-ID`) and `context.consumer_id`. The plain-id pattern accepts `@`, `.` and digits, so an e-mail or a phone number passes. These values then went raw to `agent_event`, `finding`, the **evidence chain**, the alert row, the triage text, the SIEM event, the CSV, `decision_daily` and every v2 page. My leak seeding found 30 of 36 surfaces leaking. | `38812eb`: `looks_personal()` (the vn_regex masker finds the data, no key is used). The gate replaces such a correlation or request id with a new id and drops such a consumer id. The alert service drops such a correlation id. Pages, the export and the rollup show older rows as `<id-hidden>`. Filters and deep links refuse such values with HTTP 400. Result: 0 of 36 surfaces leak. |
| F2 | High | `console/decisions_v2.py` export, `routes.py` GET download | The download name had 24 random bits and no other binding. Any auditor or admin could fetch the file at any time, as many times as they liked. Files were never removed. | `38812eb`: the link is `?exp=&t=HMAC(name\|user\|exp)` with a key that lives in the process, and it is valid for 15 minutes. The file is served once with `no-store` and then deleted. Stale files are removed on every export and every download. Exports have their own folder, apart from the audit packs. Tests cover another user, a reviewer, a bare name, a tampered token, reuse, expiry and cleanup. |
| F3 | Medium | `routes.py` export audit | The audit note had no filter hash. | `38812eb`: `filters=<16 hex>` (sha256 of the parsed filters and the sort). |
| F4 | Medium | `alerts/signals.py` `_finding_signals` | `enforcement` was `enforced` for every agent that was not in SHADOW. Findings never stop a call (R1, `derive_status`), so a `block` hint on a RUNNING agent was mislabelled and the alert stayed silent. | `38812eb`: `enforced` only when the decision status is block or pause. `shadow`, `observe` and `not_enforced` otherwise. The rule fires on `shadow`, `observe` and `not_enforced`. |
| F5 | Medium | `alerts/signals.py` `_coverage_gaps` | A gap fired for an agent that only talks (LLM calls and messages never pass the gate) and for any registered or RETIRED agent whose inventory node is still active (idle apps, every hour). | `38812eb`, decided and documented in docs/alerts.md and the ADR addendum: only `tool_call` events count. The inventory counts only for systems that are not in the registry. A RETIRED agent that still calls tools **is** a gap, because the gate records a block for every call of a retired agent. |
| F6 | Medium | `_alert_drawer.html`, `decisions_v2.resolve_ref` | The alert "Open decision" link used `?correlation=` only. One correlation id can span agents, so the link opened the newest decision of any agent, and the decision drawer listed alerts of other agents. | `38812eb`: `&agent=` on the link, `resolve_ref(agent=)`, and the drawer lists only alerts of the same agent. |
| F7 | Medium | `i18n.py` `dd_series` | "Policy actions over time" is the vendor chart title word for word (bridge plan section 4). | `9f839ea`: "Gate outcomes by day". |
| F8 | Medium | screenshots | The screenshots were taken before the Observed-decision line, and there was no Response tab. | `d0a4461`: 19 screens retaken, Response EN and VI added. |
| F9 | Medium | tests | There was no test that the old rule hashes are unchanged, no test that the export columns are pinned, no test for bootstrap on an existing file, no proof of "no raw-table read", and no test for the download token. | `38812eb`: `tests/console/test_wp39_review.py` (22 tests). |
| F10 | Low | `i18n.py` | Vietnamese: "đã chặn nếu thực thi" should be "sẽ chặn". "Chi phí chung" (an accounting term) was used for latency overhead. | `9f839ea`: "sẽ chặn" / "sẽ tạm dừng", "Thời gian còn lại". A native review is still advised. |
| F11 | Low | `_alert_drawer.html`, `alerts_list.py` | With the flag off, the drawer of an old alert gained a "Correlation id: -" row and a null JSON key. | `5442117`: the row and the key appear only when an id is stored. |
| F12 | Low | `decisions_v2._linked_events` | A NULL `capture_level` was treated as "not digest". The Traces page treats it as digest. | `38812eb`: same rule as the Traces page. |
| F13 | Low | `_decisions_list_v2.html` | The export form needs htmx. Without JS, submit does a GET on the list page. | open (BACKLOG candidate) |
| F14 | Low | `analytics_v2._validation` | The detectors harness runs on the first Detectors tab load (cached per process). | open |
| F15 | Low | `decision_rollup.not_evaluated_sql` | The `IN (SELECT ... FROM finding)` subquery has no date bound. It is fine now and slow at scale. | open |
| F16 | Low | Analytics Gate tab | The v1 KPI "Blocked 3" and the v2 series "Block 8" disagree on the demo store. The synthetic rows have no tier-0 verdict rows. | open, check on real data at merge |
| F17 | Low | Detectors tab | The window line is shown twice. | open (cosmetic) |
| F18 | Info | `detector_gate`, WP38 | WP39 records `context.consumer_id` as the caller sends it. WP38 resolves it against the registered consumers (`eff.consumer_id`, `consumer_ignored`). | integrator: record the WP38 resolved id (BACKLOG row) |

CSS (5 lines, `mark.hl` on our `--amber` tokens) and JS (9 lines, strip the deep-link parameters) are justified.
I checked the labels against the vendor handoff. The only verbatim layout label was F7. "Not evaluated", the four tab names and
"Correlation id" are sanctioned by bridge plan row 44. No vendor text, tokens or icons are on the branch.

## 2. Leak seeding per surface (synthetic)

Planted values: "Nguyễn Văn Thắng", CCCD 079203001234, phone 0987654321, e-mail thang.nguyen@vidu.vn, account 19033456789012.
I planted them through the real gate in args, tool results and output, in a correlation id (the phone), in a consumer id (the e-mail),
in a recorder row whose "masked" text was raw, in detector fragments at offset -1..99999 and spanning two tokens, in entity tokens, in a case title and
in an alert row. The scan looks for the raw form and the JSON-escaped form (the raw JSON view escapes non-ASCII).
Script: scratchpad `wp39_leak_seed.py`. Logs: `wp39_review_leak_before.txt`.

| Surface | Before | After |
|---|---|---|
| Drawer Request / Response / Detections / Metadata (4 decisions, incl. raw JSON view) | leak (phone, e-mail ids) | clean |
| List, rows partial, no-JS `?drawer=` fallback | leak (e-mail) | clean |
| `?correlation=<phone>` deep link | leak | 400, no echo |
| `?corr=` / `?consumer=` filters with personal data | echoed | 400, no echo |
| Trace head, span detail | leak (phone) | clean |
| Analytics Gate (`decision_daily` consumer key) | leak (e-mail) | `<id-hidden>` |
| Alert row, alert drawer, triage text, SIEM event | leak (phone) | id dropped or hidden |
| CSV export | leak (phone, e-mail) | clean |
| Error pages (bad drawer id, bad deep link) | clean | clean |
| Names, CCCD, accounts in text, fragments, tokens, case title | clean (masked again) | clean |

The Request tab reads only `agent_event.args_masked` / `result_masked` and masks that text again. No console code reads `agent_event_raw` (grep).
So a trace at capture level `raw` cannot pull raw text.

## 3. WP38 alignment (read with `git show wp38-collectors:src/supervisor/gateway/engine.py`)

* Labels and join match. WP38 writes tier-0 `verdict` rows with label `observe_would_block` / `observe_would_pause` (for rule matches and for a lifted `GATE-DETECTOR-FAILED`) and `event_id = d.decision_id`. WP39 `_observe_signals` reads exactly that. No patch is needed.
* WP38 also writes chain keys `mode` and `observed_decision {action, rule_id}`. The v2 Observed line now reads those too (`38812eb`).
* Mismatch, open: WP39 reads `payload["approvals"]`. WP38 has no such key (approval is `eff.observe_approved`, not recorded). Proposed patch for the integrator, in WP38 `_payload`: `out["observe_approved"] = bool(eff.observe_approved)` when `d.sem` is set. In WP39 `_observed`: `ap = payload.get("approvals", payload.get("observe_approved"))`. Until then the line shows "-".
* `consumer_id`: see F18.

## 4. Follow-ups (not blocking)

F13 to F17, F18 and the approvals key. BACKLOG has the new rows: replaced caller ids, the WP38 consumer, and `shadow_would_*` matches for AL-THREAT-NOT-ENFORCED (a SOC decision).
Ids with a 9 to 19 digit run (about 1 in 4000 random hex ids) look like a number to the masker and are replaced or hidden. Gate-generated ids are redrawn.

## 5. Commands (last lines)

```
$ uv run python -m pytest -q -x -p no:cacheprovider
3929 passed, 29 skipped, 1 warning in 543.22s (0:09:03)     (author: 3907 passed; +22 review tests)
$ uv run python -m ruff check
All checks passed!
$ uv run python -m ruff format --check
702 files already formatted
$ uv run python -m supervisor.alerts.harness
[OK] drills GO
[OK] all GO
$ uv run python -m supervisor.console.activity_harness --record --commit 5442117 --date 2026-10-20
all pages: 360 requests (3 flag states x 4 roles x 2 languages), 0 bad, ok 10000 bp
DPO: 21 pages and the export scanned, leak_items=0, export columns exact=True
SOC: triage complete 15/15 decisions (10000 bp, Wilson 95% [7961, 10000])
adversarial probes: 30/30 (10000 bp, Wilson 95% [8864, 10000])
OVERALL: GO
```

Eight reviewer probes are in the harness: PII fragment across two masked tokens, `javascript:` correlation id, forged 50,000-row export,
finding code with HTML, decision with no recorder event, SHADOW agent with 1,000 block findings in 1 minute (1 alert, 999 suppressed),
alert with the correlation id of another agent, consumer id with an RTL override.
Rate rules: 40/40 above and below the limit, Wilson [9123, 10000] bp. Old rule hashes: pinned test, unchanged. Rollup: rerun writes nothing (author test).
Analytics tabs read only `decision_daily` (spy test). Bootstrap on a WP37 SQLite file adds the 6 columns and the table (test).

## 6. Owner questions: recommendations

1. **Request tab needs the recorder event.** Accept for now. Tell gate-only clients to turn on masked capture. Add a gate-stored masked copy only if gate-only clients are common (BACKLOG row exists).
2. **Export location.** Keep `CONSOLE_EXPORT_DIR` with the new one-time link. Use a UC volume only if exports must be kept, and then with a retention class and an audit read.
3. **AL-ERROR-RATE.** Yes, persist route statuses (a small counter table). Without it, plain 400s stay invisible.
4. **Thresholds.** The bank SOC sets them. Keep them ILLUSTRATIVE and run the nine rules for two weeks route-only (inbox) to calibrate before pager or webhook.
5. **`consumer_id` in the SDK.** Yes, required in the WP38 SDK for agents that have registered consumers. Record the WP38 resolved id, never a free string. PII-shaped ids are refused (now enforced).
6. **Unregistered ids.** Keep AL-COVERAGE-GAP (high) for tool calls without a decision. Move the inventory-only, unregistered systems to a separate medium "unknown agent" rule, so the high alert means a real bypass.
