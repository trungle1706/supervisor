"""B2: restore verifies a private copy against a pinned key before touching the live store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from supervisor import cli
from supervisor.config import Settings, load_settings
from supervisor.evidence.signer import build_signer
from supervisor.ops import backup as B

from .test_backup import cfg as cfg_fixture
from .test_backup import seed

cfg = cfg_fixture  # fixture shared with test_backup.py


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = cli.main(list(argv))
    out = capsys.readouterr().out
    assert out.isascii()
    return code, out


def _live(cfg: Settings) -> Path:
    return Path(cfg.sqlite_path)  # type: ignore[arg-type]


def _no_tmp(cfg: Settings) -> None:
    assert not list(_live(cfg).parent.glob("*.restore-tmp-*"))


def _tamper(bdir: Path) -> None:
    con = sqlite3.connect(bdir / "supervisor.db")
    for (trig,) in con.execute("select name from sqlite_master where type='trigger'").fetchall():
        con.execute(f"drop trigger {trig}")
    pt = next(
        r[0]
        for r in con.execute("select name from sqlite_master where type='table'")
        if r[0].endswith("chain_payload")
    )
    cols = [r[1] for r in con.execute(f"pragma table_info({pt})")]
    col = next(c for c in cols if "payload" in c and "hash" not in c)
    con.execute(f"update {pt} set {col}=replace({col},'payments','tampered')")
    con.commit()
    con.close()
    m = json.loads((bdir / "manifest.json").read_text())
    m["db_sha256"] = B.sha256_file(bdir / "supervisor.db")
    (bdir / "manifest.json").write_text(json.dumps(m))


def _foreign_backup(tmp_path: Path) -> tuple[Settings, Path]:
    """A valid backup whose whole chain is signed by another key."""
    s = load_settings(data_dir=tmp_path / "other", sql_backend="sqlite", llm_base_url="")
    seed(s)
    bdir = tmp_path / "bk-other"
    B.backup(s, bdir)
    return s, bdir


def test_tampered_payload_refused_live_unchanged(cfg: Settings, tmp_path: Path) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir)
    _tamper(bdir)
    before = B.sha256_file(_live(cfg))
    with pytest.raises(B.BackupError, match="does not verify"):
        B.restore(cfg, bdir, force=True)
    assert B.sha256_file(_live(cfg)) == before
    assert not list(_live(cfg).parent.glob("*.pre-restore-*"))
    _no_tmp(cfg)


def test_sha_mismatch_leaves_no_temp(cfg: Settings, tmp_path: Path) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir)
    with (bdir / "supervisor.db").open("ab") as fh:
        fh.write(b"x")
    before = B.sha256_file(_live(cfg))
    with pytest.raises(B.BackupError, match="sha256 mismatch"):
        B.restore(cfg, bdir, force=True)
    assert B.sha256_file(_live(cfg)) == before
    _no_tmp(cfg)


def test_other_key_refused(cfg: Settings, tmp_path: Path, capsys) -> None:
    _, other = _foreign_backup(tmp_path)
    before = B.sha256_file(_live(cfg))
    with pytest.raises(B.BackupError, match="different key"):
        B.restore(cfg, other, force=True)
    assert B.sha256_file(_live(cfg)) == before
    _no_tmp(cfg)
    code, out = run(capsys, "restore", "--from", str(other), "--force")
    assert code == 1 and "[FAIL]" in out and "different key" in out
    assert B.sha256_file(_live(cfg)) == before


def test_allow_key_change_accepts_with_warning(cfg: Settings, tmp_path: Path, capsys) -> None:
    other_cfg, other = _foreign_backup(tmp_path)
    mine = build_signer(cfg).key_id
    theirs = build_signer(other_cfg).key_id
    code, out = run(capsys, "restore", "--from", str(other), "--force", "--allow-key-change")
    assert code == 0 and "[WARN] WARNING:" in out and mine in out and theirs in out
    assert B.sha256_file(_live(cfg)) == B.sha256_file(other / "supervisor.db")
    _no_tmp(cfg)


def test_allow_key_change_still_checks_integrity(cfg: Settings, tmp_path: Path) -> None:
    _, other = _foreign_backup(tmp_path)
    _tamper(other)
    before = B.sha256_file(_live(cfg))
    with pytest.raises(B.BackupError, match="does not verify"):
        B.restore(cfg, other, force=True, allow_key_change=True)
    assert B.sha256_file(_live(cfg)) == before
    _no_tmp(cfg)


def test_pubkey_override(cfg: Settings, tmp_path: Path) -> None:
    other_cfg, other = _foreign_backup(tmp_path)
    pem = tmp_path / "other.pem"
    build_signer(other_cfg).export_public_key(pem)
    r = B.restore(cfg, other, force=True, pubkey=pem)
    assert r["verify_ok"] and not r["key_change"] and r["moved_aside"]
    wrong = tmp_path / "wrong.pem"
    build_signer(cfg).export_public_key(wrong)
    with pytest.raises(B.BackupError, match="different key"):
        B.restore(cfg, other, force=True, pubkey=wrong)
    with pytest.raises(B.BackupError, match="--pubkey file not found"):
        B.restore(cfg, other, force=True, pubkey=tmp_path / "nope.pem")


def test_no_pinned_key_refused(cfg: Settings, tmp_path: Path) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir, include_key=True)
    s2 = load_settings(data_dir=tmp_path / "dr", sql_backend="sqlite", llm_base_url="")
    with pytest.raises(B.BackupError, match="no signer public key to pin"):
        B.restore(s2, bdir)
    assert not Path(s2.sqlite_path).exists()  # type: ignore[arg-type]
    assert not Path(s2.signer_key_path).exists()  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name",
    ["../x.db", "sub/x.db", "sub\\x.db", "/etc/passwd", "C:\\x.db", "C:x.db", "..", ".", "", " ",
     "a..b.db", "x.db\0", 7, None],
)  # fmt: skip
def test_traversal_db_file_refused(cfg: Settings, tmp_path: Path, name: object) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir)
    (tmp_path / "x.db").write_bytes((bdir / "supervisor.db").read_bytes())
    m = json.loads((bdir / "manifest.json").read_text())
    m["db_file"] = name
    (bdir / "manifest.json").write_text(json.dumps(m))
    before = B.sha256_file(_live(cfg))
    with pytest.raises(B.BackupError):
        B.restore(cfg, bdir, force=True)
    assert B.sha256_file(_live(cfg)) == before
    _no_tmp(cfg)


def test_clean_roundtrip_moves_old_store_aside(cfg: Settings, tmp_path: Path) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir)
    old = B.sha256_file(_live(cfg))
    r = B.restore(cfg, bdir, force=True)
    assert r["verify_ok"] and r["warnings"] == [] and not r["key_change"]
    assert r["moved_aside"] and B.sha256_file(Path(r["moved_aside"])) == old
    want = json.loads((bdir / "manifest.json").read_text())["db_sha256"]
    assert B.sha256_file(_live(cfg)) == want
    _no_tmp(cfg)


def _fresh_target(tmp_path: Path) -> Settings:
    return load_settings(data_dir=tmp_path / "dr", sql_backend="sqlite", llm_base_url="")


def _pub(cfg: Settings, tmp_path: Path, name: str = "pub.pem") -> Path:
    pem = tmp_path / name
    build_signer(cfg).export_public_key(pem)
    return pem


def _keyfile(s: Settings) -> Path:
    return Path(s.signer_key_path)  # type: ignore[arg-type]


def test_matching_key_restored_on_fresh_target(cfg: Settings, tmp_path: Path) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir, include_key=True)
    s2 = _fresh_target(tmp_path)
    r = B.restore(s2, bdir, pubkey=_pub(cfg, tmp_path))
    assert r["key_restored"] and build_signer(s2).key_id == build_signer(cfg).key_id


def test_attacker_key_in_backup_not_installed(cfg: Settings, tmp_path: Path) -> None:
    other_cfg, _ = _foreign_backup(tmp_path)
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir)
    (bdir / B.KEY_NAME).write_bytes(_keyfile(other_cfg).read_bytes())
    s2 = _fresh_target(tmp_path)
    r = B.restore(s2, bdir, pubkey=_pub(cfg, tmp_path))
    assert not r["key_restored"] and not _keyfile(s2).exists()
    assert any("not the pinned key" in w for w in r["warnings"])


def test_allow_key_change_installs_only_chain_key(cfg: Settings, tmp_path: Path) -> None:
    other_cfg, _ = _foreign_backup(tmp_path)
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir)
    (bdir / B.KEY_NAME).write_bytes(_keyfile(other_cfg).read_bytes())
    s2 = _fresh_target(tmp_path)
    r = B.restore(s2, bdir, allow_key_change=True)
    assert not r["key_restored"] and any("not the chain key" in w for w in r["warnings"])
    assert not _keyfile(s2).exists()


def test_symlinked_key_file_not_followed(cfg: Settings, tmp_path: Path) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir)
    real = tmp_path / "real.pem"
    real.write_bytes(_keyfile(cfg).read_bytes())
    try:
        (bdir / B.KEY_NAME).symlink_to(real)
    except OSError:
        pytest.skip("symlinks not available")
    s2 = _fresh_target(tmp_path)
    r = B.restore(s2, bdir, pubkey=_pub(cfg, tmp_path))
    assert not r["key_restored"] and not _keyfile(s2).exists()
    assert any("not a regular file" in w for w in r["warnings"])


def test_symlinked_anchor_not_copied(cfg: Settings, tmp_path: Path) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir)
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    (bdir / B.ANCHOR_DIR).mkdir()
    (bdir / B.ANCHOR_DIR / "ok.json").write_text("{}")
    try:
        (bdir / B.ANCHOR_DIR / "evil.json").symlink_to(secret)
    except OSError:
        pytest.skip("symlinks not available")
    anch = tmp_path / "anch"
    s2 = _fresh_target(tmp_path).model_copy(update={"anchor_kind": "worm_dir", "anchor_path": anch})
    r = B.restore(s2, bdir, pubkey=_pub(cfg, tmp_path))
    assert r["anchors_restored"] == 1
    assert (anch / "ok.json").is_file() and not (anch / "evil.json").exists()
    assert any("evil.json" in w for w in r["warnings"])
