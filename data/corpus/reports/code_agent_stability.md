# Source analysis agent: eval report

Date 2026-10-31. Model `qwen2.5:7b-instruct` (chat shape). Prompt `ca-prompt-10`. Runs per repo: 3. Stability: 3 runs per repo with the server's default sampling (temperature not sent), prompt ca-prompt-10.

## Split: tuned (2 repos)

| field | det P | det R | det F1 | det+agent P | det+agent R | det+agent F1 | agent added (right/wrong) |
|---|---|---|---|---|---|---|---|
| tools | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| irreversible_tools | n/a | 0.0 | n/a | 100.0 | 100.0 | 100.0 | 2/0 |
| hitl_tools | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 |
| amount_args | n/a | 0.0 | n/a | 100.0 | 100.0 | 100.0 | 1/0 |
| tool_sinks | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| egress_hosts | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| secret_sources | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| guardrails | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 |
| logging_sinks | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0/0 |
| pii_by_tool | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| entrypoints | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| pinned_models | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 |
| **micro all** | 95.2 | 87.0 | 90.9 | 95.8 | 100.0 | 97.9 | |

Tool effect accuracy: det 3/5, det+agent 5/5.
PII in the log, correct repos: det 2/2, det+agent 2/2.

Evidence: 32/32 final findings verify against the stored text (100.0 %). The agent proposed 24 claims; 14 passed the check (58.3 %). Dropped by reason: {'quote_not_on_line': 7, 'duplicate': 3}.
Cost per repo: 5.0 model calls, about 7515 tokens (estimated), 999 s; files read 80 %; stops {'max_steps': 2}.

## Split: tuned_without_exemplar_repos (2 repos)

| field | det P | det R | det F1 | det+agent P | det+agent R | det+agent F1 | agent added (right/wrong) |
|---|---|---|---|---|---|---|---|
| tools | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| irreversible_tools | n/a | 0.0 | n/a | 100.0 | 100.0 | 100.0 | 2/0 |
| hitl_tools | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 |
| amount_args | n/a | 0.0 | n/a | 100.0 | 100.0 | 100.0 | 1/0 |
| tool_sinks | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| egress_hosts | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| secret_sources | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| guardrails | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 |
| logging_sinks | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0/0 |
| pii_by_tool | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| entrypoints | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| pinned_models | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 |
| **micro all** | 95.2 | 87.0 | 90.9 | 95.8 | 100.0 | 97.9 | |

Tool effect accuracy: det 3/5, det+agent 5/5.
PII in the log, correct repos: det 2/2, det+agent 2/2.

Evidence: 32/32 final findings verify against the stored text (100.0 %). The agent proposed 24 claims; 14 passed the check (58.3 %). Dropped by reason: {'quote_not_on_line': 7, 'duplicate': 3}.
Cost per repo: 5.0 model calls, about 7515 tokens (estimated), 999 s; files read 80 %; stops {'max_steps': 2}.

## Split: all (2 repos)

| field | det P | det R | det F1 | det+agent P | det+agent R | det+agent F1 | agent added (right/wrong) |
|---|---|---|---|---|---|---|---|
| tools | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| irreversible_tools | n/a | 0.0 | n/a | 100.0 | 100.0 | 100.0 | 2/0 |
| hitl_tools | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 |
| amount_args | n/a | 0.0 | n/a | 100.0 | 100.0 | 100.0 | 1/0 |
| tool_sinks | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| egress_hosts | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| secret_sources | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| guardrails | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 |
| logging_sinks | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0/0 |
| pii_by_tool | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| entrypoints | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0/0 |
| pinned_models | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 |
| **micro all** | 95.2 | 87.0 | 90.9 | 95.8 | 100.0 | 97.9 | |

Tool effect accuracy: det 3/5, det+agent 5/5.
PII in the log, correct repos: det 2/2, det+agent 2/2.

Evidence: 32/32 final findings verify against the stored text (100.0 %). The agent proposed 24 claims; 14 passed the check (58.3 %). Dropped by reason: {'quote_not_on_line': 7, 'duplicate': 3}.
Cost per repo: 5.0 model calls, about 7515 tokens (estimated), 999 s; files read 80 %; stops {'max_steps': 2}.

## Stability

| repo | runs | identical | mean Jaccard |
|---|---|---|---|
| mlflow_chatagent_savings | 3 | True | 100.0 |
| vi_comments_insurance | 3 | True | 100.0 |
