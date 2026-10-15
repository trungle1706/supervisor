from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from supervisor.regkb import SemanticError, load_kb
from supervisor.regkb.cli import main
from tests.conftest import REPO_ROOT
from tests.regkb.conftest import instrument, kb_file, obligation, write_file

EXAMPLE = REPO_ROOT / "regulations" / "internal" / "example-ai-use-policy.yaml.example"


@pytest.fixture
def internal(tmp_path: Path) -> Path:
    d = tmp_path / "internal"
    d.mkdir()
    shutil.copy(EXAMPLE, d / "example-ai-use-policy.yaml")
    return d


def test_default_off(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REGKB_INTERNAL_DIR", raising=False)
    kb = load_kb(root)
    assert not any(i.id.startswith("INT-") for i in kb.instruments)


def test_repo_internal_dir_loads_nothing_by_default() -> None:
    kb = load_kb(internal_dir=REPO_ROOT / "regulations" / "internal")
    assert not any(i.id.startswith("INT-") for i in kb.instruments)  # only *.yaml.example there


def test_example_loads_and_merges(root: Path, internal: Path) -> None:
    kb = load_kb(root, internal)
    assert len(kb.obligations_of("INT-EXAMPLE-AIPOL")) == 3
    o = kb.get("INT-EXAMPLE-AIPOL-S4-01")
    assert o.instrument_kind == "internal" and o.verification == "VERIFIED_PRIMARY"
    assert "VN-TEST-2026-A1-01" in kb.obligations  # merged with the public data
    assert kb.version != load_kb(root).version


def test_int_prefix_enforced(root: Path, tmp_path: Path) -> None:
    d = tmp_path / "internal"
    inst = instrument("VN-SNEAKY", kind="internal")
    write_file(d, "x.yaml", kb_file(inst, [obligation("VN-SNEAKY-S1-01")]))
    with pytest.raises(SemanticError) as info:
        load_kb(root, d)
    assert any("must start with INT-" in e and "x.yaml" in e for e in info.value.errors)


def test_kind_internal_only_in_internal_dir(root: Path) -> None:
    write_file(
        root / "vn",
        "t2.yaml",
        kb_file(instrument("VN-OTHER", kind="internal"), [obligation("VN-OTHER-A1-01")]),
    )
    with pytest.raises(SemanticError) as info:
        load_kb(root)
    assert any("kind internal" in e for e in info.value.errors)


def test_cli_reads_env(root: Path, internal: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("REGKB_INTERNAL_DIR", str(internal))
    assert main(["--root", str(root), "list"]) == 0
    assert "INT-EXAMPLE-AIPOL-S4-01" in capsys.readouterr().out
    monkeypatch.setenv("REGKB_INTERNAL_DIR", "")
    assert main(["--root", str(root), "list"]) == 0
    assert "INT-EXAMPLE" not in capsys.readouterr().out
