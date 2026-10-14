"""Capability catalogue: schema, loader, selection by risk class, coverage rows."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from supervisor.adapters.factory import build_adapters
from supervisor.catalogue import (
    CatalogueError,
    coverage_rows,
    load_catalogue,
    write_coverage,
)
from supervisor.catalogue.loader import MANIFEST_DIR, parse_manifest_text
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema

REQUIRED = {
    "approved_tools",
    "single_limit",
    "daily_aggregate",
    "split_payment",
    "pii_masking",
    "injection_prefilter",
    "tier1_monitor",
    "tier2_judge",
    "drift_band",
    "fairness_slices",
    "groundedness",
    "evidence_chain",
    "case_files",
    "otlp_ingest",
    "proxy_log",
}
# WP7 builds the monitors in parallel; their modules may not exist yet.
PENDING_MODULES = {"supervisor.monitors.drift", "supervisor.monitors.fairness"}
PENDING_MODULES |= {"supervisor.monitors.groundedness"}


def test_catalogue_has_the_required_manifests() -> None:
    cat = load_catalogue()
    assert len(cat) >= 12
    assert REQUIRED <= set(cat.ids())


def test_thresholds_and_costs_are_integers() -> None:
    for m in load_catalogue().manifests.values():
        assert all(type(v) is int for v in m.default_thresholds.values()), m.id
        cost = m.cost_estimate.model_dump()
        assert all(type(v) is int for v in cost.values()), m.id


def test_only_gate_rules_can_block() -> None:
    for m in load_catalogue().manifests.values():
        if m.can_block:
            assert m.kind == "gate_rule", m.id
    text = (MANIFEST_DIR / "tier1_monitor.yaml").read_text(encoding="utf-8")
    with pytest.raises(CatalogueError, match="only gate_rule"):
        parse_manifest_text(text + "\ncan_block: true\n", "bad.yaml")


def test_float_threshold_and_unknown_key_fail() -> None:
    text = (MANIFEST_DIR / "drift_band.yaml").read_text(encoding="utf-8")
    with pytest.raises(CatalogueError, match="integers only|valid integer"):
        parse_manifest_text(text.replace("band_bp: 2000", "band_bp: 0.2"), "f.yaml")
    with pytest.raises(CatalogueError, match="surprise"):
        parse_manifest_text(text + "\nsurprise: 1\n", "x.yaml")


def test_duplicate_ids_fail(tmp_path: Path) -> None:
    (tmp_path / "dup.yaml").write_text(
        (MANIFEST_DIR / "approved_tools.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(CatalogueError, match="twice"):
        load_catalogue(extra_dirs=[tmp_path])


def test_implemented_modules_exist() -> None:
    for m in load_catalogue().manifests.values():
        if m.module in PENDING_MODULES:
            continue
        assert importlib.util.find_spec(m.module) is not None, f"{m.id}: {m.module}"


def test_selection_by_risk_class() -> None:
    cat = load_catalogue()
    money = cat.select(
        {"money", "read_only"},
        {"amount_arg", "declared_limit", "destination_arg", "customer_key", "otel_spans"},
    )
    assert {"approved_tools", "single_limit", "split_payment", "daily_aggregate"} <= set(
        money.on_ids
    )
    assert "fairness_slices" not in money.on_ids
    credit = cat.select(
        {"credit", "pii_export"}, {"decision_tool", "record_fact", "prior_read", "pii_tool"}
    )
    assert {"fairness_slices", "system_of_record", "prior_read", "pii_bulk_read"} <= set(
        credit.on_ids
    )
    assert "split_payment" not in credit.on_ids
    # proxy log only for the proxy plug point
    assert "proxy_log" not in money.on_ids
    assert "proxy_log" in cat.select({"money"}, set(), plug_point="proxy_log").on_ids


def test_coverage_rows_derive_from_selection(tmp_path: Path) -> None:
    cat = load_catalogue()
    sel = cat.select({"read_only"}, {"otel_spans"})
    rows = coverage_rows("customer_service", sel, status_on="planned")
    assert len(rows) == len(cat)
    by_id = {r["capability_id"]: r for r in rows}
    assert by_id["approved_tools"]["status"] == "planned"
    assert by_id["single_limit"]["status"] == "off"
    assert "risk class" in by_id["single_limit"]["reason"]

    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    a = build_adapters(settings)
    try:
        bootstrap_schema.run(settings, a)
        assert write_coverage(a.state, rows) == len(rows)
        assert write_coverage(a.state, rows) == 0  # idempotent
        rows[0] = {**rows[0], "status": "on"}
        assert write_coverage(a.state, rows) == 1
        stored = a.state.query("coverage", {"agent_id": "customer_service"})
        assert len(stored) == len(cat)
    finally:
        a.close()
