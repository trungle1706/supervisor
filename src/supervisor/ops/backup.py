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
import os
import secrets
import shutil
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
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
        _copy_private(key_path, out / KEY_NAME)
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


def _chain_key_ids(chain_dir: Path) -> set[str]:
    """Key ids named in the exported ``public_keys.jsonl`` (what the chain claims signed it)."""
    out: set[str] = set()
    f = chain_dir / "public_keys.jsonl"
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                kid = json.loads(line).get("key_id")
            except (ValueError, AttributeError):
                continue
            if isinstance(kid, str):
                out.add(kid)
    return out


def _verify_chain(
    settings: Settings, pubkey_pem: bytes | None = None
) -> tuple[bool, list[str], set[str]]:
    """Export the whole chain to a scratch dir and verify it offline (as the console does).

    ``pubkey_pem`` pins the notary key. Returns (ok, report lines, key ids the chain carries)."""
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
        pin: Path | None = None
        if pubkey_pem is not None:
            pin = work / "pinned.pem"
            pin.write_bytes(pubkey_pem)
        report = verify_export(
            work / "chain",
            pubkey=pin,
            anchors_dir=anchors if anchors is not None and anchors.is_dir() else None,
        )
        return report.failures == 0, list(report.lines), _chain_key_ids(work / "chain")
    finally:
        a.close()
        shutil.rmtree(work, ignore_errors=True)


def verify_chain_of(settings: Settings, pubkey_pem: bytes | None = None) -> tuple[bool, list[str]]:
    ok, lines, _ = _verify_chain(settings, pubkey_pem)
    return ok, lines


def _key_id_of_pem(pem: bytes) -> str:
    from supervisor.evidence.verify import _load_public_key

    try:
        return _load_public_key(pem)[1]
    except (ValueError, TypeError) as exc:
        raise BackupError(f"public key is not a readable Ed25519 PEM ({exc})") from exc


def current_public_key_pem(settings: Settings) -> bytes | None:
    """Public key of the signer this deployment uses now, or None when it cannot be found.

    Never creates a key: a missing key file means "no pinned key", not "make one"."""
    from supervisor.evidence.signer import build_signer

    kind = settings.signer_kind
    if kind == "ed25519_file" and not (
        settings.signer_key_path and Path(settings.signer_key_path).is_file()
    ):
        return None
    if kind == "env" and not os.environ.get(settings.signer_env_var):
        return None
    try:
        return build_signer(settings).public_key_pem().encode("ascii")
    except Exception:  # noqa: BLE001 - any signer problem means "cannot pin"
        return None


def safe_db_path(src: Path, name: Any) -> Path:
    """Manifest ``db_file`` must be a bare file name inside the backup folder."""
    bad = (
        not isinstance(name, str)
        or not name.strip()
        or name != name.strip()
        or any(c in name for c in ("/", "\\", ":", "\0"))
        or ".." in name
        or PurePosixPath(name).is_absolute()
        or PureWindowsPath(name).is_absolute()
        or PureWindowsPath(name).drive != ""
        or PurePosixPath(name).name != name
        or PureWindowsPath(name).name != name
    )
    if bad:
        raise BackupError(f"manifest db_file {name!r} is not a bare file name; backup refused")
    path = (src / name).resolve()
    if path.parent != src.resolve() or (src / name).is_symlink():
        raise BackupError(f"manifest db_file {name!r} points outside the backup folder; refused")
    return path


def _tail(lines: list[str], n: int = 3) -> str:
    bad = [x for x in lines if "FAIL" in x] or lines
    return " | ".join(bad[:n])


def _plan_key_install(
    src: Path,
    key_dst: Path | None,
    pinned_id: str | None,
    chain_ids: set[str],
    warnings: list[str],
) -> Path | None:
    """Backup key file to install, or None. Checked before the swap; a bad key is a warning.

    Installed only when it is a regular file (not a symlink), the target has no key, and its
    public key is the pinned key (or, with no pinned key, a key the chain verified with)."""
    import stat

    from supervisor.evidence.signer import SignerError, _load_pem_private, key_id_for

    key_src = src / KEY_NAME
    try:
        st = os.lstat(key_src)
    except OSError:
        return None
    if key_dst is None or os.path.lexists(key_dst):
        return None
    if not stat.S_ISREG(st.st_mode):
        warnings.append(f"{KEY_NAME} in the backup is not a regular file (symlink?): not installed")
        return None
    try:
        kid = key_id_for(_load_pem_private(key_src.read_bytes(), KEY_NAME).public_key())
    except (SignerError, ValueError, TypeError, OSError):
        warnings.append(f"{KEY_NAME} in the backup is not a readable Ed25519 key: not installed")
        return None
    if (kid != pinned_id) if pinned_id else (kid not in chain_ids):
        warnings.append(
            f"{KEY_NAME} in the backup (key {kid}) is not the "
            f"{'pinned' if pinned_id else 'chain'} key: not installed. Restore the real signing "
            "key from your secret store"
        )
        return None
    return key_src


def restore(
    settings: Settings,
    src: Path,
    *,
    force: bool = False,
    pubkey: Path | None = None,
    allow_key_change: bool = False,
) -> dict[str, Any]:
    """Restore a backup. Nothing live changes until a private copy has passed every check.

    The manifest sha256 only catches accidental damage (the manifest sits beside the data, so
    whoever can change one can change both): it is not an authenticity check. Authenticity
    comes from verifying the chain with the public key of the current signer (or ``pubkey``).
    ``allow_key_change`` accepts a backup signed by another key, with a warning, after the
    chain has been checked with the backup's own key."""
    src = Path(src).resolve()
    target = _require_sqlite(settings, "restore")
    manifest = read_manifest(src)
    db = safe_db_path(src, manifest["db_file"])
    if not db.is_file():
        raise BackupError(f"backup database missing: {db}")
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
    if target.exists() and not force:
        raise BackupError(f"target store exists: {target} (use --force to move it aside)")
    # The key to trust: --pubkey, else the current signer's. Decided before any copy.
    if pubkey is not None:
        if not Path(pubkey).is_file():
            raise BackupError(f"--pubkey file not found: {pubkey}")
        pinned: bytes | None = Path(pubkey).read_bytes()
    else:
        pinned = current_public_key_pem(settings)
    pinned_id = _key_id_of_pem(pinned) if pinned is not None else None
    if pinned is None and not allow_key_change:
        raise BackupError(
            "no signer public key to pin (no key file or env key for this deployment): pass "
            "--pubkey FILE with the notary public key, or --allow-key-change to accept the "
            "key inside the backup (that proves integrity only, not authenticity)"
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"cannot create {target.parent} ({exc})") from exc
    tmp = target.with_name(f"{target.name}.restore-tmp-{secrets.token_hex(6)}")
    key_change = False
    moved: str | None = None
    key_dst = Path(settings.signer_key_path) if settings.signer_key_path else None
    try:
        try:
            shutil.copyfile(db, tmp)  # same folder as the target: the final replace is atomic
        except OSError as exc:
            raise BackupError(f"cannot copy the backup database ({exc})") from exc
        if sha256_file(tmp) != manifest["db_sha256"]:
            raise BackupError("sha256 mismatch: the backup database was changed or damaged")
        check = settings.model_copy(update={"sqlite_path": tmp})
        ok, lines, ids = _verify_chain(check, pinned)
        if not ok:
            if not (pinned_id and ids - {pinned_id}):
                raise BackupError("evidence chain does not verify: " + _tail(lines))
            if not allow_key_change:
                raise BackupError(
                    "backup chain is signed by a different key than the pinned signer key "
                    f"(pinned {pinned_id}, backup {', '.join(sorted(ids))}); refused. Use "
                    "--pubkey FILE if the notary key changed, or --allow-key-change"
                )
            ok, lines, ids = _verify_chain(check, None)  # integrity with the backup's own key
            if not ok:
                raise BackupError("evidence chain does not verify: " + _tail(lines))
        if pinned_id is None or ids - {pinned_id}:
            key_change = True
            warnings.append(
                "WARNING: key change accepted (--allow-key-change). Pinned signer key: "
                f"{pinned_id or 'none'}; backup chain key(s): {', '.join(sorted(ids)) or 'none'}. "
                "The chain is internally consistent but its origin is not proven."
            )
        key_plan = _plan_key_install(src, key_dst, pinned_id, ids, warnings)
        stamp = utc_stamp()
        aside: Path | None = None
        if target.exists():
            aside = target.with_name(f"{target.name}.pre-restore-{stamp}")
            shutil.move(str(target), str(aside))
            moved = str(aside)
        for suffix in ("-wal", "-shm"):
            stale = target.with_name(target.name + suffix)
            if stale.exists():
                shutil.move(str(stale), str(stale) + f".pre-restore-{stamp}")
        try:
            os.replace(tmp, target)
        except OSError as exc:
            if aside is not None and not target.exists():
                shutil.move(str(aside), str(target))
            raise BackupError(f"cannot put the restored store in place ({exc})") from exc
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(tmp) + suffix).unlink(missing_ok=True)
    key_restored = False
    if key_plan is not None and key_dst is not None:
        key_dst.parent.mkdir(parents=True, exist_ok=True)
        _copy_private(key_plan, key_dst)
        key_restored = True
    anchors_restored = 0
    anchor_root = src / ANCHOR_DIR
    if anchor_root.is_symlink():
        warnings.append(f"{ANCHOR_DIR} in the backup is a symlink: anchors not restored")
    elif anchor_root.is_dir() and settings.anchor_kind == "worm_dir" and settings.anchor_path:
        dst = Path(settings.anchor_path)
        dst.mkdir(parents=True, exist_ok=True)
        root_real = anchor_root.resolve()
        for f in anchor_root.rglob("*"):
            rel = f.relative_to(anchor_root)
            if f.is_symlink() or (f.exists() and not f.resolve().is_relative_to(root_real)):
                warnings.append(f"anchor entry {rel} is a symlink or outside the backup: skipped")
                continue
            if f.is_file() and not (dst / rel).exists():
                (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dst / rel)
                anchors_restored += 1
    return {
        "target": str(target),
        "moved_aside": moved,
        "key_restored": key_restored,
        "anchors_restored": anchors_restored,
        "warnings": warnings,
        "verify_ok": True,  # the copy was verified before the swap; a failure raises instead
        "verify_lines": lines,
        "key_change": key_change,
        "pinned_key_id": pinned_id,
        "manifest": manifest,
    }


# ----------------------------------------------------------------------------- export-delta

RESTRICTED = ("agent_event_raw",)  # unmasked capture (schema/model.yaml): opt-in only


def _copy_private(src: Path, dst: Path) -> None:
    """Copy a secret (the signing key) and make it owner-only where the OS allows it."""
    shutil.copyfile(src, dst)
    try:
        os.chmod(dst, 0o600)
    except OSError:  # Windows ACLs: the folder's own permissions apply
        pass


def export_delta(
    settings: Settings,
    out: Path,
    *,
    tables: list[str] | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """One read-only SELECT per table (paged by the adapter) -> DIR/<table>.jsonl.

    The RESTRICTED raw-capture table is left out unless ``include_raw`` (or it is named in
    ``tables``): an export on disk has no table grants to protect it."""
    from supervisor.adapters.factory import build_adapters

    a = build_adapters(settings)
    try:
        model = a.model
        skipped = [] if (tables or include_raw) else [t for t in RESTRICTED if t in model.tables]
        names = tables or [t for t in model.tables if t not in skipped]
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
            "skipped_restricted": skipped,
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
