from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from supervisor import sandbox
from supervisor.cli import main as cli_main
from supervisor.evidence.anchor import WormDirAnchor
from supervisor.evidence.export import ExportError, export_chain
from supervisor.evidence.verify import main as verify_main
from supervisor.evidence.verify import verify_export
from supervisor.jobs.anchor import run as anchor_run
from tests.conftest import REPO_ROOT
from tests.evidence.conftest import Env, fixed_signer, make_writer, populate


@pytest.fixture
def exported(env: Env) -> Path:
    populate(env, n=10, root_every_n=3)
    anchor_run(env.adapters.settings, env.adapters, anchor=WormDirAnchor(env.tmp / "anchors"))
    out = env.tmp / "export"
    export_chain(env.adapters.tables, out, created_at=env.clock.now())
    fixed_signer().export_public_key(env.tmp / "pinned.pem")
    return out


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _copy(src: Path, tmp: Path, name: str) -> Path:
    dst = tmp / name
    shutil.copytree(src, dst)
    return dst


def _run(export: Path, *extra: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = verify_main([str(export), *extra])
    out = capsys.readouterr().out
    assert out.isascii()
    return code, out


def test_export_then_verify_ok(env: Env, exported: Path, capsys) -> None:
    code, out = _run(
        exported,
        "--pubkey",
        str(env.tmp / "pinned.pem"),
        "--anchors",
        str(env.tmp / "anchors"),
        "--strict",
        capsys=capsys,
    )
    assert code == 0, out
    assert "[FAIL]" not in out and out.rstrip().endswith("RESULT: OK")
    assert "[OK]   lane agent:a1: 5 entries, seq 0..4" in out
    assert "[OK]   anchors: 1 anchor document(s)" in out
    manifest = json.loads((exported / "manifest.json").read_text())
    assert set(manifest["lanes"]) == {"root", "agent:a1", "agent:a2"}
    assert manifest["key_ids"] == [fixed_signer().key_id]
    for f in ("entries.jsonl", "payloads.jsonl", "signatures.jsonl", "public_key.pem"):
        assert (exported / f).exists()
    assert "PRIVATE" not in "".join(p.read_text() for p in exported.iterdir())


def test_export_refuses_non_empty_dir(env: Env, exported: Path) -> None:
    with pytest.raises(ExportError):
        export_chain(env.adapters.tables, exported)


def test_single_lane_export_verifies(env: Env, capsys) -> None:
    populate(env, n=6)
    out = env.tmp / "one"
    export_chain(env.adapters.tables, out, lanes=["agent:a1"])
    code, text = _run(out, capsys=capsys)
    assert code == 0, text
    assert "agent:a2" not in text and "lane agent:a1" in text


def _fix_manifest(export: Path) -> None:
    """Attacker also rewrites the manifest file hashes (the chain must still catch it)."""
    import hashlib

    m = json.loads((export / "manifest.json").read_text())
    for name in m["files"]:
        m["files"][name]["sha256"] = hashlib.sha256((export / name).read_bytes()).hexdigest()
    (export / "manifest.json").write_text(json.dumps(m))


def test_tamper_edit_payload_hash(env: Env, exported: Path, capsys) -> None:
    t = _copy(exported, env.tmp, "t1")
    rows = _lines(t / "entries.jsonl")
    target = next(r for r in rows if r["lane"] == "agent:a2" and r["seq"] == 2)
    target["payload_hash"] = "f" * 64
    _write(t / "entries.jsonl", rows)
    _fix_manifest(t)
    code, out = _run(t, capsys=capsys)
    assert code == 1
    assert "[FAIL] lane agent:a2: first broken seq 2: entry_hash does not match" in out
    assert "[OK]   lane agent:a1" in out


def test_tamper_rehashed_entry_caught_by_link_and_signed_root(
    env: Env, exported: Path, capsys
) -> None:
    """Edit a record and recompute its entry_hash: the next link and the signed root fail."""
    from supervisor.evidence.verify import entry_hash

    t = _copy(exported, env.tmp, "t1b")
    rows = _lines(t / "entries.jsonl")
    target = next(r for r in rows if r["lane"] == "agent:a1" and r["seq"] == 1)
    target["record_ref"] = "verdict:forged"
    target["entry_hash"] = entry_hash(target)
    _write(t / "entries.jsonl", rows)
    _fix_manifest(t)
    code, out = _run(t, capsys=capsys)
    assert code == 1
    assert "[FAIL] lane agent:a1: first broken seq 1: entry differs from" in out


def test_tamper_delete_entry(env: Env, exported: Path, capsys) -> None:
    t = _copy(exported, env.tmp, "t2")
    rows = [
        r for r in _lines(t / "entries.jsonl") if not (r["lane"] == "agent:a1" and r["seq"] == 2)
    ]
    _write(t / "entries.jsonl", rows)
    code, out = _run(t, capsys=capsys)
    assert code == 1
    assert "[FAIL] lane agent:a1: first broken seq 2: missing entry" in out
    assert "[FAIL] manifest" in out


def test_tamper_delete_tail_with_forged_manifest(env: Env, exported: Path, capsys) -> None:
    t = _copy(exported, env.tmp, "t2b")
    rows = _lines(t / "entries.jsonl")
    last = max(r["seq"] for r in rows if r["lane"] == "agent:a1")
    rows = [r for r in rows if not (r["lane"] == "agent:a1" and r["seq"] == last)]
    _write(t / "entries.jsonl", rows)
    m = json.loads((t / "manifest.json").read_text())
    m["lanes"]["agent:a1"]["count"] -= 1
    m["lanes"]["agent:a1"]["head"] = next(
        r["entry_hash"] for r in rows if r["lane"] == "agent:a1" and r["seq"] == last - 1
    )
    (t / "manifest.json").write_text(json.dumps(m))
    _fix_manifest(t)
    code, out = _run(t, capsys=capsys)
    assert code == 1
    assert f"[FAIL] lane agent:a1: first broken seq {last}: entry committed by signed root" in out


def test_tamper_reorder(env: Env, exported: Path, capsys) -> None:
    t = _copy(exported, env.tmp, "t3")
    rows = _lines(t / "entries.jsonl")
    i = next(k for k, r in enumerate(rows) if r["lane"] == "agent:a2" and r["seq"] == 1)
    rows[i], rows[i + 1] = rows[i + 1], rows[i]
    _write(t / "entries.jsonl", rows)
    _fix_manifest(t)
    code, out = _run(t, capsys=capsys)
    assert code == 1
    assert "[FAIL] lane agent:a2: first broken seq 1: missing entry" in out


def test_tamper_swap_signatures(env: Env, exported: Path, capsys) -> None:
    t = _copy(exported, env.tmp, "t4")
    sigs = _lines(t / "signatures.jsonl")
    assert len(sigs) >= 2
    sigs[0]["signature"], sigs[1]["signature"] = sigs[1]["signature"], sigs[0]["signature"]
    _write(t / "signatures.jsonl", sigs)
    _fix_manifest(t)
    code, out = _run(t, capsys=capsys)
    assert code == 1
    assert f"[FAIL] lane root: first broken seq {sigs[0]['seq']}: signature does not verify" in out


def test_tamper_payload_text(env: Env, exported: Path, capsys) -> None:
    t = _copy(exported, env.tmp, "t5")
    rows = _lines(t / "payloads.jsonl")
    p = next(r for r in rows if r["lane"] == "agent:a1" and r["seq"] == 3)
    p["payload"] = p["payload"].replace("nghi_ngo", "an_toan")
    _write(t / "payloads.jsonl", rows)
    _fix_manifest(t)
    code, out = _run(t, capsys=capsys)
    assert code == 1
    assert "[FAIL] lane agent:a1: first broken seq 3: payload sha256" in out


def test_resigned_chain_fails_against_pinned_key(env: Env, tmp_path: Path, capsys) -> None:
    """A forger with their own key passes self-consistency but not the pinned key."""
    from tests.evidence.conftest import SEED

    populate(env)
    out = env.tmp / "e"
    export_chain(env.adapters.tables, out)
    other = fixed_signer(bytes(reversed(SEED)))
    other.export_public_key(tmp_path / "other.pem")
    code, text = _run(out, "--pubkey", str(tmp_path / "other.pem"), capsys=capsys)
    assert code == 1
    assert "not the pinned key" in text


def test_anchor_detects_truncated_root_lane(env: Env, exported: Path, capsys) -> None:
    t = _copy(exported, env.tmp, "t6")
    rows = _lines(t / "entries.jsonl")
    last_root = max(r["seq"] for r in rows if r["lane"] == "root")
    rows = [r for r in rows if not (r["lane"] == "root" and r["seq"] == last_root)]
    _write(t / "entries.jsonl", rows)
    sigs = [s for s in _lines(t / "signatures.jsonl") if s["seq"] != last_root]
    _write(t / "signatures.jsonl", sigs)
    m = json.loads((t / "manifest.json").read_text())
    m["lanes"]["root"]["count"] -= 1
    m["lanes"]["root"]["head"] = next(
        r["entry_hash"] for r in rows if r["lane"] == "root" and r["seq"] == last_root - 1
    )
    (t / "manifest.json").write_text(json.dumps(m))
    _fix_manifest(t)
    code, out = _run(t, "--anchors", str(env.tmp / "anchors"), capsys=capsys)
    assert code == 1
    assert f"anchored root seq {last_root} is missing from the export" in out


def test_unsealed_entries_reported_and_strict_fails(env: Env, capsys) -> None:
    w = make_writer(env)
    w.record("e", "e:0", {"agent_id": "a1"})
    w.record("e", "e:1", {"agent_id": "a1"})
    w.close(seal=False)
    out = env.tmp / "u"
    export_chain(env.adapters.tables, out)
    code, text = _run(out, capsys=capsys)
    assert code == 0 and "not yet sealed" in text
    code, text = _run(out, "--strict", capsys=capsys)
    assert code == 1


def test_verify_usage_errors_exit_2(tmp_path: Path, capsys) -> None:
    assert verify_main([str(tmp_path / "missing")]) == 2
    assert "[FAIL]" in capsys.readouterr().out
    (tmp_path / "manifest.json").write_text("{}")
    assert verify_main([str(tmp_path)]) == 2


def test_cli_verify_exit_codes(env: Env, exported: Path, capsys) -> None:
    assert cli_main(["verify", str(exported)]) == 0
    t = _copy(exported, env.tmp, "cli")
    rows = _lines(t / "entries.jsonl")
    rows[1]["ts"] = "2030-01-01T00:00:00.000000Z"
    _write(t / "entries.jsonl", rows)
    assert cli_main(["verify", str(t)]) == 1
    assert cli_main(["verify", str(env.tmp / "nothing")]) == 2
    out = capsys.readouterr().out
    assert out.isascii()


def test_verify_runs_as_module_in_subprocess(env: Env, exported: Path) -> None:
    res = sandbox.run(
        [sandbox.python_executable(), "-m", "supervisor.evidence.verify", str(exported)],
        cwd=env.tmp,
        timeout_s=120,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.isascii() and "RESULT: OK" in res.stdout


def test_verifier_imports_only_stdlib_cryptography_canonical() -> None:
    import sys

    path = REPO_ROOT / "src" / "supervisor" / "evidence" / "verify.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = set(sys.stdlib_module_names) | {"cryptography", "__future__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        else:
            continue
        for mod in mods:
            assert mod == "supervisor.core.canonical" or mod.split(".")[0] in allowed, mod
    init = REPO_ROOT / "src" / "supervisor" / "evidence" / "__init__.py"
    assert not [
        n
        for n in ast.walk(ast.parse(init.read_text()))
        if isinstance(n, ast.Import | ast.ImportFrom)
    ]


def test_verify_export_api(exported: Path) -> None:
    report = verify_export(exported)
    assert report.failures == 0
