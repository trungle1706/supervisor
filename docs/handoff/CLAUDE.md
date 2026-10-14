# Supervisor — project context for Claude Code

Read this file first. It is the distilled output of a multi-day planning session (9–14 Oct 2026) for a Techcombank "AI Builder" competition entry on the topic **AI Governance Supervisor**. Everything below is settled unless marked *open*. Details live in `docs/`; deliverables in `assets/`; generators in `src/`.

## What we are building, in one paragraph

**Supervisor** is a plug-and-play platform that takes any AI agent the bank runs (new or already deployed) from deployment to supervised launch, then watches every action it takes and turns incidents into evidence a regulator can act on. It has two jobs: **Onboard** (lifecycle: discover → understand → plan → instrument → launch → operate, each stage gated and producing a document) and **Watch** (runtime: millisecond gate that can block, tiered AI judge on a different model family, drift/fairness/quality/multi-agent checks, hash-chained evidence log, case files, reviewer console). It runs on the bank's **Databricks** and is independent of the agents it supervises (read-only copy of traffic in, one narrow "pause" verdict out, its own decisions logged in the same chain). The Onboarding Agent is itself an agent and runs under Watch; its integration changes go out as pull requests and never auto-merge.

## Why it matters (the brief, compressed)

The challenge: build an independent "agent supervising agents" that evaluates agent activities against expected behaviour, business policies, authorization boundaries, risk controls **and performance thresholds**, observes rather than just logs, and produces evidence a human reviewer or regulator could act on. Three pain points: velocity mismatch (agents change in hours, review in weeks), emergent multi-agent risk, no real-time proof of control. We target the first and third as core and prototype the second. Regulatory timing: Vietnam AI Law in force 1 Mar 2026; Decision 33/2026/QD-TTg (15 Aug 2026) lists autonomous banking transactions and credit decisions as high-risk; MAS AI risk guidelines published 7 Oct 2026. See `docs/01-problem-and-brief.md`.

## Timeline and scope

- **Competition submission: mid-November 2026** (confirm exact date). Four-week build.
- **December 2026:** production candidate, one real agent team in shadow mode.
- **H1 2027:** scale out, capability catalogue open to product teams, OTel and proxy plug points.
- **H2 2027:** general multi-agent detection, simulation sandbox, fine-tuned in-house monitor.
- Scope rule: enterprise-ready shape from day one (SSO, roles, masking, residency, shadow mode, PR-only changes), but the competition build is three mock agents plus a live onboarding demo.

## Architecture (see `docs/03-architecture.md`)

Rows top to bottom: Bank agents → **Onboard** (Onboarding Agent, capability catalogue, plug-in adapters, generated artefacts + PR) → Shared channel (fast-lane gateway, agent message bus, MLflow 3 trace store in Unity Catalog, agent identity registry) → **Watch** (rule engine, tiered AI judge, quality monitor, drift + fairness, multi-agent check) → Evidence and people (hash-chained log, case-file generator, reviewer console as a Databricks App, oversight metrics).

Sourcing rule: ~⅓ Databricks native, ⅓ copied from open source (MIT/Apache-2.0 only; Elastic-licensed tools excluded), ⅓ original. Original work = Onboarding Agent, capability catalogue, drift + multi-agent checks, evidence chain + case files. Those are also the gaps no vendor fills.

## Judge model policy

Judge never shares a model family with the agents it watches. Three tiers: Tier 0 inline, no LLM (rules + Llama Prompt Guard 2 + Presidio); Tier 1 cheap monitor on 100% of traces (Claude Haiku 5.5 or GPT-5.4 mini); Tier 2 strong judge on flags + random sample (Claude Opus 5.5, GPT-5.5, or Qwen3.5 122B on provisioned throughput for fully in-region). Avoid Fable models on Databricks (30-day retention) and Gemini (global endpoint, cross-region). Purpose-built guard models are pre-filters only (FinVault: best guard model 61% TPR / 30% FPR).

## Business case (illustrative; swap in bank figures)

Year 1 ≈ $381k, run-rate ≈ $309k/yr. Benefits: launch in hours not 4–6 weeks (~$15k and weeks saved per agent), unlocks high-risk agents under Decision 33, one prevented incident covers a year of run-rate, ~1 FTE of manual review redeployed. Fleet model: at 40 agents, governance cost −50%, incident exposure −89%, net benefit ×7 vs manual. See `docs/04-business-case.md`.

## Deliverables already produced (in `assets/`)

- `Supervisor.pptx` — 22-slide consulting-style deck, video embedded on slide 15, speaker notes on every slide. Regenerate with `src/deck/build.js`.
- `showcase3.mp4` — 2:16 concept video (race → Day 0 gate-by-gate → week 1 animations → drift/fairness/audit → fleet charts → close). Regenerate with `src/video/`. No audio; `showcase-voiceover.txt` is the timed script.
- `supervisor-playbook.html`, `guardian-market-scan.html` — the two web pages (self-contained) that preceded the deck.

## Conventions for this repo

- Plain language in all user-facing text; action titles; no invented statistics (bracketed placeholders like `[$__]` where the bank must supply a number).
- Every claim with a source; keep `docs/06-research-sources.md` current.
- Illustrative data must be labelled illustrative on screen.
- Vendor comparison claims are labelled as vendor claims.
- Deck: pptxgenjs, theme colours dk1 122034 / accent1 0B6E8E / accent2 B9792B / accent3 B23A32 / accent5 7A3E9D; Cambria headings, Calibri body. Video: HTML scene + Playwright frame capture + ffmpeg, 1920×1080, 24 fps.

## What Claude Code should do next (suggested order)

1. Scaffold the implementation repo per `docs/08-roadmap-and-backlog.md` (Databricks Asset Bundle layout).
2. Build the three mock agents and the red-team incident set first (they are the test fixture for everything else).
3. Fast-lane gateway (mcp-scan proxy pattern + OpenAI Guardrails checks), then MLflow tracing into Unity Catalog, then the tiered judge as MLflow scorers.
4. Onboarding Agent stages Discover → Understand → Plan (report generation), then Instrument (PR generation); Launch automation is December.
5. Evidence chain (append-only Delta + hash column + anchors), case-file generator, Databricks App console.
6. Demo harness: incident injection with reset.

*Open items:* official submission date; bank's Databricks region and model availability; which fairness attributes legal permits slicing by; real figures for the cost/benefit model; team name.
