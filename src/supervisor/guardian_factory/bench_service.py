"""The benchmark service of the guardian factory (WP-G2): packs, background runs, the chain record.

* Packs: upload, generate, import benign from stored traces (``bench.py`` holds the format).
* A run is one background thread per definition (one at a time): a ``guardian_bench_run`` row
  goes ``queued`` -> ``running`` -> ``done`` or ``failed``; the console polls it.
* A finished run writes one ``guardian_bench`` chain record: ids, the pack and definition hashes
  and integers. No case text, no rule text.

The state change draft -> benchmarked is in ``store.GuardianDefStore.mark_benchmarked``; it reads
the newest run row through ``bench.newest_run``.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core.canonical import format_ts
from supervisor.core.errors import NotFoundError
from supervisor.guardian_factory import bench, caps
from supervisor.guardian_factory.definition import GuardianFactoryError, validate_definition
from supervisor.guardian_factory.store import EDITABLE, GuardianDefStore, require_on

log = logging.getLogger("supervisor.guardian_factory")

_LOCK = threading.RLock()
_RUNNING: dict[str, str] = {}  # def id -> run id that has a thread now
_THREADS: dict[str, threading.Thread] = {}


def _new_run_id() -> str:
    return f"gbr_{time.time_ns():020d}_{secrets.token_hex(3)}"


class BenchService:
    def __init__(
        self,
        store: GuardianDefStore,
        *,
        data_dir: Any,
        evidence: Any = None,
        chat: Any = None,
        masker: Any = None,
        delegates: Any = None,
    ) -> None:
        self.store = store
        self.state = store.state
        self.tables = store.tables
        self.clock = store.clock
        self.settings = store.settings
        self.data_dir = data_dir
        self.evidence_sink = evidence
        self.chat, self.masker, self.delegates = chat, masker, delegates

    # ------------------------------------------------------------------ packs
    def _editable_row(self, def_id: str, user: Any) -> tuple[dict[str, Any], str]:
        require_on(self.settings)
        row = self.store._latest(def_id)  # noqa: SLF001 - same package
        actor = self.store._need(user, str(row["owner_group"]))  # noqa: SLF001
        if row["state"] not in EDITABLE:
            raise GuardianFactoryError(
                "not_draft", f"version {row['version']} is {row['state']}; make a new version"
            )
        return row, actor

    def _definition(self, row: dict[str, Any]) -> Any:
        return validate_definition(self.store._body(row))  # noqa: SLF001

    def list_packs(self, def_id: str) -> list[dict[str, Any]]:
        require_on(self.settings)
        self.store._latest(def_id)  # noqa: SLF001 - 404 for an unknown guardian
        out = []
        for m in bench.list_packs(self.data_dir, def_id):
            out.append(
                {
                    "id": m["id"],
                    "version": int(m["version"]),
                    "origin": m.get("origin", ""),
                    "attack": int(m["counts"]["attack"]),
                    "benign": int(m["counts"]["benign"]),
                    "pack_sha256": m["pack_sha256"],
                    "files": m["files"],
                    "created_by": m.get("created_by", ""),
                    "created_at": m.get("created_at", ""),
                }
            )
        return out

    def _store_pack(
        self,
        row: dict[str, Any],
        actor: str,
        pack_id: str,
        attack: list[bench.Case],
        benign: list[bench.Case],
        origin: str,
        op: str,
    ) -> dict[str, Any]:
        meta = bench.write_pack(
            self.data_dir,
            str(row["def_id"]),
            pack_id,
            attack,
            benign,
            origin=origin,
            actor=actor,
            now=format_ts(self.clock.now()),
        )
        self.store._event(row, f"bench_pack_{op}", str(row["state"]), actor)  # noqa: SLF001
        return {
            "id": pack_id,
            "version": meta["version"],
            "origin": origin,
            "attack": len(attack),
            "benign": len(benign),
            "pack_sha256": meta["pack_sha256"],
        }

    def _existing(self, def_id: str, pack_id: str) -> bench.Pack | None:
        try:
            return bench.load_pack(self.data_dir, def_id, pack_id)
        except GuardianFactoryError as exc:
            if exc.code == "no_pack":
                return None
            raise

    def upload(
        self,
        def_id: str,
        pack_id: Any,
        attack_jsonl: bytes | str | None,
        benign_jsonl: bytes | str | None,
        user: Any,
    ) -> dict[str, Any]:
        """Store the given files as the pack. A file left out keeps the one of the existing
        pack. Every case goes through the masker; one that trips it refuses the upload."""
        row, actor = self._editable_row(def_id, user)
        bench.check_pack_id(pack_id)
        if attack_jsonl is None and benign_jsonl is None:
            raise GuardianFactoryError("pack_invalid", "give attack.jsonl, benign.jsonl or both")
        size = sum(
            len(x.encode() if isinstance(x, str) else x) for x in (attack_jsonl, benign_jsonl) if x
        )
        if size > caps.BENCH_MAX_BYTES:
            raise GuardianFactoryError(
                "pack_too_large",
                f"the upload is larger than {caps.BENCH_MAX_BYTES // 1_000_000} MB",
            )
        old = self._existing(def_id, pack_id)
        attack = (
            bench.parse_jsonl(attack_jsonl, True, name="attack.jsonl")
            if attack_jsonl is not None
            else (old.attack if old else [])
        )
        benign = (
            bench.parse_jsonl(benign_jsonl, False, name="benign.jsonl")
            if benign_jsonl is not None
            else (old.benign if old else [])
        )
        if len(attack) + len(benign) > caps.BENCH_MAX_CASES:
            raise GuardianFactoryError(
                "pack_too_large", f"more than {caps.BENCH_MAX_CASES} cases in the pack"
            )
        return self._store_pack(row, actor, pack_id, attack, benign, "upload", "upload")

    def generate(self, def_id: str, pack_id: Any, user: Any) -> dict[str, Any]:
        """The starter pack: synthetic attack cases from the pattern library (or the keywords of
        the list) and the synthetic benign sample. No model."""
        row, actor = self._editable_row(def_id, user)
        bench.check_pack_id(pack_id)
        attack, benign = bench.generate_cases(self._definition(row))
        return self._store_pack(row, actor, pack_id, attack, benign, "generated", "generate")

    def import_traces(
        self, def_id: str, pack_id: Any, user: Any, limit: int = caps.BENCH_TRACE_SAMPLE_MAX
    ) -> dict[str, Any]:
        """The benign set from the stored, masked gate traces of the agents in scope. The attack
        set of an existing pack is kept."""
        row, actor = self._editable_row(def_id, user)
        bench.check_pack_id(pack_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise GuardianFactoryError("bad_limit", "limit: a whole number from 1")
        cases, stats = bench.trace_cases(self.tables, self._definition(row), limit)
        if not cases:
            raise GuardianFactoryError(
                "no_traces", "no stored trace of the agents and tools in scope gives a benign case"
            )
        old = self._existing(def_id, pack_id)
        out = self._store_pack(
            row, actor, pack_id, old.attack if old else [], cases, "traces", "import_traces"
        )
        return {**out, **stats}

    # ------------------------------------------------------------------ runs
    @staticmethod
    def run_view(row: Any) -> dict[str, Any]:
        raw = row.get("result_json")
        result = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        return {
            "run_id": row["run_id"],
            "def_id": row["def_id"],
            "version": int(row["version"]),
            "pack_id": row["pack_id"],
            "pack_sha256": row["pack_sha256"],
            "def_sha256": row["def_sha256"],
            "status": row["status"],
            "started_at": str(row["started_at"]),
            "finished_at": str(row["finished_at"]) if row.get("finished_at") else None,
            "gate": row["gate"],
            "failing_threshold": row.get("failing_threshold") or "",
            "created_by": row["created_by"],
            "result": result,
        }

    def get_run(self, def_id: str, run_id: str) -> dict[str, Any]:
        require_on(self.settings)
        row = self.state.get(bench.RUNS, {"run_id": run_id})
        if row is None or row["def_id"] != def_id:
            raise NotFoundError(f"benchmark run {run_id} of {def_id} does not exist")
        return self.run_view(dict(row))

    def list_runs(self, def_id: str, limit: int = 20) -> list[dict[str, Any]]:
        require_on(self.settings)
        self.store._latest(def_id)  # noqa: SLF001
        rows = [dict(r) for r in self.state.query(bench.RUNS, {"def_id": def_id})]
        rows.sort(key=lambda r: (str(r["started_at"]), str(r["run_id"])), reverse=True)
        return [self.run_view(r) for r in rows[:limit]]

    def start_run(
        self, def_id: str, user: Any, pack_id: Any = None, *, background: bool = True
    ) -> dict[str, Any]:
        """Queue a run of the newest version against a pack (default: ``benchmark_pack`` of the
        definition) and start the thread. One run at a time per guardian."""
        row, actor = self._editable_row(def_id, user)
        d = self._definition(row)
        pid = bench.check_pack_id(pack_id or d.benchmark_pack or "")
        pack = bench.load_pack(self.data_dir, def_id, pid)  # 400 no_pack / pack_changed
        body = self.store._body(row)  # noqa: SLF001
        with _LOCK:
            if def_id in _RUNNING:
                raise GuardianFactoryError(
                    "already_running", f"a benchmark of {def_id} is running; wait for it"
                )
            self._close_stale(def_id)
            run_id = _new_run_id()
            now = self.clock.now()
            self.state.insert(
                bench.RUNS,
                {
                    "run_id": run_id,
                    "def_id": def_id,
                    "version": int(row["version"]),
                    "pack_id": pid,
                    "pack_sha256": pack.sha256,
                    "def_sha256": bench.def_sha(body),
                    "status": "queued",
                    "started_at": now,
                    "finished_at": None,
                    "result_json": json.dumps({}),
                    "gate": "not_run",
                    "failing_threshold": None,
                    "created_by": actor,
                },
            )
            _RUNNING[def_id] = run_id
            th = threading.Thread(
                target=self._thread, args=(run_id, def_id, d, pack, actor), daemon=True
            )
            _THREADS[def_id] = th
        if background:
            th.start()
        else:
            self._thread(run_id, def_id, d, pack, actor)
        return self.get_run(def_id, run_id)

    def join(self, def_id: str, timeout: float = 60.0) -> None:
        th = _THREADS.get(def_id)
        if th is not None:
            th.join(timeout)

    def _close_stale(self, def_id: str) -> None:
        for r in self.state.query(bench.RUNS, {"def_id": def_id}):
            if r["status"] in ("queued", "running"):
                self._finish(dict(r), "failed", {"error": "the run was cut short (restart)"})

    def _thread(self, run_id: str, def_id: str, d: Any, pack: bench.Pack, actor: str) -> None:
        try:
            row = self.state.get(bench.RUNS, {"run_id": run_id})
            self.state.update(
                bench.RUNS, {"run_id": run_id}, {"status": "running"}, row["row_version"]
            )
            res = bench.run_benchmark(
                d, pack, chat=self.chat, masker=self.masker, delegates=self.delegates
            )
            self._finish(
                dict(self.state.get(bench.RUNS, {"run_id": run_id})), "done", res.to_dict()
            )
        except Exception as exc:  # noqa: BLE001 - the thread must leave a row, never die silently
            log.warning("guardian bench: run failed (%s)", type(exc).__name__)
            row = self.state.get(bench.RUNS, {"run_id": run_id})
            if row is not None and row["status"] in ("queued", "running"):
                text = exc.args[0] if isinstance(exc, GuardianFactoryError) else type(exc).__name__
                self._finish(dict(row), "failed", {"error": str(text)[:300]})
        finally:
            with _LOCK:
                if _RUNNING.get(def_id) == run_id:
                    del _RUNNING[def_id]

    def _finish(self, row: dict[str, Any], status: str, result: dict[str, Any]) -> None:
        gate = result.get("gate", {})
        verdict = gate.get("verdict", "not_run") if status == "done" else "not_run"
        failing = ",".join(gate.get("failing", [])) or None
        self.state.update(
            bench.RUNS,
            {"run_id": row["run_id"]},
            {
                "status": status,
                "finished_at": self.clock.now(),
                "result_json": json.dumps(result, sort_keys=True),
                "gate": verdict,
                "failing_threshold": failing,
            },
            row["row_version"],
        )
        if status == "done":
            self._chain(row, result, verdict, failing)

    def _chain(
        self, row: dict[str, Any], result: dict[str, Any], verdict: str, failing: str | None
    ) -> None:
        if self.evidence_sink is None:
            return
        chosen = next(
            (x for x in result["levels"] if x["sensitivity"] == result["chosen_sensitivity"]), {}
        )
        live = result.get("live") or {}
        try:
            self.evidence_sink.record(
                "guardian_bench",
                f"guardian:{row['def_id']}",
                {
                    "run_id": row["run_id"],
                    "def_id": row["def_id"],
                    "version": int(row["version"]),
                    "pack_id": row["pack_id"],
                    "pack_sha256": row["pack_sha256"],
                    "def_sha256": row["def_sha256"],
                    "type": result["type"],
                    "stage": result["stage"],
                    "sensitivity": int(result["chosen_sensitivity"]),
                    "gate": verdict,
                    "failing_threshold": failing or "",
                    "attack_n": int(result["counts"]["attack"]),
                    "benign_n": int(result["counts"]["benign"]),
                    "tp": int(chosen.get("tp", 0)),
                    "fn": int(chosen.get("fn", 0)),
                    "fp": int(chosen.get("fp", 0)),
                    "tn": int(chosen.get("tn", 0)),
                    "tpr_pct": int(chosen.get("tpr_pct", 0)),
                    "fpr_pct": int(chosen.get("fpr_pct", 0)),
                    "p95_us": int(chosen.get("p95_us", 0)),
                    "live_slug": live.get("slug", ""),
                    "live_tpr_pct": int(live.get("tpr_pct", 0)),
                    "live_fpr_pct": int(live.get("fpr_pct", 0)),
                    "actor_ref": actor_ref(self.settings, str(row["created_by"]), "system"),
                    "ts": format_ts(self.clock.now()),
                },
            )
        except Exception:  # noqa: BLE001
            log.exception("guardian_bench chain record failed")
