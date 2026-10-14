# 07 · Choosing the judge model, and designing for customer data in traces

Date: 2026-10-14. Answers three questions from the sponsor. Section 2 (Jev) and the benchmark table in 1.4 are filled from worker report 07a.

## 1. How to choose the "most optimal" agent to supervise or judge other agents

### 1.1 First rule: there is no single best judge. There is a best judge **per tier, per agent, per date**.

```
Tier 0  rules + classifiers     ─▶ no LLM. "Optimal" = lowest latency, zero cost, 100% deterministic
Tier 1  cheap monitor on 100%   ─▶ optimal = best recall per dollar at p95 < [bank] s, async
Tier 2  strong judge on flags   ─▶ optimal = best agreement with human reviewers on the bank golden set
Tier 3  human                   ─▶ the only judge that counts legally (Decision 33, SBV draft)
```

Re-pick every quarter and on every model-version change. The judge is a governed model (analysis 03 §3).

### 1.2 Hard constraints (filters, not scores)

| Constraint | Rule | Why |
|---|---|---|
| Family independence | `judge.model_family ≠ agent.model_family` for every agent the judge watches; enforced in registry + CI | Shared blind spots and shared jailbreaks |
| Region and retention | Served in the bank's Databricks region (or bank-hosted); zero-retention terms in writing | PDPL 91/2025, Data Law 60/2024 |
| Residency on customer data | If the trace still holds customer data after masking → in-region or bank-hosted model only | Cross-border fines up to 5% of revenue (reported) |
| Version pinning | A pinned model version (provisioned throughput or bank-hosted weights). No "latest" alias | Re-validation triggers |
| Structured output | Must return a JSON schema reliably (score, label, evidence spans) | Judge injection defence |
| Vietnamese | Must score the Vietnamese half of the golden set within [bank] points of the English half | Traces are Vietnamese |
| Licence | For open weights: licence acceptable to bank legal (Llama community licence is an exception to log) | Sourcing rule |

### 1.3 Scoring (after the filters)

Build a **bank golden set** first (analysis 03 §3): 300–500 labelled traces per risk category, Vietnamese + English, held out from prompt tuning, labelled by two reviewers with adjudication. Then score each candidate:

| Criterion | Weight (proposal) | Metric |
|---|---|---|
| Catch rate on planted incidents | 30 | TPR at the false-alarm rate the reviewers can absorb |
| False-alarm rate on benign traces | 25 | FPR at the chosen threshold; cost = reviewer minutes |
| Agreement with humans | 15 | Cohen's κ on severity label |
| Robustness to judge injection | 10 | Share of canary attacks that move the score |
| Stability | 5 | Variance over 5 runs of the same trace |
| Cost per 1k traces | 10 | Tokens × price, after prefix caching |
| Latency | 5 | p95 at expected batch size |

Pick the top model per tier. Keep the runner-up as the **challenger**: it scores a 5% sample; log disagreement; swap when the challenger wins two quarters in a row.

### 1.4 Public benchmarks to use as a pre-filter (never as the final answer)

Filled from worker report 07a (see that file for URLs). Public benchmarks tell you which models to put on the short list. Only the bank golden set tells you which one to run.

### 1.5 What "supervisor agent" means in practice

The supervisor is not one model. It is a **protocol** (ControlArena wording): rules first, a cheap monitor on everything, a strong judge on the suspicious slice, defer-to-trusted when they disagree, shut down after repeated suspicion. The "optimal agent to supervise" is the cheapest protocol that meets the bank's catch-rate and reviewer-capacity targets on the golden set. That is a measured curve (safety vs usefulness), not a model name.

Practical starting short list for the bank (must be re-checked against the region table from spike C):

| Tier | Start with | Challenger | Note |
|---|---|---|---|
| 1 | Claude Haiku 5.5 (if agents are not Claude) or GPT-5.4 mini | open-weight small model in-region | 100% async; prefix cache the policy text |
| 2 | In-region open-weight model (name after region confirmed) for traces with customer data | Claude Opus 5.5 / GPT-5.5 on masked digests only | Family ≠ agent family |
| 0 | Rules + VN regex + Presidio | Prompt Guard 2 (licence exception, weak on Vietnamese) | Deterministic |

## 2. "Jev" decisioning agent

Verified by worker 07a (web, 2026-10-14; secondary sources, vendor page not read):

| Item | Finding |
|---|---|
| What it is | Jev, from TypeSafe AI, early access since 15 Sep 2026. A small "decision model": takes a state plus fixed questions, returns typed answers (yes/no, choice, numeric score) with probabilities. It does not write text. |
| Does it judge agents? | No source says so. Named use cases: routing, escalation, retries, risk checks, fraud flag, loan "needs more checks". |
| Deployment | Hosted API by waitlist. No self-host, on-prem or Databricks option found. Underlying model undisclosed. |
| Pricing / speed | Third-party figures only (~$0.04 per 1M input tokens; 70–500 ms per decision = vendor claim). Not verified. |
| Bank customers | None named. |

Fit for Supervisor:

```
Tier 0b  "does this event need review? yes/no"   ─▶ possible cheap pre-filter (if hosted-only is acceptable)
Tier 1   read the transcript, find the problem   ─▶ NOT a fit (does not read reasoning or write a rationale)
Tier 2   strong judge with evidence spans         ─▶ NOT a fit
Gate     deterministic block                      ─▶ NOT a fit (probabilistic, hosted)
```

Blockers today: hosted-only (fails D7 residency on customer data unless the input is a PII-free digest), no version pinning seen, no independent evaluation, no Vietnamese evidence. Recommendation: put it on the Tier 0b candidate list for Phase 3, test it on the bank golden set with digest-only input, and do not build on it before then. Rule for any third-party decisioning agent in this role: it can be a **candidate judge** or a **candidate Tier 0 rules engine**, but it must pass the filters in 1.2, it must not replace the deterministic gate, and its own decisions must be logged in the evidence chain like any other judge. A vendor model that cannot be pinned, run in-region, or scored on the bank golden set is excluded by the filters, not by preference.

## 3. Design for customer data in traces

Assume every trace holds customer data (name, CCCD, account, balances, chat text). Design so the supervisor still works when it may not see it.

### 3.1 Data flow with privacy stages

```
agent ──raw──▶ [1] capture at source ──▶ [2] classify + mask ──▶ [3] tiered stores ──▶ [4] judges ──▶ [5] evidence
                 (SDK / proxy)            (Tier 0b, in-region)     raw | masked | digest   masked only    hashes only
```

| Stage | Rule | Mechanism |
|---|---|---|
| 1 Capture | Capture the minimum: tool name, args hash, masked args, result digest; raw payload only when the policy for that agent needs it | SDK / proxy config per agent (`capture_level: digest / masked / raw`) |
| 2 Mask | Mask before storage, not after. Vietnamese recognisers (CCCD/CMND, phone, tax code, account, card, name lists) + Presidio; deterministic pseudonyms (HMAC with a rotating key) so the same customer links across events without the real ID | Masking UDF in the gate path (Tier 0b) and in the ingest job |
| 3 Store | Three stores with different access: `raw` (restricted group, short TTL, column masks), `masked` (operations, 12 months), `digest` (metrics, long) | UC catalogs/schemas, column masks, row filters, tags `classification=` |
| 4 Judge | Judges read **masked** text only. Tier 2 on anything with residual customer data = in-region or bank-hosted model. Log `region`, `model_version`, `mask_version` per call in the verdict row | Routing rule in the judge service; policy hash in verdict |
| 5 Evidence | Chain holds hashes + masked excerpts, never raw PII. Raw deletion (DSAR, TTL) does not break the chain because the hash stays | `evidence.chain` schema (analysis 01 §6) |

### 3.2 What a reviewer sees

| Role | Sees | Unmask |
|---|---|---|
| Reviewer | Masked transcript, pseudonym IDs, judge rationale | No |
| Approver | Same + agent owner contact | Break-glass with reason, two approvers, logged in chain, expires |
| Auditor | Masked + chain verification | No |
| DPO | Access log, record of processing | — |

### 3.3 Controls list (put into Phase 2 data-protection workstream)

1. Record of processing for Supervisor itself (purpose: oversight; lawful basis: legal obligation / legitimate interest — counsel to confirm).
2. Transfer impact assessment on file before any out-of-region judge call, even on masked data.
3. Retention per class: raw 90 d [bank], masked 12 m [bank], chain ≥ 5 y [bank], case files per incident-record rule.
4. DSAR hook: find by pseudonym → delete raw → chain stays valid.
5. Fairness slices run on hashed IDs in a restricted schema; cells under n = 30 suppressed.
6. Masking quality is a tested metric: VN PII recall ≥ [bank] on a labelled set; a masking miss is an incident.
7. Judge prompts never include free-text customer data beyond the masked excerpt needed; use a structured digest (tool, amount band, counterparty type, policy IDs).
8. Demo and UAT use synthetic customers only; the generator lives in the repo.

### 3.4 Trade-off to state openly

Masking lowers judge accuracy on some cases (e.g. a name-based social-engineering attempt). Measure the gap on the golden set with and without masking. Where the gap matters, the answer is an in-region judge on less-masked data with a logged legal basis, never an out-of-region judge on raw data.
