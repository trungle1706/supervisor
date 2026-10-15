"""Integration tab (WP15): read-only view of integration advice reports.

A report is a sub-folder of ``settings.integration_reports_dir`` (default
``<data_dir>/integration``) that holds ``integration_report.json`` and, next to it, the
patch files named in the report (``patches/NN-slug.patch``). The console never writes
here, never applies a patch and serves a patch only as ``text/plain``.

Names are plain names (no separator, no dot-dot); the resolved path must stay inside the
reports folder. A malformed report file gives a visible message, not an error.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from supervisor.core.errors import SupervisorError

NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}$")
PATCH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}\.patch$")
REPORT_FILE = "integration_report.json"
MAX_REPORT_BYTES = 2_000_000
MAX_PATCH_BYTES = 200_000


class IntegrationInputError(SupervisorError):
    """The Integration request cannot be answered (HTTP 400)."""


def reports_root(settings: Any) -> Path:
    base = getattr(settings, "integration_reports_dir", None)
    return Path(base) if base else Path(settings.data_dir) / "integration"


def _folder(settings: Any, name: str) -> Path:
    if not NAME_RE.match(name or "") or ".." in name:
        raise IntegrationInputError("unknown integration report")
    root = reports_root(settings).resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_dir():
        raise IntegrationInputError(f"integration report {name!r} does not exist")
    return path


def _read(path: Path) -> tuple[dict[str, Any] | None, str]:
    """(data, error). ``error`` is empty when the file is a JSON object."""
    try:
        if path.stat().st_size > MAX_REPORT_BYTES:
            return None, "report file is too large"
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"report file cannot be read: {type(exc).__name__}"
    if not isinstance(data, dict):
        return None, "report file is not a JSON object"
    from pydantic import ValidationError

    from supervisor.advisory.integration.models import IntegrationReport

    try:
        IntegrationReport.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ()))
        return None, f"report does not match the integration report schema ({where})"
    return data, ""


def _g(d: Any, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
    return default if d is None else d


def list_reports(settings: Any) -> list[dict[str, Any]]:
    root = reports_root(settings)
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for sub in sorted(root.iterdir()):
        if not NAME_RE.match(sub.name) or not (sub / REPORT_FILE).is_file():
            continue
        data, err = _read(sub / REPORT_FILE)
        patches = _g(data, "patches", default=[])
        rows.append(
            {
                "name": sub.name,
                "error": err,
                "agent_id": _g(data, "agent_id", default="-"),
                "framework": _g(data, "framework", default="-"),
                "total": _g(data, "readiness", "total"),
                "patches": len(patches) if isinstance(patches, list) else 0,
            }
        )
    return rows


def load_report(settings: Any, name: str) -> dict[str, Any]:
    """The page data for one report; ``error`` is set when the file is unreadable."""
    folder = _folder(settings, name)
    file = folder / REPORT_FILE
    if not file.is_file():
        raise IntegrationInputError(f"{name} has no {REPORT_FILE}")
    data, err = _read(file)
    out: dict[str, Any] = {"name": name, "error": err, "r": data or {}, "patch_items": []}
    if data is None:
        return out
    items = []
    refs = data.get("patches")
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, dict):
            continue
        fname = Path(str(ref.get("file", ""))).name
        text, missing = "", True
        if PATCH_RE.match(fname):
            try:
                path = patch_path(settings, name, fname)
                text = path.read_text(encoding="utf-8")[:MAX_PATCH_BYTES]
                missing = False
            except (OSError, UnicodeDecodeError, IntegrationInputError):
                pass
        items.append({"ref": ref, "file": fname, "text": text, "missing": missing})
    out["patch_items"] = items
    return out


def patch_path(settings: Any, name: str, file: str) -> Path:
    if not PATCH_RE.match(file or "") or ".." in file:
        raise IntegrationInputError("unknown integration patch")
    folder = _folder(settings, name)
    for cand in (folder / "patches" / file, folder / file):
        real = cand.resolve()
        if real.parent in (folder, folder / "patches") and real.is_file():
            if real.stat().st_size > MAX_PATCH_BYTES * 5:
                raise IntegrationInputError("patch file is too large")
            return real
    raise IntegrationInputError(f"{name}/{file} does not exist")
