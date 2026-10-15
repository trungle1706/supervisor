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
  PRIMARY KEY (event_id)
);

CREATE INDEX IF NOT EXISTS ix_agent_event_agent_id_ts ON agent_event (agent_id, ts);

CREATE INDEX IF NOT EXISTS ix_agent_event_trace_id ON agent_event (trace_id);

DROP TRIGGER IF EXISTS trg_agent_event_no_update;

CREATE TRIGGER trg_agent_event_no_update
BEFORE UPDATE OF event_id, ts, trace_id, span_id, parent_span_id, agent_id, agent_version, caller_agent_id, event_type, tool_name, args_hash, amount_minor, currency, status, latency_ms, env, classification, source, capture_level, mask_version ON agent_event
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
  PRIMARY KEY (verdict_id)
);

CREATE INDEX IF NOT EXISTS ix_verdict_agent_id_ts ON verdict (agent_id, ts);

CREATE INDEX IF NOT EXISTS ix_verdict_trace_id ON verdict (trace_id);

DROP TRIGGER IF EXISTS trg_verdict_no_update;

CREATE TRIGGER trg_verdict_no_update
BEFORE UPDATE OF verdict_id, ts, trace_id, event_id, agent_id, tier, checker_id, model_id, model_family, is_mock, advisory, score, label, action, latency_ms, rule_id, policy_hash, score_bp, role, region, model_version, mask_version ON verdict
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
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (metric_date, agent_id)
);

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
