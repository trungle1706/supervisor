"""Preflight checks. Output is ASCII only: [OK] / [FAIL] / [SKIP] plus a fix.

Never prints secret values.
"""

from __future__ import annotations

import configparser
import importlib.util
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from supervisor import bootstrap
from supervisor.config import (
    FORBIDDEN_ENV,
    Settings,
    is_loopback_url,
    is_placeholder,
    load_settings,
)
from supervisor.core.errors import ConfigError

EXTRAS: dict[str, list[str]] = {
    "databricks": ["databricks.sdk"],
    "monitors": ["fairlearn", "sklearn", "pandas"],
    "presidio": ["presidio_analyzer", "presidio_anonymizer"],
    "mlflow": ["mlflow"],
    "llm": ["openai"],
}


@dataclass
class Check:
    status: str  # OK | FAIL | SKIP
    name: str
    detail: str = ""
    fix: str = ""


def ascii_line(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _check_python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return Check(
        "OK" if ok else "FAIL",
        "python",
        f"{v.major}.{v.minor}.{v.micro} at {os.path.abspath(sys.executable)}",
        "" if ok else "install Python 3.11 and run: uv sync --python 3.11",
    )


def _check_token() -> Check:
    if FORBIDDEN_ENV in os.environ:
        return Check(
            "FAIL",
            "no DATABRICKS_TOKEN",
            "DATABRICKS_TOKEN is set (value not shown); PATs are not allowed",
            "set DATABRICKS_TOKEN=   (then use: databricks auth login --profile <name>)",
        )
    return Check("OK", "no DATABRICKS_TOKEN", "not set")


def _check_truststore() -> Check:
    if bootstrap.truststore_active():
        return Check("OK", "truststore", "OS trust store injected (SSL_OS_TRUSTSTORE=1)")
    return Check(
        "SKIP",
        "truststore",
        "SSL_OS_TRUSTSTORE is not 1",
        "on the bank laptop: set SSL_OS_TRUSTSTORE=1",
    )


def _check_paths(s: Settings) -> Check:
    paths = {"DATA_DIR": s.data_dir, "SQLITE_PATH": s.sqlite_path}
    bad = [k for k, p in paths.items() if p is None or not Path(p).is_absolute()]
    if bad:
        return Check("FAIL", "paths absolute", ", ".join(bad), "report this as a bug")
    return Check("OK", "paths absolute", f"data_dir={s.data_dir}")


def _check_extras() -> list[Check]:
    out = []
    for extra, modules in EXTRAS.items():
        missing = [m for m in modules if importlib.util.find_spec(m.split(".")[0]) is None]
        if not missing and "." in modules[0]:
            missing = [m for m in modules if importlib.util.find_spec(m) is None]
        if missing:
            out.append(Check("SKIP", f"extra {extra}", "not installed", f"uv sync --extra {extra}"))
        else:
            out.append(Check("OK", f"extra {extra}", "installed"))
    return out


def _databricks_cfg_path() -> Path:
    custom = os.environ.get("DATABRICKS_CONFIG_FILE")
    return Path(custom) if custom else Path.home() / ".databrickscfg"


def _check_profile(s: Settings) -> Check:
    profile = s.databricks_config_profile
    if is_placeholder(profile):
        return Check(
            "SKIP",
            "databricks profile",
            "DATABRICKS_CONFIG_PROFILE not configured",
            "set DATABRICKS_CONFIG_PROFILE=<name> in .env after databricks auth login",
        )
    cfg_path = _databricks_cfg_path()
    parser = configparser.ConfigParser()
    try:
        parser.read(cfg_path, encoding="utf-8")
    except configparser.Error as exc:
        return Check("FAIL", "databricks profile", f"cannot parse {cfg_path}: {type(exc).__name__}")
    host = s.databricks_host or "<host>"
    login = f"databricks auth login --host {host} --profile {profile}"
    if not parser.has_section(profile or ""):
        return Check("FAIL", "databricks profile", f"profile {profile} not in {cfg_path}", login)
    return Check("OK", "databricks profile", f"profile {profile} found in {cfg_path}")


def _check_llm(s: Settings) -> Check:
    url = s.llm_base_url
    if not url:
        return Check("SKIP", "llm endpoint", "LLM_BASE_URL empty: mock judges only")
    where = "loopback" if is_loopback_url(url) else "remote (LLM_ALLOW_REMOTE=1)"
    probe = url.rstrip("/") + "/models"
    try:
        req = urllib.request.Request(probe, method="GET")  # noqa: S310 - URL from settings
        with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return Check(
            "SKIP",
            "llm endpoint",
            f"{url} ({where}) not reachable: {type(reason).__name__}",
            "start Ollama (set OLLAMA_KEEP_ALIVE=-1) or leave it off to use mock judges",
        )
    return Check("OK", "llm endpoint", f"{url} ({where}) answered HTTP {code}")


def run_checks(load: Callable[[], Settings] = load_settings) -> list[Check]:
    checks = [_check_python(), _check_token(), _check_truststore()]
    try:
        settings = load()
    except ConfigError as exc:
        checks.append(Check("FAIL", "config", str(exc).splitlines()[0], "fix .env and re-run"))
        return checks
    checks.append(
        Check(
            "OK",
            "config",
            f"mode={settings.supervisor_mode} sql_backend={settings.effective_sql_backend}",
        )
    )
    checks.append(_check_paths(settings))
    checks.extend(_check_extras())
    checks.append(_check_profile(settings))
    checks.append(_check_llm(settings))
    return checks


def format_check(c: Check) -> str:
    line = f"[{c.status}] {c.name}"
    if c.detail:
        line += f": {c.detail}"
    if c.fix and c.status != "OK":
        line += f" -- fix: {c.fix}"
    return ascii_line(line)


def main() -> int:
    checks = run_checks()
    for c in checks:
        print(format_check(c))
    failed = sum(1 for c in checks if c.status == "FAIL")
    print(ascii_line(f"preflight: {len(checks)} checks, {failed} failed"))
    return 1 if failed else 0
