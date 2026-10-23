# Policy semantics: gate order, observe mode, consumers (WP38)

The policy source of truth is YAML in git (`policies/*.yaml`, schema `policies/schema.json`).
This page says in plain words what the gate does with it. Every sentence in section 2 has a test
in `tests/gateway/test_wp38_policy.py` (the test name starts with `test_order_`).

## 1. The keys WP38 adds

```yaml
agents:
  payments:
    mode: observe            # enforce (default) | observe
    observe_approvals: [risk.lead, compliance.officer]   # needed: payments has money rules
    rule_approvals: [risk.lead, compliance.officer]      # needed to disable a money block rule
    rules: {disable: [PAY-09]}            # switch single rules off (or on, see below)
    consumers:                            # per-consumer override, key = context.consumer_id
      web-banking: {mode: enforce}
      call-centre:
        detectors: {preset: lenient}      # same shape as agents.<id>.detectors (WP37)
        rules: {disable: [SVC-04], enable: [PAY-09]}
```

* `mode` is per agent, and a consumer may override it.
* `consumers.<consumer_id>` may set `mode`, `detectors` and `rules` (`enable`, `disable`). A consumer `detectors` block may not name `dlp_vn.keep_args` (WP41: an agent setting, audited when the policy loads, refused by the loader; see `docs/detectors.md` section 3b).
* `keep_args_approvals` (WP41 review): two distinct approver ids, needed when `detectors.settings.dlp_vn.keep_args` names a money, credit or pii_export tool. Left out of the hash when empty.
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

Safety guards (WP38 review; the consumer id is asserted by the caller, so it must not be a way
around the money controls). A *money agent* is an agent with at least one rule in scope whose risk
class is `money`, `credit` or `pii_export`.

| Guard | Where |
|---|---|
| A consumer may not switch off a `block` or `pause` rule of risk class `money`, `credit` or `pii_export` | load error |
| No consumer may set `mode: observe`, on any agent (the id is asserted by the caller; observe is set on the agent) | load error |
| `rules.disable` on an agent that names a `block` or `pause` rule of risk class `money`, `credit` or `pii_export` needs two distinct ids in `rule_approvals` | load error |
| `mode: observe` on a money agent needs `initial_state: SHADOW` or two distinct ids in `observe_approvals` | load error |
| Observe lifts a decision on a `money`, `credit` or `pii_export` tool only when the agent has `observe_approvals` (so a SHADOW agent without them is enforced on those tools once it runs) | gate |
| A consumer's `detectors` block never applies to a call of a `money`, `credit` or `pii_export` tool; the agent's block applies | gate |
| `observe_approvals` and `rule_approvals`, like `mode`, are left out of the dump when unset (hash unchanged) | loader |

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
   `alert`, `block` and `pause`. State blocks (step 1) and `GATE-REDACTION` stay blocks, and so
   does `GATE-DETECTOR-FAILED` on a `pii_export` tool. A rule block is lifted before the
   redaction and the detectors run, so an observed call still gets its masked arguments; its
   status is then `transform`, not `report`. On `money`, `credit` and `pii_export` tools observe
   acts only for an agent with `observe_approvals` (section 1). A rule that cannot be evaluated
   (fail closed) counts as a block from that rule.
8. **SHADOW keeps precedence.** An agent in the SHADOW state is never stopped, whatever its mode.
   Its decision is the SHADOW one (`action: log`, reason `shadow: would block ...`) and has no
   `observed_decision`.

The answer's `consumer_id` is the **resolved** id: it is present only when the policy has an entry
for the id the caller sent (`Decision.consumer_id` in the engine). The raw value of the caller is
never copied into it; an invalid or unknown id gives `consumer_ignored: true` and no `consumer_id`.
A recorder that wants the consumer of a decision should store this field, not `context.consumer_id`.
The chain record of an observed decision also holds `observe_approved` (true when the agent has two
`observe_approvals`); the SIEM event has it as an attribute.

## 3. What is recorded in observe mode

| Place | Content |
|---|---|
| Answer | `allow: true`, `action: log`, `status: report`, `mode: observe`, `observed_decision`, `consumer_id` |
| `verdict` rows | the matched rule with action `log` and label `observe_would_block` or `observe_would_pause`; a lifted `GATE-DETECTOR-FAILED` gets its own row with that label (WP39 AL-THREAT-NOT-ENFORCED reads these rows) |
| Console Decisions drawer | "Observed decision" line on the Details tab, label on the Rules tab |
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

## 5. Several policy folders and policy reload (WP-P2)

### `POLICY_DIR` with several folders

`POLICY_DIR` may list several folders, separated by the OS path separator (`;` on Windows, `:` on
Linux). Example (Windows): `POLICY_DIR=C:\sup\policies;C:\cands\a1\policy`.

* The folders load in the order given. Each file gets the same validation as today.
* Tools, agents, reviewers and admins merge as inside one folder (the same tool with two risk
  classes, or the same agent with different values, is a load error).
* A later folder cannot define a rule id that an earlier folder defines. This is a load error
  that names the rule and both folders.
* An empty later folder is a load error.
* The policy hash covers the merged document, so it covers all folders. The order of folders does
  not change the hash.
* One folder behaves exactly as before (a test compares the hash with `load_policy_dir`).
* Some read-only helpers (analytics suggestions, risk and control refs) still read the first
  folder only.

### `POST /gate/policy/reload` (admin, needs `AGENTS_API_ENABLED=1`)

Reads the folders again from disk, validates them, deploys them to the rule table and switches
the gate to the new policy at once (no wait for the 5 second refresh). The chain gets a
`policy_reload` record: `old_policy_hash`, `new_policy_hash`, `changed`, `folders`, `rules`,
`inserted`, `retired`, `principal`, `ts`. Two `console_action` rows (permission `policy.reload`).

A load error (bad YAML, a schema error, a rule id defined twice across folders, a rule version
already deployed with other content, a detector override problem) answers HTTP 400 with the
reason, and the old policy stays in force. Nothing is written to the rule table in that case.

## 6. SHADOW and masking (WP-P2)

SHADOW observes decisions: a rule that would block or pause is logged, not enforced. Masking is
not a decision. With `DETECTORS_ENABLED=1` and `dlp_vn` in `transform` mode for the tool class, an
agent in SHADOW still gets the masked arguments in `transformed_args` and `transformed_payload`
with the shadow allow, so a collector can apply them and the tool and model never see the raw
value. The status of the verdict is `transform`. The WP24b inline redaction (without detectors)
is unchanged: it does not run in SHADOW.

## 7. Moving an agent from SHADOW to RUNNING

By API (`AGENTS_API_ENABLED=1`): `POST /gate/agents/{id}/state` with `{"to": "RUNNING", "reason":
"..."}`. It needs two different persons: the requester, then a second person with the reviewer
or approver role. The way back (`RUNNING` to `SHADOW`) needs one person with `systems.edit` or the
reviewer role. See `docs/api.md`.

Session monitor settings (WP-P2): `agents.<id>.monitors.session` is checked when the policy loads (also with `reload`), using the built-in defaults for fields left out. With `pause_scope` set, the findings weight must stay below `pause_threshold_bp`, and `pause_threshold_bp` must not be below `case_threshold_bp`. A bad block is a load error with the numbers in the message; it does not disable the session monitor at run time.

Reload and detectors (WP-P2): `POST /gate/policy/reload` swaps the rules, tools, agents and per-agent settings, and checks the new policy against the detector rules already in force. It does not rebuild the detector gate (`DETECTORS_CONFIG`, the guard model, document intake). A change of those needs a restart of the app.
