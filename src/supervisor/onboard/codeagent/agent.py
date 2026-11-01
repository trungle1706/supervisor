# ruff: noqa: E501
"""The bounded tool loop.

One run = at most ``max_steps`` model calls. Each call sends the stable brief (system prompt,
known facts, file outline), then the reported-so-far list, the last tool results and feedback,
and gets back ``{"findings": [...], "next": {...}}`` through ``ChatModel.complete_json`` (so it
runs on the local OpenAI-compatible endpoint and on the Databricks ``responses`` shape without a
new client). The loop runs one tool per call on a ``Workspace`` (read-only, in memory).

Budgets stop the loop, they never raise: steps, tokens (estimated as characters / 3.5), seconds,
lines read. Every finding is checked by ``verify.check_claim`` before it counts.

Tool policy (deterministic, in this file, not in the prompt):

* The model may not finish while a code file is unread, once; the controller names the files.
* A tool call identical to the previous one is answered with a hint instead of a repeat.
* Rejected claims come back to the model once, with the real line, so it can quote correctly.
* Repo text reaches the model only inside nonce delimiters; lines that look like injections are
  replaced by a placeholder before the model sees them.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from supervisor.core.ports import ChatModel
from supervisor.onboard.codeagent import prompts, topics
from supervisor.onboard.codeagent.models import Finding, Rejected
from supervisor.onboard.codeagent.verify import check_claim
from supervisor.onboard.codeagent.workspace import ToolError, Workspace, _show
from supervisor.onboard.injection import find_injection
from supervisor.onboard.scrub import scrub_text

log = logging.getLogger("supervisor.onboard.codeagent")

_DELIM = re.compile(r"(<{2,}|>{2,})")
CHARS_PER_TOKEN = 3.5
CODE_SUFFIXES = (".py", ".yaml", ".yml", ".toml", ".json", ".cfg", ".ini", ".sql")


@dataclass
class AgentConfig:
    max_steps: int = 14
    max_tokens: int = 40_000
    max_seconds: int = 900
    max_read_lines: int = 4_000
    prompt_chars: int = 10_500  # whole prompt; 4096-token local models need <= 11 000
    call_timeout_s: float = 400.0
    obs_chars: int = 2_100  # one tool result in the prompt
    max_findings_per_turn: int = 8
    max_findings: int = 120
    exemplar: bool = True
    guided: bool = True  # phase 1: one turn per topic with fixed leads
    free_after_guided_when_all_read: bool = False
    brief_chars: int = 2600
    known_chars: int = 1500


@dataclass
class AgentRun:
    findings: list[Finding] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    steps: int = 0
    llm_calls: int = 0
    tokens: int = 0
    seconds: float = 0.0
    stop_reason: str = "finished"
    tool_calls: Counter[str] = field(default_factory=Counter)
    tool_errors: int = 0
    proposed: int = 0
    dropped_attrs: int = 0
    notes: list[str] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)  # compact, for the eval
    rejected_log: list[dict[str, Any]] = field(
        default_factory=list
    )  # for tuning, not in the report


def est_tokens(*texts: str) -> int:
    return int(sum(len(t) for t in texts) / CHARS_PER_TOKEN) + 1


def _safe(text: str) -> str:
    return _DELIM.sub(lambda m: " ".join(m.group(0)), text)


def wrap(nonce: str, text: str) -> str:
    return f"<<<REPO_DATA nonce={nonce}>>>\n{_safe(text)}\n<<<END_REPO_DATA nonce={nonce}>>>"


def known_lines(known: Sequence[Finding], limit: int = 2200) -> str:
    """Compact KNOWN facts text (one line per finding)."""
    out: list[str] = []
    for f in known:
        ev = f.evidence[0]
        extra = ",".join(f"{k}={v}" for k, v in f.attrs.items() if k not in ("target",))
        out.append(f"{f.kind} {f.name} {ev.ref()} {extra}".strip())
    text = "\n".join(out)
    return text if len(text) <= limit else text[:limit] + "\n[more known facts cut]"


class SourceAnalysisAgent:
    def __init__(
        self,
        chat: ChatModel,
        cfg: AgentConfig | None = None,
        *,
        nonce: str | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.chat = chat
        self.cfg = cfg or AgentConfig()
        self.nonce = nonce or secrets.token_hex(6)
        self._clock = clock
        self._prose: dict[str, set[int]] = {}
        self._known_tools: set[str] = set()

    # ------------------------------------------------------------------ prompt
    def _brief(self, ws: Workspace, known: Sequence[Finding]) -> str:
        outline: list[str] = []
        for f in ws.files:
            if f.endswith(".py"):
                outline.append(ws.ast_outline(f))
                ws.opened.discard(f)  # an outline in the brief is not a read
        files = ", ".join(f"{f}({len(ws.lines[f])})" for f in ws.files)
        body = (
            f"FILES: {files}\n\nOUTLINE:\n" + "\n".join(outline) if outline else f"FILES: {files}"
        )
        if len(body) > self.cfg.brief_chars:
            body = body[: self.cfg.brief_chars] + "\n[outline cut]"
        return (
            wrap(self.nonce, body)
            + "\n\nKNOWN facts from the deterministic scanner (ground truth):\n"
            + (known_lines(known, self.cfg.known_chars) or "(none)")
        )

    def _user(
        self,
        brief: str,
        topic: topics.Topic | None,
        reported: Sequence[str],
        obs: Sequence[tuple[str, str]],
        feedback: Sequence[str],
        unread: Sequence[str],
        left: int,
    ) -> str:
        parts = [brief, topic.card if topic else prompts.CHECKLIST]
        if self.cfg.exemplar and topic and prompts.EXEMPLARS.get(topic.key):
            parts.append(prompts.EXEMPLARS[topic.key])
        parts.append("REPORTED so far: " + (", ".join(reported[-30:]) or "(nothing)"))
        for label, text in obs:
            parts.append(f"TOOL RESULT {label}:\n" + wrap(self.nonce, text[: self.cfg.obs_chars]))
        if feedback:
            parts.append("FEEDBACK on your last claims:\n" + "\n".join(feedback[:4]))
        if unread:
            parts.append("UNREAD code files: " + ", ".join(unread[:8]))
        parts.append(f"Steps left: {left}. Answer with the JSON object.")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ loop
    def run(
        self,
        ws: Workspace,
        known: Sequence[Finding],
        on_step: Callable[[int, int], None] | None = None,
    ) -> AgentRun:
        cfg = self.cfg
        run = AgentRun()
        started = self._clock()
        brief = self._brief(ws, known)
        self._known_tools = {f.name.lower() for f in known if f.kind == "tool"}
        st = _State(
            ws=ws, run=run, reported=[], seen=set(), feedback=[], on_step=on_step, started=started
        )

        def stop_reason() -> str:
            if run.steps >= cfg.max_steps:
                return "max_steps"
            if self._clock() - started > cfg.max_seconds:
                return "max_seconds"
            if run.tokens >= cfg.max_tokens:
                return "max_tokens"
            if ws.lines_read() >= cfg.max_read_lines:
                return "max_read_lines"
            return ""

        # phase 1: one turn per topic, the leads fetched by the fixed policy; one follow-up at most
        for topic in topics.TOPICS if cfg.guided else ():
            if why := stop_reason():
                run.stop_reason = why
                return self._done(run, started)
            text = topic.prefetch(ws, known)
            run.tool_calls[f"policy:{topic.key}"] += 1
            obs = [(topic.label, text)]
            for hop in range(2):
                raw = self._turn(brief, topic, obs, st, set(topic.kinds), unread=[])
                if raw is None:
                    run.stop_reason = "model_error"
                    return self._done(run, started)
                nxt = _next(raw)
                if hop == 1 or nxt[0] == "finish" or stop_reason():
                    break
                obs.append(self._exec(ws, run, nxt))
        # phase 2: free use of the tools for the steps that are left
        code_files = [f for f in ws.files if f.endswith(CODE_SUFFIXES) and f != "requirements.txt"]
        obs2: list[tuple[str, str]] = []
        nudged = False
        last_call = ""
        while True:
            if why := stop_reason():
                run.stop_reason = why
                break
            unread = [f for f in code_files if f not in ws.opened]
            if not unread and cfg.guided and not cfg.free_after_guided_when_all_read:
                run.stop_reason = "finished"
                break
            raw = self._turn(brief, None, obs2[-2:], st, None, unread=unread)
            if raw is None:
                run.stop_reason = "model_error"
                break
            tool, args = _next(raw)
            if tool == "finish":
                if unread and not nudged:
                    nudged = True
                    st.feedback.append("You may not finish yet: read the UNREAD code files first.")
                    continue
                run.stop_reason = "finished"
                break
            key = json.dumps({"tool": tool, **args}, sort_keys=True)
            if key == last_call:
                obs2.append((tool, "same call as before: choose another file, range or tool"))
                continue
            last_call = key
            obs2.append(self._exec(ws, run, (tool, args)))
        return self._done(run, started)

    def _done(self, run: AgentRun, started: float) -> AgentRun:
        run.seconds = self._clock() - started
        return run

    def _exec(
        self, ws: Workspace, run: AgentRun, call: tuple[str, dict[str, Any]]
    ) -> tuple[str, str]:
        tool, args = call
        run.tool_calls[tool] += 1
        try:
            text = ws.call(tool, args)
        except ToolError as exc:
            run.tool_errors += 1
            text = f"error: {exc}"
        label = f"{tool}({', '.join(f'{k}={v}' for k, v in args.items())})"[:100]
        return label, text

    def _turn(
        self,
        brief: str,
        topic: topics.Topic | None,
        obs: Sequence[tuple[str, str]],
        st: _State,
        kinds: set[str] | None,
        unread: Sequence[str],
    ) -> Mapping[str, Any] | None:
        cfg, run = self.cfg, st.run
        system = prompts.SYSTEM_PROMPT
        left = cfg.max_steps - run.steps
        user = self._user(brief, topic, st.reported, obs, st.feedback, unread, left)
        if len(system) + len(user) > cfg.prompt_chars:
            user = self._user(
                brief, topic, st.reported, obs[-1:], st.feedback, unread, left
            ).replace(prompts.EXEMPLARS.get(topic.key if topic else "", "\0"), "")
        if len(system) + len(user) > cfg.prompt_chars:
            user = user[: cfg.prompt_chars - len(system) - 40] + "\n[cut]"
        run.steps += 1
        run.llm_calls += 1
        if st.on_step is not None:
            try:
                st.on_step(run.steps, cfg.max_steps)
            except Exception:  # noqa: BLE001, S110 - progress is a courtesy
                pass
        try:
            raw = self.chat.complete_json(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                prompts.TURN_SCHEMA,
                cfg.call_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - any model failure ends the loop, not the run
            log.warning("code agent: model call failed (%s)", type(exc).__name__)
            run.notes.append(f"model call failed: {type(exc).__name__}")
            run.tokens += est_tokens(system, user)
            return None
        run.tokens += est_tokens(system, user, json.dumps(raw, ensure_ascii=False))
        st.feedback = self._take(raw, st.ws, run, st.reported, st.seen, kinds)
        run.transcript.append(
            {"step": run.steps, "topic": topic.key if topic else "free", "next": _next(raw)[0]}
        )
        return raw

    # ------------------------------------------------------------------ answer
    def _take(
        self,
        raw: Mapping[str, Any],
        ws: Workspace,
        run: AgentRun,
        reported: list[str],
        seen: set[tuple[str, str, str, int]],
        kinds: set[str] | None = None,
    ) -> list[str]:
        """Verify the findings of one turn. Returns feedback lines for the next turn."""
        fb: list[str] = []
        items = raw.get("findings") if isinstance(raw, Mapping) else None
        prose = self._prose
        for item in (items if isinstance(items, list) else [])[: self.cfg.max_findings_per_turn]:
            if not isinstance(item, Mapping):
                continue
            run.proposed += 1
            if len(run.findings) >= self.cfg.max_findings:
                run.rejected.append(
                    Rejected(kind="?", name="", file="", line=0, reason="over_limit")
                )
                continue
            if kinds is not None and str(item.get("kind")) not in kinds:
                run.rejected.append(
                    Rejected(
                        kind=str(item.get("kind"))[:40], name="", file="", line=0, reason="bad_kind"
                    )
                )
                continue
            f, rej, dropped = check_claim(item, ws, prose=prose, known_tools=self._known_tools)
            run.dropped_attrs += dropped
            if f is None:
                assert rej is not None
                run.rejected.append(rej)
                run.rejected_log.append(
                    {
                        "kind": rej.kind,
                        "name": rej.name,
                        "file": rej.file,
                        "line": rej.line,
                        "reason": rej.reason,
                        "quote": str(item.get("quote"))[:70],
                        "line_text": (ws.line(rej.file, rej.line) or "").strip()[:70],
                    }
                )
                fb.append(_feedback(rej, ws))
                continue
            ev = f.evidence[0]
            key = (f.kind, f.name.lower(), ev.file, ev.line)
            if key in seen:
                run.rejected.append(
                    Rejected(
                        kind=f.kind,
                        name=f.name[:120],
                        file=ev.file,
                        line=ev.line,
                        reason="duplicate",
                    )
                )
                continue
            seen.add(key)
            run.findings.append(f)
            reported.append(f"{f.kind}:{f.name}"[:50])
        return fb


@dataclass
class _State:
    ws: Workspace
    run: AgentRun
    reported: list[str]
    seen: set[tuple[str, str, str, int]]
    feedback: list[str]
    on_step: Callable[[int, int], None] | None
    started: float


def _next(raw: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    nxt = raw.get("next") if isinstance(raw, Mapping) else None
    nxt = nxt if isinstance(nxt, Mapping) else {}
    return str(nxt.get("tool") or "finish"), {k: v for k, v in nxt.items() if k != "tool"}


def _feedback(rej: Rejected, ws: Workspace) -> str:
    base = f"rejected {rej.kind} '{scrub_text(rej.name).text[:40]}' at {rej.file}:{rej.line}: {rej.reason}"
    if rej.reason in ("quote_not_on_line", "evidence_is_prose"):
        text = ws.line(rej.file, rej.line)
        if text is not None and not find_injection(text):
            base += f" (that line is: {_show(text.strip())[:110]})"
    return base
