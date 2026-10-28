"""Settings for every target. One codebase; the environment is chosen by config only.

Values come from environment variables and ``.env`` (pydantic-settings).
Rules enforced at load:

* ``DATABRICKS_TOKEN`` set anywhere (env or .env) -> hard failure (OAuth only).
* ``LLM_BASE_URL`` must be loopback unless ``LLM_ALLOW_REMOTE=1``.
* Every path is resolved to an absolute path once, here. Relative paths are
  resolved against the repo root (not the current directory), so the same
  database is used wherever the command starts.
* ``.env`` is read from the repo root, or from ``SUPERVISOR_ENV_FILE`` if set.
* Values that start with ``FILL-ME`` count as "not configured".

Databricks App mode (``SUPERVISOR_MODE=databricks_app``, WP10):

* The platform injects ``DATABRICKS_HOST`` (often without ``https://``),
  ``DATABRICKS_CLIENT_ID`` and ``DATABRICKS_CLIENT_SECRET`` (the App service principal).
  These are enough: no CLI profile is needed. The secret is a ``SecretStr`` and is never
  printed.
* ``LLM_ENDPOINT`` (bound from the ``serving_endpoint`` resource) names the workspace's
  own model-serving endpoint. When ``LLM_BASE_URL`` is not set explicitly, the LLM
  settings become the endpoint's OpenAI-compatible path
  ``https://<DATABRICKS_HOST>/serving-endpoints`` with ``LLM_MODEL=<endpoint name>``.
  ``LLM_ALLOW_REMOTE`` is implied for that URL only: the LLM is the workspace's own
  endpoint, so no data leaves the workspace. Any other non-loopback URL is still refused
  unless ``LLM_ALLOW_REMOTE=1``.
* ``SPOOL_DIR`` is accepted as an alias of ``RECORDER_SPOOL_DIR`` (a UC Volume path on the
  App, because ``/tmp`` is wiped on restart).
"""

from __future__ import annotations

import ipaddress
import logging
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from supervisor.core.errors import ConfigError

PLACEHOLDER_PREFIX = "FILL-ME"
FORBIDDEN_ENV = "DATABRICKS_TOKEN"
REPO_ROOT = Path(__file__).resolve().parents[2]

Mode = Literal["laptop", "databricks_app", "dev"]
# Dev-only pseudonym key (labelled ``dev`` in mask_version). Set MASK_HMAC_KEY for real use.
DEV_MASK_HMAC_KEY = b"supervisor-DEV-ONLY-mask-key-not-secret"
SqlBackend = Literal["auto", "sqlite", "databricks_rest"]


def is_placeholder(value: str | None) -> bool:
    return value is None or value.strip() == "" or value.strip().startswith(PLACEHOLDER_PREFIX)


def is_volume_path(path: object) -> bool:
    """True for a Unity Catalog Volume path (``/Volumes/<catalog>/<schema>/<volume>/...``)."""
    return path is not None and str(path).replace("\\", "/").startswith("/Volumes/")


def volume_mounted(path: object) -> bool:
    """True when the Volume of ``path`` is visible as a local folder."""
    parts = str(path).replace("\\", "/").strip("/").split("/")
    return len(parts) >= 4 and os.path.isdir("/" + "/".join(parts[:4]))


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def env_file_path() -> Path:
    """The .env file Settings reads: SUPERVISOR_ENV_FILE or <repo root>/.env."""
    custom = os.environ.get("SUPERVISOR_ENV_FILE")
    return Path(os.path.abspath(custom)) if custom else REPO_ROOT / ".env"


def _env_file_keys(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    keys = set()
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key.startswith("export "):
                key = key[len("export ") :].strip()
            keys.add(key)
    return keys


def check_no_databricks_token(env_file: Path | None = None) -> None:
    """Raise ConfigError if DATABRICKS_TOKEN is set. Never shows the value."""
    env_file = env_file or env_file_path()
    if FORBIDDEN_ENV in os.environ:
        raise ConfigError(
            "DATABRICKS_TOKEN is set in the environment. Personal access tokens are not "
            "allowed (OAuth only). Fix: set DATABRICKS_TOKEN=   then run "
            "databricks auth login --host <host> --profile <profile>"
        )
    if FORBIDDEN_ENV in _env_file_keys(env_file):
        raise ConfigError(f"DATABRICKS_TOKEN appears in {env_file}. Remove that line (OAuth only).")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # set per load in load_settings()
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    supervisor_mode: Mode = "laptop"
    data_dir: Path = Path("data/local")
    host: str = Field(default="127.0.0.1", validation_alias="SUPERVISOR_HOST")
    port: int = Field(default=8000, validation_alias="SUPERVISOR_PORT")
    log_level: str = "INFO"

    # Network
    ssl_os_truststore: bool = False

    # SQL backend: auto = sqlite for laptop/dev, databricks_rest for databricks_app
    sql_backend: SqlBackend = "auto"
    sqlite_path: Path | None = None
    table_prefix: str = Field(default="", pattern=r"^[a-z0-9_]*$")

    # Databricks (OAuth only: CLI profile on the laptop, platform SP on the App)
    databricks_host: str | None = None
    databricks_config_profile: str | None = None
    databricks_auth_type: str | None = None
    # Injected by the Databricks App platform (service principal, OAuth M2M). Never printed.
    databricks_client_id: str | None = None
    databricks_client_secret: SecretStr | None = None
    databricks_warehouse_id: str | None = None
    databricks_warehouse_name: str | None = None
    databricks_catalog: str | None = None
    databricks_schema: str | None = None
    databricks_sql_transport: Literal["rest"] = "rest"
    databricks_retry_timeout_s: int = Field(default=90, ge=60, le=120)
    databricks_statement_deadline_s: int = Field(default=120, ge=10, le=600)
    # Gate time budgets (WP-P6). The defaults fit a local SQLite store. On Databricks every store
    # round trip is a Statement Execution call (1 to 3 s), so a decision does not fit in 2 s:
    # raise GATE_DECISION_TIMEOUT_S and read the policy and the agent state less often.
    gate_decision_timeout_s: float = Field(default=2.0, ge=0.5, le=120)
    policy_refresh_s: float = Field(default=5.0, ge=0, le=3600)
    state_cache_ttl_s: float = Field(default=1.0, ge=0, le=3600)
    # GATE_RECORD_ASYNC (default off): the gate answers as soon as the decision is final and
    # writes the verdict, the event and the chain record afterwards in its own thread.
    gate_record_async: bool = False
    # WP-P3 (live-run hardening, all default off). SCHEMA_SELFCHECK: at start, compare the
    # tables and columns of schema/model.yaml with the warehouse (information_schema, read only)
    # and show the SQL plan at /console/admin/schema. The app never runs DDL itself.
    # HEALTHZ_MODEL_PROBE: /healthz adds model_resource from a cheap call to the LLM gateway,
    # made in the background and cached for 60 s.
    schema_selfcheck: bool = False
    healthz_model_probe: bool = False
    # WP10: shared all-purpose cluster for the Command Execution API runner (optional).
    databricks_cluster_id: str | None = None
    databricks_cluster_name: str | None = None
    databricks_command_deadline_s: int = Field(default=1800, ge=30, le=14400)

    # LLM (OpenAI-compatible). Empty base URL = mock judges only.
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_allow_remote: bool = False
    llm_model: str = "qwen3:4b"
    llm_api_key: SecretStr | None = None
    llm_timeout_s: int = Field(default=600, ge=1)
    llm_max_tokens: int = Field(default=8192, ge=16)  # WP2: cap against repetition loops
    llm_mock: bool = False  # WP2: LLM_MOCK=1 forces MockChat even when LLM_BASE_URL is set
    llm_endpoint: str | None = None  # Databricks serving endpoint name (App binding)
    # D14: Anthropic's OpenAI-compatible endpoint needs strict json_schema without minimum,
    # maximum, pattern, maxItems and refuses `temperature`. Defaults keep the old request.
    llm_strict_schema: bool = False  # strict:true + schema copy without the refused keywords
    llm_send_temperature: bool = True  # false = leave temperature out of the request
    # WP-P3: wire shape. "chat" = POST {base}/chat/completions; "responses" = POST
    # {base}/responses (OpenAI responses API, Databricks AI Gateway model service).
    llm_api_shape: Literal["chat", "responses"] = "chat"
    # WP-P4 (sandbox-only): judge calls to the workspace model service use the signed-in
    # user's forwarded token (X-Forwarded-Access-Token) instead of the App service principal.
    # Judge calls then run under the user's identity. Off by default.
    llm_user_token_forward: bool = False
    # WP-P5 (sandbox-only): inside a request that carries a forwarded user token, every SQL
    # statement runs with that token against the same warehouse/catalog/schema. Outside a
    # request the App service principal is used. Needs databricks_app + databricks_rest.
    sql_user_token_forward: bool = False

    # Judges (WP5). Advisory only. Empty JUDGE_T*_MODEL = MockJudge (labelled mock).
    # Empty JUDGE_T*_BASE_URL = LLM_BASE_URL. JUDGE_T*_FAMILY overrides the family that is
    # read from the model name (needed when the name does not show it).
    judge_enabled: bool = False  # new feature: off by default
    judge_t1_model: str = ""
    judge_t1_base_url: str = ""
    judge_t1_family: str | None = None
    judge_t2_model: str = ""
    judge_t2_base_url: str = ""
    judge_t2_family: str | None = None
    judge_challenger_model: str = ""  # empty = no challenger
    judge_challenger_base_url: str = ""
    judge_challenger_family: str | None = None
    judge_challenger_tier: int = Field(default=1, ge=1, le=2)
    judge_challenger_sample_bp: int = Field(default=500, ge=0, le=10000)  # 5 %
    judge_t2_sample_bp: int = Field(default=200, ge=0, le=10000)  # random Tier 2 sample
    judge_t1_threshold_bp: int = Field(default=5000, ge=0, le=10000)  # escalate to Tier 2
    judge_t2_threshold_bp: int = Field(default=5000, ge=0, le=10000)  # Tier 2 confirms
    judge_disagree_bp: int = Field(default=3000, ge=0, le=10000)  # gap logged as large_gap
    judge_k_suspicious: int = Field(default=3, ge=1)  # K flags in window -> open_case high
    judge_window_s: int = Field(default=3600, ge=1)
    judge_timeout_s: int = Field(default=120, ge=1)
    judge_max_retries: int = Field(default=1, ge=0, le=3)
    judge_max_input_chars: int = Field(default=12000, ge=1000)
    judge_region: str = "local"  # logged in each verdict (residency, analysis 07 3.1)
    judge_api_key: SecretStr | None = None  # empty = LLM_API_KEY
    judge_sample_salt: str = "supervisor-judge-v1"
    # D05: the judge family is derived from the model id (and endpoint metadata). A declared
    # JUDGE_*_FAMILY that disagrees is refused unless this flag is set; never in databricks_app.
    judge_family_override_test_only: bool = False
    # WP-L2: sandbox / single-model workspaces. A judge, guard or scorer model that shares the
    # family of a registered agent runs anyway (one WARNING per pair); every verdict then carries
    # independence "reduced" and family_conflict true. Unlike the test-only override above it is
    # allowed in databricks_app mode. The judge advises with reduced independence.
    judge_family_conflict_allow: bool = False
    judge_family_probe: bool = False  # ask GET /models of the judge endpoint for its family
    # D05 transition: 0 = a declared family is accepted (warning, family_source
    # declared-unverified) for a model id that shows no family. A clash is always refused.
    judge_family_strict: bool = True
    # D15: manifests of these agent ids (CSV) count as judged by the challenger, besides the
    # registered, non-retired agents of the store. Empty = registry only.
    judge_agents: str = ""
    # Judge model-risk management (WP19, docs/judge-mrm.md). Role names are FILL-ME until
    # the bank names them. Thresholds are illustrative defaults; second line sets them.
    judge_require_validation: bool = False  # new: refuse to judge without a passing record
    mrm_model_owner: str = "FILL-ME-model-owner"
    mrm_model_developer: str = "FILL-ME-model-developer"
    mrm_validator: str = "FILL-ME-independent-validator"
    mrm_approver: str = "FILL-ME-approver"
    mrm_min_catch_bp: int = Field(default=8000, ge=0, le=10000)
    mrm_max_false_alarm_bp: int = Field(default=2000, ge=0, le=10000)
    mrm_min_lang_catch_bp: int = Field(default=7000, ge=0, le=10000)  # each of vi, en
    mrm_min_injection_detect_bp: int = Field(default=8000, ge=0, le=10000)
    mrm_max_injection_lowered_bp: int = Field(default=0, ge=0, le=10000)
    mrm_max_canary_leak_bp: int = Field(default=0, ge=0, le=10000)
    mrm_max_challenger_disagree_bp: int = Field(default=3000, ge=0, le=10000)
    mrm_max_stability_range_bp: int = Field(default=1000, ge=0, le=10000)
    mrm_min_agreement_bp: int = Field(default=8000, ge=0, le=10000)  # judge vs human
    mrm_min_agreement_pairs: int = Field(default=5, ge=1)  # fewer pairs: no case raised
    incident_holidays_file: Path = Path("config/vn_holidays.yaml")  # bank-editable

    # Evidence chain (WP6). Root entries commit all lane heads and are signed.
    evidence_root_every_n: int = Field(default=100, ge=1)  # entries between signed roots
    evidence_root_every_s: int = Field(default=900, ge=1)  # seconds between signed roots
    evidence_retention_days: int = Field(default=1825, ge=1)  # Delta log/file retention
    evidence_writer_id: str | None = None  # default: <hostname>:<pid>
    signer_kind: Literal["ed25519_file", "env", "uc_volume"] = "ed25519_file"
    signer_key_path: Path | None = None  # default: <data_dir>/keys/evidence_ed25519.pem
    signer_env_var: str = Field(default="SUPERVISOR_SIGNING_KEY", pattern=r"^[A-Z][A-Z0-9_]*$")
    signer_key_managed: bool = False  # True only when the bank manages the key (label)
    # Key continuity: refuse to start the chain writer when the loaded key differs from the
    # key of the latest root_commit, unless this is set (then a key_rotation entry is written).
    signer_allow_rotation: bool = False
    # HMAC key for tool-argument digests (args_hash / args_hmac). Empty = fixed dev key,
    # labelled key id "dev" in every chain payload. Set ARGS_HASH_KEY in production.
    args_hash_key: SecretStr | None = None
    anchor_kind: Literal["worm_dir", "uc_volume"] = "worm_dir"
    anchor_path: str | None = None  # worm_dir: default <data_dir>/anchors; uc_volume: /Volumes/..
    casefile_dir: Path | None = None  # default: <data_dir>/casefiles
    casefile_decision33_text: str = (
        "FILL-ME: Decision 33 classification (bank counsel to supply the Appendix wording)"
    )
    casefile_pdf_font: Path | None = None  # Unicode TTF for PDF (VN text); none -> HTML

    # Recorder (WP4): masking at capture, OTLP/HTTP receiver, spool.
    masker_kind: Literal["vn_regex", "presidio", "none"] = "vn_regex"
    mask_hmac_key: SecretStr | None = None  # empty -> DEV_MASK_HMAC_KEY (labelled dev)
    mask_key_id: str = Field(default="", pattern=r"^[A-Za-z0-9_.-]*$")  # recorded in mask_version
    capture_default_level: Literal["digest", "masked"] = "masked"  # agents with no manifest
    otlp_max_body_bytes: int = Field(default=4_000_000, ge=1024)
    otlp_max_spans: int = Field(default=5000, ge=1)
    # Set by the loader (never by you): the Volume DATA_DIR that was not mounted (App only).
    data_dir_requested: str | None = Field(default=None, exclude=True)
    recorder_spool_dir: Path | None = Field(  # default: <data_dir>/spool
        default=None,
        validation_alias=AliasChoices("recorder_spool_dir", "spool_dir"),
    )

    # Reviewer console (WP8). Identity: dev_header (laptop: X-Dev-User + config/users.yaml,
    # not a real identity) or databricks_app (SSO headers + config/auth.yaml role map).
    # auto = databricks_app when SUPERVISOR_MODE=databricks_app, else dev_header.
    auth_kind: Literal["auto", "dev_header", "databricks_app"] = "auto"
    users_file: Path | None = None  # default: <repo>/config/users.yaml
    auth_config_file: Path | None = None  # default: <repo>/config/auth.yaml
    console_lang: Literal["en", "vi"] = "en"  # default UI language (?lang= overrides)
    console_export_dir: Path | None = None  # audit packs; default: <data_dir>/exports
    console_onboard_enabled: bool = False  # WP12: Onboard "Start" in the console (new: off)
    # --- WP-UX4b --- folders (separated by ";" or ",") the register wizard may run the readiness
    # advisor on. Empty (the default) = the advisor is off in the wizard.
    onboard_allowed_roots: str = ""
    notify_webhook_enabled: bool = False  # new feature: off by default (inbox always on)
    notify_webhook_url: str = ""  # stub: notices are queued, never sent (bank ITSM, WP11)
    # Monitors and in-process scheduler (WP7, ADR D09/D10). Every monitor is off by
    # default. SCHEDULER_ENABLED unset = on in laptop mode, off in other modes.
    scheduler_enabled: bool | None = None
    scheduler_lease_ttl_s: int = Field(default=180, ge=10)
    scheduler_lock_path: Path | None = None  # default: <data_dir>/scheduler.lock (laptop)
    sched_ingest_s: int = Field(default=60, ge=1)
    sched_anchor_s: int = Field(default=900, ge=1)
    sched_case_intake_s: int = Field(default=30, ge=1)
    sched_drift_s: int = Field(default=3600, ge=1)
    sched_fairness_s: int = Field(default=86400, ge=1)
    sched_metrics_s: int = Field(default=3600, ge=1)
    sched_judge_s: int = Field(default=300, ge=1)
    sched_multiagent_s: int = Field(default=300, ge=1)
    sched_quality_s: int = Field(default=900, ge=1)
    regkb_internal_dir: str = ""  # WP13: RegKB internal rules dir (empty = off)
    drift_enabled: bool = False
    drift_window_s: int = Field(default=86400, ge=60)
    drift_baseline_windows: int = Field(default=7, ge=2)
    drift_k: int = Field(default=3, ge=1)
    drift_consecutive: int = Field(default=3, ge=1)
    drift_min_n: int = Field(default=20, ge=1)
    fairness_enabled: bool = False
    fairness_config: Path = Path("config/fairness.yaml")
    metrics_enabled: bool = False
    multiagent_enabled: bool = False
    multiagent_window_s: int = Field(default=3600, ge=1)
    multiagent_limit_minor: int = Field(default=100_000_000, ge=1)  # PAY-08 limit, VND
    quality_enabled: bool = False
    quality_sample_bp: int = Field(default=1000, ge=0, le=10000)
    judge_sweep_settle_s: int = Field(default=60, ge=0)  # judge traces older than this
    # ADR D10: a handoff tool call (context handoff=true) without caller_agent_id fails
    # closed for money / credit / pii_export tools. Off by default.
    require_caller_id: bool = False

    # WP15 integration advisor. Console tab "Integration" (reads reports from
    # INTEGRATION_REPORTS_DIR, default <data_dir>/integration) and the advisor as a
    # run_onboarding stage: both off. RECORDER_SEMCONV maps OpenTelemetry GenAI names
    # (gen_ai.*) in the normaliser (supervisor.recorder.semconv); supervisor.* names win.
    console_integration_enabled: bool = False
    integration_reports_dir: Path | None = None
    onboard_advisor_enabled: bool = False
    recorder_semconv: bool = True

    # WP18 enterprise readiness. Pure additions are on by default (health, security
    # headers, request id, console audit rows); anything that changes phase-1 behaviour
    # is off by default. See docs/enterprise-readiness.md.
    log_format: Literal["text", "json"] = "text"  # json = one JSON object per line
    log_file: Path | None = None  # optional rotating log file (support bundle reads it)
    log_file_max_bytes: int = Field(default=10_000_000, ge=10_000)
    log_file_backups: int = Field(default=3, ge=0, le=20)
    request_id_header: str = Field(default="X-Request-ID", pattern=r"^[A-Za-z][A-Za-z0-9-]*$")
    security_headers_enabled: bool = True  # CSP, X-Frame-Options, nosniff, Referrer-Policy
    hsts_enabled: bool = False  # only behind TLS (the App proxy terminates TLS)
    max_request_bytes: int = Field(default=10_000_000, ge=0)  # 0 = no app-wide limit
    rate_limit_enabled: bool = False  # in-process limit on mutating routes (new: off)
    rate_limit_per_minute: int = Field(default=120, ge=1)  # per principal (else client IP)
    rate_limit_burst: int = Field(default=30, ge=1)
    api_rbac_enabled: bool = False  # role matrix on agent-facing /gate read routes only (new: off)
    console_audit_enabled: bool = True  # console_action row for every mutating action
    retention_enabled: bool = False  # PDPL retention job (ADR D13; new: off)
    retention_raw_days: int = Field(default=90, ge=1)  # agent_event_raw args/result
    retention_masked_days: int = Field(default=365, ge=1)  # masked excerpts
    retention_notice_days: int = Field(default=365, ge=1)  # inbox notice bodies
    retention_dry_run: bool = False  # count only, change nothing
    sched_retention_s: int = Field(default=86400, ge=60)

    # WP14 compliance advisor (advisory only; both off by default). The launch pack writes
    # compliance_matrix.* during onboarding; the console tab reads demo and onboarded products.
    onboard_compliance_enabled: bool = False
    console_compliance_enabled: bool = False
    # WP-L1 law agent: drafts duties from the stored official text of one instrument. The page
    # /console/regkb/<instrument>/drafts and the CLI python -m supervisor.regkb.lawagent need
    # LAWAGENT_ENABLED=1. LAWAGENT_MODEL empty = the bank chat model (LLM_MODEL). A draft is
    # never an obligation until a person confirms it. Not legal advice.
    lawagent_enabled: bool = False
    lawagent_model: str = ""
    # WP-W3 (phase 11): internal documents in RegKB. REGKB_INTERNAL=1 (needs LAWAGENT_ENABLED)
    # lets a person upload a policy (.txt, .md, .pdf with a text layer) under
    # DATA_DIR/regkb/internal/<doc id>/; the law agent drafts duties from the MASKED text through
    # the gateway model; a person confirms rows; they become the instrument VN-INT-<doc id>.
    # Off = upload refused (400 regkb_internal_off) and the loader ignores internal files.
    regkb_internal: bool = False
    regkb_internal_max_mb: int = Field(default=10, ge=1, le=50)
    # WP17 assurance eval packs. Bank-supplied datasets live under ASSURANCE_DATA_DIR/<pack>/;
    # OSV_DB_PATH is a local OSV vulnerability dump. All new features default off.
    assurance_data_dir: Path | None = None
    osv_db_path: Path | None = None
    assurance_licence_allow: str = (
        "MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,PSF-2.0,ISC,Unlicense,0BSD,MPL-2.0,MIT-0"
    )
    assurance_launch_enabled: bool = False  # Launch adds assurance NO-GO items
    # Launch GO may rest on mock pack results only when this is on (default off: mock-only
    # results add the NO-GO item "assurance results are mock only"). Any mock result always
    # labels the Launch reason and assurance report MOCK. Demo data sets it; production must not.
    assurance_accept_mock_for_launch: bool = False
    assurance_judge_gate_enabled: bool = True  # non-mock judge needs its judge packs passed
    # Judge gate strictness (per non-mock primary judge, t1 and t2): a validation row needs at
    # least this many items, and status "warn" validates only when allow_warn is on.
    assurance_judge_min_items: int = Field(default=50, ge=1)
    assurance_judge_allow_warn: bool = False
    console_assurance_enabled: bool = False

    # --- WP20: ingress auth (ADR D14, docs/ingress-auth.md) ---
    ingress_auth_enabled: bool = False  # per-agent credential on /gate/check and /v1/traces
    # hmac = per-agent HMAC key; databricks_sp = service-principal bearer token (SCIM Me);
    # databricks_proxy = identity header set by the Apps proxy (App mode only, no SCIM call);
    # both = hmac or databricks_sp; all = the three; auto = databricks_proxy in
    # databricks_app mode, else hmac.
    ingress_credential_kind: Literal[
        "auto", "hmac", "databricks_sp", "databricks_proxy", "both", "all"
    ] = "auto"
    # auto = file on the laptop / dev, env in databricks_app mode.
    ingress_key_store: Literal["auto", "file", "env", "secret_scope"] = "auto"
    ingress_keys_file: Path | None = None  # default: <repo>/config/agent_keys.yaml (chmod 600)
    ingress_identities_file: Path | None = None  # default: <repo>/config/agent_identities.yaml
    ingress_secret_scope: str = ""  # Databricks secret scope for ingress_key_store=secret_scope
    ingress_replay_window_s: int = Field(default=300, ge=1, le=3600)  # timestamp window + nonce TTL
    ingress_max_header_bytes: int = Field(default=512, ge=64, le=8192)  # per credential header
    ingress_identity_cache_ttl_s: int = Field(default=300, ge=0)  # SCIM Me result cache
    ingress_key_cache_ttl_s: int = Field(default=60, ge=0)  # secret scope read cache
    ingress_key_overlap_hours: int = Field(default=24, ge=1)  # rotation: previous key lifetime
    # Review follow-up (F8-F10): pre-auth cost and flood limits.
    ingress_scim_max_concurrent: int = Field(default=4, ge=1)  # parallel SCIM Me calls
    ingress_identity_negative_ttl_s: int = Field(default=30, ge=0)  # cache a refused token
    # 0 = audit every rejection. N = at most one row per (reason, client ip or claimed agent)
    # per N seconds; skipped rows are counted in ingress_audit_suppressed.
    ingress_audit_throttle_s: int = Field(default=0, ge=0)
    ingress_nonce_cap_per_agent: int = Field(default=20_000, ge=1)  # plus the global cap

    # --- WP24b --- masker amounts and inline redaction at the gate (docs/masking.md).
    # MASK_AMOUNTS: type money amounts <AMOUNT:...> in masked text; off = amounts stay in the text
    # (the credit rules need them). INLINE_REDACTION_ENABLED: for pii_export tools (and the tools
    # in INLINE_REDACTION_TOOLS, comma separated) an allowed gate answer carries transformed_args;
    # the SDK / MCP proxy apply them when their own INLINE_REDACTION_ENABLED is on.
    mask_amounts: bool = False
    inline_redaction_enabled: bool = False
    inline_redaction_tools: str = Field(default="", pattern=r"^[A-Za-z0-9_.:@, -]*$")

    # --- WP22 --- tool analytics and least privilege (docs/tool-analytics.md)
    tool_analytics_enabled: bool = False  # scheduler job, /v1/analytics/tools
    sched_tool_analytics_s: int = Field(default=3600, ge=1)
    tool_analytics_window_days: int = Field(default=30, ge=1, le=366)  # "used" lookback
    tool_analytics_min_history_days: int = Field(default=14, ge=1)  # less data = low confidence
    tool_analytics_exceptions_file: Path = Path("config/tool_exceptions.yaml")
    tool_analytics_dir: Path | None = None  # suggested diffs; default <data_dir>/analytics
    console_tools_enabled: bool = False  # the Tools page

    # --- WP21 (SIEM and alerts live). Both default off. SIEM sink details (kind, format,
    # URL, token) are read by supervisor.adapters.integrations.IntegrationSettings from the
    # same environment (SIEM_SINK, SIEM_FORMAT, SIEM_HTTP_URL, ...); only the on/off switch and
    # the job interval live here. ADR D15, docs/siem.md, docs/alerts.md.
    siem_enabled: bool = False
    sched_siem_s: int = Field(default=60, ge=5)
    alerts_enabled: bool = False
    alerts_config: Path = Path("config/alerts.yaml")
    sched_alerts_s: int = Field(default=60, ge=5)
    sched_notify_s: int = Field(default=15, ge=5)
    # Watermark lag: a signal is judged only when it is at least this old. A chain entry gets
    # its ts before its rows commit (seconds on Delta), and lanes commit in any order, so a
    # cursor at "now" would skip entries that become visible late.
    alerts_suppression_max_s: int = Field(default=30 * 86400, ge=0)  # longest planned mute
    alerts_lag_s: int = Field(default=30, ge=0, le=3600)
    notify_webhook_dead_letter: Path | None = None  # default: <data_dir>/notify/webhook.dead.jsonl
    notify_webhook_token: SecretStr | None = None  # bank vault; Authorization: Bearer <token>

    # --- WP24 --- inventory graph and shadow-AI scan (ADR D16; all off by default)
    inventory_enabled: bool = False  # tables are filled, /v1/inventory and the Inventory page work
    sched_inventory_s: int = Field(default=3600, ge=60)  # workspace refresh (databricks_app mode)
    inventory_scan_schemas: str = ""  # "catalog.schema,catalog.schema": UC schemas to list
    inventory_self_app: str = ""  # name of this Databricks App (never reported as shadow AI)
    inventory_allowlist_file: Path | None = None  # default config/inventory_allowlist.yaml
    inventory_workspace_fixture: Path | None = None  # offline: JSON fixture instead of a workspace
    # WP-G3: an unmanaged App, agent endpoint or Genie space becomes a draft ai_system with a
    # default owner. Needs INVENTORY_ENABLED and GOVERNANCE_ENABLED. Default off: the scan
    # behaves as before. Owners come from config/governance.yaml (or GOVERNANCE_CONFIG_FILE).
    # WP-G3 review M2: the six v2 scan sources (model versions, served-entity detail, Genie
    # spaces, jobs, Vector Search indexes, UC functions, MCP connections) and the Genie shadow
    # check. Default off: the scan is the WP24 scan, with the same SDK calls.
    inventory_scan_v2: bool = False
    inventory_autoregister: bool = False
    governance_config_file: Path | None = None

    # --- WP1b-B --- per-agent monitor bindings (D06, docs/monitors.md). Additive: the
    # monitor flags above keep their meaning. A second folder is read after the built-in
    # policies/ and src/supervisor_agents/ (relative paths resolve against the repo root).
    monitor_policy_dir: Path | None = None  # extra folder of policy *.yaml (agents.<id>.monitors)
    monitor_manifest_dir: Path | None = None  # extra folder of <agent>/manifest.yaml

    # --- WP1b-A --- policy folder and fact source of the served app (D13; docs/fact-sources.md)
    policy_dir: Path | None = None  # absolute folder of policy *.yaml; default <repo>/policies
    fact_source: str = ""  # "" = none | sqlite:/abs/file.db | callable:pkg.mod:factory
    fact_query_map: Path | None = None  # YAML query map; required for FACT_SOURCE=sqlite:...
    # CSV package prefixes a FACT_SOURCE=callable: module must sit under (import = code run).
    fact_callable_allow_prefix: str = "supervisor."

    # --- WP-UX1 --- console shell (docs/console.md). CONSOLE_NAV=top is the one-setting rollback
    # to the pill header; the second flag shows the links of pages that WP-UX3 has not built yet
    # (they open a "coming in WP-UX3" page).
    console_nav: Literal["sidebar", "top"] = "sidebar"
    console_nav_placeholders: bool = False
    # Two-section sidebar: "AI Management and Governance" and "AI Guardian and Supervisor",
    # each holding the groups above (new: off; off = the six-group sidebar as before).
    console_nav_sections: bool = False
    # WP-UX4a: one merged left bar (My overview + Governance + Supervisor + a settings gear),
    # section tab strips and the overview pages (new: off; off = the sidebar as before).
    console_nav_v3: bool = False
    # WP-N1: My overview as a dashboard with the candidate triage table, the Candidates tab and
    # GET /v1/candidates (new: off; off = today's My overview page; needs CONSOLE_NAV_V3,
    # GOVERNANCE_ENABLED and, for the candidate table, INVENTORY_ENABLED).
    console_overview_v4: bool = False
    # WP-N2 (route built by another work package): the "My agents" tab. Only the tab is gated here.
    console_my_agents: bool = False
    console_catalog_enabled: bool = False  # /console/catalog: guardian capabilities, on or off
    # WP-N2: My agents tab (/console/my/agents) and the Register and Guardians tabs of the agent
    # page (new: off; off = no tab, the routes answer 400; needs CONSOLE_NAV_V3).
    console_my_agents: bool = False

    # --- WP-UX3 --- new console pages, each behind its own flag (all off by default; off = HTTP
    # 400 with a message and no nav link). The audit-log page flag is CONSOLE_AUDITLOG_ENABLED
    # because CONSOLE_AUDIT_ENABLED already means "write console_action rows" (WP18).
    console_decisions_enabled: bool = False  # /console/decisions
    console_traces_enabled: bool = False  # /console/traces and the span viewer
    console_playground_enabled: bool = False  # /console/playground (dry-run gate check)
    playground_allow_app: bool = False  # PLAYGROUND_ALLOW_APP=1: Playground in databricks_app mode
    console_policies_enabled: bool = False  # /console/policies (read-only)
    console_credentials_enabled: bool = False  # /console/credentials (metadata, never a secret)
    console_users_enabled: bool = False  # /console/users (read-only role map)
    console_auditlog_enabled: bool = False  # /console/audit (console_action rows)
    console_integrations_enabled: bool = False  # /console/integrations (status, read-only)
    # Newest rows a list page reads before it filters in Python (decisions, audit log; the
    # traces list reads CONSOLE_TRACE_SCAN events). A capped list says so. Pilot sizes.
    console_scan_cap: int = Field(default=20000, ge=100, le=200_000)
    console_trace_scan: int = Field(default=5000, ge=100, le=50_000)

    # --- WP25 --- injection classifier (ADR D27, docs/injection-classifier.md).
    # Fail-closed for the classifier is honoured only when this is true AND the model card has an
    # approval (approver + the weights_sha256 it approves). Default false: an outage never stops
    # payments without a named owner (R1). Env name: CLASSIFIER_FAIL_CLOSED_APPROVED.
    classifier_fail_closed_approved: bool = False

    # --- WP-D3 --- guard model (docs/detectors.md section 3d, docs/guard-model-decision.md).
    # Used only when DETECTORS_ENABLED=1 and config/detectors.yaml has a guard_model entry.
    # GUARD_MODEL_ADAPTER: auto (classifier when GUARD_MODEL_URL is set, else the labelled mock),
    # mock, classifier (POST <url> with {"inputs": [...]}) or chat (OpenAI-compatible chat model;
    # base URL GUARD_MODEL_URL or JUDGE_T1_BASE_URL or LLM_BASE_URL, model GUARD_MODEL_NAME or
    # JUDGE_T1_MODEL; the judge family rule applies). A non-loopback URL needs LLM_ALLOW_REMOTE=1.
    guard_model_adapter: Literal["auto", "mock", "classifier", "chat"] = "auto"
    guard_model_url: str = ""
    guard_model_name: str = ""  # model id (pins the approval in the model card)
    guard_model_version: str = ""  # pinned revision; the card approval must name the same
    guard_model_api_key: SecretStr | None = None
    guard_model_timeout_ms: int = Field(default=400, ge=10, le=60_000)
    # Fail-closed and the pause path are honoured only when the model card of the guard model has
    # an approval that names the approver (R1). Env name: GUARD_MODEL_FAIL_CLOSED_APPROVED.
    guard_model_fail_closed_approved: bool = False

    # --- WP26 --- HTTP MCP gateway with tool locking (ADR D24, docs/mcp-gateway.md)
    # MCP_HTTP_ENABLED: the /v1/mcp/tools routes work and the proxy process may start (default
    # off). MCP_TOOL_LOCK: inside the proxy, hold new or changed tools for two-person review
    # (default on; the lock is deterministic and safe). MCP_LOCK_REFRESH_S: how long the proxy
    # trusts one tools/list view before it asks the upstream server again.
    mcp_http_enabled: bool = False
    mcp_tool_lock: bool = True
    mcp_lock_refresh_s: int = Field(default=60, ge=1, le=3600)
    # MCP_TOFU_INGRESS: accept --trust-on-first-use from a proxy over POST /v1/mcp/tools/observe
    # (the name is claimed by the process owner, not verified). Default off (review WP26 F3).
    mcp_tofu_ingress: bool = False
    # MCP_SERVER_AGENTS: extra agents allowed to report on a server another agent registered,
    # "server=agent1|agent2;server2=agent3" (review WP26 F12). Default: only the registering agent.
    mcp_server_agents: str = Field(default="", pattern=r"^[A-Za-z0-9_.:@=|;-]*$")

    # --- WP27 --- session monitor (ADR D29, docs/session-monitor.md). Default off. Per-agent
    # values (thresholds, weights, pause scope) live in the policy file under
    # agents.<id>.monitors.session; these are the global defaults.
    session_monitor_enabled: bool = False
    sched_session_s: int = Field(default=300, ge=10)
    session_window_s: int = Field(default=1800, ge=60, le=86400)
    session_k: int = Field(default=3, ge=1, le=8)
    session_cooldown_s: int = Field(default=3600, ge=60)

    # --- WP28 --- multi-turn Vietnamese red team (docs/redteam-multiturn.md, ADR D25).
    # The nightly job is off by default. The attacker is the offline template attacker unless
    # REDTEAM_ATTACKER_MODEL names a model on the configured LLM endpoint (LLM_BASE_URL).
    redteam_nightly_enabled: bool = False  # scheduler job `redteam_nightly`
    sched_redteam_s: int = Field(default=86400, ge=60)
    redteam_trials: int = Field(default=8, ge=1, le=500)  # per objective, assurance pack
    redteam_nightly_trials: int = Field(default=50, ge=1, le=500)  # per objective, nightly job
    redteam_seed: int = 20261020
    redteam_attacker_model: str = Field(default="", pattern=r"^[A-Za-z0-9_.:/@-]*$")
    redteam_llm_max_conversations: int = Field(default=60, ge=1, le=60)  # hard cap, live runs
    redteam_langs: str = Field(default="vi", pattern=r"^(vi|en|vi,en)$")

    # --- WP29 --- risk register (ADR D26, docs/risk-register.md). All off by default.
    # RISK_REGISTER_ENABLED: /v1/risks routes, the scheduler job risk_evidence and the CLI.
    # CONSOLE_RISKS_ENABLED: the Risks page and the Risks tab on the Agent page (needs the first
    # flag too). Band thresholds and the evidence rule live in config/risk.yaml (ILLUSTRATIVE).
    risk_register_enabled: bool = False
    console_risks_enabled: bool = False
    sched_risk_evidence_s: int = Field(default=21600, ge=60)  # one evidence pass per 6 hours
    risk_evidence_window_days: int = Field(default=7, ge=1, le=90)
    # Packs scored by a judge model count as evidence only when the owner sets this (default 0).
    risk_evidence_judged_packs: bool = False
    risk_config: Path = Path("config/risk.yaml")
    risk_starter_dir: Path = Path(
        "config/risks"
    )  # starter risks (python -m supervisor.risk import)

    # --- WP30 --- control catalogue and task list (ADR D30, docs/controls.md). All off by default.
    # CONTROLS_ENABLED: /v1/controls and /v1/tasks routes, the jobs control_status and task_due,
    # the CLIs. CONSOLE_CONTROLS_ENABLED: the Controls and Tasks pages and Agent tabs (needs the
    # first flag too). TASKS_LAUNCH_GATE_ENABLED: Launch is NO-GO while a required task of the
    # agent's current lifecycle stage is open (needs CONTROLS_ENABLED). The sizing rules and the
    # task templates live in config/tasks.yaml (ILLUSTRATIVE).
    controls_enabled: bool = False
    console_controls_enabled: bool = False
    tasks_launch_gate_enabled: bool = False
    sched_control_status_s: int = Field(default=21600, ge=60)  # one status pass per 6 hours
    sched_task_due_s: int = Field(default=3600, ge=60)
    # Window of a pack result as control evidence (packs run less often than rules fire).
    # Rules and monitors use RISK_EVIDENCE_WINDOW_DAYS (7).
    controls_pack_window_days: int = Field(default=30, ge=1, le=365)
    controls_starter_dir: Path = Path("config/controls")
    tasks_config: Path = Path("config/tasks.yaml")

    # --- WP31 --- transparency report (ADR D31, docs/transparency-report.md). Off by default.
    # TRANSPARENCY_ENABLED: /v1/transparency routes, the scheduler job and the CLI build and sign
    # reports. CONSOLE_TRANSPARENCY_ENABLED: the Transparency page and the Agent tab (needs the
    # first flag too). Files go to TRANSPARENCY_DIR (default <data_dir>/transparency).
    transparency_enabled: bool = False
    console_transparency_enabled: bool = False
    sched_transparency_s: int = Field(default=86400, ge=60)  # one pass per day
    transparency_dir: Path | None = None
    transparency_backlog_file: Path = Path("BACKLOG.md")  # the internal variant lists open items

    # --- WP37 --- detector framework and verdict contract v2 (ADR D23, docs/detectors.md).
    # Off: the gate answers and records exactly as in v0.3.0. On: detectors run after the
    # deterministic rules; the answer gains status, findings, not_executed, coverage,
    # transformed_payload, request_id and correlation_id; findings are stored (table finding).
    detectors_enabled: bool = False
    detectors_config: Path = Path("config/detectors.yaml")
    # --- WP41 --- (ADR D33, docs/detectors.md section 3b). DETECTORS_SCAN_BUDGET_BYTES: the most
    # text all detectors together scan in one call (default 65536; per detector the setting
    # max_scan_bytes, default 16384). None = the value of limits.scan_budget_bytes in the file.
    detectors_scan_budget_bytes: int | None = Field(default=None, ge=1024, le=10_000_000)
    # --- WP-D1 --- document and URL intake (docs/detectors.md "Documents and URLs"). Off: a
    # request with context.documents is refused (HTTP 400) and nothing else changes. On (needs
    # DETECTORS_ENABLED=1): the gate extracts text from the documents and scores it.
    # URL_FETCH_ENABLED=1 + URL_FETCH_ALLOWLIST (comma separated domains) lets the gate fetch a
    # document by URL (HTTPS only, SSRF guard). Both default off; the fetch is the only
    # outbound network call of the intake and only to a listed domain.
    document_intake_enabled: bool = False
    url_fetch_enabled: bool = False
    # PLAYGROUND_URL_FETCH=1: a dry run (Playground) may fetch a URL document. Default 0: a dry
    # run never touches the network and reports the document as unread (dry_run_no_fetch).
    playground_url_fetch: bool = False
    url_fetch_allowlist: str = Field(default="", pattern=r"^[A-Za-z0-9.*_, -]*$", max_length=2000)

    # --- WP38 --- collector catalogue on the Integrations page (ADR D28, docs/collectors.md).
    # Off: the Integrations page is the delivery status page of v0.3.0. On: it is the catalogue
    # (cards, Add creates the agent credential, detail drawer). The policy keys mode and
    # consumers need no flag: they only act when a policy file uses them.
    collectors_enabled: bool = False
    # Base URL shown in the setup text; empty = the address the console was opened with.
    collectors_public_url: str = ""

    # --- WP39 --- activity and analytics parity (ADR D32, docs/console.md, docs/alerts.md).
    # Off: the Decisions drawer and list, the Traces pages and the Analytics tabs are as before.
    # On: verdict v2 drawer (Request, Response, Detections, Metadata), new filters, masked CSV
    # export, Gate tables and a Detectors tab in Analytics (read from decision_daily).
    console_decisions_v2: bool = False
    console_export_max_rows: int = Field(default=5000, ge=1, le=100_000)  # CSV rows, masked cols
    sched_decision_rollup_s: int = Field(default=3600, ge=60)  # decision_daily rollup job

    # --- WP-G0 --- governance shared core: the AI system entity (docs/governance.md). Off by
    # default. GOVERNANCE_ENABLED: /v1/systems routes are mounted. CONSOLE_SYSTEMS_ENABLED: the
    # Systems pages (needs GOVERNANCE_ENABLED too).
    governance_enabled: bool = False
    console_systems_enabled: bool = False
    # --- WP-P2 (phase 8) --- agent state and separation of duties in the console: Request and
    # Approve RUNNING on the agent page, Decision 33 apply (the system owner cannot apply; every
    # answer needs a justification of 20 characters), guardian switch-off (reason; a second
    # person on a production or high-risk system). Off = nothing changes (new: off).
    console_state_actions: bool = False
    # --- WP-O1 (phase 9) --- candidate source intake (docs/onboard.md "Intake"): a zip upload or a
    # clone of an allowed host becomes a numbered, scrubbed attempt under
    # <data_dir>/intake/<node_id>/<n>/. Off = POST /v1/intake and the Source panel answer HTTP 400
    # with the flag name (new: off). ONBOARD_GIT_HOSTS: comma list of host names (empty = the
    # clone intake is off).
    onboard_intake: bool = False
    onboard_intake_max_mb: int = Field(default=20, ge=1, le=200)
    onboard_git_hosts: str = ""
    # --- WP-O2 (phase 9) --- facts card (docs/onboard.md "Facts card"): Discover + Understand run
    # on the server on a stored intake attempt; the facts (file:line + quote each) are stored as
    # onboard_facts rows and feed the inventory graph. Needs ONBOARD_INTAKE for the source. Off =
    # POST /v1/facts and the Facts tab and panel answer HTTP 400 with the flag name (new: off).
    onboard_facts: bool = False
    # --- WP-O3 (phase 9) --- pre-deploy assessment (docs/onboard.md "Pre-deploy assessment"): one
    # report per intake attempt (facts, readiness, required assurance packs in the launch sandbox,
    # the multi-turn red-team pack, the duties matrix). Needs ONBOARD_INTAKE for the source. Off =
    # POST /v1/predeploy, the Pre-deploy tab and panel answer HTTP 400 predeploy_off (new: off).
    onboard_predeploy: bool = False
    # --- WP-O4 (phase 9) --- guardian attachment view (docs/guardian-bindings.md "Attach view"):
    # the Attach tab and panel with the wiring picture, the guardians on the plug point, the last
    # evidence of each and the How to attach env lines. Read only. Off = GET /console/attach/{id}
    # answers HTTP 400 attach_off and the tab and panel are absent (new: off).
    onboard_attach_view: bool = False
    # --- WP-O3b (phase 9) --- packs against the running candidate (docs/assurance.md "HTTP target
    # (WP-O3b)"): the pre-deploy packs that need a running agent send synthetic turns to the
    # candidate's HTTP chat endpoint. Off (default): WP-O3 behaves as before. The allow list is a
    # comma list of host names (exact, or "*.suffix"); empty = no host is allowed = off. The
    # per-candidate block may lower the three limits, never raise them.
    predeploy_http_target: bool = False
    predeploy_http_allowed_hosts: str = ""
    predeploy_http_timeout_s: int = Field(default=30, ge=1, le=120)
    predeploy_http_max_turns: int = Field(default=300, ge=1, le=500)
    predeploy_http_budget_s: int = Field(default=600, ge=10, le=3600)
    # --- WP-O5 (phase 9) --- post-deploy assessment and the agent log (docs/onboard.md
    # "Post-deploy assessment and the agent log"): the Post-deploy tab and panel, the onboard_log
    # rows of every onboarding step, GET /console/postdeploy/{id} and GET /v1/postdeploy/{id}.
    # Off = those routes answer HTTP 400 postdeploy_off, the tab and panel are absent and no
    # onboard_log row is written (new: off).
    onboard_postdeploy: bool = False
    # --- WP-N3 --- register workflow v2 (docs/register-v2.md): /console/register, six steps with
    # a draft row. Needs GOVERNANCE_ENABLED and CONSOLE_SYSTEMS_ENABLED; the agent row step also
    # needs AGENTS_API_ENABLED. Off: the two-step wizard at /console/systems/new.
    console_register_v2: bool = False
    # --- WP-L2 --- Duties step in the register workflow (docs/register-v2.md "Duties step"):
    # a seventh step after the pre-deployment check. Runs the compliance matrix on the draft
    # answers; on submit writes obligation_status rows and one task per open gap. Needs
    # CONSOLE_REGISTER_V2 and GOVERNANCE_ENABLED. Off: six steps, every URL as before.
    console_register_duties: bool = False
    # --- WP-P1 --- tasks and stage approvals in the console (docs/console.md). Off: the Tasks tab
    # of a system is read only and the workflow routes answer HTTP 400 naming this flag. Needs
    # GOVERNANCE_ENABLED and CONSOLE_SYSTEMS_ENABLED (tasks also need CONTROLS_ENABLED).
    console_workflow_actions: bool = False
    # --- WP-L3 (phase 8) --- duties in the risk register and gap tasks (docs/risk-register.md
    # "Duties (WP-L3)"): Duties tab on the system page (close, waive, re-evaluate), the gap closure
    # score, the risk line of kind duties_gap and the My overview dimension. Needs
    # GOVERNANCE_ENABLED and CONSOLE_SYSTEMS_ENABLED. Off: no tab, the routes answer HTTP 400
    # risk_duties_off.
    # RISK_DUTIES_SWEEP_S: scheduler sweep that opens one reminder task per system per week for
    # duties due within 30 days; 0 = off (default), else 300 or more.
    risk_duties: bool = False
    risk_duties_sweep_s: int = Field(default=0, ge=0)
    # --- WP-C2 (phase 12) --- the eight risk types of Circular 53 Art. 14(3) as one status row per
    # AI system (docs/risk-dimensions.md): table risk_dimension_status, the Risk assessment tab on
    # the system page, /v1/systems/{id}/risk-dimensions and /v1/risk-dimensions/summary. Needs
    # GOVERNANCE_ENABLED (the tab also needs CONSOLE_SYSTEMS_ENABLED). Off: no table read, no tab,
    # the routes answer HTTP 400 risk_dimensions_off.
    risk_dimensions: bool = False
    # --- WP-F4 (phase 12) --- the onboarding orchestrator (docs/orchestrator.md): plans the eight
    # risk types for a system, runs the assessment (live factory agent or the rule proposal) under a
    # budget, writes assessment_report_v1 files and risk_dimension_status proposals (never pass).
    # Needs GOVERNANCE_ENABLED, RISK_DIMENSIONS and CLASSIFICATION_V2 (ONBOARD_FACTS adds facts v1).
    # Off: routes answer HTTP 400 orchestrator_off, no table read, the Risk tab is unchanged.
    onboard_orchestrator: bool = False
    # --- WP-F2 (phase 12B) --- the agent factory UI and catalogue (docs/factory.md): tables
    # factory_agent, factory_agent_event, factory_helper_draft; /console/factory and /v1/factory;
    # three helper agents (checklist drafter, golden-set generator, result explainer) that draft
    # only and need LLM_BASE_URL. Needs GOVERNANCE_ENABLED. Off: no table read, the routes answer
    # HTTP 400 agent_factory_off.
    agent_factory: bool = False
    # --- WP-C4 (phase 12) --- portfolio blocks on My overview (docs/console.md "Portfolio blocks"):
    # Classification (a bar per outcome) and Risk assessment (eight types by systems grid), read
    # from the services behind the two summary APIs, and GET /v1/portfolio. Needs
    # CONSOLE_OVERVIEW_V4 and GOVERNANCE_ENABLED; a block shows data only with CLASSIFICATION_V2
    # or RISK_DIMENSIONS on. Off: My overview unchanged, the route answers HTTP 400
    # overview_portfolio_off.
    overview_portfolio: bool = False
    # --- WP-L4 (phase 8) --- evidence per duty and the regulator pack (docs/regulator-pack.md):
    # live counts per control for the duties of a system, auto-close of a full-coverage duty whose
    # mapped controls all work, the group task closes with its last row, the Refresh evidence
    # button, and the signed regulator pack (JSON and HTML) per system. Needs GOVERNANCE_ENABLED
    # and RISK_DUTIES (and so CONSOLE_SYSTEMS_ENABLED). Off: no change, the routes answer HTTP 400
    # regulator_pack_off. DUTY_EVIDENCE_WINDOW_DAYS: window of the counts. DUTY_EVIDENCE_MIN_ROWS:
    # evidence rows a control needs in the window to count as working. DUTY_EVIDENCE_SWEEP_S:
    # scheduler sweep over every system; 0 = off (default), else 300 or more.
    regulator_pack: bool = False
    duty_evidence_window_days: int = Field(default=30, ge=1, le=365)
    duty_evidence_min_rows: int = Field(default=1, ge=1, le=1000000)
    duty_evidence_sweep_s: int = Field(default=0, ge=0)

    # --- WP-G2 --- assignment rules and Decision 33 classification (docs/assignment-rules.md,
    # docs/decision33.md). Both need GOVERNANCE_ENABLED. CLASSIFIER_AI_PREFILL=1 lets the
    # classification draft ask the LLM adapter for answers (tagged ai_prefill; a person applies).
    assignment_rules_config: Path = Path("config/assignment_rules.yaml")
    decision33_config: Path = Path("config/decision33.yaml")
    classifier_ai_prefill: bool = False
    # --- WP-C1 (phase 12) --- classification tree (docs/classification.md). Needs
    # GOVERNANCE_ENABLED. Off = the Decision 33 flow and the register class step are unchanged and
    # the routes answer HTTP 400 classification_v2_off (new: off).
    classification_v2: bool = False
    classification_config: Path = Path("config/classification.yaml")
    # --- WP-G1 (phase 12) --- guardian factory (docs/guardian-factory.md). Needs DETECTORS_ENABLED.
    # Off = the routes answer HTTP 400 guardian_factory_off and nothing is read or written.
    guardian_factory: bool = False
    # --- WP-G1 --- lifecycle, stage approvals, reviews, outbound events (docs/governance.md).
    # Everything is under GOVERNANCE_ENABLED. WEBHOOKS_ENABLED: the outbound event stub marks
    # events delivered and logs them (no network; the real sender is later work).
    webhooks_enabled: bool = False

    # --- WP-S1 --- per-system guardian bindings (docs/guardian-bindings.md). Off by default.
    # GUARDIAN_BINDINGS_ENABLED (needs GOVERNANCE_ENABLED too): a product owner may switch a
    # guardian feature off for the agents of one AI system, except the features in its guardian
    # floor. A binding only narrows what the instance already has on. No binding rows = no change.
    guardian_bindings_enabled: bool = False

    # --- WP-G5 --- governance loop: events to actions, incidents (docs/governance-actions.md).
    # Off by default. GOVERNANCE_ACTIONS_ENABLED (needs GOVERNANCE_ENABLED too): the job
    # governance_actions is scheduled and /v1/incidents and the Incidents tab are mounted.
    # The job never pauses or blocks an agent. GOVERNANCE_ACTIONS_LOOKBACK_S: how far back the
    # first run looks (later runs start at the cursor).
    governance_actions_enabled: bool = False
    governance_actions_config: Path = Path("config/governance_actions.yaml")
    sched_governance_s: int = Field(default=60, ge=5)
    governance_actions_lookback_s: int = Field(default=86400, ge=60, le=2_592_000)

    # --- WP-G6 --- MCP server, skills, KPI endpoint (docs/mcp-server.md). Off by default: nothing
    # is mounted, no table is read or written, the Governance overview is unchanged.
    # MCP_SERVER_ENABLED: POST /mcp (streamable HTTP, JSON-RPC 2.0), /v1/mcp/apps, /v1/kpis and
    # the KPI block of the Governance overview. `python -m supervisor.mcp_server` serves the
    # same router alone on MCP_SERVER_HOST:MCP_SERVER_PORT (loopback unless you change it).
    mcp_server_enabled: bool = False
    mcp_server_host: str = "127.0.0.1"
    mcp_server_port: int = Field(default=8765, ge=1, le=65535)

    # --- WP-P2 --- agent registry API, several policy folders (docs/api.md, docs/policy.md).
    # AGENTS_API_ENABLED (default off): POST /v1/agents, GET /v1/agents/{id} and the gate state
    # route POST /gate/agents/{id}/state work. POLICY_DIR may list several folders separated by the
    # OS path separator (";" on Windows, ":" on Linux); the first is policy_dir, the rest are
    # policy_dir_extra. One folder behaves as before.
    agents_api_enabled: bool = False
    policy_dir_extra: tuple[Path, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _wp_p2_split_policy_dir(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        for key in ("policy_dir", "POLICY_DIR"):
            raw = data.get(key)
            if isinstance(raw, str) and os.pathsep in raw:
                parts = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
                data = dict(data)
                data[key] = parts[0] if parts else None
                extra = []
                for p in parts[1:]:
                    path = Path(p).expanduser()
                    extra.append(
                        Path(os.path.abspath(path if path.is_absolute() else REPO_ROOT / path))
                    )
                if extra:
                    data["policy_dir_extra"] = tuple(extra)
        return data

    @property
    def policy_dirs(self) -> tuple[Path, ...]:
        """WP-P2: every policy folder in load order (empty when POLICY_DIR is not set)."""
        return (self.policy_dir, *self.policy_dir_extra) if self.policy_dir is not None else ()

    @field_validator(
        "data_dir",
        "sqlite_path",
        "signer_key_path",
        "casefile_dir",
        "casefile_pdf_font",
        "recorder_spool_dir",
        "users_file",
        "auth_config_file",
        "console_export_dir",
        "integration_reports_dir",
        "scheduler_lock_path",
        "fairness_config",
        "tool_analytics_exceptions_file",
        "tool_analytics_dir",
        "incident_holidays_file",
        "log_file",
        "assurance_data_dir",
        "osv_db_path",
        "ingress_keys_file",
        "ingress_identities_file",
        "alerts_config",
        "notify_webhook_dead_letter",
        "inventory_allowlist_file",
        "inventory_workspace_fixture",
        "governance_config_file",
        "governance_actions_config",
        "policy_dir",
        "fact_query_map",
        "detectors_config",
        "risk_config",
        "risk_starter_dir",
        "controls_starter_dir",
        "tasks_config",
        "assignment_rules_config",
        "decision33_config",
        "classification_config",
        "transparency_dir",
        "transparency_backlog_file",
        mode="after",
    )
    @classmethod
    def _absolute(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        value = value.expanduser()
        if not value.is_absolute():
            value = REPO_ROOT / value
        return Path(os.path.abspath(value))

    @field_validator("risk_duties_sweep_s", mode="after")
    @classmethod
    def _sweep_s(cls, value: int) -> int:
        if 0 < value < 300:
            raise ValueError("RISK_DUTIES_SWEEP_S must be 0 (off) or 300 or more")
        return value

    @field_validator("duty_evidence_sweep_s", mode="after")
    @classmethod
    def _duty_evidence_sweep_s(cls, value: int) -> int:
        if 0 < value < 300:
            raise ValueError("DUTY_EVIDENCE_SWEEP_S must be 0 (off) or 300 or more")
        return value

    @field_validator("databricks_host", mode="after")
    @classmethod
    def _host_url(cls, value: str | None) -> str | None:
        # The App injects DATABRICKS_HOST without a scheme; the SDK and URLs need https://.
        if value is None or is_placeholder(value):
            return value
        value = value.strip().rstrip("/")
        if "://" not in value:
            value = "https://" + value
        return value

    @model_validator(mode="after")
    def _rules(self) -> Settings:
        self.data_dir_requested = None
        if (
            self.supervisor_mode == "databricks_app"
            and is_volume_path(self.data_dir)
            and not volume_mounted(self.data_dir)
        ):
            # No /Volumes mount in this container: local files (signing key, case files)
            # cannot live on the Volume. Use the ephemeral container disk and say so.
            self.data_dir_requested = str(self.data_dir).replace("\\", "/")
            self.data_dir = Path(os.path.abspath(tempfile.gettempdir())) / "supervisor-data"
            logging.getLogger("supervisor.config").error(
                "DATA_DIR %s is not mounted in this container; using %s (wiped on restart). "
                "Spool and anchors still go to the Volume through the Files API; the evidence "
                "signing key is kept on the Volume (SIGNER_KIND=uc_volume).",
                self.data_dir_requested,
                self.data_dir,
            )
        if self.sqlite_path is None:
            self.sqlite_path = self.data_dir / "supervisor.db"
        if self.signer_key_path is None:
            if self.data_dir_requested:
                # App without a /Volumes mount: the key lives on the Volume (Files API).
                self.signer_key_path = Path(
                    self.data_dir_requested.rstrip("/") + "/keys/evidence_ed25519.pem"
                )
            else:
                self.signer_key_path = self.data_dir / "keys" / "evidence_ed25519.pem"
        if (
            "signer_kind" not in self.model_fields_set
            and self.supervisor_mode == "databricks_app"
            and is_volume_path(self.signer_key_path)
            and not volume_mounted(self.signer_key_path)
        ):
            self.signer_kind = "uc_volume"
        if self.casefile_dir is None:
            self.casefile_dir = self.data_dir / "casefiles"
        if self.recorder_spool_dir is None:
            self.recorder_spool_dir = self.data_dir / "spool"
        if self.users_file is None:
            self.users_file = REPO_ROOT / "config" / "users.yaml"
        if self.auth_config_file is None:
            self.auth_config_file = REPO_ROOT / "config" / "auth.yaml"
        if self.console_export_dir is None:
            self.console_export_dir = self.data_dir / "exports"
        if self.transparency_dir is None:  # WP31
            self.transparency_dir = self.data_dir / "transparency"
        if self.tool_analytics_dir is None:
            self.tool_analytics_dir = self.data_dir / "analytics"
        if self.integration_reports_dir is None:
            self.integration_reports_dir = self.data_dir / "integration"
        if self.auth_kind == "dev_header" and self.supervisor_mode == "databricks_app":
            raise ValueError(
                "AUTH_KIND=dev_header is not allowed with SUPERVISOR_MODE=databricks_app "
                "(the X-Dev-User header is not an identity); use databricks_app or auto"
            )
        if not self.console_audit_enabled and self.supervisor_mode != "dev":
            raise ValueError(
                "CONSOLE_AUDIT_ENABLED=0 is only allowed with SUPERVISOR_MODE=dev "
                "(the console audit trail cannot be switched off in laptop or databricks_app mode)"
            )
        if self.policy_dir is not None and not self.policy_dir.is_dir():
            raise ValueError(f"POLICY_DIR is not a folder: {self.policy_dir}")
        for extra in self.policy_dir_extra:  # WP-P2
            if not extra.is_dir():
                raise ValueError(f"POLICY_DIR is not a folder: {extra}")
        if self.fact_source.strip():
            from supervisor.adapters.facts import callable_target, split_fact_source

            kind, target = split_fact_source(self.fact_source)  # raises ValueError
            if kind == "callable":
                callable_target(target, self.fact_callable_allow_prefix)  # raises ValueError
            if kind == "sqlite":
                db = Path(target).expanduser()
                db = db if db.is_absolute() else REPO_ROOT / db
                self.fact_source = f"sqlite:{os.path.abspath(db)}"
                if self.fact_query_map is None:
                    raise ValueError("FACT_SOURCE=sqlite:... needs FACT_QUERY_MAP")
                if not self.fact_query_map.is_file():
                    raise ValueError(f"FACT_QUERY_MAP is not a file: {self.fact_query_map}")
        if self.judge_family_override_test_only and self.supervisor_mode == "databricks_app":
            raise ValueError(
                "JUDGE_FAMILY_OVERRIDE_TEST_ONLY=1 is not allowed with "
                "SUPERVISOR_MODE=databricks_app (a declared judge family is not an identity)"
            )
        if self.ingress_keys_file is None:
            self.ingress_keys_file = REPO_ROOT / "config" / "agent_keys.yaml"
        if self.ingress_identities_file is None:
            self.ingress_identities_file = REPO_ROOT / "config" / "agent_identities.yaml"
        if self.scheduler_lock_path is None:
            self.scheduler_lock_path = self.data_dir / "scheduler.lock"
        if self.anchor_kind == "worm_dir":
            if self.anchor_path is None:
                self.anchor_path = str(self.data_dir / "anchors")
            else:
                p = Path(self.anchor_path).expanduser()
                self.anchor_path = os.path.abspath(p if p.is_absolute() else REPO_ROOT / p)
        if (
            self.supervisor_mode == "databricks_app"
            and not is_placeholder(self.llm_endpoint)
            and "llm_base_url" not in self.model_fields_set
        ):
            if is_placeholder(self.databricks_host):
                raise ValueError(
                    "LLM_ENDPOINT is bound but DATABRICKS_HOST is not set; the App platform "
                    "injects it. Set DATABRICKS_HOST=https://<workspace host>"
                )
            self.llm_base_url = self.serving_base_url
            if "llm_model" not in self.model_fields_set:
                self.llm_model = str(self.llm_endpoint)
        if (
            self.llm_base_url
            and not self.llm_allow_remote
            and not is_loopback_url(self.llm_base_url)
            and not self.is_workspace_serving_url(self.llm_base_url)
        ):
            raise ValueError(
                "LLM_BASE_URL must be a loopback address (127.0.0.1 / localhost / ::1) "
                "unless LLM_ALLOW_REMOTE=1 (zero AI egress house rule)"
            )
        for name in ("judge_t1_base_url", "judge_t2_base_url", "judge_challenger_base_url"):
            url = getattr(self, name)
            if (
                url
                and not self.llm_allow_remote
                and not is_loopback_url(url)
                and not self.is_workspace_serving_url(url)
            ):
                raise ValueError(
                    f"{name.upper()} must be a loopback address unless LLM_ALLOW_REMOTE=1"
                )
        if self.llm_user_token_forward and not (
            self.supervisor_mode == "databricks_app"
            and bool(self.llm_base_url)
            and self.is_workspace_serving_url(self.llm_base_url)
        ):
            raise ValueError(
                "LLM_USER_TOKEN_FORWARD=1 is allowed only in databricks_app mode and when "
                "LLM_BASE_URL is the workspace serving-endpoints or ai-gateway URL "
                "(sandbox-only: judge calls then run under the signed-in user's identity)"
            )
        if self.sql_user_token_forward and not (
            self.supervisor_mode == "databricks_app"
            and self.effective_sql_backend == "databricks_rest"
        ):
            raise ValueError(
                "SQL_USER_TOKEN_FORWARD=1 is allowed only in databricks_app mode with "
                "SQL_BACKEND=databricks_rest (sandbox-only: SQL then runs as the signed-in user)"
            )
        if self.databricks_catalog and not is_placeholder(self.databricks_catalog):
            _check_identifier("DATABRICKS_CATALOG", self.databricks_catalog)
        if self.databricks_schema and not is_placeholder(self.databricks_schema):
            _check_identifier("DATABRICKS_SCHEMA", self.databricks_schema)
        return self

    @property
    def serving_base_url(self) -> str:
        """OpenAI-compatible base URL of the workspace's model-serving endpoints."""
        return f"{self.databricks_host}/serving-endpoints"

    @property
    def gateway_base_url(self) -> str:
        """WP-P3: base URL of the workspace AI Gateway (Unity Catalog model services)."""
        return f"{self.databricks_host}/ai-gateway/mlflow/v1"

    def is_workspace_serving_url(self, url: str) -> bool:
        """True only in databricks_app mode for ``<DATABRICKS_HOST>/serving-endpoints``
        or ``<DATABRICKS_HOST>/ai-gateway/mlflow/v1`` (WP-P3).

        This is the implied ``LLM_ALLOW_REMOTE``: the workspace's own endpoint, reached
        with the App's own identity, is not AI egress."""
        if self.supervisor_mode != "databricks_app" or is_placeholder(self.databricks_host):
            return False
        return url.rstrip("/") in (self.serving_base_url, self.gateway_base_url)

    @property
    def llm_uses_workspace_auth(self) -> bool:
        """The LLM is the bound serving endpoint: authenticate with the workspace identity."""
        return bool(self.llm_base_url) and self.is_workspace_serving_url(self.llm_base_url)

    @property
    def databricks_auth_kind(self) -> Literal["service_principal", "cli_profile", "sdk_default"]:
        """Which OAuth flow the SDK uses. Never a PAT."""
        if not is_placeholder(self.databricks_config_profile):
            return "cli_profile"
        secret = self.databricks_client_secret
        if (
            not is_placeholder(self.databricks_client_id)
            and secret is not None
            and not is_placeholder(secret.get_secret_value())
        ):
            return "service_principal"
        return "sdk_default"

    @property
    def effective_sql_backend(self) -> Literal["sqlite", "databricks_rest"]:
        if self.sql_backend != "auto":
            return self.sql_backend
        return "databricks_rest" if self.supervisor_mode == "databricks_app" else "sqlite"

    @property
    def effective_auth_kind(self) -> Literal["dev_header", "databricks_app"]:
        if self.auth_kind != "auto":
            return self.auth_kind
        return "databricks_app" if self.supervisor_mode == "databricks_app" else "dev_header"

    @property
    def effective_ingress_kind(
        self,
    ) -> Literal["hmac", "databricks_sp", "databricks_proxy", "both", "all"]:
        if self.ingress_credential_kind != "auto":
            return self.ingress_credential_kind
        return "databricks_proxy" if self.supervisor_mode == "databricks_app" else "hmac"

    @property
    def effective_ingress_key_store(self) -> Literal["file", "env", "secret_scope"]:
        if self.ingress_key_store != "auto":
            return self.ingress_key_store
        return "env" if self.supervisor_mode == "databricks_app" else "file"

    @property
    def scheduler_on(self) -> bool:
        """SCHEDULER_ENABLED if set, else on in laptop mode only (WP7)."""
        if self.scheduler_enabled is not None:
            return self.scheduler_enabled
        return self.supervisor_mode == "laptop"

    @property
    def inline_redaction_tool_set(self) -> frozenset[str]:
        return frozenset(t.strip() for t in self.inline_redaction_tools.split(",") if t.strip())

    @property
    def url_fetch_domains(self) -> tuple[str, ...]:
        """WP-D1: the URL_FETCH_ALLOWLIST as lower case domains (no wildcard, no empty item)."""
        return tuple(
            d
            for d in (x.strip().lower().lstrip("*.") for x in self.url_fetch_allowlist.split(","))
            if d
        )

    @property
    def mask_key(self) -> tuple[bytes, str]:
        """(HMAC key, key id) for pseudonyms. No MASK_HMAC_KEY -> the dev key, id ``dev``."""
        if self.mask_hmac_key is None or is_placeholder(self.mask_hmac_key.get_secret_value()):
            return DEV_MASK_HMAC_KEY, "dev"
        return self.mask_hmac_key.get_secret_value().encode("utf-8"), self.mask_key_id or "k1"

    @property
    def databricks_configured(self) -> bool:
        has_wh = not is_placeholder(self.databricks_warehouse_id) or not is_placeholder(
            self.databricks_warehouse_name
        )
        return (
            has_wh
            and not is_placeholder(self.databricks_catalog)
            and not is_placeholder(self.databricks_schema)
        )

    def describe_target(self) -> str:
        """Human-readable target for error messages. Never includes secrets."""
        if self.effective_sql_backend == "sqlite":
            return f"sqlite file {self.sqlite_path}"
        return (
            f"databricks host={self.databricks_host or '(from profile/env)'} "
            f"profile={self.databricks_config_profile or '-'} "
            f"warehouse={self.databricks_warehouse_id or self.databricks_warehouse_name} "
            f"schema={self.databricks_catalog}.{self.databricks_schema} transport=rest"
        )


def _check_identifier(name: str, value: str) -> None:
    import re

    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"{name} must be a plain identifier (letters, digits, _): {value!r}")


def load_settings(**overrides: object) -> Settings:
    """Load settings, enforcing the no-PAT rule first. Raises ConfigError."""
    check_no_databricks_token()
    overrides.setdefault("_env_file", str(env_file_path()))
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as exc:
        parts = []
        for err in exc.errors(include_input=False, include_url=False):
            loc = ".".join(str(x) for x in err["loc"]).upper() or "settings"
            parts.append(f"{loc}: {err['msg']}")
        raise ConfigError("invalid settings: " + "; ".join(parts)) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
