"""Clean-up audit D8 (owner decision): every CSV export uses one formula-injection rule. A cell
that starts with ``= + - @`` TAB or CR gets a leading quote, in the controls, risk, tasks and
inventory exports and in the compliance export of the console."""

from __future__ import annotations

import argparse
import csv
import io

import pytest

from supervisor.console.compliance_ux5 import csv_text
from supervisor.controls.harness_env import CtlEnv
from supervisor.controls.service import csv_cell as controls_cell
from supervisor.core.csvsafe import csv_cell
from supervisor.inventory.service import _cell as inventory_cell
from supervisor.jobs._cli_common import by_arg, cut, print_verdicts, say, write_baseline
from supervisor.risk.service import csv_cell as risk_cell

EVIL = ["=1+1", "+cmd", "-2", "@SUM(A1)", "\tTAB", "\rCR"]


def test_the_old_public_names_are_the_shared_rule() -> None:
    assert controls_cell is csv_cell and risk_cell is csv_cell and inventory_cell is csv_cell


def test_compliance_export_guards_every_cell() -> None:
    rows = [
        {
            "obligation_id": "OB-1",
            "instrument_number": "=cmd",
            "article_ref": "+1",
            "applies": True,
            "status": "gap",
            "summary_en": e,
            "status_reason": e,
        }
        for e in EVIL
    ]
    out = list(csv.reader(io.StringIO(csv_text(rows), newline="")))
    assert out[0][0] == "obligation_id" and len(out) == 1 + len(EVIL)
    for row, e in zip(out[1:], EVIL, strict=True):
        assert row[1] == "'=cmd" and row[2] == "'+1"
        assert row[5] == "'" + e and row[6] == "'" + e
        assert row[0] == "OB-1" and row[3] == "True"
    assert csv_text([]).splitlines() == [
        "obligation_id,instrument,article,applies,status,summary_en,status_reason"
    ]
    assert csv_text(rows).count("\r\n") >= len(rows) + 1  # the lines still end with CRLF


def test_control_and_risk_exports_guard_cells() -> None:
    env = CtlEnv()
    try:
        env.agent("pay")
        env.risk("=HYPERLINK(1)", "pay", [("rule", "PAY-02")])
        env.control("CTL-X", title="+evil", evidence=[("monitor", "oversight")])
        controls_csv, maps_csv = env.controls.export_csv()
        risks_csv, links_csv = env.svc.export_csv()
        assert "'+evil" in controls_csv and ",+evil" not in controls_csv
        assert "'=HYPERLINK(1)" in risks_csv
        assert maps_csv.startswith("control_id,") and links_csv.startswith("risk_id,")
    finally:
        env.close()


def test_cli_common_helpers(tmp_path, capsys) -> None:
    assert by_arg("alice.b@x") == "alice.b@x"
    for bad in ("", "a b", "x" * 65, "a;b"):
        with pytest.raises(argparse.ArgumentTypeError):
            by_arg(bad)
    assert cut("abcdef", 6) == "abcdef" and cut("abcdefg", 6) == "abcde~"
    say("café ok")
    assert capsys.readouterr().out == "caf? ok\n"
    assert print_verdicts({"a": "GO", "b": "NO-GO", "c": "NO-GO"}) == 2
    assert capsys.readouterr().out == "    a: GO\n    b: NO-GO\n    c: NO-GO\n"
    p = tmp_path / "baseline.json"
    write_baseline(p, {"b": 1, "a": {"z": [1, 2], "y": "x"}})
    assert (
        p.read_bytes()
        == b'{\n  "a": {\n    "y": "x",\n    "z": [\n      1,\n      2\n    ]\n  },\n  "b": 1\n}\n'
    )
