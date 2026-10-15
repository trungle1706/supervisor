from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from supervisor.advisory.compliance.__main__ import main
from supervisor.config import REPO_ROOT
from supervisor.regkb import DISCLAIMER

PRODUCT = """\
product_id: pay-demo
name: Payments demo
agent_classes: [payment]
data_classes: [personal, financial]
autonomy: acts_autonomously
cross_border: false
model_hosting: domestic_cloud
roles: [deployer]
customer_types: [individual]
executes_payments: true
human_approval_before_execution: false
max_transaction_vnd: 100000000
max_daily_vnd: 150000000
controls:
  supervised: true
  catalogue: [single_limit]
"""

EXAMPLE = REPO_ROOT / "regulations" / "internal" / "example-ai-use-policy.yaml.example"


@pytest.fixture(autouse=True)
def _no_env_internal(monkeypatch):
    monkeypatch.delenv("REGKB_INTERNAL_DIR", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "")


@pytest.fixture
def product(tmp_path):
    p = tmp_path / "product.yaml"
    p.write_text(PRODUCT, encoding="utf-8")
    return p


def _rows(out: Path) -> dict:
    data = json.loads((out / "compliance_matrix.json").read_text(encoding="utf-8"))
    return {r["obligation_id"]: r for r in data["rows"]}


def test_smoke_three_files_ascii_stdout(product, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(["--profile", str(product), "--out", str(out), "--mock-llm", "--internal", ""])
    text = capsys.readouterr().out
    assert code == 0
    assert text.isascii()
    assert "[OK]" in text and DISCLAIMER in text
    for name in ("compliance_matrix.json", "compliance_matrix.md", "compliance_matrix.html"):
        assert (out / name).read_text(encoding="utf-8")
    data = json.loads((out / "compliance_matrix.json").read_text(encoding="utf-8"))
    assert data["narrative"]["is_mock"] is True
    assert data["rows"] == sorted(data["rows"], key=lambda r: r["obligation_id"])
    assert _rows(out)["VN-TT53-2026-A5.01G2-01"]["status"] == "gap"


def test_write_template(tmp_path, capsys):
    target = tmp_path / "t" / "product.yaml"
    code = main(["--write-template", str(target)])
    assert code == 0 and capsys.readouterr().out.isascii()
    assert "product_id" in target.read_text(encoding="utf-8")


def test_bad_input_is_fail_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("product_id: x\nname: y\nautonomy: nonsense\n", encoding="utf-8")
    code = main(["--profile", str(bad), "--out", str(tmp_path / "o"), "--mock-llm"])
    text = capsys.readouterr().out
    assert code == 2 and "[FAIL]" in text and text.isascii()
    assert not (tmp_path / "o" / "compliance_matrix.json").exists()


def test_missing_file_is_fail(tmp_path, capsys):
    code = main(["--profile", str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "o")])
    assert code == 2 and "[FAIL]" in capsys.readouterr().out


def test_bad_as_of_is_fail(product, tmp_path, capsys):
    code = main(
        ["--profile", str(product), "--out", str(tmp_path / "o"), "--mock-llm", "--as-of", "x"]
    )
    assert code == 2 and "[FAIL]" in capsys.readouterr().out


def test_internal_rules_add_int_rows_only_when_asked(product, tmp_path, capsys):
    internal = tmp_path / "internal"
    internal.mkdir()
    shutil.copy(EXAMPLE, internal / "example-ai-use-policy.yaml")
    with_dir = tmp_path / "with"
    without = tmp_path / "without"
    assert (
        main(
            [
                "--profile",
                str(product),
                "--out",
                str(with_dir),
                "--mock-llm",
                "--internal",
                str(internal),
            ]
        )
        == 0
    )
    assert (
        main(["--profile", str(product), "--out", str(without), "--mock-llm", "--internal", ""])
        == 0
    )
    capsys.readouterr()
    assert any(k.startswith("INT-EXAMPLE-AIPOL") for k in _rows(with_dir))
    assert not any(k.startswith("INT-") for k in _rows(without))
