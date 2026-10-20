# Monitor bindings and monitor status (WP1b-B, ADR D20)

Four monitors read agent traffic: quality (groundedness of replies), fairness (approval-rate
gaps), drift (baseline bands) and multi-agent (split payment across callers). Until WP1b-B
each one knew three demo tool names (`reply`, `decide_prequal`, `transfer`) and one drift
window length. For any other agent it wrote nothing, and "on but silent" looked like "all
clear" (credit-memo benchmark, defect D06).

Now each agent can say which of its tools each monitor reads, and every monitor writes a
**status** for every agent it knows: it produced values, it cannot run (and why), or it has
nothing to compute yet.

## Status values

| Status | Meaning | Example `code` |
|---|---|---|
| `ok` | The monitor produced values for the agent today. `n` = items it read | - |
| `not_applicable` | No binding and none can be derived. `reason` names the missing tool or setting | `no_binding`, `no_attribute_source`, `no_versioned_events` |
| `no_data` | Binding exists, the window holds nothing to compute yet | `no_reply_calls`, `not_sampled`, `no_decisions`, `suppressed`, `collecting_baseline`, `no_band`, `no_events` |

Statuses are stored in `oversight_metric.monitor_status` (JSON column, one object per monitor)
on the (day, agent) row, and shown on the console Metrics page (section "Monitor status").
A status that did not change is not written again. Statuses are derived data and are not put
on the evidence chain.

## Where a binding comes from

For every field the first hit wins:

1. `policies/*.yaml` (or the `POLICY_DIR` folder when it is set, the same folder the gate reads), `agents.<id>.monitors` (the policy is the control surface),
2. the agent manifest `monitors:` key,
3. derived from the tool risk classes (below),
4. nothing: the monitor writes `not_applicable`.

```yaml
agents:
  memo_agent:
    name: Memo agent
    owner_user: lead@example.invalid
    owner_team: Credit Operations
    monitors:
      quality:
        reply_tools: [compose_memo]      # tools whose call text is the output to score
        text_arg: body                   # argument that holds the text (default: text)
      fairness:
        decision_tool: decide_limit      # the tool call that records approve / decline
        decision_arg: outcome            # default from config/fairness.yaml
        subject_arg: case_id
        approve_values: [granted]
        protected_attribute_keys: {gender: applicant_gender}   # attribute -> call argument
      split_payment:
        tool: release_funds              # money tool for the split-payment scan
        customer_key: payer_id           # hashed keys the gateway writes (default from_account_id)
        payee_key: beneficiary_id        # default payee_id
      drift:
        window_s: 3600                   # a young agent can use hourly windows
        baseline_windows: 3
        min_baseline_windows: 2
        min_n: 5
```

The binding model is strict (unknown keys fail at load), so a typo cannot switch a monitor off
silently. `ethnicity`, `religion` and the other forbidden attributes are rejected in
`protected_attribute_keys` (same list as `monitors/fairness.py`).

### Defaults derived from tool classes

| Monitor | Default when no binding | Not applicable when |
|---|---|---|
| quality | tools that are not `money` / `credit` / `pii_export` and are named like `reply`, `respond`, `response`, `answer`, `message`, `memo` | no such tool |
| fairness | the one tool of class `credit` | none, or several (set `decision_tool`) |
| multi-agent | the one tool of class `money`; with several, the one called `transfer` | none, or several without `transfer` |
| drift | global `DRIFT_*` settings | the agent has no `agent_event` rows with an `agent_version` |

Tool classes come from the manifest tools, the `tools:` map of the policy files, and the tool
names the agent was seen calling in the last days. The three demo agents keep their old
behaviour through these defaults (`customer_service` -> `reply`, `credit_prequal` ->
`decide_prequal`, `payments` -> `transfer`).

Fairness attributes: without `protected_attribute_keys` the global attribute source
(`config/fairness.yaml`, the demo uses synthetic data) is used. With them, the attribute is
read from the decision call's own arguments; the subject id is still hashed at once and the
raw value is not stored.

## Settings

The existing flags are unchanged and still switch each job on (`QUALITY_ENABLED`,
`FAIRNESS_ENABLED`, `DRIFT_ENABLED`, `MULTIAGENT_ENABLED`). Bindings are additive: with no
binding anywhere, an agent gets derived defaults or `not_applicable` rows.

| Setting | Meaning |
|---|---|
| `MONITOR_POLICY_DIR` | Extra folder of policy `*.yaml`, read after `policies/` (or `POLICY_DIR`) (its `agents.<id>.monitors` wins) |
| `MONITOR_MANIFEST_DIR` | Extra folder of `<agent>/manifest.yaml`, read after `src/supervisor_agents/` |

The served app cannot load a second gateway policy folder yet (benchmark defect D13); these two
settings only feed the monitors.

## Harness and regression test

```cmd
uv run python -m supervisor.monitors.binding_harness
uv run python -m supervisor.monitors.binding_harness --json
```

A synthetic 3-agent trace (`memo_agent` bound by policy and manifest, `helpdesk` with a
derived reply tool, `lookup_agent` with nothing to bind) goes through the four monitors in a
throw-away SQLite store. The result is compared with `data/eval/monitor_bindings/expected.json`
(12 cells; provenance and rubric in the file). Exit code 1 on any mismatch. The mock quality
scorer is labelled `mock`; no network. `tests/monitors/test_bindings.py` runs it, and also
runs the monitors without the resolver to show the old silence (all three agents: no row).

Rubric (platform engineer / model risk validator): a monitor that is switched on must either
produce a value for an agent or say why it cannot. Gate: exact match of status and code;
thresholds are ILLUSTRATIVE. There is no model risk (rules only; the mock scorer is existing
code).

## Not done

See `BACKLOG.md`: a smoke alert for "monitor on but not_applicable for a high-risk agent"
(the data exists; the alert rule does not), bindings in the Onboarding Agent PR (it does not
write `monitors:` yet), and a console editor for bindings.
