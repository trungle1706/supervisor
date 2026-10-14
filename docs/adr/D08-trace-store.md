# D08 - Trace store

Status: Accepted (plan v2, 2026-10-14)

## Context

Agent traces must be stored and read in a stable shape. MLflow trace tables in Unity Catalog have limits and are in Beta. The bank workspace version is not confirmed.

## Decision

- The own `agent_event` table (OTel-shaped) is the primary read model for Watch. It is also the source for evidence.
- Trace input paths (`TraceSource` port): `otel_inprocess`, `otlp_receiver` (OTLP/HTTP route), and an optional `mlflow_export`.
- MLflow is an optional export. It is an extra. It is off unless configured.
- The same trace gives identical `agent_event` rows through the in-process and OTLP paths. This is a WP4 test.
- Masking happens at capture with three levels: digest, masked, raw.

## Consequences

- We do not depend on MLflow version or UC trace limits.
- Teams that already use MLflow can still see traces there.
- We own the schema and its migrations. `schema/model.yaml` generates SQLite and Databricks DDL.
- `agent_event` is append-only. SQLite triggers enforce this. On Delta the grants and the code path enforce it.

## Changes from 06 section 3

- 06 says "MLflow 3 to UC tables where it works". Plan v2 makes MLflow an optional export only. BACKLOG.md item: "MLflow as primary trace path" (returns when MLflow 3.14 or newer is confirmed with CREATE TABLE in a schema).
