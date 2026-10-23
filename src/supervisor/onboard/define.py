"""Define from an artifact (WP-G3): Discover and Understand on an MLflow model artifact folder.

    python -m supervisor.onboard.define --artifact <folder> [--out <folder>] [--agent-id ID]

The folder is what ``mlflow.<flavor>.log_model`` writes (or a download of it): ``MLmodel``,
``requirements.txt``, the agent code, a tool manifest (``tools.json``, ``tools.yaml``,
``tool_manifest.*``, ``manifest.yaml`` or ``agent.yaml``) and prompt files. There is no git
repository and no workspace call. It runs the same two stages as ``python -m supervisor.onboard``
and writes the same ``inventory.json`` and ``profile.json`` (plus ``profile.md`` and
``artifact.json`` with the MLmodel and requirements facts, each with file:line evidence).

Rules (docs/onboard.md, "Define from an artifact"):

* Read only. The artifact folder is never written to; ``--out`` must be outside it.
* Every text is scrubbed (``Scrubber``) when it is read, before it is parsed or stored, so no
  secret reaches an artefact or a model. No network: the model step runs only with ``--llm``
  (the configured model) or ``--mock-llm``; the default is the deterministic profile.
* Prompt-like text in the artifact is data, never an instruction (``injection.py``).
* ASCII output only: ``[OK]``, ``[FAIL]``, ``[SKIP]``.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from collections.abc import Callable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import yaml  # noqa: E402

from supervisor.adapters.repo import LocalGitRepoReader  # noqa: E402
from supervisor.adapters.repo.local_git import RepoReadError  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.core.ports import ChatModel  # noqa: E402
from supervisor.onboard import render  # noqa: E402
from supervisor.onboard.autonomy import propose_autonomy_level  # noqa: E402
from supervisor.onboard.discover import (  # noqa: E402
    ARTIFACT_MANIFEST_NAMES,
    Discovery,
    SourceIndex,
    discover,
    features_of,
)
from supervisor.onboard.injection import neutralize, neutralize_tree  # noqa: E402
from supervisor.onboard.models import AgentProfile, Inventory, PromptInfo  # noqa: E402
from supervisor.onboard.scrub import Scrubber  # noqa: E402
from supervisor.onboard.understand import understand  # noqa: E402

MLMODEL = "MLmodel"
# MLmodel flavor -> framework name used by Discover (onboard/codefacts.py)
FLAVOR_FRAMEWORK: dict[str, str] = {
    "langchain": "langchain",
    "openai": "openai_sdk",
    "llama_index": "llamaindex",
    "crewai": "crewai",
    "anthropic": "anthropic_sdk",
}
# requirements.txt package -> framework, first match wins (same order as codefacts._FRAMEWORKS)
REQUIREMENT_FRAMEWORK: tuple[tuple[str, str], ...] = (
    ("deepagents", "deepagents"),
    ("langgraph", "langgraph"),
    ("crewai", "crewai"),
    ("llama-index", "llamaindex"),
    ("databricks-agents", "databricks_agents"),
    ("databricks-langchain", "langchain"),
    ("langchain", "langchain"),
    ("fastmcp", "fastmcp"),
    ("anthropic", "anthropic_sdk"),
    ("openai", "openai_sdk"),
)
AI_PACKAGES = frozenset(
    {
        "mlflow",
        "databricks-agents",
        "databricks-langchain",
        "langchain",
        "langgraph",
        "llama-index",
        "crewai",
        "openai",
        "anthropic",
        "mcp",
        "fastmcp",
        "transformers",
        "torch",
    }
)
PROMPT_SUFFIXES = (".txt", ".md", ".yaml", ".yml", ".json")
MAX_PROMPT_FILES = 40
_REQ = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(?:\[[^\]]*\])?\s*(==|>=|<=|~=|>|<)?\s*([\w.*+!-]*)")


class DefineError(SupervisorError):
    """Bad input to ``define`` (a CLI [FAIL], HTTP 400 if it ever reaches a route)."""


@dataclass
class DefineResult:
    out_dir: Path
    inventory: Inventory
    profile: AgentProfile
    artifact: dict[str, Any]
    autonomy: dict[str, Any] = field(default_factory=dict)
    artefacts: dict[str, Path] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)


def _json(data: Any) -> str:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- MLmodel


def mlmodel_facts(index: SourceIndex) -> dict[str, Any]:
    """Facts from the scrubbed ``MLmodel`` file, each with ``file:line`` evidence. Run ids, model
    uuids and creation times are left out on purpose (they identify a workspace object)."""
    rows = index.lines.get(MLMODEL)
    if rows is None:
        return {}
    try:
        doc = yaml.safe_load("\n".join(rows))
    except yaml.YAMLError:
        return {"error": "MLmodel is not valid YAML"}
    if not isinstance(doc, Mapping):
        return {"error": "MLmodel is not a mapping"}

    def ev(pattern: str) -> str:
        line = index.find(MLMODEL, pattern)
        return index.evidence(MLMODEL, line).ref() if line else f"{MLMODEL}:1"

    flavors = doc.get("flavors") if isinstance(doc.get("flavors"), Mapping) else {}
    out: dict[str, Any] = {
        "flavors": [
            {"name": str(k), "evidence": ev(rf"^\s*{re.escape(str(k))}:")} for k in sorted(flavors)
        ],
    }
    pyf = flavors.get("python_function") if isinstance(flavors, Mapping) else None
    if isinstance(pyf, Mapping):
        for key in ("loader_module", "python_model", "python_version"):
            if pyf.get(key):
                out[key] = {"value": str(pyf[key])[:200], "evidence": ev(rf"^\s*{key}:")}
    meta = doc.get("metadata") if isinstance(doc.get("metadata"), Mapping) else {}
    if meta.get("task"):
        out["task"] = {"value": str(meta["task"])[:80], "evidence": ev(r"^\s*task:")}
    if doc.get("signature"):
        out["signature"] = {"evidence": ev(r"^signature:")}
    if doc.get("mlflow_version"):
        out["mlflow_version"] = {
            "value": str(doc["mlflow_version"])[:40],
            "evidence": ev(r"^mlflow_version:"),
        }
    return out


def requirements_facts(index: SourceIndex) -> list[dict[str, str]]:
    """Packages of every ``requirements*.txt`` that matter for an AI agent, with evidence."""
    out: list[dict[str, str]] = []
    for f in sorted(index.lines):
        if not re.search(r"(^|/)requirements[\w.-]*\.txt$", f):
            continue
        for i, line in enumerate(index.lines[f], start=1):
            m = _REQ.match(line)
            if not m or line.lstrip().startswith(("#", "-")):
                continue
            name = m.group(1).lower().replace("_", "-")
            if name in AI_PACKAGES:
                out.append(
                    {
                        "package": name,
                        "version": (m.group(3) or "") if m.group(2) == "==" else "",
                        "evidence": index.evidence(f, i).ref(),
                    }
                )
    return out


def _framework_from(facts: Mapping[str, Any], reqs: Sequence[Mapping[str, str]]) -> tuple[str, str]:
    """(framework, evidence ref) from the MLmodel flavors, then the task, then requirements."""
    flavors = {f["name"]: f["evidence"] for f in facts.get("flavors", [])}
    for flavor, fw in FLAVOR_FRAMEWORK.items():
        if flavor in flavors:
            return fw, flavors[flavor]
    task = facts.get("task")
    if task and str(task["value"]).startswith("agent/"):
        return "databricks_agents", task["evidence"]
    names = {r["package"]: r["evidence"] for r in reqs}
    for pkg, fw in REQUIREMENT_FRAMEWORK:
        if pkg in names:
            return fw, names[pkg]
    return "unknown", ""


# --------------------------------------------------------------------------- prompt files


def _is_prompt_file(path: str, manifest: str | None) -> bool:
    low = path.lower()
    if path == manifest or not low.endswith(PROMPT_SUFFIXES):
        return False
    parts = low.split("/")
    return "prompt" in parts[-1] or any(p in ("prompt", "prompts") for p in parts[:-1])


def prompt_files(index: SourceIndex, manifest: str | None) -> list[PromptInfo]:
    """Prompt files of the artifact (``prompts/``, ``*prompt*``): kind, excerpt, hash, line."""
    out: list[PromptInfo] = []
    for f in sorted(index.lines)[:]:
        if not _is_prompt_file(f, manifest) or len(out) >= MAX_PROMPT_FILES:
            continue
        rows = index.lines[f]
        text = "\n".join(rows).strip()
        first = next((i for i, r in enumerate(rows, start=1) if r.strip()), None)
        if not text or first is None:
            continue
        low = f.lower()
        kind = "system" if "system" in low else "template" if "{{" in text else "task"
        out.append(
            PromptInfo(
                kind=kind,  # type: ignore[arg-type]
                excerpt=neutralize(" ".join(text.split()))[:240],
                sha256=_sha(text),
                evidence=index.evidence(f, first),
            )
        )
    return out


# --------------------------------------------------------------------------- the two stages


def define_artifact(
    artifact: str | Path,
    out_dir: str | Path,
    *,
    chat: ChatModel | None = None,
    agent_id: str | None = None,
    scrubber: Scrubber | None = None,
    echo: Callable[[str], None] | None = None,
) -> DefineResult:
    """Discover and Understand on an MLflow artifact folder; write the artefacts to ``out_dir``."""
    src = Path(os.path.abspath(artifact))
    out = Path(os.path.abspath(out_dir))
    if not src.is_dir():
        raise DefineError(f"artifact folder does not exist: {src.name}")
    if out == src or src in out.parents:
        raise DefineError("--out must be outside the artifact folder (the artifact is read only)")
    lines: list[str] = []

    def say(line: str) -> None:
        lines.append(line)
        if echo is not None:
            echo(line)

    reader = LocalGitRepoReader(src)
    scrubber = scrubber or Scrubber()
    agent_id = _resolve_agent_id(src, agent_id)  # WP-P2
    try:
        disc = discover(
            reader,
            scrubber=scrubber,
            agent_id=agent_id,
            manifest_names=ARTIFACT_MANIFEST_NAMES,
        )
    except RepoReadError as exc:
        raise DefineError(f"cannot read the artifact: {exc}") from exc
    disc = _add_artifact_facts(disc)
    inv = disc.inventory
    if MLMODEL not in disc.index.lines:
        say("[SKIP] no MLmodel file in the artifact: read as a plain agent folder")
    say(
        f"[OK] discover: {len(inv.tools)} tool(s), {len(inv.model_endpoints)} model endpoint(s), "
        f"{len(inv.prompts)} prompt(s), framework {inv.framework}, "
        f"{scrubber.total} secret(s) redacted"
    )
    profile = understand(disc, chat)
    autonomy = propose_autonomy_level(disc)
    say(f"[OK] autonomy level proposal: {autonomy['level']} ({autonomy['why']})")
    say(
        f"[OK] understand: proposed tier {profile.proposed_risk_tier}, Decision 33 proposal "
        f"{profile.decision33.classification} (counsel confirms), LLM used: {profile.llm.used}"
    )
    facts = {
        "version": 1,
        "agent_id": inv.agent_id,
        "mlmodel": mlmodel_facts(disc.index),
        "requirements": requirements_facts(disc.index),
        "files": inv.files,
    }
    facts = neutralize_tree(facts)
    out.mkdir(parents=True, exist_ok=True)
    texts = {
        "inventory.json": _json(inv),
        "profile.json": _json(
            {**profile.model_dump(mode="json"), "autonomy_level_proposal": autonomy}
        ),
        "profile.md": render.profile_md(inv, profile),
        "artifact.json": _json(facts),
    }
    paths: dict[str, Path] = {}
    for name, text in texts.items():
        p = out / name
        p.write_text(text, encoding="utf-8", newline="\n")
        paths[name] = p
        say(f"[OK] wrote {p}")
    return DefineResult(out, inv, profile, facts, autonomy, paths, lines)


def _mlmodel_metadata(index: SourceIndex) -> dict[str, Any]:
    rows = index.lines.get(MLMODEL)
    if rows is None:
        return {}
    try:
        doc = yaml.safe_load("\n".join(rows))
    except yaml.YAMLError:
        return {}
    meta = doc.get("metadata") if isinstance(doc, Mapping) else None
    return dict(meta) if isinstance(meta, Mapping) else {}


def _resolve_agent_id(src: Path, agent_id: str | None) -> str | None:
    """WP-P2: the ``--agent-id`` flag, else ``metadata.agent_id`` of the MLmodel file. Never the
    literal folder name ``artifact`` (an MLflow download folder says nothing about the agent)."""
    if agent_id:
        return agent_id
    f = src / MLMODEL
    if f.is_file():
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            doc = None
        meta = doc.get("metadata") if isinstance(doc, Mapping) else None
        value = meta.get("agent_id") if isinstance(meta, Mapping) else None
        if isinstance(value, str) and value.strip() and not value.upper().startswith("FILL-ME"):
            return value.strip()
    if src.name.lower() == "artifact":
        raise DefineError(
            "the agent id is unknown: pass --agent-id or set metadata.agent_id in the MLmodel file "
            "(the folder name 'artifact' is not an id)"
        )
    return None


def _add_artifact_facts(disc: Discovery) -> Discovery:
    """Add what only an artifact has: framework from MLmodel or requirements, prompt files,
    the owner (``metadata.owner`` is the owner user, ``metadata.owner_team`` the team) and no tool
    that is the agent id itself."""
    inv, index = disc.inventory, disc.index
    update: dict[str, Any] = {}
    meta = _mlmodel_metadata(index)

    def given(key: str) -> str | None:  # a FILL-ME placeholder is an absent value
        v = str(meta.get(key) or "").strip()
        return v[:200] if v and not v.upper().startswith("FILL-ME") else None

    if str(inv.owner_user).startswith("FILL-ME") and given("owner"):
        update["owner_user"] = given("owner")
    if str(inv.owner_team).startswith("FILL-ME") and given("owner_team"):
        update["owner_team"] = given("owner_team")
    phantom = [t for t in inv.tools if t.name == inv.agent_id and t.manifest_entry is None]
    if phantom:
        update["tools"] = [t for t in inv.tools if t not in phantom]
    if inv.framework == "unknown":
        fw, ref = _framework_from(mlmodel_facts(index), requirements_facts(index))
        if fw != "unknown" and ref:
            file, _, line = ref.rpartition(":")
            update["framework"] = fw
            update["framework_evidence"] = index.evidence(file, int(line))
    known = {p.sha256 for p in inv.prompts}
    extra = [p for p in prompt_files(index, inv.manifest_file) if p.sha256 not in known]
    if extra:
        update["prompts"] = [*inv.prompts, *extra]
    if update:
        inv = inv.model_copy(update=update)
        inv.features = features_of(inv)
        inv = Inventory.model_validate(neutralize_tree(inv.model_dump()))
    return Discovery(inv, index)


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m supervisor.onboard.define",
        description="Discover and Understand on an MLflow model artifact folder.",
    )
    parser.add_argument("--artifact", required=True, help="MLflow model artifact folder")
    parser.add_argument(
        "--out", help="output folder (default: define-out\\<artifact name>, outside the artifact)"
    )
    parser.add_argument("--agent-id", help="agent id (default: from the manifest or folder name)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--llm", action="store_true", help="use the configured model (scrubbed text)"
    )
    group.add_argument("--mock-llm", action="store_true", help="use the mock model (labelled mock)")
    args = parser.parse_args(argv)

    def echo(line: str) -> None:
        print(line.encode("ascii", "replace").decode("ascii"))  # noqa: T201

    out = args.out or os.path.join("define-out", Path(os.path.abspath(args.artifact)).name)
    try:
        chat: ChatModel | None = None
        if args.mock_llm:
            from supervisor.adapters.llm.mock import MockChat

            chat = MockChat(model_id="mock-onboarding-v1")
        elif args.llm:
            from supervisor.adapters.factory import make_chat_model
            from supervisor.config import load_settings

            chat = make_chat_model(load_settings())
        define_artifact(args.artifact, out, chat=chat, agent_id=args.agent_id, echo=echo)
    except (SupervisorError, OSError, ValueError) as exc:
        echo(f"[FAIL] define stopped: {type(exc).__name__}: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI prints [FAIL], never a traceback
        echo(f"[FAIL] define stopped by an internal error: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
