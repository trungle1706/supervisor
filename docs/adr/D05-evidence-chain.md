# D05 - Evidence chain

Status: Accepted (plan v2, 2026-10-14)

## Context

A writer alone proves nothing. An auditor must be able to check the record without trusting our database.

## Decision

- Linear chain by logical `seq`. Each entry hashes canonical JSON (`core/canonical.py`, with test vectors).
- One writer per agent lane, plus a root lane. Writes are serialised.
- PII stays off-chain. The chain holds hashes and references.
- A signed head is written every N minutes (default 15). The notary key is an Ed25519 key.
- The head is anchored to an immutable target. A daily Merkle root is also anchored.
- An offline CLI verifies an export: `python -m supervisor.evidence.verify <export dir>`.

| Port | Adapters |
|---|---|
| `Signer` | `ed25519_file`, `secret_env` |
| `Anchor` | `worm_dir`, `uc_volume` |

The anchor job is an in-process scheduled job: `python -m supervisor.jobs.anchor`.

## Consequences

- Tamper test: edit one row in an export copy. Verify reports the break.
- A key in a file or an env secret is weaker than an HSM. We say this in SECURITY.md.
- A `worm_dir` on a laptop is not truly immutable. It shows the mechanism only.
- Key rotation needs a rule. This is open until the bank names key custody.

## Changes from 06 section 3

- 06 names Key Vault HSM / KMS. Plan v2 uses an Ed25519 file or env secret until the bank decides. BACKLOG.md item: "HSM/KMS notary key, bank WORM anchor".
- Anchor targets are `worm_dir` and `uc_volume`, not immutable blob.
