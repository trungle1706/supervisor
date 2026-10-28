# Guardian factory (WP-G1, phase 12C)

Flag `GUARDIAN_FACTORY=1` (needs `DETECTORS_ENABLED=1`). Default off. With either flag off every
route answers HTTP 400 `guardian_factory_off` and no table is read. This package (WP-G1) defines
and stores guardian definitions. The benchmark (WP-G2, section Benchmark) is in; shadow mode,
approval and going live (WP-G3) come later.

A **guardian definition** describes one detector as data. A `live` definition becomes a detector
of the existing contract (`core/detectors.py`) through `guardian_factory/adapter.py`, so WP-G3 can
attach it to agents by id through guardian bindings. In WP-G1 the adapter is unit-tested only; it
is not mounted into the gate.

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

One table in `caps.py` (`TRANSITIONS`); `ALLOWED_NOW` marks what WP-G1 and WP-G2 allow.

| From | To | Allowed now |
|---|---|---|
| draft | retired | yes |
| retired | draft | yes (reopen) |
| draft | benchmarked | yes (WP-G2): needs a passing run, see Benchmark |
| benchmarked | draft | yes (WP-G2): by any change of the definition |
| benchmarked | retired | yes |
| benchmarked | shadow | not yet (WP-G3) |
| shadow | approved, draft, retired | not yet (WP-G3) |
| approved | live, retired | not yet (WP-G3) |
| live | retired | not yet (WP-G3) |

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
`pause`, `redact` to `transform` (with the masked copy), `log` to `report`. The gate still clamps
`block` and `pause` to `report` until the gate rules say otherwise (R1 of `core/detectors.py`).
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
  `reset_to_draft`); saving the same content keeps it. Shadow, approved and live are WP-G3.
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

## Not legal advice

The pattern library and the sample are illustrative and synthetic. A bank team confirms each
guardian before it protects anything.
