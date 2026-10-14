# Worker brief (shared by all analysis agents)

Project: "Supervisor" — Techcombank AI Builder competition entry (AI Governance Supervisor). Handoff bundle at
/home/trung/supervisor-handoff. Read CLAUDE.md first, then docs/01..08. Assets in assets/, generators in src/.
Today is 2026-10-14. Competition submission mid-Nov 2026. Goal after competition: a fully functional product
that integrates into Techcombank's systems and the bank's Databricks platform.

Your job: supplementary analysis for ONE lens (given in your prompt). Find gaps, risks, and improvements the
handoff package misses. Be concrete: name the missing component, why it matters, what to add, effort (days/weeks),
and which phase (competition / Dec production candidate / H1 2027 / H2 2027).

Rules:
- Verify claims with web search where it matters (Databricks features, licences, regulations, model availability).
  Mark each finding as VERIFIED (with URL) or ASSUMED.
- Do not invent statistics. Use brackets like [bank to supply] where a number is unknown.
- Write your report to /home/trung/supervisor-handoff/analysis/<your-file>.md in this shape:
  1. One-paragraph verdict for your lens.
  2. Findings table: | # | Gap / risk | Severity (H/M/L) | Evidence | Recommendation | Effort | Phase |
  3. Detailed notes per High finding (max 10 lines each).
  4. Things the handoff gets RIGHT (short list — so we don't "fix" what works).
  5. Open questions for the bank (numbered).
- Max ~250 lines. Plain English. Short sentences. Tables over prose.
- Do not modify any file outside analysis/.
