# Skill: d33-prep

Prepare the Decision 33 (33/2026/QD-TTg) classification of an AI system for a person. You make a
draft and explain it. A person edits and applies it in the console.

Tools used: `get_entity`, `list_entities`, `classification_draft`, `obligations`, `regulations`,
`list_tasks`.
Scopes: `governance.read`, `governance.write`, `library.read`.

## Rules

The server decides. Confirm before you write. Never classify by yourself.

* `classification_draft` makes a draft from the assignment rules. It never changes the class of
  the system. There is no tool that applies a classification, and you must not say that the
  system "is" high risk or not high risk. Say "the draft outcome is ...".
* Call `classification_draft` first without `confirm`, then with `confirm: true` after a yes.
* Obligations from the library are advisory. Not legal advice. Bank counsel must confirm.

## Steps

1. Get the system with `get_entity` (`kind: system`). Check the intake fields that drive the
   questions: `system_type`, `user_segment`, `personal_data`, `money_movement`, `credit_decision`,
   `human_control`, `autonomy_level`. If one is missing or `unspecified`, tell the person which
   one and why it matters. Do not fill it in for them.
2. Call `classification_draft` without `confirm`, then with `confirm: true`.
3. Read `classification.answers`. For each question show the answer, its `source` (`rules`,
   `ai_prefill` or `person`) and the justification. Mark every answer with source `ai_prefill`
   as "a model suggested this; a person must check it".
4. Show `classification.outcome` and `decided_by_rule` as the **draft** outcome.
5. Use `obligations` (query `33/2026` or the duty words) to explain what follows from each
   outcome. Quote the obligation id and the article.
6. Say what the person does next: open the system in the console, tab Classification, edit the
   answers, and apply. Offer `list_tasks` to show the validation tasks that wait.

## Do not

* Do not edit the answers. Only a person does.
* Do not repeat a draft to "get a better answer". The same system and the same rules file give
  the same draft.
