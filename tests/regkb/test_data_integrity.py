"""Checks over the real knowledge base (whatever valid files exist)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from supervisor.regkb import KnowledgeBase, load_kb
from tests.conftest import REPO_ROOT

REG = REPO_ROOT / "regulations"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return load_kb()


def _controls() -> dict:
    return yaml.safe_load((REG / "schema" / "controls.yaml").read_text(encoding="utf-8"))


def test_every_obligation_has_sources_and_verification(kb: KnowledgeBase) -> None:
    for o in kb.obligations.values():
        assert o.sources, o.id
        assert all(s.url and s.fetched_at for s in o.sources), o.id
        assert o.verification in {"VERIFIED_PRIMARY", "VERIFIED_SECONDARY", "ASSUMED"}, o.id


def test_ids_unique_and_prefixed(kb: KnowledgeBase) -> None:
    ids = [i.id for i in kb.instruments]
    assert len(ids) == len(set(ids))
    for o in kb.obligations.values():
        assert o.id.startswith(o.instrument_id + "-")


def test_control_mapping_resolves(kb: KnowledgeBase) -> None:
    controls = _controls()
    manifests = {
        yaml.safe_load(p.read_text(encoding="utf-8"))["id"]
        for p in (REPO_ROOT / "src/supervisor/catalogue/manifests").glob("*.yaml")
    }
    rules = {
        r["id"]
        for r in yaml.safe_load((REPO_ROOT / "policies/baseline.yaml").read_text("utf-8"))["rules"]
    }
    routes = (REPO_ROOT / "src/supervisor/console/routes.py").read_text(encoding="utf-8")
    tables = yaml.safe_load((REPO_ROOT / "schema/model.yaml").read_text("utf-8"))["tables"]
    for o in kb.obligations.values():
        for c in o.control_mapping:
            where = f"{o.id} {c.kind}:{c.id}"
            if c.kind == "catalogue":
                assert c.id in manifests, where
            elif c.kind == "rule":
                assert c.id in rules, where
            elif c.kind == "monitor":
                module = controls["monitors"][c.id]["module"]
                name = module.rsplit(".", 1)[1]
                assert (REPO_ROOT / "src/supervisor/monitors" / f"{name}.py").is_file(), where
            elif c.kind == "console":
                path = controls["console"][c.id]["path"]
                pattern = rf'@router\.(get|post)\(\s*"{re.escape(path)}"'
                assert re.search(pattern, routes), where
            elif c.kind == "evidence":
                item = controls["evidence"][c.id]
                if "table" in item:
                    assert item["table"] in tables, where
                else:
                    rel = Path("src", *item["module"].split("."))
                    assert (REPO_ROOT / rel).with_suffix(".py").is_file() or (
                        REPO_ROOT / rel / "__init__.py"
                    ).is_file(), where
            else:
                assert c.id in controls["process"], where


def test_dates_are_iso(kb: KnowledgeBase) -> None:
    def facts(dates):
        for f in (
            dates.issued,
            dates.effective,
            dates.compliance_deadline,
            *(dates.milestones or ()),
        ):
            if f is not None:
                yield f

    for i in kb.instruments:
        assert ISO.match(i.last_checked), i.id
        assert all(f.date is None or ISO.match(f.date) for f in facts(i.dates)), i.id
    for o in kb.obligations.values():
        assert all(ISO.match(s.fetched_at) for s in o.sources), o.id
        assert all(f.date is None or ISO.match(f.date) for f in facts(o.dates)), o.id


def test_status_rules(kb: KnowledgeBase) -> None:
    for i in kb.instruments:
        if i.kind == "draft" or i.status == "draft":
            assert i.status not in ("in_force", "issued"), i.id
            assert not i.binding, i.id
        if i.status == "reference":
            assert not i.binding, i.id
    for o in kb.obligations.values():
        if o.status in ("reference", "draft"):
            assert not o.binding, o.id
        if o.instrument_kind == "draft":
            assert o.status not in ("in_force", "issued"), o.id


def test_intl_files_are_not_binding(kb: KnowledgeBase) -> None:
    for i in kb.instruments:
        if i.file.startswith("regulations/intl/"):
            assert i.binding is False, i.id


def test_duties_known(kb: KnowledgeBase) -> None:
    known = set(yaml.safe_load((REG / "schema" / "duties.yaml").read_text("utf-8"))["duties"])
    for o in kb.obligations.values():
        assert set(o.duties) <= known, o.id


def test_version_hash_stable_and_order_independent(kb: KnowledgeBase, tmp_path: Path) -> None:
    assert load_kb().version == kb.version
    copy_root = tmp_path / "regulations"
    for sub in ("vn", "intl"):
        (copy_root / sub).mkdir(parents=True)
        files = sorted((REG / sub).glob("*.yaml"), reverse=True)
        for n, f in enumerate(files):
            # different names -> different read order; the data is unchanged
            shutil.copy(f, copy_root / sub / f"{len(files) - n:03d}-{f.name}")
    # local_path in sources is relative to the repo root: link the sources folder
    if (REG / "sources").is_dir():
        shutil.copytree(REG / "sources", copy_root / "sources")
    assert load_kb(copy_root).version == kb.version
