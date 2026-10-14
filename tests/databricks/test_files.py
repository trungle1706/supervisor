"""Files API helper: write-once Volume files, UcVolumeAnchor, recorder spool on a Volume."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.config import load_settings
from supervisor.databricks.files import (
    VolumeError,
    VolumeFiles,
    VolumeSpool,
    is_volume_path,
    make_spool,
    staged_spool,
    volume_root,
)
from supervisor.evidence.anchor import AnchorError, UcVolumeAnchor
from supervisor.recorder.sink import Spool
from tests.databricks.fakes import FakeFiles

ROOT = "/Volumes/cat/sch/vol"


def test_put_new_refuses_overwrite_and_reads_back() -> None:
    vf = VolumeFiles(FakeFiles())
    vf.put_new(f"{ROOT}/a.json", b"1")
    assert vf.read(f"{ROOT}/a.json") == b"1"
    with pytest.raises(VolumeError, match="already exists"):
        vf.put_new(f"{ROOT}/a.json", b"2")
    assert vf.read(f"{ROOT}/a.json") == b"1"
    assert vf.list_names(ROOT) == ["a.json"] and vf.list_names(f"{ROOT}/none") == []
    vf.delete(f"{ROOT}/a.json")
    vf.delete(f"{ROOT}/a.json")  # missing is fine
    assert not vf.exists(f"{ROOT}/a.json")


def test_permission_error_names_path_and_fix() -> None:
    fake = FakeFiles()
    fake.deny.add(ROOT)
    with pytest.raises(VolumeError) as e:
        VolumeFiles(fake).put_new(f"{ROOT}/x", b"1")
    assert ROOT in str(e.value) and "WRITE VOLUME" in str(e.value)


def test_uc_volume_anchor_through_helper() -> None:
    fake = FakeFiles()
    anchor = UcVolumeAnchor(VolumeFiles(fake), f"{ROOT}/anchors")
    receipt = anchor.put("r1.json", b"{}")
    assert receipt.startswith("sha256=") and f"{ROOT}/anchors/r1.json" in receipt
    with pytest.raises(AnchorError, match="already exists"):
        anchor.put("r1.json", b"{}")
    # a race (exists check passed, upload refused) is still refused
    fake.store[f"{ROOT}/anchors/r2.json"] = b"x"
    with pytest.raises(AnchorError):
        anchor.put("r2.json", b"{}")


def test_build_anchor_uses_files_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.databricks import files as files_mod
    from supervisor.evidence.anchor import build_anchor

    fake = FakeFiles()
    monkeypatch.setattr(files_mod, "make_files", lambda settings, client=None: VolumeFiles(fake))
    a = build_anchor(load_settings(anchor_kind="uc_volume", anchor_path=f"{ROOT}/anchors"))
    assert isinstance(a, UcVolumeAnchor) and isinstance(a.files, VolumeFiles)


def test_volume_paths() -> None:
    assert is_volume_path("/Volumes/a/b/c/d") and not is_volume_path("/tmp/x")
    assert volume_root("/Volumes/a/b/c/d/e") == "/Volumes/a/b/c"
    with pytest.raises(VolumeError):
        volume_root("/Volumes/a/b")


def test_make_spool_local_vs_volume(tmp_path: Path) -> None:
    local = make_spool(load_settings(recorder_spool_dir=tmp_path / "sp"))
    assert type(local) is Spool
    vol = make_spool(load_settings(recorder_spool_dir=f"{ROOT}/spool"), VolumeFiles(FakeFiles()))
    assert isinstance(vol, VolumeSpool)


def test_volume_spool_put_pull_ack(tmp_path: Path) -> None:
    fake = FakeFiles()
    spool = VolumeSpool(VolumeFiles(fake), f"{ROOT}/spool")
    spool.put_otlp({"resourceSpans": []})
    spool.put({"kind": "rows", "agent_event": [], "agent_event_raw": []})
    names = sorted(p for p in fake.store if p.startswith(f"{ROOT}/spool/"))
    assert len(names) == 2 and all(n.endswith(".jsonl") for n in names)
    local = tmp_path / "stage"
    pulled = spool.pull(local)
    assert len(pulled) == 2 and spool.pull(local) == []  # not pulled twice
    # ingest marks one done; ack deletes only that remote object
    first = sorted(local.glob("*.jsonl"))[0]
    first.replace(first.with_name(first.stem + ".done"))
    removed = spool.ack(local)
    assert removed == [first.name] and len([p for p in fake.store if "/spool/" in p]) == 1


def test_staged_spool_local_dir_passthrough(tmp_path: Path) -> None:
    with staged_spool(load_settings(), tmp_path) as d:
        assert d == tmp_path
    with staged_spool(load_settings(), None) as d:
        assert d is None


def test_ingest_drains_volume_spool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spool on a Volume (no local mount) -> ingest stages it, writes rows, deletes remote."""
    from supervisor.adapters.factory import build_adapters
    from supervisor.databricks import files as files_mod
    from supervisor.jobs import bootstrap_schema, ingest

    fake = FakeFiles()
    monkeypatch.setattr(files_mod, "make_files", lambda settings, client=None: VolumeFiles(fake))
    monkeypatch.setattr(files_mod.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    settings = load_settings(data_dir=tmp_path / "d", recorder_spool_dir=f"{ROOT}/spool")
    adapters = build_adapters(settings)
    bootstrap_schema.run(settings, adapters)
    spool = make_spool(settings)
    assert isinstance(spool, VolumeSpool)
    spool.put({"kind": "rows", "agent_event": [], "agent_event_raw": []})
    counts = ingest.run(settings, adapters)
    assert counts["files"] == 1
    assert [p for p in fake.store if "/spool/" in p] == []
