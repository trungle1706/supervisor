# 07a Research: "Jev" and judge/monitor model benchmarks
Date: 2026-10-14. Method: web search + page fetch. VERIFIED = page read or found in search result with URL. Vendor claims are marked "vendor claim".

## Task 1: What is Jev?

Short answer: Jev is real. It is a small "decision model" from TypeSafe AI (early access since 2026-09-15). It is NOT an agent judge. It is a fast scorer/router that an agent calls for yes/no, choice, or number decisions.

| Item | Finding | Status |
|---|---|---|
| Vendor | TypeSafe AI (founders: Diogo Almeida CEO, Erik Gafni CTO, Sasha Sheng COO; ~$40M seed, DCVC) | VERIFIED (secondary press) https://letsdatascience.com/news/typesafe-ai-launches-jev-decision-model-889a38c0 ; https://www.vktr.com/ai-platforms/chatgpt-cocreator-launches-typesafe-ai-with-jev/ |
| What it does | Takes state + fixed questions, returns typed answers with probabilities (choice, yes/no, numeric score). Does not write text. Called a "System One" model | VERIFIED https://www.eesel.ai/blog/typesafe-jev ; https://pooyagolchian.com/blog/what-is-jev-ai-decision-model-2026/ |
| Licence / deployment | Not stated on the page I could read. Access by waitlist at typesafe.ai, API key, SDK/REST, model id "jev" (third-party page, not checked against vendor docs) | PARTLY VERIFIED https://www.llmreference.com/provider/typesafe-ai/jev |
| Self-host / on-prem / inside Databricks | No public evidence. Looks like hosted API only | NOT FOUND |
| Underlying model | Not disclosed. Press says "not an LLM" | NOT FOUND (undisclosed) |
| Claims about judging agents | None. Use cases named: routing, escalation, retries, risk checks, fraud flag, claim approval, loan "needs more checks" (illustrations only) | VERIFIED (absence) https://www.parloa.com/labs/insights/jev-could-be-the-missing-decision-layer-for-agentic-cx/ |
| Bank customers | None named | NOT FOUND |
| Pricing | Sources disagree: $0.04 to $0.042 per 1M input tokens, output free (third-party). Another blog says ~$34 per 1M decisions. Official page not seen | UNVERIFIED https://www.llmreference.com/provider/typesafe-ai/jev |
| Speed claim | 70-500 ms per decision (vendor claim, no independent eval at launch) | UNVERIFIED |

Caution: one review says "cannot hallucinate" covers answer FORMAT, not answer correctness. https://wavect.io/es/blog/jev-ai-decision-model-review/

Fit for the supervisor: a possible cheap first-pass filter (for example "does this trace need review: yes/no"). Not a replacement for an LLM judge that reads reasoning. Not usable on-prem or in Databricks today as far as public data shows. Needs a holdout test on a bank golden set before any use.

Closest-name matches searched: "Jev.ai", "JEV", "Jeeves agent", "Jev decision engine" returned only the TypeSafe Jev above (plus unrelated LinkedIn profiles). No other credible product named Jev found.

## Task 2: Benchmarks and methods for choosing a judge/monitor

| Item | What it measures | Who scores well | URL | Status |
|---|---|---|---|---|
| JudgeBench (2410.12784) | Judge accuracy on hard pairs (knowledge, reasoning, math, code) with objective labels | Abstract: even strong models (GPT-4o) are only slightly above chance. Top list not read. Scores depend on split and prompt; do not compare across splits | https://arxiv.org/abs/2410.12784 | VERIFIED (abstract) |
| RewardBench 2 (2506.01937, ICLR 2026) | Reward models across several skills incl. Ties; models score ~20 pts lower than RewardBench 1 | Top list not read | https://arxiv.org/abs/2506.01937v1 | VERIFIED (search); rankings NOT FOUND |
| 2026 judge leaderboard | A ranked public leaderboard of judge models | BenchLM lists JudgeBench numbers but says reward models are "tracked, not publicly ranked" | https://benchlm.ai/models/skywork-reward-gemma-2-27b-judgebench | NOT FOUND (no authoritative one) |
| AgentHarm (2410.09024, ICLR 2025) | Whether agents refuse 110 malicious tool tasks (11 harm types, incl. fraud) | Leading models were "surprisingly compliant". It tests agents, not judges | https://arxiv.org/abs/2410.09024 | VERIFIED |
| FinVault (2601.07853) | Finance agent safety: 31 sandbox scenarios, 107 vulnerabilities, 963 cases; attack success up to 50%, best system 6.7% | Tests agents, not judges. Code: github.com/aifinlab/FinVault. Useful as a source of bank-style attack cases | https://arxiv.org/abs/2601.07853 | VERIFIED |
| Reliable Weak-to-Strong Monitoring (2508.19461) | Can weak monitors watch strong agents | A hybrid hierarchical-sequential scaffold lets weaker models monitor stronger agents. Agent awareness hurts more than monitor awareness helps. Human review of flagged cases gave ~15% TPR gain at 1% FPR | https://arxiv.org/abs/2508.19461 | VERIFIED |
| SLEIGHT-Bench (Anthropic, 2026) | 40 covert-harm coding transcripts, 11 monitor blind spots, 1% FPR | Opus 4.6 monitor: 50% of attacks never caught, 8/40 reliably. More compute and extended thinking help; code-running monitor helps more (~10x calls) | https://alignment.anthropic.com/2026/sleight-bench/ | VERIFIED |
| ControlArena APPS monitor pilot (LessWrong, informal) | 10 monitors vs 3 attackers | Specific model matters ~3x more than tier. Opus-4-8 best on all attacks; Haiku best on landed attacks but 23% false alarms. Small pilot | https://www.lesswrong.com/posts/3prmaGui6cq7cRjBh/monitor-identity-matters-more-than-tier | VERIFIED (not peer reviewed) |
| MonitoringBench (2605.09684) | Red-team of agent monitors | Capability concentrated in frontier models; weak monitors fail on stronger attacks | https://arxiv.org/pdf/2605.09684 | VERIFIED (snippet only) |
| Calibration-family overfit (2607.06596) | Trusted sabotage monitors do not transfer across model lineages | Title only read: supports family-independence and per-family calibration | https://arxiv.org/pdf/2607.06596 | SNIPPET ONLY |
| MLflow / Databricks judge alignment | Aligns an LLM judge to human labels on traces (MemAlign, SIMBA, GEPA). Needs MLflow 3.4+, >=10 traces with human feedback. Databricks claims 30-50% better agreement (vendor claim) | n/a (method) | https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/align-judges ; https://mlflow.org/docs/latest/genai/eval-monitor/scorers/llm-judge/memalign/ | VERIFIED. Default optimizer differs by doc version |

Gaps (NOT FOUND): public Vietnamese judge benchmark; ControlArena official monitor leaderboard; Anthropic/OpenAI single "pick a monitor" paper beyond the items above.

## Recommendation: pick and re-pick the judge (10 steps)

1. Build a golden set: 300+ bank traces labelled by humans, with Vietnamese cases, hard negatives, and attack cases borrowed from FinVault and AgentHarm styles.
2. List candidate judges that are NOT from the same model family as the supervised agents (family independence; see 2607.06596).
3. Drop candidates not available in your Databricks region, or with data-retention terms you cannot accept (zero retention, no training on data).
4. Score each candidate on the golden set: catch rate at a fixed 1% false-alarm rate, split by attack type (as SLEIGHT-Bench does). Do not trust one global accuracy number.
5. Run the same test on the Vietnamese subset alone. Reject a judge that falls more than an agreed gap below English.
6. Measure cost per 1k traces and p95 latency with real trace lengths.
7. Test stability: run each judge 5 times at the same settings; reject high variance. Pin an exact model version.
8. Align the best two with MLflow judge alignment using human labels, then re-score on a held-out part. Use a cheap first-pass (small model or Jev-style scorer, only if proven) and send flagged cases to a strong judge plus human review.
9. Choose by a written weighted score (accuracy 40, independence 15, Vietnamese 15, cost 10, latency 10, stability and terms 10); record the decision.
10. Re-pick every quarter and on any vendor version change, new agent family, or drift alarm: re-run steps 4 to 7 on a fresh sample, keep the old judge in shadow mode for 2 weeks.
