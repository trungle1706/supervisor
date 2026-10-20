"""Alert rule engine (WP21, ADR D15, docs/alerts.md).

Declarative YAML rules (``config/alerts.yaml``) over gate decisions, state changes, verdicts,
scheduler job runs, chain verify results and ingress rejections. Evaluated by the scheduler
job ``alerts`` (``python -m supervisor.jobs.alerts``); dry run with
``python -m supervisor.alerts test <rule_id>``. An alert is a row in the ``alert`` table and
leaves through its routes (inbox, siem, webhook, pager). Alerts only inform: they never block,
pause or quarantine anything (R1).
"""

from supervisor.alerts.engine import EvalResult, FiredAlert, evaluate
from supervisor.alerts.rules import AlertConfigError, Rule, RuleSet, load_rules, parse_rules
from supervisor.alerts.service import AlertError, AlertService, Routes, build_routes
from supervisor.alerts.signals import Signal, load_signals, read_jsonl

__all__ = [
    "AlertConfigError",
    "AlertError",
    "AlertService",
    "EvalResult",
    "FiredAlert",
    "Routes",
    "Rule",
    "RuleSet",
    "Signal",
    "build_routes",
    "evaluate",
    "load_rules",
    "load_signals",
    "parse_rules",
    "read_jsonl",
]
