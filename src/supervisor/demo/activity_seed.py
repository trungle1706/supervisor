"""Synthetic verdict v2 rows for the WP39 console tests, harness and screenshots (no gate
involved). Synthetic data only: every name, number and id below is made up."""

from __future__ import annotations

import html
import json
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from supervisor.core.canonical import canonical_json


def add_decision(
    ctx: Any,
    *,
    agent: str = "payments",
    status: str = "allow",
    action: str = "allow",
    corr: str | None = None,
    request_id: str | None = None,
    direction: str = "input",
    consumer: str | None = None,
    gaps: tuple[str, ...] = (),
    codes: tuple[str, ...] = (),
    not_executed: tuple[str, ...] = (),
    age_s: int = 60,
    tool: str = "get_balance",
    trace: str | None = None,
    span: str | None = None,
    lat: tuple[int, int, int] | None = (1500, 300, 400),
    fragments: list[dict[str, Any]] | None = None,
    entities: list[dict[str, Any]] | None = None,
    hint: str = "report",
    rule: str | None = None,
) -> str:
    """One gate decision (agent_event) plus its finding rows. ``lat`` is (total, rules,
    detectors) in microseconds. Returns the decision id."""
    tables = ctx.tables
    now = ctx.clock.now() - timedelta(seconds=age_s)
    eid = uuid.uuid4().hex
    trace = trace or f"t-{eid[:10]}"
    span = span or f"s-{eid[:10]}"
    cov: dict[str, Any] = {
        "direction": direction,
        "inspected": ["args"] if direction == "input" else ["output"],
        "not_inspected": [{"part": "tool_results", "reason": g} for g in gaps],
        "chars": 10,
    }
    tables.append(
        "agent_event",
        [
            {
                "event_id": eid,
                "ts": now,
                "trace_id": trace,
                "span_id": span,
                "agent_id": agent,
                "event_type": "gate_decision",
                "tool_name": tool,
                "args_hash": "h" * 64,
                "args_masked": canonical_json({"keys": {}}),
                "status": "denied" if status in ("block", "pause") else "allowed",
                "latency_ms": (lat[0] // 1000) if lat else 0,
                "latency_us": lat[0] if lat else None,
                "env": "test",
                "classification": "pause"
                if status == "pause"
                else ("block" if status == "block" else action),
                "source": "proxy",
                "capture_level": "digest",
                "verdict_status": status,
                "correlation_id": corr,
                "request_id": request_id,
                "coverage_json": canonical_json(cov),
                "consumer_id": consumer,
                "latency_rules_us": lat[1] if lat else None,
                "latency_detectors_us": lat[2] if lat else None,
                "detector_latency_json": canonical_json({"dlp_vn": (lat[2] // 2) if lat else 0})
                if lat
                else None,
            }
        ],
    )
    rows = []
    for code in codes:
        rows.append(
            _finding(
                eid,
                now,
                agent,
                tool,
                trace,
                corr,
                request_id,
                direction,
                code,
                None,
                status,
                hint,
                fragments,
                entities,
            )
        )
    for reason in not_executed:
        rows.append(
            _finding(
                eid,
                now,
                agent,
                tool,
                trace,
                corr,
                request_id,
                direction,
                f"not_executed.{reason}",
                reason,
                status,
                "report",
                None,
                None,
            )
        )
    if rows:
        tables.append("finding", rows)
    return eid


def _finding(
    eid,
    now,
    agent,
    tool,
    trace,
    corr,
    request_id,
    direction,
    code,
    reason,
    status,
    hint,
    fragments,
    entities,
) -> dict[str, Any]:  # noqa: ANN001
    return {
        "finding_id": uuid.uuid4().hex,
        "ts": now,
        "event_id": eid,
        "request_id": request_id or "req-" + eid[:8],
        "correlation_id": corr or "corr-" + eid[:8],
        "trace_id": trace,
        "agent_id": agent,
        "tool_name": tool,
        "direction": direction,
        "detector_slug": "dlp_vn" if code.startswith("pii") or reason else "injection_regex",
        "detector_id": ("dlp_vn" if code.startswith("pii") or reason else "injection_regex")
        + "@1.0.0",
        "code": code,
        "score_bp": 0 if reason else 9500,
        "threshold_bp": 8000,
        "masked_count": 0 if reason else 1,
        "action_hint": hint,
        "not_executed_reason": reason,
        "preset": "balanced",
        "is_mock": False,
        "verdict_status": status,
        "entities_masked": json.dumps(entities) if entities else None,
        "fragments_masked": json.dumps(fragments) if fragments else None,
    }


# ---------------------------------------------------------------------------- planted calls

PLANTED = {
    "name": "NGUYEN VAN THU",
    "phone": "0912345678",
    "cccd": "001203004567",
    "email": "thu.nguyen@example.com",
}
PLANTED_ARGS = {
    "customer_id": "C-1",
    "payee_name": PLANTED["name"],
    "cccd": PLANTED["cccd"],
    "note": f"so dien thoai {PLANTED['phone']}",
}
CORR = "corr-planted-0001"


def plant_calls(runtime: Any, ctx: Any) -> dict[str, str]:
    """Planted personal data through the REAL gate (detectors on): in the arguments, in tool
    results and in an output, plus the recorder event (masked text) of the same trace. Returns
    the decision ids and the trace and span ids."""
    from supervisor.adapters.factory import make_masker

    gw = runtime.gateway
    masker = make_masker(ctx.settings)
    now = ctx.clock.now()
    trace, span = "trace-planted-0001", "span-planted-0001"
    base = {"trace_id": trace, "span_id": span, "consumer_id": "app-mobile"}
    a = gw.check(
        "payments",
        "1.0.0",
        "add_payee",
        PLANTED_ARGS,
        base,
        correlation_id=CORR,
        request_id="req-planted-01",
    )
    b = gw.check(
        "payments",
        "1.0.0",
        "get_balance",
        {"account_id": "A-1"},
        {
            **base,
            "span_id": "span-planted-0002",
            "tool_results": [{"row": f"khach {PLANTED['name']} {PLANTED['phone']}"}],
        },
        correlation_id=CORR,
        request_id="req-planted-02",
    )
    c = gw.check(
        "payments",
        "1.0.0",
        "get_balance",
        {},
        {
            **base,
            "span_id": "span-planted-0003",
            "output": f"Gui {PLANTED['name']}, CCCD {PLANTED['cccd']}, mail {PLANTED['email']}",
        },
        direction="output",
        correlation_id=CORR,
        request_id="req-planted-03",
    )
    masked = masker.mask(json.dumps(PLANTED_ARGS, ensure_ascii=False)) if masker else None
    ctx.tables.append(
        "agent_event",
        [
            {
                "event_id": uuid.uuid4().hex,
                "ts": now,
                "trace_id": trace,
                "span_id": span,
                "agent_id": "payments",
                "event_type": "tool_call",
                "tool_name": "add_payee",
                "args_masked": masked,
                "result_masked": masker.mask(f"ok {PLANTED['name']}") if masker else None,
                "env": "test",
                "source": "otel",
                "capture_level": "masked",
            }
        ],
    )
    return {
        "trace": trace,
        "span": span,
        "a": a["decision_id"],
        "b": b["decision_id"],
        "c": c["decision_id"],
    }


EXPORT_HREF = re.compile(r'href="(/console/decisions/exports/[^"]+)"')


def export_href(html_text: str) -> str | None:
    """The one-time download link in the answer of the CSV export action (WP39 review)."""
    m = EXPORT_HREF.search(html_text)
    return html.unescape(m.group(1)) if m else None


class Kit:
    """A TestClient on the real app over a store, with the console context (tests, harness)."""

    def __init__(self, client: Any, runtime: Any, ctx: Any) -> None:
        self.client, self.runtime, self.ctx = client, runtime, ctx

    def get(self, url: str, user: str | None = "reviewer.an", **kw: Any) -> Any:
        headers = dict(kw.pop("headers", {}) or {})
        if user:
            headers["X-Dev-User"] = user
        return self.client.get(url, headers=headers, **kw)

    def post(
        self, url: str, data: Mapping[str, Any] | None = None, user: str = "reviewer.an"
    ) -> Any:
        return self.client.post(
            url, data=dict(data or {}), headers={"X-Dev-User": user, "HX-Request": "true"}
        )


@contextmanager
def kit(data_dir: Path, *, detectors: bool = True, v2: bool = True) -> Iterator[Kit]:
    """Demo replay through the real gateway (four incidents), then a console on that store.
    ``detectors`` and ``v2`` set DETECTORS_ENABLED and CONSOLE_DECISIONS_V2."""
    from fastapi.testclient import TestClient

    from supervisor.adapters.auth import set_provider
    from supervisor.adapters.factory import build_adapters
    from supervisor.app import app
    from supervisor.config import load_settings
    from supervisor.console.context import build_context, set_context
    from supervisor.demo import replay as R
    from supervisor.gateway import wiring as gate_wiring
    from supervisor.jobs import bootstrap_schema
    from supervisor.wiring import build_runtime

    settings = load_settings(
        sql_backend="sqlite",
        data_dir=data_dir,
        llm_base_url="",
        detectors_enabled=detectors,
        console_decisions_v2=v2,
        console_decisions_enabled=True,
        console_traces_enabled=True,
    )
    adapters = build_adapters(settings)
    bootstrap_schema.run(adapters.settings, adapters)
    try:
        report = R.run_gated(adapters.settings, adapters=adapters)
        if not report.ok:
            raise RuntimeError("demo replay failed: " + "; ".join(report.lines[-3:]))
        runtime = build_runtime(adapters.settings, adapters=adapters, policy_refresh_s=0.0)
        ctx = build_context(runtime)
        set_context(ctx)
        gate_wiring.set_gateway(runtime.gateway)
        try:
            yield Kit(TestClient(app, raise_server_exceptions=False), runtime, ctx)
        finally:
            set_context(None)
            gate_wiring.set_gateway(None)
            set_provider(None)
            runtime.close()
    finally:
        adapters.close()


# ------------------------------------------------------------------ demo store (screenshots)


def seed_demo_store(data_dir: Path) -> dict[str, Any]:
    """A store for screenshots and manual checks: the demo replay and planted calls through the
    real gate, 40 more synthetic decisions (statuses, consumers, gaps, a failing detector), the
    decision_daily rollup, the alert job, and three labelled demo alert rows."""
    from supervisor.jobs import alerts as alerts_job
    from supervisor.jobs import decision_rollup
    from supervisor.monitors.common import MonitorContext

    out: dict[str, Any] = {}
    with kit(data_dir) as k:
        ids = plant_calls(k.runtime, k.ctx)
        agents = ("payments", "customer_service", "credit_prequal")
        mix = [
            ("allow", (), (), ()),
            ("allow", (), (), ()),
            ("report", ("injection.ignore_previous",), (), ()),
            ("transform", ("pii.phone", "pii.person"), (), ()),
            ("allow", (), ("content_uninspectable",), ()),
            ("allow", (), (), ("timed_out",)),
            ("block", (), (), ()),
            ("skip", (), ("skipped_by_policy",), ()),
        ]
        for i in range(40):
            status, codes, gaps, ne = mix[i % len(mix)]
            add_decision(
                k.ctx,
                agent=agents[i % 3],
                status=status,
                codes=codes,
                gaps=gaps,
                not_executed=ne,
                consumer=("app-mobile", "app-web", "app-branch")[i % 3],
                direction="output" if i % 5 == 0 else "input",
                corr=f"corr-demo-{i:04d}",
                age_s=60 + i * 900,
                lat=(1200 + (i * 37) % 900, 250 + i % 7 * 20, 300 + i % 11 * 40),
            )
        mctx = MonitorContext.from_adapters(k.runtime.adapters, k.runtime.chain)
        out["rollup"] = decision_rollup.run(mctx, k.ctx.settings, days=3)
        settings = k.ctx.settings.model_copy(update={"alerts_lag_s": 0})
        out["alerts"] = alerts_job.run(mctx, settings)
        now = k.ctx.clock.now()
        for n, (rule, sev, agent) in enumerate(
            [
                ("AL-COVERAGE-GAP", "high", "support-bot"),
                ("AL-DETECTOR-FAILED", "high", "payments"),
                ("AL-LATENCY-DEGRADATION", "medium", None),
            ]
        ):
            k.ctx.state.insert(
                "alert",
                {
                    "alert_id": f"{n + 7:032x}",
                    "ts": now,
                    "dedupe_key": f"{rule}:demo",
                    "rule_id": rule,
                    "rule_hash": "d" * 64,
                    "severity": sev,
                    "status": "open",
                    "title": f"Demo alert {rule} (labelled demo row, not from the engine)",
                    "agent_id": agent,
                    "group_value": agent or "*",
                    "window_s": 900,
                    "window_count": 5,
                    "threshold": 3,
                    "first_ts": now,
                    "last_ts": now,
                    "suppressed_count": n,
                    "refs": ["demo"],
                    "routes": ["inbox"],
                    "route_status": {"inbox": "sent"},
                    "correlation_id": f"corr-demo-{n:04d}",
                },
            )
        out["ids"] = ids
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m supervisor.demo.activity_seed",
        description="Seed a demo store with verdict v2 data (synthetic; for screenshots).",
    )
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args(argv)
    res = seed_demo_store(Path(args.data_dir).resolve())
    rows, alerts = res["rollup"]["rows"], res["alerts"]
    print(f"[OK] seeded {args.data_dir}: rollup {rows} rows, alerts {alerts}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
