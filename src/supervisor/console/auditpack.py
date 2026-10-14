"""Audit pack: chain export + offline verify report + case files + judge eval report, zipped.

Written under ``CONSOLE_EXPORT_DIR`` (default ``<data_dir>/exports``) and served by the
console as a download (laptop and Databricks App both allow browser downloads). On the
App the directory is ephemeral (/tmp is wiped on restart): download the zip right away.

Order (so the pack proves itself):
1. evidence record ``audit_pack_requested`` (who, with which auth method);
2. case files (JSON + HTML) for the selected cases; each file hash goes on the chain;
3. a signed root commits every lane head;
4. ``export_chain`` of the whole chain, then ``verify_export`` (offline verifier);
5. eval report (if one exists), README, manifest with SHA-256 of every file; zip.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.core.canonical import format_ts
from supervisor.core.errors import SupervisorError
from supervisor.evidence.casefile.builder import write_case_file
from supervisor.evidence.export import export_chain
from supervisor.evidence.verify import verify_export

PACK_RE = re.compile(r"^audit-pack-\d{8}T\d{6}Z-[0-9a-f]{6}\.zip$")
EVAL_REPORT_CANDIDATES = ("eval_report.json",)


class AuditPackError(SupervisorError):
    """The audit pack cannot be built or served."""


@dataclass
class AuditPack:
    path: Path
    name: str
    verify_ok: bool
    verify_lines: list[str]
    case_count: int
    files: dict[str, str]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _eval_report(settings: Any) -> Path | None:
    for base in (Path(settings.data_dir), REPO_ROOT / "data" / "golden"):
        for name in EVAL_REPORT_CANDIDATES:
            p = base / name
            if p.is_file():
                return p
    return None


def verify_chain(ctx: Any, lane: str | None = None) -> dict[str, Any]:
    """Export (whole chain, or one lane + root) to a scratch dir and verify it offline."""
    settings = ctx.settings
    work = Path(settings.console_export_dir) / "verify" / uuid.uuid4().hex
    try:
        ctx.runtime.chain.commit_root(force=True)
        export_chain(ctx.tables, work, lanes=[lane] if lane else None)
        anchors = Path(settings.anchor_path) if settings.anchor_kind == "worm_dir" else None
        report = verify_export(
            work,
            partial=lane is not None,
            anchors_dir=anchors if anchors is not None and anchors.is_dir() else None,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    result = {
        "ok": report.failures == 0,
        "failures": report.failures,
        "lines": report.lines[-40:],
        "lane": lane or "all",
        "ts": ctx.clock.now(),
    }
    ctx.last_verify[lane or "all"] = result
    return result


def build_audit_pack(ctx: Any, actor: Any, *, case_ids: list[str] | None = None) -> AuditPack:
    settings = ctx.settings
    now = ctx.clock.now()
    name = f"audit-pack-{now:%Y%m%dT%H%M%S}Z-{uuid.uuid4().hex[:6]}"
    out_root = Path(settings.console_export_dir)
    work = out_root / name
    if work.exists():
        raise AuditPackError(f"export directory already exists: {work}")
    chain = ctx.runtime.chain
    cases = ctx.cases.list_cases() if case_ids is None else [ctx.cases.get(c) for c in case_ids]
    chain.record(
        "audit_pack_requested",
        f"audit_pack:{name}",
        {
            "pack": name,
            "requested_by": actor.user_id,
            "actor_kind": actor.kind,
            "auth_method": actor.auth_method,
            "case_count": len(cases),
            "ts": format_ts(now),
        },
    )
    try:
        cf_dir = work / "casefiles"
        for case in cases:
            cf = ctx.cases.case_file(case["case_id"], now=now)
            write_case_file(cf, cf_dir, "json", sink=chain)
            write_case_file(cf, cf_dir, "html", sink=chain)
        chain.commit_root(force=True)
        export_chain(ctx.tables, work / "chain", created_at=now)
        report = verify_export(work / "chain")
        (work / "verify_report.txt").write_text("\n".join(report.lines) + "\n", encoding="utf-8")
        evr = _eval_report(settings)
        if evr is not None:
            shutil.copyfile(evr, work / "eval_report.json")
        else:
            (work / "eval_report_NOT_RUN.txt").write_text(
                "No judge eval report found. Run: python -m supervisor.judge.eval\n",
                encoding="utf-8",
            )
        (work / "README.txt").write_text(
            "Supervisor audit pack\r\n"
            f"Created: {format_ts(now)} by {actor.user_id} ({actor.auth_method})\r\n"
            f"Cases: {len(cases)}\r\n"
            f"Offline verify: {'OK' if report.failures == 0 else 'FAIL'}\r\n"
            "Re-verify on any machine:\r\n"
            "  python -m supervisor.evidence.verify chain\r\n"
            "Case files: casefiles\\<case_id>.json and .html (masked; sign-off text verbatim)\r\n",
            encoding="utf-8",
        )
        files = {
            p.relative_to(work).as_posix(): _sha(p) for p in sorted(work.rglob("*")) if p.is_file()
        }
        (work / "manifest.json").write_text(
            json.dumps(
                {
                    "pack": name,
                    "created_at": format_ts(now),
                    "created_by": actor.user_id,
                    "auth_method": actor.auth_method,
                    "verify_ok": report.failures == 0,
                    "cases": [c["case_id"] for c in cases],
                    "files_sha256": files,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        zip_path = out_root / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(work.rglob("*")):
                if p.is_file():
                    zf.write(p, f"{name}/{p.relative_to(work).as_posix()}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    chain.record(
        "audit_pack_built",
        f"audit_pack:{name}",
        {
            "pack": name,
            "sha256": _sha(zip_path),
            "verify_ok": report.failures == 0,
            "requested_by": actor.user_id,
            "auth_method": actor.auth_method,
            "ts": format_ts(ctx.clock.now()),
        },
    )
    ctx.last_verify["all"] = {
        "ok": report.failures == 0,
        "failures": report.failures,
        "lines": report.lines[-40:],
        "lane": "all",
        "ts": now,
    }
    return AuditPack(zip_path, zip_path.name, report.failures == 0, report.lines, len(cases), files)


def pack_path(ctx: Any, name: str) -> Path:
    if not PACK_RE.match(name):
        raise AuditPackError("unknown audit pack name")
    path = Path(ctx.settings.console_export_dir) / name
    if not path.is_file():
        raise AuditPackError(f"audit pack {name} does not exist (the App wipes /tmp on restart)")
    return path


def list_packs(ctx: Any) -> list[dict[str, Any]]:
    root = Path(ctx.settings.console_export_dir)
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.glob("audit-pack-*.zip"), reverse=True):
        if PACK_RE.match(p.name):
            out.append({"name": p.name, "size": p.stat().st_size})
    return out[:20]
