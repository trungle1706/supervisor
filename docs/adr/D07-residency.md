# D07 - Residency

Status: Accepted (plan v2, 2026-10-14)

## Context

There is no Databricks region in Vietnam. We must not claim that data stays "in Vietnam". Judges may see customer data.

## Decision

- Mask before any judge call. The `Masker` port runs first. Default is the VN regex masker.
- Tier 2 on customer data uses an in-region open-weight model (name after the region is confirmed) or a bank-hosted model.
- Settings reject a non-loopback `LLM_BASE_URL` unless `LLM_ALLOW_REMOTE=1`.
- The region of each judge call is logged in the call record.
- Docs and slides make no "in Vietnam" claim.

| Check | Where |
|---|---|
| Loopback rule | `Settings` validation at start |
| Mask first | Judge router |
| Region log | `verdict` record |

## Consequences

- The zero-egress house rule holds by default.
- Regex masking can miss PII. Capture levels (digest, masked, raw) limit risk. Default is not raw.
- The list of enabled models and their retention terms comes from spike C. That spike needs the bank workspace.
- Open point: model names stay blank until the region is confirmed.

## Changes from 06 section 3

- Masking default is the VN regex masker, not Presidio. BACKLOG.md item: "Presidio as default masker".
