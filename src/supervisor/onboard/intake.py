"""Candidate source intake (WP-O1, phase 9, flag ONBOARD_INTAKE).

A person brings the code of a candidate (an inventory node) or an agent to Supervisor:

* ``submit_zip``   a zip of text files (Python and config only), at most ONBOARD_INTAKE_MAX_MB;
* ``submit_git``   a clone of an ``https://`` URL on a host of ONBOARD_GIT_HOSTS (the clone runs in
                   ``sandbox.git_clone_https``; no other module starts a process);
* ``submit_workspace`` a stub: answers ``not_built`` (WP-O1c).

Every intake is a numbered attempt (``intake_attempt`` row; a re-upload is attempt n+1 and the old
attempts stay). The WP16 scrubber (``onboard/scrub.py``) runs on every file in memory BEFORE
anything is written: the stored tree under ``<data_dir>/intake/<node_id>/<n>/`` holds scrubbed text
only, and a secret never reaches the disk, the row or a log. The row keeps the source reference,
the SHA-256 and size of what was received, the file count and a counts-only note.

Refusals are ``IntakeError`` with a code (``bad_path``, ``symlink``, ``file_type_not_allowed``,
``binary_file``, ``too_large`` ...): HTTP 400 with the message ``<code>: <text>``. A refusal after
the bytes arrived is also written as a ``failed`` attempt, so the person sees it in the list.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import threading
import uuid
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from supervisor import sandbox
from supervisor.core.canonical import format_ts
from supervisor.core.errors import SandboxError, SupervisorError
from supervisor.onboard import agent_log
from supervisor.onboard.scrub import Scrubber, scrub_text

ALLOWED_SUFFIXES = (
    ".py",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".md",
    ".txt",
    ".cfg",
    ".ini",
    ".env.example",
    ".sql",
    ".ipynb",
)
MAX_FILES = 2000
MAX_FILE_BYTES = 2_000_000
MAX_PATH_CHARS = 240
MAX_DEPTH = 20
SOURCE_KINDS = ("upload", "git", "workspace")
STATUSES = ("stored", "scrubbed", "failed")
FLAG_MESSAGE = "intake_off: candidate source intake is off (ONBOARD_INTAKE=1 turns it on)"
_NODE_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
_SAFE_DIR = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$")
_URL_PATH = re.compile(r"^/[A-Za-z0-9._~/-]{1,200}$")
_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_LOCK = threading.RLock()  # one writer allocates an attempt number at a time (one app process)


class IntakeError(SupervisorError):
    """A refused intake. ``code`` is the stable machine word; the message starts with it."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


# ----------------------------------------------------------------------------- small checks


def require_on(settings: Any) -> None:
    if not settings.onboard_intake:
        raise IntakeError("intake_off", FLAG_MESSAGE.split(": ", 1)[1])


def check_node_id(node_id: str) -> str:
    if not _NODE_ID.match(node_id or "") or node_id in (".", ".."):
        raise IntakeError("bad_node_id", "the node id must be 1 to 128 of A-Z a-z 0-9 _ . : @ -")
    return node_id


def node_dir_name(node_id: str) -> str:
    """A folder name that is safe on every file system and never collides between two ids."""
    if _SAFE_DIR.match(node_id):
        return node_id
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", node_id).lstrip("-.") or "node"
    return f"{safe[:100]}-{hashlib.sha256(node_id.encode('utf-8')).hexdigest()[:8]}"


def git_hosts(settings: Any) -> tuple[str, ...]:
    raw = str(settings.onboard_git_hosts or "").replace(";", ",")
    return tuple(h for h in (x.strip().lower() for x in raw.split(",")) if h)


def max_bytes(settings: Any) -> int:
    return int(settings.onboard_intake_max_mb) * 1024 * 1024


def allowed_name(name: str) -> bool:
    low = name.lower()
    return any(low.endswith(s) for s in ALLOWED_SUFFIXES)


def parse_git_url(url: str, hosts: tuple[str, ...]) -> str:
    """The canonical ``https://host/path`` of an allowed clone URL, else ``IntakeError``."""
    if not hosts:
        raise IntakeError("git_off", "git intake is off (ONBOARD_GIT_HOSTS is empty)")
    raw = str(url or "").strip()
    if not raw or len(raw) > 300 or any(c.isspace() or ord(c) < 32 for c in raw):
        raise IntakeError("git_url_invalid", "the URL must be one https:// address")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise IntakeError("git_url_invalid", "the URL must be one https:// address") from None
    if parts.scheme.lower() != "https":
        raise IntakeError("git_url_invalid", "only https:// URLs are allowed")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise IntakeError("url_has_credentials", "the URL must not hold a user name or password")
    host = (parts.hostname or "").lower()
    if not _HOST.match(host):
        raise IntakeError("git_url_invalid", "the URL has no valid host name")
    if host not in hosts:
        raise IntakeError("git_host_not_allowed", f"{host} is not in ONBOARD_GIT_HOSTS")
    if port not in (None, 443):
        raise IntakeError("git_url_invalid", "only the default https port is allowed")
    path = parts.path[:-1] if parts.path.endswith("/") else parts.path
    if parts.query or parts.fragment or not _URL_PATH.match(path) or ".." in path.split("/"):
        raise IntakeError("git_url_invalid", "the URL path must be plain (no query, no fragment)")
    return f"https://{host}{path}"


# ----------------------------------------------------------------------------- file checks


def _bad_path(name: str) -> bool:
    """True for an absolute path, a drive letter, a backslash, a control character or a
    ``..`` / ``.`` / empty segment."""
    if not name or len(name) > MAX_PATH_CHARS:
        return True
    if name.startswith(("/", "\\")) or _DRIVE.match(name) or "\\" in name:
        return True
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        return True
    segments = name.split("/")
    if len(segments) > MAX_DEPTH:
        return True
    return any(s in ("", ".", "..") for s in segments)


def _decode_text(name: str, data: bytes) -> str:
    if b"\x00" in data:
        raise IntakeError("binary_file", f"{_shown(name)} is not a text file")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IntakeError("binary_file", f"{_shown(name)} is not UTF-8 text") from None


def _shown(name: str) -> str:
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in name)[:80]


def notebook_to_py(name: str, text: str) -> str:
    """Only the code cells of a notebook, as Python text. Outputs and markdown are dropped
    (an output can hold data); IPython magics become comments so the text stays parseable."""
    try:
        nb = json.loads(text)
        cells = nb["cells"] if isinstance(nb, dict) else None
        if not isinstance(cells, list):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise IntakeError("bad_notebook", f"{_shown(name)} is not a valid notebook") from None
    out: list[str] = []
    for i, cell in enumerate(cells):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        body = "".join(str(x) for x in src) if isinstance(src, list) else str(src)
        lines = [
            ("# " + ln if ln.lstrip().startswith(("%", "!")) else ln) for ln in body.split("\n")
        ]
        out.append(f"# %% cell {i}\n" + "\n".join(lines).rstrip("\n") + "\n")
    return "\n".join(out)


def _add_file(files: dict[str, str], name: str, data: bytes) -> None:
    """Decode one allowed file and add it (an ipynb becomes ``.py``)."""
    text = _decode_text(name, data)
    if name.lower().endswith(".ipynb"):
        text = notebook_to_py(name, text)
        new = name[: -len(".ipynb")] + ".py"
        name = new if new not in files else name + ".py"
    key = name.lower()
    if any(k.lower() == key for k in files):
        raise IntakeError("duplicate_path", f"{_shown(name)} appears twice")
    files[name] = text


def read_zip(data: bytes, limit: int) -> dict[str, str]:
    """Check every member of a zip and return {relative path: text}. Nothing is written."""
    if len(data) > limit:
        raise IntakeError("too_large", f"the zip is larger than {limit // (1024 * 1024)} MB")
    if not data:
        raise IntakeError("not_zip", "the upload is empty")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError):
        raise IntakeError("not_zip", "the upload is not a zip file") from None
    files: dict[str, str] = {}
    total = 0
    with zf:
        members = [i for i in infos if not i.filename.endswith("/")]
        if len(members) > MAX_FILES:
            raise IntakeError("too_many_files", f"more than {MAX_FILES} files in the zip")
        for info in members:
            name = info.filename
            if _bad_path(name):
                raise IntakeError("bad_path", f"{_shown(name)} is not a safe relative path")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise IntakeError("symlink", f"{_shown(name)} is a symbolic link")
            if info.flag_bits & 0x1:
                raise IntakeError("encrypted", f"{_shown(name)} is encrypted")
            if not allowed_name(name):
                raise IntakeError(
                    "file_type_not_allowed",
                    f"{_shown(name)}: only {' '.join(ALLOWED_SUFFIXES)} files are taken in",
                )
            if info.file_size > MAX_FILE_BYTES:
                raise IntakeError("too_large", f"{_shown(name)} is larger than 2 MB")
            try:
                with zf.open(info) as fh:
                    raw = fh.read(MAX_FILE_BYTES + 1)
            except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError):
                raise IntakeError("not_zip", f"{_shown(name)} cannot be read") from None
            if len(raw) > MAX_FILE_BYTES:
                raise IntakeError("too_large", f"{_shown(name)} is larger than 2 MB")
            total += len(raw)
            if total > limit:
                raise IntakeError("too_large", "the unpacked files are larger than the limit")
            _add_file(files, name, raw)
    if not files:
        raise IntakeError("empty", "the zip holds no files")
    return files


def read_tree(root: Path, limit: int) -> tuple[dict[str, str], int]:
    """The allowed text files of a cloned folder ({path: text}, number skipped). A clone holds
    other files (images, licences, ``.git``): they are skipped and counted, not refused."""
    files: dict[str, str] = {}
    skipped = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames if d != ".git" and not (Path(dirpath) / d).is_symlink()
        )
        for fname in sorted(filenames):
            full = Path(dirpath) / fname
            rel = full.relative_to(root).as_posix()
            if full.is_symlink() or _bad_path(rel) or not allowed_name(rel):
                skipped += 1
                continue
            try:
                size = full.stat().st_size
                if size > MAX_FILE_BYTES:
                    skipped += 1
                    continue
                raw = full.read_bytes()
            except OSError:
                skipped += 1
                continue
            try:
                _add_file(files, rel, raw)
            except IntakeError as exc:
                if exc.code in ("binary_file", "bad_notebook", "duplicate_path"):
                    skipped += 1
                    continue
                raise
            total += len(raw)
            if total > limit:
                raise IntakeError("too_large", "the cloned files are larger than the limit")
            if len(files) > MAX_FILES:
                raise IntakeError("too_many_files", f"more than {MAX_FILES} files in the clone")
    if not files:
        raise IntakeError("empty", "the clone holds no Python or config files")
    return files, skipped


def tree_sha256(files: Mapping[str, str]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode("utf-8") + b"\x00")
        h.update(hashlib.sha256(files[name].encode("utf-8")).digest())
    return h.hexdigest()


def clean_name(name: str) -> str:
    """A display name for the upload: the last segment, plain characters, no secret."""
    base = re.split(r"[\\/]", str(name or "upload.zip"))[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:120] or "upload.zip"
    return scrub_text(base).text


# ----------------------------------------------------------------------------- the service


class IntakeService:
    """Attempts of one app: ``state`` is the StateStore, ``clock`` has ``now()``."""

    def __init__(self, settings: Any, state: Any, clock: Any, tables: Any = None) -> None:
        self.settings = settings
        self.state = state
        self.clock = clock
        self.tables = tables  # WP-O5: the agent log (onboard_log); None = no log

    # ------------------------------------------------------------------ read
    @property
    def root(self) -> Path:
        return Path(self.settings.data_dir) / "intake"

    def attempts(self, node_id: str) -> list[dict[str, Any]]:
        """Attempts of one node, newest first, as plain JSON-safe dicts."""
        check_node_id(node_id)
        rows = [dict(r) for r in self.state.query("intake_attempt", {"node_id": node_id})]
        rows.sort(key=lambda r: int(r["n"]), reverse=True)
        return [attempt_view(r) for r in rows]

    def tree_path(self, node_id: str, n: int) -> Path:
        """Where attempt ``n`` is stored (WP-O2 reads it). Not checked for existence."""
        check_node_id(node_id)
        return self.root / node_dir_name(node_id) / str(int(n))

    # ------------------------------------------------------------------ write
    def submit_zip(self, node_id: str, data: bytes, filename: str, actor: str) -> dict[str, Any]:
        require_on(self.settings)
        check_node_id(node_id)
        digest = hashlib.sha256(data).hexdigest()
        ref = clean_name(filename)
        try:
            files = read_zip(data, max_bytes(self.settings))
        except IntakeError as exc:
            self._record_failed(node_id, "upload", ref, digest, len(data), actor, exc)
            raise
        return self._store(node_id, "upload", ref, digest, len(data), files, actor, "")

    def submit_git(self, node_id: str, url: str, actor: str) -> dict[str, Any]:
        require_on(self.settings)
        check_node_id(node_id)
        canon = parse_git_url(url, git_hosts(self.settings))
        tmp = self.root / node_dir_name(node_id) / f".clone-{uuid.uuid4().hex[:12]}"
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            try:
                res = sandbox.git_clone_https(canon, tmp / "repo", timeout_s=120.0)
            except SandboxError as exc:
                raise IntakeError("clone_failed", _short(str(exc))) from None
            if not res.ok:
                raise IntakeError(
                    "clone_failed", "git could not clone the URL (see the server log)"
                )
            files, skipped = read_tree(tmp / "repo", max_bytes(self.settings))
        except IntakeError as exc:
            self._record_failed(node_id, "git", canon, "", 0, actor, exc)
            raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        size = sum(len(t.encode("utf-8")) for t in files.values())
        return self._store(
            node_id, "git", canon, tree_sha256(files), size, files, actor, f"skipped={skipped}"
        )

    def submit_workspace(self, node_id: str, path: str, actor: str) -> dict[str, Any]:
        require_on(self.settings)
        check_node_id(node_id)
        raise IntakeError(
            "not_built",
            "a Databricks workspace folder as a source is not built yet (WP-O1c); "
            "use a zip upload or a git URL",
        )

    # ------------------------------------------------------------------ internals
    def _next_n(self, node_id: str) -> int:
        rows = self.state.query("intake_attempt", {"node_id": node_id})
        return max((int(r["n"]) for r in rows), default=0) + 1

    def _insert(self, row: dict[str, Any]) -> dict[str, Any]:
        return attempt_view(dict(self.state.insert("intake_attempt", row)))

    def _record_failed(
        self,
        node_id: str,
        kind: str,
        ref: str,
        digest: str,
        size: int,
        actor: str,
        exc: IntakeError,
    ) -> None:
        try:
            with _LOCK:
                self._insert(
                    {
                        "attempt_id": "ita_" + uuid.uuid4().hex[:24],
                        "node_id": node_id,
                        "n": self._next_n(node_id),
                        "source_kind": kind,
                        "source_ref": ref,
                        "sha256": digest,
                        "size_bytes": size,
                        "file_count": 0,
                        "created_by": actor,
                        "created_at": self.clock.now(),
                        "status": "failed",
                        "detail": scrub_text(str(exc)).text[:200],
                    }
                )
            agent_log.log(  # WP-O5
                self,
                node_id,
                "intake",
                f"source refused: {exc.code}",
                f"intake {kind}",
                "person",
                actor,
            )
        except Exception:  # noqa: BLE001, S110 - the refusal itself is the answer; a row is a courtesy
            pass

    def _store(
        self,
        node_id: str,
        kind: str,
        ref: str,
        digest: str,
        size: int,
        files: dict[str, str],
        actor: str,
        note: str,
    ) -> dict[str, Any]:
        """Scrub in memory, write the scrubbed tree, then the ``scrubbed`` row."""
        scrubber = Scrubber()
        clean = {name: scrubber.scrub(text, source=name) for name, text in files.items()}
        base = self.root / node_dir_name(node_id)
        root = self.root.resolve()
        with _LOCK:
            n = self._next_n(node_id)
            while (base / str(n)).exists():  # a folder without a row (older crash): skip it
                n += 1
            final = base / str(n)
            tmp = base / f".tmp-{uuid.uuid4().hex[:12]}"
            try:
                for name, text in clean.items():
                    target = (tmp / name).resolve()
                    if root not in target.parents:  # never true after _bad_path; belt and braces
                        raise IntakeError("bad_path", f"{_shown(name)} leaves the intake folder")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(text.encode("utf-8"))
                tmp.replace(final)
            except OSError as exc:
                shutil.rmtree(tmp, ignore_errors=True)
                err = IntakeError(
                    "store_failed", f"the files could not be stored ({type(exc).__name__})"
                )
                self._record_failed(node_id, kind, ref, digest, size, actor, err)
                raise err from None
            except IntakeError:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            detail = f"files={len(clean)} redacted={scrubber.total}"
            if scrubber.totals:
                detail += " kinds=" + ",".join(sorted(scrubber.totals))
            if note:
                detail += " " + note
            result = self._insert(
                {
                    "attempt_id": "ita_" + uuid.uuid4().hex[:24],
                    "node_id": node_id,
                    "n": n,
                    "source_kind": kind,
                    "source_ref": ref,
                    "sha256": digest,
                    "size_bytes": size,
                    "file_count": len(clean),
                    "created_by": actor,
                    "created_at": self.clock.now(),
                    "status": "scrubbed",
                    "detail": detail[:200],
                }
            )
        agent_log.log(  # WP-O5
            self,
            node_id,
            "intake",
            f"source taken in ({kind}): {len(clean)} files, {scrubber.total} secrets redacted",
            f"intake attempt {n}",
            "person",
            actor,
            attempt_n=n,
        )
        return result


def _short(text: str) -> str:
    return scrub_text("".join(c if 32 <= ord(c) < 127 else "?" for c in text)).text[:120]


def attempt_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """The public shape of an attempt (no server path)."""
    created = row.get("created_at")
    return {
        "attempt_id": row["attempt_id"],
        "node_id": row["node_id"],
        "n": int(row["n"]),
        "source_kind": row["source_kind"],
        "source_ref": row["source_ref"],
        "sha256": row["sha256"],
        "size_bytes": int(row["size_bytes"]),
        "file_count": int(row["file_count"]),
        "created_by": row["created_by"],
        "created_at": format_ts(created)
        if created is not None and not isinstance(created, str)
        else created,
        "status": row["status"],
        "detail": row.get("detail"),
    }
