"""Support bundle (WP18, enterprise-readiness D-16): one folder + zip a bank can send.

Contents: settings.json (secrets redacted), preflight.txt (local checks; network checks only
with ``--network``), schema.json, chain.json (lane heads, no payloads), logs.txt (PII masked and
secret scrubbed), env.json (never the environment variables)
and manifest.json (sha256 of each file). A last pass removes every known secret value from all
text before it is written.
"""

from __future__ import annotations

import importlib.util
import json
import platform
import re
import sys
import zipfile
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import SecretStr

from supervisor import __version__
from supervisor.config import Settings, is_placeholder
from supervisor.core.errors import SupervisorError
from supervisor.core.schema import load_model
from supervisor.ops.backup import lane_heads, sha256_file, utc_stamp

REDACTED = "***redacted***"
SET = "***set***"
PII_FILES = {"logs.txt", "preflight.txt"}
SECRET_NAME = re.compile(r"key|secret|token|password|client_id", re.IGNORECASE)
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


class SupportBundleError(SupervisorError):
    """The bundle cannot be written."""


def _strip_query(value: str) -> str:
    if not _URL.match(value):
        return value
    p = urlsplit(value)
    netloc = p.netloc.rsplit("@", 1)[-1]  # drop user:password@
    return urlunsplit((p.scheme, netloc, p.path, "", ""))


def secret_values(settings: Settings) -> list[str]:
    """Every configured secret value (used to scrub free text). Never written anywhere."""
    out = []
    for name in type(settings).model_fields:
        v = getattr(settings, name, None)
        if isinstance(v, SecretStr):
            raw = v.get_secret_value()
        elif isinstance(v, str) and SECRET_NAME.search(name) and not is_placeholder(v):
            raw = v
        else:
            continue
        if len(raw) >= 4 and not is_placeholder(raw):
            out.append(raw)
    return sorted(set(out), key=len, reverse=True)


def redact_settings(settings: Settings) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in sorted(type(settings).model_fields):
        v = getattr(settings, name, None)
        if isinstance(v, SecretStr) or (SECRET_NAME.search(name) and isinstance(v, str | Path)):
            raw = v.get_secret_value() if isinstance(v, SecretStr) else v
            if raw in (None, ""):
                out[name] = None
            else:
                out[name] = str(raw) if is_placeholder(str(raw)) else SET
            continue
        if isinstance(v, Path):
            v = str(v)
        elif isinstance(v, str):
            v = _strip_query(v)
        elif not isinstance(v, bool | int | float | type(None) | list | dict):
            v = str(v)
        out[name] = v
    return out


def _sanitise(text: str, settings: Settings, secrets: list[str], *, pii: bool) -> str:
    """Remove known secret values; with ``pii`` also scrub secret-looking spans, mask PII."""
    from supervisor.adapters.factory import make_masker
    from supervisor.onboard.scrub import scrub_text
    from supervisor.preflight import scrub

    for secret in secrets:
        text = text.replace(secret, REDACTED)
    if pii:
        text = scrub(scrub_text(text).text)
        masker = make_masker(settings)
        if masker is not None:
            text = "\n".join(masker.mask(line) for line in text.split("\n"))
        text = _EMAIL.sub("<EMAIL:redacted>", text)
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


def read_log_tail(path: Path, max_lines: int, backups: int) -> list[str]:
    """Last ``max_lines`` lines of the log file, reaching into rotated files when needed."""
    files = [path] + [path.with_name(f"{path.name}.{i}") for i in range(1, backups + 1)]
    chunks: list[list[str]] = []
    need = max_lines
    for f in files:  # newest first
        if need <= 0 or not f.is_file():
            continue
        with f.open("r", encoding="utf-8", errors="replace") as fh:
            tail = list(deque((ln.rstrip("\r\n") for ln in fh), maxlen=need))
        chunks.append(tail)
        need -= len(tail)
    return [ln for chunk in reversed(chunks) for ln in chunk]


def preflight_text(settings: Settings, *, network: bool) -> str:
    from supervisor import preflight as pf

    if network:
        checks = pf.run_checks()
    else:
        checks = [pf._check_python(), pf._check_token(), pf._check_truststore()]
        checks.append(
            pf.Check(
                "OK",
                "config",
                f"mode={settings.supervisor_mode} sql_backend={settings.effective_sql_backend}",
            )
        )
        checks.append(pf._check_paths(settings))
        signer = pf._check_signer_durable(settings)
        if signer is not None:
            checks.append(signer)
        checks.extend(pf._check_extras())
        checks.append(
            pf.Check("SKIP", "network checks", "not run (default)", "re-run with --network")
        )
    lines = [pf.format_check(c) for c in checks]
    failed = sum(1 for c in checks if c.status == "FAIL")
    lines.append(pf.ascii_line(f"preflight: {len(checks)} checks, {failed} failed"))
    return "\n".join(lines) + "\n"


def env_info(settings: Settings) -> dict[str, Any]:
    from supervisor.preflight import EXTRAS

    extras = {}
    for extra, modules in EXTRAS.items():
        extras[extra] = all(importlib.util.find_spec(m.split(".")[0]) is not None for m in modules)
    return {
        "app_version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "mode": settings.supervisor_mode,
        "backend": settings.effective_sql_backend,
        "optional_extras_importable": extras,
    }


def schema_and_chain(settings: Settings, *, network: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    model = load_model()
    schema: dict[str, Any] = {
        "model_version": model.version,
        "model_hash": model.source_hash,
        "tables": len(model.tables),
        "store": "not checked",
        "schema_version_rows": [],
    }
    chain: dict[str, Any] = {"store": "not checked", "lanes": []}
    sqlite = settings.effective_sql_backend == "sqlite"
    if sqlite and (settings.sqlite_path is None or not Path(settings.sqlite_path).is_file()):
        schema["store"] = chain["store"] = (
            f"not reachable: no SQLite file at {settings.sqlite_path}"
        )
        return schema, chain
    if not sqlite and not network:
        schema["store"] = chain["store"] = "skipped: Databricks store (use --network)"
        return schema, chain
    from supervisor.adapters.factory import build_adapters

    try:
        a = build_adapters(settings)
    except Exception as exc:  # noqa: BLE001 - report and move on
        schema["store"] = chain["store"] = f"not reachable: {type(exc).__name__}"
        return schema, chain
    try:
        rows = a.state.query("schema_version")
        schema["schema_version_rows"] = [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
            for r in rows
        ]
        schema["store"] = "ok"
        chain["lanes"] = lane_heads(a)
        chain["store"] = "ok"
    except Exception as exc:  # noqa: BLE001
        schema["store"] = chain["store"] = f"not readable: {type(exc).__name__}"
    finally:
        a.close()
    return schema, chain


def build_support_bundle(
    settings: Settings,
    out: Path,
    *,
    log_lines: int = 500,
    force: bool = False,
    network: bool = False,
) -> tuple[Path, dict[str, str]]:
    """Write the bundle folder and zip. Returns (zip path, {file: sha256})."""
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()) and not force:
        raise SupportBundleError(f"output directory is not empty: {out} (use --force)")
    out.mkdir(parents=True, exist_ok=True)
    secrets = secret_values(settings)
    texts: dict[str, str] = {}
    texts["settings.json"] = json.dumps(redact_settings(settings), indent=2, sort_keys=True)
    texts["preflight.txt"] = preflight_text(settings, network=network)
    schema, chain = schema_and_chain(settings, network=network)
    texts["schema.json"] = json.dumps(schema, indent=2, sort_keys=True)
    texts["chain.json"] = json.dumps(chain, indent=2, sort_keys=True)
    if settings.log_file is None:
        texts["logs.txt"] = "LOG_FILE not set\n"
    else:
        lines = read_log_tail(Path(settings.log_file), log_lines, settings.log_file_backups)
        texts["logs.txt"] = (
            "\n".join(lines) + "\n" if lines else "LOG_FILE is set but empty or missing\n"
        )
    texts["env.json"] = json.dumps(env_info(settings), indent=2, sort_keys=True)
    for name, text in texts.items():
        (out / name).write_text(
            _sanitise(text, settings, secrets, pii=name in PII_FILES),
            encoding="utf-8",
            newline="\n",
        )
    hashes = {name: sha256_file(out / name) for name in sorted(texts)}
    manifest = {
        "created_at": utc_stamp(),
        "app_version": __version__,
        "files": {n: {"sha256": h, "size": (out / n).stat().st_size} for n, h in hashes.items()},
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    zpath = out / f"support-bundle-{utc_stamp()}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in [*sorted(texts), "manifest.json"]:
            zf.write(out / name, name)
    return zpath, hashes
