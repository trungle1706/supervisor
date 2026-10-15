"""WP17 CLI: list, run (with and without the store) and report; exit codes and ASCII output."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from supervisor.adapters.factory import build_adapters
from supervisor.assurance.cli import main
from supervisor.assurance.loader import PACKS_DIR
from supervisor.assurance.model import EvalPack, RunContext, RunnerOutput
from supervisor.config import load_settings
from tests.assurance.test_framework import manifest, write_pack

MODULE = "supervisor.assurance.runners.cli_demo_fake"


class GoodRunner:
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        return RunnerOutput(
            status="ok",
            metrics={"hit_rate": 9100, "miss_rate": 400, "info_count": 3},
            n_items=12,
            data_mode="synthetic",
            dataset_id="cli-demo",
            dataset_sha256="cd" * 32,
            is_mock=bool(getattr(ctx.target, "is_mock", False)),
        )


class BadRunner:
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        return RunnerOutput(
            status="ok",
            metrics={"hit_rate": 1000, "miss_rate": 9000},
            n_items=12,
            data_mode="synthetic",
            is_mock=True,
        )


@pytest.fixture(autouse=True)
def fake_runner_module() -> Iterator[None]:
    mod = types.ModuleType(MODULE)
    mod.GoodRunner = GoodRunner  # type: ignore[attr-defined]
    mod.BadRunner = BadRunner  # type: ignore[attr-defined]
    sys.modules[MODULE] = mod
    yield
    sys.modules.pop(MODULE, None)


@pytest.fixture
def packs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "packs"
    write_pack(d, manifest("good_pack", runner=f"{MODULE}:GoodRunner"))
    write_pack(
        d,
        manifest(
            "sec_good",
            dimension="security",
            runner=f"{MODULE}:GoodRunner",
            targets=["agent"],
            launch_gate="required",
        ),
    )
    return d


def run_cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_list_table_and_filters(packs_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run_cli(capsys, "list", "--packs-dir", str(packs_dir))
    assert code == 0 and out.isascii()
    header = out.splitlines()[0]
    for col in ("id", "dimension", "licence", "data modes", "targets", "launch_gate", "judge_gate"):
        assert col in header
    assert "good_pack" in out and "sec_good" in out and "2 pack(s)" in out
    code, out, _ = run_cli(capsys, "list", "--packs-dir", str(packs_dir), "--dimension", "security")
    assert "sec_good" in out and "good_pack" not in out
    code, out, _ = run_cli(capsys, "list", "--packs-dir", str(packs_dir), "--target-kind", "judge")
    assert "good_pack" in out and "sec_good" not in out


def test_list_real_packs(capsys: pytest.CaptureFixture[str]) -> None:
    if not list(PACKS_DIR.glob("*.yaml")):
        pytest.skip("no packs committed yet")
    code, out, err = run_cli(capsys, "list")
    assert code == 0, err
    assert out.isascii()


def test_run_no_store_ok(
    tmp_path: Path, packs_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "out"
    code, out, err = run_cli(
        capsys, "run", "all", "--target", "judge", "--no-store", "--out", str(out_dir),
        "--packs-dir", str(packs_dir),
    )  # fmt: skip
    assert code == 0, err + out
    assert out.isascii()
    lines = [x for x in out.splitlines() if x.startswith("[OK]")]
    row = next(x for x in lines if "good_pack" in x)
    assert "accuracy" in row and "judge:mock-judge-t1-v1" in row
    assert "hit_rate=9100 (go>=8000)" in row and "miss_rate=400 (go<=1000)" in row
    assert "sec_good" not in out.split("run run-")[0]  # security pack is agent only
    assert "ok 1" in out and "[MOCK]" in out
    assert (out_dir / "results.json").is_file() and (out_dir / "report.md").is_file()
    code, rep, _ = run_cli(capsys, "report", "--in", str(out_dir))
    assert code == 0 and "Assurance eval report" in rep and "good_pack" in rep
    code, rep, _ = run_cli(capsys, "report", "--in", str(out_dir), "--format", "json")
    assert code == 0 and '"format":"supervisor-assurance-results"' in rep


def test_run_fail_exit_code(
    tmp_path: Path, packs_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_pack(packs_dir, manifest("bad_pack", runner=f"{MODULE}:BadRunner"))
    code, out, _ = run_cli(
        capsys, "run", "bad_pack", "--target", "judge", "--no-store", "--out", str(tmp_path / "o"),
        "--packs-dir", str(packs_dir),
    )  # fmt: skip
    assert code == 1
    assert any(x.startswith("[FAIL]") and "bad_pack" in x for x in out.splitlines())


def test_run_error_exit_code(
    tmp_path: Path, packs_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_pack(packs_dir, manifest("gone_pack", runner="supervisor.assurance.runners.no_such:X"))
    code, out, _ = run_cli(
        capsys, "run", "gone_pack", "--target", "judge", "--no-store", "--out", str(tmp_path / "o"),
        "--packs-dir", str(packs_dir),
    )  # fmt: skip
    assert code == 1 and any(x.startswith("[ERROR]") for x in out.splitlines())


def test_run_demo_target_set(
    tmp_path: Path, packs_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_cli(
        capsys, "run", "all", "--target", "demo", "--no-store", "--out", str(tmp_path / "o"),
        "--packs-dir", str(packs_dir),
    )  # fmt: skip
    assert code == 0, err + out
    for target in ("agent:payments", "agent:credit_prequal", "agent:customer_service"):
        assert target in out
    assert "traces:payments" in out and "judge:judge:mock-judge-t1-v1" in out
    # 3 agents x 2 packs + 3 traces + 1 judge = 10 results
    assert "10 results" in out


@pytest.mark.parametrize(
    "argv,needle",
    [
        (["run", "nonsense", "--target", "judge"], "unknown selector"),
        (["run", "all", "--target", "agent:nobody"], "unknown agent"),
        (["run", "all", "--target", "bogus"], "unknown target"),
        (["run", "security", "--target", "judge"], "matches no pack"),
        (["run", "all", "--target", "judge", "--max-items", "0"], "max-items"),
    ],
)
def test_usage_errors_exit_2(
    tmp_path: Path,
    packs_dir: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    needle: str,
) -> None:
    code, out, err = run_cli(
        capsys, *argv, "--no-store", "--out", str(tmp_path / "o"), "--packs-dir", str(packs_dir)
    )
    assert code == 2 and needle in err and "Traceback" not in err + out
    assert err.isascii()


def test_bad_manifest_dir_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / "bad"
    data = manifest("bad_one")
    data["thresholds"][0]["go"] = 1.5
    write_pack(d, data)
    code, _, err = run_cli(capsys, "list", "--packs-dir", str(d))
    assert code == 2 and "bad_one.yaml" in err and "Traceback" not in err
    with pytest.raises(SystemExit) as exc:  # argparse usage error
        main(["run"])
    assert exc.value.code == 2


def test_run_with_store_then_report_by_run_id(
    tmp_path: Path, packs_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_cli(
        capsys, "run", "good_pack", "--target", "judge", "--out", str(tmp_path / "o"),
        "--packs-dir", str(packs_dir),
    )  # fmt: skip
    assert code == 0, err + out
    run_id = next(x.split()[1].rstrip(":") for x in out.splitlines() if x.startswith("run run-"))
    adapters = build_adapters(load_settings())
    try:
        rows = adapters.tables.query("eval_result", {"run_id": run_id})
        assert len(rows) == 1 and rows[0]["status"] == "ok" and rows[0]["evidence_hash"]
        assert adapters.tables.query("eval_run", {"run_id": run_id})[0]["ok"] == 1
        chain = adapters.tables.query("chain_entry", {"record_type": "assurance_result"})
        assert (
            len(chain) == 1
            and chain[0]["record_ref"] == f"{run_id}:good_pack:judge:mock-judge-t1-v1"
        )
        assert chain[0]["entry_hash"] == rows[0]["evidence_hash"]
    finally:
        adapters.close()
    code, rep, err = run_cli(capsys, "report", "--run-id", run_id)
    assert code == 0 and "good_pack" in rep, err
    code, _, err = run_cli(capsys, "report", "--run-id", "run-does-not-exist")
    assert code == 2 and "no stored results" in err
