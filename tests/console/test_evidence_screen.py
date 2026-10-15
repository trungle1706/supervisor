"""WP12: Evidence screen - numbers, lanes as squares (cap 60 + "+N"), verify, export."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from supervisor.console.readmodels import LANE_CAP, lane_squares, square_kind
from supervisor.evidence.verify import verify_export

from .conftest import Console


def test_lane_squares_cap_and_hidden_count() -> None:
    entries = [{"seq": i, "record_type": "gate_decision"} for i in range(100, 160)]
    lane = lane_squares("agent:payments", 160, entries, set())
    assert len(lane["squares"]) == LANE_CAP == 60
    assert lane["hidden"] == 100
    assert lane["squares"][0]["seq"] == 100 and lane["squares"][-1]["seq"] == 159
    small = lane_squares(
        "agent:x", 3, [{"seq": 2, "record_type": "case"}, {"seq": 0}, {"seq": 1}], set()
    )
    assert small["hidden"] == 0 and [s["seq"] for s in small["squares"]] == [0, 1, 2]
    assert small["squares"][-1]["kind"] == "stop"


def test_square_kinds() -> None:
    assert square_kind("root", "root_commit", True) == "root signed"
    assert square_kind("root", "root_commit", False) == "root"
    assert square_kind("agent:a", "gate_state_change", False) == "state"
    assert square_kind("agent:a", "case_event", False) == "human"
    assert square_kind("agent:a", "gate_decision", False) == ""


def test_evidence_screen_renders_real_chain(console: Console) -> None:
    r = console.get("/console/evidence")
    assert r.status_code == 200, r.text
    heads = console.runtime.chain.heads()
    total = sum(h.seq + 1 for h in heads.values())
    assert f'data-entries="{total}"' in r.text
    for lane, head in heads.items():
        m = re.search(
            rf'data-lane="{re.escape(lane)}" data-squares="(\d+)" data-hidden="(\d+)"', r.text
        )
        assert m, lane
        shown, hidden = int(m.group(1)), int(m.group(2))
        assert shown == min(head.seq + 1, LANE_CAP) and shown + hidden == head.seq + 1
    assert 'class="b root signed"' in r.text  # signed roots in gold
    assert "dev key" in r.text  # laptop signer is labelled
    assert "python -m supervisor.evidence.verify" in r.text and 'id="offline-cmd"' in r.text
    assert "Verify now" in r.text and "Export chain" in r.text and "Build audit pack" in r.text
    assert console.get("/console/export").url.path == "/console/evidence"


def test_verify_and_export_chain(console: Console, tmp_path: Path) -> None:
    v = console.post("/console/chain/verify")
    assert v.status_code == 200 and 'data-verify="ok"' in v.text
    card = console.get("/console/").text.split('data-num="chain"')[1][:1500]
    assert "verified " in card and "not verified" not in card  # the Overview card follows
    e = console.post("/console/chain/export", {}, user="auditor.dung")
    assert e.status_code == 200 and 'data-verify="ok"' in e.text, e.text
    name = re.findall(r"/console/exports/(chain-export-[^\"]+\.zip)", e.text)[0]
    dl = console.get(f"/console/exports/{name}", user="auditor.dung")
    assert dl.status_code == 200
    (tmp_path / name).write_bytes(dl.content)
    with zipfile.ZipFile(tmp_path / name) as zf:
        zf.extractall(tmp_path / "x")
    report = verify_export(tmp_path / "x" / name.removesuffix(".zip") / "chain")
    assert report.failures == 0
    # recorded on the chain, with who asked
    rows = console.ctx.tables.query("chain_entry", {"record_type": "chain_export_built"})
    assert rows
    denied = console.post("/console/chain/export", {}, user="payops-lead@example.invalid")
    assert denied.status_code == 400 and "needs role" in denied.text
