"""Fairness slices (ADR D09; analysis 07 section 3.3 item 5).

For each configured agent and each permitted attribute (``config/fairness.yaml``):

* cells = attribute values; per cell: n, approvals, gate blocks;
* cells with n < ``min_cell_n`` (30) are suppressed: no counts or rates are stored;
* approval-rate gap and block-rate gap = max - min over unsuppressed cells, integer bp;
* rows go to ``fairness_slice``; the largest approval gap goes to ``oversight_metric``
  (``fairness_gap_bp``); a gap above the threshold opens a case (``case_type`` fairness).

Subjects are hashed ids (HMAC-SHA256 with the mask key), never raw ids. Ethnicity and
religion are never sliced. Rates come from Fairlearn's ``MetricFrame`` when the
``monitors`` extra is installed, else from the pure-Python path; both give the same
integers (counts are recovered from the rates, then bp = approvals * 10000 // n).
Fairness is advisory: it opens a case, it never blocks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import yaml

from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConfigError
from supervisor.monitors.common import (
    MonitorContext,
    find_open_case,
    open_case,
    read_range,
    upsert_metric,
)

log = logging.getLogger("supervisor.monitors.fairness")

ACTOR = "monitor:fairness"
FORBIDDEN_ATTRIBUTES = frozenset(
    {"ethnicity", "ethnic_group", "race", "religion", "dan_toc", "ton_giao", "faith"}
)
BLOCKED_STATUSES = ("blocked", "paused", "denied")


# --------------------------------------------------------------------------- config


@dataclass
class FairnessConfig:
    agents: list[str] = field(default_factory=lambda: ["credit_prequal"])
    decision_tool: str = "decide_prequal"
    decision_arg: str = "decision"
    subject_arg: str = "application_id"
    approve_values: tuple[str, ...] = ("approve",)
    window_days: int = 30
    min_cell_n: int = 30
    approval_gap_threshold_bp: int = 2000
    block_gap_threshold_bp: int = 2000
    attribute_source: str = "synthetic"
    synthetic_seed: int = 20261014
    synthetic_customers: int = 40
    attributes: dict[str, bool] = field(
        default_factory=lambda: {
            "gender": True,
            "age_band": True,
            "province_code": True,
            "language": True,
        }
    )

    @property
    def active_attributes(self) -> list[str]:
        return [name for name, permitted in self.attributes.items() if permitted]

    @classmethod
    def load(cls, path: Path) -> FairnessConfig:
        try:
            doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"fairness config {path}: {exc}") from exc
        return cls.from_dict(doc, str(path))

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any], source: str = "<dict>") -> FairnessConfig:
        attrs_doc = doc.get("attributes") or {}
        if not isinstance(attrs_doc, Mapping):
            raise ConfigError(f"{source}: attributes must be a mapping")
        attrs: dict[str, bool] = {}
        for name, spec in attrs_doc.items():
            key = str(name).strip().lower()
            if key in FORBIDDEN_ATTRIBUTES:
                raise ConfigError(
                    f"{source}: attribute {name!r} is never allowed in fairness slices"
                )
            permitted = spec.get("permitted") if isinstance(spec, Mapping) else spec
            if not isinstance(permitted, bool):
                raise ConfigError(f"{source}: attributes.{name}.permitted must be true/false")
            attrs[key] = permitted
        base = cls()
        try:
            cfg = cls(
                agents=[str(a) for a in doc.get("agents", base.agents)],
                decision_tool=str(doc.get("decision_tool", base.decision_tool)),
                decision_arg=str(doc.get("decision_arg", base.decision_arg)),
                subject_arg=str(doc.get("subject_arg", base.subject_arg)),
                approve_values=tuple(str(v) for v in doc.get("approve_values", ["approve"])),
                window_days=int(doc.get("window_days", base.window_days)),
                min_cell_n=int(doc.get("min_cell_n", base.min_cell_n)),
                approval_gap_threshold_bp=int(
                    doc.get("approval_gap_threshold_bp", base.approval_gap_threshold_bp)
                ),
                block_gap_threshold_bp=int(
                    doc.get("block_gap_threshold_bp", base.block_gap_threshold_bp)
                ),
                attribute_source=str(doc.get("attribute_source", base.attribute_source)),
                synthetic_seed=int(doc.get("synthetic_seed", base.synthetic_seed)),
                synthetic_customers=int(doc.get("synthetic_customers", base.synthetic_customers)),
                attributes=attrs if attrs_doc else base.attributes,
            )
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{source}: {exc}") from exc
        if cfg.min_cell_n < 30:
            raise ConfigError(f"{source}: min_cell_n must be >= 30 (analysis 07 3.3)")
        if cfg.attribute_source not in ("synthetic", "none"):
            raise ConfigError(f"{source}: attribute_source must be synthetic or none")
        return cfg


# --------------------------------------------------------------------------- records


@dataclass(frozen=True)
class FairnessRecord:
    subject_hash: str
    attrs: Mapping[str, str]
    approved: bool
    blocked: bool


def subject_hash(key: bytes, subject_id: str) -> str:
    return hmac.new(key, subject_id.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


class AttributeLookup(Protocol):
    def attributes(self, subject_hash: str) -> Mapping[str, str] | None: ...


class SyntheticAttributeLookup:
    """Demo lookup: the synthetic loan applications of the demo world, by hashed id."""

    def __init__(self, key: bytes, seed: int, n_customers: int) -> None:
        from supervisor.data.synthetic import SyntheticGenerator

        gen = SyntheticGenerator(seed)
        customers = gen.customers(n_customers)
        self._by_hash = {
            subject_hash(key, a.application_id): _attrs_of(a)
            for a in gen.loan_applications(customers, n_customers)
        }

    def attributes(self, subject_hash: str) -> Mapping[str, str] | None:
        return self._by_hash.get(subject_hash)


def _attrs_of(app: Any) -> dict[str, str]:
    return {
        "gender": str(app.gender),
        "age_band": str(app.age_band),
        "province_code": str(app.province_code),
        "language": str(app.language),
    }


class DecisionSource(Protocol):
    def records(
        self, agent_id: str, ts_from: datetime, ts_to: datetime
    ) -> list[FairnessRecord]: ...


class EventDecisionSource:
    """Decisions from recorder ``tool_call`` events (masked args JSON) + an attribute lookup.

    The subject id in the args is hashed at once; the raw id is not kept."""

    def __init__(
        self, ctx: MonitorContext, cfg: FairnessConfig, lookup: AttributeLookup, key: bytes
    ) -> None:
        self.ctx, self.cfg, self.lookup, self.key = ctx, cfg, lookup, key

    def records(self, agent_id: str, ts_from: datetime, ts_to: datetime) -> list[FairnessRecord]:
        rows = read_range(
            self.ctx,
            "agent_event",
            ts_from,
            ts_to,
            {"agent_id": agent_id, "tool_name": self.cfg.decision_tool, "event_type": "tool_call"},
        )
        latest: dict[str, FairnessRecord] = {}
        for r in rows:
            try:
                args = json.loads(r.get("args_masked") or "")
            except ValueError:
                continue
            if not isinstance(args, Mapping):
                continue
            sid, decision = args.get(self.cfg.subject_arg), args.get(self.cfg.decision_arg)
            if not isinstance(sid, str) or not isinstance(decision, str):
                continue
            h = subject_hash(self.key, sid)
            attrs = self.lookup.attributes(h)
            if attrs is None:
                continue
            latest[h] = FairnessRecord(
                h,
                attrs,
                decision in self.cfg.approve_values,
                str(r.get("status")) in BLOCKED_STATUSES,
            )
        return list(latest.values())


# --------------------------------------------------------------------------- compute


@dataclass(frozen=True)
class Cell:
    attribute: str
    cell: str
    n: int | None
    approvals: int | None
    blocks: int | None
    approval_rate_bp: int | None
    block_rate_bp: int | None
    suppressed: bool


@dataclass
class AttributeResult:
    attribute: str
    cells: list[Cell]
    approval_gap_bp: int | None
    block_gap_bp: int | None


@dataclass
class FairnessReport:
    method: str
    n: int
    attributes: dict[str, AttributeResult]

    @property
    def max_approval_gap_bp(self) -> int | None:
        gaps = [
            a.approval_gap_bp for a in self.attributes.values() if a.approval_gap_bp is not None
        ]
        return max(gaps) if gaps else None


def fairlearn_available() -> bool:
    try:
        import fairlearn.metrics  # noqa: F401
        import pandas  # noqa: F401
    except ImportError:
        return False
    return True


def _counts_python(
    records: Sequence[FairnessRecord], attribute: str
) -> dict[str, tuple[int, int, int]]:
    out: dict[str, list[int]] = {}
    for r in records:
        value = r.attrs.get(attribute)
        if value is None:
            continue
        c = out.setdefault(str(value), [0, 0, 0])
        c[0] += 1
        c[1] += int(r.approved)
        c[2] += int(r.blocked)
    return {k: (v[0], v[1], v[2]) for k, v in out.items()}


def _counts_fairlearn(
    records: Sequence[FairnessRecord], attribute: str
) -> dict[str, tuple[int, int, int]]:
    from fairlearn.metrics import MetricFrame, count, selection_rate

    rows = [r for r in records if r.attrs.get(attribute) is not None]
    if not rows:
        return {}
    sens = [str(r.attrs[attribute]) for r in rows]
    approved = [int(r.approved) for r in rows]
    blocked = [int(r.blocked) for r in rows]
    fa = MetricFrame(
        metrics={"n": count, "rate": selection_rate},
        y_true=approved,
        y_pred=approved,
        sensitive_features=sens,
    )
    fb = MetricFrame(
        metrics={"rate": selection_rate},
        y_true=blocked,
        y_pred=blocked,
        sensitive_features=sens,
    )
    out: dict[str, tuple[int, int, int]] = {}
    for value, row in fa.by_group.iterrows():
        n = int(row["n"])
        # Counts are recovered from the rates (exact for n < 2**52); the bp maths below
        # then match the pure-Python path to the unit.
        appr = int(round(float(row["rate"]) * n))
        blk = int(round(float(fb.by_group.loc[value, "rate"]) * n))
        out[str(value)] = (n, appr, blk)
    return out


def compute(
    records: Sequence[FairnessRecord],
    attributes: Iterable[str],
    *,
    min_cell_n: int = 30,
    method: str = "auto",
) -> FairnessReport:
    """Per-attribute cells and gaps. ``method``: auto | fairlearn | python."""
    if method == "auto":
        method = "fairlearn" if fairlearn_available() else "python"
    counter = _counts_fairlearn if method == "fairlearn" else _counts_python
    report = FairnessReport(method=method, n=len(records), attributes={})
    for attribute in attributes:
        if attribute in FORBIDDEN_ATTRIBUTES:
            raise ConfigError(f"attribute {attribute!r} is never allowed in fairness slices")
        cells: list[Cell] = []
        counts = counter(records, attribute)
        for value, (n, appr, blk) in sorted(counts.items()):
            if n < min_cell_n:
                cells.append(Cell(attribute, value, None, None, None, None, None, True))
            else:
                cells.append(
                    Cell(attribute, value, n, appr, blk, appr * 10000 // n, blk * 10000 // n, False)
                )
        cells = _complementary(cells, {v: n for v, (n, _, _) in counts.items()}, min_cell_n)
        shown = [c for c in cells if not c.suppressed]
        a_gap = b_gap = None
        if len(shown) >= 2:
            a_rates = [c.approval_rate_bp for c in shown if c.approval_rate_bp is not None]
            b_rates = [c.block_rate_bp for c in shown if c.block_rate_bp is not None]
            a_gap = max(a_rates) - min(a_rates)
            b_gap = max(b_rates) - min(b_rates)
        report.attributes[attribute] = AttributeResult(attribute, cells, a_gap, b_gap)
    return report


def _complementary(cells: list[Cell], n_of: Mapping[str, int], min_cell_n: int) -> list[Cell]:
    """Complementary suppression: the suppressed cells together must hold 0 or at least
    ``min_cell_n`` subjects, else total - shown cells would reveal a small count. Hide the
    smallest shown cell until that holds (or nothing is shown)."""
    cells = list(cells)
    while True:
        hidden = sum(n_of[c.cell] for c in cells if c.suppressed)
        shown = [c for c in cells if not c.suppressed]
        if hidden == 0 or hidden >= min_cell_n or not shown:
            return cells
        smallest = min(shown, key=lambda c: (c.n or 0, c.cell))
        cells = [
            Cell(c.attribute, c.cell, None, None, None, None, None, True) if c is smallest else c
            for c in cells
        ]


# --------------------------------------------------------------------------- monitor


@dataclass
class FairnessRunResult:
    run_id: str
    reports: dict[str, FairnessReport] = field(default_factory=dict)
    cases_opened: list[str] = field(default_factory=list)


class FairnessMonitor:
    def __init__(
        self,
        ctx: MonitorContext,
        cfg: FairnessConfig,
        source: DecisionSource,
        *,
        method: str = "auto",
    ) -> None:
        self.ctx, self.cfg, self.source, self.method = ctx, cfg, source, method

    def run(self, now: datetime | None = None) -> FairnessRunResult:
        now = now or self.ctx.clock.now()
        ts_from = now - timedelta(days=self.cfg.window_days)
        res = FairnessRunResult(run_id=f"fair-{uuid.uuid4().hex[:16]}")
        for agent_id in self.cfg.agents:
            records = self.source.records(agent_id, ts_from, now)
            if not records:
                continue
            report = compute(
                records,
                self.cfg.active_attributes,
                min_cell_n=self.cfg.min_cell_n,
                method=self.method,
            )
            res.reports[agent_id] = report
            self._write(res.run_id, agent_id, report, ts_from, now)
            case_id = self._maybe_case(res.run_id, agent_id, report, ts_from, now)
            if case_id:
                res.cases_opened.append(case_id)
        return res

    def _write(
        self, run_id: str, agent_id: str, report: FairnessReport, ts_from: datetime, now: datetime
    ) -> None:
        ts = self.ctx.clock.now()
        rows = [
            {
                "run_id": run_id,
                "ts": ts,
                "agent_id": agent_id,
                "window_from": ts_from,
                "window_to": now,
                "attribute": c.attribute,
                "cell": c.cell,
                "n": c.n,
                "approvals": c.approvals,
                "blocks": c.blocks,
                "approval_rate_bp": c.approval_rate_bp,
                "block_rate_bp": c.block_rate_bp,
                "suppressed": c.suppressed,
                "method": report.method,
            }
            for a in report.attributes.values()
            for c in a.cells
        ]
        if rows:
            self.ctx.tables.append("fairness_slice", rows)
        gap = report.max_approval_gap_bp
        upsert_metric(
            self.ctx,
            now.date(),
            agent_id,
            {"fairness_gap_bp": gap, "fairness_gap": None if gap is None else gap / 10000},
        )
        self.ctx.evidence.record(
            "fairness_run",
            f"{run_id}:{agent_id}",
            {
                "agent_id": agent_id,
                "run_id": run_id,
                "window_from": format_ts(ts_from),
                "window_to": format_ts(now),
                "method": report.method,
                "min_cell_n": self.cfg.min_cell_n,
                "attributes": _evidence_attrs(report),
                "ts": format_ts(ts),
            },
        )

    def _maybe_case(
        self, run_id: str, agent_id: str, report: FairnessReport, ts_from: datetime, now: datetime
    ) -> str | None:
        over = [
            a
            for a in report.attributes.values()
            if (a.approval_gap_bp or 0) > self.cfg.approval_gap_threshold_bp
            or (a.block_gap_bp or 0) > self.cfg.block_gap_threshold_bp
        ]
        if not over or find_open_case(self.ctx, agent_id, "fairness") is not None:
            return None
        names = ", ".join(
            f"{a.attribute} (approval gap {a.approval_gap_bp} bp, block gap {a.block_gap_bp} bp)"
            for a in over
        )
        return open_case(
            self.ctx,
            agent_id=agent_id,
            severity="medium",
            case_type="fairness",
            summary=f"Fairness: {agent_id} slice gap above threshold on {names}",
            actor=ACTOR,
            evidence_payload={
                "monitor": "fairness",
                "run_id": run_id,
                "window_from": format_ts(ts_from),
                "window_to": format_ts(now),
                "approval_gap_threshold_bp": self.cfg.approval_gap_threshold_bp,
                "block_gap_threshold_bp": self.cfg.block_gap_threshold_bp,
                "attributes": _evidence_attrs(report, only=[a.attribute for a in over]),
            },
        )


def _evidence_attrs(
    report: FairnessReport, only: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    out = []
    for a in report.attributes.values():
        if only is not None and a.attribute not in only:
            continue
        out.append(
            {
                "attribute": a.attribute,
                "approval_gap_bp": a.approval_gap_bp,
                "block_gap_bp": a.block_gap_bp,
                "suppressed_cells": sum(1 for c in a.cells if c.suppressed),
                "cells": [
                    {
                        "cell": c.cell,
                        "n": c.n,
                        "approval_rate_bp": c.approval_rate_bp,
                        "block_rate_bp": c.block_rate_bp,
                    }
                    for c in a.cells
                    if not c.suppressed
                ],
            }
        )
    return out


def build_source(ctx: MonitorContext, cfg: FairnessConfig, key: bytes) -> DecisionSource | None:
    """The configured decision source, or None when ``attribute_source`` is ``none``."""
    if cfg.attribute_source == "none":
        return None
    lookup = SyntheticAttributeLookup(key, cfg.synthetic_seed, cfg.synthetic_customers)
    return EventDecisionSource(ctx, cfg, lookup, key)


__all__ = [
    "FORBIDDEN_ATTRIBUTES",
    "AttributeResult",
    "Cell",
    "EventDecisionSource",
    "FairnessConfig",
    "FairnessMonitor",
    "FairnessRecord",
    "FairnessReport",
    "SyntheticAttributeLookup",
    "build_source",
    "compute",
    "fairlearn_available",
    "subject_hash",
]
