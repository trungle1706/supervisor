"""Preflight checks. Output is ASCII only: [OK] / [FAIL] / [SKIP] plus a fix.

Never prints secret values. Exit code 1 when any check FAILs.

Always: Python version, no ``DATABRICKS_TOKEN``, trust store, config load, absolute
paths, optional extras, local LLM endpoint.

When Databricks is in use (SQL backend ``databricks_rest``, a CLI profile, a ``uc_volume``
anchor, a Volume path or the bound serving endpoint), also (bank guide section 6):

* the ``databricks`` extra is installed;
* the CLI profile exists and its OAuth token is valid (``databricks auth token``, run
  through ``sandbox.py``; the token itself is never printed), or the App service
  principal is configured;
* the SDK signs in (``current_user.me()``) with the retry cap in effect;
* the SQL warehouse resolves by name to an id and answers ``SELECT 1`` within the deadline;
* the schema is writable (create and drop a probe table with the table prefix);
* the serving endpoint exists and is READY;
* a configured Volume is writable (write and delete a probe file).
"""

from __future__ import annotations

import configparser
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from supervisor import bootstrap, sandbox
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


_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_PAT = re.compile(r"\bdapi[0-9a-f]{32}\b")
_KV = re.compile(
    r"(?i)\b(access_token|refresh_token|client_secret|token)([\"']?\s*[:=]\s*[\"']?)"
    r"[^\s\"',}]+"
)


def scrub(text: str) -> str:
    """Remove anything that looks like a token from text shown to the user."""
    text = _PAT.sub("***", _JWT.sub("***", text))
    return _KV.sub(lambda m: m.group(1) + m.group(2) + "***", text)


def ascii_line(text: str) -> str:
    return scrub(text).encode("ascii", "backslashreplace").decode("ascii")


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
    if bootstrap.truststore_requested():
        return Check(
            "FAIL",
            "truststore",
            "SSL_OS_TRUSTSTORE=1 but the OS trust store is not injected in this process",
            "start commands as uv run python -m supervisor.cli ... (the entry point injects it)",
        )
    return Check(
        "SKIP",
        "truststore",
        "SSL_OS_TRUSTSTORE is not 1",
        "on the bank laptop: set SSL_OS_TRUSTSTORE=1",
    )


def _is_volume(p: object) -> bool:
    return str(p).replace("\\", "/").startswith("/Volumes/")


def _check_paths(s: Settings) -> Check:
    paths: dict[str, object] = {
        "DATA_DIR": s.data_dir,
        "SQLITE_PATH": s.sqlite_path,
        "RECORDER_SPOOL_DIR": s.recorder_spool_dir,
        "SIGNER_KEY_PATH": s.signer_key_path,
        "CASEFILE_DIR": s.casefile_dir,
    }
    if s.anchor_kind == "worm_dir":
        paths["ANCHOR_PATH"] = s.anchor_path
    bad = [
        k
        for k, p in paths.items()
        if p is None or not (Path(str(p)).is_absolute() or _is_volume(p))
    ]
    if bad:
        return Check("FAIL", "paths absolute", ", ".join(bad), "report this as a bug")
    if s.data_dir_requested:
        return Check(
            "SKIP",
            "paths absolute",
            f"DATA_DIR {s.data_dir_requested} is not mounted here; using {s.data_dir} "
            "(wiped on restart)",
            "grant READ VOLUME, WRITE VOLUME to this identity, or accept the ephemeral data dir",
        )
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
    if s.llm_uses_workspace_auth:
        return Check("SKIP", "llm endpoint", "workspace serving endpoint: see serving endpoint")
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


# ----------------------------------------------------------------------------- Databricks

ClientFactory = Callable[[Settings], Any]
CliRunner = Callable[[list[str]], "sandbox.RunResult"]


def databricks_wanted(s: Settings) -> bool:
    """True when this configuration talks to a Databricks workspace."""
    volume = any(
        _is_volume(p) for p in (s.recorder_spool_dir, s.data_dir, s.anchor_path) if p is not None
    )
    return (
        s.effective_sql_backend == "databricks_rest"
        or not is_placeholder(s.databricks_config_profile)
        or s.anchor_kind == "uc_volume"
        or volume
        or s.llm_uses_workspace_auth
        or s.supervisor_mode == "databricks_app"
    )


def _login(s: Settings) -> str:
    return (
        f"databricks auth login --host {s.databricks_host or 'https://<workspace host>'} "
        f"--profile {s.databricks_config_profile or '<profile>'}"
    )


def _err(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0][:300] if text else ''}"


def _default_client(s: Settings) -> Any:
    from supervisor.adapters.sql.databricks_rest import make_workspace_client

    return make_workspace_client(s)


def _default_cli(argv: list[str]) -> sandbox.RunResult:
    return sandbox.run(argv, cwd=Path.home(), timeout_s=60)


def _check_oauth_cli(s: Settings, cli: CliRunner | None) -> Check:
    """``databricks auth token --profile <p>``: proves the OAuth refresh token works."""
    name = "oauth token (CLI)"
    exe = sandbox.which("databricks")
    if cli is None and exe is None:
        return Check(
            "SKIP",
            name,
            "databricks CLI not on PATH; the SDK sign-in check below still runs",
            "install the Databricks CLI, then: " + _login(s),
        )
    argv = [exe or "databricks", "auth", "token", "--profile", str(s.databricks_config_profile)]
    if not is_placeholder(s.databricks_host):
        argv += ["--host", str(s.databricks_host)]
    try:
        res = (cli or _default_cli)(argv)
    except Exception as exc:  # noqa: BLE001 - SandboxError, timeouts
        return Check("FAIL", name, _err(exc), _login(s))
    if not res.ok:
        first = (res.stderr or res.stdout or "").strip().splitlines()
        reason = first[0][:300] if first else f"exit code {res.returncode}"
        return Check("FAIL", name, f"profile {s.databricks_config_profile}: {reason}", _login(s))
    try:  # stdout holds the token: parse it, never print it
        data = json.loads(res.stdout)
        ok = bool(data.get("access_token"))
        expiry = str(data.get("expiry") or "?")
    except (ValueError, AttributeError):
        ok, expiry = False, "?"
    if not ok:
        return Check("FAIL", name, "CLI gave no access token", _login(s))
    return Check("OK", name, f"profile {s.databricks_config_profile} valid (expiry {expiry})")


def _check_auth_mode(s: Settings) -> Check:
    kind = s.databricks_auth_kind
    if kind == "service_principal":
        return Check(
            "OK",
            "databricks auth",
            "App service principal (DATABRICKS_CLIENT_ID set; secret not shown)",
        )
    if kind == "cli_profile":
        return Check("OK", "databricks auth", f"CLI OAuth profile {s.databricks_config_profile}")
    if s.supervisor_mode == "databricks_app":
        return Check(
            "FAIL",
            "databricks auth",
            "databricks_app mode but DATABRICKS_CLIENT_ID/SECRET are not injected",
            "run inside the Databricks App, or use SUPERVISOR_MODE=laptop with a CLI profile",
        )
    return Check(
        "FAIL",
        "databricks auth",
        "no DATABRICKS_CONFIG_PROFILE (OAuth CLI profile) configured",
        "set DATABRICKS_CONFIG_PROFILE=<name> and DATABRICKS_AUTH_TYPE=databricks-cli in .env, "
        "then " + _login(s),
    )


def _check_retry_caps(s: Settings, client: Any) -> Check:
    cfg = getattr(client, "config", None)
    retry = getattr(cfg, "retry_timeout_seconds", None)
    ok = isinstance(retry, int) and 60 <= retry <= 120
    detail = (
        f"SDK retry_timeout={retry}s (in Config), statement deadline="
        f"{s.databricks_statement_deadline_s}s"
    )
    if ok:
        return Check("OK", "retry caps", detail)
    return Check("FAIL", "retry caps", detail, "set DATABRICKS_RETRY_TIMEOUT_S=90 in .env")


def _check_serving(s: Settings, client: Any) -> Check:
    name = s.llm_endpoint
    if is_placeholder(name):
        return Check(
            "SKIP",
            "serving endpoint",
            "LLM_ENDPOINT not set",
            "set LLM_ENDPOINT=<existing endpoint name> to check it (the App binds it)",
        )
    from supervisor.adapters.sql.databricks_rest import _state_name

    try:
        ep = client.serving_endpoints.get(str(name))
    except Exception as exc:  # noqa: BLE001
        return Check(
            "FAIL",
            "serving endpoint",
            f"{name} on {s.databricks_host}: {_err(exc)}",
            "check the endpoint name in the Serving UI and that you have CAN_QUERY on it",
        )
    state = getattr(ep, "state", None)
    ready = _state_name(getattr(state, "ready", None)) if state is not None else "UNKNOWN"
    if ready == "READY":
        return Check("OK", "serving endpoint", f"{name} is READY")
    upd = _state_name(getattr(state, "config_update", None)) if state is not None else "-"
    return Check(
        "FAIL",
        "serving endpoint",
        f"{name} is {ready} (config_update={upd})",
        "wait until it is READY in the Serving UI, or ask the endpoint owner",
    )


def _probe_executor(s: Settings, client: Any, warehouse_id: str) -> Any:
    from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor

    return DatabricksRestExecutor(
        client.statement_execution,
        warehouse_id=warehouse_id,
        catalog=str(s.databricks_catalog),
        schema=str(s.databricks_schema),
        table_prefix=s.table_prefix,
        deadline_s=float(s.databricks_statement_deadline_s),
        host=s.databricks_host,
        identity=s.databricks_auth_kind,
    )


def _check_warehouse_and_schema(s: Settings, client: Any, where: str) -> list[Check]:
    if is_placeholder(s.databricks_warehouse_id) and is_placeholder(s.databricks_warehouse_name):
        return [
            Check(
                "SKIP",
                "sql warehouse",
                "DATABRICKS_WAREHOUSE_NAME / _ID not set",
                "set DATABRICKS_WAREHOUSE_NAME=<warehouse name> in .env",
            )
        ]
    from supervisor.adapters.sql.databricks_rest import resolve_warehouse_id

    try:
        warehouse_id = resolve_warehouse_id(client, s)
    except Exception as exc:  # noqa: BLE001
        return [
            Check(
                "FAIL",
                "sql warehouse",
                f"{where}: {_err(exc)}",
                "check DATABRICKS_WAREHOUSE_NAME (exact name) and your CAN_USE permission",
            )
        ]
    label = s.databricks_warehouse_name or "(id given)"
    out = [Check("OK", "sql warehouse", f"{label} -> id {warehouse_id}")]
    if is_placeholder(s.databricks_catalog) or is_placeholder(s.databricks_schema):
        out.append(
            Check(
                "SKIP",
                "warehouse reachable",
                "DATABRICKS_CATALOG / _SCHEMA not set",
                "set DATABRICKS_CATALOG and DATABRICKS_SCHEMA in .env",
            )
        )
        return out
    x = _probe_executor(s, client, warehouse_id)
    t0 = time.monotonic()
    try:
        rows = x.query("SELECT 1 AS ok", column_types={"ok": "int"})
    except Exception as exc:  # noqa: BLE001
        out.append(
            Check(
                "FAIL",
                "warehouse reachable",
                _err(exc),
                "start the warehouse in the SQL Warehouses UI (a cold start takes about 30 s) "
                "and re-run; on the laptop check SSL_OS_TRUSTSTORE=1",
            )
        )
        return out
    ms = int((time.monotonic() - t0) * 1000)
    status = "OK" if rows == [{"ok": 1}] else "FAIL"
    out.append(
        Check(status, "warehouse reachable", f"SELECT 1 in {ms} ms via REST ({x.describe()})")
    )
    target = x.qualify(f"preflight_probe_{uuid.uuid4().hex[:8]}")
    try:
        x.execute(f"CREATE TABLE IF NOT EXISTS {target} (id BIGINT) USING DELTA")
        x.execute(f"DROP TABLE IF EXISTS {target}")
    except Exception as exc:  # noqa: BLE001
        out.append(
            Check(
                "FAIL",
                "schema writable",
                f"{target}: {_err(exc)}",
                f"ask the owner of {s.databricks_catalog}.{s.databricks_schema} for USE CATALOG, "
                "USE SCHEMA and CREATE TABLE",
            )
        )
        return out
    out.append(Check("OK", "schema writable", f"created and dropped {target}"))
    return out


def _check_volume(s: Settings, client: Any) -> Check | None:
    candidates = [s.recorder_spool_dir, s.anchor_path if s.anchor_kind == "uc_volume" else None]
    paths = [str(p).replace("\\", "/") for p in candidates if p is not None and _is_volume(p)]
    if not paths:
        return None
    from supervisor.databricks.files import VolumeFiles

    vf = VolumeFiles(client.files)
    probe = f"{paths[0].rstrip('/')}/.preflight-{uuid.uuid4().hex[:8]}"
    try:
        vf.put_new(probe, b"preflight")
        vf.delete(probe)
    except Exception as exc:  # noqa: BLE001
        return Check(
            "FAIL",
            "volume writable",
            f"{probe}: {_err(exc)}",
            "create the volume and grant READ VOLUME, WRITE VOLUME to this identity",
        )
    return Check("OK", "volume writable", f"wrote and deleted a probe file in {paths[0]}")


def databricks_checks(
    s: Settings,
    *,
    client_factory: ClientFactory | None = None,
    cli: CliRunner | None = None,
    find_spec: Callable[[str], Any] = importlib.util.find_spec,
) -> list[Check]:
    """Workspace checks (bank guide section 6). One SKIP line when Databricks is not in use."""
    if not databricks_wanted(s):
        return [
            Check(
                "SKIP",
                "databricks",
                "not in use (SQLite backend, no profile, no Volume, no serving endpoint)",
            )
        ]
    out: list[Check] = []
    where = f"host={s.databricks_host or '(from profile)'}"
    try:
        has_sdk = find_spec("databricks") is not None and find_spec("databricks.sdk") is not None
    except (ImportError, ValueError):
        has_sdk = False
    if not has_sdk:
        out.append(
            Check(
                "FAIL",
                "databricks extra",
                "databricks-sdk is not installed",
                "uv sync --python 3.11 --extra databricks",
            )
        )
        return out
    out.append(Check("OK", "databricks extra", "databricks-sdk installed"))
    auth = _check_auth_mode(s)
    out.append(auth)
    if auth.status == "FAIL":
        return out
    if s.databricks_auth_kind == "cli_profile":
        prof = _check_profile(s)
        out.append(prof)
        if prof.status == "FAIL":
            return out
        out.append(_check_oauth_cli(s, cli))
    try:
        client = (client_factory or _default_client)(s)
        me = client.current_user.me()
        who = getattr(me, "user_name", None) or getattr(me, "display_name", None) or "?"
    except Exception as exc:  # noqa: BLE001 - ConfigError, SDK auth errors
        out.append(Check("FAIL", "databricks sign-in", f"{where}: {_err(exc)}", _login(s)))
        return out
    out.append(Check("OK", "databricks sign-in", f"{where} as {who}"))
    out.append(_check_retry_caps(s, client))
    out.extend(_check_warehouse_and_schema(s, client, where))
    out.append(_check_serving(s, client))
    vol = _check_volume(s, client)
    if vol is not None:
        out.append(vol)
    return out


def run_checks(
    load: Callable[[], Settings] = load_settings,
    *,
    client_factory: ClientFactory | None = None,
    cli: CliRunner | None = None,
) -> list[Check]:
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
    checks.append(_check_llm(settings))
    checks.extend(databricks_checks(settings, client_factory=client_factory, cli=cli))
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
