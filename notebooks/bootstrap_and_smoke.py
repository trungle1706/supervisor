# Databricks notebook source
# MAGIC %md
# MAGIC # Supervisor: bootstrap and smoke test (WP10 live test kit)
# MAGIC
# MAGIC What it does, in your own schema, as you (your Unity Catalog permissions):
# MAGIC 1. creates every Supervisor table (DDL generated from `schema/model.yaml`) with the prefix `PREFIX`;
# MAGIC 2. inserts synthetic rows (no real data);
# MAGIC 3. checks: insert-only MERGE on a `delta.appendOnly` table, UPDATE/DELETE rejected,
# MAGIC    TIMESTAMP with microseconds, ADD COLUMNS migration, retention properties;
# MAGIC 4. prints a results table and one `SUPERVISOR-EXIT-JSON:` line.
# MAGIC
# MAGIC How to run: attach to the shared cluster or a SQL-capable cluster, edit the next cell
# MAGIC (replace every FILL-ME value), then Run all. Copy the results table into your reply.
# MAGIC To run from the laptop instead: `uv run python -m supervisor.jobs.cluster_run notebooks\bootstrap_and_smoke.py --param CATALOG=... --param SCHEMA=...`

# COMMAND ----------

# SUPERVISOR-PARAMS (edit inline; cluster_run --param NAME=VALUE overrides these)
CATALOG = "FILL-ME-catalog"
SCHEMA = "FILL-ME-schema"
PREFIX = "smoke_"  # "" creates the real Supervisor tables (then set INSERT_SYNTHETIC = False)
RETENTION_DAYS = 1825
INSERT_SYNTHETIC = True
DROP_AFTER = False  # True drops every PREFIX table at the end
APP_PRINCIPAL = "FILL-ME-app-service-principal-application-id"  # optional table grants

# COMMAND ----------

# ruff: noqa: F821, T201, E501, S608, E402, UP017, S110
# GENERATED DDL BEGIN (uv run python -m supervisor.databricks.notebook; do not edit)
DDL = [
    "-- schema_version (state): Applied versions of this model.\n-- primary key (enforced by the app, not by Delta): version\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`schema_version` (\n  version BIGINT NOT NULL,\n  applied_at TIMESTAMP NOT NULL,\n  model_hash STRING NOT NULL,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Applied versions of this model.'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- agent (state): Registry of supervised agents (one row per agent).\n-- primary key (enforced by the app, not by Delta): agent_id\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`agent` (\n  agent_id STRING NOT NULL,\n  name STRING NOT NULL,\n  owner_team STRING NOT NULL,\n  owner_user STRING NOT NULL,\n  business_owner STRING,\n  risk_tier STRING NOT NULL,\n  decision33_class STRING,\n  host_type STRING NOT NULL,\n  plug_point STRING NOT NULL,\n  model_family STRING NOT NULL,\n  status STRING NOT NULL,\n  gate_state STRING NOT NULL,\n  created_at TIMESTAMP NOT NULL,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Registry of supervised agents (one row per agent).'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- agent_version (append_only): Deployed versions of an agent. Drift bands tie to a version.\n-- primary key (enforced by the app, not by Delta): agent_id, version\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`agent_version` (\n  agent_id STRING NOT NULL,\n  version STRING NOT NULL,\n  code_ref STRING,\n  prompt_hash STRING,\n  tool_manifest_hash STRING,\n  model_endpoint STRING,\n  model_family STRING NOT NULL,\n  deployed_at TIMESTAMP NOT NULL,\n  baseline_id STRING\n)\nUSING DELTA\nCOMMENT 'Deployed versions of an agent. Drift bands tie to a version.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only')",
    "-- identity_binding (state): How a black-box agent is recognised (header, SP, key hash).\n-- primary key (enforced by the app, not by Delta): agent_id, binding_type, binding_hash\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`identity_binding` (\n  agent_id STRING NOT NULL,\n  binding_type STRING NOT NULL,\n  binding_hash STRING NOT NULL,\n  valid_from TIMESTAMP NOT NULL,\n  valid_to TIMESTAMP,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'How a black-box agent is recognised (header, SP, key hash).'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- coverage (state): Which monitoring capabilities are on for each agent, and why not.\n-- primary key (enforced by the app, not by Delta): agent_id, capability_id\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`coverage` (\n  agent_id STRING NOT NULL,\n  capability_id STRING NOT NULL,\n  status STRING NOT NULL,\n  reason STRING,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Which monitoring capabilities are on for each agent, and why not.'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- agent_event (append_only): Normalised OTel-shaped events. Single read model for Watch. Masked only.\n-- primary key (enforced by the app, not by Delta): event_id\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`agent_event` (\n  event_id STRING NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  trace_id STRING NOT NULL,\n  span_id STRING NOT NULL,\n  parent_span_id STRING,\n  agent_id STRING NOT NULL,\n  agent_version STRING,\n  caller_agent_id STRING,\n  event_type STRING NOT NULL,\n  tool_name STRING,\n  args_hash STRING,\n  args_masked STRING,\n  result_masked STRING,\n  amount_minor BIGINT,\n  currency STRING,\n  status STRING,\n  latency_ms BIGINT,\n  env STRING NOT NULL,\n  classification STRING,\n  source STRING NOT NULL,\n  capture_level STRING NOT NULL,\n  mask_version STRING\n)\nUSING DELTA\nCOMMENT 'Normalised OTel-shaped events. Single read model for Watch. Masked only.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only')",
    "-- agent_event_raw (append_only): RESTRICTED. Unmasked args/result text for agents whose manifest allows capture level raw (capture.raw_allowed). Restricted group only, short TTL (raw 90 d). Never read by judges or the chain. Rows link to agent_event by event_id.\n-- primary key (enforced by the app, not by Delta): event_id\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`agent_event_raw` (\n  event_id STRING NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  trace_id STRING NOT NULL,\n  agent_id STRING NOT NULL,\n  args_raw STRING,\n  result_raw STRING,\n  access_class STRING NOT NULL\n)\nUSING DELTA\nCOMMENT 'RESTRICTED. Unmasked args/result text for agents whose manifest allows capture level raw (capture.raw_allowed). Restricted group only, short TTL (raw 90 d). Never read by judges or the chain. Rows link to agent_event by event_id.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only')",
    "-- trace_coverage (append_only): What each trace input path can see per agent (WP4). A proxy-log agent gets capability reduced with the list of missing fields. One row per agent, source and capability.\n-- primary key (enforced by the app, not by Delta): coverage_id\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`trace_coverage` (\n  coverage_id STRING NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  agent_id STRING NOT NULL,\n  source STRING NOT NULL,\n  capability STRING NOT NULL,\n  missing STRING NOT NULL,\n  note STRING\n)\nUSING DELTA\nCOMMENT 'What each trace input path can see per agent (WP4). A proxy-log agent gets capability reduced with the list of missing fields. One row per agent, source and capability.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only')",
    "-- rule (state): Deployed copy of policy rules (git is the source).\n-- primary key (enforced by the app, not by Delta): rule_id, version\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`rule` (\n  rule_id STRING NOT NULL,\n  version BIGINT NOT NULL,\n  agent_scope STRING NOT NULL,\n  expression STRING NOT NULL,\n  action STRING NOT NULL,\n  fail_mode STRING NOT NULL,\n  severity STRING NOT NULL,\n  regulation_ref STRING,\n  owner STRING NOT NULL,\n  approved_by_1 STRING,\n  approved_by_2 STRING,\n  git_sha STRING,\n  policy_hash STRING NOT NULL,\n  effective_from TIMESTAMP NOT NULL,\n  effective_to TIMESTAMP,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Deployed copy of policy rules (git is the source).'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- verdict (append_only): One row per check outcome (rule, Tier 1 or Tier 2 judge). Judges are advisory.\n-- primary key (enforced by the app, not by Delta): verdict_id\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`verdict` (\n  verdict_id STRING NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  trace_id STRING,\n  event_id STRING,\n  agent_id STRING NOT NULL,\n  tier BIGINT NOT NULL,\n  checker_id STRING NOT NULL,\n  model_id STRING,\n  model_family STRING,\n  is_mock BOOLEAN NOT NULL,\n  advisory BOOLEAN NOT NULL,\n  score DOUBLE,\n  label STRING NOT NULL,\n  action STRING NOT NULL,\n  latency_ms BIGINT,\n  rule_id STRING,\n  policy_hash STRING,\n  rationale_masked STRING,\n  score_bp BIGINT,\n  role STRING,\n  region STRING,\n  model_version STRING,\n  mask_version STRING,\n  prompt_hash STRING,\n  rubric_version STRING\n)\nUSING DELTA\nCOMMENT 'One row per check outcome (rule, Tier 1 or Tier 2 judge). Judges are advisory.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only')",
    "-- cases (state): Case header (mutable workflow state). Every change also writes case_event.\n-- primary key (enforced by the app, not by Delta): case_id\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`cases` (\n  case_id STRING NOT NULL,\n  agent_id STRING NOT NULL,\n  severity STRING NOT NULL,\n  status STRING NOT NULL,\n  opened_at TIMESTAMP NOT NULL,\n  assignee STRING,\n  itsm_ref STRING,\n  regulation_refs STRING NOT NULL,\n  summary STRING NOT NULL,\n  report_due_at TIMESTAMP,\n  closed_at TIMESTAMP,\n  case_type STRING,\n  incident_detected_at TIMESTAMP,\n  urgency_class STRING,\n  prelim_report_due_at TIMESTAMP,\n  formal_report_due_at TIMESTAMP,\n  prelim_report_sent_at TIMESTAMP,\n  formal_report_sent_at TIMESTAMP,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Case header (mutable workflow state). Every change also writes case_event.'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- case_event (append_only): Who did what on a case. Feeds the evidence chain.\n-- primary key (enforced by the app, not by Delta): case_id, seq\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`case_event` (\n  case_id STRING NOT NULL,\n  seq BIGINT NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  actor STRING NOT NULL,\n  actor_kind STRING NOT NULL,\n  action STRING NOT NULL,\n  comment_masked STRING,\n  auth_method STRING\n)\nUSING DELTA\nCOMMENT 'Who did what on a case. Feeds the evidence chain.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only')",
    "-- case_link (append_only): WP8. Which source opened or joined a case: a gate decision (block/pause), a judge verdict (CaseRequest) or a monitor finding. One row per source; makes intake idempotent.\n-- primary key (enforced by the app, not by Delta): source_kind, source_ref\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`case_link` (\n  source_kind STRING NOT NULL,\n  source_ref STRING NOT NULL,\n  case_id STRING NOT NULL,\n  agent_id STRING NOT NULL,\n  ts TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'WP8. Which source opened or joined a case: a gate decision (block/pause), a judge verdict (CaseRequest) or a monitor finding. One row per source; makes intake idempotent.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only')",
    "-- signoff (append_only): Human sign-off. Reviewer id from SSO, never the app service principal.\n-- primary key (enforced by the app, not by Delta): signoff_id\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`signoff` (\n  signoff_id STRING NOT NULL,\n  case_id STRING NOT NULL,\n  reviewer_id STRING NOT NULL,\n  decision STRING NOT NULL,\n  reason STRING NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  auth_method STRING NOT NULL\n)\nUSING DELTA\nCOMMENT 'Human sign-off. Reviewer id from SSO, never the app service principal.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only')",
    "-- chain_entry (append_only): Hash chain. One lane per agent plus the root lane. PII never enters.\n-- primary key (enforced by the app, not by Delta): lane, seq\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`chain_entry` (\n  lane STRING NOT NULL,\n  seq BIGINT NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  record_type STRING NOT NULL,\n  record_ref STRING NOT NULL,\n  payload_hash STRING NOT NULL,\n  prev_hash STRING NOT NULL,\n  entry_hash STRING NOT NULL,\n  writer STRING NOT NULL,\n  env STRING NOT NULL\n)\nUSING DELTA\nCOMMENT 'Hash chain. One lane per agent plus the root lane. PII never enters.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only')",
    "-- chain_payload (append_only): Masked canonical JSON payload of a chain entry (no floats, no raw PII).\n-- primary key (enforced by the app, not by Delta): lane, seq, payload_hash\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`chain_payload` (\n  lane STRING NOT NULL,\n  seq BIGINT NOT NULL,\n  payload_hash STRING NOT NULL,\n  payload STRING NOT NULL\n)\nUSING DELTA\nCOMMENT 'Masked canonical JSON payload of a chain entry (no floats, no raw PII).'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only')",
    "-- chain_signature (append_only): Signature over the entry_hash of a root-lane entry (signed head).\n-- primary key (enforced by the app, not by Delta): lane, seq, entry_hash\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`chain_signature` (\n  lane STRING NOT NULL,\n  seq BIGINT NOT NULL,\n  entry_hash STRING NOT NULL,\n  signature STRING NOT NULL,\n  key_id STRING NOT NULL,\n  algorithm STRING NOT NULL,\n  key_kind STRING NOT NULL,\n  public_key STRING NOT NULL\n)\nUSING DELTA\nCOMMENT 'Signature over the entry_hash of a root-lane entry (signed head).'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only')",
    "-- anchor (append_only): Signed chain heads anchored to an immutable target.\n-- primary key (enforced by the app, not by Delta): anchor_id\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`anchor` (\n  anchor_id STRING NOT NULL,\n  lane STRING NOT NULL,\n  seq_from BIGINT NOT NULL,\n  seq_to BIGINT NOT NULL,\n  root_hash STRING NOT NULL,\n  head_signature STRING NOT NULL,\n  key_id STRING NOT NULL,\n  anchored_at TIMESTAMP NOT NULL,\n  anchor_target STRING NOT NULL,\n  receipt STRING\n)\nUSING DELTA\nCOMMENT 'Signed chain heads anchored to an immutable target.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only')",
    "-- oversight_metric (state): Daily oversight metrics per agent. Feeds the console panel.\n-- primary key (enforced by the app, not by Delta): metric_date, agent_id\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`oversight_metric` (\n  metric_date DATE NOT NULL,\n  agent_id STRING NOT NULL,\n  coverage DOUBLE,\n  ttd_ms BIGINT,\n  tth_s BIGINT,\n  catch_rate DOUBLE,\n  false_alarm_rate DOUBLE,\n  chain_ok BOOLEAN,\n  groundedness DOUBLE,\n  fairness_gap DOUBLE,\n  computed_at TIMESTAMP NOT NULL,\n  events_seen BIGINT,\n  events_gated BIGINT,\n  coverage_bp BIGINT,\n  catch_rate_bp BIGINT,\n  false_alarm_bp BIGINT,\n  judge_verdicts BIGINT,\n  judge_disagree_bp BIGINT,\n  groundedness_bp BIGINT,\n  fairness_gap_bp BIGINT,\n  cases_opened BIGINT,\n  blocks BIGINT,\n  llm_calls BIGINT,\n  judge_latency_ms BIGINT,\n  judge_human_pairs BIGINT,\n  judge_human_agree_bp BIGINT,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Daily oversight metrics per agent. Feeds the console panel.'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- model_validation (append_only): WP19. One row per judge validation run (python -m supervisor.judge.mrm validate). The judge service checks it when JUDGE_REQUIRE_VALIDATION is on. Integers only.\n-- primary key (enforced by the app, not by Delta): validation_id\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`model_validation` (\n  validation_id STRING NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  judge_id STRING NOT NULL,\n  model_version STRING NOT NULL,\n  prompt_hash STRING NOT NULL,\n  rubric_version STRING NOT NULL,\n  mask_version STRING NOT NULL,\n  golden_set_hash STRING NOT NULL,\n  is_mock BOOLEAN NOT NULL,\n  decision STRING NOT NULL,\n  passed BOOLEAN NOT NULL,\n  runs BIGINT NOT NULL,\n  metrics STRING NOT NULL,\n  thresholds STRING NOT NULL,\n  failed_checks STRING NOT NULL,\n  validator STRING NOT NULL,\n  report_hash STRING NOT NULL\n)\nUSING DELTA\nCOMMENT 'WP19. One row per judge validation run (python -m supervisor.judge.mrm validate). The judge service checks it when JUDGE_REQUIRE_VALIDATION is on. Integers only.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only')",
    "-- policy_baseline (state): Drift baseline band per agent version and metric (WP7, ADR D09). Integers only: band = center +- k * scaled MAD. Also holds the breach streak of the drift monitor.\n-- primary key (enforced by the app, not by Delta): agent_id, agent_version, metric\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`policy_baseline` (\n  agent_id STRING NOT NULL,\n  agent_version STRING NOT NULL,\n  metric STRING NOT NULL,\n  baseline_id STRING NOT NULL,\n  center BIGINT NOT NULL,\n  mad BIGINT NOT NULL,\n  band_low BIGINT NOT NULL,\n  band_high BIGINT NOT NULL,\n  k BIGINT NOT NULL,\n  windows BIGINT NOT NULL,\n  window_s BIGINT NOT NULL,\n  window_from TIMESTAMP NOT NULL,\n  window_to TIMESTAMP NOT NULL,\n  breach_streak BIGINT NOT NULL,\n  last_value BIGINT,\n  last_checked_to TIMESTAMP,\n  open_case_id STRING,\n  computed_at TIMESTAMP NOT NULL,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Drift baseline band per agent version and metric (WP7, ADR D09). Integers only: band = center +- k * scaled MAD. Also holds the breach streak of the drift monitor.'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- policy_threshold (state): Monitor thresholds per agent and metric (WP7). agent_id '*' is the default for every agent. Example metrics: drift.k, drift.consecutive, fairness.approval_gap_bp.\n-- primary key (enforced by the app, not by Delta): agent_id, metric\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`policy_threshold` (\n  agent_id STRING NOT NULL,\n  metric STRING NOT NULL,\n  threshold BIGINT NOT NULL,\n  unit STRING NOT NULL,\n  owner STRING,\n  note STRING,\n  effective_from TIMESTAMP NOT NULL,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Monitor thresholds per agent and metric (WP7). agent_id ''*'' is the default for every agent. Example metrics: drift.k, drift.consecutive, fairness.approval_gap_bp.'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- fairness_slice (append_only): One row per fairness cell per run (WP7). Cells under the minimum n are suppressed: counts and rates are null. Built on hashed subject ids, never raw ids.\n-- primary key (enforced by the app, not by Delta): run_id, attribute, cell\n-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`fairness_slice` (\n  run_id STRING NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  agent_id STRING NOT NULL,\n  window_from TIMESTAMP NOT NULL,\n  window_to TIMESTAMP NOT NULL,\n  attribute STRING NOT NULL,\n  cell STRING NOT NULL,\n  n BIGINT,\n  approvals BIGINT,\n  blocks BIGINT,\n  approval_rate_bp BIGINT,\n  block_rate_bp BIGINT,\n  suppressed BOOLEAN NOT NULL,\n  method STRING NOT NULL\n)\nUSING DELTA\nCOMMENT 'One row per fairness cell per run (WP7). Cells under the minimum n are suppressed: counts and rates are null. Built on hashed subject ids, never raw ids.'\nTBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only')",
    "-- monitor_state (state): Cursors and dedupe marks of the monitors and the scheduler (WP7).\n-- primary key (enforced by the app, not by Delta): monitor, state_key\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`monitor_state` (\n  monitor STRING NOT NULL,\n  state_key STRING NOT NULL,\n  value STRING NOT NULL,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Cursors and dedupe marks of the monitors and the scheduler (WP7).'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- scheduler_lease (state): Single-instance lock of the in-process scheduler on Databricks (WP7). One row per lease; the holder renews it; another replica takes it only after expires_at.\n-- primary key (enforced by the app, not by Delta): lease_name\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`scheduler_lease` (\n  lease_name STRING NOT NULL,\n  holder STRING NOT NULL,\n  acquired_at TIMESTAMP NOT NULL,\n  expires_at TIMESTAMP NOT NULL,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Single-instance lock of the in-process scheduler on Databricks (WP7). One row per lease; the holder renews it; another replica takes it only after expires_at.'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- gate_control (state): Gateway control records (WP3). Active pause (with the state to resume to) and pending two-person resume approvals.\n-- primary key (enforced by the app, not by Delta): control_id\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gate_control` (\n  control_id STRING NOT NULL,\n  agent_id STRING NOT NULL,\n  action STRING NOT NULL,\n  principal STRING NOT NULL,\n  role STRING,\n  reason STRING,\n  resume_to STRING,\n  status STRING NOT NULL,\n  created_at TIMESTAMP NOT NULL,\n  expires_at TIMESTAMP,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'Gateway control records (WP3). Active pause (with the state to resume to) and pending two-person resume approvals.'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
    "-- notice (state): WP8. Notifier inbox (console Inbox page). Masked text only. The webhook stub queues rows with status queued and never sends them (off by default).\n-- primary key (enforced by the app, not by Delta): notice_id\nCREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`notice` (\n  notice_id STRING NOT NULL,\n  ts TIMESTAMP NOT NULL,\n  channel STRING NOT NULL,\n  subject STRING NOT NULL,\n  body STRING NOT NULL,\n  status STRING NOT NULL,\n  read_by STRING,\n  row_version BIGINT NOT NULL,\n  updated_at TIMESTAMP NOT NULL\n)\nUSING DELTA\nCOMMENT 'WP8. Notifier inbox (console Inbox page). Masked text only. The webhook stub queues rows with status queued and never sends them (off by default).'\nTBLPROPERTIES ('supervisor.kind' = 'state')",
]
# GENERATED DDL END

# COMMAND ----------

import json
import re
from datetime import datetime, timezone

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"check": name, "status": "OK" if ok else "FAIL", "detail": str(detail)[:300]})
    print(("[OK] " if ok else "[FAIL] ") + name + (": " + str(detail)[:300] if detail else ""))


for label, value in (("CATALOG", CATALOG), ("SCHEMA", SCHEMA), ("PREFIX", PREFIX)):
    if value.startswith("FILL-ME") or not re.fullmatch(r"[A-Za-z0-9_]*", value):
        raise ValueError(
            f"{label} must be a plain identifier, not {value!r}: edit the parameter cell"
        )


def fq(table):
    return f"`{CATALOG}`.`{SCHEMA}`.`{PREFIX}{table}`"


def ddl_for(stmt):
    return stmt.replace("`${catalog}`.`${schema}`.`", f"`{CATALOG}`.`{SCHEMA}`.`{PREFIX}").replace(
        "interval 1825 days", f"interval {int(RETENTION_DAYS)} days"
    )


TABLES = [re.search(r"`\$\{schema\}`\.`([a-z0-9_]+)`", s).group(1) for s in DDL]
print(f"workspace user: {spark.sql('SELECT current_user()').collect()[0][0]}")
print(f"target: {CATALOG}.{SCHEMA} prefix={PREFIX!r} tables={len(TABLES)}")

# COMMAND ----------

# 1. Create every table (idempotent).
created = 0
for stmt in DDL:
    try:
        spark.sql(ddl_for(stmt))
        created += 1
    except Exception as exc:
        name = re.search(r"`\$\{schema\}`\.`([a-z0-9_]+)`", stmt).group(1)
        check("create " + name, False, f"{type(exc).__name__}: {exc}")
check("create tables", created == len(DDL), f"{created}/{len(DDL)} statements")

# COMMAND ----------

# 2. Synthetic rows: agent (state table) and agent_event (append-only, evidence).
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
if INSERT_SYNTHETIC:
    try:
        spark.sql(
            f"MERGE INTO {fq('agent')} AS t USING (SELECT 'smoke-agent' AS agent_id) AS s "
            "ON t.agent_id = s.agent_id WHEN NOT MATCHED THEN INSERT (agent_id, name, owner_team, "
            "owner_user, risk_tier, host_type, plug_point, model_family, status, gate_state, "
            "created_at, row_version, updated_at) VALUES ('smoke-agent', 'Tro ly thanh toan (smoke)', "
            "'retail', 'owner@example.invalid', 'high', 'databricks_app', 'supervised_tool', 'qwen', "
            f"'active', 'RUNNING', TIMESTAMP'{now}', 1, TIMESTAMP'{now}')"
        )
        n = spark.sql(
            f"SELECT count(*) FROM {fq('agent')} WHERE agent_id = 'smoke-agent'"
        ).collect()[0][0]
        check("insert agent (state)", n == 1, f"rows={n}")
    except Exception as exc:
        check("insert agent (state)", False, f"{type(exc).__name__}: {exc}")

event_id = "smoke-" + now.replace(":", "").replace("-", "").replace(".", "")
merge_event = (
    f"MERGE INTO {fq('agent_event')} AS tgt USING (SELECT '{event_id}' AS event_id, "
    f"TIMESTAMP'{now}' AS ts, 't-smoke' AS trace_id, 's1' AS span_id, 'smoke-agent' AS agent_id, "
    "'tool_call' AS event_type, 'smoke' AS env, 'otel' AS source, 'digest' AS capture_level, "
    "CAST(9000000000000 AS BIGINT) AS amount_minor, 'VND' AS currency) AS src "
    "ON tgt.event_id = src.event_id WHEN NOT MATCHED THEN INSERT "
    "(event_id, ts, trace_id, span_id, agent_id, event_type, env, source, capture_level, amount_minor, currency) "
    "VALUES (src.event_id, src.ts, src.trace_id, src.span_id, src.agent_id, src.event_type, src.env, "
    "src.source, src.capture_level, src.amount_minor, src.currency)"
)

# COMMAND ----------

# 3. Insert-only MERGE on a delta.appendOnly table (the app uses it to de-duplicate appends).
try:
    first = spark.sql(merge_event).collect()[0].asDict()
    second = spark.sql(merge_event).collect()[0].asDict()
    check(
        "insert-only MERGE on appendOnly table",
        int(first.get("num_inserted_rows", -1)) == 1
        and int(second.get("num_inserted_rows", -1)) == 0,
        f"first={first} second={second}",
    )
except Exception as exc:
    check("insert-only MERGE on appendOnly table", False, f"{type(exc).__name__}: {exc}")

# COMMAND ----------

# 4. UPDATE and DELETE must be rejected on append-only tables.
for op, sql in (
    ("UPDATE", f"UPDATE {fq('agent_event')} SET env = 'x' WHERE event_id = '{event_id}'"),
    ("DELETE", f"DELETE FROM {fq('agent_event')} WHERE event_id = '{event_id}'"),
):
    try:
        spark.sql(sql).collect()
        check(f"{op} rejected on appendOnly table", False, "statement succeeded (it must fail)")
    except Exception as exc:
        msg = str(exc)
        check(
            f"{op} rejected on appendOnly table", "append" in msg.lower(), msg.splitlines()[0][:200]
        )

# COMMAND ----------

# 5. TIMESTAMP with microseconds and Z (the format the app sends as a parameter).
try:
    ts_text = "2026-10-14T05:00:00.123456Z"
    row = spark.sql(
        f"SELECT CAST('{ts_text}' AS TIMESTAMP) AS t, date_format(CAST('{ts_text}' AS TIMESTAMP), 'SSSSSS') AS us"
    ).collect()[0]
    check(
        "TIMESTAMP ...ffffffZ keeps microseconds",
        row["us"] == "123456",
        f"value={row['t']} session_tz={spark.conf.get('spark.sql.session.timeZone')}",
    )
except Exception as exc:
    check("TIMESTAMP ...ffffffZ keeps microseconds", False, f"{type(exc).__name__}: {exc}")

# COMMAND ----------

# 6. Migration: ALTER TABLE ADD COLUMNS on an append-only table with rows.
probe = fq("migration_probe")
try:
    spark.sql(f"DROP TABLE IF EXISTS {probe}")
    spark.sql(
        f"CREATE TABLE {probe} (id BIGINT NOT NULL) USING DELTA TBLPROPERTIES ('delta.appendOnly' = 'true')"
    )
    spark.sql(f"INSERT INTO {probe} VALUES (1)")
    spark.sql(f"ALTER TABLE {probe} ADD COLUMNS (note STRING, at TIMESTAMP)")
    cols = [r["col_name"] for r in spark.sql(f"DESCRIBE TABLE {probe}").collect()]
    check(
        "ALTER TABLE ADD COLUMNS on appendOnly table",
        {"note", "at"} <= set(cols),
        f"columns={cols[:5]}",
    )
    spark.sql(
        f"ALTER TABLE {probe} SET TBLPROPERTIES ('delta.logRetentionDuration' = 'interval {int(RETENTION_DAYS)} days')"
    )
    check("ALTER TABLE SET TBLPROPERTIES on appendOnly table", True)
except Exception as exc:
    check("ALTER TABLE ADD COLUMNS / SET TBLPROPERTIES", False, f"{type(exc).__name__}: {exc}")
finally:
    spark.sql(f"DROP TABLE IF EXISTS {probe}")

# COMMAND ----------

# 7. Retention properties on an evidence table.
try:
    props = {
        r["key"]: r["value"] for r in spark.sql(f"SHOW TBLPROPERTIES {fq('agent_event')}").collect()
    }
    want = f"interval {int(RETENTION_DAYS)} days"
    check(
        "evidence retention TBLPROPERTIES",
        props.get("delta.logRetentionDuration") == want and props.get("delta.appendOnly") == "true",
        {
            k: v
            for k, v in props.items()
            if k.startswith(("delta.log", "delta.deleted", "delta.append"))
        },
    )
except Exception as exc:
    check("evidence retention TBLPROPERTIES", False, f"{type(exc).__name__}: {exc}")

# COMMAND ----------

# 8. Optional: let the App service principal read and write the tables (you own them).
if not APP_PRINCIPAL.startswith("FILL-ME"):
    granted = 0
    for t in TABLES:
        try:
            spark.sql(f"GRANT SELECT, MODIFY ON TABLE {fq(t)} TO `{APP_PRINCIPAL}`")
            granted += 1
        except Exception as exc:
            check(f"grant on {t}", False, f"{type(exc).__name__}: {exc}")
    check(
        "grants for the App service principal",
        granted == len(TABLES),
        f"{granted}/{len(TABLES)} tables",
    )
else:
    print("[SKIP] grants: APP_PRINCIPAL is FILL-ME")

# COMMAND ----------

# 9. Results. Copy this table (or the SUPERVISOR-EXIT-JSON line) into your reply.
if DROP_AFTER:
    for t in TABLES:
        spark.sql(f"DROP TABLE IF EXISTS {fq(t)}")
    print(f"dropped {len(TABLES)} tables with prefix {PREFIX!r}")
width = max(len(r["check"]) for r in RESULTS) if RESULTS else 10
print("-" * (width + 60))
for r in RESULTS:
    print(f"[{r['status']}] {r['check'].ljust(width)}  {r['detail'][:120]}")
print("-" * (width + 60))
failed = sum(1 for r in RESULTS if r["status"] != "OK")
print(f"{len(RESULTS)} checks, {failed} failed")
try:
    display(spark.createDataFrame(RESULTS))
except Exception:
    pass
import sys as _sys

# Print to the live sys.stdout (the command runner may replace it between cells).
print(
    "SUPERVISOR-EXIT-JSON: " + json.dumps({"checks": RESULTS, "failed": failed}, sort_keys=True),
    file=_sys.stdout,
    flush=True,
)
