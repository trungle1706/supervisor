from __future__ import annotations

from pathlib import Path

from supervisor.regkb import AppliesTo, ProductProfile, applicable, evaluate, load_kb
from tests.regkb.conftest import instrument, kb_file, obligation, write_file


def test_empty_predicate_applies_to_everything() -> None:
    r = evaluate(AppliesTo(), ProductProfile())
    assert r.status == "applies" and r.missing_facts == ()


def test_agent_class_any_matches_without_facts() -> None:
    r = evaluate(AppliesTo(agent_class=("any",)), ProductProfile())
    assert r.status == "applies"


def test_agent_class_intersection() -> None:
    pred = AppliesTo(agent_class=("payment", "credit_decision"))
    assert (
        evaluate(pred, ProductProfile(agent_classes=("payment", "internal_tool"))).status
        == "applies"
    )
    r = evaluate(pred, ProductProfile(agent_classes=("customer_facing",)))
    assert r.status == "not_applicable"
    assert evaluate(pred, ProductProfile(agent_classes=())).status == "not_applicable"


def test_data_classes_intersection_and_unknown() -> None:
    pred = AppliesTo(data_classes=("personal", "biometric"))
    assert (
        evaluate(pred, ProductProfile(data_classes=("financial", "biometric"))).status == "applies"
    )
    assert evaluate(pred, ProductProfile(data_classes=("financial",))).status == "not_applicable"
    r = evaluate(pred, ProductProfile())
    assert r.status == "unknown" and r.missing_facts == ("data_classes",)


def test_autonomy_and_hosting_membership() -> None:
    pred = AppliesTo(autonomy=("acts_autonomously",), model_hosting=("foreign_cloud",))
    both = ProductProfile(autonomy="acts_autonomously", model_hosting="foreign_cloud")
    assert evaluate(pred, both).status == "applies"
    assert (
        evaluate(pred, ProductProfile(autonomy="advisory", model_hosting="foreign_cloud")).status
        == "not_applicable"
    )
    r = evaluate(pred, ProductProfile(autonomy="acts_autonomously"))
    assert r.status == "unknown" and r.missing_facts == ("model_hosting",)


def test_cross_border_bool() -> None:
    pred = AppliesTo(cross_border=True)
    assert evaluate(pred, ProductProfile(cross_border=True)).status == "applies"
    assert evaluate(pred, ProductProfile(cross_border=False)).status == "not_applicable"
    assert evaluate(pred, ProductProfile()).status == "unknown"
    assert (
        evaluate(AppliesTo(cross_border=False), ProductProfile(cross_border=False)).status
        == "applies"
    )


def test_role() -> None:
    pred = AppliesTo(role=("provider",))
    assert evaluate(pred, ProductProfile(roles=("deployer",))).status == "not_applicable"
    assert evaluate(pred, ProductProfile(roles=("deployer", "provider"))).status == "applies"
    assert evaluate(pred, ProductProfile()).missing_facts == ("roles",)


def test_known_excluding_fact_beats_unknown() -> None:
    pred = AppliesTo(agent_class=("payment",), data_classes=("personal",), cross_border=True)
    r = evaluate(pred, ProductProfile(agent_classes=("internal_tool",)))
    assert r.status == "not_applicable"
    assert r.missing_facts == ("data_classes", "cross_border")  # still reported
    assert any("internal_tool" in x for x in r.reasons)


def test_unknown_lists_all_missing_facts_and_never_guesses() -> None:
    pred = AppliesTo(agent_class=("payment",), data_classes=("personal",), role=("deployer",))
    r = evaluate(pred, ProductProfile())
    assert r.status == "unknown"
    assert r.missing_facts == ("agent_classes", "data_classes", "roles")


def test_reasons_are_ascii() -> None:
    r = evaluate(
        AppliesTo(agent_class=("payment",)), ProductProfile(agent_classes=("internal_tool",))
    )
    assert all(x.isascii() for x in r.reasons)


def test_applicable_over_kb(tmp_path: Path) -> None:
    reg = tmp_path / "regulations"
    obs = [
        obligation("VN-TEST-2026-A1-01", applies_to={"agent_class": ["payment"]}),
        obligation("VN-TEST-2026-A2-01", applies_to={"agent_class": ["credit_decision"]}),
        obligation("VN-TEST-2026-A3-01", applies_to={"cross_border": True}),
    ]
    write_file(reg / "vn", "t.yaml", kb_file(instrument(), obs))
    (reg / "intl").mkdir()
    kb = load_kb(reg)
    profile = ProductProfile(agent_classes=("payment",))
    got = {o.id: r.status for o, r in applicable(kb, profile)}
    assert got == {
        "VN-TEST-2026-A1-01": "applies",
        "VN-TEST-2026-A2-01": "not_applicable",
        "VN-TEST-2026-A3-01": "unknown",
    }
    kept = [o.id for o, _ in applicable(kb, profile, include_not_applicable=False)]
    assert kept == ["VN-TEST-2026-A1-01", "VN-TEST-2026-A3-01"]
