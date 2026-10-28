"""The guardian definition schema (WP-G1): pydantic, strict, one JSON Schema export.

Every rule names its field in the message ("config.pattern: ..."). The regex checks are the
existing ones of ``custom_rules`` (``supervisor.detectors.dlp_extras``): this module calls them
and does not repeat them. A model-type guardian (classifier, judge prompt) can only log or ask
for approval; only the deterministic types (regex, keyword list, policy) may block or redact.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from supervisor.core.errors import SupervisorError
from supervisor.guardian_factory import caps

_FIELD_MSG = re.compile(r"^(?:Value error, )?([A-Za-z_][A-Za-z0-9_.\[\]]*): (.*)$", re.S)


class GuardianFactoryError(SupervisorError):
    """A refused step. The message starts with a short code (HTTP 400 at the route)."""

    def __init__(self, code: str, text: str, problems: list[dict[str, str]] | None = None) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code
        self.problems = problems or []


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False)


def est_tokens(text: str) -> int:
    """A cheap upper-ish estimate: the larger of the word count and a quarter of the characters."""
    return max(len(text.split()), (len(text) + 3) // 4)


# ------------------------------------------------------------------ config per type
class RegexConfig(_Strict):
    pattern: str
    mask_token: str | None = None
    preserve_length: bool = False

    @model_validator(mode="after")
    def _existing_checks(self) -> RegexConfig:
        from supervisor.detectors.dlp_extras import extras_problems

        rule = {
            "id": "r",
            "kind": "regex",
            "pattern": self.pattern,
            "mask_token": self.mask_token,
            "preserve_length": self.preserve_length,
        }
        bad = [
            p.replace("custom_rules[0].", "config.")
            for p in extras_problems({"custom_rules": [rule]})
        ]
        if bad:
            raise ValueError("\n".join(bad))
        return self


class KeywordConfig(_Strict):
    words: list[str] = Field(default_factory=list)
    mask_token: str | None = None
    preserve_length: bool = False

    @model_validator(mode="after")
    def _words(self) -> KeywordConfig:
        from supervisor.detectors.dlp_extras import extras_problems

        bad: list[str] = []
        if not self.words:
            bad.append("config.words: at least one word")
        if len(self.words) > caps.KEYWORDS_MAX:
            bad.append(f"config.words: more than {caps.KEYWORDS_MAX} entries")
        seen: set[str] = set()
        for i, w in enumerate(self.words[: caps.KEYWORDS_MAX]):
            if not w.strip():
                bad.append(f"config.words[{i}]: is empty")
            elif len(w) > caps.KEYWORD_CHARS:
                bad.append(f"config.words[{i}]: longer than {caps.KEYWORD_CHARS} characters")
            elif any(ord(c) < 32 for c in w):
                bad.append(f"config.words[{i}]: no control characters")
            elif w.casefold() in seen:
                bad.append(f"config.words[{i}]: is listed twice")
            seen.add(w.casefold())
        rule = {
            "id": "k",
            "kind": "keyword",
            "pattern": "x",
            "mask_token": self.mask_token,
            "preserve_length": self.preserve_length,
        }
        bad += [
            p.replace("custom_rules[0].", "config.")
            for p in extras_problems({"custom_rules": [rule]})
        ]
        if bad:
            raise ValueError("\n".join(bad))
        return self


class ClassifierConfig(_Strict):
    model_ref: str
    threshold_bp: int = Field(strict=True, ge=0, le=caps.THRESHOLD_BP_MAX)

    @model_validator(mode="after")
    def _ref(self) -> ClassifierConfig:
        if self.model_ref not in caps.MODEL_REFS:
            raise ValueError(f"config.model_ref: must be one of {', '.join(caps.MODEL_REFS)}")
        return self


class JudgeConfig(_Strict):
    prompt: str
    verdict_labels: list[str]
    fail_labels: list[str]

    @model_validator(mode="after")
    def _checks(self) -> JudgeConfig:
        bad: list[str] = []
        if not self.prompt.strip():
            bad.append("config.prompt: is empty")
        elif est_tokens(self.prompt) > caps.JUDGE_PROMPT_MAX_TOKENS:
            bad.append(f"config.prompt: longer than {caps.JUDGE_PROMPT_MAX_TOKENS} tokens")
        n = len(self.verdict_labels)
        if not caps.VERDICT_LABELS_MIN <= n <= caps.VERDICT_LABELS_MAX:
            bad.append(
                f"config.verdict_labels: {caps.VERDICT_LABELS_MIN} to "
                f"{caps.VERDICT_LABELS_MAX} labels"
            )
        for i, lab in enumerate(self.verdict_labels):
            if not caps.LABEL_RE.match(lab):
                bad.append(f"config.verdict_labels[{i}]: lower case letters, digits and _ (max 32)")
        if len(set(self.verdict_labels)) != n:
            bad.append("config.verdict_labels: a label is listed twice")
        if not self.fail_labels:
            bad.append("config.fail_labels: at least one label")
        for i, lab in enumerate(self.fail_labels):
            if lab not in self.verdict_labels:
                bad.append(f"config.fail_labels[{i}]: not in verdict_labels")
        if bad:
            raise ValueError("\n".join(bad))
        return self


class Condition(_Strict):
    kind: Literal["tool", "argument", "amount", "data_class"]
    op: Literal["eq", "in", "gt", "gte", "lt", "lte", "present"]
    name: str | None = None  # argument name (kind argument) or the argument that holds the amount
    value: Any = None  # a text, a whole number or a list of texts; problems() checks it

    def problems(self, where: str) -> list[str]:
        out: list[str] = []
        if self.kind == "tool":
            if self.op not in ("eq", "in"):
                out.append(f"{where}.op: tool conditions use eq or in")
            if self.name is not None:
                out.append(f"{where}.name: not used for a tool condition")
            out += _text_values(self.value, f"{where}.value")
        elif self.kind == "data_class":
            if self.op not in ("eq", "in"):
                out.append(f"{where}.op: data_class conditions use eq or in")
            vals = [self.value] if isinstance(self.value, str) else self.value
            if not isinstance(vals, list) or not vals:
                out.append(f"{where}.value: a data class or a list of data classes")
            else:
                out += [
                    f"{where}.value: {v!r} is not one of {', '.join(caps.DATA_CLASSES)}"
                    for v in vals
                    if v not in caps.DATA_CLASSES
                ]
        elif self.kind == "argument":
            if not self.name or not caps.ARG_NAME_RE.match(self.name):
                out.append(f"{where}.name: the argument name (letters, digits, _ . -)")
            if self.op == "present":
                if self.value is not None:
                    out.append(f"{where}.value: not used with op present")
            elif self.op not in ("eq", "in"):
                out.append(f"{where}.op: argument conditions use eq, in or present")
            elif isinstance(self.value, int):
                pass
            else:
                out += _text_values(self.value, f"{where}.value")
        else:  # amount
            if not self.name or not caps.ARG_NAME_RE.match(self.name):
                out.append(f"{where}.name: the argument that holds the amount")
            if self.op not in ("eq", "gt", "gte", "lt", "lte"):
                out.append(f"{where}.op: amount conditions use eq, gt, gte, lt or lte")
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, int)
                or not 0 <= self.value <= caps.AMOUNT_MAX
            ):
                out.append(
                    f"{where}.value: a whole number of minor units between 0 and {caps.AMOUNT_MAX}"
                )
        return out


def _text_values(value: Any, where: str) -> list[str]:
    vals = [value] if isinstance(value, str) else value
    if not isinstance(vals, list) or not vals or len(vals) > caps.POLICY_VALUES_MAX:
        return [f"{where}: a text or a list of 1 to {caps.POLICY_VALUES_MAX} texts"]
    return [
        f"{where}: each value is 1 to {caps.POLICY_VALUE_CHARS} characters"
        for v in vals
        if not isinstance(v, str) or not 1 <= len(v) <= caps.POLICY_VALUE_CHARS
    ][:1]


class PolicyRule(_Strict):
    id: str
    when: list[Condition]
    then: Literal["permit", "forbid"]


class PolicyConfig(_Strict):
    rules: list[PolicyRule]
    default: Literal["permit", "forbid"] = "permit"

    @model_validator(mode="after")
    def _checks(self) -> PolicyConfig:
        bad: list[str] = []
        if not self.rules:
            bad.append("config.rules: at least one rule")
        if len(self.rules) > caps.POLICY_RULES_MAX:
            bad.append(f"config.rules: more than {caps.POLICY_RULES_MAX} rules")
        seen: set[str] = set()
        for i, r in enumerate(self.rules[: caps.POLICY_RULES_MAX]):
            where = f"config.rules[{i}]"
            if not caps.RULE_ID_RE.match(r.id):
                bad.append(f"{where}.id: lower case letters, digits and _ (start with a letter)")
            elif r.id in seen:
                bad.append(f"{where}.id: {r.id!r} is used twice")
            seen.add(r.id)
            if not r.when or len(r.when) > caps.POLICY_CONDITIONS_MAX:
                bad.append(f"{where}.when: 1 to {caps.POLICY_CONDITIONS_MAX} conditions")
            for j, c in enumerate(r.when[: caps.POLICY_CONDITIONS_MAX]):
                bad += c.problems(f"{where}.when[{j}]")
        if bad:
            raise ValueError("\n".join(bad))
        return self


CONFIG_MODELS: dict[str, type[_Strict]] = {
    "regex": RegexConfig,
    "keyword_list": KeywordConfig,
    "classifier": ClassifierConfig,
    "judge_prompt": JudgeConfig,
    "policy": PolicyConfig,
}


# ------------------------------------------------------------------ the rest of the record
class Scope(_Strict):
    agents: Any = "*"  # "*" or a list of ids
    tools: Any = "*"
    data_classes: list[str] = Field(default_factory=list)  # empty = every class

    @model_validator(mode="after")
    def _checks(self) -> Scope:
        bad: list[str] = []
        for name in ("agents", "tools"):
            val = getattr(self, name)
            if val == "*":
                continue
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                bad.append(f"scope.{name}: * or a list of ids")
                continue
            if not val:
                bad.append(f"scope.{name}: a list or *")
            if len(val) > caps.SCOPE_MAX:
                bad.append(f"scope.{name}: more than {caps.SCOPE_MAX} entries")
            bad += [
                f"scope.{name}[{i}]: letters, digits, _ . : - (max 64)"
                for i, v in enumerate(val[: caps.SCOPE_MAX])
                if not caps.SCOPE_ITEM_RE.match(v) or v == "*"
            ]
        bad += [
            f"scope.data_classes[{i}]: must be one of {', '.join(caps.DATA_CLASSES)}"
            for i, v in enumerate(self.data_classes)
            if v not in caps.DATA_CLASSES
        ]
        if bad:
            raise ValueError("\n".join(bad))
        return self


class Thresholds(_Strict):
    min_tpr_pct: int = Field(default=caps.DEFAULT_THRESHOLDS["min_tpr_pct"], ge=0, le=100)
    max_fpr_pct: int = Field(default=caps.DEFAULT_THRESHOLDS["max_fpr_pct"], ge=0, le=100)
    max_p95_ms: int = Field(default=caps.DEFAULT_THRESHOLDS["max_p95_ms"], ge=1, le=caps.P95_MS_MAX)


class Approval(_Strict):
    by: str = Field(min_length=1, max_length=caps.USER_MAX)
    group: str = Field(min_length=1, max_length=64)
    at: str


class AllowEntry(_Strict):
    agent_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=200)
    expires: str  # YYYY-MM-DD, required: an allow-list entry always ends


class Lifecycle(_Strict):
    state: Literal["draft", "benchmarked", "shadow", "approved", "live", "retired"] = "draft"
    version: int = Field(default=1, ge=1, le=10_000)
    approvals: list[Approval] = Field(default_factory=list)
    shadow_days: int = Field(default=0, ge=0, le=caps.SHADOW_DAYS_MAX)
    allow_list: list[AllowEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self) -> Lifecycle:
        bad: list[str] = []
        if len(self.approvals) > caps.APPROVALS_MAX:
            bad.append(f"lifecycle.approvals: more than {caps.APPROVALS_MAX} entries")
        if len(self.allow_list) > caps.ALLOW_LIST_MAX:
            bad.append(f"lifecycle.allow_list: more than {caps.ALLOW_LIST_MAX} entries")
        for i, a in enumerate(self.approvals[: caps.APPROVALS_MAX]):
            if not caps.TIMESTAMP_RE.match(a.at):
                bad.append(f"lifecycle.approvals[{i}].at: RFC 3339 UTC, like 2026-10-28T09:00:00Z")
        for i, e in enumerate(self.allow_list[: caps.ALLOW_LIST_MAX]):
            if not caps.DATE_RE.match(e.expires):
                bad.append(f"lifecycle.allow_list[{i}].expires: a date, like 2026-12-31")
                continue
            try:
                dt.date.fromisoformat(e.expires)
            except ValueError:
                bad.append(f"lifecycle.allow_list[{i}].expires: not a real date")
        if bad:
            raise ValueError("\n".join(bad))
        return self


class GuardianDefinition(_Strict):
    id: str
    name: str
    description: str = ""
    owner_group: str
    type: Literal["regex", "keyword_list", "classifier", "judge_prompt", "policy"]
    stage: Literal["preflight", "input", "tool_call", "output"]
    scope: Scope = Field(default_factory=Scope)
    action_on_fail: Literal["block", "redact", "require_approval", "log"]
    sensitivity: int = Field(ge=caps.SENSITIVITY_MIN, le=caps.SENSITIVITY_MAX)
    config: dict[str, Any]
    benchmark_pack: str = ""  # may be empty in draft
    thresholds: Thresholds = Field(default_factory=Thresholds)
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)
    created_by: str = Field(min_length=1, max_length=caps.USER_MAX)
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def _checks(self) -> GuardianDefinition:
        bad: list[str] = []
        if self.id in caps.RESERVED_IDS:
            bad.append(f"id: {self.id!r} is reserved")
        elif not caps.ID_RE.match(self.id):
            bad.append(
                "id: lower case letters, digits and - (start with a letter or digit, max 64)"
            )
        if not 1 <= len(self.name.strip()) <= caps.NAME_MAX:
            bad.append(f"name: 1 to {caps.NAME_MAX} characters")
        if len(self.description) > caps.DESCRIPTION_MAX:
            bad.append(f"description: longer than {caps.DESCRIPTION_MAX} characters")
        if self.owner_group not in owner_groups():
            bad.append(f"owner_group: must be one of {', '.join(owner_groups())}")
        if self.action_on_fail not in caps.ACTIONS_BY_TYPE[self.type]:
            bad.append(
                f"action_on_fail: type {self.type} may only use "
                f"{' or '.join(caps.ACTIONS_BY_TYPE[self.type])} (a model advises; "
                "only a deterministic rule blocks or redacts)"
            )
        if self.benchmark_pack and not caps.BENCH_PACK_RE.match(self.benchmark_pack):
            bad.append("benchmark_pack: lower case letters, digits, _ and - (max 64)")
        for ts in ("created_at", "updated_at"):
            v = getattr(self, ts)
            if v is not None and not caps.TIMESTAMP_RE.match(v):
                bad.append(f"{ts}: RFC 3339 UTC, like 2026-10-28T09:00:00Z")
        try:
            clean = CONFIG_MODELS[self.type].model_validate(self.config)
            self.config = clean.model_dump(mode="json")
        except ValidationError as exc:
            bad += [
                f"config.{m.field}: {m.text}"
                if not m.field.startswith("config")
                else f"{m.field}: {m.text}"
                for m in _flatten(exc)
            ]
        if bad:
            raise ValueError("\n".join(bad))
        return self


# ------------------------------------------------------------------ problems
class Problem:
    __slots__ = ("field", "text")

    def __init__(self, field: str, text: str) -> None:
        self.field = field
        self.text = text

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.text}


def _loc(loc: tuple[Any, ...]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _flatten(exc: ValidationError) -> list[Problem]:
    out: list[Problem] = []
    for err in exc.errors():
        msg = str(err.get("msg", ""))
        loc = _loc(tuple(err.get("loc", ())))
        for line in msg.split("\n"):
            m = _FIELD_MSG.match(line)
            if m and (not loc or err.get("type") == "value_error"):
                out.append(Problem(m.group(1), m.group(2)))
            else:
                text = line[len("Value error, ") :] if line.startswith("Value error, ") else line
                if err.get("type") == "extra_forbidden":
                    text = "unknown field"
                elif err.get("type") == "missing":
                    text = "required"
                out.append(Problem(loc or "definition", text))
    return out


def problems_of(exc: ValidationError) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for p in _flatten(exc):
        if (p.field, p.text) not in seen:
            seen.add((p.field, p.text))
            out.append(p.to_dict())
    return out


def validate_definition(data: Any) -> GuardianDefinition:
    """The definition, or ``GuardianFactoryError`` (code ``invalid_definition``) whose
    ``problems`` list holds {field, message} for each rule that failed."""
    if not isinstance(data, Mapping):
        raise GuardianFactoryError("invalid_definition", "the definition must be a JSON object")
    try:
        return GuardianDefinition.model_validate(dict(data))
    except ValidationError as exc:
        probs = problems_of(exc)
        text = "; ".join(f"{p['field']}: {p['message']}" for p in probs[:6])
        raise GuardianFactoryError("invalid_definition", text, probs) from None


_GROUPS: tuple[str, ...] | None = None


def owner_groups() -> tuple[str, ...]:
    """The group ids of config/factory_groups.yaml (the same groups as the agent factory)."""
    global _GROUPS
    if _GROUPS is None:
        from supervisor.factory.registry import load_groups

        _GROUPS = tuple(g.group_id for g in load_groups().groups)
    return _GROUPS


def json_schema() -> dict[str, Any]:
    """JSON Schema of the definition. ``config`` differs per type: its schemas are under
    ``x-config-by-type``. The per-type rules that JSON Schema cannot say are in docs."""
    schema = GuardianDefinition.model_json_schema()
    schema["title"] = "GuardianDefinition"
    schema["$id"] = f"supervisor/guardian-definition/{caps.SCHEMA_VERSION}"
    schema["x-config-by-type"] = {k: m.model_json_schema() for k, m in CONFIG_MODELS.items()}
    schema["x-actions-by-type"] = {k: list(v) for k, v in caps.ACTIONS_BY_TYPE.items()}
    return schema
