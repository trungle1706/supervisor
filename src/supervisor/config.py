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
"""

from __future__ import annotations

import ipaddress
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
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
    databricks_warehouse_id: str | None = None
    databricks_warehouse_name: str | None = None
    databricks_catalog: str | None = None
    databricks_schema: str | None = None
    databricks_sql_transport: Literal["rest"] = "rest"
    databricks_retry_timeout_s: int = Field(default=90, ge=60, le=120)
    databricks_statement_deadline_s: int = Field(default=120, ge=10, le=600)

    # LLM (OpenAI-compatible). Empty base URL = mock judges only.
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_allow_remote: bool = False
    llm_model: str = "qwen3:4b"
    llm_api_key: SecretStr | None = None
    llm_timeout_s: int = Field(default=600, ge=1)
    llm_max_tokens: int = Field(default=8192, ge=16)  # WP2: cap against repetition loops
    llm_mock: bool = False  # WP2: LLM_MOCK=1 forces MockChat even when LLM_BASE_URL is set
    llm_endpoint: str | None = None  # Databricks serving endpoint name (App binding)

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

    # Evidence chain (WP6). Root entries commit all lane heads and are signed.
    evidence_root_every_n: int = Field(default=100, ge=1)  # entries between signed roots
    evidence_root_every_s: int = Field(default=900, ge=1)  # seconds between signed roots
    evidence_retention_days: int = Field(default=1825, ge=1)  # Delta log/file retention
    evidence_writer_id: str | None = None  # default: <hostname>:<pid>
    signer_kind: Literal["ed25519_file", "env"] = "ed25519_file"
    signer_key_path: Path | None = None  # default: <data_dir>/keys/evidence_ed25519.pem
    signer_env_var: str = Field(default="SUPERVISOR_SIGNING_KEY", pattern=r"^[A-Z][A-Z0-9_]*$")
    signer_key_managed: bool = False  # True only when the bank manages the key (label)
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
    recorder_spool_dir: Path | None = None  # default: <data_dir>/spool

    @field_validator(
        "data_dir",
        "sqlite_path",
        "signer_key_path",
        "casefile_dir",
        "casefile_pdf_font",
        "recorder_spool_dir",
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

    @model_validator(mode="after")
    def _rules(self) -> Settings:
        if self.sqlite_path is None:
            self.sqlite_path = self.data_dir / "supervisor.db"
        if self.signer_key_path is None:
            self.signer_key_path = self.data_dir / "keys" / "evidence_ed25519.pem"
        if self.casefile_dir is None:
            self.casefile_dir = self.data_dir / "casefiles"
        if self.recorder_spool_dir is None:
            self.recorder_spool_dir = self.data_dir / "spool"
        if self.anchor_kind == "worm_dir":
            if self.anchor_path is None:
                self.anchor_path = str(self.data_dir / "anchors")
            else:
                p = Path(self.anchor_path).expanduser()
                self.anchor_path = os.path.abspath(p if p.is_absolute() else REPO_ROOT / p)
        if (
            self.llm_base_url
            and not self.llm_allow_remote
            and not is_loopback_url(self.llm_base_url)
        ):
            raise ValueError(
                "LLM_BASE_URL must be a loopback address (127.0.0.1 / localhost / ::1) "
                "unless LLM_ALLOW_REMOTE=1 (zero AI egress house rule)"
            )
        for name in ("judge_t1_base_url", "judge_t2_base_url", "judge_challenger_base_url"):
            url = getattr(self, name)
            if url and not self.llm_allow_remote and not is_loopback_url(url):
                raise ValueError(
                    f"{name.upper()} must be a loopback address unless LLM_ALLOW_REMOTE=1"
                )
        if self.databricks_catalog and not is_placeholder(self.databricks_catalog):
            _check_identifier("DATABRICKS_CATALOG", self.databricks_catalog)
        if self.databricks_schema and not is_placeholder(self.databricks_schema):
            _check_identifier("DATABRICKS_SCHEMA", self.databricks_schema)
        return self

    @property
    def effective_sql_backend(self) -> Literal["sqlite", "databricks_rest"]:
        if self.sql_backend != "auto":
            return self.sql_backend
        return "databricks_rest" if self.supervisor_mode == "databricks_app" else "sqlite"

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
