"""The signed update package of the regulation watcher and its import (WP-W1, phase 11).

Package (a zip, 50 MB at most), members:

* ``manifest.json``: ``{"format": "regwatch-package-1", "run_id", "created_at", "members":
  [{"name", "sha256", "size"}]}`` with every member except ``manifest.json`` and ``signature``;
* ``signature``: JSON ``{"algorithm": "ed25519", "key_id", "key_kind", "signed": "<sha256 of the
  manifest bytes>", "signature": "<base64>", "public_key": "<PEM>"}``. The signature is made by
  the evidence signer over ``SIGNING_PREFIX + sha256(manifest.json)``;
* ``watch-<date>.json`` and ``watch-<date>.md``: the watch report;
* ``proposed_changes.yaml``: an empty placeholder for WP-W2 (the diff mode fills it);
* ``incoming/<instrument id>/<date>/<name>.txt`` with ``<name>.meta.json``: the new texts.

Import (``verify_package`` then ``store_package``) checks size, names, signature against the
trusted public key, and every member sha against the manifest. Nothing is applied: the package
is stored under ``<data dir>/regkb/incoming/<package sha256>/`` for the review of WP-W2.
Everything inside is data: it is read as bytes and JSON, never imported or executed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from supervisor.core.errors import SupervisorError

PACKAGE_FORMAT = "regwatch-package-1"
SIGNING_PREFIX = b"supervisor-regwatch-package/v1 "
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_MEMBERS = 600
MANIFEST = "manifest.json"
SIGNATURE = "signature"
PLACEHOLDER = "proposed_changes.yaml"
PLACEHOLDER_TEXT = (
    "# Placeholder for WP-W2 (change to re-evaluation). Empty on purpose: nothing is proposed or\n"
    "# applied by the watcher.\n"
    "format: regwatch-proposed-changes-1\n"
    "proposed: []\n"
)
_FIXED = {MANIFEST, SIGNATURE, PLACEHOLDER}
_REPORT_RE = re.compile(r"^watch-\d{4}-\d{2}-\d{2}\.(json|md)$")
_INCOMING_RE = re.compile(
    r"^incoming/(?:VN|INTL|INT)-[A-Z0-9]+(?:-[A-Z0-9]+){0,3}/\d{4}-\d{2}-\d{2}/"
    r"[a-z0-9][a-z0-9._-]{0,120}\.(?:txt|meta\.json)$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

CODES = (
    "regwatch_off",
    "nothing_to_import",
    "too_large",
    "bad_zip",
    "path_traversal",
    "unknown_member",
    "bad_manifest",
    "bad_signature",
    "untrusted_key",
    "sha_mismatch",
)


class PackageError(SupervisorError):
    """A refused package. The message starts with the short code (HTTP 400 at the route)."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_id_of(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def member_allowed(name: str) -> bool:
    return name in _FIXED or bool(_REPORT_RE.match(name)) or bool(_INCOMING_RE.match(name))


def check_member_path(name: str) -> None:
    parts = name.split("/")
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or "\x00" in name
        or any(p in ("..", ".", "") for p in parts)
    ):
        raise PackageError("path_traversal", f"member path is not allowed: {name[:80]!r}")


# ---------------------------------------------------------------------------- build


def build_package(
    target: Path,
    *,
    report_json: Path,
    report_md: Path,
    incoming: Sequence[Any],
    signer: Any,
    run_id: str,
    created_at: str,
) -> tuple[Path, str]:
    """Write the signed zip. ``incoming`` items have ``instrument_id``, ``name``, ``data``,
    ``meta`` (see ``watch.Incoming``). Returns the path and the sha256 of the zip."""
    members: dict[str, bytes] = {
        report_json.name: report_json.read_bytes(),
        report_md.name: report_md.read_bytes(),
        PLACEHOLDER: PLACEHOLDER_TEXT.encode("utf-8"),
    }
    for item in incoming:
        name = f"incoming/{item.instrument_id}/{item.name}"
        members[name] = bytes(item.data)
        members[name[: -len(".txt")] + ".meta.json"] = (
            json.dumps(item.meta, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
    for name in members:
        check_member_path(name)
        if not member_allowed(name):
            raise PackageError("unknown_member", f"member name is not allowed: {name}")
    manifest = {
        "format": PACKAGE_FORMAT,
        "run_id": run_id,
        "created_at": created_at,
        "members": [
            {"name": n, "sha256": sha256_hex(members[n]), "size": len(members[n])}
            for n in sorted(members)
        ],
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=1) + "\n").encode("utf-8")
    digest = sha256_hex(manifest_bytes)
    pem = getattr(signer, "public_key_pem", None)
    raw_sig = signer.sign(SIGNING_PREFIX + digest.encode("ascii"))
    signature = {
        "algorithm": getattr(signer, "algorithm", "ed25519"),
        "key_id": signer.key_id,
        "key_kind": getattr(signer, "key_kind", "dev"),
        "signed": digest,
        "signature": base64.b64encode(raw_sig).decode("ascii"),
        "public_key": pem() if callable(pem) else str(pem or ""),
    }
    buf = io.BytesIO()
    sig_bytes = (json.dumps(signature, sort_keys=True, indent=1) + "\n").encode("utf-8")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in [
            (MANIFEST, manifest_bytes),
            (SIGNATURE, sig_bytes),
            *sorted(members.items()),
        ]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    blob = buf.getvalue()
    if len(blob) > MAX_PACKAGE_BYTES:
        raise PackageError("too_large", "the package is larger than 50 MB")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    return target, sha256_hex(blob)


# ---------------------------------------------------------------------------- verify


@dataclass
class VerifiedPackage:
    sha256: str
    size: int
    manifest: dict[str, Any]
    signature: dict[str, Any]
    members: dict[str, bytes]
    report: dict[str, Any]


def load_public_key(pem: bytes | str) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(pem.encode() if isinstance(pem, str) else pem)
    except (ValueError, TypeError) as exc:
        raise PackageError("untrusted_key", "the trusted public key is not usable") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise PackageError("untrusted_key", "the trusted public key is not an Ed25519 key")
    return key


def _open(data: bytes) -> tuple[zipfile.ZipFile, list[zipfile.ZipInfo]]:
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackageError("too_large", "the package is larger than 50 MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        return zf, zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise PackageError("bad_zip", "the file is not a zip archive") from exc


def _read_members(zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> dict[str, bytes]:
    if len(infos) > MAX_MEMBERS:
        raise PackageError("too_large", f"more than {MAX_MEMBERS} members")
    total = 0
    seen: set[str] = set()
    for info in infos:
        check_member_path(info.filename)
        if info.is_dir() or not member_allowed(info.filename) or info.filename in seen:
            raise PackageError("unknown_member", f"member is not allowed: {info.filename[:80]}")
        seen.add(info.filename)
        total += info.file_size
        if total > MAX_UNPACKED_BYTES:
            raise PackageError("too_large", "the unpacked size is larger than 200 MB")
    members: dict[str, bytes] = {}
    try:
        for info in infos:
            body = zf.read(info)
            if len(body) != info.file_size:
                raise PackageError(
                    "bad_zip", f"member size differs from its header: {info.filename}"
                )
            members[info.filename] = body
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, EOFError) as exc:
        raise PackageError("bad_zip", "a member cannot be read") from exc
    return members


def verify_package(data: bytes, trusted: Ed25519PublicKey) -> VerifiedPackage:
    """Check a package. Raises PackageError with a code; returns the members on success."""
    zf, infos = _open(data)
    members = _read_members(zf, infos)
    if MANIFEST not in members or SIGNATURE not in members:
        raise PackageError("bad_manifest", "manifest.json and signature are both required")
    manifest_bytes = members[MANIFEST]
    try:
        manifest = json.loads(manifest_bytes)
        sig = json.loads(members[SIGNATURE])
        listed = {str(m["name"]): (str(m["sha256"]), int(m["size"])) for m in manifest["members"]}
    except (ValueError, KeyError, TypeError) as exc:
        raise PackageError("bad_manifest", "manifest.json or signature is not valid") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != PACKAGE_FORMAT:
        raise PackageError("bad_manifest", f"format is not {PACKAGE_FORMAT}")
    if not isinstance(sig, dict):
        raise PackageError("bad_manifest", "signature is not valid")
    # the signature first: nothing in an unsigned manifest is trusted
    digest = sha256_hex(manifest_bytes)
    try:
        raw_sig = base64.b64decode(str(sig.get("signature", "")), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PackageError("bad_signature", "the signature is not base64") from exc
    if sig.get("signed") != digest:
        raise PackageError("bad_signature", "the signature does not cover this manifest")
    if str(sig.get("key_id", "")) != key_id_of(trusted):
        raise PackageError("untrusted_key", "the package is signed by a key that is not trusted")
    try:
        trusted.verify(raw_sig, SIGNING_PREFIX + digest.encode("ascii"))
    except InvalidSignature as exc:
        raise PackageError("bad_signature", "the signature is not valid") from exc
    # then every member against the manifest, in both directions
    body_names = set(members) - {MANIFEST, SIGNATURE}
    if set(listed) != body_names:
        extra = sorted(body_names ^ set(listed))[:3]
        raise PackageError("sha_mismatch", f"members and manifest differ: {extra}")
    for name, (sha, size) in listed.items():
        if not _SHA_RE.match(sha) or sha256_hex(members[name]) != sha or len(members[name]) != size:
            raise PackageError("sha_mismatch", f"sha256 of {name} differs from the manifest")
    reports = [n for n in body_names if n.endswith(".json") and _REPORT_RE.match(n)]
    if len(reports) != 1:
        raise PackageError("bad_manifest", "exactly one watch-<date>.json report is required")
    try:
        report = json.loads(members[reports[0]])
        if not isinstance(report, dict) or not isinstance(report.get("summary"), dict):
            raise ValueError("report")
    except ValueError as exc:
        raise PackageError("bad_manifest", "the watch report is not valid JSON") from exc
    return VerifiedPackage(sha256_hex(data), len(data), manifest, sig, members, report)


# ---------------------------------------------------------------------------- store and list


def incoming_root(data_dir: Path) -> Path:
    return Path(data_dir).resolve() / "regkb" / "incoming"


def _changes_of(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for r in report.get("instruments") or [] for c in r.get("changes") or []]


def summary_of(pkg_dir: Path) -> dict[str, Any]:
    """What the console lists for one stored package (read from the stored files)."""
    meta = json.loads((pkg_dir / "import.json").read_text(encoding="utf-8"))
    report: dict[str, Any] = {}
    for p in sorted(pkg_dir.glob("watch-*.json")):
        try:
            report = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report = {}
        break
    return {**meta, "report": report, "changes": _changes_of(report)}


def store_package(
    data_dir: Path, pkg: VerifiedPackage, *, actor: str, imported_at: str
) -> tuple[dict[str, Any], bool]:
    """Write the verified package under ``regkb/incoming/<sha>/``. Returns (summary, is_new).
    A package that is already stored is not written again. Nothing is applied."""
    target = incoming_root(data_dir) / pkg.sha256
    if (target / "import.json").is_file():
        return summary_of(target), False
    target.mkdir(parents=True, exist_ok=True)
    base = target.resolve()
    for name, body in pkg.members.items():
        path = (base / name).resolve()
        if base not in path.parents:
            raise PackageError("path_traversal", f"member path is not allowed: {name[:80]!r}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    meta = {
        "package_sha256": pkg.sha256,
        "size": pkg.size,
        "run_id": str(pkg.manifest.get("run_id", "")),
        "created_at": str(pkg.manifest.get("created_at", "")),
        "key_id": str(pkg.signature.get("key_id", "")),
        "key_kind": str(pkg.signature.get("key_kind", "")),
        "members": len(pkg.members) + 2,
        "imported_at": imported_at,
        "imported_by": actor,
        "applied": False,
    }
    (target / "import.json").write_text(
        json.dumps(meta, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return summary_of(target), True


def list_packages(data_dir: Path) -> list[dict[str, Any]]:
    root = incoming_root(data_dir)
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        if _SHA_RE.match(d.name) and (d / "import.json").is_file():
            try:
                out.append(summary_of(d))
            except (OSError, ValueError):
                continue
    return sorted(out, key=lambda r: str(r.get("imported_at", "")), reverse=True)


def list_reports(report_dir: Path) -> list[dict[str, Any]]:
    """Watch reports in the job's output folder (newest first)."""
    if not report_dir.is_dir():
        return []
    out = []
    for p in sorted(report_dir.glob("watch-*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("summary"), dict):
            out.append(
                {
                    "file": p.name,
                    "report": data,
                    "changes": _changes_of(data),
                    "sha256": sha256_hex(p.read_bytes()),
                }
            )
    return out


__all__ = [
    "CODES",
    "PackageError",
    "VerifiedPackage",
    "build_package",
    "incoming_root",
    "list_packages",
    "list_reports",
    "load_public_key",
    "store_package",
    "verify_package",
]
