"""WP23 latency benchmark of the Supervisor gate (and the paths around it).

Run:  uv run python -m tools.bench_latency            # full run, writes bench/latency-*.json
      uv run python -m tools.bench_latency --quick    # CI mode, about 30 s, no servers
      uv run python -m tools.bench_latency --help

What it measures (docs/latency.md has the method, the numbers and what is NOT measured):

  gate_inproc      Gateway.check() end to end (decision + store writes + evidence chain), in process
  chain_append     ChainWriter.record() alone (the signed hash chain)
  window_depth     gate_inproc with a deep in-memory window (aggregate rules scan the window)
  asgi_gate        POST /gate/check through the real routers and middleware, httpx ASGI transport
  asgi_passthrough same request, same JSON parse, no evaluation (the "without gateway" arm)
  otlp_*           POST /v1/traces, one span per request and 20 spans per request, and in process
  uvicorn_*        the same HTTP arms against a real uvicorn child process on a free local port
  mcp_*            stdio MCP proxy per tools/call, with and without the proxy

Policy sizes: 19 rules (policies/baseline.yaml) and 200 rules (baseline + generated rules of
the types simple, aggregate, prior and fact). Store backends: sqlite_file, sqlite_memory and
databricks_fake (MOCK: SQLite plus the REST marshalling code of the Delta adapter, no network).

Method (performance-engineering practice):
  * monotonic clock (time.perf_counter_ns), integer microseconds;
  * a warm-up phase that is discarded, then a fixed number of iterations;
  * HTTP arms are open loop: requests leave on a fixed schedule and latency is measured from the
    INTENDED send time, so a slow reply cannot hide the queue behind it (coordinated omission);
  * 3 repeats; the reported value is the median of the repeats; the spread of p50 and p95 must
    stay within the tolerance (10 percent) or the run fails with a message (full mode);
  * percentiles use the nearest-rank rule (same as GateMetrics.percentile).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import gc
import json
import math
import os
import platform
import random
import socket
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "supervisor-latency-bench/1"

SIZES = (19, 200)
BACKENDS = ("sqlite_file", "sqlite_memory", "databricks_fake")
SCENARIOS = ("inproc", "chain", "breakdown", "window", "asgi", "otlp", "server", "mcp")
GATE_BUDGET_P99_US = 50_000  # laptop SQLite budget (ILLUSTRATIVE until the bank sets it)
FORBIDDEN_PORTS = {3000, 3001, 3002, 5432, 6379, 8000, 8001, 8002, 8080}
PORT_RANGE = (20_000, 29_999)  # outside the forbidden ranges (55000-59999 and the ports above)

NOT_MEASURED = [
    "Real Delta REST round trip: databricks_fake is SQLite plus the adapter's marshalling code; "
    "the warehouse, its queue, cold start and the network are not in the numbers. Use "
    "notebooks/latency_delta.py in the workspace.",
    "Network: the HTTP arms use the loopback interface or an in-process transport; no router, "
    "proxy, load balancer or Databricks Apps front door.",
    "TLS: no handshake and no encryption cost.",
    "Authentication: ingress auth (WP20) and SSO header checks are not in the request path here.",
    "The agent's own work, the tool call itself and any LLM judge (judges are advisory and run "
    "off the gate path).",
    "Tier 0b (asynchronous regex classifier) runs as in production, after the answer is "
    "returned; its work is not timed, it only shows up as contention in the next call.",
    "Real fact sources: the fact arm is an in-memory dict; a bank system of record adds its own "
    "latency to every fact rule that fires.",
    "Several agents and many clients at once: the load is one stream at a fixed rate on a "
    "shared host, not a capacity test.",
    "Long-lived growth: the stores are fresh at the start of each combination.",
]


class BenchError(Exception):
    """A user-facing benchmark failure (bad workload, missing dependency, no reproducibility)."""


# ----------------------------------------------------------------------------- statistics


def percentile(sorted_values: Sequence[int], p: int) -> int:
    """Nearest-rank percentile of an ascending list (integer in, integer out)."""
    if not sorted_values:
        return 0
    rank = max(1, math.ceil(p * len(sorted_values) / 100))
    return int(sorted_values[rank - 1])


def summarise(samples: Sequence[int]) -> dict[str, int]:
    values = sorted(int(s) for s in samples)
    return {
        "n": len(values),
        "min": values[0] if values else 0,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": values[-1] if values else 0,
        "mean": sum(values) // len(values) if values else 0,
    }


def median_int(values: Sequence[int]) -> int:
    """Median of integers; for an even count the lower integer mean of the two middle values."""
    ordered = sorted(int(v) for v in values)
    if not ordered:
        return 0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def spread_bp(values: Sequence[int]) -> int:
    """(max - min) / median in basis points (1 bp = 0.01 percent). 0 for an empty/zero median."""
    med = median_int(values)
    if not values or med <= 0:
        return 0
    return (max(values) - min(values)) * 10_000 // med


STAT_KEYS = ("p50", "p95", "p99", "max")
GATED_KEYS = ("p50", "p95")  # the reproducibility rule applies to these (tails are noisy)


def aggregate_repeats(repeats: Sequence[dict[str, int]]) -> dict[str, Any]:
    """Median of each statistic over the repeats, plus the spread in bp."""
    med = {k: median_int([r[k] for r in repeats]) for k in (*STAT_KEYS, "mean")}
    med["n"] = repeats[0]["n"] if repeats else 0
    spread = {k: spread_bp([r[k] for r in repeats]) for k in STAT_KEYS}
    return {"median": med, "spread_bp": spread}


def reproducibility_failures(
    results: Sequence[dict[str, Any]],
    tolerance_bp: int,
    abs_floor_us: int = 0,
    tolerance_p95_bp: int | None = None,
) -> list[str]:
    """Messages for every result whose p50 (or p95) moved more than the tolerance across repeats.
    p95 rests on the slowest 5 percent of the samples, so its sampling error is wider than that
    of p50 and it has its own tolerance (default: the same)."""
    out = []
    for res in results:
        reps = res.get("repeats") or []
        if len(reps) < 2:
            continue
        for key in GATED_KEYS:
            vals = [r[key] for r in reps]
            bp = spread_bp(vals)
            limit = tolerance_p95_bp if (key == "p95" and tolerance_p95_bp) else tolerance_bp
            if bp > limit and (max(vals) - min(vals)) > abs_floor_us:
                out.append(
                    f"{res['id']}: {key} varies {bp / 100:.1f}% across repeats "
                    f"(values {vals} us, tolerance {limit / 100:.0f}%)"
                )
    return out


# ----------------------------------------------------------------------------- environment


def git_head(repo: Path = REPO_ROOT) -> str:
    """HEAD commit read from the .git files (no subprocess; works in a linked worktree)."""
    try:
        dotgit = repo / ".git"
        gitdir = dotgit
        if dotgit.is_file():
            text = dotgit.read_text(encoding="utf-8").strip()
            gitdir = Path(text.split("gitdir:", 1)[1].strip())
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(":", 1)[1].strip()
        common = gitdir
        if (gitdir / "commondir").exists():
            common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
        for base in (gitdir, common):
            f = base / ref
            if f.exists():
                return f.read_text(encoding="utf-8").strip()
        packed = common / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + ref):
                    return line.split()[0]
    except (OSError, IndexError, ValueError):
        pass
    return "unknown"


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _pkg_version(name: str) -> str:
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "absent"


def environment() -> dict[str, Any]:
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    flags = {
        "python_optimize": sys.flags.optimize,
        "python_dev_mode": bool(sys.flags.dev_mode),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "unset"),
        "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
        "gc_enabled": gc.isenabled(),
        "uvloop": _pkg_version("uvloop"),
        "httptools": _pkg_version("httptools"),
        "cpu_governor": _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") or "n/a",
        "hypervisor": "yes" if "hypervisor" in (_read("/proc/cpuinfo") or "") else "no",
    }
    return {
        "commit": git_head(),
        "date_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": platform.python_version(),
        "python_impl": platform.python_implementation(),
        "platform": platform.platform(),
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "load_avg_1_5_15": [round(x, 2) for x in load],
        "versions": {
            n: _pkg_version(n)
            for n in ("fastapi", "starlette", "uvicorn", "httpx", "pydantic", "supervisor")
        },
        "env_flags": flags,
    }


# ----------------------------------------------------------------------------- policy


BASELINE = REPO_ROOT / "policies" / "baseline.yaml"
ALL_AGENTS = "[payments, customer_service, credit_prequal]"


def _gen_rule(i: int) -> str:
    """One generated rule. Types cycle: 50% simple, 20% aggregate, 15% prior, 15% fact.

    None of them matches the benchmark workload, so the decision is always the same and the
    cost measured is the cost of evaluating the rule, not of recording extra verdicts."""
    head = (
        f"  - id: GEN-{i:04d}\n    version: 1\n    description: bench rule {i}\n"
        f"    agent_scope: {ALL_AGENTS}\n"
    )
    tail = "    action: alert\n    severity: low\n    risk_class: read_only\n    owner: bench\n\n"
    slot = i % 20
    if slot < 10:  # simple: the first predicates are true for most calls, the last is false
        tools = ["transfer", "waive_fee", "get_balance", "fetch_application"]
        k = i % len(tools)
        when = (
            "    when:\n"
            f"      tool: {{in: [{tools[k]}, {tools[(k + 1) % 4]}, list_payees]}}\n"
            "      all:\n"
            "        - {arg: customer_id, op: present}\n"
            f'        - {{arg: memo, op: matches, value: "(?i)^ref-{i}-[0-9]+$"}}\n'
            "        - {arg: amount_minor, op: gt, value: 900000000000}\n"
        )
        return head + when + tail
    if slot < 14:  # aggregate
        window = 86400 if i % 2 else 3600
        if i % 3 == 0:
            body = (
                "    when:\n      tool: transfer\n    aggregate:\n      fn: sum\n"
                f"      field: amount_minor\n      window_s: {window}\n      group_by: customer\n"
                "      customer_arg: from_account_id\n      op: gt\n      limit: 900000000000\n"
            )
        else:
            tool = ("waive_fee", "get_balance")[i % 2]
            arg = "account_id" if tool == "waive_fee" else "customer_id"
            body = (
                f"    when:\n      tool: {tool}\n    aggregate:\n      fn: count\n"
                f"      window_s: {window}\n      group_by: customer\n"
                f"      customer_arg: {arg}\n      op: gt\n      limit: 900000000\n"
            )
        return head + body + tail
    if slot < 17:  # prior
        body = (
            "    when:\n      tool: transfer\n    prior:\n      tool: add_payee\n"
            "      within_s: 3600\n      match_args: [customer_id]\n      mode: present\n"
            "      same_agent: true\n"
        )
        return head + body + tail
    body = (  # fact: the record says documents_complete is true, so this never matches
        "    when:\n      tool: {in: [fetch_application, decide_prequal]}\n      all:\n"
        "        - {arg: fact.application.documents_complete, op: ne, value: true}\n"
    )
    return head + body + tail


def write_policy_dir(directory: Path, size: int) -> int:
    """Write baseline.yaml (+ gen.yaml for size > 19) into ``directory``; return the rule count."""
    directory.mkdir(parents=True, exist_ok=True)
    base = BASELINE.read_text(encoding="utf-8")
    (directory / "baseline.yaml").write_text(base, encoding="utf-8")
    n_base = base.count("\n  - id: ")
    extra = max(0, size - n_base)
    if extra:
        text = "policy_version: 1\n\nrules:\n" + "".join(_gen_rule(i) for i in range(extra))
        (directory / "gen.yaml").write_text(text, encoding="utf-8")
    return n_base + extra


# ----------------------------------------------------------------------------- workload


APP_LAG = (
    99  # calls between an application fetch and its decision; 99 = 3 mod 8, so it hits a fetch
)


class Workload:
    """Deterministic call stream (seeded). Every id is unique so no aggregate limit trips.

    Cycle of 8 calls: get_balance, transfer, waive_fee, fetch_application, get_balance,
    read_ticket, decide_prequal, list_payees. decide_prequal uses the application fetched 12
    cycles earlier (99 calls before), so the "read first" rule passes even when requests
    are in flight together; in the first 99 calls it is a score lookup instead."""

    def __init__(self, seed: int = 7) -> None:
        self.rng = random.Random(seed)  # noqa: S311 - benchmark data, not security
        self.i = 0

    def next(self) -> tuple[str, str, str, dict[str, Any]]:
        i = self.i
        self.i += 1
        cus, acc = f"CUS-{i:08d}", f"ACC-{i:010d}"
        k = i % 8
        if k in (0, 4):
            return "payments", "1", "get_balance", {"customer_id": cus, "account_id": acc}
        if k == 1:
            return (
                "payments",
                "1",
                "transfer",
                {
                    "customer_id": cus,
                    "from_account_id": acc,
                    "payee_id": f"P{i % 997}",
                    "amount_minor": self.rng.randrange(1_000, 5_000_000),
                    "currency": "VND",
                    "channel": "app",
                    "memo": f"ref-{i}",
                },
            )
        if k == 2:
            return (
                "customer_service",
                "1",
                "waive_fee",
                {"customer_id": cus, "account_id": acc, "amount_minor": 10_000},
            )
        if k == 3:
            return "credit_prequal", "1", "fetch_application", {"application_id": f"APP-{i:08d}"}
        if k == 5:
            return "customer_service", "1", "read_ticket", {"ticket_id": f"T{i}"}
        if k == 6:
            if i < APP_LAG:
                return "credit_prequal", "1", "credit_score_lookup", {"customer_id": cus}
            return (
                "credit_prequal",
                "1",
                "decide_prequal",
                {
                    "application_id": f"APP-{i - APP_LAG:08d}",
                    "decision": "approve",
                    "amount_minor": 50_000_000,
                },
            )
        return "payments", "1", "list_payees", {"customer_id": cus}


def mcp_message(i: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": i,
        "method": "tools/call",
        "params": {"name": "get_balance", "arguments": {"account_id": f"ACC-{i:010d}"}},
    }


def check_body(call: tuple[str, str, str, dict[str, Any]]) -> bytes:
    agent, version, tool, args = call
    return json.dumps(
        {"agent_id": agent, "agent_version": version, "tool_name": tool, "args": args},
        separators=(",", ":"),
    ).encode()


def otlp_body(n_spans: int, base: int) -> bytes:
    """OTLP/HTTP JSON with ``n_spans`` tool_call spans; ids are unique per ``base``."""
    spans = []
    for j in range(n_spans):
        k = base + j
        spans.append(
            {
                "traceId": f"{k:032x}",
                "spanId": f"{k:016x}",
                "name": "execute_tool get_balance",
                "kind": 1,
                "startTimeUnixNano": str(1_760_000_000_000_000_000 + k * 1_000),
                "endTimeUnixNano": str(1_760_000_000_000_000_000 + k * 1_000 + 5_000_000),
                "attributes": [
                    _attr("supervisor.agent_id", "payments"),
                    _attr("supervisor.agent_version", "1"),
                    _attr("supervisor.event_type", "tool_call"),
                    _attr("supervisor.tool_name", "get_balance"),
                    _attr(
                        "supervisor.args",
                        f"account ACC-{k:010d} for Nguyen Van A, phone 0912345{k % 1000:03d}",
                    ),
                    _attr("supervisor.status", "ok"),
                ],
                "status": {"code": 1},
            }
        )
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", "bench-agent")]},
                "scopeSpans": [{"scope": {"name": "bench", "version": "1"}, "spans": spans}],
            }
        ]
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _attr(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


# ----------------------------------------------------------------------------- stores


def _sqlite_bench_executor() -> type:
    from supervisor.adapters.sql.sqlite import SqliteExecutor

    class BenchSqlite(SqliteExecutor):
        """SqliteExecutor that counts statements (one integer increment per call)."""

        def __init__(self, path: str | Path, table_prefix: str = "") -> None:
            super().__init__(path, table_prefix)
            self.n_execute = 0
            self.n_query = 0

        def execute(self, sql, params=None, param_types=None):  # type: ignore[no-untyped-def]
            self.n_execute += 1
            return super().execute(sql, params, param_types)

        def query(self, sql, params=None, column_types=None, param_types=None):  # type: ignore[no-untyped-def]
            self.n_query += 1
            return super().query(sql, params, column_types, param_types)

    return BenchSqlite


def _fake_delta_executor() -> type:
    """MOCK of the Delta path: SQLite in memory, plus the marshalling the REST adapter does.

    Every statement serialises its parameters as typed strings (``to_param`` and the SDK's
    ``StatementParameterListItem``), and every result goes through the REST JSON shape and the
    SDK's ``StatementResponse.from_dict`` and ``from_db``. The SQL text itself is the SQLite
    form (the Delta MERGE form cannot run on SQLite). ``rtt_ms`` adds a fixed sleep per
    statement to model a round trip; 0 by default. This is NOT a measurement of Delta."""
    try:
        from databricks.sdk.service.sql import StatementParameterListItem, StatementResponse
    except ImportError as exc:  # pragma: no cover - dev dependency
        raise BenchError("databricks_fake needs databricks-sdk (uv sync installs it)") from exc
    from supervisor.adapters.sql.databricks_fake import dml_result, succeeded
    from supervisor.core.schema import from_db, to_param

    Base = _sqlite_bench_executor()

    def _text(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return "true" if v else "false"
        return v if isinstance(v, str) else str(v)

    class FakeDeltaExecutor(Base):  # type: ignore[valid-type, misc]
        def __init__(self, rtt_ms: int = 0) -> None:
            super().__init__(":memory:")
            self.rtt_ms = rtt_ms

        def describe(self) -> str:
            return "databricks_fake (MOCK: sqlite memory + REST marshalling, no network)"

        def _request(self, params: Any, param_types: Any) -> None:
            items = []
            for name, value in (params or {}).items():
                text, db_type = to_param(value, (param_types or {}).get(name))
                items.append(StatementParameterListItem(name=name, value=text, type=db_type))
            json.dumps([p.as_dict() for p in items])
            if self.rtt_ms:
                time.sleep(self.rtt_ms / 1000)

        def execute(self, sql, params=None, param_types=None):  # type: ignore[no-untyped-def]
            self._request(params, param_types)
            n = super().execute(sql, params, param_types)
            final, _ = succeeded([("num_affected_rows", "LONG")], [[str(max(n, 0))]])
            StatementResponse.from_dict(json.loads(json.dumps(final)))
            return n

        def query(self, sql, params=None, column_types=None, param_types=None):  # type: ignore[no-untyped-def]
            self._request(params, param_types)
            rows = super().query(sql, params, None, param_types)
            cols = list(rows[0].keys()) if rows else []
            final, _ = succeeded(
                [(c, "STRING") for c in cols], [[_text(r[c]) for c in cols] for r in rows]
            )
            resp = StatementResponse.from_dict(json.loads(json.dumps(final)))
            data = (resp.result.data_array if resp.result else None) or []
            types = dict(column_types or {})
            return [
                {c: from_db(v, types.get(c)) for c, v in zip(cols, r, strict=False)} for r in data
            ]

    _ = dml_result  # kept imported: the adapter test double lives next to it
    return FakeDeltaExecutor


@contextlib.contextmanager
def isolated_env(workdir: Path) -> Iterator[None]:
    """No .env file, no inherited backend flags; settings cache cleared on entry and exit."""
    keep = {
        k: os.environ.get(k)
        for k in ("SUPERVISOR_ENV_FILE", "DATA_DIR", "SQL_BACKEND", "TABLE_PREFIX")
    }
    os.environ["SUPERVISOR_ENV_FILE"] = str(workdir / "absent.env")
    os.environ["DATA_DIR"] = str(workdir / "data")
    os.environ.pop("SQL_BACKEND", None)
    os.environ.pop("TABLE_PREFIX", None)
    from supervisor.config import get_settings

    get_settings.cache_clear()
    try:
        yield
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()


@dataclass
class Stack:
    backend: str
    rules: int
    workdir: Path
    runtime: Any
    clock: Any
    executor: Any
    recorder: Any
    sim_step_s: float = 120.0
    closed: bool = False
    injected: set = field(default_factory=set)

    @property
    def gateway(self) -> Any:
        return self.runtime.gateway

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.runtime.close()


def build_stack(
    backend: str,
    size: int,
    workdir: Path,
    *,
    sim_step_s: float = 120.0,
    fake_rtt_ms: int = 0,
) -> Stack:
    """The production composition root (``build_runtime``) on the chosen store and policy."""
    from datetime import UTC, datetime

    from supervisor.adapters.clock import FixedClock
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings
    from supervisor.gateway.facts import MappingFactSource
    from supervisor.recorder.service import build_recorder
    from supervisor.wiring import build_runtime

    if backend not in BACKENDS:
        raise BenchError(f"unknown backend {backend!r}; choose from {', '.join(BACKENDS)}")
    rules = write_policy_dir(workdir / "policy", size)
    # time-based chain roots are off: the simulated clock must not force a root every few calls
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=workdir / "data",
        evidence_root_every_s=10**9,
        _env_file=str(workdir / "absent.env"),
    )
    clock = FixedClock(datetime(2026, 10, 20, 2, 0, 0, tzinfo=UTC))
    Bench = _sqlite_bench_executor()
    if backend == "sqlite_file":
        executor = Bench(settings.sqlite_path)
    elif backend == "sqlite_memory":
        executor = Bench(":memory:")
    else:
        executor = _fake_delta_executor()(rtt_ms=fake_rtt_ms)
    adapters = build_adapters(settings, executor=executor, clock=clock)
    facts = MappingFactSource({"application": lambda k: {"documents_complete": True}})
    runtime = build_runtime(settings, adapters=adapters, policy_dir=workdir / "policy", facts=facts)
    recorder = build_recorder(settings, adapters.tables, use_spool=False)
    return Stack(backend, rules, workdir, runtime, clock, executor, recorder, sim_step_s)


# ----------------------------------------------------------------------------- generic runner


@dataclass
class Outcomes:
    """What the gate answered. A benchmark whose workload is denied is measuring the wrong path."""

    allowed: int = 0
    denied: int = 0
    other: Counter = field(default_factory=Counter)

    def add(self, result: dict[str, Any]) -> None:
        if result.get("allow") is True:
            self.allowed += 1
        else:
            self.denied += 1
            self.other[str(result.get("rule_id"))] += 1

    def require_clean(self, what: str) -> None:
        if self.denied:
            raise BenchError(
                f"{what}: the workload was denied {self.denied} times "
                f"({dict(self.other)}); the benchmark must measure the allow path"
            )


def run_gate_inproc(stack: Stack, wl: Workload, n: int, warm: int) -> tuple[list[int], dict]:
    gw = stack.gateway
    out = Outcomes()
    for _ in range(warm):
        stack.clock.advance(stack.sim_step_s)
        a, v, t, args = wl.next()
        gw.check(a, v, t, args)
    gc.collect()
    lat: list[int] = []
    for _ in range(n):
        stack.clock.advance(stack.sim_step_s)
        a, v, t, args = wl.next()
        t0 = time.perf_counter_ns()
        res = gw.check(a, v, t, args)
        lat.append((time.perf_counter_ns() - t0) // 1000)
        out.add(res)
    out.require_clean("gate_inproc")
    return lat, {"allowed": out.allowed}


def run_chain_append(stack: Stack, n: int, warm: int) -> tuple[list[int], dict]:
    chain = stack.runtime.chain
    payload = {
        "agent_id": "payments",
        "tool_name": "transfer",
        "action": "allow",
        "allow": True,
        "rule_id": None,
        "policy_hash": "0" * 64,
        "args_hmac": "1" * 64,
        "latency_us": 1500,
        "matched_rules": [],
        "agent_state": "RUNNING",
    }
    for _ in range(warm):
        chain.record("gate_decision", uuid.uuid4().hex, payload)
    gc.collect()
    lat = []
    for _ in range(n):
        ref = uuid.uuid4().hex
        t0 = time.perf_counter_ns()
        chain.record("gate_decision", ref, payload)
        lat.append((time.perf_counter_ns() - t0) // 1000)
    return lat, {}


def run_otlp_inproc(
    stack: Stack, spans: int, n: int, warm: int, base: int
) -> tuple[list[int], dict]:
    from supervisor.recorder.normalise import spans_from_otlp_json

    bodies = [otlp_body(spans, base + i * spans) for i in range(warm + n)]
    lat = []
    for i, body in enumerate(bodies):
        t0 = time.perf_counter_ns()
        parsed = spans_from_otlp_json(json.loads(body))
        res = stack.recorder.ingest_spans(parsed, "otlp")
        dt_us = (time.perf_counter_ns() - t0) // 1000
        if res.written != spans:
            raise BenchError(f"otlp_inproc: wrote {res.written} of {spans} spans")
        if i >= warm:
            lat.append(dt_us)
    return lat, {"spans_per_request": spans}


# ----------------------------------------------------------------------------- breakdown


class _Probe:
    """Per-call accumulators. A wrapped call made inside another wrapped call is not counted
    twice (the outermost category owns the time)."""

    def __init__(self) -> None:
        self._tl = threading.local()
        self._lock = threading.Lock()
        self.acc: Counter = Counter()

    def wrap(self, obj: Any, name: str, cat: str) -> Callable[[], None]:
        orig = getattr(obj, name)
        probe = self

        def wrapper(*a: Any, **k: Any) -> Any:
            if getattr(probe._tl, "depth", 0):
                return orig(*a, **k)
            probe._tl.depth = 1
            t0 = time.perf_counter_ns()
            try:
                return orig(*a, **k)
            finally:
                dt_ns = time.perf_counter_ns() - t0
                probe._tl.depth = 0
                with probe._lock:
                    probe.acc[cat] += dt_ns

        setattr(obj, name, wrapper)

        def restore() -> None:
            with contextlib.suppress(AttributeError):
                delattr(obj, name)

        return restore

    def take(self) -> dict[str, int]:
        with self._lock:
            out = {k: v // 1000 for k, v in self.acc.items()}
            self.acc.clear()
        return out


def run_breakdown(stack: Stack, wl: Workload, n: int, warm: int) -> dict[str, Any]:
    """Per-component time of one gate check, p50 and p95 per component, plus statements/check.

    parse = JSON decode + request model validation of the /gate/check body (timed on its own);
    policy_eval = decision time (Decision.latency_us) minus fact lookup;
    fact_lookup, store_write (tables.append), chain_append (evidence.record) come from probes;
    record_other = rest of the recording (payload build, hashing, canonical JSON);
    handoff = wall time of check() minus Decision.total_us (thread-pool hand-off and return)."""
    from supervisor.gateway.routes import CheckRequest

    gw = stack.gateway
    probe = _Probe()
    decisions: list[Any] = []
    orig_decide = gw._decide

    def decide(*a: Any, **k: Any) -> Any:
        d = orig_decide(*a, **k)
        decisions.append(d)
        return d

    gw._decide = decide
    restores = [
        probe.wrap(gw.facts, "get", "fact_lookup"),
        probe.wrap(gw.tables, "append", "store_write"),
        probe.wrap(gw.evidence, "record", "chain_append"),
    ]
    comps: dict[str, list[int]] = {
        k: []
        for k in (
            "parse",
            "policy_eval",
            "fact_lookup",
            "store_write",
            "chain_append",
            "record_other",
            "handoff",
            "total",
        )
    }
    try:
        for _ in range(warm):
            stack.clock.advance(stack.sim_step_s)
            a, v, t, args = wl.next()
            gw.check(a, v, t, args)
        probe.take()
        decisions.clear()
        ex0, q0 = stack.executor.n_execute, stack.executor.n_query
        for _ in range(n):
            stack.clock.advance(stack.sim_step_s)
            call = wl.next()
            body = check_body(call)
            t0 = time.perf_counter_ns()
            CheckRequest.model_validate(json.loads(body))
            comps["parse"].append((time.perf_counter_ns() - t0) // 1000)
            a, v, t, args = call
            t0 = time.perf_counter_ns()
            res = gw.check(a, v, t, args)
            wall = (time.perf_counter_ns() - t0) // 1000
            d = decisions.pop()
            acc = probe.take()
            fact = acc.get("fact_lookup", 0)
            store = acc.get("store_write", 0)
            chain = acc.get("chain_append", 0)
            record = d.total_us - d.latency_us
            comps["fact_lookup"].append(fact)
            comps["policy_eval"].append(max(0, d.latency_us - fact))
            comps["store_write"].append(store)
            comps["chain_append"].append(chain)
            comps["record_other"].append(max(0, record - store - chain))
            comps["handoff"].append(max(0, wall - d.total_us))
            comps["total"].append(wall)
            if res.get("allow") is not True:
                raise BenchError(f"breakdown: workload denied by {res.get('rule_id')}")
        stmts = {
            "execute_per_check_x100": (stack.executor.n_execute - ex0) * 100 // n,
            "query_per_check_x100": (stack.executor.n_query - q0) * 100 // n,
        }
    finally:
        for r in restores:
            r()
        with contextlib.suppress(AttributeError):
            del gw._decide
    return {
        "components_us": {
            k: {"p50": percentile(sorted(v), 50), "p95": percentile(sorted(v), 95)}
            for k, v in comps.items()
        },
        "statements": stmts,
        "n": n,
    }


# ----------------------------------------------------------------------------- window depth


def inject_window(stack: Stack, depth: int) -> int:
    """Put ``depth`` synthetic allowed events per tracked tool into the gate's in-memory window
    (spread over the last 23 hours), as if a busy agent had made that many calls today."""
    from supervisor.gateway import engine

    gw = stack.gateway
    policy = gw.policy.current()
    now_us = engine._epoch_us(stack.clock.now())
    tools = sorted(engine._window_tools(policy))
    agents = sorted(policy.doc.agents)
    rng = random.Random(11)  # noqa: S311
    span_us = 23 * 3600 * 1_000_000
    for tool in tools:
        names = set(policy.tracked_keys().get(tool, ())) | engine.DEFAULT_KEYS
        events = []
        for j in range(depth):
            keys = {nm: engine.key_hash(nm, f"INJ-{tool}-{j}") for nm in sorted(names)}
            ts = now_us - span_us + (span_us * j) // max(1, depth)
            who = (
                [a for a in agents if a != "credit_prequal"]
                if tool == "fetch_application"
                else agents
            )
            events.append(
                engine._Event(ts, who[j % len(who)], keys, rng.randrange(1_000, 5_000_000))
            )
        merged = sorted([*gw.windows.by_tool.get(tool, ()), *events], key=lambda e: e.ts_us)
        gw.windows.by_tool[tool] = engine.deque(merged)  # the window scan needs ascending time
        stack.injected.update(id(e) for e in events)
    return len(tools) * depth


def remove_injected(stack: Stack) -> None:
    ids = stack.injected
    for tool, dq in list(stack.gateway.windows.by_tool.items()):
        stack.gateway.windows.by_tool[tool] = type(dq)(e for e in dq if id(e) not in ids)
    ids.clear()


# ----------------------------------------------------------------------------- HTTP (open loop)


@dataclass
class DriveResult:
    latency_us: list[int]
    lag_us: list[int]
    errors: int
    denied: int
    wall_s: float


async def drive_open_loop(
    send: Callable[[bytes], Any], bodies: Sequence[bytes], rate_hz: int
) -> DriveResult:
    """Fire ``bodies`` on a fixed schedule; latency = completion - INTENDED send time.

    A late reply therefore delays nothing: the next request still leaves on schedule, and the
    time it waits behind the slow one is counted. ``lag_us`` is how late each send left (a
    health check of the load generator itself)."""
    n = len(bodies)
    interval_ns = 1_000_000_000 // rate_hz
    lat = [0] * n
    lag = [0] * n
    errors = 0
    denied = 0
    start = time.perf_counter_ns() + 50_000_000

    async def one(i: int, intended: int) -> None:
        nonlocal errors, denied
        ok = await send(bodies[i])
        lat[i] = (time.perf_counter_ns() - intended) // 1000
        if ok is None:
            errors += 1
        elif ok is False:
            denied += 1

    tasks = []
    for i in range(n):
        intended = start + i * interval_ns
        wait = intended - time.perf_counter_ns()
        if wait > 0:
            await asyncio.sleep(wait / 1e9)
        lag[i] = max(0, (time.perf_counter_ns() - intended) // 1000)
        tasks.append(asyncio.create_task(one(i, intended)))
    await asyncio.gather(*tasks)
    return DriveResult(lat, lag, errors, denied, (time.perf_counter_ns() - start) / 1e9)


DENY_RULES: Counter = Counter()


def _http_sender(client: Any, path: str, kind: str) -> Callable[[bytes], Any]:
    hdr = {"content-type": "application/json"}

    async def send(body: bytes) -> bool | None:
        try:
            r = await client.post(path, content=body, headers=hdr)
        except Exception:  # noqa: BLE001 - counted as an error, the run fails afterwards
            return None
        if r.status_code != 200:
            return None
        if kind == "gate":
            body = r.json()
            if body.get("allow") is not True:
                DENY_RULES[f"{body.get('rule_id')}: {str(body.get('reason'))[:80]}"] += 1
                return False
        return True

    return send


class _Tick:
    """Pure ASGI middleware: advance the simulated clock before each gate or passthrough
    request, so aggregates see a bounded window. Applied to both arms alike."""

    PATHS = ("/gate/check", "/v1/gate/check", "/bench/passthrough")

    def __init__(self, app: Any, clock: Any, step_s: float) -> None:
        self.app, self.clock, self.step_s = app, clock, step_s

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path") in self.PATHS:
            # the pass-through arm pays the same middleware cost but does not move time
            self.clock.advance(0.0 if scope["path"].endswith("passthrough") else self.step_s)
        await self.app(scope, receive, send)


def build_bench_app(stack: Stack) -> Any:
    """The real gate and OTLP routers and the real ops middleware, built like supervisor.app
    but without the console and the scheduler, plus a pass-through route (bench only)."""
    from starlette.concurrency import run_in_threadpool

    from supervisor.core.errors import SupervisorError
    from supervisor.gateway import wiring as gate_wiring
    from supervisor.gateway.routes import CheckRequest
    from supervisor.gateway.routes import router as gate_router
    from supervisor.ops import middleware as ops_middleware
    from supervisor.recorder.otlp_receiver import recorder_dep
    from supervisor.recorder.otlp_receiver import router as otlp_router

    app = FastAPI(docs_url=None, redoc_url=None)
    app.include_router(gate_router, prefix="/v1")
    app.include_router(gate_router)
    app.include_router(otlp_router)
    ops_middleware.install(app, stack.runtime.settings)

    @app.exception_handler(SupervisorError)
    async def _err(_: Request, exc: SupervisorError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    fixed = {
        "allow": True,
        "action": "allow",
        "rule_id": None,
        "reason": "passthrough (bench)",
        "latency_ms": 0,
    }

    @app.post("/bench/passthrough")
    async def passthrough(request: Request) -> JSONResponse:
        # same JSON parse and request validation as /gate/check, then the same thread hop
        CheckRequest.model_validate(await request.json())
        result = await run_in_threadpool(dict, fixed)
        return JSONResponse(content=result)

    @app.get("/bench/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    gate_wiring.set_gateway(stack.gateway)
    app.dependency_overrides[recorder_dep] = lambda: stack.recorder
    return _Tick(app, stack.clock, stack.sim_step_s)


@dataclass
class HttpPlan:
    n: int
    warm: int
    rate_hz: int
    otlp_batches: tuple[int, ...] = (1, 20)
    otlp_rate_hz: int = 100


def _check_drive(res: DriveResult, what: str) -> None:
    if res.errors:
        raise BenchError(f"{what}: {res.errors} requests failed (not HTTP 200)")
    if res.denied:
        raise BenchError(
            f"{what}: {res.denied} gate answers were deny {dict(DENY_RULES)}; "
            "the workload must allow"
        )


async def _http_arm(
    client: Any, path: str, kind: str, bodies_warm: list[bytes], bodies: list[bytes], rate: int
) -> tuple[list[int], dict]:
    send = _http_sender(client, path, kind)
    if bodies_warm:
        warm = await drive_open_loop(send, bodies_warm, rate)
        _check_drive(warm, f"{kind} warm-up")
    res = await drive_open_loop(send, bodies, rate)
    _check_drive(res, kind)
    lagged = sorted(res.lag_us)
    ach = int(len(bodies) / res.wall_s) if res.wall_s > 0 else 0
    meta = {
        "rate_hz": rate,
        "achieved_rate_hz": ach,
        "generator_lag_us": {"p50": percentile(lagged, 50), "p99": percentile(lagged, 99)},
    }
    return res.latency_us, meta


async def _prime(client: Any, bodies: list[bytes], path: str) -> None:
    """A few sequential requests so imports, regex compilation and pools are warm."""
    for b in bodies:
        await client.post(path, content=b, headers={"content-type": "application/json"})


def run_http_gate_pair(
    make_client: Callable[[], Any],
    plan: HttpPlan,
    wl: Workload,
    order: int,
    prefix: str = "",
    wl_pass: Workload | None = None,
    prime: bool = False,
) -> dict[str, tuple[list[int], dict]]:
    """One pass of the GAF pair: /gate/check and the pass-through, same rate, same payload
    shape. ``order`` alternates which arm goes first to cancel drift. ``plan.warm`` requests per
    arm are sent first and discarded; ``prime`` adds 8 sequential requests before that."""

    wl_pass = wl_pass or Workload(1_000)  # the gate's stream must stay contiguous

    def bodies(count: int, source: Workload) -> list[bytes]:
        return [check_body(source.next()) for _ in range(count)]

    async def go() -> dict[str, tuple[list[int], dict]]:
        out: dict[str, tuple[list[int], dict]] = {}
        client = make_client()
        try:
            if prime:
                await _prime(client, bodies(8, wl_pass), "/bench/passthrough")
                await _prime(client, bodies(8, wl), prefix + "/gate/check")
            arms = [("gate", prefix + "/gate/check"), ("passthrough", "/bench/passthrough")]
            if order % 2:
                arms.reverse()
            for kind, path in arms:
                out[kind] = await _http_arm(
                    client,
                    path,
                    "gate" if kind == "gate" else "pass",
                    bodies(plan.warm, wl if kind == "gate" else wl_pass),
                    bodies(plan.n, wl if kind == "gate" else wl_pass),
                    plan.rate_hz,
                )
        finally:
            await client.aclose()
        return out

    return asyncio.run(go())


def run_http_otlp(
    make_client: Callable[[], Any], plan: HttpPlan, spans: int, base: int
) -> tuple[list[int], dict]:
    async def go() -> tuple[list[int], dict]:
        client = make_client()
        try:
            warm = [otlp_body(spans, base + i * spans) for i in range(plan.warm)]
            run = [otlp_body(spans, base + (plan.warm + i) * spans) for i in range(plan.n)]
            lat, meta = await _http_arm(client, "/v1/traces", "otlp", warm, run, plan.otlp_rate_hz)
            meta["spans_per_request"] = spans
            return lat, meta
        finally:
            await client.aclose()

    return asyncio.run(go())


def asgi_client_factory(app: Any) -> Callable[[], Any]:
    import httpx

    def make() -> Any:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bench")

    return make


def tcp_client_factory(port: int) -> Callable[[], Any]:
    import httpx

    def make() -> Any:
        return httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            limits=httpx.Limits(max_connections=256, max_keepalive_connections=256),
            timeout=httpx.Timeout(30.0),
        )

    return make


# ----------------------------------------------------------------------------- server + MCP


def free_port() -> int:
    rng = random.Random()  # noqa: S311
    for _ in range(200):
        port = rng.randint(*PORT_RANGE)
        if port in FORBIDDEN_PORTS:
            continue
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise BenchError("no free port found in the benchmark range")


@contextlib.contextmanager
def server_child(backend: str, size: int, workdir: Path, fake_rtt_ms: int) -> Iterator[int]:
    """A real uvicorn process (bench app on a free local port), via the sandbox helper."""
    import httpx

    from supervisor import sandbox

    port = free_port()
    argv = [
        sys.executable, "-m", "tools.bench_latency", "--serve",
        "--backend", backend, "--policy-size", str(size), "--port", str(port),
        "--workdir", str(workdir), "--fake-rtt-ms", str(fake_rtt_ms),
    ]  # fmt: skip
    env = {
        "SUPERVISOR_ENV_FILE": str(workdir / "absent.env"),
        "DATA_DIR": str(workdir / "data"),
        "PYTHONUNBUFFERED": "1",
    }
    proc = sandbox.start_pipes(argv, cwd=REPO_ROOT, env=env)
    try:
        deadline = time.monotonic() + 90
        while True:
            if not proc.running():
                raise BenchError(f"the uvicorn child exited early ({backend}, {size} rules)")
            try:
                if httpx.get(f"http://127.0.0.1:{port}/bench/ping", timeout=1.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise BenchError("the uvicorn child did not start within 90 s")
            time.sleep(0.2)
        yield port
    finally:
        proc.stop()


def serve_main(ns: argparse.Namespace) -> int:
    """Child mode: build the stack, serve the bench app with uvicorn (lifespan off)."""
    import uvicorn

    workdir = Path(ns.workdir)
    with isolated_env(workdir):
        stack = build_stack(
            ns.backend,
            ns.policy_size,
            workdir,
            sim_step_s=ns.sim_step_s,
            fake_rtt_ms=ns.fake_rtt_ms,
        )
        app = build_bench_app(stack)
        try:
            uvicorn.run(
                app, host="127.0.0.1", port=ns.port, lifespan="off", log_level="error",
                access_log=False,
            )  # fmt: skip
        finally:
            stack.close()
    return 0


def echo_upstream_main() -> int:
    """A minimal MCP upstream: answer every request that has an id with a fixed result."""
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" in msg:
            reply = {
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
            sys.stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


def _mcp_loop(proc: Any, n: int, start: int) -> list[int]:
    lat = []
    for i in range(start, start + n):
        line = json.dumps(mcp_message(i), separators=(",", ":"))
        t0 = time.perf_counter_ns()
        proc.send_line(line)
        reply = proc.read_line(30.0)
        lat.append((time.perf_counter_ns() - t0) // 1000)
        if reply is None:
            raise BenchError("mcp: no reply from the proxy or upstream within 30 s")
        msg = json.loads(reply)
        if msg.get("id") != i or msg.get("result", {}).get("isError"):
            raise BenchError(f"mcp: unexpected reply {reply[:200]}")
    return lat


def run_mcp(
    port: int, workdir: Path, slice_n: int, rounds: int, warm: int, repeats: int
) -> dict[str, list[dict]]:
    """Closed loop on purpose: a stdio MCP client has one request in flight per pipe.
    Arms: direct to the echo upstream, and through ``supervisor.gateway.mcp_proxy`` (which
    calls the gate over HTTP on ``port``). Both processes stay alive and take turns in slices,
    so a slow moment on the host hits both arms and all repeats alike."""
    from supervisor import sandbox

    echo = [sys.executable, "-m", "tools.bench_latency", "--echo-upstream"]
    env = {"SUPERVISOR_ENV_FILE": str(workdir / "absent.env"), "DATA_DIR": str(workdir / "data")}
    proxy_argv = [
        sys.executable, "-m", "supervisor.gateway.mcp_proxy", "--agent-id", "payments",
        "--agent-version", "1", "--gate-url", f"http://127.0.0.1:{port}", "--", *echo,
    ]  # fmt: skip
    arms = {"direct": echo, "proxy": proxy_argv}
    procs = {name: sandbox.start_pipes(argv, cwd=REPO_ROOT, env=env) for name, argv in arms.items()}
    buckets: dict[str, list[list[int]]] = {a: [[] for _ in range(repeats)] for a in arms}
    ctr = 10_000_000
    try:
        for proc in procs.values():
            _mcp_loop(proc, 20 + warm, ctr)  # process start, imports and warm-up
            ctr += 20 + warm
        for _ in range(rounds):
            for r in range(repeats):
                for name, proc in procs.items():
                    buckets[name][r] += _mcp_loop(proc, slice_n, ctr)
                    ctr += slice_n
    finally:
        for proc in procs.values():
            proc.stop()
    return {name: [summarise(x) for x in reps] for name, reps in buckets.items()}


# ----------------------------------------------------------------------------- suite


@dataclass
class Options:
    quick: bool = False
    backends: tuple[str, ...] = BACKENDS
    sizes: tuple[int, ...] = SIZES
    scenarios: tuple[str, ...] = SCENARIOS
    repeats: int = 3
    n: int = 2000
    warm: int = 300
    http_n: int = 600
    http_warm: int = 100
    rate_hz: int = 100
    mcp_n: int = 200
    tolerance_pct: int = 10
    tolerance_p95_pct: int = 20
    strict: bool = True
    attempts: int = 4
    abs_floor_us: int = 50
    slice_n: int = 100
    http_slice: int = 100
    mcp_slice: int = 40
    seed: int = 7
    sim_step_s: float = 120.0
    fake_rtt_ms: int = 0
    window_depths: tuple[int, ...] = (1000, 10000)
    log: Callable[[str], None] = lambda s: None
    partial_path: Path | None = None

    @classmethod
    def quick_mode(cls, **kw: Any) -> Options:
        base: dict[str, Any] = {
            "quick": True,
            "backends": ("sqlite_file",),
            "scenarios": ("inproc", "chain", "breakdown", "asgi", "otlp"),
            "n": 300,
            "warm": 100,
            "http_n": 100,
            "http_warm": 30,
            "rate_hz": 100,
            "mcp_n": 40,
            "strict": False,
            "attempts": 1,
            "slice_n": 50,
            "http_slice": 50,
            "mcp_slice": 20,
            "window_depths": (1000,),
        }
        base.update(kw)
        return cls(**base)


def _result(
    rid: str,
    scenario: str,
    backend: str,
    rules: int,
    repeats: list[dict[str, int]],
    extra: dict[str, Any] | None = None,
    unit: str = "us",
) -> dict[str, Any]:
    agg = aggregate_repeats(repeats)
    return {
        "id": rid,
        "scenario": scenario,
        "backend": backend,
        "rules": rules,
        "unit": unit,
        "repeats": repeats,
        **agg,
        "extra": extra or {},
    }


def interleave(
    repeats: int, rounds: int, run_slice: Callable[[int], dict[str, list[int]]]
) -> dict[str, list[dict[str, int]]]:
    """Collect ``repeats`` independent sample sets in turns of one slice each (r0, r1, r2, r0, ...).

    On a shared host a slow period (disk stall, a neighbour's test run) would hit one sequential
    repeat and miss the others, and the spread would measure the host, not the code. Taking
    turns gives every repeat the same share of every period. The spread then shows the sampling
    noise of the statistic; the host's drift is shown by the load average and by comparing two
    runs (``--compare``)."""
    buckets: dict[str, list[list[int]]] = {}
    for _ in range(rounds):
        for r in range(repeats):
            gc.collect()
            for name, samples in run_slice(r).items():
                buckets.setdefault(name, [[] for _ in range(repeats)])[r] += samples
    return {name: [summarise(x) for x in reps] for name, reps in buckets.items()}


def _delta_row(
    transport: str, backend: str, rules: int, gate: dict, passthrough: dict
) -> dict[str, Any]:
    g, p = gate["median"], passthrough["median"]
    return {
        "transport": transport,
        "backend": backend,
        "rules": rules,
        "p95_with_gate_us": g["p95"],
        "p95_without_gate_us": p["p95"],
        "delta_p95_us": g["p95"] - p["p95"],
        "p50_delta_us": g["p50"] - p["p50"],
        "p99_delta_us": g["p99"] - p["p99"],
    }


Measure = Callable[[], dict[str, tuple[list[dict[str, int]], dict]]]


def _stable(
    opts: Options, label: str, measure: Measure
) -> tuple[dict[str, tuple[list[dict[str, int]], dict]], int]:
    """Run ``measure`` (one or more arms, 3 repeats each) and run it again while p50 or p95 of an
    arm moves more than the tolerance across its repeats (strict mode, up to ``attempts``).
    The number of attempts used is returned and stored with each result."""
    tol_bp = opts.tolerance_pct * 100
    attempt = 1
    while True:
        out = measure()
        bad: list[str] = []
        for name, (reps, _) in out.items():
            bad += reproducibility_failures(
                [{"id": name, "repeats": reps}],
                tol_bp,
                opts.abs_floor_us,
                opts.tolerance_p95_pct * 100,
            )
        if not bad or not opts.strict or attempt >= max(1, opts.attempts):
            return out, attempt
        opts.log(f"[{label}] spread above tolerance, attempt {attempt}: {bad[0]}")
        attempt += 1


def _rounds(n: int, slice_n: int) -> int:
    return max(1, n // max(1, slice_n))


def run_combo(backend: str, size: int, opts: Options) -> dict[str, Any]:
    """All scenarios for one (backend, policy size). Returns results, deltas and breakdowns."""
    results: list[dict[str, Any]] = []
    deltas: list[dict[str, Any]] = []
    breakdowns: list[dict[str, Any]] = []
    want = set(opts.scenarios)
    tag = f"{backend}|{size}"
    state = {"otlp": 1}
    reps_n = opts.repeats

    def otlp_n(spans: int) -> int:
        return opts.http_n if spans == 1 else max(opts.http_slice, opts.http_n // 3)

    def plan_for(n: int, warm: int, spans: int = 1) -> HttpPlan:
        return HttpPlan(n, warm, opts.rate_hz, otlp_rate_hz=100 if spans == 1 else 50)

    def record(
        out: dict[str, tuple[list[dict[str, int]], dict]], attempts: int, rules: int
    ) -> dict[str, dict[str, Any]]:
        got = {}
        for name, (reps, meta) in out.items():
            res = _result(f"{name}|{tag}", name, backend, rules, reps, meta)
            res["attempts"] = attempts
            results.append(res)
            got[name] = res
        return got

    def single(
        name: str, rounds: int, run_slice: Callable[[int], tuple[list[int], dict]]
    ) -> Measure:
        """One arm, ``rounds`` turns of slices over the repeats."""

        def measure() -> dict[str, tuple[list[dict[str, int]], dict]]:
            meta: dict[str, Any] = {}

            def one(r: int) -> dict[str, list[int]]:
                samples, m = run_slice(r)
                meta.update(m)
                return {name: samples}

            return {name: (interleave(reps_n, rounds, one)[name], meta)}

        return measure

    def pair(prefix: str, make: Callable[[], Any], wl_gate: Workload) -> Measure:
        slice_plan = plan_for(opts.http_slice, 0)
        warm_plan = plan_for(0, opts.http_warm)

        def measure() -> dict[str, tuple[list[dict[str, int]], dict]]:
            wl_pass = Workload(1_000)
            run_http_gate_pair(make, warm_plan, wl_gate, 0, wl_pass=wl_pass, prime=True)
            meta: dict[str, dict] = {}
            turn = {"i": 0}

            def one(r: int) -> dict[str, list[int]]:
                turn["i"] += 1
                out = run_http_gate_pair(make, slice_plan, wl_gate, turn["i"], wl_pass=wl_pass)
                for k, (_, m) in out.items():
                    meta[k] = m
                return {f"{prefix}_{k}": v[0] for k, v in out.items()}

            res = interleave(reps_n, _rounds(opts.http_n, opts.http_slice), one)
            return {name: (reps, meta[name.split("_", 1)[1]]) for name, reps in res.items()}

        return measure

    def otlp(name: str, make: Callable[[], Any], spans: int, base: int = 0) -> Measure:
        n = otlp_n(spans)
        slice_n = min(opts.http_slice, n)

        def run_slice(r: int) -> tuple[list[int], dict]:
            state["otlp"] += (slice_n + 5) * spans
            return run_http_otlp(make, plan_for(slice_n, 0, spans), spans, base + state["otlp"])

        inner = single(name, _rounds(n, slice_n), run_slice)

        def measure() -> dict[str, tuple[list[dict[str, int]], dict]]:
            state["otlp"] += (opts.http_warm + 5) * spans
            run_http_otlp(make, plan_for(0, opts.http_warm, spans), spans, base + state["otlp"])
            return inner()

        return measure

    with tempfile.TemporaryDirectory(prefix="bench-latency-") as tmp, isolated_env(Path(tmp)):
        workdir = Path(tmp)
        stack = build_stack(
            backend, size, workdir, sim_step_s=opts.sim_step_s, fake_rtt_ms=opts.fake_rtt_ms
        )
        rules = stack.rules
        wl = Workload(opts.seed)
        try:
            if "inproc" in want:
                opts.log(f"[{tag}] gate_inproc")
                run_gate_inproc(stack, wl, 0, opts.warm)  # warm-up, discarded
                fn = single(
                    "gate_inproc",
                    _rounds(opts.n, opts.slice_n),
                    lambda r: run_gate_inproc(stack, wl, opts.slice_n, 0),
                )
                record(*_stable(opts, tag, fn), rules)
            if "chain" in want:
                opts.log(f"[{tag}] chain_append")
                run_chain_append(stack, 0, opts.warm)
                fn = single(
                    "chain_append",
                    _rounds(opts.n, opts.slice_n),
                    lambda r: run_chain_append(stack, opts.slice_n, 0),
                )
                record(*_stable(opts, tag, fn), rules)
            if "breakdown" in want:
                opts.log(f"[{tag}] breakdown")
                bd = run_breakdown(stack, wl, max(100, opts.n // 2), opts.warm // 2)
                breakdowns.append({"backend": backend, "rules": rules, **bd})
            if "window" in want and backend == "sqlite_memory":
                for depth in opts.window_depths:
                    opts.log(f"[{tag}] window_depth {depth}")

                    def window_measure(depth: int = depth) -> Measure:
                        inner = single(
                            f"window_depth_{depth}",
                            _rounds(opts.n // 2, opts.slice_n),
                            lambda r: run_gate_inproc(stack, wl, opts.slice_n, 0),
                        )

                        def measure() -> dict[str, tuple[list[dict[str, int]], dict]]:
                            stack.sim_step_s = 10.0  # injected events must stay inside the window
                            try:
                                remove_injected(stack)
                                total = inject_window(stack, depth)
                                run_gate_inproc(stack, wl, 0, opts.warm // 3)
                                out = inner()
                            finally:
                                stack.sim_step_s = opts.sim_step_s
                            for _, meta in out.values():
                                meta["window_events"] = total
                            return out

                        return measure

                    record(*_stable(opts, tag, window_measure()), rules)
                remove_injected(stack)
            if "otlp" in want:
                for spans in (1, 20):
                    opts.log(f"[{tag}] otlp_inproc x{spans}")
                    n = otlp_n(spans)
                    slice_n = min(opts.http_slice, n)

                    def run_o(
                        r: int, spans: int = spans, slice_n: int = slice_n
                    ) -> tuple[list[int], dict]:
                        state["otlp"] += (slice_n + 5) * spans
                        return run_otlp_inproc(stack, spans, slice_n, 0, state["otlp"])

                    state["otlp"] += (opts.http_warm + 5) * spans
                    run_otlp_inproc(stack, spans, 0, opts.http_warm, state["otlp"])
                    fn = single(f"otlp_inproc_{spans}span", _rounds(n, slice_n), run_o)
                    record(*_stable(opts, tag, fn), rules)
            if "asgi" in want or "otlp" in want:
                from supervisor.gateway import wiring as gate_wiring

                make = asgi_client_factory(build_bench_app(stack))
            try:
                if "asgi" in want:
                    opts.log(f"[{tag}] asgi gate vs passthrough")
                    got = record(*_stable(opts, tag, pair("asgi", make, wl)), rules)
                    deltas.append(
                        _delta_row(
                            "asgi", backend, rules, got["asgi_gate"], got["asgi_passthrough"]
                        )
                    )
                if "otlp" in want:
                    for spans in (1, 20):
                        opts.log(f"[{tag}] otlp asgi x{spans}")
                        fn = otlp(f"otlp_asgi_{spans}span", make, spans)
                        record(*_stable(opts, tag, fn), rules)
            finally:
                if "asgi" in want or "otlp" in want:
                    gate_wiring.set_gateway(None)
        finally:
            stack.close()

    if "server" in want or "mcp" in want:
        with tempfile.TemporaryDirectory(prefix="bench-latency-srv-") as tmp2:
            wd2 = Path(tmp2)
            with server_child(backend, size, wd2, opts.fake_rtt_ms) as port:
                make_t = tcp_client_factory(port)
                if "server" in want:
                    opts.log(f"[{tag}] uvicorn gate vs passthrough (port {port})")
                    fn = pair("uvicorn", make_t, Workload(opts.seed + 1))
                    got = record(*_stable(opts, tag, fn), rules)
                    deltas.append(
                        _delta_row(
                            "uvicorn",
                            backend,
                            rules,
                            got["uvicorn_gate"],
                            got["uvicorn_passthrough"],
                        )
                    )
                    for spans in (1, 20):
                        opts.log(f"[{tag}] otlp uvicorn x{spans}")
                        fn = otlp(f"otlp_uvicorn_{spans}span", make_t, spans, 5_000_000)
                        record(*_stable(opts, tag, fn), rules)
                if "mcp" in want:
                    opts.log(f"[{tag}] mcp stdio proxy")

                    def run_m() -> dict[str, tuple[list[dict[str, int]], dict]]:
                        mcp = run_mcp(
                            port,
                            wd2,
                            opts.mcp_slice,
                            _rounds(opts.mcp_n, opts.mcp_slice),
                            max(20, opts.mcp_n // 4),
                            reps_n,
                        )
                        return {"mcp_direct": (mcp["direct"], {}), "mcp_proxy": (mcp["proxy"], {})}

                    got = record(*_stable(opts, tag, run_m), rules)
                    deltas.append(
                        _delta_row("mcp_stdio", backend, rules, got["mcp_proxy"], got["mcp_direct"])
                    )
    return {"results": results, "deltas": deltas, "breakdowns": breakdowns}


def run_suite(opts: Options) -> dict[str, Any]:
    env = environment()
    results: list[dict[str, Any]] = []
    deltas: list[dict[str, Any]] = []
    breakdowns: list[dict[str, Any]] = []
    for backend in opts.backends:
        for size in opts.sizes:
            part = run_combo(backend, size, opts)
            results += part["results"]
            deltas += part["deltas"]
            breakdowns += part["breakdowns"]
            if opts.partial_path is not None:  # a crash later must not lose finished combinations
                opts.partial_path.write_text(
                    json.dumps({"partial": True, "results": results, "deltas": deltas}) + "\n",
                    encoding="utf-8",
                )
    env["load_avg_end"] = (
        [round(x, 2) for x in os.getloadavg()] if hasattr(os, "getloadavg") else []
    )
    tol_bp = opts.tolerance_pct * 100
    failures = reproducibility_failures(
        results, tol_bp, opts.abs_floor_us, opts.tolerance_p95_pct * 100
    )
    attempts = {r["id"]: r.get("attempts", 1) for r in results if r.get("attempts", 1) > 1}
    return {
        "schema": SCHEMA,
        "mode": "quick" if opts.quick else "full",
        "environment": env,
        "parameters": {
            "backends": list(opts.backends),
            "policy_sizes": list(opts.sizes),
            "scenarios": list(opts.scenarios),
            "repeats": opts.repeats,
            "iterations": opts.n,
            "warmup": opts.warm,
            "http_iterations": opts.http_n,
            "http_warmup": opts.http_warm,
            "http_rate_hz": opts.rate_hz,
            "mcp_iterations": opts.mcp_n,
            "seed": opts.seed,
            "sim_step_s": opts.sim_step_s,
            "fake_rtt_ms": opts.fake_rtt_ms,
            "window_depths": list(opts.window_depths),
        },  # fmt: skip
        "method": {
            "clock": "time.perf_counter_ns (monotonic), integer microseconds",
            "percentile": "nearest rank: sorted[ceil(p*n/100)-1]",
            "reported": "median over repeats of each statistic; all repeats are kept",
            "http_load": "open loop, fixed schedule, latency from intended send time",
            "delta": "GAF: delta = p95(with gate) - p95(without gate); without = same JSON parse, "
            "same thread hop, fixed answer, no evaluation",
            "mock_backend": "databricks_fake is SQLite memory plus REST marshalling code: MOCK",
        },
        "results": results,
        "deltas": deltas,
        "breakdown": breakdowns,
        "reproducibility": {
            "enforced": opts.strict,
            "tolerance_bp": tol_bp,
            "tolerance_p95_bp": opts.tolerance_p95_pct * 100,
            "abs_floor_us": opts.abs_floor_us,
            "gated_statistics": list(GATED_KEYS),
            "failures": failures,
            "attempts": attempts,
        },
        "budgets": {
            "laptop_sqlite_p99_us": GATE_BUDGET_P99_US,
            "laptop_sqlite_status": "ILLUSTRATIVE until the bank sets it",
            "databricks_app": "FILL-ME: owner must confirm (see docs/latency.md)",
        },
        "not_measured": NOT_MEASURED,
    }


# ----------------------------------------------------------------------------- report


def _ms(us: int) -> str:
    return f"{us / 1000:.2f}"


def markdown(report: dict[str, Any]) -> str:
    env = report["environment"]
    lines = [
        f"Latency benchmark, commit `{env['commit'][:10]}`, {env['date_utc']}, "
        f"mode {report['mode']}",
        f"Machine: {env['cpu_model']}, {env['cpu_count']} logical CPUs, Python {env['python']}, "
        f"{env['platform']}",
        "",
        "All values are integer microseconds (us): median over the repeats of each statistic.",
        "",
        "| Scenario | Store | Rules | p50 | p95 | p99 | max | spread p50 / p95 (%) | tries |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["results"]:
        m, s = r["median"], r["spread_bp"]
        lines.append(
            f"| {r['scenario']} | {r['backend']} | {r['rules']} | {m['p50']} | {m['p95']} | "
            f"{m['p99']} | {m['max']} | {s['p50'] / 100:.1f} / {s['p95'] / 100:.1f} | "
            f"{r.get('attempts', 1)} |"
        )
    if report["deltas"]:
        lines += [
            "",
            "GAF overhead, delta = p95(with) - p95(without), microseconds:",
            "",
            "| Transport | Store | Rules | p95 with | p95 without | delta p95 |",
            "|---|---|---|---|---|---|",
        ]
        for d in report["deltas"]:
            lines.append(
                f"| {d['transport']} | {d['backend']} | {d['rules']} | {d['p95_with_gate_us']} | "
                f"{d['p95_without_gate_us']} | {d['delta_p95_us']} |"
            )
    if report["breakdown"]:
        comps = list(report["breakdown"][0]["components_us"].keys())
        lines += [
            "",
            "Per-component time of one gate check (p50 / p95 us; components do not sum to the "
            "total percentile):",
            "",
            "| Store | Rules | " + " | ".join(comps) + " | stmts/check (exec+query) |",
            "|---|---|" + "---|" * len(comps) + "---|",
        ]
        for b in report["breakdown"]:
            cells = [
                f"{b['components_us'][c]['p50']} / {b['components_us'][c]['p95']}" for c in comps
            ]
            st = b["statements"]
            tot = (st["execute_per_check_x100"] + st["query_per_check_x100"]) / 100
            lines.append(
                f"| {b['backend']} | {b['rules']} | " + " | ".join(cells) + f" | {tot:.2f} |"
            )
    rep = report["reproducibility"]
    lines += [
        "",
        f"Reproducibility (p50 within {rep['tolerance_bp'] / 100:.0f}%, p95 within "
        f"{rep['tolerance_p95_bp'] / 100:.0f}% across repeats, spreads under "
        f"{rep['abs_floor_us']} us ignored): "
        + ("enforced; " if rep["enforced"] else "not enforced (quick or --no-strict); ")
        + ("PASS" if not rep["failures"] else f"{len(rep['failures'])} FAIL"),
    ]
    lines += [f"- {f}" for f in rep["failures"]]
    lines += ["", "Not measured:"] + [f"- {x}" for x in report["not_measured"]]
    return "\n".join(lines) + "\n"


def compare_reports(old: dict[str, Any], new: dict[str, Any]) -> str:
    """Run-to-run comparison: p50 and p95 of every result present in both reports."""
    prev = {r["id"]: r for r in old["results"]}
    lines = [
        f"Run-to-run: {old['environment']['date_utc']} "
        f"(load {old['environment']['load_avg_1_5_15']}) vs {new['environment']['date_utc']} "
        f"(load {new['environment']['load_avg_1_5_15']})",
        "",
        "| Result | p50 old | p50 new | p50 diff % | p95 old | p95 new | p95 diff % |",
        "|---|---|---|---|---|---|---|",
    ]
    worst = 0
    for r in new["results"]:
        o = prev.get(r["id"])
        if o is None:
            continue
        cells = []
        for k in ("p50", "p95"):
            a, b = o["median"][k], r["median"][k]
            diff = (b - a) * 10_000 // a if a else 0
            worst = max(worst, abs(diff))
            cells += [str(a), str(b), f"{diff / 100:+.1f}"]
        lines.append(f"| {r['id']} | " + " | ".join(cells) + " |")
    lines += ["", f"Largest absolute difference: {worst / 100:.1f}%"]
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = report["environment"]
    stem = f"latency-{env['commit'][:7]}-{env['date_utc'][:10]}"
    if report["mode"] == "quick":
        stem += "-quick"
    jpath, mpath = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    jpath.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    mpath.write_text(markdown(report), encoding="utf-8")
    return jpath, mpath


# ----------------------------------------------------------------------------- CLI


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.bench_latency",
        description="Supervisor latency benchmark (WP23). See docs/latency.md.",
    )
    p.add_argument("--quick", action="store_true", help="CI mode: small counts, no servers")
    p.add_argument("--out-dir", default=str(REPO_ROOT / "bench"), help="where the JSON goes")
    p.add_argument("--backends", help=f"comma list of {','.join(BACKENDS)}")
    p.add_argument("--sizes", help="comma list of policy sizes (19,200)")
    p.add_argument("--scenarios", help=f"comma list of {','.join(SCENARIOS)}")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--iterations", type=int, help="in-process iterations per repeat")
    p.add_argument("--rate", type=int, help="HTTP arrival rate, requests per second")
    p.add_argument("--tolerance-pct", type=int, default=10, help="p50 spread across repeats")
    p.add_argument("--tolerance-p95-pct", type=int, default=20, help="p95 spread across repeats")
    p.add_argument("--attempts", type=int, default=4, help="strict runs: tries per measurement")
    p.add_argument("--abs-floor-us", type=int, default=50, help="spreads below this are ignored")
    p.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"), help="compare two JSON reports")
    p.add_argument("--no-strict", action="store_true", help="report, but do not fail, on spread")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument(
        "--fake-rtt-ms", type=int, default=0, help="databricks_fake: sleep per statement"
    )
    # internal modes
    p.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--echo-upstream", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--backend", help=argparse.SUPPRESS)
    p.add_argument("--policy-size", type=int, default=19, help=argparse.SUPPRESS)
    p.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument("--workdir", help=argparse.SUPPRESS)
    p.add_argument("--sim-step-s", type=float, default=120.0, help=argparse.SUPPRESS)
    return p


def options_from_args(ns: argparse.Namespace) -> Options:
    kw: dict[str, Any] = {
        "repeats": ns.repeats,
        "tolerance_pct": ns.tolerance_pct,
        "tolerance_p95_pct": ns.tolerance_p95_pct,
        "seed": ns.seed,
    }
    kw["fake_rtt_ms"] = ns.fake_rtt_ms
    kw["abs_floor_us"] = ns.abs_floor_us
    if not ns.quick:
        kw["attempts"] = ns.attempts
    if ns.backends:
        kw["backends"] = tuple(_csv(ns.backends))
    if ns.sizes:
        kw["sizes"] = tuple(int(x) for x in _csv(ns.sizes))
    if ns.scenarios:
        kw["scenarios"] = tuple(_csv(ns.scenarios))
    if ns.iterations:
        kw["n"] = ns.iterations
    if ns.rate:
        kw["rate_hz"] = ns.rate
    opts = Options.quick_mode(**kw) if ns.quick else Options(**kw)
    if ns.no_strict:
        opts.strict = False
    bad = [s for s in opts.scenarios if s not in SCENARIOS]
    if bad:
        raise BenchError(f"unknown scenario {bad}; choose from {', '.join(SCENARIOS)}")
    opts.log = lambda s: print(s, file=sys.stderr, flush=True)  # noqa: T201
    out_dir = Path(ns.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    opts.partial_path = out_dir / "latency-partial.json"
    return opts


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.compare:
        old, new = (json.loads(Path(x).read_text(encoding="utf-8")) for x in ns.compare)
        print(compare_reports(old, new))  # noqa: T201
        return 0
    if ns.echo_upstream:
        return echo_upstream_main()
    if ns.serve:
        return serve_main(ns)
    try:
        opts = options_from_args(ns)
        report = run_suite(opts)
    except BenchError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)  # noqa: T201
        return 2
    jpath, mpath = write_outputs(report, Path(ns.out_dir))
    if opts.partial_path is not None:
        opts.partial_path.unlink(missing_ok=True)
    print(markdown(report))  # noqa: T201
    print(f"[OK] wrote {jpath} and {mpath}")  # noqa: T201
    failures = report["reproducibility"]["failures"]
    if failures and opts.strict:
        print(  # noqa: T201
            "[FAIL] results are not reproducible within the tolerance. The machine was probably "
            "busy (see load_avg in the JSON). Re-run when the host is quiet, or raise "
            "--iterations. Details:\n  " + "\n  ".join(failures),
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
