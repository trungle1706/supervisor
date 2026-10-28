"""Facts card: "what we know about this agent" (WP-O2, phase 9, flag ONBOARD_FACTS).

``FactsService.build(node_id, n)`` runs Discover and Understand on the stored, scrubbed tree of
intake attempt ``n`` (``IntakeService.tree_path``), on the server, and writes one
``onboard_facts`` row per fact. Every fact has a file, a line and a scrubbed quote of at most
200 characters.

* Rule facts (``source=rule``) come from the inventory and the profile that Discover and
  Understand build from fixed rules.
* Model facts (``source=model``) are the extra claims the real gateway model proposes in
  ``understand``; ``validate_llm_claims`` keeps a claim only when its file:line exists and holds
  the quote. A claim without file:line is dropped and counted in the summary row
  (``kind=summary``, ``dropped_claims``). With a mock model (no LLM configured) the LLM step is
  skipped; the summary row says so and its ``model_id`` names the mock.
* Building again for the same attempt keeps the ``fact_id`` of a fact that is found again and
  sets ``active=false`` on a fact that is not found again (the state store has no delete).
* With the flag on, tools, models and endpoints, and datasets also become ``uses`` / ``reads`` /
  ``writes`` edges of the inventory graph (source ``onboard_facts``, the pointer as evidence), so
  the register prefill and the risk inheritance see them.

A secret never reaches a row: the tree is scrubbed by WP-O1, Discover scrubs again, and every text
of a row goes through the scrubber once more before it is stored.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.core.canonical import format_ts
from supervisor.core.errors import SupervisorError
from supervisor.core.ports import ChatModel
from supervisor.inventory.model import TOOL_CLASS_RISK, Edge, Node, node_id_for
from supervisor.onboard import intake
from supervisor.onboard.discover import Discovery, discover
from supervisor.onboard.models import AgentProfile, Evidence
from supervisor.onboard.scrub import scrub_text
from supervisor.onboard.understand import understand

KINDS = (
    "tool",
    "model",
    "endpoint",
    "dataset",
    "file",
    "secret_use",
    "external_url",
    "mcp_server",
    "approval_point",
    "autonomy",
    "decision33",
    "weak_spot",
    "claim",
)
SUMMARY = "summary"
SOURCES = ("rule", "model")
EDGE_SOURCE = "onboard_facts"
MAX_DETAIL = 500
MAX_QUOTE = 200
MAX_PER_KIND = 150
FLAG_TEXT = "facts_off: the facts card is off (ONBOARD_FACTS=1 turns it on)"
_REDACTED = re.compile(r"\[REDACTED:([A-Za-z0-9_]+)\]")
_URL = re.compile(r"https?://[^\s\"'<>)\]}\\,;]{3,200}")
_URL_FILES = (".py", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".sql")
_LOCK = threading.RLock()


class FactsError(SupervisorError):
    """A refused request. ``code`` is the stable machine word; the message starts with it."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def require_on(settings: Any) -> None:
    if not settings.onboard_facts:
        raise FactsError("facts_off", FLAG_TEXT.split(": ", 1)[1])


def _clean(text: Any, limit: int) -> str:
    """Scrub once more, drop control characters, cut to ``limit``."""
    raw = "".join(c if c in "\t " or ord(c) >= 32 else " " for c in str(text or ""))
    return scrub_text(raw).text.strip()[:limit]


def fact_id_for(node_id: str, n: int, kind: str, name: str, file: str, line: int | None) -> str:
    digest = hashlib.sha256(
        "\x00".join([node_id, str(n), kind, name, file, str(line or 0)]).encode("utf-8")
    ).hexdigest()
    return "fct_" + digest[:20]


class _Rows:
    """Collects fact rows, de-duplicated by fact id, capped per kind."""

    def __init__(self, node_id: str, n: int) -> None:
        self.node_id, self.n = node_id, n
        self.rows: dict[str, dict[str, Any]] = {}
        self.per_kind: dict[str, int] = {}
        self.skipped = 0

    def add(
        self,
        kind: str,
        name: str,
        detail: str,
        ev: Evidence | None,
        *,
        source: str = "rule",
        model_id: str | None = None,
    ) -> None:
        if ev is None or not ev.file or ev.file == "<none>":
            self.skipped += 1  # a fact without a pointer is not a fact
            return
        if self.per_kind.get(kind, 0) >= MAX_PER_KIND:
            return
        name_c = _clean(name, 200) or kind
        file_c = _clean(ev.file, 300)
        fid = fact_id_for(self.node_id, self.n, kind, name_c, file_c, ev.line)
        if fid in self.rows:
            return
        self.per_kind[kind] = self.per_kind.get(kind, 0) + 1
        self.rows[fid] = {
            "fact_id": fid,
            "node_id": self.node_id,
            "attempt_n": self.n,
            "kind": kind,
            "name": name_c,
            "detail": _clean(detail, MAX_DETAIL),
            "file": file_c,
            "line": int(ev.line),
            "quote": _clean(ev.quote, MAX_QUOTE),
            "source": source,
            "model_id": model_id,
            "dropped_claims": None,
            "active": True,
        }


def collect_rows(
    node_id: str, n: int, disc: Discovery, profile: AgentProfile
) -> tuple[list[dict[str, Any]], int]:
    """The fact rows of one Discover + Understand result (no summary row). Returns the rows and
    the count of rule facts left out because they have no pointer."""
    inv, idx = disc.inventory, disc.index
    out = _Rows(node_id, n)
    first = _first_ev(disc)
    llm_id = profile.llm.model_id

    purpose = profile.purpose
    out.add("claim", "purpose", purpose.claim, purpose.evidence[0])

    reversible = {c.claim.split(" ", 1)[0]: c.claim for c in profile.reversibility}
    for t in inv.tools:
        bits = [f"risk_class={t.risk_class}", f"approved={'yes' if t.approved else 'no'}"]
        if t.side_effects or t.mutates:
            bits.append("side_effects=" + ",".join(sorted({*t.side_effects, *t.mutates})))
        if t.name in reversible:
            bits.append("reversibility: " + reversible[t.name])
        out.add("tool", t.name, "; ".join(bits), t.definition or t.manifest_entry or first)

    for call in inv.llm_calls:
        label = call.model or call.family
        out.add(
            "model",
            label,
            f"provider={call.provider}; family={call.family}; via={call.via}",
            call.evidence,
        )
    for ep in inv.model_endpoints:
        family = ep.family
        if not family and ep.name == inv.model_id and inv.model_family != "unknown":
            family = inv.model_family
        out.add(
            "endpoint",
            ep.name,
            f"family={family or 'unknown'}; declared in {ep.source}",
            ep.evidence,
        )
    for tb in inv.tables:
        out.add("dataset", tb.name, f"direction={tb.direction}; source={tb.source}", tb.evidence)
    for da in inv.data_access:
        target = da.target or da.kind
        if da.kind == "file":
            out.add("file", target, f"direction={da.direction}", da.evidence)
        elif da.kind == "http":
            out.add("external_url", target, f"direction={da.direction}", da.evidence)
        else:
            out.add("dataset", target, f"direction={da.direction}; via={da.kind}", da.evidence)
    urls_seen = {(r.file, r.line) for r in inv.data_access if r.kind == "http"}
    for file in sorted(idx.lines):
        if not file.endswith(_URL_FILES):
            continue
        for i, text in enumerate(idx.lines[file], start=1):
            m = _URL.search(text)
            if m and (file, i) not in urls_seen:
                out.add(
                    "external_url",
                    re.split(r"[?#]", m.group(0), maxsplit=1)[0],
                    "an address in the code (query and fragment are not stored)",
                    idx.evidence(file, i),
                )
    for ref in inv.secret_refs:
        m = _REDACTED.search(ref.quote)
        out.add(
            "secret_use",
            m.group(1) if m else "secret",
            "a secret-looking value is in the code (kind only; the value is never stored)",
            ref,
        )
    for srv in inv.mcp_servers:
        out.add("mcp_server", srv.name, srv.detail or "MCP server", srv.evidence)
    for ev in inv.human_approval_refs:
        out.add("approval_point", "human approval step", "a human approval step in the code", ev)
    for where, names in sorted(inv.interrupt_guards.items()):
        file, _, line = where.rpartition(":")
        if file and line.isdigit():
            out.add(
                "approval_point",
                "interrupt before " + ",".join(names[:4]),
                "a LangGraph interrupt guards: " + ", ".join(names[:8]),
                idx.evidence(file, int(line)),
            )
    out.add(
        "autonomy",
        profile.autonomy or "unknown",
        profile.autonomy_reason,
        _autonomy_ev(disc, profile) or first,
    )
    d33 = profile.decision33
    out.add(
        "decision33",
        d33.classification,
        f"proposal only, counsel confirms; human_gate_in_code={d33.human_gate_in_code}",
        (d33.entries[0].evidence[0] if d33.entries else first),
    )
    for e in d33.entries:
        out.add(
            "decision33",
            f"{e.entry} {'triggered' if e.triggered else 'not triggered'}",
            e.reason,
            e.evidence[0],
        )

    seen_claims = {id(c) for c in profile.weak_spots}
    for c in profile.weak_spots:
        model = c.source == "llm"
        out.add(
            "weak_spot",
            c.claim.removeprefix("[llm] ")[:200],
            c.claim,
            c.evidence[0],
            source="model" if model else "rule",
            model_id=llm_id if model else None,
        )
    extra = [*profile.capabilities, *profile.reversibility, *profile.personal_data]
    for c in extra:
        if id(c) in seen_claims:
            continue
        if c.source == "llm":
            out.add(
                "claim",
                f"{c.category}: {c.claim.removeprefix('[llm] ')}"[:200],
                c.claim,
                c.evidence[0],
                source="model",
                model_id=llm_id,
            )
        elif c.category == "personal_data":
            out.add("claim", c.claim, "category=personal_data", c.evidence[0])
    return list(out.rows.values()), out.skipped


def _first_ev(disc: Discovery) -> Evidence | None:
    inv = disc.inventory
    f = inv.manifest_file or (inv.files[0] if inv.files else "")
    return disc.index.evidence(f, 1) if f else None


def _autonomy_ev(disc: Discovery, profile: AgentProfile) -> Evidence | None:
    for t in disc.inventory.tools:
        if profile.autonomy in ("L2", "L3") and t.risk_class in ("money", "credit"):
            return t.definition or t.manifest_entry
    return None


def direction_of(detail: str) -> str:
    m = re.search(r"direction=(read|write)", detail or "")
    return m.group(1) if m else "read"


class FactsService:
    """Facts of one app. ``chat`` builds the model for the claims step; the default is the
    gateway model (``make_chat_model``: the real adapter when LLM_BASE_URL is set, else a
    labelled mock, for which ``understand`` skips the LLM step)."""

    def __init__(
        self,
        settings: Any,
        state: Any,
        clock: Any,
        *,
        chat_factory: Callable[[], ChatModel] | None = None,
    ) -> None:
        self.settings = settings
        self.state = state
        self.clock = clock
        self._chat_factory = chat_factory

    # ------------------------------------------------------------------ helpers
    def _chat(self) -> ChatModel:
        if self._chat_factory is not None:
            return self._chat_factory()
        from supervisor.adapters.factory import make_chat_model  # late: keeps imports light

        return make_chat_model(self.settings)

    def _intake(self) -> intake.IntakeService:
        return intake.IntakeService(self.settings, self.state, self.clock)

    def latest_attempt(self, node_id: str) -> int | None:
        """The newest intake attempt that was stored (status not ``failed``)."""
        ns = [
            int(r["n"])
            for r in self.state.query("intake_attempt", {"node_id": node_id})
            if r["status"] != "failed"
        ]
        return max(ns) if ns else None

    # ------------------------------------------------------------------ read
    def rows(self, node_id: str, n: int) -> list[dict[str, Any]]:
        rows = [
            dict(r)
            for r in self.state.query("onboard_facts", {"node_id": node_id, "attempt_n": n})
            if _bool(r.get("active"))
        ]
        rows.sort(key=lambda r: (_kind_rank(r["kind"]), r["name"], r["file"] or "", r["line"] or 0))
        return [row_view(r) for r in rows]

    def built_attempt(self, node_id: str) -> int | None:
        ns = [
            int(r["attempt_n"])
            for r in self.state.query("onboard_facts", {"node_id": node_id})
            if _bool(r.get("active"))
        ]
        return max(ns) if ns else None

    def card(self, node_id: str) -> dict[str, Any]:
        """The newest built card of a node: groups by kind, the summary, the dropped count."""
        intake.check_node_id(node_id)
        built = self.built_attempt(node_id)
        latest = self.latest_attempt(node_id)
        rows = self.rows(node_id, built) if built is not None else []
        summary = next((r for r in rows if r["kind"] == SUMMARY), None)
        facts = [r for r in rows if r["kind"] != SUMMARY]
        groups = []
        for kind in KINDS:
            items = [r for r in facts if r["kind"] == kind]
            if items:
                groups.append({"kind": kind, "rows": items})
        return {
            "node_id": node_id,
            "attempt_n": built,
            "latest_attempt": latest,
            "newer_attempt": bool(latest is not None and built is not None and latest > built),
            "groups": groups,
            "total": len(facts),
            "summary": summary,
            "dropped_claims": int(summary["dropped_claims"] or 0) if summary else 0,
            "rows": rows,
        }

    # ------------------------------------------------------------------ write
    def build(self, node_id: str, n: int) -> dict[str, Any]:
        """Read attempt ``n`` of ``node_id`` and write its fact rows. Returns the card."""
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
            raise FactsError("no_attempt", f"attempt {n} of {node_id} does not exist")
        if attempt["status"] == "failed":
            raise FactsError("attempt_failed", f"attempt {n} was refused; there is no source")
        tree: Path = self._intake().tree_path(node_id, n)
        if not tree.is_dir():
            raise FactsError(
                "tree_missing",
                f"the stored source of attempt {n} is not on this server any more; upload again",
            )
        try:
            disc = discover(LocalGitRepoReader(tree))
            chat = self._chat()
            profile = understand(disc, chat)
        except FactsError:
            raise
        except SupervisorError as exc:
            raise FactsError("read_failed", _clean(exc, 200)) from None
        rows, skipped = collect_rows(node_id, n, disc, profile)
        rows.append(self._summary_row(node_id, n, profile, len(rows), skipped))
        with _LOCK:
            self._store(node_id, n, rows)
            self._feed_graph(node_id, n, disc)
        return self.card(node_id)

    def _summary_row(
        self, node_id: str, n: int, profile: AgentProfile, count: int, skipped: int
    ) -> dict[str, Any]:
        llm = profile.llm
        model_id = llm.model_id
        if llm.is_mock and "mock" not in model_id:
            model_id = "mock:" + model_id
        text = (
            f"facts={count}; skipped_without_pointer={skipped}; "
            f"model_used={'yes' if llm.used else 'no'}; "
            f"claims_proposed={llm.claims_proposed}; claims_kept={llm.claims_kept}; "
            f"claims_dropped={llm.claims_dropped}; {llm.note}"
        )
        if llm.is_mock:
            text = "MOCK MODEL: " + text
        return {
            "fact_id": fact_id_for(node_id, n, SUMMARY, "build", "", 0),
            "node_id": node_id,
            "attempt_n": n,
            "kind": SUMMARY,
            "name": "build",
            "detail": _clean(text, MAX_DETAIL),
            "file": None,
            "line": None,
            "quote": None,
            "source": "model" if llm.used else "rule",
            "model_id": _clean(model_id, 120),
            "dropped_claims": int(llm.claims_dropped),
            "active": True,
        }

    def _store(self, node_id: str, n: int, rows: list[dict[str, Any]]) -> None:
        now = self.clock.now()
        old = {
            r["fact_id"]: r
            for r in self.state.query("onboard_facts", {"node_id": node_id, "attempt_n": n})
        }
        keep = {r["fact_id"] for r in rows}
        for row in rows:
            cur = old.get(row["fact_id"])
            if cur is None:
                self.state.insert("onboard_facts", {**row, "created_at": now})
            else:
                changes = {k: v for k, v in row.items() if k not in ("fact_id", "node_id")}
                self.state.update(
                    "onboard_facts", {"fact_id": row["fact_id"]}, changes, cur["row_version"]
                )
        for fid, cur in old.items():
            if fid not in keep and _bool(cur.get("active")):
                self.state.update(
                    "onboard_facts", {"fact_id": fid}, {"active": False}, cur["row_version"]
                )

    # ------------------------------------------------------------------ inventory graph
    def _feed_graph(self, node_id: str, n: int, disc: Discovery) -> None:
        """uses / reads / writes edges from the active fact rows of this attempt."""
        from supervisor.inventory.graph import Graph
        from supervisor.inventory.store import InventoryStore

        rows = [
            r
            for r in self.rows(node_id, n)
            if r["kind"] in ("tool", "model", "endpoint", "dataset")
        ]
        store = InventoryStore(self.state, self.clock)
        sysn, exists = self._source_node(node_id, n)
        g = Graph()
        if not exists:
            g.add_node(sysn)
        for r in rows:
            ref = f"{r['file']}:{r['line']}"
            if r["kind"] == "tool":
                cls = _risk_class(r["detail"])
                node = Node(
                    "tool",
                    f"{sysn.name}/{r['name']}",
                    display_name=r["name"],
                    own_risk=TOOL_CLASS_RISK.get(cls),
                    risk_source="onboarding" if cls in TOOL_CLASS_RISK else "none",
                    attrs={"risk_class": cls, "agent": sysn.name, "risk_basis": "onboard_facts"},
                )
                edge = "uses"
            elif r["kind"] in ("model", "endpoint"):
                node = Node("model_endpoint", r["name"], attrs={"declared_in": "onboard_facts"})
                edge = "uses"
            else:
                node = Node("dataset", r["name"])
                edge = "writes" if direction_of(r["detail"]) == "write" else "reads"
            node.add_evidence(EDGE_SOURCE, ref)
            g.add_node(node)
            g.add_edge(Edge(sysn.node_id, node.node_id, edge, EDGE_SOURCE, ref))
        store.apply(g, source=EDGE_SOURCE)
        store.deactivate_edges(sysn.node_id, EDGE_SOURCE, keep=set(g.edges))

    def _source_node(self, node_id: str, n: int) -> tuple[Node, bool]:
        """The inventory node the edges start from: the node itself when it is one, else the
        system node of the agent id (a new one when the inventory does not know it yet).
        Returns the node and whether it exists."""
        from supervisor.inventory.store import node_from_row

        row = self.state.get("inventory_node", {"node_id": node_id})
        if row is None:
            row = self.state.get("inventory_node", {"node_id": node_id_for("system", node_id)})
        if row is not None:
            return node_from_row(dict(row)), True
        node = Node("system", node_id, attrs={"role": "agent"})
        node.add_evidence(EDGE_SOURCE, f"intake:{node_id}/{n}")
        return node, False


# ------------------------------------------------------------------------------ small helpers


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def _kind_rank(kind: str) -> int:
    order = (*KINDS, SUMMARY)
    return order.index(kind) if kind in order else len(order)


def _risk_class(detail: str) -> str:
    m = re.search(r"risk_class=([a-z_]+)", detail or "")
    return m.group(1) if m else ""


def row_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """The public shape of a fact row."""
    created = row.get("created_at")
    return {
        "fact_id": row["fact_id"],
        "node_id": row["node_id"],
        "attempt_n": int(row["attempt_n"]),
        "kind": row["kind"],
        "name": row["name"],
        "detail": row.get("detail") or "",
        "file": row.get("file"),
        "line": int(row["line"]) if row.get("line") is not None else None,
        "quote": row.get("quote"),
        "source": row["source"],
        "model_id": row.get("model_id"),
        "dropped_claims": int(row["dropped_claims"])
        if row.get("dropped_claims") is not None
        else None,
        "created_at": format_ts(created)
        if created is not None and not isinstance(created, str)
        else created,
    }
