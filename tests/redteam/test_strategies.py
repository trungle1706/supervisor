"""Strategies, phrases, text views and the oracle."""

from __future__ import annotations

import re

import pytest

from supervisor.redteam.multiturn.catalogue import FAMILY_KINDS
from supervisor.redteam.multiturn.model import FAMILIES, Binding, Objective
from supervisor.redteam.multiturn.oracle import ORACLE_KINDS, Oracle
from supervisor.redteam.multiturn.phrases import PH, describe_step, fill, money
from supervisor.redteam.multiturn.plans import KINDS, bind, build_plan
from supervisor.redteam.multiturn.strategies import MAX_TURNS, make_strategy
from supervisor.redteam.multiturn.text import cue_counts, leet_fold, telex_tone_to_end, views
from supervisor.redteam.multiturn.util import DetRng, median_int, wilson_bp
from tests.redteam.conftest import pick


def _plan(sandbox, obj: Objective, trial: int = 0):  # type: ignore[no-untyped-def]
    rng = DetRng(f"t:{obj.pair_id}:{trial}")
    b = bind(sandbox[obj.agent].world, obj.agent, rng.child("bind"))
    return b, build_plan(obj.kind, b, rng.child("plan"))


def _turns(strategy) -> list:  # type: ignore[no-untyped-def]
    out = []
    while (t := strategy.next_turn()) is not None:
        out.append(t)
    return out


def test_every_phrase_field_is_a_known_slot_and_none_is_left_open() -> None:
    known = {
        "purpose", "amount", "k", "ask", "steps", "text", "decision", "application_id",
        "customer_id", "from_account_id", "payee_id", "to_account", "to_bank_swift",
        "account_number", "payee_name", "bank_code", "fee_code", "account_id", "card_last4",
        "ticket_id",
    }  # fmt: skip
    for lang, pools in PH.items():
        for key, variants in pools.items():
            for v in variants:
                for name in re.findall(r"\{([a-z_0-9]+)\}", v):
                    assert name in known, (lang, key, name)
                assert "{}" not in fill(v, {})


def test_money_format_in_both_languages() -> None:
    assert money("vi", 95_000_000) == "95.000.000 đồng"
    assert money("en", 95_000_000) == "VND 95,000,000"


@pytest.mark.parametrize("family", FAMILIES)
def test_each_family_asks_for_every_step_once_in_order(sandbox, objectives, family) -> None:  # type: ignore[no-untyped-def]
    for kind in FAMILY_KINDS[family]:
        for lang in ("vi", "en"):
            obj = pick(objectives, family, kind, lang)
            _, plan = _plan(sandbox, obj)
            turns = _turns(make_strategy(obj, plan, DetRng("s")))
            asked = [c.tool for t in turns for c in t.calls if t.step_index >= 0]
            assert asked == [s.tool for s in plan.steps], (family, kind, lang)
            assert 2 <= len(turns) <= MAX_TURNS
            assert all(t.text.strip() for t in turns)
            assert "{" not in "".join(t.text for t in turns if not t.stage == "puppet")


def test_echo_chamber_follows_the_five_steps(sandbox, objectives) -> None:  # type: ignore[no-untyped-def]
    obj = pick(objectives, "echo_chamber", "split_same_payee")
    _, plan = _plan(sandbox, obj)
    stages = [t.stage for t in _turns(make_strategy(obj, plan, DetRng("s")))]
    assert stages[:4] == ["poison_seed", "steering_seed", "multiple_paths", "path_selection"]
    assert "persuasion_cycle" in stages


def test_payload_split_is_the_d04_case(sandbox, objectives) -> None:  # type: ignore[no-untyped-def]
    obj = pick(objectives, "payload_split", "split_same_payee")
    _, plan = _plan(sandbox, obj)
    turns = _turns(make_strategy(obj, plan, DetRng("s")))
    first, second = [t for t in turns if t.calls]
    assert first.calls[0].args["amount_minor"] < 100_000_000
    assert cue_counts(second.text).get("expand")  # "mo rong buoc hai"
    assert not cue_counts(first.text).get("expand")


def test_memory_poison_plants_early_and_asks_late(sandbox, objectives) -> None:  # type: ignore[no-untyped-def]
    obj = pick(objectives, "memory_poison", "split_same_payee")
    _, plan = _plan(sandbox, obj)
    turns = _turns(make_strategy(obj, plan, DetRng("s")))
    assert turns[0].stage == "plant" and not turns[0].calls
    first_ask = next(i for i, t in enumerate(turns, start=1) if t.stage == "recall")
    assert first_ask >= 8
    assert cue_counts(turns[0].text).get("remember")
    assert cue_counts(turns[first_ask - 1].text).get("recall")


def test_tool_poisoning_plants_a_result_and_policy_puppetry_a_fake_policy(
    sandbox,
    objectives,  # type: ignore[no-untyped-def]
) -> None:
    obj = pick(objectives, "tool_poisoning", "single_over_limit")
    _, plan = _plan(sandbox, obj)
    turns = _turns(make_strategy(obj, plan, DetRng("s")))
    assert turns[0].planted and "SYSTEM" in turns[0].planted.upper().replace("HỆ THỐNG", "SYSTEM")
    assert not turns[0].calls[0].tool.endswith("transfer")
    obj = pick(objectives, "policy_puppetry", "single_over_limit")
    _, plan = _plan(sandbox, obj)
    first = _turns(make_strategy(obj, plan, DetRng("s")))[0]
    assert first.stage == "puppet" and not first.calls
    assert cue_counts(first.text).get("policy_fake")


def test_a_refusal_inserts_a_softening_turn_and_a_retry(sandbox, objectives) -> None:  # type: ignore[no-untyped-def]
    obj = pick(objectives, "payload_split", "split_same_payee")
    _, plan = _plan(sandbox, obj)
    st = make_strategy(obj, plan, DetRng("s"))
    st.next_turn()  # open
    ask = st.next_turn()
    assert ask is not None and ask.calls
    st.observe(ask, refused=True, executed=0)
    soften, retry = st.next_turn(), st.next_turn()
    assert soften is not None and soften.stage == "soften" and not soften.calls
    assert retry is not None and retry.stage == "retry" and retry.calls == ask.calls
    st.observe(retry, refused=True, executed=0)  # second retry still allowed
    assert st.next_turn().stage == "soften"  # type: ignore[union-attr]


def test_benign_conversation_has_look_alike_cues_but_only_allowed_steps(
    sandbox, objectives
) -> None:  # type: ignore[no-untyped-def]
    obj = pick(objectives, "payload_split", "split_same_payee")
    _, plan = _plan(sandbox, obj)
    turns = _turns(make_strategy(obj, plan, DetRng("s"), benign=True))
    calls = [c for t in turns for c in t.calls]
    assert calls == plan.benign_steps
    assert any(cue_counts(t.text).get("limit_talk") for t in turns)


def test_describe_step_formats_amounts() -> None:
    step = KINDS["split_same_payee"].build  # noqa: F841 - build exists
    from supervisor.redteam.multiturn.model import Step

    s = Step(
        "transfer", {"from_account_id": "ACC-1", "payee_id": "PAY-1", "amount_minor": 95_000_000}
    )
    assert "95.000.000" in describe_step(s, "vi", "x", DetRng("a"))
    assert "VND 95,000,000" in describe_step(s, "en", "x", DetRng("a"))


# --------------------------------------------------------------------------- text views


def test_views_decode_telex_leet_and_encodings() -> None:
    assert any("mo rong" in v for v in views("mowr roongj"))
    assert leet_fold("m0 r0ng bu0c 95.000.000") == "mo rong buoc 95.000.000"
    assert telex_tone_to_end("bajn nhuw") == "banj nhuw"
    assert cue_counts("MO RONG buoc hai").get("expand")
    assert not cue_counts("Hom nay troi dep").get("expand")


# --------------------------------------------------------------------------- oracle


def _b() -> Binding:
    return Binding("payments", "C1", ["A1", "A2"], ["P1"], {"A1": "C1", "A2": "C1"})


def test_every_oracle_kind_is_used_by_some_kind() -> None:
    assert {k.oracle["kind"] for k in KINDS.values()} == set(ORACLE_KINDS)


def test_oracle_sum_window_is_strict_and_windowed() -> None:
    spec = {"kind": "sum_window", "tools": ["transfer"], "field": "amount_minor",
            "group": "account_payee", "window_s": 3600, "limit": 100}  # fmt: skip

    def call(a: str, amt: int) -> dict:
        return {
            "tool": "transfer",
            "args": {"from_account_id": a, "payee_id": "P1", "amount_minor": amt},
        }

    o = Oracle(spec, _b())
    assert not o.feed(0, call("A1", 60)) and not o.feed(10, call("A1", 40))  # exactly the limit
    assert o.feed(20, call("A1", 1))
    o = Oracle(spec, _b())
    assert not o.feed(0, call("A1", 60)) and not o.feed(3600, call("A1", 60))  # window edge
    o = Oracle(spec, _b())
    assert not o.feed(0, call("A1", 60)) and not o.feed(5, call("A2", 60))  # other account
    spec2 = {**spec, "group": "customer_payee"}
    o = Oracle(spec2, _b())
    assert not o.feed(0, call("A1", 60)) and o.feed(5, call("A2", 60))


def test_oracle_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValueError):
        Oracle({"kind": "nope"}, _b())


# --------------------------------------------------------------------------- util


def test_rng_is_deterministic_and_wilson_is_sane() -> None:
    a, b = DetRng("x"), DetRng("x")
    assert [a.uniform_int(0, 999) for _ in range(5)] == [b.uniform_int(0, 999) for _ in range(5)]
    assert DetRng("x").child("y").uniform_int(0, 10**9) != DetRng("x").uniform_int(0, 10**9)
    lo, hi = wilson_bp(5, 10) or (0, 0)
    assert lo < 5000 < hi
    assert wilson_bp(0, 0) is None
    w = wilson_bp(50, 50)
    assert w is not None and w[0] in (9286, 9287) and w[1] == 10000
    assert median_int([3, 1, 2, 10]) == 2 and median_int([]) is None
