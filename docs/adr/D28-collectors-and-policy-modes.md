# D28: Collectors, observe mode and per-consumer policy

Status: accepted for WP38 (phase 3, wave 2). Flag `COLLECTORS_ENABLED` (console catalogue), off by
default. The policy keys need no flag. D24 to D27 belong to other work packages; D23 (WP37) is the
highest number on this branch.

## Context

Attaching an agent meant reading `docs/INTEGRATION_GUIDE.md` and writing glue. The gate also had
one stop switch per agent (the SHADOW state) and no way to say "watch only" per policy or "this
channel is different". The bank will ask for both. Owner decisions of 2026-10-20: collector order
Python SDK, LangGraph middleware, MCP proxy first; policy source of truth stays YAML in git.

## Decision

1. **Catalogue in code** (`collectors/catalog.py`): eight templates with our own text. Served to
   the console; placeholders `<SUPERVISOR_URL>` and `<AGENT_ID>` are filled after the key exists,
   after a check of both values. The secret is never in a snippet.
2. **Adapters share one client** (`gateway/adapters/common.py`). Ids from a framework are cleaned
   or dropped, payloads are capped, the fail mode is closed by default, money, credit and
   pii_export tools are closed whatever the mode, transforms replace the whole payload.
   Frameworks are imported lazily; they are not dependencies.
3. **SDK change, additive:** `HttpGate.check_v2` and `InProcessGate.check_v2` add `direction` and
   `correlation_id`. `check` keeps its signature (a test pins it). `direction` is sent only when it
   is `output`; the header only when set. An older server is unaffected.
4. **Console Add uses the WP20 file flow** and a new permission `collectors.add` (admin,
   operator). The secret passes through the browser once, which the Credentials page avoided for
   rotation; the owner asked for this flow. Rotation stays on the command line.
5. **Observe mode.** `agents.<id>.mode: enforce | observe`. In observe a rule block or pause, and
   `GATE-DETECTOR-FAILED`, become a report; the original is kept in `observed_decision`. The
   legacy `action` is `log` (not `report`) because `supervisor_agents.common.gate` rejects unknown
   actions and fails closed; `status` is `report` where v2 exists. State blocks and
   `GATE-REDACTION` stay blocks. SHADOW keeps precedence.
6. **Per-consumer override** `agents.<id>.consumers.<id>` (mode, detectors, rules), resolved as
   `consumers[context.consumer_id] ?? agent`. An invalid or unknown id gives the agent's settings.
   A consumer cannot switch off a money or credit block or pause rule (load error).
7. **Hash stability.** Unset keys are left out of the policy dump, so a file without the new keys
   keeps its `policy_hash` (test pins the baseline policy's hash).
8. **Gate order words** are documented in `docs/policy.md` as the engine does them: fixed order
   pause, block, alert, log, then severity, then id; not file order.

## Consequences

* Existing answers, rows and hashes do not change for agents that use none of the new keys.
* `consumer_id` is asserted by the caller. With ingress auth the agent is authenticated, but the
  consumer id inside is not. An agent that is compromised can name a lenient consumer. Mitigations:
  the guard of item 6, the id and mode are in every decision, the chain and the SIEM event, and
  overrides are reviewed in git like any rule.
* Observe mode on a money agent needs `initial_state: SHADOW` or two `observe_approvals`; only
  the approvals let observe lift a decision on a money, credit or pii_export tool. A consumer of a
  money agent cannot be in observe mode, and a consumer detector override never applies to those
  tools (WP38 review, owner question 1 decided).
* The `agent_event` row has no column for the observed decision; the `verdict` rows (label
  `observe_would_*`), the chain and the SIEM carry it. A column can come with WP39.

## Open questions

See `HANDOFF_WP38.md` (observe for consumers on money tools, `skip` handling, file order wording).
