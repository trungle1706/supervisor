"""CLI: validate and dry-run alert rules (WP21). ASCII output, no writes.

    python -m supervisor.alerts list [--config FILE]
    python -m supervisor.alerts validate [--config FILE]
    python -m supervisor.alerts test RULE_ID [--config FILE] [--signals FILE.jsonl | --since-s N]

``test`` evaluates ONE rule over signals and prints the alerts it would raise: from a fixture
file (``--signals``) or from the live store (last ``--since-s`` seconds, default 3600). It
reads only; it stores nothing, sends nothing and writes no evidence. Exit 0 = the rule exists
and ran; 1 = bad config or unknown rule.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from datetime import timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from supervisor.alerts.engine import evaluate  # noqa: E402
from supervisor.alerts.rules import AlertConfigError, RuleSet, load_rules  # noqa: E402
from supervisor.alerts.signals import Signal, load_signals, read_jsonl  # noqa: E402
from supervisor.config import load_settings  # noqa: E402
from supervisor.core.canonical import format_ts  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.monitors.jobctx import ascii_line  # noqa: E402


class _NoEvidence:
    """The dry run writes nothing: an evidence sink that refuses."""

    def record(self, record_type: str, record_ref: str, payload: object) -> str:
        raise AssertionError("the dry run must not write evidence")


def _config_path(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    return load_settings().alerts_config


def _live_signals(since_s: int) -> list[Signal]:
    from supervisor.adapters.factory import build_adapters
    from supervisor.monitors.common import MonitorContext

    settings = load_settings()
    adapters = build_adapters(settings)
    try:
        ctx = MonitorContext.from_adapters(adapters, _NoEvidence())  # type: ignore[arg-type]
        now = ctx.clock.now()
        return load_signals(ctx, now - timedelta(seconds=since_s), now + timedelta(seconds=1))
    finally:
        adapters.close()


def _list(ruleset: RuleSet) -> None:
    print(f"config {ruleset.config_hash[:12]}: {len(ruleset.rules)} rule(s)")
    for r in ruleset.rules:
        where = ",".join(f"{k}={'|'.join(map(str, v))}" for k, v in r.where) or "-"
        print(
            ascii_line(
                f"  {r.id:<26} {r.severity:<8} {r.source}[{where}] by {r.group_by} "
                f">={r.threshold}/{r.window_s}s dedupe {r.dedupe_s}s -> {','.join(r.routes)}"
            )
        )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.alerts", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "validate", "test"):
        p = sub.add_parser(name)
        p.add_argument("--config", help="alerts.yaml (default: ALERTS_CONFIG)")
        if name == "test":
            p.add_argument("rule_id")
            g = p.add_mutually_exclusive_group()
            g.add_argument("--signals", help="fixture JSONL of signals instead of the live store")
            g.add_argument("--since-s", type=int, default=3600, help="live store window")
    args = ap.parse_args(argv)
    try:
        ruleset = load_rules(_config_path(args.config))
    except (AlertConfigError, SupervisorError) as exc:
        print(ascii_line(f"[FAIL] {exc}"))
        return 1
    if args.cmd == "validate":
        print(f"[OK] {len(ruleset.rules)} rule(s), {len(ruleset.suppressions)} suppression(s)")
        return 0
    if args.cmd == "list":
        _list(ruleset)
        return 0
    rule = ruleset.get(args.rule_id)
    if rule is None:
        print(
            f"[FAIL] unknown rule {args.rule_id!r}; known: {', '.join(r.id for r in ruleset.rules)}"
        )
        return 1
    try:
        signals = read_jsonl(Path(args.signals)) if args.signals else _live_signals(args.since_s)
    except (OSError, ValueError, KeyError, SupervisorError) as exc:
        print(ascii_line(f"[FAIL] cannot read signals: {type(exc).__name__}: {exc}"))
        return 1
    res = evaluate(ruleset, signals, only_rules={rule.id})
    matching = sum(1 for s in signals if s.kind == rule.source and rule.matches(s.fields))
    print(
        f"rule {rule.id}: {len(signals)} signal(s) read, {matching} match(es), "
        f"threshold {rule.threshold} in {rule.window_s}s, dedupe {rule.dedupe_s}s"
    )
    for f in res.fired:
        print(
            ascii_line(
                f"  would fire: group={f.group_value} at {format_ts(f.ts)} "
                f"count={f.window_count}/{f.rule.threshold} first={format_ts(f.first_ts)} "
                f"trigger={f.trigger.sid} repeats_suppressed={f.suppressed_count}"
            )
        )
    if res.policy_suppressed:
        print(f"  {res.policy_suppressed} candidate(s) dropped by a suppression entry")
    print(f"[OK] {len(res.fired)} alert(s) would be raised (dry run, nothing stored or sent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
