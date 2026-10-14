"""Offline verifier for an evidence export (``supervisor-verify``).

Run:  python -m supervisor.evidence.verify <export dir> [--pubkey FILE] [--anchors DIR] [--strict]

Imports only the standard library, ``cryptography`` and ``supervisor.core.canonical``,
so a copy runs offline on an auditor laptop with no database and no Databricks.

What it checks (exit code 0 = all OK, 1 = any FAIL, 2 = the export cannot be read):

1. ``manifest.json``: every listed file exists and its SHA-256 matches.
2. Every lane: entries appear in seq order 0, 1, 2, ... with no gap; each
   ``entry_hash`` is recomputed from the canonical JSON of
   ``{lane, seq, ts, record_type, record_ref, payload_hash, prev_hash}``; each
   ``prev_hash`` equals the previous ``entry_hash`` (genesis = 64 zeros).
   Lane counts and heads match the manifest.
3. Payloads (when exported): canonical, float-free, SHA-256 equals ``payload_hash``.
4. Root lane: every ``root_commit`` entry has a payload and a valid Ed25519
   signature over ``SIGNING_PREFIX + entry_hash``; the ``key_id`` is the SHA-256 of
   the raw public key; with ``--pubkey`` the key must be the pinned key. Every lane
   head committed in a root must match the exported entry at that seq.
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

from supervisor.core.canonical import CanonicalError, canonical_json, sha256_hex

# ------------------------------------------------------------------ chain spec (v1)
# The chain writer imports these, so writer and verifier cannot drift apart.

CHAIN_SPEC_VERSION = 1
GENESIS_HASH = "0" * 64
ROOT_LANE = "root"
ROOT_RECORD_TYPE = "root_commit"
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
EXPORT_FILES = (
    "entries.jsonl",
    "payloads.jsonl",
    "signatures.jsonl",
    "public_keys.jsonl",
    "anchors.jsonl",
)


def entry_hash(entry: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the hashed entry fields. ``ts`` may be a
    datetime (writer) or its RFC 3339 string (verifier): both encode the same."""
    return sha256_hex({k: entry[k] for k in ENTRY_HASH_FIELDS})


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
        self._report_lanes(lanes, manifest)
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
        if manifest.get("chain_spec_version") != CHAIN_SPEC_VERSION:
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
        for n, row in _read_jsonl(self.export_dir / "entries.jsonl"):
            if "__error__" in row or not isinstance(row, dict):
                self.report.fail(f"entries.jsonl: {row.get('__error__', f'line {n}: bad row')}")
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
            except (KeyError, CanonicalError) as exc:
                lr.fail(seq, f"entry unreadable ({exc})")
                continue
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
            if "__error__" in row:
                self.report.fail(f"payloads.jsonl: {row['__error__']}")
                continue
            lane, seq = row.get("lane"), row.get("seq")
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
        if manifest.get("payloads_included", False):
            missing = sum(
                1
                for lane, by_seq in entries.items()
                for seq in by_seq
                if (lane, seq) not in out and lane != ROOT_LANE
            )
            if missing:
                self.report.info(f"payloads: {missing} entr(y/ies) without a valid payload")
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
        for n, row in _read_jsonl(self.export_dir / "signatures.jsonl"):
            if "__error__" in row or row.get("lane") != ROOT_LANE:
                r.fail(f"signatures.jsonl line {n}: not a root-lane signature row")
                continue
            sigs[row.get("seq")] = row
        root_entries = entries.get(ROOT_LANE, {})
        root_lr = lanes.setdefault(ROOT_LANE, LaneResult(ROOT_LANE))
        verified: dict[int, Mapping[str, Any]] = {}
        for seq in sorted(root_entries):
            e = root_entries[seq]
            if e.get("record_type") != ROOT_RECORD_TYPE:
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
            if not isinstance(payload, dict) or not isinstance(payload.get("lanes"), dict):
                root_lr.fail(seq, "root payload missing or invalid")
                continue
            verified[seq] = e
            for lane, head in payload["lanes"].items():
                lr = lanes.get(lane)
                if lr is None:
                    continue  # lane not in this export (single-lane export)
                hseq = head.get("seq")
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

    def _report_lanes(self, lanes: Mapping[str, LaneResult], manifest: Mapping[str, Any]) -> None:
        r = self.report
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
            if "__error__" in row:
                r.fail(f"anchors.jsonl: {row['__error__']}")
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
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            return f"unreadable ({exc})"
        if doc.get("format") != ANCHOR_FORMAT:
            return "not an anchor document"
        try:
            computed = entry_hash(entry)
        except (KeyError, CanonicalError) as exc:
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
        exported = root_entries.get(seq)
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
) -> Report:
    pinned = pubkey.read_bytes() if pubkey is not None else None
    return Verifier(Path(export_dir), pinned, anchors_dir, strict).run()


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
    args = ap.parse_args(list(argv) if argv is not None else None)
    try:
        if args.pubkey is not None and not Path(args.pubkey).is_file():
            raise ExportError(f"--pubkey file not found: {args.pubkey}")
        report = verify_export(
            Path(args.export_dir),
            pubkey=Path(args.pubkey) if args.pubkey else None,
            anchors_dir=Path(args.anchors) if args.anchors else None,
            strict=args.strict,
        )
    except ExportError as exc:
        print(_ascii(f"[FAIL] {exc}"))  # noqa: T201 (CLI output)
        return 2
    print("\n".join(report.lines))  # noqa: T201 (CLI output)
    return 0 if report.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
