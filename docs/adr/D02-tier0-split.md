# D02 - Tier 0 split

Status: Accepted (plan v2, 2026-10-14)

## Context

The gateway has a 50 ms budget per check. Presidio and an injection classifier cannot run inside that budget with the rules too.

## Decision

Tier 0 has two parts.

| Part | Work | Mode | Budget |
|---|---|---|---|
| 0a | Rules, limits, allow-list, permissions, stateful aggregates per window | Synchronous | under 5 ms |
| 0b | PII masking and injection classifier | Asynchronous, high-risk tools only | no hard budget on the call path |

The 0a result decides allow or block. The 0b result can raise an alert, open a case or pause an agent after the call. 0b never delays a call.

The default masker is a Vietnamese regex masker (CCCD, phone, account, e-mail). Presidio is an optional extra. The injection classifier is a port. Its default is a regex classifier.

We publish p50, p95 and p99 latency for 0a with 20 rules. The numbers come from `tests/perf`.

### Normalisation (WP17-fix)

The 0b injection patterns do not run on the raw text. `tier0b.candidates()` builds up to three strings: (1) the text after NFKC, removal of Unicode Cf and zero-width characters, case fold, a small table for Latin look-alikes (Cyrillic, Greek, small caps; not the full `confusables.txt`), NFC and collapsed whitespace, with diacritics stripped, so one pattern covers "bỏ qua" and "bo qua"; (2) the same string with diacritics kept; (3) the diacritics-stripped form of the Telex decoding of (1) ("bor qua" becomes "bo qua"). The patterns run on each string and the highest count is reported. PII patterns still run on the raw text, so PII counts do not change. A finding still carries only a kind and a count. Cost: under 20 ms for 20 KB (`MAX_SCAN_CHARS`). The "chuyển ngay/gấp ... tài khoản" pattern now needs a destination word (sang, vào, tới, đến) and excludes "chuyển ngay hôm nay" (a time word, not urgency). Typo-level perturbations stay a known gap.

## Consequences

- The hot path has no model call and no network call.
- Regex masking has lower recall than Presidio. The WP4 gate is VN PII recall of 0.95 or more on the synthetic labelled set.
- 0b findings arrive after the call. For money and credit tools, 0a rules must carry the hard limits.

## Changes from 06 section 3

- Presidio is no longer the 0b default. It is an optional extra. BACKLOG.md item: "Presidio as default masker" (returns when spaCy model wheels are on Nexus).
- Stateful aggregates run in gateway code over the SQLite or Delta state store.
