"""WP5 Judge: Tier 1 / Tier 2 LLM judges that only advise (ADR D06).

* ``prompts``  - data-wrapped prompt templates, canary token, strict JSON output schema.
* ``router``   - picks a ChatModel per tier, enforces judge family != agent family,
                 pins model ids, challenger sampling.
* ``tier1`` / ``tier2`` - one judge call each (masking, retries, truncation, timeouts).
* ``service``  - trace window -> Verdict rows + evidence; escalation; ControlArena-style
                 protocol (defer-to-trusted on disagreement, open_case after K flags).
* ``mockjudge`` - deterministic offline judge (MockChat) for tests, demo and eval.
* ``eval``     - eval harness (planted, benign, judge-injection, held-out sets).

Judges never call the gateway. Their actions are log | alert | open_case | raise_severity.
"""

from __future__ import annotations

ADVISORY_ACTIONS: frozenset[str] = frozenset({"log", "alert", "open_case", "raise_severity"})
