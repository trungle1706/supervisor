# Detectors and verdict contract v2 (WP37)

Flag: `DETECTORS_ENABLED` (default `0`). Decision record: `docs/adr/D23-verdict-contract-v2.md`.
Validation report: `docs/detectors-validation-report.md`. API shape: `docs/api.md`.

With the flag off the gate answers and records exactly as in v0.3.0. A test keeps a SHA-256
fingerprint of the answers, the verdict rows, the `agent_event` rows and the chain payloads for a
fixed call sequence (`tests/detectors/test_flag_off_fingerprint.py`).

With the flag on, the gate runs **detectors** on each call. A detector looks at the call and
returns **findings**. The gate adds `status`, `findings`, `not_executed`, `coverage`,
`transformed_payload`, `request_id` and `correlation_id` to its answer. Every old field stays.

```
 call --> deterministic rules (unchanged) --> decision
              |                                  |
              +--> detectors (pre-computed ------+--> fold in: findings, status,
                   outside the lock)                    dlp transform, GATE-DETECTOR-FAILED
```

## 1. The detector contract

`src/supervisor/core/detectors.py`. Pure Python. No model weights, no network.

| Part | Meaning |
|---|---|
| `slug`, `name`, `category`, `version` | Identity. `detector_id` is `slug@version` |
| `sides` | `input` and/or `output`. The registry runs a detector only when the call direction is in `sides` |
| `protocols` | `llm`, `mcp`, `a2a`, or `all` |
| `settings_schema` | Declarative fields: `key`, `label`, `type` (string, integer, number, boolean, enum, array, object), `required`, `default`, `enum`, nested `fields`. The registry adds two common fields: `preset` and `threshold_bp` |
| `presets` | Named thresholds in basis points. Illustrative. Frozen per `version` (a test fails when a number changes without a version change) |
| `evaluate(payload, settings, direction)` | Returns a list of `Finding` |

`payload` has the parts `args`, `tool_results` (input side) or `output` (output side), and `meta`
(`tool_name`, `risk_class`, `agent_id`).

`Finding`:

| Field | Meaning |
|---|---|
| `detector_slug`, `detector_id`, `code` | Who and what. Codes look like `pii.phone`, `injection.instruction_override`, `judge.compliance_bypass` |
| `score_bp`, `threshold_bp` | Integers, 0 to 10000. The finding fires when score is at or above the threshold (a finding that transformed the payload always counts) |
| `entities` | MASKED: type and pseudonym token (`<PHONE:e65362>`), never the value |
| `fragments` | Located on MASKED text only: `part`, `path`, `start`, `end`, `text`. Offsets index the masked leaf at `path`. `precision` is `span` or `leaf` (whole leaf: used when the match came from a normalised form with no offsets) |
| `masked_count` | Number of values masked |
| `action_hint` | `report`, `transform`, `pause`, `block`. See section 4: only `transform` from `dlp_vn` acts |
| `not_executed_reason` | `None`, or one of the fixed list below |

Reasons a detector did not run (fixed list):

| Reason | When |
|---|---|
| `execution_failed` | The detector raised. Only the exception class name is kept, never the message |
| `invalid_config` | The settings do not match the schema |
| `payload_too_large` | The inspected text is longer than `limits.max_payload_chars` |
| `content_uninspectable` | A part has content no detector can read (bytes, an object, nesting deeper than 12) |
| `not_applicable_for_direction` | The detector is enabled but its `sides` do not include this direction. Informational, not a failure |
| `budget_exhausted` | WP-D4. A budget-aware detector (`judge_moderation`) stopped before it asked every question: its deadline or `max_calls` came first. Findings found so far are kept. Advisory: never fail closed |
| `timed_out` | The detector did not answer within `limits.timeout_ms`. Each detector call runs in its own daemon thread and the gate waits at most `timeout_ms` for it, so a hung detector cannot hold a gate worker or delay a money decision past the gate budget. A hung thread stays until it returns (Python cannot kill a thread); at most 32 run at once, and with no free slot the detector is not started and is reported `timed_out` (detail `no free detector slot`) at once. Keep the sum of `timeout_ms` over enabled detectors below the gate timeout (2 s) |

`DetectorRegistry` lists the catalogue from code (`GET /v1/gate/detectors`,
`python -m supervisor.detectors.harness --catalogue`), validates settings against the schema, and
runs the enabled detectors.

## 2. Catalogue (version 1.0.0 of each)

| Slug | Sides | Does | Hint | Presets strict / balanced / lenient (bp) |
|---|---|---|---|---|
| `dlp_vn` | input, output | Wraps the `vn_regex-3` masker. One finding per entity type (`pii.person`, `pii.phone`, `pii.cccd`, ...). The only detector that transforms | `transform` for tools in scope, else `report` | 5000 / 8000 / 9500 |
| `injection_regex` | input | The Tier 0b pattern list as a detector (Vietnamese and English). Scans `args` and `tool_results` (indirect injection). Codes `injection.instruction_override`, `mode_switch`, `prompt_leak`, `policy_override`, `urgent_transfer`, `role_tag` | `report` | 5000 / 7000 / 8500 |
| `judge_advisory` | input, output | The Tier 1 judge. Without a judge model it uses the MockJudge and every finding says `mock: true`. The judge sees masked text only | `report` | 3000 / 5000 / 7000 |
| `judge_moderation` (WP-D4, section 3e) | input, output | Toxicity (one yes or no answer) and up to 5 topics with definitions, asked of the judge one question at a time. Codes `moderation.toxic`, `moderation.topic:<name>`. Mock without a judge model, `mock: true` | `report` | 3000 / 5000 / 7000 |

`dlp_vn` settings: `mode` (`transform` or `report`), `transform_risk_classes` (default
`[pii_export]`), `transform_tools`. In transform scope the call carries the masked payload in
`transformed_payload` (and in `transformed_args` when the tool arguments changed, so the SDK and
the MCP proxy apply it as they do for WP24b). Outside the scope `dlp_vn` only reports.

`dlp_vn` also has two WP41 settings (section 3b): `keep_args` and `pseudonym_mode`.

`injection_regex` scores per group (illustrative): override 9000, mode switch 9000, policy
override 8500, role tag 8000, prompt leak 7000, urgent transfer 6500, plus 500 for each extra
hit. At the `balanced` preset an urgent-transfer phrase alone does not fire. Known gaps are in
`BACKLOG.md` and in the validation report (typos, leetspeak, base64, split fields, paraphrase).

`guard_model` (WP-D3, `enabled: false` by default, section 3d) is a fifth detector: a configured model
scores jailbreak and indirect injection. Presets `strict` / `balanced` / `permissive` (3500 / 5500 / 8000 bp
for `guard.jailbreak`); codes `guard.jailbreak`, `guard.indirect_injection`.

`injection_classifier` (WP25, `enabled: false` by default, see `docs/injection-classifier.md`) is a fourth
detector. It is the only one whose `pause` hint the gate obeys: `GATE-CLASSIFIER-PAUSE`, money and credit tools only.

## 3. Settings: file and per-agent override

`config/detectors.yaml` holds the defaults (`default_preset`, `limits`, one entry per detector with
`enabled`, `fail_closed`, `settings`). A wrong value stops the start-up with one ASCII line that
names `DETECTORS_CONFIG` (the gateway routes then fail closed until it is fixed), and
`python -m supervisor.preflight` shows it as `[FAIL] detectors` before any start.

A policy file can override per agent (`agents.<id>.detectors`):

```yaml
agents:
  payments:
    detectors:
      preset: strict            # default preset for this agent
      enable: [judge_advisory]
      disable: []
      settings:
        dlp_vn: {mode: report}
      skip_tools: [get_balance] # no detector runs for these tools: status "skip"
```

`skip_tools` may not name a `money`, `credit` or `pii_export` tool: the policy loader refuses such a
policy with a message that names the agent and the tool (a skip would switch off the
`GATE-DETECTOR-FAILED` protection). Read-only tools and tools not listed in `tools:` are allowed.
Until `skip` becomes a rule action with two approvers, this is the only skip.

Every policy reload runs the same check as start-up on the per-agent overrides. A reload with a bad
override (unknown detector, wrong setting value) is rejected: the old policy stays in force, one
ASCII line is logged, and `StorePolicyProvider.rejected_hash` / `rejected_reason` say why. The first
load of a bad policy fails with the same message. A bad override therefore never reaches a money
call as `invalid_config`.

The span attribute `supervisor.gate.correlation_id` is copied into `agent_event.correlation_id` by
the recorder only when `DETECTORS_ENABLED=1`.

Order, strongest first: agent `settings.<slug>`, agent `preset`, `detectors.<slug>` in the file,
`default_preset`, the detector default. The key is left out of the policy hash when unset, so an
existing policy file keeps the hash it had.

## 3b. Benchmark defects fixed in WP41 (ADR D33)

The M2 benchmark on a real bank agent found two defects in this layer. Both fixes are behind the
existing flag (`DETECTORS_ENABLED`) and weaken no control.

### Keep a lookup key unmasked (`keep_args`, D29)

The `dlp_vn` transform replaced the only argument of a `pii_export` lookup tool (a ten digit tax
code in `tax_code`) with a pseudonym, and the tool answered NOT_FOUND on 16 of 16 calls. A tool
that looks a record up by a personal identifier needs that identifier as sent. The policy can say
so, per tool and per argument name:

```yaml
agents:
  credit_memo_agent:
    detectors:
      settings:
        dlp_vn:
          keep_args:
            lookup_customer_basic_info: [tax_code]   # tool: [top-level argument names]
          pseudonym_mode: typed                       # optional, see below
    keep_args_approvals: [dpo.lan, sec.minh]          # WP41 review: two distinct ids
```

What happens on an allowed call to that tool:

| Where | The named argument |
|---|---|
| `transformed_args` and `transformed_payload.args` (what the tool receives) | **as sent** |
| findings (`entities`, `fragments`), `finding` rows, `agent_event`, the chain record, the SIEM event, the session sketch, the `args_hmac` | **masked / hashed**, as without `keep_args` |
| the answer | `kept_args: ["tax_code"]` (also in `coverage.kept_args`, stored in `coverage_json`) |
| Decisions drawer (Detections tab) and the CSV export | the names, in the section "Arguments passed unmasked" and in the column `kept_arguments` |
| chain record `gate_decision` | `kept_args` (names only) |

Rules: it is an agent setting (a `consumers.<id>.detectors` block that names it is refused by
the policy loader, and `config/detectors.yaml` may not set it: the shared file would apply it to
every agent without audit or approval); when it names a `money`, `credit` or `pii_export` tool
the agent needs two distinct approver ids in `keep_args_approvals` (same shape as
`rule_approvals`; left out of the hash when empty), or the policy is refused (WP41 review); it
applies to input checks only (never to an output check, never to `tool_results`, never to a
nested key of the same name); no environment variable or request field can set it; only top-level argument names, at most 8 per tool and 64 tools, plain identifiers. Only
`dlp_vn` honours it (it does nothing when `dlp_vn` is off for the agent). Other arguments of the
same call stay masked. A blocked or paused call has no transformed arguments, so nothing is kept.
**Loading** a policy with a `keep_args` entry writes one WARNING log line (`audit: dlp_vn
keep_args loaded for <agent>: <tool>=<names> (policy <hash16>, approvals <ids>)`) and one chain
record `policy_keep_args` (agent lane; agent, scope, policy hash, tool and argument names,
approver ids) at start and
at every changed reload. The setting is part of the policy hash, so adding or removing a
`keep_args` entry changes the hash. A wrong shape is refused when the policy loads (same path as
any bad override). Use it for a declared lookup key, not for free text: a kept argument is
personal data that reaches the tool in clear. A threat-model note is in `docs/threat-model.md`.

### Typed pseudonyms (`pseudonym_mode`, D29)

`generic` (default): the masker guesses the class from the value, so a bare ten digit tax code is
typed `<BANK_ACCOUNT:...>`. `typed`: a text value that sits directly under an argument whose NAME
says what it is (`tax`, `mst`, `ma_so_thue` / `account`, `acct`, `stk`, `tai_khoan`, as a word of
the name) is typed by the name: `<TAX_CODE:...>`, `<BANK_ACCOUNT:...>`. The class stays visible in
the finding code (`pii.tax_code`), the pseudonym is still keyed and not reversible, and the
nesting is followed (`rows[0].tax_code`).

| Need | Use |
|---|---|
| The tool must receive the real value (a lookup key) | `keep_args` |
| The tool does not need the value but the reviewer must see which class it was | `pseudonym_mode: typed` |
| Neither | the default |

`typed` alone does not repair a lookup: the tool still receives a pseudonym. It makes records,
findings and alerts say TAX_CODE where the digits alone looked like an account number.

### Scan limits (`max_scan_bytes`, `DETECTORS_SCAN_BUDGET_BYTES`, D30 and D18)

With three detectors on, 8 KB of tool results added 72 ms (p50) to a decision, and a 99 KB
argument full of personal data held the gate for 1.7 s. Now:

* every detector has a setting `max_scan_bytes` (default **16384**, 256 to 1,000,000; in the file
  or per agent): the most text it reads in one call;
* all detectors together read at most **`DETECTORS_SCAN_BUDGET_BYTES`** (default **65536**; file
  key `limits.scan_budget_bytes`; the environment value wins) per call. The budget is spent in
  catalogue order: a detector that finds it empty is listed as not executed with the reason
  `payload_too_large`;
* arguments are read first, tool results last (the order of the parts), so a long document
  cannot push the arguments out;
* text beyond the limit is **not scanned**. The coverage says so: the part moves from `inspected`
  to `not_inspected` with `{"reason": "payload_too_large", "bytes": 42000, "scanned_bytes": 16382}`
  (the least any detector read), and `coverage.bytes` holds the total. The chain keeps the same
  integers. The drawer shows `scanned / total B`;
* `dlp_vn` never transforms text it only read in part. If its transform scope covers the call
  and an **argument** or the **output** was cut, it does not run (`payload_too_large`), whether
  or not the part it could read held personal data (WP41 review: before, clean padding followed
  by a phone number passed with `allow` and the raw number reached the tool), and on a `money`, `credit` or `pii_export`
  tool the existing rule `GATE-DETECTOR-FAILED` blocks the call (fail closed: the unmasked rest
  must not reach the tool). A cut **tool result** only drops that part from the transformed
  payload (no caller applies it). To let a larger argument through, raise `max_scan_bytes` for
  `dlp_vn` on that agent and check the latency;
* `limits.max_payload_chars` (100,000) stays as the outer bound: above it no detector runs;
* a shared memoising masker (it keeps the masked text, keyed by SHA-256, never the raw text)
  makes the second and third detector read a long text for the cost of a hash, and
  `injection_regex` stops at its byte budget and when every group is already at the top score.

Measured on the development host (SQLite, two detectors on, `dlp_vn` and `injection_regex`;
numbers in `HANDOFF_WP41.md` and `REVIEW_WP41.md`): 8 KB of tool results cost 20 to 25 ms before
and 12 to 15 ms now (p50, detector time, host load about 3.6), and the 99 KB argument is
answered in under 70 ms instead of 2 s or more. The target "under 10 ms added" is **not met**.

### Cut arguments fail closed on every risky tool (WP41b, D31 and D32)

The second benchmark showed two gaps in the rules above.

* **D31 (High).** Only a detector that would transform the call (`dlp_vn`) failed closed on a
  cut argument. A `credit` or `money` tool whose argument was cut by the scan budget (a 118 KB
  argument, 16 KB read) was allowed with status `report` and 85 percent of the text unread. Now,
  when the scan budget cuts **any argument** of a `money`, `credit` or `pii_export` call, the
  decision is a block with rule `GATE-DETECTOR-FAILED` and the reason
  `*:payload_too_large` (one `not_executed` row with the detector slug `*`, detail "arguments
  cut by scan budget"), whatever detectors are on (at least one enabled detector must be
  `fail_closed`, as for every other failure). A `read_only` tool and a cut tool result stay
  coverage only. Observe mode and the `fail_closed_risk_classes` limit apply as before.
* **D32 (Medium).** The 99 KB `pii_export` call failed closed as designed but took 879 ms p50
  on the benchmark host (18 ms in the lab). The cost was the inline masker (`INLINE_REDACTION_ENABLED`),
  which read all 99 KB before the gate knew the call would be refused; the detectors, the
  record (`args_masked` holds argument names and key hashes, never text) and the SIEM event were
  cheap. With the detector gate on, an argument above the `dlp_vn` `max_scan_bytes` (a check
  that stops at the limit) is not masked **when the detector result already fails the call
  closed**: `GATE-DETECTOR-FAILED` answers in 15 to 17 ms. The full argument is still covered by
  `args_hmac` (a keyed hash of all of it); the record holds the byte count in the coverage
  (`bytes`, `scanned_bytes`). When nothing refuses the call (every detector `fail_closed: false`,
  `pii_export` left out of `fail_closed_risk_classes`, every detector disabled for the agent,
  observe mode lifting the block on a non-pii_export tool in `redact_tools`), the masker runs on
  the full text as in WP24b, so a big `pii_export` argument never reaches the tool unmasked
  (WP41b review). With `dlp_vn` off, or with no detector gate, the masker runs as in WP24b.
* A cut row of a detector that is not `fail_closed` (for example `dlp_vn` with
  `fail_closed: false`) does not replace the `*:payload_too_large` row: the call still fails
  closed when any other enabled detector is `fail_closed` (WP41b review).

## 3c. `mrm_status` per detector (D24, D25)

Each detector entry in `config/detectors.yaml` has `mrm_status: GO | NO-GO` (default `NO-GO`).
It feeds one reader: the session monitor (`docs/session-monitor.md` section 2). Findings of a
detector that is deterministic (`dlp_vn`, `injection_regex`: `deterministic = True` in code) or
has `mrm_status: GO` count in the `findings` signal; findings of any other detector are recorded
on the turn and weigh 0. Shipped: `dlp_vn` GO, `injection_regex` GO, `injection_classifier`
NO-GO (held-out recall 8111 bp, false alarm 2522 bp), `judge_advisory` NO-GO, `judge_moderation` NO-GO. The status never
changes what the gate answers or records for the decision itself.

## 3d. Secrets group, custom rules and mask tokens (WP-D2)

The build plan calls this section 3c; `3c` was already `mrm_status`, so it is 3d here. Three new
`dlp_vn` settings. All are off or empty by default. With `secrets` absent (or `enabled: false`),
`custom_rules` empty and `mask_tokens` empty, the detector takes the old code path and its output
is byte for byte the same (golden test `tests/detectors/test_dlp_off_path_d2.py`).

```yaml
detectors:
  dlp_vn:
    settings:
      secrets: {enabled: true, action: report}     # action: report (default) | block
      custom_rules:
        - {id: proj, kind: regex, pattern: "PRJ-[0-9]{4}-[A-Z]{2}"}
        - {id: conf, kind: keyword, pattern: "CONFIDENTIAL", mask_token: "[HIDDEN]"}
        - {id: emp, kind: regex, pattern: "EMP[0-9]{5}", preserve_length: true}
      mask_tokens: {pii.phone: "<PHONE>"}
```

A per-agent value goes in `agents.<id>.detectors.settings.dlp_vn` as for every other setting.

### Secrets are a different kind of finding

A leaked credential is an incident, not a privacy problem, so it has its own finding code
`secret.<kind>` (never `pii.*`), score 10000. The kinds are in `supervisor.core.secret_patterns`
(`KINDS`): AWS access and secret keys, Azure storage key, SAS signature and client secret, Google
API key, private key id and OAuth token, GitHub, GitLab, Hugging Face, npm, Vault, Slack, Stripe
and SendGrid tokens, OpenAI (`openai_api_key`) and Anthropic (`anthropic_api_key`) keys, JWT,
bearer header, HTTP basic, URL with a password (a DSN), PEM private key block, Databricks token
and OAuth secret, three forms of a password assignment, and `password_field`: a string under a
key whose LAST word is `password`, `passwd`, `pwd`, `passphrase`, `secret`, `token`, `pin`, `pw`,
`mk`, or two words that join to `apikey`, `secretkey`, `privatekey`, `accesskey`. So
`client_secret`, `apiKey` and `accessToken` are found; `passwordPolicy`, `password_changed_at`,
`apiKeyName`, `privateKeyType`, `secrets_manager`, `client_secret_id` and `pwd_reset_url` are
metadata and are not. The value must be 6 or more characters (4 for `pin`, `pw`, `mk`; a pin is
digits), with no space, and not a date, a version, a URL, a template (`${X}`), a placeholder or a
flag; for `secret`, `token`, `apikey` and the like a plain lower-case word (`none`, `enabled`)
is skipped too. Vietnamese names are covered with the accents removed: `mat_khau`, `matkhau`,
`matKhau`, `mật_khẩu`, plus `mk` and `pw`. Other Vietnamese or local words are not (add a custom
rule). A secret hidden in base64 (a run of 24 or more characters that decodes to text with a
secret in it) is found and masked as a whole, also next to a plain secret in the same text. A
secret used as a dict KEY is found and masked too (the finding points at the dict, precision
`leaf`).

**One pattern source.** The onboarding scrubber (`onboard/scrub.py`) and this detector both use
`src/supervisor/core/secret_patterns.py`. A pattern added there protects both. The scrubber gained
the kinds it did not have (GitLab, Hugging Face, Stripe, SendGrid, npm, Vault) and a fix: the AWS
secret key pattern no longer needs a word boundary after a key that ends in `/` or `+`.

**What a finding keeps.** The kind and a keyed hash of the value: the first 12 hex characters
of an HMAC-SHA256 under the masker key (`VnRegexMasker.keyed_hash`; a masker without one gets a
random key held in the process), in the entity as `<SECRET:aws_access_key:3c1f...>`. It is never
an unkeyed hash: with one, anyone who reads the audit store could confirm a guessed password
offline and link one key across calls. The hash changes with the masker key, so it is stable only
while the key is. The value is never in a finding, a fragment, a log line, a record or the chain. The transformed payload holds `<SECRET:aws_access_key>` where
the value was, where `dlp_vn` transforms (mode `transform` and a tool in scope, as for personal
data). A secret is masked before the personal-data masker runs, so the masker never sees it.

**`action`.** `report` (default): a finding, and the mask above where `dlp_vn` transforms.
`block`: a secret in a tool ARGUMENT blocks the call with rule `GATE-SECRET-IN-ARGS` for every
tool class (a masked credential has still left, and a request that carries one is usually a bug
worth surfacing). The block uses the same fail-closed shape as `GATE-DETECTOR-FAILED`: `allow:
false`, `fail_mode: closed`, `status: block`, no `transformed_args`. A secret only in a tool
result, in `output` or in the context does not block; it is reported and masked. In `observe`
mode the block is lifted on a read-only or money/credit tool (money and credit need the two
observe approvals, as before) and the call goes on with the MASKED arguments in
`transformed_args`, status `report`: never weaker than report mode. On a `pii_export` tool the
block is held in observe mode, like `GATE-DETECTOR-FAILED`. The detector only sets the hint `block`; the gate decides (R1).

**Oversize payloads.** A payload over `limits.max_payload_chars` is skipped by every detector
(coverage `payload_too_large`; risky tools fail closed). With `secrets.action: block` `dlp_vn` is
the one exception: it declares `scan_head_when_oversize` and the registry runs it on the first
`max_scan_bytes` of the arguments only, with no transform. A `secret.*` block finding from that
head stands (`GATE-SECRET-IN-ARGS` on every tool class, read-only too), the `payload_too_large`
coverage stays, and `coverage.notes` gets `{detector: dlp_vn, reason: head_only, detail: "head
only: <n> of <m> bytes"}`. A secret after the head is not seen: that is the stated limit. With
`action: report` nothing changes for an oversize payload. Observe mode does not lift a block from
a cut or oversize payload (there is no masked copy to send).

**Report mode and the transform scope.** In `report` mode a secret is masked only where
`dlp_vn` transforms (mode `transform` and the tool in `transform_risk_classes` or
`transform_tools`). In the arguments of a tool outside that scope the secret reaches the tool as
sent and the finding is the only trace. Use `action: block` for money and credit tools.

**Not found, on purpose.** A secret split over two fields, with spaces, a zero-width character, a
hyphen inside, reversed or percent encoded is not found. The adversarial row of the validation
report counts them. If that matters, add an egress control on the tool.

### Custom rules

`custom_rules` is a list of at most 32 rules, applied in order after the secrets.

| Field | Meaning |
|---|---|
| `id` | `[a-z][a-z0-9_]{0,31}`, unique. The finding code is `custom.<id>` |
| `kind` | `keyword`: exact, case-sensitive substring. `regex`: Python `re` |
| `pattern` | 1 to 200 characters |
| `mask_token` | optional, 1 to 40 characters. Default `<CUSTOM:id>` |
| `preserve_length` | optional. The match becomes `*` repeated to its length |

A finding holds the rule id, the count and a short hash of each value; the value is never in it.
Checks at load (a bad value stops the start with a `ConfigError` that names the field, never a
call): unknown keys, an id used twice, a bad regex, a regex that matches the empty text, and a
risky shape: a repeat inside a repeat (`(a+)+`), an alternation under an unbounded repeat
(`(a|b)*`), a back reference, a finite repeat above 1000, groups nested deeper than 4, more than
two variable repeats (`+ * ? {n,m}`; `?` counts, so `a?a?a?...aaa` is refused) and two unbounded
repeats in sequence (`.*.*x`, `\w+\w+!`). A mask token
must not look like a pseudonym (`<TYPE:hex>`).

**Text cap and time budget.** A regex rule reads only the first 2000 characters of one text (a
leaf of the payload); the rest is not scanned. Keywords are not capped. A regex rule also has
10 ms for the whole call (all texts together). Python `re` runs in C and cannot be interrupted, so
the shape check above and the 2000 character cap are what bound one match; the budget is checked
between matches. A rule that reads less than all of a text, or goes over its budget, is a
**coverage note** (`coverage.notes: [{detector, reason: cut, detail}]` in the verdict), not a
`timed_out` row and not a finding: it never fails a call closed on its own. What it found before
the cut is still masked. Keep an eye on `coverage.notes` for rules that matter.

### Per-entity mask tokens

`mask_tokens: {pii.phone: "<PHONE>"}` replaces the pseudonym of the built-in entity in the
TRANSFORMED payload only. The keys are `pii.` plus the lower-case entity type. Findings, entities
and fragments keep the pseudonym (`<PHONE:ab12cd>`), so the fragment offsets refer to the default
masked text. A configured token loses the consistent pseudonym: two phones both become `<PHONE>`.

### Where the transform applies

**Version.** `dlp_vn` stays at 1.0.0 on purpose: `detector_id` (`dlp_vn@1.0.0`) is in every
finding, row and chain record, so a bump would change the bytes of the off path, which must be
identical. The new settings are visible in the catalogue schema.

The transformed payload comes from the `dlp_vn` transform. With inline redaction on
(`INLINE_REDACTION_ENABLED`) the masker pass of WP24b knows personal data only; when a `secret.*`
or `custom.*` finding exists, the detector's `args` replace those, so a secret never stays in
`transformed_args`.

## 3e. `judge_moderation`: toxicity and topic scope (WP-D4)

Phase 5. A judge detector that answers two kinds of question about text. It advises and reports;
it never blocks, pauses or transforms (R1), it never fails closed, and it is off by default
(`judge_moderation.enabled: false`, `mrm_status: NO-GO`). With the slug absent from
`config/detectors.yaml`, or with `enabled: false`, nothing changes: no judge call, no finding.

| Item | Rule |
|---|---|
| Sides and parts | `input`: the user text in `args` (the latest `role: user` message when `args.messages` is a list, else every string leaf). `output`: the assistant text in `output` |
| Questions | `toxicity: {enabled}`: is the text harmful language (abusive, hateful, degrading, threatening)? One answer, no breakdown by kind. `topics: [{name, definition}]`: is the text about this subject? One answer per topic; the other topics never change its score. A "no" answer never gives a finding, on any preset |
| Limits | At most 5 topics per detector (add a second detector entry for more). `name` 1 to 120 characters and unique. `definition` up to 400 characters. Unknown keys are errors. Checked when the file loads (`DetectorsFile`, per-agent override too), so a bad topic is a startup error, not a runtime surprise |
| What is scored | The DEFINITION. The name is only the label of the finding |
| Prompts | ONE prompt per text window carries every enabled question; the judge answers each by `id` with `{answer: yes or no, score_bp, reason}` in a strict schema. A topic definition is escaped, put on one line, quoted and marked in the prompt as a label, not an instruction; a definition with a control character (line break, tab) is refused when the file loads. A reply with the canary token (the model obeyed the data) is dropped and listed as `not_executed` `execution_failed`; it never becomes a finding |
| Windows | The first 10 000 characters, in windows of 1 200 characters with 200 overlap (at most 10). The highest "yes" score per question over the windows wins, so a subject at the end of a long text is found. Text past 10 000 characters is not read |
| Findings | `moderation.toxic`, `moderation.topic:<name>`. Score in basis points. A finding is returned when the score reaches the threshold (strict 3000, balanced 5000, lenient 7000; one threshold for all topics). `action_hint` is always `report`. No text in a finding |
| Judge | The Tier 1 judge the product built for `judge_advisory` (same model, same family rule: the judge family differs from every agent family, checked in `JudgeRouter`). Without a judge model the labelled MockJudge answers (keyword cues; it proves the harness, not a model) and every finding says `mock: true` |
| Cost and deadline | Model calls per check = number of windows: 1 for text up to 1 200 characters, usually 1 to 3, at most 10 for 10 000 characters, whatever the number of questions (up to 6). Retries count as calls and `max_calls` (default 12, 1 to 30) is a hard cap. The gate tells the detector its deadline (`limits.timeout_ms`, or the `timeout_ms` setting of this detector when set); the detector stops starting calls at 80 percent of it, never waits on a model longer than the time left, and then returns. Questions it did not ask are `not_executed` with reason `budget_exhausted` (the findings found so far are kept). So its thread frees its slot in the shared pool of 32 close to the gate timeout, and a slow judge cannot starve `dlp_vn`. A real judge model needs a larger `timeout_ms` for this detector (for example 8000) and still adds that time to the gate answer: keep it off in the hot path until a latency budget is set |

Settings, in `config/detectors.yaml` or per agent (`agents.<id>.detectors.settings.judge_moderation`):

```yaml
judge_moderation:
  enabled: true
  settings:
    toxicity: {enabled: true}
    topics:
      - name: Financial advice
        definition: Personal recommendations about what to invest in, buy, sell or borrow ...
```

Ten editable drafts, in Vietnamese and English, are in `config/moderation_topics.yaml` (financial
advice, legal advice, politics, loan approval promises, competitor products, internal project names,
medical advice, illegal activity, adult content, staff and branch security). The file is a menu: the detector never
reads it and none of the drafts is enabled. Copy a draft into the settings and edit it. Write one
plain sentence that says what belongs to the topic, in the language of your traffic; do not name a
neighbouring topic to rule it out; do not paste example messages. After a change, run the harness
on sample messages before you turn the topic on.

Harness: `python -m supervisor.detectors.harness --detector judge_moderation` (golden set in
`src/supervisor/detectors/moderation_golden.py`: toxic and benign, on-topic and off-topic, VI and
EN, 21 dev, 20 held-out and 10 adversarial items; the rubric is in that file; the topics are financial advice, politics and loan approval promises). Report:
`docs/judge-moderation-validation-report.md`. It ran on the MockJudge, so the numbers prove the
harness; `mrm_status` stays NO-GO until a real judge model runs the set (see `docs/judge-mrm.md`).
NO-GO (held-out recall 8111 bp, false alarm 2522 bp), `judge_advisory` NO-GO, `guard_model` NO-GO (WP-D3). The status never
changes what the gate answers or records for the decision itself.

## 3d. `guard_model`: ML jailbreak and indirect-injection scoring (WP-D3)

A fifth detector asks a configured model whether a text tries to take control of the agent. It
completes the regex (`injection_regex`) and the local classifier (`injection_classifier`) with a
model the bank chooses (`docs/guard-model-decision.md`). **Off by default**, `mrm_status: NO-GO`
until a real run gives GO, and a slug that is absent from `config/detectors.yaml` changes nothing.

| Item | Value |
|---|---|
| Sides, protocols | input and output; `llm` and `mcp` |
| Codes | `guard.jailbreak` (a person writes to the agent), `guard.indirect_injection` (hidden instructions in third-party text) |
| Parts read | `args` (user text fields), `tool_results`, tool descriptions (`meta.tool_description` and `meta.tool_descriptions`), `documents` (WP-D1; `payload["documents"]`), and `output` on the output side |
| Never read | system prompts. They are no payload part, and an argument key named `system`, `system_prompt`, `developer`, `developer_message` or `instructions` is left out |
| Text sent | the **masked** text (the masker runs on every leaf first; `dlp_vn` and the guard share the same masker) |
| Windows | 2,000 characters, 500 characters of overlap; the highest score wins; at most `max_windows` (12) per call, spread over the text; one batch per call; scores cached by text hash |
| Label | a model that names its class (`jailbreak`, `injection`) sets the label; a one-class model (`malicious`) takes the label of the surface (arguments: jailbreak; the rest: indirect injection) |

**Presets** are thresholds per label in basis points, frozen with the detector version
(ILLUSTRATIVE until the harness runs on the real model):

| Preset | jailbreak | indirect_injection |
|---|---|---|
| `strict` | 3500 | 4000 |
| `balanced` (default) | 5500 | 6000 |
| `permissive` (`lenient` is an alias) | 8000 | 8500 |

The preset moves one thing: how sure the model must be before the detector reports. `threshold_bp`
replaces the preset for both labels.

**Settings** (`config/detectors.yaml`, per agent in the policy file as for any detector):
`scan_args`, `scan_tool_results`, `scan_tool_descriptions`, `scan_documents` (all true),
`pause_tool_classes` (default empty), `pause_threshold_bp` (can raise the pause bar, never lower it
below the `permissive` value of the label), `max_windows` (at most this many windows in all, the
model's own `window_cap` can lower it; a note `windows dropped: n of m` is set in the `detail` of
the findings when some were left out), `timeout_ms` (this detector's own deadline, empty =
`limits.timeout_ms`). Common: `preset`, `threshold_bp`,
`max_scan_bytes`.

**The model** comes from the environment (`GUARD_MODEL_*`, `config.py`), not from the file:

| Setting | Meaning |
|---|---|
| `GUARD_MODEL_ADAPTER` | `auto` (default: `classifier` when `GUARD_MODEL_URL` is set, else the labelled mock), `mock`, `classifier`, `chat` |
| `GUARD_MODEL_URL` | `classifier`: the endpoint (`POST <url>` with `{"inputs": [...]}`). `chat`: the OpenAI-compatible base URL (default `JUDGE_T1_BASE_URL`, then `LLM_BASE_URL`) |
| `GUARD_MODEL_NAME` | model id; for `chat` the model (default `JUDGE_T1_MODEL`); it pins the approval |
| `GUARD_MODEL_VERSION` | the pinned revision of that model; it also pins the approval (see below) |
| `GUARD_MODEL_API_KEY` | bearer key; in `databricks_app` mode a workspace serving URL uses the App identity instead. For `chat` with no key set, the judge or LLM key is used only when `GUARD_MODEL_URL` equals the base URL of that same key (`JUDGE_T1_BASE_URL`, `LLM_BASE_URL`), never for another URL |
| `GUARD_MODEL_TIMEOUT_MS` | the total time of ONE call to the model, default 400: all batches or texts, the credential call and every attempt together, not a per-phase timeout. The adapter returns `timed_out` at that time even when the server sends one byte at a time. Keep it below the deadline of the detector (`limits.timeout_ms`, or the `timeout_ms` setting of `guard_model`) |
| `GUARD_MODEL_FAIL_CLOSED_APPROVED` | see below |

A URL that is not loopback needs `LLM_ALLOW_REMOTE=1`, unless it is the workspace's own serving
endpoint. The `chat` adapter obeys the judge family rule: the family is derived from the model id,
must be known, and must differ from every registered agent family, or start-up stops
(`FamilyConflictError`). The three adapters are in `src/supervisor/adapters/guard/`; port
`GuardModelPort.score(texts)` in `core/ports.py`. With no port the detector reports
`execution_failed` (only reachable by a per-agent `enable`, because the wiring sets the port only
when the slug is in the file).

**Time and threads.** The detector is budget aware (like `judge_moderation`): it takes 90 percent of
its deadline, never starts a model call with less than the adapter timeout left (reason
`budget_exhausted`), and runs the call in its own pool of 4 threads for all agents together. A slow
model therefore holds at most 4 threads and never the shared pool of 32, so `dlp_vn` is not
starved; when the 4 are taken, a call fails at once with `timed_out` ("busy"). Residual: a server
that answers the headers one byte at a time can keep its thread until httpx gives up; at most 4 such
threads exist. A real model needs `timeout_ms` for this detector above the gate default (500).

**Actions (R1).** Findings only. A timeout is `timed_out`, any other error `execution_failed`
(never an exception, never a block). The detector is **not fail closed**: `fail_closed: true` in the
file is ignored unless `GUARD_MODEL_FAIL_CLOSED_APPROVED=1` AND the card approval is valid. The
pause path is the WP25 one (section 5 of `docs/injection-classifier.md`): the finding carries the
pause hint only when all of these hold, and the gate then turns it into `pause` with rule
`GATE-CLASSIFIER-PAUSE` (never a block; a shadow agent is never paused). Residual: an endpoint
that reports no version leaves the version as the operator's declaration, and a model swapped
behind the same name is not seen; the classifier adapter reads `X-Model-Version` or a
`model_version` field of the answer when there is one:

```
 direction = input
 AND tool risk class in pause_tool_classes            (default empty = report only)
 AND finding score >= the pause bar of its label      (permissive threshold, can be raised)
 AND data/models/guard_model/model_card.json has approval.approver  (a person, not FILL-ME)
     AND approval.model_id == model_id == the model id the adapter serves (GUARD_MODEL_NAME)
     AND approval.model_version == model_version == GUARD_MODEL_VERSION (set, not FILL-ME)
     AND the version the endpoint reports, if it reports one, equals GUARD_MODEL_VERSION
 AND the adapter is not the mock
```

**Harness.** `python -m supervisor.detectors.guard_harness` runs the WP25 corpus (dev, held-out,
adversarial; `--split evasion` for the rewritten set) through the WP37 rubric with the mock adapter
(CI; `data/eval/guard_model/baseline_mock.json`, `--check`), or with the real endpoint when
`GUARD_MODEL_URL` is set. A mock run is never GO, and neither is a run with any item the detector did not score (printed
"run invalid") or without all three of dev, held-out and adversarial. Report: `docs/guard-model-validation-report.md`.
Model card: `docs/guard-model-card-template.md`, `data/models/guard_model/model_card.json`.

Tests: `tests/detectors/test_guard_model_review.py`, `tests/detectors/test_guard_model.py`, `test_guard_adapters.py`, `test_guard_model_gate.py`,
`test_guard_model_harness.py`, `test_guard_model_catalog.py`.

## 4. Verdict v2 and precedence

The status of a verdict:

| Rank | Status | When |
|---|---|---|
| 5 | `block` | A deterministic rule, a built-in block or `GATE-DETECTOR-FAILED` denied the call. Also when a block rule matched together with a pause rule that decided first |
| 4 | `pause` | A pause denied the call and no block rule matched: a pause rule, the classifier pause (`GATE-CLASSIFIER-PAUSE`), the state pause of an already paused agent (`GATE-PAUSED`) or the session pause (`GATE-SESSION-PAUSE`) (D26, WP41b). The old `action` field of the two built-in pauses stays `block` |
| 3 | `transform` | The call is allowed and `dlp_vn` (or WP24b redaction) produced a masked payload |
| 2 | `report` | The call is allowed and a finding fired, or a rule with action `log` or `alert` matched |
| 1 | `allow` | None of the above |
| - | `skip` | Only from a policy value (`skip_tools`), only when the deterministic decision would be allow or report. A block or pause is never hidden by skip, and a transform (WP24b inline redaction still runs on a skipped tool) shows as `transform` |

Precedence: **block > pause > transform > report > allow**. The old `action` field keeps the gate
order (a pause rule decides before a block rule), so one call can show `action: pause` and
`status: block`. The agent is paused in that case; the status tells the reader that a block rule
matched too.

What a detector may do to the decision (R1):

1. `dlp_vn` may add a transform to an allowed, non-shadow call.
2. A detector that is `fail_closed` and could not run makes an allowed call to a `money`, `credit`
   or `pii_export` tool a block with rule id **`GATE-DETECTOR-FAILED`** (`fail_mode: closed`).
   On any other tool the failure is only an entry in `not_executed`. An `advisory` detector
   (`judge_advisory`) never fails closed: the registry ignores `fail_closed: true` for it (a
   warning is logged at start-up), so a judge outage never blocks a payment.
3. Nothing else. A finding with `action_hint` `pause` or `block` counts as `report`. A shadow agent
   is never blocked or transformed; the findings are still reported.

Detector results are computed before the gate takes its lock (a masker pass over a 2 KB payload
costs a few milliseconds) and folded in after the deterministic decision exists. The rules do not
read them.

Direction: `direction` is `input` (default) or `output`. An **output check** is not a tool call:
no rule is evaluated, no window changes, no pause. The built-in state checks still apply (a
quarantined agent is blocked). The output text goes in `context.output`. For an input check the
tool results that fed the call go in `context.tool_results`. With the flag off, `direction:
output` is refused with HTTP 400.

## 5. Coverage

`coverage` says which parts of the payload were looked at:

```json
{"direction": "input", "inspected": ["args"],
 "not_inspected": [{"part": "tool_results", "reason": "not_provided"},
                   {"part": "output", "reason": "not_applicable_for_direction"}],
 "chars": 130}
```

Reasons for a part: `not_provided`, `not_applicable_for_direction`, `content_uninspectable`,
`payload_too_large`, `skipped_by_policy`, `execution_failed`, `gate_failed`. A part is `inspected`
when it was provided, every leaf is readable text (or a number), the total size is within
`limits.max_payload_chars` and every detector could read all of it (section 3b: `max_scan_bytes`
and the scan budget). A part that was read in part is listed with `payload_too_large` and the
integers `bytes` and `scanned_bytes`. Coverage lists parts, reasons and integers only, never text.

## 6. Ids

`request_id` is the HTTP request id (or a generated one). `correlation_id` comes from the
`X-Supervisor-Correlation-Id` request header (1 to 128 characters of `A-Za-z0-9_.:@-`; another
value is HTTP 400) or is generated. It is echoed in the response header and written to the
decision (`agent_event.correlation_id`), the `finding` rows, the chain record and the SIEM event.
The agent SDK runtime sets span attributes `supervisor.gate.correlation_id` and
`supervisor.gate.status` from the answer, so a trace span, a decision and an alert share one id.

## 7. Evidence and persistence

| Where | What (flag on) |
|---|---|
| Table `finding` (`schema/model.yaml`, both DDLs) | One row per fired finding and per detector that did not run. Entities and fragments are masked text. Retention class `masked` (columns `entities_masked`, `fragments_masked`) |
| `agent_event` | New nullable columns `verdict_status`, `correlation_id`, `coverage_json`. The old `status` column keeps `allowed` / `denied` |
| Chain record `gate_decision` | Adds `status`, `direction`, `request_id`, `correlation_id`, `finding_codes`, `finding_hashes` (SHA-256 of each finding without text), `not_executed`, `coverage` (parts and reasons), `transformed` (bool), `detectors`. No text, no token, no path |
| SIEM / OCSF event | `attrs.status`, `attrs.finding_codes`, `attrs.correlation_id` (OCSF `unmapped.attrs`) |

Paths in fragments show dict keys that are plain identifiers; any other key shows as `*`, because a
key could hold a name or a number.

## 8. Evaluation harness

```
python -m supervisor.detectors.harness            # score all detectors, print the table
python -m supervisor.detectors.harness --check    # exit 1 on a drop below the baseline
python -m supervisor.detectors.harness --help
```

Golden set: `data/eval/detectors/` (synthetic, licence "own (synthetic, MIT)"; `MANIFEST.json`
has hashes and counts). Per detector 60 items in `dev` and 60 in `heldout` (different templates;
nobody tunes on held-out), plus `adversarial.jsonl`: 38 hand-written probes the templates do not
generate (typos, leetspeak, Telex, no-diacritic Vietnamese, mixed language, split fields, base64,
reversed text, benign look-alikes). The report gives recall, precision, false-positive rate with
Wilson 95% intervals, typed recall (the expected code fired), fragment exactness (the fragment is
the text at its offsets in the masked leaf), leak items (a raw sensitive string anywhere in an
answer; must be 0), latency per item (p50, p95, max), the failure taxonomy and a GO / NO-GO per
metric against illustrative thresholds. The judge runs on the MockJudge: it proves the harness,
not a model. `tests/detectors/test_harness.py` fails on a drop below `baseline.json`.

Expert rubrics: SOC analyst reading a verdict (typed recall, fragments you can find, false
positives, speed) and data protection officer (no raw personal data in findings, fragments,
entities or the transformed payload).

WP-D2 adds the suite `dlp_vn_secrets` (`--detector dlp_vn_secrets`): the secrets group and custom
rules, with dev, held-out and adversarial items built at run time (no credential-shaped string is
committed) and its own baseline `data/eval/detectors/baseline_secrets.json`. The DPO rubric covers
the secret values and the custom matches too: `leak_items` must be 0.

## 9. How to add a detector

1. Write a class with the attributes of section 1 in `src/supervisor/detectors/<slug>.py`. Keep
   it pure: no network, no file reads, no model download. Return masked entities and fragments.
2. Give it `presets` with a `balanced` entry. Freeze them: add the numbers to
   `test_presets_are_frozen_per_version`.
3. Register it in `build_registry` (`src/supervisor/detectors/__init__.py`) and add an entry to
   `config/detectors.yaml` (`enabled`, `fail_closed`).
4. Add golden items (`golden.py`: dev, held-out, and at least a few probes outside the templates),
   regenerate with `--regenerate`, run the harness and record the baseline with `--record`.
5. Add tests: the contract (fires, does not fire, a failure becomes `execution_failed`), and that
   no raw value reaches a finding. Document the codes here.
6. A detector that uses a model needs a model card and a validation report under `judge/mrm/`
   conventions before it may run outside the mock path (team brief section 3, point 8).

## 10. Not in this version

See `BACKLOG.md` (WP37 rows): a console page for findings (WP39), per-entity mask tokens and
custom keyword rules for `dlp_vn`, tool-description scanning, the ML injection classifier
(WP25), a per-consumer policy binding (WP38).
