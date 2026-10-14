from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from supervisor.core.canonical import CanonicalError, sha256_hex
from supervisor.core.ports import EvidenceSink
from supervisor.evidence.chain import (
    ChainConflictError,
    ChainError,
    ChainWriter,
    FloatInPayloadError,
)
from supervisor.evidence.verify import (
    GENESIS_HASH,
    ROOT_LANE,
    entry_hash,
    signing_message,
)
from tests.evidence.conftest import Env, fixed_signer, make_writer

# Test vector (chain spec v1). Any verifier in any language must reproduce it.
VECTOR_ENTRY = {
    "lane": "agent:a1",
    "seq": 0,
    "ts": "2026-10-14T02:00:01.000000Z",
    "record_type": "verdict",
    "record_ref": "verdict:v0",
    "payload_hash": sha256_hex({"agent_id": "a1", "score_bp": 7500}),
    "prev_hash": GENESIS_HASH,
}
VECTOR_PAYLOAD_HASH = "5ea7eafcff678a4ae1f6d7c29bce557e7fadf7f3720287f7fb7b72b06aa10c2f"
VECTOR_ENTRY_HASH = "1606256a8c66f179392598567b987e9ec8d258e85af18f668015b2204c4288ed"
VECTOR_KEY_ID = "56475aa75463474c0285df5dbf2bcab73da651358839e9b77481b2eab107708c"


def test_pinned_vectors() -> None:
    assert VECTOR_ENTRY["payload_hash"] == VECTOR_PAYLOAD_HASH
    assert entry_hash(VECTOR_ENTRY) == VECTOR_ENTRY_HASH
    assert fixed_signer().key_id == VECTOR_KEY_ID  # sha256 of raw public key of seed 00..1f


def _rows(env: Env, table: str, lane: str) -> list[dict]:
    return env.adapters.tables.query(table, {"lane": lane}, order_by=["seq"])


def test_writer_is_an_evidence_sink(env: Env) -> None:
    import inspect

    w = make_writer(env)
    sink: EvidenceSink = w  # structural typing
    proto = inspect.signature(EvidenceSink.record).parameters
    impl = inspect.signature(ChainWriter.record).parameters
    assert list(proto)[:4] == list(impl)[:4]
    assert len(sink.record("e", "e:0", {"agent_id": "a1"})) == 64
    w.close()


def test_entry_hash_vector_and_canonical_payload() -> None:
    payload_text = '{"agent_id":"a1","score_bp":7500}'
    import hashlib

    assert VECTOR_ENTRY["payload_hash"] == hashlib.sha256(payload_text.encode()).hexdigest()
    canon = (
        '{"lane":"agent:a1","payload_hash":"' + VECTOR_ENTRY["payload_hash"] + '",'
        '"prev_hash":"' + GENESIS_HASH + '","record_ref":"verdict:v0","record_type":"verdict",'
        '"seq":0,"ts":"2026-10-14T02:00:01.000000Z"}'
    )
    assert entry_hash(VECTOR_ENTRY) == hashlib.sha256(canon.encode()).hexdigest()
    # datetime and its RFC 3339 string hash the same
    as_dt = {**VECTOR_ENTRY, "ts": datetime(2026, 10, 14, 2, 0, 1, tzinfo=UTC)}
    assert entry_hash(as_dt) == entry_hash(VECTOR_ENTRY)


def test_chain_is_deterministic_with_fixed_clock(env: Env) -> None:
    w = make_writer(env)
    env.clock.advance(1)
    h = w.record("verdict", "verdict:v0", {"agent_id": "a1", "score_bp": 7500})
    w.close(seal=False)
    assert h == entry_hash(VECTOR_ENTRY)
    row = _rows(env, "chain_entry", "agent:a1")[0]
    assert row["seq"] == 0 and row["prev_hash"] == GENESIS_HASH
    assert row["writer"] == "test-writer" and row["env"] == "dev"
    payload = _rows(env, "chain_payload", "agent:a1")[0]
    assert payload["payload"] == '{"agent_id":"a1","score_bp":7500}'


def test_lanes_are_isolated_and_linked(env: Env) -> None:
    w = make_writer(env)
    hashes = {"a1": [], "a2": []}
    for i in range(6):
        env.clock.advance(1)
        agent = "a1" if i % 2 else "a2"
        hashes[agent].append(w.record("event", f"e:{i}", {"agent_id": agent, "n": i}))
    w.close()
    for agent in ("a1", "a2"):
        rows = _rows(env, "chain_entry", f"agent:{agent}")
        assert [r["seq"] for r in rows] == [0, 1, 2]
        assert [r["entry_hash"] for r in rows] == hashes[agent]
        prev = GENESIS_HASH
        for r in rows:
            assert r["prev_hash"] == prev
            prev = r["entry_hash"]


def test_explicit_lane_and_agentless_records_go_to_root(env: Env) -> None:
    w = make_writer(env)
    w.record("note", "n:1", {"text": "khong co agent"})
    w.record("event", "e:1", {"x": 1}, lane="agent:zz")
    w.close()
    root_types = [r["record_type"] for r in _rows(env, "chain_entry", ROOT_LANE)]
    assert "note" in root_types
    assert len(_rows(env, "chain_entry", "agent:zz")) == 1
    with pytest.raises(ChainError):
        make_writer(env).record("x", "y", {"a": 1}, lane="bad lane")


def test_root_entry_commits_heads_and_is_signed(env: Env) -> None:
    w = make_writer(env, root_every_n=2)
    for i in range(4):
        env.clock.advance(1)
        w.record("event", f"e:{i}", {"agent_id": "a1" if i % 2 else "a2", "n": i})
    heads = w.heads()
    w.close()
    roots = [r for r in _rows(env, "chain_entry", ROOT_LANE) if r["record_type"] == "root_commit"]
    assert roots, "no root commit written"
    last = roots[-1]
    payload = json.loads(
        env.adapters.tables.query("chain_payload", {"lane": ROOT_LANE, "seq": last["seq"]})[0][
            "payload"
        ]
    )
    assert payload["lanes"] == {
        lane: {"seq": h.seq, "entry_hash": h.entry_hash}
        for lane, h in heads.items()
        if lane != ROOT_LANE
    }
    sig = env.adapters.tables.query("chain_signature", {"lane": ROOT_LANE, "seq": last["seq"]})[0]
    signer = fixed_signer()
    assert sig["key_id"] == signer.key_id and sig["algorithm"] == "ed25519"
    assert sig["key_kind"] == "dev" and "BEGIN PUBLIC KEY" in sig["public_key"]
    import base64

    raw = base64.b64decode(sig["signature"])
    assert signer.verify(signing_message(last["entry_hash"]), raw)
    assert not signer.verify(signing_message(roots[0]["entry_hash"]), raw) or len(roots) == 1


def test_root_cadence_by_count_and_time(env: Env) -> None:
    w = make_writer(env, root_every_n=3, root_every_s=60)
    w.record("e", "e:0", {"agent_id": "a1"})  # new lane -> root 0
    n_roots = lambda: sum(  # noqa: E731
        r["record_type"] == "root_commit" for r in _rows(env, "chain_entry", ROOT_LANE)
    )
    assert n_roots() == 1
    w.record("e", "e:1", {"agent_id": "a1"})
    w.record("e", "e:2", {"agent_id": "a1"})
    assert n_roots() == 1
    w.record("e", "e:3", {"agent_id": "a1"})  # 3rd since root -> root 1
    assert n_roots() == 2
    env.clock.advance(61)
    w.record("e", "e:4", {"agent_id": "a1"})  # time -> root 2
    assert n_roots() == 3
    assert w.commit_root() is None  # nothing new
    w.close(seal=False)


@pytest.mark.parametrize(
    "payload",
    [
        {"agent_id": "a1", "score": 0.5},
        {"agent_id": "a1", "nested": {"rates": [1, 2.0]}},
        {"agent_id": "a1", "amount_minor": 10.0},
    ],
)
def test_float_payload_is_rejected(env: Env, payload: dict) -> None:
    w = make_writer(env)
    with pytest.raises(FloatInPayloadError) as e:
        w.record("verdict", "verdict:x", payload)
    assert isinstance(e.value, CanonicalError)
    assert env.adapters.tables.query("chain_entry", {"lane": "agent:a1"}) == []
    w.close(seal=False)


def test_masker_is_applied_before_hashing(env: Env) -> None:
    class Mask:
        def mask(self, text: str) -> str:
            return text.replace("0912345678", "09******78")

    w = make_writer(env, masker=Mask(), mask_version="vn_regex/1")
    w.record("event", "e:1", {"agent_id": "a1", "text": "goi 0912345678"})
    w.close(seal=False)
    p = _rows(env, "chain_payload", "agent:a1")[0]["payload"]
    assert "0912345678" not in p and "09******78" in p


def test_single_writer_rules(env: Env) -> None:
    w = make_writer(env)
    with pytest.raises(ChainConflictError):
        make_writer(env)  # second writer on the same store in one process
    w.record("e", "e:0", {"agent_id": "a1"})
    w.close()
    # A "second process": same tables, its own cached head -> conflict on (lane, seq)
    w2 = make_writer(env, writer_id="w2")
    w2._head("agent:a1")  # cache current head
    env.adapters.tables.append(
        "chain_entry",
        [
            {
                "lane": "agent:a1",
                "seq": 1,
                "ts": env.clock.now(),
                "record_type": "e",
                "record_ref": "rogue",
                "payload_hash": "a" * 64,
                "prev_hash": "b" * 64,
                "entry_hash": "c" * 64,
                "writer": "rogue",
                "env": "dev",
            }
        ],
    )
    with pytest.raises(ChainConflictError):
        w2.record("e", "e:1", {"agent_id": "a1"})
    w2.close(seal=False)


def test_restart_continues_lanes(env: Env) -> None:
    w = make_writer(env)
    w.record("e", "e:0", {"agent_id": "a1"})
    w.close()
    w = make_writer(env)
    h = w.record("e", "e:1", {"agent_id": "a1"})
    w.close()
    rows = _rows(env, "chain_entry", "agent:a1")
    assert [r["seq"] for r in rows] == [0, 1] and rows[1]["prev_hash"] == rows[0]["entry_hash"]
    assert rows[1]["entry_hash"] == h


def test_root_commit_cannot_be_recorded_directly(env: Env) -> None:
    w = make_writer(env)
    with pytest.raises(ChainError):
        w.record("root_commit", "x", {"lanes": {}})
    w.close(seal=False)
    with pytest.raises(ChainError):
        w.record("e", "e", {"agent_id": "a"})  # closed


def test_writer_needs_positive_cadence(env: Env) -> None:
    with pytest.raises(ChainError):
        ChainWriter(env.adapters.tables, env.clock, fixed_signer(), root_every_n=0)


def test_restart_without_changes_does_not_need_a_new_root(env: Env) -> None:
    w = make_writer(env)
    w.record("e", "e:0", {"agent_id": "a1"})
    w.close()  # sealed
    w = make_writer(env)
    assert w.commit_root() is None
    w.close()


def test_entry_is_written_last(env: Env) -> None:
    """A failure while writing the entry leaves no chain_entry row (orphans only)."""

    class FailingTables:
        def __init__(self, inner):
            self.inner = inner

        def query(self, *a, **k):
            return self.inner.query(*a, **k)

        def append(self, table, rows):
            if table == "chain_entry":
                raise RuntimeError("crash")
            return self.inner.append(table, rows)

    w = ChainWriter(FailingTables(env.adapters.tables), env.clock, fixed_signer())
    with pytest.raises(RuntimeError):
        w.record("e", "e:0", {"agent_id": "a1"})
    assert env.adapters.tables.query("chain_entry") == []
    w._closed = True
    w2 = make_writer(env)
    w2.record("e", "e:0", {"agent_id": "a1"})
    w2.close()
    assert len(env.adapters.tables.query("chain_entry", {"lane": "agent:a1"})) == 1
