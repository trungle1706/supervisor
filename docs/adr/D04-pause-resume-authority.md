# D04 - Pause and resume authority

Status: Accepted (plan v2, 2026-10-14)

## Context

A kill switch with no defined owner is a risk. A pause that anyone can undo is not a pause.

## Decision

| Action | Who | Rule |
|---|---|---|
| Pause | Any on-call reviewer | One click. No second approval. |
| Resume | Reviewer plus agent owner | Two different people. |
| Break-glass resume | Two approvers | Auto-expires. Reason required. |

Every pause, resume and break-glass event is written to the evidence chain (see D05). The console shows who did what and when.

The `Principal` port gives the user identity (the gate control routes use only it: explicit `X-Dev-User` on the laptop, SSO headers on Databricks; never a body field or a raw `X-Forwarded-User`; role check always on). On the laptop it is a dev users file. On Databricks it comes from the SSO headers (`X-Forwarded-User`). The same person cannot fill both resume roles.

All user errors on these actions return HTTP 400 with a message. htmx drops 500 responses.

## Consequences

- Pause is fast and cheap. A false pause costs time, not money.
- Resume needs two people. The agent owner must be named at onboarding.
- The dev users file is not a real identity. Real SSO roles beyond the demo user are out of Phase 1 scope.
- Break-glass expiry is a scheduled job in the in-process scheduler.

## Changes from 06 section 3

- None. Identity source changes with the target (dev file or SSO headers).
