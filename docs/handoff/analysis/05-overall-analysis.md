# 05 · Overall analysis of the Supervisor package

Date: 2026-10-14. Author: supervisor session (synthesis of worker reports 01–04; every finding below points to its source report).
Inputs: handoff bundle (CLAUDE.md, docs/01–08, assets, src) + four worker reports in this folder.

## 1. Verdict in one paragraph

The package is a strong **concept and pitch**. The story is consistent across deck, video and docs. The architecture shape is right: deterministic gate first, tiered judge on another model family, hash-chained evidence, PR-only changes, shadow mode first. It is **not yet a buildable engineering plan** and it is **not yet integration-ready for Techcombank**. The four workers found 92 findings; 31 are High. They cluster into six root causes (section 3). None blocks the competition demo. All of them block a December production candidate unless work starts now, because most are bank-bound (legal rulings, region, identity, network, SIEM) and the bank's clock is slower than the build clock.

## 2. Scorecard

| Area | Score | Why | Report |
|---|---|---|---|
| Problem framing and regulatory spine | 🟢 strong | Brief read correctly; AI Law, Decision 33, MAS cited; honest labels | 03 |
| Product concept (Onboard + Watch) | 🟢 strong | Clear stages, two speeds, independence rules | 02, 04 |
| Deck / video consistency | 🟢 strong | Same numbers and names everywhere | 04 |
| Architecture detail | 🟡 partial | Right shape; gateway source stale, pause undefined, no fail mode, no threat model | 02 |
| Databricks fit | 🟡 partial | Right services; several Preview/Beta limits not known; region not confirmed | 01 |
| Bank integration | 🔴 missing | No IAM, network, SIEM, ITSM, paging, CI/CD, DR, environments, chargeback | 01 |
| Data model | 🔴 missing | Tables named, no schemas; chain concurrency undesigned | 01, 02 |
| Regulatory coverage | 🟡 partial | Misses draft SBV AI circular, PDPL 91/2025, Data Law 60/2024; Decision 33 wording wrong | 03 |
| Judge governance | 🔴 missing | No owner, no eval set, no injection defence, no validation | 02, 03 |
| Business case | 🔴 broken | Fleet model contradicts cost model; break-even math short by ~$109k; residency claim likely false | 04 |
| Demo readiness | 🟡 partial | Good script; no runbook, no fallback, high cold-start/network risk | 04 |
| Scope vs team | 🔴 over | ~13–16 person-weeks of build vs ~10–12 available | 04 |
| Reproducibility of assets | 🟡 partial | Deck builds; video generator fails (Playwright browser, no ffmpeg); no lockfiles | 04 |

## 3. Six root causes (what to fix, not the 92 symptoms)

```
RC1  "Enforcement" is a slide word ──▶ gateway source stale, only MCP covered, pause undefined,
                                        no fail-open/closed rule, no credential brokering
RC2  Evidence trust is assumed    ──▶ writer = trust point, no key owner, no anchor store,
                                        no offline verifier, chain concurrency undesigned
RC3  Judge is ungoverned          ──▶ reads attacker text, no eval set, targets circular,
                                        no owner / validation / change control, family rule unenforced
RC4  Platform limits unknown      ──▶ UC trace Beta limits, no VN region, Qwen3.5 not in SG,
                                        gate host undecided, Lakehouse Monitoring not for GenAI
RC5  Bank edge not designed       ──▶ IAM, network, SIEM, ITSM, paging, CI/CD, DR, envs, data
                                        classification, Vietnamese PII, legacy-agent identity
RC6  Numbers outrun evidence      ──▶ fleet model, break-even, "no data leaves Vietnam",
                                        7 ms / 19 ms / 12 checks / billion decisions unsourced
```

## 4. Top findings (High only, merged and de-duplicated)

| # | Finding | RC | Fix now (competition) | Fix later | Src |
|---|---|---|---|---|---|
| 1 | `mcp-scan` is now `snyk/agent-scan` (scanner, "experimental"); the proxy `invariant-gateway` is dormant since Nov 2025 | RC1 | Write own thin gateway; cite "Invariant Gateway pattern" | — | 02 |
| 2 | Gate covers MCP only; Python tools, REST, SQL have no interception point | RC1 | `@supervised_tool` SDK wrapper + MCP proxy; say "cooperative" on the slide | Egress allow-list + credential brokering (H1) | 02 |
| 3 | "Pause" has no mechanism; no agent states; no fail-open/closed rule | RC1 | Define RUNNING / SHADOW / PAUSED / QUARANTINED; fail-closed for money, credit, PII export | Jobs cancel, serving traffic-to-zero, hold/release for payments | 02, 01 |
| 4 | Gate host undecided; Databricks App is the wrong host; 50 ms budget leaves no spare for Presidio + Prompt Guard | RC4 | Model Serving with route optimization; Tier 0a rules (<5 ms) sync, Tier 0b classifiers async; publish p50/p95/p99 | Sidecar option for non-Databricks agents | 01, 02 |
| 5 | Evidence chain: no key owner, no signature, no anchor target, no independent verifier | RC2 | Linear chain + signed head; `supervisor-verify` CLI; hashes only on chain, PII off-chain | Notary key in Key Vault HSM / KMS; immutable blob anchor; daily Merkle root; VN-licensed signature | 02, 03 |
| 6 | UC trace storage needs MLflow ≥ 3.14, 200 traces/s default, no Private Link storage | RC4 | Week-1 spike; own `agent_event` table as fallback and evidence source | Quota increase; confirm Private Link stance | 01 |
| 7 | No Databricks region in Vietnam; Qwen3.5 122B not listed in Singapore; "no customer data leaves Vietnam" likely false | RC4, RC6 | Reword to "runs in the bank's workspace; residency per region + legal sign-off"; mask first; log region per judge call | Legal ruling on SG processing; Qwen3-Next 80B SG or bank-hosted open model | 01, 03, 04 |
| 8 | Judge prompt injection undefended; no labelled eval set; 90% / 5% targets measured on our own attacks | RC3 | Data-wrapped input, JSON-only output, no tools; held-out attack set written by a different person; report measured numbers with CI | Golden set 300–500 items VN+EN; challenger model; MRM validation | 02, 03, 04 |
| 9 | Judge has no owner, inventory entry, validation plan or change control | RC3 | Name owner on a slide; "Judge Model Card" stub | Full MRM pack; re-validation triggers | 03 |
| 10 | Draft SBV circular on AI in banking not in the package (24 h incident report, 5-day remediation, bias monitoring, model management) | — | Add regulatory-clock fields to case file; map duties → artefacts | Track final text weekly | 03 |
| 11 | Decision 33 wording is "without human inspection, approval or control **before execution**" — a pause is not pre-execution review | — | Fix docs/01 + deck s4; claim = "proves the human gate is real" | Pre-execution approval step in agent workflows | 03 |
| 12 | PDPL 91/2025 (in force 1 Jan 2026), Data Law 60/2024 + Decree 165/2025, Cybersecurity Law 116/2025 not covered | — | Cite correctly; note 5% revenue fines for cross-border breach | Transfer impact assessment, record of processing, DSAR hook, retention by class | 03 |
| 13 | No IAM / network / SIEM / ITSM / paging / CI-CD / DR / environment design | RC5 | One-page integration map (from report 01 §4) on a slide | Build each adapter in Dec–H1 | 01 |
| 14 | Legacy / black-box agents are the common first case, share service accounts, have no identity binding | RC5 | Registry gets `identity_binding` + per-agent coverage score | Proxy log schema; API-gateway correlation | 01 |
| 15 | Data model unspecified; hash-chain concurrency undesigned | RC2 | Freeze v0 DDL (report 01 §6) in week 1; one writer per lane; verdicts via queue | Lakebase CAS heads; schema versioning | 01, 02 |
| 16 | No message bus exists; "streaming over the bus" has no producer | RC1 | Derive stream from gateway events; one pattern = split-payment aggregate limit | General patterns H2 2027 | 02 |
| 17 | Onboarding Agent reads repos: secret exposure + injection from repo text | RC3 | Read-only per-repo token, secret scrub, repo = untrusted, pydantic output with evidence pointers, libcst codemod for PRs | — | 02 |
| 18 | No threat model for the supervisor; kill-switch authority undefined | RC1 | Threat table (report 02 §3.6) → doc 09 + one slide; pause = 1 person, resume = 2 | Break-glass with expiry | 02, 03 |
| 19 | Fleet model: Supervisor cost 309 + 4N ignores ~$46k/agent token cost; "−50% / ×7" fails; break-even sums to $200k vs $309k | RC6 | Rebuild with per-agent variable cost; show crossover N; sensitivity table | Replace with bank figures | 04 |
| 20 | Fairness attributes unresolved; slicing is a new data purpose | — | Design for gender, age band, province, interaction language; never infer ethnicity/religion/health | DPO + counsel sign-off before UI | 03 |
| 21 | Scope: ~13–16 person-weeks vs ~10–12 available | — | Cut list (report 04 §6); fixtures with on-screen labels | — | 04 |
| 22 | Demo: no runbook, no fallback; cold starts, network, non-deterministic injection | — | Replay mode, snapshot reset, 5-level fallback, T-7d runbook | — | 04 |
| 23 | Reviewer console, "click Onboard" entry point, alert-fatigue controls not specified | RC5 | 2-page console spec, 3 screens; button-in-App trigger | Vietnamese UI, ITSM sync, CRO report | 04 |
| 24 | Prompt Guard 2 is Llama-licensed (breaks the MIT/Apache rule) and lists no Vietnamese; Presidio has no Vietnamese recognisers | — | Note exception; add VN regex recognisers (CCCD, phone, account) | Vietnamese test set; fallback to Tier 1 | 02, 01 |

Medium and Low findings stay in reports 01–04 (68 items). Documentation fixes are listed in section 7.

## 5. Conflicts between workers (resolved)

| Topic | Report A | Report B | Resolution |
|---|---|---|---|
| In-region Tier 2 model | 03: "Qwen on provisioned throughput" | 01: Qwen3.5 122B not seen in Singapore; Qwen3-Next 80B is | Plan says "in-region open-weight judge" and names the model after the bank confirms region |
| Gate host | 01: Model Serving endpoint | 02: FastAPI / Envoy ext_authz service | Same thing: a thin FastAPI service, deployed on Model Serving (route optimization) or as a sidecar |
| Tier 0 latency | 01: sync vs async check sets | 02: Tier 0a vs 0b | Same design; use the 0a/0b names |
| Dec target | Handoff: production candidate in Dec | 01/03: bank-bound items take weeks; Decision 33 deadline 1 Mar 2027 for new systems | Dec = shadow pilot starts on one agent; Feb 2027 = hardened production candidate (see plan) |

## 6. What the handoff gets right (keep)

- Gate as a service, never a Delta round-trip; model proposes, deterministic policy decides.
- Tiered judge on another family; guard models as pre-filters only; FinVault numbers used honestly.
- Hash chain + anchors, with the honest note that Delta time travel is not proof.
- PR-only changes, second approver, Onboarding Agent runs under Watch.
- Shadow mode first; illustrative labels; bracketed placeholders; vendor claims labelled.
- Red-team incident set before checks; OTel as the contract.
- One consistent story across deck, video, voice-over, docs.

## 7. Documentation fixes (small, do before submission)

| File | Change | Src |
|---|---|---|
| CLAUDE.md, docs/03 | "mcp-scan proxy pattern" → "Invariant Gateway pattern (dormant); own thin gateway" | 02 |
| CLAUDE.md, docs/03 | "MIT/Apache only" → add Llama community licence exception for Prompt Guard 2, pending legal | 02 |
| docs/03, 06 | ControlArena = MIT (confirmed); Presidio URL → `data-privacy-stack/presidio`; PyRIT → `microsoft/PyRIT` | 02 |
| docs/01, deck s4 | Decision 33 wording; transition dates 1 Mar 2027 / 1 Sep 2027 | 03 |
| docs/01 | Add draft SBV AI circular, PDPL 91/2025, Data Law 60/2024, Cybersecurity Law 116/2025 | 03 |
| docs/04, deck s19–20, video part 3 | Rebuild fleet model; print output-token assumptions; fix break-even; sensitivity | 04 |
| deck s18, playbook | Remove "no customer data leaves Vietnam" | 04 |
| deck s12, s13, s14, s16 | Source or remove "12 checks", "19 ms", "7 ms", "billion decisions" | 04 |
| deck s1, s22, s20 | Fill `[Team name]`, replace brackets with labelled ranges | 04 |
| assets/supervisor-playbook.html | Mark "earlier draft" or regenerate (3 incidents, no Onboard) | 04 |
| src/ | Add package.json + requirements.txt + Makefile; note `playwright install` | 04 |
| new docs/09 | Threat model of the supervisor | 02 |
| new docs/10 | Integration map + v0 data model | 01 |

## 8. Consolidated questions for the bank (top 15 of 56)

Ordered by how much the answer changes the plan.

1. Which cloud and region host the Databricks workspace? Which Foundation Model APIs and Unity Gateway are enabled? (01, 04)
2. May masked customer data be processed in Singapore? Who rules, and when? (01, 03)
3. Official submission date, demo slot length, live internet on site, and the real track names. (03, 04)
4. Which team is the December shadow pilot? Which approvals (MRM, legal, security) must come first? (04)
5. Which agent frameworks and hosts exist today (Mosaic, LangGraph, MCP, Java/.NET, SaaS copilots)? (01, 02)
6. Is there an API gateway or ESB in front of T24/Temenos, cards and CRM that the gate can sit behind? (01)
7. Fail-open or fail-closed per action class, and who approves that list? (01, 02, 03)
8. Who may pause, who may resume a production agent? Is four-eyes on resume acceptable? (02, 03)
9. Who owns the judge model, and which team validates it independently? (03)
10. Which fairness attributes may be sliced? Is a DPIA needed? (03)
11. Which SIEM, ITSM, pager, chat, source control and CI are standard, and who owns the integration accounts? (01)
12. Retention periods for incident records, logs, case files; legal-hold process; who holds signing keys; existing WORM store? (01, 02, 03)
13. Peak actions per second, acceptable p99 from the gate on payment paths, reviewer capacity in cases per day. (02)
14. Real figures: launch effort per agent, agents per year, incident history, DBU contract rate, loaded FTE rates. (04)
15. Has the SBV AI circular been signed? Who in the bank tracks it? (03)
