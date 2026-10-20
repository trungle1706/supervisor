# Policy folder and fact source of the served app (D13)

The served app used to load only `<repo>/policies` and had no fact source, so every new agent
needed a code patch. Two settings fix that. Both default to the old behaviour.

| Setting | Default | Meaning |
|---|---|---|
| `POLICY_DIR` | empty (= `<repo>/policies`) | Absolute folder with the policy `*.yaml` (and `schema.json`). Must exist. A relative value is read from the repo root. Used by `wiring.build_runtime` and `gateway.wiring.build_gateway` in laptop and databricks_app mode |
| `FACT_SOURCE` | empty (= none) | `<kind>:<target>`, see below |
| `FACT_QUERY_MAP` | empty | YAML query map, required for `sqlite:` |

A rule reads a fact with the path `fact.<source>.<field>`; the key is the tool argument
`<source>_id` (`fact.application.documents_complete` reads argument `application_id`). Without a
fact source, or when the record or field is missing, the rule errors and its fail mode applies
(closed for money, credit and PII export). This does not change.

## Kinds

| `FACT_SOURCE` | What it builds |
|---|---|
| empty | no fact source |
| `callable:pkg.mod:name` | `name(settings)` must return an object with `get(source, key)`; use it to wrap a bank system. The in-process `MappingFactSource` is built this way |
| `sqlite:/abs/file.db` | `SqliteFactSource`: the file is opened read-only (`mode=ro` plus `PRAGMA query_only`); a write fails |

## SQLite query map

    sources:
      application:                       # rule path fact.application.<field>
        query: >-
          SELECT documents_complete, status, amount_minor
          FROM applications WHERE application_id = ?
        bool_fields: [documents_complete]   # 0/1 columns returned as true/false

Rules for the map (checked at startup, a fault is a `ConfigError` with the reason):

* source names are `[a-z][a-z0-9_]*`;
* each query is ONE `SELECT` with exactly one `?`; the key is bound to it, never pasted into SQL;
* the gateway refuses float facts: cast to an integer (minor units) or text in the query;
* a database error, an unknown source or no row returns no record, so the rule errors and fails
  by its fail mode (closed for money, credit and PII export). The log shows the error class only.

Example for the benchmark: a SQLite file standing in for the bank warehouse. In production use the
`callable:` kind with a read-only service identity; SQLite is for laptops, tests and benchmarks.

## Not done

See `BACKLOG.md`: a Databricks SQL warehouse kind, a REST kind, a cache, and `POLICY_DIR` for the
tool analytics and assurance pages (they still read `<repo>/policies`).
