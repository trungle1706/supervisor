"""Databricks deployment kit helpers (WP10).

Modules here never import ``databricks`` themselves (architecture test): the SDK client
is built in ``supervisor.adapters.sql.databricks_rest.make_workspace_client`` and the
parts used here (``api_client.do``, ``files``, ``config.authenticate``) are injected.

* ``command_exec``: Command Execution API runner for the shared interactive cluster.
* ``files``: Files API helper for Unity Catalog Volumes (anchors, spool).
* ``serving``: ChatModel for the bound model-serving endpoint with fresh OAuth headers.
* ``notebook``: Databricks source-format notebook cells (split, generate, check).
"""
