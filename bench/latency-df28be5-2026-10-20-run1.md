Latency benchmark, commit `df28be504d`, 2026-10-20T06:00:53Z, mode full
Machine: QEMU Virtual CPU version 2.5+, 16 logical CPUs, Python 3.11.17, Linux-6.8.0-147-generic-x86_64-with-glibc2.39

All values are integer microseconds (us): median over the repeats of each statistic.

| Scenario | Store | Rules | p50 | p95 | p99 | max | spread p50 / p95 (%) | tries |
|---|---|---|---|---|---|---|---|---|
| gate_inproc | sqlite_file | 19 | 1527 | 2828 | 4635 | 7454 | 1.4 / 15.5 | 1 |
| chain_append | sqlite_file | 19 | 573 | 883 | 1760 | 8372 | 1.7 / 10.1 | 1 |
| otlp_inproc_1span | sqlite_file | 19 | 565 | 1393 | 2502 | 43945 | 2.1 / 1.8 | 3 |
| otlp_inproc_20span | sqlite_file | 19 | 3181 | 4506 | 6674 | 9428 | 4.8 / 13.4 | 2 |
| asgi_passthrough | sqlite_file | 19 | 1833 | 2826 | 3184 | 3603 | 5.5 / 3.2 | 1 |
| asgi_gate | sqlite_file | 19 | 3937 | 7053 | 10521 | 18898 | 4.8 / 16.3 | 1 |
| otlp_asgi_1span | sqlite_file | 19 | 2324 | 3711 | 4177 | 5847 | 6.8 / 8.6 | 1 |
| otlp_asgi_20span | sqlite_file | 19 | 5801 | 7777 | 9015 | 22804 | 4.0 / 7.1 | 1 |
| uvicorn_passthrough | sqlite_file | 19 | 2345 | 3666 | 4155 | 4920 | 5.9 / 0.5 | 2 |
| uvicorn_gate | sqlite_file | 19 | 4699 | 6892 | 8432 | 16386 | 1.0 / 9.8 | 2 |
| otlp_uvicorn_1span | sqlite_file | 19 | 3516 | 4946 | 5944 | 8012 | 1.1 / 6.9 | 1 |
| otlp_uvicorn_20span | sqlite_file | 19 | 7052 | 9077 | 10234 | 10787 | 7.6 / 13.3 | 2 |
| mcp_direct | sqlite_file | 19 | 45 | 66 | 198 | 210 | 31.1 / 18.2 | 1 |
| mcp_proxy | sqlite_file | 19 | 8730 | 19905 | 24711 | 27397 | 1.5 / 4.7 | 1 |
| gate_inproc | sqlite_file | 200 | 2424 | 4467 | 6777 | 54879 | 4.2 / 15.5 | 1 |
| chain_append | sqlite_file | 200 | 551 | 867 | 1646 | 3426 | 0.9 / 16.1 | 1 |
| otlp_inproc_1span | sqlite_file | 200 | 508 | 866 | 1233 | 2875 | 1.0 / 56.7 | 4 |
| otlp_inproc_20span | sqlite_file | 200 | 3052 | 3987 | 5224 | 6488 | 0.8 / 8.4 | 1 |
| asgi_passthrough | sqlite_file | 200 | 1817 | 2839 | 3103 | 3592 | 3.0 / 4.8 | 1 |
| asgi_gate | sqlite_file | 200 | 4623 | 8075 | 28511 | 57698 | 3.9 / 3.7 | 1 |
| otlp_asgi_1span | sqlite_file | 200 | 2244 | 3594 | 3771 | 4121 | 4.4 / 2.3 | 1 |
| otlp_asgi_20span | sqlite_file | 200 | 5369 | 6962 | 7727 | 7919 | 5.7 / 6.9 | 1 |
| uvicorn_passthrough | sqlite_file | 200 | 2334 | 3566 | 4109 | 4581 | 1.9 / 2.3 | 1 |
| uvicorn_gate | sqlite_file | 200 | 5384 | 7560 | 11155 | 26245 | 4.9 / 11.6 | 1 |
| otlp_uvicorn_1span | sqlite_file | 200 | 3292 | 4777 | 5876 | 6976 | 4.2 / 15.1 | 1 |
| otlp_uvicorn_20span | sqlite_file | 200 | 6601 | 8688 | 9967 | 21213 | 6.0 / 18.7 | 2 |
| mcp_direct | sqlite_file | 200 | 59 | 79 | 226 | 261 | 11.9 / 41.8 | 1 |
| mcp_proxy | sqlite_file | 200 | 10536 | 21778 | 26916 | 30786 | 4.2 / 4.5 | 1 |
| gate_inproc | sqlite_memory | 19 | 455 | 676 | 941 | 1526 | 3.1 / 4.9 | 1 |
| chain_append | sqlite_memory | 19 | 68 | 96 | 376 | 512 | 1.5 / 2.1 | 1 |
| window_depth_1000 | sqlite_memory | 19 | 495 | 933 | 1546 | 2126 | 2.8 / 5.8 | 1 |
| window_depth_10000 | sqlite_memory | 19 | 511 | 3135 | 5203 | 6159 | 3.7 / 7.8 | 1 |
| otlp_inproc_1span | sqlite_memory | 19 | 150 | 175 | 264 | 452 | 0.7 / 1.7 | 1 |
| otlp_inproc_20span | sqlite_memory | 19 | 2452 | 2506 | 2770 | 2993 | 0.2 / 1.1 | 1 |
| asgi_passthrough | sqlite_memory | 19 | 1801 | 2726 | 3019 | 3949 | 1.6 / 3.1 | 1 |
| asgi_gate | sqlite_memory | 19 | 2485 | 3830 | 4417 | 5366 | 4.6 / 2.4 | 1 |
| otlp_asgi_1span | sqlite_memory | 19 | 2286 | 3643 | 3988 | 4683 | 1.2 / 2.5 | 1 |
| otlp_asgi_20span | sqlite_memory | 19 | 4957 | 6160 | 7388 | 7577 | 9.6 / 17.2 | 3 |
| uvicorn_passthrough | sqlite_memory | 19 | 2410 | 3626 | 4197 | 4974 | 7.4 / 2.0 | 1 |
| uvicorn_gate | sqlite_memory | 19 | 3084 | 4133 | 5039 | 6093 | 0.5 / 1.5 | 1 |
| otlp_uvicorn_1span | sqlite_memory | 19 | 2854 | 3819 | 4492 | 5079 | 2.7 / 7.3 | 1 |
| otlp_uvicorn_20span | sqlite_memory | 19 | 6059 | 7245 | 7662 | 7992 | 5.7 / 15.1 | 1 |
| mcp_direct | sqlite_memory | 19 | 56 | 82 | 173 | 200 | 21.4 / 14.6 | 1 |
| mcp_proxy | sqlite_memory | 19 | 6363 | 15192 | 23410 | 24619 | 2.7 / 7.7 | 1 |
| gate_inproc | sqlite_memory | 200 | 991 | 1866 | 2498 | 15134 | 2.8 / 1.4 | 1 |
| chain_append | sqlite_memory | 200 | 66 | 90 | 285 | 733 | 0.0 / 2.2 | 1 |
| window_depth_1000 | sqlite_memory | 200 | 1434 | 8971 | 9501 | 13302 | 1.7 / 1.9 | 1 |
| window_depth_10000 | sqlite_memory | 200 | 3417 | 54907 | 58282 | 62045 | 3.0 / 1.5 | 1 |
| otlp_inproc_1span | sqlite_memory | 200 | 149 | 173 | 239 | 461 | 0.7 / 1.1 | 1 |
| otlp_inproc_20span | sqlite_memory | 200 | 2477 | 2538 | 2980 | 3102 | 0.3 / 0.4 | 1 |
| asgi_passthrough | sqlite_memory | 200 | 1750 | 2702 | 2966 | 4573 | 6.2 / 5.0 | 2 |
| asgi_gate | sqlite_memory | 200 | 3127 | 4490 | 6490 | 20696 | 4.2 / 3.2 | 2 |
| otlp_asgi_1span | sqlite_memory | 200 | 2268 | 3536 | 3882 | 4288 | 3.1 / 4.3 | 1 |
| otlp_asgi_20span | sqlite_memory | 200 | 4730 | 5911 | 6184 | 6432 | 4.0 / 6.2 | 2 |
| uvicorn_passthrough | sqlite_memory | 200 | 2267 | 3601 | 3966 | 5169 | 2.4 / 2.8 | 1 |
| uvicorn_gate | sqlite_memory | 200 | 3733 | 5210 | 6583 | 22175 | 1.8 / 6.3 | 1 |
| otlp_uvicorn_1span | sqlite_memory | 200 | 2661 | 3877 | 4427 | 5696 | 5.2 / 6.2 | 1 |
| otlp_uvicorn_20span | sqlite_memory | 200 | 5837 | 7938 | 8553 | 9295 | 5.0 / 12.1 | 2 |
| mcp_direct | sqlite_memory | 200 | 30 | 67 | 172 | 192 | 3.3 / 3.0 | 1 |
| mcp_proxy | sqlite_memory | 200 | 8071 | 16597 | 21756 | 33500 | 2.9 / 8.2 | 1 |
| gate_inproc | databricks_fake | 19 | 682 | 1005 | 1372 | 3497 | 3.1 / 9.8 | 1 |
| chain_append | databricks_fake | 19 | 151 | 195 | 619 | 774 | 0.7 / 1.0 | 1 |
| otlp_inproc_1span | databricks_fake | 19 | 219 | 258 | 418 | 847 | 1.4 / 6.2 | 1 |
| otlp_inproc_20span | databricks_fake | 19 | 3043 | 3114 | 3265 | 3624 | 0.2 / 1.5 | 1 |
| asgi_passthrough | databricks_fake | 19 | 1719 | 2649 | 2838 | 3076 | 1.5 / 2.9 | 1 |
| asgi_gate | databricks_fake | 19 | 2380 | 3807 | 4128 | 5201 | 6.4 / 3.1 | 1 |
| otlp_asgi_1span | databricks_fake | 19 | 2438 | 3631 | 4098 | 5177 | 6.6 / 0.9 | 1 |
| otlp_asgi_20span | databricks_fake | 19 | 6065 | 7728 | 8478 | 8564 | 5.1 / 15.2 | 2 |
| uvicorn_passthrough | databricks_fake | 19 | 2336 | 3739 | 4310 | 4675 | 1.4 / 4.2 | 1 |
| uvicorn_gate | databricks_fake | 19 | 3407 | 4812 | 5584 | 6766 | 4.4 / 5.3 | 1 |
| otlp_uvicorn_1span | databricks_fake | 19 | 3009 | 4538 | 5070 | 6140 | 3.0 / 14.2 | 2 |
| otlp_uvicorn_20span | databricks_fake | 19 | 7502 | 8856 | 9750 | 10394 | 5.7 / 11.8 | 1 |
| mcp_direct | databricks_fake | 19 | 33 | 68 | 184 | 266 | 6.1 / 8.8 | 1 |
| mcp_proxy | databricks_fake | 19 | 6943 | 17794 | 23411 | 23776 | 2.0 / 13.2 | 1 |
| gate_inproc | databricks_fake | 200 | 1220 | 2137 | 3095 | 15584 | 1.3 / 0.7 | 1 |
| chain_append | databricks_fake | 200 | 150 | 186 | 526 | 885 | 0.7 / 1.1 | 1 |
| otlp_inproc_1span | databricks_fake | 200 | 223 | 252 | 322 | 513 | 0.0 / 0.8 | 1 |
| otlp_inproc_20span | databricks_fake | 200 | 3055 | 3181 | 3673 | 3697 | 0.6 / 2.3 | 1 |
| asgi_passthrough | databricks_fake | 200 | 1817 | 2766 | 3103 | 3434 | 3.4 / 8.0 | 1 |
| asgi_gate | databricks_fake | 200 | 3643 | 5009 | 6150 | 25276 | 4.4 / 7.7 | 1 |
| otlp_asgi_1span | databricks_fake | 200 | 2518 | 3794 | 4437 | 4996 | 5.5 / 3.0 | 1 |
| otlp_asgi_20span | databricks_fake | 200 | 6271 | 7865 | 8758 | 9374 | 17.1 / 6.7 | 4 |
| uvicorn_passthrough | databricks_fake | 200 | 2266 | 3585 | 3999 | 4454 | 1.9 / 2.4 | 1 |
| uvicorn_gate | databricks_fake | 200 | 4190 | 5665 | 7584 | 25868 | 6.1 / 7.1 | 1 |
| otlp_uvicorn_1span | databricks_fake | 200 | 2748 | 3759 | 4516 | 5253 | 5.8 / 8.5 | 1 |
| otlp_uvicorn_20span | databricks_fake | 200 | 6171 | 8299 | 10094 | 10247 | 0.5 / 10.2 | 2 |
| mcp_direct | databricks_fake | 200 | 45 | 81 | 156 | 236 | 35.5 / 23.4 | 1 |
| mcp_proxy | databricks_fake | 200 | 8482 | 16616 | 19042 | 23544 | 2.5 / 3.5 | 1 |

GAF overhead, delta = p95(with) - p95(without), microseconds:

| Transport | Store | Rules | p95 with | p95 without | delta p95 |
|---|---|---|---|---|---|
| asgi | sqlite_file | 19 | 7053 | 2826 | 4227 |
| uvicorn | sqlite_file | 19 | 6892 | 3666 | 3226 |
| mcp_stdio | sqlite_file | 19 | 19905 | 66 | 19839 |
| asgi | sqlite_file | 200 | 8075 | 2839 | 5236 |
| uvicorn | sqlite_file | 200 | 7560 | 3566 | 3994 |
| mcp_stdio | sqlite_file | 200 | 21778 | 79 | 21699 |
| asgi | sqlite_memory | 19 | 3830 | 2726 | 1104 |
| uvicorn | sqlite_memory | 19 | 4133 | 3626 | 507 |
| mcp_stdio | sqlite_memory | 19 | 15192 | 82 | 15110 |
| asgi | sqlite_memory | 200 | 4490 | 2702 | 1788 |
| uvicorn | sqlite_memory | 200 | 5210 | 3601 | 1609 |
| mcp_stdio | sqlite_memory | 200 | 16597 | 67 | 16530 |
| asgi | databricks_fake | 19 | 3807 | 2649 | 1158 |
| uvicorn | databricks_fake | 19 | 4812 | 3739 | 1073 |
| mcp_stdio | databricks_fake | 19 | 17794 | 68 | 17726 |
| asgi | databricks_fake | 200 | 5009 | 2766 | 2243 |
| uvicorn | databricks_fake | 200 | 5665 | 3585 | 2080 |
| mcp_stdio | databricks_fake | 200 | 16616 | 81 | 16535 |

Per-component time of one gate check (p50 / p95 us; components do not sum to the total percentile):

| Store | Rules | parse | policy_eval | fact_lookup | store_write | chain_append | record_other | handoff | total | stmts/check (exec+query) |
|---|---|---|---|---|---|---|---|---|---|---|
| sqlite_file | 19 | 13 / 29 | 106 / 277 | 0 / 1 | 690 / 1166 | 616 / 944 | 99 / 154 | 50 / 153 | 1581 / 2552 | 4.03 |
| sqlite_file | 200 | 14 / 34 | 568 / 1470 | 0 / 8 | 785 / 1211 | 601 / 1073 | 154 / 194 | 56 / 166 | 2339 / 3787 | 4.03 |
| sqlite_memory | 19 | 10 / 21 | 111 / 239 | 0 / 1 | 125 / 245 | 115 / 152 | 71 / 96 | 49 / 137 | 517 / 740 | 4.03 |
| sqlite_memory | 200 | 11 / 23 | 516 / 1390 | 0 / 7 | 126 / 237 | 116 / 160 | 121 / 147 | 43 / 132 | 988 / 1867 | 4.03 |
| databricks_fake | 19 | 10 / 13 | 110 / 188 | 0 / 1 | 262 / 361 | 197 / 231 | 67 / 85 | 47 / 125 | 729 / 867 | 4.03 |
| databricks_fake | 200 | 10 / 23 | 523 / 1403 | 0 / 7 | 281 / 414 | 213 / 253 | 125 / 148 | 48 / 142 | 1259 / 2158 | 4.03 |

Reproducibility (p50 within 10%, p95 within 20% across repeats, spreads under 50 us ignored): enforced; 2 FAIL
- otlp_inproc_1span|sqlite_file|200: p95 varies 56.7% across repeats (values [866, 691, 1182] us, tolerance 20%)
- otlp_asgi_20span|databricks_fake|200: p50 varies 17.1% across repeats (values [6271, 5592, 6664] us, tolerance 10%)

Not measured:
- Real Delta REST round trip: databricks_fake is SQLite plus the adapter's marshalling code; the warehouse, its queue, cold start and the network are not in the numbers. Use notebooks/latency_delta.py in the workspace.
- Network: the HTTP arms use the loopback interface or an in-process transport; no router, proxy, load balancer or Databricks Apps front door.
- TLS: no handshake and no encryption cost.
- Authentication: ingress auth (WP20) and SSO header checks are not in the request path here.
- The agent's own work, the tool call itself and any LLM judge (judges are advisory and run off the gate path).
- Tier 0b (asynchronous regex classifier) runs as in production, after the answer is returned; its work is not timed, it only shows up as contention in the next call.
- Real fact sources: the fact arm is an in-memory dict; a bank system of record adds its own latency to every fact rule that fires.
- Several agents and many clients at once: the load is one stream at a fixed rate on a shared host, not a capacity test.
- Long-lived growth: the stores are fresh at the start of each combination.
