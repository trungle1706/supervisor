"""Anchors (port ``Anchor``): write the signed root entry to a write-once target.

* ``WormDirAnchor``: a local directory. ``put`` refuses to overwrite (O_EXCL) and
  marks the file read-only. On a laptop this shows the mechanism only: an admin
  can still delete files (ADR D05). The bank WORM target is a backlog item.
* ``UcVolumeAnchor``: a Unity Catalog volume path written through the Databricks
  Files API (``WorkspaceClient().files``). The Files API object is injected, so
  this module never imports ``databricks``; tests use a fake.

Receipt format (ASCII): ``sha256=<hex of the bytes>;path=<where it was written>``.
The anchor document is canonical JSON with the root entry, its payload, the
signature and the public key, named ``<root entry hash>.json``.
"""

from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from supervisor.core.canonical import canonical_bytes
from supervisor.core.errors import SupervisorError
from supervisor.evidence.verify import ANCHOR_FORMAT, CHAIN_SPEC_VERSION, anchor_name


class AnchorError(SupervisorError):
    """The anchor target refused the write or cannot be reached."""


def receipt_for(data: bytes, path: str) -> str:
    return f"sha256={hashlib.sha256(data).hexdigest()};path={path}"


def _check_name(name: str) -> None:
    if not name or "/" in name or "\\" in name or name.startswith(".") or ".." in name:
        raise AnchorError(f"invalid anchor file name {name!r}")


class WormDirAnchor:
    """Write-once directory anchor."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(os.path.abspath(path))
        self.target = f"worm_dir:{self.path}"

    def location(self, name: str) -> str:
        _check_name(name)
        return str(self.path / name)

    def exists(self, name: str) -> bool:
        _check_name(name)
        return (self.path / name).exists()

    def put(self, name: str, data: bytes) -> str:
        _check_name(name)
        self.path.mkdir(parents=True, exist_ok=True)
        dest = self.path / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(dest, flags, 0o444)
        except FileExistsError:
            raise AnchorError(f"anchor {dest} already exists; write-once target") from None
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        try:
            os.chmod(dest, 0o444)
        except OSError:
            pass
        return receipt_for(data, str(dest))


class FilesApi(Protocol):
    """The part of ``databricks.sdk`` ``WorkspaceClient().files`` this anchor uses."""

    def upload(self, file_path: str, contents: Any, *, overwrite: bool | None = None) -> Any: ...

    def get_metadata(self, file_path: str) -> Any: ...


def _is_not_found(exc: Exception) -> bool:
    name = type(exc).__name__
    code = str(getattr(exc, "error_code", "") or "")
    return name in ("NotFound", "ResourceDoesNotExist") or code in (
        "NOT_FOUND",
        "RESOURCE_DOES_NOT_EXIST",
    )


class UcVolumeAnchor:
    """Unity Catalog volume anchor (``/Volumes/<catalog>/<schema>/<volume>/<dir>``)."""

    def __init__(self, files: FilesApi, volume_path: str) -> None:
        path = volume_path.rstrip("/")
        if not path.startswith("/Volumes/") or path.count("/") < 4:
            raise AnchorError("ANCHOR_PATH must look like /Volumes/<catalog>/<schema>/<volume>")
        self.files = files
        self.volume_path = path
        self.target = f"uc_volume:{path}"

    def location(self, name: str) -> str:
        _check_name(name)
        return f"{self.volume_path}/{name}"

    def exists(self, name: str) -> bool:
        _check_name(name)
        try:
            self.files.get_metadata(f"{self.volume_path}/{name}")
        except Exception as exc:  # noqa: BLE001 - SDK error classes are not imported here
            if _is_not_found(exc):
                return False
            raise AnchorError(f"cannot read {self.volume_path}/{name}: {exc}") from exc
        return True

    def put(self, name: str, data: bytes) -> str:
        dest = self.location(name)
        if self.exists(name):
            raise AnchorError(f"anchor {dest} already exists; write-once target")
        try:
            self.files.upload(dest, io.BytesIO(data), overwrite=False)
        except Exception as exc:  # noqa: BLE001
            raise AnchorError(f"upload to {dest} failed: {exc}") from exc
        return receipt_for(data, dest)


def anchor_document(
    root_entry: Mapping[str, Any],
    payload_text: str,
    signature: Mapping[str, Any],
    public_key_pem: str,
) -> tuple[str, bytes]:
    """(file name, canonical bytes) of the anchor document for one signed root."""
    entry = dict(root_entry)
    doc = {
        "format": ANCHOR_FORMAT,
        "chain_spec_version": CHAIN_SPEC_VERSION,
        "root_entry": entry,
        "payload": payload_text,
        "signature": {
            "signature": signature["signature"],
            "key_id": signature["key_id"],
            "algorithm": signature["algorithm"],
            "key_kind": signature.get("key_kind", "dev"),
        },
        "public_key": public_key_pem,
    }
    return anchor_name(str(entry["entry_hash"])), canonical_bytes(doc)


def build_anchor(settings: Any) -> WormDirAnchor | UcVolumeAnchor:
    """Anchor adapter from Settings (``ANCHOR_KIND`` = worm_dir | uc_volume)."""
    kind = getattr(settings, "anchor_kind", "worm_dir")
    path = getattr(settings, "anchor_path", None)
    if not path:
        raise AnchorError("ANCHOR_PATH is not set")
    if kind == "worm_dir":
        return WormDirAnchor(Path(path))
    if kind == "uc_volume":
        from supervisor.adapters.sql.databricks_rest import make_workspace_client

        return UcVolumeAnchor(make_workspace_client(settings).files, str(path))
    raise AnchorError(f"unknown ANCHOR_KIND {kind!r}")
