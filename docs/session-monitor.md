# Session monitor (WP27, ADR D29)

A conversation can be steered over many turns toward a payment split, a limit breach or a
PII leak while every single call looks fine. The session monitor watches the conversation, not the
call. It is deterministic: counters, integer weights and thresholds. Judges and detector findings
are inputs (one counter each), never deciders (rule R1).

Flag: `SESSION_MONITOR_ENABLED` (default `0`). With the flag off the gate answers and records
exactly as before (a test keeps the fingerprint). Default action when on: **open a case only**;
the session pause is off until a policy turns it on.

```
 turn text, args, ctx            gate (in-request)                       batch job (every 5 min)
 session_id, consumer_id  --->   identity + features (before the lock)   replays agent_event rows
 turn_text (memory only)         decision (rules, as before)             same engine, same actions
                                 observe: add turn, score, act      <--  lifts expired pauses
                                          |
              +---------------------------+---------------------------+
              | case session_escalation   | session pause (opt-in)     |
              | masked timeline, no clock | GATE-SESSION-PAUSE         |
              +---------------------------+---------------------------+
```

## 1. What the caller sends

| Context key | Meaning |
|---|---|
| `session_id` | Conversation id, 1-128 characters of `A-Za-z0-9_.:-` (no `@`). Must not hold personal data. WP38 collectors send it. |
| `consumer_id` | Who is on the other end (user, channel or service principal id). Stored only as a keyed 6-byte hash. |
| `turn_text` | The user message of this turn. Read in memory for the phrase lists and the sketch, then dropped. Never stored (R2). |

No `session_id`: the gate derives a stable id from agent + consumer + day and marks
`session_source=derived`. A derived id can merge two real conversations of one consumer on one day
(a probe in the harness shows it). Span events set `session_id` from `supervisor.session_id` (or
`gen_ai.conversation.id`) with `session_source=span`.
The gate answer gains `session_id` and `session_source`; `agent_event` gains the nullable columns
`session_id`, `session_source`, `session_json` (flags, a keyed shingle sketch, finding codes; no text).
On Delta run `python -m supervisor.jobs.bootstrap_schema` before enabling.

## 2. The nine signals

Each signal has a strength 0..10000 bp. A **hit** is a strength at or above `hit_bp` (5000).
Score = sum(weight x strength) / 10000, an integer.

| Signal | Counts in the window | Weight (bp) |
|---|---|---|
| `findings` | detector and Tier 0b finding codes (saturates at 3). PII-shaped codes (`pii*`) never count: an account number in a legitimate add-payee request is not an attack. A detector that timed out is not a finding. | 1800 |
| `refusals` | blocked or paused decisions (saturates at 3). A block by `GATE-DETECTOR-FAILED` is an outage of ours and never counts. | 900 |
| `expand` | "expand on", "continue", "tell me more", "mo rong", "tiep tuc", "buoc hai" ... (small VN/EN phrase list, diacritics folded; saturates at 3) | 1300 |
| `drift` | topic drift markers: a tool the drift baseline calls rare, a step up in tool risk class after read-only turns, a turn about limits, authority, urgency, exceptions (saturates at 3) | 800 |
| `money` | money moved in the window as a share of the daily cap taken from the policy's own aggregate rule (PAY-03); 0 when the policy has no cap | 1300 |
| `near_dup` | repeated near-duplicate arguments of a money, credit or pii_export tool: bottom-16 sketch of 3-token shingles, keyed hash, on the **masked** arguments (saturates at 3) | 800 |
| `timing` | burst rate against the session's own median gap (needs 8 turns; a session that is always fast has no burst) | 400 |
| `cross_agent` | the same consumer touching money tools of two agents inside the window | 1300 |
| `memory` | **state signal.** An authority or permission fact asserted early ("management approved my limit", "from now on ...") comes back in a money or credit call at least 3 turns later: by a recall phrase, a shared identifier, or because the assertion was a standing instruction. Counters miss this pattern (quiet plant, filler turns, one ask). | 1400 |

`timing`, `near_dup` and `cross_agent` are the three anomaly signals of vendor-parity row 30
(timing pattern, content similarity, cross-agent correlation). All weights are policy values and
must sum to 10000 (a policy file whose weights do not is rejected at load).

## 3. Rules (R1)

* **Case**: `hits >= k` or `score >= case_threshold_bp` or a `solo_signals` hit (default `memory`).
  Case type `session_escalation`, severity medium, **high** when a money or credit tool is in the
  window, no incident clock, summary = masked timeline (tool, class, outcome, amount, flags, codes).
  One open case per session; a closed case suppresses a new one for `cooldown_s`.
* **Pause** (opt-in): case rule fires and `score >= pause_threshold_bp` and the tool class is in
  `pause_scope` (`money`, `credit`). Row in `session_control`. The gate then blocks the money and
  credit tools of **that session only** with rule `GATE-SESSION-PAUSE` (read-only tools still work;
  a SHADOW agent is never blocked). It ends by the two-person resume (agent owner + reviewer, same
  rule as the agent resume; `POST /v1/sessions/<id>/resume`, or the agent's own two-person resume) or
  when `cooldown_s` runs out (recorded on the chain as `session_pause_expired`).
* Chain records: `session_pause`, `session_resume_requested`, `session_resumed`,
  `session_pause_expired`, `case_opened`, and `gate_decision` with `session_sha256`. Hashes and
  integers only.

## 4. Settings

Global (`config.py`): `SESSION_MONITOR_ENABLED`, `SCHED_SESSION_S` (300), `SESSION_WINDOW_S` (1800),
`SESSION_K` (3), `SESSION_COOLDOWN_S` (3600). Per agent, in the policy file
(`agents.<id>.monitors.session`, every field optional):

```yaml
agents:
  payments:
    monitors:
      session:
        k: 3                    # signal hits that open a case
        case_threshold_bp: 2500 # or a score at least this high
        pause_threshold_bp: 4000
        pause_scope: [money]    # empty (default) = case only
        window_s: 1800
        cooldown_s: 3600
        hit_bp: 5000
        solo_signals: [memory]
        cap_minor: 150000000    # else the PAY-03 style aggregate rule of the policy
        weights: {findings: 1800, refusals: 900, expand: 1300, drift: 800, money: 1300,
                  near_dup: 800, timing: 400, cross_agent: 1300, memory: 1400}   # must sum to 10000
        enabled: true
```

## 5. Where to look

| What | How |
|---|---|
| Monitor status | `oversight_metric.monitor_status` key `session` per agent and day (`ok`, `no_data`) |
| One conversation | `GET /v1/sessions/<id>[?agent_id=]`: masked timeline, scores, config, case id, pauses. Permission `session.view` (every role but viewer). 400 when the flag is off, 404 when unknown. |
| Lift a pause | `POST /v1/sessions/<id>/resume` body `{"agent_id": ..., "reason": ...}`, permission `agent.resume`, two different people |
| Batch path | `python -m supervisor.jobs.session_monitor` (also in the scheduler); idempotent next to the in-request path |
| Alert | `AL-SESSION-ESCALATION` in `config/alerts.yaml` (source `case`, `case_type` filter) |

No console page (WP39 owns them).

## 6. Harness and numbers

```
python -m supervisor.monitors.session_harness                 # dev, held-out, 25 probes, GO/NO-GO
python -m supervisor.monitors.session_harness --tune          # dev only: sweep K and threshold
python -m supervisor.monitors.session_harness --check         # no drop below data/eval/session/baseline.json
python -m supervisor.monitors.session_harness --redteam PATH  # catch rate per WP28 family
```

Sessions run through the real gateway (baseline policy, Tier 0b, SQLite, fixed clock). Golden set
`data/eval/session/` (60 attacks in 5 families + 60 benign per split, 25 hand-written probes);
rubrics: fraud investigator, SOC analyst (harness docstring). The result and its limits are in
`docs/session-monitor-validation-report.md`. Thresholds are ILLUSTRATIVE.

Honest reading: the synthetic sets were written by the same author as the monitor. The probes and
the WP28 traces are the evidence that matters; on the WP28 traces the catch rate is lower than on
the synthetic sessions, and a single-call attack (a planted tool result, a fake policy block) ends
before three hits are possible. K=3 / 2500 bp is the quiet operating point (no false alarm on 120
benign sessions in either split); K=3 / 1500 bp is the sensitive one (about 4 percent false alarms on
WP28 benign controls, catch up to 7100 bp on its held-out successes).

### WP28 trace format (what `from_redteam_trace` reads)

One JSON object per conversation (`traces.jsonl` of `python -m supervisor.redteam.multiturn run`):
`objective_id, trial, family, agent, lang, benign, success, success_turn, split` and `turns[]` with
`i, text (digit runs masked), tier0b[], planted_tier0b[], cues{}, asked_calls, executed[{tool,
amount_minor, status}], refused, gate_would_stop[], ts`. A turn with an executed call becomes a turn
of that tool; a refused ask a denied turn of the agent's main tool; `gate_would_stop` counts as a
refusal. `S.first_trip(...)` replays the turns one by one and returns the turn at which the case
rule first fires.

## 7. Not done

See the WP27 rows of `BACKLOG.md`: slow attacks over days, session id churn, obfuscated phrases,
paraphrased memory poison, per-consumer cross-session view, a console page, a background pause
refresher on Delta.
