"""WP-C1: the classification tree file. Strict loader, every path ends in an outcome, every
article is a row of RegKB, the walk (prefill, person wins, sub-flow, excluded) and the level map.
Pure code: no store, no app."""

from __future__ import annotations

import copy
import itertools
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.governance import classification_tree as ct
from supervisor.governance import model as gm
from supervisor.governance.conditions import RulesError
from supervisor.regkb import load_kb
from tests.conftest import REPO_ROOT

FILE = REPO_ROOT / "config" / "classification.yaml"


@pytest.fixture(scope="module")
def tree() -> ct.Tree:
    return ct.load_tree(FILE)


def doc() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(FILE.read_text("utf-8")))


def bad(mutate: Any, tmp_path: Path) -> RulesError:
    d = doc()
    mutate(d)
    p = tmp_path / "classification.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    with pytest.raises(RulesError) as info:
        ct.load_tree(p)
    return info.value


# ------------------------------------------------------------------ the file


def test_the_shipped_file_loads_with_the_planned_shape(tree: ct.Tree) -> None:
    assert tree.illustrative is True and tree.start == "N-SYSTEM"
    assert list(tree.nodes) == [
        "N-SYSTEM",
        "N-PROHIBITED",
        "N-PM-LIST",
        "N-THRESHOLD",
        "N-CERT",
        "N-CONFUSE",
    ]
    assert list(tree.outcomes) == list(ct.OUTCOME_IDS)
    assert dict(tree.thresholds) == {
        "personal_per_transaction_vnd": 10_000_000,
        "personal_per_day_vnd": 20_000_000,
        "organisation_per_transaction_vnd": 50_000_000,
        "organisation_per_day_vnd": 100_000_000,
        "credit_vnd": 50_000_000,
    }
    assert all(isinstance(v, int) for v in tree.thresholds.values())  # no floats
    assert [t.article.ref for t in tree.retriggers] == [
        "Art. 11(1)(a)",
        "Art. 11(1)(b)",
        "Art. 11(1)(c)",
        "Art. 11(1)(d)",
        "Art. 11(2)",
    ]
    assert [t.article.ref for t in tree.not_triggers] == ["Art. 11(4)"]  # 11(4) is not a trigger
    assert tree.node("N-PM-LIST").subflow == "decision33"
    assert tree.node("N-CONFUSE").answers["excluded"] == "low"


def test_level_mapping(tree: ct.Tree) -> None:
    levels = {o.id: o.level for o in tree.outcomes.values()}
    assert levels == {
        "not_system": None,
        "prohibited": "prohibited",
        "high_certify": "high",
        "high_self": "high",
        "medium": "medium",
        "low": "low",
    }
    assert {x for x in levels.values() if x} <= set(gm.RISK_LEVELS)


def test_every_path_ends_in_an_outcome(tree: ct.Tree) -> None:
    """Try every combination of answers (and both outcomes of the sub-flow) from the start."""
    seen: set[str] = set()
    for combo in itertools.product(*[list(n.answers) for n in tree.nodes.values()]):
        pick = dict(zip(tree.nodes, combo, strict=True))
        cur, hops = tree.start, 0
        while cur in tree.nodes:
            cur = tree.nodes[cur].answers[pick[cur]]
            hops += 1
            assert hops <= len(tree.nodes), "loop"
        assert cur in tree.outcomes
        seen.add(cur)
    assert seen == set(ct.OUTCOME_IDS)  # every outcome can be reached


def test_every_node_article_is_in_regkb(tree: ct.Tree) -> None:
    kb = load_kb()
    missing = [
        f"{where}: {a.text}"
        for where, a in tree.articles()
        if not ct.article_in_kb(kb, a.instrument, a.ref)
    ]
    assert missing == []
    for n in tree.nodes.values():  # every node cites an article
        assert n.article.ref.startswith("Art.")


def test_article_match_rules() -> None:
    kb = load_kb()
    assert ct.article_in_kb(kb, "VN-DEC142-2026", "Art. 6(2)")  # an exact row
    assert ct.article_in_kb(kb, "VN-TT53-2026", "Art. 4(2)")  # parts 4(2)(a) and (b) are rows
    assert ct.article_in_kb(kb, "VN-DEC142-2026", "Art. 11(1)(b)")  # inside the row 11(1)
    assert not ct.article_in_kb(kb, "VN-DEC142-2026", "Art. 99")
    assert not ct.article_in_kb(kb, "VN-AI-2025", "Art. 6(2)")  # same article, other instrument


def test_new_regkb_rows_are_verified_primary_with_text() -> None:
    kb = load_kb()
    ids = [
        "VN-AI-2025-A7.02-01",
        "VN-AI-2025-A9.02-01",
        "VN-AI-2025-A10.04-01",
        "VN-DEC142-2026-A6.02-01",
        "VN-DEC142-2026-A6.03-01",
        "VN-DEC142-2026-A8.01-01",
        "VN-DEC142-2026-A8.02-01",
        "VN-DEC142-2026-A9.01-01",
        "VN-DEC142-2026-A9.03-01",
        "VN-DEC142-2026-A11.02-01",
        "VN-DEC142-2026-A11.04-01",
        "VN-DEC142-2026-A12.02-01",
    ]
    for oid in ids:
        o = kb.get(oid)
        assert o.verification == "VERIFIED_PRIMARY" and o.text_vi and o.article_ref, oid
        kinds = {(c.kind, c.id) for c in o.control_mapping}
        assert ("console", "classification_v2") in kinds, oid
        assert ("evidence", "classification_record") in kinds, oid


# ------------------------------------------------------------------ strict keys


def test_unknown_keys_name_the_field(tmp_path: Path) -> None:
    assert "unknown key: extra" in str(bad(lambda d: d.update(extra=1), tmp_path))
    assert "node 1" in str(bad(lambda d: d["nodes"][0].update(colour="x"), tmp_path))
    assert "unknown key: colour" in str(bad(lambda d: d["nodes"][0].update(colour="x"), tmp_path))
    assert "article" in str(bad(lambda d: d["nodes"][0]["article"].update(page=3), tmp_path))
    assert "thresholds" in str(bad(lambda d: d["thresholds"].update(other=5), tmp_path))
    assert "outcome" in str(bad(lambda d: d["outcomes"][0].update(x=1), tmp_path))
    assert "retriggers" in str(bad(lambda d: d["retriggers"][0].update(x=1), tmp_path))


def test_values_are_checked(tmp_path: Path) -> None:
    assert "version" in str(bad(lambda d: d.update(version=2), tmp_path))
    assert "answer maybe" in str(
        bad(lambda d: d["nodes"][0]["answers"].update(maybe="N-CERT"), tmp_path)
    )
    assert "unknown N-NOWHERE" in str(
        bad(lambda d: d["nodes"][0]["answers"].update({"yes": "N-NOWHERE"}), tmp_path)
    )
    assert "start" in str(bad(lambda d: d.update(start="N-GONE"), tmp_path))
    assert "above 0" in str(
        bad(lambda d: d["thresholds"].update(credit_vnd=1.5), tmp_path)
    )  # a float is refused
    assert "above 0" in str(bad(lambda d: d["thresholds"].update(credit_vnd=True), tmp_path))
    assert "level" in str(bad(lambda d: d["outcomes"][0].update(level="extreme"), tmp_path))
    assert "outcomes missing" in str(bad(lambda d: d["outcomes"].pop(), tmp_path))
    assert "instrument" in str(
        bad(lambda d: d["nodes"][0]["article"].update(instrument="not an id"), tmp_path)
    )
    assert "unknown field" in str(
        bad(lambda d: d["nodes"][0]["prefill"]["when"].update(field="nonsense"), tmp_path)
    )


def test_loop_and_unreachable_node_are_refused(tmp_path: Path) -> None:
    assert "loop" in str(
        bad(lambda d: d["nodes"][1]["answers"].update({"no": "N-SYSTEM"}), tmp_path)
    )

    def orphan(d: dict[str, Any]) -> None:
        extra = copy.deepcopy(d["nodes"][-1])
        extra["id"] = "N-ORPHAN"
        d["nodes"].append(extra)

    assert "not reachable" in str(bad(orphan, tmp_path))


def test_subflow_node_needs_both_decision33_outcomes(tmp_path: Path) -> None:
    assert "high_risk" in str(
        bad(lambda d: d["nodes"][2]["answers"].pop("not_high_risk"), tmp_path)
    )
    assert "answer yes" in str(
        bad(lambda d: d["nodes"][2]["answers"].update({"yes": "N-CERT"}), tmp_path)
    )


def test_missing_file_and_bad_yaml(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="missing"):
        ct.load_tree(tmp_path / "none.yaml")
    p = tmp_path / "x.yaml"
    p.write_text("a: [", encoding="utf-8")
    with pytest.raises(RulesError, match="cannot read"):
        ct.load_tree(p)


def test_unquoted_yes_and_no_are_read_as_text(tmp_path: Path) -> None:
    text = FILE.read_text("utf-8").replace(
        '"yes": N-PROHIBITED, "no": not_system', "yes: N-PROHIBITED, no: not_system"
    )
    assert "yes: N-PROHIBITED" in text
    p = tmp_path / "t.yaml"
    p.write_text(text, encoding="utf-8")
    assert ct.load_tree(p).node("N-SYSTEM").answers == {"yes": "N-PROHIBITED", "no": "not_system"}


# ------------------------------------------------------------------ the walk


def a(**kw: str) -> dict[str, dict[str, str]]:
    return {k.replace("_", "-").upper(): {"answer": v} for k, v in kw.items()}


def walk(
    tree: ct.Tree,
    answers: dict[str, Any],
    facts: dict[str, Any] | None = None,
    d33: str | None = None,
) -> ct.Walk:
    return ct.walk(tree, answers, facts or {}, d33)


def test_not_a_system_ends_at_once(tree: ct.Tree) -> None:
    w = walk(tree, {"N-SYSTEM": {"answer": "no"}})
    assert w.outcome == "not_system" and [s.node for s in w.steps] == ["N-SYSTEM"]


def test_prohibited(tree: ct.Tree) -> None:
    w = walk(tree, {"N-SYSTEM": {"answer": "yes"}, "N-PROHIBITED": {"answer": "yes"}})
    assert w.outcome == "prohibited"


def test_high_paths(tree: ct.Tree) -> None:
    base = {"N-SYSTEM": {"answer": "yes"}, "N-PROHIBITED": {"answer": "no"}}
    mid = {**base, "N-THRESHOLD": {"answer": "yes"}}
    assert (
        walk(tree, {**mid, "N-CERT": {"answer": "yes"}}, d33="high_risk").outcome == "high_certify"
    )
    assert walk(tree, {**mid, "N-CERT": {"answer": "no"}}, d33="high_risk").outcome == "high_self"
    below = walk(
        tree,
        {**base, "N-THRESHOLD": {"answer": "no"}, "N-CONFUSE": {"answer": "no"}},
        d33="high_risk",
    )
    assert below.outcome == "low"  # on the list but under the SBV threshold: the tree goes on


def test_medium_low_and_excluded(tree: ct.Tree) -> None:
    base = {"N-SYSTEM": {"answer": "yes"}, "N-PROHIBITED": {"answer": "no"}}
    for ans, outcome in (("yes", "medium"), ("no", "low"), ("excluded", "low")):
        w = walk(tree, {**base, "N-CONFUSE": {"answer": ans}}, d33="not_high_risk")
        assert w.outcome == outcome, ans
        assert w.steps[-1].node == "N-CONFUSE" and w.steps[2].source == "decision33"


def test_open_subflow_keeps_the_path_open(tree: ct.Tree) -> None:
    base = {"N-SYSTEM": {"answer": "yes"}, "N-PROHIBITED": {"answer": "no"}}
    w = walk(tree, base, d33=None)
    assert w.outcome is None and w.pending == "N-PM-LIST" and w.pending_reason == "decision33_open"
    assert not w.complete and [s.node for s in w.steps] == ["N-SYSTEM", "N-PROHIBITED"]


def test_prefill_answers_but_a_person_wins(tree: ct.Tree) -> None:
    facts = {"component.agent.count": 1, "user_segment": "customer", "system_type": "assistant"}
    w = walk(tree, {"N-PROHIBITED": {"answer": "no"}}, facts, d33="not_high_risk")
    assert w.outcome == "medium"
    by = {s.node: s for s in w.steps}
    assert by["N-SYSTEM"].source == "rules" and by["N-CONFUSE"].source == "rules"
    assert by["N-PROHIBITED"].source == "person"
    w2 = walk(
        tree,
        {"N-PROHIBITED": {"answer": "no"}, "N-CONFUSE": {"answer": "no"}},
        facts,
        d33="not_high_risk",
    )
    assert w2.outcome == "low" and {s.node: s for s in w2.steps}["N-CONFUSE"].source == "person"
    # a prefill never answers when its condition is false
    w3 = walk(tree, {}, {"component.agent.count": 0})
    assert w3.pending == "N-SYSTEM" and w3.pending_reason == "unanswered"


def test_bad_answer_for_a_node(tree: ct.Tree) -> None:
    with pytest.raises(ct.TreeAnswerError, match="N-SYSTEM"):
        walk(tree, {"N-SYSTEM": {"answer": "excluded"}})  # N-SYSTEM has no excluded branch


def test_pointer_and_note_limits(tree: ct.Tree) -> None:
    ok = walk(tree, {"N-SYSTEM": {"answer": "no", "evidence": "x" * 200, "note": "y" * 300}})
    assert ok.steps[0].evidence == "x" * 200
    with pytest.raises(ct.TreeAnswerError, match="evidence"):
        walk(tree, {"N-SYSTEM": {"answer": "no", "evidence": "x" * 201}})
    with pytest.raises(ct.TreeAnswerError, match="note"):
        walk(tree, {"N-SYSTEM": {"answer": "no", "note": "y" * 301}})
    with pytest.raises(ct.TreeAnswerError, match="control"):
        walk(tree, {"N-SYSTEM": {"answer": "no", "note": "a\x00b"}})


def test_tree_view_marks_the_path(tree: ct.Tree) -> None:
    from supervisor.governance.classification_v2 import tree_view

    w = walk(tree, {"N-SYSTEM": {"answer": "yes"}, "N-PROHIBITED": {"answer": "no"}})
    view = tree_view(tree, w)
    states = {n["id"]: n["state"] for n in view["nodes"]}
    assert (
        states["N-SYSTEM"] == "on" and states["N-PM-LIST"] == "open" and states["N-CERT"] == "off"
    )
    taken = [(n["id"], e["answer"]) for n in view["nodes"] for e in n["edges"] if e["taken"]]
    assert taken == [("N-SYSTEM", "yes"), ("N-PROHIBITED", "no")]
    assert not view["complete"] and view["pending"] == "N-PM-LIST"
    done = tree_view(tree, walk(tree, {"N-SYSTEM": {"answer": "no"}}))
    assert done["outcome"] == "not_system" and [
        o["id"] for o in done["outcomes"] if o["reached"]
    ] == ["not_system"]
