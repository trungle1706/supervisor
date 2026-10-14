-- GENERATED from schema/model.yaml (version 1). Do not edit.
-- Regenerate: uv run python -m schema.generate
-- Dialect: databricks

-- schema_version (state): Applied versions of this model.
-- primary key (enforced by the app, not by Delta): version
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`schema_version` (
  version BIGINT NOT NULL,
  applied_at TIMESTAMP NOT NULL,
  model_hash STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Applied versions of this model.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- agent (state): Registry of supervised agents (one row per agent).
-- primary key (enforced by the app, not by Delta): agent_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`agent` (
  agent_id STRING NOT NULL,
  name STRING NOT NULL,
  owner_team STRING NOT NULL,
  owner_user STRING NOT NULL,
  business_owner STRING,
  risk_tier STRING NOT NULL,
  decision33_class STRING,
  host_type STRING NOT NULL,
  plug_point STRING NOT NULL,
  model_family STRING NOT NULL,
  status STRING NOT NULL,
  gate_state STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Registry of supervised agents (one row per agent).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- agent_version (append_only): Deployed versions of an agent. Drift bands tie to a version.
-- primary key (enforced by the app, not by Delta): agent_id, version
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`agent_version` (
  agent_id STRING NOT NULL,
  version STRING NOT NULL,
  code_ref STRING,
  prompt_hash STRING,
  tool_manifest_hash STRING,
  model_endpoint STRING,
  model_family STRING NOT NULL,
  deployed_at TIMESTAMP NOT NULL,
  baseline_id STRING
)
USING DELTA
COMMENT 'Deployed versions of an agent. Drift bands tie to a version.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

-- identity_binding (state): How a black-box agent is recognised (header, SP, key hash).
-- primary key (enforced by the app, not by Delta): agent_id, binding_type, binding_hash
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`identity_binding` (
  agent_id STRING NOT NULL,
  binding_type STRING NOT NULL,
  binding_hash STRING NOT NULL,
  valid_from TIMESTAMP NOT NULL,
  valid_to TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'How a black-box agent is recognised (header, SP, key hash).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- coverage (state): Which monitoring capabilities are on for each agent, and why not.
-- primary key (enforced by the app, not by Delta): agent_id, capability_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`coverage` (
  agent_id STRING NOT NULL,
  capability_id STRING NOT NULL,
  status STRING NOT NULL,
  reason STRING,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Which monitoring capabilities are on for each agent, and why not.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- agent_event (append_only): Normalised OTel-shaped events. Single read model for Watch. Masked only.
-- primary key (enforced by the app, not by Delta): event_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`agent_event` (
  event_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  trace_id STRING NOT NULL,
  span_id STRING NOT NULL,
  parent_span_id STRING,
  agent_id STRING NOT NULL,
  agent_version STRING,
  caller_agent_id STRING,
  event_type STRING NOT NULL,
  tool_name STRING,
  args_hash STRING,
  args_masked STRING,
  result_masked STRING,
  amount_minor BIGINT,
  currency STRING,
  status STRING,
  latency_ms BIGINT,
  env STRING NOT NULL,
  classification STRING,
  source STRING NOT NULL,
  capture_level STRING NOT NULL
)
USING DELTA
COMMENT 'Normalised OTel-shaped events. Single read model for Watch. Masked only.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- rule (state): Deployed copy of policy rules (git is the source).
-- primary key (enforced by the app, not by Delta): rule_id, version
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`rule` (
  rule_id STRING NOT NULL,
  version BIGINT NOT NULL,
  agent_scope STRING NOT NULL,
  expression STRING NOT NULL,
  action STRING NOT NULL,
  fail_mode STRING NOT NULL,
  severity STRING NOT NULL,
  regulation_ref STRING,
  owner STRING NOT NULL,
  approved_by_1 STRING,
  approved_by_2 STRING,
  git_sha STRING,
  policy_hash STRING NOT NULL,
  effective_from TIMESTAMP NOT NULL,
  effective_to TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Deployed copy of policy rules (git is the source).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- verdict (append_only): One row per check outcome (rule, Tier 1 or Tier 2 judge). Judges are advisory.
-- primary key (enforced by the app, not by Delta): verdict_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`verdict` (
  verdict_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  trace_id STRING,
  event_id STRING,
  agent_id STRING NOT NULL,
  tier BIGINT NOT NULL,
  checker_id STRING NOT NULL,
  model_id STRING,
  model_family STRING,
  is_mock BOOLEAN NOT NULL,
  advisory BOOLEAN NOT NULL,
  score DOUBLE,
  label STRING NOT NULL,
  action STRING NOT NULL,
  latency_ms BIGINT,
  rule_id STRING,
  policy_hash STRING,
  rationale_masked STRING
)
USING DELTA
COMMENT 'One row per check outcome (rule, Tier 1 or Tier 2 judge). Judges are advisory.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- cases (state): Case header (mutable workflow state). Every change also writes case_event.
-- primary key (enforced by the app, not by Delta): case_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`cases` (
  case_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  severity STRING NOT NULL,
  status STRING NOT NULL,
  opened_at TIMESTAMP NOT NULL,
  assignee STRING,
  itsm_ref STRING,
  regulation_refs STRING NOT NULL,
  summary STRING NOT NULL,
  report_due_at TIMESTAMP,
  closed_at TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Case header (mutable workflow state). Every change also writes case_event.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- case_event (append_only): Who did what on a case. Feeds the evidence chain.
-- primary key (enforced by the app, not by Delta): case_id, seq
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`case_event` (
  case_id STRING NOT NULL,
  seq BIGINT NOT NULL,
  ts TIMESTAMP NOT NULL,
  actor STRING NOT NULL,
  actor_kind STRING NOT NULL,
  action STRING NOT NULL,
  comment_masked STRING
)
USING DELTA
COMMENT 'Who did what on a case. Feeds the evidence chain.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- signoff (append_only): Human sign-off. Reviewer id from SSO, never the app service principal.
-- primary key (enforced by the app, not by Delta): signoff_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`signoff` (
  signoff_id STRING NOT NULL,
  case_id STRING NOT NULL,
  reviewer_id STRING NOT NULL,
  decision STRING NOT NULL,
  reason STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  auth_method STRING NOT NULL
)
USING DELTA
COMMENT 'Human sign-off. Reviewer id from SSO, never the app service principal.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- chain_entry (append_only): Hash chain. One lane per agent plus the root lane. PII never enters.
-- primary key (enforced by the app, not by Delta): lane, seq
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`chain_entry` (
  lane STRING NOT NULL,
  seq BIGINT NOT NULL,
  ts TIMESTAMP NOT NULL,
  record_type STRING NOT NULL,
  record_ref STRING NOT NULL,
  payload_hash STRING NOT NULL,
  prev_hash STRING NOT NULL,
  entry_hash STRING NOT NULL,
  writer STRING NOT NULL,
  env STRING NOT NULL
)
USING DELTA
COMMENT 'Hash chain. One lane per agent plus the root lane. PII never enters.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- chain_payload (append_only): Masked canonical JSON payload of a chain entry (no floats, no raw PII).
-- primary key (enforced by the app, not by Delta): lane, seq, payload_hash
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`chain_payload` (
  lane STRING NOT NULL,
  seq BIGINT NOT NULL,
  payload_hash STRING NOT NULL,
  payload STRING NOT NULL
)
USING DELTA
COMMENT 'Masked canonical JSON payload of a chain entry (no floats, no raw PII).'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- chain_signature (append_only): Signature over the entry_hash of a root-lane entry (signed head).
-- primary key (enforced by the app, not by Delta): lane, seq, entry_hash
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`chain_signature` (
  lane STRING NOT NULL,
  seq BIGINT NOT NULL,
  entry_hash STRING NOT NULL,
  signature STRING NOT NULL,
  key_id STRING NOT NULL,
  algorithm STRING NOT NULL,
  key_kind STRING NOT NULL,
  public_key STRING NOT NULL
)
USING DELTA
COMMENT 'Signature over the entry_hash of a root-lane entry (signed head).'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- anchor (append_only): Signed chain heads anchored to an immutable target.
-- primary key (enforced by the app, not by Delta): anchor_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`anchor` (
  anchor_id STRING NOT NULL,
  lane STRING NOT NULL,
  seq_from BIGINT NOT NULL,
  seq_to BIGINT NOT NULL,
  root_hash STRING NOT NULL,
  head_signature STRING NOT NULL,
  key_id STRING NOT NULL,
  anchored_at TIMESTAMP NOT NULL,
  anchor_target STRING NOT NULL,
  receipt STRING
)
USING DELTA
COMMENT 'Signed chain heads anchored to an immutable target.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- oversight_metric (state): Daily oversight metrics per agent. Feeds the console panel.
-- primary key (enforced by the app, not by Delta): metric_date, agent_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`oversight_metric` (
  metric_date DATE NOT NULL,
  agent_id STRING NOT NULL,
  coverage DOUBLE,
  ttd_ms BIGINT,
  tth_s BIGINT,
  catch_rate DOUBLE,
  false_alarm_rate DOUBLE,
  chain_ok BOOLEAN,
  groundedness DOUBLE,
  fairness_gap DOUBLE,
  computed_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Daily oversight metrics per agent. Feeds the console panel.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- gate_control (state): Gateway control records (WP3). Active pause (with the state to resume to) and pending two-person resume approvals.
-- primary key (enforced by the app, not by Delta): control_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gate_control` (
  control_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  action STRING NOT NULL,
  principal STRING NOT NULL,
  role STRING,
  reason STRING,
  resume_to STRING,
  status STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  expires_at TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Gateway control records (WP3). Active pause (with the state to resume to) and pending two-person resume approvals.'
TBLPROPERTIES ('supervisor.kind' = 'state');
