# 04 · Deliverables quality, business case, demo readiness, product/UX, scope
Lens: deliverables, business case, competition and demo, product gaps. Date 2026-10-14.
Method: read all docs, extracted all 22 slides + notes (python-pptx, venv at analysis/.venv), read both HTML pages, voice-over, scene.html; re-derived costs in Python; tried both generators.

## 1. Verdict
The package is strong on story and structure. Deck, video and docs agree on the headline numbers. The weak points are the money and the demo.
(a) The fleet model (docs/04) contradicts the cost model: token cost is flat at 3 agents but is treated as nearly flat to 40. This breaks the video's "-50% / x7" claim. A bank finance team will find it in minutes.
(b) Residency claim "No customer data leaves Vietnam" is likely false as written (no Databricks region in Vietnam found; Claude "regional processing" is a 10% uplift, not in-country).
(c) The live demo (1 onboarding + 4 incidents + tamper test) has no runbook, no fallback and many network and cold-start risks.
(d) Docs/08 sprint 1-2 is too much for 4 people in 4 weeks unless the Onboarding Agent is mostly template and fixture driven. A cut list is in section 6.
(e) The reviewer console, the developer "click Onboard" path and alert-fatigue controls are named but not specified.

## 2. Findings table
| # | Gap / risk | Sev | Evidence | Recommendation | Effort | Phase |
|---|---|---|---|---|---|---|
| 1 | Fleet model Supervisor cost = 309 + 4N ignores token growth. Token lines (45+65+20+8 = $138k) belong to 3 agents = ~$46k/agent/yr. At 40 agents the same logic gives ~$1.8M tokens, not $469k total. "-50% cost" and "x7" fail | H | docs/04 fleet model; deck s15; video Part three | Rebuild fleet model with per-agent variable cost (volume per agent, tier mix, caching, batch). Re-state claims. Or state "same volume per agent" and show sensitivity | 1 day | Competition |
| 2 | Net benefit "x7" is driven by one unsourced input: 90k/agent benefit and the cap on manual launches (N_eff 23 vs 40). Governance savings alone are small. Video shows it as headline | H | docs/04: net = 90*N_eff - cost - exposure | Split the chart: (i) cost, (ii) exposure, (iii) launch throughput as a separate assumption. Label 90k and cap as [bank to supply] on screen | 0.5 day | Competition |
| 3 | Exposure model 18k vs 2k per agent, and -89%, has no source or method. A CRO will ask "where does 18 come from?" | H | docs/04 | Replace with expected-loss form: frequency x severity x control effectiveness, all bracketed. Keep as illustrative | 1 day | Competition |
| 4 | "No customer data leaves Vietnam" (deck s18, playbook). I found no Vietnam region in Databricks region lists (closest Singapore, Jakarta). Docs/03 also says check region. Claude on Databricks "regional processing" is a cross-border story | H | WebSearch: docs.databricks.com/aws/en/resources/supported-regions, /gcp/resources/supported-regions (Azure list truncated). VERIFIED partly; bank's actual workspace region is ASSUMED unknown | Change wording to "runs in the bank's own workspace; residency per bank's region and legal sign-off". Ask the bank for region. Prepare the in-region Qwen / open-weight path as the answer | 0.5 day text; open question | Competition |
| 5 | Slide 12 says "Licences checked: MIT and Apache-2.0 only" but docs/03 says ControlArena licence "not confirmed" and judge protocol is "Copied" from it | M | docs/03 vs deck s12 | Check the licence now (MIT per repo, ASSUMED). Fix wording | 1 hour | Competition |
| 6 | Cost model arithmetic needs unstated output-token assumptions ($45k and $65k hold only if output ~150 and ~600 tokens per read). Not printed | M | my derivation section 3 | Print token in/out per tier on slide 19 and in docs/04 | 0.5 day | Competition |
| 7 | "Actions" vs "traces": 300k actions/day is used as traces. A trace can hold many LLM calls and tool calls. Tier 1 reads whole transcripts | M | docs/04 | Define unit. Show cost per 1k actions | 0.5 day | Competition |
| 8 | FTE value inconsistent: run team 1.5 FTE = $108k ($6k/month = $72k/yr per FTE) but benefit 4 values 1 FTE redeployed at ~$50k | M | docs/04 cost vs benefit 4 | Use one loaded cost. Bank HR rate [bank to supply] | 1 hour | Competition |
| 9 | Break-even claim: "covered by onboarding savings across 10 agents ($150k) plus 1 analyst ($50k)" = $200k, not $309k | H | docs/04 break-even; deck s20 | Fix math: either 15+ agents or add other benefits. Show break-even by N | 0.5 day | Competition |
| 10 | Governance cost crosses only at N~14 (309+4N = 60+22N). At 3-12 agents Supervisor costs MORE than manual (321 vs 126 at N=3). Video hides this | M | docs/04 fleet formulas | Be honest: payback needs fleet size or incident avoidance. Show the crossover on the chart | 0.5 day | Competition |
| 11 | Targets (catch >= 90%, false alarm < 5%, groundedness >= 0.9, gap <= 5) measured on a red-team set we wrote ourselves. Circular. FinVault shows best guard 61% TPR / 30% FPR, so jury will doubt 90% / 5% | H | deck s16, s13 | Pre-register held-out attack set written by someone else (risk teammate or external pack). Report real measured numbers with CI. Show false-alarm number honestly | 3 days | Competition |
| 12 | Voice-over / video states "seven minutes" onboarding, "113 of 120" blocked, "11 days", "$14.8k vs $400", "1,842 cases" as fixed numbers. Labelled illustrative on screen, but the live demo will not reproduce them | M | voiceover; scene.html | In the live demo show measured numbers from the real run. Keep video numbers marked as concept | 0.5 day | Competition |
| 13 | Placeholders left: `[Team name]` slides 1 and 22 (2 in build.js); `[$__]`, `[1,000]`, `[$50]`, `[10 agents]` on s20. Official date, track mapping ("three track definitions cut off") still open | M | deck, CLAUDE.md | Close before submission. Map to tracks 1 and 3 explicitly on slide 4 | 0.5 day | Competition |
| 14 | Playbook HTML is stale: 3 incidents, old team roles, no Onboard. Readers may open it and see a different story | L | playbook vs docs/07 | Mark as "earlier draft" or regenerate; do not submit as-is | 0.5 day | Competition |
| 15 | Anthropic stat: slide 16 says "more than a billion agent decisions in August 2026"; docs/01 and 06 do not carry that figure | M | deck s16 vs docs/01 | Add the quote and URL to docs/06 or delete the "billion" | 1 hour | Competition |
| 16 | Unsourced numbers on slides: "12 ready checks" (s12), "about 19 ms per input" Prompt Guard (s13), "10-15% by 2030" (sourced), Detect "7 ms" (design target, not measured) | M | deck s12, s13, s14 | Source or remove. Replace 7 ms with measured p50/p99 from the real gateway | 0.5 day | Competition |
| 17 | Deck s15 notes: video has no audio; panel must narrate or record. No Vietnamese or English subtitle track | L | s15 notes | Record voice-over (or TTS) and burn captions. Needed for a jury that watches muted | 1 day | Competition |
| 18 | Model names (Haiku/Opus 5.5, GPT-5.4 mini, Qwen3.5 122B) and DBU prices are from the planning session. I could not re-verify them against the Databricks pricing page in this pass | M | docs/04 | ASSUMED. Re-check the pricing page the week before submission; keep a pricing date on slide 19 | 1 hour | Competition |
| 19 | No reviewer-console spec (section 5) | H | docs/02 item 8 is one line | Write 2-page console spec; build 3 screens only | 2 days | Competition |
| 20 | No developer entry point for "click Onboard" | H | docs/02, s7, s17 | Define trigger: Databricks App button, CLI, or UC tag. See section 5 | 1 day | Competition |
| 21 | No alert-fatigue controls (dedupe, grouping, suppression, severity routing) | M | metrics list false alarm < 5% only | Add case grouping and rate limits to console spec | 2 days | Dec |
| 22 | No CRO / board report | M | audit pack only | One-page monthly oversight report from metrics panel | 3 days | H1 2027 |
| 23 | Demo has no runbook or fallback | H | docs/07 | Section 4 | 2 days | Competition |
| 24 | Scope exceeds 4 people x 4 weeks | H | docs/08 | Section 6 cut list | - | Competition |
| 25 | Fail-safe design says low-risk actions continue when supervisor is down. A jury may ask who decides "low-risk" and what the audit gap is | L | s18 | Say: gap is logged on recovery; backfill from traces | 0.5 day | Dec |

## 3. Cost model audit (docs/04)
Prices: DBU $0.07. Haiku in 1.429 = $0.100/M, out 7.143 = $0.500/M. Opus in 57.143 = $4.00/M, out 285.714 = $20.00/M. (Per-token dollars match published Claude 5.5-class rates only if the docs' DBU table is right: ASSUMED.)
Volume: 300,000 x 365 = 109.5M actions/yr. Tier 2 = 1.5% = 1.64M reads/yr.

| Line | Input only | + output | Doc | Verdict |
|---|---|---|---|---|
| Tier 1 (3k in) no uplift | $32.9k | out 150 tok: ~$41k | $45k | Holds if out ~150 tok and uplift 10% (out 147 tok exactly) |
| Tier 1 with 10% uplift | $36.1k | out 100: $42.2k; out 200: $48.2k | $45k | Plausible |
| Tier 2 (6k in) with uplift | $43.4k | out 500: $61.4k; out 1000: $79.5k | $65k | Holds if out ~600 tok |
| Onboarding $8k | 24 runs/yr = $333/run | | $8k | Plausible; reads code + traces. Needs token count |
| Sums | 72+108+45+65+20+8+15+48 = 381; 381-72 = 309 | | | Arithmetic correct |
Result: $45k and $65k are reproducible but only with unprinted output-token assumptions (~150 and ~600). Print them.
Hidden issues:
- Judge cost is linear in volume. The doc has volume for 3 agents only. Fleet at 40 agents scales tokens ~13x (finding 1).
- No prompt caching, no batch discount, no retry/error rate, no judge-of-judge (meta-governance) cost, no PII-masking compute on tokens, no storage growth (traces + hash log at 4M+ entries).
- Tier 1 on 100% of traces with a cheap model is the right shape. Cost risk is Tier 2 if "flags" exceed 1.5% (false alarm 30% for guard models).
- "Vietnam loaded engineer $6k/month" and build team of 4 x 3 months: bank will replace with internal rate card.
- Year 1 build team is 3 months but run team is a full 12 months from Oct: overlap not shown.
- Missing lines: Databricks support/premium plan, security review, model-risk validation effort (MRM sign-off is real work), legal fees for fairness attributes, pen test, DR/second region, training, change management, reviewer headcount (the people who will triage cases are a cost, not only a saving).

Fleet formulas check (docs/04): N=40: manual 60+22x40 = 940 OK; Supervisor 309+4x40 = 469 OK (-50.1%); exposure 720 vs 80 (-88.9%) OK; net 90x23-940-720 = 410 OK; 90x40-469-80 = 3051 OK; ratio 7.4 "x7" OK. The arithmetic is right. The structure is wrong (finding 1, 2, 3, 10).

Assumptions a bank finance team will reject:
1. Supervisor marginal cost $4k per extra agent (no basis, contradicts own token numbers).
2. $90k net benefit per effective agent (unsourced).
3. Manual route capped by "review capacity" (a bank can hire).
4. Incident exposure $18k/agent/yr manual vs $2k (no incident history).
5. $15k per launch from 2 FTE x 5 weeks (fine as shape, needs time-sheet data).
6. Zero cost for reviewers, legal, MRM.
7. List DBU price, no commit discount, no Databricks enterprise agreement.
8. "Prevented incident pays a year" is an anecdote, not a forecast.

Proposed sensitivity table (fill with the corrected model; values below are what to compute, not results):
| Driver | Low | Base | High | Report |
|---|---|---|---|---|
| Actions per agent per day | 20k | 100k | 500k | Year-1 and run-rate token cost |
| Tier 2 share | 0.5% | 1.5% | 5% | Tier 2 cost |
| Output tokens Tier 2 | 300 | 600 | 1500 | Tier 2 cost |
| Prompt caching hit rate | 0% | 30% | 60% | Tier 1 cost |
| Judge model | Haiku/Opus | as base | Qwen3.5 on provisioned throughput (fixed cost) | Crossover volume |
| Number of agents N | 3 | 10 | 40 | Governance cost vs manual, crossover N |
| Loaded FTE rate | $4k | $6k | $9k | Run team |
| Launches per year | 5 | 10 | 20 | Onboarding saving |
| Incident frequency x severity | bank history | - | - | Expected loss avoided (bank to supply) |
Show a tornado chart for run-rate and a break-even N. One slide, one video beat.

## 4. Demo readiness
Demo as planned: Step 0 live onboarding of loan-prequal-agent, then 4 incidents (each re-runnable < 1 min), tamper test, stretch multi-agent. "Minutes on stage" is not quantified; competition slots are usually short [organiser to confirm slot length].

Failure modes:
| Area | Failure | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Network | Venue Wi-Fi blocks workspace, model endpoints, SSO | High | Total | Local laptop fallback build; recorded screen capture; mobile hotspot; test on venue network a day before |
| Model latency | Tier 1 / Tier 2 call takes 5-30 s or rate-limits (429) | High | Incident 2 (alert) stalls | Pre-warm; cache judge output keyed by trace hash; provisioned throughput for demo; timeout then show cached verdict marked "replay" |
| Onboarding | Agent reads repo, UC lineage and writes PR live: slow, non-deterministic, tool errors | High | Step 0 fails | Stage progress UI; run the real Onboarding Agent in background, but have each stage output pre-baked and revealed on completion; real PR on a demo repo with token pre-set |
| Databricks | Serverless job / App cold start (minutes), cluster start, App deploy | High | Everything | Keep warm: start 30 min before; use always-on serving endpoint; no job start on stage |
| Drift incident 3 | "Simulated week" needs data and a monitor refresh; Lakehouse Monitoring refresh is not instant | High | Incident 3 can't run live | Replay a pre-generated week; compute drift on a table already loaded; show band and case opening live |
| Fairness incident 4 | Needs sliced stats on enough rows | Med | Case does not open | Pre-load 5-10k decisions with seeded 8 pt gap; deterministic seeds |
| Reset | Reset leaves stale state (paused flags, chain, cases) | Med | Second run diverges | Reset = one script that restores a snapshot (Delta clone / RESTORE VERSION AS OF); test 20 times |
| Tamper test | Editing "one line" in Delta needs write rights that the bank would not allow; hash verify job duration | Med | Weak moment | Use a pre-built "tamper tool" in console that edits the copy; verify runs on 100k rows < 2 s; practise explaining why it is not our own table you edited |
| UI | Console auto-refresh lag, SSO re-login, small text on projector | Med | Visible fumbles | Fixed 1080p layout, big font, no SSO prompt (long-lived session), second screen with terminal |
| LLM non-determinism | Injection payload doesn't trigger the agent on stage | High | Incident 1 fizzles | Scripted "attack replay" mode: inject the pre-recorded agent tool call (agent output fixed, gate and judge real) |
| People | One presenter, one operator, no cue | Med | Pace | Two roles, timed cue card |

Pre-bake vs live:
| Live (real code path) | Pre-baked (reveal) |
|---|---|
| Gate block of the injected tool call (fast lane, deterministic) | Onboarding stage outputs for loan-prequal-agent (real agent run recorded; reveal in sync) |
| Pause switch and case-file creation | Simulated week of data, baselines, sliced fairness table |
| Hash-chain tamper then verify | Tier 2 judge results (cached, labelled) |
| Reviewer sign-off click | Dashboard backing tables |
| Reset button | PR on demo repo |
Rule: anything that calls a frontier model, starts compute, or leaves the room must have a recorded twin.

Fallback plan (levels):
1. Live all green.
2. Replay mode toggle in console: same UI, data from a recorded run, "REPLAY" badge on screen.
3. Laptop-local build (SQLite + local hash chain + stub judge) on a USB stick.
4. Recorded 3-minute screen video of the full demo (not the concept video) with narration.
5. showcase3.mp4 concept video (already exists).
Decision rule: if a step is not green 20 s after start, switch to replay for that step and say so.

Demo runbook skeleton:
```
T-7d  freeze build; tag demo-v1; full run x20, log timings
T-3d  dry run on venue network if allowed; record fallback video of a clean run
T-1d  warm endpoints; pre-load data; snapshot "clean" state; print cue card; charge devices
T-60m warm-up run of all steps; restore snapshot; check model quota and rate limits
T-10m open: console, onboard panel, terminal, backup video; mute notifications; screen 1080p
T0   Step 0 onboard (target <= 3 min incl. narration)  -> checkpoint A
     Incident 1 pause (45 s)                           -> checkpoint B
     Incident 2 alert (45 s)
     Incident 3 drift (60 s, replayed week)
     Incident 4 fairness (45 s)
     Tamper test (45 s)
     Metrics panel + close (30 s)
After: restore snapshot; export logs
Each step: owner, trigger button, expected screen, max wait, fallback switch.
```
Budget: if the slot is 10 min, cut incident 3 or 4 to a recorded clip. [organiser to supply slot length]

## 5. Product / UX gaps
Reviewer console (docs/02 item 8 is one line). Missing:
| Area | Missing | Minimum for competition | Production |
|---|---|---|---|
| Triage queue | Sort, filter, ownership, "what do I do first" | One queue sorted by severity then age; badge for blocked vs alert | Per-team queues, assignment, round-robin |
| Case states | Not defined | Open, Triaged, Contained, Confirmed, False alarm, Closed (+ reopened) | Add Escalated, Awaiting owner, Regulator-reportable |
| SLA timers | Only "time to human < 5 min" metric | Visible clock per case; colour at 50/80/100% | Per-severity SLA, paging, escalation chain, calendar-aware |
| Bulk actions | None | Skip | Bulk close false-alarm groups, bulk mute rule for N hours with approver |
| Explanations for non-technical reviewers | Case file is technical (rule IDs, ms, chain hash) | Plain "What happened / Why it matters / What you can do" box on top; technical detail below | Per-role view (ops, risk, audit); glossary |
| Vietnamese UI | Not mentioned. Reviewers are Vietnamese; regulator wording is Vietnamese | English UI for jury; i18n keys from day 1; Vietnamese case-file summary generated by the judge | Full Vietnamese UI, legal-reviewed regulatory text |
| Evidence handling | Who may see raw vs masked transcript | Masked only | Break-glass unmask with reason, logged in chain |
| Actions available | pause/resume only | Pause, resume, confirm, override with reason | Rollback to previous agent version, quarantine a tool, rule edit via PR |
| Four-eyes | Stated for rule change | Show on resume of a high-severity pause | Configurable |

Agent developer experience ("how does a developer click Onboard"):
| Gap | Recommendation |
|---|---|
| No defined trigger | Three entry points: (1) button in a Databricks App "Supervisor" tab, (2) `supervisor onboard <app-url>` CLI / bundle target, (3) UC tag `supervisor.onboard=true` on the App picked up by a job. Competition: button only |
| Developer inputs | Minimal form: owner, business purpose (1 line), data classification, criticality. Rest inferred and shown for confirmation |
| Permissions | Onboarding Agent needs a service principal with read on repo, App, MLflow, UC lineage. Who grants it? Document grant steps and least privilege |
| Status and errors | Progress per stage, retry, "what I could not find" list. Human-in-the-loop checkpoint after Understand (developer corrects the profile) |
| PR review | Who reviews the PR: the developer or the risk team? Define CODEOWNERS and checks (lint policy YAML, dry-run in sandbox) |
| Re-onboarding | New agent version triggers diff and re-plan; baseline reset rules |
| Opt-out/override | Developer can request a waiver; recorded in chain |

Alert-fatigue controls (none specified):
- Case grouping (same rule, same agent, same hour = one case with count).
- Per-rule rate limit and cool-down; suppression with expiry and approver.
- Severity from a matrix (action reversibility x data class x tier), not from judge score alone.
- Weekly precision report per rule: flags, confirmed, false alarm. Retire rules below a threshold.
- Shadow-mode period measures false alarm before blocking is enabled (already stated; add exit criteria).
- Reviewer feedback ("this was false alarm") feeds Tier 1 threshold tuning and a labelled set.

Reporting for CRO / board:
| Report | Content | Cadence |
|---|---|---|
| CRO dashboard | Agents by risk tier, coverage %, open cases by age, SLA breaches, blocks by rule, false-alarm rate | Live |
| Board pack (1 page) | Agent inventory count, high-risk agents under Decision 33 and their oversight status, incidents, top 3 risks, cost | Quarterly |
| Regulator pack | Per-agent evidence export, chain verification certificate | On demand |
| Model risk | Judge accuracy vs human labels, drift of the judge itself ("watch the watcher") | Monthly |

## 6. Scope risk: docs/08 sprints 1-2 for 4 people, 4 weeks
Verdict: not achievable at full depth. Eleven backlog items include four 2-3 week items per docs/03 (Onboarding Agent 2-3 wk, judge protocol 1-2 wk, console 1-2 wk, gateway 1 wk, tamper log 1 wk, case file 1 wk, drift 1 wk, quality 1 wk, catalogue 1 wk, multi-agent 1 wk). Sum of the docs/03 estimates ~13-16 person-weeks for build-only, plus mock agents, red-team set, demo harness, deck/video finalisation, and Databricks workspace/permission friction. Four people x 4 weeks = 16 person-weeks with no slack, no sickness, no pitch work, and the risk/pitch person is not an engineer. Realistic engineering capacity: ~10-12 person-weeks.

Cut list:
| Class | Items |
|---|---|
| MUST (demo dies without) | 3 mock agents + incident fixtures (item 1, 2); gateway with approved-tools + transfer limit + pause (3); MLflow tracing to UC (4, minimal); Tier 1 + Tier 2 judge for fee-waiver case (6); hash-chained log + tamper check + case file (9); console with queue, case view, sign-off, pause/resume, metrics (10); demo harness + reset + replay mode (11); Onboard Discover + Understand + Plan on ONE agent (5, 8 partial) |
| SHOULD | Drift detector with baseline band (7) on pre-generated week; fairness slicing (7) on seeded data; Instrument step as template-filled PR; Presidio masking UDF; 120-attack red-team run with measured catch rate |
| COULD | Quality judges (groundedness) beyond one scorer; catalogue as YAML manifests (3 manifests are enough); anchor job to write-once store; audit-pack export as PDF; Prompt Guard 2 |
| WON'T (say "December") | Multi-agent combined-transfer check (keep as designed slide, not code); Launch stage automation; OTel collector for non-Databricks agents; NeMo rails; capability catalogue UI; Vietnamese UI; SSO/roles beyond demo user |

Fake with fixtures (declare on slide "demo uses recorded fixtures for X"):
| Fake | How | Honesty label |
|---|---|---|
| Onboarding Agent outputs for loan-prequal-agent | Real code path on one agent; outputs reviewed and cached; reveal staged | "Recorded run, same code" |
| Simulated week of approvals | Generated Delta table with seeded drift and a seeded 8-pt segment gap | "Synthetic data" |
| Tier 2 judge on incident 2 | Cached verdict for the fixed trace | "Replay" badge |
| Anchor to write-once storage | Second Delta table / volume with different permissions | "Production uses object-lock" |
| Reviewer SSO and roles | Single demo user with role switcher | "Production: workspace SSO" |
| Regulator mapping text | Template pending legal | "Draft, legal review pending" |
| Fleet charts | Parametrised model, bracketed inputs | "Illustrative" |
Do not fake: gate blocking, hash chain break, pause switch. Those are the credibility moments.

Suggested 4-week plan:
| Week | Eng 1 (agents) | Eng 2 (gateway/judge) | Eng 3 (onboard/evidence) | Risk/pitch |
|---|---|---|---|---|
| 1 | 3 agents + fixtures + red-team set | Gateway + pause | Registry, tracing, hash log | Policy list, held-out attack set, reg mapping |
| 2 | Seeded data (week, segments) | Tier 1/2 judge | Onboard Discover/Understand | Console wireframes, sensitivity table |
| 3 | Demo harness, reset, replay | Drift + fairness | Plan + PR template, case file | Deck fixes, voice-over, finance model |
| 4 | Rehearse, fallbacks | Measure metrics honestly | Console polish, verify | Final deck, video captions, submission |

## 7. Deliverables critique: deck for a bank jury (slide by slide)
Consistency check passed: 22 slides = docs/07 list; $381k / $309k match docs/04, CLAUDE.md, s19, s20; -50/-89/x7 match video, voice-over, s15; 120/113 = 94% >= 90% target; nine signals, eight of eight, 4m29s, 7 ms same in deck, case file, playbook. Stage names match (6 stages, 5 Watch steps). Tiers match (0/1/2).
Inconsistencies found: ControlArena licence (finding 5); "Vietnam" residency (4); break-even (9); FTE rate (8); playbook has 3 incidents vs 4 (14); docs/08 says "Onboard stages 1-3" for competition while s7/s8/s17 sell all seven artefacts and a launch to shadow mode (the live demo shows PR and dashboard, which are stages 4); s15 "drift caught in 2 hours" vs voice-over "fixed before lunch": consistent in spirit.

| Slide | What a CRO / CTO / CISO pushes back on | Fix |
|---|---|---|
| 1 | "Proposal for discussion" and `[Team name]` look unfinished | Fill name; strong subtitle |
| 2 | "Bank already owns the platform": do they have the right Databricks tier and models enabled? | Add "assumes Mosaic AI Gateway/Foundation Model APIs enabled; to confirm" |
| 3 | Chart is conceptual (16 red blocks). CRO: "show real change cadence" | Label illustrative (done); add the bank's real release data when available |
| 4 | CRO: is Decision 33 interpretation legal advice? Deck says "to be confirmed" in only some places | Add legal-review note on s4 too |
| 5 | CTO: 4-6 weeks is illustrative; "unsupported by the market" is strong when ServiceNow/Microsoft discover agents | Say "no vendor generates the launch pack end to end (our scan, Oct 2026)" |
| 6 | CISO: AI that writes integration code in prod pipelines | Good: PR-only. Add threat model slide for the Onboarding Agent itself |
| 7-8 | CTO: how does "auto-detect" work with permissions? Which repo hosts? | Add prerequisites box (service principal, repo access) |
| 9 | "Zero code from the developer" is a strong claim for native plug point | Soften to "no code for tracing; PR for policy" |
| 10 | Frontier-lab analogy: those labs control the model and the harness; the bank does not | Add caveat; the bank controls the gateway only |
| 11 | CTO: single point of failure, latency inline, who owns the gateway SLO? | Add availability target and failure behaviour (s18 has some) |
| 12 | "One third / one third / one third" is not shown; counts are 4 original, 2 native, 4 copied | Remove claim or compute honestly |
| 13 | CISO: judge sees PII? LLM-as-judge prompt injection (judge reads attacker text)? Judge disagreement | Add judge hardening (structured output, no tools, untrusted-text framing) and judge calibration vs human labels |
| 14 | Regulator: is a hash chain in Delta with anchors "tamper-proof"? Who holds the anchor key? | Name the anchor store (object lock/WORM), key custody, verification procedure |
| 15 | Video is concept with no audio; jury may skip | Add captions or voice |
| 16 | Targets, not results. CRO: "show me one real number" | Present measured numbers from the build on slide 16 |
| 17 | Demo is risky and long (section 4) | Offer a recorded fallback; have a 2-minute cut |
| 18 | CISO: "No customer data leaves Vietnam" contradicts the Claude/GPT endpoints | Reword (finding 4) |
| 19 | Finance: hidden costs, volumes for 3 agents only | Add sensitivity and per-1k-action cost |
| 20 | Mostly brackets. Jury scores empty brackets as no case | Fill with defensible ranges labelled "assumption", not blanks |
| 21 | Dec production candidate with one real agent team: who is it? Dependencies on bank approvals (MRM, legal, security) not on roadmap | Add dependencies and owner on the bank side |
| 22 | Close is fine; add the ask (what do we want from the jury/bank) | Add one explicit ask: pilot team, sandbox access |

Missing slides a bank jury expects: (1) threat model of Supervisor itself ("who watches the watcher" is a Q&A answer, not a slide); (2) measured results; (3) team and delivery plan; (4) risks and what we are not doing; (5) integration with bank's existing GRC/ITSM/SIEM (ServiceNow, SOC); (6) data flow for PII and residency.

## 8. Generators (tried)
| Generator | Result |
|---|---|
| src/deck/build.js | Needs `npm i pptxgenjs` (not installed). With it installed in a scratch dir and node_modules symlinked, it ran: "wrote out.pptx slides: 22", 4.96 MB, same size as assets/Supervisor.pptx. apply_theme.js is vendored in the folder (docs/08 says it is missing; it is present). No package.json: add one with pinned versions |
| src/video/render.py | Needs Python `playwright` (installed in analysis/.venv) and its Chromium. Cached browser in ~/.cache/ms-playwright (chromium_headless_shell-1243) does not match the installed playwright version, so launch failed with the "playwright install" message. Not run further (no system installs). No system `ffmpeg` on PATH (only Playwright's bundled ffmpeg, which is limited and has no libx264 assumption). Full render = 3,264 screenshots at 1080p, then ffmpeg encode |
| Reproducibility gaps | No requirements.txt / package.json / lockfile; render.py has relative frame path `frames/` then ffmpeg step is manual; no Makefile. Add `make deck`, `make video` and a README with exact versions |

## 9. What the handoff gets RIGHT (do not "fix")
- One story across deck, video, voice-over, docs; same numbers and stage names.
- Illustrative labels on every video scene and on figures; targets labelled "design goals, not measured".
- Bracketed placeholders instead of invented bank figures (apart from findings above).
- Vendor claims labelled as claims (market scan); honest "partial fit" ratings.
- Live onboarding as opening is a strong differentiator; PR-only with second approver answers the obvious fear.
- Tiered judge with different model family; cost control via tiers; FinVault used to explain why not a guard model.
- Demo includes four response levels (log, alert, pause, case) and a tamper test.
- Fail-safe and shadow-mode-first design.
- Speaker notes on every slide; sources on most slides.

## 10. Open questions for the bank
1. Official submission date, demo slot length, and whether a live demo with internet is allowed on site.
2. Which of the three tracks (cut off in screenshot) is the entry judged on?
3. Databricks region, cloud (Azure/AWS/GCP), tier, and which Foundation Model APIs are enabled there. Is Vietnam in-country processing required for customer data?
4. Actual DBU contract rate and any committed-use discount.
5. Loaded cost per engineer, per reviewer and per risk analyst at the bank.
6. Real figures: launch effort per agent (time-sheet), agents planned per year, incident history, loss per incident, programme value.
7. Number of agents and daily actions expected in 2027; trace size and retention rules.
8. Who will be the reviewers (team, headcount, hours), and which language do they work in?
9. Existing tools Supervisor must feed: ServiceNow, SIEM/SOC, GRC, ticketing, paging.
10. Which models the bank's own agents use (the judge must be a different family).
11. Does the bank want the evidence log anchored in an existing WORM store, and who holds keys?
12. Which team may be the December shadow-mode pilot, and what approvals (MRM, legal, security) are required before that?
13. Which fairness attributes may legally be sliced?
14. Are the Vietnamese regulatory mappings to be written by bank legal, or by us for review?
