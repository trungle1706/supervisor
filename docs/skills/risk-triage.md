# Skill: risk-triage

Find the risks of an AI system that have no control or no owner, and propose draft risks for the
gaps. Use it when a person asks "what risks are missing", "triage the risks" or "propose risks".

Tools used: `get_entity`, `list_entities`, `starter_risks`, `starter_controls`, `propose_risk`,
`guardian_catalog`, `assignment_rules`, `kpis`.
Scopes: `governance.read`, `governance.write`, `library.read`.

## Rules

The server decides. Confirm before you write. Never classify by yourself.

* `propose_risk` stores a **draft**. It is never active. A person reviews it in the console and
  makes it active.
* You cannot accept a risk, lower a residual score by yourself or change a risk level. The tool
  refuses `treatment: accept`. If the person wants to accept a risk, send them to the console.
* Give the scores (likelihood and impact, 1 to 5) as the person's, not as yours. Ask for them.
* Call `propose_risk` first without `confirm`, show the planned change, then with `confirm: true`
  after a yes.

## Steps

1. `get_entity` (`kind: system`) for the system and its linked agents (`components`).
2. `list_entities` (`kind: risk`) and keep the risks whose `agent_id` is one of those agents.
   Note the ones with no control: the Controls tab of the system, or `list_entities`
   (`kind: control`) to see which controls exist.
3. Compare with the library. `starter_risks` lists risks that fit the agent kinds (money
   movement, credit decision, personal data, injection, model behaviour, availability, third
   party). `assignment_rules` shows which starter risks the rules already assign to the system.
4. List the gaps in a short table: the starter risk id, the title, why it fits this system.
   Offer to propose **one** at a time.
5. For the chosen gap ask the person for: the agent, the category, likelihood, impact, treatment
   (`avoid`, `mitigate` or `transfer`), the owner and the review date. Then `propose_risk`
   (without, then with `confirm`).
6. Tell the person that the draft waits for review in the console.

## Do not

* Do not propose more than one risk without a yes for each.
* Do not copy text from the starter risk as if it were the person's own assessment. Name the
  starter risk id in the description.
* Do not claim that a system is "low risk". The level is set and inherited by the server.
