# 01 · Problem and brief

## The challenge text (transcribed from the Techcombank AI Builder page)

**Topic: AI Governance. Pain points.** As Techcombank Group scales autonomous AI agents across customer service, operations, product, risk, and employee productivity, a systemic governance gap emerges: human oversight cannot keep pace with how fast these agents evolve. Modern AI agents continuously learn, adapt decision logic, invoke new tools, and collaborate with other agents, exposing three structural risks:

- **Velocity mismatch** — agents adjust behaviour in near real-time or short cycles (hours/days), while human review operates on periodic cycles (weeks/months). Risk accumulates undetected in that gap.
- **Non-linear, emergent risk** — when agents interact, aggregate risk is not the sum of individual agent risks; new behaviours can emerge that no single agent exhibited in isolation testing.
- **No real-time proof of control** — even where review exists, the organization struggles to demonstrate to regulators that oversight kept pace with agent adaptation, particularly after an incident (hallucination-driven decisions, policy violations, unauthorized actions beyond approved scope).

**Challenge.** Build an AI Governance Supervisor that acts as an independent "agent supervising agents." The Supervisor continuously evaluates AI agent activities and decisions against expected behaviour, business policies, authorization boundaries, risk controls, and performance thresholds. Each team must pick at least one of these three pain points and build a solution that directly answers it, corresponding to one of the three tracks below. Regardless of track, the solution must behave as an independent supervisory agent: it observes, it does not just log, and it must produce evidence a human reviewer or regulator could act on. The solution should function as an independent supervisory agent, providing transparency, explainability, auditability, and continuous assurance that AI agents remain aligned with business objectives, operational controls, regulatory requirements, and risk appetite.

*The three track definitions were cut off in the screenshot. Map the plan to them before submitting.*

## Our reading of the brief

- "Performance thresholds" means quality evaluation is in scope, not only behaviour supervision: groundedness, fairness, adversarial robustness. The quality monitor exists because of this line.
- "Observes, does not just log" means blocking and pausing are required, not optional.
- "Evidence a human reviewer or regulator could act on" is the differentiator: tamper-evident case files, not dashboards.

## The fourth problem we added

Every agent launch today is a bespoke governance project: working out what the agent touches (3–5 days), risk assessment and Decision 33 tiering (1–2 weeks), tracing/logging/guardrails (1 week), dashboards and alerts (3–5 days), runbooks and sign-off pack (1 week). Total 4–6 weeks per agent (illustrative estimate). Consequences: inconsistent instrumentation, governance as the critical path, no market product that reads an agent and produces its launch pack. This is what justifies **Onboard**.

## Regulatory context (verified)

| Date | What | Why it matters |
|---|---|---|
| 1 Mar 2026 | Vietnam Law on AI No. 134/2025/QH15 in force; three risk tiers; human oversight for high-risk | First standalone AI law in the country |
| 15 Aug 2026 | Decision 33/2026/QD-TTg: 46 high-risk systems across six sectors; banking: AI that autonomously executes banking transactions or makes credit approval decisions | Many listed systems are high-risk only when AI output is the sole basis without meaningful human review, so demonstrable oversight is the control |
| 7 Oct 2026 | MAS Guidelines on AI Risk Management for Financial Institutions (effective 7 Oct 2027) | Regional benchmark: inventories, risk materiality, lifecycle controls, human oversight |
| Draft law provisions | Revenue-based fines for serious violations by large organisations; temporary or permanent suspension of a system | Confirm against final text |

## Market context (verified)

- Gartner Market Guide for Guardian Agents (25 Feb 2026): market is early, observation and posture focused, limited inline blocking; through 2028 at least 80% of unauthorised agent transactions will be internal policy violations rather than attacks; recommends deterministic checks before model-as-judge and meta-governance of the supervisors themselves. Gartner predicts guardian agents at 10–15% of the agentic AI market by 2030.
- Frontier labs run exactly this on their own agents: OpenAI monitors internal coding agents (chain of thought + actions, review within ~30 min); Anthropic reports ~30,000 concurrent agents, every action through an online monitor, ~1 in 47,000 blocked, offline monitor flags 1–2 per 1,000 transcripts; Google DeepMind's AI Control Roadmap (June 2026) treats agents as potential insider threats with trusted AI supervisors that can block.
- Research: multi-agent systems show collusion-like and conformity behaviours that agent-level safeguards cannot prevent (Huang et al., ICML 2026; Gradient Institute report for the Australian Government).
