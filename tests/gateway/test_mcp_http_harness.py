"""WP26 regression: the harness on the mock path must not fall below the recorded baseline.

Baseline: tests/fixtures/mcp_http/baseline.json (date and commit inside). Re-record with
``python -m supervisor.gateway.mcp_http_harness --no-latency --record`` only on purpose.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from supervisor.gateway import mcp_http_harness as H
from tests.conftest import REPO_ROOT

FIX = REPO_ROOT / "tests" / "fixtures" / "mcp_http"
HIGHER = ("drift_catch", "poison_catch", "removed_logged", "call_block")
LOWER = ("lock_false_alarm", "scan_false_alarm")


def _bp(m: dict[str, int]) -> int:
    return 0 if m["n"] == 0 else m["k"] * 10000 // m["n"]


@pytest.fixture(scope="module")
def quality() -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        env = H.build_env("sqlite", Path(tmp))
        try:
            return H.run_quality(env, "all")
        finally:
            env.close()


def test_no_metric_falls_below_the_baseline(quality: dict[str, Any]) -> None:
    base = json.loads((FIX / "baseline.json").read_text())
    assert base["schema"] == H.SCHEMA and base["recorded_on"] and base["commit"]
    got = H.baseline_view({"quality": quality, "commit": "x"})["metrics"]
    for part, metrics in base["metrics"].items():
        for name in HIGHER:
            assert _bp(got[part][name]) >= _bp(metrics[name]), (part, name)
        for name in LOWER:
            assert _bp(got[part][name]) <= _bp(metrics[name]), (part, name)
        assert got[part]["held_calls_leaked"] <= metrics["held_calls_leaked"], part


def test_verdict_is_go_and_every_metric_has_an_interval(quality: dict[str, Any]) -> None:
    v = H.verdicts(quality, None)
    assert {k: x["verdict"] for k, x in v.items() if x["verdict"] != "GO"} == {}
    for part in ("templates", "heldout", "probes"):
        for name in ("drift_catch", "poison_catch", "scan_false_alarm", "lock_false_alarm"):
            m = quality[part][name]
            assert m["wilson_bp"] is not None and m["wilson_bp"][0] <= m["bp"] <= m["wilson_bp"][1]


def test_templates_do_not_hide_the_probe_weak_spots(quality: dict[str, Any]) -> None:
    """The probes must keep reporting the documented limits instead of passing silently."""
    misses = set(quality["probes"]["misses"])
    assert {"poison:base64", "poison:rot13", "poison:leetspeak"} <= misses
    assert "drift:unhashed_field" in misses
    assert any("benign_lookalike" in k for k in quality["probes"]["false_alarms"])
    assert quality["known_gap_probes"] == ["X-20", "X-21", "X-22", "X-26", "X-30"]


def test_chain_records_cover_every_lock_event(quality: dict[str, Any]) -> None:
    kinds = quality["chain_records"]
    assert kinds["mcp_manifest_seeded"] == quality["n_items"]
    assert kinds["mcp_tool_lock_change"] > 0 and kinds["mcp_tool_blocked"] > 0


# --------------------------------------------------------------------------- fixture rules
def _items() -> list[dict[str, Any]]:
    return H.load_items("all")


def test_golden_set_has_provenance_and_enough_items() -> None:
    items = _items()
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    for i in items:
        assert i["source"] and i["licence"] and i["labeller"] in ("synthetic", "expert rubric")
        assert i["split"] in ("dev", "heldout", "probe")
        assert set(i["labels"]) == {"hold", "poison", "removed"}
    tmpl = [i for i in items if i["split"] != "probe"]
    assert len(tmpl) >= 50
    assert sum(len(i["labels"]["poison"]) for i in tmpl) >= 50  # n >= 50 per metric
    assert sum(len(i["labels"]["hold"]) for i in tmpl) >= 50
    assert len([i for i in items if i["split"] == "probe"]) >= 20
    assert {i["split"] for i in tmpl} == {"dev", "heldout"}
    families = {i["scenario"] for i in tmpl}
    assert {"clean_same", "renamed", "redescribed", "schema_widened", "poisoned_new"} <= families


def test_poison_phrases_of_the_two_splits_do_not_overlap() -> None:
    items = [i for i in _items() if i["scenario"].startswith("poisoned")]
    dev = {i["id"] for i in items if i["split"] == "dev"}
    held = {i["id"] for i in items if i["split"] == "heldout"}
    assert dev and held and not dev & held

    def text(i: dict[str, Any]) -> str:
        return json.dumps(i["observed"])

    spec = importlib.util.spec_from_file_location("bg", FIX / "build_golden.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for lang in ("en", "vi"):
        a, b = set(mod.BANK["dev"][lang]), set(mod.BANK["heldout"][lang])
        assert not a & b
    for i in items:
        bank = mod.BANK[i["split"]]
        other = mod.BANK["heldout" if i["split"] == "dev" else "dev"]
        mine = {json.dumps(p, ensure_ascii=True)[1:-1] for lang in bank.values() for p in lang}
        theirs = {json.dumps(p, ensure_ascii=True)[1:-1] for lang in other.values() for p in lang}
        t = text(i)
        assert any(p in t for p in mine) and not any(p in t for p in theirs), i["id"]


def test_fixtures_are_current() -> None:
    spec = importlib.util.spec_from_file_location("bg2", FIX / "build_golden.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.render(mod.build_templates()) == (FIX / "golden.json").read_text()
    assert mod.render(mod.build_probes()) == (FIX / "probes.json").read_text()


def test_probes_are_not_template_output() -> None:
    probes = [i for i in _items() if i["split"] == "probe"]
    families = {p["scenario"] for p in probes}
    tmpl = {i["scenario"] for i in _items() if i["split"] != "probe"}
    assert not families & tmpl
    assert {
        "homoglyph_name",
        "whitespace_only",
        "telex",
        "no_diacritics_vi",
        "base64",
        "benign_lookalike",
    } <= families


def test_baseline_names_date_and_commit() -> None:
    base = json.loads((FIX / "baseline.json").read_text())
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", base["recorded_on"])
    assert re.fullmatch(r"[0-9a-f]{12}|unknown", base["commit"])


# --------------------------------------------------------------------------- other parts
def test_wilson_matches_known_values() -> None:
    assert H.wilson_bp(0, 0) is None
    lo, hi = H.wilson_bp(50, 50)  # type: ignore[misc]
    assert hi == 10000 and 9000 < lo < 9500
    lo, hi = H.wilson_bp(0, 100)  # type: ignore[misc]
    assert lo == 0 and 100 < hi < 500


def test_percentile_is_nearest_rank() -> None:
    assert H.percentile([1, 2, 3, 4], 50) == 2 and H.percentile([1, 2, 3, 4], 95) == 4
    assert H.percentile([], 50) == 0


def test_latency_run_measures_the_allow_path(tmp_path: Path) -> None:
    env = H.build_env("sqlite", tmp_path)
    try:
        lat = H.run_latency(env, n=30, warm=5, repeats=1, gate_server=False)
    finally:
        env.close()
    assert set(lat["arms"]) >= {
        "direct",
        "proxy_nolock_stubgate",
        "proxy_lock_stubgate",
        "proxy_lock_gate_inproc",
    }
    assert all(a["p50_us"] > 0 and a["p95_us"] >= a["p50_us"] for a in lat["arms"].values())
    assert lat["arms"]["direct"]["p50_us"] < lat["arms"]["proxy_lock_gate_inproc"]["p50_us"]
    assert lat["upstream_connections"] < 40  # kept alive: not one connection per call


def test_databricks_fake_backend_gives_the_same_probe_numbers(tmp_path: Path) -> None:
    sq = H.build_env("sqlite", tmp_path / "a")
    fk = H.build_env("databricks_fake", tmp_path / "b")
    try:
        a = H.run_quality(sq, "probe")["probes"]
        b = H.run_quality(fk, "probe")["probes"]
    finally:
        sq.close()
        fk.close()
    for name in (
        "drift_catch",
        "poison_catch",
        "scan_false_alarm",
        "lock_false_alarm",
        "call_block",
    ):
        assert (a[name]["k"], a[name]["n"]) == (b[name]["k"], b[name]["n"]), name
    assert a["misses"] == b["misses"]


def test_cli_help_and_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        H.main(["--help"])
    assert exc.value.code == 0
    assert "--gate-server" in capsys.readouterr().out
    assert H.main(["--split", "probe", "--no-latency", "--record"]) == 2  # --record needs all
