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

    # --- WP37 --- detector framework and verdict contract v2 (ADR D23, docs/detectors.md).
    # Off: the gate answers and records exactly as in v0.3.0. On: detectors run after the
    # deterministic rules; the answer gains status, findings, not_executed, coverage,
    # transformed_payload, request_id and correlation_id; findings are stored (table finding).
    detectors_enabled: bool = False
    detectors_config: Path = Path("config/detectors.yaml")

    # --- WP39 --- activity and analytics parity (ADR D32, docs/console.md, docs/alerts.md).
    # Off: the Decisions drawer and list, the Traces pages and the Analytics tabs are as before.
    # On: verdict v2 drawer (Request, Response, Detections, Metadata), new filters, masked CSV
    # export, Gate tables and a Detectors tab in Analytics (read from decision_daily).
    console_decisions_v2: bool = False
    console_export_max_rows: int = Field(default=5000, ge=1, le=100_000)  # CSV rows, masked cols
    sched_decision_rollup_s: int = Field(default=3600, ge=60)  # decision_daily rollup job

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
        "policy_dir",
        "fact_query_map",
        "detectors_config",
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
        if self.databricks_catalog and not is_placeholder(self.databricks_catalog):
            _check_identifier("DATABRICKS_CATALOG", self.databricks_catalog)
        if self.databricks_schema and not is_placeholder(self.databricks_schema):
            _check_identifier("DATABRICKS_SCHEMA", self.databricks_schema)
        return self

    @property
    def serving_base_url(self) -> str:
        """OpenAI-compatible base URL of the workspace's model-serving endpoints."""
        return f"{self.databricks_host}/serving-endpoints"

    def is_workspace_serving_url(self, url: str) -> bool:
        """True only in databricks_app mode for ``<DATABRICKS_HOST>/serving-endpoints``.

        This is the implied ``LLM_ALLOW_REMOTE``: the workspace's own endpoint, reached
        with the App's own identity, is not AI egress."""
        if self.supervisor_mode != "databricks_app" or is_placeholder(self.databricks_host):
            return False
        return url.rstrip("/") == self.serving_base_url

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
