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

## Key storage on Databricks

- `/tmp` is wiped on every App restart. A key file there gives a new key each time, and older signed roots no longer verify against the current public key. The bundle pattern forbids secret-scope resources, so the key cannot come from a secret scope.
- `SIGNER_KIND=uc_volume` (`VolumeFileSigner`): the PKCS#8 PEM key is one write-once object on a UC Volume, written through the Files API (`databricks/files.py`, exclusive put, no overwrite). Start loads it if present. A start-up race reloads the winner's key. The key is never logged; `repr()` shows key id and kind only.
- In `databricks_app` mode with a `/Volumes/...` `SIGNER_KEY_PATH` and no explicit `SIGNER_KIND`, the factory selects `uc_volume`. `app.yaml` sets both. Preflight fails when the key path is on the container disk.
- A Volume key is readable by anyone with READ VOLUME on it: restrict the grant to the App service principal. Key custody (HSM/KMS) stays a bank decision.
- Key continuity (all signer kinds): at writer start the loaded key id is compared with the key id of the latest `root_commit`. A difference stops the writer (`KeyContinuityError`) unless `SIGNER_ALLOW_ROTATION=1`. Then the writer appends a `key_rotation` entry on the root lane (old and new key id, signed by the new key). The verifier checks that signature and accepts both keys from the export.

## Spec v2 (WP6 review fix)

- Spec v1 left `writer` and `env` outside `entry_hash`: an attacker could change who wrote an entry, or its environment, with no detection.
- Spec v2 hashes `{lane, seq, ts, record_type, record_ref, payload_hash, prev_hash, writer, env, chain_spec_version}`. `CHAIN_SPEC_VERSION = 2`. The writer emits v2 only.
- Export rows carry `chain_spec_version`. A row without it is v1. The verifier hashes each row by its own version and still reads v1 exports. The manifest accepts 1 or 2.
- A version cannot go down inside a lane (downgrade check). A row marked v1 cannot hide an edit to a v2 row, because the v1 hash differs. `--strict` fails any v1 entry, because v1 does not protect `writer` and `env`.
- The `chain_entry` table has no version column. Export and anchor detect the version by testing which hash matches the stored `entry_hash`.
- Offline verifier: `supervisor.evidence.verify` imports only the standard library, `cryptography` and `supervisor.evidence._canonical_stdlib`. That module matches `core/canonical.py` byte for byte for chain data, but rejects floats. A test compares both on the canonical vectors and on 200 random float-free structures, and a subprocess test imports `verify` with pydantic blocked.
