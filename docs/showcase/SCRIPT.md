# Presenter script: act 2 (three journeys) and act 5 (proof)

> Synthetic data only. Every journey row carries the tag `demo:showcase`. Not for a production App.
> "Not legal advice. Bank counsel must confirm." stays on the screen.

Code: `python -m supervisor.demo.showcase journeys | traffic` (`src/supervisor/demo/showcase_journeys.py`,
`showcase_traffic.py`). Plan: `SHOWCASE_PLAN.md` sections 1, 2, 5. Sources: `tests/fixtures/showcase/*.zip`
(rebuilt by `python tools/showcase_sources.py`).

## 0. Before the session

| What | Command or setting |
|---|---|
| Flags on the App and on the shell that runs the commands | `SHOWCASE_ENABLED`, `GOVERNANCE_ENABLED`, `CONSOLE_SYSTEMS_ENABLED`, `CONSOLE_REGISTER_V2`, `REGISTER_V3`, `CLASSIFICATION_V2`, `RISK_DIMENSIONS`, `ONBOARD_INTAKE`, `ONBOARD_FACTS`, `ONBOARD_PREDEPLOY`, `ONBOARD_ORCHESTRATOR`, `SMART_GUARDIAN`, `GUARDIAN_BINDINGS_ENABLED`, `CONSOLE_STATE_ACTIONS`, `INVENTORY_ENABLED` (all `=1`); for the traffic also `DETECTORS_ENABLED=1`, `INLINE_REDACTION_ENABLED=1`, `POLICY_DIR=policies:tests/fixtures/showcase/policy` |
| Model path | Set `LLM_BASE_URL` (the gateway model) to get model claims in the facts card. With it empty the run says `[SKIP] LLM_BASE_URL is empty` and uses the rule path |
| Console URL printed in the run | `--console-url https://FILL-ME-supervisor-app-url` (or env `CONSOLE_URL`) |
| Deployed candidate Apps (optional) | env `SHOWCASE_APP_URL_KB_HELPDESK_BOT`, `..._CS_ASSISTANT`, `..._PAYMENT_OPS_COPILOT` before step 1: the node then has an App URL and the pre-deploy report can run the packs against the live App (`PREDEPLOY_HTTP_TARGET=1`, `PREDEPLOY_HTTP_ALLOWED_HOSTS`). Without it the stored code is read, not run, and the report says `no_go` |
| Check the plan | `python -m supervisor.demo.showcase journeys --dry-run` |
| Clean start | `python -m supervisor.demo.showcase journeys --reset` (removes the journey rows only; the evidence chain keeps its records) |

Two synthetic people do every two-person step. **reviewer.an** asks and decides. **reviewer.binh**
approves. Sign in as `reviewer.an` in the console for the live steps. Switch to `reviewer.binh` for
every "second person" click (Switch user).

## 1. Choose the start point

| Plan | Run | You do live |
|---|---|---|
| Show the whole flow in the console | `journeys --step 1` | steps 2 to 9 |
| Show the judgement steps live | `journeys --step 3` | classify, assess, duties, guardians, approvals |
| Show only the result | `journeys` (all nine steps) | traffic and the pages |

`--step N` stops after step N. A later run with a higher N carries on from the data. A second run of
the same N changes nothing. `--candidate kb-helpdesk-bot` (or the other ids) runs one journey.

## 2. Act 2: the three journeys (10 minutes)

Order: `kb-helpdesk-bot` (low), `cs-assistant` (medium), `payment-ops-copilot` (high). Say the class
reason once per journey (the run prints it as `why:`).

### Screen 1: Candidates tab (`/console/candidates`)

| Say | Expected |
|---|---|
| The scan found three unmanaged Apps. The score tells us which to register first. | Three rows, status unmanaged. Score about 39 (kb), 75 (cs), 75 (payments); the kb score rises to 45 after the facts step |
| Click the row: the drawer shows the evidence and the tools. | Tools: kb 1 read-only; cs 3 (customer lookup, ticket, fee waiver); payments 3 (reconcile, payee, transfer) |

### Screen 2: Source and Facts (drawer panels, steps 1 and 2)

| Say | Expected |
|---|---|
| The source is a zip of the code. It is scrubbed before it is stored. | Attempt 1, status scrubbed |
| Each fact has a file, a line and a quote. No claim without evidence. | Rule path: 14 facts (kb), 23 (cs), 20 (payments). Model path: more claims, some dropped for no evidence |

### Screen 3: Register, identify (`/console/register/<draft>/step/3`, step 3)

| Say | Expected |
|---|---|
| Fields from the facts show "from facts". The AI type and four flags follow a fixed rule. | kb: assistant, agentic and generative yes, customer facing no. cs: assistant, customer facing yes. payments: automation, agentic yes, decides no |
| Saving this step makes the system record. The agent is linked in SHADOW. | Gate state SHADOW, stage initiation |

### Screen 4: Classification (system page, tab Classification, step 4)

| Say | Expected |
|---|---|
| One person decides along the tree. A second person approves. The tree shows the path. | Path highlighted; decided by reviewer.an, approved by reviewer.binh |
| The class decides what follows. | kb **low**: internal, no customer (Decree 142 Art. 8(2), 9(3)). cs **medium**: customers may mistake it for a person (Law Art. 9(1)(b), Circular 53 Art. 20(3)). payments **high, self-assess**: auto payment above the SBV threshold without pre-approval (Decision 33 IV.1, Circular 53 Art. 4(2)) |

If the class differs, the run stops with `unexpected_class`. Do not click on.

### Screen 5: Risk assessment (tab Risk types, step 5)

| Say | Expected |
|---|---|
| The orchestrator plans the eight risk types of Circular 53 Art. 14(3) from the class. | kb: 5 assessed, 3 not applicable (reputation, supply chain, third party). cs and payments: all 8 assessed |
| It never writes pass. A person confirms each row. | Every assessed row `in_progress`, a proposal and a report link. No live assessment agent yet, so the rule runner answers: it says so on the row |

### Screen 6: Duties (step 6)

| Say | Expected |
|---|---|
| The duties come from the class and the AI type, marked "from classification" and "from AI type". | Medium and high show the dossier and notification duties; high adds the impact assessment, conformity and board approval (Circular 53 Art. 13, Law Art. 13, Circular 53 Art. 12(3)). cs: "customer facing" answered yes from the AI type |
| Open duties become tasks at submit. | Duty rows and gap tasks on the Duties tab after step 8 |

### Screen 7: Guardians and pre-deploy (tab Guardians, step 7)

| Say | Expected |
|---|---|
| The smart guardian reads the assessment and proposes. Each line has a rule and a reason. A person accepts. | kb: the floor guardian `dlp_vn`; 2 session limit lines accepted. cs: 7 lines accepted (session monitor, split payment monitor, guard model preset, approval above and daily total, session limits); floor `dlp_vn`, `injection_regex`, `policy_rules`. payments: 8 lines accepted (split payment monitor, strict preset, pause on money and credit, drift, level cap, approval limits); floor adds `session_monitor` |
| The pre-deploy report is the proof of fit. | On a laptop or without an App URL: `no_go` (9 to 10 packs fail with "no harness"). With the deployed App and the HTTP target on, the packs run against it |

Known limit (tell the audience if asked): the five autonomy limit lines of a payments system do not
fit the 120 characters of the system tag `autonomy_limits`. The run accepts the three that fit
(level cap, approval above, daily total) and prints `[SKIP]` for the two session limits. It is an
open issue of WP-G4.

### Screen 8: Review and approval (step 8, tab Tasks)

| Say | Expected |
|---|---|
| Submit asks for the stage approval. The person who asked cannot answer it. The owner cannot either. | Stage approval initiation to deployment, requested by reviewer.an, approved by reviewer.binh, then moved |
| Nothing goes live on one signature. | Stage deployment |

### Screen 9: Agent page (step 9, `/console/agents/<id>`)

| Say | Expected |
|---|---|
| The agent starts in SHADOW. The gate records what it would stop and stops nothing. | SHADOW, would-block count |
| Two people move it to RUNNING. Then the stage moves to operation (a second approval). | RUNNING; stage operation; two approvals per system in the stage list |

### Screen 10: Live traffic (agent page and Activity, `/console/activity`)

Start the traffic in a second window:
`python -m supervisor.demo.showcase traffic --candidate payment-ops-copilot --minutes 5 --rate 20`

| Say | Expected |
|---|---|
| Real calls go through the gate. Four things happen. | Planned mix of the run (exact counts): kb 82 allowed, 12 masked, 6 blocked per 100; cs 70, 18 masked, 4 paused, 8 blocked; payments 72, 12 masked, 8 paused, 8 blocked |
| Masked: account number, phone and CCCD never reach the log. | Verdict shows `transform`; the stored copy has tokens such as `<CCCD:495cee>` |
| Paused: a transfer above 20,000,000 VND needs a person. Blocked: above 100,000,000 VND, a fee waiver above 500,000 VND, or a tool that is not approved. An injection text in a blocked call shows next to the rule. | `SHOW-PAY-01`, `PAYOPS-02`, `CSA-02`, `KB-01`; the injection detector only reports, the rules stop the call |

A pause stops the whole agent (a product rule). The generator resumes it with the synthetic owner and
reviewer so the stream goes on. To show the resume live, add `--no-resume`: the agent stays PAUSED;
the owner (the agent owner id) and `reviewer.an` resume it on the agent page (two people).

Total for 5 minutes at 20 per minute: 100 calls. The counts above scale with the total.

### Traffic against the deployed gate on Databricks

| Step | Detail |
|---|---|
| Target | The Supervisor App URL (the gate). The candidate Apps call it with their own service principal; the generator does the same without the App |
| Credential | Option 1: HMAC key file of the agent (`--key-file`; first line is the secret, mode 600; issue it with `python -m supervisor.gateway.ingress_auth issue <agent-id> --out-key-file F`). Option 2: an OAuth token of a service principal that `config/agent_identities.yaml` maps to the agent: put it in an environment variable and give the name with `--bearer-env VAR` (the value is never printed) |
| Command | `python -m supervisor.demo.showcase traffic --candidate payment-ops-copilot --url https://FILL-ME-supervisor-app-url --bearer-env SHOWCASE_TOKEN --minutes 5 --rate 20` |
| Policy | The App needs the showcase policy next to the baseline (`POLICY_DIR` second folder = `tests/fixtures/showcase/policy`) and the three agents; otherwise the masking and the limits do not apply to these ids |
| Pause | Over HTTP the generator cannot resume. After the first pause the rest of the calls answer `GATE-PAUSED`. Resume in the console (two people) or run with a pause-free candidate (`kb-helpdesk-bot`) |
| Isolation | Decision rows are append-only evidence. `--reset` does not remove them; they stay tagged by the call context `source: demo:showcase` |

## 3. Act 5: proof (2 minutes)

Use `payment-ops-copilot` (high). The system id is printed in step 3 of the run, and is on the
system page.

| Screen | Say | Expected |
|---|---|---|
| System page, tab Duties | Every duty shows what the Supervisor produced for it, with counts. | Evidence marks per control; counts are rows in the window, not proof of legal compliance |
| Regulator pack: `GET /v1/systems/<id>/regulator-pack.html` (flag `REGULATOR_PACK=1`) | One signed pack for this system: class, path, eight types, duties, guardians, approvals. | Header with a SHA-256 and an Ed25519 signature |
| Offline verify (shell, no network): `python -m supervisor.evidence.verify regulator-pack.json` | The check runs on a laptop without the Supervisor. | `[OK]`. Edit one byte of the JSON and run again: the check fails. This is real, not staged |
| Law change (Regulation watch, `/console/regkb/watch`, admin; flag `REGWATCH_ENABLED=1`) | If a law text changes, the duties that cite it re-open with a note and a task. | A banner or row for the changed article; re-opened duty rows on the Duties tab |

Close with the audit view: Activity shows the masked, paused and blocked decisions of act 2 with the
same ids as in the pack.

## 4. After the session

| What | Command |
|---|---|
| Remove the journey rows | `python -m supervisor.demo.showcase journeys --reset` (second run prints `nothing to remove`) |
| Check the sources are still the same | `python tools/showcase_sources.py --check` |
| What stays | The evidence chain and the decision rows (append only), and the portfolio rows of act 1 (`portfolio --remove`) |
