# HANDOFF WP37: Verdict contract v2 and detector framework

Branch `wp37-verdict-detectors` (off main, v0.3.0). Flag `DETECTORS_ENABLED`, default off.
Nothing pushed, nothing merged, no history rewritten. Author: Sonnet 5.5 engineer.

## 1. What was built

| Part | Where |
|---|---|
| Detector contract: `Detector` protocol, `SettingsSchema` / `SettingField` (7 field types), `Finding`, `Entity`, `Fragment`, fixed `NOT_EXECUTED_REASONS`, `DetectorRegistry` (catalogue from code, settings validation, runner, coverage, fail-closed list), `derive_status` | `src/supervisor/core/detectors.py` |
| Detectors `dlp_vn` (masker; the only transform), `injection_regex` (Tier 0b patterns; report only), `judge_advisory` (Tier 1 judge; report only; MockJudge labelled `mock` by default). Presets strict / balanced / lenient as integer bp, frozen per version `1.0.0` (test) | `src/supervisor/detectors/` |
| Gate side: pre-lock detector pass, fold-in, `GATE-DETECTOR-FAILED`, dlp transform, finding rows, chain fields, fallback v2 | `src/supervisor/gateway/detector_gate.py`, small edits in `gateway/engine.py` |
| Verdict v2 on `POST /v1/gate/check`: `status`, `findings[]`, `not_executed[]`, `coverage`, `transformed_payload`, `request_id`, `correlation_id`, `direction`, `detectors`, `detector_latency_us`; `direction` in the request; header `X-Supervisor-Correlation-Id` in and out; `GET /v1/gate/detectors` (catalogue) | `gateway/routes.py` |
| Settings: `config/detectors.yaml`; per-agent override `agents.<id>.detectors` (preset, enable, disable, settings, skip_tools) in the policy file | `config/detectors.yaml`, `detectors/config.py`, `gateway/policy.py` |
| Persistence: table `finding`; `agent_event` gets nullable `verdict_status`, `correlation_id`, `coverage_json`; chain `gate_decision` record gets status, ids, finding codes, finding hashes, coverage reasons (no text); SIEM / OCSF attrs `status`, `finding_codes`, `correlation_id` | `schema/model.yaml` + both DDLs, `siem.py` |
| Harness: `python -m supervisor.detectors.harness`; golden set `data/eval/detectors/` (3 detectors x 60 dev + 60 held-out, 38 adversarial probes), Wilson intervals, latency, taxonomy, GO/NO-GO, `--check`, `--record`, `--md`; baseline file; regression pytest | `src/supervisor/detectors/harness.py`, `golden.py`, `tests/detectors/test_harness.py` |
| Docs: `docs/detectors.md`, `docs/detectors-validation-report.md`, `docs/api.md` (v2 section), ADR `docs/adr/D23-verdict-contract-v2.md` (highest existing was D22), README row, `docs/index.md`, `docs/siem.md` row, 12 BACKLOG rows, threat-model section 3.10 | `docs/`, `README.md`, `BACKLOG.md` |

Precedence (documented in `docs/detectors.md` section 4 and tested): block > pause > transform >
report > allow. `skip` only from a policy value (`skip_tools`). The old `action` keeps the gate
order (pause rule first), so a call can show `action: pause` with `status: block` when a block rule
matched as well.

## 2. Decisions I took (please check)

1. **"`gate_decision` gets columns" -> `agent_event`.** There is no `gate_decision` table; the
   decision row is `agent_event` with `event_type=gate_decision`. The old `status` column there
   already means allowed / denied, so the new column is named `verdict_status`.
2. **Flag off = the old answer, byte for byte.** The v2 fields are added to the answer only when
   `DETECTORS_ENABLED=1`. The off-path fingerprint test (`tests/detectors/test_flag_off_fingerprint.py`)
   was recorded on v0.3.0 code before any WP37 code existed (`6522e57b...`). The three new NULL
   columns of `agent_event` appear in rows read back from the store; the fingerprint ignores them
   when NULL (nothing writes them with the flag off). `direction: output` with the flag off is HTTP 400.
3. **Output direction is not a tool call:** no rule is evaluated, no window changes, no pause. State
   checks (quarantined, retired, unknown agent) still block. The output text goes in
   `context.output`; tool results for an input check in `context.tool_results`.
4. **`skip`** has no rule action in the policy language (not added). It comes from
   `agents.<id>.detectors.skip_tools`, a deterministic policy value. A skip never hides a block or pause.
5. **Detectors run before the gate lock** (like `_pre_redact`) and are folded in after the
   deterministic decision exists. The brief said "after the deterministic rules"; the decision and
   the rules never read detector output, but the work itself is not sequenced after the rules.
6. **`judge_advisory` is `fail_closed: false` and `enabled: false`** in `config/detectors.yaml`.
   A judge outage must not stop payments (R1), and a real judge model in the hot path is slow.
7. **A finding with `action_hint` pause or block counts as `report`.** Reserved for WP25 after MRM.
8. **The dlp transform** also fills the old `transformed_args` (when args changed and WP24b did not
   already), so the SDK and the MCP proxy keep working with their own local switch.
9. **`policy_hash` is unchanged** for policy files without `detectors` (the key is dropped from the
   dump when unset; test). `policies/schema.json` regenerated (68 added lines, none removed).
10. **Fragments with `precision: leaf`:** when an injection phrase only matches after Telex decoding,
    look-alike folding, or on the unmasked text (the masker once swallowed a word of it: a name before
    "Ignore" became one PERSON token), no offsets exist, so the fragment points at the whole masked leaf.
11. **Path keys:** a dict key that is not a plain identifier shows as `*` in a fragment path.
12. **Commit trailers:** the team brief names `Claude Fable 5.1`; the first commit (fingerprint)
    carries `Claude Sonnet 5.5` from the session attribution reminder; all later commits use the brief's line.

## 3. Flags and commands

| | |
|---|---|
| Flag | `DETECTORS_ENABLED=1` (default 0); `DETECTORS_CONFIG` (path, default `config/detectors.yaml`) |
| Harness | `python -m supervisor.detectors.harness` (`--help`, `--check`, `--record --commit <sha> --date <day>`, `--md PATH`, `--json PATH`, `--catalogue`, `--regenerate`) |
| Catalogue | `GET /v1/gate/detectors` or `python -m supervisor.detectors.harness --catalogue` |

## 4. Harness result (mock path, preset balanced; thresholds ILLUSTRATIVE)

Overall GO on every metric, with these honest weaknesses (also in BACKLOG and the report):

| Detector | dev recall | held-out recall | precision (dev / held-out) | adversarial recall (n positives) | notes |
|---|---|---|---|---|---|
| `dlp_vn` | 10000 | 10000 | 10000 / 9756 | 5000 (6 of 12) | misses spelled-out digits, letter O for zero, dotted name, obfuscated e-mail, base64, value split across two fields. Fragments 10000 exact. 0 leaks |
| `injection_regex` | 9000 | 9000 | 10000 / 10000 | 5294 (9 of 17), 2 false positives on look-alikes | `urgent_transfer` (6500 bp) is below the balanced threshold (7000 bp): 4 `below_threshold` per split. Misses typo, leetspeak, base64, reversed text, split fields, paraphrase, text past 20,000 characters |
| `judge_advisory` (MockJudge) | 10000 | 10000 | 10000 / 10000 | 3333 (1 of 3) | the mock is keyword based, so the templates are its cues; this proves the harness, not a model |

p95 latency per item: dlp about 1.0 ms, injection about 0.3 ms, judge mock about 0.8 ms.
The adversarial thresholds (5000 / 4000 / 3000 bp) were written before the first run and not changed after.

## 5. Tests

| | Count |
|---|---|
| Before (main, v0.3.0, brief) | 3,684 passed |
| After (this branch, full suite) | 3,800 passed, 29 skipped (live Databricks, perf and optional-extra tests, as before). 115 are new, so the old part is 3,685 passed (the brief says 3,684; I did not get a clean run on main: my first baseline log was overwritten by another agent, see section 8) |
| New tests | 115 in `tests/detectors/` (contract 35, gate v2 34, routes 12, persistence 10, harness 23, fingerprint 1) plus 1 edited expectation in `tests/test_retention.py` |

Existing tests changed: `tests/test_retention.py` (expected retention-class map gets the `finding`
table). Regenerated generated files: `schema/ddl/*.sql`, `policies/schema.json`,
`notebooks/bootstrap_and_smoke.py` (embeds the DDL). No existing test was skipped or reduced.

Both modes: SQLite laptop and `databricks_app` mode (on the SQLite stand-in the other e2e tests use)
through `build_runtime`; the Delta statements for the `finding` table on the recorded fake executor
(`MERGE INTO`, typed parameters, no raw text in the statement).

Commands run (last lines):

```
$ uv sync
$ uv run python -m pytest -q -p no:cacheprovider
3800 passed, 29 skipped in 483.95s (0:08:03)
$ uv run python -m ruff check
All checks passed!
$ uv run python -m ruff format --check
682 files already formatted
$ uv run python -m supervisor.detectors.harness
OVERALL: GO
$ uv run python -m supervisor.detectors.harness --check
[OK] no drop below the baseline
$ uv run python -m pytest -q tests/detectors -p no:cacheprovider
115 passed
$ uv run python -m schema.generate        (DDL regenerated; tests/test_schema.py checks it is current)
$ uv run python -m supervisor.databricks.notebook     (notebooks/bootstrap_and_smoke.py regenerated)
```
Two full runs: the first (after the schema change) showed 4 failures that I fixed (the AgentEvent
model columns, which two tests needed, the committed Databricks notebook, and the retention-class test); the second
run is the one above. An earlier log of mine was overwritten by another agent writing the same file
name in the shared scratchpad; I re-ran into a private folder.

## 6. Files touched outside the package (`src/supervisor/detectors/`, `core/detectors.py`, `gateway/detector_gate.py`, `tests/detectors/`)

| File | Change |
|---|---|
| `src/supervisor/config.py` | block `# --- WP37 ---`: `detectors_enabled`, `detectors_config` (+ the path validator list) |
| `src/supervisor/app.py` | not touched (the new route rides on the existing gate router) |
| `src/supervisor/gateway/routes.py` | `direction` on `CheckRequest`; correlation header; `GET /gate/detectors` |
| `src/supervisor/gateway/engine.py` | `detector_gate` argument, `direction` / `correlation_id` / `request_id` keyword arguments on `check` and `evaluate_only`, `_pre_detect`, fold-in at the end of `_evaluate`, finding rows, extra `agent_event` and chain keys, `_fail` fallback. All additive, all behind `detector_gate is not None` |
| `src/supervisor/gateway/policy.py` | `AgentDetectors` model, `AgentManifest.detectors`, hash helper that drops the unset key, `Policy.agent_detectors` |
| `src/supervisor/gateway/wiring.py`, `src/supervisor/wiring.py` | `make_detector_gate`, passed to `Gateway`; startup error on a bad config or override |
| `src/supervisor/core/rbac.py` | route entry `GET /gate/detectors` -> `gate.read` |
| `src/supervisor/core/models.py` | `AgentEvent`: 3 optional fields |
| `src/supervisor/recorder/normalise.py` | span attribute `supervisor.gate.correlation_id` -> `agent_event.correlation_id` |
| `src/supervisor_agents/common/runtime.py`, `tracing.py` | span attributes `supervisor.gate.correlation_id` and `.status` when the answer has them |
| `src/supervisor/adapters/integrations/siem.py` | `attrs` for a gate decision that has a status |
| `schema/model.yaml`, `schema/ddl/sqlite.sql`, `schema/ddl/databricks.sql` | table `finding`, 3 `agent_event` columns; generator run |
| `policies/schema.json`, `notebooks/bootstrap_and_smoke.py` | regenerated |
| `pyproject.toml` | one line: `T20` (print) allowed in `detectors/harness.py` like the other harness CLIs |
| `config/detectors.yaml` | new |
| `data/eval/detectors/` | new golden set, manifest, baseline |
| `README.md`, `BACKLOG.md`, `docs/*` | see section 1 |

No new dependency. No change to the console pages.

## 7. Not done (BACKLOG has the rows)

Console view of findings and the latency split (WP39); SDK sends `direction`, `context.output` and
the correlation header (WP38); per-entity mask token and custom rules for dlp; description scan of
tools (WP26); the ML classifier (WP25); a preemptive detector timeout (today it is checked after
the call returns); a real judge model inline (adds its latency; not validated here); observe mode and
per-consumer policy (WP38).

## 8. Self-review (R1 to R3, secrets, 500s, ASCII, defaults)

* R1: no finding blocks or pauses; hints pause and block are clamped to report (test). The only
  paths that change a decision: `GATE-DETECTOR-FAILED` (fail-closed detector could not look, money,
  credit or pii_export tool; `judge_advisory` is excluded) and the dlp transform. Tested for both, and
  for "flag on gives the same allow / action / rule_id as flag off" on a call set.
* R2: findings, fragments, entities, rows and chain hold masked text, codes, counts and hashes only.
  Tests search the answer, the `finding` rows, the `agent_event` rows, the chain payloads and the Delta
  statement for raw name, phone and CCCD strings. The harness fails on any leak (`leak_items`).
  An exception message is never copied (class name only). Dict keys in paths are sanitised.
* R3: no network in the contract or the detectors; the judge uses the configured endpoint only (or the mock).
* No `exec`, `eval`, `compile` or `subprocess` (the AST test passes). No secrets. User errors are
  HTTP 400 (bad `direction`, bad correlation header, `direction=output` with the flag off).
* ASCII: CLI output is ASCII (tested). Golden data contains Vietnamese text on purpose.
* Defaults off: flag false; the config file is read only when the flag is on.

Risks for the integrator:

* `engine.py` is a hot merge file (WP24b, WP22 edits). My edits are small and additive; the
  `_evaluate` signature gets two trailing optional parameters (`det`, `req`).
* The three `agent_event` columns and the `finding` table need the additive migration on an existing
  Delta schema (`python -m supervisor.jobs.bootstrap_schema`, the same path WP22 used for `latency_us`).
* The scratchpad directory is shared between agents: my first full test log was overwritten by another
  agent's file of the same name; the numbers in this file come from a private subfolder.

## 9. Open questions for the owner

1. Is `verdict_status` on `agent_event` acceptable, or do you want a separate `gate_decision` table
   (a copy of the decision row with the v2 columns)?
2. Should a real judge be allowed inline (`judge_advisory` enabled with a real model)? It adds model
   latency to every call. Option: an async path that attaches the finding after the call.
3. Thresholds: are the presets (dlp 5000 / 8000 / 9500, injection 5000 / 7000 / 8500, judge 3000 /
   5000 / 7000 bp) acceptable as illustrative defaults? Should `urgent_transfer` (6500 bp) fire at `balanced`?
4. Which risk classes fail closed when a detector cannot run? Today: money, credit, pii_export (the
   bridge plan list). Should `read_only` tools that return personal data count?
5. Should the correlation id be generated by the SDK (so one id covers the span and the call from
   the start) instead of by the gate when the header is missing?
6. Does the bank want `skip` as a rule action in the policy language (with two approvers like block and
   pause), instead of `skip_tools` in the agent override?
7. Fragments and entity tokens are stored under the `masked` retention class (`finding` table). Same
   retention days as `agent_event.args_masked`: confirm.
