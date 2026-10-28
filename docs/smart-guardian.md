# Smart guardian (WP-G4, phase 12C)

Flag `SMART_GUARDIAN=1` (default `0`; needs `GOVERNANCE_ENABLED` and `RISK_DIMENSIONS`;
`ONBOARD_ORCHESTRATOR` adds the assessment reports as input; accepting guardian lines also needs
`GUARDIAN_BINDINGS_ENABLED`; the panel on the system page needs `CONSOLE_SYSTEMS_ENABLED`; Windows
cmd: `set SMART_GUARDIAN=1`). Rules: `config/smart_guardian.yaml` (`illustrative: true`). Code:
`src/supervisor/onboard/smart_guardian.py`. Not legal advice. Bank counsel must confirm.

## 1. What it does

For one AI system, fixed rules read the assessment and propose what to put around the agent. A
person decides. The pre-deploy test (WP-O3) proves the fit. Nothing attaches by itself and nothing
is scheduled.

```
 facts v1 ----------+
 8 risk statuses ---+--> rules table --> PROPOSAL --> person accepts some or all lines
 assessment reports-+    (no model)      (open)            |
 classification ----+                                      v
 ai_* flags --------+                           bindings | thresholds | limits
 autonomy level ----+                                      |
                                              "Run pre-deploy now" = the proof
```

No model call. Every line has a `why` pointer and a `rule_id`. Numbers are whole numbers.
A new assessment run, or a newer proposal, supersedes the open proposal.

## 2. The proposal

Four groups:

| Group | A line is | Accepting it |
|---|---|---|
| `guardian_set` | a guardian slug to bind, with the stage it acts on | `GuardianService.set(system, slug, "on")`. The floor and the off-request rule stay. It turns an `off` row back on; it never turns on what the instance has off (the result says "Off in this instance") |
| `thresholds` | `monitor_threshold` (`drift.k`, `drift.consecutive`) or `detector_setting` (`<slug>.<setting>`) | a monitor threshold goes into `policy_threshold` for each linked agent. A detector setting is recorded in the proposal and shown as a policy-file block (`agents.<id>.detectors.settings`): the per-agent detector override lives in the policy file, and a person changes that file by pull request |
| `autonomy_limits` | `max_level`, `approval_above_vnd`, `daily_total_vnd`, `credit_approval_above_vnd`, `session_max_tool_calls`, `session_max_minutes` | merged into the system tag `autonomy_limits` (JSON text, integers and a level name) through `SystemService.update_fields`. The autonomy level of the system itself is not changed |
| `floor` | a slug of `RulesService.guardian_floor` | cannot be accepted or removed (HTTP 400 `floor_line`); always on |

Proposal JSON (the column `proposal_json`):

```json
{
  "version": 1, "illustrative": true, "system_id": "sys_...", "attempt_n": 2,
  "classification_outcome": "high_self", "generated_at": "2026-10-28T09:00:00Z",
  "config_sha256": "...",
  "inputs": {"dimension_status": {"cybersecurity": "fail"}, "flags": {"agentic": true},
             "autonomy_level": "l4_autonomous_bounded", "money_movement": true,
             "credit_decision": false, "personal_data": "identifiable", "user_segment": "customer",
             "facts_n": 14, "findings_n": 31, "reports_n": 8},
  "counts": {"guardian_set": 6, "thresholds": 4, "autonomy_limits": 5, "floor": 2},
  "lines": [{
    "line_id": "ln_a741f14569", "group": "guardian_set", "kind": "bind",
    "subject": "guard_model", "stage": "tool_call", "rule_id": "SG-G-INJ-PAIR",
    "why": {"kind": "finding", "id": "cybersecurity/f8-cy-08",
            "detail": "report rep-cy-1 checklist CY-08 verdict fail"},
    "selectable": true, "state": "proposed"
  }],
  "decision": {"accepted": ["ln_..."], "results": [{"line_id": "ln_...", "subject": "guard_model",
               "group": "guardian_set", "result": "applied"}],
               "detector_overrides": {}, "policy_snippet": "", "next": "run_predeploy"}
}
```

`why.kind` is one of `finding` (`<dimension>/<finding id>`), `fact` (`fact:<id>`, with file and
line in `detail`), `dimension` (`risk_dimension:<id>`, with the status), `flag` (`ai_<flag>`),
`classification` (`outcome:<outcome>`), `system_record` (`ai_system:<field>`) or `rule` (the
assignment rule of a floor line). When several conditions of a rule hold, the most specific pointer
is shown (finding, then fact, dimension, flag, system record, classification). A finding's text is
never copied; only its id, its checklist id and its report id.

## 3. Rules table (ILLUSTRATIVE; the bank sets the real one)

| Rule | Condition | Proposed line |
|---|---|---|
| `SG-G-INJ-PAIR` | cybersecurity finding `fail` on a checklist item named `CY-08` or "inject", or cybersecurity status `fail` | bind `injection_regex` and `guard_model` on `tool_call` |
| `SG-G-INJ-AGENTIC` | agentic flag and outcome high or medium | bind `injection_regex` (`tool_call`) |
| `SG-G-DLP` | data_governance `fail`, or personal data other than `none`, or a dataset fact | bind `dlp_vn` (`output`) |
| `SG-G-SESSION` | autonomy L3 or more, or outcome high | bind `session_monitor` |
| `SG-G-JUDGE` | the `decides` flag, or ethics `fail` | bind `judge_t2_sample` |
| `SG-G-DRIFT` | model `fail` or a failed model finding | bind `monitor_drift` and `monitor_quality` |
| `SG-G-FAIR` | credit decision | bind `monitor_fairness` |
| `SG-G-SPLIT` | money movement and agentic | bind `monitor_split_payment` (`tool_call`) |
| `SG-T-DLP-TRANSFORM` | personal data and a tool fact whose name matches export, send, mail, upload, report, statement, share ... | `dlp_vn.transform_tools` = the matched tool names |
| `SG-T-PRESET-STRICT` | outcome high, or cybersecurity `fail` | `guard_model.preset` = `strict` |
| `SG-T-PRESET-BALANCED` | outcome medium | `guard_model.preset` = `balanced` |
| `SG-T-PAUSE-CLASSES` | money movement and outcome high | `guard_model.pause_tool_classes` = `[money, credit]` (the model approval of `GATE-CLASSIFIER-PAUSE` still applies) |
| `SG-T-DRIFT-CONSECUTIVE` | outcome high, or model `fail` | `drift.consecutive` = 2 |
| `SG-T-DRIFT-K` | outcome high | `drift.k` = 2 |
| `SG-A-CAP-HIGH` | outcome high and autonomy L4 or more | `max_level` = `l3_tool_using_supervised` |
| `SG-A-CAP-FAIL` | cybersecurity, model or ethics `fail`, autonomy L4 or more | `max_level` = `l3_tool_using_supervised` |
| `SG-A-MONEY-APPROVAL` | money movement | `approval_above_vnd` and `daily_total_vnd` from `config/classification.yaml` thresholds: a customer system uses the personal values, others the organisation values |
| `SG-A-CREDIT-APPROVAL` | credit decision | `credit_approval_above_vnd` = the `credit_vnd` threshold |
| `SG-A-SESSION-CALLS` | agentic flag | `session_max_tool_calls` and `session_max_minutes` by outcome (high_certify 20 and 30, high_self 30 and 30, medium 60 and 60, low 100 and 120) |
| `SG-F-FLOOR` | always | one floor line per slug of the guardian floor (the engine adds these; they are not in the YAML) |

A guardian line for a slug that is already in the floor is left out (the floor shows it). A
`max_level` line appears only when it would lower the current level. A line whose number cannot be
built (no threshold in the file) is left out.

## 4. Storage and chain

Table `guardian_proposal` (appended at the end of `schema/model.yaml`): `proposal_id`,
`system_id`, `attempt_n` (the orchestrator attempt read; 0 when there was no run), `proposal_json`,
`status` (`proposed`, `accepted`, `rejected`, `superseded`), `proposed_at`, `proposed_by`,
`decided_by`, `decided_at`, `note` (at most 300 characters, URLs and long numbers removed).
Chain record `guardian_proposal` (ref `system:<id>`): `proposal_id`, `system_id`, `attempt_n`,
`status`, `proposal_sha256`, `n_guardian_set`, `n_thresholds`, `n_autonomy_limits`, `n_floor`,
`n_accepted`, `actor_ref`, `ts`. Integers and hashes only; no text, no name. The guardian bindings
written by an accept make their own `binding_change` records through the service.

## 5. API and console

| Route | Permission | What |
|---|---|---|
| `GET /v1/systems/{id}/guardian-proposal` | `systems.view` | the open proposal, else the newest (404 when none) |
| `POST /v1/systems/{id}/guardian-proposal` | `systems.edit` | make a proposal (201). The same content returns the open one; other content supersedes it |
| `POST .../guardian-proposal/accept` | `systems.edit` | `{"lines": ["ln_..."], "note": ""}` |
| `POST .../guardian-proposal/reject` | `systems.edit` | `{"reason": "20 characters or more"}` |
| `GET/POST /console/systems/{id}/guardian-proposal[/accept|/reject]` | view / edit | the panel fragment (HTMX); accept reads the fields `sel_<line id>` |

Errors are HTTP 400 with a code at the start of the message: `smart_guardian_off`,
`classification_required` (no approved classification), `plan_blocked` (prohibited or not a
system), `archived`, `no_open_proposal`, `no_lines`, `unknown_line`, `floor_line`,
`reason_too_short`, `note_too_long`, `changed` (the proposal was replaced; reload). A guardian line
the service refuses is listed in `decision.results` with its message; the other lines still apply.
A system outside the caller's scope answers 404. Every POST writes two `console_action` rows.

The panel sits on the **Guardians** tab of the system page and on the **Guardian fit** step of the
register workflow. Lines are grouped (guardian set, thresholds, autonomy limits, floor) with the
why pointer and the rule id; the floor has no checkbox. After an accept the panel shows the result
per line, the policy-file block for detector settings, and **Run pre-deploy now** (the existing
`POST /console/predeploy/{node}`, with `ONBOARD_PREDEPLOY` on and a node linked to the system).

## 6. Off path

With the flag off, every route answers HTTP 400 `smart_guardian_off`, no table is read, and the
Guardians tab and the Guardian fit step are unchanged.

## 7. Not here

* No write to the policy file. Detector settings are proposals with a ready block.
* No model call, no judge. A proposal never blocks or pauses anything; the gate rules do.
* No automatic attach, no schedule. The pre-deploy test is run by a person.
