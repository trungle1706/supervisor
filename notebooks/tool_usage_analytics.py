# Databricks notebook source
# MAGIC %md
# MAGIC # Supervisor: tool usage analytics (WP22)
# MAGIC
# MAGIC Reads the Delta table `tool_usage_daily` (one row per UTC day, agent and tool; written by
# MAGIC `python -m supervisor.analytics.tools rollup` or by the app when `TOOL_ANALYTICS_ENABLED=1`).
# MAGIC Shows, per agent, usage in the window and the allowed tools that were never used.
# MAGIC Read only: it changes nothing. A least-privilege change is a policy pull request
# MAGIC (see `docs/tool-analytics.md`).
# MAGIC
# MAGIC Run: attach to a SQL-capable cluster or serverless, edit the next cell (replace every
# MAGIC FILL-ME value), then Run all. Your own Unity Catalog permissions apply.
# MAGIC The same rows are served as JSON at `GET /v1/analytics/tools?agent_id=...` (App).

# COMMAND ----------

# Edit inline. Names are placeholders on purpose: no workspace value is committed.
CATALOG = "FILL-ME-catalog"
SCHEMA = "FILL-ME-schema"
PREFIX = ""  # the TABLE_PREFIX of the deployment, if any
AGENT_ID = ""  # empty = all agents
WINDOW_DAYS = 30

# COMMAND ----------

# ruff: noqa: F821, T201, E501, S608, E402
import re

# The names go into SQL text: allow identifier characters only (no quote, no backtick).
for _name, _value in (
    ("CATALOG", CATALOG),
    ("SCHEMA", SCHEMA),
    ("PREFIX", PREFIX),
    ("AGENT_ID", AGENT_ID),
):
    if _value and not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", _value):
        raise ValueError(f"{_name} has characters that are not allowed: {_value!r}")
WINDOW_DAYS = int(WINDOW_DAYS)
TABLE = f"`{CATALOG}`.`{SCHEMA}`.`{PREFIX}tool_usage_daily`"
agent_filter = f"AND agent_id = '{AGENT_ID}'" if AGENT_ID else ""

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Usage per agent and tool in the window
# MAGIC `p95_us` is the worst daily p95. `users_max` is the largest number of distinct
# MAGIC (hashed) end users on one day. Hashed ids are never stored in this table.

# COMMAND ----------

usage = spark.sql(f"""
  SELECT agent_id, tool_name, max(risk_class) AS risk_class,
         sum(calls) AS calls, sum(allows) AS allows, sum(blocks) AS blocks,
         sum(pauses) AS pauses, sum(errors) AS errors,
         max(p95_us) AS p95_us, max(distinct_callers) AS callers_max,
         max(distinct_users) AS users_max,
         min(first_seen) AS first_seen, max(last_seen) AS last_seen,
         count(*) AS days_active
  FROM {TABLE}
  WHERE usage_date > date_sub(current_date(), {int(WINDOW_DAYS)}) {agent_filter}
  GROUP BY agent_id, tool_name
  ORDER BY agent_id, CASE max(risk_class) WHEN 'money' THEN 0 WHEN 'credit' THEN 1
           WHEN 'pii_export' THEN 2 WHEN 'read_only' THEN 3 ELSE 4 END, calls DESC
""")
display(usage)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Daily calls (for a chart: pick "line", x = usage_date, series = tool_name)

# COMMAND ----------

daily = spark.sql(f"""
  SELECT usage_date, agent_id, tool_name, calls, blocks + pauses AS not_allowed, p95_us
  FROM {TABLE}
  WHERE usage_date > date_sub(current_date(), {int(WINDOW_DAYS)}) {agent_filter}
  ORDER BY usage_date, agent_id, tool_name
""")
display(daily)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Tools called but not allowed to the agent
# MAGIC Tools with `pauses` or `blocks` and no `allows`: the gate stopped them. Review by hand.
# MAGIC The allow-list itself lives in `policies/*.yaml` (rules PAY-07, SVC-07, CRD-07), so the
# MAGIC full "allowed but unused" list comes from `python -m supervisor.analytics.tools suggest`.

# COMMAND ----------

stopped = usage.where("allows = 0 AND (blocks + pauses) > 0")
display(stopped)
print(
    f"[OK] {usage.count()} agent/tool rows, {stopped.count()} never allowed in the last {WINDOW_DAYS} days"
)
