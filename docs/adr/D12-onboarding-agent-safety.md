# D12 - Onboarding Agent safety

Status: Accepted (plan v2, 2026-10-14)

## Context

The Onboarding Agent reads repos and opens pull requests. Repo access is an attack surface. Repo text can carry prompt injection.

## Decision

- Read-only access. One repo token per run. Short life.
- Repo text is untrusted data. It is wrapped before any LLM call.
- A secret scrub runs before text goes to an LLM. The goal is gitleaks.
- The profile is a pydantic model. Each claim has file:line evidence.
- The pull request is built by a libcst codemod and templates. The LLM does not write free code into the PR.
- Git operations go only through `src/supervisor/sandbox.py`. An AST test blocks exec, eval and subprocess elsewhere.
- The agent never merges. A human merges.
- The Onboarding Agent is registered and watched like other agents.

## Consequences

- Prompt injection in a repo can distort the profile. Evidence links let a reviewer check.
- Bank data reads follow the house rule: a single `SELECT`, checked with `sqlglot` before connection.

## Open point: gitleaks

gitleaks is a Go binary. The bank laptop rules forbid binaries that need a build or download. Plan v2 uses an in-process regex secret scrubber. If the bank provides gitleaks, the scrubber port can call it through `sandbox.py`. The regex scrubber has lower recall. Add this to BACKLOG.md.

## Changes from 06 section 3

- gitleaks scrub becomes a goal. Plan v2 default is an in-process regex scrubber.
- "Read-only per-repo token" depends on the `RepoReader` adapter: `local_git` (no token) or `databricks_repo`.


## Implementation note (2026-10-14, WP9)

The codemod is implemented with the standard library `ast` module plus text templates, not libcst (no new dependency). Secret scrubbing before any LLM call is the in-repo regex scrubber in `src/supervisor/onboard/scrub.py`; gitleaks is optional if the bank supplies an approved binary (see BACKLOG.md).
