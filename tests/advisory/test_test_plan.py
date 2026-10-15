"""WP15: the test plan names WP17 assurance packs per dimension (read as data)."""

from __future__ import annotations

from pathlib import Path

from supervisor.advisory.integration.advise import _PACK_DIMENSION, assurance_packs
from supervisor.advisory.integration.models import AssuranceItem

DIMENSIONS = AssuranceItem.model_fields["dimension"].annotation.__args__  # type: ignore[union-attr]


def test_every_dimension_has_agent_packs() -> None:
    packs = assurance_packs()
    for dim in DIMENSIONS:
        assert packs.get(_PACK_DIMENSION.get(dim, dim)), dim


def test_missing_packs_dir_gives_no_packs(tmp_path: Path) -> None:
    assert assurance_packs(tmp_path / "absent") == {}


def test_non_agent_and_broken_packs_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("id: a\ndimension: accuracy\ntargets: [agent]\n")
    (tmp_path / "j.yaml").write_text("id: j\ndimension: accuracy\ntargets: [judge]\n")
    (tmp_path / "bad.yaml").write_text("id: [\n")
    assert assurance_packs(tmp_path) == {"accuracy": ["a"]}
