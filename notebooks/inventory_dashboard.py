# Databricks notebook source
# MAGIC %md
# MAGIC # Supervisor: inventory views for a Databricks dashboard (WP24)
# MAGIC
# MAGIC Creates read-only SQL views over the Supervisor tables `inventory_node` and `inventory_edge`
# MAGIC (in the schema where the Supervisor app writes them) so a Lakeview / AI/BI dashboard can chart:
# MAGIC unmanaged workspace items (shadow AI), the tools and endpoints each agent resolves to, and
# MAGIC items by status. It only creates views in `VIEW_SCHEMA`; it never writes to the Supervisor tables.
# MAGIC
# MAGIC Offline alternative: `python -m supervisor.inventory export --out <dir>` writes
# MAGIC `inventory_nodes.csv` and `inventory_edges.csv`; upload the pair to a Volume and set `CSV_DIR`.
# MAGIC
# MAGIC How to run: replace every FILL-ME value in the next cell, then Run all.

# COMMAND ----------

# SUPERVISOR-PARAMS (edit inline; replace every FILL-ME value in your local copy only)
CATALOG = "FILL-ME-catalog"  # catalog of the Supervisor schema
SCHEMA = "FILL-ME-schema"  # schema that holds inventory_node and inventory_edge
VIEW_SCHEMA = "FILL-ME-view-schema"  # where the dashboard views are created
CSV_DIR = ""  # optional: /Volumes/FILL-ME-catalog/FILL-ME-schema/FILL-ME-volume/inventory

# COMMAND ----------

# ruff: noqa: F821, T201, E501, S608, E402
SRC = f"`{CATALOG}`.`{SCHEMA}`"
OUT = f"`{CATALOG}`.`{VIEW_SCHEMA}`"

if CSV_DIR:
    nodes = spark.read.option("header", True).csv(f"{CSV_DIR}/inventory_nodes.csv")
    edges = spark.read.option("header", True).csv(f"{CSV_DIR}/inventory_edges.csv")
    nodes.createOrReplaceTempView("inv_node")
    edges.createOrReplaceTempView("inv_edge")
    N, E = "inv_node", "inv_edge"
    ACTIVE = "active = 'true'"
    LAST_SEEN = "CAST(NULL AS TIMESTAMP) AS last_seen"  # the CSV export has no last_seen
    # A permanent view cannot reference a temp view: over the CSV pair the views are temporary.
    CREATE = "CREATE OR REPLACE TEMP VIEW `{name}`"
else:
    N, E = f"{SRC}.`inventory_node`", f"{SRC}.`inventory_edge`"
    ACTIVE = "active = true"
    LAST_SEEN = "last_seen"
    CREATE = "CREATE OR REPLACE VIEW " + OUT + ".`{name}`"

# COMMAND ----------

VIEWS = {
    # shadow AI: Apps and serving endpoints seen in the workspace with no Supervisor manifest
    "v_inventory_unmanaged": f"""
        SELECT kind, display_name, status, {LAST_SEEN}
        FROM {N} WHERE status = 'unmanaged' ORDER BY kind, display_name""",
    # what each agent uses, with evidence (file:line or workspace reference)
    "v_inventory_agent_links": f"""
        SELECT s.name AS agent, e.kind AS edge, d.kind AS target_kind, d.display_name AS target,
               d.own_risk, e.source, e.evidence_ref
        FROM {E} e JOIN {N} s ON e.src_id = s.node_id JOIN {N} d ON e.dst_id = d.node_id
        WHERE e.{ACTIVE} AND s.kind = 'system' ORDER BY agent, edge, target""",
    "v_inventory_counts": f"""
        SELECT kind, status, COUNT(*) AS n FROM {N} GROUP BY kind, status ORDER BY kind, status""",
}
# Effective risk (max along `uses` edges) is computed by the app: use inventory.json / the CSV
# column `effective_risk`, or GET /v1/inventory/{agent_id}. It is not recomputed in SQL.

for name, sql in VIEWS.items():
    stmt = CREATE.format(name=name)
    spark.sql(f"{stmt} AS {sql}")
    print(f"[OK] {stmt.split()[-1]}")
display(spark.sql("SELECT * FROM " + CREATE.format(name="v_inventory_counts").split()[-1]))
