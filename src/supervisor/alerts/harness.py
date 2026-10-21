"""Evaluation harness for the alert rules (WP21; TEAM_BRIEF section 3).

    python -m supervisor.alerts.harness [--split dev|heldout|both] [--fixtures DIR] [--config FILE]
                                        [--write-baseline]

Runs the rule engine over a labelled fixture (``tests/fixtures/alerts``: 500 synthetic gate
decisions plus the other signal kinds, 6 planted incidents) and scores it the way a bank SOC
analyst and detection engineer would:

* precision: of the alerts raised, how many belong to a planted incident (a false alert costs
  analyst time and trust);
* recall: of the alerts a planted incident must raise, how many were raised (a miss is an
  incident nobody saw);
* dedupe: the number of repeats each alert absorbed equals the planted repeats (no flood, and
  no repeat lost);
* triage completeness: every alert carries what the analyst needs in under two minutes:
  rule id, severity, agent or group, window count and threshold, first and last time, and the
  chain lane, seq and entry hash of the trigger.

Numbers are integers (basis points, counts) with Wilson 95 percent intervals. Thresholds are
ILLUSTRATIVE until the bank SOC sets its own. No model is used, so there is no mock path,
no model card; the run is deterministic and takes well under a second.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from supervisor.alerts.engine import FiredAlert, evaluate
from supervisor.alerts.rules import RuleSet, load_rules
from supervisor.alerts.signals import read_jsonl

# ILLUSTRATIVE go / no-go thresholds in basis points (the fixture is small and synthetic).
THRESHOLDS_BP = {"precision": 10000, "recall": 10000, "dedupe_exact": 10000, "triage": 10000}
Z95 = 1.959964


def wilson_bp(successes: int, n: int) -> tuple[int, int]:
    """Wilson 95 percent interval of a proportion, in integer basis points."""
    if n <= 0:
        return (0, 10000)
    p = successes / n
    z2 = Z95 * Z95
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (
        max(0, math.floor((centre - half) * 10000)),
        min(10000, math.ceil((centre + half) * 10000)),
    )


def _bp(part: int, whole: int) -> int:
    return 10000 if whole == 0 else part * 10000 // whole


def triage_missing(a: FiredAlert) -> list[str]:
    """The triage fields an alert lacks (empty list = complete)."""
    t = a.trigger
    miss = []
    if not a.rule.id:
        miss.append("rule_id")
    if not a.rule.severity:
        miss.append("severity")
    if not (a.agent_id or a.group_value not in ("", "-")):
        miss.append("agent_or_group")
    if not (a.window_count >= 1 and a.rule.threshold >= 1):
        miss.append("window_counts")
    if a.first_ts is None or a.last_ts is None:
        miss.append("window_times")
    if not (t.lane and t.seq is not None and t.entry_hash) and t.kind not in ("verdict", "job_run"):
        miss.append("chain_ref")
    return miss


def score(ruleset: RuleSet, signals: list[Any], expected: dict[str, Any]) -> dict[str, Any]:
    res = evaluate(ruleset, signals)
    want: dict[tuple[str, str], int] = {}
    for inc in expected["incidents"]:
        for al in inc["alerts"]:
            want[(al["rule_id"], al["group"])] = int(al["suppressed"])
    got = {(f.rule.id, f.group_value): f for f in res.fired}
    # an alert that fired twice for the same (rule, group) counts as one hit and one false alert
    tp_keys = [k for k in want if k in got]
    extra = [f for f in res.fired if (f.rule.id, f.group_value) not in want]
    dup = len(res.fired) - len(got)
    tp = len(tp_keys)
    fp = len(extra) + dup
    fn_keys = [k for k in want if k not in got]
    precision = _bp(tp, tp + fp)
    recall = _bp(tp, len(want))
    dedupe_ok = sum(1 for k in tp_keys if got[k].suppressed_count == want[k])
    triage_ok = sum(1 for f in res.fired if not triage_missing(f))
    by_rule: dict[str, dict[str, int]] = {}
    for rid in sorted({r.id for r in ruleset.rules}):
        by_rule[rid] = {
            "expected": sum(1 for k in want if k[0] == rid),
            "fired": sum(1 for f in res.fired if f.rule.id == rid),
            "false_positive": sum(1 for f in extra if f.rule.id == rid),
            "missed": sum(1 for k in fn_keys if k[0] == rid),
        }
    matching = sum(
        1 for s in signals for r in ruleset.rules if s.kind == r.source and r.matches(s.fields)
    )
    suppressed = sum(f.suppressed_count for f in res.fired)
    metrics = {
        "precision_bp": precision,
        "precision_ci_bp": list(wilson_bp(tp, tp + fp)),
        "recall_bp": recall,
        "recall_ci_bp": list(wilson_bp(tp, len(want))),
        "dedupe_exact_bp": _bp(dedupe_ok, len(tp_keys)),
        "triage_complete_bp": _bp(triage_ok, len(res.fired)),
        "alerts_fired": len(res.fired),
        "alerts_expected": len(want),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": len(fn_keys),
        "matching_signals": matching,
        "suppressed_repeats": suppressed,
        "flood_ratio_x100": 0 if not res.fired else (matching * 100) // len(res.fired),
        # false alerts per signal read, upper bound of the 95 percent interval (n = all signals)
        "false_alert_rate_upper_bp": wilson_bp(fp, len(signals))[1],
        "n_signals": len(signals),
        "n_gate_decisions": sum(1 for s in signals if s.kind == "gate_decision"),
    }
    verdicts = {
        "precision": "GO" if precision >= THRESHOLDS_BP["precision"] else "NO-GO",
        "recall": "GO" if recall >= THRESHOLDS_BP["recall"] else "NO-GO",
        "dedupe_exact": (
            "GO" if metrics["dedupe_exact_bp"] >= THRESHOLDS_BP["dedupe_exact"] else "NO-GO"
        ),
        "triage": "GO" if metrics["triage_complete_bp"] >= THRESHOLDS_BP["triage"] else "NO-GO",
    }
    return {
        "metrics": metrics,
        "verdicts": verdicts,
        "failure_taxonomy": {
            "false_negative": [{"rule_id": r, "group": g} for r, g in fn_keys],
            "false_positive": [{"rule_id": f.rule.id, "group": f.group_value} for f in extra],
            "duplicate_alert": dup,
            "triage_gaps": {f.alert_id: triage_missing(f) for f in res.fired if triage_missing(f)},
        },
        "by_rule": by_rule,
        "thresholds_bp": THRESHOLDS_BP,
        "thresholds_note": "ILLUSTRATIVE until the bank SOC sets them",
    }


def run_split(fixtures: Path, split: str, ruleset: RuleSet) -> dict[str, Any]:
    signals = read_jsonl(fixtures / f"{split}.signals.jsonl")
    expected = json.loads((fixtures / f"{split}.expected.json").read_text(encoding="utf-8"))
    out = score(ruleset, signals, expected)
    out["split"] = split
    out["rules_config_hash"] = ruleset.config_hash
    return out


def default_fixtures() -> Path:
    from supervisor.config import REPO_ROOT

    return REPO_ROOT / "tests" / "fixtures" / "alerts"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.alerts.harness", description=__doc__)
    ap.add_argument("--split", choices=("dev", "heldout", "both"), default="both")
    ap.add_argument("--fixtures", help="fixture folder (default: tests/fixtures/alerts)")
    ap.add_argument("--config", help="alerts.yaml (default: config/alerts.yaml)")
    ap.add_argument("--write-baseline", action="store_true", help="rewrite baseline.json")
    ap.add_argument(
        "--no-drills", action="store_true", help="skip the WP39 drills of the nine use cases"
    )
    args = ap.parse_args(argv)
    from supervisor.config import REPO_ROOT

    fixtures = Path(args.fixtures) if args.fixtures else default_fixtures()
    ruleset = load_rules(Path(args.config) if args.config else REPO_ROOT / "config" / "alerts.yaml")
    splits = ("dev", "heldout") if args.split == "both" else (args.split,)
    results = {s: run_split(fixtures, s, ruleset) for s in splits}
    bad = 0
    for s, r in results.items():
        m = r["metrics"]
        print(
            f"[{s}] signals={m['n_signals']} decisions={m['n_gate_decisions']} "
            f"alerts={m['alerts_fired']}/{m['alerts_expected']} "
            f"precision={m['precision_bp']}bp {m['precision_ci_bp']} "
            f"recall={m['recall_bp']}bp {m['recall_ci_bp']} "
            f"dedupe_exact={m['dedupe_exact_bp']}bp triage={m['triage_complete_bp']}bp "
            f"flood_ratio_x100={m['flood_ratio_x100']}"
        )
        for name, v in r["verdicts"].items():
            print(f"    {name}: {v}")
            bad += v != "GO"
    if args.write_baseline:
        (fixtures / "baseline.json").write_text(
            json.dumps(
                {
                    "note": "Recorded by `python -m supervisor.alerts.harness --write-baseline`. "
                    "tests/alerts/test_harness.py fails if a metric drops below this.",
                    "date": "2026-10-20",
                    "base_commit": "bf3a23a",
                    "branch": "WP21",
                    "results": results,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print("[OK] wrote baseline.json")
    if not args.no_drills:  # WP39: fire, quiet, suppress, SIEM correlation id, rate sweeps, storm
        from supervisor.alerts import drills

        result = drills.run_all(ruleset)
        for line in drills.render(result):
            print(line)
        bad += 0 if result["go"] else 1
    print("[OK] all GO" if not bad else f"[FAIL] {bad} NO-GO verdict(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
