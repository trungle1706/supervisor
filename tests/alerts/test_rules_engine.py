"""WP21: alert rule loader (strict, no code) and the pure engine (windows, dedupe, suppression)."""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.alerts import (
    AlertConfigError,
    Signal,
    evaluate,
    load_rules,
    parse_rules,
)
from supervisor.config import REPO_ROOT

T0 = datetime(2026, 10, 19, 8, 0, 0, tzinfo=UTC)


def _rules(**over: Any) -> dict[str, Any]:
    rule = {
        "id": "AL-TEST-ONE",
        "title": "Test rule",
        "source": "gate_decision",
        "where": {"action": "block"},
        "group_by": "agent_id",
        "window_s": 600,
        "threshold": 3,
        "severity": "high",
        "dedupe_s": 1800,
        "routes": ["inbox"],
    }
    rule.update(over)
    return {"version": 1, "rules": [rule]}


def _sig(n: int, t: float, agent: str = "a1", action: str = "block") -> Signal:
    return Signal(
        sid=f"{agent}:{n}",
        kind="gate_decision",
        ts=T0 + timedelta(seconds=t),
        fields={"agent_id": agent, "action": action},
        lane=agent,
        seq=n,
        entry_hash=f"h{n}",
    )


def test_shipped_config_is_valid_and_complete() -> None:
    rs = load_rules(REPO_ROOT / "config" / "alerts.yaml")
    ids = {r.id for r in rs.rules}
    assert ids == {
        "AL-BLOCK-BURST",
        "AL-QUARANTINE",
        "AL-CHAIN-VERIFY-FAIL",
        "AL-JUDGE-ESCALATION",
        "AL-INGRESS-REJECT-BURST",
        "AL-FAILCLOSED-DRILL-FAIL",
        "AL-JOB-FAILURE",
    }
    for r in rs.rules:
        assert r.routes and r.severity and r.rule_hash and r.dedupe_s >= 0


def test_rule_hash_is_stable_and_changes_with_the_rule() -> None:
    a = parse_rules(_rules()).rules[0].rule_hash
    assert a == parse_rules(_rules()).rules[0].rule_hash
    assert a != parse_rules(_rules(threshold=4)).rules[0].rule_hash


@pytest.mark.parametrize(
    "over, needle",
    [
        ({"id": "bad id"}, "id must match"),
        ({"source": "nope"}, "source must be one of"),
        ({"severity": "urgent"}, "severity must be one of"),
        ({"routes": ["fax"]}, "routes must be"),
        ({"routes": []}, "routes must be"),
        ({"where": {"colour": "red"}}, "not a field of gate_decision"),
        ({"group_by": "job"}, "not a field of gate_decision"),
        ({"threshold": 0}, "threshold must be an integer"),
        ({"window_s": -1}, "window_s must be an integer"),
        ({"window_s": 0, "threshold": 2}, "threshold > 1 needs window_s > 0"),
        ({"surprise": 1}, "unknown key"),
        ({"title": ""}, "title must be"),
    ],
)
def test_bad_rules_are_refused_with_a_clear_message(over: dict[str, Any], needle: str) -> None:
    with pytest.raises(AlertConfigError, match=needle):
        parse_rules(_rules(**over))


def test_all_problems_are_reported_at_once() -> None:
    with pytest.raises(AlertConfigError) as ei:
        parse_rules(_rules(severity="x", routes=["y"], threshold=0))
    msg = str(ei.value)
    assert "severity" in msg and "routes" in msg and "threshold" in msg


def test_duplicate_ids_and_bad_suppressions() -> None:
    doc = _rules()
    doc["rules"].append(dict(doc["rules"][0]))
    with pytest.raises(AlertConfigError, match="duplicate id"):
        parse_rules(doc)
    doc = _rules()
    doc["suppressions"] = [
        {"rule_id": "AL-NOPE", "agent_id": "a", "until": "2026-01-01", "reason_code": "X"}
    ]
    with pytest.raises(AlertConfigError, match="suppressions"):
        parse_rules(doc)


def test_yaml_is_data_not_code(tmp_path: Path) -> None:
    """A YAML tag that would run code is refused by safe_load; expressions are plain text."""
    p = tmp_path / "a.yaml"
    p.write_text("version: 1\nrules: !!python/object/apply:os.system ['echo hi']\n", "utf-8")
    with pytest.raises(AlertConfigError, match="not valid YAML"):
        load_rules(p)
    p.write_text(
        textwrap.dedent(
            """
            version: 1
            rules:
              - {id: AL-X-ONE, title: t, source: gate_decision, severity: low,
                 where: {action: "__import__('os').system('x')"}}
            """
        ),
        "utf-8",
    )
    rs = load_rules(p)  # the string is only ever compared for equality
    assert rs.rules[0].where == (("action", ("__import__('os').system('x')",)),)
    assert not rs.rules[0].matches({"action": "block"})


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(AlertConfigError, match="cannot read"):
        load_rules(tmp_path / "none.yaml")


# --------------------------------------------------------------------------- engine


def test_threshold_and_window() -> None:
    rs = parse_rules(_rules())
    sigs = [_sig(i, i * 100.0) for i in range(3)]  # 3 in 200 s
    res = evaluate(rs, sigs)
    assert [(f.group_value, f.window_count) for f in res.fired] == [("a1", 3)]
    assert res.fired[0].first_ts == T0 and res.fired[0].trigger.sid == "a1:2"
    slow = [_sig(i, i * 400.0) for i in range(3)]  # 3 over 800 s: the window never holds 3
    assert evaluate(rs, slow).fired == []


def test_groups_are_independent() -> None:
    rs = parse_rules(_rules())
    sigs = [_sig(i, i * 10.0, agent=f"a{i % 2}") for i in range(4)]  # 2 each
    assert evaluate(rs, sigs).fired == []
    sigs += [_sig(10 + i, 100 + i, agent="a0") for i in range(2)]
    assert [f.group_value for f in evaluate(rs, sigs).fired] == ["a0"]


def test_dedupe_collapses_repeats_then_fires_again_after_the_window() -> None:
    rs = parse_rules(_rules(threshold=2, window_s=60, dedupe_s=1000))
    burst1 = [_sig(i, i * 5.0) for i in range(6)]
    burst2 = [_sig(20 + i, 1500 + i * 5.0) for i in range(4)]  # after the dedupe window
    res = evaluate(rs, burst1 + burst2)
    assert len(res.fired) == 2
    assert res.fired[0].suppressed_count == 4  # signals 2..5 of burst 1
    assert res.fired[1].suppressed_count == 2
    assert res.fired[1].ts > res.fired[0].ts + timedelta(seconds=1000)


def test_dedupe_zero_fires_every_time() -> None:
    rs = parse_rules(_rules(threshold=1, window_s=0, dedupe_s=0))
    assert len(evaluate(rs, [_sig(i, i) for i in range(5)]).fired) == 5


def test_window_zero_counts_only_the_signal_itself() -> None:
    rs = parse_rules(_rules(threshold=1, window_s=0, dedupe_s=100))
    res = evaluate(rs, [_sig(0, 0), _sig(1, 1)])
    assert (
        len(res.fired) == 1
        and res.fired[0].window_count == 1
        and res.fired[0].suppressed_count == 1
    )


def test_cursor_judges_each_signal_once_and_is_idempotent() -> None:
    rs = parse_rules(_rules(threshold=2, window_s=60, dedupe_s=1000))
    sigs = [_sig(i, i * 5.0) for i in range(6)]
    first = evaluate(rs, sigs[:3])
    assert len(first.fired) == 1 and first.cursor == (sigs[2].ts, sigs[2].sid)
    last = {first.fired[0].dedupe_key: first.fired[0].ts}
    second = evaluate(rs, sigs, cursor=first.cursor, last_fired=last)  # replays old signals
    assert second.fired == [] and second.judged == 3
    assert second.suppressed_existing == {"AL-TEST-ONE:a1": (3, sigs[5].ts)}
    third = evaluate(rs, sigs, cursor=second.cursor, last_fired=last)
    assert third.judged == 0 and third.suppressed_existing == {}


def test_result_is_independent_of_input_order() -> None:
    rs = parse_rules(_rules(threshold=2, window_s=60))
    sigs = [_sig(i, i * 7.0, agent=f"a{i % 3}") for i in range(30)]
    a = evaluate(rs, sigs)
    b = evaluate(rs, list(reversed(sigs)))
    assert [(f.alert_id, f.window_count, f.suppressed_count) for f in a.fired] == [
        (f.alert_id, f.window_count, f.suppressed_count) for f in b.fired
    ]


def test_policy_suppression_is_time_boxed_and_counted() -> None:
    doc = _rules(threshold=1, window_s=0, dedupe_s=0)
    doc["suppressions"] = [
        {
            "rule_id": "AL-TEST-ONE",
            "agent_id": "a1",
            "until": (T0 + timedelta(seconds=100)).isoformat().replace("+00:00", "Z"),
            "reason_code": "planned_test",
        }
    ]
    rs = parse_rules(doc)
    res = evaluate(rs, [_sig(0, 10), _sig(1, 50), _sig(2, 150), _sig(3, 20, agent="a2")])
    assert res.policy_suppressed == 2
    assert sorted((f.group_value, f.trigger.sid) for f in res.fired) == [
        ("a1", "a1:2"),
        ("a2", "a2:3"),
    ]


def test_only_rules_filter_and_alert_id_is_deterministic() -> None:
    doc = _rules()
    rs = parse_rules(doc)
    sigs = [_sig(i, i) for i in range(3)]
    a = evaluate(rs, sigs).fired[0].alert_id
    assert a == evaluate(rs, sigs).fired[0].alert_id
    assert evaluate(rs, sigs, only_rules={"OTHER"}).fired == []
    assert yaml.safe_dump(doc)  # the dict used above is plain data


# --------------------------------------------------------------------------- review fixes


def test_enabled_false_takes_the_rule_out_and_is_validated() -> None:
    rs = parse_rules(_rules(enabled=False))
    assert rs.rules == ()
    sigs = [_sig(i, i * 10.0) for i in range(5)]
    assert evaluate(rs, sigs).fired == []
    with pytest.raises(AlertConfigError, match="enabled must be true or false"):
        parse_rules(_rules(enabled="no"))
    # a suppression may still name the disabled rule
    doc = _rules(enabled=False)
    doc["suppressions"] = [
        {"rule_id": "AL-TEST-ONE", "agent_id": "*", "until": "2027-01-01T00:00:00Z",
         "reason_code": "planned_test"}
    ]  # fmt: skip
    assert len(parse_rules(doc).suppressions) == 1


def test_unknown_top_level_and_suppression_keys_are_errors() -> None:
    doc = _rules()
    doc["suppresion"] = []  # a typo must not silently drop the block
    with pytest.raises(AlertConfigError, match="unknown top-level key 'suppresion'"):
        parse_rules(doc)
    doc = _rules()
    doc["suppressions"] = [
        {"rule_id": "AL-TEST-ONE", "agent_id": "*", "until": "2027-01-01T00:00:00Z",
         "reason_code": "planned_test", "agnet": "x"}
    ]  # fmt: skip
    with pytest.raises(AlertConfigError, match="unknown key 'agnet'"):
        parse_rules(doc)
