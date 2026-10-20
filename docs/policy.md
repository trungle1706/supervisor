# Policy semantics: gate order, observe mode, consumers (WP38)

The policy source of truth is YAML in git (`policies/*.yaml`, schema `policies/schema.json`).
This page says in plain words what the gate does with it. Every sentence in section 2 has a test
in `tests/gateway/test_wp38_policy.py` (the test name starts with `test_order_`).

## 1. The keys WP38 adds

```yaml
agents:
  payments:
    mode: observe            # enforce (default) | observe
    rules: {disable: [PAY-09]}            # switch single rules off (or on, see below)
    consumers:                            # per-consumer override, key = context.consumer_id
      web-banking: {mode: enforce}
      call-centre:
        mode: observe
        detectors: {preset: lenient}      # same shape as agents.<id>.detectors (WP37)
        rules: {disable: [SVC-04], enable: [PAY-09]}
```

* `mode` is per agent, and a consumer may override it.
* `consumers.<consumer_id>` may set `mode`, `detectors` and `rules` (`enable`, `disable`).
* A policy file that uses none of these keys has the same `policy_hash` as before (test).
  Files that use them need no flag: the keys only act when they are in the file.

### How a consumer override is resolved

`consumers[context.consumer_id] ?? agent`, field by field:

| Field | Result |
|---|---|
| `mode` | the consumer's value if set, else the agent's, else `enforce` |
| `detectors` | the consumer's block if set (it replaces the agent's block), else the agent's |
| `rules` | agent `disable`, minus the consumer's `enable`, plus the consumer's `disable` |

`consumer_id` comes from the request context. The SDK adapters and the middleware set it. It must
be 1 to 128 characters from `A-Za-z0-9_.:@-`. A value that is not a string, is too long or has
other characters is ignored: the agent's own settings apply, never an override. The same happens
for an id without an entry; the answer then shows `consumer_ignored: true`. The same rule
validates the keys in the policy file.

Safety guard: a consumer may not switch off a `block` or `pause` rule whose risk class is
`money` or `credit` (the policy fails to load). The consumer id is asserted by the caller, so it
must not be a way around the money controls. Setting `mode: observe` for a consumer is allowed;
see the open question in the ADR.

## 2. Gate order

1. **State first.** Before any rule: an unknown agent, a quarantined or retired agent, a paused
   agent (for tools that are not read-only), an unknown tool and a handoff without a caller id
   (when required) are blocked. These are state blocks. Observe mode does not lift them.
2. **Rules run in a fixed order.** Every rule in scope is evaluated: first `pause` rules, then
   `block`, then `alert`, then `log`; inside one action by severity (critical first), then by rule
   id. Rule files are merged and sorted, so the order of a file does not matter. Rules that are
   switched off for this agent or consumer are skipped. Every rule that matches is recorded.
3. **A report rule logs and continues.** A rule with action `log` or `alert` never stops a call.
   (Its hit is a `report` in the v2 status.)
4. **The first pause or block decides.** The first matching `pause` or `block` rule in the
   order of step 2 decides the answer (`pause` before `block`). A `pause` rule also pauses the
   agent. In the v2 status, `block` wins when a block rule matched as well (WP37 precedence
   `block > pause > transform > report > allow`).
5. **Skip.** `skip` is the verdict for a tool listed in `agents.<id>.detectors.skip_tools`: no
   detector runs for the call. It never hides a block or a pause, and observe mode does not
   change it. The policy loader refuses money, credit and pii_export tools there (also in a consumer override).
6. **Detectors run after the rules** (the work is done before the gate lock, and folded in after
   the rule decision exists). A detector can only add findings (status `report`), give a masked
   payload (status `transform`), or, when it cannot run on a money, credit or pii_export tool,
   cause the block `GATE-DETECTOR-FAILED`. A finding never blocks or pauses (R1).
7. **Observe mode.** In observe mode a `block` or `pause` decision from a rule, and the block
   `GATE-DETECTOR-FAILED`, become a `report`: the call is allowed, `observed_decision` keeps the
   original (allow, action, rule id, reason), the agent is not paused, and the status is
   `report`. The legacy `action` is `log`, because older clients only know `allow`, `log`,
   `alert`, `block` and `pause`. State blocks (step 1) and `GATE-REDACTION` stay blocks.
8. **SHADOW keeps precedence.** An agent in the SHADOW state is never stopped, whatever its mode.
   Its decision is the SHADOW one (`action: log`, reason `shadow: would block ...`) and has no
   `observed_decision`.

## 3. What is recorded in observe mode

| Place | Content |
|---|---|
| Answer | `allow: true`, `action: log`, `status: report`, `mode: observe`, `observed_decision`, `consumer_id` |
| `verdict` rows | the matched rule with action `log` and label `observe_would_block` or `observe_would_pause` |
| Evidence chain (`gate_decision`) | `mode`, `consumer_id`, `observed_decision` (action and rule id) next to `allow: true` |
| SIEM event | outcome `log`, attrs `mode`, `observed_action`, `observed_rule_id`, `consumer_id` |
| Metrics | counter `observe` |
| Playground dry run | `observed_decision` and the mode in the result; `would_pause` is false |

Answers of agents that use none of the new keys have none of the new fields.

## 4. Why a bank would use it

* `mode: observe` on a new agent shows what the rules would stop, with no outage. Switch it to
  `enforce` (a pull request, two reviewers) when the report is clean.
* A consumer override lets one channel (a pilot, a call centre) run in observe or with another
  detector preset while the rest stays strict.
