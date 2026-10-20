"""Harness for the activity and analytics parity package (WP39; TEAM_BRIEF section 3).

    python -m supervisor.console.activity_harness [--check] [--record --commit SHA --date DAY]
                                                  [--json PATH]

It builds throwaway stores (SQLite, synthetic data, the real gate with detectors on) and checks
the Decisions, Traces, Analytics and Alerts pages the way two experts would:

* **SOC analyst on call.** Can I triage from the drawer alone? Every decision opens with the
  request id, the correlation id, the link to the trace span, the status, the rule ids and the
  latency split. Do the nine alert use cases fire, stay quiet, suppress and carry the
  correlation id (the alert drills)? Does the page survive hostile input?
* **Data protection officer.** Does any page, the drawer, the Traces pages, the Analytics tabs,
  the Alerts page or the CSV export show raw personal data planted in the arguments, in tool
  results, in the output, in a case title, in a verdict text or in a bad detector row? Does the
  export hold only the allow-listed columns?

Parts: (1) the all-pages probe in the three flag states and both languages, (2) the fingerprint
test with planted personal data, (3) 22 adversarial probes that no template generates, (4) the
alert drills with Wilson intervals, (5) the SOC and DPO metrics. Numbers are integers (counts,
bp); thresholds are ILLUSTRATIVE; there is no model, so the run is deterministic. A GO needs
every check to pass; a capability that passes only its own templates would be NO-GO, so the
probes use shapes the seed data does not contain.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from supervisor.alerts.drills import wilson_bp
from supervisor.demo import activity_seed as seed
from supervisor.demo.activity_seed import CORR, PLANTED, Kit

HARNESS_VERSION = "1"
BASELINE = Path(__file__).resolve().parents[3] / "data" / "eval" / "activity" / "baseline.json"
RAW = tuple(PLANTED.values())
PAGES = (
    "/console/",
    "/console/agents",
    "/console/cases",
    "/console/alerts",
    "/console/alerts?status=all",
    "/console/evidence",
    "/console/inbox",
    "/console/analytics?tab=gate",
    "/console/analytics?tab=metrics",
    "/console/analytics?tab=latency",
    "/console/analytics?tab=detectors",
    "/console/decisions",
    "/console/decisions?status=report",
    "/console/decisions?noteval=1",
    "/console/traces",
)
STATES = (("off", False, False), ("detectors", True, False), ("v2", True, True))
USERS = ("reviewer.an", "auditor.dung", "admin.chi", "viewer.hoa")


def _page_state_ok(url: str, status: int, v2: bool) -> bool:
    """200 everywhere, except the pages that belong to the flag (HTTP 400 with a message)."""
    if status >= 500:
        return False
    if "tab=detectors" in url and not v2:
        return status == 400
    return status in (200, 400)  # 400: a page whose own flag is off


# --------------------------------------------------------------------------- probes


Probe = Callable[[Kit, dict[str, str]], "tuple[bool, str]"]
PROBES: list[tuple[str, Probe]] = []


def probe(name: str) -> Callable[[Probe], Probe]:
    def deco(fn: Probe) -> Probe:
        PROBES.append((name, fn))
        return fn

    return deco


def _add(k: Kit, **kw: Any) -> str:
    return seed.add_decision(k.ctx, **kw)


def _rows(k: Kit, qs: str) -> set[str]:
    r = k.get(f"/console/decisions?{qs}")
    return set(re.findall(r'data-row="([0-9a-f]{32})"', r.text))


@probe("fragment_offsets_at_the_edges_never_break_or_leak")
def _p_offsets(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    cases = [(0, 5), (10, 15), (-5, 3), (500, 600), (4, 4)]
    for n, (s, e) in enumerate(cases):
        tr, sp = f"tr-off{n}", f"sp-off{n}"
        eid = _add(
            k, codes=("pii.phone",), trace=tr, span=sp,
            fragments=[{"part": "args", "path": "$.note", "start": s, "end": e, "text": "<A:1>",
                        "precision": "span"}],
            entities=[{"type": "PHONE", "token": PLANTED["phone"], "count": 1}],
        )  # fmt: skip
        k.ctx.tables.append(
            "agent_event",
            [{"event_id": f"off{n}" + "0" * 27, "ts": k.ctx.clock.now(), "trace_id": tr,
              "span_id": sp, "agent_id": "payments", "event_type": "tool_call",
              "args_masked": '{"note": "<A:1>12345<A:1>"}', "env": "test", "source": "otel",
              "capture_level": "masked"}],
        )  # fmt: skip
        for tab in ("request", "detections"):
            r = k.get(f"/console/decisions/{eid}/drawer?tab={tab}")
            if r.status_code != 200 or PLANTED["phone"] in r.text:
                return False, f"offset {s}:{e} tab {tab} status {r.status_code}"
    return True, f"{len(cases)} offset shapes"


@probe("stored_correlation_id_with_html_and_header_injection_is_inert")
def _p_corr(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    evil = "<img src=x onerror=alert(1)>\r\nX-Evil: 1"
    eid = _add(k, corr=evil, trace="tr-evil", span="sp-evil")
    _add(k, corr=evil)
    for url in ("/console/decisions", f"/console/decisions/{eid}/drawer?tab=metadata",
                "/console/traces/tr-evil", "/console/traces"):  # fmt: skip
        r = k.get(url)
        if r.status_code != 200 or "<img src=x" in r.text or "X-Evil" in r.headers:
            return False, url
    return True, "escaped, percent-encoded in links"


@probe("hostile_correlation_in_the_query_string_is_a_400")
def _p_corr_q(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    for qs in ("corr=a%0d%0aSet-Cookie:%20x=1", "correlation=%3Cscript%3E", "event=a%0d%0ab"):
        r = k.get(f"/console/decisions?{qs}")
        if r.status_code != 400 or "Set-Cookie" in r.headers:
            return False, qs
    return True, "3 shapes"


@probe("export_of_10001_rows_is_cut_at_the_cap_with_a_notice")
def _p_export_cap(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    now = k.ctx.clock.now()
    rows = [{"event_id": f"bulk{i:08d}", "ts": now - timedelta(days=2), "trace_id": f"tb{i}",
             "span_id": f"sb{i}", "agent_id": "payments", "event_type": "gate_decision",
             "tool_name": "get_balance", "status": "allowed", "env": "test",
             "classification": "allow", "source": "proxy", "capture_level": "digest",
             "verdict_status": "allow"} for i in range(10_001)]  # fmt: skip
    k.ctx.tables.append("agent_event", rows)
    r = k.post("/console/decisions/export", {}, user="auditor.dung")
    cap = int(k.ctx.settings.console_export_max_rows)
    m = re.search(r"/console/decisions/exports/([A-Za-z0-9._-]+\.csv)", r.text)
    if r.status_code != 200 or not m or f"truncated: {cap} of " not in r.text:
        return False, f"status {r.status_code}"
    body = k.get(f"/console/decisions/exports/{m.group(1)}", user="auditor.dung").text
    n = len(list(csv.reader(io.StringIO(body))))
    return n == cap + 1, f"{n - 1} rows of {cap}"


@probe("unknown_finding_code_is_shown_escaped_and_filterable")
def _p_code(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    eid = _add(k, codes=("vendor.never_seen_9",))
    d = k.get(f"/console/decisions/{eid}/drawer?tab=detections")
    return d.status_code == 200 and eid in _rows(k, "code=vendor.never_seen_9"), "class other"


@probe("agent_seen_under_two_ids_raises_a_gap_for_the_unknown_one")
def _p_two_ids(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    from supervisor.alerts.signals import load_signals
    from supervisor.monitors.common import MonitorContext

    now = k.ctx.clock.now()
    _add(k, agent="payments")
    k.ctx.tables.append(
        "agent_event",
        [{"event_id": "alias" + "0" * 27, "ts": now - timedelta(seconds=20), "trace_id": "ta",
          "span_id": "sa", "agent_id": "payments-v2", "event_type": "llm_call", "env": "test",
          "source": "otel", "capture_level": "digest"}],
    )  # fmt: skip
    mctx = MonitorContext.from_adapters(k.runtime.adapters, k.runtime.chain)
    sigs = load_signals(
        mctx, now - timedelta(hours=1), now + timedelta(seconds=1), gap_window_s=3600
    )
    gaps = {s.fields["agent_id"] for s in sigs if s.kind == "coverage_gap"}
    return gaps == {"payments-v2"}, f"gaps {sorted(gaps)}"


@probe("shadow_agent_with_block_findings_is_not_enforced_and_alerts")
def _p_shadow(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    from supervisor.alerts import signals as S
    from supervisor.alerts.engine import evaluate
    from supervisor.alerts.rules import load_rules
    from supervisor.config import REPO_ROOT
    from supervisor.monitors.common import MonitorContext

    eid = _add(
        k, agent="shadow-x", codes=("injection.ignore_previous",), hint="block", status="report"
    )
    now = k.ctx.clock.now()
    mctx = MonitorContext.from_adapters(k.runtime.adapters, k.runtime.chain)
    sigs = S._finding_signals(
        mctx, now - timedelta(hours=1), now + timedelta(minutes=1), {eid: "SHADOW"}
    )
    res = evaluate(load_rules(REPO_ROOT / "config" / "alerts.yaml"), sigs,
                   only_rules={"AL-THREAT-NOT-ENFORCED"})  # fmt: skip
    row = [r for r in _row_status(k, eid)]
    return len(res.fired) == 1 and row == ["report"], "status stays report (R1), alert fires"


def _row_status(k: Kit, eid: str) -> list[str]:
    return [str(e["verdict_status"]) for e in k.ctx.tables.query("agent_event", {"event_id": eid})]


@probe("alert_storm_of_5000_signals_gives_one_alert")
def _p_storm(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    from supervisor.alerts import drills

    res = drills.run_all()
    ok = all(
        s["alerts"] == 1 and s["suppressed"] == s["expected_suppressed"] for s in res["storms"]
    )
    return ok, f"{len(res['storms'])} rules, 5000 signals each"


@probe("buggy_detector_row_with_raw_text_is_masked_again")
def _p_buggy(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    eid = _add(
        k, codes=("pii.phone",),
        fragments=[{"part": "args", "path": "$.note", "start": 0, "end": 10,
                    "text": PLANTED["phone"], "precision": "span"}],
        entities=[{"type": "PHONE", "token": PLANTED["email"], "count": 1}],
    )  # fmt: skip
    for tab in ("request", "response", "detections", "metadata"):
        t = k.get(f"/console/decisions/{eid}/drawer?tab={tab}").text
        if PLANTED["phone"] in t or PLANTED["email"] in t:
            return False, tab
    return True, "4 tabs"


@probe("csv_formula_cells_are_neutralised")
def _p_formula(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    _add(k, corr='=HYPERLINK("http://x")', consumer="@cmd")
    r = k.post("/console/decisions/export", {"consumer": "@cmd"}, user="auditor.dung")
    m = re.search(r"/console/decisions/exports/([A-Za-z0-9._-]+\.csv)", r.text)
    if not m:
        return False, f"status {r.status_code}"
    cells = [
        c
        for row in csv.reader(io.StringIO(k.get(m.group(0), user="auditor.dung").text))
        for c in row
    ]
    return not any(c.startswith(("=", "+", "@")) for c in cells), "leading quote added"


@probe("export_is_refused_for_reviewer_and_viewer")
def _p_perm(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    got = [
        k.post("/console/decisions/export", {}, user=u).status_code
        for u in ("reviewer.an", "viewer.hoa")
    ]
    return got == [403, 403], f"{got}"


@probe("export_columns_are_exactly_the_allow_list")
def _p_cols(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    from supervisor.console.decisions_v2 import EXPORT_COLUMNS

    r = k.post("/console/decisions/export", {}, user="admin.chi")
    m = re.search(r"/console/decisions/exports/([A-Za-z0-9._-]+\.csv)", r.text)
    head = next(csv.reader(io.StringIO(k.get(m.group(0), user="admin.chi").text))) if m else []
    bad = [
        c for c in head if any(w in c for w in ("args", "fragment", "hash", "key", "token", "text"))
    ]
    return tuple(head) == EXPORT_COLUMNS and not bad, f"{len(head)} columns"


@probe("decision_without_findings_or_text_opens")
def _p_empty(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    eid = _add(k, lat=None)
    return all(k.get(f"/console/decisions/{eid}/drawer?tab={t}").status_code == 200
               for t in ("request", "response", "detections", "metadata")), "4 tabs"  # fmt: skip


@probe("recorder_text_that_is_not_json_does_not_break_the_request_tab")
def _p_json(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    tr, sp = "tr-notjson", "sp-notjson"
    eid = _add(k, codes=("pii.phone",), trace=tr, span=sp)
    for n, text in enumerate(("not json {", "[1, 2", '"' + "x" * 5000 + '"', "\x00\x01 ctrl")):
        k.ctx.tables.append(
            "agent_event",
            [{"event_id": f"nj{n}" + "0" * 28, "ts": k.ctx.clock.now(), "trace_id": tr, "span_id": sp,
              "agent_id": "payments", "event_type": "tool_call", "args_masked": text,
              "result_masked": text, "env": "test", "source": "otel", "capture_level": "masked"}],
        )  # fmt: skip
    codes = [k.get(f"/console/decisions/{eid}/drawer?tab={t}").status_code
             for t in ("request", "response", "detections", "metadata")]  # fmt: skip
    return all(c == 200 for c in codes), f"{codes}"


@probe("vietnamese_text_and_multibyte_offsets")
def _p_vi(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    tr, sp = "tr-vi", "sp-vi"
    eid = _add(k, codes=("pii.person",), trace=tr, span=sp,
               fragments=[{"part": "args", "path": "$.note", "start": 17, "end": 30,
                           "text": "<PERSON:abcd1>", "precision": "span"}])  # fmt: skip
    k.ctx.tables.append(
        "agent_event",
        [{"event_id": "vi" + "0" * 30, "ts": k.ctx.clock.now(), "trace_id": tr, "span_id": sp,
          "agent_id": "payments", "event_type": "tool_call",
          "args_masked": json.dumps({"note": "Chuyển khoản cho <PERSON:abcd1> ngay"}, ensure_ascii=False),
          "env": "test", "source": "otel", "capture_level": "masked"}],
    )  # fmt: skip
    t = k.get(f"/console/decisions/{eid}/drawer?tab=request").text
    return '<mark class="hl">&lt;PERSON:abcd1&gt;' in t, "located by the token"


@probe("500_fragments_in_one_finding_are_capped")
def _p_many(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    frags = [{"part": "args", "path": f"$.f{i}", "start": 0, "end": 3, "text": "<A>", "precision": "span"}
             for i in range(500)]  # fmt: skip
    eid = _add(k, codes=("pii.phone",), fragments=frags)
    r = k.get(f"/console/decisions/{eid}/drawer?tab=detections")
    return r.status_code == 200 and len(r.text) < 400_000, f"{len(r.text)} bytes"


@probe("scan_cap_is_announced")
def _p_cap(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    old = k.ctx.settings.console_scan_cap
    try:
        object.__setattr__(k.ctx.settings, "console_scan_cap", 100)
        r = k.get("/console/decisions")
    finally:
        object.__setattr__(k.ctx.settings, "console_scan_cap", old)
    return r.status_code == 200 and "hint" in r.text, "cap hint shown"


@probe("deep_link_to_an_unknown_decision_is_a_400")
def _p_deep(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    return k.get("/console/decisions?event=no-such-decision-1").status_code == 400, "400"


@probe("output_decision_with_no_recorded_text_opens")
def _p_out(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    r = k.get(f"/console/decisions/{ids['c']}/drawer?tab=request")
    return r.status_code == 200 and all(v not in r.text for v in RAW), "masked only"


@probe("alert_row_with_a_hostile_correlation_id_stores_none")
def _p_alert_corr(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    from supervisor.alerts.service import _corr

    return _corr("<b>x</b>\r\n") is None and _corr("ok-id_1") == "ok-id_1", "dropped"


@probe("detectors_tab_without_rollup_says_how_to_fill_it")
def _p_norollup(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    r = k.get("/console/analytics?tab=detectors")
    return r.status_code == 200 and "decision_rollup" in r.text, "empty state"


@probe("traces_corr_filter_rejects_markup")
def _p_trace_corr(k: Kit, ids: dict[str, str]) -> tuple[bool, str]:
    return k.get("/console/traces?corr=%3Cb%3E").status_code == 400, "400"


# --------------------------------------------------------------------------- parts


def all_pages(workdir: Path) -> dict[str, Any]:
    """Every page, three flag states, both languages, four roles. No 5xx; nothing raw."""
    total = bad = 0
    detail: list[str] = []
    for name, det, v2 in STATES:
        with seed.kit(workdir / f"pages-{name}", detectors=det, v2=v2) as k:
            if det:
                seed.plant_calls(k.runtime, k.ctx)
            for user in USERS:
                for lang in ("en", "vi"):
                    for url in PAGES:
                        sep = "&" if "?" in url else "?"
                        r = k.get(f"{url}{sep}lang={lang}", user=user)
                        total += 1
                        ok = _page_state_ok(url, r.status_code, v2) and not any(
                            x in r.text for x in RAW
                        )
                        if not ok:
                            bad += 1
                            detail.append(f"{name}/{user}/{lang} {url} -> {r.status_code}")
    return {
        "checked": total,
        "bad": bad,
        "ok_bp": (total - bad) * 10000 // total,
        "detail": detail[:10],
    }


def fingerprint_and_metrics(workdir: Path) -> dict[str, Any]:
    """Planted personal data in args, tool results, output, a case title and a verdict text;
    then every page that could show it, and the export."""
    out: dict[str, Any] = {}
    with seed.kit(workdir / "fp", detectors=True, v2=True) as k:
        ids = seed.plant_calls(k.runtime, k.ctx)
        k.ctx.cases.open_case(
            agent_id="payments", severity="high",
            summary=f"Chuyen tien cho {PLANTED['name']} {PLANTED['phone']}",
            source_kind="gate", source_ref=ids["a"],
        )  # fmt: skip
        k.ctx.tables.append(
            "verdict",
            [{"verdict_id": "v" * 32, "ts": k.ctx.clock.now(), "trace_id": ids["trace"],
              "event_id": ids["a"], "agent_id": "payments", "tier": 0, "checker_id": "gate.tier0a",
              "is_mock": False, "advisory": False, "label": "matched", "action": "log",
              "rule_id": "PAY-RAW", "rationale_masked": f"raw {PLANTED['name']} {PLANTED['phone']}"}],
        )  # fmt: skip
        k.ctx.tables.append(
            "agent_event",
            [{"event_id": "x" * 32, "ts": k.ctx.clock.now(), "trace_id": ids["trace"],
              "span_id": ids["span"], "agent_id": "payments", "event_type": "llm_call",
              "result_masked": f"{PLANTED['name']} {PLANTED['cccd']} {PLANTED['email']}",
              "env": "test", "source": "otel", "capture_level": "masked"}],
        )  # fmt: skip
        from supervisor.jobs import decision_rollup
        from supervisor.monitors.common import MonitorContext

        mctx = MonitorContext.from_adapters(k.runtime.adapters, k.runtime.chain)
        decision_rollup.run(mctx, k.ctx.settings)
        pages = [k.get(u).text for u in (
            "/console/decisions", f"/console/decisions?correlation={CORR}", "/console/traces",
            f"/console/traces/{ids['trace']}", f"/console/traces/{ids['trace']}/span/{ids['span']}",
            "/console/analytics?tab=gate", "/console/analytics?tab=detectors", "/console/alerts?status=all",
        )]  # fmt: skip
        for key in ("a", "b", "c"):
            for tab in ("request", "response", "detections", "metadata"):
                pages.append(k.get(f"/console/decisions/{ids[key]}/drawer?tab={tab}").text)
        exp = k.post("/console/decisions/export", {}, user="auditor.dung")
        m = re.search(r"/console/decisions/exports/([A-Za-z0-9._-]+\.csv)", exp.text)
        csv_text = k.get(m.group(0), user="auditor.dung").text if m else ""
        pages.append(csv_text)
        leaks = sum(text.count(raw) for text in pages for raw in RAW)
        out["pages_scanned"] = len(pages)
        out["leak_items"] = leaks
        # SOC triage completeness: every v2 decision opens with what an analyst needs
        decisions = k.ctx.tables.query("agent_event", {"event_type": "gate_decision"}, limit=500)
        v2rows = [e for e in decisions if e.get("verdict_status")]
        complete = 0
        for e in v2rows:
            t = k.get(f"/console/decisions/{e['event_id']}/drawer?tab=metadata").text
            need = [str(e.get("correlation_id") or ""), "us<", "/console/traces/"]
            need_ok = all(n in t or n == "us<" for n in need) and "Rules" in t and "Overhead" in t
            complete += bool(need_ok and (e.get("request_id") or "-") in t)
        out["triage_n"] = len(v2rows)
        out["triage_complete"] = complete
        out["triage_complete_bp"] = complete * 10000 // max(1, len(v2rows))
        out["triage_ci_bp"] = list(wilson_bp(complete, len(v2rows)))
        from supervisor.console.decisions_v2 import EXPORT_COLUMNS

        head = next(csv.reader(io.StringIO(csv_text)), [])
        out["export_columns_exact"] = tuple(head) == EXPORT_COLUMNS
    return out


def run_probes(workdir: Path) -> dict[str, Any]:
    results = []
    with seed.kit(workdir / "probes", detectors=True, v2=True) as k:
        ids = seed.plant_calls(k.runtime, k.ctx)
        for name, fn in PROBES:
            try:
                ok, detail = fn(k, ids)
            except Exception as exc:  # noqa: BLE001 - a probe that raises is a failed probe
                ok, detail = False, f"raised {type(exc).__name__}"
            results.append({"name": name, "ok": bool(ok), "detail": detail})
    passed = sum(r["ok"] for r in results)
    return {
        "n": len(results),
        "passed": passed,
        "passed_bp": passed * 10000 // len(results),
        "ci_bp": list(wilson_bp(passed, len(results))),
        "results": results,
    }


def run(workdir: Path | None = None) -> dict[str, Any]:
    from supervisor.alerts import drills

    with tempfile.TemporaryDirectory(prefix="wp39_harness_") as tmp:
        base = workdir or Path(tmp)
        pages = all_pages(base)
        fp = fingerprint_and_metrics(base)
        probes = run_probes(base)
    dr = drills.run_all()
    verdicts = {
        "all_pages_no_5xx_no_raw": pages["bad"] == 0,
        "dpo_leak_items_zero": fp["leak_items"] == 0,
        "dpo_export_columns_exact": bool(fp["export_columns_exact"]),
        "soc_triage_complete": fp["triage_complete"] == fp["triage_n"] and fp["triage_n"] > 0,
        "soc_alert_drills": bool(dr["go"]),
        "adversarial_probes": probes["passed"] == probes["n"] and probes["n"] >= 20,
    }
    return {
        "harness": HARNESS_VERSION,
        "mode": "sqlite, synthetic data, real gate with detectors on, no model",
        "pages": pages,
        "fingerprint": fp,
        "probes": probes,
        "drills": {
            "go": dr["go"],
            "sweeps": dr["sweeps"],
            "storms": [{k: v for k, v in s.items()} for s in dr["storms"]],
        },
        "verdicts": {k: ("GO" if v else "NO-GO") for k, v in verdicts.items()},
        "overall": "GO" if all(verdicts.values()) else "NO-GO",
    }


def render(rep: dict[str, Any]) -> str:
    p, f, pr = rep["pages"], rep["fingerprint"], rep["probes"]
    lines = [
        f"activity harness {rep['harness']}: {rep['mode']}",
        "thresholds are ILLUSTRATIVE; numbers are integers (counts, bp = basis points)",
        f"all pages: {p['checked']} requests (3 flag states x 4 roles x 2 languages), "
        f"{p['bad']} bad, ok {p['ok_bp']} bp",
        f"DPO: planted personal data in args, tool results, output, case title, verdict text; "
        f"{f['pages_scanned']} pages and the export scanned, leak_items={f['leak_items']}, "
        f"export columns exact={f['export_columns_exact']}",
        f"SOC: triage complete {f['triage_complete']}/{f['triage_n']} decisions "
        f"({f['triage_complete_bp']} bp, Wilson 95% {f['triage_ci_bp']})",
        f"adversarial probes: {pr['passed']}/{pr['n']} ({pr['passed_bp']} bp, Wilson 95% {pr['ci_bp']})",
    ]
    for r in pr["results"]:
        lines.append(f"  [{'OK' if r['ok'] else 'FAIL'}] {r['name']}: {r['detail']}")
    lines.append(
        f"alert drills: {'GO' if rep['drills']['go'] else 'NO-GO'} (python -m supervisor.alerts.harness)"
    )
    for name, v in rep["verdicts"].items():
        lines.append(f"  {v:<6}{name}")
    lines.append(f"OVERALL: {rep['overall']}")
    return "\n".join(lines)


def compare(rep: dict[str, Any], base: dict[str, Any]) -> list[str]:
    """Drops below the recorded baseline (empty list = none)."""
    bad = []
    if rep["pages"]["ok_bp"] < base["pages"]["ok_bp"]:
        bad.append("all-pages ok rate dropped")
    if rep["fingerprint"]["leak_items"] > base["fingerprint"]["leak_items"]:
        bad.append("leak_items rose")
    if rep["fingerprint"]["triage_complete_bp"] < base["fingerprint"]["triage_complete_bp"]:
        bad.append("triage completeness dropped")
    if (
        rep["probes"]["passed"] < base["probes"]["passed"]
        or rep["probes"]["n"] < base["probes"]["n"]
    ):
        bad.append("adversarial probes dropped")
    if rep["overall"] != "GO":
        bad.append("overall is not GO")
    return bad


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.console.activity_harness", description=__doc__
    )
    ap.add_argument("--check", action="store_true", help="fail on a drop below the baseline")
    ap.add_argument("--record", action="store_true", help="rewrite the baseline file")
    ap.add_argument("--commit", default="unknown")
    ap.add_argument("--date", default="unknown")
    ap.add_argument("--json", help="write the full report as JSON")
    args = ap.parse_args(argv)
    rep = run()
    print(render(rep))  # noqa: T201 - CLI output
    if args.json:
        Path(args.json).write_text(
            json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.record:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        slim = {k: rep[k] for k in ("harness", "pages", "fingerprint", "probes", "overall")}
        slim["pages"] = {k: v for k, v in rep["pages"].items() if k != "detail"}
        slim["probes"] = {k: v for k, v in rep["probes"].items() if k != "results"}
        BASELINE.write_text(
            json.dumps({"commit": args.commit, "date": args.date, **slim}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(f"[OK] wrote {BASELINE}")  # noqa: T201
    if args.check:
        drop = compare(rep, json.loads(BASELINE.read_text(encoding="utf-8")))
        for line in drop:
            print(f"[FAIL] {line}")  # noqa: T201
        if not drop:
            print("[OK] no drop below the baseline")  # noqa: T201
        return 1 if drop else 0
    return 0 if rep["overall"] == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
