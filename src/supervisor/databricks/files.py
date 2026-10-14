"""Files API helper for Unity Catalog Volumes (``/Volumes/<catalog>/<schema>/<volume>/...``).

Why: on the Databricks App ``/tmp`` is wiped on restart, so durable files (anchors, the
recorder spool) go to a Volume. The App may have no ``/Volumes`` file mount, so writes go
through the Files API (``WorkspaceClient().files``), which is injected here: this module
never imports ``databricks`` (architecture test). Tests use a fake with the same methods.

* :class:`VolumeFiles` wraps the Files API: write-once put, read, list, delete, and the
  ``upload`` / ``get_metadata`` pair that :class:`~supervisor.evidence.anchor.UcVolumeAnchor`
  uses. Errors name the path and the fix.
* :class:`VolumeSpool` is the recorder spool on a Volume. The Files API cannot append, so
  every ``put`` writes a new small JSONL object. ``staged_spool`` copies the objects to a
  local folder for the ingest job and deletes each remote object only after its local
  copy was ingested (``.done``). Replays are safe: the event writer skips known event ids.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from supervisor.core.errors import SupervisorError
from supervisor.recorder.sink import SPOOL_SUFFIX, Spool

VOLUME_PREFIX = "/Volumes/"


class VolumeError(SupervisorError):
    """A Files API call on a Unity Catalog Volume failed."""


class FilesApiLike(Protocol):
    """The part of ``WorkspaceClient().files`` used here."""

    def upload(self, file_path: str, contents: Any, *, overwrite: bool | None = None) -> Any: ...

    def get_metadata(self, file_path: str) -> Any: ...

    def download(self, file_path: str) -> Any: ...

    def list_directory_contents(self, directory_path: str) -> Any: ...

    def delete(self, file_path: str) -> Any: ...

    def create_directory(self, directory_path: str) -> Any: ...


def is_volume_path(path: str | os.PathLike[str] | None) -> bool:
    return path is not None and str(path).replace("\\", "/").startswith(VOLUME_PREFIX)


def volume_root(path: str) -> str:
    """``/Volumes/<catalog>/<schema>/<volume>`` of a path inside a Volume."""
    parts = str(path).replace("\\", "/").strip("/").split("/")
    if len(parts) < 4 or parts[0] != "Volumes" or not all(parts[1:4]):
        raise VolumeError(f"not a Unity Catalog Volume path: {path} (want /Volumes/c/s/v/...)")
    return "/" + "/".join(parts[:4])


def volume_mounted(path: str) -> bool:
    """True when the Volume is visible as a local folder (a /Volumes mount exists)."""
    try:
        return os.path.isdir(volume_root(path))
    except VolumeError:
        return False


def _code(exc: Exception) -> str:
    return str(getattr(exc, "error_code", "") or "").upper()


def is_not_found(exc: Exception) -> bool:
    return type(exc).__name__ in ("NotFound", "ResourceDoesNotExist") or _code(exc) in (
        "NOT_FOUND",
        "RESOURCE_DOES_NOT_EXIST",
    )


def is_already_exists(exc: Exception) -> bool:
    return type(exc).__name__ in ("AlreadyExists", "ResourceAlreadyExists") or _code(exc) in (
        "ALREADY_EXISTS",
        "RESOURCE_ALREADY_EXISTS",
    )


def _fail(action: str, path: str, exc: Exception) -> VolumeError:
    hint = ""
    name = type(exc).__name__
    if name == "PermissionDenied" or "PERMISSION" in _code(exc) or "403" in str(exc):
        hint = (
            " -- fix: grant READ VOLUME and WRITE VOLUME on the volume to this identity "
            "(the App service principal on the App)"
        )
    elif is_not_found(exc):
        hint = " -- fix: create the volume (CREATE VOLUME catalog.schema.volume) or fix the path"
    return VolumeError(f"Files API {action} {path} failed: {name}: {exc}{hint}")


class VolumeFiles:
    """Files API wrapper with write-once semantics and self-diagnosing errors."""

    def __init__(self, files: FilesApiLike) -> None:
        self.files = files

    # -- FilesApi protocol used by UcVolumeAnchor --------------------------------------
    def upload(self, file_path: str, contents: Any, *, overwrite: bool | None = None) -> Any:
        try:
            return self.files.upload(file_path, contents, overwrite=overwrite)
        except Exception as exc:  # noqa: BLE001 - SDK error classes are not imported here
            if is_already_exists(exc):
                raise VolumeError(f"{file_path} already exists; write-once target") from exc
            raise _fail("upload", file_path, exc) from exc

    def get_metadata(self, file_path: str) -> Any:
        return self.files.get_metadata(file_path)  # caller maps NotFound

    # -- helpers --------------------------------------------------------------------------
    def exists(self, path: str) -> bool:
        try:
            self.files.get_metadata(path)
        except Exception as exc:  # noqa: BLE001
            if is_not_found(exc):
                return False
            raise _fail("get_metadata", path, exc) from exc
        return True

    def put_new(self, path: str, data: bytes) -> str:
        """Write ``data`` to ``path``; refuse to overwrite. Return the path."""
        if self.exists(path):
            raise VolumeError(f"{path} already exists; write-once target")
        self.upload(path, io.BytesIO(data), overwrite=False)
        return path

    def read(self, path: str) -> bytes:
        try:
            resp = self.files.download(path)
        except Exception as exc:  # noqa: BLE001
            raise _fail("download", path, exc) from exc
        body = getattr(resp, "contents", resp)
        return body.read() if hasattr(body, "read") else bytes(body)

    def list_names(self, directory: str) -> list[str]:
        """File names (not directories) in ``directory``; [] when it does not exist."""
        try:
            entries = list(self.files.list_directory_contents(directory.rstrip("/")))
        except Exception as exc:  # noqa: BLE001
            if is_not_found(exc):
                return []
            raise _fail("list", directory, exc) from exc
        return sorted(
            str(getattr(e, "name", None) or str(getattr(e, "path", "")).rsplit("/", 1)[-1])
            for e in entries
            if not getattr(e, "is_directory", False)
        )

    def delete(self, path: str) -> None:
        try:
            self.files.delete(path)
        except Exception as exc:  # noqa: BLE001
            if is_not_found(exc):
                return
            raise _fail("delete", path, exc) from exc


class VolumeSpool(Spool):
    """Recorder spool on a Volume through the Files API. One small object per ``put``."""

    def __init__(self, files: VolumeFiles, directory: str) -> None:
        volume_root(directory)  # validates the path
        self.dir = Path(directory)  # informational; never opened locally
        self.remote_dir = str(directory).replace("\\", "/").rstrip("/")
        self.vfiles = files
        self._lock = threading.Lock()
        self._prefix = f"spool-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._seq = 0

    def put(self, record: Mapping[str, Any]) -> Path:  # type: ignore[override]
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock:
            self._seq += 1
            name = f"{self._prefix}-{self._seq:08d}{SPOOL_SUFFIX}"
        path = f"{self.remote_dir}/{name}"
        self.vfiles.put_new(path, (line + "\n").encode("utf-8"))
        return Path(path)

    def pull(self, local_dir: Path) -> list[str]:
        """Copy remote spool objects not yet staged into ``local_dir``. Return their names."""
        local_dir.mkdir(parents=True, exist_ok=True)
        pulled = []
        for name in self.vfiles.list_names(self.remote_dir):
            if not name.endswith(SPOOL_SUFFIX):
                continue
            stem = name[: -len(SPOOL_SUFFIX)]
            if any((local_dir / (stem + s)).exists() for s in (SPOOL_SUFFIX, ".ingesting")):
                continue
            data = self.vfiles.read(f"{self.remote_dir}/{name}")
            tmp = local_dir / (stem + ".part")
            tmp.write_bytes(data)
            tmp.replace(local_dir / name)
            pulled.append(name)
        return pulled

    def ack(self, local_dir: Path) -> list[str]:
        """Delete remote objects whose local copy was ingested (``<stem>.done``)."""
        removed = []
        for name in self.vfiles.list_names(self.remote_dir):
            stem = name[: -len(SPOOL_SUFFIX)] if name.endswith(SPOOL_SUFFIX) else None
            if stem and (local_dir / (stem + ".done")).exists():
                self.vfiles.delete(f"{self.remote_dir}/{name}")
                removed.append(name)
        return removed


def make_files(settings: Any, client: Any = None) -> VolumeFiles:
    if client is None:
        from supervisor.adapters.sql.databricks_rest import make_workspace_client

        client = make_workspace_client(settings)
    return VolumeFiles(client.files)


def make_spool(settings: Any, files: VolumeFiles | None = None) -> Spool | None:
    """The recorder spool for ``RECORDER_SPOOL_DIR`` / ``SPOOL_DIR``.

    A local folder (or a mounted Volume) -> :class:`Spool`. A ``/Volumes/...`` path with no
    local mount (the Databricks App) -> :class:`VolumeSpool` over the Files API."""
    directory = getattr(settings, "recorder_spool_dir", None)
    if directory is None:
        return None
    text = str(directory).replace("\\", "/")
    if is_volume_path(text) and not volume_mounted(text):
        return VolumeSpool(files or make_files(settings), text)
    return Spool(Path(directory))


def staging_dir(remote_dir: str) -> Path:
    """Local folder where a Volume spool is staged for ingest (per spool path)."""
    tag = remote_dir.strip("/").replace("/", "_")
    return Path(tempfile.gettempdir()).resolve() / "supervisor-spool-staging" / tag


@contextmanager
def staged_spool(settings: Any, directory: Path | str | None) -> Iterator[Path | None]:
    """Yield the folder the ingest job should read.

    For a Volume spool with no local mount: pull the remote objects to a local staging
    folder first, and after the caller ingested them delete the remote copies that ended
    ``.done``. Otherwise yield ``directory`` unchanged."""
    text = None if directory is None else str(directory).replace("\\", "/")
    if text is None or not is_volume_path(text) or volume_mounted(text):
        yield None if directory is None else Path(directory)
        return
    spool = VolumeSpool(make_files(settings), text)
    local = staging_dir(text)
    spool.pull(local)
    yield local
    spool.ack(local)
