"""Internal (bank) rules merge into the matrix only when asked (WP14).

The CLI side is covered in test_cli.py. Not legal advice.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from supervisor.advisory.compliance import demo_product
from supervisor.advisory.compliance.matrix import build_matrix
from supervisor.regkb import load_kb
from supervisor.regkb.loader import REPO_ROOT

EXAMPLE = REPO_ROOT / "regulations" / "internal" / "example-ai-use-policy.yaml.example"
KW = {"as_of": "2026-10-15", "generated_at": "2026-10-15T00:00:00Z", "chat": None}


def _rows(m):
    return [[r.obligation_id, r.applies, r.status] for r in m.rows]


def test_internal_rows_added(tmp_path: Path):
    shutil.copy(EXAMPLE, tmp_path / "example-ai-use-policy.yaml")
    kb = load_kb(internal_dir=tmp_path)
    m = build_matrix(kb, demo_product("payments"), **KW)
    int_rows = [r for r in m.rows if r.obligation_id.startswith("INT-EXAMPLE-AIPOL")]
    assert int_rows
    assert m.header.internal_rules is True
    assert "INT-EXAMPLE-AIPOL" in m.header.internal_instruments
    assert any(r.applies == "yes" for r in int_rows)
    assert all(r.status for r in int_rows)


def test_internal_off_path_unchanged(kb):
    m = build_matrix(load_kb(), demo_product("payments"), **KW)
    assert m.header.internal_rules is False
    assert not any(r.obligation_id.startswith("INT-") for r in m.rows)
    base = build_matrix(kb, demo_product("payments"), **KW)
    assert _rows(m) == _rows(base)
