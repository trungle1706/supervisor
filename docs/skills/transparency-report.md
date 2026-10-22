# Skill: transparency-report

Read the transparency report of an AI system and explain it to the right reader: a regulator, a
customer or the bank itself. Use it when a person asks for the report, for what to tell a
customer, or whether the report is current.

Tools used: `transparency_report`, `get_entity`, `list_tasks`, `chain_verify`, `obligations`,
`regulations`.
Scopes: `governance.read`, `library.read`, `supervisor.read`.

## Rules

The server decides. Confirm before you write. Never classify by yourself.

* This skill only reads. It does not generate or sign a report; a reviewer does that in the
  console (Transparency page). If `info.status` is `preview`, say so: a preview is built from the
  current facts and is not signed.
* A report has three variants: `regulator`, `customer`, `internal`. Show the variant the person
  asked for. Never copy text from `internal` into a `customer` answer.
* Report only what the report says. Do not add claims about safety, fairness or compliance.

## Steps

1. Ask which variant and which system. `get_entity` (`kind: system`) to check the system and its
   linked agents.
2. Call `transparency_report` with `system_id` and `variant`. For each agent in the answer read
   `info.status` (`signed` or `preview`), `info.version` and the report sections.
3. If the status is `preview`, or the report is old, say what is missing and who signs it
   (a reviewer, on the Transparency page).
4. For the evidence behind a signed report call `chain_verify` for the agent and tell the person
   the result in one line: ok or the number of failures.
5. For the duties behind a section use `obligations` with the duty words and name the obligation
   id. Not legal advice. Bank counsel must confirm.
6. Offer **one** next step, for example `list_tasks` for the open tasks that block a signature.

## Do not

* Do not paraphrase a regulator report in a way that changes a number.
* Do not publish or send the report. You give it to the person who asked.
