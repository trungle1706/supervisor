from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import stat
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from supervisor.config import load_settings
from supervisor.evidence.anchor import AnchorError, UcVolumeAnchor, WormDirAnchor, build_anchor
from supervisor.evidence.signer import (
    Ed25519FileSigner,
    EnvSecretSigner,
    SignerError,
    build_signer,
    generate_seed_b64,
)
from supervisor.evidence.verify import ANCHOR_FORMAT, entry_hash
from supervisor.jobs.anchor import run as anchor_run
from tests.evidence.conftest import SEED, Env, fixed_signer, populate

# ------------------------------------------------------------------ signer


def test_file_signer_creates_key_0600_and_reuses_it(tmp_path: Path) -> None:
    path = tmp_path / "keys" / "k.pem"
    s1 = Ed25519FileSigner(path)
    assert path.exists()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    s2 = Ed25519FileSigner(path)
    assert s1.key_id == s2.key_id and s1.key_kind == "dev"
    raw = s1.public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert s1.key_id == hashlib.sha256(raw).hexdigest()
    sig = s1.sign(b"data")
    assert s2.verify(b"data", sig)
    assert not s2.verify(b"datA", sig)
    assert not s2.verify(b"data", sig[:-1] + bytes([sig[-1] ^ 1]))
    assert Ed25519FileSigner(path, managed=True).key_kind == "managed"
    with pytest.raises(SignerError):
        Ed25519FileSigner(tmp_path / "none.pem", create=False)


def test_signature_from_other_key_is_rejected(tmp_path: Path) -> None:
    a = Ed25519FileSigner(tmp_path / "a.pem")
    b = Ed25519FileSigner(tmp_path / "b.pem")
    assert a.key_id != b.key_id
    assert not b.verify(b"x", a.sign(b"x"))


def test_public_key_export(tmp_path: Path) -> None:
    s = Ed25519FileSigner(tmp_path / "k.pem")
    out = s.export_public_key(tmp_path / "pub.pem")
    text = out.read_text(encoding="ascii")
    assert text.startswith("-----BEGIN PUBLIC KEY-----")
    assert "PRIVATE" not in text


@pytest.mark.parametrize("fmt", ["b64", "hex", "pem"])
def test_env_signer_formats_and_no_key_in_repr(
    monkeypatch: pytest.MonkeyPatch, fmt: str, caplog: pytest.LogCaptureFixture
) -> None:
    ref = fixed_signer()
    if fmt == "b64":
        value = base64.b64encode(SEED).decode()
    elif fmt == "hex":
        value = SEED.hex()
    else:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        value = (
            Ed25519PrivateKey.from_private_bytes(SEED)
            .private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            .decode()
        )
    monkeypatch.setenv("SUPERVISOR_SIGNING_KEY", value)
    caplog.set_level(logging.DEBUG)
    s = EnvSecretSigner()
    assert s.key_id == ref.key_id
    assert s.verify(b"m", ref.sign(b"m"))
    shown = repr(s) + str(s) + caplog.text
    for secret in (value, SEED.hex(), base64.b64encode(SEED).decode()):
        assert secret not in shown


def test_env_signer_errors_do_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_SIGNING_KEY", raising=False)
    with pytest.raises(SignerError, match="not set"):
        EnvSecretSigner()
    monkeypatch.setenv("SUPERVISOR_SIGNING_KEY", "not-a-key-but-secret-ish")
    with pytest.raises(SignerError) as e:
        EnvSecretSigner()
    assert "not-a-key-but-secret-ish" not in str(e.value)
    assert len(base64.b64decode(generate_seed_b64())) == 32


def test_build_signer_from_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = load_settings(data_dir=tmp_path)
    signer = build_signer(s)
    assert isinstance(signer, Ed25519FileSigner)
    assert signer.key_path == tmp_path / "keys" / "evidence_ed25519.pem"
    monkeypatch.setenv("SUPERVISOR_SIGNING_KEY", base64.b64encode(SEED).decode())
    s2 = load_settings(data_dir=tmp_path, signer_kind="env", signer_key_managed=True)
    env_signer = build_signer(s2)
    assert isinstance(env_signer, EnvSecretSigner) and env_signer.key_kind == "managed"


# ------------------------------------------------------------------ anchors


def test_worm_dir_refuses_overwrite(tmp_path: Path) -> None:
    a = WormDirAnchor(tmp_path / "anchors")
    receipt = a.put("abc.json", b"hello")
    assert (
        receipt == f"sha256={hashlib.sha256(b'hello').hexdigest()};path={tmp_path}/anchors/abc.json"
    )
    assert a.exists("abc.json")
    with pytest.raises(AnchorError, match="already exists"):
        a.put("abc.json", b"other")
    assert (tmp_path / "anchors" / "abc.json").read_bytes() == b"hello"
    for bad in ("../x.json", "a/b.json", ".hidden", ""):
        with pytest.raises(AnchorError):
            a.put(bad, b"x")


class FakeNotFound(Exception):
    error_code = "NOT_FOUND"


class FakeFiles:
    """Fake of databricks.sdk FilesAPI (upload / get_metadata) with server-side overwrite check."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.calls: list[tuple[str, str, object]] = []

    def get_metadata(self, file_path: str) -> dict:
        self.calls.append(("get_metadata", file_path, None))
        if file_path not in self.store:
            raise FakeNotFound(f"{file_path} not found")
        return {"content_length": len(self.store[file_path])}

    def upload(
        self, file_path: str, contents: io.BytesIO, *, overwrite: bool | None = None
    ) -> None:
        self.calls.append(("upload", file_path, overwrite))
        if file_path in self.store and not overwrite:
            raise RuntimeError("ALREADY_EXISTS")
        self.store[file_path] = contents.read()


def test_uc_volume_anchor_against_fake() -> None:
    files = FakeFiles()
    a = UcVolumeAnchor(files, "/Volumes/main/sup/evidence/anchors/")
    assert a.target == "uc_volume:/Volumes/main/sup/evidence/anchors"
    r = a.put("h.json", b"doc")
    path = "/Volumes/main/sup/evidence/anchors/h.json"
    assert files.store[path] == b"doc"
    assert ("upload", path, False) in files.calls
    assert r == f"sha256={hashlib.sha256(b'doc').hexdigest()};path={path}"
    with pytest.raises(AnchorError, match="already exists"):
        a.put("h.json", b"doc2")
    assert files.store[path] == b"doc"
    with pytest.raises(AnchorError):
        UcVolumeAnchor(files, "/tmp/x")


def test_uc_volume_anchor_errors_are_wrapped() -> None:
    class Broken(FakeFiles):
        def get_metadata(self, file_path: str) -> dict:
            raise PermissionError("403 PERMISSION_DENIED")

    with pytest.raises(AnchorError, match="cannot read"):
        UcVolumeAnchor(Broken(), "/Volumes/c/s/v").put("x.json", b"1")


def test_build_anchor_from_settings(tmp_path: Path) -> None:
    a = build_anchor(load_settings(data_dir=tmp_path))
    assert isinstance(a, WormDirAnchor) and a.path == tmp_path / "anchors"


@pytest.mark.skipif(os.environ.get("RUN_DATABRICKS") != "1", reason="set RUN_DATABRICKS=1")
@pytest.mark.databricks
def test_uc_volume_anchor_live() -> None:  # pragma: no cover - live kit
    import uuid

    s = load_settings(anchor_kind="uc_volume", anchor_path=os.environ["ANCHOR_PATH"])
    a = build_anchor(s)
    name = f"live-test-{uuid.uuid4().hex}.json"
    a.put(name, b"{}")
    with pytest.raises(AnchorError):
        a.put(name, b"{}")


def test_anchor_job_writes_document_and_row(env: Env) -> None:
    populate(env)
    anchor = WormDirAnchor(env.tmp / "anchors")
    res = anchor_run(env.adapters.settings, env.adapters, anchor=anchor)
    assert res["status"] == "anchored"
    rows = env.adapters.tables.query("anchor")
    assert len(rows) == 1
    row = rows[0]
    doc_path = env.tmp / "anchors" / res["name"]
    data = doc_path.read_bytes()
    assert row["receipt"].startswith(f"sha256={hashlib.sha256(data).hexdigest()};")
    import json

    doc = json.loads(data)
    assert doc["format"] == ANCHOR_FORMAT
    assert entry_hash(doc["root_entry"]) == doc["root_entry"]["entry_hash"] == row["root_hash"]
    assert "BEGIN PUBLIC KEY" in doc["public_key"] and doc["signature"]["key_id"] == row["key_id"]
    assert row["seq_from"] == 0 and row["seq_to"] == doc["root_entry"]["seq"]
    # idempotent: second run skips
    assert anchor_run(env.adapters.settings, env.adapters, anchor=anchor)["status"] == "skipped"


def test_anchor_job_seal_and_crash_recovery(env: Env) -> None:
    from tests.evidence.conftest import make_writer

    w = make_writer(env)
    w.record("e", "e:0", {"agent_id": "a1"})
    anchor = WormDirAnchor(env.tmp / "anchors")
    anchor_run(env.adapters.settings, env.adapters, anchor=anchor)
    w.record("e", "e:1", {"agent_id": "a1"})
    res = anchor_run(env.adapters.settings, env.adapters, anchor=anchor, writer=w, seal=True)
    assert res["status"] == "anchored"
    rows = env.adapters.tables.query("anchor", order_by=["seq_to"])
    assert rows[1]["seq_from"] == rows[0]["seq_to"] + 1
    w.record("e", "e:2", {"agent_id": "a1"})
    w.commit_root()
    w.close(seal=False)

    # crash after file write, before the row: rerun records the row with the same receipt
    class CrashAfterPut(WormDirAnchor):
        def put(self, name: str, data: bytes) -> str:
            super().put(name, data)
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        anchor_run(env.adapters.settings, env.adapters, anchor=CrashAfterPut(env.tmp / "anchors"))
    res = anchor_run(env.adapters.settings, env.adapters, anchor=anchor)
    assert res["status"] == "anchored"
    data = (env.tmp / "anchors" / res["name"]).read_bytes()
    assert (
        res["receipt"]
        == f"sha256={hashlib.sha256(data).hexdigest()};path={anchor.location(res['name'])}"
    )


def test_anchor_job_without_root_skips(env: Env) -> None:
    res = anchor_run(env.adapters.settings, env.adapters, anchor=WormDirAnchor(env.tmp / "a"))
    assert res["status"] == "skipped"


def test_anchor_job_cli(tmp_path: Path) -> None:
    from supervisor import sandbox

    res = sandbox.run(
        [sandbox.python_executable(), "-m", "supervisor.jobs.anchor"], cwd=tmp_path, timeout_s=120
    )
    # no tables yet -> clear ASCII failure or skip, never a traceback
    assert res.stdout.isascii() and "Traceback" not in res.stderr, res.stderr
    assert res.stdout.startswith(("[FAIL]", "[SKIP]")), res.stdout
    assert sys.executable  # keep import used
