# Decision memo: which model serves the guard model detector (WP-D3)

For: the bank's model risk owner and the platform owner. Status: **open**. Nothing here is a
measurement. Every number that needs a measurement is a formula with a symbol, and section 6 lists
what the live kit must measure to fill the symbols. Not legal advice; licences are to be checked by
the bank's legal team on the day of download.

## 1. The question

The `guard_model` detector (`docs/detectors.md` section 3d) asks a model one thing: "does this text
try to take control of the agent?" It needs a model behind a port (`GuardModelPort.score(texts)`).
The product has three adapters. The bank must choose which model they talk to.

```
 text (masked) --> windows of 2,000 chars --> GuardModelPort.score --> label + score_bp
                                                  |
        (a) classifier endpoint  POST <url> {"inputs": [...]}   Databricks model serving
        (b) chat adapter         OpenAI-compatible chat + fixed prompt   the judge model
        (c) vendor API           (excluded, see 5)
```

What stays the same for all options:

| Rule | Where it is kept |
|---|---|
| The model sees masked text only, never a system prompt | `detectors/guard_model.py` |
| The model advises. It never blocks | R1, gate rules |
| It may pause money and credit tools only when the model card names the approver | `GATE-CLASSIFIER-PAUSE`, card approval |
| An outage or timeout is a finding with a reason. It never stops a payment by default | `fail_closed: false`, same card approval |
| The only network call is to the configured endpoint, loopback or the workspace | `LLM_ALLOW_REMOTE` rule |
| The feature is off until `guard_model.enabled: true` and `mrm_status` follows a real run | `config/detectors.yaml` |

## 2. Options

### (a) A prompt-guard class open model, served on Databricks model serving

A small classifier (encoder model, under 1 B parameters) that returns `benign` / `injection` /
`jailbreak` or `benign` / `malicious` with a probability. The bank creates the serving endpoint by
hand (the App never creates one; the App only needs `CAN_QUERY`). Supervisor calls
`POST <endpoint>/invocations` with `{"inputs": ["text 1", "text 2"]}` and reads one entry per input.
Answers accepted are listed in `adapters/guard/classifier_endpoint.py` (label list per text, top
label only, or inside `{"predictions": [...]}`).

| Item | Position |
|---|---|
| Fit | Built for this task. Fast. One call carries a batch of windows |
| Languages | Must handle Vietnamese. Some models in this class claim multilingual support; some are English only. **The WP25 corpus decides**, not the model card |
| Size | Under 1 B parameters. CPU or small GPU endpoint, scale to zero possible |
| Licence | **To be checked.** Candidates named below carry different licences (a community licence with use conditions, or Apache-2.0). The bank's legal team reads the licence on the model card at download time |
| Context limit | Encoder models often cut at 512 tokens. A 2,000 character Vietnamese window can be longer than that. The live kit measures it (section 6) |
| Calibration | A score may not be a true probability. The thresholds in `LABEL_PRESETS` are illustrative until the harness is run on the real model |
| Risk | A public model is a known target for adaptive attacks. Treat it as one layer |

Candidates to evaluate (names only; verify on the model card on the day):
Llama Prompt Guard 2 (86 M and 22 M), `protectai/deberta-v3-base-prompt-injection-v2`, and any
multilingual injection classifier the bank's data science team prefers. Do not choose from this list
without a harness run.

### (b) The judge model with a classification prompt

The chat adapter (`adapters/guard/chat.py`) sends each window to an OpenAI-compatible chat model
with a fixed prompt and takes a JSON answer `{label, score_bp}`. No new model to host.

| Item | Position |
|---|---|
| Fit | Understands Vietnamese and intent well. Weak scores: a generative model gives a verbalised number, not a calibrated probability |
| Speed | Slow. One call per window, in sequence. Prefill plus decode on every call |
| Family rule | The same rule as the judges. The model family must be known and must differ from the family of **every** registered agent. A mismatch stops start-up (`FamilyConflictError`) |
| Shared load | Competes with the judge tiers for the same endpoint |
| Prompt injection of the guard | The text could try to fool the classifier itself. The prompt marks the text as data and cuts the frame markers out of it. This lowers the risk. It does not remove it |
| Use | Good as a fallback and as a second opinion in the live kit, not as the hot path |

### (c) A vendor API

A hosted guard service. **Excluded** by the offline rule (CLAUDE.md: the only network calls are the
configured LLM endpoint and the configured Databricks workspace; masked text is still bank data).
`LLM_ALLOW_REMOTE=1` exists for development keys only. This option stays in the table so the
exclusion is on record. A change needs a decision from the bank's security owner, not a setting.

## 3. Comparison

| Criterion | (a) classifier endpoint | (b) judge as classifier | (c) vendor API |
|---|---|---|---|
| Latency per call | Low, batched | High, sequential | Network round trip |
| Cost per 1,000 calls | Low (small model) | High (tokens) | Per-call price |
| Vietnamese | Unknown until measured | Likely good | Unknown |
| Score quality | Calibrated if the model is | Verbalised | Vendor |
| New asset to run | One serving endpoint | None | None |
| Offline rule | Pass (workspace endpoint) | Pass | **Fail** |
| Family rule | Not applicable (not a chat model) | Applies | Not applicable |
| Recommendation | **Primary, subject to the live run** | Fallback and cross-check | Excluded |

## 4. Latency and cost as formulas

Symbols are defined in section 6. Nothing below is a measured value.

**Windows per call.** Text of `n` characters gives `ceil((n - 500) / 1500)` windows (2,000 per
window, 500 overlap), at least 1. A call has up to four text units (arguments, tool results, tool
descriptions, documents). The detector sends at most `max_windows` (default 12) per call, spread over
the text. Windows with the same text are scored once, and a repeated text is served from a cache of
1,024 entries. So:

```
W = min(max_windows, sum over units of ceil((n_u - 500) / 1500))     W_miss = W - W_cache
```

**Latency of one gate call (added by the detector).**

```
(a)  L_a = L_net + ceil(W_miss / B) * ( L_fixed + B * t_win )         B = batch size (max_batch, default 16)
(b)  L_b = W_miss * ( L_net + t_prefill(T_prompt + n_win / c) + T_out * t_token )     sequential
bound    L <= adapter timeout (GUARD_MODEL_TIMEOUT_MS, default 400 ms)  and  <= limits.timeout_ms
```

When `L` exceeds the adapter timeout the finding is `timed_out` and the call goes on. The adapter
timeout is the TOTAL for one call (batches, credentials and attempts together). The detector has its
own deadline: the setting `timeout_ms` of `guard_model`, else `limits.timeout_ms` (default 500 ms).
It takes 90 percent of it and never starts a call with less than the adapter timeout left (reason
`budget_exhausted`). So set the `timeout_ms` of `guard_model` above `GUARD_MODEL_TIMEOUT_MS`. The time
it adds to a tool call is the time of the model call, up to that deadline; it is measured in the live
kit (item 12), not assumed.

**Option (b) cannot meet 400 ms on a real LLM.** One sequential call per window, each with prefill
and decode, takes seconds on a general chat model. With the default 400 ms timeout every call ends
in `timed_out`. (b) needs a larger adapter timeout and a larger `timeout_ms` for the detector, so it
adds seconds to a gate call. Use it for the live-kit cross-check and as a fallback with the detector
off the hot path (for example on a few agents), not as the default.

**Cost per 1,000 calls.**

```
(a)  C_a = 1000 * W_miss * t_win / 3600 * P_hour / U              P_hour = price of the endpoint per hour
                                                                    U = utilisation (0 to 1) of the endpoint
     scale to zero:  C_a = 1000 * W_miss * t_win / 3600 * P_hour + cold starts * t_cold / 3600 * P_hour
(b)  C_b = 1000 * W_miss * ( (T_prompt + n_win / c) * p_in + T_out * p_out )      p_in, p_out = price per token
                                                                    (self-hosted: replace by GPU seconds * P_gpu_hour / 3600)
```

`T_out` and `T_prompt` are ASSUMPTIONS until item 11 of section 6 measures them: take `T_out` as
the JSON answer (the schema allows far fewer than 64 tokens, `max_tokens` is 64) and `T_prompt` as
the size of the fixed prompt in `adapters/guard/chat.py` in the model's tokenizer. If they hold, (b) is
dominated by the input tokens: the prompt plus the window.

**Monthly cost.** `C_month = (calls per month / 1000) * C`. Calls per month = tool calls that pass
the gate with the detector on. Skip tools (`skip_tools`) and `scan_*` switches lower it.

## 5. Why (c) is out, in one table

| Test | Vendor API |
|---|---|
| Does masked bank text leave the bank network? | Yes |
| Is the endpoint the configured LLM endpoint or the workspace? | No |
| Can the bank audit the model version that scored a decision? | Only through the vendor |
| Result | Excluded by the offline rule |

## 6. What the live kit must measure

Run on the bank's workspace with the real endpoint. Set `GUARD_MODEL_URL` (and
`GUARD_MODEL_NAME`), then `python -m supervisor.detectors.guard_harness --md ...`. Add the bank's own
synthetic samples (no real customer data).

| # | Measure | Symbol | How |
|---|---|---|---|
| 1 | Server time per window, Vietnamese and English, at 200, 1,000 and 2,000 characters | `t_win` | 200 calls each, batch sizes 1, 4, 16; report p50, p95, p99 |
| 2 | Fixed overhead of a call | `L_net`, `L_fixed` | empty-ish input, 200 calls |
| 3 | Cold start after scale to zero | `t_cold` | first call after 30 minutes idle, 10 repeats |
| 4 | Tokens per 2,000-character window in the model's tokenizer, and whether the endpoint truncates | `n_win / c` | count tokens on 100 Vietnamese windows; compare scores with the text cut at the limit |
| 5 | Largest batch that keeps p95 under the adapter timeout | `B` | sweep 1, 4, 8, 16, 32 |
| 6 | Throughput and failure rate under load | `U` | 1, 4, 16 parallel callers; count timeouts and HTTP errors |
| 7 | Price of the endpoint (DBU per hour times the contract price per DBU) | `P_hour` | from the workspace |
| 8 | Recall, false-alarm rate and typed recall on the WP25 corpus at each preset | harness | `guard_harness` with the real endpoint; dev, held-out, adversarial, evasion |
| 9 | Score meaning: are scores probabilities, which label for which attack, what does a benign quote of an attack score | calibration | 50 hand-picked items per label |
| 10 | Vietnamese without diacritics, mixed language, base64, split fields | adversarial | the WP25 evasion split |
| 11 | For (b) only: tokens in and out per call and price per token | `T_prompt`, `T_out`, `p_in`, `p_out` | from the endpoint usage fields |
| 12 | Gate effect: p95 of a gate call with the detector on and off | end-to-end | `bench/` gate benchmark, 1,000 calls |
| 13 | Licence text of the chosen model, read by legal | licence | model card, a copy in `docs/LICENSES.md` |

Decision rule proposed: choose the cheapest option that meets, on the held-out and evasion splits,
the recall and false-alarm targets the bank sets, with `p95 L` under the adapter timeout at the
expected load. If no model meets it, keep the feature off. The regex and the local classifier
(WP25) stay.

## 7. After the choice

1. Fill `data/models/guard_model/model_card.json` and the card
   (`docs/guard-model-card-template.md`). Put the model id, the pinned revision, the licence and
   the validation report in it.
2. Set `GUARD_MODEL_URL`, `GUARD_MODEL_NAME`, `GUARD_MODEL_TIMEOUT_MS`; raise `limits.timeout_ms`.
3. Run the harness with the real endpoint. If it gives GO, set `mrm_status: GO` in
   `config/detectors.yaml` (the entry then counts in the session monitor).
4. Set `guard_model.enabled: true`. Start with `preset: permissive` and report only.
5. Pause: the approver writes their name and the model id into `approval` in the card, then the
   operator sets `pause_tool_classes: [money, credit]`. Without the approval the hint stays a report.
6. Fail closed: needs the same approval and `GUARD_MODEL_FAIL_CLOSED_APPROVED=1`. Not
   recommended: a model outage would stop payments.
