# Classification tree (WP-C1 of phase 12)

Flag `CLASSIFICATION_V2=1` (needs `GOVERNANCE_ENABLED=1`). Off by default. Windows cmd:
`set CLASSIFICATION_V2=1`.

The tree gives each AI system one of six outcomes. A person walks it, a second person approves the
result, and only then does the risk level of the system change. The questions follow Law 134/2025
(Art. 7, 9, 10, 13), Decree 142/2026 (Art. 6, 8, 9, 11, 12), Decision 33/2026 and Circular 53/2026
Art. 4. The file is `config/classification.yaml` and it is ILLUSTRATIVE: counsel confirms it.

## The tree

```
N-SYSTEM  AI system, or model in a system?   Decree 6(2)
   |no --> not_system                         (nothing changes)
   |yes
N-PROHIBITED  forbidden purpose?             Law 7(2)
   |yes --> prohibited
   |no
N-PM-LIST  on the Prime Minister's list?     Decree 6(3)   answered by the Decision 33 questions
   |not_high_risk ----------------------+
   |high_risk                            |
N-THRESHOLD  over an SBV threshold?      Circular 53 Art. 4(2)
   |no  ---------------------------------+
   |yes                                  |
N-CERT  certificate before use?          Law 13(1)         N-CONFUSE  confuses users about AI?  Law 9(1)
   |yes --> high_certify                                       |yes --> medium
   |no  --> high_self                                          |no or excluded --> low
```

| Outcome | Risk level | Duties named on the outcome card |
|---|---|---|
| `not_system` | no change | none |
| `prohibited` | `prohibited` | do not build, supply, deploy or use (Law 7(2)) |
| `high_certify` | `high` | certificate (Law 13), impact assessment (Circular 53 Art. 13), board approval (Art. 12(3)), dossier (Decree 12(2)), notice to the Ministry (Law 10(3)) |
| `high_self` | `high` | the same, with the conformity assessment by the provider or a registered body |
| `medium` | `medium` | dossier (Decree 12(2)), notice (Law 10(3)) |
| `low` | `low` | none |

The SBV thresholds sit in the file as integers in VND: person 10,000,000 per transaction and
20,000,000 per day; organisation 50,000,000 and 100,000,000; credit 50,000,000.

## Answers

Each node takes `yes`, `no` or `excluded` (a legal exclusion applies; Decree 9(3) for the medium
node). A node can have a `prefill` rule: a deterministic condition over the fields of the system
record, written in the same syntax as `config/assignment_rules.yaml`. A model never answers. The
page shows who answered each node: a rule, a person, or the Decision 33 flow. A person's answer
always wins over a rule.

The node `N-PM-LIST` has no questions of its own. The four questions of
[Decision 33](decision33.md) answer it (`high_risk` or `not_high_risk`). The tree does not repeat
them. While those questions are open the path stays open at that node.

## Steps

| Step | Who | What happens |
|---|---|---|
| Evaluate | a person with `systems.edit` | The page walks the tree for the given answers. Nothing is stored. |
| Save (`decide`) | a person with `systems.edit` | The path is stored in `classification_v2`. A path that does not end in an outcome is refused (`incomplete_path`). The system does not change. |
| Approve | a second person with `systems.approve` | The risk level is raised to the level of the outcome (never lowered). The Decision 33 draft of the sub-flow is made from the answers and applied with the existing `apply`. |

Rules of the approval (Circular 53 Art. 4(3)):

- The person who approves is not the person who decided: HTTP 400 `same_person`.
- The system owner (`owner_user` or an active `system_owner` of the team) cannot approve:
  HTTP 400 `owner_cannot_approve`.
- A tree file that changed after the decision is refused: HTTP 400 `tree_changed`. Decide again.
- Decision 33 `apply` has its own checks (autonomy level set, the owner rule of
  `CONSOLE_STATE_ACTIONS`, a person with `systems.edit`). A refusal there is a 400 and the record
  stays waiting for approval. It is skipped when the list says high but the threshold node says no
  (the tree overrules the list), so the Decision 33 class does not claim high risk then.
- Record fields: `decided_by`, `approved_by`, `approved_at`, `inherited_from_provider` (the bank took
  the provider's result, Art. 4(4)) and `valid_until` (review every year, Art. 4(5); set again at
  approval). The summary counts the records whose date has passed as review due.

A record has the status `pending_approval` until it is approved. Only the newest record counts. A
new decision replaces a record that waits for approval; an approved record stays in the history.

## Levels

`prohibited` gives the risk level `prohibited`; `high_certify` and `high_self` give `high`; `medium`
gives `medium`; `low` gives `low`; `not_system` changes nothing. The floor rule of Decision 33 holds:
the stored level never goes down here. A lower level needs the separate reasoned call
`POST /v1/systems/{id}/risk-level/lower`.

## Re-classification

The page lists the events that start a new classification (Decree 142 Art. 11(1)(a)-(d) and 11(2))
and names the event that does not (Art. 11(4): upgrades, tuning, ordinary bug fixes, periodic data
updates that leave the nature of the risk unchanged). These lists are in the YAML file. Nothing
starts a new record by itself yet.

## API

| Route | Permission | Use |
|---|---|---|
| `GET /v1/systems/{id}/classification-v2` | `systems.view` | approved record, record waiting for approval, thresholds, triggers |
| `POST /v1/systems/{id}/classification-v2` | `systems.edit` | store a path; 201. With `?preview=1` the tree is walked and nothing is stored; 200 |
| `POST /v1/systems/{id}/classification-v2/approve` | `systems.approve` | second person approves |
| `GET /v1/classification/summary` | `systems.view` | counts per outcome, waiting, no record, review due (for the portfolio views) |

The routes `/v1/systems/{id}/classification` (no `-v2`) stay the Decision 33 flow.

Body of `POST`:

```json
{
  "answers": {"N-PROHIBITED": {"answer": "no", "evidence": "doc:legal-review-12", "note": "No forbidden purpose."}},
  "decision33": {"Q-OTHER": {"answer": "no", "justification": "Checked against Appendix IV."}},
  "inherited_from_provider": false
}
```

`evidence` is a pointer (file and line, table row id, document id; 200 characters at most). `note` is
300 characters at most and must hold no personal data. Errors are HTTP 400 with `<code>: <text>`:
`classification_v2_off`, `bad_input`, `unknown_node`, `bad_answer`, `incomplete_path`,
`no_record`, `already_approved`, `same_person`, `owner_cannot_approve`, `tree_changed`,
`decision33_changed`, `tree_invalid`. A system outside the scope of the caller answers 404.

## Console

- `/console/systems/{id}/classify`: the page. The tree is drawn on the server from boxes and
  arrows (CSS only, no script; the policy is `script-src 'self'`). Each box shows the node, the
  article, the answer, who answered, the evidence pointer and the branches; the path taken is
  marked. The outcome card names the duties that follow. A fragment is returned for `HX-Request`.
- Register v2, step 4 (class): a read-only copy of the tree with the path the rules and the
  Decision 33 answers give now. The record itself is made on the Classify page once the system exists.

## Chain and audit

Each save and each approval writes a `classification_v2` chain record: system id, record id, action,
outcome, `path_hash`, `tree_sha256`, step count, the actor reference and a time. It holds no note, no
evidence text and no user id. Each POST also writes two `console_action` rows.

## RegKB

The tree cites articles that must exist in RegKB. Rows were added for Law Art. 7(2), 9(2), 10(4)
and Decree Art. 6(2), 6(3), 8(1), 8(2), 9(1), 9(3), 11(2), 11(4), 12(2), with the verbatim Vietnamese text.
The rows of Law Art. 7(2)(b), 7(2)(c), 9(1), 10(1)-(3) and Decree Art. 6(4), 8(2)(b), 11(1), 11(3)(a)
got the new controls `classification_v2` (console) and `classification_v2_record` (evidence).
