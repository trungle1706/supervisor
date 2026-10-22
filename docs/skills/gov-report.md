# Skill: gov-report

Write the periodic governance report for the second line: where the portfolio stands, what is
late, what needs a decision. Use it for the monthly or quarterly report, or when a person asks "how
are we doing".

Tools used: `kpis`, `list_entities`, `get_entity`, `list_tasks`, `pack_results`, `decisions`,
`findings`, `gate_state`, `regulations`.
Scopes: `governance.read`, `supervisor.read`, `library.read`.

## Rules

The server decides. Confirm before you write. Never classify by yourself.

* This skill only reads. It writes no row.
* Use the numbers of `kpis` as they are. A rate is in basis points (10000 = 100 percent). A figure
  that is `null` is not available; the key `unavailable` says why. Write "not available" and the
  reason. Do not estimate.
* The report is decision support. The decisions (classify, approve, accept a risk, change a level,
  close an incident, turn a guardian off) are for people. Write them as "needs a decision" with
  the id of the thing.
* Mock results are labelled mock. Say so.

## Steps

1. `kpis` for the scope of this app. Build three short tables: coverage, quality, speed. Use the
   groups of the answer.
2. Coverage: systems by risk level and by stage, the classification rate, the policy coverage.
   Name the systems that are `unclassified` (`list_entities`, `kind: system`).
3. Quality: risk treatment coverage, acceptable residual rate, control readiness, implementation
   per policy. For a low figure name the systems from `implementation_by_system`.
4. Speed: average days per stage, overdue tasks (`list_tasks` for the systems that matter),
   inheritance rate, automation runs and their success.
5. Runtime: for each agent of the systems that matter, `gate_state`, the last stops from
   `decisions`, `findings` and `pack_results`. One line each. Use masked text only.
6. Incidents and reviews: `list_entities` with `kind: incident` and `kind: review`. List the
   open ones.
7. End with a list "Needs a decision", each item with an id and the person or role who decides.
8. Offer **one** next step.

## Do not

* Do not name people. Use ids.
* Do not compare with a target that the bank has not set. Say "no target set".
* Do not hide a `null` figure.
