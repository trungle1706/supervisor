"""Each semantic rule has a broken fixture that must fail naming the file and the id."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pytest

from supervisor.regkb import SchemaError, SemanticError, load_kb
from supervisor.regkb.errors import RegKBError
from tests.regkb.conftest import SRC, instrument, kb_file, obligation, write_file

OID = "VN-TEST-2026-A1-01"


def _load_bad(root: Path, exc: type[RegKBError] = SemanticError) -> RegKBError:
    with pytest.raises(exc) as info:
        load_kb(root)
    return info.value


def _replace(
    root: Path, inst: dict[str, Any] | None = None, obs: list[dict[str, Any]] | None = None
):
    write_file(root / "vn", "test.yaml", kb_file(inst, obs))


def test_valid_fixture_loads(root: Path) -> None:
    kb = load_kb(root)
    assert OID in kb.obligations
    o = kb.get(OID)
    assert o.instrument_id == "VN-TEST-2026" and o.instrument_kind == "law" and o.binding is True
    assert len(kb.version) == 64


def test_header_merge_and_overrides(root: Path) -> None:
    over = {
        "status": "superseded",
        "dates": {
            "effective": {"date": None, "source": "https://e.invalid/x", "verification": "ASSUMED"}
        },
    }
    _replace(root, obs=[obligation(**over)])
    o = load_kb(root).get(OID)
    assert o.status == "superseded"
    assert o.dates.effective is not None and o.dates.effective.date is None
    assert o.issuer == "Test Issuer" and o.title_vi == "Luat thu nghiem"


def test_no_source(root: Path) -> None:
    _replace(root, obs=[obligation(sources=[])])
    err = _load_bad(root, SchemaError)
    assert any("test.yaml" in e and OID in e and "sources" in e for e in err.errors)


def test_source_without_fetched_at(root: Path) -> None:
    bad = {k: v for k, v in SRC.items() if k != "fetched_at"}
    _replace(root, obs=[obligation(sources=[bad])])
    err = _load_bad(root, SchemaError)
    assert any("fetched_at" in e and OID in e for e in err.errors)


def test_unknown_duty(root: Path) -> None:
    _replace(root, obs=[obligation(duties=["no_such_duty"])])
    err = _load_bad(root)
    assert any("test.yaml" in e and OID in e and "no_such_duty" in e for e in err.errors)


def test_unresolved_control(root: Path) -> None:
    ctl = [{"kind": "rule", "id": "NOPE-99", "coverage": "full"}]
    _replace(root, obs=[obligation(control_mapping=ctl)])
    err = _load_bad(root)
    assert any(OID in e and "rule:NOPE-99" in e for e in err.errors)


def test_control_id_of_wrong_kind(root: Path) -> None:
    ctl = [{"kind": "monitor", "id": "pii_masking", "coverage": "full"}]
    _replace(root, obs=[obligation(control_mapping=ctl)])
    assert any("monitor:pii_masking" in e for e in _load_bad(root).errors)


def test_draft_instrument_in_force(root: Path) -> None:
    _replace(root, inst=instrument(kind="draft", status="in_force"))
    err = _load_bad(root)
    assert any("test.yaml" in e and "VN-TEST-2026" in e and "draft" in e for e in err.errors)
    assert any(OID in e and "in_force" in e for e in err.errors)


def test_draft_status_obligation_override_in_force(root: Path) -> None:
    _replace(
        root, inst=instrument(status="draft", binding=False), obs=[obligation(status="in_force")]
    )
    assert any(OID in e and "in_force" in e for e in _load_bad(root).errors)


def test_reference_must_not_be_binding(root: Path) -> None:
    _replace(root, inst=instrument(status="reference", binding=True))
    assert any("binding false" in e for e in _load_bad(root).errors)


def test_draft_must_not_be_binding(root: Path) -> None:
    _replace(root, inst=instrument(kind="draft", status="draft", binding=True))
    assert any("binding false" in e for e in _load_bad(root).errors)


def test_duplicate_obligation_id(root: Path) -> None:
    _replace(root, obs=[obligation(), obligation()])
    assert any(OID in e and "duplicate" in e for e in _load_bad(root).errors)


def test_duplicate_instrument_id_across_files(root: Path) -> None:
    write_file(root / "vn", "other.yaml", kb_file(obs=[obligation("VN-TEST-2026-A2-01")]))
    assert any("duplicate instrument" in e for e in _load_bad(root).errors)


def test_obligation_id_prefix(root: Path) -> None:
    _replace(root, obs=[obligation("VN-OTHER-A1-01")])
    assert any(
        "VN-OTHER-A1-01" in e and "must start with VN-TEST-2026-" in e
        for e in _load_bad(root).errors
    )


def test_verified_primary_without_primary_source(root: Path) -> None:
    sec = dict(SRC, kind="secondary")
    _replace(root, obs=[obligation(sources=[sec])])
    assert any(OID in e and "kind primary" in e for e in _load_bad(root).errors)


def test_verified_primary_vn_needs_text_vi(root: Path) -> None:
    no_text = obligation()
    del no_text["text_vi"]
    _replace(root, obs=[no_text])
    assert any(OID in e and "text_vi" in e for e in _load_bad(root).errors)
    # intl does not need it
    intl = instrument(
        "INTL-TESTFW", jurisdiction="INTL", kind="standard", status="reference", binding=False
    )
    ob = obligation("INTL-TESTFW-G1-01")
    del ob["text_vi"]
    write_file(root / "intl", "fw.yaml", kb_file(intl, [ob]))
    _replace(root)
    assert "INTL-TESTFW-G1-01" in load_kb(root).obligations


def test_unquoted_date(root: Path) -> None:
    path = root / "vn" / "test.yaml"
    path.write_text(path.read_text("utf-8").replace("'2026-10-15'", "2026-10-15"), "utf-8")
    err = _load_bad(root, SchemaError)
    assert any("test.yaml" in e and "quote dates" in e for e in err.errors)


def test_schema_error_names_file_and_collects_all(root: Path) -> None:
    _replace(
        root, obs=[obligation(confidence="great"), obligation("VN-TEST-2026-A2-01", duties=[])]
    )
    err = _load_bad(root, SchemaError)
    assert len(err.errors) >= 2
    assert all("test.yaml" in e for e in err.errors)


def test_invalid_yaml(root: Path) -> None:
    (root / "vn" / "broken.yaml").write_text("a: [unclosed", "utf-8")
    assert any("broken.yaml" in e for e in _load_bad(root, SchemaError).errors)


def _with_source(root: Path, tmp_path: Path, content: bytes, sha: str | None) -> None:
    rel = "regulations/sources/VN-TEST-2026/doc.txt"
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    src = dict(SRC, local_path=rel)
    if sha:
        src["sha256"] = sha
    _replace(root, obs=[obligation(sources=[src])])


def test_local_path_sha_ok(root: Path, tmp_path: Path) -> None:
    _with_source(root, tmp_path, b"text", hashlib.sha256(b"text").hexdigest())
    assert OID in load_kb(root).obligations


def test_local_path_sha_mismatch(root: Path, tmp_path: Path) -> None:
    _with_source(root, tmp_path, b"text", "0" * 64)
    err = _load_bad(root)
    assert any(OID in e and "sha256" in e and "test.yaml" in e for e in err.errors)


def test_local_path_missing(root: Path) -> None:
    src = dict(SRC, local_path="regulations/sources/VN-TEST-2026/none.txt")
    _replace(root, obs=[obligation(sources=[src])])
    assert any("does not exist" in e for e in _load_bad(root).errors)


def test_local_path_escape(root: Path) -> None:
    src = dict(SRC, local_path="regulations/sources/../../escape.txt")
    _replace(root, obs=[obligation(sources=[src])])
    assert any(
        "leaves the repository" in e or "does not exist" in e for e in _load_bad(root).errors
    )


def test_wrong_directory_prefix(root: Path) -> None:
    write_file(
        root / "intl", "x.yaml", kb_file(instrument("VN-WRONG"), [obligation("VN-WRONG-A1-01")])
    )
    assert any("must start with INTL-" in e for e in _load_bad(root).errors)


def test_assumed_without_notes_warns(root: Path) -> None:
    _replace(root, obs=[obligation(verification="ASSUMED")])
    assert any(OID in w for w in load_kb(root).warnings)


def test_unknown_id_lookup(root: Path) -> None:
    from supervisor.regkb import UnknownObligationError

    with pytest.raises(UnknownObligationError):
        load_kb(root).get("VN-NOPE-A1-01")


def test_draft_instrument_issued(root: Path) -> None:
    _replace(root, inst=instrument(kind="draft", status="issued", binding=False))
    assert any("VN-TEST-2026" in e and "issued" in e for e in _load_bad(root).errors)


def test_issued_binding_is_fine(root: Path) -> None:
    _replace(root, inst=instrument(status="issued"))
    assert load_kb(root).get(OID).status == "issued"


def _eff(date: str) -> dict[str, Any]:
    return {"effective": {"date": date, "source": "https://e.invalid/x", "verification": "ASSUMED"}}


def test_in_force_before_effective_date_fails(root: Path, monkeypatch) -> None:
    monkeypatch.setattr("supervisor.regkb.loader._today", lambda: dt.date(2026, 10, 15))
    _replace(root, inst=instrument(status="in_force", dates=_eff("2026-11-15")))
    err = _load_bad(root)
    assert any("VN-TEST-2026" in e and "effective date 2026-11-15" in e for e in err.errors)


def test_issued_warns_once_effective_date_passed(root: Path, monkeypatch) -> None:
    _replace(root, inst=instrument(status="issued", dates=_eff("2026-11-15")))
    monkeypatch.setattr("supervisor.regkb.loader._today", lambda: dt.date(2026, 10, 15))
    assert not any("has passed" in w for w in load_kb(root).warnings)
    monkeypatch.setattr("supervisor.regkb.loader._today", lambda: dt.date(2026, 12, 1))
    assert any("has passed" in w for w in load_kb(root).warnings)
