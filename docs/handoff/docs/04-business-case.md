# 04 · Business case (illustrative; replace bracketed figures with bank data)

## Cost model

Assumptions: $0.07 per DBU (Databricks serverless list; confirm contract rate); 10% regional-processing uplift on Claude models; Vietnam loaded engineer cost ~$6k/month; 300k agent actions/day across three agents at scale; ~3k input tokens per Tier 1 read, ~6k per Tier 2 read; 1.5% of traces reach Tier 2; ~2 onboardings per month.

Token prices (Databricks published, DBU per 1M tokens): Claude Haiku 5.5 in 1.429 / out 7.143; Claude Sonnet 5.5 in 28.571 / out 142.857; Claude Opus 5.5 in 57.143 / out 285.714.

| Line | Basis | Year 1 | Run-rate/yr |
|---|---|---|---|
| Build team (one-off) | 4 people × 3 months | $72k | – |
| Run team | 1.5 FTE | $108k | $108k |
| Tier 1 monitor tokens | Haiku 5.5, 100% of traces | $45k | $45k |
| Tier 2 judge tokens | Opus 5.5, 1.5% of traces | $65k | $65k |
| Quality scorer tokens | MLflow groundedness/relevance judges | $20k | $20k |
| Onboarding runs | Opus reads code/prompts/traces, ~2/month | $8k | $8k |
| Tier 0 screen | small GPU endpoint (Prompt Guard, Presidio) | $15k | $15k |
| Platform compute | gateway endpoint, streaming, monitoring, storage, App | $48k | $48k |
| **Total** | | **$381k** | **$309k** |

Buying instead: enterprise governance platforms are custom-quoted (typically six-figure annual licences) plus integration; none onboards an agent; evidence layer and judge tokens would still be built and paid for.

## Benefits

1. **Launches in hours, not weeks.** Today ≈ [2 FTE × 5 weeks] ≈ [$15k] per launch plus delay; at [10 agents/yr] ≈ [$150k] of effort and months of time-to-market returned.
2. **Unlocks the agent programme.** Decision 33 makes autonomous transactions and credit decisions high-risk; continuous oversight with evidence is the control that lets the bank deploy them. Value = the programme's own case, [$__/yr].
3. **Avoids incident losses and sanctions.** One blocked unauthorised transfer, or a hallucinated fee waiver reaching [1,000] customers at [$50], covers a year of run-rate. AI Law draft contemplated revenue-based fines and suspension.
4. **Replaces sampled manual review.** 100% coverage replaces periodic transcript sampling: ≈ [1 FTE] redeployed (~$50k/yr); audit prep from weeks to exporting case files.

Break-even: run-rate ≈ $309k/yr is covered by onboarding savings across [10] agents plus one analyst redeployed, before any prevented incident.

## Fleet model (used in the video's Part three)

Agents in production Q4'26→Q4'28: 3, 5, 8, 12, 16, 21, 27, 33, 40. Manual route effective agents (launches capped by review capacity): 3, 5.5, 8, 10.5, 13, 15.5, 18, 20.5, 23.

- Governance cost/yr: manual = 60 + 22·N ($k); Supervisor = 309 + 4·N.
- Incident exposure/yr: manual = 18·N; Supervisor = 2·N.
- Net benefit/yr: 90·N_effective − cost − exposure.
- At N = 40: cost $940k vs $469k (−50%); exposure $720k vs $80k (−89%); net benefit $410k vs $3,051k (×7).

All of these are modelling assumptions, printed on screen in the video. Replace with the bank's launch costs, incident history and programme value.
