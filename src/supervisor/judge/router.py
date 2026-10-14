"""Judge router: which ChatModel judges which tier, and the family-independence rule.

* One model per tier from settings (``JUDGE_T1_MODEL``, ``JUDGE_T2_MODEL``, base URLs);
  MockJudge when unset. Optional challenger (``JUDGE_CHALLENGER_MODEL``) scores a
  deterministic sample (``JUDGE_CHALLENGER_SAMPLE_BP``, default 500 = 5 %) of one tier;
  its verdicts are stored with role ``challenger`` and never acted on.
* ``judge.family != agent.family`` for every agent in the registry (manifests plus the
  ``agent`` / ``agent_version`` tables when a StateStore is given). A conflict, or a judge
  whose family cannot be read from its name, raises :class:`FamilyConflictError` at
  startup. ``tests/judge/test_router.py`` runs the same check in CI on the committed
  manifests and the default settings.
* Model ids are pinned: ``latest`` aliases are refused. ``region``, ``model_version`` and
  the masker version are carried into each verdict.
* Sampling is a hash of (salt, trace_id): reproducible and auditable, not ``random``.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from supervisor.config import REPO_ROOT, Settings
from supervisor.core.errors import ConfigError
from supervisor.core.ports import ChatModel, StateStore, TableStore

log = logging.getLogger("supervisor.judge")

Role = Literal["primary", "challenger"]
MANIFEST_ROOT = REPO_ROOT / "src" / "supervisor_agents"

# Aliases so "claude" and "anthropic" (etc.) count as the same family.
FAMILY_ALIASES: dict[str, str] = {
    "claude": "anthropic",
    "gpt": "openai",
    "o1": "openai",
    "llama": "meta",
    "gemma": "google",
    "gemini": "google",
    "qwen3": "qwen",
    "qwen2": "qwen",
    "mistralai": "mistral",
}


class FamilyConflictError(ConfigError):
    """A judge shares its model family with an agent it watches (or the family is unknown)."""


def normalize_family(family: str | None) -> str:
    f = (family or "").strip().lower()
    return FAMILY_ALIASES.get(f, f)


def _model_version(model_id: str) -> str:
    """Tag after ``:`` or ``@`` (``qwen3:4b`` -> ``4b``), else the whole id."""
    for sep in ("@", ":"):
        if sep in model_id:
            return model_id.rsplit(sep, 1)[1]
    return model_id


def check_pinned(model_id: str) -> None:
    low = model_id.strip().lower()
    if low == "latest" or low.endswith((":latest", "-latest", "@latest", "/latest")):
        raise ConfigError(
            f"judge model {model_id!r} is not pinned: use an exact version, not 'latest' "
            "(a model change is a re-validation trigger, ADR D06)"
        )


@dataclass(frozen=True)
class JudgeModel:
    """One configured judge: a ChatModel plus what goes into every verdict it writes."""

    tier: int
    role: Role
    chat: ChatModel
    region: str

    @property
    def family(self) -> str:
        return normalize_family(self.chat.family)

    @property
    def model_id(self) -> str:
        return self.chat.model_id

    @property
    def model_version(self) -> str:
        return _model_version(self.chat.model_id)

    @property
    def is_mock(self) -> bool:
        return bool(self.chat.is_mock)

    @property
    def checker_id(self) -> str:
        return f"judge.t{self.tier}.{self.role}"


def load_manifest_families(root: Path = MANIFEST_ROOT) -> dict[str, str]:
    """``{agent_id: model_family}`` from every ``*/manifest.yaml`` under ``root``."""
    out: dict[str, str] = {}
    for path in sorted(root.glob("*/manifest.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if "id" in data:
            out[str(data["id"])] = str(data.get("model_family") or "")
    return out


def load_registry_families(
    state: StateStore | None = None, tables: TableStore | None = None
) -> dict[str, set[str]]:
    """``{agent_id: {families}}`` from the ``agent`` (state) and ``agent_version`` tables."""
    rows: list[Mapping[str, Any]] = []
    if state is not None:
        rows.extend(state.query("agent"))
    if tables is not None:
        rows.extend(tables.query("agent_version"))
    out: dict[str, set[str]] = {}
    for row in rows:
        fam = row.get("model_family")
        if fam:
            out.setdefault(str(row["agent_id"]), set()).add(str(fam))
    return out


def check_family_independence(
    judges: Iterable[JudgeModel], agent_families: Mapping[str, str | Iterable[str]]
) -> None:
    """Raise FamilyConflictError when any judge shares a family with any agent."""
    problems: list[str] = []
    for j in judges:
        fam = j.family
        if fam in ("", "unknown"):
            problems.append(
                f"{j.checker_id} model {j.model_id!r}: family unknown; set "
                f"JUDGE_{'CHALLENGER' if j.role == 'challenger' else 'T' + str(j.tier)}_FAMILY"
            )
            continue
        for agent_id, fams in sorted(agent_families.items()):
            fam_set = {fams} if isinstance(fams, str) else set(fams)
            if fam in {normalize_family(f) for f in fam_set}:
                problems.append(
                    f"{j.checker_id} model {j.model_id!r} is family {fam!r}, the same as "
                    f"agent {agent_id!r}"
                )
    if problems:
        raise FamilyConflictError(
            "judge model family must differ from the agent model family: " + "; ".join(problems)
        )


def sample_hit(salt: str, key: str, rate_bp: int) -> bool:
    """Deterministic Bernoulli(rate_bp / 10000) by hash of (salt, key)."""
    if rate_bp <= 0:
        return False
    if rate_bp >= 10000:
        return True
    digest = hashlib.sha256(f"{salt}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 10000 < rate_bp


class JudgeRouter:
    def __init__(
        self,
        t1: JudgeModel,
        t2: JudgeModel,
        challenger: JudgeModel | None = None,
        *,
        agent_families: Mapping[str, str | Iterable[str]],
        challenger_sample_bp: int = 500,
        t2_sample_bp: int = 200,
        salt: str = "supervisor-judge-v1",
    ) -> None:
        if t1.tier != 1 or t2.tier != 2 or t1.role != "primary" or t2.role != "primary":
            raise ConfigError("router needs a primary Tier 1 and a primary Tier 2 judge")
        if challenger is not None and challenger.role != "challenger":
            raise ConfigError("challenger judge must have role 'challenger'")
        judges = [j for j in (t1, t2, challenger) if j is not None]
        for j in judges:
            if not j.is_mock:
                check_pinned(j.model_id)
        check_family_independence(judges, agent_families)
        if t1.family == t2.family and not t1.is_mock:
            log.warning(
                "Tier 1 and Tier 2 judges share family %r; one payload may beat both", t1.family
            )
        self.t1, self.t2, self.challenger = t1, t2, challenger
        self.agent_families = dict(agent_families)
        self.challenger_sample_bp = challenger_sample_bp
        self.t2_sample_bp = t2_sample_bp
        self.salt = salt

    @property
    def is_mock(self) -> bool:
        return self.t1.is_mock or self.t2.is_mock

    def model(self, tier: int) -> JudgeModel:
        return self.t1 if tier == 1 else self.t2

    def t2_sampled(self, trace_id: str) -> bool:
        return sample_hit(self.salt + ":t2", trace_id, self.t2_sample_bp)

    def challenger_for(self, tier: int, trace_id: str) -> JudgeModel | None:
        c = self.challenger
        if c is None or c.tier != tier:
            return None
        return (
            c
            if sample_hit(self.salt + ":challenger", trace_id, self.challenger_sample_bp)
            else None
        )

    def describe(self) -> dict[str, Any]:
        def one(j: JudgeModel | None) -> dict[str, Any] | None:
            if j is None:
                return None
            return {
                "checker_id": j.checker_id,
                "model_id": j.model_id,
                "model_version": j.model_version,
                "family": j.family,
                "region": j.region,
                "is_mock": j.is_mock,
            }

        return {"t1": one(self.t1), "t2": one(self.t2), "challenger": one(self.challenger)}

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        agent_families: Mapping[str, str | Iterable[str]] | None = None,
        state: StateStore | None = None,
        tables: TableStore | None = None,
        chats: Mapping[str, ChatModel] | None = None,
    ) -> JudgeRouter:
        """Build the router; raise FamilyConflictError / ConfigError at startup.

        ``agent_families`` defaults to the committed manifests; with ``state`` /
        ``tables`` the registry rows (agent, agent_version) are added.
        ``chats`` overrides models per role (tests)."""
        from supervisor.adapters.factory import make_judge_chat_model

        families: dict[str, set[str]] = {}
        source = agent_families if agent_families is not None else load_manifest_families()
        for agent_id, fams in source.items():
            families.setdefault(agent_id, set()).update({fams} if isinstance(fams, str) else fams)
        if state is not None or tables is not None:
            for agent_id, fams in load_registry_families(state, tables).items():
                families.setdefault(agent_id, set()).update(fams)

        def chat(role: str) -> ChatModel:
            if chats and role in chats:
                return chats[role]
            return make_judge_chat_model(settings, role)

        t1 = JudgeModel(1, "primary", chat("t1"), settings.judge_region)
        t2 = JudgeModel(2, "primary", chat("t2"), settings.judge_region)
        challenger = None
        if settings.judge_challenger_model or (chats and "challenger" in chats):
            challenger = JudgeModel(
                settings.judge_challenger_tier,
                "challenger",
                chat("challenger"),
                settings.judge_region,
            )
        return cls(
            t1,
            t2,
            challenger,
            agent_families=families,
            challenger_sample_bp=settings.judge_challenger_sample_bp,
            t2_sample_bp=settings.judge_t2_sample_bp,
            salt=settings.judge_sample_salt,
        )
