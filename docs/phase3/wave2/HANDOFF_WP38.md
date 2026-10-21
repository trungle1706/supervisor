# HANDOFF WP38: Collectors and policy semantics

Branch `wp38-collectors` (built on `wp37-verdict-detectors`, final head merged). Flag `COLLECTORS_ENABLED`
(default off; off = the v0.3.0 Integrations page). Nothing pushed, merged or rewritten. Author: Sonnet 5.5.

## 1. What was built

| Part | Where |
|---|---|
| Catalogue in code: 8 templates (python_sdk, langgraph_middleware, fastapi_middleware, rest, mcp_stdio_proxy, mcp_http_proxy "available after WP26", litellm_guardrail, claude_code_hook), own text, placeholders filled after the key exists, values validated | `src/supervisor/collectors/catalog.py` |
| Adapters (fail_mode closed by default, lazy framework imports, fakes in tests) | `src/supervisor/gateway/adapters/` (`common.py`, `langgraph.py`, `fastapi_mw.py`, `litellm_guardrail.py`, `claude_code_hook.py`) |
| SDK: `HttpGate.check_v2` / `InProcessGate.check_v2` add `direction` and correlation header; `check` signature unchanged (a test pins it) | `gateway/sdk.py` |
| Console: catalogue cards by category, agent select, Add (first key via WP20 file store, shown once, no-store), drawer Connection / Credential (metadata) / Policy binding; delivery table kept | `console/collectors_view.py`, 3 templates, routes, `collectors/credentials.py` |
| RBAC: new `collectors.add` (admin, operator), matrix in `docs/console.md` regenerated | `core/rbac.py` |
| Policy: `agents.<id>.mode`, `rules {enable,disable}`, `consumers.<id>` {mode, detectors, rules}; resolved `consumers[ctx.consumer_id] ?? agent`; observe in the engine; SIEM attrs; hash unchanged without the keys (pinned) | `gateway/policy.py`, `gateway/engine.py`, `adapters/integrations/siem.py` |
| Playground: sample library (8 samples, EN and VI, synthetic) + extra attributes panel; dry run still no-write (fingerprint test green) | `console/playground.py`, templates, `data/eval/playground_samples/` |
| Harness: 144 contract cases (4 adapters x 9 statuses x 4 settings) on a real HttpGate replaying answers of a real gateway; 26 probes; overhead p50/p95; baseline; regression pytest; mutation test | `collectors/harness.py`, `collectors/probes.py`, `data/eval/collectors/`, `tests/collectors/test_harness.py` |
| Docs: `docs/collectors.md`, `docs/policy.md`, `docs/collectors-validation-report.md`, ADR `D28` (D23 was the highest on the branch), INTEGRATION_GUIDE pattern D, console.md, api.md, threat-model 3.11, README, index, CHANGELOG, 9 BACKLOG rows | `docs/` |

## 2. Decisions to check

1. **Observe sets legacy `action: log`, not `report`.** `supervisor_agents/common/gate.py` rejects unknown actions and fails closed, so `report` would block old clients. `status: report` is set (also when detectors are off), plus `observed_decision`, `mode`. Verdict rows get label `observe_would_*`.
2. **Gate order words describe what the engine does:** fixed order pause, block, alert, log, then severity, then rule id. NOT file order (files are merged and sorted). The brief's sentence "rules run in file order" and "detectors may raise to pause" do not match the code or WP37 (a finding never pauses); policy.md follows the code.
3. **Observe does not lift** state blocks, `GATE-REDACTION`, or SHADOW (SHADOW keeps precedence). It does turn `GATE-DETECTOR-FAILED` into a report.
4. **Invalid or unknown consumer id** is ignored (agent settings apply, `consumer_ignored: true`) instead of a 400, so a bad id can never pick an override.
5. **Guard added:** a consumer cannot disable a block/pause rule of risk class money or credit (load error). Consumer `skip_tools` for money/credit/pii_export is refused (WP37 rule extended to consumers).
6. **Consumer detector overrides reuse `DetectorGate.check_policy`** (small additive edit in a WP37 file: it now also walks consumers).
7. **No new column.** `agent_event` has no observed field; verdict rows, chain, SIEM carry it (BACKLOG, WP39).
8. **Add needs a page flag:** it sits behind `CONSOLE_INTEGRATIONS_ENABLED` and `COLLECTORS_ENABLED`; key store `file` is written, env/secret scope shows manual steps.
9. **Correlation id:** the adapters generate it (one per tool call, shared by input and output check); the gate still generates one when the header is missing. `supervised_tool` and `HttpGate.check` do not send one yet (BACKLOG).
10. **WP37 review items applied:** adapters apply `transformed_payload` on status `transform` (also for a redacted skip), replace the whole payload, never merge; `timed_out` is not failed open; a `transform` without values is a block.
11. Playground sample format is my own (one JSON per sample: id, titles, category, language, source, licence, labeller, agent_hint, tool, args, context, direction, consumer_id, note). WP28 should match or convert.
12. Tests edited: `tests/test_rbac.py` (operator set gets `collectors.add`), `tests/console/test_rbac_matrix.py` (audit coverage list). Nothing skipped or reduced.

## 3. Tests

| | Count |
|---|---|
| Before (WP37 head at start) | 3800 passed, 29 skipped |
| After (final, WP37 final head merged) | 4011 passed, 29 skipped (the WP37 review added its own tests) |
| New in WP38 | tests/gateway/test_wp38_policy.py (52 with params), tests/collectors (97), tests/console/test_collectors_page.py (19), test_playground_wp38.py (about 12) |

Commands (last lines):
```
uv sync
uv run python -m pytest -q          -> 4011 passed, 29 skipped, 1 warning in 539.03s
uv run python -m ruff check         -> All checks passed!
uv run python -m ruff format --check -> files already formatted
uv run python -m supervisor.collectors.harness --check -> [OK] no drop below the baseline  (OVERALL: GO)
```
Harness: contract 144/144, probes 26/26, overhead p95 about 30 us (langgraph, hook) and 150 to 290 us (asgi, litellm), limit 5000 us (illustrative). Wilson lower bound of contract pass is above 9700 bp. No tuning set exists (expectations come from the spec), so no dev/held-out split.

## 4. Files touched outside the package

`src/supervisor/config.py` (WP38 block: `collectors_enabled`, `collectors_public_url`), `core/rbac.py`, `console/routes.py`, `console/i18n.py`, `console/playground.py`, `console/templates/playground.html` and `_playground_result.html`, `gateway/sdk.py`, `gateway/policy.py`, `gateway/engine.py`, `gateway/detector_gate.py` (check_policy, additive), `adapters/integrations/siem.py`, `policies/schema.json` (regenerated, +104 lines), `pyproject.toml` (E501 ignore for the two harness files), `tests/test_rbac.py`, `tests/console/test_rbac_matrix.py`, docs (see above), README, CHANGELOG, BACKLOG.

## 5. Open questions for the owner

1. Should `mode: observe` be allowed per consumer on agents with money tools? Today only rule switches are guarded; a compromised agent can name an observe-mode consumer.
2. OK that `action` stays `log` in observe (status says `report`)?
3. Want the "file order" wording changed in the engine instead (a behaviour change that moves policy hashes of decisions)? I documented the real order.
4. May Add pass the secret through the browser (it does, once, no-store, not in the audit row)? Rotation stays on the CLI.
5. Operator may Add (as the brief said); confirm that operators may issue agent keys.
6. A real-framework run (LangGraph, deepagents, LiteLLM installed) is not part of this repo's CI; wanted as a nightly outside the repo?
7. Add a column for the observed decision to `agent_event` with WP39?

## 6. Follow-ups after review (REVIEW_WP38.md, commits bdef889 70517c7 610de1a f9424e5 kept)

| Item | What was done | Commit |
|---|---|---|
| F14 | New agent key `rule_approvals` (two distinct ids, same shape as `observe_approvals`). Agent-level `rules.disable` naming a block or pause rule of risk class money, credit or pii_export is refused at load without it; the ASCII message names the agent and the rule. Left out of the hash when empty (test). Schema regenerated, `docs/policy.md` updated | 138576f |
| F15 | The loader refuses `mode: observe` for any consumer of any agent (not only money agents). Agent-level observe unchanged. Tests and doc updated; the reviewer and author tests that used consumer observe now use other consumer fields | 138576f |
| F16 | Stays a BACKLOG row (updated). The hook's catalogue steps now say the minimum assistant version rule and give a self-test (`python -m supervisor.gateway.adapters.claude_code_hook < event.json`, exit 0 allowed, 2 refused) with a sample event line. I did not invent a version number: the text says "the first release whose hook documentation lists updatedInput for PreToolUse". The owner or tooling team should name the number | 138576f |
| Cleanup | The reviewer's scratch logs had been swept into 138576f by `git add -A`; they are untracked again | c54248c |

Commands (last lines):
```
uv run python -m pytest -q            -> 4053 passed, 29 skipped, 1 warning in 492.26s
uv run python -m ruff check           -> All checks passed!
uv run python -m ruff format --check  -> 714 files already formatted
uv run python -m supervisor.collectors.harness --check -> OVERALL: GO / [OK] no drop below the baseline
```
Test count before the follow-ups: 4049 (review). After: 4053 (+4 net: 4 new F14/F15 tests; the consumer observe tests were rewritten in place). One earlier run with `-x` stopped on `tests/integrations/test_integrations.py::test_chain_feed_writes_schema_events_once`: a random 10-digit run inside a hash matched the "no long digit run" regex. It passed on rerun and is unrelated to WP38 (flaky, worth a note for the integrator). Scratch logs: `wp38_followup_pytest.txt`, `wp38_followup_pytest2.txt` (untracked).

## 7. Alignment with WP39

`observe_approved` (bool) is now in the chain record of an observed decision (next to `observed_decision`) and in the SIEM attrs. `Decision.consumer_id` exposes the resolved consumer id (only when the policy has an entry for the caller value; the raw value is never echoed). Integrator: make WP39 record `Decision.consumer_id` / the answer field `consumer_id` instead of the raw `context.consumer_id`. Documented in docs/policy.md. Tests in tests/gateway/test_wp38_policy.py.
