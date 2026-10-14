# 08 · Roadmap and implementation backlog

## Roadmap

| Phase | When | Scope |
|---|---|---|
| Competition build | Oct → mid-Nov 2026 | Three mock agents + red-team incident set; Onboard stages 1–3 with generated profile/plan/dashboard/PR; Watch: gate with blocking, tiered judge, drift + fairness; evidence chain, case files, metrics panel; live demo (onboard on stage + four incidents) |
| Production candidate | Dec 2026 | Onboard one real agent team in shadow mode; Launch stage automated (red-team, baseline, go/no-go); SSO, roles, masked logs, retention; model-risk sign-off; legal sign-off on fairness attributes; runbooks for pause and rollback |
| Scale out | H1 2027 | Blocking on; payments and credit agents onboarded; capability catalogue opened to product teams; OTel and proxy plug points for non-Databricks agents; regulator export pack (Decision 33, MAS); red-team suite on every release; vendor PoCs (gateway, registry) |
| Advanced | H2 2027 | General multi-agent pattern detection; simulation sandbox for agent groups; containment playbooks with human approval; fine-tuned in-house monitor (e.g., Qwen3.5 4B on bank incidents); onboarding for agents outside Databricks |

Team of four: agent builder, onboarding engineer, supervisor engineer, risk and pitch.

## Suggested repository layout (Databricks Asset Bundle)

```
supervisor/
  databricks.yml                 # bundle: jobs, apps, model serving endpoints
  agents/                        # three mock agents (customer service, credit pre-check, payments)
    customer_service/  credit_prequal/  payments/
    redteam/incidents.jsonl      # planted incidents + attack taxonomy (OWASP agentic, FinVault)
  gateway/                       # fast-lane proxy service (mcp-scan pattern), policy YAML, checks (OpenAI Guardrails port), Prompt Guard, Presidio
  judge/                         # tier1/tier2 scorers as MLflow scorers; ControlArena-style protocol; model routing (family != agent family)
  monitors/                      # drift (Lakehouse Monitoring metrics), fairness slicing, quality judges, multi-agent streaming job
  onboard/                       # Onboarding Agent: discover.py, understand.py, plan.py, instrument.py (PR), launch.py; templates for artefacts
  catalogue/                     # capability manifests (yaml), loader
  evidence/                      # append-only Delta writer with hash chain, anchor job, case-file generator, audit-pack export
  console/                       # Databricks App (reviewer console, metrics, sign-off via Lakebase)
  registry/                      # agent identity registry schema + API
  demo/                          # incident injection + reset harness
  docs/                          # this handoff
```

## Backlog (first two sprints, in order)

**Sprint 1 (weeks 1–2)**
1. Mock agents with tools, limits and a policy list on fake but realistic bank data; OTel/MLflow tracing on; each agent has an ID in the registry.
2. Red-team incident set written before any checks (the test fixture).
3. Gateway service: approved-tools rule, transfer limits, PII block/mask, injection screen; pause switch; latency budget < 50 ms.
4. MLflow tracing → Unity Catalog tables; inference tables on; Presidio masking UDF.
5. Onboard Discover + Understand: read App/repo/prompts/tools/UC lineage → inventory + agent profile (Markdown + JSON) + understanding graph.

**Sprint 2 (weeks 3–4)**
6. Tiered judge: Tier 1 scorer on 100% (Haiku 5.5 or GPT-5.4 mini), Tier 2 on flags + 1.5% sample (Opus 5.5 / GPT-5.5 / Qwen3.5 122B); suspicion score schema; escalation.
7. Drift detector (baseline band per version) and fairness slicing; quality judges (groundedness, relevance) on customer-facing answers; thresholds in the registry.
8. Onboard Plan + Instrument: monitoring plan + playbook from the catalogue; generated policy YAML, dashboard definition, alert routes; open a PR.
9. Evidence chain: append-only Delta, hash column, anchor job, tamper check; case-file generator; audit-pack export.
10. Reviewer console (Databricks App): cases, sign-off, pause/resume, metrics panel (coverage, time-to-detect, time-to-human, catch rate, false alarms, chain status, groundedness, fairness gap, deployment-to-launch).
11. Demo harness: inject incidents 1–4 with reset; tamper test; rehearse.

## Regenerating the deliverables

Deck (pptxgenjs preinstalled in the original environment; `npm i pptxgenjs` otherwise). `build.js` requires `apply_theme.js` from the pptx skill; if absent, remove the `applyTheme` call (scheme colours then fall back to Office defaults) or vendor the file.
```
cd src/deck && VIDEO=../../assets/showcase3.mp4 POSTER=poster.jpg node build.js Supervisor.pptx
```
Video (Playwright + Chromium, ffmpeg):
```
cd src/video && python render.py preview      # key frames
python render.py full && ffmpeg -framerate 24 -i frames/f%05d.jpg -c:v libx264 -crf 21 -pix_fmt yuv420p -movflags +faststart showcase.mp4
```
Scene timing lives in `scene.html` (`S` array for scene windows, `keys` for camera moves, per-beat `f(t, start, dur)` calls).
