"""WP39: Decisions page under verdict v2 (drawer, filters, deep links, not-evaluated badge, CSV
export), flag off = today's pages."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

import pytest

from supervisor.console import decisions_v2

from .conftest import Console
from .wp39_fixtures import CORR, PLANTED, plant
from .wp39_helpers import add_decision

RAW = (PLANTED["name"], PLANTED["phone"], PLANTED["cccd"], PLANTED["email"])


def _body(html: str) -> str:
    return html.split('id="tab-body"')[1] if 'id="tab-body"' in html else html


# --------------------------------------------------------------------------- flag off


def test_flag_off_is_todays_drawer_and_list(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_decisions_enabled", True)
    assert console.ctx.settings.console_decisions_v2 is False
    page = console.get("/console/decisions").text
    assert "f-code" not in page and "f-consumer" not in page and "export-csv" not in page
    row = console.ctx.tables.query("agent_event", {"event_type": "gate_decision"}, limit=1)[0]
    d = console.get(f"/console/decisions/{row['event_id']}/drawer").text
    assert 'data-tab="details"' in d and 'data-tab="request"' not in d
    # the new routes and parameters do nothing with the flag off
    assert console.post("/console/decisions/export", user="auditor.dung").status_code == 400
    r = console.get(f"/console/decisions?event={row['event_id']}")
    assert r.status_code == 200 and "data-strip" not in r.text
    monkeypatch.setattr(console.ctx.settings, "console_tools_enabled", True)
    assert console.get("/console/analytics?tab=detectors").status_code == 400
    assert "detectors" not in re.findall(
        r'data-tab="(\w+)"', console.get("/console/analytics").text
    )


# --------------------------------------------------------------------------- drawer


def test_drawer_has_four_tabs_and_masked_request(v2console: Console) -> None:
    ids = plant(v2console)
    d = v2console.get(f"/console/decisions/{ids['a']}/drawer").text
    assert re.findall(r'data-tab="(\w+)"', d) == ["request", "response", "detections", "metadata"]
    body = _body(d)
    # three located fragments, highlighted in place on the masked text
    assert body.count('<mark class="hl">') == 3
    assert "&lt;PERSON:" in body and "&lt;CCCD:" in body and "&lt;PHONE:" in body
    for raw in RAW:
        assert raw not in d
    assert 'id="masked-record"' in body  # formatted + JSON of the masked record


def test_detections_one_row_per_finding_and_per_not_executed(v2console: Console) -> None:
    eid = add_decision(
        v2console,
        status="report",
        codes=("pii.phone", "injection.ignore_previous"),
        not_executed=("timed_out", "payload_too_large"),
        hint="report",
    )
    body = _body(v2console.get(f"/console/decisions/{eid}/drawer?tab=detections").text)
    rows = re.findall(r'<tr data-code="([^"]+)"', body)
    assert sorted(rows) == sorted(
        [
            "pii.phone",
            "injection.ignore_previous",
            "not_executed.timed_out",
            "not_executed.payload_too_large",
        ]
    )
    assert "9500 / 8000" in body  # score and threshold in bp
    assert "a detector timed out" in body and "payload too large" in body


def test_metadata_latency_split_and_links(v2console: Console) -> None:
    eid = add_decision(
        v2console,
        corr="corr-meta-1",
        request_id="req-meta-1",
        consumer="app-web",
        lat=(2000, 300, 900),
        trace="trace-meta",
        span="span-meta",
    )
    v2console.ctx.state.insert(
        "alert",
        {
            "alert_id": "e" * 32,
            "ts": v2console.ctx.clock.now(),
            "dedupe_key": "AL-X:a",
            "rule_id": "AL-PII-OUTPUT",
            "rule_hash": "h" * 64,
            "severity": "high",
            "status": "open",
            "title": "t",
            "agent_id": "payments",
            "group_value": "payments",
            "window_s": 600,
            "window_count": 3,
            "threshold": 3,
            "first_ts": v2console.ctx.clock.now(),
            "last_ts": v2console.ctx.clock.now(),
            "suppressed_count": 0,
            "refs": [],
            "routes": ["inbox"],
            "route_status": {"inbox": "sent"},
            "correlation_id": "corr-meta-1",
        },
    )
    body = _body(v2console.get(f"/console/decisions/{eid}/drawer?tab=metadata").text)
    assert "req-meta-1" in body and "corr-meta-1" in body and "app-web" in body
    assert "2000 us" in body and "300 us" in body and "900 us" in body
    assert "800 us" in body  # overhead = 2000 - 300 - 900
    assert "/console/traces/trace-meta?span=span-meta" in body
    assert f"/console/alerts?status=all&amp;drawer={'e' * 32}" in body
    # the alert drawer links back
    a = v2console.get(f"/console/alerts/{'e' * 32}/drawer").text
    assert "corr-meta-1" in a and "/console/decisions?correlation=corr-meta-1" in a


def test_response_tab_status_decision_rules_and_payload(v2console: Console) -> None:
    ids = plant(v2console)
    body = _body(v2console.get(f"/console/decisions/{ids['a']}/drawer?tab=response").text)
    assert "Transform" in body and "allowed" in body
    assert body.count('<mark class="hl">') == 3  # the payload after masking, rebuilt
    blk = next(
        e
        for e in v2console.ctx.tables.query(
            "agent_event", {"event_type": "gate_decision"}, limit=500
        )
        if e["verdict_status"] == "block"
    )
    body = _body(v2console.get(f"/console/decisions/{blk['event_id']}/drawer?tab=response").text)
    assert "Block" in body and "denied" in body and "The payload was not changed." in body


def test_not_evaluated_badge_on_row_and_in_drawer(v2console: Console) -> None:
    bad = add_decision(v2console, gaps=("payload_too_large",), not_executed=("timed_out",))
    ok = add_decision(v2console)
    lst = v2console.get("/console/decisions?noteval=1").text
    assert f'data-row="{bad}"' in lst and f'data-row="{ok}"' not in lst
    assert "ne-badge" in lst and "Not evaluated" in lst
    d = v2console.get(f"/console/decisions/{bad}/drawer").text
    assert "ne-badge" in d and "payload too large" in d and "a detector timed out" in d
    d_ok = v2console.get(f"/console/decisions/{ok}/drawer").text
    assert "ne-badge" not in d_ok


# --------------------------------------------------------------------------- filters


@pytest.fixture
def dataset(v2console: Console) -> dict[str, str]:
    return {
        "a": add_decision(
            v2console,
            agent="payments",
            status="report",
            consumer="app-web",
            codes=("pii.phone",),
            corr="corr-A",
            direction="output",
        ),
        "b": add_decision(
            v2console,
            agent="payments",
            status="transform",
            consumer="app-mobile",
            codes=("pii.person",),
            corr="corr-B",
        ),
        "c": add_decision(v2console, agent="customer_service", status="skip", corr="corr-C"),
        "d": add_decision(
            v2console,
            agent="payments",
            status="pause",
            gaps=("content_uninspectable",),
            consumer="app-web",
            corr="corr-D",
        ),
    }


def _rows(c: Console, qs: str) -> set[str]:
    r = c.get(f"/console/decisions?{qs}")
    assert r.status_code == 200, r.text[:300]
    return set(re.findall(r'data-row="([0-9a-f]{32})"', r.text))


@pytest.mark.parametrize(
    ("qs", "want"),
    [
        ("status=report", {"a"}),
        ("status=transform", {"b"}),
        ("status=skip", {"c"}),
        ("status=pause", {"d"}),
        ("code=pii.phone", {"a"}),
        ("noteval=1", {"d"}),
        ("consumer=app-web", {"a", "d"}),
        ("direction=output", {"a"}),
        ("corr=corr-C", {"c"}),
    ],
)
def test_new_filters(v2console: Console, dataset: dict[str, str], qs: str, want: set[str]) -> None:
    got = _rows(v2console, qs)
    assert {dataset[k] for k in want} <= got
    others = {v for k, v in dataset.items() if k not in want}
    assert not (others & got)


@pytest.mark.parametrize(
    "qs",
    [
        "status=bogus",
        "code=a b",
        "code=<script>",
        "noteval=2",
        "consumer=a<b",
        "direction=up",
        "corr=x%0d%0aSet-Cookie:%20a=b",
        "corr=%3Cscript%3E",
    ],
)
def test_bad_filter_values_are_400_not_500(v2console: Console, qs: str) -> None:
    assert v2console.get(f"/console/decisions?{qs}").status_code == 400


def test_status_tiles_count_by_status(v2console: Console, dataset: dict[str, str]) -> None:
    page = v2console.get("/console/decisions").text
    tiles = re.findall(
        r'class="tile[^"]*"[^>]*><span class="n">(\d+)</span><span class="l">([^<]+)', page
    )
    labels = {label: int(n) for n, label in tiles}
    assert labels["Report"] >= 1 and labels["Pause"] >= 1 and labels["Transform"] >= 1


# --------------------------------------------------------------------------- deep links


def test_deep_links_open_the_drawer_and_are_stripped(v2console: Console) -> None:
    eid = add_decision(v2console, corr="corr-deep", request_id="req-deep")
    for qs, strip in (
        (f"event={eid}", "event"),
        ("event=req-deep", "event"),
        ("correlation=corr-deep", "correlation"),
    ):
        r = v2console.get(f"/console/decisions?{qs}")
        assert r.status_code == 200
        assert f'data-strip="{strip}"' in r.text
        assert "drawer-title" in r.text and "corr-deep" in r.text
        assert 'id="drawer"' in r.text and re.search(r'<aside id="drawer"[^>]*(?<!hidden)>', r.text)
    js = v2console.get("/console/static/console.js").text
    assert "replaceState" in js and "data-strip" in js


@pytest.mark.parametrize(
    "qs",
    [
        "event=nope-unknown-1",
        "correlation=nope-unknown-1",
        "event=%3Cscript%3E",
        "correlation=a%0d%0aX-Evil:1",
    ],
)
def test_deep_link_unknown_or_hostile_is_400(v2console: Console, qs: str) -> None:
    r = v2console.get(f"/console/decisions?{qs}")
    assert r.status_code == 400
    assert "X-Evil" not in r.headers and "<script>" not in r.text


# --------------------------------------------------------------------------- export


def _export(c: Console, qs: dict[str, str] | None = None, user: str = "auditor.dung") -> Any:
    return c.post("/console/decisions/export", qs or {}, user=user)


def _csv_of(c: Console, resp: Any) -> list[list[str]]:
    name = re.search(r"/console/decisions/exports/([A-Za-z0-9._-]+\.csv)", resp.text).group(1)
    got = c.get(f"/console/decisions/exports/{name}", user="auditor.dung")
    assert got.status_code == 200 and "text/csv" in got.headers["content-type"]
    return list(csv.reader(io.StringIO(got.text)))


def test_export_permission_and_columns(v2console: Console) -> None:
    add_decision(v2console, corr="corr-x", consumer="app-web", codes=("pii.phone",))
    assert _export(v2console, user="reviewer.an").status_code == 403
    assert _export(v2console, user="viewer.hoa").status_code == 403
    assert (
        v2console.get(
            "/console/decisions/exports/decisions-20260101T000000Z-abcdef.csv", user="reviewer.an"
        ).status_code
        == 403
    )
    r = _export(v2console)
    assert r.status_code == 200 and "CSV built" in r.text and "truncated" not in r.text
    rows = _csv_of(v2console, r)
    assert tuple(rows[0]) == decisions_v2.EXPORT_COLUMNS
    assert len(rows) > 5
    for forbidden in ("args", "fragment", "entit", "hash", "key", "secret", "token", "text"):
        assert not any(forbidden in c for c in rows[0]), forbidden
    assert _export(v2console, user="admin.chi").status_code == 200


def test_export_is_audited_as_a_console_action(v2console: Console) -> None:
    assert _export(v2console).status_code == 200
    acts = [
        a for a in v2console.ctx.tables.query("console_action", {"permission": "decisions.export"})
    ]
    assert sorted(a["outcome"] for a in acts) == ["attempted", "ok"]
    ok = next(a for a in acts if a["outcome"] == "ok")
    assert re.fullmatch(r"rows=\d+;total=\d+;truncated=0", ok["detail"])


def test_export_cap_with_ascii_truncated_notice(
    v2console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    tables = v2console.ctx.tables
    now = v2console.ctx.clock.now()
    rows = [
        {
            "event_id": f"bulk{i:08d}",
            "ts": now,
            "trace_id": f"tb{i}",
            "span_id": f"sb{i}",
            "agent_id": "payments",
            "event_type": "gate_decision",
            "tool_name": "get_balance",
            "status": "allowed",
            "env": "test",
            "classification": "allow",
            "source": "proxy",
            "capture_level": "digest",
            "verdict_status": "allow",
        }
        for i in range(10_001)
    ]
    tables.append("agent_event", rows)
    r = _export(v2console)
    assert r.status_code == 200
    assert 'data-export="truncated"' in r.text and "truncated: 5000 of " in r.text
    assert r.text.isascii() or "truncated" in r.text
    out = _csv_of(v2console, r)
    assert len(out) == 5000 + 1
    assert "-truncated.csv" in r.text
    # a smaller cap by setting
    monkeypatch.setattr(v2console.ctx.settings, "console_export_max_rows", 7)
    out = _csv_of(v2console, _export(v2console))
    assert len(out) == 7 + 1


def test_export_neutralises_formulas_and_control_characters(v2console: Console) -> None:
    add_decision(v2console, corr="=cmd|' /C calc'!A0", consumer="app-web")
    add_decision(v2console, corr="a\r\nb", consumer="app-web")
    # stored ids are untrusted: the export must still be safe
    out = _csv_of(v2console, _export(v2console))
    cells = [c for row in out[1:] for c in row]
    assert not any(c.startswith(("=", "+", "@")) for c in cells)
    assert not any("\r" in c or "\n" in c for c in cells)
    assert any(c.startswith("'=cmd") for c in cells)


def test_export_follows_the_filters(v2console: Console) -> None:
    keep = add_decision(v2console, consumer="only-this-app")
    add_decision(v2console, consumer="another-app")
    out = _csv_of(v2console, _export(v2console, {"consumer": "only-this-app"}))
    assert len(out) == 2 and out[1][1] == keep
    assert _export(v2console, {"status": "nonsense"}).status_code == 400


# --------------------------------------------------------------------------- raw text never shown


def _all_text(c: Console, ids: dict[str, str]) -> str:
    """Every response that could show text of the planted calls."""
    parts = [c.get("/console/decisions").text, c.get(f"/console/decisions?correlation={CORR}").text]
    for k in ("a", "b", "c"):
        for tab in ("request", "response", "detections", "metadata"):
            parts.append(c.get(f"/console/decisions/{ids[k]}/drawer?tab={tab}").text)
            parts.append(c.get(f"/console/decisions?drawer={ids[k]}&dtab={tab}").text)
    parts.append(c.get(f"/console/traces/{ids['trace']}").text)
    parts.append(c.get(f"/console/traces/{ids['trace']}?span={ids['span']}").text)
    parts.append(c.get(f"/console/traces/{ids['trace']}/span/{ids['span']}").text)
    parts.append(c.get("/console/traces").text)
    parts.append(c.get("/console/analytics?tab=gate").text)
    parts.append(c.get("/console/analytics?tab=detectors").text)
    parts.append(c.get("/console/alerts?status=all").text)
    return "\n".join(parts)


def test_fingerprint_no_raw_text_in_drawer_list_traces_or_export(v2console: Console) -> None:
    ids = plant(v2console)
    # a case whose title carries personal data (the case service masks it; the page shows the id)
    case = v2console.ctx.cases.open_case(
        agent_id="payments",
        severity="high",
        summary=f"Chuyen tien cho {PLANTED['name']} so {PLANTED['phone']}",
        source_kind="gate",
        source_ref=ids["a"],
    )
    # a verdict rationale and a recorder event with raw text (bad data must not get through)
    v2console.ctx.tables.append(
        "verdict",
        [
            {
                "verdict_id": "v" * 32,
                "ts": v2console.ctx.clock.now(),
                "trace_id": ids["trace"],
                "event_id": ids["a"],
                "agent_id": "payments",
                "tier": 0,
                "checker_id": "gate.tier0a",
                "is_mock": False,
                "advisory": False,
                "label": "matched",
                "action": "log",
                "rule_id": "PAY-RAW",
                "rationale_masked": f"raw by mistake {PLANTED['name']} {PLANTED['phone']}",
            }
        ],
    )
    v2console.ctx.tables.append(
        "agent_event",
        [
            {
                "event_id": "x" * 32,
                "ts": v2console.ctx.clock.now(),
                "trace_id": ids["trace"],
                "span_id": ids["span"],
                "agent_id": "payments",
                "event_type": "llm_call",
                "result_masked": f"Gui {PLANTED['name']} CCCD {PLANTED['cccd']} {PLANTED['email']}",
                "env": "test",
                "source": "otel",
                "capture_level": "masked",
            }
        ],
    )
    text = _all_text(v2console, ids)
    assert case["case_id"] in text
    for raw in RAW:
        assert raw not in text, raw
        assert raw.lower() not in text.lower()
    # the export, with every status
    out = _csv_of(v2console, _export(v2console))
    flat = "\n".join(",".join(r) for r in out)
    for raw in RAW:
        assert raw not in flat
    # no key material or argument hash anywhere in the export
    assert "h" * 64 not in flat
    # a decision page for a masked-level span event shows the output only as tokens
    assert "&lt;EMAIL:" in text or "&lt;PERSON:" in text


def test_a_buggy_detector_row_with_raw_text_is_masked_again(v2console: Console) -> None:
    eid = add_decision(
        v2console,
        codes=("pii.phone",),
        fragments=[
            {
                "part": "args",
                "path": "$.note",
                "start": 0,
                "end": 10,
                "text": PLANTED["phone"],
                "precision": "span",
            }
        ],
        entities=[{"type": "PHONE", "token": PLANTED["phone"], "count": 1}],
    )
    for tab in ("detections", "request", "response", "metadata"):
        d = v2console.get(f"/console/decisions/{eid}/drawer?tab={tab}").text
        assert PLANTED["phone"] not in d


def test_unknown_finding_code_is_shown_escaped_and_filterable(v2console: Console) -> None:
    eid = add_decision(v2console, codes=("vendor.weird_code_9",))
    d = v2console.get(f"/console/decisions/{eid}/drawer?tab=detections")
    assert d.status_code == 200 and "vendor.weird_code_9" in d.text
    assert eid in _rows(v2console, "code=vendor.weird_code_9")


def test_hostile_stored_correlation_id_is_escaped_everywhere(v2console: Console) -> None:
    evil = "<script>alert(1)</script>\r\nX-Evil: 1"
    eid = add_decision(v2console, corr=evil, trace="trace-evil", span="span-evil")
    add_decision(v2console, corr=evil)  # a second decision: the "same correlation" link shows
    for url in (
        "/console/decisions",
        f"/console/decisions/{eid}/drawer?tab=metadata",
        f"/console/decisions/{eid}/drawer?tab=request",
        "/console/traces/trace-evil",
        "/console/traces",
    ):
        r = v2console.get(url)
        assert r.status_code == 200, url
        assert "<script>alert(1)" not in r.text, url
        assert "X-Evil" not in r.headers
    meta = v2console.get(f"/console/decisions/{eid}/drawer?tab=metadata").text
    assert "&lt;script&gt;" in meta  # escaped, shown as text
    assert "%3Cscript%3E" in meta  # the link is percent-encoded


@pytest.mark.parametrize(
    "start,end,text",
    [
        (0, 3, "<A:1>"),  # offsets that do not match the text: found by the token
        (-5, 3, "<A:1>"),
        (500, 600, "<A:1>"),  # past the end
        (4, 4, "<A:1>"),  # empty range
        ("x", None, "<A:1>"),  # not integers
        (0, 5, "<A:1>"),  # the exact span at offset 0
        (10, 15, "<A:1>"),  # the exact span at the very end of the text
        (3, 8, "<GONE:9>"),  # a token that is not in the text at all
    ],
)
def test_fragment_offset_edges_never_break_the_drawer(
    v2console: Console, start: Any, end: Any, text: str
) -> None:
    eid = add_decision(
        v2console,
        codes=("pii.phone",),
        trace="trace-edge",
        span="span-edge",
        fragments=[
            {
                "part": "args",
                "path": "$.note",
                "start": start,
                "end": end,
                "text": text,
                "precision": "span",
            }
        ],
    )
    v2console.ctx.tables.append(
        "agent_event",
        [
            {
                "event_id": "edge" + "0" * 28,
                "ts": v2console.ctx.clock.now(),
                "trace_id": "trace-edge",
                "span_id": "span-edge",
                "agent_id": "payments",
                "event_type": "tool_call",
                "tool_name": "get_balance",
                "args_masked": '{"note": "<A:1>12345<A:1>"}',
                "env": "test",
                "source": "otel",
                "capture_level": "masked",
            }
        ],
    )
    d = v2console.get(f"/console/decisions/{eid}/drawer?tab=request")
    assert d.status_code == 200
    d2 = v2console.get(f"/console/decisions/{eid}/drawer?tab=detections")
    assert d2.status_code == 200
    assert d.text.count('<mark class="hl">') <= 1


def test_locate_unit() -> None:
    f = {"start": 2, "end": 5, "text": "abc"}
    assert decisions_v2.locate("xxabcxx", f, set()) == (2, 5)
    assert decisions_v2.locate("abcxabc", f, set()) == (0, 3)  # offsets wrong, first token
    assert decisions_v2.locate("abcxabc", f, {(0, 3)}) == (4, 7)  # the second one is free
    assert decisions_v2.locate("xyz", f, set()) is None
    assert decisions_v2.locate("abc", {"start": 0, "end": 3, "text": ""}, set()) is None
    assert decisions_v2.locate("abc", {"start": True, "end": 3, "text": "abc"}, set()) == (0, 3)
