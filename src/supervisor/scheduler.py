"""In-process scheduler (ADR D09): APScheduler inside the app process, one leader only.

Jobs (interval in seconds from Settings; each also runs as ``python -m supervisor.jobs.X``):

=============  =====================  ===============================================
job            enabled by             does
=============  =====================  ===============================================
ingest         scheduler on           drain the recorder spool into ``agent_event``
anchor         scheduler on           ``commit_root`` on the app's chain writer (the
                                      chain seals when quiet) + anchor the signed root
drift          DRIFT_ENABLED          drift bands and drift cases
fairness       FAIRNESS_ENABLED       fairness slices
metrics        METRICS_ENABLED        daily ``oversight_metric`` rows
multiagent     MULTIAGENT_ENABLED     split payment across callers
case_intake    scheduler on           gate block/pause verdicts become cases (also run once
                                      at scheduler start; the console GET never writes)
judge_sweep    JUDGE_ENABLED          advisory judges over new events
quality        QUALITY_ENABLED        groundedness / guideline scores (sampled)
retention      RETENTION_ENABLED      null personal-data columns past their TTL (ADR D13)
=============  =====================  ===============================================

The scheduler itself is on when ``SCHEDULER_ENABLED`` is set true, or unset in laptop
mode. One APScheduler interval job ("tick", every ``tick_s``) runs every due job in turn
(one thread, no overlap). Each job's last run is kept in ``monitor_state``, so after a
restart a missed run is caught up at the first tick (D09). Before each tick the
scheduler takes or renews a lease: a file lock on the laptop (``SCHEDULER_LOCK_PATH``),
a ``scheduler_lease`` row with ``row_version`` on Databricks. A replica without the
lease runs nothing. A failing job is logged and recorded; the other jobs still run.

Every job that writes evidence uses the app's own chain writer (single writer per lane).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError
from supervisor.core.ports import Clock, StateStore
from supervisor.monitors.common import MonitorContext, as_dt, get_state, put_state

log = logging.getLogger("supervisor.scheduler")

LEASE_NAME = "supervisor-scheduler"
MONITOR = "scheduler"
START_DELAY_S = 15  # first tick after startup (the app finishes starting first)
DEFAULT_TICK_S = 15
STARTUP_JOBS = ("case_intake",)  # also run once, at once, when the scheduler starts


# --------------------------------------------------------------------------- leases


class Lease(Protocol):
    holder: str

    def acquire(self, now: datetime) -> bool:
        """Take or renew the lease until ``now + ttl``. False when another holder has it."""
        ...

    def release(self) -> None: ...


def default_holder() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class FileLease:
    """Laptop lease: a JSON file ``{holder, expires_at}``; a guard file serialises edits."""

    GUARD_STALE_S = 30

    def __init__(self, path: Path, ttl_s: int, holder: str | None = None) -> None:
        self.path = Path(path)
        self.guard = self.path.with_name(self.path.name + ".guard")
        self.ttl = timedelta(seconds=ttl_s)
        self.holder = holder or default_holder()
        self._now: datetime | None = None

    def _read(self) -> dict[str, Any]:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return doc if isinstance(doc, dict) else {}

    def _take_guard(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - self.guard.stat().st_mtime
                except OSError:
                    continue
                if age > self.GUARD_STALE_S:  # a crashed process left it
                    self.guard.unlink(missing_ok=True)
                    continue
                return False
            os.close(fd)
            return True
        return False

    def acquire(self, now: datetime) -> bool:
        if not self._take_guard():
            return False
        try:
            doc = self._read()
            held_by_other = (
                doc.get("holder") not in (None, self.holder)
                and doc.get("expires_at")
                and as_dt(doc["expires_at"]) > now
            )
            if held_by_other:
                return False
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            tmp.write_text(
                json.dumps({"holder": self.holder, "expires_at": format_ts(now + self.ttl)}),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
            return True
        finally:
            self.guard.unlink(missing_ok=True)

    def release(self) -> None:
        if not self._take_guard():
            return
        try:
            if self._read().get("holder") == self.holder:
                self.path.unlink(missing_ok=True)
        finally:
            self.guard.unlink(missing_ok=True)


class StateLease:
    """Databricks lease: one ``scheduler_lease`` row, optimistic concurrency on row_version."""

    def __init__(
        self, state: StateStore, ttl_s: int, holder: str | None = None, name: str = LEASE_NAME
    ) -> None:
        self.state = state
        self.ttl = timedelta(seconds=ttl_s)
        self.holder = holder or default_holder()
        self.name = name

    def acquire(self, now: datetime) -> bool:
        key = {"lease_name": self.name}
        row = self.state.get("scheduler_lease", key)
        try:
            if row is None:
                self.state.insert(
                    "scheduler_lease",
                    {
                        **key,
                        "holder": self.holder,
                        "acquired_at": now,
                        "expires_at": now + self.ttl,
                    },
                )
                return True
            if row["holder"] != self.holder and as_dt(row["expires_at"]) > now:
                return False
            changes: dict[str, Any] = {"holder": self.holder, "expires_at": now + self.ttl}
            if row["holder"] != self.holder:
                changes["acquired_at"] = now
            self.state.update("scheduler_lease", key, changes, row["row_version"])
            return True
        except (DuplicateKeyError, ConcurrencyError):
            return False  # another replica won the race

    def release(self) -> None:
        key = {"lease_name": self.name}
        row = self.state.get("scheduler_lease", key)
        if row is None or row["holder"] != self.holder:
            return
        try:
            self.state.update(
                "scheduler_lease", key, {"expires_at": as_dt(row["acquired_at"])},
                row["row_version"],
            )  # fmt: skip
        except ConcurrencyError:
            pass


def build_lease(settings: Any, state: StateStore) -> Lease:
    if settings.effective_sql_backend == "sqlite":
        return FileLease(settings.scheduler_lock_path, settings.scheduler_lease_ttl_s)
    return StateLease(state, settings.scheduler_lease_ttl_s)


# --------------------------------------------------------------------------- scheduler


@dataclass
class JobSpec:
    name: str
    interval_s: int
    fn: Callable[[], Any]
    enabled: bool = True


@dataclass
class JobRun:
    name: str
    status: str  # ok | error | skipped
    result: Any = None
    error: str | None = None


class SupervisorScheduler:
    def __init__(
        self,
        jobs: list[JobSpec],
        *,
        ctx: MonitorContext,
        lease: Lease,
        clock: Clock | None = None,
        tick_s: int = DEFAULT_TICK_S,
    ) -> None:
        self.jobs = {j.name: j for j in jobs}
        self.ctx = ctx
        self.lease = lease
        self.clock = clock or ctx.clock
        self.tick_s = tick_s
        self._lock = threading.Lock()
        self._aps: Any = None

    # -- core (deterministic; tests drive it with a fixed clock) ---------------------
    def last_run(self, name: str) -> datetime | None:
        state = get_state(self.ctx, MONITOR, f"last:{name}")
        return as_dt(state["ts"]) if state and state.get("ts") else None

    def due(self, now: datetime | None = None) -> list[str]:
        now = now or self.clock.now()
        out = []
        for job in self.jobs.values():
            if not job.enabled:
                continue
            last = self.last_run(job.name)
            if last is None or now - last >= timedelta(seconds=job.interval_s):
                out.append(job.name)
        return out

    def run_job(self, name: str) -> JobRun:
        job = self.jobs[name]
        started = self.clock.now()
        try:
            run = JobRun(name, "ok", job.fn())
        except Exception as exc:  # noqa: BLE001 - one failing job must not stop the others
            log.exception("scheduled job %s failed", name)
            run = JobRun(name, "error", error=f"{type(exc).__name__}: {exc}"[:300])
        try:
            put_state(
                self.ctx,
                MONITOR,
                f"last:{name}",
                {"ts": format_ts(started), "status": run.status, "error": run.error},
            )
        except Exception:  # noqa: BLE001 - the store may be what failed
            log.exception("could not record the last run of %s", name)
        return run

    def tick(self) -> dict[str, JobRun]:
        """Run every due job once, if this process holds the lease."""
        if not self._lock.acquire(blocking=False):
            return {}
        try:
            now = self.clock.now()
            try:
                leader = self.lease.acquire(now)
            except Exception:  # noqa: BLE001
                log.exception("scheduler lease check failed")
                leader = False
            if not leader:
                return {}
            out: dict[str, JobRun] = {}
            for name in self.due(now):
                out[name] = self.run_job(name)
                self.lease.acquire(self.clock.now())  # renew between long jobs
            return out
        finally:
            self._lock.release()

    def run_now(self, names: list[str]) -> dict[str, JobRun]:
        """Run the named jobs once, now, if this process holds the lease (startup run)."""
        if not self._lock.acquire(blocking=False):
            return {}
        try:
            try:
                if not self.lease.acquire(self.clock.now()):
                    return {}
            except Exception:  # noqa: BLE001
                log.exception("scheduler lease check failed")
                return {}
            return {n: self.run_job(n) for n in names if n in self.jobs and self.jobs[n].enabled}
        finally:
            self._lock.release()

    # -- APScheduler ---------------------------------------------------------------
    def start(self, start_delay_s: int = START_DELAY_S) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        aps = BackgroundScheduler(timezone=UTC, daemon=True)
        aps.add_job(
            self.tick,
            IntervalTrigger(seconds=self.tick_s, timezone=UTC),
            id="supervisor-tick",
            next_run_time=datetime.now(UTC) + timedelta(seconds=start_delay_s),
            max_instances=1,
            coalesce=True,
            misfire_grace_time=None,
        )
        aps.add_job(
            self.run_now,
            args=[list(STARTUP_JOBS)],
            id="supervisor-startup",
            next_run_time=datetime.now(UTC),
            max_instances=1,
            misfire_grace_time=None,
        )
        aps.start()
        self._aps = aps
        log.info(
            "scheduler started (holder %s): %s",
            self.lease.holder,
            ", ".join(f"{j.name}/{j.interval_s}s" for j in self.jobs.values() if j.enabled),
        )

    @property
    def running(self) -> bool:
        return self._aps is not None and bool(self._aps.running)

    def shutdown(self) -> None:
        aps, self._aps = self._aps, None
        if aps is not None:
            aps.shutdown(wait=True)
        try:
            self.lease.release()
        except Exception:  # noqa: BLE001
            log.exception("scheduler lease release failed")


# --------------------------------------------------------------------------- wiring


def build_jobs(settings: Any, runtime: Any, ctx: MonitorContext) -> list[JobSpec]:
    """The job list for the app. ``runtime`` is ``supervisor.wiring.Runtime``."""
    from supervisor.jobs import anchor as anchor_job
    from supervisor.jobs import case_intake as case_intake_job
    from supervisor.jobs import drift as drift_job
    from supervisor.jobs import fairness as fairness_job
    from supervisor.jobs import ingest as ingest_job
    from supervisor.jobs import judge_sweep as judge_job
    from supervisor.jobs import metrics as metrics_job
    from supervisor.jobs import multiagent as multiagent_job
    from supervisor.jobs import quality as quality_job
    from supervisor.jobs import retention as retention_job
    from supervisor.monitors.sweeps import build_judge_sweep, build_quality_sweep

    adapters = runtime.adapters
    cases: list[Any] = []

    def case_service() -> Any:
        if not cases:  # the console's case service when the app built one (it notifies)
            from supervisor.cases import build_case_service
            from supervisor.console.context import peek_context

            ctx_ = peek_context()
            cases.append(ctx_.cases if ctx_ is not None else build_case_service(runtime))
        return cases[0]

    def intake() -> list[str]:
        return case_intake_job.run(case_service())

    def inventory() -> Any:  # WP24: manifests + workspace + shadow-AI cases
        from supervisor.jobs import inventory as inventory_job

        return inventory_job.run(adapters, settings, cases=case_service())

    judge = quality = None
    if settings.judge_enabled:
        try:
            judge = build_judge_sweep(ctx, settings)
        except Exception:  # noqa: BLE001 - e.g. FamilyConflictError: log, run without it
            log.exception("judge sweep disabled: the judge service could not be built")
    if settings.quality_enabled:
        try:
            quality = build_quality_sweep(ctx, settings)
        except Exception:  # noqa: BLE001
            log.exception("quality sweep disabled: the scorer could not be built")
    jobs = [
        JobSpec("ingest", settings.sched_ingest_s, lambda: ingest_job.run(settings, adapters)),
        JobSpec(
            "anchor",
            settings.sched_anchor_s,
            lambda: anchor_job.run(settings, adapters, writer=runtime.chain, seal=True),
        ),
        JobSpec("case_intake", settings.sched_case_intake_s, intake),
        JobSpec("drift", settings.sched_drift_s, lambda: drift_job.run(ctx, settings),
                settings.drift_enabled),
        JobSpec("fairness", settings.sched_fairness_s, lambda: fairness_job.run(ctx, settings),
                settings.fairness_enabled),
        JobSpec("metrics", settings.sched_metrics_s, lambda: metrics_job.run(ctx, settings),
                settings.metrics_enabled),
        JobSpec("multiagent", settings.sched_multiagent_s,
                lambda: multiagent_job.run(ctx, settings), settings.multiagent_enabled),
        JobSpec("judge_sweep", settings.sched_judge_s,
                lambda: judge_job.run(ctx, settings, judge), judge is not None),
        JobSpec("quality", settings.sched_quality_s,
                lambda: quality_job.run(ctx, settings, quality), quality is not None),
        JobSpec("retention", settings.sched_retention_s,
                lambda: retention_job.run(settings, adapters, chain=runtime.chain),
                settings.retention_enabled),
    ]  # fmt: skip
    from supervisor.jobs import inventory as inventory_job

    if inventory_job.scheduled(settings):  # WP24: listed only when it can run
        jobs.append(JobSpec("inventory", settings.sched_inventory_s, inventory))
    return jobs


def build_scheduler(settings: Any, runtime: Any) -> SupervisorScheduler:
    ctx = MonitorContext.from_adapters(runtime.adapters, runtime.chain)
    return SupervisorScheduler(
        build_jobs(settings, runtime, ctx),
        ctx=ctx,
        lease=build_lease(settings, runtime.adapters.state),
    )


_lock = threading.Lock()
_scheduler: SupervisorScheduler | None = None


def start_for_runtime(settings: Any, runtime: Any) -> SupervisorScheduler | None:
    """Start the process scheduler (app lifespan). None when the scheduler is off."""
    global _scheduler
    if not settings.scheduler_on:
        log.info("scheduler off (SCHEDULER_ENABLED)")
        return None
    with _lock:
        if _scheduler is None:
            sched = build_scheduler(settings, runtime)
            sched.start()
            _scheduler = sched
        return _scheduler


def stop() -> None:
    """Stop the process scheduler (app lifespan shutdown, before the chain is sealed)."""
    global _scheduler
    with _lock:
        sched, _scheduler = _scheduler, None
    if sched is not None:
        sched.shutdown()


def current() -> SupervisorScheduler | None:
    return _scheduler


__all__ = [
    "FileLease",
    "JobRun",
    "JobSpec",
    "StateLease",
    "SupervisorScheduler",
    "build_jobs",
    "build_lease",
    "build_scheduler",
    "current",
    "start_for_runtime",
    "stop",
]
