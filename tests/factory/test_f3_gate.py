"""WP-F3: the test gate (layers 1 to 3), the sample batch, the signed report, golden gate cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.evidence import verify as ev
from supervisor.factory import caps, gate, golden
from tests.factory.f3_helpers import FakeChat, create_agent, golden_cases, load_golden, make_env


@pytest.fixture
def env(adapters: Any, sink: Any, tmp_path: Path) -> gate.GateEnv:
    return make_env(adapters, sink, FakeChat(), tmp_path)


def test_full_gate_passes_and_marks_tested(env: gate.GateEnv, sink: Any) -> None:
    row = create_agent(env)
    load_golden(env, row)
    run = gate.start(env, "mr-agent", "0.1", "full", "reviewer.an", background=False)
    assert run["status"] == "done", run
    assert run["layer1"]["ok"], run["layer1"]
    assert run["layer2"]["calibration"]["kappa_hundredths"] == 100
    assert run["verdict"] == "pass"
    assert env.store.get("mr-agent", "0.1")["state"] == "tested"
    assert run["layer3"]["status"] == "no_data"
    # signed report verifies offline
    path = gate.gate_dir(env.data_dir, "mr-agent", run["run_id"]) / "report.json"
    assert gate.verify_report(path)
    assert ev.verify_signed_doc(path).failures == 0
    assert sink.of("factory_gate_run") and sink.of("factory_promotion")
    doc = json.loads(path.read_text())
    assert "float" not in json.dumps(doc) and not _has_float(doc)


def _has_float(v: Any) -> bool:
    if isinstance(v, float):
        return True
    if isinstance(v, dict):
        return any(_has_float(x) for x in v.values())
    if isinstance(v, list):
        return any(_has_float(x) for x in v)
    return False


def test_sample_never_promotes(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    run = gate.start(env, "mr-agent", "0.1", "sample", "reviewer.an", n=10, background=False)
    assert run["status"] == "done" and run["verdict"] == "pass"
    assert run["cost"]["cases"] == 10
    assert run["layer2"]["calibration"] == {"status": "skipped"}
    assert env.store.get("mr-agent", "0.1")["state"] == "draft"


def test_golden_cases_ready_check() -> None:
    defn = {"id": "x", "checklist": [{"id": "A"}, {"id": "B"}]}
    cases = [{"case_id": f"c{i}", "expected": {"A": "pass"}} for i in range(caps.GOLDEN_MIN_CASES)]
    s = golden.gate_stratification(cases, [c["id"] for c in defn["checklist"]])
    assert not s["ready"] and s["uncovered"] == ["B"]
    assert golden_cases  # imported helper
