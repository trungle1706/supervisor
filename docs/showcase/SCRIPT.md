# Showcase presenter script

Plan: `docs/showcase/SHOWCASE_PLAN.md`. This file holds one section per act. WP-D2 writes acts 2
and 5 in the same file: add its sections where the markers say, do not overwrite the others.
Everything on screen is synthetic. Every seeded row carries the tag `demo:showcase`.

<!-- act 1: WP-D1 -->

<!-- act 2: WP-D2 -->

<!-- act 3 and act 4: WP-D3 (begin) -->

## Acts 3 and 4: the AI factory and the guardian factory (10 minutes)

Commands for the Windows cmd shell. Code: `src/supervisor/demo/showcase_factory.py`.

### Before the show (about 10 minutes, once)

Stop the console that uses the same data directory first (SQLite has one chain writer; the runner
opens its own runtime). Then:

```text
set SHOWCASE_ENABLED=1
set GOVERNANCE_ENABLED=1
set AGENT_FACTORY=1
set AGENT_FACTORY_GATE=1
set REGKB_INTERNAL=1
set LAWAGENT_ENABLED=1
set DETECTORS_ENABLED=1
set GUARDIAN_FACTORY=1
set GUARDIAN_SHADOW=1
python -m supervisor.demo.showcase factory --reset
python -m supervisor.demo.showcase factory --part agents --until tested
python -m supervisor.demo.showcase factory --part guardians --until shadow
```

Start the console with the same flags. Check the printed table: both agents `tested`, both
guardians `shadow`, no `[FAIL]`. Use the same shell variables for the console.

| Model | What runs | What the table says |
|---|---|---|
| `LLM_BASE_URL` set (Databricks gateway model, GLM 5.3 flash) | law agent drafts duties from the two policies, checklist drafter proposes rows, the gate judges and the calibration use the gateway model | `model: gateway model`. These are the numbers to quote. |
| `LLM_BASE_URL` empty (laptop) | law agent and drafter are skipped with a message, the gate runs on the development fake model (`dev-fixture-replay`) | `model: fake model`. Say so on stage: layer 1 is real, layer 2 and the kappa only show that the plumbing works. Refused in `databricks_app` mode. |

Console users (dev header on a laptop; SSO groups on Databricks):

| User | Role in the story | Groups |
|---|---|---|
| `reviewer.an` | author of agents and guardians | none (role mapping) |
| `reviewer.binh` | synthetic reviewer of the simulation and shadow marks | none |
| `lead.model` | owner lead, Model Risk | `model_risk` |
| `lead.data` | owner lead, Data Office (added for the showcase in `config/users.yaml`) | `data` |
| `lead.cyber` | owner lead, Payments and Cyber | `cyber` |
| `second.line` | second line, second approval | `platform` |

### Act 3: AI factory (6 minutes)

| Min | Say | Show (console) | Expected |
|---|---|---|---|
| 0:00 | "Risk teams build their own assessors. No code." | `/console/factory`: two cards, `credit-model-risk-assessor` (Model Risk) and `customer-data-privacy-assessor` (Data Office), state `tested` | Cards carry the last gate result |
| 0:45 | "The policy is the bank's own. It is uploaded, masked, and a law agent drafts the duties." | `/console/regkb/internal`: `TCB-MRM-POL-07` and `TCB-DG-STD-02`, marked synthetic. Open the drafts page of one. | With the gateway model: duty rows confirmed by `counsel.synthetic`. Without: "uploaded", no rows (say why). |
| 1:30 | "The agent reads the policy and Circular 53." Open the credit agent, step 2 and 3. | Policy references: `VN-TT53-2026` and `VN-INT-...`; checklist (6 template rows, plus rows from the drafter on the gateway) | Data agent: step 6, loop with the rules evaluator, max 3 |
| 2:15 | "Sixty cases with a known answer, and 24 labels from people." Step 9. | Golden set: 60 cases or more, every item covered; labels 24 | |
| 3:00 | "Before the full test, a person reviews it on three real systems." Step 10, the simulation run. | `/console/factory/credit-model-risk-assessor/simulation/<run>`: findings beside evidence, marks agree / disagree / unsure by `reviewer.binh` | About 15 agree, 1 or 2 disagree, 1 unsure per agent. Marks became calibration labels. |
| 3:45 | "The full gate has three layers." Gate panel of the newest full run. | Layer 1 deterministic 100 percent; layer 2 judge match, kappa (floor 70), regression against the live version; layer 3 shadow | See "Numbers" below |
| 4:30 | "Two people release it. The author cannot approve." Switch user to `lead.model`, then `second.line`. | Submit (`reviewer.an`), approve `owner_lead` (`lead.model`), approve `second_line` (`second.line`), Activate (`lead.model`) | State `live`. For the data agent: `lead.data` and `second.line`. |
| 5:30 | "It is now the live agent of its dimension in the risk assessment." | `/console/factory` strip of the eight dimensions: `model` and `data_governance` show the live agent | |

To make the release live on stage, stop at `tested` (the default of the before-the-show commands).
To show the gate itself on stage, stop at `draft` and press **Run full gate** (on the gateway model it
takes minutes: do it for one agent only, and talk while it runs). To skip the stage work, run
`python -m supervisor.demo.showcase factory --part agents --until live`.

### Act 4: guardian factory (4 minutes)

| Min | Say | Show (console) | Expected |
|---|---|---|---|
| 0:00 | "A guardian is a rule written in plain words." | `/console/guardian-factory`: `vn-account-number-mask` (Data Office) and `transfer-above-limit-needs-approval` (Payments and Cyber), both in `shadow` | |
| 0:30 | "The first one: mask bank account numbers. The pattern comes from the library, no model." | Guardian 1 editor: regex, stage tool call, action redact, scope the payments agent | |
| 1:00 | "Before it touches anything, we measure it against the live detector." Benchmark panel. | Starter pack (100 attack, 140 benign): TPR 100, FPR 0, p95 about 30 microseconds; live comparison `dlp_vn` TPR 100, FPR 8 | |
| 1:45 | "The second one is a policy: a transfer above 20,000,000 VND needs an approval, or it is blocked." | Guardian 2 editor: policy rules (within the limit permit, approval present permit, default forbid), hand-built pack 40 attack and 60 benign: TPR 100, FPR 0 | Boundary: exactly 20,000,000 passes; 20,000,001 does not |
| 2:15 | "Then it watches real traffic and acts on nothing." Shadow panel. | Guardian 1: 300 calls seen, 63 would act, 60 correct, 3 false (4 percent, limit 5). Guardian 2: 202 seen, 24 would act, 23 correct, 1 false | Counts come from synthetic traffic written through the shadow runner. The window is 1 day for the demo (product default 7). |
| 2:45 | "Again two people." Switch user to `lead.data`, then `second.line`; then `lead.data` presses Go live. For guardian 2: `lead.cyber`, `second.line`, `lead.cyber`. | Promotion panel: approvals `owner_lead` and `platform_security`; state `live` | |
| 3:30 | "Now the proof." Run the final check, or the payments traffic, and open Activity. | An over-limit transfer (25,000,000) is **blocked** by `GATE-GUARDIAN-BLOCK` (`gf:transfer-above-limit-needs-approval@1`); a payee note with an account number is **masked** (`gf:vn-account-number-mask@1`); a transfer of the same amount with an approval id passes | The runner prints the same three lines |

To skip the stage work, run `python -m supervisor.demo.showcase factory --part guardians --until live`;
it ends with the final check.

### Numbers (fake model run, laptop, 2026-10-29)

Rates are integer percent, kappa in hundredths (floor 70). The agent columns are from the fake
model: they prove the plumbing, not the quality of a model on a bank document. The guardian
columns do not use a model.

```text
agent                           state    cases/lbl  L1% judge% kappa   regression L3 shadow sim a/d/u  model
credit-model-risk-assessor      live         60/24  100    100    78         none   no_data    15/2/1  fake model
customer-data-privacy-assessor  live         60/24  100    100    84         none   no_data    13/1/1  fake model

guardian                              state      TPR% FPR% p95 us       live compare shadow seen/act false%
transfer-above-limit-needs-approval   live        100    0     20      none (policy)          202/24      4
vn-account-number-mask                live        100    0     29       dlp_vn 100/8          300/63      4
```

L1 = layer 1 (11 checks), judge = layer 2 verdict match, sim a/d/u = simulation marks agree,
disagree, unsure, L3 shadow = layer 3 (no stored onboarding yet, so `no_data`; it informs only).
Guardian p95 is in microseconds and changes a little on each run.

The table is written to `DATA_DIR/showcase/factory-results.json` after each run. Replace the agent
rows with the table of the Databricks run (gateway model) before the show.

### If something goes wrong

| Symptom | Do |
|---|---|
| `[FAIL] the showcase is off` | `set SHOWCASE_ENABLED=1`. Never in a production App. |
| The runner cannot write the chain (two writers) | Stop the console on the same data directory, run again, start the console. |
| The gate says `model_not_configured` | `LLM_BASE_URL` is empty. Use the runner (fake model on a laptop) or set the gateway. |
| A screen shows no showcase row | The console needs the same flags as the runner (the runner prints the list). |
| Start again | `python -m supervisor.demo.showcase factory --reset`, then the commands above. Reset removes only the rows tagged `demo:showcase`. Append-only events and the evidence chain stay by design. |

<!-- act 3 and act 4: WP-D3 (end) -->

<!-- act 5: WP-D2 -->
