"""Offline verifier for an evidence export (``supervisor-verify``).

Run:  python -m supervisor.evidence.verify <export dir> [--pubkey FILE] [--anchors DIR] [--strict]

Imports only the standard library, ``cryptography`` and
``supervisor.evidence._canonical_stdlib`` (no pydantic), so a copy runs offline on an
auditor laptop with no database and no Databricks.

What it checks (exit code 0 = all OK, 1 = any FAIL, 2 = the export cannot be read):

1. ``manifest.json``: every listed file exists and its SHA-256 matches.
2. Every lane: entries appear in seq order 0, 1, 2, ... with no gap; each
   ``entry_hash`` is recomputed from the canonical JSON of
   ``{lane, seq, ts, record_type, record_ref, payload_hash, prev_hash}`` (spec v1) or
   that plus ``writer``, ``env`` and ``chain_spec_version`` (spec v2); each
   ``prev_hash`` equals the previous ``entry_hash`` (genesis = 64 zeros).
   Lane counts and heads match the manifest.
3. Payloads (when exported): canonical, float-free, SHA-256 equals ``payload_hash``.
4. Root lane: every ``root_commit`` entry has a payload and a valid Ed25519
   signature over ``SIGNING_PREFIX + entry_hash``; the ``key_id`` is the SHA-256 of
   the raw public key; with ``--pubkey`` the key must be the pinned key. Every lane
   head committed in a root must match the exported entry at that seq.
   A lane committed by a signed root but absent from the export fails (unless
   ``--partial`` for a lane export); a lane that a later signed root does not
   commit fails (injected lane). An export without any verified root fails.
5. ``--anchors DIR``: every anchor document re-hashes to its root entry, its
   signature verifies, the root exists in the export, and the receipts in
   ``anchors.jsonl`` match the SHA-256 of the anchor files.

The report is ASCII: ``[OK]`` / ``[FAIL]`` per check, with the first broken seq per lane.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from supervisor.evidence._canonical_stdlib import CanonicalError, canonical_json, sha256_hex

# ------------------------------------------------------------------ chain spec (v2)
# The chain writer imports these, so writer and verifier cannot drift apart.

CHAIN_SPEC_VERSION = 2
SUPPORTED_SPEC_VERSIONS = (1, 2)  # v1 is read-only legacy: the writer emits v2
GENESIS_HASH = "0" * 64
ROOT_LANE = "root"
ROOT_RECORD_TYPE = "root_commit"
KEY_ROTATION_RECORD_TYPE = "key_rotation"
SIGNING_PREFIX = b"supervisor-chain/v1 root "
ALGORITHM = "ed25519"
EXPORT_FORMAT = "supervisor-evidence-export"
ANCHOR_FORMAT = "supervisor-evidence-anchor"
ENTRY_HASH_FIELDS = (
    "lane",
    "seq",
    "ts",
    "record_type",
    "record_ref",
    "payload_hash",
    "prev_hash",
)
ENTRY_HASH_FIELDS_V2 = (*ENTRY_HASH_FIELDS, "writer", "env", "chain_spec_version")
EXPORT_FILES = (
    "entries.jsonl",
    "payloads.jsonl",
    "signatures.jsonl",
    "public_keys.jsonl",
    "anchors.jsonl",
)


def entry_version(entry: Mapping[str, Any]) -> int:
    """Spec version of an entry: its ``chain_spec_version`` field, else 1 (legacy)."""
    v = entry.get("chain_spec_version", 1)
    if type(v) is not int or v not in SUPPORTED_SPEC_VERSIONS:
        raise CanonicalError(f"unsupported entry chain_spec_version {v!r}")
    return v


def entry_hash(entry: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the hashed entry fields, chosen by the entry's
    spec version (v1: 7 fields; v2: also ``writer``, ``env``, ``chain_spec_version``).
    ``ts`` may be a datetime (writer) or its RFC 3339 string (verifier): same bytes."""
    fields = ENTRY_HASH_FIELDS_V2 if entry_version(entry) == 2 else ENTRY_HASH_FIELDS
    return sha256_hex({k: entry[k] for k in fields})


def detect_entry_version(row: Mapping[str, Any]) -> int:
    """Version of a stored row that has no version column: the one whose hash matches
    ``entry_hash``. Unmatched rows count as the current version (the verifier fails them)."""
    for v in (CHAIN_SPEC_VERSION, 1):
        try:
            if entry_hash({**row, "chain_spec_version": v}) == row.get("entry_hash"):
                return v
        except (KeyError, TypeError):
            pass
    return CHAIN_SPEC_VERSION


def signing_message(entry_hash_hex: str) -> bytes:
    return SIGNING_PREFIX + entry_hash_hex.encode("ascii")


def key_id_of_raw(raw_public_key: bytes) -> str:
    return hashlib.sha256(raw_public_key).hexdigest()


def anchor_name(root_entry_hash: str) -> str:
    return f"{root_entry_hash}.json"


# ------------------------------------------------------------------ helpers


class ExportError(Exception):
    """The export cannot be read at all (exit code 2)."""


def _reject_float(text: str) -> Any:
    raise ValueError(f"float value {text} is not allowed")


def _loads_strict(text: str) -> Any:
    return json.loads(text, parse_float=_reject_float, parse_constant=_reject_float)


def _read_jsonl(path: Path) -> list[tuple[int, Any]]:
    out: list[tuple[int, Any]] = []
    if not path.exists():
        return out
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                out.append((n, _loads_strict(line)))
            except ValueError as exc:
                out.append((n, {"__error__": f"line {n}: {exc}"}))
    return out


def _load_public_key(pem: str | bytes) -> tuple[Ed25519PublicKey, str]:
    data = pem.encode("ascii") if isinstance(pem, str) else pem
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, key_id_of_raw(raw)


def _verify_sig(key: Ed25519PublicKey, entry_hash_hex: str, sig_b64: str) -> bool:
    try:
        sig = base64.b64decode(sig_b64, validate=True)
        key.verify(sig, signing_message(entry_hash_hex))
    except (InvalidSignature, binascii.Error, ValueError, TypeError):
        return False
    return True


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


@dataclass
class LaneResult:
    lane: str
    count: int = 0
    seq_to: int | None = None
    head: str | None = None
    sealed_to: int | None = None  # highest seq committed by a verified root
    first_ts: str | None = None
    committed: bool = False  # listed in at least one verified root
    problems: list[tuple[int, str]] = field(default_factory=list)

    def fail(self, seq: int, reason: str) -> None:
        self.problems.append((seq, reason))

    @property
    def first_broken(self) -> tuple[int, str] | None:
        return min(self.problems, key=lambda p: p[0]) if self.problems else None


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    failures: int = 0

    def ok(self, text: str) -> None:
        self.lines.append(_ascii(f"[OK]   {text}"))

    def fail(self, text: str) -> None:
        self.failures += 1
        self.lines.append(_ascii(f"[FAIL] {text}"))

    def skip(self, text: str) -> None:
        self.lines.append(_ascii(f"[SKIP] {text}"))

    def info(self, text: str) -> None:
        self.lines.append(_ascii(f"       {text}"))


# ------------------------------------------------------------------ verifier


@dataclass
class Verifier:
    export_dir: Path
    pinned_pem: bytes | None = None
    anchors_dir: Path | None = None
    strict: bool = False
    partial: bool = False  # accept lanes that signed roots commit but the export lacks
    report: Report = field(default_factory=Report)

    def run(self) -> Report:
        r = self.report
        r.lines.append(_ascii(f"Supervisor evidence verify - export {self.export_dir}"))
        manifest = self._manifest()
        self._check_files(manifest)
        keys = self._keys()
        entries, lanes = self._lanes(manifest)
        payloads = self._payloads(entries, lanes, manifest)
        roots = self._roots(entries, lanes, payloads, keys)
        if not roots:
            r.fail("signed roots: none verified; the export proves nothing without one")
        self._report_lanes(lanes, roots)
        if self.anchors_dir is not None:
            self._anchors(entries, roots, keys)
        else:
            r.skip("anchors: no --anchors directory given")
        verdict = "OK" if r.failures == 0 else f"FAIL ({r.failures} problem(s))"
        r.lines.append(f"RESULT: {verdict}")
        return r

    # -- manifest and files

    def _manifest(self) -> dict[str, Any]:
        path = self.export_dir / "manifest.json"
        if not self.export_dir.is_dir():
            raise ExportError(f"export directory not found: {self.export_dir}")
        if not path.exists():
            raise ExportError(f"manifest.json not found in {self.export_dir}")
        try:
            manifest = _loads_strict(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ExportError(f"manifest.json is not valid JSON: {exc}") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != EXPORT_FORMAT:
            raise ExportError("manifest.json is not a supervisor evidence export")
        for key, kind in (("files", dict), ("lanes", dict)):
            if not isinstance(manifest.get(key), kind):
                raise ExportError(f"manifest.json: '{key}' is missing or not an object")
        if manifest.get("chain_spec_version") not in SUPPORTED_SPEC_VERSIONS:
            raise ExportError(
                f"unsupported chain_spec_version {manifest.get('chain_spec_version')!r}"
            )
        return manifest

    def _check_files(self, manifest: Mapping[str, Any]) -> None:
        files = manifest.get("files") or {}
        bad = []
        for name, info in sorted(files.items()):
            p = self.export_dir / name
            if "/" in name or "\\" in name or not p.is_file():
                bad.append(f"{name} missing")
                continue
            if hashlib.sha256(p.read_bytes()).hexdigest() != info.get("sha256"):
                bad.append(f"{name} sha256 differs from manifest")
        if bad:
            self.report.fail("manifest: " + "; ".join(bad))
        else:
            self.report.ok(f"manifest: {len(files)} files, sha256 match")

    def _keys(self) -> dict[str, Ed25519PublicKey]:
        r = self.report
        keys: dict[str, Ed25519PublicKey] = {}
        for n, row in _read_jsonl(self.export_dir / "public_keys.jsonl"):
            try:
                if not isinstance(row, dict) or "__error__" in row:
                    raise ValueError("not a JSON object")
                key, kid = _load_public_key(row["public_key"])
            except (KeyError, TypeError, ValueError) as exc:
                r.fail(f"public_keys.jsonl line {n}: unreadable key ({exc})")
                continue
            if row.get("key_id") != kid:
                r.fail(f"public_keys.jsonl line {n}: key_id is not sha256(public key)")
                continue
            keys[kid] = key
        pem_file = self.export_dir / "public_key.pem"
        if pem_file.exists():
            try:
                key, kid = _load_public_key(pem_file.read_bytes())
                keys.setdefault(kid, key)
            except ValueError as exc:
                r.fail(f"public_key.pem: unreadable ({exc})")
        if self.pinned_pem is not None:
            try:
                pinned, pinned_id = _load_public_key(self.pinned_pem)
            except ValueError as exc:
                r.fail(f"--pubkey: unreadable ({exc})")
                return {}
            others = sorted(k for k in keys if k != pinned_id)
            if others:
                r.fail(
                    "pinned key: export carries key(s) that are not the pinned key: "
                    + ", ".join(k[:16] for k in others)
                )
            r.ok(f"pinned key {pinned_id[:16]}... used for every signature check")
            return {pinned_id: pinned}
        if keys:
            r.ok(
                "public key(s) from the export: "
                + ", ".join(k[:16] + "..." for k in sorted(keys))
                + " (not pinned: pass --pubkey to pin the notary key)"
            )
        return keys

    # -- lanes

    def _lanes(
        self, manifest: Mapping[str, Any]
    ) -> tuple[dict[str, dict[int, dict[str, Any]]], dict[str, LaneResult]]:
        entries: dict[str, dict[int, dict[str, Any]]] = {}
        lanes: dict[str, LaneResult] = {}
        expected: dict[str, int] = {}
        prev: dict[str, str] = {}
        lane_ver: dict[str, int] = {}
        for n, row in _read_jsonl(self.export_dir / "entries.jsonl"):
            if not isinstance(row, dict) or "__error__" in row:
                err = row.get("__error__") if isinstance(row, dict) else None
                self.report.fail(f"entries.jsonl: {err or f'line {n}: not a JSON object'}")
                continue
            lane = row.get("lane")
            seq = row.get("seq")
            if not isinstance(lane, str) or type(seq) is not int:
                self.report.fail(f"entries.jsonl line {n}: lane/seq missing or wrong type")
                continue
            lr = lanes.setdefault(lane, LaneResult(lane))
            want = expected.get(lane, 0)
            if seq != want:
                if seq > want:
                    lr.fail(want, f"missing entry (next entry in file is seq {seq})")
                else:
                    lr.fail(seq, f"out of order or duplicate (expected seq {want})")
                expected[lane] = max(want, seq + 1)
            else:
                expected[lane] = seq + 1
            try:
                computed = entry_hash(row)
            except (KeyError, TypeError, CanonicalError) as exc:
                lr.fail(seq, f"entry unreadable ({exc})")
                continue
            ver = entry_version(row)
            if ver < lane_ver.get(lane, 1):
                lr.fail(seq, "chain_spec_version goes down inside a lane (downgrade)")
            lane_ver[lane] = max(ver, lane_ver.get(lane, 1))
            if ver == 1 and self.strict:
                lr.fail(seq, "legacy spec v1 entry: writer/env are not covered by entry_hash")
            if lr.first_ts is None and isinstance(row.get("ts"), str):
                lr.first_ts = row["ts"]
            if computed != row.get("entry_hash"):
                lr.fail(seq, "entry_hash does not match the entry content")
            link = prev.get(lane, GENESIS_HASH)
            if seq == want and row.get("prev_hash") != link:
                if seq == 0:
                    lr.fail(0, "first entry does not start from the genesis hash")
                else:
                    # seq's own hash is checked above, so its prev_hash is authentic:
                    # the entry before it is the one that changed.
                    lr.fail(seq - 1, f"entry differs from the prev_hash committed by seq {seq}")
            prev[lane] = row.get("entry_hash", "")
            if seq not in entries.setdefault(lane, {}):
                entries[lane][seq] = row
            lr.count += 1
            lr.seq_to = seq if lr.seq_to is None else max(lr.seq_to, seq)
            lr.head = row.get("entry_hash")
        for lane, info in (manifest.get("lanes") or {}).items():
            lr = lanes.setdefault(lane, LaneResult(lane))
            if info.get("count") != lr.count:
                lr.fail(
                    (lr.seq_to + 1) if lr.seq_to is not None else 0,
                    f"manifest lists {info.get('count')} entries, export has {lr.count}",
                )
            elif info.get("head") != lr.head:
                lr.fail(lr.seq_to or 0, "lane head differs from manifest")
        return entries, lanes

    def _payloads(
        self,
        entries: Mapping[str, Mapping[int, Mapping[str, Any]]],
        lanes: Mapping[str, LaneResult],
        manifest: Mapping[str, Any],
    ) -> dict[tuple[str, int], Any]:
        out: dict[tuple[str, int], Any] = {}
        checked = 0
        for n, row in _read_jsonl(self.export_dir / "payloads.jsonl"):
            if not isinstance(row, dict) or "__error__" in row:
                err = row.get("__error__") if isinstance(row, dict) else None
                self.report.fail(f"payloads.jsonl: {err or f'line {n}: not a JSON object'}")
                continue
            lane, seq = row.get("lane"), row.get("seq")
            if not isinstance(lane, str) or type(seq) is not int:
                self.report.fail(f"payloads.jsonl line {n}: lane/seq missing or wrong type")
                continue
            entry = entries.get(lane, {}).get(seq)
            lr = lanes.get(lane)
            if entry is None or lr is None:
                self.report.fail(f"payloads.jsonl line {n}: no entry {lane}#{seq}")
                continue
            text = row.get("payload")
            if not isinstance(text, str):
                lr.fail(seq, "payload missing")
                continue
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest != entry.get("payload_hash") or row.get("payload_hash") != digest:
                lr.fail(seq, "payload sha256 does not match payload_hash")
                continue
            try:
                value = _loads_strict(text)
                if canonical_json(value) != text:
                    lr.fail(seq, "payload is not canonical JSON")
                    continue
            except (ValueError, CanonicalError) as exc:
                lr.fail(seq, f"payload rejected ({exc})")
                continue
            out[(lane, seq)] = value
            checked += 1
        # Root payloads are always exported; agent payloads when the manifest says so.
        include_all = bool(manifest.get("payloads_included", False))
        for lane, by_seq in entries.items():
            if lane != ROOT_LANE and not include_all:
                continue
            lr = lanes[lane]
            for seq in by_seq:
                if (lane, seq) not in out and not any(p[0] == seq for p in lr.problems):
                    lr.fail(seq, "payload missing from the export")
        self.report.ok(f"payloads: {checked} payload(s) re-hashed") if checked else None
        return out

    # -- root lane

    def _roots(
        self,
        entries: Mapping[str, Mapping[int, Mapping[str, Any]]],
        lanes: dict[str, LaneResult],
        payloads: Mapping[tuple[str, int], Any],
        keys: Mapping[str, Ed25519PublicKey],
    ) -> dict[int, Mapping[str, Any]]:
        r = self.report
        sigs: dict[int, Mapping[str, Any]] = {}
        root_lr = lanes.setdefault(ROOT_LANE, LaneResult(ROOT_LANE))
        for n, row in _read_jsonl(self.export_dir / "signatures.jsonl"):
            if (
                not isinstance(row, dict)
                or "__error__" in row
                or row.get("lane") != ROOT_LANE
                or type(row.get("seq")) is not int
            ):
                r.fail(f"signatures.jsonl line {n}: not a root-lane signature row")
                continue
            if row["seq"] in sigs:
                root_lr.fail(row["seq"], "more than one signature row")
                continue
            sigs[row["seq"]] = row
        root_entries = entries.get(ROOT_LANE, {})
        verified: dict[int, Mapping[str, Any]] = {}
        for seq in sorted(root_entries):
            e = root_entries[seq]
            kind = e.get("record_type")
            if kind not in (ROOT_RECORD_TYPE, KEY_ROTATION_RECORD_TYPE):
                continue
            sig = sigs.pop(seq, None)
            if sig is None:
                root_lr.fail(seq, "root entry has no signature")
                continue
            key = keys.get(sig.get("key_id", ""))
            if key is None:
                root_lr.fail(seq, f"signature key {str(sig.get('key_id'))[:16]} is not trusted")
                continue
            if sig.get("algorithm") != ALGORITHM or sig.get("entry_hash") != e.get("entry_hash"):
                root_lr.fail(seq, "signature row does not match the root entry")
                continue
            if not _verify_sig(key, e["entry_hash"], sig.get("signature", "")):
                root_lr.fail(seq, "signature does not verify")
                continue
            payload = payloads.get((ROOT_LANE, seq))
            if kind == KEY_ROTATION_RECORD_TYPE:
                if not isinstance(payload, dict) or payload.get("new_key_id") != sig.get("key_id"):
                    root_lr.fail(seq, "key_rotation is not signed by the key it names")
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("lanes"), dict):
                root_lr.fail(seq, "root payload missing or invalid")
                continue
            verified[seq] = e
            for lane, head in payload["lanes"].items():
                hseq = head.get("seq") if isinstance(head, dict) else None
                if type(hseq) is not int:
                    root_lr.fail(seq, f"root payload has a bad head for lane {lane}")
                    continue
                lr = lanes.get(lane)
                if lr is None:
                    if self.partial:
                        continue  # partial (single-lane) export, accepted by --partial
                    lr = lanes.setdefault(lane, LaneResult(lane))
                    lr.fail(0, f"lane committed by signed root seq {seq} is missing")
                    continue
                lr.committed = True
                target = entries.get(lane, {}).get(hseq)
                if target is None:
                    lr.fail(hseq, f"entry committed by signed root seq {seq} is missing")
                elif target.get("entry_hash") != head.get("entry_hash"):
                    lr.fail(hseq, f"entry differs from the head signed in root seq {seq}")
                else:
                    lr.sealed_to = max(lr.sealed_to or -1, hseq)
            root_lr.sealed_to = seq
        for seq in sorted(sigs):
            root_lr.fail(seq, "signature row without a root entry")
        if verified:
            r.ok(f"signed roots: {len(verified)} verified")
        return verified

    def _report_lanes(
        self, lanes: Mapping[str, LaneResult], roots: Mapping[int, Mapping[str, Any]]
    ) -> None:
        r = self.report
        for lr in lanes.values():
            if lr.lane == ROOT_LANE or lr.committed or lr.first_ts is None:
                continue
            later = [s for s, e in roots.items() if str(e.get("ts", "")) > lr.first_ts]
            if later:
                lr.fail(
                    0, f"lane is not committed by signed root seq {min(later)} written after it"
                )
        for name in sorted(lanes, key=lambda x: (x != ROOT_LANE, x)):
            lr = lanes[name]
            first = lr.first_broken
            if first is not None:
                more = f" (+{len(lr.problems) - 1} more)" if len(lr.problems) > 1 else ""
                r.fail(f"lane {name}: first broken seq {first[0]}: {first[1]}{more}")
                continue
            rng = f"seq 0..{lr.seq_to}" if lr.seq_to is not None else "empty"
            head = (lr.head or "")[:16]
            unsealed = (lr.seq_to if lr.seq_to is not None else -1) - (
                lr.sealed_to if lr.sealed_to is not None else -1
            )
            if unsealed > 0 and name != ROOT_LANE:
                msg = f"{unsealed} entr(y/ies) after the last signed root (not yet sealed)"
                if self.strict:
                    r.fail(f"lane {name}: {msg}")
                    continue
                r.ok(f"lane {name}: {lr.count} entries, {rng}, head {head}...; {msg}")
            else:
                r.ok(f"lane {name}: {lr.count} entries, {rng}, head {head}...")

    # -- anchors

    def _anchors(
        self,
        entries: Mapping[str, Mapping[int, Mapping[str, Any]]],
        roots: Mapping[int, Mapping[str, Any]],
        keys: Mapping[str, Ed25519PublicKey],
    ) -> None:
        r = self.report
        assert self.anchors_dir is not None
        if not self.anchors_dir.is_dir():
            r.fail(f"anchors: directory not found: {self.anchors_dir}")
            return
        root_entries = entries.get(ROOT_LANE, {})
        files = {p.name: p for p in self.anchors_dir.glob("*.json")}
        receipts = {}
        for n, row in _read_jsonl(self.export_dir / "anchors.jsonl"):
            if not isinstance(row, dict) or "__error__" in row:
                r.fail(f"anchors.jsonl line {n}: not a JSON object")
                continue
            receipts[anchor_name(str(row.get("root_hash")))] = (n, row)
        ok = 0
        for name, path in sorted(files.items()):
            data = path.read_bytes()
            problem = self._check_anchor_doc(name, data, root_entries, roots, keys)
            if problem:
                r.fail(f"anchor {name[:20]}...: {problem}")
                continue
            if name in receipts:
                _, row = receipts.pop(name)
                want = _receipt_sha256(row.get("receipt"))
                if want != hashlib.sha256(data).hexdigest():
                    r.fail(f"anchor {name[:20]}...: receipt sha256 does not match the file")
                    continue
            ok += 1
        for name, (n, _) in sorted(receipts.items()):
            r.fail(f"anchors.jsonl line {n}: anchored file {name[:20]}... not in anchors dir")
        if ok:
            r.ok(f"anchors: {ok} anchor document(s) match the export")
        elif not files:
            r.fail("anchors: no anchor documents found")

    def _check_anchor_doc(
        self,
        name: str,
        data: bytes,
        root_entries: Mapping[int, Mapping[str, Any]],
        roots: Mapping[int, Mapping[str, Any]],
        keys: Mapping[str, Ed25519PublicKey],
    ) -> str | None:
        try:
            doc = _loads_strict(data.decode("utf-8"))
            entry = doc["root_entry"]
            sig = doc["signature"]
            if not isinstance(entry, dict) or not isinstance(sig, dict):
                raise TypeError("root_entry/signature must be objects")
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            return f"unreadable ({exc})"
        if doc.get("format") != ANCHOR_FORMAT:
            return "not an anchor document"
        try:
            computed = entry_hash(entry)
        except (KeyError, TypeError, CanonicalError) as exc:
            return f"root entry unreadable ({exc})"
        if computed != entry.get("entry_hash") or name != anchor_name(computed):
            return "root entry hash does not match the document or file name"
        try:
            doc_key, doc_kid = _load_public_key(doc.get("public_key", ""))
        except ValueError as exc:
            return f"public key unreadable ({exc})"
        if self.pinned_pem is not None and doc_kid not in keys:
            return "anchor public key is not the pinned key"
        if sig.get("key_id") != doc_kid or not _verify_sig(
            doc_key, computed, sig.get("signature", "")
        ):
            return "signature does not verify"
        seq = entry.get("seq")
        exported = root_entries.get(seq) if type(seq) is int else None
        if exported is None:
            return f"anchored root seq {seq} is missing from the export (truncated?)"
        if exported.get("entry_hash") != computed:
            return f"anchored root seq {seq} differs from the exported root entry"
        if seq not in roots:
            return f"anchored root seq {seq} did not verify in the export"
        return None


def _receipt_sha256(receipt: Any) -> str | None:
    if not isinstance(receipt, str):
        return None
    for part in receipt.split(";"):
        key, _, value = part.partition("=")
        if key.strip() == "sha256":
            return value.strip()
    return None


def verify_export(
    export_dir: Path,
    *,
    pubkey: Path | None = None,
    anchors_dir: Path | None = None,
    strict: bool = False,
    partial: bool = False,
) -> Report:
    pinned = pubkey.read_bytes() if pubkey is not None else None
    return Verifier(Path(export_dir), pinned, anchors_dir, strict, partial).run()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.evidence.verify",
        description="Verify a Supervisor evidence export offline.",
    )
    ap.add_argument("export_dir", help="directory written by supervisor.evidence.export")
    ap.add_argument("--pubkey", default=None, help="pinned notary public key (PEM)")
    ap.add_argument("--anchors", default=None, help="directory of anchor documents")
    ap.add_argument(
        "--strict", action="store_true", help="fail when entries are not yet sealed by a root"
    )
    ap.add_argument(
        "--partial",
        action="store_true",
        help="accept a lane export: lanes committed by roots but not exported are skipped",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)
    try:
        if args.pubkey is not None and not Path(args.pubkey).is_file():
            raise ExportError(f"--pubkey file not found: {args.pubkey}")
        report = verify_export(
            Path(args.export_dir),
            pubkey=Path(args.pubkey) if args.pubkey else None,
            anchors_dir=Path(args.anchors) if args.anchors else None,
            strict=args.strict,
            partial=args.partial,
        )
    except (TypeError, KeyError, AttributeError) as exc:
        print(_ascii(f"[FAIL] malformed export: {type(exc).__name__}: {exc}"))  # noqa: T201
        return 1
    except ExportError as exc:
        print(_ascii(f"[FAIL] {exc}"))  # noqa: T201 (CLI output)
        return 2
    print("\n".join(report.lines))  # noqa: T201 (CLI output)
    return 0 if report.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
