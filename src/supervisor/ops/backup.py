"""Backup, restore and Delta export (WP18, enterprise-readiness D-9, D-10).

SQLite mode: ``backup`` copies the store with the SQLite online backup API (the app may run),
``restore`` puts a backup back and re-verifies the evidence chain. App mode (Databricks):
``export_delta`` reads every model table with one SELECT each through the Statement
Execution API adapter and writes JSONL files. Restoring Delta is a DBA task (time travel,
DEEP CLONE). No database library is imported here: the SQLite specifics live in the adapter.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from supervisor import __version__
from supervisor.config import Settings, is_placeholder
from supervisor.core.canonical import format_ts
from supervisor.core.errors import SupervisorError
from supervisor.core.schema import load_model

MANIFEST = "manifest.json"
DB_NAME = "supervisor.db"
KEY_NAME = "evidence_ed25519.pem"
ANCHOR_DIR = "anchors"
BACKUP_FORMAT = 1


class BackupError(SupervisorError):
    """Backup, restore or export cannot continue."""


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return format_ts(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"cannot serialise {type(value).__name__}")


def table_counts(adapters: Any, tables: list[str] | None = None) -> dict[str, int]:
    ex = adapters.executor
    out: dict[str, int] = {}
    for name in tables or list(adapters.model.tables):
        sql = f"SELECT COUNT(*) AS n FROM {ex.qualify(name)}"  # noqa: S608 - model identifier
        rows = ex.query(sql, column_types={"n": "int"})
        out[name] = int(rows[0]["n"])
    return out


def lane_heads(adapters: Any) -> list[dict[str, Any]]:
    """Latest chain entry per lane: lane, seq, entry_hash, ts. No payloads."""
    ex = adapters.executor
    q = ex.qualify("chain_entry")
    sub = f"(SELECT lane AS l, MAX(seq) AS m FROM {q} GROUP BY lane) h"  # noqa: S608
    cols = "e.lane AS lane, e.seq AS seq, e.entry_hash AS entry_hash, e.ts AS ts"
    sql = f"SELECT {cols} FROM {q} e JOIN {sub} ON e.lane = h.l AND e.seq = h.m ORDER BY e.lane"  # noqa: S608
    rows = ex.query(sql, column_types={"lane": "string", "seq": "int", "ts": "timestamp"})
    return [{**r, "ts": format_ts(r["ts"]) if r["ts"] is not None else None} for r in rows]


def _require_sqlite(settings: Settings, what: str) -> Path:
    if settings.effective_sql_backend != "sqlite" or settings.sqlite_path is None:
        raise BackupError(f"{what} is for SQLite mode; use export-delta")
    return Path(settings.sqlite_path)


# ----------------------------------------------------------------------------- backup


def backup(settings: Settings, out: Path, *, include_key: bool = False) -> dict[str, Any]:
    from supervisor.adapters.factory import build_adapters

    db = _require_sqlite(settings, "backup")
    if not db.is_file():
        raise BackupError(f"SQLite store not found: {db}")
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise BackupError(f"backup directory is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    live = build_adapters(settings)
    try:
        live.executor.backup_to(out / DB_NAME)  # type: ignore[attr-defined]
    finally:
        live.close()
    snap = build_adapters(settings.model_copy(update={"sqlite_path": out / DB_NAME}))
    try:
        counts = table_counts(snap)
        heads = lane_heads(snap)
    finally:
        snap.close()
    for suffix in ("-wal", "-shm"):
        (out / (DB_NAME + suffix)).unlink(missing_ok=True)
    key_path = Path(settings.signer_key_path) if settings.signer_key_path else None
    key_included = False
    if include_key and key_path is not None and key_path.is_file():
        shutil.copyfile(key_path, out / KEY_NAME)
        key_included = True
    anchors_copied = 0
    if settings.anchor_kind == "worm_dir" and settings.anchor_path:
        src = Path(settings.anchor_path)
        if src.is_dir():
            shutil.copytree(src, out / ANCHOR_DIR)
            anchors_copied = sum(1 for p in (out / ANCHOR_DIR).rglob("*") if p.is_file())
    model = load_model()
    manifest: dict[str, Any] = {
        "format": BACKUP_FORMAT,
        "created_at": utc_stamp(),
        "app_version": __version__,
        "schema_version": model.version,
        "schema_model_hash": model.source_hash,
        "table_prefix": settings.table_prefix,
        "db_file": DB_NAME,
        "db_sha256": sha256_file(out / DB_NAME),
        "db_size": (out / DB_NAME).stat().st_size,
        "table_counts": counts,
        "chain_lane_heads": heads,
        "signing_key_included": key_included,
        "signing_key_note": (
            f"{KEY_NAME} is in this folder: store it as a secret, separate from the data."
            if key_included
            else "The signing key is NOT in this backup. Back up SIGNER_KEY_PATH separately "
            "to a secret store, or re-run with --include-key. Without it, restored "
            "evidence still verifies, but new roots need the same key (key continuity)."
        ),
        "anchors_dir": ANCHOR_DIR if anchors_copied else None,
        "anchor_files": anchors_copied,
    }
    write_json(out / MANIFEST, manifest)
    return manifest


# ----------------------------------------------------------------------------- restore


def read_manifest(src: Path) -> dict[str, Any]:
    mp = Path(src) / MANIFEST
    if not mp.is_file():
        raise BackupError(f"no {MANIFEST} in {src}")
    try:
        doc = json.loads(mp.read_text(encoding="utf-8"))
        _ = (doc["db_sha256"], doc["db_file"], doc["schema_version"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BackupError(f"{mp} is not a valid backup manifest ({type(exc).__name__})") from exc
    return doc  # type: ignore[no-any-return]


def verify_chain_of(settings: Settings) -> tuple[bool, list[str]]:
    """Export the whole chain to a scratch dir and verify it offline (as the console does)."""
    from supervisor.adapters.factory import build_adapters
    from supervisor.evidence.export import export_chain
    from supervisor.evidence.verify import verify_export

    a = build_adapters(settings)
    work = Path(tempfile.mkdtemp(prefix="supervisor-verify-"))
    try:
        export_chain(a.tables, work / "chain")
        anchors = (
            Path(settings.anchor_path)
            if settings.anchor_kind == "worm_dir" and settings.anchor_path
            else None
        )
        report = verify_export(
            work / "chain",
            anchors_dir=anchors if anchors is not None and anchors.is_dir() else None,
        )
        return report.failures == 0, list(report.lines)
    finally:
        a.close()
        shutil.rmtree(work, ignore_errors=True)


def restore(settings: Settings, src: Path, *, force: bool = False) -> dict[str, Any]:
    src = Path(src).resolve()
    target = _require_sqlite(settings, "restore")
    manifest = read_manifest(src)
    db = src / manifest["db_file"]
    if not db.is_file():
        raise BackupError(f"backup database missing: {db}")
    if sha256_file(db) != manifest["db_sha256"]:
        raise BackupError("sha256 mismatch: the backup database was changed or damaged")
    model = load_model()
    warnings: list[str] = []
    if int(manifest["schema_version"]) > model.version:
        raise BackupError(
            f"backup schema version {manifest['schema_version']} is newer than this code "
            f"({model.version}); install the newer release first"
        )
    if manifest.get("schema_model_hash") != model.source_hash:
        warnings.append(
            "backup schema model differs from this code (older backup); run: "
            "python -m supervisor.jobs.bootstrap_schema (migrates additively)"
        )
    if manifest.get("table_prefix", "") != settings.table_prefix:
        raise BackupError(
            f"backup table prefix {manifest.get('table_prefix')!r} differs from "
            f"TABLE_PREFIX {settings.table_prefix!r}"
        )
    moved: str | None = None
    if target.exists():
        if not force:
            raise BackupError(f"target store exists: {target} (use --force to move it aside)")
        aside = target.with_name(f"{target.name}.pre-restore-{utc_stamp()}")
        shutil.move(str(target), str(aside))
        moved = str(aside)
    for suffix in ("-wal", "-shm"):
        stale = target.with_name(target.name + suffix)
        if stale.exists():
            shutil.move(str(stale), str(stale) + f".pre-restore-{utc_stamp()}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(db, target)
    key_restored = False
    key_src = src / KEY_NAME
    key_dst = Path(settings.signer_key_path) if settings.signer_key_path else None
    if key_src.is_file() and key_dst is not None and not key_dst.exists():
        key_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(key_src, key_dst)
        key_restored = True
    anchors_restored = 0
    if (src / ANCHOR_DIR).is_dir() and settings.anchor_kind == "worm_dir" and settings.anchor_path:
        dst = Path(settings.anchor_path)
        dst.mkdir(parents=True, exist_ok=True)
        for f in (src / ANCHOR_DIR).rglob("*"):
            rel = f.relative_to(src / ANCHOR_DIR)
            if f.is_file() and not (dst / rel).exists():
                (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dst / rel)
                anchors_restored += 1
    ok, lines = verify_chain_of(settings)
    return {
        "target": str(target),
        "moved_aside": moved,
        "key_restored": key_restored,
        "anchors_restored": anchors_restored,
        "warnings": warnings,
        "verify_ok": ok,
        "verify_lines": lines,
        "manifest": manifest,
    }


# ----------------------------------------------------------------------------- export-delta


def export_delta(
    settings: Settings, out: Path, *, tables: list[str] | None = None
) -> dict[str, Any]:
    """One read-only SELECT per table (paged by the adapter) -> DIR/<table>.jsonl."""
    from supervisor.adapters.factory import build_adapters

    a = build_adapters(settings)
    try:
        model = a.model
        names = tables or list(model.tables)
        unknown = [n for n in names if n not in model.tables]
        if unknown:
            raise BackupError(f"unknown table(s): {', '.join(unknown)}")
        out = Path(out).resolve()
        if out.exists() and any(out.iterdir()):
            raise BackupError(f"export directory is not empty: {out}")
        out.mkdir(parents=True, exist_ok=True)
        files: dict[str, dict[str, Any]] = {}
        for name in names:
            t = model.table(name)
            sql = f"SELECT {', '.join(t.column_names)} FROM {a.executor.qualify(name)}"  # noqa: S608
            rows = a.executor.query(sql, column_types=t.types)
            path = out / f"{name}.jsonl"
            with path.open("w", encoding="utf-8", newline="\n") as fh:
                for row in rows:
                    fh.write(
                        json.dumps(row, default=_jsonable, sort_keys=True, ensure_ascii=False)
                        + "\n"
                    )
            files[name] = {"file": path.name, "rows": len(rows), "sha256": sha256_file(path)}
        host = settings.databricks_host
        manifest: dict[str, Any] = {
            "format": BACKUP_FORMAT,
            "created_at": utc_stamp(),
            "app_version": __version__,
            "schema_version": model.version,
            "schema_model_hash": model.source_hash,
            "backend": settings.effective_sql_backend,
            "workspace_host": "FILL-ME-host" if host is None or is_placeholder(host) else host,
            "catalog": settings.databricks_catalog,
            "schema": settings.databricks_schema,
            "tables": files,
        }
        write_json(out / MANIFEST, manifest)
        return manifest
    finally:
        a.close()
