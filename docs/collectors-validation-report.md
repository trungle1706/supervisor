# Collectors validation report (WP38)

Harness `collectors-eval-1`, commit `639959f90995`, date 2026-10-20.
Thresholds are ILLUSTRATIVE until the bank sets them. Offline, deterministic, no framework
installed. Command: `python -m supervisor.collectors.harness`.

| Check | Result | Threshold | Verdict |
|---|---|---|---|
| Contract cases passed | 144 of 144 (10000 bp, CI [9740, 10000]) | 10000 bp | GO |
| Adversarial probes passed | 26 of 26 (10000 bp) | 10000 bp | GO |
| Overhead p95 per adapter | see below | 5000 us | GO |

## Overhead (microseconds, instant in-memory gate)

| Adapter | p50 | p95 | max |
|---|---|---|---|
| langgraph | 16 | 26 | 83 |
| litellm | 57 | 140 | 256 |
| fastapi | 143 | 167 | 245 |
| hook | 20 | 22 | 32 |

## Contract by adapter

| Adapter | Passed | Cases |
|---|---|---|
| langgraph | 36 | 36 |
| fastapi | 36 | 36 |
| litellm | 36 | 36 |
| hook | 36 | 36 |

## Probes

| Id | Adapter | What | Result |
|---|---|---|---|
| P01 | langgraph | consumer id with a newline is dropped | pass |
| P02 | litellm | consumer id of 129 characters is dropped | pass |
| P03 | fastapi | consumer id with non-ASCII bytes is dropped | pass |
| P04 | langgraph | consumer id that is an object is dropped | pass |
| P05 | fastapi | CRLF in the inbound correlation id is replaced | pass |
| P06 | fastapi | 200 character correlation id is replaced | pass |
| P07 | sdk | hostile correlation id never reaches the transport headers | pass |
| P08 | langgraph | oversized args on a money tool: not sent, tool stops | pass |
| P09 | common | oversized args, plain tool, open mode: marked pass, not sent | pass |
| P10 | fastapi | oversized request is 413, app and gate not called | pass |
| P11 | fastapi | oversized response is refused, nothing leaks | pass |
| P12 | common | unicode tool names map to accepted, distinct names | pass |
| P13 | common | traversal, empty and long tool names are accepted names | pass |
| P14 | langgraph | pause in the middle of a run stops that call and later ones | pass |
| P15 | litellm | pause in the middle of an async run stops later calls | pass |
| P16 | common | string, list, None answers fail closed | pass |
| P17 | common | allow as the string yes fails closed | pass |
| P18 | langgraph | transform answer without values is a block | pass |
| P19 | langgraph | NUL, lone surrogate and huge integers do not raise | pass |
| P20 | langgraph | 5000 levels of nesting: closed, no crash, gate not called | pass |
| P21 | hook | 10 MB hook event refused without a gate call | pass |
| P22 | hook | ANSI and newlines in a reason become one ASCII line | pass |
| P23 | hook | malformed hook events exit 2 | pass |
| P24 | langgraph | 40 threads keep distinct correlation ids | pass |
| P25 | fastapi | session id with CRLF is dropped | pass |
| P26 | langgraph | a block message carries no argument value | pass |

Overall: **GO**

Failure taxonomy: every failed contract case is listed with adapter, scenario, tool class, fail mode, wanted and got; every failed probe by id.
