# Candidate triage (WP-N1)

Off by default (`CONSOLE_OVERVIEW_V4=1`; the page needs `CONSOLE_NAV_V3=1`, `GOVERNANCE_ENABLED=1`
and, for the candidate table, `INVENTORY_ENABLED=1`). Plan: `docs/phase7/BUILD_PLAN_PHASE7.md`
section 1.

## What it does

The workspace scan finds objects that no AI system covers. Triage gives each one a row: how much it
matters, how much it can do alone, how complex it is, and what to do first. The rows feed:

* the "Top candidates to register" table on My overview (10 per page);
* the Candidates tab, `/console/candidates` (all rows, filters, sort, drawer);
* `GET /v1/candidates` (permission `inventory.view`, mounted only with the flag).

Code: `supervisor.governance.triage` (pure functions over the inventory graph, no store, no web).
It reads only. A person decides; the score is a hint.

## Candidates

A node with status `unmanaged` and one of:

| `kind` in the row | Node |
|---|---|
| `app` | `system` with `attrs.role = databricks_app` |
| `endpoint` | `model_endpoint` with `attrs.agent_endpoint` or `attrs.task = agent` |
| `genie_space` | `genie_space` |
| `job` | `job` |

Nodes that a system already links to (`system_component`, `ref_kind = node`) are left out.

## Rules (the `SIGNALS` table)

What a candidate reaches is found along active `uses`, `serves`, `reads` and `writes` edges, three
steps deep.

| Signal | Points | Fires when |
|---|---|---|
| `external_model` | +20 | the candidate or an endpoint it reaches has `external_providers` |
| `customer_table` | +25 | it reaches a dataset whose name has a token `customer`, `khach`, `cif`, `card`, `the`, `account`, `tai_khoan`, `loan`, `khoan_vay`, `payment`, `thanh_toan`, `txn`, `transaction` (a plural `s` is allowed; `the` does not match `other`) |
| `money_tool` | +30 | it reaches a `tool` or `uc_function` with `attrs.risk_class` money, credit or pii_export |
| `writes` | +10 | a job with a `writes` edge |
| `agent_endpoint` | +10 | kind `endpoint` |
| `genie_space` | +10 | kind `genie_space` |
| `app_agent` | +10 | kind `app` that reaches an agent endpoint |
| `unknown` | +5 | none of the signals above that score fired |
| `scheduled` | 0 | `attrs.schedule` is set |
| `no_owner` | 0 | no `attrs.owner_group` |

`impact` = the sum, at most 100.

| Field | Rule |
|---|---|
| `autonomy` | `attrs.autonomy_proposal` when it is a known level. Else: Genie space, or endpoint with no tool = `l1_assistive`; app or endpoint that reaches tools = `l3_tool_using_supervised`; job with a schedule that writes = `l4_autonomous_bounded`; else `unspecified` |
| `complexity` | reached models, tools, UC functions, datasets and MCP servers: 0 = 0, 1-2 = 30, 3-5 = 60, 6 or more = 90; +10 with an external provider; at most 100 |
| `score` | `impact * 0.6 + complexity * 0.2 + 10 * rank`, integer arithmetic `(6*impact + 2*complexity) // 10 + 10*rank`, at most 100. Rank: unspecified 1, l0 0, l1 1, l2 2, l3 3, l4 4, l5 5 |
| `recommended_action` | score 70 or more: `register_now`; else money or customer signal: `register_and_classify`; else external model: `register_review_vendor`; else `register_when_convenient`. The reason text is the i18n key `tri_reason_<action>` |
| `band` | `high` (70 or more), `medium` (40 to 69), `low` |

No float is stored or sent. No URL and no workspace id is in any field: every string goes through
`triage.scrub`.

## Row shape

```json
{
  "node_id": "inv_0123456789abcdef",
  "kind": "app",
  "node_kind": "system",
  "name": "loan-copilot",
  "owner_group": "lending",
  "impact": 85,
  "autonomy": "l3_tool_using_supervised",
  "autonomy_rank": 3,
  "complexity": 70,
  "score": 95,
  "band": "high",
  "signals": ["external_model", "customer_table", "money_tool", "app_agent"],
  "description": "Databricks App `loan-copilot` in group `lending`; calls endpoint ...",
  "recommended_action": "register_now",
  "reason_key": "tri_reason_register_now",
  "evidence": [{"source": "workspace_scan", "ref": "workspace:app/loan-copilot"}],
  "from_override": false
}
```

`GET /v1/candidates` returns `{count, total, items}`; filters `kind`, `signal`, `band` (an unknown
value is HTTP 400). The page rows also carry `facts` (names and counts the description is built
from; the console writes the Vietnamese sentence from it).

## For a background analyst agent

A job (`supervisor.jobs.triage`, not part of WP-N1) can store a richer row in
`inventory_node.attrs["triage"]` of a candidate. The page then prefers it. The same dict can go to
`triage.triage(graph, overrides={node_id: {...}})`; the argument wins over the attribute.

Allowed fields (anything else, and any invalid value, is ignored):

| Field | Type |
|---|---|
| `impact`, `complexity`, `score` | integer 0 to 100 (the score is computed again from the others unless `score` is given) |
| `autonomy` | one of `unspecified`, `l0_rule_based` ... `l5_self_directed` |
| `signals` | list of slugs from the table above |
| `description` | one plain sentence; scrubbed of URLs and long numbers; shown as it is in every language |
| `recommended_action` | one of the four actions above |

## Recommended action of a system or an agent

`supervisor.governance.next_action.recommend` (plan section 1.3). First match wins: overdue task,
stage approval that waits for me, Decision 33 class unclassified, guardian below the floor, gate
SHADOW for over 7 days with no open case, open case, any other open required task, no action. The
gate keeps no time of a state change; the age of the agent row stands in for it.

## Not in WP-N1

The Register button links to `/console/systems/new?from=<node_id>` (today's wizard; the register
workflow v2 of WP-N3 will read `from`). My agents (WP-N2) only has its tab entry here
(`CONSOLE_MY_AGENTS`).
