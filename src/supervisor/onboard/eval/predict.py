"""Run the analyser on one repo and extract comparable predictions.

Every field is read with ``getattr`` fallbacks so the eval works before and after the
analyser gains new fields (llm_calls, framework, data_access, tracing, autonomy, ...).
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.onboard.discover import discover
from supervisor.onboard.render import profile_md
from supervisor.onboard.scrub import Scrubber
from supervisor.onboard.understand import build_messages, understand

_MODEL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("qwen", "qwen"),
    ("llama", "meta"),
    ("gemma", "google"),
    ("deepseek", "deepseek"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("dbrx", "databricks"),
)
_VENDOR_PREFIXES = ("databricks-", "meta-", "us.anthropic.", "anthropic.")


def family_of(model: str) -> str:
    """Model family by the README table (vendor prefixes cut first)."""
    name = model.strip().lower().rsplit("/", 1)[-1]
    changed = True
    while changed:
        changed = False
        for p in _VENDOR_PREFIXES:
            if name.startswith(p):
                name, changed = name[len(p) :], True
    for prefix, fam in _MODEL_PREFIXES:
        if name.startswith(prefix):
            return fam
    return "unknown"


@dataclass(frozen=True)
class Item:
    """One predicted or labelled thing at a place. Unused attributes keep their defaults."""

    file: str
    line: int
    name: str = ""
    kind: str = ""
    direction: str = ""
    target: str | None = None
    provider: str = ""
    family: str = ""
    model: str | None = None

    def short(self) -> str:
        return f"{self.name or self.kind or 'item'}@{self.file}:{self.line}"


class CapturingChat:
    """Wraps a chat model and records every ``messages`` list passed to ``complete_json``."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.family = inner.family
        self.model_id = inner.model_id
        self.is_mock = inner.is_mock
        self.seen: list[list[dict[str, str]]] = []

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        self.seen.append([dict(m) for m in messages])
        return self.inner.complete_json(messages, json_schema, timeout_s)  # type: ignore[no-any-return]


@dataclass
class Prediction:
    tools: list[Item] = field(default_factory=list)
    llm_calls: list[Item] = field(default_factory=list)
    data_access: list[Item] = field(default_factory=list)
    pii_fields: list[str] = field(default_factory=list)
    tracing: list[str] = field(default_factory=list)
    framework: str = "unknown"
    decision33: str = "unknown"
    autonomy: str = "unknown"
    injections: list[tuple[str, int]] = field(default_factory=list)
    artefacts: dict[str, str] = field(default_factory=dict)
    prompts: list[str] = field(default_factory=list)
    index_lines: dict[str, list[str]] = field(default_factory=dict)


def _ev(ev: Any) -> tuple[str, int]:
    return (str(getattr(ev, "file", "")), int(getattr(ev, "line", 0)))


def _tools(inv: Any) -> list[Item]:
    out = []
    for t in inv.tools:
        file, line = _ev(t.definition or t.manifest_entry)
        out.append(Item(file=file, line=line, name=t.name))
    return out


def _llm_calls(inv: Any) -> list[Item]:
    calls = getattr(inv, "llm_calls", None)
    if isinstance(calls, list):
        out = []
        for c in calls:
            file, line = _ev(getattr(c, "evidence", None))
            out.append(
                Item(
                    file=file,
                    line=line,
                    provider=str(getattr(c, "provider", "unknown")),
                    family=str(getattr(c, "family", "unknown")),
                    model=getattr(c, "model", None),
                )
            )
        return out
    out = []
    for e in inv.model_endpoints:  # fallback: endpoints found in code
        if e.source != "code" or e.evidence is None:
            continue
        is_model = family_of(e.name) != "unknown" or re.search(r"\d", e.name) is not None
        model = e.name if is_model else None
        file, line = _ev(e.evidence)
        out.append(
            Item(
                file=file,
                line=line,
                provider="unknown",
                family=family_of(model) if model else "unknown",
                model=model,
            )
        )
    return out


def _data_access(inv: Any) -> list[Item]:
    rows = getattr(inv, "data_access", None)
    if isinstance(rows, list):
        out = []
        for d in rows:
            file, line = _ev(getattr(d, "evidence", None))
            out.append(
                Item(
                    file=file,
                    line=line,
                    kind=str(d.kind),
                    direction=str(d.direction),
                    target=getattr(d, "target", None),
                )
            )
        return out
    out = []
    for t in inv.tables:
        if t.evidence is None:
            continue
        file, line = _ev(t.evidence)
        out.append(Item(file=file, line=line, kind="db", direction=t.direction, target=t.name))
    return out


def _tracing(inv: Any) -> list[str]:
    declared = getattr(inv, "tracing", None)
    if isinstance(declared, list):
        return sorted({str(x) for x in declared})
    found: set[str] = set()
    for t in inv.traces:
        n = t.name.lower()
        if "opentelemetry" in n or "otel" in n:
            found.add("otel")
        if "mlflow" in n:
            found.add("mlflow")
    return sorted(found)


def predict_repo(repo_dir: str | Path) -> Prediction:
    """Run discover + understand (mock model) on one repo folder; no network."""
    disc = discover(LocalGitRepoReader(repo_dir), scrubber=Scrubber())
    inv, idx = disc.inventory, disc.index
    chat = CapturingChat(MockChat(model_id="mock-onboard-eval"))
    kwargs: dict[str, Any] = {}
    if "exercise_llm" in inspect.signature(understand).parameters:
        kwargs["exercise_llm"] = True
    profile = understand(disc, chat, **kwargs)  # type: ignore[arg-type]
    messages = [*chat.seen, build_messages(inv, idx, nonce="eval")]
    refs = getattr(inv, "injection_refs", None) or []
    dump = {
        "inventory.json": inv.model_dump(mode="json"),
        "profile.json": profile.model_dump(mode="json"),
    }
    artefacts = {k: json.dumps(v, ensure_ascii=False, sort_keys=True) for k, v in dump.items()}
    artefacts["profile.md"] = profile_md(inv, profile)
    return Prediction(
        tools=_tools(inv),
        llm_calls=_llm_calls(inv),
        data_access=_data_access(inv),
        pii_fields=sorted(set(inv.pii_fields) | set(getattr(inv, "pii_identifiers", {}))),
        tracing=_tracing(inv),
        framework=getattr(inv, "framework", None) or "unknown",
        decision33=profile.decision33.classification,
        autonomy=getattr(profile, "autonomy", None) or "unknown",
        injections=[_ev(getattr(r, "evidence", r)) for r in refs],
        artefacts=artefacts,
        prompts=[str(m.get("content", "")) for msgs in messages for m in msgs],
        index_lines={f: list(rows) for f, rows in idx.lines.items()},
    )
