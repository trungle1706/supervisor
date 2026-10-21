"""WP38: Playground sample library and extra attributes. The dry run stays a no-write path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supervisor.console import playground

from .conftest import Console
from .test_ux3_playground import fingerprint, pg  # noqa: F401  (fixture reuse)

IDS = {
    "injection_en",
    "injection_vi",
    "pii_vi",
    "jailbreak_en",
    "secrets_en",
    "toxicity_vi",
    "split_payment_vi",
    "output_pii_en",
}


def run(c: Console, **kw: str):
    data = {"agent_id": "customer_service", "tool": "reply", "version": "1", "args": "{}"}
    data.update(kw)
    return c.post("/console/playground/run", data, user="operator.khanh")


def test_library_has_the_eight_samples_with_provenance() -> None:
    samples = {s["id"]: s for s in playground.load_samples()}
    assert IDS <= set(samples)
    cats = {s["category"] for s in samples.values()}
    assert {"injection", "pii", "jailbreak", "secrets", "toxicity", "split_payment"} <= cats
    assert {s["language"] for s in samples.values()} >= {"en", "vi"}
    for s in samples.values():
        assert s["labeller"] == "synthetic" and s["licence"] and s["source"]


def test_a_bad_sample_file_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "ok.json").write_text(
        json.dumps({"id": "ok", "tool": "reply", "args": {}}), encoding="utf-8"
    )
    (tmp_path / "bad1.json").write_text("{nope", encoding="utf-8")
    (tmp_path / "bad2.json").write_text(json.dumps({"id": "a b", "tool": "t", "args": {}}))
    (tmp_path / "bad3.json").write_text(json.dumps({"id": "x", "tool": "t", "args": []}))
    (tmp_path / "big.json").write_text(" " * 40_000)
    assert [s["id"] for s in playground.load_samples(tmp_path)] == ["ok"]
    assert playground.load_samples(tmp_path / "missing") == []


def test_page_lists_samples_and_a_sample_fills_the_form(pg: Console) -> None:  # noqa: F811
    r = pg.get("/console/playground", user="operator.khanh")
    assert (
        r.status_code == 200 and 'data-sample="pii_vi"' in r.text and 'name="consumer_id"' in r.text
    )
    r = pg.get("/console/playground?sample=pii_vi", user="operator.khanh")
    assert "add_payee" in r.text and "0912345678" in r.text  # synthetic sample text, in the form
    assert 'value="add_payee"' in r.text
    assert pg.get("/console/playground?sample=nope", user="operator.khanh").status_code == 200
    assert pg.get("/console/playground?sample=a%20b", user="operator.khanh").status_code == 400


def test_extra_attributes_fill_the_context(pg: Console) -> None:  # noqa: F811
    form = playground.parse_form(
        {
            "agent_id": "payments",
            "tool": "transfer",
            "args": "{}",
            "context": '{"trace_id": "t1"}',
            "consumer_id": "web-1",
            "tool_class": "money",
            "direction": "input",
        }
    )
    assert form["context"] == {
        "trace_id": "t1",
        "consumer_id": "web-1",
        "declared_risk_class": "money",
    }
    assert form["direction"] == "input"


@pytest.mark.parametrize(
    "bad",
    [
        {"consumer_id": "a b"},
        {"consumer_id": "x" * 129},
        {"consumer_id": "café"},
        {"tool_class": "huge"},
        {"direction": "sideways"},
    ],
)
def test_bad_extra_attributes_are_400(pg: Console, bad: dict[str, str]) -> None:  # noqa: F811
    assert run(pg, **bad).status_code == 400


def test_output_direction_needs_detectors(pg: Console) -> None:  # noqa: F811
    r = run(pg, direction="output", context='{"output": "x"}')
    assert r.status_code == 400 and "DETECTORS_ENABLED" in r.text


def test_dry_run_with_samples_and_attributes_still_writes_nothing(pg: Console) -> None:  # noqa: F811
    gw = pg.ctx.gateway
    pg.get("/console/")
    gw.drain()
    before = fingerprint(pg)
    heads = {k: (v.seq, v.entry_hash) for k, v in pg.ctx.runtime.chain.heads().items()}
    for s in playground.load_samples():
        if s.get("direction") == "output":
            continue
        r = run(
            pg,
            agent_id=s["agent_hint"],
            tool=s["tool"],
            args=json.dumps(s["args"]),
            consumer_id="web-1",
            tool_class="read_only",
        )
        assert r.status_code == 200, (s["id"], r.text[:200])
    gw.drain()
    assert fingerprint(pg) == before
    assert {k: (v.seq, v.entry_hash) for k, v in pg.ctx.runtime.chain.heads().items()} == heads
