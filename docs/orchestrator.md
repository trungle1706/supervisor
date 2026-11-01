# Onboarding orchestrator (WP-F4)

> **Not legal advice. Bank counsel must confirm.**

Flag `ONBOARD_ORCHESTRATOR=1` (default `0`; needs `GOVERNANCE_ENABLED`, `RISK_DIMENSIONS` and `CLASSIFICATION_V2`; `ONBOARD_FACTS` adds facts v1; the panel also needs `CONSOLE_SYSTEMS_ENABLED`; Windows cmd: `set ONBOARD_ORCHESTRATOR=1`).

Demo setting `ASSESS_PENDING_CLASS=1` (default `0`): the plan takes the newest *saved* classification while its second-person approval waits, so a demo can run the assessment right after step 4. The smart guardian reads the same outcome. The approval itself is unchanged: it stays on the system page. Leave it off in production.

Demo setting `ORCH_DEMO_PACE_MS` (default `0`, max `5000`): a pause before each applicable risk type, so the live progress bar of the panel can be seen; the rule runner answers in milliseconds. The pause counts against the time budget of the run. Leave it at `0` in production.

Real-model settings (W1, v0.11.2):

| Setting | Default | What it does |
|---|---|---|
| `ORCH_RUN_DRAFT_AGENTS` | `0` | Demo only. A risk type with no `live` agent uses the newest **draft** version of the factory agent for that type (needs `AGENT_FACTORY_GATE`). The plan item and the run item carry `agent_kind` = `rule`, `live` or `draft`, and the agent version ends in `-draft`; the console shows "Draft agent, not tested". Off: only live agents run, every other type keeps the rule proposal. |
| `ORCH_AGENT_SECONDS` | `120` (10..3600) | Time limit of one live or draft agent. The rule runner keeps 30 s. |
| `ORCH_TOTAL_SECONDS` | `900` (30..14400) | Time limit of the whole run. |

A call to the AI model that fails (HTTP error, time limit, bad reply) does not stop the run. The items of that call get the verdict `question` and the rationale "The AI model call failed (HTTP 400). A person decides this item."; the run item note says how many calls failed and why (`model_error`, at most 120 characters, no key and no request text). The report keeps its schema. The route `POST /v1/systems/{id}/orchestrate` uses the same factory catalogue as the console, and the runner gets the process `settings`, so the model works from a job or the CLI too.

Executive findings (`ORCH_EXEC_FINDINGS=1`, default `0`; the summary page needs `CONSOLE_UX5`): a list of checks such as "Required test pii_canary has not been run yet." says little to a manager. With the setting on, the run stores `<type>.exec.json` (`executive_v1`, in `DATA_DIR/assessments/<system>/<attempt>/`) next to each report: a rating (`high`, `medium`, `low`, `clear`, `open`), a one-sentence bottom line and up to six findings, each with a key, a status (`fail`, `open`), a severity, a headline, why it matters, the next step and the role that acts (English and Vietnamese). Layer A is deterministic and has no network: it combines the findings of the report with facts of the code scan (`facts_v1`) and the system record, in `onboard/executive.py`. Keys: `money_tool_no_gate`, `declared_control_mismatch`, `personal_data_fields`, `personal_data_mismatch`, `pii_export_tool`, `model_unknown`, `no_tracing`, `hardcoded_secret`, `external_endpoint`, `risk_level_mismatch`, `tests_missing`, `tests_failed` (plus `depends_open`, `depends_failed`, `person_decides` for the types that read other types or are decided by a person). The text cites file:line and field names only, never a value. A test that was not run is an open point ("no evidence either way"), never a claim about the code; open points of this kind do not raise the rating. A finding of a factory agent uses the optional `executive` block of its checklist item. The summary starts with **Bottom line** (the top three findings over all types, once each) and shows **Key findings** per type; the raw findings stay in **All checks**. The table column **Result** shows the top headline of each type. For a run made before the setting was on, the page builds the text from the stored report and stores nothing.

`ORCH_EXEC_LLM=1` (default `0`; needs `ORCH_EXEC_FINDINGS` and `LLM_BASE_URL`) adds Layer B: one structured call per risk type, through the same gateway model as the agents, rewords headline, impact and bottom line (30 s limit). A reworded line is kept only if it keeps the key and adds no number, quoted id, name, file or absolute claim ("illegal", "breach", ...) that Layer A did not have; otherwise the Layer A text stays. Status, severity, owner, next step and rating never change. The page shows who wrote the text: "Written by rules", "AI-written (<model>)" or "mock". A failure leaves the Layer A text. Both settings off: nothing is written and the summary is as before.

Progress and brief report (console, `CONSOLE_UX5`): while a run is queued or running, the panel polls every 2 s and shows one bar segment per applicable risk type (waits, runs, done, needs a person or error), the type that runs now and the seconds since the start. The first poll after the end reloads the rows of the table once. **View brief report** loads `GET /console/systems/{id}/orchestrate/{run_id}/brief` in place (a full page without `HX-Request`; `?dim=<type>` opens that type). The brief sums the stored `assessment_report_v1` files: totals of pass / fail / open, the failed checks, and per type the verdict, the agent, the time and the findings with their evidence. It reads only.

The orchestrator is deterministic and has **no model call of its own**. For one AI system it plans the eight risk types of Circular 53 Art. 14(3), runs the assessment of each under a budget, writes a report per type and a *proposal* into the status rows (WP-C2). It never writes `pass`: a person confirms with the existing Confirm action.

```
approved classification ──► plan ──► run (queued → running → done | failed)
facts v1, system record          │         │
                                 │         ├─ per type, in order: runner → assessment_report_v1
                                 │         │    budget cut → budget_exceeded
                                 │         │    high fail / approval point → needs_person
                                 │         ├─ report JSON + SHA-256 under DATA_DIR/assessments/<system>/<attempt>/
                                 │         ├─ risk_dimension_status: in_progress | fail (never pass)
                                 │         └─ onboard_log rows, chain record orchestrator_run
                                 └─ duties_prefill.json
```

## Plan rules

`plan(system, classification_outcome, ai_type_flags, facts_v1) -> Plan`. The outcome is the newest *approved* record of WP-C1. Order of the run: `model`, `data_governance`, `cybersecurity`, `ethics`, `third_party`, `supply_chain`, `reputation`, **`legal_compliance` last** (it reads the other reports).

| Outcome | Types that apply | Types `not_applicable` (reason code) |
|---|---|---|
| none approved, unknown | none, the run is refused: 400 `plan_blocked` | `classification_required` |
| `prohibited`, `not_system` | none, 400 `plan_blocked` | `prohibited`, `not_system` |
| `high_certify`, `high_self` | all eight | `reputation` for a non-bank: `bank_only` |
| `medium` | `model`, `data_governance`, `cybersecurity`, `legal_compliance`; `ethics` with a customer decision or personal data; `third_party` and `supply_chain` when flags or facts show a signal, or when unknown; `reputation` for a bank when the user segment is `customer` | `no_customer_decision_no_personal_data`, `no_third_party_signal`, `no_dependency_signal`, `medium_customer_facing_only`, `bank_only` |
| `low` | the four core types; `ethics` with a customer decision or personal data | `low_core_only`, the same ethics reason |

Signals. `customer_decision`: flag, else `credit_decision` or `system_type = decision` of the record. `personal_data`: flag, else the record is not `none`. `third_party`: flag `third_party_model`, else a fact of kind `model`, `endpoint`, `external_url` or `mcp_server`. `supply_chain`: flag `dependencies`, else a fact of kind `tool`, `mcp_server`, `model`, `external_url` or `dataset`. **An unknown signal (no flag, no facts) means the type applies** (`unknown_assume_applies`): an unknown is never a reason to skip. The institution is `bank` unless the setting `institution_type` says otherwise (the setting does not exist yet; the default is `bank`).

Agent per type: a `live` factory agent from the `AgentCatalog` (`agent_id@version`), else `rule`, the rule proposal of `risk_dimensions.propose`. Budget (integers, `factory/caps.py`): per agent 120 s and the agent's loop `budget_tokens` (default `LOOP_BUDGET_DEFAULT` = 60,000, at most `LOOP_BUDGET_MAX`); per rule item 30 s and 0 tokens; the run 900 s and 8 x `LOOP_BUDGET_DEFAULT` tokens. The plan hash is the SHA-256 of the canonical plan.

## Interfaces

```python
class AgentCatalog(Protocol):
    def live_agent(self, dimension_id: str) -> LiveAgent | None: ...   # WP-F2's store plugs in
@dataclass(frozen=True)
class LiveAgent: agent_id: str; version: str; definition: Mapping[str, Any]
class Runner(Protocol):
    def run(self, request: AgentRequest) -> dict[str, Any]: ...        # an assessment_report_v1 dict
```

`set_catalog(catalog)` plugs in the factory store (default `NullCatalog`). The default runner is `RoutingRunner`: a live agent goes to `supervisor.factory.runtime.run_agent(definition, inputs)` once WP-F3 provides it, everything else to `RuleRunner`. The rule runner makes one finding per mapped pack or monitor with the stored result as evidence (`ok` pass, `fail` fail, anything else a question when required and `not_applicable` when optional); a type with no mapped item (`legal_compliance`, `third_party`, `reputation`) gets one question for a person; `legal_compliance` also gets one finding per report it read. A report that does not validate as `assessment_report_v1` fails its item.

## Rules of a run

* **Budget.** A runner runs in a thread with the time limit; an overrun item is `budget_exceeded` (its result is dropped, no file, no status change). A live agent that reports more tokens than its budget is `budget_exceeded`. When the run budget is used up, the remaining items are `budget_exceeded`.
* **Stop points (hitl).** A `fail` on a `high` severity checklist item stops the type: item status `needs_person`, `stop_point` names the item. For the rule runner a required pack is `high`, an optional one `low`; for a live agent the severity comes from its checklist, and `harness.hitl.approval_points` (verdict or checklist) stop the type too. Other types go on.
* **Conflict rule.** The worst verdict wins across the findings (`fail`, `question`, `pass`, `not_applicable`). A `fail` needs a person (`needs_person: true`).
* **Status rows.** Written: `fail` (verdict fail or stop point) or `in_progress` (everything else), with `assessed_by` (`rule` or `agent@version`), `report_ref`, evidence pointers (`report:<id>` and the pack pointers) and a chain record `risk_dimension_status` from `rule:orchestrator`. `pass` is only in the item as `proposed_status`; a person confirms it with Confirm or Set on the tab. A `waived` row is left alone. A type that is not applicable by rule gets `not_applicable` with the reason as note (rows already `pass`, `fail`, `waived` are not touched).
* **One run at a time per system.** A second start answers 400 `run_in_progress`. A row left `queued` or `running` by a restart becomes `failed` at the next start. A re-run is a new attempt number.

## Files

`DATA_DIR/assessments/<system>/<attempt>/<dimension>.json` (the report; its SHA-256 is in the item) and `duties_prefill.json`:

```json
{"version": 1, "system_id": "...", "attempt_n": 1, "run_id": "orc_...", "plan_hash": "...",
 "covered": [{"dimension_id": "model", "articles": ["..."], "controls": ["..."],
              "report_ref": "orc_...-model", "report_sha256": "...", "confirmed": false}],
 "open": [{"dimension_id": "ethics", "why": "question"}]}
```

`covered` lists the types whose report verdict is `pass` (no stop point). `read_duties_prefill(settings, system_id, state=None)` returns the newest file; with `state`, `confirmed` is true when the status row is now `pass`. The Duties step UI is unchanged; WP-C3 wires the reader.

## API and console

| Route | Permission | Answer |
|---|---|---|
| `POST /v1/systems/{id}/orchestrate` | `systems.edit` | 202 with the run row; 400 `run_in_progress`, `plan_blocked`, `orchestrator_off` |
| `GET /v1/systems/{id}/orchestrate` | `systems.view` | newest run with items (404 when none) |
| `GET /v1/orchestrate/{run_id}` | `systems.view` | one run |
| `GET /v1/orchestrate/{run_id}/reports/{dim}` | `systems.view` | the stored report JSON |
| `GET`/`POST /console/systems/{id}/orchestrate` | view / edit | the run panel (HTMX fragment; polls every 2 s while running) |

The **Run assessment** button and the run panel are at the top of the Risk assessment tab (plan outcome and hash, budget used, a row per type with agent, status, verdict, stop point and a link to the report JSON). With the flag on the disabled "Request re-assessment" placeholder of WP-C2 is gone; with the flag off the tab is unchanged. Every POST writes two `console_action` rows. `onboard_log` rows (step `orchestrate`, by `rule`) are written for the plan, each type start and end, and the summary (they need `ONBOARD_POSTDEPLOY` or this flag). Chain record `orchestrator_run`: run id, system id, attempt, plan hash, status and integer counts; no names, no floats.

Table `orchestrator_run` (appended at the end of `schema/model.yaml`): `run_id`, `system_id`, `attempt_n`, `plan_json`, `plan_hash`, `status`, `started_at`, `finished_at`, `budget_json`, `items_json`, `summary` (at most 300 characters), `created_by`.
