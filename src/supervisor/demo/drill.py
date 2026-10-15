"""Fail-mode drill: break the state store under a running gateway and show what it does.

    python -m supervisor.demo drill [--data-dir DIR]

Runs on a throwaway SQLite store (a fresh temporary directory unless ``--data-dir`` is
given; that directory is wiped first only if it is empty or carries the demo marker).
It builds the real runtime (gateway, policy, evidence chain), then:

a. baseline: a money transfer within limits is decided normally (allowed);
b. closes the real sqlite connection the gateway uses (not a mocked decision);
c. calls the gateway again and prints what it returned: a money tool and an unknown tool
   must be BLOCKED (fail closed), a read-only tool must pass with an alert (fail open),
   per ADR D03;
d. opens a new connection to the same file: a normal decision again;
e. verifies the evidence chain offline.

Evidence during the outage: the gateway writes its decision record to the chain through
the same store, so while the store is down that write fails too. The gateway counts it
(``evidence_failed`` / ``record_failed`` metrics) and still returns the fail-mode
decision; those decisions have no chain entry. The drill reports that gap and checks
that the chain written before and after the outage still verifies.
Exit code 0 only when every expected outcome matched.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from supervisor.core.errors import SupervisorError
from supervisor.demo.session import Echo, build_session, default_echo, demo_settings

AGENT = "payments"
CTX = {"trace_id": "drill-trace"}


class DrillReport:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failures = 0

    @property
    def ok(self) -> bool:
        return self.failures == 0


def _break(executor: Any) -> None:
    """Really close the sqlite connection under the gateway."""
    with executor._lock:  # noqa: SLF001 - the drill breaks the real connection
        executor._conn.close()  # noqa: SLF001


def _restore(executor: Any) -> None:
    """Open a new connection to the same file by building a fresh executor on it."""
    fresh = type(executor)(executor.path, executor.table_prefix)
    with executor._lock:  # noqa: SLF001
        executor._conn = fresh._conn  # noqa: SLF001


def _money_args(world: Any) -> dict[str, Any]:
    for acc_id, acc in world.accounts.items():
        payees = world.customer_payees(acc.customer_id)
        amount = min(world.balances[acc_id] // 4, 50_000_000) // 1000 * 1000
        if payees and amount >= 100_000:
            return {
                "from_account_id": acc_id,
                "payee_id": payees[0]["payee_id"],
                "amount_minor": amount,
                "memo": "drill",
            }
    raise SupervisorError("drill: no account with a payee and balance in the synthetic world")


def _show(d: dict[str, Any]) -> str:
    return (
        f"allow={d.get('allow')} action={d.get('action')} fail_mode={d.get('fail_mode')} "
        f"rule={d.get('rule_id')}"
    )


def run_drill(data_dir: Path | None = None, echo: Echo = default_echo) -> DrillReport:
    """Run the drill. ``data_dir=None`` uses a fresh temporary directory (removed after)."""
    if data_dir is None:
        tmp = Path(tempfile.mkdtemp(prefix="supervisor-drill-"))
        try:
            return _drill(tmp, echo)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return _drill(Path(data_dir), echo)


def _drill(data_dir: Path, echo: Echo) -> DrillReport:
    from supervisor.core.canonical import sha256_hex
    from supervisor.demo.seed import wipe
    from supervisor.evidence.export import export_chain
    from supervisor.evidence.verify import verify_export
    from supervisor.wiring import register_agents
    from supervisor_agents.common.manifest import load_manifest
    from supervisor_agents.common.runtime import default_system_prompt

    rep = DrillReport()

    def say(line: str) -> None:
        rep.lines.append(line)
        echo(line)

    def check(cond: bool, ok: str, bad: str) -> None:
        if cond:
            say(f"[OK] {ok}")
        else:
            rep.failures += 1
            say(f"[FAIL] {bad}")

    wipe(data_dir)  # refuses a non-empty directory that is not a demo dir
    settings = demo_settings(data_dir)
    session = build_session(settings)
    try:
        rt = session.runtime
        gw = rt.gateway
        say(f"[OK] runtime built on a throwaway store: {settings.sqlite_path}")
        manifest = load_manifest(AGENT)
        register_agents(
            rt, [manifest], prompt_hashes={manifest.id: sha256_hex(default_system_prompt(manifest))}
        )
        money = _money_args(session.world)

        def call(tool: str, **args: Any) -> dict[str, Any]:
            return dict(gw.check(AGENT, manifest.version, tool, args, CTX))

        # a. baseline
        base = call("transfer", **money)
        say(f"       baseline transfer: {_show(base)}")
        check(
            base["allow"] is True and base.get("fail_mode") is None,
            "(a) baseline: money transfer within limits decided normally (allowed)",
            "(a) baseline: transfer was not allowed normally",
        )
        gw.drain()
        rt.chain.commit_root()
        before = len(session.tables.query("chain_entry"))
        metrics0 = gw.metrics.snapshot()

        # b. break the store
        _break(rt.adapters.executor)
        say("[OK] (b) state store connection closed under the running gateway")

        # c. outage decisions
        d_money = call("transfer", **money)
        say(f"       outage transfer (money):  {_show(d_money)}")
        check(
            d_money["allow"] is False
            and d_money["action"] == "block"
            and d_money.get("fail_mode") == "closed",
            "(c) money tool BLOCKED, fail mode closed",
            "(c) money tool was not blocked with fail mode closed",
        )
        d_read = call("get_balance", account_id=money["from_account_id"])
        say(f"       outage get_balance (read): {_show(d_read)}")
        check(
            d_read["allow"] is True
            and d_read["action"] == "alert"
            and d_read.get("fail_mode") == "open",
            "(c) read-only tool passed with an alert, fail mode open (ADR D03)",
            "(c) read-only tool did not follow fail open plus alert",
        )
        d_unknown = call("brand_new_tool")
        say(f"       outage brand_new_tool:    {_show(d_unknown)}")
        check(
            d_unknown["allow"] is False and d_unknown.get("fail_mode") == "closed",
            "(c) unknown tool BLOCKED, fail mode closed",
            "(c) unknown tool was not blocked with fail mode closed",
        )
        metrics1 = gw.metrics.snapshot()
        c0, c1 = metrics0["counts"], metrics1["counts"]
        lost = c1.get("evidence_failed", 0) - c0.get("evidence_failed", 0)
        side = c1.get("record_failed", 0) - c0.get("record_failed", 0)
        say(
            f"       evidence during the outage: {lost} chain write(s) and {side} verdict write(s) "
            "failed (same store); the gateway still returned each fail-mode decision"
        )

        # d. restore
        _restore(rt.adapters.executor)
        again = call("transfer", **money)
        say(f"       restored transfer: {_show(again)}")
        check(
            again["allow"] is True and again.get("fail_mode") is None,
            "(d) store restored: money transfer decided normally again",
            "(d) after restore the transfer was not decided normally",
        )

        # e. chain
        gw.drain()
        rt.chain.commit_root()
        after = len(session.tables.query("chain_entry"))
        out = data_dir / "drill-export"
        export_chain(session.tables, out)
        result = verify_export(out, strict=True)
        check(
            result.failures == 0,
            f"(e) evidence chain verifies offline ({before} entries before the outage, "
            f"{after} after; the outage decisions are not on the chain)",
            "(e) evidence chain did not verify: " + "; ".join(result.lines[-3:]),
        )
        check(
            after > before,
            "(e) the chain accepts new entries after the restore",
            "(e) no new chain entry after the restore",
        )
    finally:
        try:
            session.close()
        except Exception as exc:  # noqa: BLE001 - report the drill result, not a close error
            say(f"[SKIP] runtime close after the drill: {type(exc).__name__}")
    say("[OK] fail-mode drill: all outcomes matched" if rep.ok else "[FAIL] fail-mode drill")
    return rep


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m supervisor.demo drill", description=__doc__)
    p.add_argument("--data-dir", default=None, help="throwaway data dir (default: a temp dir)")
    args = p.parse_args(list(argv) if argv is not None else None)
    try:
        rep = run_drill(Path(args.data_dir).resolve() if args.data_dir else None)
    except SupervisorError as exc:
        default_echo(f"[FAIL] {exc}")
        return 1
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
