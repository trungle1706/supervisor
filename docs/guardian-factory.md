# Guardian factory (WP-G1, phase 12C)

Flag `GUARDIAN_FACTORY=1` (needs `DETECTORS_ENABLED=1`). Default off. With either flag off every
route answers HTTP 400 `guardian_factory_off` and no table is read. This package (WP-G1) defines
and stores guardian definitions. The benchmark (WP-G2) and shadow mode, approval and going live
(WP-G3) come later.

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

One table in `caps.py` (`TRANSITIONS`); `ALLOWED_NOW` marks what WP-G1 allows.

| From | To | Allowed now |
|---|---|---|
| draft | retired | yes |
| retired | draft | yes (reopen) |
| draft | benchmarked | not yet (WP-G2) |
| benchmarked | shadow, draft, retired | not yet (WP-G2, WP-G3) |
| shadow | approved, draft, retired | not yet (WP-G3) |
| approved | live, retired | not yet (WP-G3) |
| live | retired | not yet (WP-G3) |

Only a draft is edited in place. "New version" copies a non-draft version into version + 1 as a
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

The editor has panels for the benchmark and for shadow mode and promotion; both say that the work
arrives in a later package.

## Not legal advice

The pattern library and the sample are illustrative and synthetic. A bank team confirms each
guardian before it protects anything.
