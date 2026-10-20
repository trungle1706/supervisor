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
  mask_version STRING
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
  rubric_version STRING
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
