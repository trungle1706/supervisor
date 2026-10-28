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
  capture_level STRING NOT NULL,
  mask_version STRING,
  latency_us BIGINT,
  verdict_status STRING,
  correlation_id STRING,
  coverage_json STRING,
  session_id STRING,
  session_source STRING,
  session_json STRING,
  request_id STRING,
  consumer_id STRING,
  latency_rules_us BIGINT,
  latency_detectors_us BIGINT,
  detector_latency_json STRING
)
USING DELTA
COMMENT 'Normalised OTel-shaped events. Single read model for Watch. Masked only.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- agent_event_raw (append_only): RESTRICTED. Unmasked args/result text for agents whose manifest allows capture level raw (capture.raw_allowed). Restricted group only, short TTL (raw 90 d). Never read by judges or the chain. Rows link to agent_event by event_id.
-- primary key (enforced by the app, not by Delta): event_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`agent_event_raw` (
  event_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  trace_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  args_raw STRING,
  result_raw STRING,
  access_class STRING NOT NULL
)
USING DELTA
COMMENT 'RESTRICTED. Unmasked args/result text for agents whose manifest allows capture level raw (capture.raw_allowed). Restricted group only, short TTL (raw 90 d). Never read by judges or the chain. Rows link to agent_event by event_id.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

-- trace_coverage (append_only): What each trace input path can see per agent (WP4). A proxy-log agent gets capability reduced with the list of missing fields. One row per agent, source and capability.
-- primary key (enforced by the app, not by Delta): coverage_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`trace_coverage` (
  coverage_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  agent_id STRING NOT NULL,
  source STRING NOT NULL,
  capability STRING NOT NULL,
  missing STRING NOT NULL,
  note STRING
)
USING DELTA
COMMENT 'What each trace input path can see per agent (WP4). A proxy-log agent gets capability reduced with the list of missing fields. One row per agent, source and capability.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

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
  rationale_masked STRING,
  score_bp BIGINT,
  role STRING,
  region STRING,
  model_version STRING,
  mask_version STRING,
  prompt_hash STRING,
  rubric_version STRING,
  family_source STRING
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
  case_type STRING,
  incident_detected_at TIMESTAMP,
  urgency_class STRING,
  prelim_report_due_at TIMESTAMP,
  formal_report_due_at TIMESTAMP,
  prelim_report_sent_at TIMESTAMP,
  formal_report_sent_at TIMESTAMP,
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
  comment_masked STRING,
  auth_method STRING
)
USING DELTA
COMMENT 'Who did what on a case. Feeds the evidence chain.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- case_link (append_only): WP8. Which source opened or joined a case: a gate decision (block/pause), a judge verdict (CaseRequest) or a monitor finding. One row per source; makes intake idempotent.
-- primary key (enforced by the app, not by Delta): source_kind, source_ref
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`case_link` (
  source_kind STRING NOT NULL,
  source_ref STRING NOT NULL,
  case_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP8. Which source opened or joined a case: a gate decision (block/pause), a judge verdict (CaseRequest) or a monitor finding. One row per source; makes intake idempotent.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

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
  events_seen BIGINT,
  events_gated BIGINT,
  coverage_bp BIGINT,
  catch_rate_bp BIGINT,
  false_alarm_bp BIGINT,
  judge_verdicts BIGINT,
  judge_disagree_bp BIGINT,
  groundedness_bp BIGINT,
  fairness_gap_bp BIGINT,
  cases_opened BIGINT,
  blocks BIGINT,
  llm_calls BIGINT,
  judge_latency_ms BIGINT,
  judge_human_pairs BIGINT,
  judge_human_agree_bp BIGINT,
  monitor_status STRING,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Daily oversight metrics per agent. Feeds the console panel.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- model_validation (append_only): WP19. One row per judge validation run (python -m supervisor.judge.mrm validate). The judge service checks it when JUDGE_REQUIRE_VALIDATION is on. Integers only.
-- primary key (enforced by the app, not by Delta): validation_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`model_validation` (
  validation_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  judge_id STRING NOT NULL,
  model_version STRING NOT NULL,
  prompt_hash STRING NOT NULL,
  rubric_version STRING NOT NULL,
  mask_version STRING NOT NULL,
  golden_set_hash STRING NOT NULL,
  is_mock BOOLEAN NOT NULL,
  decision STRING NOT NULL,
  passed BOOLEAN NOT NULL,
  runs BIGINT NOT NULL,
  metrics STRING NOT NULL,
  thresholds STRING NOT NULL,
  failed_checks STRING NOT NULL,
  validator STRING NOT NULL,
  report_hash STRING NOT NULL
)
USING DELTA
COMMENT 'WP19. One row per judge validation run (python -m supervisor.judge.mrm validate). The judge service checks it when JUDGE_REQUIRE_VALIDATION is on. Integers only.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- policy_baseline (state): Drift baseline band per agent version and metric (WP7, ADR D09). Integers only: band = center +- k * scaled MAD. Also holds the breach streak of the drift monitor.
-- primary key (enforced by the app, not by Delta): agent_id, agent_version, metric
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`policy_baseline` (
  agent_id STRING NOT NULL,
  agent_version STRING NOT NULL,
  metric STRING NOT NULL,
  baseline_id STRING NOT NULL,
  center BIGINT NOT NULL,
  mad BIGINT NOT NULL,
  band_low BIGINT NOT NULL,
  band_high BIGINT NOT NULL,
  k BIGINT NOT NULL,
  windows BIGINT NOT NULL,
  window_s BIGINT NOT NULL,
  window_from TIMESTAMP NOT NULL,
  window_to TIMESTAMP NOT NULL,
  breach_streak BIGINT NOT NULL,
  last_value BIGINT,
  last_checked_to TIMESTAMP,
  open_case_id STRING,
  computed_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Drift baseline band per agent version and metric (WP7, ADR D09). Integers only: band = center +- k * scaled MAD. Also holds the breach streak of the drift monitor.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- policy_threshold (state): Monitor thresholds per agent and metric (WP7). agent_id '*' is the default for every agent. Example metrics: drift.k, drift.consecutive, fairness.approval_gap_bp.
-- primary key (enforced by the app, not by Delta): agent_id, metric
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`policy_threshold` (
  agent_id STRING NOT NULL,
  metric STRING NOT NULL,
  threshold BIGINT NOT NULL,
  unit STRING NOT NULL,
  owner STRING,
  note STRING,
  effective_from TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Monitor thresholds per agent and metric (WP7). agent_id ''*'' is the default for every agent. Example metrics: drift.k, drift.consecutive, fairness.approval_gap_bp.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- fairness_slice (append_only): One row per fairness cell per run (WP7). Cells under the minimum n are suppressed: counts and rates are null. Built on hashed subject ids, never raw ids.
-- primary key (enforced by the app, not by Delta): run_id, attribute, cell
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`fairness_slice` (
  run_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  agent_id STRING NOT NULL,
  window_from TIMESTAMP NOT NULL,
  window_to TIMESTAMP NOT NULL,
  attribute STRING NOT NULL,
  cell STRING NOT NULL,
  n BIGINT,
  approvals BIGINT,
  blocks BIGINT,
  approval_rate_bp BIGINT,
  block_rate_bp BIGINT,
  suppressed BOOLEAN NOT NULL,
  method STRING NOT NULL
)
USING DELTA
COMMENT 'One row per fairness cell per run (WP7). Cells under the minimum n are suppressed: counts and rates are null. Built on hashed subject ids, never raw ids.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

-- monitor_state (state): Cursors and dedupe marks of the monitors and the scheduler (WP7).
-- primary key (enforced by the app, not by Delta): monitor, state_key
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`monitor_state` (
  monitor STRING NOT NULL,
  state_key STRING NOT NULL,
  value STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Cursors and dedupe marks of the monitors and the scheduler (WP7).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- scheduler_lease (state): Single-instance lock of the in-process scheduler on Databricks (WP7). One row per lease; the holder renews it; another replica takes it only after expires_at.
-- primary key (enforced by the app, not by Delta): lease_name
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`scheduler_lease` (
  lease_name STRING NOT NULL,
  holder STRING NOT NULL,
  acquired_at TIMESTAMP NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'Single-instance lock of the in-process scheduler on Databricks (WP7). One row per lease; the holder renews it; another replica takes it only after expires_at.'
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

-- notice (state): WP8. Notifier inbox (console Inbox page). Masked text only. The webhook stub queues rows with status queued and never sends them (off by default).
-- primary key (enforced by the app, not by Delta): notice_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`notice` (
  notice_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  channel STRING NOT NULL,
  subject STRING NOT NULL,
  body STRING NOT NULL,
  status STRING NOT NULL,
  read_by STRING,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP8. Notifier inbox (console Inbox page). Masked text only. The webhook stub queues rows with status queued and never sends them (off by default).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- console_action (append_only): WP18. One row per mutating console or API action (and per denied attempt): who, when, what, target, row hash before and after, request id. Append-only; in the audit pack.
-- primary key (enforced by the app, not by Delta): action_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`console_action` (
  action_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  request_id STRING NOT NULL,
  actor STRING NOT NULL,
  actor_kind STRING NOT NULL,
  auth_method STRING NOT NULL,
  roles STRING NOT NULL,
  permission STRING NOT NULL,
  method STRING NOT NULL,
  path STRING NOT NULL,
  target_kind STRING,
  target_id STRING,
  outcome STRING NOT NULL,
  before_hash STRING,
  after_hash STRING,
  detail STRING
)
USING DELTA
COMMENT 'WP18. One row per mutating console or API action (and per denied attempt): who, when, what, target, row hash before and after, request id. Append-only; in the audit pack.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- eval_run (append_only): WP17 assurance eval packs. One row per run of `python -m supervisor.assurance run` (counts per status). Integers and strings only.
-- primary key (enforced by the app, not by Delta): run_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`eval_run` (
  run_id STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP NOT NULL,
  target_spec STRING NOT NULL,
  selector STRING NOT NULL,
  packs_total BIGINT NOT NULL,
  ok BIGINT NOT NULL,
  warn BIGINT NOT NULL,
  fail BIGINT NOT NULL,
  skip BIGINT NOT NULL,
  error BIGINT NOT NULL,
  is_mock BOOLEAN NOT NULL,
  settings_digest STRING,
  out_dir STRING
)
USING DELTA
COMMENT 'WP17 assurance eval packs. One row per run of `python -m supervisor.assurance run` (counts per status). Integers and strings only.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

-- eval_result (append_only): WP17 assurance eval packs. One row per pack x target x run: integer metrics, the per-metric status against the manifest thresholds, the dataset digest and the hash of the assurance_result chain record. Mock runs are labelled is_mock.
-- primary key (enforced by the app, not by Delta): run_id, pack_id, target_kind, target_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`eval_result` (
  run_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  pack_id STRING NOT NULL,
  pack_version BIGINT NOT NULL,
  manifest_sha256 STRING NOT NULL,
  dimension STRING NOT NULL,
  target_kind STRING NOT NULL,
  target_id STRING NOT NULL,
  status STRING NOT NULL,
  metrics STRING NOT NULL,
  metric_status STRING NOT NULL,
  thresholds STRING NOT NULL,
  reasons STRING NOT NULL,
  n_items BIGINT NOT NULL,
  data_mode STRING NOT NULL,
  dataset_id STRING NOT NULL,
  dataset_sha256 STRING NOT NULL,
  is_mock BOOLEAN NOT NULL,
  launch_gate STRING NOT NULL,
  judge_gate BOOLEAN NOT NULL,
  details STRING NOT NULL,
  evidence_hash STRING
)
USING DELTA
COMMENT 'WP17 assurance eval packs. One row per pack x target x run: integer metrics, the per-metric status against the manifest thresholds, the dataset digest and the hash of the assurance_result chain record. Mock runs are labelled is_mock.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- tool_usage_daily (state): WP22. Per agent, tool and UTC day: gate decision counts, latency percentiles, distinct callers and end users (counts only; hashed ids are never stored), first and last call. Recomputed from agent_event by python -m supervisor.analytics.tools rollup (idempotent: a day is overwritten). Feeds the console Tools page, /v1/analytics/tools and the least-privilege suggestion. Integers only.
-- primary key (enforced by the app, not by Delta): usage_date, agent_id, tool_name
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`tool_usage_daily` (
  usage_date DATE NOT NULL,
  agent_id STRING NOT NULL,
  tool_name STRING NOT NULL,
  risk_class STRING,
  calls BIGINT NOT NULL,
  allows BIGINT NOT NULL,
  blocks BIGINT NOT NULL,
  pauses BIGINT NOT NULL,
  errors BIGINT NOT NULL,
  p50_us BIGINT,
  p95_us BIGINT,
  distinct_callers BIGINT NOT NULL,
  distinct_users BIGINT NOT NULL,
  first_seen TIMESTAMP,
  last_seen TIMESTAMP,
  computed_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP22. Per agent, tool and UTC day: gate decision counts, latency percentiles, distinct callers and end users (counts only; hashed ids are never stored), first and last call. Recomputed from agent_event by python -m supervisor.analytics.tools rollup (idempotent: a day is overwritten). Feeds the console Tools page, /v1/analytics/tools and the least-privilege suggestion. Integers only.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- decision_daily (state): WP39. Per UTC day and dimension: gate decision counts by verdict status, the not-evaluated count and, for dimension detector_latency, latency percentiles. Recomputed from agent_event and finding by python -m supervisor.jobs.decision_rollup (idempotent: a day is overwritten). Feeds the console Analytics Gate and Detectors tabs so the App never scans the raw table on page load. dimension: total | agent | consumer | rule | detector_code | detector_latency. Integers and ids only; no text.
-- primary key (enforced by the app, not by Delta): usage_date, dimension, dim_key, dim_key2
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`decision_daily` (
  usage_date DATE NOT NULL,
  dimension STRING NOT NULL,
  dim_key STRING NOT NULL,
  dim_key2 STRING NOT NULL,
  requests BIGINT NOT NULL,
  allows BIGINT NOT NULL,
  reports BIGINT NOT NULL,
  transforms BIGINT NOT NULL,
  pauses BIGINT NOT NULL,
  blocks BIGINT NOT NULL,
  skips BIGINT NOT NULL,
  not_evaluated BIGINT NOT NULL,
  p50_us BIGINT,
  p95_us BIGINT,
  computed_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP39. Per UTC day and dimension: gate decision counts by verdict status, the not-evaluated count and, for dimension detector_latency, latency percentiles. Recomputed from agent_event and finding by python -m supervisor.jobs.decision_rollup (idempotent: a day is overwritten). Feeds the console Analytics Gate and Detectors tabs so the App never scans the raw table on page load. dimension: total | agent | consumer | rule | detector_code | detector_latency. Integers and ids only; no text.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- alert (state): WP21. One row per fired alert (rule engine, ADR D15). Ids, counts and hashes only, never free text. dedupe_key = rule_id + group value; repeats inside the rule's dedupe window raise suppressed_count on the open row instead of making a new row. status: open, acknowledged (by an operator, audited), closed.
-- primary key (enforced by the app, not by Delta): alert_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`alert` (
  alert_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  dedupe_key STRING NOT NULL,
  rule_id STRING NOT NULL,
  rule_hash STRING NOT NULL,
  severity STRING NOT NULL,
  status STRING NOT NULL,
  title STRING NOT NULL,
  agent_id STRING,
  group_value STRING,
  window_s BIGINT NOT NULL,
  window_count BIGINT NOT NULL,
  threshold BIGINT NOT NULL,
  first_ts TIMESTAMP NOT NULL,
  last_ts TIMESTAMP NOT NULL,
  suppressed_count BIGINT NOT NULL,
  case_id STRING,
  chain_lane STRING,
  chain_seq BIGINT,
  entry_hash STRING,
  refs STRING NOT NULL,
  routes STRING NOT NULL,
  route_status STRING NOT NULL,
  acknowledged_by STRING,
  acknowledged_at TIMESTAMP,
  correlation_id STRING,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP21. One row per fired alert (rule engine, ADR D15). Ids, counts and hashes only, never free text. dedupe_key = rule_id + group value; repeats inside the rule''s dedupe window raise suppressed_count on the open row instead of making a new row. status: open, acknowledged (by an operator, audited), closed.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- siem_event (append_only): WP21. Delta sink of the SIEM export (SIEM_SINK=delta): one row per event, with the OCSF document, so a Databricks-hosted SIEM connector or Lakehouse Monitoring can read it. Ids, hashes and enums only. event_id is the idempotency key.
-- primary key (enforced by the app, not by Delta): event_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`siem_event` (
  event_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  event_type STRING NOT NULL,
  severity BIGINT NOT NULL,
  outcome STRING NOT NULL,
  agent_id STRING,
  rule_id STRING,
  case_id STRING,
  actor STRING,
  chain_lane STRING,
  chain_seq BIGINT,
  entry_hash STRING,
  env STRING NOT NULL,
  event_schema STRING NOT NULL,
  ocsf_class_uid BIGINT NOT NULL,
  ocsf_json STRING NOT NULL
)
USING DELTA
COMMENT 'WP21. Delta sink of the SIEM export (SIEM_SINK=delta): one row per event, with the OCSF document, so a Databricks-hosted SIEM connector or Lakehouse Monitoring can read it. Ids, hashes and enums only. event_id is the idempotency key.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

-- inventory_node (state): WP24 inventory graph node (system, model, model_endpoint, tool, mcp_server, dataset, prompt, supplier). node_id is a hash of kind + canonical name, so a refill never duplicates. own_risk is low|medium|high|critical or NULL; the effective level is computed on read, never stored. decision33_class is human-set (copied from the agent row), never inferred. evidence lists {source, ref} pairs (manifest | onboarding | workspace_scan | manual | gate, plus file:line or a workspace reference).
-- primary key (enforced by the app, not by Delta): node_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`inventory_node` (
  node_id STRING NOT NULL,
  kind STRING NOT NULL,
  name STRING NOT NULL,
  display_name STRING NOT NULL,
  status STRING NOT NULL,
  own_risk STRING,
  risk_source STRING NOT NULL,
  decision33_class STRING,
  attrs STRING NOT NULL,
  evidence STRING NOT NULL,
  first_seen TIMESTAMP NOT NULL,
  last_seen TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP24 inventory graph node (system, model, model_endpoint, tool, mcp_server, dataset, prompt, supplier). node_id is a hash of kind + canonical name, so a refill never duplicates. own_risk is low|medium|high|critical or NULL; the effective level is computed on read, never stored. decision33_class is human-set (copied from the agent row), never inferred. evidence lists {source, ref} pairs (manifest | onboarding | workspace_scan | manual | gate, plus file:line or a workspace reference).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- inventory_edge (state): WP24 inventory graph edge (uses, serves, reads, writes, hosted_on, owned_by). One row per (src, kind, dst, source) so every claim keeps its own evidence. active is false when the source no longer reports the edge.
-- primary key (enforced by the app, not by Delta): edge_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`inventory_edge` (
  edge_id STRING NOT NULL,
  src_id STRING NOT NULL,
  dst_id STRING NOT NULL,
  kind STRING NOT NULL,
  source STRING NOT NULL,
  evidence_ref STRING NOT NULL,
  active BOOLEAN NOT NULL,
  first_seen TIMESTAMP NOT NULL,
  last_seen TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP24 inventory graph edge (uses, serves, reads, writes, hosted_on, owned_by). One row per (src, kind, dst, source) so every claim keeps its own evidence. active is false when the source no longer reports the edge.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- session_control (state): WP27 session-scoped pause of money / credit tools. One row per pause: active until a two-person resume (owner + reviewer, same rule as an agent resume) or until expires_at (cool-down). Written only by a deterministic rule of the session monitor. The gate reads active rows (GATE-SESSION-PAUSE). Free text never lands here.
-- primary key (enforced by the app, not by Delta): control_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`session_control` (
  control_id STRING NOT NULL,
  session_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  scope STRING NOT NULL,
  status STRING NOT NULL,
  score_bp BIGINT NOT NULL,
  case_id STRING,
  created_at TIMESTAMP NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  approver_1 STRING,
  approver_1_role STRING,
  approver_1_at TIMESTAMP,
  lifted_by STRING,
  lifted_at TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP27 session-scoped pause of money / credit tools. One row per pause: active until a two-person resume (owner + reviewer, same rule as an agent resume) or until expires_at (cool-down). Written only by a deterministic rule of the session monitor. The gate reads active rows (GATE-SESSION-PAUSE). Free text never lands here.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- finding (append_only): WP37 one row per detector result of a gate decision: a fired finding, or a detector that did not run (not_executed_reason set, score 0). Entities and fragments are MASKED text only (pseudonym tokens and masked excerpts); raw values never reach this table. event_id is the gate decision (agent_event.event_id); correlation_id ties decision, trace span and finding.
-- primary key (enforced by the app, not by Delta): finding_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`finding` (
  finding_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  event_id STRING NOT NULL,
  request_id STRING NOT NULL,
  correlation_id STRING NOT NULL,
  trace_id STRING,
  agent_id STRING NOT NULL,
  tool_name STRING NOT NULL,
  direction STRING NOT NULL,
  detector_slug STRING NOT NULL,
  detector_id STRING NOT NULL,
  code STRING NOT NULL,
  score_bp BIGINT NOT NULL,
  threshold_bp BIGINT NOT NULL,
  masked_count BIGINT NOT NULL,
  action_hint STRING NOT NULL,
  not_executed_reason STRING,
  preset STRING,
  is_mock BOOLEAN NOT NULL,
  verdict_status STRING NOT NULL,
  entities_masked STRING,
  fragments_masked STRING
)
USING DELTA
COMMENT 'WP37 one row per detector result of a gate decision: a fired finding, or a detector that did not run (not_executed_reason set, score 0). Entities and fragments are MASKED text only (pseudonym tokens and masked excerpts); raw values never reach this table. event_id is the gate decision (agent_event.event_id); correlation_id ties decision, trace span and finding.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- mcp_tool_manifest (state): WP26 locked tool manifest per upstream MCP server. One row per (server, tool) plus one server row (tool_name '*') that holds the whole-list hash. locked_hash is what two different reviewers approved; observed_hash is what the server shows now. A tool whose status is new or changed is hidden from the agent and its tools/call is blocked (MCP-TOOL-UNREVIEWED). approvals lists {by, role, at, hash}; they count only for the observed hash. scan is the report-only poisoning scan (kinds and counts, no text).
-- primary key (enforced by the app, not by Delta): manifest_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`mcp_tool_manifest` (
  manifest_id STRING NOT NULL,
  server_id STRING NOT NULL,
  tool_name STRING NOT NULL,
  row_kind STRING NOT NULL,
  agent_id STRING NOT NULL,
  status STRING NOT NULL,
  locked_hash STRING,
  observed_hash STRING,
  locked_def STRING,
  observed_def STRING,
  suspicious BOOLEAN NOT NULL,
  scan STRING,
  approvals STRING NOT NULL,
  case_id STRING,
  seeded_by STRING,
  first_seen TIMESTAMP NOT NULL,
  last_seen TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP26 locked tool manifest per upstream MCP server. One row per (server, tool) plus one server row (tool_name ''*'') that holds the whole-list hash. locked_hash is what two different reviewers approved; observed_hash is what the server shows now. A tool whose status is new or changed is hidden from the agent and its tools/call is blocked (MCP-TOOL-UNREVIEWED). approvals lists {by, role, at, hash}; they count only for the observed hash. scan is the report-only poisoning scan (kinds and counts, no text).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- risk (state): WP29 risk register entry. Anchored on an agent or on an inventory node (a shared model, tool, MCP server or dataset, which every agent that reaches it inherits). Likelihood and impact are whole numbers 1 to 5; the score is their product and is computed on read, never stored. residual_* is what the person declares for the treated risk; the value the product uses is decided by the evidence rule (risk_evidence), see docs/risk-register.md.
-- primary key (enforced by the app, not by Delta): risk_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`risk` (
  risk_id STRING NOT NULL,
  title STRING NOT NULL,
  description STRING NOT NULL,
  category STRING NOT NULL,
  agent_id STRING,
  node_id STRING,
  inherent_likelihood BIGINT NOT NULL,
  inherent_impact BIGINT NOT NULL,
  marginal_risk BIGINT,
  marginal_note STRING,
  treatment STRING NOT NULL,
  treatment_note STRING,
  residual_likelihood BIGINT NOT NULL,
  residual_impact BIGINT NOT NULL,
  owner STRING NOT NULL,
  review_date DATE,
  status STRING NOT NULL,
  source STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP29 risk register entry. Anchored on an agent or on an inventory node (a shared model, tool, MCP server or dataset, which every agent that reaches it inherits). Likelihood and impact are whole numbers 1 to 5; the score is their product and is computed on read, never stored. residual_* is what the person declares for the treated risk; the value the product uses is decided by the evidence rule (risk_evidence), see docs/risk-register.md.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- risk_link (state): WP29 link of a risk to a compliance matrix row (obligation id), a gate rule id, an assurance pack id, a monitor name or a case id. rule, pack and monitor links are the controls the evidence rule looks at; matrix and case links are references.
-- primary key (enforced by the app, not by Delta): link_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`risk_link` (
  link_id STRING NOT NULL,
  risk_id STRING NOT NULL,
  kind STRING NOT NULL,
  target STRING NOT NULL,
  active BOOLEAN NOT NULL,
  created_at TIMESTAMP NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP29 link of a risk to a compliance matrix row (obligation id), a gate rule id, an assurance pack id, a monitor name or a case id. rule, pack and monitor links are the controls the evidence rule looks at; matrix and case links are references.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- risk_evidence (append_only): WP29. One row per risk and window: what the linked controls did (counts), the state (working | failing | no_evidence), the reason code and the residual score the evidence rule allows. Integers, codes and hashes only; no text. The matching chain record is risk_evidence. A repeat for the same window is a no-op (evidence_id is a hash).
-- primary key (enforced by the app, not by Delta): evidence_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`risk_evidence` (
  evidence_id STRING NOT NULL,
  risk_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  window_start TIMESTAMP NOT NULL,
  window_end TIMESTAMP NOT NULL,
  state STRING NOT NULL,
  reason STRING NOT NULL,
  agents_n BIGINT NOT NULL,
  agents_excluded BIGINT NOT NULL,
  rule_links BIGINT NOT NULL,
  rule_hits BIGINT NOT NULL,
  rule_stops BIGINT NOT NULL,
  rules_missing BIGINT NOT NULL,
  pack_links BIGINT NOT NULL,
  pack_ok BIGINT NOT NULL,
  pack_warn BIGINT NOT NULL,
  pack_fail BIGINT NOT NULL,
  pack_nodata BIGINT NOT NULL,
  monitor_links BIGINT NOT NULL,
  monitor_ok BIGINT NOT NULL,
  monitor_other BIGINT NOT NULL,
  controls_working BIGINT NOT NULL,
  controls_failing BIGINT NOT NULL,
  controls_idle BIGINT NOT NULL,
  declared_residual_likelihood BIGINT NOT NULL,
  declared_residual_impact BIGINT NOT NULL,
  residual_likelihood BIGINT NOT NULL,
  residual_impact BIGINT NOT NULL,
  digest STRING NOT NULL,
  chain_hash STRING
)
USING DELTA
COMMENT 'WP29. One row per risk and window: what the linked controls did (counts), the state (working | failing | no_evidence), the reason code and the residual score the evidence rule allows. Integers, codes and hashes only; no text. The matching chain record is risk_evidence. A repeat for the same window is a no-op (evidence_id is a hash).'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- control (state): WP30 control: an action the bank or the product takes to meet obligations and hold risks down. One control covers many obligations and many risks (control_map). type is preventive, detective or corrective; implemented_by is product or bank. scope_agents is a JSON list of agent ids, or [*] for every supervised agent. Evidence status is computed from runtime facts (control_status), never typed in.
-- primary key (enforced by the app, not by Delta): control_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`control` (
  control_id STRING NOT NULL,
  title STRING NOT NULL,
  objective STRING NOT NULL,
  control_type STRING NOT NULL,
  implemented_by STRING NOT NULL,
  owner STRING NOT NULL,
  status STRING NOT NULL,
  review_date DATE,
  scope_agents STRING NOT NULL,
  source STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP30 control: an action the bank or the product takes to meet obligations and hold risks down. One control covers many obligations and many risks (control_map). type is preventive, detective or corrective; implemented_by is product or bank. scope_agents is a JSON list of agent ids, or [*] for every supervised agent. Evidence status is computed from runtime facts (control_status), never typed in.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- control_map (state): WP30 map of one control. kind matrix = obligation id of the compliance matrix, risk = risk id of the register; rule, pack, monitor, detector and document are evidence sources. Only rule, pack and monitor are observed at runtime; detector and document are references.
-- primary key (enforced by the app, not by Delta): map_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`control_map` (
  map_id STRING NOT NULL,
  control_id STRING NOT NULL,
  kind STRING NOT NULL,
  target STRING NOT NULL,
  active BOOLEAN NOT NULL,
  created_at TIMESTAMP NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP30 map of one control. kind matrix = obligation id of the compliance matrix, risk = risk id of the register; rule, pack, monitor, detector and document are evidence sources. Only rule, pack and monitor are observed at runtime; detector and document are references.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- control_status (append_only): WP30. One row per control, agent and window: working, failing or no_data, a fixed reason code and integer counts of the evidence sources. No text. The matching chain record is control_status (one per agent and pass, carrying the compliance bp). A repeat for the same window is a no-op (status_id is a hash).
-- primary key (enforced by the app, not by Delta): status_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`control_status` (
  status_id STRING NOT NULL,
  control_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  window_start TIMESTAMP NOT NULL,
  window_end TIMESTAMP NOT NULL,
  status STRING NOT NULL,
  reason STRING NOT NULL,
  sources_n BIGINT NOT NULL,
  working_n BIGINT NOT NULL,
  failing_n BIGINT NOT NULL,
  idle_n BIGINT NOT NULL,
  refs_n BIGINT NOT NULL,
  digest STRING NOT NULL,
  chain_hash STRING
)
USING DELTA
COMMENT 'WP30. One row per control, agent and window: working, failing or no_data, a fixed reason code and integer counts of the evidence sources. No text. The matching chain record is control_status (one per agent and pass, carrying the compliance bp). A repeat for the same window is a no-op (status_id is a hash).'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- task (state): WP30 lifecycle task of one agent, made from a template in config/tasks.yaml. kind move is the lifecycle move itself (a task); it is done only when no required task of the stage is open. Waiving needs a reason and a second person (waive_requested_by, waive_approved_by). evidence_kind says what proves the task done: control, pack, document or none.
-- primary key (enforced by the app, not by Delta): task_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`task` (
  task_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  template_id STRING NOT NULL,
  kind STRING NOT NULL,
  stage STRING NOT NULL,
  target_stage STRING,
  title STRING NOT NULL,
  owner_role STRING NOT NULL,
  required BOOLEAN NOT NULL,
  status STRING NOT NULL,
  due_at TIMESTAMP,
  evidence_kind STRING NOT NULL,
  evidence_ref STRING,
  level STRING NOT NULL,
  d33_class STRING NOT NULL,
  waive_reason STRING,
  waive_requested_by STRING,
  waive_approved_by STRING,
  done_by STRING,
  done_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP30 lifecycle task of one agent, made from a template in config/tasks.yaml. kind move is the lifecycle move itself (a task); it is done only when no required task of the stage is open. Waiving needs a reason and a second person (waive_requested_by, waive_approved_by). evidence_kind says what proves the task done: control, pack, document or none.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- task_event (append_only): WP30. Every change of a task: generate, start, done, waive_request, waive_approve, waive_reject, resize, overdue. From and to status, the actor and hashes; reasons are stored as a hash only. The matching chain record is task_change.
-- primary key (enforced by the app, not by Delta): event_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`task_event` (
  event_id STRING NOT NULL,
  task_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  ts TIMESTAMP NOT NULL,
  action STRING NOT NULL,
  actor STRING NOT NULL,
  from_status STRING,
  to_status STRING,
  reason_sha256 STRING,
  row_hash STRING NOT NULL,
  chain_hash STRING
)
USING DELTA
COMMENT 'WP30. Every change of a task: generate, start, done, waive_request, waive_approve, waive_reject, resize, overdue. From and to status, the actor and hashes; reasons are stored as a hash only. The matching chain record is task_change.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- transparency_report (append_only): WP31. One row per generated report file set: agent, variant (regulator | customer | internal), language, version (a whole number per agent and variant) and the sha256 of the JSON and of each rendered file. The report data holds ids, integers, hashes and masked text only; this row holds hashes, counts and section hashes (for the diff to the next version), no text. The matching chain record is transparency_report. A repeat for the same (agent, variant, lang, version) is a no-op (report_id is a hash).
-- primary key (enforced by the app, not by Delta): report_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`transparency_report` (
  report_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  variant STRING NOT NULL,
  lang STRING NOT NULL,
  version BIGINT NOT NULL,
  schema_version BIGINT NOT NULL,
  generated_at TIMESTAMP NOT NULL,
  generated_by STRING NOT NULL,
  content_hash STRING NOT NULL,
  json_hash STRING NOT NULL,
  html_hash STRING,
  pdf_hash STRING,
  sections_total BIGINT NOT NULL,
  sections_available BIGINT NOT NULL,
  section_hashes STRING NOT NULL,
  verify_state STRING NOT NULL,
  chain_hash STRING
)
USING DELTA
COMMENT 'WP31. One row per generated report file set: agent, variant (regulator | customer | internal), language, version (a whole number per agent and variant) and the sha256 of the JSON and of each rendered file. The report data holds ids, integers, hashes and masked text only; this row holds hashes, counts and section hashes (for the diff to the next version), no text. The matching chain record is transparency_report. A repeat for the same (agent, variant, lang, version) is a no-op (report_id is a hash).'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'delta.logRetentionDuration' = 'interval 1825 days', 'delta.deletedFileRetentionDuration' = 'interval 1825 days', 'supervisor.kind' = 'append_only');

-- ai_system (state): WP-G0. The unit of governance: one AI system (product, platform, feature or use case) with named owners, a few unambiguous intake fields and a manual risk level. The effective risk level (manual level and the level inherited from linked agents and inventory nodes) is computed on read, never stored. decision33_class is human-set. Changes go on the chain as system_change.
-- primary key (enforced by the app, not by Delta): system_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`ai_system` (
  system_id STRING NOT NULL,
  name STRING NOT NULL,
  owner_user STRING NOT NULL,
  owner_team STRING NOT NULL,
  business_owner STRING,
  purpose STRING NOT NULL,
  system_type STRING NOT NULL,
  org_role STRING NOT NULL,
  user_segment STRING NOT NULL,
  personal_data STRING NOT NULL,
  money_movement BOOLEAN NOT NULL,
  credit_decision BOOLEAN NOT NULL,
  human_control STRING NOT NULL,
  lifecycle_stage STRING NOT NULL,
  risk_level STRING NOT NULL,
  risk_level_source STRING NOT NULL,
  risk_justification STRING,
  decision33_class STRING NOT NULL,
  business_impact STRING NOT NULL,
  autonomy_level STRING NOT NULL,
  status STRING NOT NULL,
  tags STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G0. The unit of governance: one AI system (product, platform, feature or use case) with named owners, a few unambiguous intake fields and a manual risk level. The effective risk level (manual level and the level inherited from linked agents and inventory nodes) is computed on read, never stored. decision33_class is human-set. Changes go on the chain as system_change.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- system_team (state): WP-G0. Who is on an AI system and in which role. A member sees and edits the system; a reviewer or oversight manager cannot be the system owner of the same system (segregation of duties).
-- primary key (enforced by the app, not by Delta): system_id, user_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`system_team` (
  system_id STRING NOT NULL,
  user_id STRING NOT NULL,
  team_role STRING NOT NULL,
  active BOOLEAN NOT NULL,
  added_at TIMESTAMP NOT NULL,
  added_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G0. Who is on an AI system and in which role. A member sees and edits the system; a reviewer or oversight manager cannot be the system owner of the same system (segregation of duties).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- system_component (state): WP-G0. A link from an AI system to an agent or an inventory node. component_id is a hash of (system_id, ref_kind, ref_id, role), so a repeat is a no-op. active is false after an unlink (the row stays as history).
-- primary key (enforced by the app, not by Delta): component_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`system_component` (
  component_id STRING NOT NULL,
  system_id STRING NOT NULL,
  ref_kind STRING NOT NULL,
  ref_id STRING NOT NULL,
  role STRING NOT NULL,
  source STRING NOT NULL,
  evidence_ref STRING NOT NULL,
  active BOOLEAN NOT NULL,
  first_seen TIMESTAMP NOT NULL,
  last_seen TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G0. A link from an AI system to an agent or an inventory node. component_id is a hash of (system_id, ref_kind, ref_id, role), so a repeat is a no-op. active is false after an unlink (the row stays as history).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- assignment (state): WP-G2. One thing the assignment rules put on an AI system: an obligation, a control, a risk, a task template or a guardian feature. assignment_id is a hash of (system, kind, ref), so a repeat run keeps the row. active is false when no rule fires for it any more; a row is never deleted. fired lists the rules and the fields that fired, for the explanation. A run writes a rule_run chain record.
-- primary key (enforced by the app, not by Delta): assignment_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`assignment` (
  assignment_id STRING NOT NULL,
  system_id STRING NOT NULL,
  rule_id STRING NOT NULL,
  kind STRING NOT NULL,
  ref_id STRING NOT NULL,
  active BOOLEAN NOT NULL,
  fired STRING NOT NULL,
  first_seen TIMESTAMP NOT NULL,
  last_seen TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G2. One thing the assignment rules put on an AI system: an obligation, a control, a risk, a task template or a guardian feature. assignment_id is a hash of (system, kind, ref), so a repeat run keeps the row. active is false when no rule fires for it any more; a row is never deleted. fired lists the rules and the fields that fired, for the explanation. A run writes a rule_run chain record.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- classification (state): WP-G2. A Decision 33 classification of one AI system: a draft made from the rules, edited by a person, then applied by a person (never by a model). answers holds, per question, the answer, its source (rules | ai_prefill | person) and the justification. Applying sets decision33_class on the system and the classifier floor of its risk level. Changes go on the chain as classification_change.
-- primary key (enforced by the app, not by Delta): classification_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`classification` (
  classification_id STRING NOT NULL,
  system_id STRING NOT NULL,
  outcome STRING NOT NULL,
  answers STRING NOT NULL,
  flow_sha256 STRING NOT NULL,
  status STRING NOT NULL,
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  applied_by STRING,
  applied_at TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G2. A Decision 33 classification of one AI system: a draft made from the rules, edited by a person, then applied by a person (never by a model). answers holds, per question, the answer, its source (rules | ai_prefill | person) and the justification. Applying sets decision33_class on the system and the classifier floor of its risk level. Changes go on the chain as classification_change.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- stage_approval (state): WP-G1. A request to move an AI system to a lifecycle stage that needs an approval (config/tasks.yaml, stages: ... approval: true), and the answer. The approver is a reviewer or oversight manager of the system or holds the approver role, and is neither the requester nor the owner. applied_at is set when the move used the approval. Changes go on the chain as stage_change.
-- primary key (enforced by the app, not by Delta): approval_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`stage_approval` (
  approval_id STRING NOT NULL,
  system_id STRING NOT NULL,
  from_stage STRING NOT NULL,
  to_stage STRING NOT NULL,
  requested_by STRING NOT NULL,
  status STRING NOT NULL,
  decided_by STRING,
  reason STRING,
  created_at TIMESTAMP NOT NULL,
  decided_at TIMESTAMP,
  applied_at TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G1. A request to move an AI system to a lifecycle stage that needs an approval (config/tasks.yaml, stages: ... approval: true), and the answer. The approver is a reviewer or oversight manager of the system or holds the approver role, and is neither the requester nor the owner. applied_at is set when the move used the approval. Changes go on the chain as stage_change.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- review (state): WP-G1. A review of an AI system (internal, external, conformity or classification audit) with its scope, window and reports. Completing a review locks it; reopening needs a reason. Changes go on the chain as review_change.
-- primary key (enforced by the app, not by Delta): review_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`review` (
  review_id STRING NOT NULL,
  system_id STRING NOT NULL,
  kind STRING NOT NULL,
  title STRING NOT NULL,
  scope STRING NOT NULL,
  reviewer_user STRING NOT NULL,
  status STRING NOT NULL,
  window_start TIMESTAMP,
  window_end TIMESTAMP,
  reports STRING NOT NULL,
  completed_at TIMESTAMP,
  completed_by STRING,
  locked BOOLEAN NOT NULL,
  reopen_reason STRING,
  reopen_count BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G1. A review of an AI system (internal, external, conformity or classification audit) with its scope, window and reports. Completing a review locks it; reopening needs a reason. Changes go on the chain as review_change.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- outbound_event (state): WP-G1. An event for other systems (stage approved, review completed, system registered, system archived). The payload holds ids and enums only. The webhook stub (WEBHOOKS_ENABLED) marks it delivered; nothing else reads the table yet.
-- primary key (enforced by the app, not by Delta): event_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`outbound_event` (
  event_id STRING NOT NULL,
  kind STRING NOT NULL,
  system_id STRING NOT NULL,
  payload STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  delivered BOOLEAN NOT NULL,
  delivered_at TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G1. An event for other systems (stage approved, review completed, system registered, system archived). The payload holds ids and enums only. The webhook stub (WEBHOOKS_ENABLED) marks it delivered; nothing else reads the table yet.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- incident (state): WP-G5. An incident made by the governance action job from an event (alert, gate stop on a risky tool, failed detector, failing monitor, assurance NO-GO, chain break, model version change, judge escalation). Auto-created only; a person moves it on and closes it. The title comes from a template; no free text from an event. root_cause and affected_scope are typed by a person. Changes go on the chain as incident_change.
-- primary key (enforced by the app, not by Delta): incident_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`incident` (
  incident_id STRING NOT NULL,
  system_id STRING,
  agent_id STRING NOT NULL,
  kind STRING NOT NULL,
  severity STRING NOT NULL,
  title STRING NOT NULL,
  event_ref STRING NOT NULL,
  root_cause STRING,
  affected_scope STRING,
  status STRING NOT NULL,
  opened_at TIMESTAMP NOT NULL,
  closed_at TIMESTAMP,
  closed_by STRING,
  case_id STRING,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G5. An incident made by the governance action job from an event (alert, gate stop on a risky tool, failed detector, failing monitor, assurance NO-GO, chain break, model version change, judge escalation). Auto-created only; a person moves it on and closes it. The title comes from a template; no free text from an event. root_cause and affected_scope are typed by a person. Changes go on the chain as incident_change.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- governance_event (state): WP-G5. The marker that an event was processed (one row per event key, a hash of kind, ref and system). Written before the actions run (status started), so an event is processed once across runs; the actions column holds the result of each action (and an attempting entry before an action runs), so a retry of a started event skips what was done or may have been done. A failed action is retried up to 3 runs, then failed_final. Ids and enums only.
-- primary key (enforced by the app, not by Delta): event_key
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`governance_event` (
  event_key STRING NOT NULL,
  kind STRING NOT NULL,
  severity STRING NOT NULL,
  agent_id STRING NOT NULL,
  system_id STRING,
  ref STRING NOT NULL,
  event_at TIMESTAMP NOT NULL,
  status STRING NOT NULL,
  rules STRING NOT NULL,
  actions STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  done_at TIMESTAMP,
  detail STRING,
  runner_id STRING,
  lease_until TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G5. The marker that an event was processed (one row per event key, a hash of kind, ref and system). Written before the actions run (status started), so an event is processed once across runs; the actions column holds the result of each action (and an attempting entry before an action runs), so a retry of a started event skips what was done or may have been done. A failed action is retried up to 3 runs, then failed_final. Ids and enums only.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- mcp_app (state): WP-G6. An application connected to the MCP server (a pipeline or an AI assistant). The first connection is pending until an admin approves it; a blocked app is refused at once. scopes lists what it may call (governance.read, governance.write, library.read, supervisor.read); roles are the console roles the app acts with (never admin), so its view of the AI systems is scoped like a person's. key_hash is the SHA-256 of the current HMAC secret (the secret itself lives in the WP20 key store under the app id). Every change is a console_action row; no free text from a client is stored here.
-- primary key (enforced by the app, not by Delta): app_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`mcp_app` (
  app_id STRING NOT NULL,
  name STRING NOT NULL,
  scopes STRING NOT NULL,
  roles STRING NOT NULL,
  created_by STRING NOT NULL,
  approved_by STRING,
  status STRING NOT NULL,
  key_hash STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  approved_at TIMESTAMP,
  first_connected_at TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G6. An application connected to the MCP server (a pipeline or an AI assistant). The first connection is pending until an admin approves it; a blocked app is refused at once. scopes lists what it may call (governance.read, governance.write, library.read, supervisor.read); roles are the console roles the app acts with (never admin), so its view of the AI systems is scoped like a person''s. key_hash is the SHA-256 of the current HMAC secret (the secret itself lives in the WP20 key store under the app id). Every change is a console_action row; no free text from a client is stored here.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- registration_draft (state): WP-N3. A half-finished registration of an AI system (register workflow v2, six steps). One row per person and attempt; data holds the answers, the suggestions with their reason keys and the source of each value. No evidence rows and no chain records: a draft is working state. submitted means the system was written; abandoned means the person dropped it.
-- primary key (enforced by the app, not by Delta): draft_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`registration_draft` (
  draft_id STRING NOT NULL,
  owner_user STRING NOT NULL,
  status STRING NOT NULL,
  step BIGINT NOT NULL,
  source_kind STRING NOT NULL,
  source_ref STRING,
  data STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-N3. A half-finished registration of an AI system (register workflow v2, six steps). One row per person and attempt; data holds the answers, the suggestions with their reason keys and the source of each value. No evidence rows and no chain records: a draft is working state. submitted means the system was written; abandoned means the person dropped it.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- guardian_binding (state): WP-S1. A product owner's switch for one guardian feature on one AI system: on or off. No row means on. A binding can only narrow what the instance already has on; the assignment rules' guardian floor always wins (a floor feature cannot be set off, and a floor added later overrides an old off row at resolution time). mandatory is the floor state when the row was written (a snapshot for the audit; resolution reads the floor again). Changes go on the chain as binding_change (ids and enums only).
-- primary key (enforced by the app, not by Delta): system_id, feature_slug
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`guardian_binding` (
  system_id STRING NOT NULL,
  feature_slug STRING NOT NULL,
  state STRING NOT NULL,
  mandatory BOOLEAN NOT NULL,
  set_by STRING NOT NULL,
  set_at TIMESTAMP NOT NULL,
  reason STRING,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-S1. A product owner''s switch for one guardian feature on one AI system: on or off. No row means on. A binding can only narrow what the instance already has on; the assignment rules'' guardian floor always wins (a floor feature cannot be set off, and a floor added later overrides an old off row at resolution time). mandatory is the floor state when the row was written (a snapshot for the audit; resolution reads the floor again). Changes go on the chain as binding_change (ids and enums only).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- guardian_off_request (state): WP-P2 (phase 8, CONSOLE_STATE_ACTIONS). A request to switch a guardian feature off on an AI system that is in production or has a high risk level. A second person, not the requester, approves or rejects it; only an approval writes the guardian_binding row. The reason is required. Changes go on the chain as binding_change (ids, enums and a reason hash).
-- primary key (enforced by the app, not by Delta): request_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`guardian_off_request` (
  request_id STRING NOT NULL,
  system_id STRING NOT NULL,
  feature_slug STRING NOT NULL,
  requested_by STRING NOT NULL,
  reason STRING NOT NULL,
  status STRING NOT NULL,
  decided_by STRING,
  decision_reason STRING,
  created_at TIMESTAMP NOT NULL,
  decided_at TIMESTAMP,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-P2 (phase 8, CONSOLE_STATE_ACTIONS). A request to switch a guardian feature off on an AI system that is in production or has a high risk level. A second person, not the requester, approves or rejects it; only an approval writes the guardian_binding row. The reason is required. Changes go on the chain as binding_change (ids, enums and a reason hash).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- intake_attempt (state): WP-O1 (phase 9, ONBOARD_INTAKE). One numbered intake of the source code of an inventory candidate or an agent: a zip upload, a clone or (later) a workspace folder. Re-upload makes attempt n+1; old attempts stay. The files are stored scrubbed under DATA_DIR/intake/<node_id>/<n>/ (the WP16 scrubber runs before anything is written); this row holds only the source reference (no secrets), the SHA-256 and size of what was received, the count of stored files and a counts-only detail note. status: scrubbed (stored after the scrub), failed (refused; detail has the code), stored (reserved).
-- primary key (enforced by the app, not by Delta): attempt_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`intake_attempt` (
  attempt_id STRING NOT NULL,
  node_id STRING NOT NULL,
  n BIGINT NOT NULL,
  source_kind STRING NOT NULL,
  source_ref STRING NOT NULL,
  sha256 STRING NOT NULL,
  size_bytes BIGINT NOT NULL,
  file_count BIGINT NOT NULL,
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  status STRING NOT NULL,
  detail STRING,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-O1 (phase 9, ONBOARD_INTAKE). One numbered intake of the source code of an inventory candidate or an agent: a zip upload, a clone or (later) a workspace folder. Re-upload makes attempt n+1; old attempts stay. The files are stored scrubbed under DATA_DIR/intake/<node_id>/<n>/ (the WP16 scrubber runs before anything is written); this row holds only the source reference (no secrets), the SHA-256 and size of what was received, the count of stored files and a counts-only detail note. status: scrubbed (stored after the scrub), failed (refused; detail has the code), stored (reserved).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- regkb_draft (state): WP-L1. A draft duty that the law agent read from the stored official text of one instrument, one row per draft. A draft is never an obligation: a person with regkb.confirm sets status confirmed or dropped. text_vi is a verbatim quote that the rules checked against the stored article text. source is model (the agent) or rule (a deterministic parser); model_id and prompt_version say which model and prompt wrote it (a mock model has mock in model_id). The CLI python -m supervisor.regkb.lawagent --export-confirmed turns confirmed rows into regulations YAML for a pull request; the app cannot edit repo files. No PII: law text only.
-- primary key (enforced by the app, not by Delta): draft_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`regkb_draft` (
  draft_id STRING NOT NULL,
  instrument_id STRING NOT NULL,
  article STRING NOT NULL,
  duty_id STRING NOT NULL,
  subject STRING NOT NULL,
  trigger STRING NOT NULL,
  evidence_asked STRING NOT NULL,
  text_vi STRING NOT NULL,
  summary_en STRING NOT NULL,
  source STRING NOT NULL,
  model_id STRING,
  prompt_version STRING,
  status STRING NOT NULL,
  confirmed_by STRING,
  confirmed_at TIMESTAMP,
  run_id STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-L1. A draft duty that the law agent read from the stored official text of one instrument, one row per draft. A draft is never an obligation: a person with regkb.confirm sets status confirmed or dropped. text_vi is a verbatim quote that the rules checked against the stored article text. source is model (the agent) or rule (a deterministic parser); model_id and prompt_version say which model and prompt wrote it (a mock model has mock in model_id). The CLI python -m supervisor.regkb.lawagent --export-confirmed turns confirmed rows into regulations YAML for a pull request; the app cannot edit repo files. No PII: law text only.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- obligation_status (state): WP-L2. One row per duty (RegKB obligation) that applies to one AI system, written by the Duties step of the register workflow v2 on submit. applies is the matrix answer (the step writes yes rows only); coverage says how well Supervisor controls cover the duty (full, partial, none, unknown); status is the work state (open, closed, waived). closing_control is a Supervisor control id or a bank manual control, set later (WP-L3). No PII, no free text from a person. Advisory only: not legal advice, bank counsel must confirm.
-- primary key (enforced by the app, not by Delta): status_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`obligation_status` (
  status_id STRING NOT NULL,
  system_id STRING NOT NULL,
  obligation_id STRING NOT NULL,
  instrument_id STRING NOT NULL,
  applies STRING NOT NULL,
  coverage STRING NOT NULL,
  status STRING NOT NULL,
  owner_user STRING NOT NULL,
  due_date DATE,
  closing_control STRING,
  note STRING,
  created_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-L2. One row per duty (RegKB obligation) that applies to one AI system, written by the Duties step of the register workflow v2 on submit. applies is the matrix answer (the step writes yes rows only); coverage says how well Supervisor controls cover the duty (full, partial, none, unknown); status is the work state (open, closed, waived). closing_control is a Supervisor control id or a bank manual control, set later (WP-L3). No PII, no free text from a person. Advisory only: not legal advice, bank counsel must confirm.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- onboard_facts (state): WP-O2 (phase 9, ONBOARD_FACTS). One fact about an agent or candidate, found by Discover and Understand on one stored intake attempt (the scrubbed tree): a tool, model, endpoint, dataset, file, secret use (kind only), external URL, MCP server, approval point, the autonomy level, the Decision 33 proposal or a weak spot. Every fact row has the file, the line and a scrubbed quote of at most 200 characters (no secret, no personal data). source is rule (deterministic) or model (a claim of the real gateway model that passed validate_llm_claims; model_id says which, and a mock model is named mock). A summary row (kind summary) per build counts the dropped_claims (model claims without evidence). Building again for the same attempt replaces that attempt's rows: a fact that is found again keeps its fact_id and is updated; a fact that is not found again gets active false (the state store has no delete). Readers use active rows only. kind claim holds the purpose, the personal data fields and the model claims that are not weak spots.
-- primary key (enforced by the app, not by Delta): fact_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`onboard_facts` (
  fact_id STRING NOT NULL,
  node_id STRING NOT NULL,
  attempt_n BIGINT NOT NULL,
  kind STRING NOT NULL,
  name STRING NOT NULL,
  detail STRING,
  file STRING,
  line BIGINT,
  quote STRING,
  source STRING NOT NULL,
  model_id STRING,
  dropped_claims BIGINT,
  active BOOLEAN NOT NULL,
  created_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-O2 (phase 9, ONBOARD_FACTS). One fact about an agent or candidate, found by Discover and Understand on one stored intake attempt (the scrubbed tree): a tool, model, endpoint, dataset, file, secret use (kind only), external URL, MCP server, approval point, the autonomy level, the Decision 33 proposal or a weak spot. Every fact row has the file, the line and a scrubbed quote of at most 200 characters (no secret, no personal data). source is rule (deterministic) or model (a claim of the real gateway model that passed validate_llm_claims; model_id says which, and a mock model is named mock). A summary row (kind summary) per build counts the dropped_claims (model claims without evidence). Building again for the same attempt replaces that attempt''s rows: a fact that is found again keeps its fact_id and is updated; a fact that is not found again gets active false (the state store has no delete). Readers use active rows only. kind claim holds the purpose, the personal data fields and the model claims that are not weak spots.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- predeploy_report (state): WP-O3 (phase 9, ONBOARD_PREDEPLOY). One pre-deploy assessment of one intake attempt of an inventory candidate or agent. It joins the facts card (onboard_facts), the readiness advisor, the assurance packs with launch_gate required (run in the launch sandbox with the gate in SHADOW and the synthetic world), the multi-turn red-team pack (advisory) and the duties matrix (when CONSOLE_REGISTER_DUTIES is on and a draft exists for the node). status: queued, running, done or failed (the run itself broke). verdict is deterministic from the items: no_go (a fail item in a required section), questions (a question item), go, or none (not finished). The model never sets it. items is a JSON list of {section, id, status ok | warn | fail | question | skip, text, pointer}; text is scrubbed, no personal data, integers only. A run on a mock agent says mock in the item text. A report is never updated after it is done; Run again writes a new report_id.
-- primary key (enforced by the app, not by Delta): report_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`predeploy_report` (
  report_id STRING NOT NULL,
  node_id STRING NOT NULL,
  attempt_n BIGINT NOT NULL,
  status STRING NOT NULL,
  verdict STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  items_total BIGINT NOT NULL,
  items_fail BIGINT NOT NULL,
  items_question BIGINT NOT NULL,
  summary STRING NOT NULL,
  items STRING NOT NULL,
  model_id STRING,
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-O3 (phase 9, ONBOARD_PREDEPLOY). One pre-deploy assessment of one intake attempt of an inventory candidate or agent. It joins the facts card (onboard_facts), the readiness advisor, the assurance packs with launch_gate required (run in the launch sandbox with the gate in SHADOW and the synthetic world), the multi-turn red-team pack (advisory) and the duties matrix (when CONSOLE_REGISTER_DUTIES is on and a draft exists for the node). status: queued, running, done or failed (the run itself broke). verdict is deterministic from the items: no_go (a fail item in a required section), questions (a question item), go, or none (not finished). The model never sets it. items is a JSON list of {section, id, status ok | warn | fail | question | skip, text, pointer}; text is scrubbed, no personal data, integers only. A run on a mock agent says mock in the item text. A report is never updated after it is done; Run again writes a new report_id.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- onboard_log (append_only): WP-O5 (phase 9, ONBOARD_POSTDEPLOY). The agent log: one row per onboarding action of a candidate or agent, shown in the console as a timeline "plan, read, found, suggest". step names the onboarding step: scan (the node became a candidate), intake (a source was taken in), facts, predeploy, attach, postdeploy, state (Request or Approve RUNNING) duties or orchestrate (WP-F4). by_kind says who did it: rule (deterministic code), model (the gateway model produced the content, a mock model says so in what) or person (actor is the person id). what is a short scrubbed sentence of at most 300 characters; pointer is where to look (file:line, report id, row id or pack id) at most 200 characters. Rows are never updated or deleted. No personal data, no secret, no float; counts are integers. A write failure never fails the action that was logged.
-- primary key (enforced by the app, not by Delta): log_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`onboard_log` (
  log_id STRING NOT NULL,
  node_id STRING NOT NULL,
  attempt_n BIGINT,
  step STRING NOT NULL,
  what STRING NOT NULL,
  pointer STRING NOT NULL,
  by_kind STRING NOT NULL,
  actor STRING NOT NULL,
  at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-O5 (phase 9, ONBOARD_POSTDEPLOY). The agent log: one row per onboarding action of a candidate or agent, shown in the console as a timeline "plan, read, found, suggest". step names the onboarding step: scan (the node became a candidate), intake (a source was taken in), facts, predeploy, attach, postdeploy, state (Request or Approve RUNNING) duties or orchestrate (WP-F4). by_kind says who did it: rule (deterministic code), model (the gateway model produced the content, a mock model says so in what) or person (actor is the person id). what is a short scrubbed sentence of at most 300 characters; pointer is where to look (file:line, report id, row id or pack id) at most 200 characters. Rows are never updated or deleted. No personal data, no secret, no float; counts are integers. A write failure never fails the action that was logged.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

-- risk_dimension_status (state): WP-C2 (phase 12, RISK_DIMENSIONS). One row per AI system and per risk type of Circular 53 Art. 14(3) (model, data_governance, cybersecurity, legal_compliance, ethics, third_party, supply_chain, reputation): the status of the assessment. status is not_started, in_progress, pass, fail, waived or not_applicable. pass needs at least one evidence pointer; waived needs a reason and a person who is not the system owner. evidence_json is a JSON list of pointers (pack result id, fact id, document id), never text from a person. threshold_json holds the bank threshold (integers and enums, no floats). note is masked and at most 300 characters. The service creates the eight rows the first time a system is read with the flag on. Every change writes a chain record risk_dimension_status. Advisory only: not legal advice, bank counsel must confirm.
-- primary key (enforced by the app, not by Delta): status_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`risk_dimension_status` (
  status_id STRING NOT NULL,
  system_id STRING NOT NULL,
  dimension_id STRING NOT NULL,
  status STRING NOT NULL,
  owner_team STRING,
  assessed_by STRING,
  report_ref STRING,
  evidence_json STRING NOT NULL,
  threshold_json STRING NOT NULL,
  note STRING,
  updated_by STRING NOT NULL,
  valid_until DATE,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-C2 (phase 12, RISK_DIMENSIONS). One row per AI system and per risk type of Circular 53 Art. 14(3) (model, data_governance, cybersecurity, legal_compliance, ethics, third_party, supply_chain, reputation): the status of the assessment. status is not_started, in_progress, pass, fail, waived or not_applicable. pass needs at least one evidence pointer; waived needs a reason and a person who is not the system owner. evidence_json is a JSON list of pointers (pack result id, fact id, document id), never text from a person. threshold_json holds the bank threshold (integers and enums, no floats). note is masked and at most 300 characters. The service creates the eight rows the first time a system is read with the flag on. Every change writes a chain record risk_dimension_status. Advisory only: not legal advice, bank counsel must confirm.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- classification_v2 (state): WP-C1 (phase 12, CLASSIFICATION_V2). One record of the classification tree (config/classification.yaml) for one AI system: the path from the first question to an outcome (not_system, prohibited, high_certify, high_self, medium, low), decided by a person and approved by a different person (Circular 53 Art. 4(3)). path_json is a JSON list of steps {node, answer, source (rules | person | decision33), evidence (a pointer: file:line, table row id or document id, at most 200 characters), note (at most 300 characters, masked)}; a step of the Decision 33 sub-flow also carries the answers of its questions. No personal data, no floats. inherited_from_provider: the bank took the provider's result (Art. 4(4)). valid_until: the yearly review date (Art. 4(5)), set again at approval. approved_by and approved_at are null until a second person approves; only then does the risk level of the system change (floor rule, never lowers). Changes go on the chain as classification_v2.
-- primary key (enforced by the app, not by Delta): classification_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`classification_v2` (
  classification_id STRING NOT NULL,
  system_id STRING NOT NULL,
  outcome STRING NOT NULL,
  path_json STRING NOT NULL,
  tree_sha256 STRING NOT NULL,
  path_hash STRING NOT NULL,
  decided_by STRING NOT NULL,
  approved_by STRING,
  approved_at TIMESTAMP,
  inherited_from_provider BOOLEAN NOT NULL,
  valid_until TIMESTAMP NOT NULL,
  created_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-C1 (phase 12, CLASSIFICATION_V2). One record of the classification tree (config/classification.yaml) for one AI system: the path from the first question to an outcome (not_system, prohibited, high_certify, high_self, medium, low), decided by a person and approved by a different person (Circular 53 Art. 4(3)). path_json is a JSON list of steps {node, answer, source (rules | person | decision33), evidence (a pointer: file:line, table row id or document id, at most 200 characters), note (at most 300 characters, masked)}; a step of the Decision 33 sub-flow also carries the answers of its questions. No personal data, no floats. inherited_from_provider: the bank took the provider''s result (Art. 4(4)). valid_until: the yearly review date (Art. 4(5)), set again at approval. approved_by and approved_at are null until a second person approves; only then does the risk level of the system change (floor rule, never lowers). Changes go on the chain as classification_v2.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- orchestrator_run (state): WP-F4 (phase 12, ONBOARD_ORCHESTRATOR). One run of the onboarding orchestrator for one AI system: it plans which of the eight risk types of Circular 53 Art. 14(3) apply and which agent assesses each (a live factory agent, else the rule proposal of risk_dimensions), runs them in order under a time and token budget, writes one assessment_report_v1 per type under DATA_DIR/assessments/<system>/<attempt>/ and a proposal into risk_dimension_status (never pass: a person confirms). status: queued, running, done or failed (the run itself broke). The orchestrator has no model call of its own and decides by deterministic rules only. plan_json is the plan (dimensions, reasons, agents, order, budget); budget_json holds the budget and what was used (integers); items_json is a JSON list with one entry per type {dimension_id, order, applies, reason, agent (rule or id@version), status (queued, running, done, needs_person, budget_exceeded, failed, not_applicable, skipped), verdict, proposed_status, status_written, report_ref, report_sha256, stop_point, needs_person, ms_used, tokens_used, note}. No personal data, no floats. A re-run is a new attempt_n and a new run_id.
-- primary key (enforced by the app, not by Delta): run_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`orchestrator_run` (
  run_id STRING NOT NULL,
  system_id STRING NOT NULL,
  attempt_n BIGINT NOT NULL,
  plan_json STRING NOT NULL,
  plan_hash STRING NOT NULL,
  status STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  budget_json STRING NOT NULL,
  items_json STRING NOT NULL,
  summary STRING NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-F4 (phase 12, ONBOARD_ORCHESTRATOR). One run of the onboarding orchestrator for one AI system: it plans which of the eight risk types of Circular 53 Art. 14(3) apply and which agent assesses each (a live factory agent, else the rule proposal of risk_dimensions), runs them in order under a time and token budget, writes one assessment_report_v1 per type under DATA_DIR/assessments/<system>/<attempt>/ and a proposal into risk_dimension_status (never pass: a person confirms). status: queued, running, done or failed (the run itself broke). The orchestrator has no model call of its own and decides by deterministic rules only. plan_json is the plan (dimensions, reasons, agents, order, budget); budget_json holds the budget and what was used (integers); items_json is a JSON list with one entry per type {dimension_id, order, applies, reason, agent (rule or id@version), status (queued, running, done, needs_person, budget_exceeded, failed, not_applicable, skipped), verdict, proposed_status, status_written, report_ref, report_sha256, stop_point, needs_person, ms_used, tokens_used, note}. No personal data, no floats. A re-run is a new attempt_n and a new run_id.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- guardian_def (state): WP-G1. One row per version of a guardian definition (a detector described as data: regex, keyword_list, classifier, judge_prompt or policy). definition_json is the validated definition (config/guardian definition schema, docs/guardian-factory.md): the rule text, the scope and the thresholds; it holds no personal data and no floats (rates are integer percent, scores integer basis points). state is draft, benchmarked, shadow, approved, live or retired; in WP-G1 only draft and retired are reachable (the others belong to WP-G2 and WP-G3). A saved version is replaced in place only while it is a draft; a new version is a new row. Changes go on the chain as guardian_def (ids, enums, hashes).
-- primary key (enforced by the app, not by Delta): def_id, version
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`guardian_def` (
  def_id STRING NOT NULL,
  version BIGINT NOT NULL,
  owner_group STRING NOT NULL,
  type STRING NOT NULL,
  stage STRING NOT NULL,
  definition_json STRING NOT NULL,
  state STRING NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G1. One row per version of a guardian definition (a detector described as data: regex, keyword_list, classifier, judge_prompt or policy). definition_json is the validated definition (config/guardian definition schema, docs/guardian-factory.md): the rule text, the scope and the thresholds; it holds no personal data and no floats (rates are integer percent, scores integer basis points). state is draft, benchmarked, shadow, approved, live or retired; in WP-G1 only draft and retired are reachable (the others belong to WP-G2 and WP-G3). A saved version is replaced in place only while it is a draft; a new version is a new row. Changes go on the chain as guardian_def (ids, enums, hashes).'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- guardian_def_event (append_only): WP-G1. One row per change of a guardian definition: created, saved, new_version, retired, reopened (and, from WP-G2 and WP-G3, the later state changes). def_sha256 is the hash of the canonical definition after the change; no definition text, no personal data.
-- primary key (enforced by the app, not by Delta): event_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`guardian_def_event` (
  event_id STRING NOT NULL,
  def_id STRING NOT NULL,
  version BIGINT NOT NULL,
  action STRING NOT NULL,
  from_state STRING,
  to_state STRING NOT NULL,
  actor STRING NOT NULL,
  def_sha256 STRING NOT NULL,
  at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G1. One row per change of a guardian definition: created, saved, new_version, retired, reopened (and, from WP-G2 and WP-G3, the later state changes). def_sha256 is the hash of the canonical definition after the change; no definition text, no personal data.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

-- regkb_internal_doc (state): WP-W3 (phase 11, REGKB_INTERNAL). One internal document (policy, standard, procedure) that a person uploaded to RegKB. The raw text and the masked text sit under DATA_DIR/regkb/internal/<doc_id>/ (text.txt, text.masked.txt, .meta.json); only the masked text goes to the gateway model. status: uploaded, drafted (the law agent wrote drafts into regkb_draft with instrument_id VN-INT-<doc_id>), confirmed (a person with regkb.confirm accepted at least one row, so instrument.yaml exists) or retired. sha256 is the hash of the raw text file. No personal data in this row: title and owner_group are masked on upload.
-- primary key (enforced by the app, not by Delta): doc_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`regkb_internal_doc` (
  doc_id STRING NOT NULL,
  title STRING NOT NULL,
  owner_group STRING NOT NULL,
  version_label STRING NOT NULL,
  sha256 STRING NOT NULL,
  status STRING NOT NULL,
  uploaded_by STRING NOT NULL,
  uploaded_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-W3 (phase 11, REGKB_INTERNAL). One internal document (policy, standard, procedure) that a person uploaded to RegKB. The raw text and the masked text sit under DATA_DIR/regkb/internal/<doc_id>/ (text.txt, text.masked.txt, .meta.json); only the masked text goes to the gateway model. status: uploaded, drafted (the law agent wrote drafts into regkb_draft with instrument_id VN-INT-<doc_id>), confirmed (a person with regkb.confirm accepted at least one row, so instrument.yaml exists) or retired. sha256 is the hash of the raw text file. No personal data in this row: title and owner_group are masked on upload.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- factory_agent (state): WP-F2 (phase 12B, AGENT_FACTORY). One row per version of an assessment agent definition (docs/factory.md). definition_json is the agent_definition_v1 document, validated on every save; it holds no personal data and no float. state is draft or retired in WP-F2 (tested, approved and live belong to WP-F3). A version other than draft is not edited; a change makes a new version. owner_group is a group of config/factory_groups.yaml and owns dimension_id.
-- primary key (enforced by the app, not by Delta): id, version
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`factory_agent` (
  id STRING NOT NULL,
  version STRING NOT NULL,
  owner_group STRING NOT NULL,
  dimension_id STRING NOT NULL,
  definition_json STRING NOT NULL,
  state STRING NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-F2 (phase 12B, AGENT_FACTORY). One row per version of an assessment agent definition (docs/factory.md). definition_json is the agent_definition_v1 document, validated on every save; it holds no personal data and no float. state is draft or retired in WP-F2 (tested, approved and live belong to WP-F3). A version other than draft is not edited; a change makes a new version. owner_group is a group of config/factory_groups.yaml and owns dimension_id.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- factory_agent_event (append_only): WP-F2 (phase 12B, AGENT_FACTORY). Append-only log of every change of an agent version in the factory: created, saved, new_version, retired, helper rows accepted or dropped, golden set uploaded. detail is a masked sentence of at most 300 characters. Rows are never updated or deleted. No personal data, no float.
-- primary key (enforced by the app, not by Delta): event_id
-- append-only: delta.appendOnly blocks UPDATE/DELETE. Owner to set history retention (logRetentionDuration) to the legal period; never VACUUM below it.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`factory_agent_event` (
  event_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  version STRING NOT NULL,
  kind STRING NOT NULL,
  actor_ref STRING NOT NULL,
  detail STRING NOT NULL,
  created_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-F2 (phase 12B, AGENT_FACTORY). Append-only log of every change of an agent version in the factory: created, saved, new_version, retired, helper rows accepted or dropped, golden set uploaded. detail is a masked sentence of at most 300 characters. Rows are never updated or deleted. No personal data, no float.'
TBLPROPERTIES ('delta.appendOnly' = 'true', 'supervisor.kind' = 'append_only');

-- factory_helper_draft (state): WP-F2 (phase 12B, AGENT_FACTORY). A row proposed by a helper agent (checklist_drafter, golden_generator, result_explainer) through the gateway model. A draft is never part of an agent: a person accepts or drops each row. row_json is the proposed row (a checklist item, a golden case or an explanation sentence with its pointers). A golden case that trips the masker is refused and never stored. No personal data, no float.
-- primary key (enforced by the app, not by Delta): draft_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`factory_helper_draft` (
  draft_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  version STRING NOT NULL,
  helper STRING NOT NULL,
  row_json STRING NOT NULL,
  status STRING NOT NULL,
  model_id STRING NOT NULL,
  prompt_version STRING NOT NULL,
  run_id STRING NOT NULL,
  decided_by STRING,
  decided_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-F2 (phase 12B, AGENT_FACTORY). A row proposed by a helper agent (checklist_drafter, golden_generator, result_explainer) through the gateway model. A draft is never part of an agent: a person accepts or drops each row. row_json is the proposed row (a checklist item, a golden case or an explanation sentence with its pointers). A golden case that trips the masker is refused and never stored. No personal data, no float.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- guardian_bench_run (state): WP-G2. One row per benchmark run of a guardian definition (docs/guardian-factory.md, section Benchmark). The run is a background job: queued, running, then done or failed. result_json holds integers only (counts per sensitivity level, true and false positive rate in integer percent, p50 and p95 latency in microseconds, token cost, the live detector row, the gate); it holds no case text and no personal data. gate is pass, fail or not_run; failing_threshold names the thresholds that failed (min_tpr_pct, max_fpr_pct, max_p95_ms, comma separated). def_sha256 is the hash of the definition without its lifecycle: a pass counts for a transition to benchmarked only for the same version and the same hash. Each finished run also goes on the chain as guardian_bench.
-- primary key (enforced by the app, not by Delta): run_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`guardian_bench_run` (
  run_id STRING NOT NULL,
  def_id STRING NOT NULL,
  version BIGINT NOT NULL,
  pack_id STRING NOT NULL,
  pack_sha256 STRING NOT NULL,
  def_sha256 STRING NOT NULL,
  status STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  result_json STRING NOT NULL,
  gate STRING NOT NULL,
  failing_threshold STRING,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G2. One row per benchmark run of a guardian definition (docs/guardian-factory.md, section Benchmark). The run is a background job: queued, running, then done or failed. result_json holds integers only (counts per sensitivity level, true and false positive rate in integer percent, p50 and p95 latency in microseconds, token cost, the live detector row, the gate); it holds no case text and no personal data. gate is pass, fail or not_run; failing_threshold names the thresholds that failed (min_tpr_pct, max_fpr_pct, max_p95_ms, comma separated). def_sha256 is the hash of the definition without its lifecycle: a pass counts for a transition to benchmarked only for the same version and the same hash. Each finished run also goes on the chain as guardian_bench.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- gate_run (state): WP-F3 (phase 12B, AGENT_FACTORY_GATE). One run of the test gate for one version of a factory agent. kind: full (layers 1, 2 and 3; the only kind that can lead to state tested), sample (layers 1 and 2 on a small batch; never promotes), simulation (the draft on chosen systems of the inventory, assessed by a person in a review screen; never promotes) or shadow (layer 3 only). status: queued, running, done or failed (the run itself broke). verdict: pass, fail or not_run. layer1_json is the deterministic layer (checks and the harness component tests), layer2_json the guideline judges with the calibration (Cohen's kappa in hundredths, the confusion matrix, the paired comparison with the live version), layer3_json the shadow run (agreement counts). cost_json holds integers (model calls, estimated tokens, seconds). report_sha256 and signature belong to the signed JSON report on disk under DATA_DIR/factory/<agent>/gate/<run_id>/ (evidence signer). Integers only: no floats, no personal data, no text of a document.
-- primary key (enforced by the app, not by Delta): run_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`gate_run` (
  run_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  version STRING NOT NULL,
  kind STRING NOT NULL,
  status STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  layer1_json STRING NOT NULL,
  layer2_json STRING NOT NULL,
  layer3_json STRING NOT NULL,
  cost_json STRING NOT NULL,
  verdict STRING NOT NULL,
  report_sha256 STRING,
  signature STRING,
  definition_sha256 STRING NOT NULL,
  created_by STRING NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-F3 (phase 12B, AGENT_FACTORY_GATE). One run of the test gate for one version of a factory agent. kind: full (layers 1, 2 and 3; the only kind that can lead to state tested), sample (layers 1 and 2 on a small batch; never promotes), simulation (the draft on chosen systems of the inventory, assessed by a person in a review screen; never promotes) or shadow (layer 3 only). status: queued, running, done or failed (the run itself broke). verdict: pass, fail or not_run. layer1_json is the deterministic layer (checks and the harness component tests), layer2_json the guideline judges with the calibration (Cohen''s kappa in hundredths, the confusion matrix, the paired comparison with the live version), layer3_json the shadow run (agreement counts). cost_json holds integers (model calls, estimated tokens, seconds). report_sha256 and signature belong to the signed JSON report on disk under DATA_DIR/factory/<agent>/gate/<run_id>/ (evidence signer). Integers only: no floats, no personal data, no text of a document.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- guardian_shadow_finding (state): WP-G3 (GUARDIAN_FACTORY + GUARDIAN_SHADOW). One finding of a guardian definition in state shadow, found on live gate traffic in log-only mode. Nothing was blocked or redacted. call_ref is the correlation or request id of the call; value_hash is the SHA-256 digest of the finding (ids, code, integers and fragment digests), never the masked value text. count is the number of matches. would_action is the action_on_fail the guardian would take once live. reviewed is empty (not yet), correct (a true finding) or false (a false positive); a person sets it with reviewed_by. No personal data, no floats.
-- primary key (enforced by the app, not by Delta): finding_id
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`guardian_shadow_finding` (
  finding_id STRING NOT NULL,
  def_id STRING NOT NULL,
  version BIGINT NOT NULL,
  agent_id STRING NOT NULL,
  call_ref STRING NOT NULL,
  stage STRING NOT NULL,
  finding_code STRING NOT NULL,
  count BIGINT NOT NULL,
  value_hash STRING NOT NULL,
  would_action STRING NOT NULL,
  reviewed STRING,
  reviewed_by STRING,
  created_at TIMESTAMP NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G3 (GUARDIAN_FACTORY + GUARDIAN_SHADOW). One finding of a guardian definition in state shadow, found on live gate traffic in log-only mode. Nothing was blocked or redacted. call_ref is the correlation or request id of the call; value_hash is the SHA-256 digest of the finding (ids, code, integers and fragment digests), never the masked value text. count is the number of matches. would_action is the action_on_fail the guardian would take once live. reviewed is empty (not yet), correct (a true finding) or false (a false positive); a person sets it with reviewed_by. No personal data, no floats.'
TBLPROPERTIES ('supervisor.kind' = 'state');

-- guardian_shadow_day (state): WP-G3. One row per guardian version and UTC day of its shadow run: calls in scope, calls with a finding that would act (would_act), calls where the shadow detector was skipped because the latency budget was used (skipped_budget) and findings written. Integers only. A daily job writes one guardian_shadow_day chain record per closed day (chained).
-- primary key (enforced by the app, not by Delta): def_id, version, day
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`guardian_shadow_day` (
  def_id STRING NOT NULL,
  version BIGINT NOT NULL,
  day STRING NOT NULL,
  calls_seen BIGINT NOT NULL,
  would_act BIGINT NOT NULL,
  skipped_budget BIGINT NOT NULL,
  findings_n BIGINT NOT NULL,
  chained BOOLEAN NOT NULL,
  row_version BIGINT NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
COMMENT 'WP-G3. One row per guardian version and UTC day of its shadow run: calls in scope, calls with a finding that would act (would_act), calls where the shadow detector was skipped because the latency budget was used (skipped_budget) and findings written. Integers only. A daily job writes one guardian_shadow_day chain record per closed day (chained).'
TBLPROPERTIES ('supervisor.kind' = 'state');
