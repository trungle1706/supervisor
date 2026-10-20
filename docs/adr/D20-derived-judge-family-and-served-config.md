# D20: Judge family is derived; challenger scope; strict endpoints; served config

Status: accepted (WP1b-A, phase 3). Source: credit-memo benchmark defects D05, D12, D13, D14, D15.

## Context

The benchmark ran Supervisor 0.2.0 against a real agent and a real judge. It found that the
family-independence control (judge family != agent family) trusted a free-text label, that a
challenger from the demo agents' family stopped the judge service, that Anthropic's
OpenAI-compatible endpoint could not be used with the shipped request, and that the served app
could not load another policy folder or a fact source.

## Decisions

1. **Family is derived (D05).** The family comes from the model id table and, with
   `JUDGE_FAMILY_PROBE=1`, the endpoint's `GET /models`. A declared family counts only if it
   agrees; otherwise it needs `JUDGE_FAMILY_OVERRIDE_TEST_ONLY=1`, refused in `databricks_app`
   mode. `family_source` (`derived`, `declared-test-only`, `mock`) is stored in every verdict row
   and chain record, the model card and the validation report.
   Rejected: keep the declaration and only warn (a warning does not stop a qwen judge watching a
   qwen agent); probe always (a network call at every router build, also in tests and CI).
2. **Challenger scope (D15).** The challenger is checked against registered non-retired agents
   plus manifests named in `JUDGE_AGENTS`. T1 and T2 keep the all-manifests check, so the control
   for the judges that act is not weakened. With no store and no `JUDGE_AGENTS` (eval, validate)
   the challenger judges no concrete agent.
3. **Strict endpoints (D14).** Two flags, `LLM_STRICT_SCHEMA` and `LLM_SEND_TEMPERATURE`, both
   defaulting to the old request. The adapter sends a stripped schema copy and validates the
   reply with the full schema. Rejected: strip keywords always (servers that enforce a grammar
   from the schema, such as vLLM, lose constraints they honour).
4. **Served config (D13).** `POLICY_DIR`, `FACT_SOURCE`, `FACT_QUERY_MAP`. Kinds: `callable`
   (module:factory) and a read-only `sqlite` with a query map. The key is a bound parameter.
5. **SDK path (D12).** `HttpGate` posts to `/v1/gate/check` and falls back once to `/gate/check`
   on HTTP 404 (older server). The WP20 signature covers method and path, and the SDK signs the
   path it sends.

## Consequences

* One behaviour change with flags off: a declared judge family that disagrees with the model id
  now stops startup. Mock judges are unaffected.
* `verdict` gets a nullable column `family_source`; Delta needs the additive bootstrap before
  deploy.
* `callable:` imports a module named in settings. Settings are operator-controlled; same trust as
  the environment. Recorded in `docs/threat-model.md`.
