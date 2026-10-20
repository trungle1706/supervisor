"""Read-only facts for the transparency report (WP31).

``Facts`` is the one place that talks to the stores. The builder calls its small methods and the
read services of other packages (inventory, risk register, compliance matrix); it holds no query
of its own. Every method only reads. A method that cannot answer raises; the builder turns that
into a section that says "not available" rather than guessing.
"""

from __future__ import annotations

import datetime as dt
import re
import shutil
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.core.canonical import format_ts

OPEN_STATUSES = ("open", "triaged", "contained")
_ROOT = "root"
_WORD = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class Sources:
    """The ports the facts need. Built from adapters (CLI, job) or from the console context."""

    state: Any
    tables: Any
    clock: Any
    settings: Any
    chain: Any = None  # ChainWriter-like: .heads()
    masker: Any = None  # Masker or None
    last_verify: dict[str, dict[str, Any]] = field(default_factory=dict)
    verify_fn: Callable[[str], dict[str, Any]] | None = None

    @classmethod
    def from_adapters(cls, adapters: Any, chain: Any = None, masker: Any = None) -> Sources:
        return cls(
            adapters.state,
            adapters.tables,
            adapters.clock,
            adapters.settings,
            chain=chain,
            masker=masker,
        )

    @classmethod
    def from_context(cls, ctx: Any) -> Sources:
        from supervisor.adapters.factory import make_masker

        return cls(
            ctx.state,
            ctx.tables,
            ctx.clock,
            ctx.settings,
            chain=ctx.runtime.chain,
            masker=make_masker(ctx.settings),
            last_verify=ctx.last_verify,
        )


def verify_lane(tables: Any, settings: Any, lane: str) -> dict[str, Any]:
    """Export one lane plus the root lane to a scratch folder and verify it offline (the same
    check as the console "verify", but it writes no chain record: a report is built from
    facts and must not add facts of its own while it reads)."""
    from supervisor.evidence.export import export_chain
    from supervisor.evidence.verify import verify_export

    work = Path(settings.console_export_dir) / "verify" / ("tr-" + uuid.uuid4().hex)
    try:
        export_chain(tables, work, lanes=[lane])
        anchors = Path(settings.anchor_path) if settings.anchor_kind == "worm_dir" else None
        report = verify_export(
            work,
            partial=True,
            anchors_dir=anchors if anchors is not None and anchors.is_dir() else None,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"ok": report.failures == 0, "failures": int(report.failures)}


class Facts:
    def __init__(self, src: Sources) -> None:
        self.src = src
        self.settings = src.settings
        self._masker = src.masker

    # ------------------------------------------------------------------ small helpers
    def now(self) -> dt.datetime:
        return self.src.clock.now()

    def mask(self, text: Any, limit: int = 160) -> str:
        """Masked, cut to ``limit`` characters. With no masker the text is dropped, never kept
        raw (a report must not carry a string nobody masked)."""
        if text is None:
            return ""
        raw = str(text)
        if self._masker is None:
            return "[unmasked text dropped]"
        out = str(self._masker.mask(raw))
        return out if len(out) <= limit else out[: limit - 1] + "~"

    # ------------------------------------------------------------------ registry
    def agent_row(self, agent_id: str) -> dict[str, Any] | None:
        row = self.src.state.get("agent", {"agent_id": agent_id})
        return dict(row) if row else None

    def agent_ids(self) -> list[str]:
        return sorted(str(r["agent_id"]) for r in self.src.state.query("agent"))

    def running_agents(self) -> list[str]:
        """Registered agents that are not retired (the job builds reports for these)."""
        return sorted(
            str(r["agent_id"])
            for r in self.src.state.query("agent")
            if str(r.get("status")) != "retired"
        )

    def d33_proposal(self, agent_id: str) -> str | None:
        """The classification an Onboard run proposed (profile.json), if one exists."""
        import json

        prof = Path(self.settings.data_dir) / "onboard" / agent_id / "profile.json"
        try:
            if prof.stat().st_size > 2_000_000:
                return None
            data = json.loads(prof.read_text(encoding="utf-8"))
            return str(data["decision33"]["classification"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    # ------------------------------------------------------------------ other services
    def inventory(self, agent_id: str) -> dict[str, Any] | None:
        if not self.settings.inventory_enabled:
            return None
        from supervisor.inventory.service import InventoryService

        return InventoryService(self.src.state, self.src.clock, self.settings).summary_for_agent(
            agent_id
        )

    def matrix(self, agent_id: str) -> dict[str, Any]:
        from supervisor.console import compliance_view

        return compliance_view.matrix_for(self.settings, agent_id)

    def risk_summary(self, agent_id: str) -> dict[str, Any] | None:
        if not self.settings.risk_register_enabled:
            return None
        from supervisor.risk.service import RiskService

        svc = RiskService(self.src.state, self.src.tables, self.src.clock, self.settings)
        return svc.agent_summary(agent_id)

    def risk_link_counts(self, risk_id: str) -> dict[str, int]:
        """How many active links of a risk are evidence and how many are references only (the
        evidence rule of the register: rule and pack links, and the monitors it lists)."""
        from supervisor.risk.evidence import EVIDENCE_MONITORS
        from supervisor.risk.service import RiskService

        svc = RiskService(self.src.state, self.src.tables, self.src.clock, self.settings)
        ev = ref = 0
        for x in svc.links(risk_id):
            counts = x["kind"] in ("rule", "pack") or (
                x["kind"] == "monitor" and x["target"] in EVIDENCE_MONITORS
            )
            ev, ref = (ev + 1, ref) if counts else (ev, ref + 1)
        return {"evidence_links_n": ev, "reference_links_n": ref}

    def judge_card(self) -> dict[str, Any]:
        from supervisor.judge.mrm.card import build_card

        return build_card(self.settings, tables=self.src.tables, now=self.now())

    def validations(self, limit: int = 3) -> list[dict[str, Any]]:
        rows = self.src.tables.query("model_validation", order_by=("-ts",), limit=limit)
        return [dict(r) for r in rows]

    def monitor_bindings(self, agent_id: str) -> Any:
        from supervisor.monitors.bindings import BindingResolver

        return BindingResolver.from_settings(self.settings).resolve(agent_id)

    def oversight_latest(self, agent_id: str) -> dict[str, Any] | None:
        rows = [dict(r) for r in self.src.state.query("oversight_metric", {"agent_id": agent_id})]
        return max(rows, key=lambda r: str(r["metric_date"])) if rows else None

    def assurance_latest(self, agent_id: str) -> list[dict[str, Any]]:
        from supervisor.assurance.results import latest_results

        return latest_results(self.src.tables, "agent", agent_id)

    # ------------------------------------------------------------------ cases
    def cases(self, agent_id: str) -> list[dict[str, Any]]:
        rows = self.src.state.query("cases", {"agent_id": agent_id})
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ evidence chain
    def chain_lane(self, agent_id: str) -> dict[str, Any] | None:
        """Head of the agent lane: entry count and head hash (None when the lane is empty)."""
        lane = f"agent:{agent_id}"
        rows = self.src.tables.query("chain_entry", {"lane": lane}, order_by=("-seq",), limit=1)
        if not rows:
            return None
        head = rows[0]
        return {"lane": lane, "entries": int(head["seq"]) + 1, "head_hash": str(head["entry_hash"])}

    def chain_root(self) -> dict[str, Any] | None:
        sig = self.src.tables.query("chain_signature", {"lane": _ROOT}, order_by=("-seq",), limit=1)
        if not sig:
            return None
        s = sig[0]
        return {
            "seq": int(s["seq"]),
            "key_id": str(s["key_id"]),
            "key_kind": str(s["key_kind"]),
            "algorithm": str(s["algorithm"]),
        }

    def anchored(self) -> bool:
        return bool(self.src.tables.query("anchor", None, order_by=("-anchored_at",), limit=1))

    def verify(self, agent_id: str, *, fresh: bool) -> dict[str, Any]:
        """The chain check for one agent lane. ``fresh`` runs the offline verifier now; else the
        newest console result is used if there is one. ``state`` is ok, failed or not_run."""
        lane = f"agent:{agent_id}"
        if fresh and self.chain_lane(agent_id) is None:
            return {"state": "empty", "failures": 0, "how": "run_now"}  # no records to check
        if fresh:
            fn = self.src.verify_fn or (lambda ln: verify_lane(self.src.tables, self.settings, ln))
            res = fn(lane)
            return {
                "state": "ok" if res["ok"] else "failed",
                "failures": int(res["failures"]),
                "how": "run_now",
            }
        for key in (lane, "all"):
            res = self.src.last_verify.get(key)
            if res is not None:
                return {
                    "state": "ok" if res.get("ok") else "failed",
                    "failures": int(res.get("failures", 0)),
                    "how": "console_cache",
                }
        return {"state": "not_run", "failures": 0, "how": "none"}

    # ------------------------------------------------------------------ backlog
    def backlog_rows(self) -> list[tuple[str, str]] | None:
        """(item, returns_when) rows of BACKLOG.md, or None when the file is not there (the App
        container may not ship it)."""
        path = Path(self.settings.transparency_backlog_file)
        try:
            if path.stat().st_size > 1_000_000:
                return None
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        rows: list[tuple[str, str]] = []
        for line in text.splitlines():
            if not line.startswith("|") or line.startswith("|---") or line.startswith("| Item"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2:
                rows.append((cells[0], " | ".join(cells[1:])))
        return rows

    @staticmethod
    def words(text: str) -> set[str]:
        return {w.lower() for w in _WORD.findall(text)}


def fmt_day(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return format_ts(value)[:10]
    return str(value)[:10]


def plain(value: Mapping[str, Any]) -> dict[str, Any]:
    """Row to plain JSON types: timestamps to RFC 3339 text."""
    out: dict[str, Any] = {}
    for k, v in value.items():
        out[k] = format_ts(v) if isinstance(v, dt.datetime) else v
    return out
