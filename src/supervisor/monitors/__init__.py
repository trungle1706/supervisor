"""Monitors (WP7): drift, fairness, quality, multi-agent pattern, oversight metrics.

Every monitor is domain code: it reads ``agent_event`` / ``verdict`` through the ports,
writes rows through ``TableStore`` / ``StateStore`` and records evidence through
``EvidenceSink``. Integers only in evidence (basis points, minor units, milliseconds).
The jobs in ``supervisor.jobs`` (drift, fairness, metrics, multiagent, judge_sweep) run
them, from the command line or from the in-process scheduler (``supervisor.scheduler``).
"""
