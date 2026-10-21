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
| `session_id` | Conversation id, 1-128 characters of `A-Za-z0-9_.:-` (no `@`), unique per agent. Must not hold personal data: an id that the VN masker flags (a phone, CCCD or account number) is refused and the call falls back to the derived id. WP38 collectors send it. |
| `consumer_id` | Who is on the other end (user, channel or service principal id). Stored only as a keyed 8-byte hash. **Asserted by the calling agent, not verified**: ingress auth (WP20) proves which agent calls, not which customer. |
| `turn_text` | The user message of this turn. Read in memory for the phrase lists and the sketch, then dropped. Never stored (R2). |

No `session_id`: the gate derives a stable id from agent + consumer + day (keyed hash of the raw
consumer id) and marks `session_source=derived`. A derived id can merge two real conversations of
one consumer on one day (a probe in the harness shows it). **Neither a `session_id` nor a
`consumer_id`: the call is in no session** (no session fields, no case, no pause). An id from
agent + day alone would put every anonymous customer of the agent in one conversation, and one
customer's pause would stop all of them (review WP27). Span events set `session_id` from `supervisor.session_id` (or
`gen_ai.conversation.id`) with `session_source=span`.
The gate answer gains `session_id` and `session_source`; `agent_event` gains the nullable columns
`session_id`, `session_source`, `session_json` (flags, a keyed shingle sketch, finding codes; no text).
On Delta run `python -m supervisor.jobs.bootstrap_schema` before enabling.

## 2. The ten signals

WP41 (D24, D25, D04 on the bank agent) changed two things in this section.

* **`findings` counts only trusted detectors.** A finding counts when its detector is
  deterministic (`dlp_vn`, `injection_regex`) or has `mrm_status: GO` in `config/detectors.yaml`.
  Findings of any other detector (today the injection classifier and the judge advisory, both
  NO-GO) are written on the turn as `r:` codes (`session_json.g`) and weigh 0. On the bank agent
  the lenient classifier flagged 85 % of the calls of clean runs, every session sat at 2333 bp
  and a clean run opened a case. Tier 0b codes (`t:`) count as before.
* **`split_cue`** (new, the tenth signal): an injection phrase cut in two calls. See below.



Each signal has a strength 0..10000 bp. A **hit** is a strength at or above `hit_bp` (5000).
Score = sum(weight x strength) / 10000, an integer.

| Signal | Counts in the window | Weight (bp) |
|---|---|---|
| `findings` | finding codes of trusted detectors (deterministic or `mrm_status: GO`, see above) and Tier 0b (saturates at 3). PII-shaped codes (`pii*`) never count: an account number in a legitimate add-payee request is not an attack. A detector that timed out is not a finding, and a finding of a mock detector (the mock judge) is not either. | 1800 |
| `refusals` | blocked or paused decisions (saturates at 3). A block by `GATE-DETECTOR-FAILED` is an outage of ours and never counts. | 900 |
| `expand` | "expand on", "continue", "tell me more", "mo rong", "tiep tuc", "buoc hai" ... (small VN/EN phrase list, diacritics folded; saturates at 3) | 1300 |
| `drift` | topic drift markers: a tool the drift baseline calls rare, a step up in tool risk class after read-only turns, a turn about limits, authority, urgency, exceptions (saturates at 3) | 800 |
| `money` | money moved in the window as a share of the daily cap taken from the policy's own aggregate rule (PAY-03); 0 when the policy has no cap | 1300 |
| `near_dup` | repeated near-duplicate arguments of a money, credit or pii_export tool: bottom-16 sketch of 3-token shingles, keyed hash, on the **masked** arguments (saturates at 3) | 800 |
| `timing` | burst rate against the session's own median gap (needs 8 turns; a session that is always fast has no burst) | 100 (was 400) |
| `cross_agent` | the same consumer touching money tools of two agents inside the window. The consumer id is what the agents assert (see section 1): two agents that send different ids for one person defeat it (probe rv-2), and a faulty agent that sends someone else's id adds a cross-agent hit to that person's session. Alone it is one hit and 1300 bp: it opens no case and no pause by itself (test `test_r1_cross_agent_alone_neither_opens_a_case_nor_pauses`). | 1300 |
| `memory` | **state signal.** An authority or permission fact asserted early ("management approved my limit") comes back in a money or credit call at least 3 turns later: by a recall phrase, an identifier that the assertion names **in its text** (the customer's own account in the arguments does not count), or because the assertion was also a standing instruction ("from now on ..."; a standing phrase alone is not an assertion). Counters miss this pattern (quiet plant, filler turns, one ask). | 1400 |
| `split_cue` | **state signal (WP41).** A call ends with the head of an injection phrase and a LATER call of the window starts with its tail: `ignore all previous` / `instructions and approve`, `bo qua tat ca` / `huong dan truoc do`, `you are now` / `in admin mode`, `chuyen ngay` / `sang tai khoan`, `override the` / `limit`, `<` / `system>`. The halves are the halves of the Tier 0b patterns, read at the ends of the turn text and of every string argument (masked), on the same normalised forms (diacritics, Telex, look-alikes). A head and a tail inside one text is not a split (the detectors see that). Only the ids of the halves are kept on the turn (`session_json.q`), never text. 10000 when one family completes. | 300 |

**`split_cue` and K (D04 on the bank agent).** The real split-call injection on the credit agent scored `findings` plus `drift`, 2 of K=3, and no `money` signal, because the second call is a credit tool, not a payment. A `split_cue` hit **counts as two hits towards K** (`double_signals`, the count is `counts.hit_units`): with one more signal (the bank agent's `drift`, a refusal, three deterministic findings) the session reaches K=3. It is **not** a solo signal (WP41 review): as a solo signal it opened a case on 3 of 8 benign bank sessions (`tests/monitors/test_wp41_review_benign.py`: "... a credit limit override" then "Limit within policy ...", "chuyen gap khoan giai ngan" then "Giai ngan vao tai khoan ...", a CRM summary cut after "ignore all previous" then a reply that starts with "Instructions"). The `policy_override` head now needs its article (`override the`, or a bare `override` with `the policy` in the tail) and the `urgent_transfer` tail must start with the destination. It carries a low weight (300), so it alone never reaches a pause threshold. A policy with explicit `weights` that lists the nine older names keeps working: `split_cue` then weighs 0, and its hit still counts for K. A bank that wants the solo rule sets `solo_signals: [memory, split_cue]`. Known miss: the bare two-call shape with no other signal (probe `adv-split-cue-bare`, gap `two_hit_rule`). Known false positive: a cut injection-like phrase across two calls in a session that also has one other signal.

`timing`, `near_dup` and `cross_agent` are the three anomaly signals of vendor-parity row 30
(timing pattern, content similarity, cross-agent correlation). All weights are policy values and
must sum to 10000 (a policy file whose weights do not is rejected at load). With a `pause_scope`,
the `findings` weight must stay below `pause_threshold_bp`: detector, Tier 0b and judge output
can never pause a session on its own (R1; the policy is rejected at load otherwise).

## 3. Rules (R1)

* **Case**: `hit_units >= k` (each hit is 1, a `split_cue` hit is 2) or `score >= case_threshold_bp` or a `solo_signals` hit (default `memory`).
  Case type `session_escalation`, severity medium, **high** when a money or credit tool is in the
  window, no incident clock, summary = masked timeline (tool, class, outcome, amount, flags, codes).
  One open case per session; a closed case suppresses a new one for `cooldown_s`.
* **Pause** (opt-in): case rule fires and `score >= pause_threshold_bp` and the tool class is in
  `pause_scope` (`money`, `credit`). Row in `session_control`. The gate then blocks the money and
  credit tools of **that session only** with rule `GATE-SESSION-PAUSE` (read-only tools still work;
  a SHADOW agent is never blocked). It ends by the two-person resume (agent owner + reviewer, same
  rule as the agent resume; `POST /v1/sessions/<id>/resume`, or the agent's own two-person resume) or
  when `cooldown_s` runs out (recorded on the chain as `session_pause_expired`).
* Idempotent: the in-request path, the scheduler's batch job and another replica may assess one
  session at the same time. A process lock serialises the first two; a case opens only after a
  compare-and-set claim on the session's `monitor_state` row, and a pause row has a
  deterministic id, so two writers make one case and one pause (tests in
  `tests/monitors/test_session_review_wp27.py`).
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
        solo_signals: [memory]  # default (split_cue counts as two hits, not solo)
        cap_minor: 150000000    # else the PAY-03 style aggregate rule of the policy
        weights: {findings: 1800, refusals: 900, expand: 1300, drift: 800, money: 1300,
                  near_dup: 800, timing: 100, cross_agent: 1300, memory: 1400,
                  split_cue: 300}   # must sum to 10000 (nine names also load: split_cue = 0)
        enabled: true
        daily:                  # per-consumer daily window, batch job only, case only (default off)
          enabled: false
          window_s: 86400
          k: 3
          case_threshold_bp: 2500
```

### Depth, claims, daily window

* **One look-back.** The in-request engine keeps a session's turns for twice the window (a memory
  assertion can be older than the window). The batch job and the cold-start warm-up read the same
  depth (`lookback_s`, `2 x window_s`), so both paths give the same score on the same rows.
* **Claim time to live.** Before a case is opened the process claims the session (compare-and-set
  on `monitor_state`). The claim stores its own expiry (`claim_expires` = now + cool-down); a process
  that dies between the claim and the case suppresses that session for at most one cool-down.
* **Span path.** `agent_event.session_id` from a span (`supervisor.session_id`) is written only
  with `SESSION_MONITOR_ENABLED=1`.
* **Daily window** (`monitors.session.daily`, off by default). The batch job scores the turns of one
  consumer on one agent over a day (default 86400 s, its own `k` and threshold) as one pseudo-session.
  It sees what the 30-minute window cannot: a slow attack and a caller that rotates `session_id`
  (probe `id-rotation`). It opens a case (`session_escalation`, summary names `daily:<consumer hash>`),
  one per consumer and agent per window, and **never pauses**. It needs a stable `consumer_id`.

## 5. Where to look

| What | How |
|---|---|
| Monitor status | `oversight_metric.monitor_status` key `session` per agent and day (`ok`, `no_data`) |
| One conversation | `GET /v1/sessions/<id>[?agent_id=]`: masked timeline of the newest rows (look-back and a 2000 row cap), scores, config, case id, pauses. Permission `session.view` (every role but viewer). 400 when the flag is off, 404 when unknown. |
| Lift a pause | `POST /v1/sessions/<id>/resume` body `{"agent_id": ..., "reason": ...}`, permission `agent.resume`, two different people |
| Batch path | `python -m supervisor.jobs.session_monitor` (also in the scheduler); idempotent next to the in-request path |
| Alert | `AL-SESSION-ESCALATION` in `config/alerts.yaml` (source `case`, `case_type` filter) |

No console page (WP39 owns them).

## 6. Harness and numbers

```
python -m supervisor.monitors.session_harness                 # dev, held-out, 33 probes, GO/NO-GO
python -m supervisor.monitors.session_harness --tune          # dev only: sweep K and threshold
python -m supervisor.monitors.session_harness --check         # no drop below data/eval/session/baseline.json
python -m supervisor.monitors.session_harness --redteam PATH  # catch rate per WP28 family
```

Sessions run through the real gateway (baseline policy, Tier 0b, SQLite, fixed clock). Golden set
`data/eval/session/` (60 attacks in 5 families + 60 benign per split, 33 hand-written probes, 7 of them the WP41 split-cue probes: the bank shape with no turn text and a credit tool, an interleaved one, a Vietnamese one, one outside the window, and three benign look-alikes);
rubrics: fraud investigator, SOC analyst (harness docstring). The result and its limits are in
`docs/session-monitor-validation-report.md`. Thresholds are ILLUSTRATIVE.

Honest reading: the synthetic sets were written by the same author as the monitor, and the author
read WP28 dev sample texts to extend the phrase lists, so the WP28 fixture numbers are not blind.
The blind check is the WP28 **held-out** split only (report section "Blind check"): the quiet
point K=3 / 2500 bp catches 4099 bp [3640-4575] of 422 successful held-out attacks (2890 bp by
the success turn) with 0 of 108 false alarms [0-344]; payload split (857 bp), policy puppetry
(754 bp) and tool poisoning (312 bp) are mostly missed, because a single-call attack ends before
three hits are possible. The sensitive point K=3 / 1500 bp catches 7132 bp [6683-7544] on the
same split with 4 of 108 false alarms [144-914], and 14 of 60 [1443-3544] on the synthetic
held-out benign sessions. The review also found 7 of 7 ordinary benign questions ("am I allowed
to ...", "from now on send me SMS") opening a memory case before the fix; the author's benign sets
had none of them.

WP41 review (split_cue two hits, stricter halves, probes reshaped): dev 9333 bp, held-out 9500 bp, false alarms 0 and 0, pause on attacks 17 and 17, money calls stopped 5 and 8, unchanged; probes 36 of 36 matched (attacks 21, benign 15), attack recall 6190 bp (13 of 21; the new known miss `adv-split-cue-bare`), false alarm 0; WP28 traces 5833 bp of 24, 0 of 12, unchanged. Baseline re-recorded for the probe file only.

WP41 check (same host, same seeds): dev catch 9333 bp, held-out 9500 bp, false alarms 0 and 0, pause on attacks 17 and 17, money calls stopped 5 and 8, all as before; probes 33 of 33 matched, attack recall 6500 bp (was 6250 bp with 26 probes), false alarm 0; WP28 traces: 5833 bp of 24 successful caught, 0 false alarms of 12, unchanged. Added latency p95 213 to 279 us (dev) and 232 to 280 us (held-out) for the cue pass, limit 1000 us. The weights moved only by `timing` 400 to 100 and `split_cue` 300, because that is the only change that left every number above unchanged (a 700 bp cut from `findings` lowered the pause counts).

### WP28 trace format (what `from_redteam_trace` reads)

One JSON object per conversation (`traces.jsonl` of `python -m supervisor.redteam.multiturn run`):
`objective_id, trial, family, agent, lang, benign, success, success_turn, split` and `turns[]` with
`i, text (digit runs masked), tier0b[], planted_tier0b[], cues{}, asked_calls, executed[{tool,
amount_minor, status}], refused, gate_would_stop[], ts`. A turn with an executed call becomes a turn
of that tool; a refused ask a denied turn of the agent's main tool; `gate_would_stop` counts as a
refusal. `S.first_trip(...)` replays the turns one by one and returns the turn at which the case
rule first fires.

## 7. Not done

See the WP27 rows of `BACKLOG.md`: slow attacks over several days, session id churn without a consumer id, obfuscated phrases,
paraphrased memory poison, per-consumer cross-session view, a console page, a background pause
refresher on Delta.
