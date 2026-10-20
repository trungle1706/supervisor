"""MCP tool lock service (WP26, ADR D24): the locked manifest per upstream server, the hold of
new or changed tools, the two-person approval, the review case and the chain records.

Table ``mcp_tool_manifest`` (one row per server and tool, plus a server row with tool_name
``*``). Tool status::

    new       never approved                          -> hidden, tools/call blocked
    changed   approved before, hash differs now       -> hidden, tools/call blocked
    approved  observed hash == locked hash            -> visible, passes the gate
    removed   locked, but the server no longer lists  -> logged only

Approval is the two-person pattern of ``gateway/state.py`` (resume) and ``cases/service.py``
(sign-off): two DIFFERENT people approve the SAME observed hash. An approval counts only for the
hash the reviewer saw (``observed_hash`` is required), so a change between "look" and "approve"
is never approved by accident. A new observed hash drops the approvals collected so far.

Every lock change is a chain record (hashes, tool names and finding kinds; never descriptions).
A new or changed tool opens one case ``mcp_tool_review`` (high when the scan marks it
suspicious, else medium). The case never calls the gate; the lock does.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, SupervisorError
from supervisor.core.ports import Clock, EvidenceSink, StateStore
from supervisor.gateway import mcp_lock

log = logging.getLogger("supervisor.mcp_lock")

SERVER_ROW = "*"
SOURCE_KIND = "mcp_tool_review"
LAST_SEEN_REFRESH = timedelta(days=1)
APPROVALS_NEEDED = 2
RULE_UNREVIEWED = "MCP-TOOL-UNREVIEWED"
_USER = re.compile(r"^[A-Za-z0-9_.@+-]{1,128}\Z")
_SERVER = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}\Z")
_AGENT = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}\Z")
_FULL_HASH = re.compile(r"^[0-9a-fA-F]{64}\Z")


class ToolLockError(SupervisorError):
    """A lock request is not allowed (HTTP 400 with the message)."""


def manifest_id(server_id: str, tool_name: str) -> str:
    return hashlib.sha256(f"{server_id}\x00{tool_name}".encode()).hexdigest()[:24]


def check_server_id(server_id: str) -> str:
    if not isinstance(server_id, str) or not _SERVER.match(server_id):
        raise ToolLockError("server_id must be 1-128 characters of A-Z a-z 0-9 _ . : @ -")
    return server_id


def _ascii(text: Any, limit: int = 128) -> str:
    return str(text).encode("ascii", "backslashreplace").decode("ascii")[:limit]


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    import json

    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def _as_dt(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def valid_approvals(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Approvals given for the hash the server shows now."""
    return [a for a in _json(row.get("approvals"), []) if a.get("hash") == row.get("observed_hash")]


def public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """The row as the CLI and the route show it (definitions stay in ``diff``)."""
    ap = valid_approvals(row)
    scan = _json(row.get("scan"), {}) or {}
    return {
        "server_id": row["server_id"],
        "tool": _ascii(row["tool_name"]),
        "tool_escaped": row["tool_name"] != _ascii(row["tool_name"], 4000),
        "status": row["status"],
        "hidden": row["status"] in ("new", "changed"),
        "suspicious": _bool(row.get("suspicious")),
        "findings": scan.get("findings", []),
        "score_bp": scan.get("score_bp"),
        "locked_hash": row.get("locked_hash"),
        "observed_hash": row.get("observed_hash"),
        "approvals": [{"by": a["by"], "role": a.get("role"), "at": a.get("at")} for a in ap],
        "approvals_needed": APPROVALS_NEEDED,
        "case_id": row.get("case_id"),
        "seeded_by": row.get("seeded_by"),
        "first_seen": _ts(row.get("first_seen")),
        "last_seen": _ts(row.get("last_seen")),
    }


def _ts(value: Any) -> str | None:
    return format_ts(value) if isinstance(value, datetime) else None


class ToolLockService:
    def __init__(
        self,
        state: StateStore,
        evidence: EvidenceSink,
        clock: Clock,
        cases: Any = None,
        *,
        on_new_server: Callable[[str, str], None] | None = None,
    ) -> None:
        self.on_new_server = on_new_server
        self.state = state
        self.evidence = evidence
        self.clock = clock
        self.cases = cases
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ rows
    def _rows(self, server_id: str) -> dict[str, dict[str, Any]]:
        return {
            r["tool_name"]: r
            for r in self.state.query("mcp_tool_manifest", {"server_id": server_id})
        }

    def _update(self, row: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
        key = {"manifest_id": row["manifest_id"]}
        for attempt in (0, 1):
            cur = row if attempt == 0 else self.state.get("mcp_tool_manifest", key)
            if cur is None:
                raise ToolLockError("manifest row disappeared; retry")
            try:
                return dict(
                    self.state.update("mcp_tool_manifest", key, changes, cur["row_version"])
                )
            except ConcurrencyError:
                if attempt:
                    raise ToolLockError("manifest changed concurrently; retry") from None
        raise AssertionError  # pragma: no cover

    def _chain(self, kind: str, agent_id: str, payload: Mapping[str, Any]) -> None:
        body = {"agent_id": agent_id, "ts": format_ts(self.clock.now()), **payload}
        self.evidence.record(kind, f"mcp:{payload.get('server_id', '')}", body)

    # ------------------------------------------------------------------ observe
    def observe(
        self,
        server_id: str,
        agent_id: str,
        tools: list[dict[str, Any]],
        *,
        tofu_by: str | None = None,
        tofu_via: str | None = None,
    ) -> dict[str, Any]:
        """Compare a ``tools/list`` result with the locked manifest, record every change, and
        return the view the proxy needs (which tools the agent may see and call)."""
        check_server_id(server_id)
        if not isinstance(agent_id, str) or not _AGENT.match(agent_id):
            raise ToolLockError("agent_id is not valid")
        if tofu_by is not None and not _USER.match(tofu_by):
            raise ToolLockError("trust-on-first-use needs a valid user name")
        by_name = mcp_lock.group_tools(tools)
        if SERVER_ROW in by_name:  # F9: would collide with the server row; fail closed
            raise ToolLockError("a tool named '*' is not allowed (reserved for the server row)")
        with self._lock:
            return self._observe(server_id, agent_id, by_name, tofu_by, tofu_via)

    def _observe(
        self,
        server_id: str,
        agent_id: str,
        by_name: dict[str, dict[str, Any]],
        tofu_by: str | None,
        tofu_via: str | None = None,
    ) -> dict[str, Any]:
        now = self.clock.now()
        rows = self._rows(server_id)
        first_time = not rows
        hashes = {n: mcp_lock.hash_group(t) for n, t in by_name.items()}
        lhash = mcp_lock.list_hash(hashes)
        changes: list[dict[str, Any]] = []
        server_row = rows.get(SERVER_ROW)
        seed = tofu_by if (first_time and tofu_by) else None
        if tofu_by and not first_time:
            changes.append({"tool": "*", "change": "tofu_ignored"})
        initial_case: str | None = None
        if first_time and not seed and by_name:
            initial_case = self._open_case(
                agent_id,
                server_id,
                f"{server_id}:initial:{lhash}",
                "medium",
                f"New MCP server {_ascii(server_id)}: {len(by_name)} tool(s) held for "
                "two-person review",
            )
        for name in sorted(by_name):
            tool = by_name[name]
            h = hashes[name]
            row = rows.get(name)
            if row is not None and row["observed_hash"] == h and row["status"] != "removed":
                last = _as_dt(row.get("last_seen"))  # steady state: no scan, no write
                if last is None or now - last >= LAST_SEEN_REFRESH:
                    self._update(row, {"last_seen": now})
                continue
            scan = mcp_lock.scan_tool(tool)
            definition = mcp_lock.stored_definition(tool)
            if row is None:
                self._insert_tool(
                    server_id, name, agent_id, h, definition, scan, now, seed, initial_case
                )
                kind = "seeded" if seed else "new"
                changes.append({"tool": name, "change": kind})
                self._chain(
                    "mcp_tool_lock_change",
                    agent_id,
                    {
                        "server_id": server_id,
                        "tool_name": _ascii(name),
                        "change": kind,
                        "observed_hash": h,
                        "locked_hash": h if seed else None,
                        "suspicious": bool(scan["suspicious"]),
                        "finding_kinds": mcp_lock.finding_kinds(scan),
                    },
                )
                if not seed and initial_case is None:
                    self._attach_case(server_id, name, agent_id, h, scan)
                continue
            changes.append(self._moved(row, h, definition, scan, agent_id, now))
        for name, row in sorted(rows.items()):
            if name == SERVER_ROW or name in by_name or row["status"] == "removed":
                continue
            self._update(row, {"status": "removed", "last_seen": now})
            changes.append({"tool": name, "change": "removed"})
            self._chain(
                "mcp_tool_lock_change",
                agent_id,
                {
                    "server_id": server_id,
                    "tool_name": _ascii(name),
                    "change": "removed",
                    "locked_hash": row.get("locked_hash"),
                    "observed_hash": row.get("observed_hash"),
                },
            )
        self._server_row(server_id, agent_id, lhash, seed, now, server_row)
        if first_time and self.on_new_server is not None:
            try:  # the inventory link is advice: a failure never touches the lock
                self.on_new_server(server_id, agent_id)
            except Exception as exc:  # noqa: BLE001
                log.error("inventory registration failed: %s", type(exc).__name__)
        if seed:
            self._chain(
                "mcp_manifest_seeded",
                agent_id,
                {
                    "server_id": server_id,
                    "seeded_by": seed,
                    # the name is claimed, not verified; "via" is who sent it (F3)
                    "via": _ascii(tofu_via or "local"),
                    "method": "trust_on_first_use",
                    "list_hash": lhash,
                    "tool_count": len(by_name),
                },
            )
        out = self.view(server_id)
        out["changes"] = changes
        return out

    def _insert_tool(
        self,
        server_id: str,
        name: str,
        agent_id: str,
        h: str,
        definition: str,
        scan: dict[str, Any],
        now: datetime,
        seed: str | None,
        case_id: str | None,
    ) -> None:
        try:
            self.state.insert(
                "mcp_tool_manifest",
                {
                    "manifest_id": manifest_id(server_id, name),
                    "server_id": server_id,
                    "tool_name": name,
                    "row_kind": "tool",
                    "agent_id": agent_id,
                    "status": "approved" if seed else "new",
                    "locked_hash": h if seed else None,
                    "observed_hash": h,
                    "locked_def": definition if seed else None,
                    "observed_def": definition,
                    "suspicious": bool(scan["suspicious"]),
                    "scan": scan,
                    "approvals": [],
                    "case_id": case_id,
                    "seeded_by": seed,
                    "first_seen": now,
                    "last_seen": now,
                },
            )
        except DuplicateKeyError:
            raise ToolLockError("manifest changed concurrently; retry") from None

    def _moved(
        self,
        row: dict[str, Any],
        h: str,
        definition: str,
        scan: dict[str, Any],
        agent_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        """A known tool shows a different hash (or comes back after a removal)."""
        name = row["tool_name"]
        locked = row.get("locked_hash")
        if locked and h == locked:
            change, status = "restored", "approved"
        elif locked:
            change, status = "changed", "changed"
        else:
            change, status = "new", "new"
        upd: dict[str, Any] = {
            "status": status,
            "observed_hash": h,
            "observed_def": definition,
            "suspicious": bool(scan["suspicious"]),
            "scan": scan,
            "last_seen": now,
        }
        if status == "approved":
            upd["case_id"] = row.get("case_id")
        self._update(row, upd)
        self._chain(
            "mcp_tool_lock_change",
            agent_id,
            {
                "server_id": row["server_id"],
                "tool_name": _ascii(name),
                "change": change,
                "observed_hash": h,
                "locked_hash": locked,
                "previous_observed_hash": row.get("observed_hash"),
                "suspicious": bool(scan["suspicious"]),
                "finding_kinds": mcp_lock.finding_kinds(scan),
            },
        )
        if status != "approved":
            self._attach_case(row["server_id"], name, agent_id, h, scan, row=row)
        return {"tool": name, "change": change}

    def _server_row(
        self,
        server_id: str,
        agent_id: str,
        lhash: str,
        seed: str | None,
        now: datetime,
        row: dict[str, Any] | None,
    ) -> dict[str, Any]:
        rows = self._rows(server_id)
        pending = any(r["status"] in ("new", "changed") for n, r in rows.items() if n != SERVER_ROW)
        locked_list = row.get("locked_hash") if row else None
        if not pending:
            locked_list = lhash
        values = {
            "observed_hash": lhash,
            "locked_hash": locked_list,
            "status": "open" if pending else "locked",
            "last_seen": now,
        }
        if row is None:
            try:
                return dict(
                    self.state.insert(
                        "mcp_tool_manifest",
                        {
                            "manifest_id": manifest_id(server_id, SERVER_ROW),
                            "server_id": server_id,
                            "tool_name": SERVER_ROW,
                            "row_kind": "server",
                            "agent_id": agent_id,
                            "locked_def": None,
                            "observed_def": None,
                            "suspicious": False,
                            "scan": None,
                            "approvals": [],
                            "case_id": None,
                            "seeded_by": seed,
                            "first_seen": now,
                            **values,
                        },
                    )
                )
            except DuplicateKeyError:
                return {}
        if all(row.get(k) == v for k, v in values.items() if k != "last_seen"):
            return row
        return self._update(row, values)

    # ------------------------------------------------------------------ cases
    def _open_case(
        self, agent_id: str, server_id: str, ref: str, severity: str, summary: str
    ) -> str | None:
        if self.cases is None:
            return None
        try:
            case = self.cases.open_case(
                agent_id=agent_id,
                severity=severity,
                summary=summary,
                source_kind=SOURCE_KIND,
                source_ref=ref,
            )
            return str(case["case_id"])
        except Exception as exc:  # noqa: BLE001 - the lock holds even if the case cannot open
            log.error("mcp_tool_review case failed: %s", type(exc).__name__)
            return None

    def _attach_case(
        self,
        server_id: str,
        name: str,
        agent_id: str,
        h: str,
        scan: Mapping[str, Any],
        row: Mapping[str, Any] | None = None,
    ) -> None:
        sus = bool(scan.get("suspicious"))
        kinds = ",".join(mcp_lock.finding_kinds(scan)) or "none"
        case_id = self._open_case(
            agent_id,
            server_id,
            f"{server_id}:{hashlib.sha256(name.encode()).hexdigest()[:16]}:{h}",
            "high" if sus else "medium",
            f"MCP tool {_ascii(name)} on server {_ascii(server_id)} is new or changed and held "
            f"for two-person review. Hash {h[:16]}. Suspicious: {'yes' if sus else 'no'}"
            f" (scan findings: {kinds}).",
        )
        if case_id:
            cur = row or self.state.get(
                "mcp_tool_manifest", {"manifest_id": manifest_id(server_id, name)}
            )
            if cur is not None:
                fresh = self.state.get("mcp_tool_manifest", {"manifest_id": cur["manifest_id"]})
                self._update(fresh or cur, {"case_id": case_id})

    # ------------------------------------------------------------------ reads
    def view(self, server_id: str) -> dict[str, Any]:
        """What the proxy needs: visible and hidden tool names with their status."""
        check_server_id(server_id)
        rows = self._rows(server_id)
        srv = rows.get(SERVER_ROW)
        tools = {n: r for n, r in rows.items() if n != SERVER_ROW}
        return {
            "server_id": server_id,
            "known": srv is not None,
            "list_hash": srv.get("observed_hash") if srv else None,
            "locked_list_hash": srv.get("locked_hash") if srv else None,
            "visible": sorted(n for n, r in tools.items() if r["status"] == "approved"),
            "hidden": {
                n: r["status"]
                for n, r in sorted(tools.items())
                if r["status"] in ("new", "changed")
            },
            "removed": sorted(n for n, r in tools.items() if r["status"] == "removed"),
            "suspicious": sorted(n for n, r in tools.items() if _bool(r.get("suspicious"))),
        }

    def list_tools(self, server_id: str | None = None) -> list[dict[str, Any]]:
        where = {"server_id": check_server_id(server_id)} if server_id else None
        rows = self.state.query("mcp_tool_manifest", where, order_by=("server_id", "tool_name"))
        return [public_row(r) for r in rows if r["tool_name"] != SERVER_ROW]

    def servers(self) -> list[dict[str, Any]]:
        rows = self.state.query("mcp_tool_manifest", {"tool_name": SERVER_ROW})
        return [
            {
                "server_id": r["server_id"],
                "status": r["status"],
                "list_hash": r.get("observed_hash"),
                "locked_list_hash": r.get("locked_hash"),
                "seeded_by": r.get("seeded_by"),
            }
            for r in sorted(rows, key=lambda r: r["server_id"])
        ]

    def _tool_row(self, server_id: str, tool: str) -> dict[str, Any]:
        check_server_id(server_id)
        row = self.state.get("mcp_tool_manifest", {"manifest_id": manifest_id(server_id, tool)})
        if row is None or tool == SERVER_ROW:
            raise ToolLockError(f"tool {_ascii(tool)} is not known on server {_ascii(server_id)}")
        return dict(row)

    def diff(self, server_id: str, tool: str) -> dict[str, Any]:
        row = self._tool_row(server_id, tool)
        old = _json(row.get("locked_def"), None)
        new = _json(row.get("observed_def"), None)
        out = public_row(row)
        d = (
            mcp_lock.diff_tools(old, new)
            if old is not None
            else {"changed": [], "notes": ["never approved"]}
        )
        out["diff"] = d
        out["locked"] = old
        out["observed"] = new
        return out

    # ------------------------------------------------------------------ approval
    def propose(self, server_id: str, tool: str, by: str, observed_hash: str) -> dict[str, Any]:
        """First approval (an operator may give it). Same rules as ``approve``."""
        return self._approve(server_id, tool, by, observed_hash, "proposer")

    def approve(self, server_id: str, tool: str, by: str, observed_hash: str) -> dict[str, Any]:
        return self._approve(server_id, tool, by, observed_hash, "approver")

    def _approve(
        self, server_id: str, tool: str, by: str, observed_hash: str, role: str
    ) -> dict[str, Any]:
        if not isinstance(by, str) or not _USER.match(by):
            raise ToolLockError("the approving user name is not valid")
        if not isinstance(observed_hash, str) or not _FULL_HASH.match(observed_hash):
            # the FULL hash (F5): a 12-character prefix is 48 bits, which an upstream server can
            # match with a poisoned definition by brute force between "look" and "approve"
            raise ToolLockError(
                "observed_hash (all 64 hex characters, from diff) is required: approve what you "
                "reviewed"
            )
        with self._lock:
            row = self._tool_row(server_id, tool)
            if row["status"] == "approved":
                raise ToolLockError("this tool is already approved")
            if row["status"] == "removed":
                raise ToolLockError("this tool is no longer listed by the server")
            if not hmac.compare_digest(str(row["observed_hash"]), observed_hash.lower()):
                raise ToolLockError(
                    "the tool changed since you reviewed it (hash differs); review the diff again"
                )
            ap = valid_approvals(row)
            if any(a["by"].lower() == by.lower() for a in ap):
                raise ToolLockError(
                    f"{by} already approved this change; a second, different person must approve"
                )
            now = self.clock.now()
            entry = {"by": by, "role": role, "at": format_ts(now), "hash": row["observed_hash"]}
            others = [a for a in _json(row.get("approvals"), []) if a not in ap]
            approvals = [*others, *ap, entry][-20:]
            done = len(ap) + 1 >= APPROVALS_NEEDED
            if done and role == "proposer":
                # F2: ``propose`` (operators may) never completes the lock; the approval that
                # locks needs ``mcp.tools.approve`` (ADR D24 decision 3)
                raise ToolLockError(
                    "the second approval needs mcp.tools.approve: use approve, not propose"
                )
            agent_id = row["agent_id"]
            if not done:
                self._update(row, {"approvals": approvals})
                self._chain(
                    "mcp_tool_approval",
                    agent_id,
                    {
                        "server_id": server_id,
                        "tool_name": _ascii(tool),
                        "principal": by,
                        "role": role,
                        "observed_hash": row["observed_hash"],
                        "status": "pending_second",
                    },
                )
                return {
                    **public_row({**row, "approvals": approvals}),
                    "locked": False,
                    "needs": "a second, different person",
                }
            self._update(
                row,
                {
                    "approvals": approvals,
                    "status": "approved",
                    "locked_hash": row["observed_hash"],
                    "locked_def": row.get("observed_def"),
                    "last_seen": now,
                },
            )
            self._chain(
                "mcp_tool_approval",
                agent_id,
                {
                    "server_id": server_id,
                    "tool_name": _ascii(tool),
                    "principal": by,
                    "role": role,
                    "approvers": sorted({a["by"] for a in [*ap, entry]}),
                    "observed_hash": row["observed_hash"],
                    "previous_locked_hash": row.get("locked_hash"),
                    "status": "locked",
                },
            )
            self._refresh_server_row(server_id, now)
            fresh = self._tool_row(server_id, tool)
            return {**public_row(fresh), "locked": True}

    def _refresh_server_row(self, server_id: str, now: datetime) -> None:
        rows = self._rows(server_id)
        srv = rows.get(SERVER_ROW)
        if srv is None:
            return
        pending = any(r["status"] in ("new", "changed") for n, r in rows.items() if n != SERVER_ROW)
        changes: dict[str, Any] = {"status": "open" if pending else "locked", "last_seen": now}
        if not pending:
            changes["locked_hash"] = srv.get("observed_hash")
        self._update(srv, changes)

    # ------------------------------------------------------------------ blocked calls
    def report_block(self, server_id: str, tool: str, agent_id: str, rule_id: str) -> None:
        """Chain record for a tools/call the proxy refused (the lock, not the gate)."""
        check_server_id(server_id)
        if not _AGENT.match(agent_id or ""):
            raise ToolLockError("agent_id is not valid")
        self._chain(
            "mcp_tool_blocked",
            agent_id,
            {
                "server_id": server_id,
                "tool_name": _ascii(tool),
                "rule_id": _ascii(rule_id, 64),
            },
        )


def inventory_hook(state: Any, clock: Clock) -> Callable[[str, str], None]:
    """WP24 link: register the upstream server as an ``mcp_server`` inventory node, used by the
    agent that first listed it (evidence source ``manual``, ref ``mcp_tool_manifest``). Pass as
    ``on_new_server`` when INVENTORY_ENABLED=1."""

    def register(server_id: str, agent_id: str) -> None:
        from supervisor.inventory.graph import Graph
        from supervisor.inventory.model import Edge, Node, node_id_for
        from supervisor.inventory.store import InventoryStore

        g = Graph()
        node = Node("mcp_server", server_id, attrs={"gateway": "mcp_http"})
        ref = f"mcp_tool_manifest:{server_id}"
        node.add_evidence("manual", ref)
        g.add_node(node)
        g.add_edge(Edge(node_id_for("system", agent_id), node.node_id, "uses", "manual", ref))
        InventoryStore(state, clock).apply(g, source="manual")

    return register
