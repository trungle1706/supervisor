# 03 · Regulatory, model-risk, data-protection and governance gaps
Lens: Vietnam first, then regional. Date: 2026-10-14. Author: worker agent (not legal advice; bank counsel must confirm).
Tags: VERIFIED = seen in a source I fetched or searched (secondary law-firm/press unless stated). ASSUMED = my judgement or industry practice.

## 1. Verdict
The handoff has the right regulatory spine (AI Law, Decision 33, MAS) but misses the rules that bite first. Four items matter most:
(a) a **draft SBV circular on AI in banking** (model management, logging, 24-hour incident report, bias monitoring, human review of disputed decisions) that is the real compliance target;
(b) the **2025 Personal Data Protection Law (91/2025/QH15)**, in force 1 Jan 2026, which replaced Decree 13/2023 — the handoff still cites nothing here;
(c) the **Data Law 60/2024 + Decree 165/2025** and the **new Cybersecurity Law 116/2025 (1 Jul 2026)**, which hit the plan to send traces to external judge models and the evidence log;
(d) the Decision 33 "human review" wording: the handoff says "sole basis without meaningful human review". The text I could check says **"without human inspection, approval or control before execution"** and "without independent approval by credit officers". The "meaningful" wording is NOT confirmed. Supervisor must not claim it moves an agent out of high-risk; it only produces evidence that the human step is real.
Also: the judge itself is a model under model-risk rules and has no owner, no validation plan and no change control in the package. Competition track names were not found.

## 2. Findings table
| # | Gap / risk | Sev | Evidence | Recommendation | Effort | Phase |
|---|---|---|---|---|---|---|
| 1 | Draft SBV circular on AI in banking not mentioned | H | VERIFIED (secondary): Baker McKenzie Apr 2026 https://www.bakermckenzie.com/en/insight/publications/2026/04/vietnam-draft-circular-on-ai-deployment-in-banking ; Vietstock Aug 2026 says still drafting. Not signed as far as I found. | Add a "draft SBV AI circular" column to the regulatory mapping. Map each draft duty to a Supervisor artefact (see section 4). Track final text. | 2 d | Competition |
| 2 | Decision 33 wording differs from handoff; "meaningful human review" unverified | H | VERIFIED (secondary): Allen & Gledhill https://www.allenandgledhill.com/sg/publication/articles/33374/identifies-high-risk-ai-systems-across-six-sectors . Banking items: high-value e-transactions executed "without human inspection, approval or control before execution"; credit scoring / loan decisions "without independent approval by credit officers". Article has no "sole basis" or "meaningful" phrase. | Fix docs/01 and deck wording. Quote the Appendix text from the official gazette. Reframe claim: "Supervisor proves the human gate exists and works", not "removes high-risk status". | 1 d | Competition |
| 3 | Transition dates missing | M | VERIFIED (same source): systems running before 15 Aug 2026 in finance/health/education comply by 1 Sep 2027; new systems started within 6 months of 15 Aug 2026 comply by 1 Mar 2027. | Put dates in the roadmap. Dec 2026 shadow pilot may count as a "new system" with 1 Mar 2027 deadline. Ask counsel. | 0.5 d | Competition |
| 4 | Personal Data Protection Law 91/2025/QH15 and Decree 356/2025 missing; Decree 13/2023 is superseded | H | VERIFIED (secondary): Tilleke https://tilleke.com/insights/vietnams-new-personal-data-protection-law-a-closer-look ; digitalpolicyalert Decree 356/2025. Law in force 1 Jan 2026; Decree 356 adopted 31 Dec 2025; fines up to 5% prior-year revenue for cross-border breaches. Sensitive-data definition and DPIA detail NOT verified. | Do not cite Decree 13 as current. Add: record of processing, cross-border transfer impact assessment (TIA) when traces leave VN, DPO sign-off on masking design, data-subject rights hook (access / delete) on traces. | 1 wk | Dec candidate |
| 5 | Cross-border flow: judge models and traces | H | VERIFIED (secondary): Data Law 60/2024 (in force 1 Jul 2025) and Decree 165/2025: core data must stay in VN; important data transfer needs notice (15 d reported; draft said 5 d, check text); logs kept at least 6 months. A July 2026 report (single source) says a proposed data-security law would add MPS approval for large volumes of personal data. | Default to in-region judge (Qwen on provisioned throughput) for Tier 2 on any trace with customer data. Mask before any out-of-region call. Log the region of every judge call in the evidence chain. | 1 wk | Dec candidate |
| 6 | Cybersecurity Law 116/2025 (from 1 Jul 2026) and Decree 53/2022 localisation | M | VERIFIED (secondary): Duane Morris https://blogs.duanemorris.com/vietnam/2026/01/08/vietnam-law-on-cybersecurity-2026-what-you-must-know/ . 2018 law had 24-month local storage on request; whether it carries over, and bank-specific scope, NOT confirmed. Decree 330/2026 sanctions (19 Aug 2026) reported by one source. | Keep evidence vault and traces in a VN-region workspace. Ask counsel if the bank is a critical-information-system operator (SBV Circular 09/2020 regime). | 2 d (legal) | Dec candidate |
| 7 | SBV Circular 09/2020/TT-NHNN (IS security) and third-party IT rules | M | VERIFIED (title/scope only): https://english.luatvietnam.vn/circular-no-09-2020-tt-nhnn-dated-october-21-2020-of-the-state-bank-of-vietnam-promulgating-the-security-of-information-system-in-banking-operations-192825-Doc1.html . Covers third-party IT services, access management (no shared accounts). Amendments NOT found. Circular 50/2024 is online-banking security, a different topic. | Supervisor is a new IS: needs security classification, pen test before go-live, named admin accounts, no shared service logins. Add to Dec checklist. Pull the current consolidated text. | 1 wk | Dec candidate |
| 8 | Cloud / outsourcing rules for AI vendors | M | Draft AI circular: bank stays "fully responsible" for outsourced AI; vendor oversight and independent audit (VERIFIED, secondary). It does not address cloud by name. Specific SBV cloud rule NOT found. | Treat each external judge model provider as a third party: vendor register, contract clauses (no training, retention, region), exit plan. Put in Supervisor's vendor inventory. | 1 wk | Dec candidate |
| 9 | Law on Credit Institutions 2024 | L | VERIFIED (secondary): customer-information confidentiality widened to all customer-related information; in force 1 Jul 2024. Decree 117/2018 still gives confidentiality duty. I found no AI or retention rule in it. | Treat case files that contain customer data as confidential customer information: access log, need-to-know roles. | 2 d | Dec candidate |
| 10 | E-transactions: legal weight of anchoring | M | VERIFIED (secondary): Law 20/2023/QH15 + Decree 23/2025/ND-CP; e-signature cannot be denied validity only for being electronic. Time-stamp service rules NOT found. | See section 6. Use a licensed VN certificate provider for signing case files. Do not rely on a foreign blockchain as the only anchor. | 1 wk | H1 2027 |
| 11 | Judge is a model with no owner, inventory entry, validation or change control | H | Not in docs (ASSUMED gap). Draft SBV circular asks for model management, monitoring, drift (VERIFIED, secondary). | Add "Judge Model Card + MRM pack" deliverable; see section 3. | 1 wk | Dec candidate |
| 12 | Fairness slicing: attributes and legal exposure unresolved | H | CLAUDE.md lists as open. Draft circular bars discriminatory outcomes and requires bias monitoring (VERIFIED, secondary). | See section 4 below (fairness). Decide before building the slice UI. | 3 d + counsel | Competition (design), Dec (build) |
| 13 | 24-hour SBV incident report clock not in the case file | H | VERIFIED (secondary): draft circular, report within 24 h of detection; remediation report in 5 working days. | Case file gets "regulator clock" fields and a pre-filled SBV report draft. Strong demo moment. | 3 d | Competition |
| 14 | Customer-facing duties: AI disclosure, explain key factors, right to human review of disputed decisions | M | VERIFIED (secondary): Viet Nam News Feb 2026, Baker McKenzie. | Supervisor checks that the agent sent the AI notice and logs the explanation. Add as rule pack "customer-rights". | 1 wk | H1 2027 |
| 15 | Retention periods undefined | M | Draft circular gives no period (VERIFIED, secondary). Decree 165 gives 6 months minimum for logs. Banking record rules NOT checked. | Make retention a per-class setting. Propose defaults in section 6 and ask bank. Tension: evidence must be kept long, personal data must be minimised. | 2 d | Dec candidate |
| 16 | Language: Vietnamese case files | M | ASSUMED. Regulator and internal audit work in Vietnamese. | Generate case file in Vietnamese plus English. Keep original-language trace text unchanged. Judge rationale in Vietnamese. | 1 wk | Competition (one sample) |
| 17 | MAS date has a single source | L | VERIFIED consultation: 13 Nov 2025, closed 31 Jan 2026 (Allen & Gledhill https://www.allenandgledhill.com/vn/publication/articles/31741/mas-consults-on-proposed-guidelines-for-artificial-intelligence-risk-management ). Final 7 Oct 2026 / effective 7 Oct 2027: one source only. | Keep, but cite MAS own page. Label "regional benchmark, not binding in VN". | 0.5 d | Competition |
| 18 | Law on AI: conformity assessment, national AI portal registration, penalties | M | VERIFIED (secondary): high-risk needs conformity assessment route (Art. 13), registration, human oversight. Fines/suspension per draft: "confirm against final text" in docs/01 is still open. | Pull final text of 134/2025. Check which obligations fall on provider vs deployer; the bank is deployer, vendors are providers. Supervisor helps with deployer records. | 2 d | Competition |
| 19 | Competition rules: ethics, data security, national security bar | M | VERIFIED (press): "AI Thuc Chien" season 2 says solutions must meet technology-safety, AI-ethics, data-security and national-security standards. Unclear if same event (see section 7). | Add a one-slide "how this build meets safety, ethics, data security" mapped to the points above. | 1 d | Competition |

## 3. Model risk management (MRM) fit
### What a bank MRM function expects (ASSUMED, based on common SR 11-7 style practice; SBV draft asks for model-management procedures, monitoring, lifecycle, retirement — VERIFIED secondary)
| MRM element | What they ask | How Supervisor maps | Gap |
|---|---|---|---|
| Inventory | Every model/agent: owner, purpose, tier, status, dependencies | Agent identity registry + Onboarding Agent output | Registry does not yet hold MRM fields (owner, risk tier, validation date). Add them. Also list the **judge models and rule packs as inventory items**. |
| Risk tiering | Materiality tier drives validation depth | Decision 33 / draft SBV tier in the onboarding report | Needs a bank-owned tier scale. [bank to supply] |
| Development doc | Purpose, data, limits, assumptions | Generated launch pack | Add "known limits" section for the judge. |
| Independent validation | Second line reviews before use and periodically | Not covered | Add validation plan (below). |
| Ongoing monitoring | Performance thresholds, drift, overrides | Quality monitor, drift checks | Good. Add judge-vs-human agreement metric. |
| Change control | Versioned, approved changes, re-validation triggers | PR-only changes, second approver on rules | Extend to judge prompt, judge model version, thresholds, rubric. A model-version bump = change. |
| Issue / incident log | Findings tracked to closure | Case files | Add finding-to-remediation tracking and link to SBV report. |
| Retirement | Safe decommission | Not covered | Add "retire agent" stage to Onboard. |

### Who owns the judge? (decision needed)
| Role | Proposed holder | Why |
|---|---|---|
| Model owner (accountable) | Head of the team that runs Supervisor (first line, platform / AI governance office) [bank to name] | Owns performance and changes. |
| Model developer | Supervisor build team | Writes rubrics, prompts, thresholds. |
| Independent validator | Bank MRM / second line, not the build team | Required independence. |
| Model user | Reviewers and risk officers using the console | Give override feedback. |
| Approver of rule / threshold changes | Second line risk + owner of the supervised agent's business unit | Four-eyes. |
| Assurance | Internal audit (third line) | Samples the chain and the validation. |
Key point: the Supervisor must not be validated by the same people who validate the agents it supervises only if they also own its thresholds. ASSUMED. Bank sets the rule.

### Independent validation of the judge (what to build)
1. Golden set: human-labelled traces, Vietnamese and English, held out from rubric tuning. Size [bank to supply]; start 300 to 500 labelled items per risk category (ASSUMED sizing).
2. Report TPR, FPR, agreement with humans, and by-language results. Do not copy vendor numbers; the handoff cites FinVault best guard model 61% TPR / 30% FPR — keep it labelled as a published benchmark.
3. Adversarial test of the judge itself: prompt injection inside the traces it reads, judge-targeted jailbreaks, position/length bias.
4. Stability: same trace run N times; report variance. Pin model version; re-run golden set on every model or prompt change.
5. Challenger: run a second model family on a sample; log disagreement rate.
6. Tier 0 rules: unit tests and mutation tests, since these are the part that can block.
7. Re-validation triggers: model version change, rubric change, agreement drop below threshold [bank to set], new agent type.
Effort: 2 weeks for first golden set and report. Phase: competition = show a small golden-set result labelled illustrative; Dec = real.

## 4. Fairness
### Realistic attributes in a Vietnam credit context (ASSUMED unless marked)
| Attribute | Usually collected? | Legal exposure | Proxy risk | Advice |
|---|---|---|---|---|
| Gender | Yes (ID, KYC) | Gender equality law applies generally; personal data, probably not "sensitive" but confirm | Name, title, occupation, product choice | Slice. Lowest-risk first choice. |
| Age band | Yes (date of birth) | Low | Tenure, employment type | Slice in bands, not exact age. |
| Region / province | Yes (address) | Low to medium | Ethnicity, income | Slice at province or urban/rural level. |
| Income band, occupation, employment type | Yes | Low; this is a legitimate credit factor | Proxy for many | Slice as a control, not as a protected class. |
| Ethnicity, religion | Generally not collected; ID card may show them (ASSUMED) | High; sensitive personal data in the usual reading, but definition under the 2025 law NOT verified | Province, name, language | Do not collect. Do not infer. |
| Disability, health | No | High | Medical-loan history | Do not collect or infer. |
| Marital status | Sometimes | Medium | Gender | Slice only if already held and counsel agrees. |
| Language of the interaction (Vietnamese / English / other) | Observed in the trace | Low | Region, education | Very useful for chat agents; no extra collection. |
### Rules
- Fairness slicing is a data-protection act. It is a new purpose for the data: needs a lawful basis, a DPIA-style assessment, and DPO sign-off (ASSUMED; check Decree 356/2025).
- Never infer protected attributes with a model. Inference creates new sensitive data and error risk.
- If an attribute is not collected: (1) report that it cannot be measured, (2) use the allowed proxies above as monitored slices, (3) use outcome-based tests that need no attribute: counterfactual tests with synthetic Vietnamese personas (swap name, gender cue, province) on the agent, (4) log "fairness coverage" as a number in the case file, so absence is visible.
- Slice computation should run on masked, hashed IDs in a restricted Unity Catalog schema. Small cells (n below [bank to set], ASSUMED 30) suppressed.
- Show metric + confidence interval, not a bare "gap ≤ 5 pts". The 5-point target in docs/02 is a design goal; the bank's risk appetite sets it.
- Draft SBV circular says monitor for bias and bar discriminatory outcomes (VERIFIED, secondary).

## 5. Human oversight, the high-risk tier and RACI
### What the law says vs what the handoff says
- VERIFIED (secondary): Decision 33 banking entries apply when there is no human inspection/approval/control before execution (transactions) or no independent approval by credit officers (credit). Systems must support human supervision, control and intervention, and must not improperly replace the powers of competent persons.
- The handoff phrase "sole basis without meaningful human review" is not confirmed. Quote the official text.
- Important consequence: a "pause" verdict is NOT human review before execution. Supervisor's pause is a safety control. It does not by itself take an agent out of the high-risk list. The agent's own workflow needs the pre-execution approval step. Supervisor then proves that step happened.

### What a real review looks like (design requirements; ASSUMED, aligned to the wording above)
| Requirement | Why | Supervisor evidence |
|---|---|---|
| Reviewer is a named, trained, authorised person (e.g. credit officer) with power to reject | "Independent approval" | Identity from SSO; authority matrix check; training record link |
| Review happens before execution, not after | Text says before execution | Timestamps: proposed action, approval, execution; rule fails if execution precedes approval |
| Reviewer sees the inputs and reasons, not only the AI score | Avoid rubber-stamp | Log what the reviewer screen showed |
| Reviewer can override and the override is respected | Control | Record override and its effect |
| Not a rubber stamp: dwell time, approval rate, disagree rate tracked | Automation bias | Oversight metrics panel; alert at approval rate near 100% or very short dwell time |
| Workload fits: queue size vs reviewers | Real capacity | Queue age and reviewer load |
| Four-eyes on high-value items | Bank control norm | Two distinct identities; maker cannot be checker |
### SLAs (proposals; bank to set)
| Item | Proposed | Note |
|---|---|---|
| Inline block / pause | under 1 s (design goal in docs/02) | Machine |
| Page to reviewer | under 5 min (docs/02) | Match to bank on-call |
| First human triage of a pause | 15 min business hours; [bank to set] after hours | Pausing a customer-facing agent has cost; need after-hours cover |
| Decision to resume or retire | 4 h for medium; same business day for high | ASSUMED |
| SBV report | 24 h from detection (draft) | VERIFIED secondary |
| Remediation report | 5 working days after fix (draft) | VERIFIED secondary |
### RACI for pause decisions
| Decision | Responsible | Accountable | Consulted | Informed |
|---|---|---|---|---|
| Auto-pause by Tier 0 rule (pre-agreed rule) | Supervisor | Model owner of Supervisor | Agent owner (at rule approval time) | Agent owner, reviewers |
| Confirm / lift pause | On-call reviewer (second line risk or ops risk) | Head of ops risk [bank to name] | Agent owner, compliance | CISO, internal audit |
| Manual pause on judge flag | On-call reviewer | Head of ops risk | Agent owner | Agent owner |
| Override a pause to restore service (business-critical) | Agent owner | Risk executive plus business executive (two signatures) | Compliance, CISO | Audit; logged in chain |
| Decide SBV notification | Compliance / legal | Chief compliance officer [bank to name] | CISO, agent owner, DPO | CEO office |
| Rule or threshold change | Supervisor team | Model owner | Second line, agent owner | Audit |
| Judge model version change | Supervisor team | Model owner | MRM validator | Audit |
Note: the pause must be narrow and reversible. Document a "fail mode" for when Supervisor itself is down: fail-open or fail-closed per agent tier. This is a bank decision and a regulator question. [bank to supply]

## 6. Evidence, retention, language, anchoring
### What would they ask after an incident? (ASSUMED list, aligned to draft SBV duties)
1. What happened, when detected, by whom or what; time from detection to block, to human.
2. Which agent version, model version, tools, permissions, policy version were live.
3. Full trace, inputs, outputs, tool calls; who approved what.
4. Which control should have caught it; why it did or did not.
5. Customer impact: who, how many, money, data exposed.
6. Was the incident reported on time (24 h) and was the data subject informed where required.
7. Proof that logs were not edited; chain verification report.
8. Who owns the agent, who owns the control, who approved the last change.
9. Remediation, re-test, and sign-off.
10. Prior similar flags and what was done (trend).
Case file template should have a section for each. Add "judge version + prompt hash + golden-set result at that date".
### Retention (proposal; ASSUMED; confirm with bank records policy and counsel)
| Class | Proposed | Basis |
|---|---|---|
| Full raw traces with personal data | Short, e.g. 90 days [bank to set]; masked copy longer | Data minimisation; Decree 165 minimum 6 months for logs may apply, check |
| Masked traces | 12 months [bank to set] | Operations and drift |
| Evidence chain (hashes, decisions, verdicts, sign-offs) | At least 5 years, ideally match bank incident-record rule [bank to supply] | Audit and regulator look-back; hashes hold no personal data |
| Case files (incident) | Same as the longest bank rule for incident / complaint records [bank to supply] | Contains customer data: restrict |
| Judge validation packs and model changes | Life of model + 5 years [bank to set] | MRM |
Design point: store personal data off-chain and only salted hashes in the chain, so a delete request does not break the chain. Do not log raw PII to the evidence table. Add a "legal hold" flag.
### Language
Case file in Vietnamese (primary) with English summary. Keep original trace text. Test the judge on Vietnamese; many guard models are weaker outside English (ASSUMED; measure). Presidio has no strong Vietnamese support out of the box (ASSUMED; verify) — add Vietnamese patterns for CCCD/CMND numbers, phone, tax code, account numbers.
### Anchoring and time-stamp options in Vietnam
| Option | Strength | Weakness | Fit |
|---|---|---|---|
| Daily root hash signed with a bank-held key in HSM / Key Vault, stored in WORM storage in a second VN region or system | Simple, local, cheap | Bank controls the key (internal) | Competition and Dec |
| Sign the daily root with a **public digital signature from a licensed VN certificate provider** (Law 20/2023, Decree 23/2025: e-signature not denied validity because it is electronic — VERIFIED secondary) | Legal weight in VN; third-party identity | Needs org certificate; time-stamp not proven | Dec candidate |
| Licensed time-stamp service (trust service) | Independent time proof | I did not find VN time-stamp provider rules; ASSUMED to exist under the 2023 law; verify provider list and format (RFC 3161) | H1 2027; ask counsel |
| Send root hash to SBV or external auditor by email/portal as a receipt | Independent holder, trivial | Not cryptographic | Cheap extra |
| Public blockchain / RFC 3161 foreign TSA (e.g. a foreign service) | Strong independence | Cross-border question; only a hash leaves, no personal data, so low risk, but still ask | Optional extra |
Recommendation: tier 1 (own-key signature + WORM) now; add VN-licensed signature in Dec; ask SBV-facing counsel which time-stamp they accept.

## 7. Competition brief: the three tracks
- I searched for "Techcombank AI Builder 2026 AI Governance Supervisor tracks". **Not found.** Results only showed the Techcombank-sponsored national TV competition "AI Thuc Chien" season 2 / National A.I Challenge (organised with National Data Centre, National Data Association, VTV; July to December 2026; registration closed 15 Sep 2026; solutions must meet technology-safety, AI-ethics, data-security and national-security standards). VERIFIED (press): https://mekongasean.vn/khoi-dong-cuoc-thi-ai-thuc-chien-2026-loi-giai-cong-nghe-cho-bai-toan-thuc-te-56467.html . I cannot say it is the same event as the "AI Builder" page the team used. Ask the organiser or re-open the page.
- docs/01 says tracks correspond to the three pain points. Brief text: "pick at least one ... corresponding to one of the three tracks". So the tracks are very likely the three pain points. ASSUMED.
| Likely track | Our claim | Proof to show in demo | Gap |
|---|---|---|---|
| A. Velocity mismatch | Instrument in hours; change-triggered re-checks; drift vs baseline | Agent prompt change at hour 0 -> re-run policy suite -> gate or alert in minutes; time chart vs 4-6 week manual | Show a *change event* trigger, not only runtime watching. Add "agent change detector" (prompt/tool/model diff -> auto re-test). 3 d |
| B. Emergent multi-agent risk | Prototype message-bus check | Two agents, each compliant alone, jointly breach (e.g. one splits a limit, other approves) | Docs call it a prototype; keep claim small; one scripted scenario with a clear before/after. 4 d |
| C. Real-time proof of control | Hash-chained log, case files, oversight metrics | Auditor asks "show control kept pace" -> one-click proof pack with chain verification, plus SBV 24-h clock | Strongest track; add the regulator-clock report (finding 13) and a "verify chain" button. 3 d |
Pick: A + C as core (as handoff chose). Rename deck claims to those track names once confirmed.

## 8. Detailed notes on High findings
**#1 Draft SBV AI circular.** Biggest missed item. Reported duties: classify AI by risk; match oversight to risk; model-management procedures and continuous monitoring; lifecycle controls (drift, update, retire); log operational data; AI disclosure and explanation to customers; human review of disputed decisions; bias monitoring; bank fully responsible for third-party AI; incident report in 24 h, remediation report in 5 working days; annual staff capability reviews. Not found: retention period, separate validation function, cloud rules, internal-audit duty. Status: expected 2026, not confirmed signed; early press said March start and September 2027 for existing systems (conflicts with later "still drafting"). Action: build a mapping table duty -> artefact -> demo screen. Re-check status weekly until the competition.

**#2 Decision 33 wording.** The claim "demonstrable oversight is the control" is sound in spirit. The exact trigger is "no human check before execution" and "no independent approval by credit officers". So the Supervisor's value is to prove the human gate is real, timed before execution, by an authorised person. Do not promise to change the tier. Get the official Appendix text and have counsel confirm which agents are in scope.

**#4 and #5 Data protection and cross-border.** Law 91/2025 in force 1 Jan 2026 replaced Decree 13/2023. Penalties up to 5% of revenue for cross-border breaches (reported). Supervisor handles traces full of customer data and sends some to judge models. Design rules: mask first, Tier 2 in-region by default, region logged per call, transfer impact assessment on file, record of processing for Supervisor itself, data-subject request path, retention by class. Cost: mostly documents plus a masking test suite.

**#11 Judge as a model.** See section 3. Name an owner, put the judge in the inventory, validate with a golden set, pin versions, treat prompt/model/threshold change as a controlled change. Without this, the supervisor is the least governed model in the bank — a point regulators and Gartner's "meta-governance" note (cited in docs/01) both raise.

**#12 Fairness.** See section 4. Choose gender, age band, province/urban-rural, interaction language, plus synthetic counterfactual tests. Do not collect or infer ethnicity, religion, health. Ask counsel and DPO before building. Show "fairness coverage" openly.

**#13 24-hour clock.** Case file shows detect time, notify-by time, status, and draft SBV report text in Vietnamese. Cheap to build, high demo value. Wait for the final circular for the form.

## 9. What the handoff gets right
- Judge on a different model family; deterministic rules first (matches Gartner advice and good MRM practice).
- Supervisor's own decisions logged in the same chain (meta-governance).
- PR-only changes, second approver on rule changes (this is change control).
- Shadow mode first (fits transition periods in finding 3).
- Avoiding Gemini global endpoint and long-retention models (matches cross-border concerns).
- Fairness attributes flagged as a legal decision first.
- Illustrative data labelled; targets stated as design goals.
- Hash chain with external anchors; honest note that Delta time travel is not proof.

## 10. Open questions for the bank
1. Has the SBV AI circular been signed? Who in the bank tracks it and can share the latest draft?
2. Which Techcombank agents does counsel consider in scope of Decision 33 Appendix (transactions, credit)? Text of the two banking entries as the bank reads them.
3. Does the Dec 2026 shadow pilot count as a "new system" (comply by 1 Mar 2027) or not?
4. Who is the model owner of the judge, and which team is the independent validator?
5. Is the bank a critical-information-system operator under the Cybersecurity Law, and does local storage apply to Supervisor traces?
6. Is Tier 2 judging with customer data allowed on out-of-region models if masked? Is a transfer impact assessment already on file for Databricks?
7. Which fairness attributes does legal and the DPO allow to be sliced? Is a DPIA needed for the new purpose?
8. Bank retention rules for incident records, complaint records and logs (years).
9. Fail-open or fail-closed rule when Supervisor is down, per agent tier.
10. Who is on-call for pauses after hours, and who may override a pause?
11. Which time-stamp or signing provider does the bank already use? Does SBV or audit accept it?
12. Is Vietnamese case-file output mandatory for SBV reports?
13. What are the real competition tracks and the exact submission date? Is "AI Builder" the same programme as "AI Thuc Chien" season 2?
14. Does the bank have an AI incident definition ("serious") that matches the SBV draft?

## Sources used
- https://www.allenandgledhill.com/sg/publication/articles/33374/identifies-high-risk-ai-systems-across-six-sectors
- https://www.bakermckenzie.com/en/insight/publications/2026/04/vietnam-draft-circular-on-ai-deployment-in-banking
- https://vietnamnews.vn/economy/1766000/central-bank-moves-to-tighten-ai-use-in-banking-requires-prior-customer-notification.html
- https://en.vietstock.vn/2026/08/central-bank-enhances-oversight-of-ai-in-banking-operations-37-640453.htm
- https://tilleke.com/insights/vietnams-new-personal-data-protection-law-a-closer-look
- https://www.legal500.com/developments/thought-leadership/legal-update-on-vietnams-data-law/
- https://blogs.duanemorris.com/vietnam/2026/01/08/vietnam-law-on-cybersecurity-2026-what-you-must-know/
- https://www.mondaq.com/corporate-and-company-law/1650870/regulations-on-e-signatures-and-trust-services-in-vietnam
- https://www.allenandgledhill.com/vn/publication/articles/31741/mas-consults-on-proposed-guidelines-for-artificial-intelligence-risk-management
- https://mekongasean.vn/khoi-dong-cuoc-thi-ai-thuc-chien-2026-loi-giai-cong-nghe-cho-bai-toan-thuc-te-56467.html
