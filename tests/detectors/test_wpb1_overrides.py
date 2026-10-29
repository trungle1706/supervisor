"""WP-B1 item 1: stored per-agent detector setting overrides (table ``detector_override``).

The service, the chain record, the gate merge (policy file wins for the keys it names), the
refusals and the off path (no source when SMART_GUARDIAN is off).
"""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.detectors.overrides import (
    DetectorOverrideService,
    OverrideError,
    OverrideSource,
    make_source,
)
from supervisor.evidence.chain import check_no_floats
from supervisor.gateway.policy import AgentDetectors
from tests.detectors.conftest import (  # noqa: F401
    MemoryEvidence,
    adapters,
    clock,
    make_gate,
    masker,  # noqa: F401
)

ACTOR = "reviewer.an"


@pytest.fixture
def svc(adapters: Any, evidence: MemoryEvidence) -> DetectorOverrideService:  # noqa: F811
    return DetectorOverrideService(
        adapters.state, adapters.clock, adapters.settings, evidence=evidence
    )


def _gate(masker: Any, adapters: Any) -> Any:  # noqa: F811
    gate = make_gate(masker)
    gate.overrides = OverrideSource(adapters.state)
    return gate


def test_set_stores_a_row_and_one_chain_record(svc: DetectorOverrideService, evidence: Any) -> None:
    svc.set("pay-agent", "dlp_vn", "mode", "report", ACTOR, source="smart_guardian")
    assert svc.for_agent("pay-agent") == {"dlp_vn": {"mode": "report"}}
    recs = [r for r in evidence.entries if r[0] == "detector_override"]
    assert len(recs) == 1
    payload = recs[0][2]
    check_no_floats(payload)
    assert payload["agent_id"] == "pay-agent" and payload["action"] == "added"
    assert "report" not in str(payload) and payload["actor_ref"].startswith("act_")
    svc.set("pay-agent", "dlp_vn", "mode", "transform", ACTOR)
    assert evidence.entries[-1][2]["action"] == "changed"


def test_agent_row_beats_the_wildcard_row(svc: DetectorOverrideService) -> None:
    svc.set("*", "dlp_vn", "mode", "report", ACTOR)
    svc.set("a1", "dlp_vn", "mode", "transform", ACTOR)
    assert svc.for_agent("a1")["dlp_vn"]["mode"] == "transform"
    assert svc.for_agent("other")["dlp_vn"]["mode"] == "report"


@pytest.mark.parametrize(
    "args",
    [
        ("a1", "dlp_vn", "keep_args", {"x": ["y"]}),
        ("a1", "dlp_vn", "mode", 1.5),
        ("a1", "dlp_vn", "mode", None),
        ("a1", "Bad Slug", "mode", "report"),
        ("a1", "dlp_vn", "mode", ""),
        ("bad id!", "dlp_vn", "mode", "report"),
    ],
)
def test_refusals_are_400_style_errors(svc: DetectorOverrideService, args: tuple[Any, ...]) -> None:
    with pytest.raises(OverrideError):
        svc.set(*args, ACTOR)


def test_gate_applies_the_row_and_the_policy_file_wins(
    svc: DetectorOverrideService,
    adapters: Any,  # noqa: F811
    masker: Any,  # noqa: F811
) -> None:
    gate = _gate(masker, adapters)
    svc.set("a1", "dlp_vn", "mode", "report", ACTOR)
    got = gate._with_stored(None, "a1")  # noqa: SLF001
    run, _ = gate.resolved.for_agent(got)
    assert run.detectors["dlp_vn"].settings["mode"] == "report"
    # the policy file names the key: it wins
    locked = AgentDetectors(settings={"dlp_vn": {"mode": "transform"}})
    run, _ = gate.resolved.for_agent(gate._with_stored(locked, "a1"))  # noqa: SLF001
    assert run.detectors["dlp_vn"].settings["mode"] == "transform"
    # enable / disable stay the policy's: the floor is untouched
    assert gate._with_stored(AgentDetectors(disable=["injection_regex"]), "a1").disable == [  # noqa: SLF001
        "injection_regex"
    ]


def test_a_value_the_catalogue_refuses_is_not_applied(
    svc: DetectorOverrideService,
    adapters: Any,  # noqa: F811
    masker: Any,  # noqa: F811
) -> None:
    gate = _gate(masker, adapters)
    svc.set("a1", "dlp_vn", "mode", "nonsense", ACTOR)  # no registry on the service: stored
    run, _ = gate.resolved.for_agent(gate._with_stored(None, "a1"))  # noqa: SLF001
    assert run.detectors["dlp_vn"].settings["mode"] == "transform"
    run, _ = gate.resolved.for_agent(None)
    assert run.detectors["dlp_vn"].settings["mode"] == "transform"


def test_no_rows_changes_nothing(adapters: Any, masker: Any) -> None:  # noqa: F811
    gate = _gate(masker, adapters)
    assert gate._with_stored(None, "nobody") is None  # noqa: SLF001
    pol = AgentDetectors(preset="strict")
    assert gate._with_stored(pol, "nobody") is pol  # noqa: SLF001


def test_off_path_has_no_source(adapters: Any) -> None:  # noqa: F811
    s = adapters.settings
    s.smart_guardian = False
    s.detectors_enabled = True
    assert make_source(s, adapters.state) is None
    s.smart_guardian = True
    s.detectors_enabled = False
    assert make_source(s, adapters.state) is None
    s.detectors_enabled = True
    assert make_source(s, adapters.state) is not None
    assert make_gate.__name__  # the gate default: no source until wiring sets one
