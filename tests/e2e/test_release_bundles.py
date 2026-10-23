"""WP-P1: `release --bundles` builds the laptop and Databricks bundles from a clean clone."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from supervisor import release, sandbox
from tests.conftest import REPO_ROOT


def _git(cwd: Path, *args: str) -> None:
    res = sandbox.run(
        ["git", "-c", "user.name=wp-p1-test", "-c", "user.email=p1@example.invalid", *args],
        cwd=cwd,
        timeout_s=120,
    )
    assert res.ok, res.stderr


@pytest.fixture(scope="module")
def bundles(tmp_path_factory: pytest.TempPathFactory) -> release.BundleReport:
    base = tmp_path_factory.mktemp("bundles")
    _git(base, "clone", "--quiet", "--no-local", str(REPO_ROOT), "clone")
    _git(base / "clone", "tag", "v0.0.0-test")
    lines: list[str] = []
    rep = release.build_bundles(
        base / "out", repo=base / "clone", ref="v0.0.0-test", echo=lines.append
    )
    assert rep.ok, "\n".join(lines)
    return rep


def test_two_folders_with_the_expected_files(bundles: release.BundleReport) -> None:
    lap, dbx = bundles.folders["laptop"], bundles.folders["databricks"]
    assert lap.name == "laptop" and dbx.name == "databricks"
    lap_names = {p.name for p in lap.iterdir()}
    dbx_names = {p.name for p in dbx.iterdir()}
    assert {
        "requirements.txt",
        ".env.laptop.example",
        "LAUNCH_LAPTOP.md",
        "SHA256SUMS.txt",
    } <= lap_names
    assert {"app.yaml", "databricks.yml", "requirements.txt", "LAUNCH_DATABRICKS.md"} <= dbx_names
    assert any(n.startswith("supervisor-0.") and n.endswith(".zip") for n in lap_names)
    assert any(n.startswith("supervisor-databricks-") and n.endswith(".zip") for n in dbx_names)


def test_zips_are_clean_and_differ_by_target(bundles: release.BundleReport) -> None:
    for target, zpath in bundles.zips.items():
        assert release.leak_sweep(zpath) == []
        with zipfile.ZipFile(zpath) as zf:
            names = set(zf.namelist())
            handoff = zf.read("supervisor/HANDOFF.md").decode()
        assert "supervisor/.env.laptop.example" in names
        assert "supervisor/tools/smoke_launch.py" in names
        assert "supervisor/docs/deploy/LAUNCH_LAPTOP.md" in names
        assert not any(n.endswith(".env") or "/.git/" in n for n in names)
        if target == "laptop":
            assert "supervisor/uv.toml" in names
            assert "LAUNCH_LAPTOP.md" in handoff
        else:
            assert "supervisor/uv.toml" not in names
            assert "LAUNCH_DATABRICKS.md" in handoff


def test_loose_files_match_the_zip_and_the_sums(bundles: release.BundleReport) -> None:
    for target, folder in bundles.folders.items():
        sums = dict(
            reversed(line.split("  ", 1))
            for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
        )
        files = [p for p in folder.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt"]
        assert set(sums) == {p.name for p in files}
        for p in files:
            assert hashlib.sha256(p.read_bytes()).hexdigest() == sums[p.name], p.name
        with zipfile.ZipFile(bundles.zips[target]) as zf:
            req = zf.read("supervisor/requirements.txt")
        assert (folder / "requirements.txt").read_bytes() == req
        assert b"pypdf==" in req


def test_databricks_files_keep_placeholders(bundles: release.BundleReport) -> None:
    dbx = bundles.folders["databricks"]
    for name in ("app.yaml", "databricks.yml"):
        text = (dbx / name).read_text(encoding="utf-8")
        assert "FILL-ME" in text
        assert "dbc-" not in text


def test_bad_target_is_refused(tmp_path: Path) -> None:
    with pytest.raises(release.ReleaseError):
        release.build_release(tmp_path, repo=REPO_ROOT, target="mainframe")
