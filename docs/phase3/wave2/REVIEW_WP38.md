# REVIEW WP38: Collectors and policy semantics

Reviewer: Opus (application security and integration). Branch `wp38-collectors`. Scope: the WP38
delta, `git diff wp37-verdict-detectors...HEAD` (author head 8124b75). The reviewer did not push,
merge or rewrite history. Fix commits: `bdef889`, `70517c7`, `610de1a`, and the docs commit that
holds this file.

## 1. Verdict

**APPROVED WITH FOLLOW-UPS.** The review found 4 High and 8 Medium findings. All of them are
fixed on the branch and each fix has a test. The open follow-ups are Low and are in BACKLOG.md.

## 2. Findings

| Id | Sev | File:line (author head) | What | Fix |
|---|---|---|---|---|
| F1 | High | `gateway/engine.py:902,915-935` | Observe lifted a rule block AFTER `_redact` and the detector transform were skipped (they run only on an allowed call). An observed `pii_export` call was then allowed with the raw arguments and no `transformed_args`. A lifted `GATE-DETECTOR-FAILED` on a `pii_export` tool also let raw PII through. | `bdef889`: the rule block is lifted before the redaction and the detectors run. `GATE-REDACTION` and `GATE-DETECTOR-FAILED` on `pii_export` stay blocks. Tests: `test_approved_observe_on_a_pii_export_block_still_masks_the_arguments`, `test_observe_keeps_gate_redaction_a_block`, `test_approved_observe_keeps_detector_failure_on_pii_export_a_block` |
| F2 | High | `gateway/policy.py:418-441`, `engine.py:_apply_mode` | Observe had no money guard. A policy edit with `mode: observe` (agent level) or a consumer entry with `mode: observe` let money calls through. The consumer id is asserted by the caller, so a compromised agent could name the observe consumer (owner question 1). | `bdef889`: the loader refuses agent-level observe on a money agent unless `initial_state: SHADOW` or two distinct `observe_approvals`. It refuses consumer observe on a money agent in all cases. The messages are ASCII. At the gate, observe lifts nothing on money, credit or pii_export tools unless the agent has the approvals. |
| F3 | High | `gateway/engine.py:_pre_detect` (~952) | A consumer `detectors` override also applied to money tools. A caller-chosen consumer could disable a fail-closed detector and escape `GATE-DETECTOR-FAILED`. The author's own `test_per_consumer_detector_override_is_used` showed this on the money tool `pay`. | `bdef889`: a consumer detector override never applies to a money, credit or pii_export tool (the agent's block applies). Test `test_review_a_consumer_detector_override_never_applies_to_a_money_tool`. The author test was rewritten to use a read_only tool. |
| F4 | High | `adapters/langgraph.py:161`, `fastapi_mw.py:152`, `litellm_guardrail.py:96`, `claude_code_hook.py:143` | All four adapters applied masked values only when `status == "transform"`. A gate with `INLINE_REDACTION` on and `DETECTORS` off (v0.3.0, or WP37 with the flag off) sends `transformed_args` with no `status`. The adapters ignored the mask and the raw PII reached the tool. | `70517c7`: `GateAnswer.status` gives `transform` when masked values exist. The adapters apply masked values whenever they are present. Test `test_a_v1_only_masked_answer_is_applied_not_ignored`. |
| F5 | Medium | `adapters/common.py:refusal` | `allow: true` with `status: block`, with `action: block`, or with an unknown action (`report`) or status was let through. `supervisor_agents.common.gate` fails closed on the same answers. | `70517c7`: `GateClient.contradicts` refuses the call with `SDK-ANSWER-CONTRADICTS`. Test checks all 4 adapters x 4 shapes. |
| F6 | Medium | `engine.py:as_result`, `_payload` | Observe forced `status: report` also when a transform existed. A v2 client then dropped the masked payload. | `bdef889`: `observed_status()` keeps `transform`, keeps `block` when the final decision is a block, else gives `report`. |
| F7 | Medium | `litellm_guardrail.py:96`, `fastapi_mw.py:_body_from`, `common.py:refusal` | A transform that cannot be applied let the original through: LiteLLM values without `messages`, ASGI values without `body` or `text`, an output transform that is not a string, a `transformed_payload` that is not an object. | `70517c7`: all of these are a block (`SDK-TRANSFORM-UNAPPLIED`). Three tests. |
| F8 | Medium | `fastapi_mw.py:236-245` | When the response was too large and `fail_mode=open`, the chunks above the cap were dropped and the CUT body was sent with HTTP 200. | `70517c7`: the answer is 502 in both modes. Memory use stays bounded. Test `test_asgi_open_mode_never_sends_a_cut_response`. |
| F9 | Medium | `gateway/sdk.py:_send` | A request with a correlation header and no credential went through the default httpx `signed_transport`. This bypassed a `transport=` that the caller had configured (proxy, TLS settings). Every adapter call sends the header. | `70517c7`: if the caller set only `transport`, that transport is used (the header is then not sent). Test. |
| F10 | Medium | `claude_code_hook.py:build_gate` | The hook needed httpx (`adapters/http_json.py`). The brief requires the standard library only on a developer laptop. | `70517c7`: the hook uses its own `urllib` transport. Only `http`/`https` URLs are accepted. A 401 maps to `GATE-AUTH`. Tests. |
| F11 | Medium | `langgraph.py:_after_input/_after_output` | With `apply_transform=False`, the raw values went through on money and pii_export tools. | `70517c7`: for those tools the option has no effect. Test. |
| F12 | Medium | `engine.py:_tier0` rows, `console/decisions.py` | A lifted `GATE-DETECTOR-FAILED` had no `observe_would_*` verdict row, so the observe period could not be audited for it. The Decisions page did not show the observed decision. | `bdef889` (extra verdict row), `610de1a` (Details tab line "Observed decision"). Tests. |
| F13 | Low | `policy.py:_PROTECTED_RISK` | The consumer rule-switch guard covered money and credit, but not `pii_export`. | `bdef889` |
| F14 | Low | `policy.py:RuleSwitches` | Agent-level `rules.disable` can switch off a money block rule with one edit. The rule itself needs two approvers. | open, BACKLOG |
| F15 | Low | `policy.py:money_agent` | "Money agent" means a money, credit or pii_export rule in scope. An agent with no such rule can still call a money tool. The gate guards (F2, F3) protect that agent, but the loader does not refuse its consumer observe. | open, BACKLOG (per-agent tool lists, WP40) |
| F16 | Low | `claude_code_hook.py` | An old assistant version that ignores `updatedInput` runs the raw input. | open, BACKLOG |
| F17 | Info | `console/routes.py:integrations_page` | Flag off = the old page. Proved by the code path (the off branch is the v0.3.0 code, unchanged) and by marker tests. No stored byte fingerprint. | accepted |
| F18 | Info | `docs/policy.md` section 2 | The gate-order words match the engine: `Policy.ordered` sorts by action (pause, block, alert, log), then severity, then id, and `_ACTION_ORDER` re-sorts the matches. All rules are evaluated, and the first pause or block decides. The brief's "first block stops" is stated as "the first matching pause or block decides". One sentence added: a rule that cannot be evaluated counts as a block from that rule. The engine order was not changed. | doc line only |

WP37 extension (`detector_gate.check_policy`): additive (it walks the consumers in addition). All
WP37 tests pass unchanged (`tests/detectors`, incl. `test_review_wp37.py`: 144 passed). The
reviewer's runtime guard is in `engine._pre_detect`, not in the WP37 file.

## 3. Observe-mode test matrix

| Case | Expected | Test |
|---|---|---|
| SHADOW agent + observe | SHADOW downgrade, no `observed_decision` | `test_shadow_keeps_precedence_over_observe`, `test_unapproved_observe_never_lifts_a_money_block_after_shadow_ends` |
| Quarantined / unknown tool (state block) | block | `test_observe_does_not_lift_a_state_block`, `..._unknown_tool_block` |
| GATE-REDACTION in observe | block, agent not paused | `test_observe_keeps_gate_redaction_a_block` |
| GATE-DETECTOR-FAILED on pii_export, approved observe | block | `test_approved_observe_keeps_detector_failure_on_pii_export_a_block` |
| GATE-DETECTOR-FAILED on money, approved observe | report + verdict row `observe_would_block` + chain | `test_a_lifted_detector_failure_has_an_auditable_verdict_row` |
| Observe on running money agent, no approvers | load error (ASCII) | `test_observe_on_a_running_money_agent_without_two_approvers_is_refused` |
| SHADOW money agent, no approvers, later RUNNING | money block and pause enforced; read_only block lifted | `test_unapproved_observe_never_lifts_a_money_block_after_shadow_ends` |
| Consumer observe on money agent (even with approvers) | load error | `test_consumer_observe_on_a_money_agent_is_refused_even_with_approvers` |
| Guessed observe consumer + money tool, detector down | block GATE-DETECTOR-FAILED | `test_a_guessed_observe_consumer_gets_no_free_pass_on_a_money_tool` |
| Zero-width, homoglyph, CRLF, trailing-space consumer ids | override never selected, `consumer_ignored` | `test_confusable_or_injected_consumer_ids_never_select_the_override` (5 ids) |
| Approved observe on pii_export block | allowed, masked args, status `transform` | `test_approved_observe_on_a_pii_export_block_still_masks_the_arguments` |
| Old client (`supervisor_agents.common.gate.safe_check`) | allow, action `log` | `test_old_clients_accept_the_observe_answer` |
| Adapters (4) on the observe answer | pass | `test_an_observe_answer_passes_in_every_adapter` |
| AL-THREAT-NOT-ENFORCED data | computable from `verdict` label `observe_would_*` | `test_threat_not_enforced_is_computable_from_verdict_rows` |
| Console | Decisions drawer line | `tests/console/test_review_wp38.py` |
| Chain, SIEM | `mode`, `observed_decision`, attrs | author tests `test_observe_records_both_...`, `test_observe_is_visible_in_the_siem_event` |

## 4. Reviewer adversarial cases (outside the harness templates)

12 cases in `tests/collectors/test_review_wp38.py`, plus 5 consumer ids in `tests/gateway/test_review_wp38.py`:
1. `allow: true` with `status: block`; 2. `allow: true` with `action: report`; 3. an unknown status
`quarantine`; 4. `transformed_payload` that is a string (all four adapters each); 5. a v1-only masked
answer from an old gate (LangGraph, hook); 6. a pause on the output check (LangGraph, also with
`on_block=message`); 7. `apply_transform=False` on a money tool; 8. LiteLLM transform without
messages; 9. ASGI transform without body or text; 10. ASGI open-mode overflow; 11. zero-width,
CRLF and Cyrillic consumer and session ids; 12. a custom transport with a correlation id; plus the
async LangGraph path on a contradiction, the hook stdlib transport (file: URL refused, 401 =
GATE-AUTH, unreachable = exit 2).

The harness was checked again: 144 contract cases = 4 adapters x 9 statuses x 4 settings, run on
a real `HttpGate` that replays recorded gateway answers. 26 probes. The numbers reproduce. Latency
p95 is 21 to 351 us against an illustrative limit of 5000 us.

## 5. Other checks

* Vendor text: 6 and 7 word shingles of the catalogue, hook, adapters, i18n, the docs, the
  Playground samples and the collector templates were compared with the vendor handoff. The only
  overlap is Python import boilerplate. No copied sentence or code was found.
* Console: the key is shown once with `Cache-Control: no-store`. The audit row has
  `template:<id>|key:<key_id>` and no secret (author test). POST only, htmx header required (GET
  and non-htmx POST refused, no key issued: reviewer test). `collectors.add` can issue the first
  key only, and rotation stays on the CLI, so the permission is consistent with WP20. The
  Playground no-write fingerprint test and the i18n duplicate-key test pass.
* Lazy imports: importing the four adapter modules loads no third-party module. The hook and the
  SDK load none either; `http_json` (httpx) is not used by the hook any more.
* Shared files: the reviewer edits are in `engine.py`, `policy.py`, `sdk.py`, `console/decisions.py`,
  `_decision_drawer.html` and `policies/schema.json` (regenerated, +8 lines). No DDL change.

## 6. Commands (last lines)

```
uv run python -m pytest -q -x            -> 4049 passed, 29 skipped, 1 warning in 532.13s
                                            (before review: 4011 passed, 29 skipped)
uv run python -m ruff check              -> All checks passed!
uv run python -m ruff format --check     -> 713 files already formatted
uv run python -m supervisor.collectors.harness --check
                                         -> contract 144/144  probes 26/26 ... OVERALL: GO
                                            [OK] no drop below the baseline
```
Scratch logs (not committed): `wp38_review_pytest_before.txt`, `wp38_review_pytest_after.txt`,
`wp38_review_harness.txt`, `wp38_review_ruff.txt`, `wp38_review_fmt.txt`.

Final test count: **4049 passed, 29 skipped** (+38 reviewer tests; no test skipped or removed;
the author's WP38 policy tests were changed to use a policy where observe is allowed).

## 7. Recommendations on the seven owner questions

| # | Question | Recommendation |
|---|---|---|
| 1 | Consumer observe on money agents? | **No** (implemented). Consumer observe on a money agent is a load error. Agent-level observe on a money agent needs SHADOW or two `observe_approvals`, and only the approvals let observe lift a decision on a money, credit or pii_export tool. |
| 2 | `action: log` with `status: report`? | **Yes, keep it.** `supervisor_agents.common.gate`, the SDK, the MCP proxy (it reads `allow`) and the four adapters accept it (tests). `report` as an action would make old clients fail closed. |
| 3 | File order wording vs engine order? | **Keep the engine order** and the current doc. A change would move the policy hash and the semantics of every decision. |
| 4 | Secret through the browser once on Add? | **Accept** with the current controls: no-store, no key material in the audit row, htmx-only POST, first key only. Rotation stays on the CLI. Do not add a rotate button without a two-person check. |
| 5 | May operators issue agent keys? | **Accept for the first key only** (that is what the code allows). Look at it again with WP33, if the bank's segregation of duties puts key issuance with IAM admins. |
| 6 | Nightly run with real LangGraph, deepagents, LiteLLM? | **Yes, outside the repo CI**, with pinned framework versions in a separate environment. Report the results in the validation report. The frameworks must not become dependencies. |
| 7 | Column for the observed decision on `agent_event`? | **Not now.** The verdict rows (`observe_would_*`, now also for a lifted GATE-DETECTOR-FAILED), the chain and the SIEM carry it, and AL-THREAT-NOT-ENFORCED can be computed from them (test). Add a nullable column in WP39 only if the alert query must run without a join. |
