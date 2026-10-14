"""Signers for chain heads (port ``Signer``): Ed25519 key in a file, or in an env variable.

* ``Ed25519FileSigner``: PKCS#8 PEM key file under ``data_dir`` (created on first use,
  mode 0600 on POSIX). Labelled ``key_kind = dev`` unless settings say ``managed``.
* ``EnvSecretSigner``: private key from an environment variable (Databricks App service
  principal: the platform injects the value; the app never writes it anywhere).
  Accepted formats: PKCS#8 PEM text, or base64 / hex of the raw 32-byte Ed25519 seed.

``key_id`` = SHA-256 hex of the raw 32-byte public key. Keys are never logged or
shown: ``repr()`` shows the key id and kind only.

Security note: a key in a file or an env variable is weaker than an HSM/KMS key
(ADR D05). The verifier pins the public key; key custody is a bank decision.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ALGORITHM = "ed25519"
KeyKind = Literal["dev", "managed"]


class SignerError(RuntimeError):
    """Signer cannot be built or used. Messages never contain key material."""


def key_id_for(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def public_key_pem(public_key: Ed25519PublicKey) -> str:
    return public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")


class _Ed25519Signer:
    algorithm: str = ALGORITHM

    def __init__(self, private_key: Ed25519PrivateKey, key_kind: KeyKind) -> None:
        self.__key = private_key
        self._public = private_key.public_key()
        self.key_id = key_id_for(self._public)
        self.key_kind: KeyKind = key_kind

    def __repr__(self) -> str:
        return f"{type(self).__name__}(key_id={self.key_id[:16]}..., key_kind={self.key_kind})"

    def sign(self, data: bytes) -> bytes:
        return self.__key.sign(data)

    def verify(self, data: bytes, signature: bytes) -> bool:
        try:
            self._public.verify(signature, data)
        except InvalidSignature:
            return False
        return True

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._public

    def public_key_pem(self) -> str:
        """Public key (SubjectPublicKeyInfo PEM) for verifiers and anchors."""
        return public_key_pem(self._public)

    def export_public_key(self, path: Path) -> Path:
        path = Path(os.path.abspath(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.public_key_pem(), encoding="ascii", newline="\n")
        return path


class Ed25519FileSigner(_Ed25519Signer):
    """Ed25519 key stored as an unencrypted PKCS#8 PEM file (dev or laptop)."""

    def __init__(self, key_path: Path, *, managed: bool = False, create: bool = True) -> None:
        self.key_path = Path(os.path.abspath(key_path))
        if self.key_path.exists():
            key = _load_pem_private(self.key_path.read_bytes(), str(self.key_path))
        elif create:
            key = Ed25519PrivateKey.generate()
            _write_private_key(self.key_path, key)
        else:
            raise SignerError(f"signing key file not found: {self.key_path}")
        super().__init__(key, "managed" if managed else "dev")


class EnvSecretSigner(_Ed25519Signer):
    """Ed25519 key read from an environment variable. The value is never logged."""

    def __init__(self, env_var: str = "SUPERVISOR_SIGNING_KEY", *, managed: bool = False) -> None:
        self.env_var = env_var
        value = os.environ.get(env_var, "")
        if not value.strip():
            raise SignerError(f"signing key variable {env_var} is not set")
        super().__init__(_parse_secret(value, env_var), "managed" if managed else "dev")


def _load_pem_private(data: bytes, where: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError) as exc:
        raise SignerError(f"cannot read the Ed25519 key in {where}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SignerError(f"the key in {where} is not an Ed25519 key")
    return key


def _parse_secret(value: str, where: str) -> Ed25519PrivateKey:
    text = value.strip()
    if text.startswith("-----BEGIN"):
        return _load_pem_private(text.replace("\\n", "\n").encode("ascii"), where)
    raw: bytes | None = None
    if len(text) == 64:
        try:
            raw = bytes.fromhex(text)
        except ValueError:
            raw = None
    if raw is None:
        try:
            raw = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            raw = None
    if raw is None or len(raw) != 32:
        raise SignerError(f"{where}: expected PKCS#8 PEM, or base64/hex of a 32-byte Ed25519 seed")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _write_private_key(path: Path, key: Ed25519PrivateKey) -> None:
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, pem)
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)  # Windows: only the read-only bit is honoured
    except OSError:
        pass


def generate_seed_b64() -> str:
    """New random Ed25519 seed as base64 (for provisioning EnvSecretSigner)."""
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return base64.b64encode(raw).decode("ascii")


def build_signer(settings: object) -> _Ed25519Signer:
    """Signer from Settings (``SIGNER_KIND`` = ed25519_file | env)."""
    kind = getattr(settings, "signer_kind", "ed25519_file")
    managed = bool(getattr(settings, "signer_key_managed", False))
    if kind == "env":
        return EnvSecretSigner(
            getattr(settings, "signer_env_var", "SUPERVISOR_SIGNING_KEY"), managed=managed
        )
    if kind == "ed25519_file":
        path = getattr(settings, "signer_key_path", None)
        if path is None:
            raise SignerError("SIGNER_KEY_PATH is not set")
        return Ed25519FileSigner(Path(path), managed=managed)
    raise SignerError(f"unknown SIGNER_KIND {kind!r}")
