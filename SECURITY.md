# Security policy

Supervisor watches AI agents at a bank: a deterministic gateway that can block or pause an
agent, advisory AI judges, a hash-chained evidence store with offline verification, and a
reviewer console. This file says how to report a problem and where the security design is.

## Reporting a vulnerability

- Internal (bank) channel: **FILL-ME-security-contact** (the bank owner fills in the
  security team mailbox or ticket queue before the first production use).
- Do not open a public issue. Do not put real customer data, tokens or workspace ids in a
  report; describe the steps with the synthetic demo data (`python -m supervisor.cli demo`).
- Expected first answer: **FILL-ME** business days (bank owner decides).
- Include: version (`/version`), target (laptop or Databricks App), the command or page,
  the `[FAIL]` line or HTTP 400 message, and whether evidence verification still passes
  (`python -m supervisor.cli verify <export dir> --strict`).

## Design and controls

- Threat model, trust boundaries, controls mapped to code, and known gaps:
  [`docs/threat-model.md`](docs/threat-model.md).
- Design decisions: [`docs/adr/`](docs/adr/) (gateway D01, fail mode D03, pause/resume
  authority D04, evidence chain D05, judge hardening D06, residency D07).
- Bank integrations (SIEM, ITSM, pager, SCIM), all off by default:
  [`docs/bank-integration.md`](docs/bank-integration.md).
- Deployment constraints learned at the bank: [`docs/BANK_DEPLOY_GUIDE.md`](docs/BANK_DEPLOY_GUIDE.md).

## Rules every change keeps

| Rule | Enforced by |
|---|---|
| Only deterministic rules block or pause; judges advise | `core/models.py` (`Verdict`), `judge/service.py` |
| The gate block, the pause and the chain break are never faked (also not in the demo) | `demo/inject.py`, `demo/tamper.py`, `tests/demo/` |
| No secrets or real workspace ids in git; `FILL-ME` placeholders | `tests/test_no_secrets.py` |
| Hand-off zips are built from `git archive HEAD` and leak-swept | `python -m supervisor.cli release` (`src/supervisor/release.py`) |
| No PAT: OAuth only for Databricks | `config.py`, `preflight.py` |
| No `exec` / `eval` / `subprocess` outside `src/supervisor/sandbox.py` | `tests/test_architecture.py` |
| PII never enters the evidence chain (hashes and masked excerpts only) | `evidence/chain.py`, `core/args_hmac.py`, `adapters/masking/` |
| New features are off by default | Settings defaults; tests of the off path |

## Known gaps (summary)

Enforcement is cooperative until the bank puts a credential broker or egress proxy in
front of agent tools. The default signing key and HMAC keys are development keys (labelled
`dev` in the evidence). The OTLP receiver has no caller authentication yet. On the
Databricks App a request without SSO headers runs as the app service principal, read only
by default. Details and planned answers: `docs/threat-model.md` section 4.

## Supported versions

Pre-release (0.x). Only the latest hand-off zip is supported.
