# LLM-empowered features (WP-L1)

This page lists every feature that calls a language model. In the Databricks App (`app.yaml`)
all of them are on. They all use one model: the bank chat model, a Unity Catalog model service
behind the Databricks AI Gateway.

## Model settings

| Setting | Value |
|---|---|
| `LLM_BASE_URL` | `https://<workspace host>/ai-gateway/mlflow/v1` |
| `LLM_MODEL` | `<catalog>.<schema>.<model-service>` (3 parts) |
| `LLM_API_SHAPE` | `responses` (use `chat` if the gateway accepts only `/chat/completions`) |
| Login | The App service principal (OAuth). No key is stored. |
| Grant | The App service principal needs EXECUTE on the model service in Unity Catalog. |

The model family (for example `glm`) comes from the 3-part name. The judge family rule still
applies: the judge and guard family must differ from the family of every agent they watch.

`JUDGE_FAMILY_CONFLICT_ALLOW=1` (default `0`, allowed in `databricks_app` mode) is for sandbox
and single-model workspaces. The judge, guard and quality scorer then start even when they share a
family with an agent. One WARNING per judge/agent pair is logged ("judge family conflict
allowed"). Each `judge_verdict` evidence record for such a pair carries `independence: "reduced"`
and `family_conflict: true`. The judge still only advises, but its independence is reduced: do
not use its verdicts as independent evidence. An unknown family is still refused.

## The features

| Feature | What it does for the user | Where it runs | Switch (App value) | What it sees | What it can do | What it can never do |
|---|---|---|---|---|---|---|
| Judge Tier 1, Tier 2, challenger | Reads agent traces and gives an opinion on risk | Scheduler sweep (judge sweep) and console action | `JUDGE_ENABLED=1`, `JUDGE_T1_MODEL=<3-part name>` (empty = mock judge). T2 and challenger: `JUDGE_T2_MODEL`, `JUDGE_CHALLENGER_MODEL` (empty = off or mock) | Masked trace text only | Advise, raise severity, open a case | Block or pause a call; call the gate |
| Detector `judge_advisory` | Gives a Tier 1 opinion on a call while it passes the gate | Gate call path | `DETECTORS_ENABLED=1` and `enabled: true` in `config/detectors.databricks.yaml` (set by `DETECTORS_CONFIG`) | Masked arguments and results | Add a finding to the gate answer | Block, pause or fail closed |
| Detector `judge_moderation` | Checks for toxic text (and topics, if listed) | Gate call path | Same file; `toxicity.enabled: true` | Masked text, in windows | Add a finding | Block, pause or fail closed |
| Detector `guard_model` | Scores text for jailbreak and indirect injection | Gate call path | Same file; `GUARD_MODEL_ADAPTER=chat` (model = `JUDGE_T1_MODEL` unless `GUARD_MODEL_NAME` is set) | Masked text, in windows | Add a finding. It can pause money or credit tools only if `pause_tool_classes` is set AND a model card approval names a person. Both are off here. | Block, or fail closed |
| Decision 33 classification prefill | Fills a draft of the classification answers | Console action | `CLASSIFIER_AI_PREFILL=1` (needs `GOVERNANCE_ENABLED=1`) | Masked system description | Write a draft tagged `ai_prefill` | Apply an answer. A person must apply it. |
| Integration advisor | Reads an agent repo and suggests how to wire it to Supervisor | Onboarding stage; console tab; CLI `python -m supervisor.advisory.integration` | `ONBOARD_ADVISOR_ENABLED=1` (stage), `CONSOLE_INTEGRATION_ENABLED=1` (tab) | Repo text after secret scrubbing | Write a report | Change the repo or the gate |
| Compliance advisor | Suggests a compliance matrix for a product | Onboarding stage; console tab; CLI `python -m supervisor.advisory.compliance` | `ONBOARD_COMPLIANCE_ENABLED=1` (stage), `CONSOLE_COMPLIANCE_ENABLED=1` (tab) | Masked product facts | Write a matrix draft | Mark a control as met; decide launch |
| Onboarding agent (`run_onboarding`, console onboard runs) | Writes the onboarding steps and the pull request text | Console action; CLI `python -m supervisor.onboard` | Uses `LLM_BASE_URL`. If the model check fails it falls back to the mock model. | Scrubbed repo text | Open a pull request for a person to review | Merge; push to a protected branch |
| Define from artifact (`--llm`) | Drafts an agent definition from a file | CLI `python -m supervisor.onboard.define --llm` | Flag `--llm` (uses the configured model) | The artifact text after scrubbing | Write a draft | Register the agent by itself |
| Red team LLM attacker | Writes the attack turns of the multi-turn Vietnamese red team test | Nightly job and assurance run | `REDTEAM_ATTACKER_MODEL=<3-part name>` (empty = template attacker). Nightly job: `REDTEAM_NIGHTLY_ENABLED` (stays 0 here) | Test objectives only | Produce test text; fall back to the template on any error | Touch real agents or real data |
| Law agent (WP-L1) | Reads the stored official text of one instrument article by article and drafts the duties in it, each with a verbatim quote | CLI `python -m supervisor.regkb.lawagent --instrument <id>` (an engineer runs it; the console has no run button) | `LAWAGENT_ENABLED=1` (needs the CLI or the page `/console/regkb/<id>/drafts`). `LAWAGENT_MODEL=<3-part name>` (empty = `LLM_MODEL`). A mock model is refused unless `--allow-mock`. | Law text only (public, no personal data) and the duty vocabulary | Write drafts to the `regkb_draft` table. The rules drop a draft whose quote is not in the article, whose duty id is unknown or whose article does not exist. | Make an obligation, or mark anything verified. A person with `regkb.confirm` confirms a draft; the CLI exports confirmed rows for a pull request. Not legal advice. |

## Rules for every feature

- Only a deterministic rule can block or pause. A model answer is advice.
- `LLM_MOCK=1` forces mock adapters. Every mock verdict is labelled `mock`.
- To switch one feature off, set its value to `"0"` (or clear the model name) in `app.yaml`.
- Detectors: `config/detectors.yaml` keeps the default (off). The App uses
  `config/detectors.databricks.yaml`, with `limits.timeout_ms` 8000 because a model call is slow.
