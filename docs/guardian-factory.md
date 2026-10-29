# Guardian factory (WP-G1, phase 12C)

Flag `GUARDIAN_FACTORY=1` (needs `DETECTORS_ENABLED=1`). Default off. With either flag off every
route answers HTTP 400 `guardian_factory_off` and no table is read. This package (WP-G1) defines
and stores guardian definitions. The benchmark (WP-G2, section Benchmark) and shadow mode,
approval and going live (WP-G3, sections Shadow, Promotion, Allow-lists) are in.

A **guardian definition** describes one detector as data. A `live` definition becomes a detector
of the existing contract (`core/detectors.py`) through `guardian_factory/adapter.py`, and WP-G3
attaches it to agents by id and version (slug `gf:<id>@<version>`, guardian bindings).

```
 plain words ──► author (library, else gateway model) ──► artifact draft ──► person edits ──► save (draft)
                                                                                               │
 definition (strict schema, regex safety checks of custom_rules) ◄─────────────────────────────┘
        │  draft ◄──► retired   (WP-G1)        benchmarked ► shadow ► approved ► live   (WP-G2, WP-G3)
        ▼
 adapter: live definition ──► Detector (regex / keyword / policy / classifier / judge)
```

Rules that hold everywhere:

* Only a **deterministic** rule blocks or redacts: `regex`, `keyword_list`, `policy`. A model type
  (`classifier`, `judge_prompt`) can only `log` or `require_approval`; the schema refuses the rest
  with a message that names `action_on_fail`.
* The model **drafts**, a person accepts. Nothing is saved by "Draft the artifact".
* The regex checks are the ones of `custom_rules` (`detectors/dlp_extras.py`: `regex_problems`
  and the mask-token check). The factory calls them; it has no second validator.
* No floats and no personal data in the chain or in the table: rates are integer percent, scores
  integer basis points, amounts integer minor units.

## Definition fields

All limits are in `src/supervisor/guardian_factory/caps.py`. JSON Schema:
`GET /v1/guardian-defs-schema` (per-type `config` schemas under `x-config-by-type`).

| Field | Rule |
|---|---|
| `id` | lower case letters, digits, `-`; at most 64; not `new` or `schema` |
| `name` | 1 to 64 characters |
| `description` | at most 1,024 characters |
| `owner_group` | a group of `config/factory_groups.yaml` |
| `type` | `regex`, `keyword_list`, `classifier`, `judge_prompt`, `policy` |
| `stage` | `preflight`, `input`, `tool_call`, `output` |
| `scope` | `agents` and `tools`: `*` or a list (at most 50); `data_classes`: list from `public, internal, confidential, pii, pii_export, credit, money` (empty = all) |
| `action_on_fail` | `block`, `redact`, `require_approval`, `log`; classifier and judge_prompt: `log` or `require_approval` only |
| `sensitivity` | integer 1 to 4 |
| `config` | per type, below |
| `benchmark_pack` | id of a pack under `DATA_DIR/guardian_factory/<id>/bench` with `attack` and `benign` sets; may be empty in draft |
| `thresholds` | integers: `min_tpr_pct` (0-100, default 90), `max_fpr_pct` (0-100, default 5), `max_p95_ms` (1-60000, default 50) |
| `lifecycle` | `state`, `version`, `approvals[]` {by, group, at}, `shadow_days` (0-90), `allow_list[]` {agent_id, reason, `expires` YYYY-MM-DD, required} |
| `created_by`, `created_at`, `updated_at` | set by the store |

Config per type:

| Type | Config |
|---|---|
| `regex` | `pattern` (at most 200 characters, existing safety checks), `mask_token` (optional, not shaped like a pseudonym), `preserve_length` (bool) |
| `keyword_list` | `words` (1 to 500, each at most 80 characters, no duplicates), `mask_token`, `preserve_length` |
| `classifier` | `model_ref` from the allow-list `injection_classifier`, `guard_model`; `threshold_bp` integer 0 to 10000 |
| `judge_prompt` | `prompt` (at most 2,000 tokens), `verdict_labels` (2 to 6), `fail_labels` (subset of the labels) |
| `policy` | `rules` (1 to 20): `id`, `when` (1 to 5 conditions, all must hold), `then` `permit` or `forbid`; `default` `permit` or `forbid` |

Policy conditions: `tool` (`eq`/`in`, tool name), `argument` (`eq`/`in`/`present`, argument
`name`), `amount` (`eq`/`gt`/`gte`/`lt`/`lte`, `name` of the argument, integer minor units; a
float or a bool never matches), `data_class` (`eq`/`in`). Evaluation: a matching `forbid` wins,
then a matching `permit`, then `default`.

## States

One table in `caps.py` (`TRANSITIONS`); `ALLOWED_NOW` marks what is open. The conditions of every
move are in `promotion.py` (WP-G3) and `store.py` (WP-G1, WP-G2).

| From | To | Route and role | Condition |
|---|---|---|---|
| draft | retired | `retire`, guardians.edit | none |
| retired | draft | `reopen`, guardians.edit | none |
| draft | benchmarked | `mark-benchmarked`, guardians.edit | a passing run of this version and definition, see Benchmark |
| benchmarked | draft | any change, guardians.edit | none |
| benchmarked | shadow | `shadow/start`, guardians.edit | the newest run still fits the definition |
| shadow | approved | `approve` twice, guardians.approve | two people, see Promotion |
| shadow | draft | `shadow/stop`, guardians.edit | approvals are dropped |
| approved | live | `go-live`, guardians.approve | owner lead or admin; both approvals given |
| retired | live | `rollback`, admin | reason of at least 20 characters; the version was live before |
| shadow, approved, live | retired | `retire-version`, guardians.edit | none |

Only a draft or a benchmarked version is edited in place (a change of a benchmarked version
sends it back to draft, see Benchmark). "New version" copies a non-draft version into version + 1 as a
draft (one row per version in `guardian_def`). `guardian_def_event` is append only.

## Plain-words authoring

`POST /v1/guardian-defs/{id}/draft-artifact` with `{type, text}` (text at most 1,000 characters).

1. `regex` and `keyword_list`: the pattern library first. Entries: `card_number` (16 digits in a
   row), `cccd` (12 digits starting with 0), `phone_vn` (+84 or 0, then 9 digits), `amount_vnd`
   (thousand separators and a unit), `account_number` (9 to 14 digits); named words (quoted words,
   or the list after `words:`).
2. Otherwise, and for `judge_prompt` and `policy`: one `complete_json` call to the gateway model
   with a strict output schema. The sentence goes to the model after the secret scrubber and the
   masker. The answer is validated with the definition schema (the regex safety checks run on it);
   a bad answer is refused with the field problems (`model_output_refused`). With `LLM_BASE_URL`
   empty (or `LLM_MOCK=1`) the model path answers `model not configured`; the library still works.
3. Over-broad check: the regex or keyword list is run on a synthetic benign sample of 120 texts
   (`benign_sample.py`). A match share above 5 percent sets `over_broad: true` and `match_pct`
   (integer percent). The draft is returned, not refused.

## Adapter

`adapter.to_detector(definition, delegates=, chat=, masker=)` for a `live` definition (`build` for
the benchmark and the shadow run). Slug `guardian_<id>`, version `<version>.0.0`, sides from the
stage (`output` reads `output`, the others read `args`; `input` also `tool_results`). Regex uses the
`custom_rules` machinery (`Extras`), keyword list a case-insensitive scan, policy the evaluator
above. Classifier delegates to the existing detector named by `model_ref`. Judge prompt makes one
judge call on the masked text; a judge that cannot answer is a `not_executed` entry, never a pass.
`action_on_fail` becomes the finding `action_hint`: `block` to `block`, `require_approval` to
`pause`, `redact` to `transform` (with the masked copy), `log` to `report`. The gate clamps
`block` and `pause` to `report` (R1 of `core/detectors.py`) except where a gate rule says otherwise:
see Promotion (WP-G3).
Scope (`agents`, `tools`, `data_classes`) and the allow-list (an entry stops counting after its
`expires` date) are checked before the detector runs.

## API and console

| Route | Permission |
|---|---|
| `GET /v1/guardian-defs` (`state`, `owner_group`, `stage`, `type`), `GET /v1/guardian-defs/{id}` (`version`), `GET /v1/guardian-defs-schema` | `guardians.view` (every role) |
| `POST /v1/guardian-defs`, `POST /v1/guardian-defs/{id}`, `.../draft-artifact`, `.../retire`, `.../reopen`, `.../new-version` | `guardians.edit` (reviewer, approver, owner, admin) |
| `GET /console/guardian-factory`, `GET /console/guardian-factory/{id}` (`new` opens an empty editor) | `guardians.view` |
| `POST /console/guardian-factory/{id}` (save; `new` creates), `.../draft`, `.../retire`, `.../reopen`, `.../new-version` | `guardians.edit` |

A member of the owner group (a role listed for the group in `config/factory_groups.yaml`) edits
its guardians; an admin edits all; everyone else reads. A wrong group is HTTP 403. A validation
error is HTTP 400 and the message names the field (`config.pattern: nested repeats ...`). Every
POST writes two `console_action` rows. Each save and state change writes a `guardian_def` chain
record (ids, enums, integers and the SHA-256 of the canonical definition; no rule text) and one
`guardian_def_event` row.

The editor has the Benchmark panel (section Benchmark) and a panel for shadow mode and promotion
that says the work arrives in a later package.

## Benchmark (WP-G2)

Same flag (`GUARDIAN_FACTORY=1`, `DETECTORS_ENABLED=1`); with it off every route below answers
HTTP 400 `guardian_factory_off`, reads no table and creates no folder. A definition in `draft` or
`benchmarked` can be benchmarked; no new setting.

```
 pack (attack + benign) --run--> for each sensitivity 1..4: adapter.build(definition) ---> TP FN FP TN
        |                                     \--> live detector of the same stage ------> same numbers
        |                                                  |
 generator / upload / traces                gate at the chosen sensitivity -> pass | fail (names the threshold)
                                                           |
              draft --[ mark benchmarked: newest run passed, same version, same definition hash ]--> benchmarked
              benchmarked --[ any change of the definition (hash differs) ]--> draft
```

### Pack format

A pack is a folder `DATA_DIR/guardian_factory/<def_id>/bench/<pack_id>/` (`pack_id`: lower case
letters, digits, `_`, `-`, at most 64) with three files.

| File | Content |
|---|---|
| `attack.jsonl` | One JSON object per line: cases that must be caught. `{case_id, stage, text` or `arguments, meta?, expected: true, label}` |
| `benign.jsonl` | The same shape with `expected: false`: cases that must pass (`label` optional) |
| `pack.json` | `{id, version, def_id, origin, counts{attack, benign}, files{name: {sha256, bytes}}, pack_sha256, created_by, created_at}` |

* `case_id`: letters, digits, `_`, `.`, `-` (at most 64), unique in the file.
* `stage`: `preflight`, `input`, `tool_call` or `output`. The runner uses the cases whose stage is
  the stage of the definition and counts the others as `other_stage`.
* Give `text` (a string) or `arguments` (an object), never both. `text` goes to `args.text`, or to
  `output` for an `output` stage; `arguments` becomes `args`. `meta` may hold `agent_id`,
  `tool_name`, `data_class` (strings), for scope and policy conditions.
* Limits: 5 MB, 5,000 cases in a pack, 4,000 characters per case. A bad line refuses the whole
  file with the line numbers (`pack_invalid`); too big is `pack_too_large`.
* `pack_sha256` is the SHA-256 of `<sha of attack.jsonl>:<sha of benign.jsonl>`. A run reads the
  files through these hashes; a file changed by hand is refused (`pack_changed`). A new upload
  to the same `pack_id` is `version + 1`.
* **Masker.** Every case of an upload and of a trace import goes through the Vietnamese regex
  masker (the one the golden sets use). A case that trips it (a name, a phone, an account or id
  number of nine or more digits, an address, an email) refuses the file; nothing is stored. So a
  pack for personal-data detectors cannot be uploaded with realistic values: use the generator,
  which writes values from fixed fake blocks only (`origin: generated`; no masker pass, by design).

### Making a pack

| Way | Route / button | What it does |
|---|---|---|
| Generate starter pack | `POST .../bench-packs {op: "generate", pack_id}` | For a `keyword_list` or a `regex` whose pattern is a library pattern (`card_number`, `cccd`, `phone_vn`, `amount_vnd`, `account_number`): 100 synthetic attack cases (five Vietnamese and English sentence templates, values from a hash) and 140 benign cases (the 120 texts of `benign_sample.py` plus 20 near-miss texts for the pattern). No model. Any other regex or type: `generator_unsupported`. |
| Upload | `POST .../bench-packs {op: "upload", pack_id, attack_jsonl?, benign_jsonl?}`; console: one multipart file and `which` | Stores the given file(s); a file left out keeps the one of the existing pack. |
| Import benign from traces | `POST .../bench-packs {op: "import_traces", pack_id, limit?}` | Reads the stored, masked gate traces (`agent_event`, `gate_decision` and `tool_call` rows; `args_masked`, or `result_masked` for an `output` stage) of the agents and tools in the scope of the definition; drops empty and repeated texts and any text that still trips the masker; at most 2,000, evenly spaced over the rows sorted by event id. Keeps the attack set of an existing pack. `no_traces` when none is left. |

### Runner

`bench.run_benchmark(definition, pack, sensitivities=(1, 2, 3, 4), live=None)` returns a
`BenchResult` (`to_dict()` is the stored `result_json`). For each level it builds the detector with
`adapter.build` on a copy of the definition with that `sensitivity` (no live-state check) and runs
every case of the stage. `classifier` and `judge_prompt` use the gateway model (`chat=`); a case
the model cannot answer counts in `not_executed` and fails the gate. The adapter does not read
`sensitivity` today, so a deterministic type gives the same counts at each level (only latency
varies); the rows are there so a later detector that uses it is measured the same way.

Result shape (integers only; no case text):

```
{ "schema": 1, "def_id", "version", "type", "stage", "pack_id", "pack_sha256",
  "chosen_sensitivity": 2,
  "counts": {"attack": 100, "benign": 140, "other_stage": 0},
  "levels": [ {"sensitivity": 1..4, "tp", "fn", "fp", "tn", "tpr_pct", "fpr_pct",
               "p50_us", "p95_us", "cost_tokens", "not_executed"} ... ],
  "live": {"slug": "dlp_vn", "tp", "fn", "fp", "tn", "tpr_pct", "fpr_pct", "p50_us", "p95_us", ...} | null,
  "gate": {"verdict": "pass|fail|not_run", "failing": [...], "thresholds": {...}, "checked": {"tpr_pct", "fpr_pct", "p95_us"}},
  "advisory": false, "mock": false }
```

* `tpr_pct` = TP * 100 / (TP + FN) rounded **down**; `fpr_pct` = FP * 100 / (FP + TN) rounded
  **up** (the report never flatters a guardian). Latency is per case, in microseconds
  (`perf_counter_ns` // 1000), p50 and p95 by nearest rank. `cost_tokens` is the estimated token
  count of the prompt and the case for a `judge_prompt`, `0` for every other type.
* **Live comparison.** `compare_with` of the definition (`""`, `dlp_vn`, `injection_regex`, `none`;
  new optional field, default `""`). Empty means the catalogue detector closest to the stage:
  `injection_regex` at `preflight` and `input`, `dlp_vn` (report mode) at `tool_call` and
  `output`; none for a `policy`. The live row runs the same cases.
* **Gate.** At the sensitivity of the definition: pass when `tpr_pct >= thresholds.min_tpr_pct`
  and `fpr_pct <= thresholds.max_fpr_pct` and `p95_us <= thresholds.max_p95_ms * 1000`. Otherwise
  `fail`, and `failing` lists every threshold missed (`min_tpr_pct`, `max_fpr_pct`, `max_p95_ms`,
  and `not_executed` for a model that did not answer); the table column `failing_threshold` holds
  them comma separated. `not_run` when the chosen sensitivity was not in the run. A `classifier`
  or `judge_prompt` result carries `advisory: true` (and `mock: true` for a mock judge): the gate is
  shown, but such a guardian can only `log` or `require_approval` anyway.

### Runs, states, chain

* `POST /v1/guardian-defs/{id}/benchmark {pack_id?}` queues a run (HTTP 202) in a background
  thread, one at a time per guardian (`already_running`). The pack defaults to `benchmark_pack` of
  the definition. The table `guardian_bench_run` holds one row per run: `status` `queued`,
  `running`, `done` or `failed` (the message is in `result_json.error`), `gate`, `failing_threshold`,
  `pack_sha256`, `def_sha256`, `result_json`. A row left running by a restart is closed as
  `failed` at the next start. The console panel polls every two seconds while a run is active.
* `def_sha256` is the SHA-256 of the canonical definition without `lifecycle`, `created_*` and
  `updated_at`.
* **Mark benchmarked** (`POST .../mark-benchmarked`): `draft -> benchmarked` only when the newest
  run of this version is `done` with gate `pass`, its `def_sha256` equals the definition now, and
  its pack is `benchmark_pack` of the definition. Otherwise `no_passing_run` (HTTP 400) with the
  reason. Saving a benchmarked version with a different hash sets it back to `draft` (event
  `reset_to_draft`); saving the same content keeps it. Shadow, approved and live are WP-G3 (see Shadow and Promotion).
* Each finished run writes a chain record `guardian_bench`: run id, definition id and version,
  pack id and hashes, type, stage, sensitivity, gate, failing threshold, case counts, TP FN FP TN,
  the three rates, p95 in microseconds, the live detector slug and its two rates. Integers and
  ids only. Pack changes write `guardian_def_event` rows (`bench_pack_generate`, `_upload`,
  `_import_traces`).

### Routes

| Route | Permission |
|---|---|
| `GET /v1/guardian-defs/{id}/bench-packs`, `GET .../benchmark/{run_id}`, `GET /console/guardian-factory/{id}/benchmark` | `guardians.view` |
| `POST /v1/guardian-defs/{id}/bench-packs`, `.../benchmark`, `.../mark-benchmarked` | `guardians.edit` + owner group |
| `POST /console/guardian-factory/{id}/bench-packs/{upload,generate,import-traces}`, `.../benchmark`, `.../mark-benchmarked` | `guardians.edit` + owner group |

Every refusal is HTTP 400 with the code in the message (404 for an unknown guardian or run); every
POST writes two `console_action` rows.

## Shadow (WP-G3)

Flag `GUARDIAN_SHADOW=1` (needs `GUARDIAN_FACTORY=1` and `DETECTORS_ENABLED=1`; default off). The
hook costs gate latency, so it has its own flag and a budget (`GUARDIAN_SHADOW_BUDGET_MS`, default
20 ms per call for all shadow guardians together). With the flag off the gate has no hook
(`DetectorGate.shadow` is None) and nothing here runs.

`POST /v1/guardian-defs/{id}/shadow/start` moves the newest version from `benchmarked` to
`shadow` (guardians.edit, owner group). The shadow period is `lifecycle.shadow_days` (0 or unset
= 7, at most 90). From then on `DetectorGate.prepare` calls the `ShadowRunner` after the real
detector pass of every call, outside the gate lock:

```
call -> policy rules -> prepare: real detectors (registry.run) -> shadow.observe  -> apply -> decision
                                                                  |  log only
                                                                  v
                      guardian_shadow_finding, guardian_shadow_day (counters)
```

* The runner builds each shadow definition with `adapter.build` and runs it only when the call
  direction fits the stage and `applies(meta)` says the call is in scope and not allow-listed.
  A regex, keyword or policy guardian runs inline. A classifier or judge guardian runs on one
  worker thread behind a queue of 50, so the gate never waits for a model; without a gateway model
  it is not run.
* The budget is read with a monotonic clock from the start of the hook. A shadow detector that
  would start after the budget is used is skipped and counted (`skipped_budget`).
* Findings: one row per finding in `guardian_shadow_finding`: `finding_id`, `def_id`, `version`,
  `agent_id`, `call_ref` (correlation or request id), `stage`, `finding_code`, `count`,
  `value_hash` (the finding digest: ids, code, integers, fragment digests), `would_action` (the
  `action_on_fail`), `reviewed` (empty, `correct`, `false`), `reviewed_by`, `created_at`. No masked
  value text and no argument text.
* Nothing is blocked, redacted or returned: the decision, the response and the records of the call
  are the same with and without the hook (a test compares a synthetic call set).
* Day counters (`guardian_shadow_day`: calls in scope, calls that would act, skipped, findings)
  are kept in memory and written every 25 calls or 5 seconds. The daily job
  (`python -m supervisor.jobs.guardian_shadow`, in-process job `guardian_shadow`, every
  `SCHED_GUARDIAN_SHADOW_S` = 86400 seconds) writes one chain record `guardian_shadow_day` per
  closed day: counts only.

The Shadow panel (in the editor) shows days elapsed, calls seen, would-act count, skipped, the
reviewed counts, the false rate against `max_fpr_pct`, and the review list with a Correct and a
False button per finding. `POST .../shadow/findings/{finding_id}/review` takes
`{"mark": "correct" | "false", "allow": {"reason", "expires"}}`; `allow` goes only with `false`.
A person may change a mark while the version is in shadow.

## Promotion (WP-G3)

```
benchmarked --start--> shadow --approve (owner_lead)--+
                          |    approve (platform_security)--> approved --go-live--> live
                          +--stop--> draft                                   |
                                          retired <--superseded, retire, rollback--+
```

**Approve** (`POST .../approve`, permission `guardians.approve`: roles approver and admin):

| Kind | Who |
|---|---|
| `owner_lead` | the approver of the owner group (a role the group lists in `config/factory_groups.yaml`, or the group in the user's `groups`), or an admin |
| `platform_security` | a member of the `platform` group (same rule), or an admin |

Refusals, all HTTP 400 with the code first: `author_cannot_approve` (the creator or anyone who
saved or created the version), `same_person` (the same person gives both approvals; case does not
matter), `not_eligible`, `already_approved`, `bad_kind`, and `shadow_not_passed`. The shadow
check runs on every approval: the period must be complete (now is at least the start plus
`shadow_days`), the reviewed false rate (integer percent of the reviewed findings) must be at most
`thresholds.max_fpr_pct`, and when findings exist at least one must be reviewed. The message
carries the numbers: day, calls seen, would act, reviewed, false rate, limit. When both kinds are
given the version becomes `approved`.

**Go live** (`POST .../go-live`, owner lead or admin): `approved -> live`. The previous live
version of the id becomes `retired` and stays readable. A live version is immutable (save is
refused with `not_draft`); a change is a new version.

**Attach.** The gate holds `LiveGuardians` (`DetectorGate.attach`, only when `GUARDIAN_FACTORY=1`).
A live definition is built with `adapter.to_detector` and registered in the detector registry
under the slug `gf:<def_id>@<version>`, for example `gf:account-numbers@2`. The per-agent override
that `DetectorGate.prepare` already reads (`AgentDetectors.enable`) switches the slug on for the
agents of `scope.agents` (`*` or a list; a consumer id `agent/consumer` counts as `agent`);
`scope.tools` and `scope.data_classes` are checked by the detector. The list is cached for 5
seconds and dropped at once after a move in the same process.

**Bindings.** A guardian binding (`docs/guardian-bindings.md`) may name the slug
`gf:<def_id>@<version>` of a live version: a product owner switches it off for the agents of one
AI system. The floor rules of `governance/guardians.py` apply unchanged (a slug in the floor of
the system cannot be switched off). With the flag off the slug is unknown.

**What `action_on_fail` does once live** (the gate rules, R1):

| Type | Action | Effect |
|---|---|---|
| regex, keyword list, policy | `block` | the call is blocked, rule `GATE-GUARDIAN-BLOCK`, input direction (preflight, input, tool_call stages) on every tool class; observe mode lifts it like the other detector blocks |
| regex, keyword list | `redact` | the masked arguments go back (the existing dlp transform) |
| any | `require_approval` | recorded as a finding with hint `pause`; the gate does not pause an agent for it (clamped to a report) |
| any | `log` | recorded as a finding |
| classifier, judge prompt | any | a report only; a model advises (the definition schema already refuses `block` and `redact`) |

A guardian that cannot run (a timeout, no model) never fails a risky call closed
(`fail_closed_allowed` is false). Output-stage `block` is clamped to a report.

**Rollback** (`POST .../rollback`, admin): `{"reason": "...at least 20 characters...", "to_version": n}`
sets the newest earlier version that was live (or `to_version`) live again; the live version
becomes retired. **Retire** (`POST .../retire-version`, `{"version": n}`, guardians.edit) retires
a shadow, approved or live version on request.

Every move writes a `guardian_def_event` row (`shadow_started`, `approval`, `approved`, `live`,
`retired`, `rolled_back`, `shadow_stopped`, `allow_added`, `allow_removed`, `allow_expired`) and a
chain record `guardian_promotion`: `def_id`, `version`, `action`, `from`, `to`, `def_sha256` (the
definition without its lifecycle), `approvals_n`, `actor_ref` (keyed short hash), `ts` and
integers. No person id, no text, no float.

## Allow-lists (WP-G3)

`lifecycle.allow_list` holds entries `{agent_id, reason, expires}`; an entry always ends.

* `POST .../allow` `{"agent_id", "reason", "expires"}` (guardians.edit, owner group) on a
  shadow, approved or live version; `POST .../allow/remove` `{"agent_id"}`. A false mark in the
  review list may add the entry in one step.
* `expires` is a date `YYYY-MM-DD`, not in the past and at most 90 days from today
  (`bad_expiry`); the reason is required; at most 50 live entries; one entry per agent
  (`allow_exists`).
* An allow-list entry only changes `lifecycle`, so it does not change the definition hash and
  does not need a new version.
* An expired entry is ignored by the guardian at once (the adapter compares the date) and is
  flagged on the panel. The daily job removes it and writes the event `allow_expired`.

## API and console additions (WP-G3)

| Method and path | Permission |
|---|---|
| `GET /v1/guardian-defs/{id}/shadow` (`?pending=1`) | guardians.view |
| `POST .../shadow/start`, `.../shadow/stop` | guardians.edit |
| `POST .../shadow/findings/{finding_id}/review` | guardians.edit |
| `POST .../allow`, `.../allow/remove`, `.../retire-version` | guardians.edit |
| `POST .../approve`, `.../go-live`, `.../rollback` | guardians.approve |
| `GET /console/guardian-factory/{id}/shadow`, `.../promotion` (panels) | guardians.view |
| `POST /console/guardian-factory/{id}/shadow/start`, `shadow/stop`, `shadow/review/{finding_id}`, `allow`, `allow/remove`, `retire-version` | guardians.edit |
| `POST /console/guardian-factory/{id}/approve`, `go-live`, `rollback` | guardians.approve |

`guardians.approve` is held by the roles approver and admin. `GET /v1/guardian-defs` adds
`shadow_days` (days elapsed, in state shadow) and `live_version` to each row. Every console POST
writes two `console_action` rows.

## Not legal advice

The pattern library and the sample are illustrative and synthetic. A bank team confirms each
guardian before it protects anything.
