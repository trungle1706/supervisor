"""Hash-chain writer (``EvidenceSink``): one lane per agent plus a root lane.

Entry (table ``chain_entry``)::

    payload_hash = sha256(canonical(payload))
    entry_hash   = sha256(canonical({lane, seq, ts, record_type, record_ref,
                                     payload_hash, prev_hash,
                                     writer, env, chain_spec_version}))

* ``seq`` is per lane, starts at 0, +1 per entry; ``prev_hash`` of seq 0 is 64 zeros.
* Spec v2 (current): ``entry_hash`` also covers ``writer``, ``env`` and
  ``chain_spec_version`` (2). Spec v1 entries did not; the verifier still reads them.
* ``ts`` comes from the injected ``Clock``.
* The payload is stored separately (table ``chain_payload``) as canonical JSON text.
  It must already be masked (hashes and masked excerpts only, never raw PII); an
  optional ``Masker`` is applied to every string value before hashing. Floats are
  rejected (scores are integer basis points, money integer minor units).
* Lane selection: ``lane=`` argument, else ``agent:<payload['agent_id']>``, else ``root``.
* Single writer: one process-level lock serialises every append, one active
  ``ChainWriter`` per TableStore in a process, and a ``writer_id`` on every entry.
  A second process writing the same lane hits the primary key (lane, seq) and
  gets ``ChainConflictError``: the chain is never forked silently.
* Every ``root_every_n`` entries or ``root_every_s`` seconds (and when a new lane
  opens) a ``root_commit`` entry on the root lane commits the heads of all lanes
  and is signed with the ``Signer`` (row in ``chain_signature``).
  Backlog: a Merkle root over the day's entries (ADR D05); v0 commits a list of heads.
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import threading
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from supervisor.core.canonical import CanonicalError, canonical_json, sha256_bytes_hex
from supervisor.core.errors import DuplicateKeyError, SupervisorError
from supervisor.core.models import ChainEntry
from supervisor.core.ports import Clock, Masker, Signer, TableStore
from supervisor.evidence.verify import (
    ALGORITHM,
    CHAIN_SPEC_VERSION,
    GENESIS_HASH,
    KEY_ROTATION_RECORD_TYPE,
    ROOT_LANE,
    ROOT_RECORD_TYPE,
    entry_hash,
    signing_message,
)

LANE_RE = re.compile(r"^(root|agent:[A-Za-z0-9._@/-]{1,200})$")
_PROCESS_LOCK = threading.RLock()
_ACTIVE: weakref.WeakKeyDictionary[Any, str] = weakref.WeakKeyDictionary()


class ChainError(SupervisorError):
    """The evidence chain cannot accept this record."""


class FloatInPayloadError(ChainError, CanonicalError):
    """A chain payload contains a float. Use integer basis points or minor units."""


class KeyContinuityError(ChainError):
    """The signing key differs from the key of the latest root_commit."""


class ChainConflictError(ChainError):
    """Another writer appended to the same lane: single-writer rule broken."""


def check_no_floats(value: Any, path: str = "$") -> None:
    """Raise FloatInPayloadError if ``value`` contains a float anywhere."""
    if isinstance(value, float):
        raise FloatInPayloadError(
            f"{path}: float {value!r} is not allowed in a chain payload "
            "(use integer basis points 0-10000 or integer minor units)"
        )
    if isinstance(value, Mapping):
        for k, v in value.items():
            check_no_floats(v, f"{path}.{k}")
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            check_no_floats(v, f"{path}[{i}]")
    elif hasattr(value, "model_dump"):
        check_no_floats(value.model_dump(mode="python"), path)


def _mask_strings(value: Any, mask: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, Mapping):
        return {k: _mask_strings(v, mask) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_mask_strings(v, mask) for v in value]
    return value


def default_writer_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass(frozen=True)
class LaneHead:
    seq: int
    entry_hash: str


class ChainWriter:
    """EvidenceSink that appends hash-chained entries to ``chain_entry``."""

    def __init__(
        self,
        tables: TableStore,
        clock: Clock,
        signer: Signer,
        *,
        writer_id: str | None = None,
        env: str = "dev",
        root_every_n: int = 100,
        root_every_s: int = 900,
        masker: Masker | None = None,
        mask_version: str = "caller-masked",
        allow_rotation: bool = False,
    ) -> None:
        if root_every_n < 1 or root_every_s < 1:
            raise ChainError("root_every_n and root_every_s must be >= 1")
        self.tables = tables
        self.clock = clock
        self.signer = signer
        self.writer_id = writer_id or default_writer_id()
        self.env = env
        self.root_every_n = root_every_n
        self.root_every_s = root_every_s
        self.masker = masker
        self.mask_version = mask_version
        self._heads: dict[str, LaneHead | None] = {}
        self._since_root = 0
        self._last_root_ts: datetime | None = None
        self._closed = False
        with _PROCESS_LOCK:
            try:
                owner = _ACTIVE.get(tables)
            except TypeError:  # store not weak-referenceable
                owner = None
            if owner is not None:
                raise ChainConflictError(
                    f"a chain writer ({owner}) is already active for this store in this "
                    "process; close it first (single-writer rule)"
                )
            try:
                _ACTIVE[tables] = self.writer_id
            except TypeError:
                pass
            try:
                self._load_root_state()
                self._check_key_continuity(allow_rotation)
            except BaseException:
                try:
                    if _ACTIVE.get(tables) == self.writer_id:
                        del _ACTIVE[tables]
                except TypeError:
                    pass
                raise

    # ------------------------------------------------------------ public API

    def record(
        self,
        record_type: str,
        record_ref: str,
        payload: Mapping[str, Any],
        *,
        lane: str | None = None,
    ) -> str:
        """Append one entry. Return its entry hash (hex)."""
        if record_type == ROOT_RECORD_TYPE:
            raise ChainError("root_commit entries are written by commit_root() only")
        if record_type == KEY_ROTATION_RECORD_TYPE:
            raise ChainError("key_rotation entries are written at writer start only")
        if not record_type or not record_ref:
            raise ChainError("record_type and record_ref are required")
        if not isinstance(payload, Mapping):
            raise ChainError("payload must be a mapping")
        if lane is None:
            agent_id = payload.get("agent_id")
            lane = f"agent:{agent_id}" if agent_id else ROOT_LANE
        with _PROCESS_LOCK:
            self._check_open()
            new_lane = lane != ROOT_LANE and self._head(lane) is None
            h = self._append(lane, record_type, record_ref, payload)
            self._since_root += 1
            if new_lane or self._root_due():
                self.commit_root()
            return h

    def commit_root(self, *, force: bool = False) -> str | None:
        """Write and sign a root entry committing every lane head.

        Returns the root entry hash, or None when nothing changed since the last
        root and ``force`` is False."""
        with _PROCESS_LOCK:
            self._check_open()
            if self._since_root == 0 and not force and self._last_root_ts is not None:
                return None
            lanes = {
                name: {"seq": head.seq, "entry_hash": head.entry_hash}
                for name, head in sorted(self._heads.items())
                if head is not None and name != ROOT_LANE
            }
            payload = {
                "kind": ROOT_RECORD_TYPE,
                "chain_spec_version": CHAIN_SPEC_VERSION,
                "lanes": lanes,
                "lane_count": len(lanes),
                "writer": self.writer_id,
                "key_id": self.signer.key_id,
                "algorithm": ALGORITHM,
                "mask_version": self.mask_version,
            }
            head = self._head(ROOT_LANE)
            seq = 0 if head is None else head.seq + 1
            h = self._append(ROOT_LANE, ROOT_RECORD_TYPE, f"root:{seq}", payload, sign=True)
            self._since_root = 0
            self._last_root_ts = self.clock.now()
            return h

    def heads(self) -> dict[str, LaneHead]:
        """Current head of every lane this writer knows."""
        with _PROCESS_LOCK:
            return {k: v for k, v in self._heads.items() if v is not None}

    def close(self, *, seal: bool = True) -> None:
        """Seal pending entries with a root commit and release the writer slot."""
        with _PROCESS_LOCK:
            if self._closed:
                return
            try:
                if seal and self._since_root:
                    self.commit_root()
            finally:
                self._closed = True
                try:
                    if _ACTIVE.get(self.tables) == self.writer_id:
                        del _ACTIVE[self.tables]
                except TypeError:
                    pass

    def __enter__(self) -> ChainWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close(seal=exc[0] is None)

    # ------------------------------------------------------------ internals

    def _check_open(self) -> None:
        if self._closed:
            raise ChainError("chain writer is closed")

    def _root_due(self) -> bool:
        if self._since_root >= self.root_every_n:
            return True
        if self._last_root_ts is None:
            return True
        return (self.clock.now() - self._last_root_ts).total_seconds() >= self.root_every_s

    def _head(self, lane: str) -> LaneHead | None:
        if lane not in self._heads:
            rows = self.tables.query("chain_entry", {"lane": lane}, order_by=["-seq"], limit=1)
            self._heads[lane] = LaneHead(rows[0]["seq"], rows[0]["entry_hash"]) if rows else None
        return self._heads[lane]

    def _load_root_state(self) -> None:
        """Learn lane heads from the last root commit (lanes are re-read on use)."""
        rows = self.tables.query(
            "chain_entry",
            {"lane": ROOT_LANE, "record_type": ROOT_RECORD_TYPE},
            order_by=["-seq"],
            limit=1,
        )
        if not rows:
            return
        self._last_root_ts = rows[0]["ts"]
        root = rows[0]
        payloads = self.tables.query(
            "chain_payload",
            {"lane": ROOT_LANE, "seq": root["seq"], "payload_hash": root["payload_hash"]},
            limit=1,
        )
        committed: dict[str, Any] = {}
        if payloads:
            committed = json.loads(payloads[0]["payload"]).get("lanes", {})
            for name in committed:
                self._head(name)  # current head from the table, not the root snapshot
        root_head = self._head(ROOT_LANE)
        # Entries written after the last root by an earlier process stay unsealed
        # until the next root; the verifier reports them as "not yet sealed".
        changed = root_head is None or root_head.entry_hash != root["entry_hash"]
        for name, snap in committed.items():
            head = self._heads.get(name)
            if head is None or head.entry_hash != snap.get("entry_hash"):
                changed = True
        self._since_root = 1 if changed or not payloads else 0

    def _check_key_continuity(self, allow_rotation: bool) -> None:
        """Refuse to start with a key other than the one on the latest root_commit.

        With ``allow_rotation`` write a ``key_rotation`` entry (root lane, signed by the new
        key) that names the old and the new key id, then continue."""
        rows = self.tables.query(
            "chain_signature", {"lane": ROOT_LANE}, order_by=["-seq"], limit=50
        )
        roots = self.tables.query(
            "chain_entry",
            {"lane": ROOT_LANE, "record_type": ROOT_RECORD_TYPE},
            order_by=["-seq"],
            limit=1,
        )
        if not roots:
            return
        old = next((r["key_id"] for r in rows if r["seq"] == roots[0]["seq"]), None)
        if old is None or old == self.signer.key_id:
            return
        if not allow_rotation:
            raise KeyContinuityError(
                f"signing key {self.signer.key_id[:16]}... differs from key {str(old)[:16]}... "
                "of the latest root_commit; earlier roots would not verify with the new key. "
                "Restore the old key, or set SIGNER_ALLOW_ROTATION=1 once to record a "
                "key_rotation entry"
            )
        head = self._head(ROOT_LANE)
        seq = 0 if head is None else head.seq + 1
        self._append(
            ROOT_LANE,
            KEY_ROTATION_RECORD_TYPE,
            f"key_rotation:{seq}",
            {
                "kind": KEY_ROTATION_RECORD_TYPE,
                "chain_spec_version": CHAIN_SPEC_VERSION,
                "old_key_id": old,
                "new_key_id": self.signer.key_id,
                "algorithm": ALGORITHM,
                "writer": self.writer_id,
            },
            sign=True,
        )
        self._since_root = max(self._since_root, 1)  # next root seals under the new key

    def _prepare_payload(self, payload: Mapping[str, Any]) -> str:
        check_no_floats(payload)
        if self.masker is not None:
            payload = _mask_strings(payload, self.masker.mask)
        try:
            return canonical_json(payload)
        except CanonicalError as exc:
            raise ChainError(f"payload is not canonicalisable: {exc}") from exc

    def _append(
        self,
        lane: str,
        record_type: str,
        record_ref: str,
        payload: Mapping[str, Any],
        *,
        sign: bool = False,
    ) -> str:
        if not LANE_RE.match(lane):
            raise ChainError(f"invalid lane name {lane!r} (root or agent:<id>)")
        text = self._prepare_payload(payload)
        payload_hash = sha256_bytes_hex(text.encode("utf-8"))
        head = self._head(lane)
        seq = 0 if head is None else head.seq + 1
        prev = GENESIS_HASH if head is None else head.entry_hash
        ts = self.clock.now()
        fields = {
            "lane": lane,
            "seq": seq,
            "ts": ts,
            "record_type": record_type,
            "record_ref": record_ref,
            "payload_hash": payload_hash,
            "prev_hash": prev,
        }
        # Spec v2: writer, env and the spec version are hashed too.
        h = entry_hash(
            {
                **fields,
                "writer": self.writer_id,
                "env": self.env,
                "chain_spec_version": CHAIN_SPEC_VERSION,
            }
        )
        entry = ChainEntry(**fields, entry_hash=h, writer=self.writer_id, env=self.env)
        # Commit order: payload, signature, then the entry (the commit point). A crash
        # before the entry leaves only orphan rows keyed by their hash; export ignores
        # them and a retry (new ts -> new hashes) does not collide with them.
        self._append_side(
            "chain_payload",
            {"lane": lane, "seq": seq, "payload_hash": payload_hash, "payload": text},
        )
        if sign:
            signature = self.signer.sign(signing_message(h))
            pem = getattr(self.signer, "public_key_pem", None)
            self._append_side(
                "chain_signature",
                {
                    "lane": lane,
                    "seq": seq,
                    "entry_hash": h,
                    "signature": base64.b64encode(signature).decode("ascii"),
                    "key_id": self.signer.key_id,
                    "algorithm": getattr(self.signer, "algorithm", ALGORITHM),
                    "key_kind": getattr(self.signer, "key_kind", "dev"),
                    "public_key": pem() if callable(pem) else "",
                },
            )
        try:
            self.tables.append("chain_entry", [entry])
        except DuplicateKeyError as exc:
            self._heads.pop(lane, None)  # re-read on next use
            raise ChainConflictError(
                f"lane {lane} seq {seq} was written by another writer; "
                "only one chain writer may run (single-writer rule)"
            ) from exc
        self._heads[lane] = LaneHead(seq, h)
        return h

    def _append_side(self, table: str, row: Mapping[str, Any]) -> None:
        try:
            self.tables.append(table, [row])
        except DuplicateKeyError:
            pass  # identical row (same key includes the content hash) already stored


def build_chain_writer(
    settings: Any, tables: TableStore, clock: Clock, files: Any = None
) -> ChainWriter:
    """ChainWriter from Settings (signer, writer id, root cadence)."""
    from supervisor.evidence.signer import build_signer

    return ChainWriter(
        tables,
        clock,
        build_signer(settings, files),
        writer_id=getattr(settings, "evidence_writer_id", None),
        env=str(getattr(settings, "supervisor_mode", "dev")),
        root_every_n=int(getattr(settings, "evidence_root_every_n", 100)),
        root_every_s=int(getattr(settings, "evidence_root_every_s", 900)),
        allow_rotation=bool(getattr(settings, "signer_allow_rotation", False)),
    )
