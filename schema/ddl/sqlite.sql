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
  PRIMARY KEY (event_id)
);

CREATE INDEX IF NOT EXISTS ix_agent_event_agent_id_ts ON agent_event (agent_id, ts);

CREATE INDEX IF NOT EXISTS ix_agent_event_trace_id ON agent_event (trace_id);

CREATE TRIGGER IF NOT EXISTS trg_agent_event_no_update
BEFORE UPDATE ON agent_event
BEGIN
  SELECT RAISE(ABORT, 'agent_event is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_agent_event_no_delete
BEFORE DELETE ON agent_event
BEGIN
  SELECT RAISE(ABORT, 'agent_event is append-only');
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
  PRIMARY KEY (verdict_id)
);

CREATE INDEX IF NOT EXISTS ix_verdict_agent_id_ts ON verdict (agent_id, ts);

CREATE INDEX IF NOT EXISTS ix_verdict_trace_id ON verdict (trace_id);

CREATE TRIGGER IF NOT EXISTS trg_verdict_no_update
BEFORE UPDATE ON verdict
BEGIN
  SELECT RAISE(ABORT, 'verdict is append-only');
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
  PRIMARY KEY (case_id, seq)
);

CREATE TRIGGER IF NOT EXISTS trg_case_event_no_update
BEFORE UPDATE ON case_event
BEGIN
  SELECT RAISE(ABORT, 'case_event is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_case_event_no_delete
BEFORE DELETE ON case_event
BEGIN
  SELECT RAISE(ABORT, 'case_event is append-only');
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
  row_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (metric_date, agent_id)
);
