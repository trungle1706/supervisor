"""Instruction linter of the agent factory (WP-F2).

Pure function, no store, no model. Rules (``config/factory_lint.yaml`` holds the phrase list):

* ``tokens``            error when the instructions exceed the platform cap (``caps``); a warning
                        at ``warn_token_percent`` of the cap.
* ``control_chars``     error for control characters other than newline, tab and return.
* ``override``          error for text that tries to override the locked preamble
                        (``caps.OVERRIDE_PATTERNS``).
* ``forbidden_phrase``  error for each phrase of the config list found in the text.
* ``checklist_unreferenced``  warning for each checklist id the text never names. A definition
                        is *lint-ready* (``is_ready``) only when this rule is clean; the gate
                        (WP-F3) asks for it before a test run. A draft may be saved without it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from supervisor.config import REPO_ROOT
from supervisor.core.errors import SupervisorError
from supervisor.factory import caps

LINT_PATH = REPO_ROOT / "config" / "factory_lint.yaml"
_OVERRIDE = re.compile("|".join(caps.OVERRIDE_PATTERNS), re.IGNORECASE)
RULES = ("tokens", "control_chars", "override", "forbidden_phrase", "checklist_unreferenced")


class LintConfigError(SupervisorError):
    """``config/factory_lint.yaml`` is wrong."""


@dataclass(frozen=True)
class LintConfig:
    forbidden_phrases: tuple[str, ...]
    warn_token_percent: int


@dataclass(frozen=True)
class LintIssue:
    rule: str
    severity: str  # error | warn
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "severity": self.severity, "message": self.message}


def _fold(text: str) -> str:
    return " ".join(text.lower().split())


def load_config(path: Path | None = None) -> LintConfig:
    path = path or LINT_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LintConfigError(f"{path.name}: cannot read the file ({type(exc).__name__})") from exc
    if not isinstance(raw, Mapping):
        raise LintConfigError(f"{path.name}: must be an object")
    allowed = {"version", "warn_token_percent", "forbidden_phrases"}
    unknown = sorted(str(k) for k in set(raw) - allowed)
    if unknown:
        raise LintConfigError(f"{path.name}: unknown key: {', '.join(unknown)}")
    if raw.get("version") != 1:
        raise LintConfigError(f"{path.name}: version must be 1")
    pct = raw.get("warn_token_percent")
    if isinstance(pct, bool) or not isinstance(pct, int) or not 1 <= pct <= 100:
        raise LintConfigError(f"{path.name}: warn_token_percent must be an integer 1 to 100")
    phrases = raw.get("forbidden_phrases")
    if not isinstance(phrases, list) or not all(isinstance(p, str) and p.strip() for p in phrases):
        raise LintConfigError(f"{path.name}: forbidden_phrases must be a list of text")
    return LintConfig(tuple(_fold(p) for p in phrases), pct)


def lint(
    instructions: str, checklist_ids: Iterable[str], config: LintConfig | None = None
) -> list[LintIssue]:
    cfg = config or load_config()
    text = instructions or ""
    out: list[LintIssue] = []
    tokens = caps.estimate_tokens(text)
    if tokens > caps.INSTRUCTIONS_MAX_TOKENS:
        out.append(
            LintIssue(
                "tokens",
                "error",
                f"about {tokens} tokens, the cap is {caps.INSTRUCTIONS_MAX_TOKENS}",
            )
        )
    elif tokens * 100 >= caps.INSTRUCTIONS_MAX_TOKENS * cfg.warn_token_percent:
        out.append(
            LintIssue(
                "tokens", "warn", f"about {tokens} of {caps.INSTRUCTIONS_MAX_TOKENS} tokens used"
            )
        )
    if any(ord(c) < 32 and c not in "\n\t\r" for c in text):
        out.append(LintIssue("control_chars", "error", "control characters are not allowed"))
    m = _OVERRIDE.search(text)
    if m:
        out.append(
            LintIssue(
                "override", "error", f"text that overrides the platform preamble ({m.group(0)!r})"
            )
        )
    folded = _fold(text)
    for phrase in cfg.forbidden_phrases:
        if phrase in folded:
            out.append(LintIssue("forbidden_phrase", "error", f"forbidden phrase: {phrase!r}"))
    for cid in checklist_ids:
        if not re.search(rf"(?<![A-Za-z0-9_-]){re.escape(cid)}(?![A-Za-z0-9_-])", text):
            out.append(
                LintIssue("checklist_unreferenced", "warn", f"checklist item {cid} is not named")
            )
    return out


def lint_definition(defn: Mapping[str, Any], config: LintConfig | None = None) -> list[LintIssue]:
    ids = [str(c.get("id")) for c in defn.get("checklist") or [] if isinstance(c, Mapping)]
    return lint(str(defn.get("instructions") or ""), ids, config)


def has_errors(issues: Iterable[LintIssue]) -> bool:
    return any(i.severity == "error" for i in issues)


def is_ready(issues: Iterable[LintIssue]) -> bool:
    """No error and no unreferenced checklist item (the gate asks for this, WP-F3)."""
    return not any(i.severity == "error" or i.rule == "checklist_unreferenced" for i in issues)
