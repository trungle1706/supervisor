"""WP-W0: regulations/REGULATOR_MAP.md agrees with the files.

* Every instrument in the map that is marked `stored: yes` has a YAML file and a
  `regulations/sources/<id>/` folder whose stored files all have sidecars; `yaml-only` has the YAML.
* Every instrument file under regulations/vn and regulations/intl is listed in the map (no
  silent additions).
* The obligation count in the map equals the count in the file.
* Missing rows have a reference `M-nn` and say what to do.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
MAP = REPO / "regulations" / "REGULATOR_MAP.md"
SOURCES = REPO / "regulations" / "sources"

_ROW = re.compile(r"^\|\s*`((?:VN|INTL)-[A-Z0-9-]+)`\s*\|")


def _instrument_files() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sub in ("vn", "intl"):
        for f in sorted((REPO / "regulations" / sub).glob("*.yaml")):
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            out[doc["instrument"]["id"]] = {"file": f, "n": len(doc["obligations"])}
    return out


def _map_rows() -> list[dict[str, str]]:
    rows = []
    for line in MAP.read_text(encoding="utf-8").splitlines():
        if not _ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 12, f"row has {len(cells)} cells: {line[:80]}"
        rows.append(
            {
                "id": cells[0].strip("`"),
                "stored": cells[8],
                "verified": cells[9],
                "n": cells[10],
            }
        )
    return rows


FILES = _instrument_files()
ROWS = _map_rows()


def test_map_exists_and_has_the_banner() -> None:
    text = MAP.read_text(encoding="utf-8")
    assert "Not legal advice. Bank counsel must confirm." in text
    assert "## Missing, open or checked-and-closed" in text


def test_every_instrument_file_is_in_the_map() -> None:
    listed = {r["id"] for r in ROWS}
    assert set(FILES) - listed == set(), "instrument files missing from REGULATOR_MAP.md"
    assert listed - set(FILES) == set(), "map rows with no instrument file"
    assert len(ROWS) == len(listed), "an instrument is listed twice"


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_stored_marker_matches_the_files(row: dict[str, str]) -> None:
    iid = row["id"]
    assert row["stored"] in {"yes", "yaml-only"}, f"{iid}: stored must be yes or yaml-only"
    assert FILES[iid]["file"].is_file()
    folder = SOURCES / iid
    if row["stored"] == "yes":
        assert folder.is_dir(), f"{iid}: marked stored but no sources folder"
        stored = [p for p in folder.iterdir() if p.is_file() and not p.name.endswith(".meta.json")]
        assert stored, f"{iid}: sources folder is empty"
        for p in stored:
            assert p.with_name(p.stem + ".meta.json").is_file(), f"{iid}: no sidecar for {p.name}"
    else:
        assert not (folder.is_dir() and any(folder.iterdir())), (
            f"{iid}: has stored files but the map says yaml-only"
        )


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_obligation_count_matches(row: dict[str, str]) -> None:
    assert row["n"] == str(FILES[row["id"]]["n"]), f"{row['id']}: count in the map is stale"


def test_missing_rows_have_reference_and_action() -> None:
    text = MAP.read_text(encoding="utf-8")
    section = text.split("## Missing, open or checked-and-closed", 1)[1].split("\n## ", 1)[0]
    rows = [ln for ln in section.splitlines() if re.match(r"^\|\s*M-\d\d\s*\|", ln)]
    assert len(rows) >= 10
    refs = []
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        assert len(cells) == 11, ln[:80]
        refs.append(cells[0])
        assert cells[10], f"{cells[0]}: gap or action is empty"
        assert cells[8].startswith("no"), f"{cells[0]}: a missing row must say stored no"
    assert len(refs) == len(set(refs))
