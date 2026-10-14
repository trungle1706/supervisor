# 06 · Development plan: from handoff to a product integrated with Techcombank and Databricks

Date: 2026-10-14. Builds on docs/08 and on analysis 01–05. Dates are proposals; bank-bound dates are marked ⏳.

## 1. Goal and end state

End state (H2 2027): any agent the bank runs, on Databricks or not, can be onboarded in under a day, is watched on 100% of actions (or the gap is logged), can be paused by one person and resumed by two, and every incident produces a Vietnamese case file with an offline-verifiable evidence chain that answers SBV, Decision 33 and PDPL questions. Supervisor itself is a governed model in the bank's inventory, feeds the SOC and ITSM, and deploys through the bank's CI/CD.

## 2. Phases and gates

```
Phase 0        Phase 1              Phase 2                 Phase 3                 Phase 4
Decide + spike Competition build    Shadow pilot →          Scale-out               Advanced
14–20 Oct      20 Oct – 14 Nov ⏳   production candidate    H1 2027                 H2 2027
               (4 weeks)            Dec 2026 – Feb 2027     (Mar – Jun)             (Jul – Dec)
     │              │                     │                       │                     │
   G0: design     G1: demo passes       G2: pilot agent        G3: 3+ agents          G4: catalogue
   decisions      runbook ×20,          in shadow, SIEM +      enforced, MRM          open, general
   signed,        measured catch/FA     paging live, chain     validated, regulator   multi-agent,
   bank asked     numbers on slide      anchored, legal        pack accepted by       in-house monitor
   15 questions                         rulings on file        internal audit
```

| Gate | Exit criteria (all must hold) |
|---|---|
| G0 | 12 design decisions (section 3) recorded; v0 DDL frozen; UC-trace + gate-latency + region spikes done; 15 questions sent to the bank |
| G1 | Demo runbook passes 20 consecutive runs; replay fallback works offline; measured catch rate and false-alarm rate (held-out set) shown on slide 16; deck fixes in 05 §7 done; submission filed |
| G2 | One real agent in shadow mode ≥ 4 weeks; false-alarm rate below reviewer capacity; evidence chain anchored to bank WORM store and verified offline; SIEM + paging live; legal rulings on region and fairness on file; judge owner named and golden-set report v1 |
| G3 | Blocking enabled on ≥ 3 agents incl. one payments or credit agent; credential brokering live; MRM validation signed; regulator pack exported and accepted by internal audit; DR drill passed; Vietnamese case files |
| G4 | Product teams add capabilities without the core team; general multi-agent patterns; simulation sandbox; fine-tuned in-house monitor in Tier 1 |

## 3. Design decisions to take at G0 (replace the handoff where they differ)

| # | Decision | Choice | Why | Src |
|---|---|---|---|---|
| D1 | Gateway | Own thin FastAPI service; hosted on Model Serving (route optimization) or as sidecar; three enforcement points (MCP proxy, `@supervised_tool`, egress proxy later) | mcp-scan is a scanner now; Invariant Gateway dormant | 02, 01 |
| D2 | Tier 0 split | 0a = rules, limits, allow-list, sync, < 5 ms; 0b = Presidio + injection classifier, async, high-risk tools only; publish p50/p95/p99 | 50 ms budget has no spare otherwise | 01, 02 |
| D3 | Agent states + fail mode | RUNNING / SHADOW / PAUSED / QUARANTINED; fail-closed for money, credit, PII export; fail-open + alert for read-only and chat; unknown = closed; 2 s hard timeout | No rule exists today | 02 |
| D4 | Pause / resume authority | Pause: any on-call reviewer, one click. Resume: reviewer + agent owner. Break-glass: two approvers, auto-expiry. All in chain | Kill switch undefined | 02, 03 |
| D5 | Evidence chain | Linear chain by logical `seq`, canonical JSON hash, one writer per agent lane; signed head every 15 min by a notary key (Key Vault HSM / KMS); anchor to immutable blob; daily Merkle root; offline `supervisor-verify` CLI; PII off-chain | Writer alone proves nothing | 02, 03 |
| D6 | Judge hardening + governance | Data-wrapped input, no tools, JSON-only output; registry enforces model family ≠ agent family (CI + runtime); eval sets: planted, benign, judge-injection, held-out; judge has owner, model card, re-validation triggers | RC3 | 02, 03 |
| D7 | Residency | Mask before any judge call; Tier 2 on customer data = in-region open-weight model (name after region confirmed) or bank-hosted; log region per call; no claim of "in Vietnam" | No VN region | 01, 03, 04 |
| D8 | Trace store | MLflow 3 → UC tables where it works; own `agent_event` table (OTel-shaped) is the read model for Watch and the source for evidence | UC trace limits, Beta | 01 |
| D9 | Drift | Scheduled Delta job over `agent_event` + metrics tables, baseline band per agent version; Lakehouse Monitoring optional view | Not confirmed for GenAI | 01 |
| D10 | Multi-agent | Stream derived from gateway events; `caller_agent_id` header mandatory; one pattern: split-payment aggregate limit | No bus exists | 02 |
| D11 | Policy language | YAML authored by risk staff and the Onboarding Agent; compile to Cedar in H1 2027; stateful limits in gateway code | Testable now, analysable later | 02 |
| D12 | Onboarding Agent safety | Read-only per-repo token per run; gitleaks scrub before LLM; repo text untrusted; pydantic profile with file:line evidence; PR by libcst codemod + templates; never auto-merge | Repo access = attack surface | 02 |

## 4. Phase 0 (14–20 Oct): decide and spike

| Day | Task | Owner | Output |
|---|---|---|---|
| 1 | Record D1–D12 in docs/09 (threat model + decisions) | Supervisor eng | docs/09 |
| 1 | Send the 15 questions (05 §8) to the bank sponsor | Risk/pitch | email + tracker |
| 1–2 | Freeze v0 DDL from 01 §6; add `identity_binding`, `coverage`, `schema_version`, `policy_hash` | Supervisor eng | `schema/v0.sql` |
| 2–3 | Spike A: MLflow 3 traces → UC in the bank workspace (version, grants, throughput, Private Link) | Platform eng | 1-page result |
| 2–3 | Spike B: FastAPI gate on Model Serving with route optimization; measure p50/p95/p99 with 20 rules | Supervisor eng | numbers for slide 13 |
| 3 | Spike C: list models actually enabled in the workspace region; retention terms per model | Platform eng | table for D7 |
| 3–5 | Rebuild fleet model with variable per-agent cost, crossover N, sensitivity; fix break-even | Risk/pitch | docs/04 v2 |
| 4–5 | Fix documentation items (05 §7); add docs/10 integration map | All | PR |
| 5 | G0 review | Team | go / no-go per decision |

If the bank workspace is not available in week 1, run spikes A–C on a trial workspace and label results "trial, re-measure in bank".

## 5. Phase 1 (20 Oct – 14 Nov ⏳): competition build

Scope rule: MUST items are real code paths. SHOULD items may use seeded data. COULD items only if MUST is green by week 3. WON'T items appear as design slides only, labelled "December".

| Class | Items |
|---|---|
| MUST | 3 mock agents + incident fixtures; gateway (approved tools, transfer limit, pause, fail mode); tracing → UC + `agent_event`; Tier 1 + Tier 2 judge (hardened) on the fee-waiver case; evidence chain + signed head + tamper check + `supervisor-verify`; case file with SBV 24 h clock; console (queue, case, sign-off, pause/resume, metrics); Onboard Discover + Understand + Plan on ONE agent; demo harness with snapshot reset + replay mode |
| SHOULD | Drift band on a pre-generated week; fairness slices on seeded data (gender, age band, province, language); Instrument = template-filled PR; Presidio + VN regex masking UDF; 120-attack held-out run with measured numbers; change-event trigger (prompt diff → re-run policy suite) for track A |
| COULD | Groundedness scorer; 3 catalogue manifests; anchor job to a second-permission volume; audit-pack PDF; Prompt Guard 2 on CPU endpoint |
| WON'T | Multi-agent code (design slide + one scripted scenario at most); Launch automation; OTel collector; NeMo rails; catalogue UI; Vietnamese UI; SSO roles beyond demo user |

Week plan (4 people; risk/pitch is not an engineer):

| Week | Eng 1 · agents + demo | Eng 2 · gateway + judge | Eng 3 · onboard + evidence + console | Risk / pitch |
|---|---|---|---|---|
| 1 (20–24 Oct) | 3 agents, registry entries, incident set v1 | Gateway D1–D3, pause, fail mode, latency numbers | Registry + `agent_event` + chain writer + verify CLI | Policy list; held-out attack set (written alone); reg mapping incl. SBV draft |
| 2 (27–31 Oct) | Seeded week + segment data; attack replay mode | Tier 1/2 judge hardened; family check; eval harness | Onboard Discover + Understand (pydantic, evidence pointers) | Console wireframes; fleet model v2; deck fixes |
| 3 (3–7 Nov) | Demo harness, snapshot reset, replay toggle | Drift job + fairness slices; measured catch/FA | Plan + PR template; case file + 24 h clock; console 3 screens | Voice-over + captions for video; finance slide; threat-model slide |
| 4 (10–14 Nov) | 20 runbook runs; fallback video; venue test | Final measurements; judge model card stub | Console polish; audit pack; docs 09/10 | Final deck; submission; Q&A pack |

Demo honesty rules (from 04): never fake the gate block, the pause switch or the chain break. Every fixture is labelled on screen. Switch a step to replay if not green after 20 s.

## 6. Phase 2 (Dec 2026 – Feb 2027): shadow pilot → production candidate

The handoff puts "production candidate" in December. The bank-bound items below make February realistic; December is when the pilot **starts**. Decision 33 gives new systems until 1 Mar 2027 ⏳ (counsel to confirm whether the pilot counts).

| Workstream | Deliverables | Depends on bank for |
|---|---|---|
| Pilot agent | Estate survey (3–5 teams); pick one agent; onboard it from its last 90 days of traces; shadow mode ≥ 4 weeks; false-alarm report | Pilot team, repo read token, SP grants |
| Identity | SCIM groups (reviewers, approvers, owners, auditors, admins); 5 service principals; OAuth M2M; no PATs; evidence-writer SP cannot edit | Entra/AD admin |
| Network | Diagram with the network team; private ingress; egress allow-list; Private Link stance on trace storage | Network team |
| Evidence | Notary key in Key Vault HSM / KMS; anchor to bank WORM store; daily Merkle root; nightly immutable copy; `supervisor-verify` in the audit pack | Security team key custody; storage team |
| SOC + ops | JSON/CEF events to SIEM via change feed; heartbeat + dead-man alert; Teams/email/pager webhook with ack write-back | SIEM and pager owners |
| Change mgmt | DAB targets dev/uat/prod; three catalogs; CODEOWNERS on policy YAML; signed commits; policy rollback | Source-control and CI owners |
| Data protection | Classification → UC tags; column masks; VN PII recognisers; retention per class; legal-hold flag; record of processing; transfer impact assessment; DSAR hook | DPO, counsel |
| Judge governance | Owner named; inventory entry; golden set v1 (300–500 items VN+EN); stability + challenger report; change-control procedure | MRM function |
| Regulatory | Case file v2: Vietnamese + English, SBV 24 h / 5-day clocks, pre-filled report draft; Decision 33 mapping with official Appendix text; SBV AI circular duty → artefact map | Compliance, counsel |
| Launch stage | Red-team pack in sandbox, baseline capture, go/no-go report, rule-by-rule enforcement switch | — |
| DR + fail mode | Two gate instances; local policy cache; kill drill; Delta deep clone per DR tier | DR tier decision |
| Security review | Circular 09/2020 checklist: security classification, pen test, named admin accounts, SBOM, pinned deps | CISO office |

Team for Phase 2: the 4 competition people + 1 platform/Databricks engineer + 0.5 security engineer + named bank owners (DPO, MRM, SOC, network). Without the bank owners, Phase 2 slips.

## 7. Phase 3 (H1 2027): scale-out

| Item | Detail |
|---|---|
| Enforcement | Blocking on; credential brokering + egress proxy so bypass is impossible; YAML → Cedar compile; hold/release for irreversible payment actions |
| Plug points | `supervisor-sdk` (trace, gate, identity); OTel collector for non-Databricks agents; sidecar/reverse proxy; proxy log schema for black-box agents; per-agent coverage score on console |
| Agents | Payments and credit agents onboarded; API-gateway correlation by `trace_id` with core banking calls |
| Console | Vietnamese UI; ITSM two-way sync; alert grouping, rate limits, suppression with approver; CRO dashboard; quarterly board pack |
| Regulatory | Regulator export pack (Decision 33, SBV circular, MAS); VN-licensed digital signature on daily root; customer-rights rule pack (AI notice, explanation, human review) |
| Governance | MRM independent validation signed; judge-vs-human agreement metric monthly; retire-agent stage in Onboard |
| Catalogue | Capability manifests open to product teams; policy packs per product |
| Vendor PoCs | Security gateway in front; registry suite above; both via OTel-in / case-files-out contracts |

## 8. Phase 4 (H2 2027): advanced

General multi-agent pattern detection over gateway-event streams; simulation sandbox for agent groups; containment playbooks with human approval; fine-tuned in-house Tier 1 monitor (e.g. Qwen 4B on bank incidents) with its own validation; onboarding for agents outside Databricks via the sidecar path.

## 9. Critical path and bank dependencies

```
Region/cloud answer ──▶ model list ──▶ D7 residency ──▶ Tier 2 design ──▶ judge golden set ──▶ MRM validation (G3)
Legal: SG processing ──┘                                                   
Pilot team named ──▶ estate survey ──▶ adapters ──▶ shadow mode ≥ 4 wk ──▶ G2
Entra/SP grants ──▶ repo read token ──▶ Onboarding Agent on real agent
Key custody decision ──▶ notary key ──▶ anchors ──▶ offline verify ──▶ audit acceptance (G3)
SIEM/pager owners ──▶ event schema ──▶ live feed ──▶ G2
```

Rule: every bank dependency has a named owner and a date in the tracker. The two slowest are legal rulings (region, fairness) and network. Ask in week 1.

## 10. Risk register (top 10)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Bank workspace or SP access not granted before Phase 1 ends | High | Demo on trial workspace; results labelled | Ask day 1; trial workspace fallback |
| 2 | Live demo fails on venue network or cold start | High | Jury sees nothing | Replay mode, local build, recorded run (04 §4) |
| 3 | False-alarm rate too high in shadow mode | Medium | Pilot stalls; reviewers reject | Calibrate on benign traces; reviewer feedback loop; threshold per agent |
| 4 | Legal rules out SG processing of masked data | Medium | Tier 2 limited to in-region open-weight model | D7 already assumes it; measure open-weight judge quality early |
| 5 | SBV circular final text differs from draft | Medium | Case-file fields change | Field-level config; track weekly |
| 6 | Gate latency above agent-team tolerance | Medium | Teams refuse the gate | 0a/0b split; async for low-risk; publish p99 |
| 7 | Enforcement stays cooperative (no credential brokering) | Medium | Bypass possible; weak claim | Say so on slides; brokering in Phase 3 critical path |
| 8 | Judge fooled by injection in traces | Medium | Missed incidents | D6 controls; canary tests in CI |
| 9 | Scope creep in Phase 1 | High | Nothing finished | Cut list enforced at weekly review |
| 10 | Business case rejected by finance | High | Loses the pitch | Fleet model v2, sensitivity, bracketed inputs |

## 11. First actions (this week)

1. Record D1–D12 and send the 15 questions. (Day 1)
2. Freeze v0 DDL. (Day 2)
3. Run spikes A–C. (Days 2–3)
4. Rebuild the fleet model. (Days 3–5)
5. Apply the documentation fixes in 05 §7. (Days 4–5)
6. Hold G0. (Day 5)
