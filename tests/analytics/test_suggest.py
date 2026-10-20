"""Least-privilege suggestion: exact expected diff, window boundaries, exceptions, confidence."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from supervisor.analytics import tools_suggest as ts
from supervisor.analytics.tools import AnalyticsError, rollup
from supervisor.config import load_settings
from supervisor.gateway.policy import load_policy_dir
from tests.analytics.conftest import END

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tool_analytics"
POLICIES = FIX / "policies"
AGENTS = FIX / "agents"
START = END - timedelta(days=89)


@pytest.fixture
def rolled(ctx, loaded):
    rollup(ctx, START, END)
    return ctx


def _build(ctx, settings=None, **kw):
    kw.setdefault("as_of", END)
    kw.setdefault("policy_dir", POLICIES)
    kw.setdefault("manifest_dir", AGENTS)
    return ts.build_all(ctx.state, settings or load_settings(), **kw)


def _by_agent(sug):
    return {s["agent_id"]: s for s in sug}


def test_expected_diff_is_exact(rolled) -> None:
    sug = _build(rolled)
    got = _by_agent(sug)
    assert got["payments"]["remove"] == ["add_payee"]
    assert got["customer_service"]["remove"] == ["open_dispute"]
    assert got["credit_prequal"]["remove"] == []
    assert [e["tool"] for e in got["payments"]["undeclared"]] == ["ext_transfer_api"]
    base = "tests/fixtures/tool_analytics"
    want = (
        f"--- a/{base}/policies/baseline.yaml\n"
        f"+++ b/{base}/policies/baseline.yaml\n"
        "@@ -63,12 +63,12 @@\n"
        "   # ---- approved tools per agent (allow-lists). ext_transfer_api is registered for the\n"
        "   # ---- payments agent but NOT approved for it (operations staff only).\n"
        "   - id: PAY-07\n"
        "-    version: 1\n"
        "+    version: 2\n"
        "     description: Payments agent may call approved tools only\n"
        "     agent_scope: [payments]\n"
        "     when:\n"
        "       tool:\n"
        "-        not_in: [get_balance, list_payees, add_payee, transfer]\n"
        "+        not_in: [get_balance, list_payees, transfer]\n"
        "     action: pause\n"
        "     severity: critical\n"
        "     risk_class: money\n"
        f"--- a/{base}/agents/payments/manifest.yaml\n"
        f"+++ b/{base}/agents/payments/manifest.yaml\n"
        "@@ -27,10 +27,6 @@\n"
        "     risk_class: read_only\n"
        "     description: List saved payees of a customer.\n"
        "     args: {customer_id: string}\n"
        "-  - name: add_payee\n"
        "-    risk_class: pii_export\n"
        "-    description: Add a new payee (name, bank code, account number) for a customer.\n"
        "-    args: {customer_id: string, payee_name: string, bank_code: string, "
        "account_number: string}\n"
        "   - name: transfer\n"
        "     risk_class: money\n"
        "     description: Domestic transfer from a customer account to a saved payee. "
        "Amount in VND minor units.\n"
    )
    assert got["payments"]["diff"] == want
    # the whole generated document is pinned too (YAML patch + CLI text)
    golden = FIX / "expected_suggestion.yaml"
    text = ts.render_yaml(
        sug, as_of=END, window_days=30, diff_name="least_privilege_2026-10-20.diff"
    )
    assert text == golden.read_text(encoding="utf-8")
    assert text.isascii()


def test_patched_policy_parses_and_matches_proposal(rolled, tmp_path) -> None:
    sug = _by_agent(_build(rolled))
    for agent, rule in (("payments", "PAY-07"), ("customer_service", "SVC-07")):
        old = (POLICIES / "baseline.yaml").read_text(encoding="utf-8")
        new = ts.patch_rule_list(old, rule, sug[agent]["remove"])
        assert new is not None
        (tmp_path / "baseline.yaml").write_text(new, encoding="utf-8")
        policy = load_policy_dir(tmp_path)  # still a valid policy
        assert ts.allow_rules(policy, agent) == [(rule, sug[agent]["proposed"])]


def test_suggestion_never_edits_files(rolled, settings, tmp_path) -> None:
    files = [*POLICIES.glob("*.yaml"), *AGENTS.glob("*/manifest.yaml")]
    before = {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    out = ts.write_all(
        rolled,
        settings,
        as_of=END,
        out_dir=tmp_path / "o",
        policy_dir=POLICIES,
        manifest_dir=AGENTS,
    )
    assert before == {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    names = sorted(Path(p).name for p in out["files"])
    assert names == ["least_privilege_2026-10-20.diff", "least_privilege_2026-10-20.yaml"]
    doc = yaml.safe_load(Path(out["files"][0]).read_text(encoding="utf-8"))
    assert doc["status"] == "SUGGESTION - NOT APPLIED"
    assert Path(out["files"][1]).read_text(encoding="utf-8").startswith("--- a/")


@pytest.mark.parametrize(
    ("agent", "tool", "last_day_back", "unused_below", "used_from"),
    [("payments", "add_payee", 40, 40, 41), ("customer_service", "open_dispute", 45, 45, 46)],
)
def test_window_boundary(rolled, agent, tool, last_day_back, unused_below, used_from) -> None:
    """The tool was last called ``last_day_back`` days before the end. A window of N days
    covers END-N+1 .. END, so the tool is used from N = last_day_back + 1."""
    s = _by_agent(_build(rolled, days=unused_below))[agent]
    assert tool in s["remove"]
    s = _by_agent(_build(rolled, days=used_from))[agent]
    assert tool not in s["remove"]
    status = {e["tool"]: e["status"] for e in s["tools"]}
    assert status[tool] == "used"
    last = next(e for e in s["tools"] if e["tool"] == tool)["last_seen"]
    assert last.date() == END - timedelta(days=last_day_back)


def test_as_of_moves_the_window(rolled) -> None:
    # 20 days earlier add_payee was still in use in the last 30 days
    early = _by_agent(_build(rolled, as_of=END - timedelta(days=20)))["payments"]
    assert "add_payee" not in early["remove"]
    assert early["window_from"] == (END - timedelta(days=49)).isoformat()


def _rows(tool_calls: dict[str, int], day: date = END):
    return [
        {
            "usage_date": day, "agent_id": "a", "tool_name": t, "risk_class": None, "calls": n,
            "allows": n, "blocks": 0, "pauses": 0, "errors": 0, "p50_us": 5, "p95_us": 9,
            "distinct_callers": 1, "distinct_users": 1, "first_seen": None, "last_seen": None,
        }
        for t, n in tool_calls.items()
    ]  # fmt: skip


def _pure(rows, *, rules=(("A-07", ("t_read", "t_money", "t_pii", "t_credit", "t_used")),),
          exceptions=(), history=date(2026, 1, 1), min_hist=14, manifest=()):  # fmt: skip
    return ts.build_suggestion(
        "a",
        window_rows=rows,
        history_first_day=history,
        policy_rules=rules,
        manifest_tools=manifest,
        risk={
            "t_read": "read_only",
            "t_money": "money",
            "t_pii": "pii_export",
            "t_credit": "credit",
            "t_used": "read_only",
        },  # fmt: skip
        exceptions=exceptions,
        as_of=END,
        window_days=30,
        min_history_days=min_hist,
    )


def test_risky_and_unused_come_first() -> None:
    s = _pure(_rows({"t_used": 5}))
    assert [e["tool"] for e in s["tools"]] == ["t_money", "t_credit", "t_pii", "t_read", "t_used"]
    assert s["remove"] == ["t_money", "t_credit", "t_pii", "t_read"]
    assert s["proposed"] == ["t_used"]


def test_documented_exception_keeps_tool_until_it_expires() -> None:
    def exc(expires):
        return [
            {
                "agent_id": "a", "tool": "t_money", "reason": "quarterly batch",
                "approver": "risk.lead", "expires": expires,
            }
        ]  # fmt: skip

    for expires, kept in (
        (END, True),
        (END + timedelta(days=1), True),
        (END - timedelta(days=1), False),
    ):
        s = _pure(_rows({"t_used": 1}), exceptions=exc(expires))
        assert ("t_money" not in s["remove"]) is kept
        st = {e["tool"]: e["status"] for e in s["tools"]}
        assert st["t_money"] == ("exception" if kept else "unused")
    other_agent = [{**exc(END)[0], "agent_id": "b"}]
    assert "t_money" in _pure(_rows({"t_used": 1}), exceptions=other_agent)["remove"]


def test_undeclared_tools_are_flagged_not_added() -> None:
    s = _pure(_rows({"t_used": 1, "t_new": 4}))
    assert [e["tool"] for e in s["undeclared"]] == ["t_new"]
    assert "t_new" not in s["proposed"] and "t_new" not in s["remove"]
    assert any("t_new" in w for w in s["warnings"])


def test_confidence_low_and_no_data() -> None:
    low = _pure(_rows({"t_used": 1}), history=END - timedelta(days=5))
    assert low["confidence"] == "low" and low["remove"]
    assert any("low confidence" in w for w in low["warnings"])
    none = _pure([])
    assert (
        none["confidence"] == "no_data"
        and none["remove"] == []
        and none["proposed"] == none["current"]
    )
    ok = _pure(_rows({"t_used": 1}), history=END - timedelta(days=13))
    assert ok["confidence"] == "ok"  # 14 days of history including the first and the last day


def test_all_unused_warns_about_retiring() -> None:
    s = _pure(_rows({"t_other": 1}))
    assert s["proposed"] == [] and any("retiring" in w for w in s["warnings"])


def test_two_allow_rules_use_the_intersection() -> None:
    s = _pure(_rows({"x": 1}), rules=(("R1", ("x", "y", "z")), ("R2", ("x", "z"))))
    assert s["current"] == ["x", "z"] and s["remove"] == ["z"]


def test_manifest_is_the_fallback_declaration() -> None:
    s = _pure(_rows({"m1": 2}), rules=(), manifest=("m1", "m2"))
    assert s["declared_source"] == "manifest" and s["remove"] == ["m2"] and s["rule_ids"] == []


def test_patch_rule_list_edge_cases() -> None:
    text = (
        "rules:\n"
        "  - id: R-1\n"
        "    version: 3\n"
        "    when:\n"
        "      tool:\n"
        "        not_in: ['a', \"b\", c]  # note\n"
        "  - id: R-2\n"
        "    version: 1\n"
        "    when:\n"
        "      tool:\n"
        "        not_in:\n"
        "          - a\n"
    )
    patched = ts.patch_rule_list(text, "R-1", ["b"])
    assert "not_in: ['a', c]  # note" in patched and "version: 4" in patched
    assert "version: 1" in patched  # R-2 is untouched
    assert ts.patch_rule_list(text, "R-2", ["a"]) is None  # block style: by hand
    assert ts.patch_rule_list(text, "R-9", ["a"]) is None
    assert ts.patch_manifest_text("tools:\n  - name: a\n    x: 1\n  - name: b\n", ["zz"]) is None
    out = ts.patch_manifest_text("tools:\n  - name: a\n    x: 1\n\n  - name: b\n    y: 2\n", ["a"])
    assert out == "tools:\n\n  - name: b\n    y: 2\n"


def test_exceptions_file_is_validated(tmp_path) -> None:
    p = tmp_path / "e.yaml"
    assert ts.load_exceptions(tmp_path / "missing.yaml") == []
    p.write_text(
        "exceptions:\n  - {agent_id: a, tool: t, reason: r, approver: x, expires: 2027-01-31}\n"
    )
    (e,) = ts.load_exceptions(p)
    assert e["expires"] == date(2027, 1, 31)
    p.write_text("exceptions:\n  - {agent_id: a, tool: t}\n")
    with pytest.raises(AnalyticsError):
        ts.load_exceptions(p)
    p.write_text("exceptions: [")
    with pytest.raises(AnalyticsError):
        ts.load_exceptions(p)


def test_unknown_agent_is_a_user_error(rolled) -> None:
    with pytest.raises(AnalyticsError):
        _build(rolled, agent_id="nope")


def test_repo_baseline_allow_lists_match_the_manifests() -> None:
    """The three real allow-list rules exist and name only tools of their manifest, so the
    suggestion has a declared set for every demo agent."""
    from supervisor.analytics.tools_suggest import POLICY_DIR

    policy = load_policy_dir(POLICY_DIR)
    for agent, rule in (
        ("payments", "PAY-07"),
        ("customer_service", "SVC-07"),
        ("credit_prequal", "CRD-07"),
    ):
        ((rid, tools),) = ts.allow_rules(policy, agent)
        assert rid == rule and tools


def test_combined_diff_applies_every_agent_to_one_file(rolled, tmp_path) -> None:
    sug = _build(rolled)
    text = ts.combined_diff(sug)
    assert text.count("--- a/tests/fixtures/tool_analytics/policies/baseline.yaml") == 1
    assert text.count("+++ b/") == 3  # baseline + payments manifest + customer_service manifest
    # replay the policy part of the patch the way a human tool would: all edits on one file
    old = (POLICIES / "baseline.yaml").read_text(encoding="utf-8")
    new = old
    by = _by_agent(sug)
    new = ts.patch_rule_list(new, "PAY-07", by["payments"]["remove"])
    new = ts.patch_rule_list(new, "SVC-07", by["customer_service"]["remove"])
    (tmp_path / "baseline.yaml").write_text(new, encoding="utf-8")
    policy = load_policy_dir(tmp_path)
    assert ts.allow_rules(policy, "payments")[0][1] == by["payments"]["proposed"]
    assert ts.allow_rules(policy, "customer_service")[0][1] == by["customer_service"]["proposed"]
    assert {r.id: r.version for r in policy.rules if r.id.endswith("-07")} == {
        "PAY-07": 2, "SVC-07": 2, "CRD-07": 1,
    }  # fmt: skip


# --------------------------------------------------------------------------- review fixes


PAY07_LIST = "        not_in: [get_balance, list_payees, add_payee, transfer]\n"


def _policy_copy(tmp_path, old: str, new: str) -> Path:
    text = (POLICIES / "baseline.yaml").read_text(encoding="utf-8")
    assert old in text
    d = tmp_path / "pol"
    d.mkdir()
    (d / "baseline.yaml").write_text(text.replace(old, new), encoding="utf-8")
    return d


def test_patch_refuses_an_edit_it_cannot_make_exactly() -> None:
    """A text edit that would not equal the intended structural edit gives None (a human
    edits the rule) instead of a wrong diff."""
    bracket = "rules:\n  - id: R-1\n    version: 3\n    when:\n      tool:\n" + (
        "        not_in: [a, b]  # see [doc]\n"
    )
    assert ts.patch_rule_list(bracket, "R-1", ["b"]) is None  # was: version bumped, b kept
    last_block = (
        "rules:\n  - id: R-1\n    version: 1\n    when:\n      tool:\n        not_in:\n"
        "          - a\n          - b\nother:\n  x:\n    not_in: [a, b]\n"
    )
    assert ts.patch_rule_list(last_block, "R-1", ["b"]) is None  # never edits "other"
    assert ts.verify_rule_patch(bracket, bracket, "R-1", ["b"]) is False
    m = "tools:\n  - name: a\n    x: 1\n  - name: b\n"
    assert ts.verify_manifest_patch(m, "tools:\n  - name: b\n", ["a"]) is True
    assert ts.verify_manifest_patch(m, "tools: []\n", ["a"]) is False


def test_rule_shared_with_other_agents_gets_no_diff() -> None:
    s = {
        "agent_id": "payments", "remove": ["add_payee"], "rule_ids": ["PAY-07"],
        "rule_scopes": {"PAY-07": ["customer_service", "payments"]},
        "manifest_tools": ["add_payee"], "warnings": [],
    }  # fmt: skip
    out = ts.attach_diff(s, POLICIES, AGENTS)
    assert out["diff"] == "" and out["_manifest_path"] is None and out["_rule_files"] == {}
    assert any("NO DIFF" in w and "more agents" in w for w in out["warnings"])
    assert ts.combined_diff([out]) == ""


def test_unpatchable_rule_withholds_the_whole_agent_diff(rolled, tmp_path) -> None:
    block = "        not_in:\n" + "".join(
        f"          - {t}\n" for t in ("get_balance", "list_payees", "add_payee", "transfer")
    )
    pol = _policy_copy(tmp_path, PAY07_LIST, block)
    by = _by_agent(_build(rolled, policy_dir=pol))
    pay = by["payments"]
    assert pay["remove"] and pay["diff"] == "" and pay["manifest_file"] is None
    assert any(w.startswith("NO DIFF") for w in pay["warnings"])
    text = ts.combined_diff(list(by.values()))
    assert "payments/manifest.yaml" not in text  # no manifest edit without the policy edit
    assert "customer_service/manifest.yaml" in text


def test_conditional_allow_list_is_not_a_declaration(tmp_path) -> None:
    cond = PAY07_LIST + "      all:\n        - {arg: amount_minor, op: gt, value: 0}\n"
    policy = load_policy_dir(_policy_copy(tmp_path, PAY07_LIST, cond))
    assert ts.allow_rules(policy, "payments") == []


def test_stale_rollup_lowers_confidence(rolled) -> None:
    pay = _by_agent(_build(rolled, as_of=END + timedelta(days=5)))["payments"]
    assert pay["confidence"] == "low"
    assert any("stale" in w for w in pay["warnings"])
    fresh = _by_agent(_build(rolled, as_of=END + timedelta(days=2)))["payments"]
    assert not any("stale" in w for w in fresh["warnings"])
