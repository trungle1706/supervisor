"""Dev tool (WP-D2): build the three synthetic candidate source zips of the Databricks showcase.

python tools/showcase_sources.py [--candidates-dir DIR] [--out-dir DIR] [--check]

Reads the testbed candidates (read only) and writes
``src/supervisor/demo/showcase_data/<name>.zip``: text files only, an explicit allow-list of paths
per candidate, the agent ids renamed to the showcase names, scrubbed with the same scrubber the
intake uses, and a final secret check. No ``.env`` file, key file, wheel, binary or log is ever
added. The zips are deterministic (fixed timestamps, sorted names), so a second run changes
nothing. ``--check`` only verifies the zips on disk. ASCII output."""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from supervisor.onboard.scrub import scrub_text  # noqa: E402

DEFAULT_CANDIDATES = Path("~/supervisor-testbed/candidates").expanduser()
DEFAULT_OUT = REPO / "src" / "supervisor" / "demo" / "showcase_data"
FIXED_TIME = (2026, 10, 29, 0, 0, 0)
MAX_FILE = 64 * 1024
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json"}
SECRET = re.compile(
    r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*KEY|eyJ[A-Za-z0-9_-]{20,}\.|dapi[0-9a-f]{20,}"
    r"|(?i:(password|secret|api_key|token)\s*[:=]\s*['\"][^'\"\s]{8,})"
)

# candidate folder -> name, [(source path or dir, zip path or prefix)], text renames
CANDIDATES: dict[str, dict[str, Any]] = {
    "a1-kb-chatbot": {
        "name": "kb-helpdesk-bot",
        "sources": [
            ("adapted/agent.py", "agent.py"),
            ("adapted/app.py", "app.py"),
            ("adapted/llm.py", "llm.py"),
            ("adapted/kb.py", "kb.py"),
            ("adapted/ui.py", "ui.py"),
            ("adapted/app.yaml", "app.yaml"),
            ("adapted/requirements.pypi.txt", "requirements.txt"),
            ("policies/kb_chatbot.yaml", "policies/agent.yaml"),
            ("artifact/tools.json", "tools.json"),
        ],
        "renames": {"kb_chatbot": "kb-helpdesk-bot", "kb-chatbot": "kb-helpdesk-bot"},
    },
    "a2-customer-service": {
        "name": "cs-assistant",
        "sources": [
            ("artifact/code", "code"),
            ("artifact/prompts", "prompts"),
            ("artifact/tools.json", "tools.json"),
            ("artifact/requirements.txt", "requirements.txt"),
            ("policies/cs_agent.yaml", "policies/agent.yaml"),
        ],
        "renames": {"cs_agent": "cs-assistant"},
    },
    "a3-payments-ops": {
        "name": "payment-ops-copilot",
        "sources": [
            ("artifact/code", "code"),
            ("artifact/prompts", "prompts"),
            ("artifact/tools.json", "tools.json"),
            ("adapted/app.yaml", "app.yaml"),
            ("adapted/requirements.txt", "requirements.txt"),
            ("policies/payops_agent.yaml", "policies/agent.yaml"),
        ],
        "renames": {"payops_agent": "payment-ops-copilot"},
    },
}


def _files(base: Path, rel: str, target: str) -> list[tuple[Path, str]]:
    path = base / rel
    if path.is_dir():
        return [
            (p, f"{target}/{p.relative_to(path).as_posix()}")
            for p in sorted(path.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        ]
    return [(path, target)]


def _clean(text: str, renames: dict[str, str]) -> str:
    for old, new in renames.items():
        text = text.replace(old, new)
    return scrub_text(text).text


def build_one(base: Path, spec: dict[str, Any]) -> bytes:
    entries: dict[str, str] = {}
    for rel, target in spec["sources"]:
        for src, name in _files(base, rel, target):
            if src.suffix not in TEXT_SUFFIXES or src.name.startswith(".env"):
                continue
            if src.stat().st_size > MAX_FILE:
                raise SystemExit(f"[FAIL] {src.name} is larger than {MAX_FILE} bytes")
            entries[name] = _clean(src.read_text("utf-8"), spec["renames"])
    for name, text in entries.items():
        if SECRET.search(text):
            raise SystemExit(f"[FAIL] {name}: a secret-like value is in the text; not written")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, entries[name])
    return buf.getvalue()


SHOW_PAY_LIMIT = {
    "id": "SHOW-PAY-01",
    "version": 1,
    "description": "A transfer above 20,000,000 VND needs an approval (showcase guardian)",
    "agent_scope": ["payment-ops-copilot"],
    "when": {
        "tool": "transfer",
        "all": [{"arg": "amount_minor", "op": "gt", "value": 20000000}],
    },
    "action": "pause",
    "severity": "high",
    "risk_class": "money",
    "regulation_ref": "Showcase: transfer above limit needs approval",
    "owner": "Payments Ops",
    "approvals": ["risk.lead", "compliance.officer"],
}
OWNERS = {
    "kb-helpdesk-bot": ("owner.hr@example.invalid", "HR Services (synthetic)"),
    "cs-assistant": ("cc-lead@example.invalid", "Retail Customer Care (synthetic)"),
    "payment-ops-copilot": ("payops-lead@example.invalid", "Payments Ops (synthetic)"),
}


def build_policy(base: Path) -> str:
    """One policy file for the three showcase agents, from the candidate policy fragments with
    the showcase agent ids (the gate in the traffic generator loads it next to the baseline)."""
    import yaml

    doc: dict[str, Any] = {"policy_version": 1, "tools": {}, "agents": {}, "rules": []}
    for folder, spec in CANDIDATES.items():
        src = next((base / folder / "policies").glob("*.yaml"), None)
        if src is None:
            raise SystemExit(f"[FAIL] no policy fragment in {folder}/policies")
        text = src.read_text("utf-8")
        for old, new in spec["renames"].items():
            text = text.replace(old, new)
        frag = yaml.safe_load(text)
        doc["tools"].update(frag.get("tools") or {})
        for aid, agent in (frag.get("agents") or {}).items():
            owner, team = OWNERS[spec["name"]]
            agent = dict(agent)
            if aid == "cs-assistant":  # mask phone and CCCD in the text of a service ticket
                agent["detectors"]["settings"]["dlp_vn"]["transform_tools"] = ["create_ticket"]
            agent["owner_user"], agent["owner_team"] = owner, team
            agent["initial_state"] = "SHADOW"
            doc["agents"][aid] = agent
        doc["rules"].extend(frag.get("rules") or [])
    # tools that the traffic generator calls although the rules do not approve them: the policy
    # must know them (an unknown tool is a different block) so that the approved-tools rule acts
    doc["tools"].update({"export_all_documents": "read_only", "delete_customer": "money"})
    doc["rules"].append(SHOW_PAY_LIMIT)
    head = (
        "# Showcase policy for the three journey agents (WP-D2). Built by\n"
        "# tools/showcase_sources.py from the candidate fragments; synthetic owners.\n"
        "# Put it next to baseline.yaml in POLICY_DIR (second folder) for the traffic generator.\n"
    )
    return head + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--candidates-dir", type=Path, default=DEFAULT_CANDIDATES)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="verify the zips on disk, write nothing")
    args = ap.parse_args(argv)
    bad = 0
    for folder, spec in CANDIDATES.items():
        base = args.candidates_dir / folder
        out = args.out_dir / f"{spec['name']}.zip"
        if not base.is_dir():
            print(f"[SKIP] {folder}: not found in {args.candidates_dir}")
            continue
        data = build_one(base, spec)
        if args.check:
            same = out.is_file() and out.read_bytes() == data
            print(f"[{'OK' if same else 'FAIL'}] {out.name} {'current' if same else 'differs'}")
            bad += 0 if same else 1
            continue
        args.out_dir.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            print(f"[OK] {out.name}: {len(zf.namelist())} files, {len(data)} bytes")
    base = args.candidates_dir
    if all((base / f).is_dir() for f in CANDIDATES):
        policy = args.out_dir / "policy" / "showcase_agents.yaml"
        text = build_policy(base)
        if args.check:
            same = policy.is_file() and policy.read_text("utf-8") == text
            print(
                f"[{'OK' if same else 'FAIL'}] policy/{policy.name} "
                f"{'current' if same else 'differs'}"
            )
            bad += 0 if same else 1
        else:
            policy.parent.mkdir(parents=True, exist_ok=True)
            policy.write_text(text, "utf-8")
            print(f"[OK] policy/{policy.name}: {len(text)} chars")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
