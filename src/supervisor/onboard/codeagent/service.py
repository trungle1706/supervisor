# ruff: noqa: E501
"""Service of the source analysis agent (flag ``CODE_AGENT_ENABLED``).

One report per intake attempt, stored next to the scrubbed tree:

    <DATA_DIR>/code_analysis/<node dir>/<n>/report.json   the CodeAnalysisReport
                                          /status.json   queued | running | done | failed
                                          /applied.json  the finding ids written to onboard_facts

``start`` runs the analysis in a background thread (the console polls ``status``). The agent gets
its model from ``make_chat_model``: with no LLM configured the report is deterministic and says
so. "Use in assessment" (``apply``) writes the agent's verified findings into ``onboard_facts`` as
model rows (``source=model``, ``model_id=code-agent:<model>``); ``FactsService.build`` keeps them
on a re-read while the applied marker exists. Nothing here blocks or pauses anything.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from supervisor.core.errors import SupervisorError
from supervisor.core.ports import ChatModel
from supervisor.onboard import intake
from supervisor.onboard.codeagent.agent import AgentConfig
from supervisor.onboard.codeagent.analyse import analyse_tree
from supervisor.onboard.codeagent.models import CodeAnalysisReport, Finding
from supervisor.onboard.scrub import scrub_text

log = logging.getLogger("supervisor.onboard.codeagent")

FLAG_TEXT = "code_agent_off: the source analysis agent is off (CODE_AGENT_ENABLED=1 turns it on)"
STATES = ("none", "queued", "running", "done", "failed")
_LOCK = threading.RLock()
_THREADS: dict[tuple[str, int], threading.Thread] = {}
MODEL_SOURCE = "model"
KIND_OF_FINDING = {
    "tool": "tool",
    "model": "model",
    "egress": "external_url",
    "hitl": "approval_point",
    "data_flow": "dataset",
    "guardrail": "claim",
    "secret_handling": "secret_use",
    "logging": "weak_spot",
    "pii": "claim",
}
RISK_CLASS = {
    "money": "money",
    "credit": "credit",
    "message": "pii_export",
    "delete": "pii_export",
    "write": "pii_export",
    "other": "pii_export",
    "read": "read_only",
}


class CodeAgentError(SupervisorError):
    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def require_on(settings: Any) -> None:
    if not getattr(settings, "code_agent_enabled", False):
        raise CodeAgentError("code_agent_off", FLAG_TEXT.split(": ", 1)[1])


def agent_config(settings: Any) -> AgentConfig:
    return AgentConfig(
        max_steps=int(settings.code_agent_max_steps),
        max_tokens=int(settings.code_agent_max_tokens),
        max_seconds=int(settings.code_agent_max_seconds),
        max_read_lines=int(settings.code_agent_max_read_lines),
        call_timeout_s=float(getattr(settings, "llm_timeout_s", 400) or 400),
    )


def _clean(text: Any, limit: int) -> str:
    raw = "".join(c if c in "\t " or ord(c) >= 32 else " " for c in str(text or ""))
    return scrub_text(raw).text.strip()[:limit]


class CodeAgentService:
    def __init__(
        self,
        settings: Any,
        state: Any,
        clock: Any,
        *,
        chat_factory: Callable[[], ChatModel] | None = None,
        tables: Any = None,
    ) -> None:
        self.settings = settings
        self.state = state
        self.clock = clock
        self.tables = tables
        self._chat_factory = chat_factory

    # ------------------------------------------------------------------ paths
    def _intake(self) -> intake.IntakeService:
        return intake.IntakeService(self.settings, self.state, self.clock)

    def root(self, node_id: str, n: int) -> Path:
        intake.check_node_id(node_id)
        return (
            Path(self.settings.data_dir)
            / "code_analysis"
            / intake.node_dir_name(node_id)
            / str(int(n))
        )

    def latest_attempt(self, node_id: str) -> int | None:
        ns = [
            int(r["n"])
            for r in self.state.query("intake_attempt", {"node_id": node_id})
            if r["status"] != "failed"
        ]
        return max(ns) if ns else None

    def _chat(self) -> ChatModel:
        if self._chat_factory is not None:
            return self._chat_factory()
        from supervisor.adapters.factory import make_chat_model

        return make_chat_model(self.settings)

    # ------------------------------------------------------------------ read
    def status(self, node_id: str, n: int | None = None) -> dict[str, Any]:
        intake.check_node_id(node_id)
        latest = self.latest_attempt(node_id)
        n = n if n is not None else latest
        base: dict[str, Any] = {
            "node_id": node_id,
            "attempt_n": n,
            "latest_attempt": latest,
            "state": "none",
            "step": 0,
            "steps": 0,
            "error": "",
            "started_at": None,
            "finished_at": None,
            "applied": 0,
            "newer_attempt": False,
        }
        if n is None:
            return base
        p = self.root(node_id, n) / "status.json"
        if p.is_file():
            try:
                base.update(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                base["state"] = "failed"
                base["error"] = "status file unreadable"
        if base["state"] in ("queued", "running") and (node_id, n) not in _THREADS:
            base["state"], base["error"] = (
                "failed",
                "interrupted (the server restarted); run it again",
            )
        base["applied"] = len(self._applied(node_id, n))
        has_report = (self.root(node_id, n) / "report.json").is_file()
        base["has_report"] = has_report
        if has_report:
            rb = self._built_attempt(node_id)
            base["newer_attempt"] = bool(rb is not None and latest is not None and latest > rb)
        return base

    def _built_attempt(self, node_id: str) -> int | None:
        base = self.root(node_id, 0).parent
        ns = [
            int(p.name)
            for p in base.glob("*")
            if p.name.isdigit() and (p / "report.json").is_file()
        ]
        return max(ns) if ns else None

    def report(self, node_id: str, n: int | None = None) -> CodeAnalysisReport | None:
        n = n if n is not None else (self._built_attempt(node_id) or self.latest_attempt(node_id))
        if n is None:
            return None
        p = self.root(node_id, n) / "report.json"
        if not p.is_file():
            return None
        try:
            return CodeAnalysisReport.model_validate_json(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------------ run
    def _write_status(self, node_id: str, n: int, **kw: Any) -> None:
        d = self.root(node_id, n)
        d.mkdir(parents=True, exist_ok=True)
        p = d / "status.json"
        cur: dict[str, Any] = {}
        if p.is_file():
            try:
                cur = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cur = {}
        cur.update(kw)
        tmp = d / "status.json.tmp"
        tmp.write_text(json.dumps(cur), encoding="utf-8")
        tmp.replace(p)

    def start(self, node_id: str, n: int | None, actor: str) -> dict[str, Any]:
        require_on(self.settings)
        intake.check_node_id(node_id)
        n = int(n) if n is not None else self.latest_attempt(node_id)
        if n is None:
            raise CodeAgentError(
                "no_attempt", "there is no stored source; add one in the Source panel first"
            )
        tree = self._tree(node_id, n)
        with _LOCK:
            if (node_id, n) in _THREADS and _THREADS[(node_id, n)].is_alive():
                raise CodeAgentError(
                    "already_running", "an analysis of this source is already running"
                )
            self._write_status(
                node_id,
                n,
                state="queued",
                step=0,
                steps=int(self.settings.code_agent_max_steps),
                error="",
                started_at=self.clock.now().isoformat()
                if hasattr(self.clock.now(), "isoformat")
                else str(self.clock.now()),
                finished_at=None,
                actor=actor,
            )
            th = threading.Thread(
                target=self._work, args=(node_id, n, tree), name=f"code-agent-{n}", daemon=True
            )
            _THREADS[(node_id, n)] = th
            th.start()
        return self.status(node_id, n)

    def tree_for(self, node_id: str, n: int) -> Path:
        """The stored scrubbed tree of an attempt (``CodeAgentError`` when there is none)."""
        return self._tree(node_id, n)

    def _tree(self, node_id: str, n: int) -> Path:
        attempt = next(
            (
                r
                for r in self.state.query("intake_attempt", {"node_id": node_id})
                if int(r["n"]) == n
            ),
            None,
        )
        if attempt is None:
            raise CodeAgentError("no_attempt", f"attempt {n} of {node_id} does not exist")
        if attempt["status"] == "failed":
            raise CodeAgentError("attempt_failed", f"attempt {n} was refused; there is no source")
        tree = self._intake().tree_path(node_id, n)
        if not tree.is_dir():
            raise CodeAgentError(
                "tree_missing",
                f"the stored source of attempt {n} is not on this server any more; upload again",
            )
        return tree

    def _work(self, node_id: str, n: int, tree: Path) -> None:
        try:
            self._write_status(node_id, n, state="running")
            self.run_sync(node_id, n, tree=tree)
            self._write_status(node_id, n, state="done", finished_at=_now(self.clock))
        except Exception as exc:  # noqa: BLE001 - a background run must end in a state, never in a traceback
            log.exception("code agent run failed")
            self._write_status(
                node_id,
                n,
                state="failed",
                error=_clean(f"{type(exc).__name__}: {exc}", 200),
                finished_at=_now(self.clock),
            )
        finally:
            with _LOCK:
                _THREADS.pop((node_id, n), None)

    def run_sync(
        self, node_id: str, n: int, *, tree: Path | None = None, use_agent: bool = True
    ) -> CodeAnalysisReport:
        require_on(self.settings)
        tree = tree or self._tree(node_id, n)
        chat = self._chat()
        report, _run = analyse_tree(
            tree,
            chat,
            agent_config(self.settings),
            node_id=node_id,
            attempt_n=n,
            use_agent=use_agent,
            api_shape=str(getattr(self.settings, "llm_api_shape", "")),
            on_step=lambda i, m: self._write_status(node_id, n, step=i, steps=m),
        )
        d = self.root(node_id, n)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "report.json.tmp"
        tmp.write_text(report.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(d / "report.json")
        if (d / "applied.json").is_file():  # a new report replaces the rows of the old one
            self._apply_rows(node_id, n, report, replace=True)
        return report

    # ------------------------------------------------------------------ downstream
    def downstream(self, report: CodeAnalysisReport) -> list[dict[str, Any]]:
        """Which facts the report would add, grouped by fact kind (the "Use in assessment" preview)."""
        rows = rows_of(report, node_id="-", n=report.attempt_n)
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            g = out.setdefault(r["kind"], {"kind": r["kind"], "count": 0, "examples": []})
            g["count"] += 1
            if len(g["examples"]) < 3:
                g["examples"].append(r["name"])
        return sorted(out.values(), key=lambda g: g["kind"])

    def _applied(self, node_id: str, n: int) -> list[str]:
        p = self.root(node_id, n) / "applied.json"
        if not p.is_file():
            return []
        try:
            return list(json.loads(p.read_text(encoding="utf-8")).get("fact_ids") or [])
        except (OSError, ValueError):
            return []

    def apply(self, node_id: str, n: int | None, actor: str) -> dict[str, Any]:
        require_on(self.settings)
        n = n if n is not None else self._built_attempt(node_id)
        rep = self.report(node_id, n) if n is not None else None
        if rep is None or n is None:
            raise CodeAgentError("no_report", "run the analysis first")
        if rep.mode != "agent":
            raise CodeAgentError(
                "no_agent_findings", "this report has no agent findings (no model answered)"
            )
        ids = self._apply_rows(node_id, n, rep, replace=True, actor=actor)
        return {"attempt_n": n, "facts_written": len(ids)}

    def _apply_rows(
        self, node_id: str, n: int, report: CodeAnalysisReport, *, replace: bool, actor: str = ""
    ) -> list[str]:
        rows = rows_of(report, node_id=node_id, n=n)
        now = self.clock.now()
        old = {
            r["fact_id"]: r
            for r in self.state.query("onboard_facts", {"node_id": node_id, "attempt_n": n})
        }
        keep: set[str] = set()
        for row in rows:
            keep.add(row["fact_id"])
            cur = old.get(row["fact_id"])
            if cur is None:
                self.state.insert("onboard_facts", {**row, "created_at": now})
            else:
                changes = {k: v for k, v in row.items() if k not in ("fact_id", "node_id")}
                self.state.update(
                    "onboard_facts", {"fact_id": row["fact_id"]}, changes, cur["row_version"]
                )
        prior = set(self._applied(node_id, n))
        for fid in prior - keep:
            cur = old.get(fid)
            if cur is not None and str(cur.get("active")).lower() not in ("false", "0"):
                self.state.update(
                    "onboard_facts", {"fact_id": fid}, {"active": False}, cur["row_version"]
                )
        d = self.root(node_id, n)
        d.mkdir(parents=True, exist_ok=True)
        (d / "applied.json").write_text(
            json.dumps({"fact_ids": sorted(keep), "actor": actor}), encoding="utf-8"
        )
        return sorted(keep)

    def fact_rows(self, node_id: str, n: int) -> list[dict[str, Any]]:
        """Rows to keep on a facts re-read: those of an applied report (empty when not applied)."""
        if not getattr(self.settings, "code_agent_enabled", False) or not self._applied(node_id, n):
            return []
        rep = self.report(node_id, n)
        return rows_of(rep, node_id=node_id, n=n) if rep is not None and rep.mode == "agent" else []


def _now(clock: Any) -> str:
    t = clock.now()
    return t.isoformat() if hasattr(t, "isoformat") else str(t)


# ----------------------------------------------------------------------------- rows


def rows_of(report: CodeAnalysisReport, *, node_id: str, n: int) -> list[dict[str, Any]]:
    """``onboard_facts`` rows for the agent's own findings and the risk summaries built from the
    merged report. Rows follow the conventions of ``onboard.facts`` (kind, name, detail, file,
    line, quote, source, model_id)."""
    from supervisor.onboard.facts import MAX_DETAIL, MAX_QUOTE, fact_id_for

    model_id = _clean(f"code-agent:{report.model.model_id if report.model else 'none'}", 120)
    out: dict[str, dict[str, Any]] = {}

    def add(kind: str, name: str, detail: str, f: Finding) -> None:
        ev = f.evidence[0]
        nm = _clean(name, 200) or kind
        fid = fact_id_for(node_id, n, kind, nm, ev.file, ev.line)
        out.setdefault(
            fid,
            {
                "fact_id": fid,
                "node_id": node_id,
                "attempt_n": n,
                "kind": kind,
                "name": nm,
                "detail": _clean(detail, MAX_DETAIL),
                "file": _clean(ev.file, 300),
                "line": int(ev.line),
                "quote": _clean(ev.quote, MAX_QUOTE),
                "source": MODEL_SOURCE,
                "model_id": model_id,
                "dropped_claims": None,
                "active": True,
            },
        )

    for f in report.findings:
        a = f.attrs
        if f.source == "agent":
            if f.kind == "tool":
                eff = str(a.get("effect", "other"))
                add(
                    "tool",
                    f.name,
                    f"risk_class={RISK_CLASS.get(eff, 'pii_export')}; approved={'yes' if a.get('approval') else 'no'}; found by the code agent; effect={eff}",
                    f,
                )
            elif f.kind == "model":
                add(
                    "model",
                    f.name,
                    f"provider={a.get('provider', 'unknown')}; family={a.get('family', 'unknown')}; via=code agent",
                    f,
                )
            elif f.kind == "egress" and a.get("internal") is not True:
                add(
                    "external_url",
                    f.name,
                    f"direction={a.get('direction', 'write')}; host found by the code agent",
                    f,
                )
            elif f.kind == "hitl":
                add(
                    "approval_point",
                    f"human approval ({a.get('mode')})",
                    f"guards: {a.get('guards', '-')}; found by the code agent",
                    f,
                )
            elif f.kind == "data_flow" and a.get("target"):
                add(
                    "dataset",
                    str(a["target"]),
                    f"direction={a.get('direction')}; via={a.get('sink')}; tool={a.get('tool')}",
                    f,
                )
            elif f.kind == "guardrail":
                add(
                    "claim",
                    f"guardrail: {a.get('guard')}",
                    f"scope={a.get('scope', '-')}; category=guardrail",
                    f,
                )
            elif f.kind == "secret_handling" and a.get("source") == "hardcoded":
                add(
                    "secret_use",
                    "hardcoded secret",
                    "a secret is set in code (kind only; value never stored)",
                    f,
                )
            elif f.kind == "pii" and a.get("tool"):
                add("claim", f"personal data: {f.name}", "category=personal_data", f)
        if f.kind == "logging" and a.get("logs_pii") is True:
            add("weak_spot", "personal data is written to the log", f"sink={a.get('sink')}", f)
        if (
            f.kind == "tool"
            and a.get("irreversible") is True
            and a.get("approval") is not True
            and (f.source == "agent" or any(b == "agent" for b in f.attr_basis.values()))
        ):
            add(
                "weak_spot",
                f"{f.name}: irreversible action without a human approval step",
                f"effect={a.get('effect')}; found by the code agent",
                f,
            )
    return list(out.values())
