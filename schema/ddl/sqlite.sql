-- GENERATED from schema/model.yaml (version 1). Do not edit.
-- Regenerate: uv run python -m schema.generate
-- Dialect: sqlite

-- schema_version (state): Applied versions of this model.
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL,
  applied_at TEXT NOT NULL,
  model_hash TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (version)
);

-- agent (state): Registry of supervised agents (one row per agent).
CREATE TABLE IF NOT EXISTS agent (
  agent_id TEXT NOT NULL,
  name TEXT NOT NULL,
  owner_team TEXT NOT NULL,
  owner_user TEXT NOT NULL,
  business_owner TEXT,
  risk_tier TEXT NOT NULL,
  decision33_class TEXT,
  host_type TEXT NOT NULL,
  plug_point TEXT NOT NULL,
  model_family TEXT NOT NULL,
  status TEXT NOT NULL,
  gate_state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (agent_id)
);

-- agent_version (append_only): Deployed versions of an agent. Drift bands tie to a version.
CREATE TABLE IF NOT EXISTS agent_version (
  agent_id TEXT NOT NULL,
  version TEXT NOT NULL,
  code_ref TEXT,
  prompt_hash TEXT,
  tool_manifest_hash TEXT,
  model_endpoint TEXT,
  model_family TEXT NOT NULL,
  deployed_at TEXT NOT NULL,
  baseline_id TEXT,
  PRIMARY KEY (agent_id, version)
);

CREATE TRIGGER IF NOT EXISTS trg_agent_version_no_update
BEFORE UPDATE ON agent_version
BEGIN
  SELECT RAISE(ABORT, 'agent_version is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_agent_version_no_delete
BEFORE DELETE ON agent_version
BEGIN
  SELECT RAISE(ABORT, 'agent_version is append-only');
END;

-- identity_binding (state): How a black-box agent is recognised (header, SP, key hash).
CREATE TABLE IF NOT EXISTS identity_binding (
  agent_id TEXT NOT NULL,
  binding_type TEXT NOT NULL,
  binding_hash TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (agent_id, binding_type, binding_hash)
);

-- coverage (state): Which monitoring capabilities are on for each agent, and why not.
CREATE TABLE IF NOT EXISTS coverage (
  agent_id TEXT NOT NULL,
  capability_id TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (agent_id, capability_id)
);

-- agent_event (append_only): Normalised OTel-shaped events. Single read model for Watch. Masked only.
CREATE TABLE IF NOT EXISTS agent_event (
  event_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  span_id TEXT NOT NULL,
  parent_span_id TEXT,
  agent_id TEXT NOT NULL,
  agent_version TEXT,
  caller_agent_id TEXT,
  event_type TEXT NOT NULL,
  tool_name TEXT,
  args_hash TEXT,
  args_masked TEXT,
  result_masked TEXT,
  amount_minor INTEGER,
  currency TEXT,
  status TEXT,
  latency_ms INTEGER,
  env TEXT NOT NULL,
  classification TEXT,
  source TEXT NOT NULL,
  capture_level TEXT NOT NULL,
  mask_version TEXT,
  latency_us INTEGER,
  verdict_status TEXT,
  correlation_id TEXT,
  coverage_json TEXT,
  session_id TEXT,
  session_source TEXT,
  session_json TEXT,
  request_id TEXT,
  consumer_id TEXT,
  latency_rules_us INTEGER,
  latency_detectors_us INTEGER,
  detector_latency_json TEXT,
  PRIMARY KEY (event_id)
);

CREATE INDEX IF NOT EXISTS ix_agent_event_agent_id_ts ON agent_event (agent_id, ts);

CREATE INDEX IF NOT EXISTS ix_agent_event_trace_id ON agent_event (trace_id);

DROP TRIGGER IF EXISTS trg_agent_event_no_update;

CREATE TRIGGER trg_agent_event_no_update
BEFORE UPDATE OF event_id, ts, trace_id, span_id, parent_span_id, agent_id, agent_version, caller_agent_id, event_type, tool_name, args_hash, amount_minor, currency, status, latency_ms, env, classification, source, capture_level, mask_version, latency_us, verdict_status, correlation_id, coverage_json, session_id, session_source, session_json, request_id, consumer_id, latency_rules_us, latency_detectors_us, detector_latency_json ON agent_event
BEGIN
  SELECT RAISE(ABORT, 'agent_event is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_agent_event_retention_null_only
BEFORE UPDATE OF args_masked, result_masked ON agent_event
WHEN NEW.args_masked IS NOT NULL OR NEW.result_masked IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'agent_event is append-only: retention may only set NULL');
END;

CREATE TRIGGER IF NOT EXISTS trg_agent_event_no_delete
BEFORE DELETE ON agent_event
BEGIN
  SELECT RAISE(ABORT, 'agent_event is append-only');
END;

-- agent_event_raw (append_only): RESTRICTED. Unmasked args/result text for agents whose manifest allows capture level raw (capture.raw_allowed). Restricted group only, short TTL (raw 90 d). Never read by judges or the chain. Rows link to agent_event by event_id.
CREATE TABLE IF NOT EXISTS agent_event_raw (
  event_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  args_raw TEXT,
  result_raw TEXT,
  access_class TEXT NOT NULL,
  PRIMARY KEY (event_id)
);

CREATE INDEX IF NOT EXISTS ix_agent_event_raw_agent_id_ts ON agent_event_raw (agent_id, ts);

DROP TRIGGER IF EXISTS trg_agent_event_raw_no_update;

CREATE TRIGGER trg_agent_event_raw_no_update
BEFORE UPDATE OF event_id, ts, trace_id, agent_id, access_class ON agent_event_raw
BEGIN
  SELECT RAISE(ABORT, 'agent_event_raw is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_agent_event_raw_retention_null_only
BEFORE UPDATE OF args_raw, result_raw ON agent_event_raw
WHEN NEW.args_raw IS NOT NULL OR NEW.result_raw IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'agent_event_raw is append-only: retention may only set NULL');
END;

CREATE TRIGGER IF NOT EXISTS trg_agent_event_raw_no_delete
BEFORE DELETE ON agent_event_raw
BEGIN
  SELECT RAISE(ABORT, 'agent_event_raw is append-only');
END;

-- trace_coverage (append_only): What each trace input path can see per agent (WP4). A proxy-log agent gets capability reduced with the list of missing fields. One row per agent, source and capability.
CREATE TABLE IF NOT EXISTS trace_coverage (
  coverage_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  source TEXT NOT NULL,
  capability TEXT NOT NULL,
  missing TEXT NOT NULL,
  note TEXT,
  PRIMARY KEY (coverage_id)
);

CREATE TRIGGER IF NOT EXISTS trg_trace_coverage_no_update
BEFORE UPDATE ON trace_coverage
BEGIN
  SELECT RAISE(ABORT, 'trace_coverage is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_trace_coverage_no_delete
BEFORE DELETE ON trace_coverage
BEGIN
  SELECT RAISE(ABORT, 'trace_coverage is append-only');
END;

-- rule (state): Deployed copy of policy rules (git is the source).
CREATE TABLE IF NOT EXISTS rule (
  rule_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  agent_scope TEXT NOT NULL,
  expression TEXT NOT NULL,
  action TEXT NOT NULL,
  fail_mode TEXT NOT NULL,
  severity TEXT NOT NULL,
  regulation_ref TEXT,
  owner TEXT NOT NULL,
  approved_by_1 TEXT,
  approved_by_2 TEXT,
  git_sha TEXT,
  policy_hash TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (rule_id, version)
);

-- verdict (append_only): One row per check outcome (rule, Tier 1 or Tier 2 judge). Judges are advisory.
CREATE TABLE IF NOT EXISTS verdict (
  verdict_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  trace_id TEXT,
  event_id TEXT,
  agent_id TEXT NOT NULL,
  tier INTEGER NOT NULL,
  checker_id TEXT NOT NULL,
  model_id TEXT,
  model_family TEXT,
  is_mock INTEGER NOT NULL,
  advisory INTEGER NOT NULL,
  score REAL,
  label TEXT NOT NULL,
  action TEXT NOT NULL,
  latency_ms INTEGER,
  rule_id TEXT,
  policy_hash TEXT,
  rationale_masked TEXT,
  score_bp INTEGER,
  role TEXT,
  region TEXT,
  model_version TEXT,
  mask_version TEXT,
  prompt_hash TEXT,
  rubric_version TEXT,
  family_source TEXT,
  PRIMARY KEY (verdict_id)
);

CREATE INDEX IF NOT EXISTS ix_verdict_agent_id_ts ON verdict (agent_id, ts);

CREATE INDEX IF NOT EXISTS ix_verdict_trace_id ON verdict (trace_id);

DROP TRIGGER IF EXISTS trg_verdict_no_update;

CREATE TRIGGER trg_verdict_no_update
BEFORE UPDATE OF verdict_id, ts, trace_id, event_id, agent_id, tier, checker_id, model_id, model_family, is_mock, advisory, score, label, action, latency_ms, rule_id, policy_hash, score_bp, role, region, model_version, mask_version, prompt_hash, rubric_version, family_source ON verdict
BEGIN
  SELECT RAISE(ABORT, 'verdict is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_verdict_retention_null_only
BEFORE UPDATE OF rationale_masked ON verdict
WHEN NEW.rationale_masked IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'verdict is append-only: retention may only set NULL');
END;

CREATE TRIGGER IF NOT EXISTS trg_verdict_no_delete
BEFORE DELETE ON verdict
BEGIN
  SELECT RAISE(ABORT, 'verdict is append-only');
END;

-- cases (state): Case header (mutable workflow state). Every change also writes case_event.
CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  assignee TEXT,
  itsm_ref TEXT,
  regulation_refs TEXT NOT NULL,
  summary TEXT NOT NULL,
  report_due_at TEXT,
  closed_at TEXT,
  case_type TEXT,
  incident_detected_at TEXT,
  urgency_class TEXT,
  prelim_report_due_at TEXT,
  formal_report_due_at TEXT,
  prelim_report_sent_at TEXT,
  formal_report_sent_at TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (case_id)
);

CREATE INDEX IF NOT EXISTS ix_cases_agent_id_status ON cases (agent_id, status);

-- case_event (append_only): Who did what on a case. Feeds the evidence chain.
CREATE TABLE IF NOT EXISTS case_event (
  case_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  actor_kind TEXT NOT NULL,
  action TEXT NOT NULL,
  comment_masked TEXT,
  auth_method TEXT,
  PRIMARY KEY (case_id, seq)
);

DROP TRIGGER IF EXISTS trg_case_event_no_update;

CREATE TRIGGER trg_case_event_no_update
BEFORE UPDATE OF case_id, seq, ts, actor, actor_kind, action, auth_method ON case_event
BEGIN
  SELECT RAISE(ABORT, 'case_event is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_case_event_retention_null_only
BEFORE UPDATE OF comment_masked ON case_event
WHEN NEW.comment_masked IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'case_event is append-only: retention may only set NULL');
END;

CREATE TRIGGER IF NOT EXISTS trg_case_event_no_delete
BEFORE DELETE ON case_event
BEGIN
  SELECT RAISE(ABORT, 'case_event is append-only');
END;

-- case_link (append_only): WP8. Which source opened or joined a case: a gate decision (block/pause), a judge verdict (CaseRequest) or a monitor finding. One row per source; makes intake idempotent.
CREATE TABLE IF NOT EXISTS case_link (
  source_kind TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  case_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  PRIMARY KEY (source_kind, source_ref)
);

CREATE INDEX IF NOT EXISTS ix_case_link_case_id ON case_link (case_id);

CREATE TRIGGER IF NOT EXISTS trg_case_link_no_update
BEFORE UPDATE ON case_link
BEGIN
  SELECT RAISE(ABORT, 'case_link is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_case_link_no_delete
BEFORE DELETE ON case_link
BEGIN
  SELECT RAISE(ABORT, 'case_link is append-only');
END;

-- signoff (append_only): Human sign-off. Reviewer id from SSO, never the app service principal.
CREATE TABLE IF NOT EXISTS signoff (
  signoff_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  reviewer_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  ts TEXT NOT NULL,
  auth_method TEXT NOT NULL,
  PRIMARY KEY (signoff_id)
);

CREATE INDEX IF NOT EXISTS ix_signoff_case_id ON signoff (case_id);

CREATE TRIGGER IF NOT EXISTS trg_signoff_no_update
BEFORE UPDATE ON signoff
BEGIN
  SELECT RAISE(ABORT, 'signoff is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_signoff_no_delete
BEFORE DELETE ON signoff
BEGIN
  SELECT RAISE(ABORT, 'signoff is append-only');
END;

-- chain_entry (append_only): Hash chain. One lane per agent plus the root lane. PII never enters.
CREATE TABLE IF NOT EXISTS chain_entry (
  lane TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts TEXT NOT NULL,
  record_type TEXT NOT NULL,
  record_ref TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  entry_hash TEXT NOT NULL,
  writer TEXT NOT NULL,
  env TEXT NOT NULL,
  PRIMARY KEY (lane, seq)
);

CREATE TRIGGER IF NOT EXISTS trg_chain_entry_no_update
BEFORE UPDATE ON chain_entry
BEGIN
  SELECT RAISE(ABORT, 'chain_entry is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_chain_entry_no_delete
BEFORE DELETE ON chain_entry
BEGIN
  SELECT RAISE(ABORT, 'chain_entry is append-only');
END;

-- chain_payload (append_only): Masked canonical JSON payload of a chain entry (no floats, no raw PII).
CREATE TABLE IF NOT EXISTS chain_payload (
  lane TEXT NOT NULL,
  seq INTEGER NOT NULL,
  payload_hash TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (lane, seq, payload_hash)
);

CREATE TRIGGER IF NOT EXISTS trg_chain_payload_no_update
BEFORE UPDATE ON chain_payload
BEGIN
  SELECT RAISE(ABORT, 'chain_payload is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_chain_payload_no_delete
BEFORE DELETE ON chain_payload
BEGIN
  SELECT RAISE(ABORT, 'chain_payload is append-only');
END;

-- chain_signature (append_only): Signature over the entry_hash of a root-lane entry (signed head).
CREATE TABLE IF NOT EXISTS chain_signature (
  lane TEXT NOT NULL,
  seq INTEGER NOT NULL,
  entry_hash TEXT NOT NULL,
  signature TEXT NOT NULL,
  key_id TEXT NOT NULL,
  algorithm TEXT NOT NULL,
  key_kind TEXT NOT NULL,
  public_key TEXT NOT NULL,
  PRIMARY KEY (lane, seq, entry_hash)
);

CREATE TRIGGER IF NOT EXISTS trg_chain_signature_no_update
BEFORE UPDATE ON chain_signature
BEGIN
  SELECT RAISE(ABORT, 'chain_signature is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_chain_signature_no_delete
BEFORE DELETE ON chain_signature
BEGIN
  SELECT RAISE(ABORT, 'chain_signature is append-only');
END;

-- anchor (append_only): Signed chain heads anchored to an immutable target.
CREATE TABLE IF NOT EXISTS anchor (
  anchor_id TEXT NOT NULL,
  lane TEXT NOT NULL,
  seq_from INTEGER NOT NULL,
  seq_to INTEGER NOT NULL,
  root_hash TEXT NOT NULL,
  head_signature TEXT NOT NULL,
  key_id TEXT NOT NULL,
  anchored_at TEXT NOT NULL,
  anchor_target TEXT NOT NULL,
  receipt TEXT,
  PRIMARY KEY (anchor_id)
);

CREATE TRIGGER IF NOT EXISTS trg_anchor_no_update
BEFORE UPDATE ON anchor
BEGIN
  SELECT RAISE(ABORT, 'anchor is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_anchor_no_delete
BEFORE DELETE ON anchor
BEGIN
  SELECT RAISE(ABORT, 'anchor is append-only');
END;

-- oversight_metric (state): Daily oversight metrics per agent. Feeds the console panel.
CREATE TABLE IF NOT EXISTS oversight_metric (
  metric_date TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  coverage REAL,
  ttd_ms INTEGER,
  tth_s INTEGER,
  catch_rate REAL,
  false_alarm_rate REAL,
  chain_ok INTEGER,
  groundedness REAL,
  fairness_gap REAL,
  computed_at TEXT NOT NULL,
  events_seen INTEGER,
  events_gated INTEGER,
  coverage_bp INTEGER,
  catch_rate_bp INTEGER,
  false_alarm_bp INTEGER,
  judge_verdicts INTEGER,
  judge_disagree_bp INTEGER,
  groundedness_bp INTEGER,
  fairness_gap_bp INTEGER,
  cases_opened INTEGER,
  blocks INTEGER,
  llm_calls INTEGER,
  judge_latency_ms INTEGER,
  judge_human_pairs INTEGER,
  judge_human_agree_bp INTEGER,
  monitor_status TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (metric_date, agent_id)
);

-- model_validation (append_only): WP19. One row per judge validation run (python -m supervisor.judge.mrm validate). The judge service checks it when JUDGE_REQUIRE_VALIDATION is on. Integers only.
CREATE TABLE IF NOT EXISTS model_validation (
  validation_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  judge_id TEXT NOT NULL,
  model_version TEXT NOT NULL,
  prompt_hash TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  mask_version TEXT NOT NULL,
  golden_set_hash TEXT NOT NULL,
  is_mock INTEGER NOT NULL,
  decision TEXT NOT NULL,
  passed INTEGER NOT NULL,
  runs INTEGER NOT NULL,
  metrics TEXT NOT NULL,
  thresholds TEXT NOT NULL,
  failed_checks TEXT NOT NULL,
  validator TEXT NOT NULL,
  report_hash TEXT NOT NULL,
  PRIMARY KEY (validation_id)
);

CREATE INDEX IF NOT EXISTS ix_model_validation_model_version_prompt_hash ON model_validation (model_version, prompt_hash);

CREATE TRIGGER IF NOT EXISTS trg_model_validation_no_update
BEFORE UPDATE ON model_validation
BEGIN
  SELECT RAISE(ABORT, 'model_validation is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_model_validation_no_delete
BEFORE DELETE ON model_validation
BEGIN
  SELECT RAISE(ABORT, 'model_validation is append-only');
END;

-- policy_baseline (state): Drift baseline band per agent version and metric (WP7, ADR D09). Integers only: band = center +- k * scaled MAD. Also holds the breach streak of the drift monitor.
CREATE TABLE IF NOT EXISTS policy_baseline (
  agent_id TEXT NOT NULL,
  agent_version TEXT NOT NULL,
  metric TEXT NOT NULL,
  baseline_id TEXT NOT NULL,
  center INTEGER NOT NULL,
  mad INTEGER NOT NULL,
  band_low INTEGER NOT NULL,
  band_high INTEGER NOT NULL,
  k INTEGER NOT NULL,
  windows INTEGER NOT NULL,
  window_s INTEGER NOT NULL,
  window_from TEXT NOT NULL,
  window_to TEXT NOT NULL,
  breach_streak INTEGER NOT NULL,
  last_value INTEGER,
  last_checked_to TEXT,
  open_case_id TEXT,
  computed_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (agent_id, agent_version, metric)
);

-- policy_threshold (state): Monitor thresholds per agent and metric (WP7). agent_id '*' is the default for every agent. Example metrics: drift.k, drift.consecutive, fairness.approval_gap_bp.
CREATE TABLE IF NOT EXISTS policy_threshold (
  agent_id TEXT NOT NULL,
  metric TEXT NOT NULL,
  threshold INTEGER NOT NULL,
  unit TEXT NOT NULL,
  owner TEXT,
  note TEXT,
  effective_from TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (agent_id, metric)
);

-- fairness_slice (append_only): One row per fairness cell per run (WP7). Cells under the minimum n are suppressed: counts and rates are null. Built on hashed subject ids, never raw ids.
CREATE TABLE IF NOT EXISTS fairness_slice (
  run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  window_from TEXT NOT NULL,
  window_to TEXT NOT NULL,
  attribute TEXT NOT NULL,
  cell TEXT NOT NULL,
  n INTEGER,
  approvals INTEGER,
  blocks INTEGER,
  approval_rate_bp INTEGER,
  block_rate_bp INTEGER,
  suppressed INTEGER NOT NULL,
  method TEXT NOT NULL,
  PRIMARY KEY (run_id, attribute, cell)
);

CREATE INDEX IF NOT EXISTS ix_fairness_slice_agent_id_ts ON fairness_slice (agent_id, ts);

CREATE TRIGGER IF NOT EXISTS trg_fairness_slice_no_update
BEFORE UPDATE ON fairness_slice
BEGIN
  SELECT RAISE(ABORT, 'fairness_slice is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_fairness_slice_no_delete
BEFORE DELETE ON fairness_slice
BEGIN
  SELECT RAISE(ABORT, 'fairness_slice is append-only');
END;

-- monitor_state (state): Cursors and dedupe marks of the monitors and the scheduler (WP7).
CREATE TABLE IF NOT EXISTS monitor_state (
  monitor TEXT NOT NULL,
  state_key TEXT NOT NULL,
  value TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (monitor, state_key)
);

-- scheduler_lease (state): Single-instance lock of the in-process scheduler on Databricks (WP7). One row per lease; the holder renews it; another replica takes it only after expires_at.
CREATE TABLE IF NOT EXISTS scheduler_lease (
  lease_name TEXT NOT NULL,
  holder TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (lease_name)
);

-- gate_control (state): Gateway control records (WP3). Active pause (with the state to resume to) and pending two-person resume approvals.
CREATE TABLE IF NOT EXISTS gate_control (
  control_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  action TEXT NOT NULL,
  principal TEXT NOT NULL,
  role TEXT,
  reason TEXT,
  resume_to TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (control_id)
);

CREATE INDEX IF NOT EXISTS ix_gate_control_agent_id_status ON gate_control (agent_id, status);

-- notice (state): WP8. Notifier inbox (console Inbox page). Masked text only. The webhook stub queues rows with status queued and never sends them (off by default).
CREATE TABLE IF NOT EXISTS notice (
  notice_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  channel TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL,
  read_by TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (notice_id)
);

CREATE INDEX IF NOT EXISTS ix_notice_channel_status ON notice (channel, status);

-- console_action (append_only): WP18. One row per mutating console or API action (and per denied attempt): who, when, what, target, row hash before and after, request id. Append-only; in the audit pack.
CREATE TABLE IF NOT EXISTS console_action (
  action_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  request_id TEXT NOT NULL,
  actor TEXT NOT NULL,
  actor_kind TEXT NOT NULL,
  auth_method TEXT NOT NULL,
  roles TEXT NOT NULL,
  permission TEXT NOT NULL,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  target_kind TEXT,
  target_id TEXT,
  outcome TEXT NOT NULL,
  before_hash TEXT,
  after_hash TEXT,
  detail TEXT,
  PRIMARY KEY (action_id)
);

CREATE INDEX IF NOT EXISTS ix_console_action_ts ON console_action (ts);

CREATE INDEX IF NOT EXISTS ix_console_action_actor_ts ON console_action (actor, ts);

CREATE TRIGGER IF NOT EXISTS trg_console_action_no_update
BEFORE UPDATE ON console_action
BEGIN
  SELECT RAISE(ABORT, 'console_action is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_console_action_no_delete
BEFORE DELETE ON console_action
BEGIN
  SELECT RAISE(ABORT, 'console_action is append-only');
END;

-- eval_run (append_only): WP17 assurance eval packs. One row per run of `python -m supervisor.assurance run` (counts per status). Integers and strings only.
CREATE TABLE IF NOT EXISTS eval_run (
  run_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  target_spec TEXT NOT NULL,
  selector TEXT NOT NULL,
  packs_total INTEGER NOT NULL,
  ok INTEGER NOT NULL,
  warn INTEGER NOT NULL,
  fail INTEGER NOT NULL,
  skip INTEGER NOT NULL,
  error INTEGER NOT NULL,
  is_mock INTEGER NOT NULL,
  settings_digest TEXT,
  out_dir TEXT,
  PRIMARY KEY (run_id)
);

CREATE TRIGGER IF NOT EXISTS trg_eval_run_no_update
BEFORE UPDATE ON eval_run
BEGIN
  SELECT RAISE(ABORT, 'eval_run is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_eval_run_no_delete
BEFORE DELETE ON eval_run
BEGIN
  SELECT RAISE(ABORT, 'eval_run is append-only');
END;

-- eval_result (append_only): WP17 assurance eval packs. One row per pack x target x run: integer metrics, the per-metric status against the manifest thresholds, the dataset digest and the hash of the assurance_result chain record. Mock runs are labelled is_mock.
CREATE TABLE IF NOT EXISTS eval_result (
  run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  pack_id TEXT NOT NULL,
  pack_version INTEGER NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  dimension TEXT NOT NULL,
  target_kind TEXT NOT NULL,
  target_id TEXT NOT NULL,
  status TEXT NOT NULL,
  metrics TEXT NOT NULL,
  metric_status TEXT NOT NULL,
  thresholds TEXT NOT NULL,
  reasons TEXT NOT NULL,
  n_items INTEGER NOT NULL,
  data_mode TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_sha256 TEXT NOT NULL,
  is_mock INTEGER NOT NULL,
  launch_gate TEXT NOT NULL,
  judge_gate INTEGER NOT NULL,
  details TEXT NOT NULL,
  evidence_hash TEXT,
  PRIMARY KEY (run_id, pack_id, target_kind, target_id)
);

CREATE INDEX IF NOT EXISTS ix_eval_result_target_kind_target_id_ts ON eval_result (target_kind, target_id, ts);

CREATE INDEX IF NOT EXISTS ix_eval_result_pack_id ON eval_result (pack_id);

CREATE TRIGGER IF NOT EXISTS trg_eval_result_no_update
BEFORE UPDATE ON eval_result
BEGIN
  SELECT RAISE(ABORT, 'eval_result is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_eval_result_no_delete
BEFORE DELETE ON eval_result
BEGIN
  SELECT RAISE(ABORT, 'eval_result is append-only');
END;

-- tool_usage_daily (state): WP22. Per agent, tool and UTC day: gate decision counts, latency percentiles, distinct callers and end users (counts only; hashed ids are never stored), first and last call. Recomputed from agent_event by python -m supervisor.analytics.tools rollup (idempotent: a day is overwritten). Feeds the console Tools page, /v1/analytics/tools and the least-privilege suggestion. Integers only.
CREATE TABLE IF NOT EXISTS tool_usage_daily (
  usage_date TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  risk_class TEXT,
  calls INTEGER NOT NULL,
  allows INTEGER NOT NULL,
  blocks INTEGER NOT NULL,
  pauses INTEGER NOT NULL,
  errors INTEGER NOT NULL,
  p50_us INTEGER,
  p95_us INTEGER,
  distinct_callers INTEGER NOT NULL,
  distinct_users INTEGER NOT NULL,
  first_seen TEXT,
  last_seen TEXT,
  computed_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (usage_date, agent_id, tool_name)
);

CREATE INDEX IF NOT EXISTS ix_tool_usage_daily_agent_id_usage_date ON tool_usage_daily (agent_id, usage_date);

-- decision_daily (state): WP39. Per UTC day and dimension: gate decision counts by verdict status, the not-evaluated count and, for dimension detector_latency, latency percentiles. Recomputed from agent_event and finding by python -m supervisor.jobs.decision_rollup (idempotent: a day is overwritten). Feeds the console Analytics Gate and Detectors tabs so the App never scans the raw table on page load. dimension: total | agent | consumer | rule | detector_code | detector_latency. Integers and ids only; no text.
CREATE TABLE IF NOT EXISTS decision_daily (
  usage_date TEXT NOT NULL,
  dimension TEXT NOT NULL,
  dim_key TEXT NOT NULL,
  dim_key2 TEXT NOT NULL,
  requests INTEGER NOT NULL,
  allows INTEGER NOT NULL,
  reports INTEGER NOT NULL,
  transforms INTEGER NOT NULL,
  pauses INTEGER NOT NULL,
  blocks INTEGER NOT NULL,
  skips INTEGER NOT NULL,
  not_evaluated INTEGER NOT NULL,
  p50_us INTEGER,
  p95_us INTEGER,
  computed_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (usage_date, dimension, dim_key, dim_key2)
);

CREATE INDEX IF NOT EXISTS ix_decision_daily_dimension_usage_date ON decision_daily (dimension, usage_date);

-- alert (state): WP21. One row per fired alert (rule engine, ADR D15). Ids, counts and hashes only, never free text. dedupe_key = rule_id + group value; repeats inside the rule's dedupe window raise suppressed_count on the open row instead of making a new row. status: open, acknowledged (by an operator, audited), closed.
CREATE TABLE IF NOT EXISTS alert (
  alert_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  rule_hash TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  title TEXT NOT NULL,
  agent_id TEXT,
  group_value TEXT,
  window_s INTEGER NOT NULL,
  window_count INTEGER NOT NULL,
  threshold INTEGER NOT NULL,
  first_ts TEXT NOT NULL,
  last_ts TEXT NOT NULL,
  suppressed_count INTEGER NOT NULL,
  case_id TEXT,
  chain_lane TEXT,
  chain_seq INTEGER,
  entry_hash TEXT,
  refs TEXT NOT NULL,
  routes TEXT NOT NULL,
  route_status TEXT NOT NULL,
  acknowledged_by TEXT,
  acknowledged_at TEXT,
  correlation_id TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (alert_id)
);

CREATE INDEX IF NOT EXISTS ix_alert_status_ts ON alert (status, ts);

CREATE INDEX IF NOT EXISTS ix_alert_dedupe_key_ts ON alert (dedupe_key, ts);

-- siem_event (append_only): WP21. Delta sink of the SIEM export (SIEM_SINK=delta): one row per event, with the OCSF document, so a Databricks-hosted SIEM connector or Lakehouse Monitoring can read it. Ids, hashes and enums only. event_id is the idempotency key.
CREATE TABLE IF NOT EXISTS siem_event (
  event_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity INTEGER NOT NULL,
  outcome TEXT NOT NULL,
  agent_id TEXT,
  rule_id TEXT,
  case_id TEXT,
  actor TEXT,
  chain_lane TEXT,
  chain_seq INTEGER,
  entry_hash TEXT,
  env TEXT NOT NULL,
  event_schema TEXT NOT NULL,
  ocsf_class_uid INTEGER NOT NULL,
  ocsf_json TEXT NOT NULL,
  PRIMARY KEY (event_id)
);

CREATE INDEX IF NOT EXISTS ix_siem_event_ts ON siem_event (ts);

CREATE TRIGGER IF NOT EXISTS trg_siem_event_no_update
BEFORE UPDATE ON siem_event
BEGIN
  SELECT RAISE(ABORT, 'siem_event is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_siem_event_no_delete
BEFORE DELETE ON siem_event
BEGIN
  SELECT RAISE(ABORT, 'siem_event is append-only');
END;

-- inventory_node (state): WP24 inventory graph node (system, model, model_endpoint, tool, mcp_server, dataset, prompt, supplier). node_id is a hash of kind + canonical name, so a refill never duplicates. own_risk is low|medium|high|critical or NULL; the effective level is computed on read, never stored. decision33_class is human-set (copied from the agent row), never inferred. evidence lists {source, ref} pairs (manifest | onboarding | workspace_scan | manual | gate, plus file:line or a workspace reference).
CREATE TABLE IF NOT EXISTS inventory_node (
  node_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL,
  own_risk TEXT,
  risk_source TEXT NOT NULL,
  decision33_class TEXT,
  attrs TEXT NOT NULL,
  evidence TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (node_id)
);

CREATE INDEX IF NOT EXISTS ix_inventory_node_kind_status ON inventory_node (kind, status);

-- inventory_edge (state): WP24 inventory graph edge (uses, serves, reads, writes, hosted_on, owned_by). One row per (src, kind, dst, source) so every claim keeps its own evidence. active is false when the source no longer reports the edge.
CREATE TABLE IF NOT EXISTS inventory_edge (
  edge_id TEXT NOT NULL,
  src_id TEXT NOT NULL,
  dst_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  source TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  active INTEGER NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (edge_id)
);

CREATE INDEX IF NOT EXISTS ix_inventory_edge_src_id ON inventory_edge (src_id);

CREATE INDEX IF NOT EXISTS ix_inventory_edge_dst_id ON inventory_edge (dst_id);

-- session_control (state): WP27 session-scoped pause of money / credit tools. One row per pause: active until a two-person resume (owner + reviewer, same rule as an agent resume) or until expires_at (cool-down). Written only by a deterministic rule of the session monitor. The gate reads active rows (GATE-SESSION-PAUSE). Free text never lands here.
CREATE TABLE IF NOT EXISTS session_control (
  control_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  status TEXT NOT NULL,
  score_bp INTEGER NOT NULL,
  case_id TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  approver_1 TEXT,
  approver_1_role TEXT,
  approver_1_at TEXT,
  lifted_by TEXT,
  lifted_at TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (control_id)
);

CREATE INDEX IF NOT EXISTS ix_session_control_agent_id_status ON session_control (agent_id, status);

CREATE INDEX IF NOT EXISTS ix_session_control_session_id ON session_control (session_id);

-- finding (append_only): WP37 one row per detector result of a gate decision: a fired finding, or a detector that did not run (not_executed_reason set, score 0). Entities and fragments are MASKED text only (pseudonym tokens and masked excerpts); raw values never reach this table. event_id is the gate decision (agent_event.event_id); correlation_id ties decision, trace span and finding.
CREATE TABLE IF NOT EXISTS finding (
  finding_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  event_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  trace_id TEXT,
  agent_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  direction TEXT NOT NULL,
  detector_slug TEXT NOT NULL,
  detector_id TEXT NOT NULL,
  code TEXT NOT NULL,
  score_bp INTEGER NOT NULL,
  threshold_bp INTEGER NOT NULL,
  masked_count INTEGER NOT NULL,
  action_hint TEXT NOT NULL,
  not_executed_reason TEXT,
  preset TEXT,
  is_mock INTEGER NOT NULL,
  verdict_status TEXT NOT NULL,
  entities_masked TEXT,
  fragments_masked TEXT,
  PRIMARY KEY (finding_id)
);

CREATE INDEX IF NOT EXISTS ix_finding_agent_id_ts ON finding (agent_id, ts);

CREATE INDEX IF NOT EXISTS ix_finding_event_id ON finding (event_id);

CREATE INDEX IF NOT EXISTS ix_finding_correlation_id ON finding (correlation_id);

DROP TRIGGER IF EXISTS trg_finding_no_update;

CREATE TRIGGER trg_finding_no_update
BEFORE UPDATE OF finding_id, ts, event_id, request_id, correlation_id, trace_id, agent_id, tool_name, direction, detector_slug, detector_id, code, score_bp, threshold_bp, masked_count, action_hint, not_executed_reason, preset, is_mock, verdict_status ON finding
BEGIN
  SELECT RAISE(ABORT, 'finding is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_finding_retention_null_only
BEFORE UPDATE OF entities_masked, fragments_masked ON finding
WHEN NEW.entities_masked IS NOT NULL OR NEW.fragments_masked IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'finding is append-only: retention may only set NULL');
END;

CREATE TRIGGER IF NOT EXISTS trg_finding_no_delete
BEFORE DELETE ON finding
BEGIN
  SELECT RAISE(ABORT, 'finding is append-only');
END;

-- mcp_tool_manifest (state): WP26 locked tool manifest per upstream MCP server. One row per (server, tool) plus one server row (tool_name '*') that holds the whole-list hash. locked_hash is what two different reviewers approved; observed_hash is what the server shows now. A tool whose status is new or changed is hidden from the agent and its tools/call is blocked (MCP-TOOL-UNREVIEWED). approvals lists {by, role, at, hash}; they count only for the observed hash. scan is the report-only poisoning scan (kinds and counts, no text).
CREATE TABLE IF NOT EXISTS mcp_tool_manifest (
  manifest_id TEXT NOT NULL,
  server_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  row_kind TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  status TEXT NOT NULL,
  locked_hash TEXT,
  observed_hash TEXT,
  locked_def TEXT,
  observed_def TEXT,
  suspicious INTEGER NOT NULL,
  scan TEXT,
  approvals TEXT NOT NULL,
  case_id TEXT,
  seeded_by TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (manifest_id)
);

CREATE INDEX IF NOT EXISTS ix_mcp_tool_manifest_server_id ON mcp_tool_manifest (server_id);

-- risk (state): WP29 risk register entry. Anchored on an agent or on an inventory node (a shared model, tool, MCP server or dataset, which every agent that reaches it inherits). Likelihood and impact are whole numbers 1 to 5; the score is their product and is computed on read, never stored. residual_* is what the person declares for the treated risk; the value the product uses is decided by the evidence rule (risk_evidence), see docs/risk-register.md.
CREATE TABLE IF NOT EXISTS risk (
  risk_id TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  category TEXT NOT NULL,
  agent_id TEXT,
  node_id TEXT,
  inherent_likelihood INTEGER NOT NULL,
  inherent_impact INTEGER NOT NULL,
  marginal_risk INTEGER,
  marginal_note TEXT,
  treatment TEXT NOT NULL,
  treatment_note TEXT,
  residual_likelihood INTEGER NOT NULL,
  residual_impact INTEGER NOT NULL,
  owner TEXT NOT NULL,
  review_date TEXT,
  status TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (risk_id)
);

CREATE INDEX IF NOT EXISTS ix_risk_agent_id ON risk (agent_id);

CREATE INDEX IF NOT EXISTS ix_risk_status ON risk (status);

-- risk_link (state): WP29 link of a risk to a compliance matrix row (obligation id), a gate rule id, an assurance pack id, a monitor name or a case id. rule, pack and monitor links are the controls the evidence rule looks at; matrix and case links are references.
CREATE TABLE IF NOT EXISTS risk_link (
  link_id TEXT NOT NULL,
  risk_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  target TEXT NOT NULL,
  active INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (link_id)
);

CREATE INDEX IF NOT EXISTS ix_risk_link_risk_id ON risk_link (risk_id);

CREATE INDEX IF NOT EXISTS ix_risk_link_kind_target ON risk_link (kind, target);

-- risk_evidence (append_only): WP29. One row per risk and window: what the linked controls did (counts), the state (working | failing | no_evidence), the reason code and the residual score the evidence rule allows. Integers, codes and hashes only; no text. The matching chain record is risk_evidence. A repeat for the same window is a no-op (evidence_id is a hash).
CREATE TABLE IF NOT EXISTS risk_evidence (
  evidence_id TEXT NOT NULL,
  risk_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  state TEXT NOT NULL,
  reason TEXT NOT NULL,
  agents_n INTEGER NOT NULL,
  agents_excluded INTEGER NOT NULL,
  rule_links INTEGER NOT NULL,
  rule_hits INTEGER NOT NULL,
  rule_stops INTEGER NOT NULL,
  rules_missing INTEGER NOT NULL,
  pack_links INTEGER NOT NULL,
  pack_ok INTEGER NOT NULL,
  pack_warn INTEGER NOT NULL,
  pack_fail INTEGER NOT NULL,
  pack_nodata INTEGER NOT NULL,
  monitor_links INTEGER NOT NULL,
  monitor_ok INTEGER NOT NULL,
  monitor_other INTEGER NOT NULL,
  controls_working INTEGER NOT NULL,
  controls_failing INTEGER NOT NULL,
  controls_idle INTEGER NOT NULL,
  declared_residual_likelihood INTEGER NOT NULL,
  declared_residual_impact INTEGER NOT NULL,
  residual_likelihood INTEGER NOT NULL,
  residual_impact INTEGER NOT NULL,
  digest TEXT NOT NULL,
  chain_hash TEXT,
  PRIMARY KEY (evidence_id)
);

CREATE INDEX IF NOT EXISTS ix_risk_evidence_risk_id_ts ON risk_evidence (risk_id, ts);

CREATE TRIGGER IF NOT EXISTS trg_risk_evidence_no_update
BEFORE UPDATE ON risk_evidence
BEGIN
  SELECT RAISE(ABORT, 'risk_evidence is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_risk_evidence_no_delete
BEFORE DELETE ON risk_evidence
BEGIN
  SELECT RAISE(ABORT, 'risk_evidence is append-only');
END;

-- control (state): WP30 control: an action the bank or the product takes to meet obligations and hold risks down. One control covers many obligations and many risks (control_map). type is preventive, detective or corrective; implemented_by is product or bank. scope_agents is a JSON list of agent ids, or [*] for every supervised agent. Evidence status is computed from runtime facts (control_status), never typed in.
CREATE TABLE IF NOT EXISTS control (
  control_id TEXT NOT NULL,
  title TEXT NOT NULL,
  objective TEXT NOT NULL,
  control_type TEXT NOT NULL,
  implemented_by TEXT NOT NULL,
  owner TEXT NOT NULL,
  status TEXT NOT NULL,
  review_date TEXT,
  scope_agents TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (control_id)
);

CREATE INDEX IF NOT EXISTS ix_control_status ON control (status);

-- control_map (state): WP30 map of one control. kind matrix = obligation id of the compliance matrix, risk = risk id of the register; rule, pack, monitor, detector and document are evidence sources. Only rule, pack and monitor are observed at runtime; detector and document are references.
CREATE TABLE IF NOT EXISTS control_map (
  map_id TEXT NOT NULL,
  control_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  target TEXT NOT NULL,
  active INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (map_id)
);

CREATE INDEX IF NOT EXISTS ix_control_map_control_id ON control_map (control_id);

CREATE INDEX IF NOT EXISTS ix_control_map_kind_target ON control_map (kind, target);

-- control_status (append_only): WP30. One row per control, agent and window: working, failing or no_data, a fixed reason code and integer counts of the evidence sources. No text. The matching chain record is control_status (one per agent and pass, carrying the compliance bp). A repeat for the same window is a no-op (status_id is a hash).
CREATE TABLE IF NOT EXISTS control_status (
  status_id TEXT NOT NULL,
  control_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT NOT NULL,
  sources_n INTEGER NOT NULL,
  working_n INTEGER NOT NULL,
  failing_n INTEGER NOT NULL,
  idle_n INTEGER NOT NULL,
  refs_n INTEGER NOT NULL,
  digest TEXT NOT NULL,
  chain_hash TEXT,
  PRIMARY KEY (status_id)
);

CREATE INDEX IF NOT EXISTS ix_control_status_control_id_agent_id_ts ON control_status (control_id, agent_id, ts);

CREATE INDEX IF NOT EXISTS ix_control_status_agent_id_ts ON control_status (agent_id, ts);

CREATE TRIGGER IF NOT EXISTS trg_control_status_no_update
BEFORE UPDATE ON control_status
BEGIN
  SELECT RAISE(ABORT, 'control_status is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_control_status_no_delete
BEFORE DELETE ON control_status
BEGIN
  SELECT RAISE(ABORT, 'control_status is append-only');
END;

-- task (state): WP30 lifecycle task of one agent, made from a template in config/tasks.yaml. kind move is the lifecycle move itself (a task); it is done only when no required task of the stage is open. Waiving needs a reason and a second person (waive_requested_by, waive_approved_by). evidence_kind says what proves the task done: control, pack, document or none.
CREATE TABLE IF NOT EXISTS task (
  task_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  template_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  stage TEXT NOT NULL,
  target_stage TEXT,
  title TEXT NOT NULL,
  owner_role TEXT NOT NULL,
  required INTEGER NOT NULL,
  status TEXT NOT NULL,
  due_at TEXT,
  evidence_kind TEXT NOT NULL,
  evidence_ref TEXT,
  level TEXT NOT NULL,
  d33_class TEXT NOT NULL,
  waive_reason TEXT,
  waive_requested_by TEXT,
  waive_approved_by TEXT,
  done_by TEXT,
  done_at TEXT,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (task_id)
);

CREATE INDEX IF NOT EXISTS ix_task_agent_id_stage ON task (agent_id, stage);

CREATE INDEX IF NOT EXISTS ix_task_status ON task (status);

-- task_event (append_only): WP30. Every change of a task: generate, start, done, waive_request, waive_approve, waive_reject, resize, overdue. From and to status, the actor and hashes; reasons are stored as a hash only. The matching chain record is task_change.
CREATE TABLE IF NOT EXISTS task_event (
  event_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  action TEXT NOT NULL,
  actor TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  reason_sha256 TEXT,
  row_hash TEXT NOT NULL,
  chain_hash TEXT,
  PRIMARY KEY (event_id)
);

CREATE INDEX IF NOT EXISTS ix_task_event_task_id_ts ON task_event (task_id, ts);

CREATE INDEX IF NOT EXISTS ix_task_event_agent_id_ts ON task_event (agent_id, ts);

CREATE TRIGGER IF NOT EXISTS trg_task_event_no_update
BEFORE UPDATE ON task_event
BEGIN
  SELECT RAISE(ABORT, 'task_event is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_task_event_no_delete
BEFORE DELETE ON task_event
BEGIN
  SELECT RAISE(ABORT, 'task_event is append-only');
END;

-- transparency_report (append_only): WP31. One row per generated report file set: agent, variant (regulator | customer | internal), language, version (a whole number per agent and variant) and the sha256 of the JSON and of each rendered file. The report data holds ids, integers, hashes and masked text only; this row holds hashes, counts and section hashes (for the diff to the next version), no text. The matching chain record is transparency_report. A repeat for the same (agent, variant, lang, version) is a no-op (report_id is a hash).
CREATE TABLE IF NOT EXISTS transparency_report (
  report_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  variant TEXT NOT NULL,
  lang TEXT NOT NULL,
  version INTEGER NOT NULL,
  schema_version INTEGER NOT NULL,
  generated_at TEXT NOT NULL,
  generated_by TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  json_hash TEXT NOT NULL,
  html_hash TEXT,
  pdf_hash TEXT,
  sections_total INTEGER NOT NULL,
  sections_available INTEGER NOT NULL,
  section_hashes TEXT NOT NULL,
  verify_state TEXT NOT NULL,
  chain_hash TEXT,
  PRIMARY KEY (report_id)
);

CREATE INDEX IF NOT EXISTS ix_transparency_report_agent_id_variant_version ON transparency_report (agent_id, variant, version);

CREATE TRIGGER IF NOT EXISTS trg_transparency_report_no_update
BEFORE UPDATE ON transparency_report
BEGIN
  SELECT RAISE(ABORT, 'transparency_report is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_transparency_report_no_delete
BEFORE DELETE ON transparency_report
BEGIN
  SELECT RAISE(ABORT, 'transparency_report is append-only');
END;

-- ai_system (state): WP-G0. The unit of governance: one AI system (product, platform, feature or use case) with named owners, a few unambiguous intake fields and a manual risk level. The effective risk level (manual level and the level inherited from linked agents and inventory nodes) is computed on read, never stored. decision33_class is human-set. Changes go on the chain as system_change.
CREATE TABLE IF NOT EXISTS ai_system (
  system_id TEXT NOT NULL,
  name TEXT NOT NULL,
  owner_user TEXT NOT NULL,
  owner_team TEXT NOT NULL,
  business_owner TEXT,
  purpose TEXT NOT NULL,
  system_type TEXT NOT NULL,
  org_role TEXT NOT NULL,
  user_segment TEXT NOT NULL,
  personal_data TEXT NOT NULL,
  money_movement INTEGER NOT NULL,
  credit_decision INTEGER NOT NULL,
  human_control TEXT NOT NULL,
  lifecycle_stage TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  risk_level_source TEXT NOT NULL,
  risk_justification TEXT,
  decision33_class TEXT NOT NULL,
  business_impact TEXT NOT NULL,
  autonomy_level TEXT NOT NULL,
  status TEXT NOT NULL,
  tags TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (system_id)
);

CREATE INDEX IF NOT EXISTS ix_ai_system_status ON ai_system (status);

CREATE INDEX IF NOT EXISTS ix_ai_system_owner_team ON ai_system (owner_team);

-- system_team (state): WP-G0. Who is on an AI system and in which role. A member sees and edits the system; a reviewer or oversight manager cannot be the system owner of the same system (segregation of duties).
CREATE TABLE IF NOT EXISTS system_team (
  system_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  team_role TEXT NOT NULL,
  active INTEGER NOT NULL,
  added_at TEXT NOT NULL,
  added_by TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (system_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_system_team_user_id ON system_team (user_id);

-- system_component (state): WP-G0. A link from an AI system to an agent or an inventory node. component_id is a hash of (system_id, ref_kind, ref_id, role), so a repeat is a no-op. active is false after an unlink (the row stays as history).
CREATE TABLE IF NOT EXISTS system_component (
  component_id TEXT NOT NULL,
  system_id TEXT NOT NULL,
  ref_kind TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  role TEXT NOT NULL,
  source TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  active INTEGER NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (component_id)
);

CREATE INDEX IF NOT EXISTS ix_system_component_system_id ON system_component (system_id);

CREATE INDEX IF NOT EXISTS ix_system_component_ref_kind_ref_id ON system_component (ref_kind, ref_id);

-- assignment (state): WP-G2. One thing the assignment rules put on an AI system: an obligation, a control, a risk, a task template or a guardian feature. assignment_id is a hash of (system, kind, ref), so a repeat run keeps the row. active is false when no rule fires for it any more; a row is never deleted. fired lists the rules and the fields that fired, for the explanation. A run writes a rule_run chain record.
CREATE TABLE IF NOT EXISTS assignment (
  assignment_id TEXT NOT NULL,
  system_id TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  active INTEGER NOT NULL,
  fired TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (assignment_id)
);

CREATE INDEX IF NOT EXISTS ix_assignment_system_id ON assignment (system_id);

CREATE INDEX IF NOT EXISTS ix_assignment_kind_ref_id ON assignment (kind, ref_id);

-- classification (state): WP-G2. A Decision 33 classification of one AI system: a draft made from the rules, edited by a person, then applied by a person (never by a model). answers holds, per question, the answer, its source (rules | ai_prefill | person) and the justification. Applying sets decision33_class on the system and the classifier floor of its risk level. Changes go on the chain as classification_change.
CREATE TABLE IF NOT EXISTS classification (
  classification_id TEXT NOT NULL,
  system_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  answers TEXT NOT NULL,
  flow_sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  applied_by TEXT,
  applied_at TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (classification_id)
);

CREATE INDEX IF NOT EXISTS ix_classification_system_id ON classification (system_id);

-- stage_approval (state): WP-G1. A request to move an AI system to a lifecycle stage that needs an approval (config/tasks.yaml, stages: ... approval: true), and the answer. The approver is a reviewer or oversight manager of the system or holds the approver role, and is neither the requester nor the owner. applied_at is set when the move used the approval. Changes go on the chain as stage_change.
CREATE TABLE IF NOT EXISTS stage_approval (
  approval_id TEXT NOT NULL,
  system_id TEXT NOT NULL,
  from_stage TEXT NOT NULL,
  to_stage TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  status TEXT NOT NULL,
  decided_by TEXT,
  reason TEXT,
  created_at TEXT NOT NULL,
  decided_at TEXT,
  applied_at TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (approval_id)
);

CREATE INDEX IF NOT EXISTS ix_stage_approval_system_id ON stage_approval (system_id);

-- review (state): WP-G1. A review of an AI system (internal, external, conformity or classification audit) with its scope, window and reports. Completing a review locks it; reopening needs a reason. Changes go on the chain as review_change.
CREATE TABLE IF NOT EXISTS review (
  review_id TEXT NOT NULL,
  system_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  scope TEXT NOT NULL,
  reviewer_user TEXT NOT NULL,
  status TEXT NOT NULL,
  window_start TEXT,
  window_end TEXT,
  reports TEXT NOT NULL,
  completed_at TEXT,
  completed_by TEXT,
  locked INTEGER NOT NULL,
  reopen_reason TEXT,
  reopen_count INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (review_id)
);

CREATE INDEX IF NOT EXISTS ix_review_system_id ON review (system_id);

-- outbound_event (state): WP-G1. An event for other systems (stage approved, review completed, system registered, system archived). The payload holds ids and enums only. The webhook stub (WEBHOOKS_ENABLED) marks it delivered; nothing else reads the table yet.
CREATE TABLE IF NOT EXISTS outbound_event (
  event_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  system_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  delivered INTEGER NOT NULL,
  delivered_at TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (event_id)
);

CREATE INDEX IF NOT EXISTS ix_outbound_event_system_id ON outbound_event (system_id);

CREATE INDEX IF NOT EXISTS ix_outbound_event_delivered ON outbound_event (delivered);

-- incident (state): WP-G5. An incident made by the governance action job from an event (alert, gate stop on a risky tool, failed detector, failing monitor, assurance NO-GO, chain break, model version change, judge escalation). Auto-created only; a person moves it on and closes it. The title comes from a template; no free text from an event. root_cause and affected_scope are typed by a person. Changes go on the chain as incident_change.
CREATE TABLE IF NOT EXISTS incident (
  incident_id TEXT NOT NULL,
  system_id TEXT,
  agent_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  event_ref TEXT NOT NULL,
  root_cause TEXT,
  affected_scope TEXT,
  status TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  closed_by TEXT,
  case_id TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (incident_id)
);

CREATE INDEX IF NOT EXISTS ix_incident_status ON incident (status);

CREATE INDEX IF NOT EXISTS ix_incident_system_id ON incident (system_id);

CREATE INDEX IF NOT EXISTS ix_incident_agent_id ON incident (agent_id);

-- governance_event (state): WP-G5. The marker that an event was processed (one row per event key, a hash of kind, ref and system). Written before the actions run (status started), so an event is processed once across runs; the actions column holds the result of each action (and an attempting entry before an action runs), so a retry of a started event skips what was done or may have been done. A failed action is retried up to 3 runs, then failed_final. Ids and enums only.
CREATE TABLE IF NOT EXISTS governance_event (
  event_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  system_id TEXT,
  ref TEXT NOT NULL,
  event_at TEXT NOT NULL,
  status TEXT NOT NULL,
  rules TEXT NOT NULL,
  actions TEXT NOT NULL,
  started_at TEXT NOT NULL,
  done_at TEXT,
  detail TEXT,
  runner_id TEXT,
  lease_until TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (event_key)
);

CREATE INDEX IF NOT EXISTS ix_governance_event_status ON governance_event (status);

-- mcp_app (state): WP-G6. An application connected to the MCP server (a pipeline or an AI assistant). The first connection is pending until an admin approves it; a blocked app is refused at once. scopes lists what it may call (governance.read, governance.write, library.read, supervisor.read); roles are the console roles the app acts with (never admin), so its view of the AI systems is scoped like a person's. key_hash is the SHA-256 of the current HMAC secret (the secret itself lives in the WP20 key store under the app id). Every change is a console_action row; no free text from a client is stored here.
CREATE TABLE IF NOT EXISTS mcp_app (
  app_id TEXT NOT NULL,
  name TEXT NOT NULL,
  scopes TEXT NOT NULL,
  roles TEXT NOT NULL,
  created_by TEXT NOT NULL,
  approved_by TEXT,
  status TEXT NOT NULL,
  key_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  approved_at TEXT,
  first_connected_at TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (app_id)
);

CREATE INDEX IF NOT EXISTS ix_mcp_app_status ON mcp_app (status);

-- registration_draft (state): WP-N3. A half-finished registration of an AI system (register workflow v2, six steps). One row per person and attempt; data holds the answers, the suggestions with their reason keys and the source of each value. No evidence rows and no chain records: a draft is working state. submitted means the system was written; abandoned means the person dropped it.
CREATE TABLE IF NOT EXISTS registration_draft (
  draft_id TEXT NOT NULL,
  owner_user TEXT NOT NULL,
  status TEXT NOT NULL,
  step INTEGER NOT NULL,
  source_kind TEXT NOT NULL,
  source_ref TEXT,
  data TEXT NOT NULL,
  created_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (draft_id)
);

CREATE INDEX IF NOT EXISTS ix_registration_draft_owner_user_status ON registration_draft (owner_user, status);

-- guardian_binding (state): WP-S1. A product owner's switch for one guardian feature on one AI system: on or off. No row means on. A binding can only narrow what the instance already has on; the assignment rules' guardian floor always wins (a floor feature cannot be set off, and a floor added later overrides an old off row at resolution time). mandatory is the floor state when the row was written (a snapshot for the audit; resolution reads the floor again). Changes go on the chain as binding_change (ids and enums only).
CREATE TABLE IF NOT EXISTS guardian_binding (
  system_id TEXT NOT NULL,
  feature_slug TEXT NOT NULL,
  state TEXT NOT NULL,
  mandatory INTEGER NOT NULL,
  set_by TEXT NOT NULL,
  set_at TEXT NOT NULL,
  reason TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (system_id, feature_slug)
);

CREATE INDEX IF NOT EXISTS ix_guardian_binding_state ON guardian_binding (state);

-- guardian_off_request (state): WP-P2 (phase 8, CONSOLE_STATE_ACTIONS). A request to switch a guardian feature off on an AI system that is in production or has a high risk level. A second person, not the requester, approves or rejects it; only an approval writes the guardian_binding row. The reason is required. Changes go on the chain as binding_change (ids, enums and a reason hash).
CREATE TABLE IF NOT EXISTS guardian_off_request (
  request_id TEXT NOT NULL,
  system_id TEXT NOT NULL,
  feature_slug TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  decided_by TEXT,
  decision_reason TEXT,
  created_at TEXT NOT NULL,
  decided_at TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (request_id)
);

CREATE INDEX IF NOT EXISTS ix_guardian_off_request_system_id_status ON guardian_off_request (system_id, status);

-- intake_attempt (state): WP-O1 (phase 9, ONBOARD_INTAKE). One numbered intake of the source code of an inventory candidate or an agent: a zip upload, a clone or (later) a workspace folder. Re-upload makes attempt n+1; old attempts stay. The files are stored scrubbed under DATA_DIR/intake/<node_id>/<n>/ (the WP16 scrubber runs before anything is written); this row holds only the source reference (no secrets), the SHA-256 and size of what was received, the count of stored files and a counts-only detail note. status: scrubbed (stored after the scrub), failed (refused; detail has the code), stored (reserved).
CREATE TABLE IF NOT EXISTS intake_attempt (
  attempt_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  n INTEGER NOT NULL,
  source_kind TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  file_count INTEGER NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (attempt_id)
);

CREATE INDEX IF NOT EXISTS ix_intake_attempt_node_id_n ON intake_attempt (node_id, n);

-- regkb_draft (state): WP-L1. A draft duty that the law agent read from the stored official text of one instrument, one row per draft. A draft is never an obligation: a person with regkb.confirm sets status confirmed or dropped. text_vi is a verbatim quote that the rules checked against the stored article text. source is model (the agent) or rule (a deterministic parser); model_id and prompt_version say which model and prompt wrote it (a mock model has mock in model_id). The CLI python -m supervisor.regkb.lawagent --export-confirmed turns confirmed rows into regulations YAML for a pull request; the app cannot edit repo files. No PII: law text only.
CREATE TABLE IF NOT EXISTS regkb_draft (
  draft_id TEXT NOT NULL,
  instrument_id TEXT NOT NULL,
  article TEXT NOT NULL,
  duty_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  trigger TEXT NOT NULL,
  evidence_asked TEXT NOT NULL,
  text_vi TEXT NOT NULL,
  summary_en TEXT NOT NULL,
  source TEXT NOT NULL,
  model_id TEXT,
  prompt_version TEXT,
  status TEXT NOT NULL,
  confirmed_by TEXT,
  confirmed_at TEXT,
  run_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (draft_id)
);

CREATE INDEX IF NOT EXISTS ix_regkb_draft_instrument_id_status ON regkb_draft (instrument_id, status);

-- obligation_status (state): WP-L2. One row per duty (RegKB obligation) that applies to one AI system, written by the Duties step of the register workflow v2 on submit. applies is the matrix answer (the step writes yes rows only); coverage says how well Supervisor controls cover the duty (full, partial, none, unknown); status is the work state (open, closed, waived). closing_control is a Supervisor control id or a bank manual control, set later (WP-L3). No PII, no free text from a person. Advisory only: not legal advice, bank counsel must confirm.
CREATE TABLE IF NOT EXISTS obligation_status (
  status_id TEXT NOT NULL,
  system_id TEXT NOT NULL,
  obligation_id TEXT NOT NULL,
  instrument_id TEXT NOT NULL,
  applies TEXT NOT NULL,
  coverage TEXT NOT NULL,
  status TEXT NOT NULL,
  owner_user TEXT NOT NULL,
  due_date TEXT,
  closing_control TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (status_id)
);

CREATE INDEX IF NOT EXISTS ix_obligation_status_system_id_status ON obligation_status (system_id, status);

-- onboard_facts (state): WP-O2 (phase 9, ONBOARD_FACTS). One fact about an agent or candidate, found by Discover and Understand on one stored intake attempt (the scrubbed tree): a tool, model, endpoint, dataset, file, secret use (kind only), external URL, MCP server, approval point, the autonomy level, the Decision 33 proposal or a weak spot. Every fact row has the file, the line and a scrubbed quote of at most 200 characters (no secret, no personal data). source is rule (deterministic) or model (a claim of the real gateway model that passed validate_llm_claims; model_id says which, and a mock model is named mock). A summary row (kind summary) per build counts the dropped_claims (model claims without evidence). Building again for the same attempt replaces that attempt's rows: a fact that is found again keeps its fact_id and is updated; a fact that is not found again gets active false (the state store has no delete). Readers use active rows only. kind claim holds the purpose, the personal data fields and the model claims that are not weak spots.
CREATE TABLE IF NOT EXISTS onboard_facts (
  fact_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  attempt_n INTEGER NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  detail TEXT,
  file TEXT,
  line INTEGER,
  quote TEXT,
  source TEXT NOT NULL,
  model_id TEXT,
  dropped_claims INTEGER,
  active INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (fact_id)
);

CREATE INDEX IF NOT EXISTS ix_onboard_facts_node_id_attempt_n ON onboard_facts (node_id, attempt_n);

-- predeploy_report (state): WP-O3 (phase 9, ONBOARD_PREDEPLOY). One pre-deploy assessment of one intake attempt of an inventory candidate or agent. It joins the facts card (onboard_facts), the readiness advisor, the assurance packs with launch_gate required (run in the launch sandbox with the gate in SHADOW and the synthetic world), the multi-turn red-team pack (advisory) and the duties matrix (when CONSOLE_REGISTER_DUTIES is on and a draft exists for the node). status: queued, running, done or failed (the run itself broke). verdict is deterministic from the items: no_go (a fail item in a required section), questions (a question item), go, or none (not finished). The model never sets it. items is a JSON list of {section, id, status ok | warn | fail | question | skip, text, pointer}; text is scrubbed, no personal data, integers only. A run on a mock agent says mock in the item text. A report is never updated after it is done; Run again writes a new report_id.
CREATE TABLE IF NOT EXISTS predeploy_report (
  report_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  attempt_n INTEGER NOT NULL,
  status TEXT NOT NULL,
  verdict TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  items_total INTEGER NOT NULL,
  items_fail INTEGER NOT NULL,
  items_question INTEGER NOT NULL,
  summary TEXT NOT NULL,
  items TEXT NOT NULL,
  model_id TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (report_id)
);

CREATE INDEX IF NOT EXISTS ix_predeploy_report_node_id_attempt_n ON predeploy_report (node_id, attempt_n);

-- onboard_log (append_only): WP-O5 (phase 9, ONBOARD_POSTDEPLOY). The agent log: one row per onboarding action of a candidate or agent, shown in the console as a timeline "plan, read, found, suggest". step names the onboarding step: scan (the node became a candidate), intake (a source was taken in), facts, predeploy, attach, postdeploy, state (Request or Approve RUNNING) or duties. by_kind says who did it: rule (deterministic code), model (the gateway model produced the content, a mock model says so in what) or person (actor is the person id). what is a short scrubbed sentence of at most 300 characters; pointer is where to look (file:line, report id, row id or pack id) at most 200 characters. Rows are never updated or deleted. No personal data, no secret, no float; counts are integers. A write failure never fails the action that was logged.
CREATE TABLE IF NOT EXISTS onboard_log (
  log_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  attempt_n INTEGER,
  step TEXT NOT NULL,
  what TEXT NOT NULL,
  pointer TEXT NOT NULL,
  by_kind TEXT NOT NULL,
  actor TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (log_id)
);

CREATE INDEX IF NOT EXISTS ix_onboard_log_node_id_at ON onboard_log (node_id, at);

CREATE TRIGGER IF NOT EXISTS trg_onboard_log_no_update
BEFORE UPDATE ON onboard_log
BEGIN
  SELECT RAISE(ABORT, 'onboard_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_onboard_log_no_delete
BEFORE DELETE ON onboard_log
BEGIN
  SELECT RAISE(ABORT, 'onboard_log is append-only');
END;

-- classification_v2 (state): WP-C1 (phase 12, CLASSIFICATION_V2). One record of the classification tree (config/classification.yaml) for one AI system: the path from the first question to an outcome (not_system, prohibited, high_certify, high_self, medium, low), decided by a person and approved by a different person (Circular 53 Art. 4(3)). path_json is a JSON list of steps {node, answer, source (rules | person | decision33), evidence (a pointer: file:line, table row id or document id, at most 200 characters), note (at most 300 characters, masked)}; a step of the Decision 33 sub-flow also carries the answers of its questions. No personal data, no floats. inherited_from_provider: the bank took the provider's result (Art. 4(4)). valid_until: the yearly review date (Art. 4(5)), set again at approval. approved_by and approved_at are null until a second person approves; only then does the risk level of the system change (floor rule, never lowers). Changes go on the chain as classification_v2.
CREATE TABLE IF NOT EXISTS classification_v2 (
  classification_id TEXT NOT NULL,
  system_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  path_json TEXT NOT NULL,
  tree_sha256 TEXT NOT NULL,
  path_hash TEXT NOT NULL,
  decided_by TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT,
  inherited_from_provider INTEGER NOT NULL,
  valid_until TEXT NOT NULL,
  created_at TEXT NOT NULL,
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (classification_id)
);

CREATE INDEX IF NOT EXISTS ix_classification_v2_system_id ON classification_v2 (system_id);
