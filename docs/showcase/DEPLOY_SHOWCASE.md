# Deploy the full product on Databricks and run the four showcases

For the owner. Windows `cmd` on the laptop, plus one Databricks notebook. OAuth only: never set or
paste `DATABRICKS_TOKEN`. Per-workspace values are `FILL-ME-...` in this file; the filled copy of
`app.yaml` and `databricks.yml` comes to you in a separate zip and is never committed.

Status: the whole flow ran end to end on a laptop (SQLite) on 2026-10-29, and the video of that run
is the reference. **Nothing of the showcase has run on Delta or on the gateway model yet.** The first
Databricks run is the test. Report every `[FAIL]` line.

| Document | Use it for |
|---|---|
| `docs/deploy/LAUNCH_DATABRICKS.md` | the base deploy: bundle, tables, grants, models, failure map |
| `docs/showcase/SHOWCASE_PLAN.md` | what each act shows and why |
| `docs/showcase/SCRIPT.md` | the presenter script, screen by screen, with the expected numbers |
| this file | the order of work from an empty workspace to the show |

## 1. The picture

```
 laptop (you, OAuth profile)              workspace
 +----------------------------+  deploy  +--------------------------------------------+
 | bundle (v0.11.0)           | -------> | App: Guardian (console + gate)  [STOP for   |
 | bootstrap_schema (SQL)     | -- SQL ->|   steps 5.2 to 5.4, START for the show]     |
 | act 1 seed (state tables)  | -- SQL ->| Delta tables  catalog.schema (86 tables)    |
 +----------------------------+          | Volume: keys, spool, anchors, DATA_DIR files|
                                         | Notebook "showcase-seed" (cluster):         |
                                         |   journeys, factory  (one chain writer)     |
                                         | Gateway model (GLM 5.3 flash): judges, law  |
                                         |   agent, drafter                            |
                                         +--------------------------------------------+
```

Rule: **one evidence-chain writer at a time.** The journey and factory runners open their own
runtime and write the chain. The App must be fully stopped while they run. A second writer is refused
with `ChainConflictError ... only one chain writer may run`. This happened on the laptop when the
console had not yet exited; nothing broke, the run stopped. Wait for the state `STOPPED`.

## 2. Order of work

| # | Step | Where | Time |
|---|---|---|---|
| 1 | Unpack the bundle, fill in the values, check the showcase flags | laptop | 15 min |
| 2 | Create or upgrade the tables | laptop | 5 min |
| 3 | Deploy the App, grants, role map, first start | laptop, Apps UI | 30 min |
| 4 | Smoke check | browser | 5 min |
| 5 | Seed the showcases (act 1 with the App on; acts 2 to 4 with the App stopped) | laptop, notebook | 30 min |
| 6 | Start the App, rehearse with the script | browser | 30 min |
| 7 | The show (25 min) | browser, second window for traffic | |
| 8 | Clean up | laptop, notebook | 5 min |

## 3. Bundle, values, flags (step 1)

1. Unzip `supervisor-databricks-0.11.0-<sha>.zip` to `C:\work\supervisor`. Check the hash with
   `certutil -hashfile <zip> SHA256` against `SHA256SUMS.txt`.
2. Fill in `databricks.yml` and `app.yaml` as in `LAUNCH_DATABRICKS.md` section 3, or copy the two
   files from the FILLED zip (already filled for your sandbox workspace).
3. Check that these lines are active (not commented) in `app.yaml`. The FILLED copy has them on.

| Group | Variables (all `"1"`) |
|---|---|
| Showcase | `SHOWCASE_ENABLED` (demo workspace only, never a production App), `CONSOLE_UX5` (the new console design) |
| Governance and register | `GOVERNANCE_ENABLED`, `CONSOLE_SYSTEMS_ENABLED`, `CONSOLE_NAV_V3`, `CONSOLE_OVERVIEW_V4`, `CONSOLE_REGISTER_V2`, `CONSOLE_REGISTER_DUTIES`, `REGISTER_V3`, `CLASSIFICATION_V2`, `RISK_DIMENSIONS`, `RISK_DUTIES`, `OVERVIEW_PORTFOLIO`, `INVENTORY_ENABLED`, `CONSOLE_STATE_ACTIONS`, `CONSOLE_WORKFLOW_ACTIONS` |
| Onboarding | `ONBOARD_INTAKE`, `ONBOARD_FACTS`, `ONBOARD_PREDEPLOY`, `ONBOARD_ATTACH_VIEW`, `ONBOARD_ORCHESTRATOR`, `SMART_GUARDIAN`, `GUARDIAN_BINDINGS_ENABLED` |
| Gate | `DETECTORS_ENABLED`, `INLINE_REDACTION_ENABLED` |
| Factories | `AGENT_FACTORY`, `AGENT_FACTORY_GATE`, `FACTORY_SEED_STARTERS`, `REGKB_INTERNAL`, `LAWAGENT_ENABLED`, `GUARDIAN_FACTORY`, `GUARDIAN_SHADOW` |
| Proof | `REGULATOR_PACK`, `REGWATCH_ENABLED`, `REGKB_CHANGE_LOOP` |

4. `POLICY_DIR` must name two folders: `policies:src/supervisor/demo/showcase_data/policy`. Without
   the second folder the masking and the limits of the three journey agents do not apply.
5. The model lines (`LLM_BASE_URL`, `LLM_MODEL`, `JUDGE_T1_MODEL`, `LLM_API_SHAPE=responses`) point to
   the gateway model (`LAUNCH_DATABRICKS.md` section 7). With them, the factory numbers are real model
   numbers. Without them the runners refuse the fake model in `databricks_app` mode.
6. Optional, for a GO verdict in the pre-deploy step: deploy the three candidate Apps
   (`LAUNCH_DATABRICKS.md` section 10), then set `PREDEPLOY_HTTP_TARGET=1`,
   `PREDEPLOY_HTTP_ALLOWED_HOSTS=*.databricksapps.com`, and in the notebook
   `SHOWCASE_APP_URL_KB_HELPDESK_BOT`, `SHOWCASE_APP_URL_CS_ASSISTANT`,
   `SHOWCASE_APP_URL_PAYMENT_OPS_COPILOT`. Without them the verdict is `NO-GO` (no running agent to
   test). That is correct, and the script says so.

## 4. Tables (step 2)

From the bundle folder, with `SQL_BACKEND=databricks_rest` and the `DATABRICKS_*` lines in `.env`:

```
databricks auth login --host https://FILL-ME-workspace-host --profile FILL-ME-profile
.venv\Scripts\python.exe -m supervisor.cli preflight
.venv\Scripts\python.exe -m supervisor.jobs.bootstrap_schema --plan
.venv\Scripts\python.exe -m supervisor.jobs.bootstrap_schema
```

Upgrade from v0.9.0 adds one table, `detector_override` (smart guardian Accept). It never drops
anything. If you cannot run SQL from the laptop, paste `bootstrap_schema_v0100_delta.sql` (from the
FILLED zip) into the SQL editor.

## 5. App, grants, users (step 3)

Do `LAUNCH_DATABRICKS.md` sections 5, 6 and 7: `bundle validate`, `bundle deploy`, `bundle run`,
then the grants to the App service principal (tables, schema, Volume, the model service). After every
`bundle deploy`, add the Model resource again in the Apps UI (failure map in that file).

**Two people.** Every approval step needs a second person. The author can never approve. In
`config\auth.yaml` (local copy), give:

| Person | Roles | Workspace groups (for the factory) |
|---|---|---|
| You (presenter) | `admin`, `reviewer` | the group mapped to `model_risk`, `data`, `cyber`, `platform` |
| A colleague (second person) | `reviewer`, `approver` | `model_risk`, `platform` |

Set `group_lookup: scim_me` and keep `sql` and the SCIM scope in `user_api_scopes` (comments in the
file). Without groups the factory falls back to the role mapping of `config\factory_groups.yaml`.
The runners use the synthetic people of `config\users.yaml` (`reviewer.an`, `reviewer.binh`,
`lead.model`, `lead.data`, `lead.cyber`, `second.line`). Those rows show in the console with these
names. Your own live clicks show your SSO name.

## 6. Smoke check (step 4)

| Check | Expected |
|---|---|
| `GET <app url>/healthz` | `"status":"ok"`, `schema_ok: true` |
| Console, My overview | loads; no `TABLE_OR_VIEW_NOT_FOUND` (else run step 2 again, or open `/console/admin/schema`) |
| Console, Factory | the eight dimensions and six starter agents (draft) |
| Console, Guardian factory | empty list, "New guardian" button |

## 7. Seed the four showcases (step 5)

### 7.1 Act 1, portfolio (App may run)

The portfolio seeder writes state tables only, no chain record. From the laptop:

```
set SHOWCASE_ENABLED=1
.venv\Scripts\python.exe -m supervisor.demo.showcase portfolio --systems 300 --dry-run
.venv\Scripts\python.exe -m supervisor.demo.showcase portfolio --systems 300 --seed 1
```

Laptop result: 300 systems, 22,231 rows, 5 seconds. On Delta expect minutes (batched `INSERT`).

### 7.2 Stop the App

```
databricks apps stop FILL-ME-app-name --profile FILL-ME-profile
databricks apps get  FILL-ME-app-name --profile FILL-ME-profile
```

Go on only when `compute_status` says `STOPPED`.

### 7.3 Acts 2 to 4, in a notebook on the cluster

The runners also write files under `DATA_DIR` (source intake, facts, pre-deploy reports, factory
packs). These files must be on the App Volume, so run them in a notebook on the cluster, not on the
laptop. Create the notebook `showcase-seed` and attach it to the shared cluster.

Cell 1, packages (offline wheels from the bundle, copied once to the Volume):

```
%pip install --no-index --find-links /Volumes/FILL-ME-catalog/FILL-ME-schema/FILL-ME-volume/supervisor/wheels -r /Workspace/FILL-ME-bundle-folder/requirements.offline.txt
```

Cell 2, the same settings as the App (copy them from your filled `app.yaml`):

```
import os, sys
sys.path.insert(0, "/Workspace/FILL-ME-bundle-folder/src")
os.chdir("/Workspace/FILL-ME-bundle-folder")
V = "/Volumes/FILL-ME-catalog/FILL-ME-schema/FILL-ME-volume/supervisor"
os.environ.update({
    "SQL_BACKEND": "databricks_rest", "DATA_DIR": V + "/data", "SIGNER_KEY_PATH": V + "/keys/evidence_ed25519.pem",
    "SPOOL_DIR": V + "/spool", "ANCHOR_PATH": V + "/anchors",
    "POLICY_DIR": "policies:src/supervisor/demo/showcase_data/policy",
    "CONSOLE_URL": "https://FILL-ME-supervisor-app-url",
    # every flag of section 3 table, each "1"; and the four model lines of section 3 item 5
})
from supervisor.demo import showcase
def run(*args):
    rc = showcase.main(list(args))
    print("RC", rc)
    assert rc == 0, args
```

Use the same values as `app.yaml` for `DATA_DIR`, `SIGNER_KEY_PATH`, `SPOOL_DIR` and `ANCHOR_PATH`. A
different key path makes a second signing key and the offline verify then names two keys.

Cell 3 onwards, one command per cell. Choose the start point (SCRIPT.md section 1):

| Cell | Command | Leaves for the live show |
|---|---|---|
| 3 | `run("journeys", "--dry-run")` | plan only |
| 4 | `run("journeys", "--step", "3")` (or `"1"` for the whole flow live, `"9"` for result only) | steps 4 to 9 per journey |
| 5 | `run("factory", "--part", "agents", "--until", "tested")` | submit, two approvals, activate |
| 6 | `run("factory", "--part", "guardians", "--until", "shadow")` | two approvals, go-live |

Laptop times: journeys 20 s per step for three candidates, factory agents 6 s and guardians 5 s on the
fake model. On the gateway model the full gate takes minutes per agent. Check the printed table:
both agents `tested`, both guardians `shadow`, no `[FAIL]`. The table is also in
`DATA_DIR/showcase/factory-results.json`. Copy its agent rows into SCRIPT.md "Numbers" before the
show (these are the real gateway numbers).

### 7.4 Start the App

```
databricks apps start FILL-ME-app-name --profile FILL-ME-profile
```

From now on do not run cells 4 to 6 while the App runs.

## 8. The show (step 7, 25 minutes)

Detail and expected values per screen: `SCRIPT.md`. Short form:

| Act | Min | Pages | Live action | Who clicks |
|---|---|---|---|---|
| 1 Portfolio | 3 | My overview (scope All), Systems | none | you |
| 2 Journeys | 10 | Candidates, facts card, Register step 3, system tabs Classification, Risk assessment, Duties, Guardians, Tasks, agent page | the steps after your start point; accept the autonomy cap line of `payment-ops-copilot` live (after it, every money call pauses for a person, `GATE-AUTONOMY-CAP`) | you ask, the colleague approves |
| 2 Traffic | (2) | agent page, Activity | second window: traffic generator (below) | |
| 3 AI factory | 6 | Factory, Internal documents, agent editor steps 2, 3, 6, 9, simulation review, Test and promote | submit; approve owner lead and second line; activate | you, colleague |
| 4 Guardian factory | 4 | Guardian factory, both editors (Benchmark, Shadow, Promotion) | two approvals and Go live per guardian; then traffic again | you, colleague |
| 5 Proof | 2 | system Duties tab, `Regulator pack (HTML)`, Regulation watch | download the JSON pack; verify offline on the laptop, edit one byte, verify again (fails) | you |

Traffic against the deployed gate (laptop, second window). The agent credential is in
`SCRIPT.md` "Traffic against the deployed gate":

```
.venv\Scripts\python.exe -m supervisor.demo.showcase traffic --candidate payment-ops-copilot --url https://FILL-ME-supervisor-app-url --bearer-env SHOWCASE_TOKEN --minutes 5 --rate 20
```

Over HTTP the generator cannot resume a paused agent: after the first pause the other calls answer
`GATE-PAUSED`. Resume on the agent page (two people), or show `kb-helpdesk-bot` (no pause).

What the payments traffic shows after act 4 (laptop result): a transfer above 20,000,000 VND is still
**paused** by the policy rule `SHOW-PAY-01`, and the new guardian
`transfer-above-limit-needs-approval` is listed next to it as a finding. A live guardian turns an
*allowed* call into a block; it does not change a pause, which already waits for a person. The block
by `GATE-GUARDIAN-BLOCK` shows on an agent without the pause rule: the factory runner prints it as the
final check. Say this on stage if asked. The account-number mask shows on every `add_payee` call.

Offline verify (laptop, no network):

```
.venv\Scripts\python.exe -m supervisor.evidence.verify regulator-pack.json
```

Expected `RESULT: OK` with the content hash and the Ed25519 signature. After you change one value
the check fails.

## 9. Clean up (step 8)

| What | Command |
|---|---|
| Journey rows | `run("journeys", "--reset")` (App stopped) |
| Factory rows | `run("factory", "--reset")` (App stopped) |
| Portfolio rows | `showcase portfolio --remove` (laptop) |
| What stays | the evidence chain and the gate decision rows (append only, by design). Every row is tagged `demo:showcase` or has the prefix `shw_` |
| Switch off | `SHOWCASE_ENABLED` to `"0"` in `app.yaml`, redeploy |

## 10. If something fails

| Symptom | Do |
|---|---|
| `ChainConflictError ... only one chain writer may run` | the App (or another notebook) still runs. Stop it, wait for `STOPPED`, run the cell again. The step that failed changed nothing after its last `[OK]` line |
| `[FAIL] the showcase seeder is off` | `SHOWCASE_ENABLED=1` in the shell or in cell 2 (the runners read the process environment) |
| `unexpected_class` in a journey | stop; do not click on. Send the output |
| Factory `model_not_configured` or `model_error` | the model lines are empty or the App service principal has no `EXECUTE` on the model service |
| A page shows no showcase rows | the App needs the same flags as the notebook |
| Pre-deploy `NO-GO` | expected without the candidate App URLs (section 3 item 6) |
| Anything in the base deploy | `LAUNCH_DATABRICKS.md` section 13 |

## 11. Not proven yet

| Item | Risk | How we learn |
|---|---|---|
| Runners on Delta through the Statement Execution API | slow, or a missing grant | the first notebook run, step 7.3 |
| Runners in a notebook (paths, `%pip`, Volume files) | the cluster image differs from the laptop | cell 1 and 2 output |
| Gateway model in the factory gate | slower, numbers differ from the fake model | the printed table |
| Pre-deploy against the candidate Apps | headers, allow-list | section 3 item 6 |
| Two real SSO users with groups | `scim_me` scope | your colleague's first approval |
