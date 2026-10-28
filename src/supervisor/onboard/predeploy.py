"""Pre-deploy assessment (WP-O3, phase 9, flag ONBOARD_PREDEPLOY).

One report per run for one intake attempt of a candidate or an agent. The run fills five sections,
in this order, and goes on when one section breaks (that section becomes one item with status
``fail`` and the reason):

1. ``facts``     the active ``onboard_facts`` rows of the attempt (WP-O2). Weak spots, secret use
                 and external addresses are ``warn`` items. No facts: a ``question`` item.
2. ``readiness`` the integration readiness advisor (``systems_wizard.scan_folder``) on the stored,
                 scrubbed tree.
3. ``packs``     the assurance packs with ``launch_gate: required``, run on the attempt in the
                 launch sandbox (gate in SHADOW, synthetic world). A skip is a ``fail`` for a
                 required pack, as in ``docs/assurance.md``, except a structured "not applicable".
                 With ``PREDEPLOY_HTTP_TARGET`` on and an ``http_target`` block on the candidate
                 (WP-O3b), the packs that need a running agent send synthetic turns to the
                 candidate's HTTP chat endpoint instead (``HttpAgentTarget``); each pack item says
                 which target ran (``target: http <host>``, ``sandbox demo`` or ``no harness``).
4. ``multiturn`` the multi-turn red-team pack (``launch_gate: advisory``): never blocks. It uses
                 the same target as ``packs``.
5. ``duties``    the duties matrix (WP-L2) when ``CONSOLE_REGISTER_DUTIES`` is on and a register
                 draft exists for the node; else the ``question`` item "duties: not run".

The verdict is a pure function of the items (``verdict_of``): ``no_go`` when any item with status
``fail`` sits in a required section, else ``questions`` when any item is a ``question``, else
``go``. The model is never asked for the verdict (the facts step uses the gateway model through
``FactsService``; a mock model is named ``mock`` in the facts summary and in the item text).

The run is one background thread per start, one at a time per node (``already_running``). Items
hold no personal data (every text goes through the scrubber) and no floats.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.core.errors import SupervisorError
from supervisor.evidence.chain import check_no_floats
from supervisor.onboard import facts as facts_mod
from supervisor.onboard import intake
from supervisor.onboard.scrub import scrub_text

log = logging.getLogger(__name__)

SECTIONS = ("facts", "readiness", "packs", "multiturn", "duties")
REQUIRED_SECTIONS = ("facts", "readiness", "packs")
STATUSES = ("ok", "warn", "fail", "question", "skip")
VERDICTS = ("go", "no_go", "questions", "none")
MULTITURN_PACK = "multiturn_redteam_vi"
FLAG_TEXT = "the pre-deploy assessment is off (ONBOARD_PREDEPLOY=1 turns it on)"
MAX_TEXT = 300
MAX_POINTER = 200
MAX_SUMMARY = 2000
MAX_ITEMS = 300
PER_GROUP = 40
STALE_S = 1800  # a queued or running row older than this, with no thread, was cut by a restart
READINESS_OK = 80  # same limit as register step 3
BAND_TEXT = {
    "ux4b_band_ready": "ready",
    "ux4b_band_patches": "patches needed",
    "ux4b_band_work": "work needed",
}
_LOCK = threading.RLock()
_RUNNING: dict[str, str] = {}  # node id -> report id of the run that has a thread now
_THREADS: dict[str, threading.Thread] = {}


class PredeployError(SupervisorError):
    """A refused request. ``code`` is the stable machine word; the message starts with it."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def require_on(settings: Any) -> None:
    if not settings.onboard_predeploy:
        raise PredeployError("predeploy_off", FLAG_TEXT)


def _clean(text: Any, limit: int) -> str:
    raw = "".join(c if c in " " or ord(c) >= 32 else " " for c in str(text or ""))
    return " ".join(scrub_text(raw).text.split())[:limit]


def make_item(section: str, item_id: str, status: str, text: str, pointer: str) -> dict[str, str]:
    """One item. The text is scrubbed and cut, the pointer too. A bad status is a programming
    error."""
    if section not in SECTIONS or status not in STATUSES:
        raise ValueError(f"bad item: {section!r} {status!r}")
    return {
        "section": section,
        "id": _clean(item_id, 120) or section,
        "status": status,
        "text": _clean(text, MAX_TEXT),
        "pointer": _clean(pointer, MAX_POINTER) or "-",
    }


def verdict_of(items: Sequence[Mapping[str, Any]]) -> str:
    """The verdict from the items alone. A fail item in a required section is NO-GO; else an
    open question; else GO. Pure and deterministic; no model."""
    if any(i["status"] == "fail" and i["section"] in REQUIRED_SECTIONS for i in items):
        return "no_go"
    if any(i["status"] == "question" for i in items):
        return "questions"
    return "go"


def counts_of(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for i in items:
        out[i["status"]] += 1
    return out


def _as_ts(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return format_ts(value)


# ------------------------------------------------------------------------------ target


def agent_id_of(tree: Path, node_id: str) -> str:
    """The agent id the packs run for: the node id, or the manifest id of the tree when that is
    one of the demo agents (the only agents that have a launch harness)."""
    from supervisor.assurance.targets import DEMO_AGENTS

    if node_id in DEMO_AGENTS:
        return node_id
    try:
        import yaml

        for path in [tree / "manifest.yaml", *sorted(tree.glob("*/manifest.yaml"))]:
            if path.is_file() and path.stat().st_size <= 256 * 1024:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                mid = str((data or {}).get("id") or "") if isinstance(data, dict) else ""
                if mid in DEMO_AGENTS:
                    return mid
    except Exception:  # noqa: BLE001 - an unreadable manifest only means "not a demo agent"
        log.debug("predeploy: manifest not read")
    return node_id


def build_target(tree: Path, agent_id: str, work_dir: Path, settings: Any) -> Any:
    """The target the packs run on. A demo agent runs in the launch sandbox (gate in SHADOW,
    synthetic world, mock agent LLM: every result says mock). Any other tree has no launch
    harness: it becomes an offline ``RepoAgentTarget`` that can answer the static packs (pins,
    licences, tool manifest) and not the ones that need the agent to run."""
    from supervisor.assurance.targets import DEMO_AGENTS, DemoAgentTarget, RepoAgentTarget

    if agent_id in DEMO_AGENTS:
        return DemoAgentTarget(agent_id, work_dir, settings=settings)
    return RepoAgentTarget(agent_id, tree)


# ------------------------------------------------------------------------------ service


class PredeployService:
    """Starts, runs and reads pre-deploy reports.

    ``ctx`` (the console context) is needed only for the duties section; without it that section
    is the question "duties: not run". ``chat_factory``, ``target_factory`` and ``executor`` exist
    for unit tests (a fake chat adapter, a fake target, a fake pack engine); the product path
    uses the gateway model, ``build_target`` and ``assurance.engine.execute``."""

    def __init__(
        self,
        settings: Any,
        state: Any,
        clock: Any,
        *,
        ctx: Any = None,
        chat_factory: Callable[[], Any] | None = None,
        target_factory: Callable[[Path, str, Path, Any], Any] | None = None,
        executor: Callable[..., list[Any]] | None = None,
        http_transport: Any = None,
        http_auth: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        self.settings = settings
        self.state = state
        self.clock = clock
        self.ctx = ctx
        self._chat_factory = chat_factory
        self._target_factory = target_factory or build_target
        self._executor = executor
        # WP-O3b: tests inject a local transport and a fake auth header; the product path uses
        # httpx and the service principal of the Supervisor (never a stored token).
        self._http_transport = http_transport
        self._http_auth = http_auth

    # ------------------------------------------------------------------ read
    def _rows(self, node_id: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.state.query("predeploy_report", {"node_id": node_id})]
        rows.sort(key=lambda r: (str(_as_ts(r["created_at"])), int(r.get("row_version") or 1)))
        return rows

    def latest(self, node_id: str) -> dict[str, Any] | None:
        """The newest report of the node as a view, or ``None``."""
        intake.check_node_id(node_id)
        rows = self._rows(node_id)
        return view(rows[-1]) if rows else None

    def has_report(self, node_id: str) -> bool:
        return bool(self.state.query("predeploy_report", {"node_id": node_id}, limit=1))

    def get(self, report_id: str) -> dict[str, Any] | None:
        row = self.state.get("predeploy_report", {"report_id": report_id})
        return view(dict(row)) if row is not None else None

    def join(self, node_id: str, timeout: float = 120.0) -> None:
        """Wait for the thread of ``node_id`` (tests, and a clean shutdown)."""
        th = _THREADS.get(node_id)
        if th is not None:
            th.join(timeout)

    # ------------------------------------------------------------------ start
    def start(self, node_id: str, n: int, by: str, *, background: bool = True) -> dict[str, Any]:
        """Write a ``queued`` report for attempt ``n`` and run it in a background thread. One run
        at a time per node: a second start while one runs answers ``already_running``. With
        ``background=False`` the run is finished before the call returns (tests, the CLI)."""
        require_on(self.settings)
        intake.check_node_id(node_id)
        n = int(n)
        attempt = next(
            (
                r
                for r in self.state.query("intake_attempt", {"node_id": node_id})
                if int(r["n"]) == n
            ),
            None,
        )
        if attempt is None:
            raise PredeployError("no_attempt", f"attempt {n} of {node_id} does not exist")
        if attempt["status"] == "failed":
            raise PredeployError("attempt_failed", f"attempt {n} was refused; there is no source")
        with _LOCK:
            if node_id in _RUNNING:
                raise PredeployError(
                    "already_running", f"an assessment of {node_id} is running; wait for it"
                )
            self._close_stale(node_id)
            now = self.clock.now()
            report_id = (
                "pdr_" + hashlib.sha256(f"{node_id}|{n}|{time.time_ns()}".encode()).hexdigest()[:20]
            )
            row = self.state.insert(
                "predeploy_report",
                {
                    "report_id": report_id,
                    "node_id": node_id,
                    "attempt_n": n,
                    "status": "queued",
                    "verdict": "none",
                    "started_at": now,
                    "finished_at": None,
                    "items_total": 0,
                    "items_fail": 0,
                    "items_question": 0,
                    "summary": "queued",
                    "items": "[]",
                    "model_id": None,
                    "created_by": _clean(by, 120) or "unknown",
                    "created_at": now,
                },
            )
            _RUNNING[node_id] = report_id
            if background:
                th = threading.Thread(
                    target=self._thread, args=(report_id, node_id, n), daemon=True
                )
                _THREADS[node_id] = th
        if background:
            th.start()
        else:
            self._thread(report_id, node_id, n)
        return view(dict(self.state.get("predeploy_report", {"report_id": report_id}) or row))

    def _close_stale(self, node_id: str) -> None:
        """A row left ``queued`` or ``running`` by a restart (no thread of ours) becomes failed,
        so the node is not blocked for ever."""
        for r in self.state.query("predeploy_report", {"node_id": node_id}):
            if r["status"] in ("queued", "running"):
                self._finish(
                    dict(r), "failed", "none", [], "the run was cut short (the server restarted)"
                )

    # ------------------------------------------------------------------ run
    def _thread(self, report_id: str, node_id: str, n: int) -> None:
        try:
            self.run(report_id, node_id, n)
        except Exception as exc:  # noqa: BLE001 - the thread must leave a row, never die silently
            log.warning("predeploy: run failed (%s)", type(exc).__name__)
            row = self.state.get("predeploy_report", {"report_id": report_id})
            if row is not None and row["status"] in ("queued", "running"):
                self._finish(
                    dict(row), "failed", "none", [], f"the run broke: {type(exc).__name__}"
                )
        finally:
            with _LOCK:
                if _RUNNING.get(node_id) == report_id:
                    del _RUNNING[node_id]

    def run(self, report_id: str, node_id: str, n: int) -> None:
        """Fill the five sections and store the result. A section that raises becomes one
        ``fail`` item; the others still run."""
        row = self.state.get("predeploy_report", {"report_id": report_id})
        if row is None:
            raise PredeployError("no_report", f"report {report_id} does not exist")
        row = dict(
            self.state.update(
                "predeploy_report",
                {"report_id": report_id},
                {"status": "running"},
                row["row_version"],
            )
        )
        tree = intake.IntakeService(self.settings, self.state, self.clock).tree_path(node_id, n)
        run = _Run(self, node_id, n, tree, report_id)
        items: list[dict[str, str]] = []
        try:
            for section, fn in (
                ("facts", run.facts),
                ("readiness", run.readiness),
                ("packs", run.packs),
                ("multiturn", run.multiturn),
                ("duties", run.duties),
            ):
                try:
                    items += fn()[:MAX_ITEMS]
                except Exception as exc:  # noqa: BLE001 - one section must not stop the others
                    items.append(
                        make_item(
                            section,
                            f"{section}:error",
                            "fail",
                            f"the {section} step did not run: {_reason(exc)}",
                            f"section {section}",
                        )
                    )
        finally:
            run.close()
        items = items[:MAX_ITEMS]
        verdict = verdict_of(items)
        c = counts_of(items)
        mock_note = f"; facts model: {run.model_id}" if run.model_id else ""
        summary = (
            f"verdict {verdict}: {len(items)} items, {c['fail']} fail, {c['question']} question, "
            f"{c['warn']} warn, {c['ok']} ok, {c['skip']} skip{mock_note}"
        )
        self._finish(row, "done", verdict, items, summary, run.model_id)

    def _finish(
        self,
        row: Mapping[str, Any],
        status: str,
        verdict: str,
        items: list[dict[str, str]],
        summary: str,
        model_id: str | None = None,
    ) -> None:
        check_no_floats(items)
        c = counts_of(items)
        fresh = self.state.get("predeploy_report", {"report_id": row["report_id"]}) or row
        self.state.update(
            "predeploy_report",
            {"report_id": row["report_id"]},
            {
                "status": status,
                "verdict": verdict,
                "finished_at": self.clock.now(),
                "items_total": len(items),
                "items_fail": c["fail"],
                "items_question": c["question"],
                "summary": _clean(summary, MAX_SUMMARY),
                "items": json.dumps(items, sort_keys=True, ensure_ascii=False),
                "model_id": _clean(model_id, 120) if model_id else None,
            },
            fresh["row_version"],
        )


def _reason(exc: BaseException) -> str:
    text = _clean(str(exc), 200)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


# ------------------------------------------------------------------------------ the sections


class _Run:
    """The state of one run: the sections share one sandbox target."""

    def __init__(
        self, svc: PredeployService, node_id: str, n: int, tree: Path, report_id: str
    ) -> None:
        self.svc, self.node_id, self.n, self.tree = svc, node_id, n, tree
        self.settings = svc.settings
        self.model_id: str | None = None
        self._work = Path(self.settings.data_dir) / "predeploy" / report_id
        self._target: Any = None
        self._target_error: BaseException | None = None
        self._http_refused: str = ""
        self._packs: list[Any] | None = None

    def close(self) -> None:
        if self._target is not None:
            close = getattr(self._target, "close", None)
            try:
                if close:
                    close()
            except Exception:  # noqa: BLE001, S110 - closing a sandbox must not hide the verdict
                pass
        shutil.rmtree(self._work, ignore_errors=True)

    # -- (a) facts -----------------------------------------------------------
    def facts(self) -> list[dict[str, str]]:
        fsvc = facts_mod.FactsService(self.settings, self.svc.state, self.svc.clock)
        built = fsvc.built_attempt(self.node_id)
        rows = fsvc.rows(self.node_id, self.n) if built == self.n else []
        body = [r for r in rows if r["kind"] != facts_mod.SUMMARY]
        summary = next((r for r in rows if r["kind"] == facts_mod.SUMMARY), None)
        if summary is not None and summary.get("model_id"):
            self.model_id = str(summary["model_id"])
        if not body:
            why = (
                "no facts yet, build the facts card"
                if built is None
                else f"the facts card is for attempt {built}, not {self.n}: build it again"
            )
            return [make_item("facts", "facts:none", "question", why, "table onboard_facts")]
        out = [
            make_item(
                "facts",
                "facts:read",
                "ok",
                f"{len(body)} facts read from attempt {self.n}"
                + (f" (model {self.model_id})" if self.model_id else ""),
                f"table onboard_facts, attempt {self.n}",
            )
        ]
        if self.model_id and "mock" in self.model_id:
            out.append(
                make_item(
                    "facts",
                    "facts:mock",
                    "warn",
                    "no real model answered the facts step (mock): only rule facts",
                    f"table onboard_facts, model {self.model_id}",
                )
            )
        labels = {
            "weak_spot": "weak spot",
            "secret_use": "secret used in code",
            "external_url": "external address",
        }
        for kind, label in labels.items():
            for r in [x for x in body if x["kind"] == kind][:PER_GROUP]:
                detail = r.get("detail") or ""
                detail = f" - {detail}" if detail and not r["name"].startswith(detail[:40]) else ""
                out.append(
                    make_item(
                        "facts",
                        f"{kind}:{r['fact_id']}",
                        "warn",
                        f"{label}: {r['name']}{detail}",
                        f"{r['file']}:{r['line']}",
                    )
                )
        return out

    # -- (b) readiness -------------------------------------------------------
    def readiness(self) -> list[dict[str, str]]:
        from supervisor.console import systems_wizard as wiz
        from supervisor.console.listing import ListingError

        if not self.tree.is_dir():
            raise PredeployError("tree_missing", "the stored source is not on this server; upload")
        result: dict[str, Any] = {}
        for _ in range(30):  # the advisor runs one at a time for the whole server
            try:
                result = wiz.scan_folder(self.tree)
                break
            except ListingError:
                time.sleep(1)
        else:
            raise PredeployError("busy", "the readiness advisor stayed busy for 30 s")
        total = result.get("total")
        if total is None:
            return [
                make_item(
                    "readiness",
                    "readiness:na",
                    "question",
                    f"readiness not available ({result.get('na') or 'unknown'})",
                    "readiness advisor",
                )
            ]
        total = int(total)
        ok = total >= READINESS_OK
        out = [
            make_item(
                "readiness",
                "readiness:total",
                "ok" if ok else "warn",
                f"readiness {total} of 100 ({BAND_TEXT.get(result.get('band', ''), '')}); "
                f"{int(result.get('patches') or 0)} patches proposed",
                "readiness advisor",
            )
        ]
        for a in result.get("areas") or []:
            if int(a["points"]) < int(a["weight"]):
                out.append(
                    make_item(
                        "readiness",
                        f"readiness:{a['id']}",
                        "warn",
                        f"area {a['id']}: {int(a['points'])} of {int(a['weight'])} points",
                        f"readiness area {a['id']}",
                    )
                )
        return out

    # -- (c) + (d) assurance -------------------------------------------------
    def _all_packs(self) -> list[Any]:
        if self._packs is None:
            from supervisor.assurance.loader import load_packs

            self._packs = list(load_packs())
        return self._packs

    def _target_once(self) -> Any:
        if self._target is None:
            if self._target_error is not None:
                raise self._target_error
            try:
                agent_id = agent_id_of(self.tree, self.node_id)
                self._work.mkdir(parents=True, exist_ok=True)
                self._target = self._http_target(agent_id) or self.svc._target_factory(  # noqa: SLF001
                    self.tree, agent_id, self._work, self.settings
                )
            except BaseException as exc:
                self._target_error = exc
                raise
        return self._target

    def _http_target(self, agent_id: str) -> Any:
        """WP-O3b: the HTTP target for a candidate that has an ``http_target`` block, else
        ``None`` (the WP-O3 target is built). A block the rules refuse leaves a reason in
        ``_http_refused``; the packs section turns it into a ``fail`` item."""
        from supervisor.assurance.targets import (
            DEMO_AGENTS,
            HttpAgentTarget,
            TargetError,
            service_principal_headers,
            split_allowed_hosts,
        )
        from supervisor.onboard import predeploy_http

        if agent_id in DEMO_AGENTS or not predeploy_http.enabled(self.settings):
            return None
        try:
            cfg = predeploy_http.resolve(self.settings, self.svc.state, self.node_id, self.tree)
            if cfg is None:
                return None
            from supervisor.adapters.factory import make_masker

            return HttpAgentTarget(
                agent_id,
                cfg,
                allowed_hosts=split_allowed_hosts(self.settings.predeploy_http_allowed_hosts),
                auth_headers=self.svc._http_auth  # noqa: SLF001
                or service_principal_headers(self.settings),
                repo_dir=self.tree if self.tree.is_dir() else None,
                transport=self.svc._http_transport,  # noqa: SLF001
                masker=make_masker(self.settings),
            )
        except TargetError as exc:
            self._http_refused = _clean(str(exc), 200)
            return None

    def _execute(self, packs: Sequence[Any]) -> list[Any]:
        from supervisor.adapters.clock import FixedClock
        from supervisor.assurance.engine import execute
        from supervisor.assurance.model import RunContext
        from supervisor.config import REPO_ROOT
        from supervisor.onboard.launch import T0

        target = self._target_once()
        allow = tuple(
            x.strip() for x in self.settings.assurance_licence_allow.split(",") if x.strip()
        )
        ctx = RunContext(
            target=target,
            repo_root=REPO_ROOT,
            data_root=self.settings.assurance_data_dir,
            data_mode="auto",
            osv_db_path=self.settings.osv_db_path,
            licence_allow=allow,
            extras={"out_dir": str(self._work / "assurance")},
        )
        run = self.svc._executor or execute  # noqa: SLF001
        if hasattr(target, "begin_pack"):  # WP-O3b: the HTTP target counts turns per pack
            ctx.max_items = int(target.cfg.max_turns)
            out: list[Any] = []
            for pack in packs:
                target.begin_pack(pack.id)
                out += list(run([pack], target, ctx, "run-predeploy", FixedClock(T0)))
            return out
        return list(run(list(packs), target, ctx, "run-predeploy", FixedClock(T0)))

    def packs(self) -> list[dict[str, str]]:
        from supervisor.assurance.gates import (
            MOCK_ONLY_ITEM,
            assurance_mock_items,
            assurance_mock_state,
            not_applicable,
        )

        required = [
            p for p in self._all_packs() if p.launch_gate == "required" and "agent" in p.targets
        ]
        results = self._execute(required)
        by_id = {p.id: p for p in required}
        out: list[dict[str, str]] = []
        label = _target_label(self._target)
        if self._http_refused:
            out.append(
                make_item(
                    "packs",
                    "packs:http_target",
                    "fail",
                    f"the HTTP target is configured but refused: {self._http_refused}",
                    "docs/assurance.md HTTP target (WP-O3b)",
                )
            )
        if type(self._target).__name__ == "HttpAgentTarget":
            if self._agent_state() == "RUNNING":
                out.append(
                    make_item(
                        "packs",
                        "packs:running_agent",
                        "warn",
                        "assessment ran against a RUNNING agent: the pack turns reached a live "
                        "agent (the candidate should be in SHADOW)",
                        f"agent {self._http_agent_id()}",
                    )
                )
        if type(self._target).__name__ == "RepoAgentTarget":
            out.append(
                make_item(
                    "packs",
                    "packs:no_harness",
                    "warn",
                    "the stored code is not run on the server (no launch harness): packs that "
                    "need a running agent cannot pass",
                    "docs/onboard.md Launch sandbox",
                )
            )
        seen: set[str] = set()
        for r in sorted(results, key=lambda x: x.pack_id):
            if r.pack_id not in by_id:
                continue
            seen.add(r.pack_id)
            out.append(
                _pack_item("packs", r, required=True, na=not_applicable(_as_dict(r)), label=label)
            )
        for p in required:  # a required pack with no result at all is a fail, never a pass
            if p.id not in seen:
                out.append(
                    make_item(
                        "packs",
                        f"pack:{p.id}",
                        "fail",
                        f"required pack {p.id} has no result",
                        f"pack {p.id}",
                    )
                )
        accept = bool(getattr(self.settings, "assurance_accept_mock_for_launch", False))
        rows = [_as_dict(r) for r in results if r.pack_id in by_id]
        if assurance_mock_items(rows, accept_mock=accept) == [MOCK_ONLY_ITEM]:
            out.append(
                make_item(
                    "packs",
                    "packs:mock_only",
                    "fail",
                    "the results are mock only: the agent ran as a mock demo agent "
                    "(set ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH to accept)",
                    "pack results",
                )
            )
        elif assurance_mock_state(rows) != "none":
            out.append(
                make_item(
                    "packs",
                    "packs:mock",
                    "warn",
                    "some results are from a mock agent (mock demo sandbox)",
                    "pack results",
                )
            )
        return out

    def multiturn(self) -> list[dict[str, str]]:
        pack = next((p for p in self._all_packs() if p.id == MULTITURN_PACK), None)
        if pack is None:
            return [
                make_item(
                    "multiturn",
                    f"pack:{MULTITURN_PACK}",
                    "skip",
                    "the multi-turn red-team pack is not installed",
                    f"pack {MULTITURN_PACK}",
                )
            ]
        results = [r for r in self._execute([pack]) if r.pack_id == MULTITURN_PACK]
        if not results:
            return [
                make_item(
                    "multiturn",
                    f"pack:{MULTITURN_PACK}",
                    "skip",
                    "the pack does not apply to this target",
                    f"pack {MULTITURN_PACK}",
                )
            ]
        return [
            _pack_item(
                "multiturn", results[0], required=False, na=False, label=_target_label(self._target)
            )
        ]

    def _http_agent_id(self) -> str:
        return str(getattr(self._target, "agent_id", "") or self.node_id)

    def _agent_state(self) -> str:
        """``RUNNING`` when any registry row the candidate may have is RUNNING; else the state of
        the first row found (SHADOW, PAUSED, ...), or ``""`` when there is no row."""
        from supervisor.onboard import predeploy_http

        found = ""
        for aid in predeploy_http.agent_ids(self.tree, self.node_id):
            try:
                row = self.svc.state.get("agent", {"agent_id": aid})
            except Exception:  # noqa: BLE001, S112 - no agent table: state unknown
                continue
            state = str((row or {}).get("gate_state") or "")
            if state == "RUNNING":
                return state
            found = found or state
        return found

    # -- (e) duties ----------------------------------------------------------
    def duties(self) -> list[dict[str, str]]:
        from supervisor.governance.register_v2 import duties as dut

        ctx = self.svc.ctx
        not_run = [
            make_item(
                "duties",
                "duties:not_run",
                "question",
                "duties: not run",
                "setting CONSOLE_REGISTER_DUTIES",
            )
        ]
        if ctx is None or not dut.enabled(self.settings):
            return not_run
        from supervisor.governance.register_v2.draft import _view

        drafts = [
            _view(dict(r))
            for r in self.svc.state.query("registration_draft", {"source_ref": self.node_id})
            if r["source_kind"] == "scan"
        ]
        drafts.sort(key=lambda d: str(d.get("updated_at") or d["created_at"]))
        if not drafts:
            return [
                make_item(
                    "duties",
                    "duties:no_draft",
                    "question",
                    "duties: not run (no register draft for this node)",
                    f"node {self.node_id}",
                )
            ]
        draft = drafts[-1]
        if not draft["data"]["v"].get("user_segment"):
            return [
                make_item(
                    "duties",
                    "duties:incomplete",
                    "question",
                    "duties: not run (the register draft has no user segment yet)",
                    f"register draft {draft['draft_id']}",
                )
            ]
        matrix = dut.matrix_of(ctx, draft)
        rows = list(matrix.rows)
        applies = [r for r in rows if r.applies == "yes"]
        groups = dut.gap_groups(rows)
        out = [
            make_item(
                "duties",
                "duties:matrix",
                "ok" if not groups else "warn",
                f"{len(applies)} duties apply, {sum(len(g) for g in groups.values())} with "
                f"partial or no coverage in {len(groups)} groups",
                f"register draft {draft['draft_id']}",
            )
        ]
        for (instrument, cov), group in list(groups.items())[:PER_GROUP]:
            out.append(
                make_item(
                    "duties",
                    f"duties:{instrument}:{cov}",
                    "warn",
                    f"{len(group)} duties of {instrument} have {cov} coverage",
                    f"duty {group[0].obligation_id}",
                )
            )
        open_q = [r for r in rows if r.applies == "needs_answer"]
        if open_q:
            out.append(
                make_item(
                    "duties",
                    "duties:needs_answer",
                    "question",
                    f"{len(open_q)} duties need an answer before they can be judged",
                    f"duty {open_q[0].obligation_id}",
                )
            )
        return out


def _as_dict(r: Any) -> dict[str, Any]:
    if isinstance(r, Mapping):
        return dict(r)
    return {
        "pack_id": r.pack_id,
        "status": r.status,
        "details": dict(r.details),
        "is_mock": bool(r.is_mock),  # assurance.gates._row drops is_mock from a PackResult
    }


def _target_label(target: Any) -> str:
    """Which target ran a pack: ``http <host>``, ``sandbox demo``, ``no harness`` or ``""``
    (a target that is none of these, such as a unit-test fake)."""
    name = type(target).__name__
    if name == "HttpAgentTarget":
        return f"http {target.host}"
    if name == "DemoAgentTarget":
        return "sandbox demo"
    if name == "RepoAgentTarget":
        return "no harness"
    return ""


def _pack_item(
    section: str, r: Any, *, required: bool, na: bool, label: str = ""
) -> dict[str, str]:
    """One pack result as one item. A required pack that failed, errored or skipped is ``fail``
    (a skip is never a pass), except a structured "not applicable" skip. An advisory pack never
    gives ``fail``."""
    reasons = "; ".join(str(x) for x in (r.reasons or [])[:2]) or "no reason given"
    mock = " (mock)" if r.is_mock else ""
    details = r.details if isinstance(getattr(r, "details", None), Mapping) else {}
    if label and details.get("target_kind") == "http":
        label += f", {int(details.get('turns') or 0)} turns"
    head = f"pack {r.pack_id}{mock}: {r.status}" + (f" [target: {label}]" if label else "")
    pointer = f"pack {r.pack_id}"
    na_reason = str(details.get("reason") or "") if r.status == "skip" else ""
    if required and na_reason.startswith("not_applicable:"):
        # WP-O3b: the pack structurally cannot run on this target (no data for it, or a
        # capability that the target can never have). Not a pass and not a defect of the
        # candidate: an open question for the reviewer. Launch still treats the skip as NO-GO.
        what = na_reason[len("not_applicable:") :].strip()
        action = str(details.get("action") or "supply what is missing")
        return make_item(
            section,
            f"pack:{r.pack_id}",
            "question",
            f"pack {r.pack_id} cannot run on this target: {what}; {action} or accept the gap",
            pointer,
        )
    if r.status == "ok":
        status, text = "ok", head
    elif r.status == "warn":
        status, text = "warn", f"{head} - {reasons}"
    elif r.status == "skip" and na:
        status, text = "skip", f"{head} (not applicable) - {reasons}"
    elif r.status == "skip":
        status, text = ("fail" if required else "skip"), f"{head} - {reasons}"
    else:  # fail or error
        status, text = ("fail" if required else "warn"), f"{head} - {reasons}"
    return make_item(section, f"pack:{r.pack_id}", status, text, pointer)


# ------------------------------------------------------------------------------ the view


_ITEM_KEYS = ("section", "id", "status", "text", "pointer")


def view(row: Mapping[str, Any]) -> dict[str, Any]:
    """The public shape of a report: counts, and the items grouped by section in run order."""
    try:
        raw = json.loads(row.get("items") or "[]")
    except ValueError:
        raw = []
    items = [
        {k: str(i.get(k, "")) for k in _ITEM_KEYS}
        for i in (raw if isinstance(raw, list) else [])
        if isinstance(i, dict) and i.get("section") in SECTIONS and i.get("status") in STATUSES
    ]
    groups = [
        {
            "section": s,
            "required": s in REQUIRED_SECTIONS,
            "rows": [i for i in items if i["section"] == s],
        }
        for s in SECTIONS
    ]
    return {
        "report_id": row["report_id"],
        "node_id": row["node_id"],
        "attempt_n": int(row["attempt_n"]),
        "status": row["status"],
        "verdict": row["verdict"],
        "started_at": _as_ts(row.get("started_at")),
        "finished_at": _as_ts(row.get("finished_at")),
        "items_total": int(row.get("items_total") or 0),
        "items_fail": int(row.get("items_fail") or 0),
        "items_question": int(row.get("items_question") or 0),
        "items_warn": sum(1 for i in items if i["status"] == "warn"),
        "summary": row.get("summary") or "",
        "model_id": row.get("model_id"),
        "created_by": row.get("created_by"),
        "running": row["status"] in ("queued", "running"),
        "groups": [g for g in groups if g["rows"]],
        "items": items,
    }


__all__ = [
    "PredeployError",
    "PredeployService",
    "REQUIRED_SECTIONS",
    "SECTIONS",
    "build_target",
    "counts_of",
    "make_item",
    "require_on",
    "verdict_of",
    "view",
]
