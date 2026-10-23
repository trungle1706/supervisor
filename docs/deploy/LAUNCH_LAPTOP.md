# Launch Supervisor v0.5.0 on the work laptop

Windows 11, `cmd` only, no admin rights, Python 3.11, offline at run time, SQLite, synthetic data.
Every command is `cmd` syntax. Run them from the `supervisor` folder unless stated. Nothing here
needs the internet after the packages are installed. Nothing here talks to Databricks.

Not run on a Windows laptop yet. The same steps were run on Linux with the same Python 3.11 and
the same files (`docs/deploy/SMOKE_RESULT.md`). The first Windows run is the test.

## 1. What you need

| Item | Check |
|---|---|
| The bundle `laptop\supervisor-0.5.0-<sha>.zip` | `SHA256SUMS.txt` in the same folder: `certutil -hashfile supervisor-0.5.0-<sha>.zip SHA256` must match |
| Python 3.11 | `py -3.11 --version` prints `Python 3.11.x` |
| Package index for `pip` | Nexus (section 3), or a folder of wheels |
| A browser | Edge or Chrome |

## 2. Unzip

Unzip to `C:\work\`. You get `C:\work\supervisor`.

```
cd /d C:\work\supervisor
```

## 3. Install (pip, from `requirements.txt`)

`requirements.txt` was exported from `uv.lock`. It has every package for the laptop, including
`pypdf` for PDF intake. It has no compiler step and no model download.

```
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt --index-url https://nexus-dev.techcombank.com.vn/repository/pypi-common-proxy/simple/ --trusted-host nexus-dev.techcombank.com.vn
```

If your desk uses another index, change the two options. If `pip` reports a certificate error,
add `--use-feature=truststore`. The package `supervisor` itself is not installed; the next line
tells Python where it is. Run it in every new `cmd` window:

```
set PYTHONPATH=%CD%\src
```

From here, `PY` means `.venv\Scripts\python.exe`. Never use the `.exe` stubs in `.venv\Scripts`
(AppLocker blocks them). Always `python -m ...`.

## 4. Configure

```
copy .env.laptop.example .env
notepad .env
```

In Notepad choose "All files" when you save, or it becomes `.env.txt`.

What to check in `.env`:

| Line | Set |
|---|---|
| `SSL_OS_TRUSTSTORE` | `1` on the bank laptop (Windows certificate store) |
| `LLM_BASE_URL` | empty: mock judges, labelled `mock` on every screen. A local model is optional |
| `URL_FETCH_ALLOWLIST` | leave `FILL-ME-allowed-domain` while `URL_FETCH_ENABLED=0` |
| lines that start with `# ` | optional; leave them off |

The file lists every flag added in phase 4 and 5 with one comment each. Never put
`DATABRICKS_TOKEN` in it: the preflight refuses to run.

## 5. Check

```
.venv\Scripts\python.exe -m supervisor.cli preflight
```

Expected: `preflight: N checks, 0 failed`. `[SKIP]` lines are fine (optional extras, no Databricks).
A `[FAIL]` line names its fix.

Then the launch smoke test. It starts the app on a free port with a temporary folder, opens the
console, registers a system, runs a Playground check, verifies the evidence chain, stops the app:

```
.venv\Scripts\python.exe tools\smoke_launch.py
```

Expected: one `[OK]` line per step and `[OK] smoke test passed`. On a `[FAIL]` it prints the last
lines of the app log. Send that output back; nothing else is needed.

## 6. Seed the demo

```
.venv\Scripts\python.exe -m supervisor.cli demo seed
.venv\Scripts\python.exe -m supervisor.cli demo seed-systems --candidates-dir C:\work\candidates
```

| Command | What it does |
|---|---|
| `demo seed` | fresh store in `data\local\demo`, three agents (customer service, credit pre-qualification, payments), a normal day of 134 gate decisions, a reset snapshot |
| `demo seed-systems` | reads `C:\work\candidates\<name>\supervisor.manifest.yaml`, registers each as an AI system, links its agent, makes the Decision 33 draft, prints the system ids. Run it again: nothing changes. A folder with no manifest, or a bad one, is `[SKIP]` with the reason |

Without `--candidates-dir` the folder is `%USERPROFILE%\supervisor-testbed\candidates`. The
manifest format is in section 8. If you have no candidate folders, the command prints `[SKIP]`
and you register systems by hand in step 1 of the story.

## 7. Serve, open the console, tell the story

Stage mode runs the console and the demo keys in one process (one evidence chain writer):

```
.venv\Scripts\python.exe -m supervisor.cli demo serve
```

Open http://127.0.0.1:8000/console/ . Pick a user in the top-right menu (dev identity, demo only;
`reviewer.an` can edit systems, `owner.credit` owns the seeded systems). Language: top right, EN or VI.

Keys in the `cmd` window: `1` to `4` inject incident 1 to 4, `t` tamper test, `z` reset to the
snapshot (the seeded systems stay), `s` status, `q` quit. Plain server without keys:
`.venv\Scripts\python.exe -m supervisor.cli serve` (it reads the same `data\local\demo` folder).

### The ten steps

| # | Say | Do | See | Flag |
|---|---|---|---|---|
| 1 | Register a product | Governance, Systems, Register (`/console/systems/new`). Name `Payments assistant (demo)`, owner `owner.credit`, system type `assistant`, personal data `identifiable`, money movement yes, human control `none`, autonomy `l2_workflow_step` | Preliminary checks: readiness, proposed risk class, packs to run, guardian floor. Nothing is applied. A draft is created with intake tasks | `GOVERNANCE_ENABLED`, `CONSOLE_SYSTEMS_ENABLED` |
| 2 | Rules fire | Open the system, tab Rules | Obligations, controls, risks, tasks and the guardian floor, each with the rule and the fields that fired | same |
| 3 | Classify | Tab Classification: Make a draft, answer `Q-OTHER` no with a justification, Apply | Decision 33 class `high_risk` (money movement, no approval before execution), risk floor `high`. A stale draft is refused. You cannot apply as the system's own reviewer | same |
| 4 | Inherit risk | Open `Bank knowledge chatbot` (or any seeded system), tabs Overview and Risks | Risk level is the higher of the manual level and the level of the linked agents, tools and data; each shows its source | `INVENTORY_ENABLED` |
| 5 | Lifecycle | Tabs Tasks and Reviews | Tasks sized by level and class. A stage approval needs a second person (segregation of duties). Reviews lock when completed | `GOVERNANCE_ENABLED` |
| 6 | Guard it | Tab Guardians | Per-system switches. Floor slugs are locked on. Gate rules cannot be bound | `GUARDIAN_BINDINGS_ENABLED` |
| 7 | Watch it | Supervisor, Overview and Activity | Calls checked, blocks, pauses, detector health, latency, chain state per system | existing |
| 8 | React | In the `cmd` window press `1`, then `2`. Cases and alerts, Incidents | An agent is blocked or paused. The event maps to an action: incident, notify, raise risk, re-evaluate, review, webhook row (a stub; sends nothing) | `GOVERNANCE_ACTIONS_ENABLED` |
| 9 | Prove | System tab Reports, and Transparency (`/console/transparency`) | Transparency report, incidents, chain verify, audit pack link. Press `t` for the tamper test: the break is found | `TRANSPARENCY_ENABLED` |
| 10 | Agent-first | New `cmd` window: `curl.exe -s -H "X-Dev-User: reviewer.an" http://127.0.0.1:8000/v1/kpis` | KPIs as integers: coverage, quality, speed. The MCP endpoint is `POST /mcp` (21 tools, writes make drafts only, decision tools are refused by name). `docs\mcp-server.md` has a signed client example | `MCP_SERVER_ENABLED` |

Step 11 of `docs\phase4\PITCH_READINESS.md` (auto-record from a Databricks workspace) cannot run on
the laptop. It needs a workspace and `INVENTORY_SCAN_V2=1`; see `docs\deploy\LAUNCH_DATABRICKS.md`.

What the story must not claim: nothing has run on a live Databricks workspace; judges are `mock`
until a model is configured; the guard model and the moderation judge are built and off; there
is no OCR (a scan is "uninspectable" and fails closed on risky tools); a bare name with no cue
can pass the masker. Full list: `docs\phase4\PITCH_READINESS.md` sections 3 and 6.

Document intake (phase 5): Supervisor, Playground, add a document to the context (`.txt`,
`.csv`, `.docx`, `.pdf`). The result has a Documents table. A URL in the context is refused
while `URL_FETCH_ENABLED=0`.

## 8. Candidate manifests (the input of `demo seed-systems`)

One file per candidate agent: `<candidates dir>\<name>\supervisor.manifest.yaml`. Synthetic data only.

```yaml
manifest_version: 1
system:
  name: "Bank knowledge chatbot"
  owner_user: owner.credit
  owner_team: "SME Credit Underwriting (synthetic)"
  purpose: "one paragraph"
  system_type: assistant        # assistant | decision | automation | platform | feature
  org_role: deployer            # provider | deployer | both
  user_segment: internal        # internal | customer | partner
  personal_data: none           # none | identifiable | pseudonymised | special
  money_movement: false
  credit_decision: false
  human_control: post_review    # pre_approval | post_review | none
  business_impact: medium       # high | medium | low
  autonomy_level: l1_assistive  # l0_rule_based .. l5_self_directed
agent:
  agent_id: kb_chatbot
  name: "Bank knowledge chatbot"
  model_family: qwen
  plug_point: fastapi_middleware   # fastapi_middleware | langgraph_middleware | sdk
  tools:
    - {name: search_policies, risk_class: read_only, description: "..."}
  policy_fragment: policies/kb_chatbot.yaml
  artifact_dir: artifact
```

| Rule | Detail |
|---|---|
| Agent registry row | Added when absent: owner team from the system, host type `app`, plug point and model family from the manifest, gate state `SHADOW`, one `agent_registered` chain record |
| Risk tier of the agent | The highest tool risk class: `read_only` is low, `pii_export` medium, `money` and `credit` high |
| System | Registered with the intake fields; the id is `sys_` plus a hash of the name, so a second run is a no-op |
| Classification | A draft is made and left for a person to apply. It is never applied by the command |
| Policy fragment | Not deployed by this command. The agent runs in `SHADOW` in the registry until its policy is deployed (`docs\onboard.md`) |
| `[SKIP]` | No manifest, bad YAML, a missing or wrong field, a value the system form refuses. The other folders still run |

## 9. Stop, reset, move on

| Need | Command |
|---|---|
| Stop | `q` in the `demo serve` window, or `Ctrl+C` |
| Back to the seed (systems stay) | `z` in the `demo serve` window, or `.venv\Scripts\python.exe -m supervisor.cli demo reset` with the server stopped |
| Start over | `.venv\Scripts\python.exe -m supervisor.cli demo seed`, then `demo seed-systems` |
| Verify an evidence export | `.venv\Scripts\python.exe -m supervisor.cli verify <export dir> --strict` |
| The whole demo 20 times | `.venv\Scripts\python.exe -m supervisor.cli demo --loop 20 --quiet` (wipes `data\local\demo`) |
| Databricks | `docs\deploy\LAUNCH_DATABRICKS.md` |

## 10. If something fails

| Symptom | Fix |
|---|---|
| `No module named supervisor` | `set PYTHONPATH=%CD%\src` in this `cmd` window (section 3) |
| `pip` cannot find a package | check the index options (section 3); the list is `requirements.txt` |
| `.env.txt` instead of `.env` | save again with "All files" |
| `DATABRICKS_TOKEN is set` | remove it from the environment and from `.env` |
| Port 8000 is in use | `demo serve --port 8001`, or `serve --port 8001` |
| `no seeded demo` | run `demo seed` first |
| `ChainConflictError` | two processes use the same folder; stop the other one |
| Anything else | `docs\RUNBOOK.md` has a symptom, cause, fix table. Paste the `[FAIL]` line |
