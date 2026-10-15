"""WP17 monitor packs: groundedness and fairness monitors as pack runners."""

from __future__ import annotations

import json
import zlib
from datetime import UTC, datetime
from typing import Any

import yaml

from supervisor.assurance.engine import apply_thresholds
from supervisor.assurance.loader import PACKS_DIR
from supervisor.assurance.model import EvalPack
from supervisor.assurance.runners.monitors import (
    FairnessMonitorRunner,
    GroundednessMonitorRunner,
    MockQualityChat,
)
from supervisor.data.synthetic import SyntheticGenerator
from supervisor.monitors.fairness import FairnessConfig
from tests.assurance.fakes import FakeTraces, ctx

T = datetime(2026, 10, 15, tzinfo=UTC)


def pack(pack_id: str) -> EvalPack:
    return EvalPack.model_validate(
        yaml.safe_load((PACKS_DIR / f"{pack_id}.yaml").read_text(encoding="utf-8"))
    )


def status_of(p: EvalPack, metrics: dict[str, Any]) -> str:
    return apply_thresholds(p, metrics)[2]


def _reply_trace(i: int, tool_text: str, reply: str) -> list[dict[str, Any]]:
    base = {"trace_id": f"t{i}", "agent_id": "customer_service", "ts": T}
    return [
        {
            **base,
            "event_id": f"e{i}a",
            "event_type": "tool_call",
            "tool_name": "read_ticket",
            "args_masked": json.dumps({"ticket_id": f"TCK-{i}"}),
            "result_masked": tool_text,
        },
        {
            **base,
            "event_id": f"e{i}b",
            "event_type": "tool_call",
            "tool_name": "reply",
            "args_masked": json.dumps({"text": reply}),
            "result_masked": None,
        },
    ]


def _grounded_events(good: bool) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for i in range(8):
        reply = (
            f"Phi {200000 + i} VND da duoc hoan."
            if good
            else f"Phi {999000 + i} VND va 77 ngay da duoc hoan."
        )
        events += _reply_trace(i, f"fee {200000 + i} VND charged", reply)
    return events


def test_manifests_validate() -> None:
    assert pack("groundedness_monitor").dimension == "hallucination"
    assert pack("fairness_monitor").dimension == "bias_fairness"
    for pid in ("groundedness_monitor", "fairness_monitor"):
        p = pack(pid)
        assert p.licence == "own" and p.launch_gate == "advisory" and p.targets == ["traces"]


def test_groundedness_good_and_bad() -> None:
    p = pack("groundedness_monitor")
    run = GroundednessMonitorRunner()
    good = run.run(p, ctx(FakeTraces(rows=_grounded_events(True))))
    assert good.status == "ok" and good.is_mock and good.n_items == 8
    assert good.metrics["mean_groundedness_bp"] == 10000
    assert status_of(p, good.metrics) == "ok"
    bad = run.run(p, ctx(FakeTraces(rows=_grounded_events(False))))
    assert bad.metrics["mean_groundedness_bp"] == 0
    assert bad.metrics["low_groundedness_bp"] == 10000
    assert status_of(p, bad.metrics) == "fail"


def test_groundedness_skip_and_cap() -> None:
    p = pack("groundedness_monitor")
    assert GroundednessMonitorRunner().run(p, ctx(FakeTraces(rows=[]))).status == "skip"
    capped = GroundednessMonitorRunner().run(
        p, ctx(FakeTraces(rows=_grounded_events(True)), max_items=3)
    )
    assert capped.n_items == 3
    assert MockQualityChat().is_mock


def _decisions(approve_fn: Any, n: int = 400) -> list[dict[str, Any]]:
    gen = SyntheticGenerator(20261014)
    apps = gen.loan_applications(gen.customers(n), n)
    out = []
    for i, a in enumerate(apps):
        out.append(
            {
                "event_id": f"d{i}",
                "trace_id": f"dt{i}",
                "agent_id": "credit_prequal",
                "event_type": "tool_call",
                "tool_name": "decide_prequal",
                "status": "ok",
                "ts": T,
                "args_masked": json.dumps(
                    {
                        "application_id": a.application_id,
                        "decision": "approve" if approve_fn(a, i) else "deny",
                    }
                ),
            }
        )
    return out


def _cfg() -> FairnessConfig:
    return FairnessConfig(synthetic_customers=400, attributes={"gender": True, "language": True})


def test_fairness_good_and_bad() -> None:
    p = pack("fairness_monitor")
    run = FairnessMonitorRunner()
    good = run.run(
        p,
        ctx(
            FakeTraces(
                rows=_decisions(lambda a, i: zlib.crc32(a.application_id.encode()) % 2 == 0),
                target_id="credit_prequal",
            ),
            extras={"fairness_config": _cfg()},
        ),
    )
    assert good.status == "ok", good.skip_reason
    assert good.metrics["max_approval_gap_bp"] <= 1000, good.details
    assert status_of(p, good.metrics) == "ok"
    bad = run.run(
        p,
        ctx(
            FakeTraces(
                rows=_decisions(lambda a, i: a.gender == "male" or i % 7 == 0),
                target_id="credit_prequal",
            ),
            extras={"fairness_config": _cfg()},
        ),
    )
    assert bad.status == "ok" and bad.metrics["max_approval_gap_bp"] > 2000
    assert status_of(p, bad.metrics) == "fail"


def test_fairness_skips_when_too_few() -> None:
    p = pack("fairness_monitor")
    run = FairnessMonitorRunner()
    empty = run.run(p, ctx(FakeTraces(rows=[], target_id="credit_prequal")))
    assert empty.status == "skip"
    few = run.run(
        p,
        ctx(
            FakeTraces(rows=_decisions(lambda a, i: True, n=40), target_id="credit_prequal"),
            extras={"fairness_config": FairnessConfig(synthetic_customers=40)},
        ),
    )
    assert few.status == "skip" and "not enough decisions" in few.skip_reason
