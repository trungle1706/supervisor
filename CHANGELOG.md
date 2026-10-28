# Changelog

## Unreleased

- WP-O1 (phase 9): candidate source intake, `ONBOARD_INTAKE` (default `0`),
  `ONBOARD_INTAKE_MAX_MB` (default `20`), `ONBOARD_GIT_HOSTS` (default empty = git off). New
  **Source** panel in the Candidates drawer and **Source** tab on the agent page (upload form,
  attempts list, **Re-upload**); `POST` and `GET /v1/intake/{node_id}` (`systems.edit` /
  `systems.view`; a POST writes two audit rows). A zip of at most 20 MB with text files only
  (`.py .yaml .yml .toml .json .md .txt .cfg .ini .env.example .sql .ipynb`; notebooks keep code
  cells as `.py`) or an `https://` URL on an allowed host is checked (no `..`, absolute path,
  symlink, binary file), scrubbed with the WP16 scrubber in memory, then stored under
  `DATA_DIR/intake/<node_id>/<n>/`. Each attempt is a row of the new table `intake_attempt` (run
  `python -m supervisor.jobs.bootstrap_schema` before the new app version on Delta); a re-upload is
  attempt n+1. The clone runs in the new `sandbox.git_clone_https` (https only, shallow). The
  workspace folder source answers HTTP 400 `not_built` (WP-O1c). `BodyLimitMiddleware` takes a
  per-path limit so the intake paths may exceed `MAX_REQUEST_BYTES`. Off = no tab, no panel,
  routes answer 400 `intake_off`.
- WP-P3 (live-run hardening, from the first live run on Databricks, 2026-10-27). Both new flags
  default off; with them off nothing changes except the extra fields of `/healthz`.
  - `SCHEMA_SELFCHECK=1`: at start the app compares `schema/model.yaml` with the warehouse (one
    `information_schema.columns` query) and keeps the result. A missing table or column shows at
    `/console/admin/schema` (admin) as the exact SQL plan (`CREATE TABLE IF NOT EXISTS`, `ALTER
    TABLE ... ADD COLUMNS`) to copy, plus a banner on the pages an admin sees. The app never runs
    DDL. SQLite: no-op, reports ok. A failing check logs a WARNING and the state is `unknown`.
  - `GET /healthz` adds `schema_ok` (true, false, "unknown"), `judge_sweep` (enabled, disabled),
    `gate_timeout_s` (the configured `GATE_DECISION_TIMEOUT_S`) and `model_resource` (ok, fail,
    unknown). `HEALTHZ_MODEL_PROBE=1` turns on the model probe (one small call to the LLM gateway
    in a background thread, cached 60 s); off by default it stays "unknown".
  - `python -m supervisor.demo seed --databricks`: writes three synthetic systems, their agents
    and three cases (with chain evidence) into the configured SQL backend. Idempotent, deletes
    nothing. The marker is the id prefix `demo-` (agent ids, system names, case source refs): the
    tables have no `demo` column.
  - Docs: the timeout budget rule in `docs/ingress-auth.md` (candidate `SUPERVISOR_TIMEOUT_S` must
    be larger than `GATE_DECISION_TIMEOUT_S`); four new rows in the failure map of
    `docs/deploy/LAUNCH_DATABRICKS.md` (old tables, gate timeout, Model resource reset by
    `bundle deploy`, stale `.databricks` snapshot, Umbrella DNS block).
  - New permission `schema.view` (admin) in the role matrix.

- WP-P1: `CONSOLE_WORKFLOW_ACTIONS` (default `0`). The Tasks tab of a system gets buttons: Done,
  Waive (reason of 10 characters or more; the creator of the task cannot ask; a second person
  approves or rejects the waiver), Request move (target stage, reason), Approve or Reject by a
  second person (the requester gets HTTP 400 `same_person`) and Move. The rules are those of
  `TaskService` and `LifecycleService`; the console adds the role check (task role or
  `systems.edit`) and the reasons. Six new routes under `POST /console/systems/<id>/`; with the
  flag off they answer HTTP 400 naming the flag and the tab is read only as before. Each action
  writes the two `console_action` rows with a fixed note (action, status before and after, hash
  of the reason). The next action of a system and the stage approvals waiting for you link to the
  Tasks tab, never to an API path. `LifecycleService.request` takes an optional `reason`
  (kept in `stage_approval.reason` while the request waits; the API call is unchanged). No schema
  change. See `docs/console.md`.
- WP-P2 (phase 8): `CONSOLE_STATE_ACTIONS` (default `0`) closes UX findings H3, H4 and M8.
  Agent page: **Request RUNNING** (from SHADOW, reason required) and **Approve RUNNING** by a
  second person who is the agent owner or a policy reviewer; the requester gets HTTP 400
  `same_person`. It uses the rule of `POST /v1/gate/agents/{id}/state`; the shadow would-block
  count of the last 7 days shows next to the button. Decision 33 apply: the system owner cannot
  apply the class on the own system (`owner_cannot_apply`); every person answer needs a
  justification of 20 characters (`justification_too_short`). Guardian switch-off: reason
  required; on a production or high-risk system a second person approves before the binding takes
  effect (new table `guardian_off_request`; run `python -m supervisor.jobs.bootstrap_schema`
  before the new app version on Delta). The guardian floor is unchanged. New routes:
  `POST /console/agents/{id}/running/{request|approve}`,
  `POST /v1/systems/{id}/guardian-off-requests/{rid}/decide`,
  `POST /console/systems/{id}/guardian-requests/{rid}/{approve|reject}`. Off = no change.
- WP-L2: `JUDGE_FAMILY_CONFLICT_ALLOW` (default `0`). When set, a judge, guard or quality-scorer
  model that shares the family of a registered agent no longer stops start-up: one WARNING per
  pair is logged, and every `judge_verdict` evidence record for that pair carries
  `independence: "reduced"` and `family_conflict: true`. For sandbox and single-model
  workspaces. Allowed in `databricks_app` mode. An unknown family is still refused.

## v0.5.0 (phase 4 governance product, phase 5 guardian detectors, deploy package) - 2026-10-23

Everything new is behind a flag that is off by default; with the flags off every answer, row and
chain record is as in v0.4.1 (each package has an off-path test). `__version__` is `0.5.0`
(`pyproject.toml` keeps its old `0.2.0`, as in the earlier releases: `uv.lock` records it).
Nothing has run on a live Databricks workspace. On Delta, run
`python -m supervisor.jobs.bootstrap_schema` BEFORE the new app version (migration note below).
The pitch status and its limits: `docs/phase4/PITCH_READINESS.md`. Deploy package:
`docs/deploy/LAUNCH_LAPTOP.md`, `docs/deploy/LAUNCH_DATABRICKS.md`.

### What is new

| Phase | Packages | Feature | Docs |
|---|---|---|---|
| 4 | G0, UX4a, G1, G2, G3, G5, UX4b, S1, G6 | Governance product on the shared core: the AI system (intake, team, components, inherited risk), merged sidebar, lifecycle with stage approvals, reviews and outbound events, assignment rules and Decision 33 classification, workspace scan v2 and auto-record, governance actions and incidents, per-system guardian bindings with a mandatory floor, MCP server (21 tools, draft-only writes) and `GET /v1/kpis` | `docs/governance.md`, `docs/decision33.md`, `docs/governance-actions.md`, `docs/guardian-bindings.md`, `docs/mcp-server.md`, `docs/inventory.md` |
| 5 | D1, D2, D3, D4 | Guardian detectors: document and URL intake, secrets and custom DLP rules, guard model adapter and decision memo (NO-GO, off), judge moderation (off) | `docs/detectors.md`, `docs/guard-model-decision.md` |
| 6 | P1 | Deploy package: `demo seed-systems`, `tools/smoke_launch.py`, laptop and Databricks bundles, launch guides, `.env.laptop.example` | `docs/deploy/` |

### New flags and settings (all default off or empty)

`GOVERNANCE_ENABLED`, `CONSOLE_SYSTEMS_ENABLED`, `CONSOLE_NAV_SECTIONS`, `CONSOLE_NAV_V3`,
`CONSOLE_CATALOG_ENABLED`, `GOVERNANCE_ACTIONS_ENABLED`, `SCHED_GOVERNANCE_S`,
`GUARDIAN_BINDINGS_ENABLED`, `MCP_SERVER_ENABLED`, `WEBHOOKS_ENABLED`, `CLASSIFIER_AI_PREFILL`,
`INVENTORY_SCAN_V2`, `INVENTORY_AUTOREGISTER`, `DOCUMENT_INTAKE_ENABLED`, `URL_FETCH_ENABLED`,
`URL_FETCH_ALLOWLIST`, `PLAYGROUND_URL_FETCH`, `GUARD_MODEL_ADAPTER`, `GUARD_MODEL_URL`,
`GUARD_MODEL_NAME`, `GUARD_MODEL_VERSION`, `GUARD_MODEL_API_KEY`, `GUARD_MODEL_TIMEOUT_MS`,
`GUARD_MODEL_FAIL_CLOSED_APPROVED`. The laptop file `.env.laptop.example` and `app.yaml` list them
with one comment each.

### Deploy note for Delta (databricks_app mode)

New tables: `ai_system`, `system_team`, `system_component`, `assignment`, `classification`,
`stage_approval`, `review`, `outbound_event`, `incident`, `governance_event`, `mcp_app`,
`guardian_binding`. `bootstrap_schema` creates them and adds missing columns; it never drops.
`requirements.txt` now includes the `documents` extra (`pypdf`, BSD-3-Clause): the App BUILD must
find it.

### WP-P1: release and deploy package

- `requirements.txt` is exported with `--extra documents` (`EXPORT_REQS_ARGV` in `cli.py` and
  `release.py`); preflight reports the `documents` extra.
- `python -m supervisor.cli release --bundles --out <dir> [--ref v0.5.0]` builds `<dir>/laptop/`
  and `<dir>/databricks/`: the leak-swept zip of the ref, loose copies of the files read first,
  `SHA256SUMS.txt`. `build_release` takes `target` (`laptop`, `databricks`) and `ref`. The leak sweep
  allows `.env.laptop.example`.
- `python -m supervisor.cli demo seed-systems [--candidates-dir DIR]`: registers the candidate agents
  as AI systems from `supervisor.manifest.yaml` (agent registry row, system, link, Decision 33
  draft; idempotent; `[SKIP]` with the reason for a missing or bad manifest; refreshes the reset
  snapshot).
- `tools/smoke_launch.py`: starts the app on a free port with a temporary folder, opens the
  console, registers a system, runs a Playground check, verifies the chain, stops the app. Linux and
  Windows, no bash. Result: `docs/deploy/SMOKE_RESULT.md`.
- `.env.laptop.example`, `docs/deploy/LAUNCH_LAPTOP.md`, `docs/deploy/LAUNCH_DATABRICKS.md`;
  `app.yaml` and `databricks.yml` carry the phase 4 and 5 variables as FILL-ME or "0";
  `docs/live-test-kit.md` items 13 to 16 and `docs/databricks-prereqs.md` rows 9 to 12.

### Per-package notes

### WP-D1: document and URL intake

Two flags, both off by default: `DOCUMENT_INTAKE_ENABLED` (with `DETECTORS_ENABLED`) and
`URL_FETCH_ENABLED` with `URL_FETCH_ALLOWLIST`. Off = `context.documents` is HTTP 400 and every
answer, row and chain record is as before (tests keep the fingerprint). Details:
`docs/detectors.md` section 11.

- `context.documents` on `POST /v1/gate/check`, the Playground and the SDK: at most 10 documents,
  2 MB each, 10 unique URLs, 2 s per document. New payload part `documents`, scored by
  `injection_regex` and `dlp_vn` (a detector reads it only when it lists it in `parts`); the dlp
  transform applies to document text only on a `pii_export` tool. Coverage reports the part as
  scanned, cut or not read, with the reason.
- `detectors/intake.py`: TXT, CSV, Markdown, JSON, HTML, DOCX (standard library) and PDF
  (`pypdf`, new optional extra `documents`, BSD-3-Clause, logged in `docs/LICENSES.md`). The first
  bytes decide the kind. Images, scans, damaged and encrypted files are `document.uninspectable`
  with a reason; no OCR. Raw bytes and text are never stored: the chain keeps sha256, size and
  media type per document.
- New detector `document_intake` (`config/detectors.yaml`, `fail_closed: true`): findings
  `document.uninspectable`, `document.limit_exceeded`, `url.ssrf_refused`, `url.domain_blocked`.
  An unread document on a money, credit or pii_export tool is a block through the existing
  `GATE-DETECTOR-FAILED` path.
- `adapters/fetch/`: URL fetch behind the two flags. HTTPS only; the address is checked after DNS
  (private, loopback, link-local, metadata, shared, reserved, site-local, wrapped IPv6 refused) and
  the connection goes to the address that was checked; redirects only to the same host; 1 MB;
  3 s. Standard library only.
- Collectors: the SDK (`supervised_tool(documents_arg=...)`, `GateClient.check(documents=...)`),
  the LangGraph middleware (attachments of the newest human message) and the FastAPI middleware
  (multipart uploads) pass attachments when `DOCUMENT_INTAKE_ENABLED` is set in the agent process.
- Playground: documents in the context (limit 256 KB with documents), two samples
  (`document_invoice_vi`, `document_cv_vi`), a Documents table in the result.
- Harness rows `document_injection_vi`, `document_pii_vi`, `url_ssrf`
  (`python -m supervisor.detectors.intake_eval`, also in the detectors harness), golden set in
  `data/eval/documents/`, baseline, `docs/document-intake-validation-report.md`.
  `python -m tools.bench_documents` and `docs/latency.md` have the numbers (100 KB of PDF text:
  about 240 ms in total).
- Catalog card and EN and VI labels. `core/bounded.py` (a thread with a deadline and a slot cap).
- Review fixes: the intake has 1.4 s in all (the gateway's hard timeout is 2 s), so a slow file is
  `unread (deadline)` and the arguments are still scanned; one linear pass over DOCX XML (nesting
  and element caps, 8 MB per part, BOM and NUL refused); any reader error is `parse_failed`;
  documents have their own scan budget `limits.document_max_scan_bytes` (262,144) outside
  `max_payload_chars`, and on a pii_export tool only the cut document fails closed; the fetch
  deadline is checked before every read (headers capped at 16 KB); four reading slots; a dry run
  never fetches (`PLAYGROUND_URL_FETCH=1` allows it); the guardians view follows the intake flag;
  a disabled reporter fails closed on risky tools; `transformed_payload.documents` is
  `[{index, text}]` for changed documents only; digests are keyed with the mask key; non-ASCII
  URL paths are percent-encoded; `%PDF-` only at offset 0; `pypdf >= 6`.
- Changed outside the package: `core/detectors.py` (part `documents`, `parts_for`, coverage),
  `dlp_vn.py` and `injection_regex.py` (read the part), `detector_gate.py`, `engine.py`
  (`documents_on`), `routes.py`, `wiring.py`, `config.py`, `gateway/sdk.py`,
  `gateway/adapters/*`, `console/playground.py`, `catalog_view.py`, `guardians_view.py`, `i18n.py`,
  `detectors/harness.py`, `pyproject.toml` (extra `documents`, one ruff ignore), `uv.lock`.

### WP-D2: secrets group and custom rules for dlp_vn

No new flag. Three new `dlp_vn` settings, all off or empty by default; with none of them set the
detector output is byte for byte what it was (golden test). Details: `docs/detectors.md` section 3d,
`docs/masking.md`.

- `secrets: {enabled, action: report | block}`: 29 secret kinds reported as `secret.<kind>`
  (cloud keys, API tokens, JWT, PEM, DSN, password assignments and password fields, a secret in
  base64). A finding keeps the kind and a 12 character hash; the transformed payload holds
  `<SECRET:kind>`. `action: block` is the new gate rule `GATE-SECRET-IN-ARGS`: a secret in a tool
  argument blocks the call on every tool class, in the fail-closed shape of
  `GATE-DETECTOR-FAILED`. Default `report`.
- `custom_rules: [{id, kind: keyword | regex, pattern, mask_token?, preserve_length?}]`: strict
  schema, a bad regex or a risky shape (nested quantifiers, back references, length) stops the
  load; 1 ms per regex rule and text; mask token default `<CUSTOM:id>`.
- `mask_tokens: {pii.phone: "<PHONE>"}`: a fixed text for a built-in entity in the transformed
  payload.
- One pattern source: `src/supervisor/core/secret_patterns.py`, used by `dlp_vn` and by the
  onboarding scrubber. The scrubber gained GitLab, Hugging Face, Stripe, SendGrid, npm and Vault
  tokens, and the AWS secret key pattern accepts a key that ends in `/` or `+`.
- With inline redaction on, a call with a `secret.*` or `custom.*` finding takes the detector's
  masked `args`, so a secret does not stay in `transformed_args`.
- Harness suite `dlp_vn_secrets` (`python -m supervisor.detectors.harness --detector
  dlp_vn_secrets`): items are built at run time, so no credential-shaped string is committed; own
  baseline `data/eval/detectors/baseline_secrets.json`. Validation report section added.
  Observe mode lifts `GATE-SECRET-IN-ARGS` like other blocks.
- Catalog card text of `dlp_vn` extended (English and Vietnamese).

Review fixes (same entry):

- Custom regex: `?` counts as a variable repeat; more than two variable repeats, and two
  unbounded repeats in sequence, are refused at load (`.*.*.*.*x`, `\w+\w+\w+\w+!`,
  `a?`x22 `a`x22). A regex reads at most 2000 characters of a text. The budget is 10 ms per
  rule and call. A cut or an overrun is a `coverage.notes` entry, never `timed_out`.
- The hash in a secret finding is a keyed HMAC (masker key, else a per-process random key).
- Observe mode: `GATE-SECRET-IN-ARGS` is held on `pii_export` tools; where it is lifted the
  call carries the masked `transformed_args`.
- A base64 secret next to a plain secret is found. `password_field` matches the last word of
  the key name, covers Vietnamese and short names, and skips dates, versions, URLs and enum
  words. A secret used as a dict key is found and masked.

### WP-D4: judge moderation detector (toxicity and topic scope)

New detector `judge_moderation` (phase 5), off by default (`enabled: false`, `mrm_status: NO-GO`);
absent or off = nothing changes. Details: `docs/detectors.md` section 3e.

- Toxicity (one answer) and up to 5 topics `{name, definition}` (definition up to 400 characters on one
  line, the definition is what the judge reads), input and output, ONE judge prompt per text window on
  masked text with every question in it (at most 10 calls per check, `max_calls` default 12), overlapping
  windows, highest "yes" score per topic; a "no" never gives a finding. A deadline (80 percent of the
  gate timeout, or the per-detector `timeout_ms` setting) stops the calls; unasked questions are
  `not_executed` `budget_exhausted` (new reason, advisory). Review fixes: topic definitions escaped and
  quoted in the prompt; two draft topics renamed to bank topics (loan approval promises, staff and
  branch security). Findings `moderation.toxic` and
  `moderation.topic:<name>`, report only, never fail closed. MockJudge without a judge model,
  every finding `mock: true`. Strict topic checks when `config/detectors.yaml` or an agent override
  loads.
- `config/moderation_topics.yaml`: 10 editable draft topics in Vietnamese and English, none enabled.
- Harness rows with a small synthetic VI and EN set and a rubric; report
  `docs/judge-moderation-validation-report.md`. Catalog card and i18n (EN, VI); Guardians card
  binding `judge_moderation`.
### WP-D3: guard model detector and the model decision memo

One new detector, `guard_model`, off by default (`enabled: false`, `mrm_status: NO-GO` in
`config/detectors.yaml`). A slug that is absent from the file changes nothing. Details:
`docs/detectors.md` section 3d, memo `docs/guard-model-decision.md`.

- `guard_model`: a configured model scores user text in arguments, tool results, tool descriptions
  and documents for jailbreak and indirect injection (codes `guard.jailbreak`,
  `guard.indirect_injection`), input and output side, `llm` and `mcp`. Masked text only, no system
  prompt, 2,000-character windows with 500 overlap and the highest score wins, scores cached by text
  hash. Presets `permissive | balanced | strict` are thresholds per label in basis points.
- Port `GuardModelPort.score(texts)` (`core/ports.py`) and three adapters in
  `adapters/guard/`: a direct classifier endpoint (`POST <url>` with `{"inputs": [...]}`, the shape
  of a Databricks serving endpoint), an OpenAI-compatible chat model with a fixed classification
  prompt (judge family rule applies), and a labelled mock. Settings `GUARD_MODEL_ADAPTER`,
  `GUARD_MODEL_URL`, `GUARD_MODEL_NAME`, `GUARD_MODEL_VERSION`, `GUARD_MODEL_API_KEY`, `GUARD_MODEL_TIMEOUT_MS`,
  `GUARD_MODEL_FAIL_CLOSED_APPROVED`.
- Findings only. A timeout or error is a `timed_out` or `execution_failed` row, never a block and
  never fail closed by default. The pause hint (rule `GATE-CLASSIFIER-PAUSE`, money and credit
  tools) needs `pause_tool_classes` and a card approval that names the approver, the model id and the version
  (`data/models/guard_model/model_card.json`). `gateway/detector_gate.py` lists `guard_model` as a
  pause-capable detector.
- Harness `python -m supervisor.detectors.guard_harness` on the WP25 corpus: mock adapter in CI
  (never GO; baseline `data/eval/guard_model/baseline_mock.json`), real endpoint when
  `GUARD_MODEL_URL` is set. Report `docs/guard-model-validation-report.md`.
- Docs: decision memo (prompt-guard class model on Databricks serving, the judge model as
  classifier, vendor API excluded; latency and cost as formulas; what the live kit measures), model
  card template, `docs/llm-adapter.md` section 5. Catalog card and i18n EN and VI.
- The detector is always in the catalogue (`GET /v1/gate/detectors` lists it, like every detector),
  but its port is built and it runs only when the `guard_model` entry is enabled in
  `config/detectors.yaml` or a per-agent override enables it. Off, a bad `GUARD_MODEL_*` setting is a
  `[SKIP]` line in the log, never a start-up failure.
- Review fixes: one total deadline per model call (the classifier adapter cuts a trickling body, the
  chat adapter passes the time left to a single attempt and skips the retry), a guard-only pool of 4
  threads so a slow model cannot starve `dlp_vn`, `budget_aware` with a per-detector `timeout_ms`
  and reason `budget_exhausted` (WP-D4 mechanism), frame markers stripped until stable, the approval
  pins `GUARD_MODEL_VERSION` as well as the model id, the judge or LLM key only goes to its own URL,
  at most `max_windows` windows in all with a `windows dropped` note, harness run invalid when an
  item was not scored, exact catalogue list in three tests.
- Shared files touched: `config/detectors.yaml`, `src/supervisor/config.py` (settings block),
  `core/ports.py`, `core/errors.py`, `wiring.py`, `detectors/__init__.py`, `gateway/detector_gate.py`
  (one set entry), `console/catalog_view.py`, `console/i18n.py`, `console/guardians_view.py`; tests
  `test_contract.py`, `test_routes.py`, `test_harness.py` now compare the first four slugs only.

### WP-G6: MCP server, skills, KPI endpoint

One new flag, off by default (`MCP_SERVER_ENABLED`). Off = nothing is mounted, no table is read or
written, the Governance overview is as before, the command line prints `[SKIP]`. Details:
`docs/mcp-server.md`.

- `POST /mcp` (streamable HTTP, JSON-RPC 2.0: `initialize`, `tools/list`, `tools/call`, `ping`)
  in the app, and `python -m supervisor.mcp_server` to serve it alone. The JSON-RPC error shape is
  the one of the WP26 proxy (`gateway/mcp_proxy.error_response`); no new dependency.
- Connected apps: table `mcp_app` (pending, approved, blocked; scopes; console roles, never admin),
  signed with the WP20 HMAC credential (the key store of the agents; the row holds the SHA-256 of
  the current secret). The first connection is pending until an admin approves it
  (`POST /v1/mcp/apps/{id}/approve`, permission `mcp.apps`, or the command line). Every refused
  request leaves a `console_action` row (`mcp.auth`).
- Tools: governance (`list_entities`, `get_entity`, `register_system`, `link_component`,
  `propose_risk`, `list_tasks`, `complete_task`, `transparency_report`, `classification_draft`,
  `kpis`), library (`regulations`, `obligations`, `starter_risks`, `starter_controls`,
  `guardian_catalog`, `assignment_rules`), supervisor (`gate_state`, `decisions`, `findings`,
  `chain_verify`, `pack_results`).
- Every write is a draft and needs `confirm: true` (without it: the planned change, nothing
  written) and the console permission a person would need; two audit rows per write with the app
  as actor. A tool that would classify, approve, accept a risk, change a risk level, close an
  incident or turn a guardian off is refused at registration; a test enumerates the tools.
- Five skills in `docs/skills/`: `vn-system-registration`, `d33-prep`, `risk-triage`,
  `transparency-report`, `gov-report`.
- `GET /v1/kpis` (coverage, quality, speed; integers and basis points; scoped like G0) and a KPI
  block on the Governance overview (EN and VI) that read the same function.
- Review fixes: free text is masked in every tool result (empty with no masker);
  `chain_verify` is a write (confirm, two audit rows, one call per minute per app);
  `classification_draft` never replaces a draft that a person made or edited; a draft cannot carry
  `autonomy_level`; refused tool names are matched by verb word with an allowlist of the existing
  tools; KPI reads are bounded and cached for 30 s, the overview survives a KPI failure; every read
  is audited; the person who issued an app cannot approve it and the command line checks the
  admin role in the users file; an app owns the drafts it registers; the agent ingress refuses
  ids that start with `mcp-`; `gate_state` no longer returns who approved a resume.
- New permission `mcp.apps` (admin). Shared files touched: `schema/model.yaml` (table
  `mcp_app`), `config.py` (three settings), `core/rbac.py`, `adapters/auth/audit.py` (target kind
  `mcp_app`), `ops/openapi.py`, `console/i18n.py`, `gateway/mcp_proxy.py` (public alias
  `error_response`), `gateway/ingress_auth.py` (`refuse_prefixes`).
### WP-S1: per-system guardian bindings and the mandatory floor

One new flag, off by default: `GUARDIAN_BINDINGS_ENABLED=1` (needs `GOVERNANCE_ENABLED=1`). Off =
no route is mounted, no engine holds a lookup, the Catalog page is as before and the table stays
empty. On with no rows = the same answers as off. See `docs/guardian-bindings.md`.

- Table `guardian_binding` (system, feature slug, state on or off, mandatory, set by, set at,
  reason) and chain record `binding_change` (ids, enums and a reason hash).
- Effective state of a feature for an agent = the instance has it on AND (binding on OR the slug
  is in the system's guardian floor). A binding only narrows. The floor is read from
  `RulesService.guardian_floor` at resolution time. A floor feature cannot be set off (HTTP 400);
  `policy_rules` (the gate rules) is never bindable.
- Applied to detectors (`DetectorGate`, through the agent's `disable` list before
  `ResolvedDetectors.for_agent`), judge sampling (Tier 2 random sample and challenger), the
  session monitor (gate and batch job) and the monitors (WP1b-B bindings; drift skips the agent).
- `GET /v1/systems/{id}/guardians`, `PUT /v1/systems/{id}/guardians/{slug}`,
  `POST /console/systems/{id}/guardians/{slug}`; no new permission (`systems.view`,
  `systems.edit`). Catalog page: system picker and a switch per capability card, a lock for the
  floor. EN and VI.

### WP-UX4b: governance pages on the AI system

Needs `CONSOLE_NAV_V3=1` and `CONSOLE_SYSTEMS_ENABLED=1` (with `GOVERNANCE_ENABLED=1`). With the flags off nothing changes; with `GOVERNANCE_ENABLED` off the two overviews keep the agent-based pages of WP-UX4a.

- System page tabs Risks, Controls, Policies, Guardians (read only) and Reports, in the order Overview, Components, Risks, Controls, Policies, Guardians, Tasks, Reviews, Reports. Every figure comes from the existing risk, control, compliance, detector and transparency services; a figure that cannot be computed shows "not available" and the reason. The Reports tab has a guarded slot for incidents (WP-G5).
- Register wizard `/console/systems/new`: intake, preliminary checks (readiness advisor on a repository folder, assurance packs for the declared system, Decision 33 class proposal, guardian floor), one result page. Nothing is applied; confirming registers a draft and opens two initiation tasks.
- My overview and Governance overview count systems when `GOVERNANCE_ENABLED` is on (risk level, classification rate, control readiness per system, overdue tasks, stage table, by autonomy level when the column exists).
- Catalogues > Agents: a System column and a linked / unlinked filter.
- Screenshots in `docs/design/screens-v3` replaced; `tools/console_screenshots.py --v3` seeds four systems.

### WP-G5: governance loop, incidents

One new flag, off by default (off = nothing is mounted or scheduled, the tables stay empty, the
console and the system pages are as before). `GOVERNANCE_ACTIONS_ENABLED=1` needs
`GOVERNANCE_ENABLED=1` too.

- Normalised `GovernanceEvent` from eight read-only sources: alerts, gate block or pause on money,
  credit or pii_export tools, failed detectors, monitor breach cases (drift, fairness,
  multiagent) and low quality verdicts, required assurance packs with a NO-GO, failed chain
  verifies, new model versions, judge escalation cases. One event per linked AI system.
- `config/governance_actions.yaml` with a strict schema and a starter file (the nine SOC use
  cases of `docs/alerts.md`, chain break, pack NO-GO and more). Seven actions: `create_incident`,
  `notify_owner`, `raise_risk_level` (one step up, never down, never above `high`, source
  `event`), `move_to_re_evaluation` (G1 lifecycle move), `create_review` (G1 review, scope = the
  event), `fire_webhook` (G1 outbound event `governance_action`), `reopen_control` (a `failing`
  `control_status` row, reason `reopened_by_event`, through the control service). No action
  pauses or blocks an agent; the loader refuses those words.
- New tables `incident` and `governance_event` (the processed marker). Chain records
  `incident_change`, `governance_action`, `control_reopen`; `system_change` gets the action
  `risk_raise`. Incidents are auto-created only and closed only by a person.
- Job `python -m supervisor.jobs.governance_actions [--dry-run]` and the scheduler entry
  `governance_actions` (`SCHED_GOVERNANCE_S`, default 60): deterministic, an event is processed
  once, a raising action does not stop the others, a crashed event is resumed.
- `GET /v1/incidents`, `GET /v1/incidents/{id}`, `POST /v1/incidents/{id}/transition`; new
  permissions `incidents.view` (all roles) and `incidents.transition` (reviewer, owner, admin);
  tab **Incidents** on Cases & alerts and tab **Reports** on the system page. EN and VI.
- Changes to earlier code, all additive: risk source `event`; outbound event kind
  `governance_action`; review scope kind `event`; audit target kind `incident`.
- Docs: `docs/governance-actions.md`, `docs/incidents.md`, `docs/governance.md` section 20.

### WP-G3: Databricks auto-record v2 and agent auto-define

Two new flags, both off by default (off = the inventory scan and the governance tables are as before). `INVENTORY_SCAN_V2=1` turns on the scan sources v2; `INVENTORY_AUTOREGISTER=1` the draft registration.

- Inventory scan sources v2 (`INVENTORY_ENABLED` and `INVENTORY_SCAN_V2`, read-only SDK calls, evidence
  `workspace:<kind>/<name>`, no workspace URL or id stored): MLflow model versions, serving
  endpoint config (foundation, external and custom served entities, agent endpoint flag), Genie
  spaces, jobs and notebook tasks that name an LLM endpoint, Vector Search indexes, Unity Catalog
  functions and MCP connections. New node kinds `genie_space`, `job`, `vector_index`,
  `uc_function`. A Genie space is part of the shadow-AI check (new `genie_spaces` allow-list key).
  Live kit test 12 checks each call shape.
- `python -m supervisor.onboard.define --artifact <folder>`: Discover and Understand on an MLflow
  model artifact folder (code, tool manifest, prompt files, `requirements.txt`, `MLmodel`) with no
  code repository. Same `inventory.json` and `profile.json`, plus `artifact.json`. Two synthetic
  fixtures under `tests/onboard/data/`.
- `INVENTORY_AUTOREGISTER=1` (with `GOVERNANCE_ENABLED=1`): an unmanaged App, agent endpoint or
  Genie space becomes a draft AI system with a default owner from `config/governance.yaml`, the
  node is linked, and the initiation task "Confirm context" is opened. Deduplicated on the node
  id. The scan never blocks anything.
- Docs: `docs/inventory.md` ("Scan sources v2", "Draft registration from the scan"),
  `docs/onboard.md` ("Define from an artifact").

### WP-G0: governance shared core, the AI system entity

Two new flags, both off by default (off = nothing is mounted and the console is as in v0.4.1).

- `GOVERNANCE_ENABLED=1`: new tables `ai_system`, `system_team`, `system_component`; chain record
  `system_change`; service `supervisor.governance.systems`; routes `/v1/systems` (list, register,
  get, patch, team, links, archive). People with the roles `owner`, `viewer` or `operator` see only
  the systems they are on, own, or that their team owns. The risk level of a system is the higher
  of the level a person set and the level inherited from the linked agents and inventory nodes.
  The owner of a system cannot be its reviewer or oversight manager.
- `CONSOLE_SYSTEMS_ENABLED=1`: pages `/console/systems` and `/console/systems/<id>`, nav item
  under Onboard. EN and VI.
- New permissions `systems.view` (all roles) and `systems.edit` (reviewer, owner, admin).
- Docs: `docs/governance.md`.
### WP-UX4a: merged sidebar and the Supervisor-side pages (`CONSOLE_NAV_V3`)

One new flag, off by default (off = the console as before, also with `CONSOLE_NAV_SECTIONS=1`).

- `CONSOLE_NAV_V3=1`: one left bar with My overview, five Governance items, six Supervisor items
  and a settings gear (inline SVG line icons, section folds remembered in `localStorage`). A tab
  strip shows on every page that belongs to a section: Activity, Guardians, Cases and alerts,
  Analytics (with an Evidence chain tab), Catalogues, Risks and controls. The Systems item
  shows only with `console_systems_enabled` (the page belongs to WP-G0).
- New pages: My overview, Governance overview, Supervisor overview (numbers are integers or
  basis points from existing services; a figure that cannot be computed shows "not available" and
  why; judges without a model show `mock`), read-only Workflows, Catalogues asset tabs (models,
  tools, datasets, MCP servers) and the Detectors, Judges and Monitors tabs of Guardians.
- Section routes (`/activity`, `/risks-controls`, `/catalogues`,
  `/guardians`) answer 302 to the tab page. Old URLs keep working. A bad tab or scope is 400.
- `tools/console_screenshots.py --v3` captures the new screens; EN and VI strings; see
  `docs/console.md`, "Navigation v3".

### WP-G1: lifecycle, stage approvals, reviews, outbound events

All under `GOVERNANCE_ENABLED=1` (off = nothing is mounted and nothing changes). One new flag,
`WEBHOOKS_ENABLED`, off by default.

- Task sizing: an agent linked to an AI system is sized from the effective risk level of the system
  and the Decision 33 floor; a system with an unspecified level gives the initiation set only. An
  agent with no link is sized as before. Task templates accept `min_risk_level` and
  `required_from_level` (low, medium, high, prohibited).
- New tables `stage_approval`, `review`, `outbound_event`; chain records `stage_change` and
  `review_change`.
- Lifecycle: `POST /v1/systems/{id}/stage`; a move into a stage marked `approval: true` in
  `config/tasks.yaml` (default deployment and operation) needs an approved stage approval. The
  approver is a reviewer or oversight manager of the system, or an approver, and is not the
  requester or the owner (`segregation of duties:`). `PATCH` no longer changes `lifecycle_stage`.
- Reviews with scope, window and reports; complete locks, reopen needs a reason.
- Outbound events written on stage approved, review completed, system registered and archived; the
  webhook stub (`WEBHOOKS_ENABLED=1`) logs and marks them delivered, it sends nothing.
- Routes under `/v1/systems/{id}`: `approvals`, `approvals/{aid}/decide`, `stage`, `reviews`,
  `reviews/{rid}`, `reviews/{rid}/complete`, `reviews/{rid}/reopen`. New permissions
  `systems.approve` and `systems.review`.
- Console: tabs Tasks and Reviews on the system page. EN and VI.
- Docs: `docs/governance.md` sections 12 to 19.

### WP-G2: assignment rules engine and Decision 33 classification

No new flag. Everything is under `GOVERNANCE_ENABLED` (off = nothing mounted, nothing changes).
`CLASSIFIER_AI_PREFILL` (default 0) is new and needs it.

- `config/assignment_rules.yaml` (strict schema, starter rules for PDPL, Circular 53 money movement,
  Decision 33 high risk and an internal baseline) and a pure, deterministic evaluator
  (`supervisor.governance.rules`). New table `assignment` (rows are switched off, never deleted);
  chain record `rule_run` with the sha256 of the rules file. Runs after register, update, link and
  unlink, and by `python -m supervisor.governance.rules run|explain|check`.
- Additive hooks: assigned task templates join the task set (sizing stays the floor), assigned
  controls join the scope of the agents of the system, assigned obligations show on the obligation
  matrix with source `rule`. `GET /v1/systems/{id}/guardian-floor` for WP-S1. Agents on no system
  behave exactly as before.
- `config/decision33.yaml` (question flow), table `classification`, routes to draft, edit and apply
  (`/v1/systems/{id}/classification`), chain record `classification_change`. Only a person applies,
  never the system's reviewer or oversight manager. Applying sets `decision33_class` and the floor
  of the risk level (`high_risk` is at least `high`; the effective level uses the floor too).
  Optional AI pre-fill, answers tagged `ai_prefill` (and `mock`).
- Autonomy level: new column `ai_system.autonomy_level` (`unspecified`, `l0_rule_based` ...
  `l5_self_directed`), an ordered field in the rules (`gte`; `unspecified` never matches), starter
  rules `AR-AUTONOMY-L3/L4/L5`, a classification cannot be applied while it is `unspecified`, and
  l5 sets the risk floor to `prohibited`. New starter items: task `OPS-RESUME-2P` (new template
  key `assigned_only`: sizing never picks it), control `CTL-BANK-PAUSETEST` (kept in `config/controls_pending/`, so the starter catalogue is unchanged), risk `RSK-SHR-003` (kept in `config/risks_pending/`, not in the register until the governing body approves it).
  Docs: `docs/autonomy-levels.md`.
- Console: tabs Rules and Classification on the system page. EN and VI.
- New routes under `/v1/systems/{id}/` (assignments, obligations, guardian-floor, rules/explain,
  assignments/run, classification) use the existing permissions `systems.view` and `systems.edit`.
- Docs: `docs/assignment-rules.md`, `docs/decision33.md`.

### Console: two-section sidebar and Catalog page

Two new flags, both off by default (off = the console as in v0.4.1).

- `CONSOLE_NAV_SECTIONS=1`: the sidebar is split into "AI Management and Governance" and "AI
  Guardian and Supervisor". The existing groups become sub-groups of the two sections.
- `CONSOLE_CATALOG_ENABLED=1`: new read-only page `/console/catalog` that lists the guardian
  capabilities by category, with their on/off status and the setting that turns each one on.

## v0.4.1 (M2 triage fixes) - 2026-10-21

Fixes from the second benchmark on the bank agent, reviewed (two further High findings fixed in review: a cut argument
on a PII-export tool was allowed when the masker was not fail-closed; an over-budget argument reached the tool unmasked
when nothing blocked the call). Tests: 5,232 passed, 32 skipped. No new flag.

### WP41b: triage of the second benchmark (ADR D33, `HANDOFF_WP41B.md`)

No new flag; all three changes act only with `DETECTORS_ENABLED` on.

- D31 (High): a cut (`payload_too_large`) argument of a money, credit or pii_export tool is now
  `GATE-DETECTOR-FAILED` for any detector set (before, only a transforming detector did that, so a
  credit call with 85 percent of its text unread was allowed with status `report`). A read_only
  tool stays coverage only.
- D32 (Medium): the fail-closed 99 KB pii_export call took 879 ms on the bench host because the
  inline masker read the whole text; above the `dlp_vn` scan budget it does not run when the
  call is refused anyway (15 to 17 ms). Review: when nothing refuses the call (fail_closed off,
  observe, detectors disabled for the agent) the masker still masks the full text.
- D26 (Medium): status `pause` (not `block`) for the state pause `GATE-PAUSED` and the session
  pause `GATE-SESSION-PAUSE`, in the answer, `agent_event.verdict_status`, the chain record, the
  SIEM `attrs.status`, the drawer and the rollup. The old `action` field stays `block`.


## v0.4.0 (phase 3 waves 2 and 3) - 2026-10-21

Integration branch `phase3-wave2` (ten packages, merge report `docs/phase3/wave2/INTEGRATION_WAVE2.md`).
`__version__` stays `0.3.0`. Every new feature is behind a flag that is off by default; the
behaviour changes that apply with the flags off are listed below. On Delta, run
`python -m supervisor.jobs.bootstrap_schema` BEFORE the new app version (migration note at the end).

### What is new

| WP | Feature | Docs | ADR |
|---|---|---|---|
| WP37 | Verdict contract v2 on `POST /v1/gate/check` (`status`, `findings`, `not_executed`, `coverage`, `transformed_payload`, `request_id`, `correlation_id`, `direction`, `detectors`, `detector_latency_us`; old fields kept), header `X-Supervisor-Correlation-Id`, detector framework (`dlp_vn` transform, `injection_regex` and `judge_advisory` report only), precedence block > pause > transform > report > allow, `GATE-DETECTOR-FAILED` for fail-closed detectors on money / credit / pii_export tools (advisory detectors never fail closed), `GET /v1/gate/detectors`, per-agent `agents.<id>.detectors` override, table `finding`, harness `python -m supervisor.detectors.harness` | `docs/detectors.md`, `docs/detectors-validation-report.md`, `docs/api.md` | D23 |
| WP26 | Streamable-HTTP MCP proxy `python -m supervisor.gateway.mcp_http` (same gate path as the stdio proxy, pooled upstream client), tool locking (hash per tool, new or changed tools hidden and refused with `MCP-TOOL-UNREVIEWED` until two different people approve the full hash, removed tools logged, case `mcp_tool_review` without incident clock), report-only poisoning scan, review CLI `tools list|diff|propose|approve`, routes `/v1/mcp/tools...` (`mcp.tools.view|propose|approve`) and two signed ingress routes, table `mcp_tool_manifest`, harness `python -m supervisor.gateway.mcp_http_harness` | `docs/mcp-gateway.md`, `docs/INTEGRATION_GUIDE.md` (pattern C) | D24 |
| WP28 | Multi-turn Vietnamese and English red team: 6 attack families, 122 objectives, deterministic oracle, labelled MOCK agent, optional capped LLM attacker (`REDTEAM_ATTACKER_MODEL`, at most 60 conversations), advisory pack `multiturn_redteam_vi` with a 7-day trend, nightly job `python -m supervisor.jobs.redteam_nightly`, 40 probes, Playground samples, harness `python -m supervisor.redteam.multiturn` | `docs/redteam-multiturn.md`, `docs/redteam-multiturn-validation.md`, `docs/redteam-attacker-model-card.md` | D25 |
| WP29 | Risk register: likelihood x impact (ILLUSTRATIVE bands), inheritance up the inventory graph, links to matrix rows, gate rules, packs and monitors, evidence rule (declared residual only while no linked control fails and one works), job `python -m supervisor.jobs.risk_evidence`, `/v1/risks...` (`risks.view`, `risks.edit`), Risks page and Agent tab, CLI `python -m supervisor.risk`, 19 starter risks, tables `risk`, `risk_link`, `risk_evidence`, harness `python -m supervisor.risk.harness` | `docs/risk-register.md` | D26 |
| WP25 | Injection classifier `injection_classifier` 1.1.0 (Vietnamese and English, pure-Python linear model, weights pinned by SHA-256 in the model card with an approval block) for tool arguments, tool results and tool descriptions; pause hint obeyed only on allowed input calls to money / credit tools (`GATE-CLASSIFIER-PAUSE`, never a block); training `python -m tools.train_classifier`, grouped CV `python -m tools.cross_validate`, sealed held-out protocol. **Validation NO-GO; the entry ships `enabled: false`.** Integration: registered as the WP26 tool-lock scorer when enabled (report only; refused weights hold the tool) | `docs/injection-classifier.md`, `docs/injection-classifier-validation-report.md`, `docs/mcp-gateway.md` section 7 | D27 |
| WP38 | Collector catalogue on the Integrations page (Python SDK, LangGraph / deepagents middleware, FastAPI middleware, REST, MCP stdio and HTTP proxy, LiteLLM guardrail, Claude Code hook; Add issues the first agent key, `collectors.add`), SDK `check_v2` with `direction` and correlation id, policy keys `agents.<id>.mode: observe` (money agents need SHADOW or two `observe_approvals`), `rules {enable, disable}` (money / credit / pii_export block rules need `rule_approvals`), `consumers.<id>` override (no consumer observe), resolved `Decision.consumer_id`, Playground sample library, harness `python -m supervisor.collectors.harness` | `docs/collectors.md`, `docs/policy.md`, `docs/collectors-validation-report.md` | D28 |
| WP27 | Session monitor: `session_id` on every decision and span, nine integer signals with policy weights, case `session_escalation` at K hits (memory may open a case alone), opt-in session pause `GATE-SESSION-PAUSE` (two-person resume or cool-down), daily per-consumer window in the batch job (case only), `GET /v1/sessions/<id>`, `POST /v1/sessions/<id>/resume` (`session.view`), job `python -m supervisor.jobs.session_monitor`, alert `AL-SESSION-ESCALATION`, table `session_control`, harness `python -m supervisor.monitors.session_harness` | `docs/session-monitor.md`, `docs/session-monitor-validation-report.md` | D29 |
| WP30 | Control catalogue (28 starter controls, working / failing / no_data per agent, compliance figure in bp, `control` as a WP29 link kind) and the lifecycle task list sized by Decision 33 class and band (two-person waiver, segregation of duties per stage, Launch NO-GO while a required task is open with `TASKS_LAUNCH_GATE_ENABLED`), `/v1/controls`, `/v1/tasks` (`controls.view|edit`, `tasks.view|edit|approve`), tasks CSV, Controls and Tasks pages and Agent tabs, jobs `control_status`, `task_due`, CLIs `python -m supervisor.controls`, `python -m supervisor.tasks`, five tables, harness `python -m supervisor.controls.harness` | `docs/controls.md` | D30 |
| WP31 | Transparency report per agent in three variants (regulator, customer, internal) with allow-lists and a second leak check, "what this report does not show", JSON / HTML / PDF in Vietnamese and English, content-hash versions signed into the chain, `/v1/transparency...` (`transparency.view`, `transparency.generate`), Transparency page and Agent tab, job `python -m supervisor.jobs.transparency`, CLI `python -m supervisor.transparency`, table `transparency_report`, controls section from WP30 when `CONTROLS_ENABLED=1`, harness `python -m supervisor.transparency.harness` | `docs/transparency-report.md` | D31 |
| WP39 | Verdict v2 Decisions drawer (Request, Response with the Observed-decision line, Detections, Metadata; masked text only), filters, masked CSV export (`decisions.export`, row cap, one-time link), deep links and correlation id across decision, trace and alert, Gate tables and Detectors tab in Analytics from `decision_daily` (job `python -m supervisor.jobs.decision_rollup`), nine SOC alert rules with `where_min` and `rate`, alert drills, console activity harness `python -m supervisor.console.activity_harness` | `docs/console.md`, `docs/alerts.md` | D32 |

### WP41: defects of the M2 benchmark on the bank agent (ADR D33, `HANDOFF_WP41.md`)

No new flag; every change is behind a flag that exists or in an adapter option.

- D29: `agents.<id>.detectors.settings.dlp_vn.keep_args` (a lookup key reaches the tool as sent,
  stays masked in every record, `kept_args` on the decision, the drawer and the export column
  `kept_arguments`, audit log line and chain record `policy_keep_args` when the policy loads) and
  `dlp_vn.pseudonym_mode: typed`.
- D30, D18: detector setting `max_scan_bytes` (16384) and `DETECTORS_SCAN_BUDGET_BYTES` (65536
  per call); arguments first; the cut is coverage `payload_too_large` with `bytes` and
  `scanned_bytes`; a cut argument of a pii_export tool is never transformed in part
  (`GATE-DETECTOR-FAILED`); a memoising masker and an early exit in `injection_regex`.
- D24, D25: per-detector `mrm_status` in `config/detectors.yaml`; the session `findings` signal
  counts only deterministic or GO detectors (others are recorded, weight 0).
- D04: session signal `split_cue` (weight 300; `timing` 400 to 100; after the review it counts
  as two hits towards K, not as a solo signal); ten new harness probes.
- Review (Opus): a cut argument or output of a call that `dlp_vn` would transform fails closed
  even when the scanned part is clean; `keep_args` needs `keep_args_approvals` (two ids) on a
  money / credit / pii_export tool, is refused in a consumer block and in
  `config/detectors.yaml`, and applies to input checks only; `split_cue` halves are stricter.
- D19: gate-only agents are registered in the inventory (source `gate`) on the first decision.
- D23: the stock LangGraph middleware sends the last 3 tool results (`send_tool_results`).
- D28: pack results on the `traces:` target count as evidence for risks and controls.
- D27: Agent page Tools tab answers 200 with a hint for an agent with no policy record; reads the
  served `POLICY_DIR`.

### New flags and settings (all features default off)

| Flag | Turns on | Related settings |
|---|---|---|
| `DETECTORS_ENABLED` (WP37) | Detectors on the gate, verdict v2 fields, `finding` rows, `GET /v1/gate/detectors`; also needed by the WP25 classifier and the WP39 facts | `DETECTORS_CONFIG` (`config/detectors.yaml`) |
| `detectors.injection_classifier.enabled` in `DETECTORS_CONFIG` (WP25, shipped `false`) | The injection classifier detector and its tool-lock score | `CLASSIFIER_FAIL_CLOSED_APPROVED` (default `0`; fail-closed also needs a named approver and the weights SHA-256 in the card) |
| `MCP_HTTP_ENABLED` (WP26) | `/v1/mcp/tools...` routes, the HTTP proxy and the review CLI | `MCP_TOOL_LOCK` (default `1`), `MCP_LOCK_REFRESH_S` (`60`), `MCP_TOFU_INGRESS` (`0`), `MCP_SERVER_AGENTS` (empty) |
| `REDTEAM_NIGHTLY_ENABLED` (WP28) | Scheduler job `redteam_nightly` | `SCHED_REDTEAM_S`, `REDTEAM_TRIALS`, `REDTEAM_NIGHTLY_TRIALS`, `REDTEAM_SEED`, `REDTEAM_LANGS`, `REDTEAM_ATTACKER_MODEL` (empty = templates), `REDTEAM_LLM_MAX_CONVERSATIONS` (max 60) |
| `RISK_REGISTER_ENABLED`, `CONSOLE_RISKS_ENABLED` (WP29) | `/v1/risks`, job `risk_evidence`, CLI; Risks page and Agent tab | `SCHED_RISK_EVIDENCE_S`, `RISK_EVIDENCE_WINDOW_DAYS` (`7`), `RISK_EVIDENCE_JUDGED_PACKS` (`0`), `RISK_CONFIG`, `RISK_STARTER_DIR` |
| `COLLECTORS_ENABLED` (WP38) | Integrations page as the collector catalogue (needs `CONSOLE_INTEGRATIONS_ENABLED`) | `COLLECTORS_PUBLIC_URL`. The policy keys `mode`, `rules`, `consumers` need no flag: they act only when a policy file uses them |
| `SESSION_MONITOR_ENABLED` (WP27) | Session monitor at the gate, job `session_monitor`, `/v1/sessions` | `SCHED_SESSION_S`, `SESSION_WINDOW_S`, `SESSION_K`, `SESSION_COOLDOWN_S`; per agent `agents.<id>.monitors.session` (pause and daily window off by default) |
| `CONTROLS_ENABLED`, `CONSOLE_CONTROLS_ENABLED`, `TASKS_LAUNCH_GATE_ENABLED` (WP30) | `/v1/controls`, `/v1/tasks`, jobs `control_status` and `task_due`, CLIs; pages and tabs; the Launch gate on open tasks | `SCHED_CONTROL_STATUS_S`, `SCHED_TASK_DUE_S`, `CONTROLS_PACK_WINDOW_DAYS` (`30`), `CONTROLS_STARTER_DIR`, `TASKS_CONFIG` |
| `TRANSPARENCY_ENABLED`, `CONSOLE_TRANSPARENCY_ENABLED` (WP31) | `/v1/transparency`, job `transparency`, CLI; page and tab | `SCHED_TRANSPARENCY_S`, `TRANSPARENCY_DIR`, `TRANSPARENCY_BACKLOG_FILE`; PDF needs the optional extra `pdf` (fpdf2) and `CASEFILE_PDF_FONT` |
| `CONSOLE_DECISIONS_V2` (WP39) | Verdict v2 Decisions list and drawer, export, Analytics tables, job `decision_rollup` | `CONSOLE_EXPORT_MAX_ROWS` (`5000`), `SCHED_DECISION_ROLLUP_S`; the alert rules need `ALERTS_ENABLED` |

### Behaviour changes with the flags off

- **WP41, settings and defaults.** `DETECTORS_SCAN_BUDGET_BYTES` (default 65536) and the detector
  setting `max_scan_bytes` (default 16384) apply with `DETECTORS_ENABLED=1`: a text longer than
  the limit is no longer scanned in full (coverage says so), and a pii_export call whose argument
  is longer than 16 KB is blocked by `GATE-DETECTOR-FAILED` instead of being masked in full (raise
  `max_scan_bytes` for `dlp_vn` on that agent). The default session weights changed (`timing`
  400 to 100, new `split_cue` 300) and a `split_cue` hit counts as two hits towards K; both act only with
  `SESSION_MONITOR_ENABLED=1`. A detector with no `mrm_status` counts 0 in the session `findings`
  signal. `python -m supervisor.analytics.tools` and the Tools views read `POLICY_DIR` when it is
  set. The stock LangGraph middleware sends `context.tool_results` (option `send_tool_results`,
  default on). The Decisions CSV export has the column `kept_arguments`. The DDL files changed in
  comments only (no column changed).

- **WP26 F13, stdio MCP proxy (no flag; kept as the security default).** `resources/read`,
  `resources/templates/list`, `prompts/get` and `completion/complete` now go through the gate as
  the read-only tools `mcp.resources.read`, `mcp.resources.templates.list`, `mcp.prompts.get`,
  `mcp.completion.complete`; a policy that does not list them refuses them (JSON-RPC error
  `-32000` with `error.data.rule_id`). A forwarded `tools/call` keeps only `name`, `arguments` and
  `_meta.progressToken`; other `params` keys are dropped. `policies/baseline.yaml` and the demo
  agents make no such call (the assurance packs give the same results as v0.3.0 in mock mode),
  so the baseline policy needs no new tool. See `docs/mcp-gateway.md` section 3.
- **WP37 F14, policy loader.** `agents.<id>.detectors.skip_tools` that names a money, credit or
  pii_export tool is refused at load (also for WP38 consumers). Policy files without the new key
  load and hash as before.
- WP38: the policy loader refuses `consumers.<id>.mode: observe`, agent `mode: observe` on a
  money agent without SHADOW or two `observe_approvals`, and an agent `rules.disable` of a
  money / credit / pii_export block or pause rule without two `rule_approvals`. Only files that
  use the new keys are affected; `policy_hash` of an old file is unchanged (test).
- WP28: the assurance catalogue has 34 packs (new advisory pack `multiturn_redteam_vi`); with
  assurance-at-launch on it also runs at Launch (about 15 s per agent, advisory).
- WP21 / WP27 / WP39: `config/alerts.yaml` has 18 rules (8 + 1 + 9); the hash of every old rule
  is unchanged, the rule-set `config_hash` changes. The new rules act only with `ALERTS_ENABLED`.
- WP27: a completed two-person agent resume also lifts that agent's session pauses (there are
  none with the monitor off).
- Integration: `agent_event.consumer_id` (WP39, written only with `DETECTORS_ENABLED=1`) holds the
  consumer id that the WP38 policy resolved, never the raw caller value.
- `policies/schema.json` gained the optional keys `detectors`, `mode`, `rules`, `consumers`,
  `observe_approvals`, `rule_approvals` and `monitors.session` (no key removed).

### Deploy note for Delta (databricks_app mode)

The app does not migrate Delta at start. Run the schema bootstrap BEFORE you deploy the new app
version:

    python -m supervisor.jobs.bootstrap_schema

(or the migration cell in `notebooks/bootstrap_and_smoke.py`). It adds the tables `finding`,
`mcp_tool_manifest`, `session_control`, `risk`, `risk_link`, `risk_evidence`, `control`,
`control_map`, `control_status`, `task`, `task_event`, `transparency_report` and
`decision_daily`, and the nullable columns `agent_event.verdict_status`, `correlation_id`,
`coverage_json` (WP37), `session_id`, `session_source`, `session_json` (WP27), `request_id`,
`consumer_id`, `latency_rules_us`, `latency_detectors_us`, `detector_latency_json` (WP39) and
`alert.correlation_id` (WP39). If the app runs first with `DETECTORS_ENABLED=1` or
`SESSION_MONITOR_ENABLED=1`, gate decision inserts fail on the unknown columns. SQLite (laptop) is
bootstrapped at app start and needs no step.

## v0.3.0 (phase 3, wave 1) - 2026-10-20

Merged from the integration branch `phase3-wave1` (3,684 tests, 29 skipped). Every new feature is behind a
flag that is off by default. On Delta, run `python -m supervisor.jobs.bootstrap_schema` before deploying
(new columns and tables listed below).

### What is new

| WP | Feature | Docs | ADR |
|---|---|---|---|
| WP20 | Per-agent ingress credentials on `POST /gate/check`, `/v1/gate/check`, `/v1/traces` (HMAC key, Databricks SP bearer, Apps proxy identity), rotation CLI, audited 401 / 403 | `docs/ingress-auth.md` | D14 |
| WP21 | SIEM export (file, http, delta; jsonl, CEF, OCSF 1.1 subset), alert engine (`config/alerts.yaml`), Alerts section on Metrics with acknowledge, queued webhook notifier | `docs/siem.md`, `docs/alerts.md` | D15 |
| WP22 | Tool usage rollup `tool_usage_daily`, least-privilege diff (suggestion only), console Tools page, `GET /v1/analytics/tools` | `docs/tool-analytics.md` | D18 |
| WP24 | Inventory graph (agents, models, endpoints, tools, MCP servers, datasets), shadow-AI scan with low-severity cases (no incident clocks), console Inventory page, `GET /v1/inventory/...` | `docs/inventory.md` | D16 |
| WP23 | Latency benchmark `python -m tools.bench_latency` (in process, HTTP open loop with GAF delta, OTLP, MCP proxy; SQLite and a labelled MOCK Delta path), Delta round-trip notebook, two committed full runs. Laptop gate p99 4.6 ms (19 rules), 6.8 ms (200 rules) against 50 ms. The 50 ms test runs with `RUN_PERF=1` | `docs/latency.md` | D19 |
| WP1b-B | Onboarding: FastAPI routes are `entrypoints` (file:line), not tools; `deepagents` framework; MCP `tools/list`, `create_react_agent` / `create_deep_agent` tool lists; model family from endpoint names and env / `app.yaml` values via the judge alias table; corpus repo `fastapi_deepagents_credit_toy`, eval with precision, recall, Wilson intervals. Monitors: per-agent bindings (manifest and `policies/*.yaml`), defaults from tool classes, `monitor_status` with `not_applicable` reasons on the Metrics page, harness `python -m supervisor.monitors.binding_harness` | `docs/onboard.md`, `docs/onboard-eval.md`, `docs/monitors.md` | D20 |
| WP1b-A | Judge config fixes D05, D12, D13, D14, D15: derived judge family with `family_source`, strict structured output for Anthropic-compatible endpoints, challenger scope, served `POLICY_DIR` and `FACT_SOURCE`, SDK on `/v1/gate/check` (details in the next section) | `docs/llm-adapter.md`, `docs/fact-sources.md`, `docs/judge-mrm.md` | D21 |
| WP24b | Masker `vn_regex-3` (names in every case form, addresses, amounts kept), inline redaction of `pii_export` tool arguments at the gate, `pii_canary` v2, PII eval harness | `docs/masking.md`, `docs/masker-validation-report.md` | D17 |
| WP-UX2 | Console page migrations: agent page `/console/agents/<id>` with eight tabs (Overview with the lifecycle controls moved from the Agents cards, Policy, Tools, Inventory, Traces, Cases, Assurance, Compliance; htmx plus `?tab=`), Alerts page `/console/alerts` (moved out of Metrics, filters, drawer), Sign-off list `/console/signoff` and `CaseService.waiting_approvals`, Analytics page `/console/analytics` (Gate, Tools, Oversight metrics, Latency under one toolbar), 303 redirects for `/console/metrics` and `/console/tools`, Cases, Inbox and Inventory on the list components, Case page on the shared tabs macro, Vietnamese labels | `docs/console.md` | - |
| WP-UX1 | Console shell: left sidebar with six groups (Watch, Act, Prove, Onboard, Analytics, Settings), reduced top bar with global search (`GET /console/search`), `CONSOLE_NAV=sidebar` or `top` (the old header stays behind `top`), `CONSOLE_NAV_PLACEHOLDERS`, a "coming in WP-UX3" page for seven pages, component macros (crumbs, page header, tiles, filter bar, sortable paged table, row drawer, tabs, key-value, timeline, empty state, stat, toast), Overview and Agents list migrated as proof, Vietnamese labels, skip link and `aria-*` | `docs/console.md` | - |
| WP-UX3 | Eight console pages, each behind its own flag (default off) and permission, replacing the placeholders: Gate decisions (list, filters, drawer), Traces (list and span-tree viewer, capture level decides the text), Playground (dry-run gate check through the new `Gateway.evaluate_only`, no side effect, `PLAYGROUND_ALLOW_APP=1` on the App), Policies, Credentials (metadata only), Users and roles, Audit log (`CONSOLE_AUDITLOG_ENABLED`), Integrations. New permissions `decisions.view`, `traces.view`, `playground.run`, `policies.view`, `credentials.view`, `users.view`, `audit.view`, `integrations.view` | `docs/console.md` | D22 |

### WP1b-A: benchmark defects D05, D12, D13, D14, D15

| Defect | Change | Docs |
|---|---|---|
| D14 | `LLM_STRICT_SCHEMA`, `LLM_SEND_TEMPERATURE`: the adapter can talk to Anthropic's OpenAI-compatible endpoint (stripped schema copy, local validation against the full schema); contract test on recorded 400s and a recorded 200 | `docs/llm-adapter.md` |
| D05 | Judge family derived from the model id (and endpoint metadata with `JUDGE_FAMILY_PROBE`); declared family only with `JUDGE_FAMILY_OVERRIDE_TEST_ONLY=1` (refused in `databricks_app`); `family_source` in `verdict` rows, chain records, model card, validation report | `docs/llm-adapter.md`, `docs/judge-mrm.md`, ADR D21 |
| D15 | Challenger checked only against registered non-retired agents and `JUDGE_AGENTS`; `mrm validate` mock mode no longer calls a configured real challenger | `docs/llm-adapter.md` |
| D13 | `POLICY_DIR`, `FACT_SOURCE` (`sqlite:` read-only with `FACT_QUERY_MAP`, `callable:`) wired through `wiring.py` and `gateway/wiring.py` | `docs/fact-sources.md` |
| D12 | `HttpGate` posts to `/v1/gate/check`; falls back once to `/gate/check` on HTTP 404 | `docs/api.md` |

Behaviour change with flags off: a declared `JUDGE_*_FAMILY` that disagrees with the model id (or
is given for a model whose family cannot be derived) now stops startup. New nullable column
`verdict.family_source`: run `python -m supervisor.jobs.bootstrap_schema` before deploying on Delta.

### New flags (all default off)

| Flag | Turns on | Related settings |
|---|---|---|
| `INGRESS_AUTH_ENABLED` | Credential check on the three agent ingress routes | `INGRESS_CREDENTIAL_KIND`, `INGRESS_KEY_STORE`, `INGRESS_KEYS_FILE`, `INGRESS_IDENTITIES_FILE`, `INGRESS_SECRET_SCOPE`, `INGRESS_REPLAY_WINDOW_S`, `INGRESS_AUDIT_THROTTLE_S`, `INGRESS_NONCE_CAP_PER_AGENT`, ... |
| `SIEM_ENABLED` | Scheduler job `siem` sends chain events to the sink | `SIEM_SINK`, `SIEM_FORMAT`, `SIEM_FILE_PATH`, `SIEM_WEBHOOK_URL`, `SIEM_HTTP_TOKEN`, `SIEM_DEAD_LETTER_PATH`, `SCHED_SIEM_S` |
| `ALERTS_ENABLED` | Scheduler job `alerts`, Alerts section on Metrics | `ALERTS_CONFIG`, `ALERTS_LAG_S`, `ALERTS_SUPPRESSION_MAX_S`, `SCHED_ALERTS_S` |
| `NOTIFY_WEBHOOK_ENABLED` | Scheduler job `notify` sends queued notices (needs `NOTIFY_WEBHOOK_URL`) | `NOTIFY_WEBHOOK_TOKEN`, `NOTIFY_WEBHOOK_DEAD_LETTER`, `SCHED_NOTIFY_S` |
| `TOOL_ANALYTICS_ENABLED` | Scheduler job `tool_analytics`, `GET /v1/analytics/tools` | `TOOL_ANALYTICS_WINDOW_DAYS`, `TOOL_ANALYTICS_MIN_HISTORY_DAYS`, `TOOL_ANALYTICS_EXCEPTIONS_FILE`, `TOOL_ANALYTICS_DIR`, `SCHED_TOOL_ANALYTICS_S` |
| `CONSOLE_TOOLS_ENABLED` | Console Tools page | - |
| `INVENTORY_ENABLED` | Inventory fill, scheduler job `inventory`, console Inventory page, `/v1/inventory/...` | `INVENTORY_SCAN_SCHEMAS`, `INVENTORY_SELF_APP`, `INVENTORY_ALLOWLIST_FILE`, `INVENTORY_WORKSPACE_FIXTURE`, `SCHED_INVENTORY_S` |
| `INLINE_REDACTION_ENABLED` | Gate answer carries masked `transformed_args` for `pii_export` tools (SDK / MCP proxy switch must also be on) | `INLINE_REDACTION_TOOLS` |
| `MASK_AMOUNTS` | Types money amounts as `<AMOUNT:...>` in masked text | - |
| `LLM_STRICT_SCHEMA` (default `0`), `LLM_SEND_TEMPERATURE` (default `1`) | Strict structured output for endpoints that require it | - |
| `JUDGE_FAMILY_OVERRIDE_TEST_ONLY` | Accepts a declared judge family (tests only) | `JUDGE_FAMILY_PROBE`, `JUDGE_AGENTS` |
| `JUDGE_FAMILY_STRICT` (default `1`) | `0` = one-release path: a declared family for a model id with no family (custom endpoint name) is accepted as `declared-unverified`; `mrm validate` gives NO_GO | - |
| `POLICY_DIR`, `FACT_SOURCE` | Served app loads another policy folder and a fact source | `FACT_QUERY_MAP`, `FACT_CALLABLE_ALLOW_PREFIX` |

### Behaviour changes with flags off

- Masker version is `vn_regex-3` (was `vn_regex-2`). Masked text and `mask_version` change for
  names, addresses and grouped accounts; amounts are no longer masked as accounts.
- `agent_event` rows carry `latency_us` (integer microseconds) in addition to `latency_ms`.
- `post_json` (gate SDK transport) returns `{}` for an empty 2xx body instead of raising.
- Reserved agent ids `inventory` and `app:*` are refused at registration and Discover.
- Console "Verify chain" writes a `chain_verify` record after each verify.
- WP1b-B: a FastAPI route outside a `/tools/` path is no longer a tool in the onboarding inventory
  (it is an `entrypoints` item); `Inventory.model_family` / `model_id` are filled from code when
  the manifest has none (`model_family_source`); `oversight_metric` gains the nullable column
  `monitor_status`; the policy schema accepts `agents.<id>.monitors`; the inventory graph has an
  `entrypoint` node kind. New settings `MONITOR_POLICY_DIR`, `MONITOR_MANIFEST_DIR` (no flag:
  bindings are additive and the existing monitor flags are unchanged).
- WP1b-A: `HttpGate` posts to `/v1/gate/check` (one fallback to `/gate/check` on HTTP 404); a
  declared judge family that disagrees with the model id stops startup; `verdict` gains the
  nullable column `family_source`.
- Integration: with `POLICY_DIR` set, the monitor bindings (quality sweep, drift, fairness,
  multi-agent) read that folder too, like the gate. Other readers of `<repo>/policies` are
  listed in BACKLOG.

### Deploy note for Delta (databricks_app mode)

The app does not migrate Delta at start. Run the schema bootstrap BEFORE you deploy the new
app version:

    python -m supervisor.jobs.bootstrap_schema

(or the migration cell in `notebooks/bootstrap_and_smoke.py`). It adds the columns
`agent_event.latency_us`, `oversight_metric.monitor_status` (WP1b-B) and `verdict.family_source`
(WP1b-A) and the new tables
`alert`, `siem_event`, `tool_usage_daily`, `inventory_node` and `inventory_edge`. If the app runs
first, every gate decision insert fails on the unknown column `latency_us`, and the monitor jobs
fail on `monitor_status`, and judge verdict inserts fail on `family_source`. SQLite (laptop) is bootstrapped at app start and needs no
step.
