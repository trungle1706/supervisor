"""Tamper test: export the chain, flip one byte in a COPY, verify both.

    python -m supervisor.cli demo tamper [--data-dir DIR]

1. seal the chain (signed root) and export it (``supervisor.evidence.export``) to
   ``<data dir>/tamper/<stamp>/original``;
2. verify the original offline, strict (``supervisor.evidence.verify``): must be OK;
3. copy it to ``.../tampered`` and flip ONE bit of one byte in the copy: the rule id of a
   gate block (``PAY-08`` -> ``PAY-09``) inside the stored payload. The "attacker" also
   recomputes the SHA-256 lines in ``manifest.json``, so only the hash chain can catch it;
4. verify the copy: must FAIL and name the broken lane;
5. verify the original again: still OK; the live store is never written by this step
   (chain entry count and root head are compared before and after).

The chain break is real: the verifier is the same offline code an auditor runs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from supervisor.demo.session import DemoSession, Echo, default_echo

PREFERRED_RULES = ("PAY-08", "CRD-01", "SVC-02", "PAY-07")  # gate blocks / pauses


@dataclass
class TamperReport:
    lines: list[str] = field(default_factory=list)
    ok: bool = True
    original_dir: Path | None = None
    tampered_dir: Path | None = None
    target: str = ""
    seconds: float = 0.0

    def fail(self, text: str) -> None:
        self.ok = False
        self.lines.append(f"[FAIL] {text}")


def _facts(session: DemoSession) -> tuple[int, str | None]:
    entries = session.tables.query("chain_entry", order_by=["lane", "seq"])
    roots = [e for e in entries if e["lane"] == "root"]
    return len(entries), (roots[-1]["entry_hash"] if roots else None)


def flip_one_byte(export_dir: Path) -> tuple[str, int, int]:
    """Flip one bit of one byte in ``payloads.jsonl`` of an export COPY.

    Returns (description, byte offset, line number). Prefers the last character of the
    rule id of a gate block (``PAY-08`` -> ``PAY-09``: 0x38 -> 0x39, one bit)."""
    path = export_dir / "payloads.jsonl"
    data = bytearray(path.read_bytes())
    best: tuple[int, int, str] | None = None
    offset = 0
    for raw in bytes(data).split(b"\n"):
        if raw:
            payload = json.loads(json.loads(raw)["payload"])
            rule = payload.get("rule_id")
            if rule in PREFERRED_RULES and payload.get("allow") is False:
                at = raw.find(rule.encode())
                rank = PREFERRED_RULES.index(rule)
                if at >= 0 and (best is None or rank < best[0]):
                    best = (rank, offset + at + len(rule) - 1, rule)
        offset += len(raw) + 1
    if best is not None:
        _, pos, rule = best
        old = chr(data[pos])
        data[pos] ^= 0x01
        desc = f"rule_id {rule} -> {rule[:-1]}{chr(data[pos])} (byte {old!r} -> {chr(data[pos])!r})"
    else:  # no gate stop in the export: flip one character of the first payload text
        pos = data.find(b'"payload":"') + len(b'"payload":"') + 2
        old = chr(data[pos])
        data[pos] ^= 0x01
        desc = f"one byte of the first payload ({old!r} -> {chr(data[pos])!r})"
    path.write_bytes(bytes(data))
    return desc, pos, bytes(data[:pos]).count(b"\n") + 1


def rewrite_manifest(export_dir: Path) -> None:
    """What an attacker who edits the export would also do: fix the file hashes."""
    mpath = export_dir / "manifest.json"
    manifest: dict[str, Any] = json.loads(mpath.read_text(encoding="utf-8"))
    for name in manifest["files"]:
        manifest["files"][name]["sha256"] = hashlib.sha256(
            (export_dir / name).read_bytes()
        ).hexdigest()
    mpath.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def tamper(
    session: DemoSession, *, echo: Echo = default_echo, out_dir: Path | None = None
) -> TamperReport:
    from supervisor.evidence.export import export_chain
    from supervisor.evidence.verify import verify_export

    t0 = time.perf_counter()
    rep = TamperReport()

    def say(line: str) -> None:
        rep.lines.append(line)
        echo(line)

    def fail(text: str) -> None:
        rep.fail(text)
        echo(rep.lines[-1])

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    base = out_dir or Path(session.settings.data_dir) / "tamper" / stamp
    original, tampered = base / "original", base / "tampered"
    rep.original_dir, rep.tampered_dir = original, tampered

    session.gateway.drain()
    session.runtime.chain.commit_root()
    before = _facts(session)
    export_chain(session.tables, original)
    digest = _tree_digest(original)
    say(f"[OK] chain exported: {before[0]} entries -> {original}")

    first = verify_export(original, strict=True)
    if first.failures:
        fail("verify of the ORIGINAL export failed before any tamper:")
        for line in first.lines:
            echo(f"       {line}")
        return rep
    say("[OK] verify ORIGINAL: RESULT OK (hash chain + signed roots, offline)")

    shutil.copytree(original, tampered)
    desc, pos, line_no = flip_one_byte(tampered)
    rep.target = desc
    rewrite_manifest(tampered)
    say(f"       tamper on the COPY only: payloads.jsonl line {line_no}, byte {pos}: {desc}")
    say("       the attacker also recomputed manifest.json SHA-256 to hide the edit")
    broken = verify_export(tampered, strict=True)
    fail_lines = [ln for ln in broken.lines if ln.startswith("[FAIL]")]
    if broken.failures == 0:
        fail("verify of the TAMPERED copy passed: the chain did not catch the edit")
        return rep
    say(f"[OK] verify TAMPERED copy: RESULT FAIL ({broken.failures} problem(s)) as expected")
    for ln in fail_lines[:3]:
        say("       verifier: " + ln.replace("[FAIL]", "FAIL", 1).strip())

    again = verify_export(original, strict=True)
    if again.failures:
        fail("verify of the ORIGINAL failed after the tamper of the copy")
        return rep
    if _tree_digest(original) != digest:
        fail("the original export changed during the tamper step")
        return rep
    after = _facts(session)
    if after != before:
        fail(f"the live store changed during the tamper step: {before} -> {after}")
        return rep
    say("[OK] verify ORIGINAL again: RESULT OK; live store unchanged (entries + root head)")
    say("       console: Metrics /console/metrics -> Verify chain shows OK for the live store")
    rep.seconds = time.perf_counter() - t0
    return rep


__all__ = ["TamperReport", "flip_one_byte", "rewrite_manifest", "tamper"]
