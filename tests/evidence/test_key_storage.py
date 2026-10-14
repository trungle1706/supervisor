"""Signing key on a UC Volume (Files API fake) and the key continuity check."""

from __future__ import annotations

import json
import logging

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from supervisor.databricks.files import VolumeFiles
from supervisor.evidence.chain import ChainWriter, KeyContinuityError, build_chain_writer
from supervisor.evidence.export import export_chain
from supervisor.evidence.signer import (
    SignerError,
    VolumeFileSigner,
    _Ed25519Signer,
    build_signer,
)
from supervisor.evidence.verify import main as verify_main
from tests.databricks.fakes import FakeFiles
from tests.evidence.conftest import Env, fixed_signer, make_writer

KEY = "/Volumes/c/s/v/supervisor/data/keys/evidence_ed25519.pem"


def test_create_once_then_load(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeFiles()
    with caplog.at_level(logging.DEBUG):
        a = VolumeFileSigner(VolumeFiles(fake), KEY)
        assert KEY in fake.store and b"PRIVATE KEY" in fake.store[KEY]
        pem = fake.store[KEY]
        b = VolumeFileSigner(VolumeFiles(fake), KEY)  # second start: load, no new key
    assert fake.store[KEY] == pem
    assert a.key_id == b.key_id and a.key_kind == "dev"
    assert b.verify(b"m", a.sign(b"m"))
    secret = pem.decode()
    assert secret not in caplog.text and secret.splitlines()[1] not in caplog.text
    assert secret.splitlines()[1] not in repr(a) and "PRIVATE" not in repr(a)
    assert a.public_key_pem().startswith("-----BEGIN PUBLIC KEY")


def test_managed_label_only_when_settings_say_so() -> None:
    assert VolumeFileSigner(VolumeFiles(FakeFiles()), KEY, managed=True).key_kind == "managed"


def test_write_is_refuse_overwrite() -> None:
    fake = FakeFiles()
    vf = VolumeFiles(fake)
    VolumeFileSigner(vf, KEY)
    before = fake.store[KEY]
    from supervisor.databricks.files import VolumeError

    with pytest.raises(VolumeError):
        vf.put_new(KEY, b"other")
    assert fake.store[KEY] == before


def test_start_race_reloads_winner() -> None:
    fake = FakeFiles()
    winner = Ed25519PrivateKey.generate()
    from supervisor.evidence.signer import _private_pem

    class Racy(VolumeFiles):
        def exists(self, path: str) -> bool:
            if path not in fake.store and not getattr(self, "raced", False):
                self.raced = True
                fake.store[path] = _private_pem(winner)  # another start wrote it meanwhile
                return False
            return super().exists(path)

    s = VolumeFileSigner(Racy(fake), KEY)
    from supervisor.evidence.signer import key_id_for

    assert s.key_id == key_id_for(winner.public_key())


def test_bad_key_object_and_bad_path_do_not_leak() -> None:
    fake = FakeFiles()
    fake.store[KEY] = (
        b"-----BEGIN PRIV" + b"ATE KEY-----\nSECRETISH\n-----END PRIV" + b"ATE KEY-----\n"
    )
    with pytest.raises(SignerError) as e:
        VolumeFileSigner(VolumeFiles(fake), KEY)
    assert "SECRETISH" not in str(e.value) and "SECRETISH" not in repr(e.value.__cause__)
    with pytest.raises(SignerError):
        VolumeFileSigner(VolumeFiles(FakeFiles()), "/tmp/key.pem")


def test_permission_denied_is_a_signer_error() -> None:
    fake = FakeFiles()
    fake.deny.add("/Volumes/c/s/v")
    with pytest.raises(SignerError) as e:
        VolumeFileSigner(VolumeFiles(fake), KEY)
    assert "READ VOLUME" in str(e.value)


def test_build_signer_and_default_selection(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from supervisor.config import load_settings

    monkeypatch.setenv("SUPERVISOR_MODE", "databricks_app")
    monkeypatch.setenv("DATA_DIR", "/Volumes/c/s/v/supervisor/data")
    s = load_settings()
    assert s.signer_kind == "uc_volume"
    fake = FakeFiles()
    signer = build_signer(s, VolumeFiles(fake))
    assert isinstance(signer, VolumeFileSigner) and KEY in fake.store
    # explicit choice wins over the default
    s2 = load_settings(signer_kind="ed25519_file", signer_key_path=tmp_path / "k.pem")
    assert s2.signer_kind == "ed25519_file"
    # uc_volume needs a Volume path
    s3 = load_settings(signer_kind="uc_volume", signer_key_path=tmp_path / "k.pem")
    with pytest.raises(SignerError):
        build_signer(s3, VolumeFiles(fake))


def test_laptop_default_unchanged(tmp_path) -> None:
    from supervisor.config import load_settings

    assert load_settings(data_dir=tmp_path).signer_kind == "ed25519_file"
    assert load_settings(data_dir=tmp_path).signer_allow_rotation is False


# ------------------------------------------------------------ key continuity


def _other() -> _Ed25519Signer:
    return _Ed25519Signer(Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33))), "dev")


def _writer(env: Env, signer: _Ed25519Signer, **kw: object) -> ChainWriter:
    return ChainWriter(
        env.adapters.tables,
        env.clock,
        signer,
        writer_id="test-writer",
        root_every_n=1000,
        root_every_s=10_000,
        **kw,  # type: ignore[arg-type]
    )


def _seed(env: Env) -> None:
    w = make_writer(env)
    w.record("verdict", "verdict:v0", {"agent_id": "a1", "score_bp": 1})
    w.close()


def test_same_key_starts(env: Env) -> None:
    _seed(env)
    make_writer(env).close()
    make_writer(env).close()


def test_empty_store_accepts_any_key(env: Env) -> None:
    _writer(env, _other()).close()


def test_different_key_is_refused_and_slot_released(env: Env) -> None:
    _seed(env)
    with pytest.raises(KeyContinuityError) as e:
        _writer(env, _other())
    assert "SIGNER_ALLOW_ROTATION=1" in str(e.value)
    make_writer(env).close()  # the old key still works: the failed start left no lock behind
    rows = env.adapters.tables.query("chain_entry", {"lane": "root"}, order_by=["seq"])
    assert all(r["record_type"] == "root_commit" for r in rows)


def test_rotation_records_entry_and_export_verifies(env: Env, capsys) -> None:
    _seed(env)
    new = _other()
    old_id = fixed_signer().key_id
    w = _writer(env, new, allow_rotation=True)
    env.clock.advance(1)
    w.record("verdict", "verdict:v1", {"agent_id": "a1", "score_bp": 2})
    w.close()
    tables = env.adapters.tables
    rot = tables.query("chain_entry", {"lane": "root", "record_type": "key_rotation"})
    assert len(rot) == 1
    payload = json.loads(
        tables.query("chain_payload", {"lane": "root", "seq": rot[0]["seq"]})[0]["payload"]
    )
    assert payload["old_key_id"] == old_id and payload["new_key_id"] == new.key_id
    sig = tables.query("chain_signature", {"lane": "root", "seq": rot[0]["seq"]})[0]
    assert sig["key_id"] == new.key_id
    # a later start with the new key needs no flag
    _writer(env, new).close()
    with pytest.raises(KeyContinuityError):
        make_writer(env)
    out = env.tmp / "export"
    export_chain(tables, out, created_at=env.clock.now())
    code = verify_main([str(out)])
    text = capsys.readouterr().out
    assert code == 0, text


def test_rotation_entry_cannot_be_recorded_by_callers(env: Env) -> None:
    from supervisor.evidence.chain import ChainError

    w = make_writer(env)
    with pytest.raises(ChainError):
        w.record("key_rotation", "x", {"a": 1}, lane="root")
    w.close()


def test_build_chain_writer_uses_volume_key_and_rotation_flag(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.config import load_settings

    monkeypatch.setenv("SUPERVISOR_MODE", "databricks_app")
    monkeypatch.setenv("DATA_DIR", "/Volumes/c/s/v/supervisor/data")
    fake = FakeFiles()
    s = load_settings()
    t, c = env.adapters.tables, env.clock
    w = build_chain_writer(s, t, c, VolumeFiles(fake))
    w.record("verdict", "verdict:v0", {"agent_id": "a1", "score_bp": 1})
    w.close()
    w = build_chain_writer(s, t, c, VolumeFiles(fake))  # restart: same key
    w.close()
    fake.store.clear()  # the key is lost (the old failure mode): new key on next start
    with pytest.raises(KeyContinuityError):
        build_chain_writer(s, t, c, VolumeFiles(fake))
    fake.store.clear()
    s2 = load_settings(signer_allow_rotation=True)
    build_chain_writer(s2, t, c, VolumeFiles(fake)).close()
    assert t.query("chain_entry", {"lane": "root", "record_type": "key_rotation"})
