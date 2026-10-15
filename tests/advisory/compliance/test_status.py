from __future__ import annotations

from supervisor.advisory.compliance.model import (
    ControlCheck,
    Pointer,
    ProductControls,
    RuleFact,
    ThresholdFinding,
)
from supervisor.advisory.compliance.status import check_controls, derive_status
from supervisor.regkb.model import AppliesTo, Control, Dates, Obligation


def _ob(*controls: Control) -> Obligation:
    return Obligation(
        id="OB-1",
        instrument_id="I",
        jurisdiction="VN",
        instrument_kind="law",
        issuer="x",
        number="1",
        title_en="t",
        status="in_force",
        binding=True,
        dates=Dates(),
        article_ref="Art. 1",
        summary_en="s",
        duties=(),
        applies_to=AppliesTo(),
        control_mapping=tuple(controls),
        evidence_needed=(),
        verification="V",
        sources=(),
        confidence="high",
    )


def _c(kind, cid, cov, present, ptr=None):
    return ControlCheck(kind, cid, cov, present, ptr)


def _exceeds():
    return ThresholdFinding(
        "TH-1-effective", "OB-1", "PAY-03", "daily", "individual", 150, 100, "exceeds", "too high"
    )


def test_row1_not_applicable():
    st, why = derive_status("no", [_c("catalogue", "a", "full", True)], [_exceeds()])
    assert st == "not_applicable" and why


def test_row2_threshold_exceeds_is_gap_even_with_full_control():
    st, why = derive_status("yes", [_c("catalogue", "a", "full", True)], [_exceeds()])
    assert st == "gap"
    assert "PAY-03" in why and "150" in why


def test_threshold_not_exceeds_does_not_gap():
    f = ThresholdFinding(
        "TH-1-effective", "OB-1", "PAY-03", "daily", "individual", 100, 100, "at_cap", "r"
    )
    st, _ = derive_status("yes", [_c("catalogue", "a", "full", True)], [f])
    assert st == "met"


def test_row3_process_only_is_bank_process():
    st, why = derive_status("yes", [_c("process", "kyc", "partial", None)], [])
    assert st == "bank_process" and "kyc" in why


def test_row3_empty_mapping_is_bank_process():
    st, _ = derive_status("yes", [], [])
    assert st == "bank_process"


def test_row4_none_present_is_gap():
    st, why = derive_status(
        "yes", [_c("catalogue", "a", "full", False), _c("process", "p", "partial", None)], []
    )
    assert st == "gap"
    assert "missing: a" in why


def test_row5_full_present_is_met():
    st, why = derive_status(
        "yes",
        [
            _c("catalogue", "a", "full", True, Pointer("plan", "a")),
            _c("monitor", "d", "partial", False),
        ],
        [],
    )
    assert st == "met"
    assert "present: a (a)" in why and "d" in why


def test_row6_only_partial_present_is_partial():
    st, _ = derive_status("yes", [_c("catalogue", "a", "partial", True)], [])
    assert st == "partial"


def test_coverage_none_present_control_does_not_count():
    st, why = derive_status("yes", [_c("catalogue", "a", "none", True)], [])
    assert st == "gap"
    assert "coverage none" in why
    st, _ = derive_status(
        "yes", [_c("catalogue", "a", "none", True), _c("rule", "b", "partial", True)], []
    )
    assert st == "partial"


def test_needs_answer_keeps_derived_status():
    st, why = derive_status("needs_answer", [_c("catalogue", "a", "full", True)], [])
    assert st == "met" and "if the obligation applies" in why
    st, _ = derive_status("needs_answer", [_c("catalogue", "a", "full", False)], [])
    assert st == "gap"


def test_every_status_reason_names_control_ids():
    cases = [
        ("yes", [_c("catalogue", "ctl_gap", "full", False)], []),
        ("yes", [_c("catalogue", "ctl_met", "full", True)], []),
        ("yes", [_c("catalogue", "ctl_part", "partial", True)], []),
        ("yes", [_c("process", "proc_id", "partial", None)], []),
    ]
    for applies, checks, th in cases:
        _, why = derive_status(applies, checks, th)
        assert checks[0].id in why


def test_check_controls_presence_per_kind():
    controls = ProductControls(
        known=True,
        catalogue_on=("c1",),
        rules=(RuleFact("R1", "d", Pointer("rule", "p.yaml:1")),),
        monitors=("m1",),
        evidence=("e1",),
        console=("s1",),
        pointers={"rule:R1": Pointer("rule", "p.yaml:1")},
    )
    ob = _ob(
        Control("catalogue", "c1", "full"),
        Control("catalogue", "c2", "full"),
        Control("rule", "R1", "partial"),
        Control("monitor", "m1", "partial"),
        Control("evidence", "e1", "full"),
        Control("evidence", "e2", "full"),
        Control("console", "s1", "partial"),
        Control("process", "pp", "partial"),
    )
    got = {(c.kind, c.id): c for c in check_controls(ob, controls)}
    assert got[("catalogue", "c1")].present is True
    assert got[("catalogue", "c2")].present is False
    assert got[("rule", "R1")].present is True and got[("rule", "R1")].pointer.ref == "p.yaml:1"
    assert got[("monitor", "m1")].present is True
    assert got[("evidence", "e2")].present is False
    assert got[("console", "s1")].present is True
    assert got[("process", "pp")].present is None


def test_unknown_controls_count_as_absent():
    ob = _ob(Control("catalogue", "c1", "full"))
    (chk,) = check_controls(ob, ProductControls(known=False, catalogue_on=("c1",)))
    assert chk.present is False
    st, _ = derive_status("yes", [chk], [])
    assert st == "gap"
