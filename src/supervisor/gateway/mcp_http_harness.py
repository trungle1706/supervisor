"""Evaluation harness of the HTTP MCP gateway and its tool lock (WP26, team brief section 3).

Run:  python -m supervisor.gateway.mcp_http_harness              quality + latency, prints a table
      python -m supervisor.gateway.mcp_http_harness --help

Expert rubric: an APPLICATION SECURITY ENGINEER who reviews third-party MCP servers. That person
asks, in this order: (1) does ANY change to what the model can read or call get held until a
human looks (drift catch)? (2) are unchanged tools left alone (false alarm of the lock)? (3) is
poisoned text in a description or a schema marked for the reviewer (poisoning catch, report
only)? (4) does the scan leave honest tools alone (false alarm of the scan)? (5) is a held tool
really not callable (call block)? (6) is a removed tool logged? (7) what does the gate cost per
call, with and without it, on a kept-alive connection?

Method:
  * Golden set: tests/fixtures/mcp_http/golden.json (template items, dev and held-out split)
    and probes.json (hand-written probes OUTSIDE the templates). Provenance fields on every item.
  * Each item: a fake streamable-HTTP MCP server (MOCK, in process) lists the BASELINE tools, the
    proxy seeds the lock with trust-on-first-use, the server then lists the OBSERVED tools, the
    proxy lists again; hidden tools, suspicious marks, removed tools and tools/call answers are
    compared with the labels. The proxy, the lock service, the SQL store and the chain are the
    real code (SQLite, or databricks_fake = SQLite behind the REST marshalling, MOCK).
  * Metrics are integer basis points (bp), counts and microseconds, with Wilson 95% intervals.
    Thresholds are ILLUSTRATIVE until the bank sets its own. The verdict is GO only if every
    metric is GO. A probe row is reported on its own; a capability that only passes its own
    templates is NO-GO (probe thresholds below).
  * Failure taxonomy: every miss and false alarm is counted per scenario and finding kind.
  * No model is used (R1: the scan is deterministic and report only), so there is no model card.
    The WP25 classifier plugs in through mcp_lock.register_description_scorer and then needs its
    own card under judge/mrm/ conventions.
  * Latency: the same tools/call through (a) the fake server directly, (b) the proxy with the
    lock off and a stub gate, (c) the proxy with the lock on and a stub gate, (d) with the real
    in-process gateway, (e) with the real gateway over HTTP (HttpGate, as the stdio proxy does)
    when --gate-server is given. Keep-alive on both hops. Nearest-rank percentiles, warm-up
    discarded, 3 repeats, median of repeats.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import importlib.util
import json
import math
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT

SCHEMA = "supervisor-mcp-http-harness/1"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "mcp_http"
BASELINE_FILE = FIXTURES / "baseline.json"
RULE = "MCP-TOOL-UNREVIEWED"

# ILLUSTRATIVE thresholds: (op, value). bp = basis points, us = microseconds.
THRESHOLDS: dict[str, tuple[str, int]] = {
    "drift_catch_bp": (">=", 10000),
    "lock_false_alarm_bp": ("<=", 0),
    "call_block_bp": (">=", 10000),
    "removed_logged_bp": (">=", 10000),
    "poison_catch_bp": (">=", 9000),
    "poison_catch_heldout_bp": (">=", 8000),
    "scan_false_alarm_bp": ("<=", 500),
    "probe_drift_catch_bp": (">=", 8500),
    "probe_poison_catch_bp": (">=", 7500),
    "probe_scan_false_alarm_bp": ("<=", 2000),
    "latency_p50_overhead_us": ("<=", 15000),
    "latency_p95_overhead_us": ("<=", 50000),
}


class HarnessError(Exception):
    """A usage or environment problem (exit code 2)."""


# ----------------------------------------------------------------------------- statistics
def wilson_bp(k: int, n: int, z: float = 1.96) -> list[int] | None:
    """Wilson score interval for k of n, in basis points [low, high]."""
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [
        max(0, math.floor((centre - half) * 10000)),
        min(10000, math.ceil((centre + half) * 10000)),
    ]


def rate(k: int, n: int) -> dict[str, Any]:
    return {
        "k": k,
        "n": n,
        "bp": None if n == 0 else (k * 10000) // n,
        "wilson_bp": wilson_bp(k, n),
    }


def percentile(values: list[int], pct: int) -> int:
    """Nearest-rank percentile (same rule as GateMetrics.percentile)."""
    if not values:
        return 0
    s = sorted(values)
    return s[max(0, min(len(s) - 1, math.ceil(pct / 100 * len(s)) - 1))]


# ----------------------------------------------------------------------------- fixtures
def _fake_module() -> Any:
    path = FIXTURES / "fake_server.py"
    if not path.exists():
        raise HarnessError(f"fixtures not found at {FIXTURES}: run from a repository checkout")
    spec = importlib.util.spec_from_file_location("mcp_http_fake_server", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mcp_http_fake_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_items(split: str = "all", fixtures: Path = FIXTURES) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in ("golden.json", "probes.json"):
        p = fixtures / name
        if not p.exists():
            raise HarnessError(f"missing fixture {p}")
        out.extend(json.loads(p.read_text(encoding="utf-8")))
    if split == "all":
        return out
    if split == "templates":
        return [i for i in out if i["split"] in ("dev", "heldout")]
    return [i for i in out if i["split"] == split]


# ----------------------------------------------------------------------------- environment
class AllowGate:
    """Stub GateHook for the quality run (MOCK: the rules are not under test here)."""

    is_mock = True

    def check(self, agent_id, agent_version, tool_name, args, context=None):  # type: ignore[no-untyped-def]
        return {"allow": True, "action": "allow", "rule_id": None}


class CountingSink:
    """EvidenceSink that keeps the records (no float may enter, as in the real chain)."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        from supervisor.core.canonical import canonical_json

        canonical_json(payload)
        self.records.append((record_type, dict(payload)))
        return "0" * 64


@dataclass
class Env:
    backend: str
    workdir: Path
    adapters: Any
    sink: CountingSink
    svc: Any
    fake: Any
    upstream: Any
    closers: list[Any] = field(default_factory=list)

    def close(self) -> None:
        for c in reversed(self.closers):
            with contextlib.suppress(Exception):
                c()


def build_env(backend: str, workdir: Path) -> Env:
    from datetime import UTC, datetime

    from supervisor.adapters.clock import FixedClock
    from supervisor.adapters.factory import build_adapters
    from supervisor.adapters.mcp_upstream import HttpUpstream
    from supervisor.config import load_settings
    from supervisor.gateway.mcp_lock_service import ToolLockService
    from supervisor.jobs import bootstrap_schema

    settings = load_settings(
        sql_backend="sqlite",
        data_dir=workdir / "data",
        llm_base_url="",
        _env_file=str(workdir / "absent.env"),
    )
    clock = FixedClock(datetime(2026, 10, 20, 2, 0, 0, tzinfo=UTC))
    executor = None
    if backend == "databricks_fake":
        bench = REPO_ROOT / "tools" / "bench_latency.py"  # loaded by path: src never imports tools
        if not bench.exists():
            raise HarnessError(
                "backend databricks_fake needs the repository's tools/bench_latency.py"
            )
        spec = importlib.util.spec_from_file_location("mcp_http_bench_latency", bench)
        assert spec is not None and spec.loader is not None
        bl = importlib.util.module_from_spec(spec)
        sys.modules["mcp_http_bench_latency"] = bl
        spec.loader.exec_module(bl)
        executor = bl._fake_delta_executor()()
    elif backend == "sqlite":
        from supervisor.adapters.sql.sqlite import SqliteExecutor

        executor = SqliteExecutor(":memory:")  # same SQL as the file store, no fsync per statement
    else:
        raise HarnessError("backend must be sqlite or databricks_fake")
    adapters = build_adapters(settings, executor=executor, clock=clock)
    bootstrap_schema.run(adapters.settings, adapters)
    sink = CountingSink()
    svc = ToolLockService(adapters.state, sink, adapters.clock)
    fake = _fake_module().FakeMcpServer([]).start()
    upstream = HttpUpstream(fake.url)
    env = Env(backend, workdir, adapters, sink, svc, fake, upstream)
    env.closers += [adapters.close, fake.stop, upstream.close]
    return env


def make_proxy(
    env: Env, server_id: str, *, gate: Any = None, lock: bool = True, tofu: str | None = None
) -> Any:
    from supervisor.gateway.mcp_http import LocalLockClient, McpHttpGateProxy

    return McpHttpGateProxy(
        gate or AllowGate(),
        "payments",
        "mcp-http-1",
        env.upstream,
        server_id=server_id,
        lock=LocalLockClient(env.svc) if lock else None,
        refresh_s=0.0,
        tofu_by=tofu,
    )


# ----------------------------------------------------------------------------- quality run
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def _call(name: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}},
    }


def run_item(env: Env, item: dict[str, Any]) -> dict[str, Any]:
    sid = "g-" + item["id"].lower()
    t0 = time.perf_counter_ns()
    env.fake.set_tools(item["baseline"])
    proxy = make_proxy(env, sid, tofu="harness-seed")
    proxy.handle(LIST)  # trust-on-first-use: the baseline is the locked manifest
    env.fake.set_tools(item["observed"])
    resp = proxy.handle(LIST)
    obs_names = {t["name"] for t in item["observed"]}
    shown = {t["name"] for t in resp["result"]["tools"]} if resp and "result" in resp else set()
    hidden = obs_names - shown
    view = env.svc.view(sid)
    rows = {r["tool"]: r for r in env.svc.list_tools(sid)}
    suspicious = {n for n in obs_names if _row(rows, n) and _row(rows, n)["suspicious"]}
    kinds = {n: sorted({f["kind"] for f in _row(rows, n)["findings"]}) for n in suspicious}
    removed = set(view["removed"])
    lab = item["labels"]
    # tools/call: a held tool must be refused by the lock and never reach the server
    call_ok = 0
    call_n = 0
    leaked = 0
    for name in sorted(set(lab["hold"]) & obs_names)[:2]:
        before = len(env.fake.calls)
        r = proxy.handle(_call(name))
        call_n += 1
        meta = (r or {}).get("result", {}).get("_meta", {}).get("supervisor", {})
        call_ok += int(meta.get("rule_id") == RULE)
        if name in hidden and len(env.fake.calls) > before:
            leaked += 1  # a hidden tool must NEVER be executed upstream
    for name in sorted(shown)[:1]:
        r = proxy.handle(_call(name))
        call_n += 1
        call_ok += int(bool(r) and not r["result"].get("isError"))
    held_calls_leaked = leaked
    wall_us = (time.perf_counter_ns() - t0) // 1000
    return {
        "id": item["id"],
        "scenario": item["scenario"],
        "split": item["split"],
        "known_gap": bool(item.get("known_gap")),
        "hold": sorted(lab["hold"]),
        "poison": sorted(lab["poison"]),
        "removed_label": sorted(lab["removed"]),
        "observed": sorted(obs_names),
        "hidden": sorted(hidden),
        "suspicious": sorted(suspicious),
        "finding_kinds": kinds,
        "removed_seen": sorted(removed),
        "calls_ok": call_ok,
        "calls_n": call_n,
        "held_calls_leaked": held_calls_leaked,
        "item_us": wall_us,
    }


def _row(rows: Mapping[str, Any], name: str) -> Any:
    ascii_name = name.encode("ascii", "backslashreplace").decode("ascii")[:128]
    return rows.get(ascii_name)


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics and failure taxonomy of a list of item results."""
    drift_k = drift_n = lock_fa = lock_neg = 0
    poi_k = poi_n = scan_fa = scan_neg = 0
    rem_k = rem_n = 0
    call_k = call_n = leaked = 0
    misses: Counter[str] = Counter()
    alarms: Counter[str] = Counter()
    for r in results:
        hold, poison = set(r["hold"]), set(r["poison"])
        hidden, sus = set(r["hidden"]), set(r["suspicious"])
        for n in r["observed"]:
            if n in hold:
                drift_n += 1
                if n in hidden:
                    drift_k += 1
                else:
                    misses[f"drift:{r['scenario']}"] += 1
            else:
                lock_neg += 1
                if n in hidden:
                    lock_fa += 1
                    alarms[f"lock:{r['scenario']}"] += 1
            if n in poison:
                poi_n += 1
                if n in sus:
                    poi_k += 1
                else:
                    misses[f"poison:{r['scenario']}"] += 1
            else:
                scan_neg += 1
                if n in sus:
                    scan_fa += 1
                    for kind in r["finding_kinds"].get(n, []):
                        alarms[f"scan:{r['scenario']}:{kind}"] += 1
        if r["removed_label"] or r["removed_seen"]:
            rem_n += 1
            if sorted(r["removed_label"]) == sorted(r["removed_seen"]):
                rem_k += 1
            else:
                misses[f"removed:{r['scenario']}"] += 1
        call_k += r["calls_ok"]
        call_n += r["calls_n"]
        leaked += r["held_calls_leaked"]
    return {
        "items": len(results),
        "drift_catch": rate(drift_k, drift_n),
        "lock_false_alarm": rate(lock_fa, lock_neg),
        "poison_catch": rate(poi_k, poi_n),
        "scan_false_alarm": rate(scan_fa, scan_neg),
        "removed_logged": rate(rem_k, rem_n),
        "call_block": rate(call_k, call_n),
        "held_calls_leaked": leaked,
        "misses": dict(sorted(misses.items())),
        "false_alarms": dict(sorted(alarms.items())),
    }


def run_quality(env: Env, split: str = "all") -> dict[str, Any]:
    items = load_items(split)
    results = [run_item(env, it) for it in items]
    tmpl = [r for r in results if r["split"] in ("dev", "heldout")]
    out = {
        "n_items": len(results),
        "templates": score(tmpl),
        "dev": score([r for r in tmpl if r["split"] == "dev"]),
        "heldout": score([r for r in tmpl if r["split"] == "heldout"]),
        "probes": score([r for r in results if r["split"] == "probe"]),
        "known_gap_probes": sorted(r["id"] for r in results if r["known_gap"]),
        "chain_records": dict(sorted(Counter(t for t, _ in env.sink.records).items())),
        "rows": [
            {
                k: r[k]
                for k in (
                    "id",
                    "scenario",
                    "split",
                    "hold",
                    "poison",
                    "hidden",
                    "suspicious",
                    "item_us",
                )
            }
            for r in results
        ],
    }
    return out


# ----------------------------------------------------------------------------- latency
class KeepAliveClient:
    def __init__(self, url: str) -> None:
        host, port = url.split("//")[1].split("/")[0].split(":")
        self.conn = http.client.HTTPConnection(host, int(port), timeout=30)
        self.path = "/" + url.split("//")[1].split("/", 1)[1]
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.session: str | None = None

    def post(self, msg: dict[str, Any]) -> bytes:
        h = dict(self.headers)
        if self.session:
            h["Mcp-Session-Id"] = self.session
        self.conn.request("POST", self.path, body=json.dumps(msg), headers=h)
        r = self.conn.getresponse()
        data = r.read()
        if msg.get("method") == "initialize":
            self.session = r.getheader("Mcp-Session-Id")
        if r.status >= 400:
            raise HarnessError(f"HTTP {r.status} from {self.path}")
        return data

    def close(self) -> None:
        self.conn.close()


CALL_MSG = {
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {"name": "get_balance", "arguments": {"account_id": "A-1"}},
}


def _arm(client: KeepAliveClient, n: int, warm: int) -> list[int]:
    for _ in range(warm):
        client.post(CALL_MSG)
    lat = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        data = client.post(CALL_MSG)
        lat.append((time.perf_counter_ns() - t0) // 1000)
        if b'"isError":true' in data:
            raise HarnessError("latency arm was refused: the benchmark must measure the allow path")
    return lat


def _free_socket() -> Any:
    """A bound loopback socket on a free port in 20000-29999 (never the host's service ports)."""
    import random
    import socket

    from supervisor.gateway.mcp_http import FREE_PORTS

    rnd = random.SystemRandom()
    for _ in range(300):
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", rnd.randint(*FREE_PORTS)))
            # a socket handed to uvicorn must carry NODELAY itself; without it every kept-alive
            # answer waits 40 ms for the client's delayed ACK (found while measuring, see
            # docs/mcp-gateway.md)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return sock
        except OSError:
            sock.close()
    raise HarnessError("no free port in 20000-29999")


@contextlib.contextmanager
def _gate_server(workdir: Path) -> Iterator[tuple[str, Any]]:
    """The real gateway behind the real routers on a free local port (uvicorn in a thread)."""
    import uvicorn

    from supervisor.app import app
    from supervisor.config import load_settings
    from supervisor.gateway import wiring
    from supervisor.wiring import build_runtime

    settings = load_settings(
        sql_backend="sqlite",
        data_dir=workdir / "gdata",
        llm_base_url="",
        _env_file=str(workdir / "absent.env"),
    )
    runtime = build_runtime(settings)
    wiring.set_gateway(runtime.gateway)
    sock = _free_socket()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}", runtime
    finally:
        server.should_exit = True
        thread.join(5)
        wiring.set_gateway(None)
        runtime.close()
        sock.close()


def run_latency(env: Env, n: int, warm: int, repeats: int, gate_server: bool) -> dict[str, Any]:
    from supervisor.config import load_settings
    from supervisor.gateway.mcp_http import McpHttpServer, running
    from supervisor.gateway.sdk import HttpGate, InProcessGate
    from supervisor.wiring import build_runtime

    fake_mod = _fake_module()
    env.fake.set_tools(
        [
            fake_mod.tool(
                "get_balance",
                "Returns the balance.",
                {"account_id": {"type": "string"}},
                ["account_id"],
            )
        ]
    )
    ctxs = contextlib.ExitStack()
    arms: dict[str, KeepAliveClient] = {}
    notes: dict[str, str] = {}
    try:
        direct = KeepAliveClient(env.fake.url)
        arms["direct"] = direct
        notes["direct"] = "client -> fake server (MOCK upstream)"
        local = load_settings(
            sql_backend="sqlite",
            data_dir=env.workdir / "rt",
            llm_base_url="",
            _env_file=str(env.workdir / "absent.env"),
        )
        runtime = build_runtime(local)
        ctxs.callback(runtime.close)
        specs: list[tuple[str, Any, bool, str]] = [
            ("proxy_nolock_stubgate", AllowGate(), False, "proxy, lock off, stub gate (MOCK)"),
            ("proxy_lock_stubgate", AllowGate(), True, "proxy, lock on, stub gate (MOCK)"),
            (
                "proxy_lock_gate_inproc",
                InProcessGate(runtime.gateway),
                True,
                "proxy, lock on, real gateway in process",
            ),
        ]
        if gate_server:
            from supervisor.adapters.http_json import PooledJson

            url, _rt = ctxs.enter_context(_gate_server(env.workdir))
            pool = PooledJson()
            ctxs.callback(pool.close)
            specs.append(
                (
                    "proxy_lock_gate_http",
                    HttpGate(url, timeout_s=5.0),
                    True,
                    "proxy, lock on, real gateway over HTTP, new connection per gate call (as mcp_proxy)",
                )
            )
            specs.append(
                (
                    "proxy_lock_gate_http_pooled",
                    HttpGate(
                        url,
                        timeout_s=5.0,
                        transport=pool.post_json,
                        signed_transport=pool.post_bytes,
                    ),
                    True,
                    "proxy, lock on, real gateway over HTTP, kept-alive gate connection (mcp_http default)",
                )
            )
        for name, gate, lock, note in specs:
            proxy = make_proxy(env, "lat-" + name, gate=gate, lock=lock, tofu="harness-seed")
            proxy._refresh_s = 3600.0  # steady state: the view is cached, as in production
            srv = ctxs.enter_context(running(McpHttpServer(proxy)))
            cl = KeepAliveClient(srv.url)
            cl.post({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
            if lock:
                cl.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            arms[name] = cl
            notes[name] = note
        direct.post({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        samples: dict[str, list[tuple[int, int]]] = {k: [] for k in arms}
        order = list(arms)
        for rep in range(repeats):
            for name in order[rep % len(order) :] + order[: rep % len(order)]:
                lat = _arm(arms[name], n, warm)
                samples[name].append((percentile(lat, 50), percentile(lat, 95)))
        res = {
            name: {
                "note": notes[name],
                "p50_us": int(statistics.median(p[0] for p in s)),
                "p95_us": int(statistics.median(p[1] for p in s)),
                "p50_repeats_us": [p[0] for p in s],
                "p95_repeats_us": [p[1] for p in s],
            }
            for name, s in samples.items()
        }
        top = "proxy_lock_gate_http_pooled" if gate_server else "proxy_lock_gate_inproc"
        return {
            "n": n,
            "warmup": warm,
            "repeats": repeats,
            "arms": res,
            "top_arm": top,
            "overhead_p50_us": res[top]["p50_us"] - res["direct"]["p50_us"],
            "overhead_p95_us": res[top]["p95_us"] - res["direct"]["p95_us"],
            "lock_cost_p50_us": res["proxy_lock_stubgate"]["p50_us"]
            - res["proxy_nolock_stubgate"]["p50_us"],
            "upstream_connections": env.fake.connections,
        }
    finally:
        for c in arms.values():
            c.close()
        ctxs.close()


# ----------------------------------------------------------------------------- verdicts
def verdicts(q: dict[str, Any], lat: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    t, h, p = q["templates"], q["heldout"], q["probes"]
    values: dict[str, int | None] = {
        "drift_catch_bp": t["drift_catch"]["bp"],
        "lock_false_alarm_bp": t["lock_false_alarm"]["bp"],
        "call_block_bp": t["call_block"]["bp"],
        "removed_logged_bp": t["removed_logged"]["bp"],
        "poison_catch_bp": t["poison_catch"]["bp"],
        "poison_catch_heldout_bp": h["poison_catch"]["bp"],
        "scan_false_alarm_bp": t["scan_false_alarm"]["bp"],
        "probe_drift_catch_bp": p["drift_catch"]["bp"],
        "probe_poison_catch_bp": p["poison_catch"]["bp"],
        "probe_scan_false_alarm_bp": p["scan_false_alarm"]["bp"],
    }
    if lat is not None:
        values["latency_p50_overhead_us"] = lat["overhead_p50_us"]
        values["latency_p95_overhead_us"] = lat["overhead_p95_us"]
    out = {}
    for name, v in values.items():
        op, limit = THRESHOLDS[name]
        ok = v is not None and (v >= limit if op == ">=" else v <= limit)
        out[name] = {"value": v, "threshold": f"{op} {limit}", "verdict": "GO" if ok else "NO-GO"}
    leaked = t["held_calls_leaked"] + p["held_calls_leaked"]
    out["held_calls_leaked"] = {
        "value": leaked,
        "threshold": "<= 0",
        "verdict": "GO" if leaked == 0 else "NO-GO",
    }
    return out


def report(
    backend: str, split: str, latency: bool, gate_server: bool, n: int, repeats: int
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mcp-http-harness-") as tmp:
        env = build_env(backend, Path(tmp))
        try:
            q = run_quality(env, split)
            lat = run_latency(env, n, max(20, n // 5), repeats, gate_server) if latency else None
        finally:
            env.close()
    v = verdicts(q, lat) if split == "all" else {}
    return {
        "schema": SCHEMA,
        "commit": git_commit(),
        "backend": backend
        if backend == "sqlite"
        else "databricks_fake (MOCK: SQLite behind REST marshalling)",
        "upstream": "mock: in-process fake streamable-HTTP MCP server",
        "split": split,
        "thresholds_note": "ILLUSTRATIVE until the bank sets its own",
        "quality": q,
        "latency": lat,
        "verdicts": v,
        "overall": ("GO" if v and all(x["verdict"] == "GO" for x in v.values()) else "NO-GO")
        if v
        else "n/a",
    }


def git_commit() -> str:
    """HEAD commit read from the .git folder or file (no subprocess)."""
    try:
        git = REPO_ROOT / ".git"
        if git.is_file():
            git = Path(git.read_text().split("gitdir:")[1].strip())
        head = (git / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = head.split(None, 1)[1]
            for base in (git, git.parent.parent if git.parent.name == "worktrees" else git):
                f = base / ref
                if f.exists():
                    return f.read_text().strip()[:12]
            packed = (
                git.parent.parent / "packed-refs"
                if git.parent.name == "worktrees"
                else git / "packed-refs"
            )
            if packed.exists():
                for line in packed.read_text().splitlines():
                    if line.endswith(" " + ref):
                        return line.split()[0][:12]
            return "unknown"
        return head[:12]
    except (OSError, IndexError):
        return "unknown"


# ----------------------------------------------------------------------------- output
def _say(text: str) -> None:
    print(text.encode("ascii", "replace").decode("ascii"))  # noqa: T201


def _pct(m: Mapping[str, Any]) -> str:
    if m["bp"] is None:
        return "n/a"
    lo, hi = m["wilson_bp"]
    return f"{m['bp']:>5} bp ({m['k']}/{m['n']}, 95% {lo}-{hi})"


def print_report(rep: dict[str, Any]) -> None:
    q = rep["quality"]
    _say(f"HTTP MCP gateway harness  backend={rep['backend']}  upstream={rep['upstream']}")
    _say(f"commit {rep['commit']}  items {q['n_items']}  thresholds ILLUSTRATIVE")
    for label, key in (
        ("templates (dev+heldout)", "templates"),
        ("  dev", "dev"),
        ("  held-out", "heldout"),
        ("PROBES (outside templates)", "probes"),
    ):
        s = q[key]
        _say(f"\n{label}: {s['items']} items")
        _say(f"  drift catch        {_pct(s['drift_catch'])}")
        _say(f"  lock false alarm   {_pct(s['lock_false_alarm'])}")
        _say(f"  poison catch       {_pct(s['poison_catch'])}")
        _say(f"  scan false alarm   {_pct(s['scan_false_alarm'])}")
        _say(f"  removed logged     {_pct(s['removed_logged'])}")
        _say(
            f"  held call refused  {_pct(s['call_block'])}  leaked to server: {s['held_calls_leaked']}"
        )
        for k, v in s["misses"].items():
            _say(f"  MISS  {k} x{v}")
        for k, v in s["false_alarms"].items():
            _say(f"  FALSE ALARM  {k} x{v}")
    if q["known_gap_probes"]:
        _say("\nknown-gap probes (documented limits): " + ", ".join(q["known_gap_probes"]))
    lat = rep["latency"]
    if lat:
        _say(
            f"\nlatency per tools/call, keep-alive, n={lat['n']} x {lat['repeats']} repeats (median of repeats), us"
        )
        for name, a in lat["arms"].items():
            _say(f"  {name:26} p50 {a['p50_us']:>7}  p95 {a['p95_us']:>7}   {a['note']}")
        _say(
            f"  overhead of {lat['top_arm']} over direct: p50 {lat['overhead_p50_us']} us, p95 {lat['overhead_p95_us']} us"
        )
        _say(f"  cost of the lock alone (cached view): p50 {lat['lock_cost_p50_us']} us")
    if rep["verdicts"]:
        _say("\nverdicts (ILLUSTRATIVE thresholds)")
        for name, v in rep["verdicts"].items():
            _say(f"  [{v['verdict']:5}] {name:28} {v['value']}  (need {v['threshold']})")
    _say(f"\nOVERALL: {rep['overall']}")


def baseline_view(rep: dict[str, Any]) -> dict[str, Any]:
    """The numbers the regression test pins: counts and bp of the deterministic quality run."""
    q = rep["quality"]
    keys = (
        "drift_catch",
        "lock_false_alarm",
        "poison_catch",
        "scan_false_alarm",
        "removed_logged",
        "call_block",
    )
    out: dict[str, Any] = {}
    for part in ("templates", "heldout", "probes"):
        out[part] = {k: {"k": q[part][k]["k"], "n": q[part][k]["n"]} for k in keys}
        out[part]["held_calls_leaked"] = q[part]["held_calls_leaked"]
    return {
        "schema": SCHEMA,
        "recorded_on": time.strftime("%Y-%m-%d"),
        "commit": rep["commit"],
        "n_items": q["n_items"],
        "metrics": out,
        "known_gap_probes": q["known_gap_probes"],
        "misses": q["probes"]["misses"],
        "false_alarms": q["probes"]["false_alarms"],
        "note": "Quality run on the mock upstream, SQLite. Latency is not pinned (machine dependent).",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.gateway.mcp_http_harness",
        description="Golden set, adversarial probes and latency of the HTTP MCP gateway (WP26).",
    )
    ap.add_argument(
        "--split", choices=("all", "dev", "heldout", "templates", "probe"), default="all"
    )
    ap.add_argument("--backend", choices=("sqlite", "databricks_fake"), default="sqlite")
    ap.add_argument("--no-latency", action="store_true", help="skip the latency arms (CI)")
    ap.add_argument(
        "--gate-server", action="store_true", help="add the arm with the real gateway over HTTP"
    )
    ap.add_argument("-n", type=int, default=300, help="calls per arm and repeat")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--json", type=Path, default=None, help="write the full report here")
    ap.add_argument(
        "--record", action="store_true", help="write tests/fixtures/mcp_http/baseline.json"
    )
    ns = ap.parse_args(argv)
    try:
        rep = report(ns.backend, ns.split, not ns.no_latency, ns.gate_server, ns.n, ns.repeats)
    except HarnessError as exc:
        _say(f"[FAIL] {exc}")
        return 2
    print_report(rep)
    if ns.json:
        ns.json.write_text(
            json.dumps(rep, indent=1, sort_keys=True, ensure_ascii=True), encoding="utf-8"
        )
        _say(f"[OK] report written to {ns.json}")
    if ns.record:
        if ns.split != "all":
            _say("[FAIL] --record needs --split all")
            return 2
        BASELINE_FILE.write_text(
            json.dumps(baseline_view(rep), indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        _say(f"[OK] baseline written to {BASELINE_FILE}")
    return 0 if rep["overall"] in ("GO", "n/a") else 1


if __name__ == "__main__":
    raise SystemExit(main())
