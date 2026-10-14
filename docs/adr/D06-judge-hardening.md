# D06 - Judge hardening and governance

Status: Accepted (plan v2, 2026-10-14)

## Context

Judges read agent output. That output may carry an attack aimed at the judge. A judge from the same model family as the agent can share its blind spots.

## Decision

- Judge input is wrapped as data. The judge has no tools. Output is JSON only, checked against a schema. Truncation and repetition guards apply.
- The judge registry enforces: judge model family differs from agent model family. This is a CI test and a runtime check.
- Verdicts are advisory. Judges never block. Rules block (D02, D03).
- Four eval sets: planted, benign, judge-injection, held-out.
- A judge has an owner, a model card and re-validation triggers (model change, prompt change, drift alarm).
- The attack set author is a separate sub-agent from the rule author.

| Tier | Use |
|---|---|
| Tier 1 | Cheap, wide screen |
| Tier 2 | Stronger model, flagged items only |

## Consequences

- Eval report shows catch rate, false-alarm rate and judge-injection move rate on the held-out set.
- With `MockChat` the numbers prove the harness, not the model. A real run needs a model endpoint.
- The `ChatModel` port is OpenAI-compatible. Default is loopback Ollama on the laptop, a bound serving endpoint on Databricks.
- Small CPU models (4B) may fail the held-out gate. The owner then picks a bigger model.

## Changes from 06 section 3

- None in the design. The model host is the `ChatModel` port, not a Model Serving pyfunc.
