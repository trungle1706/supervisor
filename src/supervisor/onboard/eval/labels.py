"""Gold labels (schema in data/corpus/README.md) and the label checker."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from supervisor.onboard.scrub import scrub_text

Framework = Literal[
    "langgraph",
    "langchain",
    "llamaindex",
    "openai_sdk",
    "anthropic_sdk",
    "databricks_agents",
    "fastmcp",
    "fastapi",
    "crewai",
    "custom",
]


class _L(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolLabel(_L):
    name: str
    file: str
    line: int = Field(ge=1)


class LlmCallLabel(_L):
    file: str
    line: int = Field(ge=1)
    provider: str
    family: str
    model: str | None = None


class DataAccessLabel(_L):
    kind: Literal["db", "http", "bank_api", "file"]
    direction: Literal["read", "write"]
    target: str | None = None
    file: str
    line: int = Field(ge=1)


class SecretLabel(_L):
    file: str
    line: int = Field(ge=1)
    kind: str
    needle: str = Field(min_length=1)


class InjectionLabel(_L):
    file: str
    line: int = Field(ge=1)
    lang: Literal["en", "vi"]
    needle: str = Field(min_length=1)


class RepoLabels(_L):
    framework: Framework
    summary: str = ""
    tools: list[ToolLabel] = Field(default_factory=list)
    llm_calls: list[LlmCallLabel] = Field(default_factory=list)
    data_access: list[DataAccessLabel] = Field(default_factory=list)
    pii_fields: list[str] = Field(default_factory=list)
    tracing: list[Literal["mlflow", "otel"]] = Field(default_factory=list)
    decision33: Literal["high_risk", "not_high_risk"]
    autonomy: Literal["L0", "L1", "L2", "L3"]
    secrets: list[SecretLabel] = Field(default_factory=list)
    injections: list[InjectionLabel] = Field(default_factory=list)


class Labels(_L):
    version: Literal[1]
    repos: dict[str, RepoLabels]


def load_labels(path: str | Path) -> Labels:
    """Parse and validate a labels file (raises ValueError / OSError / yaml.YAMLError)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Labels.model_validate(data)


def _located(lab: RepoLabels) -> list[tuple[str, str, int, str | None]]:
    """(what, file, line, needle) for every label that points into a file."""
    out: list[tuple[str, str, int, str | None]] = []
    out += [(f"tool {t.name}", t.file, t.line, t.name) for t in lab.tools]
    out += [("llm_call", c.file, c.line, None) for c in lab.llm_calls]
    out += [("data_access", d.file, d.line, None) for d in lab.data_access]
    out += [("secret", s.file, s.line, s.needle) for s in lab.secrets]
    out += [("injection", i.file, i.line, i.needle) for i in lab.injections]
    return out


def check_labels(corpus_dir: str | Path, labels: Labels) -> list[str]:
    """Problems found when the labels are compared with the repo files (empty = fine)."""
    root = Path(corpus_dir)
    problems: list[str] = []
    dirs = {p.name for p in root.iterdir() if p.is_dir()} if root.is_dir() else set()
    for name in sorted(set(labels.repos) - dirs):
        problems.append(f"{name}: repo dir missing")
    for name in sorted(dirs - set(labels.repos)):
        problems.append(f"{name}: repo dir without labels")
    cache: dict[Path, list[str] | None] = {}
    for name in sorted(set(labels.repos) & dirs):
        lab = labels.repos[name]
        base = (root / name).resolve()
        for what, file, line, needle in _located(lab):
            where = f"{name}/{file}:{line}"
            path = (base / file).resolve()
            if Path(file).is_absolute() or not path.is_relative_to(base):
                problems.append(f"{where}: {what}: path outside the repo")
                continue
            if path not in cache:
                cache[path] = (
                    path.read_text(encoding="utf-8", errors="replace").splitlines()
                    if path.is_file()
                    else None
                )
            rows = cache[path]
            if rows is None:
                problems.append(f"{where}: {what}: file missing")
                continue
            if not 1 <= line <= len(rows):
                problems.append(f"{where}: {what}: line out of range (file has {len(rows)})")
                continue
            text = rows[line - 1]
            if what.startswith("tool"):
                head = text.strip()
                if not head.startswith(("def ", "async def ", "class ")) and needle not in text:
                    problems.append(f"{where}: {what}: line is not a def/class and lacks the name")
            elif needle is not None and needle not in text:
                problems.append(f"{where}: {what}: needle not on the line")
        for s in lab.secrets:
            if scrub_text(s.needle).total:
                problems.append(f"{name}/{s.file}:{s.line}: secret needle matches a scrubber")
    return problems
