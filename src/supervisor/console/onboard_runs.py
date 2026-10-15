"""Onboard from the console (WP12): one background run at a time, plus the last-run cards.

The run is the real ``supervisor.onboard.run.run_onboarding`` on the console's own store and
chain writer (one writer per store), so the Onboarding Agent runs under Watch as from the
CLI. The model is MockChat (labelled mock) unless the configured LLM endpoint answers the
preflight probe. Off by default: ``CONSOLE_ONBOARD_ENABLED=1`` turns the Start form on; the
last-run cards always show what is on disk.

Artefacts land in ``<data_dir>/onboard/<agent folder name>/`` (same place as the demo).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.core.errors import SupervisorError

log = logging.getLogger("supervisor.console")

AGENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# What a run writes (supervisor.onboard.run.ARTEFACTS); the console serves only these.
ARTEFACTS = (
    "inventory.json",
    "profile.json",
    "profile.md",
    "plan.json",
    "plan.md",
    "playbook.md",
    "policy.yaml",
    "dashboard.json",
    "alert_routes.yaml",
    "pr_description.md",
    "launch_report.json",
    "launch_report.md",
    "baseline.json",
    "handover.json",
)
MAX_LINES = 400


class OnboardInputError(SupervisorError):
    """The Onboard start request cannot run (HTTP 400)."""


@dataclass
class OnboardJob:
    key: str
    target: str
    agent: str
    out_dir: Path
    started_at: dt.datetime
    started_by: str
    mock: bool
    status: str = "running"  # running | done | failed
    error: str = ""
    finished_at: dt.datetime | None = None
    go: bool | None = None
    lines: list[str] = field(default_factory=list)

    def say(self, line: str) -> None:
        if len(self.lines) < MAX_LINES:
            self.lines.append(line)


def onboard_root(settings: Any) -> Path:
    return Path(settings.data_dir) / "onboard"


def resolve_target(raw: str) -> Path:
    """A folder inside a git repo. Relative paths are taken from the repo root."""
    text = (raw or "").strip()
    if not text or len(text) > 512 or "\x00" in text:
        raise OnboardInputError("give the folder of the agent to onboard")
    p = Path(text)
    if not p.is_absolute():
        p = REPO_ROOT / p
    p = Path(os.path.abspath(p))
    if not p.is_dir():
        raise OnboardInputError(f"folder not found: {text}")
    if p.parent == p:
        raise OnboardInputError("choose the agent's folder, not a drive root")
    if not AGENT_RE.match(p.name):
        raise OnboardInputError("the agent folder name may use letters, digits, _ . - only")
    return p


class OnboardRunner:
    """Holds the current and recent console runs (in memory; the artefacts are on disk)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, OnboardJob] = {}
        self._order: list[str] = []

    def get(self, key: str) -> OnboardJob | None:
        with self._lock:
            return self._jobs.get(key)

    def latest(self) -> OnboardJob | None:
        with self._lock:
            return self._jobs[self._order[-1]] if self._order else None

    def running(self) -> OnboardJob | None:
        with self._lock:
            for key in reversed(self._order):
                if self._jobs[key].status == "running":
                    return self._jobs[key]
        return None

    def start(self, ctx: Any, target: Path, actor: Any, *, chat: Any | None = None) -> OnboardJob:
        with self._lock:
            if any(j.status == "running" for j in self._jobs.values()):
                raise OnboardInputError("an onboarding run is already in progress; wait for it")
            chat = chat or pick_chat(ctx.settings)
            job = OnboardJob(
                key=uuid.uuid4().hex[:12],
                target=str(target),
                agent=target.name,
                out_dir=onboard_root(ctx.settings) / target.name,
                started_at=ctx.clock.now(),
                started_by=actor.user_id,
                mock=bool(getattr(chat, "is_mock", False)),
            )
            self._jobs[job.key] = job
            self._order.append(job.key)
            del self._order[:-10]
            for k in list(self._jobs):
                if k not in self._order:
                    del self._jobs[k]
        thread = threading.Thread(
            target=self._run, args=(ctx, job, chat), name=f"onboard-{job.agent}", daemon=True
        )
        thread.start()
        return job

    def _run(self, ctx: Any, job: OnboardJob, chat: Any) -> None:
        from supervisor.onboard.run import run_onboarding

        job.say(f"[OK] start {job.agent} (by {job.started_by}, model {chat.model_id})")
        try:
            result = run_onboarding(
                job.target,
                job.out_dir,
                settings=ctx.settings,
                adapters=ctx.runtime.adapters,
                evidence=ctx.runtime.chain,
                chat=chat,
                echo=job.say,
            )
            job.go = bool(result.launch.go)
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 - a failed run is shown, never a crash
            job.status = "failed"
            job.error = (
                f"{type(exc).__name__}: {str(exc).splitlines()[0][:300] if str(exc) else ''}"
            )
            job.say(f"[FAIL] {job.error}")
            log.warning("console onboarding run failed: %s", type(exc).__name__)
        finally:
            job.finished_at = ctx.clock.now()


def pick_chat(settings: Any) -> Any:
    """MockChat unless an LLM is configured and answers (the preflight probe, 3 s)."""
    from supervisor.adapters.llm.mock import MockChat

    mock = MockChat(model_id="mock-onboarding-v1")
    if getattr(settings, "llm_mock", False) or not getattr(settings, "llm_base_url", ""):
        return mock
    try:
        from supervisor.adapters.factory import make_chat_model
        from supervisor.preflight import _check_llm

        if _check_llm(settings).status != "OK":
            return mock
        return make_chat_model(settings)
    except Exception:  # noqa: BLE001 - no reachable model: the mock, labelled
        return mock


# ---------------------------------------------------------------------------- last runs


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def run_summary(out_dir: Path) -> dict[str, Any]:
    """Cards for one run folder: profile, plan and launch report, plus the files."""
    profile = _load(out_dir / "profile.json") or {}
    plan = _load(out_dir / "plan.json") or {}
    launch = _load(out_dir / "launch_report.json") or {}
    handover = _load(out_dir / "handover.json") or {}
    files = [n for n in ARTEFACTS if (out_dir / n).is_file()]
    tools = profile.get("tool_risk_classes") or {}
    d33 = profile.get("decision33") or {}
    caps = plan.get("capabilities") or []
    rules = plan.get("rules") or []
    stamp = max(((out_dir / n).stat().st_mtime for n in files), default=0.0)
    return {
        "agent": out_dir.name,
        "files": files,
        "updated": dt.datetime.fromtimestamp(stamp, dt.UTC) if stamp else None,
        "profile": {
            "present": bool(profile),
            "d33": d33.get("classification"),
            "human_gate": d33.get("human_gate_in_code"),
            "tools": len(tools),
            "money": sum(1 for c in tools.values() if c == "money"),
            "risk": profile.get("proposed_risk_tier"),
            "mock": bool((profile.get("llm") or {}).get("is_mock")),
        },
        "plan": {
            "present": bool(plan),
            "caps_on": sum(1 for c in caps if c.get("status") == "on"),
            "caps": len(caps),
            "rules": len(rules),
            "stop_rules": sum(
                1 for r in rules if (r.get("spec") or {}).get("action") in ("block", "pause")
            ),
            "judges": [
                {"id": j.get("id"), "sample_bp": j.get("sample_bp")} for j in plan.get("judges", [])
            ],
        },
        "launch": {
            "present": bool(launch),
            "go": launch.get("go"),
            "caught": launch.get("rule_caught"),
            "expected": launch.get("rule_expected"),
            "catch_bp": launch.get("catch_rate_bp"),
            "false_bp": launch.get("false_alarm_bp"),
            "benign": launch.get("benign_cases"),
            "flagged": launch.get("benign_flagged"),
            "mock": launch.get("llm_is_mock"),
            "reasons": launch.get("reasons") or [],
        },
        "branch": handover.get("branch"),
        "commit": (handover.get("commit_sha") or "")[:10],
    }


def last_runs(settings: Any, limit: int = 3) -> list[dict[str, Any]]:
    root = onboard_root(settings)
    if not root.is_dir():
        return []
    dirs = [d for d in root.iterdir() if d.is_dir() and AGENT_RE.match(d.name)]
    runs = [run_summary(d) for d in dirs]
    runs = [r for r in runs if r["files"]]
    runs.sort(key=lambda r: r["updated"] or dt.datetime.min.replace(tzinfo=dt.UTC), reverse=True)
    return runs[:limit]


def artefact_path(settings: Any, agent: str, name: str) -> Path:
    if not AGENT_RE.match(agent or "") or name not in ARTEFACTS:
        raise OnboardInputError("unknown onboarding artefact")
    path = onboard_root(settings) / agent / name
    if not path.is_file():
        raise OnboardInputError(f"{agent}/{name} does not exist")
    return path
