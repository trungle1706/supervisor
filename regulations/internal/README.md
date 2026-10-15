# Internal rules (bank policies)

A bank can add its own policies to the regulation knowledge base. They are loaded with the
same schema and the same checks as the public instruments, and they show up in `list`,
`coverage` and the applicability results. Not legal advice. Bank counsel must confirm.

Nothing here is loaded by default. Only `*.yaml` files in the folder you name are read.
The sample `example-ai-use-policy.yaml.example` has a `.example` suffix, so it is never loaded.

## File format

One file per internal document. Same layout as `regulations/vn/*.yaml`
(schema: `regulations/schema/obligation.schema.json`, `$defs/instrument_file`).

| Field | Rule for an internal document |
|---|---|
| `instrument.id` | Starts with `INT-`, upper case, for example `INT-ACME-AIPOL` |
| `instrument.kind` | `internal` (only allowed in an internal folder) |
| `instrument.issuer` | The bank unit that owns the document |
| `instrument.number` | The document number in your document system |
| `obligations[].id` | `<instrument id>-<section token>-<2 digits>`, for example `INT-ACME-AIPOL-S4-01` |
| `verification` | `VERIFIED_PRIMARY` when you read the intranet document |
| `sources[]` | One source of `kind: primary` with a non-public URL, for example `https://intranet.example.invalid/policies/ai-pol-001` |
| `duties` | Ids from `regulations/schema/duties.yaml` |
| `control_mapping` | Ids from the catalogue, `policies/baseline.yaml` and `regulations/schema/controls.yaml` |
| dates | Quoted strings: `"2026-01-15"` |

Do not copy confidential text into a public repository. Keep the folder outside the repository.

## Use it (Windows cmd)

```
set REGKB_INTERNAL_DIR=C:\path\to\internal
python -m supervisor.regkb validate
python -m supervisor.regkb list --jurisdiction VN
```

Or put `REGKB_INTERNAL_DIR=C:\path\to\internal` in `.env`. A relative path is read from the
repository root. An empty value turns internal rules off. `validate` prints every problem it
finds, one `[FAIL]` line each, with the file and the obligation id.
