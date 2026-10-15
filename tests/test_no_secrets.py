"""No real workspace ids, tokens, keys or .env files are committed. FILL-ME is allowed."""

from __future__ import annotations

import re

from supervisor import sandbox
from supervisor.release import fake_secret_allowed
from tests.conftest import REPO_ROOT

# Reference documents handed over by the owner. They name the bank workspace on purpose.
# They are excluded here and listed as an open question for the owner.
ALLOWLIST = {
    "docs/BANK_DEPLOY_GUIDE.md",
}
ALLOW_PREFIXES = ("docs/handoff/",)

PATTERNS = {
    "databricks workspace host": re.compile(r"\bdbc-[0-9a-f]{8}-[0-9a-f]{4}\b"),
    "azure databricks host": re.compile(r"\badb-\d{8,}\.\d+\.azuredatabricks\.net"),
    "databricks PAT": re.compile(r"\bdapi[0-9a-f]{32}\b"),
    "warehouse http path": re.compile(r"/sql/1\.0/warehouses/[0-9a-f]{16}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "openai-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "assigned DATABRICKS_TOKEN": re.compile(r"DATABRICKS_TOKEN\s*=\s*['\"]?[A-Za-z0-9]{8,}"),
}


def _repo_files() -> list[str]:
    res = sandbox.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=REPO_ROOT
    )
    assert res.ok, res.stderr
    return [line for line in res.stdout.splitlines() if line.strip()]


def test_no_env_file_tracked() -> None:
    files = _repo_files()
    bad = [f for f in files if f.split("/")[-1] == ".env" or f.endswith("/.env")]
    bad += [f for f in files if f.endswith((".db", ".sqlite", ".sqlite3", ".pem", ".key"))]
    assert bad == []


def test_no_secret_patterns() -> None:
    hits = []
    for rel in _repo_files():
        if rel in ALLOWLIST or rel.startswith(ALLOW_PREFIXES):
            continue
        path = REPO_ROOT / rel
        if not path.is_file() or path.suffix in {".mp4", ".png", ".jpg", ".pdf", ".zip"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pat in PATTERNS.items():
            for m in pat.finditer(text):
                if "FILL-ME" in m.group(0):
                    continue
                if fake_secret_allowed(rel, m.group(0)):  # WP16 corpus fakes only
                    continue
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{rel}:{line} {name}")
    assert hits == [], "\n".join(hits)


def test_deploy_files_use_placeholders() -> None:
    for name in ("databricks.yml", "app.yaml", ".env.example"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert "FILL-ME" in text, name
    yml = (REPO_ROOT / "databricks.yml").read_text(encoding="utf-8")
    assert "variables:" not in yml and "secret_scope" not in yml and "${var." not in yml


def test_fake_secret_allowance_is_narrow() -> None:
    fake = "AKIA" + "IOSFODNN7EXAMPLE"
    real_shape = "AKIA" + "Q3V7K2M9P4X8R6T1"
    assert fake_secret_allowed("data/corpus/repos/x/settings.py", fake)
    assert not fake_secret_allowed("data/corpus/repos/x/settings.py", real_shape)
    assert not fake_secret_allowed("src/supervisor/x.py", fake)
    assert fake_secret_allowed("data/corpus/repos/x/c.yaml", "dapi" + "e0" * 16)


def test_patterns_detect_planted_values() -> None:
    planted = "host " + "dbc-" + "12345678-abcd token dapi" + "0" * 32
    assert PATTERNS["databricks workspace host"].search(planted)
    assert PATTERNS["databricks PAT"].search(planted)
