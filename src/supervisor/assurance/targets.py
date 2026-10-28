"""Targets for assurance runs: demo agents in the launch sandbox, onboarded repos, stored
traces and the judge.

``DemoAgentTarget`` re-uses the launch sandbox recipe (``supervisor.onboard.launch``): a
private SQLite store under ``work_dir``, a fresh synthetic ``BankWorld``, the real
``Gateway`` in SHADOW mode on the committed policy (``policies/*.yaml`` with every agent's
``initial_state`` set to SHADOW), a fixed clock that jumps between calls, the real
``AgentRuntime`` and tracer (traces land in the sandbox store). Only the agent's LLM is a
mock: ``MockChat`` driven by ``MockResponder`` (always labelled ``is_mock``).

``HttpAgentTarget`` (WP-O3b) reaches a candidate that runs elsewhere through its HTTP chat
endpoint (see ``docs/assurance.md`` "HTTP target (WP-O3b)").

Spec grammar of :func:`build_targets` (comma separated): ``agent:<id>``, ``traces:<id>``,
``judge``, ``demo``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.llm.mock import MockChat
from supervisor.assurance.mockagent import MockResponder
from supervisor.assurance.model import ModelDependency, TargetReply
from supervisor.config import REPO_ROOT, Settings, load_settings
from supervisor.core.errors import SupervisorError
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import Policy, StaticPolicyProvider, load_policy_texts
from supervisor.onboard.launch import (
    CASE_GAP_S,
    T0,
    _errors,
    _Recorder,
    _Sink,
    _stops,
    demo_harness,
)

DEMO_AGENTS: tuple[str, ...] = ("payments", "credit_prequal", "customer_service")
POLICY_DIR = REPO_ROOT / "policies"
LOCK_FILES = ("uv.lock", "poetry.lock", "Pipfile.lock", "pyproject.toml")
CONTEXT_OPEN = "<<<CONTEXT (reference passages)"
CONTEXT_CLOSE = "CONTEXT>>>"

_VENDOR = {
    "qwen": "Alibaba",
    "llama": "Meta",
    "gemma": "Google",
    "gemini": "Google",
    "mistral": "Mistral AI",
    "anthropic": "Anthropic",
    "claude": "Anthropic",
    "openai": "OpenAI",
    "gpt": "OpenAI",
    "mock": "mock",
}


class TargetError(SupervisorError):
    """A target cannot be built (unknown agent, bad spec)."""


# --------------------------------------------------------------------------- helpers


def _version_pinned(model_id: str) -> bool:
    """True when the model id carries an explicit tag or version (not ``latest``)."""
    low = model_id.strip().lower()
    if not low or low == "latest" or low.endswith(("latest", "-latest")):
        return False
    for sep in (":", "@"):
        if sep in low:
            return low.rsplit(sep, 1)[1] not in ("", "latest")
    return bool(re.search(r"\d", low))


def _vendor(family: str) -> str:
    return _VENDOR.get(family.strip().lower(), family.strip().title() or "unknown")


def repo_dependency_files(root: Path) -> list[Path]:
    """Lock and requirements files at ``root`` and one folder level down."""
    found: list[Path] = []
    dirs = [root] + sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    for d in dirs:
        try:
            names = sorted(p.name for p in d.iterdir() if p.is_file())
        except OSError:
            continue
        for name in names:
            if name in LOCK_FILES or re.fullmatch(r"requirements[\w.-]*\.txt", name):
                found.append(d / name)
    return found


def _own_dependency_files() -> list[Path]:
    return [p for p in (REPO_ROOT / "uv.lock", REPO_ROOT / "pyproject.toml") if p.is_file()]


def _call_dict(c: Any) -> dict[str, Any]:
    return {"tool": c.tool, "args": dict(c.args), "status": c.status}


def shadow_policy() -> Policy:
    """The committed policy (``policies/*.yaml``) with every agent starting in SHADOW."""
    texts = []
    for f in sorted(POLICY_DIR.glob("*.yaml")):
        text = f.read_text(encoding="utf-8")
        texts.append((f.name, re.sub(r"initial_state:\s*RUNNING", "initial_state: SHADOW", text)))
    return load_policy_texts(texts)


# --------------------------------------------------------------------------- demo agent


class DemoAgentTarget:
    """One of the three demo agents in the launch sandbox (gate in SHADOW, mock LLM)."""

    kind: Literal["agent"] = "agent"
    is_mock = True

    def __init__(
        self,
        agent_id: str,
        work_dir: str | Path,
        *,
        settings: Settings | None = None,
        policy: Policy | None = None,
    ) -> None:
        if agent_id not in DEMO_AGENTS:
            raise TargetError(f"{agent_id!r} is not a demo agent; use --repo for other agents")
        harness = demo_harness(agent_id)
        if harness is None:
            raise TargetError(f"no launch harness for agent {agent_id!r}")
        self.agent_id = agent_id
        self.target_id = agent_id
        self.settings = settings
        self.harness = harness
        sandbox = Path(work_dir) / "assurance_sandbox" / agent_id
        sandbox.mkdir(parents=True, exist_ok=True)
        self.sandbox_dir = sandbox
        sb_settings = load_settings(
            sql_backend="sqlite", data_dir=sandbox, sqlite_path=sandbox / "assurance.sqlite"
        )
        if sb_settings.sqlite_path and sb_settings.sqlite_path.exists():
            sb_settings.sqlite_path.unlink()
        self.clock = FixedClock(T0)
        self._adapters: Adapters = build_adapters(sb_settings, clock=self.clock)
        from supervisor.jobs import bootstrap_schema
        from supervisor_agents.common.tracing import AgentEventExporter, make_tracer_provider

        bootstrap_schema.run(sb_settings, self._adapters)
        self.sink = _Sink()
        self.world = harness.make_world()
        self.policy = policy if policy is not None else shadow_policy()
        self.gateway = Gateway(
            StaticPolicyProvider(self.policy),
            self._adapters.tables,
            self._adapters.state,
            self.sink,
            self.clock,
            facts=harness.facts(self.world) if harness.facts else None,
            env="sandbox",
            state_cache_ttl_s=0,
        )
        self._exporter = AgentEventExporter(self._adapters.tables, env="sandbox")
        self._provider = make_tracer_provider(self._exporter, service_name="supervisor-assurance")
        self._rec = _Recorder(self.gateway)
        self.chat = MockChat(seed=0, model_id="mock-assurance-agent")
        self.responder = MockResponder()
        self.runtime = harness.build(
            self.chat, self.world, gate=self._rec, tracer_provider=self._provider, env="sandbox"
        )
        self._max_steps = self.runtime.max_steps
        self._n = 0
        caps = {"chat", "tools", "planned", "deps", "models", "tool_manifest"}
        if agent_id == "credit_prequal":
            caps.add("decide")
        self.capabilities: frozenset[str] = frozenset(caps)

    # -- store -----------------------------------------------------------------
    def tables(self) -> Any:
        """The sandbox store that holds this agent's traces."""
        return self._adapters.tables

    def trace_target(self) -> StoreTraceTarget:
        return StoreTraceTarget(self.tables(), self.agent_id, is_mock=True)

    # -- running ---------------------------------------------------------------
    def _run(
        self,
        task: str,
        script: Sequence[Any],
        *,
        max_steps: int | None = None,
        gap_s: int | None = None,
    ) -> tuple[Any, list[str]]:
        self._n += 1
        key = f"assurance:{self._n}"
        self.clock.advance(CASE_GAP_S if gap_s is None else gap_s)
        self.chat.add_script(key, list(script))
        start = len(self._rec.answers)
        self.runtime.max_steps = max_steps or self._max_steps
        try:
            with self.chat.scenario(key):
                result = self.runtime.run(task, context={})
        finally:
            self.runtime.max_steps = self._max_steps
            answers = self._rec.answers[start:]
            self._rec.answers.clear()
            self.chat.calls.clear()
            self._exporter.spans.clear()
            self._exporter.events.clear()
            self.sink.entries.clear()
        stops = sorted(set(_stops(answers)) | set(_errors(answers)))
        return result, stops

    def _reply(self, result: Any, stops: list[str], *, refused: bool = False) -> TargetReply:
        return TargetReply(
            text=str(result.final_message or ""),
            refused=refused,
            tool_calls=[_call_dict(c) for c in result.tool_calls],
            gate_would_stop=stops,
            trace_id=result.trace_id,
            is_mock=True,
        )

    def _loop_script(
        self,
        prompt: str,
        context: Sequence[str],
        sample: int,
        first_tool: tuple[str, Mapping[str, Any]] | None = None,
    ) -> list[Callable[[Sequence[Mapping[str, str]]], Mapping[str, Any]]]:
        def step(messages: Sequence[Mapping[str, str]]) -> Mapping[str, Any]:
            return self.responder.step(
                messages,
                tools=self.runtime.tools.names(),
                prompt=prompt,
                context=context,
                sample=sample,
                first_tool=first_tool,
            )

        return [step] * (self._max_steps + 1)

    # -- AgentTarget -----------------------------------------------------------
    def respond(self, prompt: str, *, context: Sequence[str] = (), sample: int = 0) -> TargetReply:
        task = prompt
        if context:
            block = "\n".join(f"[{i}] {c}" for i, c in enumerate(context, 1))
            task = f"{prompt}\n\n{CONTEXT_OPEN}\n{block}\n{CONTEXT_CLOSE}"
        answer = self.responder.answer(prompt, context, sample)
        result, stops = self._run(task, self._loop_script(prompt, context, sample))
        return self._reply(result, stops, refused=answer.refused)

    def _placeholder_args(self, tool: str) -> dict[str, Any]:
        spec = self.runtime.manifest.tool(tool)
        w = self.world
        known: dict[str, Any] = {
            "customer_id": next(iter(w.customers), ""),
            "account_id": next(iter(w.accounts), ""),
            "ticket_id": next(iter(w.tickets), ""),
            "application_id": next(iter(w.applications), ""),
            "payee_id": next(iter(w.payees), ""),
        }
        args: dict[str, Any] = {}
        for name, typ in (spec.args if spec else {}).items():
            if name in known:
                args[name] = known[name]
            elif typ == "integer":
                args[name] = 0
            elif typ == "array":
                args[name] = []
            else:
                args[name] = ""
        return args

    def run_with_tool_result(
        self, prompt: str, tool: str, injected_result: Mapping[str, Any]
    ) -> TargetReply:
        registry = self.runtime.tools
        original = registry.tools.get(tool)
        injected = dict(injected_result)
        used = {"n": 0}

        def wrapped(args: Mapping[str, Any]) -> Mapping[str, Any]:
            if used["n"] == 0:
                used["n"] = 1
                return dict(injected)
            if original is None:
                return {"error": "no such tool"}
            return original(args)

        registry.tools[tool] = wrapped
        try:
            first = (tool, self._placeholder_args(tool))
            result, stops = self._run(prompt, self._loop_script(prompt, (), 0, first))
        finally:
            if original is None:
                registry.tools.pop(tool, None)
            else:
                registry.tools[tool] = original
        return self._reply(result, stops)

    def run_planned(
        self,
        prompt: str,
        planned_calls: Sequence[Mapping[str, Any]],
        *,
        gap_s: int | None = None,
    ) -> TargetReply:
        # gap_s (WP28): seconds the sandbox clock moves before the run. The default is the
        # two-day case gap; a multi-turn conversation passes a short gap so that the gate's
        # one-hour and one-day aggregate windows see earlier turns of the same conversation.
        script: list[Mapping[str, Any]] = [
            {
                "action": "tool",
                "tool": str(c["tool"]),
                "args": dict(c.get("args") or {}),
                "message": "",
            }
            for c in planned_calls
        ]
        script.append({"action": "final", "tool": "", "args": {}, "message": "done"})
        result, stops = self._run(prompt[:2000], script, max_steps=len(script) + 1, gap_s=gap_s)
        return self._reply(result, stops)

    def decide(self, applicant: Mapping[str, Any]) -> Mapping[str, Any]:
        if "decide" not in self.capabilities:
            raise TargetError(f"agent {self.agent_id} does not make credit decisions")
        verdict = self.responder.decide(applicant)
        apps = self.world.applications
        app_id = applicant.get("application_id")
        if app_id not in apps:
            app_id = next(iter(apps))
        customer_id = apps[app_id].customer_id
        script = [
            {
                "action": "tool",
                "tool": "fetch_application",
                "args": {"application_id": app_id},
                "message": "",
            },
            {
                "action": "tool",
                "tool": "credit_score_lookup",
                "args": {"customer_id": customer_id},
                "message": "",
            },
            {
                "action": "tool",
                "tool": "decide_prequal",
                "args": {
                    "application_id": app_id,
                    "decision": "approve" if verdict["approved"] else "decline",
                    "amount_minor": int(verdict["limit_minor"]),
                    "reason": str(verdict["reason"]),
                },
                "message": "",
            },
            {"action": "final", "tool": "", "args": {}, "message": "done"},
        ]
        self._run("decide", script, max_steps=len(script) + 1)
        return dict(verdict)

    def dependency_files(self) -> list[Path]:
        return _own_dependency_files()

    def model_inventory(self) -> list[ModelDependency]:
        m = self.runtime.manifest
        return [
            ModelDependency(
                role="agent",
                vendor=_vendor(m.model_family),
                family=m.model_family,
                model_id=m.model_id,
                version_pinned=_version_pinned(m.model_id),
                hosting_region=None,
                is_mock=True,
            )
        ]

    def tool_manifest(self) -> Mapping[str, Any]:
        m = self.runtime.manifest
        return {
            "tools": [
                {
                    "name": t.name,
                    "risk_class": t.risk_class,
                    "description": t.description,
                    "args": dict(t.args),
                }
                for t in m.tools
            ],
            "declared_hash": m.tool_manifest_hash(),
            "registered": self.runtime.tools.names(),
            "mcp_servers": [],
        }

    def system_prompt(self) -> str:
        return str(self.runtime.system_prompt)

    def close(self) -> None:
        try:
            self.gateway.drain()
            self.gateway.close()
        finally:
            self._provider.shutdown()
            self._adapters.close()

    def __enter__(self) -> DemoAgentTarget:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# --------------------------------------------------------------------------- repo agent


MANIFEST_NAME = "supervisor.manifest.yaml"
MAX_TOOLS = 100


def read_declared_tools(repo_dir: Path) -> list[dict[str, Any]] | None:
    """Tools declared in ``supervisor.manifest.yaml`` (root or one folder down), under ``agent:``
    or at the top level. ``None`` when there is no such manifest with an ``agent`` section or a
    ``tools`` key; ``[]`` when it declares no tools. Each tool keeps name, risk class, a cut
    description and the argument types (WP-O3b)."""
    import yaml

    try:
        folders = [repo_dir, *sorted(p for p in repo_dir.iterdir() if p.is_dir())]
    except OSError:
        return None
    for folder in folders:
        path = folder / MANIFEST_NAME
        try:
            if not path.is_file() or path.stat().st_size > 256 * 1024:
                continue
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001, S112 - an unreadable manifest is not a manifest
            continue
        if not isinstance(doc, Mapping):
            continue
        agent = doc.get("agent")
        raw = agent.get("tools") if isinstance(agent, Mapping) else None
        if raw is None:
            raw = doc.get("tools")
        if raw is None and not isinstance(agent, Mapping):
            continue
        out: list[dict[str, Any]] = []
        for t in raw if isinstance(raw, list) else []:
            if not isinstance(t, Mapping) or not isinstance(t.get("name"), str):
                continue
            tool: dict[str, Any] = {
                "name": t["name"][:64],
                "risk_class": str(t.get("risk_class") or "")[:32],
                "description": str(t.get("description") or "")[:500],
                "args": dict(t["args"]) if isinstance(t.get("args"), Mapping) else {},
            }
            out.append(tool)
            if len(out) >= MAX_TOOLS:
                break
        return out
    return None


class RepoAgentTarget:
    """An onboarded agent known only by its repository (read offline, nothing runs)."""

    kind: Literal["agent"] = "agent"
    is_mock = False
    tree_target = True  # WP-O3b: only the stored tree is known (no registry, no baseline)

    def __init__(self, agent_id: str, repo_dir: str | Path) -> None:
        self.agent_id = agent_id
        self.target_id = agent_id
        self.repo_dir = Path(repo_dir)
        if not self.repo_dir.is_dir():
            raise TargetError(f"repo folder not found: {self.repo_dir}")
        self._manifest = self._read_manifest()
        self._declared_tools = (
            read_declared_tools(self.repo_dir) if self._manifest is None else None
        )
        caps = set()
        if self.dependency_files():
            caps.add("deps")
        if self._manifest is not None:
            caps |= {"models", "tool_manifest"}
        elif self._declared_tools is not None:
            caps.add("tool_manifest")  # WP-O3b: tools from supervisor.manifest.yaml
        self.capabilities: frozenset[str] = frozenset(caps)

    def _read_manifest(self) -> Any:
        import yaml

        from supervisor_agents.common.manifest import parse_manifest

        candidates = [self.repo_dir / "manifest.yaml"]
        candidates += sorted(
            p / "manifest.yaml"
            for p in self.repo_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
        found = []
        for path in candidates:
            if not path.is_file() or path.stat().st_size > 256 * 1024:
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                found.append(parse_manifest(data))
            except Exception:  # noqa: BLE001, S112 - not an agent manifest, keep looking
                continue
        for m in found:
            if m.id == self.agent_id:
                return m
        return found[0] if len(found) == 1 else None

    def dependency_files(self) -> list[Path]:
        return repo_dependency_files(self.repo_dir)

    def model_inventory(self) -> list[ModelDependency]:
        m = self._manifest
        if m is None:
            return []
        return [
            ModelDependency(
                role="agent",
                vendor=_vendor(m.model_family),
                family=m.model_family,
                model_id=m.model_id,
                version_pinned=_version_pinned(m.model_id),
                hosting_region=None,
                is_mock=False,
            )
        ]

    def tool_manifest(self) -> Mapping[str, Any]:
        m = self._manifest
        if m is None and self._declared_tools is not None:
            # registered is None: a stored tree cannot say which tools are registered at run time
            return {
                "tools": [dict(t) for t in self._declared_tools],
                "declared_hash": "",
                "registered": None,
                "mcp_servers": [],
            }
        if m is None:
            return {"tools": [], "declared_hash": "", "registered": [], "mcp_servers": []}
        return {
            "tools": [
                {
                    "name": t.name,
                    "risk_class": t.risk_class,
                    "description": t.description,
                    "args": dict(t.args),
                }
                for t in m.tools
            ],
            "declared_hash": m.tool_manifest_hash(),
            "registered": [],
            "mcp_servers": [],
        }

    def system_prompt(self) -> str:
        return ""

    def _unsupported(self, what: str) -> TargetError:
        return TargetError(f"repo agent {self.agent_id} cannot {what} (offline repo target)")

    def respond(self, prompt: str, *, context: Sequence[str] = (), sample: int = 0) -> TargetReply:
        raise self._unsupported("answer prompts")

    def run_with_tool_result(
        self, prompt: str, tool: str, injected_result: Mapping[str, Any]
    ) -> TargetReply:
        raise self._unsupported("run tools")

    def run_planned(self, prompt: str, planned_calls: Sequence[Mapping[str, Any]]) -> TargetReply:
        raise self._unsupported("replay planned calls")

    def decide(self, applicant: Mapping[str, Any]) -> Mapping[str, Any]:
        raise self._unsupported("decide")

    def close(self) -> None:
        return None


# --------------------------------------------------------------------------- http target (WP-O3b)

HTTP_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}(\.[A-Za-z_][A-Za-z0-9_]{0,39}){0,3}$")
HTTP_PATH_RE = re.compile(r"^/[A-Za-z0-9._~\-/]{0,120}$")
ANSWER_FALLBACKS = ("answer", "reply", "response", "text", "message", "output", "content")
MAX_REPLY_CHARS = 4000
MAX_REPLY_TOOLS = 20


class TurnLimitError(TargetError):
    """The per-pack turn cap or the total time budget of an HTTP target is used up."""


def _host_allowed(host: str, allowed: Sequence[str]) -> bool:
    host = host.lower().rstrip(".")
    for entry in allowed:
        e = entry.strip().lower().rstrip(".")
        if not e:
            continue
        if e.startswith("*."):
            if host.endswith(e[1:]) and len(host) > len(e) - 1:
                return True
        elif host == e:
            return True
    return False


def split_allowed_hosts(text: str) -> list[str]:
    return [h.strip() for h in str(text or "").split(",") if h.strip()]


def check_http_url(url: str, allowed_hosts: Sequence[str]) -> str:
    """The host of ``url`` when it may be used as a target, else ``TargetError``.

    Rules: https only, no user info, no query, no fragment, port absent or 443, and the host
    is on the allow list (exact name, or ``*.suffix``). An empty allow list allows nothing."""
    from urllib.parse import urlsplit

    if not allowed_hosts:
        raise TargetError("http target refused: PREDEPLOY_HTTP_ALLOWED_HOSTS is empty")
    try:
        parts = urlsplit(str(url).strip())
        port = parts.port
    except ValueError:
        raise TargetError("http target refused: the URL cannot be read") from None
    if parts.scheme != "https":
        raise TargetError("http target refused: the URL must use https")
    if not parts.hostname:
        raise TargetError("http target refused: the URL has no host")
    if parts.username is not None or parts.password is not None:
        raise TargetError("http target refused: the URL must not hold user info")
    if parts.query or parts.fragment:
        raise TargetError("http target refused: the URL must have no query and no fragment")
    if port not in (None, 443):
        raise TargetError("http target refused: only port 443 is allowed")
    host = parts.hostname.lower()
    if not _host_allowed(host, allowed_hosts):
        raise TargetError(
            f"http target refused: host {host} is not in PREDEPLOY_HTTP_ALLOWED_HOSTS"
        )
    return host


@dataclass(frozen=True)
class HttpTargetConfig:
    """Where and how to talk to one candidate. Field names are the candidate's own: the
    kb-chatbot uses ``message_field: question`` and ``history_field: history``.

    * ``message_field``  JSON key that carries the synthetic user turn;
    * ``session_field``  JSON key for a session id (``""`` = not sent);
    * ``history_field``  JSON key for the earlier turns of the same session as a list of
                         ``{"role", "text"}`` (``""`` = not sent);
    * ``answer_field``   dotted path of the answer in the JSON reply (``""`` = try the usual
                         names: answer, reply, response, text, message, output, content)."""

    url: str
    path: str = "/chat"
    message_field: str = "message"
    session_field: str = "session_id"
    history_field: str = ""
    answer_field: str = ""
    tools_field: str = "tool_calls"
    timeout_s: int = 30
    max_turns: int = 50
    budget_s: int = 600

    @property
    def endpoint(self) -> str:
        return self.url.rstrip("/") + self.path


def http_target_config(
    block: Mapping[str, Any],
    *,
    allowed_hosts: Sequence[str],
    max_timeout_s: int = 30,
    max_turns: int = 50,
    max_budget_s: int = 600,
) -> HttpTargetConfig:
    """Validate a candidate's ``http_target`` block. The three limits can be lowered by the
    block, never raised above the server settings. Raises ``TargetError`` (a refusal with a
    reason the report can show)."""
    if not isinstance(block, Mapping):
        raise TargetError("http target refused: http_target must be a mapping")
    known = {
        "url",
        "path",
        "message_field",
        "session_field",
        "history_field",
        "answer_field",
        "tools_field",
        "timeout_s",
        "max_turns",
        "budget_s",
    }
    extra = sorted(str(k) for k in block if k not in known)
    if extra:
        raise TargetError(f"http target refused: unknown key {extra[0][:40]!r}")
    url = str(block.get("url") or "")
    check_http_url(url, allowed_hosts)
    path = str(block.get("path") or "/chat")
    if not HTTP_PATH_RE.match(path) or ".." in path:
        raise TargetError("http target refused: bad path")
    fields: dict[str, str] = {}
    for key, default, allow_empty in (
        ("message_field", "message", False),
        ("session_field", "session_id", True),
        ("history_field", "", True),
        ("answer_field", "", True),
        ("tools_field", "tool_calls", True),
    ):
        val = block.get(key, default)
        val = default if val is None else str(val)
        if val == "" and not allow_empty:
            raise TargetError(f"http target refused: {key} must not be empty")
        if val and not HTTP_FIELD_RE.match(val):
            raise TargetError(f"http target refused: bad {key}")
        fields[key] = val
    nums: dict[str, int] = {}
    for key, cap in (
        ("timeout_s", max_timeout_s),
        ("max_turns", max_turns),
        ("budget_s", max_budget_s),
    ):
        raw = block.get(key, cap)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise TargetError(f"http target refused: {key} must be a positive integer")
        nums[key] = min(raw, cap)
    return HttpTargetConfig(url=url.strip(), path=path, **fields, **nums)


def _norm_digits(text: str) -> str:
    return re.sub(r"\W+", "", text).lower()


HttpTransport = Callable[[str, dict[str, Any], float, Mapping[str, str]], tuple[int, Any]]


def default_http_transport(
    url: str, payload: dict[str, Any], timeout_s: float, headers: Mapping[str, str]
) -> tuple[int, Any]:
    from supervisor.adapters.http_json import post_json_status

    return post_json_status(url, payload, timeout_s, headers=headers)


def service_principal_headers(settings: Settings) -> Callable[[], Mapping[str, str]]:
    """The Supervisor's own OAuth identity: the ``Authorization`` header from the Databricks SDK
    ``Config.authenticate()`` (the same call the chat adapter uses). Nothing is stored; the SDK
    caches and refreshes the token. Built on first use."""
    state: dict[str, Any] = {}

    def headers() -> Mapping[str, str]:
        if "fn" not in state:
            from supervisor.adapters.sql.databricks_rest import make_workspace_client

            state["fn"] = make_workspace_client(settings).config.authenticate
        return dict(state["fn"]())

    return headers


class HttpAgentTarget:
    """A candidate that runs elsewhere, reached through its HTTP chat endpoint (WP-O3b).

    Every turn is synthetic text from a pack. The candidate should be in SHADOW. Replies are
    masked before a pack reads them: a value that the pack itself sent (a planted canary) is
    kept, because the pack checks for it; any other personal-data span is replaced by the
    existing masker. The static packs (pins, licences, models, tool manifest) read the stored
    tree through a ``RepoAgentTarget``.

    Limits: at most ``cfg.max_turns`` turns per pack (``begin_pack`` starts a new count), each
    turn at most ``cfg.timeout_s``, and ``cfg.budget_s`` of wall time for the whole target. When
    one is used up the target raises :class:`TurnLimitError`; the engine records the pack as
    ``error``, never as a pass. The auth header and the URL path never reach a log."""

    kind: Literal["agent"] = "agent"
    is_mock = False
    tree_target = True
    # a chat endpoint can never replay planned calls, inject a tool result or decide credit:
    # the packs that need these are "not applicable" (a question in the pre-deploy report)
    not_applicable_capabilities = frozenset({"planned", "tools", "decide"})

    def __init__(
        self,
        agent_id: str,
        cfg: HttpTargetConfig,
        *,
        allowed_hosts: Sequence[str],
        auth_headers: Callable[[], Mapping[str, str]],
        repo_dir: str | Path | None = None,
        transport: HttpTransport | None = None,
        masker: Any = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        import time

        self.host = check_http_url(cfg.url, allowed_hosts)
        self.cfg = cfg
        self.agent_id = agent_id
        self.target_id = agent_id
        self._auth = auth_headers
        self._transport = transport or default_http_transport
        self._masker = masker
        self._mono = monotonic or time.monotonic
        self._t0 = self._mono()
        self._pack = ""
        self._pack_turns = 0
        self._total_turns = 0
        self._failed_turns = 0
        self._session_n = 0
        self._histories: dict[str, list[dict[str, str]]] = {}
        self._inner = RepoAgentTarget(agent_id, repo_dir) if repo_dir is not None else None
        caps = {"chat", "converse"}
        if self._inner is not None:
            caps |= set(self._inner.capabilities)
        self.capabilities: frozenset[str] = frozenset(caps)

    # -- accounting ------------------------------------------------------------
    def begin_pack(self, pack_id: str) -> None:
        self._pack = pack_id
        self._pack_turns = 0

    @property
    def turns(self) -> int:
        return self._pack_turns

    @property
    def total_turns(self) -> int:
        return self._total_turns

    def turns_left(self) -> int:
        return max(0, self.cfg.max_turns - self._pack_turns)

    def result_details(self) -> dict[str, Any]:
        return {
            "target_kind": "http",
            "target_host": self.host,
            "turns": self._pack_turns,
            "turn_cap": self.cfg.max_turns,
        }

    # -- one turn --------------------------------------------------------------
    def new_session(self) -> str:
        self._session_n += 1
        return f"suppack-{self._pack or 'x'}-{self._session_n}"[:80]

    def _extract(self, data: Any) -> str:
        if not isinstance(data, Mapping):
            raise TargetError("http target: the reply is not a JSON object")
        paths = [self.cfg.answer_field] if self.cfg.answer_field else list(ANSWER_FALLBACKS)
        for dotted in paths:
            cur: Any = data
            for part in dotted.split("."):
                cur = cur.get(part) if isinstance(cur, Mapping) else None
            if isinstance(cur, str):
                return cur
        raise TargetError("http target: the reply has no answer text")

    def _tools(self, data: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw = data.get(self.cfg.tools_field) if self.cfg.tools_field else None
        out: list[dict[str, Any]] = []
        for c in raw if isinstance(raw, list) else []:
            if not isinstance(c, Mapping):
                continue
            name = str(c.get("tool") or c.get("name") or "")[:64]
            if name:  # arguments are dropped: they may hold personal data
                status = str(c.get("status") or c.get("outcome") or "")[:32]
                out.append({"tool": name, "args": {}, "status": status})
            if len(out) >= MAX_REPLY_TOOLS:
                break
        return out

    def _mask(self, text: str, sent: str) -> str:
        """Mask personal data in a reply except values the pack sent itself."""
        text = text[:MAX_REPLY_CHARS]
        masker = self._masker
        if masker is not None:
            finder = getattr(masker, "find", None)
            if callable(finder):
                keep = _norm_digits(sent)
                canon = masker.canonical(text) if hasattr(masker, "canonical") else text
                out: list[str] = []
                pos = 0
                for sp in finder(text):
                    seen = _norm_digits(sp.text)
                    if seen and seen in keep:
                        continue  # a synthetic value that the pack sent: the pack reads it
                    out.append(canon[pos : sp.start])
                    out.append(f"<{sp.type}:{masker.pseudonym(sp.type, sp.text)}>")
                    pos = sp.end
                out.append(canon[pos:])
                text = "".join(out)
            else:
                text = masker.mask(text)
        from supervisor.onboard.scrub import scrub_text

        return scrub_text(text).text

    def send(self, session_id: str, text: str, *, context_sent: str = "") -> TargetReply:
        """One turn in session ``session_id``: the earlier turns of that session go along only
        when ``history_field`` is set. Counts one turn."""
        if self._pack_turns >= self.cfg.max_turns:
            raise TurnLimitError(
                f"http target: turn cap {self.cfg.max_turns} reached for this pack "
                "(PREDEPLOY_HTTP_MAX_TURNS)"
            )
        if self._mono() - self._t0 > self.cfg.budget_s:
            raise TurnLimitError(
                f"http target: total time budget {self.cfg.budget_s} s used up "
                "(PREDEPLOY_HTTP_BUDGET_S)"
            )
        payload: dict[str, Any] = {self.cfg.message_field: text}
        if self.cfg.session_field:
            payload[self.cfg.session_field] = session_id
        hist = self._histories.setdefault(session_id, [])
        if self.cfg.history_field and hist:
            payload[self.cfg.history_field] = [dict(h) for h in hist[-10:]]
        self._pack_turns += 1
        self._total_turns += 1
        try:
            headers = {"Content-Type": "application/json", **dict(self._auth())}
        except Exception as exc:  # noqa: BLE001 - the reason must not carry a token
            raise TargetError(f"http target: no auth header ({type(exc).__name__})") from None
        try:
            status, data = self._transport(
                self.cfg.endpoint, payload, float(self.cfg.timeout_s), headers
            )
        except TimeoutError:
            self._failed_turns += 1
            raise TargetError(
                f"http target: a turn took more than {self.cfg.timeout_s} s"
            ) from None
        except Exception as exc:  # noqa: BLE001 - class name only: no URL, no header
            self._failed_turns += 1
            raise TargetError(f"http target: the call failed ({type(exc).__name__})") from None
        if status in (401, 403):
            raise TargetError(f"http target: the candidate refused our identity (HTTP {status})")
        if not 200 <= status < 300:
            self._failed_turns += 1
            raise TargetError(f"http target: the candidate answered HTTP {status}")
        answer = self._extract(data)
        reply = TargetReply(
            text=self._mask(answer, text + "\n" + context_sent),
            refused=False,
            tool_calls=self._tools(data) if isinstance(data, Mapping) else [],
            gate_would_stop=[],
            trace_id="",
            is_mock=False,
        )
        hist.append({"role": "user", "text": text[:800]})
        hist.append({"role": "assistant", "text": reply.text[:800]})
        return reply

    # -- AgentTarget -----------------------------------------------------------
    def respond(self, prompt: str, *, context: Sequence[str] = (), sample: int = 0) -> TargetReply:
        task = prompt
        sent = ""
        if context:
            block = "\n".join(f"[{i}] {c}" for i, c in enumerate(context, 1))
            task = f"{prompt}\n\n{CONTEXT_OPEN}\n{block}\n{CONTEXT_CLOSE}"
            sent = block
        return self.send(self.new_session(), task, context_sent=sent)

    def _unsupported(self, what: str) -> TargetError:
        return TargetError(f"http target of {self.agent_id} cannot {what} (chat endpoint only)")

    def run_with_tool_result(
        self, prompt: str, tool: str, injected_result: Mapping[str, Any]
    ) -> TargetReply:
        raise self._unsupported("run a tool with an injected result")

    def run_planned(self, prompt: str, planned_calls: Sequence[Mapping[str, Any]]) -> TargetReply:
        raise self._unsupported("replay planned calls")

    def decide(self, applicant: Mapping[str, Any]) -> Mapping[str, Any]:
        raise self._unsupported("decide")

    # -- static facts from the stored tree --------------------------------------
    def dependency_files(self) -> list[Path]:
        return self._inner.dependency_files() if self._inner is not None else []

    def model_inventory(self) -> list[ModelDependency]:
        return self._inner.model_inventory() if self._inner is not None else []

    def tool_manifest(self) -> Mapping[str, Any]:
        if self._inner is not None:
            return self._inner.tool_manifest()
        return {"tools": [], "declared_hash": "", "registered": [], "mcp_servers": []}

    def system_prompt(self) -> str:
        return ""

    def close(self) -> None:
        self._histories.clear()


# --------------------------------------------------------------------------- traces


def _as_dt(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


class StoreTraceTarget:
    """Recorded ``agent_event`` rows of one agent (masked), optionally in a time window."""

    kind: Literal["traces"] = "traces"

    def __init__(
        self,
        tables: Any,
        agent_id: str,
        since: datetime | None = None,
        until: datetime | None = None,
        *,
        is_mock: bool = False,
        closer: Callable[[], None] | None = None,
    ) -> None:
        self._tables = tables
        self.agent_id = agent_id
        self.target_id = agent_id
        self.since = since
        self.until = until
        self.is_mock = is_mock
        self._closer = closer

    def events(self) -> list[Mapping[str, Any]]:
        rows = self._tables.query("agent_event", {"agent_id": self.agent_id}, order_by=["ts"])
        out = []
        for row in rows:
            ts = _as_dt(row.get("ts"))
            if ts is not None:
                if self.since is not None and ts < self.since:
                    continue
                if self.until is not None and ts >= self.until:
                    continue
            out.append(dict(row))
        return out

    def tables(self) -> Any:
        return self._tables

    def close(self) -> None:
        if self._closer is not None:
            closer, self._closer = self._closer, None
            closer()


# --------------------------------------------------------------------------- judge


class _JudgeTargetBase:
    kind: Literal["judge"] = "judge"
    is_mock = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self._service: Any = None
        self._router: Any = None
        self._factory = self._make_factory()
        router = self._router_once()
        self.is_mock = bool(router.is_mock)
        self.target_id = f"judge:{router.t1.model_id}"

    def _make_factory(self) -> Callable[[], Any]:
        raise NotImplementedError

    def router_factory(self) -> Callable[[], Any]:
        """Callable that returns a fresh ``JudgeRouter`` (judge eval harness style)."""
        return self._factory

    def _router_once(self) -> Any:
        if self._router is None:
            self._router = self._factory()
        return self._router

    def _judge_service(self) -> Any:
        if self._service is None:
            from supervisor.judge.masking import IdentityMasker
            from supervisor.judge.service import JudgeService

            s = self.settings
            self._service = JudgeService(
                self._factory(),
                FixedClock(T0),
                masker=IdentityMasker(),  # trace rows are already masked
                t1_threshold_bp=s.judge_t1_threshold_bp,
                t2_threshold_bp=s.judge_t2_threshold_bp,
                disagree_bp=s.judge_disagree_bp,
                k_suspicious=10**9,  # the K-flags protocol is not part of a single score
                timeout_s=float(s.judge_timeout_s),
                max_retries=s.judge_max_retries,
                max_input_chars=s.judge_max_input_chars,
            )
        return self._service

    def score(self, events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        """Judge one trace through the tier-1 path (tier 2 when tier 1 flags it)."""
        outcome = self._judge_service().evaluate_trace(list(events))
        final = outcome.final_bp
        return {
            "score_bp": int(final) if final is not None else 0,
            "label": str(outcome.final_label or ("unavailable" if final is None else "")),
            "tier": 2 if outcome.t2 is not None else 1,
        }

    def model_inventory(self) -> list[ModelDependency]:
        desc = self._router_once().describe()
        out = []
        for key, role in (("t1", "judge_t1"), ("t2", "judge_t2"), ("challenger", "challenger")):
            d = desc.get(key)
            if not d:
                continue
            mid = str(d["model_id"])
            out.append(
                ModelDependency(
                    role=role,
                    vendor=_vendor(str(d["family"])),
                    family=str(d["family"]),
                    model_id=mid,
                    version_pinned=_version_pinned(mid) or bool(d.get("is_mock")),
                    hosting_region=str(d["region"]) if d.get("region") else None,
                    is_mock=bool(d.get("is_mock")),
                )
            )
        return out

    def dependency_files(self) -> list[Path]:
        return _own_dependency_files()

    def close(self) -> None:
        return None


class MockJudgeTarget(_JudgeTargetBase):
    """The deterministic MockJudge (labelled mock). ``gullible`` obeys data instructions."""

    def __init__(self, settings: Settings | None = None, gullible: bool = False) -> None:
        self.gullible = gullible
        super().__init__(settings)

    def _make_factory(self) -> Callable[[], Any]:
        from supervisor.judge.mockjudge import MockJudgeChat
        from supervisor.judge.mrm._common import with_mock_challenger
        from supervisor.judge.router import JudgeRouter

        settings, gullible = self.settings, self.gullible

        def build() -> Any:
            chats = {
                "t1": MockJudgeChat(1, model_id="mock-judge-t1-v1", gullible=gullible),
                "t2": MockJudgeChat(2, model_id="mock-judge-t2-v1", gullible=gullible),
            }
            # A mock target never calls a configured real challenger (D15 review).
            return JudgeRouter.from_settings(settings, chats=with_mock_challenger(settings, chats))

        return build


class SettingsJudgeTarget(_JudgeTargetBase):
    """The judges configured in settings (JUDGE_T1_MODEL, ...); mock when unset.

    ``tier=2`` makes the configured tier-2 model the judge UNDER TEST: the router the packs
    get has the t2 chat model in both slots, so its ``target_id`` is ``judge:<t2 model id>``
    and every score comes from that model. This writes the validation rows that the judge
    enablement gate (``gates.judge_enablement_problems``) wants for the t2 model."""

    def __init__(self, settings: Settings | None = None, tier: int = 1) -> None:
        if tier not in (1, 2):
            raise TargetError(f"judge tier must be 1 or 2, not {tier!r}")
        self.tier = tier
        super().__init__(settings)

    def _make_factory(self) -> Callable[[], Any]:
        from supervisor.judge.router import JudgeModel, JudgeRouter

        settings, tier = self.settings, self.tier
        if tier == 1:
            return lambda: JudgeRouter.from_settings(settings)

        def build_t2() -> Any:
            base = JudgeRouter.from_settings(settings)
            t1 = JudgeModel(1, "primary", base.t2.chat, base.t2.region)
            return JudgeRouter(t1, base.t2, agent_families=base.agent_families)

        return build_t2


# --------------------------------------------------------------------------- spec


def build_targets(
    spec: str,
    settings: Settings,
    work_dir: str | Path,
    *,
    repo: str | Path | None = None,
    judge: str = "mock",
    adapters: Adapters | None = None,
    judge_tier: int = 1,
) -> list[Any]:
    """Targets for a comma separated ``spec``.

    * ``agent:<id>``  demo agent (sandbox), or a ``RepoAgentTarget`` when ``repo`` is set;
    * ``traces:<id>`` ``agent_event`` rows of that agent in the configured store;
    * ``judge``       the mock judge (``judge="settings"``: the configured judges;
                      ``judge_tier=2``: the tier-2 model is the judge under test);
    * ``demo``        the three demo agents, then the traces of each from its own sandbox
                      store (read after the agent packs ran), then the mock judge.

    Raises :class:`TargetError` for an unknown spec. Close the targets (``close()``) when
    done."""
    if judge not in ("mock", "settings"):
        raise TargetError(f"--judge must be mock or settings, not {judge!r}")
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        raise TargetError("empty target spec; use agent:<id>, traces:<id>, judge or demo")

    def make_judge() -> Any:
        if judge == "settings":
            return SettingsJudgeTarget(settings, tier=judge_tier)
        return MockJudgeTarget(settings)

    targets: list[Any] = []
    try:
        for part in parts:
            kind, _, name = part.partition(":")
            if kind == "demo" and not name:
                demos = [DemoAgentTarget(a, work_dir, settings=settings) for a in DEMO_AGENTS]
                targets += demos
                targets += [d.trace_target() for d in demos]
                targets.append(make_judge())
            elif kind == "judge" and not name:
                targets.append(make_judge())
            elif kind == "agent" and name:
                if repo is not None:
                    targets.append(RepoAgentTarget(name, repo))
                elif name in DEMO_AGENTS:
                    targets.append(DemoAgentTarget(name, work_dir, settings=settings))
                else:
                    raise TargetError(
                        f"unknown agent {name!r}; demo agents: {', '.join(DEMO_AGENTS)}; "
                        "for another agent pass --repo PATH"
                    )
            elif kind == "traces" and name:
                if adapters is not None:
                    targets.append(StoreTraceTarget(adapters.tables, name))
                else:
                    own = build_adapters(settings)
                    targets.append(StoreTraceTarget(own.tables, name, closer=own.close))
            else:
                raise TargetError(
                    f"unknown target {part!r}; use agent:<id>, traces:<id>, judge or demo"
                )
    except BaseException:
        for t in targets:
            close = getattr(t, "close", None)
            if close:
                close()
        raise
    return targets


def close_targets(targets: Sequence[Any]) -> None:
    for t in targets:
        close = getattr(t, "close", None)
        if close is not None:
            try:
                close()
            except Exception:  # noqa: BLE001, S110 - best effort cleanup
                pass


__all__ = [
    "DEMO_AGENTS",
    "DemoAgentTarget",
    "HttpAgentTarget",
    "HttpTargetConfig",
    "MockJudgeTarget",
    "RepoAgentTarget",
    "SettingsJudgeTarget",
    "StoreTraceTarget",
    "TargetError",
    "TurnLimitError",
    "build_targets",
    "check_http_url",
    "http_target_config",
    "service_principal_headers",
    "split_allowed_hosts",
    "close_targets",
]
