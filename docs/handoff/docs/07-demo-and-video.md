# 07 · Demo script, video storyboard, deck structure

## Live demo (competition)

**Step 0 · Onboard live.** A developer deploys `loan-prequal-agent` as a Databricks App. Click Onboard. The panel watches the profile, data-flow map, monitoring plan, playbook, dashboard and PR appear; the agent goes to shadow mode. (Target: minutes on stage.)

**Four incidents, four response levels** (against the freshly onboarded agents; each must be re-runnable in under a minute via a reset button):
1. *Pause* — payments agent calls an unapproved tool after a prompt-injected support ticket; gate blocks before execution, agent paused.
2. *Alert* — service agent invents a fee-waiver policy; judge checks against the real policy list, alerts a reviewer.
3. *Log then escalate* — credit approvals creep up over a simulated week after a prompt update; drift detector opens a case when the rate leaves its band.
4. *Case opened* — overall approvals flat, one customer segment drifts 8 points; fairness monitor opens a case with sliced numbers.

**Tamper test:** edit one line in the evidence log on stage; the hash chain breaks visibly. **Stretch:** two agents each under their transfer limit, together over it.

## Video storyboard (assets/showcase3.mp4, 2:16, 1920×1080, 24 fps, no audio)

| Time | Scene | Beats |
|---|---|---|
| 0:00 | Title | "Supervisor · Two launches. Same Monday." |
| 0:05 | Part one · the race | Split screen Linh (manual) vs Minh (Supervisor); six-week calendar scrubs; event cards; counters (days, meetings, cost: 42+ / 3 / $14.8k vs 2 / 0 / $400); punch line: same injected ticket, 11 days unnoticed vs blocked in 7 ms |
| 0:32 | Part two · Day 0, gate by gate | Stepper of six gates; canvas: folder scan → understanding graph → agent + data architecture maps → monitoring plan (9 signals) + mechanism wiring → playbook + MLflow terminal → integration check 8/8 → report "Monitoring integrated correctly · READY TO LAUNCH" |
| 0:59 | Week 1 | Red-team dots vs GATE shield (113/120 blocked, 94%); claims linking to source docs (groundedness 0.94); segment bars settling in band (gap 14 → 1.8); GO stamp |
| 1:13 | Week 3 | Approval-rate line drifts out of band; CASE SUP-0187; fixed, prompt v1.3 |
| 1:23 | Month 2 | Segment C bar drops and turns red; CASE SUP-0231 fairness gap 8 pts; segment frozen, root cause stale bureau feed |
| 1:34 | Month 6 | Audit pack: 1,842 cases, 100% covered, chain verified, exported, mapped to Decision 33 and MAS; "Every agent gets this story, automatically." |
| 1:44 | Part three · as the fleet grows | Three animated charts 3→40 agents: governance cost, incident exposure, net benefit; band: −50% / −89% / ×7 |
| 2:02 | Close | 1 day / 100% / 1 incident payback; tagline; Supervisor |

Every scene carries an "illustrative / mock data" label. Voice-over script with timings: `assets/showcase-voiceover.txt`. Regenerate: `src/video/` (see 08 for commands).

## Deck structure (assets/Supervisor.pptx, 22 slides)

1 Cover · 2 Executive summary · 3 Velocity mismatch · 4 Three risks + regulation · 5 Every launch is a bespoke project · 6 One platform, two jobs · 7 Onboard: six stages · 8 Seven artefacts · 9 Plug points + capability catalogue · 10 Watch: five steps, two speeds · 11 Architecture · 12 Components and sources · 13 Judge tiers · 14 Case file · 15 Showcase video · 16 Metrics · 17 Live demo · 18 Enterprise readiness · 19 Cost · 20 Benefit · 21 Roadmap · 22 Close.

Each slide has speaker notes. Two `[Team name]` placeholders on slides 1 and 22. Bracketed figures on slide 20 need bank data.

## Earlier video approaches considered (for reference)

A split-screen race; B fleet/portfolio view (CRO's eyes); C life of one agent; D guided product tour. Chosen: A+C hybrid, later extended with Day 0 gate-by-gate, Week 1 animations and the fleet charts (B's idea folded in as Part three). D remains the live demo.
