"""Stage 1 Discover: inventory of an agent repository (pure function, no LLM).

Reads the repo through a ``RepoReader`` and the workspace through a ``WorkspaceReader``.
Every text is scrubbed (``Scrubber``) right after it is read, before it is parsed or
stored. Python files are parsed with ``ast`` (never imported or run); YAML with
``yaml.safe_load``. Each finding carries file:line evidence.

Finds: the agent manifest (id, owner, model, tools with risk classes, limits), tool
definitions and registrations, entrypoints, prompts (system text and task prompts),
model endpoints, MCP servers, tables read and written (SQL strings, Spark calls,
workspace lineage), existing tracing, personal-data fields, notes such as "not
enforced" or "not approved", human-approval steps in code, and redacted secrets.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import yaml

from supervisor.adapters.repo.local_git import RepoReadError
from supervisor.core.errors import check_agent_id
from supervisor.core.ports import RepoReader, WorkspaceReader
from supervisor.onboard import codefacts
from supervisor.onboard.injection import WITHHELD, find_injection, neutralize_tree
from supervisor.onboard.models import (
    DataAccess,
    Endpoint,
    Evidence,
    Inventory,
    LimitInfo,
    LlmCallSite,
    NamedRef,
    Note,
    PromptInfo,
    TableRef,
    ToolInfo,
)
from supervisor.onboard.scrub import Scrubber

MANIFEST_NAMES = ("manifest.yaml", "manifest.yml", "agent.yaml", "agent.yml")
# WP-G3: an MLflow agent artifact keeps its tool list in one of these (see onboard/define.py)
ARTIFACT_MANIFEST_NAMES = MANIFEST_NAMES + (
    "tools.json",
    "tools.yaml",
    "tools.yml",
    "tool_manifest.json",
    "tool_manifest.yaml",
    "tool_manifest.yml",
)
EXTRA_FILES = ("MLmodel",)  # extensionless files that Discover reads (WP-G3)
MAX_FILES = 400
RISK_ORDER = {"money": 3, "credit": 2, "pii_export": 1, "read_only": 0}

_DEST_ARGS = (
    "payee_id",
    "to_account",
    "to_account_id",
    "beneficiary",
    "beneficiary_account",
    "destination",
    "iban",
    "to_bank_swift",
    "recipient",
)
_KEY_ARGS = (
    "from_account_id",
    "account_id",
    "customer_id",
    "application_id",
    "loan_id",
    "card_id",
)
_PII_RE = re.compile(
    r"^(customer_id|account_number|account_id|from_account_id|payee_name|full_name|name|"
    r"cccd|national_id|id_number|phone|phone_number|email|address|income|"
    r"monthly_income_minor|dob|date_of_birth|card_last4|card_number|employment|"
    r"to_account|text)$"
)
_MODEL_RE = re.compile(
    r"^(qwen|llama|gpt-|o[134]-|claude|mistral|mixtral|gemma|phi-|deepseek|"
    r"databricks-|meta-llama)[\w.:/-]*$",
    re.IGNORECASE,
)
_SQL_READ = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.`]*)", re.IGNORECASE)
_SQL_WRITE = re.compile(
    r"\b(?:INSERT\s+INTO|MERGE\s+INTO|UPDATE|CREATE\s+(?:OR\s+REPLACE\s+)?TABLE"
    r"(?:\s+IF\s+NOT\s+EXISTS)?|DELETE\s+FROM)\s+([A-Za-z_][\w.`]*)",
    re.IGNORECASE,
)
_SQL_HINT = re.compile(r"\b(SELECT|INSERT|MERGE|UPDATE|CREATE|DELETE)\b", re.IGNORECASE)
_NOTE_RULES: tuple[tuple[str, str], ...] = (
    ("not_enforced", r"(?i)\b(not|never|n't)\s+(be\s+)?enforc|does not enforce|no limit check"),
    ("not_enforced", r"(?i)only the gateway|belongs to the gateway|left to the gateway"),
    ("not_approved", r"(?i)not approved|operations staff only|ops only|internal use only"),
    ("human_step", r"(?i)human (underwriter|officer|approver|review)|stays with a human"),
    ("todo", r"\b(TODO|FIXME|HACK|XXX)\b"),
)
_HUMAN_APPROVAL_IDENT = re.compile(
    r"(?i)^(request|await|require|get|wait_for)_(human_|officer_|maker_checker_|four_eyes_)?"
    r"(approval|sign_?off)$|maker_checker|four_eyes|human_approval|officer_approval"
)
_RISK_HEURISTIC: tuple[tuple[str, str], ...] = (
    # WP16: credit changes first ("record_payment_plan" changes credit terms, it pays nothing)
    (
        "credit",
        r"payment_plan|restructur|reschedul|preapprov|decision|underwrit|score_override|"
        r"phe_duyet|han_muc|ke_hoach_tra_no|co_cau_no|gia_han_no|"
        r"(raise|set|increase|change|update)_\w*limit",
    ),
    ("pii_export", r"add_payee|save_payee|luu_nguoi_thu_huong"),
    (
        "money",
        r"transfer|pay|refund|waive|disburse|withdraw|deposit|remit|dispute|charge|"
        r"chuyen_tien|chuyen_khoan|thanh_toan|chi_tra|giai_ngan|hoan_tien|hoan_phi|ung_luong|"
        r"tam_ung|advance|nap_tien|nap_tiet_kiem|gui_tiet_kiem|top_up|topup",
    ),
    ("credit", r"decide|approve|credit|loan|limit|underwrit|score_override"),
    ("pii_export", r"export|fetch_application|add_payee|customer_data|dump|download"),
)
# WP16: a tool whose name starts with a read verb only reads (checked before the table).
_READ_VERB = re.compile(
    r"(?i)^(get|list|lookup|look_up|read|fetch|search|find|check|show|view|query|describe|"
    r"calc|calculate|compute|estimate|quote|explain|summari[sz]e|tra_cuu|xem|kiem_tra|tinh|"
    r"doc|lay|liet_ke|tim)(_|$)"
)
# WP16: destination argument names beyond the fixed list (money moves to a chosen account).
_DEST_RE = re.compile(
    r"(?i)(payee|beneficiary|biller|recipient|destination|to_acc|tai_khoan_nhan|nguoi_nhan|"
    r"thu_huong|so_tai_khoan|iban|swift)"
)
_NOT_ARGS = {"self", "cls", "args", "kwargs", "state", "config", "run_manager", "ctx", "context"}


@dataclass
class SourceIndex:
    """Scrubbed text of every scanned file (kept in memory to verify evidence)."""

    lines: dict[str, list[str]] = field(default_factory=dict)

    def evidence(self, file: str, line: int) -> Evidence:
        rows = self.lines.get(file, [])
        text = rows[line - 1] if 0 < line <= len(rows) else ""
        return Evidence.at(file, max(line, 1), text)

    def find(self, file: str, pattern: str, start: int = 1, stop: int | None = None) -> int | None:
        rx = re.compile(pattern)
        rows = self.lines.get(file, [])
        for i in range(max(start, 1), min(stop or len(rows), len(rows)) + 1):
            if rx.search(rows[i - 1]):
                return i
        return None

    def verify(self, ev: Evidence) -> bool:
        rows = self.lines.get(ev.file)
        if not rows or ev.line > len(rows):
            return False
        if ev.quote == WITHHELD:  # injection text is withheld; the line must still be flagged
            return find_injection(rows[ev.line - 1]) is not None
        return ev.quote.strip() != "" and ev.quote.strip() in rows[ev.line - 1]


@dataclass
class Discovery:
    inventory: Inventory
    index: SourceIndex


def discover(
    repo: RepoReader,
    *,
    scrubber: Scrubber | None = None,
    workspace: WorkspaceReader | None = None,
    agent_id: str | None = None,
    revision: str | None = None,
    max_files: int = MAX_FILES,
    manifest_names: Sequence[str] = MANIFEST_NAMES,
) -> Discovery:
    """Build the inventory. ``agent_id`` overrides the id from the manifest or folder."""
    scrubber = scrubber or Scrubber()
    index = SourceIndex()
    skipped: dict[str, str] = {}
    files = [f for f in repo.list_files("**/*") if _interesting(f)][:max_files]
    for f in files:
        try:
            raw = repo.read_text(f)
        except RepoReadError as exc:
            skipped[f] = type(exc).__name__
            continue
        index.lines[f] = scrubber.scrub(raw, source=f).splitlines()
    skipped.update(getattr(repo, "skipped", {}) or {})

    st = _State(index=index)
    manifest_file = next(
        (
            f
            for f in sorted(index.lines, key=lambda p: (p.count("/"), p))
            if _is_manifest(f, manifest_names)
        ),
        None,
    )
    manifest: dict[str, Any] = {}
    if manifest_file:
        manifest = _parse_manifest(manifest_file, index, st)
    for f in sorted(index.lines):
        if f.endswith(".py"):
            _scan_python(f, index, st)
        elif f.endswith((".json", ".yaml", ".yml", ".toml")) and f != manifest_file:
            _scan_config(f, index, st)
        _scan_notes(f, index, st)
    injection_refs: list[Evidence] = []
    for f, rows in index.lines.items():
        for i, line in enumerate(rows, start=1):
            if "[REDACTED:" in line:
                st.secret_refs.append(index.evidence(f, i))
            if find_injection(line):
                injection_refs.append(index.evidence(f, i))
    facts = codefacts.analyse(index.lines)
    _add_code_tools(facts, index, st)
    for ep in facts.entrypoints:  # WP1b-B: routes are entrypoints, not tools
        st.entrypoints.append(
            NamedRef(
                name=ep.name, detail=f"route:{ep.func}", evidence=index.evidence(ep.file, ep.line)
            )
        )

    folder_id = _folder_id(repo)
    aid = check_agent_id(agent_id or str(manifest.get("id") or folder_id or "agent"))
    tools = _merge_tools(manifest_file, manifest, st, index)
    _side_effects(tools, facts)
    _money_by_shape(tools)
    limits = _limits(manifest_file, manifest, tools, st, index)
    _link_limits_in_code(limits, index)
    if workspace is not None:
        _scan_workspace(workspace, aid, scrubber, st, str(manifest.get("model_id") or ""))
    model_family, model_id, model_source = _model_identity(manifest, facts)
    inv = Inventory(
        agent_id=aid,
        name=str(manifest.get("name") or aid),
        version=str(manifest.get("version") or "0.0.0"),
        owner_team=str(manifest.get("owner") or "FILL-ME-owner-team"),
        owner_user=str(manifest.get("owner_user") or "FILL-ME-owner-user"),
        description=" ".join(str(manifest.get("description") or "").split())[:1000],
        declared_risk_tier=manifest.get("risk_tier")
        if manifest.get("risk_tier") in ("low", "medium", "high", "critical")
        else None,
        model_family=model_family,
        model_id=model_id,
        model_family_source=model_source,
        host_type=str(manifest.get("host_type") or "python"),
        plug_point=str(manifest.get("plug_point") or "gate_hook"),
        manifest_file=manifest_file,
        revision=revision,
        files=sorted(index.lines),
        entrypoints=st.entrypoints,
        tools=tools,
        prompts=st.prompts,
        model_endpoints=_dedupe(st.endpoints, lambda e: (e.name, e.source)),
        mcp_servers=st.mcp,
        tables=_dedupe(st.tables, lambda t: (t.name, t.direction)),
        traces=_dedupe(st.traces, lambda t: (t.name, t.detail)),
        limits=limits,
        notes=st.notes,
        constants=st.constants,
        pii_fields=dict(sorted(st.pii.items())),
        human_approval_refs=st.human_refs,
        secret_refs=st.secret_refs,
        skipped=dict(sorted(skipped.items())),
        scrub=scrubber.summary(),
        apps=st.apps,
        framework=facts.framework,
        framework_evidence=_fact_ev(index, facts.framework_evidence),
        llm_calls=[
            LlmCallSite(
                provider=c.provider,
                family=c.family,
                model=c.model,
                via=c.via,
                evidence=index.evidence(c.file, c.line),
            )
            for c in facts.llm_calls
        ],
        data_access=[
            DataAccess(
                kind=d.kind,  # type: ignore[arg-type]
                direction=d.direction,  # type: ignore[arg-type]
                target=d.target[:200] if d.target else None,
                evidence=index.evidence(d.file, d.line),
            )
            for d in facts.data_access
        ],
        tracing=sorted(facts.tracing),
        pii_identifiers={k: index.evidence(v.file, v.line) for k, v in sorted(facts.pii.items())},
        injection_refs=injection_refs,
        dynamic_tool_sources=[index.evidence(d.file, d.line) for d in facts.dynamic_tools],
    )
    inv.features = features_of(inv)
    # Repo text that looks like a prompt injection never reaches an artefact (ADR D12).
    inv = Inventory.model_validate(neutralize_tree(inv.model_dump()))
    return Discovery(inv, index)


def _model_identity(
    manifest: Mapping[str, Any], facts: codefacts.CodeFacts
) -> tuple[str, str | None, str]:
    """(family, model id, source). The manifest wins; otherwise the most common known family
    among the model call sites that name a model (endpoint names and ids go through the same
    alias table as the judge router)."""
    m_family = str(manifest.get("model_family") or "")
    m_id = str(manifest["model_id"]) if manifest.get("model_id") else None
    if m_family and m_family != "unknown":
        return m_family, m_id, "manifest"
    if m_id and codefacts.model_family(m_id) != "unknown":
        return codefacts.model_family(m_id), m_id, "manifest"
    known = [c for c in facts.llm_calls if c.model and c.family != "unknown"]
    if known:
        counts = Counter(c.family for c in known)
        fam = sorted(counts, key=lambda k: (-counts[k], k))[0]
        mid = next(c.model for c in known if c.family == fam)
        return fam, m_id or mid, "code"
    return m_family or "unknown", m_id, "unknown"


_AMOUNT_RE = re.compile(r"(?i)(^amount|_minor$|_vnd$|^so_tien|^so_tien_|amount$)")


def _money_by_shape(tools: Sequence[ToolInfo]) -> None:
    """WP16: a heuristic tool that writes and takes an amount and a destination account
    moves money, whatever its name says (names are often Vietnamese or vague)."""
    for t in tools:
        if t.risk_source != "heuristic" or t.risk_class != "read_only" or not t.side_effects:
            continue
        amount = next((a for a in sorted(t.args) if _AMOUNT_RE.search(a)), None)
        dest = next((a for a in sorted(t.args) if _DEST_RE.search(a)), None)
        if amount and dest and dest != "so_tai_khoan":
            t.risk_class = "money"
            t.destination_arg = dest
            t.amount_arg = t.amount_arg or amount


def _fact_ev(index: SourceIndex, fact: codefacts.Fact | None) -> Evidence | None:
    return index.evidence(fact.file, fact.line) if fact is not None else None


def _def_nodes(tree: ast.Module | None) -> dict[int, ast.AST]:
    out: dict[int, ast.AST] = {}
    for node in ast.walk(tree) if tree is not None else ():
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out.setdefault(node.lineno, node)
    return out


def _model_fields(*trees: ast.Module | None) -> dict[str, set[str]]:
    """Annotated fields of classes (pydantic models, dataclasses): name -> field names."""
    out: dict[str, set[str]] = {}
    for tree in trees:
        for node in ast.walk(tree) if tree is not None else ():
            if isinstance(node, ast.ClassDef):
                names = {
                    s.target.id
                    for s in node.body
                    if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
                }
                if names:
                    out.setdefault(node.name, names)
    return out


def _params(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, models: Mapping[str, set[str]] | None = None
) -> set[str]:
    """Parameter names; a parameter typed with a request model gives the model's fields."""
    a = fn.args
    out: set[str] = set()
    for x in a.posonlyargs + a.args + a.kwonlyargs:
        if x.arg in _NOT_ARGS:
            continue
        ann = x.annotation.id if isinstance(x.annotation, ast.Name) else None
        if models and ann in models:
            out |= models[ann]
        else:
            out.add(x.arg)
    return out


def _add_code_tools(facts: codefacts.CodeFacts, index: SourceIndex, st: _State) -> None:
    """WP16: tools that the base scan misses (decorators with explicit names, tool objects,
    tool classes, schema + dispatch, registries, config-enabled plugins, tool lists)."""
    models = _model_fields(*facts.trees.values())
    for tf in facts.tools:
        if tf.name in st.code_tools:
            if tf.func and tf.func in models:
                continue
            fn = _def_nodes(facts.trees.get(tf.file)).get(tf.line)
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                st.code_tools[tf.name].setdefault("args", set())
                st.code_tools[tf.name]["args"] |= _params(fn, models)
            continue
        if tf.func and tf.func != tf.name and tf.func in st.code_tools and tf.how == "decorator":
            st.code_tools[tf.name] = st.code_tools.pop(tf.func)
            continue
        node = _def_nodes(facts.trees.get(tf.file)).get(tf.line)
        info: dict[str, Any] = {
            "evidence": index.evidence(tf.file, tf.line),
            "returns": set(),
            "mutates": set(),
            "args": set(),
        }
        if isinstance(node, ast.ClassDef):
            node = next(
                (
                    b
                    for b in node.body
                    if isinstance(b, ast.FunctionDef | ast.AsyncFunctionDef)
                    and b.name in ("_run", "run", "_arun", "__call__")
                ),
                None,
            )
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            info["args"] = _params(node, models) | _subscript_keys(node)
            _body_facts(node, info)
        st.code_tools[tf.name] = info


def _body_facts(fn: ast.AST, info: dict[str, Any]) -> None:
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
            for k in sub.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    info["returns"].add(k.value)
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in ("append", "extend", "insert")
            and isinstance(sub.func.value, ast.Attribute)
        ):
            info["mutates"].add(sub.func.value.attr)


def _side_effects(tools: Sequence[ToolInfo], facts: codefacts.CodeFacts) -> None:
    """WP16: writes (db, http, bank API, file) inside a tool's body or in a repo function
    it calls (two levels)."""
    spans: dict[str, tuple[str, int, int]] = {}
    for file, tree in facts.trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                spans.setdefault(node.name, (file, node.lineno, node.end_lineno or node.lineno))
    writes = [d for d in facts.data_access if d.direction == "write"]

    def effects(file: str, start: int, end: int, depth: int) -> set[str]:
        out = {f"{d.kind} write" for d in writes if d.file == file and start <= d.line <= end}
        if depth > 0:
            node = _def_nodes(facts.trees.get(file)).get(start)
            for sub in ast.walk(node) if node is not None else ():
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    target = spans.get(sub.func.id)
                    if target and target[1] != start:
                        out |= effects(*target, depth - 1)
        return out

    for t in tools:
        ev = t.definition
        if ev is None:
            continue
        node = _def_nodes(facts.trees.get(ev.file)).get(ev.line)
        if node is None:
            continue
        end = getattr(node, "end_lineno", None) or ev.line
        t.side_effects = sorted(effects(ev.file, ev.line, end, 2))


# --------------------------------------------------------------------------- state


@dataclass
class _State:
    index: SourceIndex
    entrypoints: list[NamedRef] = field(default_factory=list)
    prompts: list[PromptInfo] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    mcp: list[NamedRef] = field(default_factory=list)
    tables: list[TableRef] = field(default_factory=list)
    traces: list[NamedRef] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    constants: dict[str, list[str]] = field(default_factory=dict)
    pii: dict[str, Evidence] = field(default_factory=dict)
    human_refs: list[Evidence] = field(default_factory=list)
    secret_refs: list[Evidence] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)
    code_tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    manifest_tool_lines: dict[str, tuple[int, int]] = field(default_factory=dict)


def _interesting(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in EXTRA_FILES or path.endswith(
        (".py", ".yaml", ".yml", ".json", ".toml", ".md", ".txt", ".sql")
        + (".ini", ".cfg", ".env.example")  # WP16: config files often hold secrets
    )


def _is_manifest(path: str, names: Sequence[str] = MANIFEST_NAMES) -> bool:
    return path.rsplit("/", 1)[-1] in names


def _folder_id(repo: RepoReader) -> str | None:
    root = getattr(repo, "root", None)
    if root is None:
        return None
    name = re.sub(r"[^A-Za-z0-9_.:-]", "_", str(getattr(root, "name", "")))
    return name or None


def _dedupe(items: Iterable[Any], key: Callable[[Any], Any]) -> list[Any]:
    seen: set[Any] = set()
    out = []
    for it in items:
        k = key(it)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- manifest


def _parse_manifest(file: str, index: SourceIndex, st: _State) -> dict[str, Any]:
    text = "\n".join(index.lines[file])
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    data = _normalise_tool_manifest(data)
    if not isinstance(data, Mapping):
        return {}
    rows = index.lines[file]
    # Tool blocks: "- name: <tool>" (or a JSON "name": "<tool>" line) up to the next one (line
    # ranges for evidence).
    starts = [
        (i, m.group(1) or m.group(2))
        for i, line in enumerate(rows, start=1)
        if (
            m := re.match(
                r"^\s*-\s*name:\s*['\"]?([\w.-]+)|^\s*\"name\"\s*:\s*\"([\w.-]+)\"",
                line,
            )
        )
    ]
    for n, (line, name) in enumerate(starts):
        end = starts[n + 1][0] - 1 if n + 1 < len(starts) else len(rows)
        st.manifest_tool_lines[name] = (line, end)
    desc_line = index.find(file, r"^description:")
    if desc_line:
        nxt = desc_line + 1 if rows[desc_line - 1].rstrip().endswith((">", "|")) else desc_line
        text_desc = " ".join(str(data.get("description") or "").split())
        if text_desc:
            st.prompts.append(
                PromptInfo(
                    kind="system",
                    excerpt=text_desc[:240],
                    sha256=_sha(text_desc),
                    evidence=index.evidence(file, min(nxt, len(rows))),
                )
            )
    model_line = index.find(file, r"^model_id:")
    if data.get("model_id") and model_line:
        st.endpoints.append(
            Endpoint(
                name=str(data["model_id"]),
                family=str(data.get("model_family") or "") or None,
                source="manifest",
                evidence=index.evidence(file, model_line),
            )
        )
    capture_line = index.find(file, r"^capture:")
    if capture_line:
        st.traces.append(
            NamedRef(
                name="capture",
                detail=f"capture level {(data.get('capture') or {}).get('level', '?')}",
                source="manifest",
                evidence=index.evidence(file, capture_line),
            )
        )
    for key in ("mcp_servers", "mcp"):
        for server in data.get(key) or []:
            line = index.find(file, rf"^{key}:") or 1
            st.mcp.append(
                NamedRef(name=str(server), source="manifest", evidence=index.evidence(file, line))
            )
    return dict(data)


def _normalise_tool_manifest(data: Any) -> Any:
    """WP-G3. A bare list of tools, or a list in the function-calling shape
    (``{"type": "function", "function": {"name", "description", "parameters"}}``), becomes
    ``{"tools": [{"name", "description", "args"}]}``. A mapping is returned unchanged."""
    if isinstance(data, list):
        data = {"tools": data}
    if not isinstance(data, Mapping) or not isinstance(data.get("tools"), list):
        return data
    tools = []
    for t in data["tools"]:
        if isinstance(t, Mapping) and isinstance(t.get("function"), Mapping):
            fn = t["function"]
            props = (fn.get("parameters") or {}).get("properties") or {}
            tools.append(
                {
                    "name": fn.get("name"),
                    "description": fn.get("description"),
                    "risk_class": t.get("risk_class") or fn.get("risk_class"),
                    "args": {
                        str(k): str((v or {}).get("type", "unknown"))
                        if isinstance(v, Mapping)
                        else "unknown"
                        for k, v in props.items()
                    },
                }
            )
        else:
            tools.append(t)
    return {**data, "tools": tools}


def _merge_tools(
    manifest_file: str | None,
    manifest: Mapping[str, Any],
    st: _State,
    index: SourceIndex,
) -> list[ToolInfo]:
    tools: dict[str, ToolInfo] = {}
    for t in manifest.get("tools") or []:
        if not isinstance(t, Mapping) or not t.get("name"):
            continue
        name = str(t["name"])
        rc = str(t.get("risk_class") or "")
        from_manifest = rc in RISK_ORDER
        desc = " ".join(str(t.get("description") or "").split())[:400]
        args = {str(k): str(v) for k, v in (t.get("args") or {}).items()}
        start, end = st.manifest_tool_lines.get(name, (1, 1))
        entry = index.evidence(manifest_file, start) if manifest_file else None
        approved, note, appr_ev = True, None, None
        if manifest_file:
            hit = index.find(manifest_file, _NOTE_RULES[2][1], start, end)
            if hit:
                approved = False
                note = "manifest says the tool is not approved for this agent's flows"
                appr_ev = index.evidence(manifest_file, hit)
        tools[name] = ToolInfo(
            name=name,
            risk_class=rc if from_manifest else _guess_risk(name),  # type: ignore[arg-type]
            risk_source="manifest" if from_manifest else "heuristic",
            description=desc,
            args=args,
            approved=approved,
            approval_note=note,
            manifest_entry=entry,
            approval_evidence=appr_ev,
        )
    for name, info in st.code_tools.items():
        t = tools.get(name)
        if t is None:
            t = ToolInfo(
                name=name,
                risk_class=_guess_risk(name),  # type: ignore[arg-type]
                risk_source="heuristic",
                args={a: "unknown" for a in info["args"]},
            )
            tools[name] = t
        t.definition = info["evidence"]
        t.returns_fields = sorted(info["returns"])
        t.mutates = sorted(info["mutates"])
        for a in info["args"]:
            t.args.setdefault(a, "unknown")
    for t in tools.values():
        t.amount_arg = next((a for a in sorted(t.args) if a.endswith("_minor")), None)
        t.destination_arg = next((a for a in _DEST_ARGS if a in t.args), None)
        if t.destination_arg is None and t.risk_class == "money":
            t.destination_arg = next(
                (a for a in sorted(t.args) if _DEST_RE.search(a) and not a.endswith("_name")),
                None,
            )
        t.key_args = [a for a in _KEY_ARGS if a in t.args]
        for a in t.args:
            if _PII_RE.match(a) and a not in st.pii:
                ev = t.manifest_entry or t.definition
                if ev is not None:
                    st.pii[a] = ev
        for f in t.returns_fields:
            if _PII_RE.match(f) and f not in st.pii and t.definition is not None:
                st.pii[f] = t.definition
    return [tools[k] for k in sorted(tools)]


def _guess_risk(name: str) -> str:
    if _READ_VERB.match(name):
        return "read_only"
    for rc, pattern in _RISK_HEURISTIC:
        if re.search(pattern, name, re.IGNORECASE):
            return rc
    return "read_only"


def _limits(
    manifest_file: str | None,
    manifest: Mapping[str, Any],
    tools: Sequence[ToolInfo],
    st: _State,
    index: SourceIndex,
) -> list[LimitInfo]:
    out: list[LimitInfo] = []
    names = [t.name for t in tools]
    for key, value in (manifest.get("limits") or {}).items():
        if type(value) is not int or not manifest_file:
            continue
        k = str(key)
        daily = "daily" in k or "per_day" in k
        words = [
            w
            for w in re.sub(r"_minor$", "", k).split("_")
            if w not in {"daily", "max", "amount", "limit", "per", "day", "total", "minor"}
        ]
        stem = "_".join(words)
        tool = stem if stem in names else None
        if tool is None and words:
            cands = [n for n in names if all(w in n for w in words)]
            tool = min(cands, key=len) if cands else None
        line = index.find(manifest_file, rf"^\s+{re.escape(k)}\s*:") or 1
        out.append(
            LimitInfo(
                key=k,
                value=value,
                tool=tool,
                period="daily" if daily else "per_call",
                evidence=index.evidence(manifest_file, line),
            )
        )
    return out


def _link_limits_in_code(limits: Sequence[LimitInfo], index: SourceIndex) -> None:
    for lim in limits:
        for f, rows in index.lines.items():
            if not f.endswith(".py"):
                continue
            for i, line in enumerate(rows, start=1):
                if lim.key in line:
                    lim.code_refs.append(Evidence.at(f, i, line))


# --------------------------------------------------------------------------- python


def _scan_python(file: str, index: SourceIndex, st: _State) -> None:
    text = "\n".join(index.lines[file])
    try:
        tree = ast.parse(text, filename=file)
    except SyntaxError:
        st.notes.append(
            Note(
                text="file does not parse (after secret scrubbing); scanned as text only",
                kind="other",
                evidence=index.evidence(file, 1),
            )
        )
        return
    defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            defs.setdefault(node.name, node)
    models = _model_fields(tree)
    registered: dict[str, int] = {}
    for node in ast.walk(tree):
        # reg.register("name", fn) / reg.register(fn.__name__, fn)
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple | ast.List):
            body_calls = [
                c
                for b in node.body
                for c in ast.walk(b)
                if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute)
                and c.func.attr in ("register", "add_tool")
            ]
            if body_calls:
                for elt in node.iter.elts:
                    if isinstance(elt, ast.Name):
                        registered.setdefault(elt.id, elt.lineno)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("register", "add_tool") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    registered.setdefault(first.value, node.lineno)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for dec in node.decorator_list:
                dname = _call_name(dec)
                if dname in ("tool", "function_tool", "supervised_tool") or dname.endswith(".tool"):
                    registered.setdefault(node.name, node.lineno)
    for name, line in registered.items():
        fn = defs.get(name)
        line_no = fn.lineno if fn is not None else line
        info = st.code_tools.setdefault(
            name,
            {"evidence": index.evidence(file, line_no), "returns": set(), "mutates": set()},
        )
        info.setdefault("args", set())
        if fn is not None:
            info["args"] |= _subscript_keys(fn) | _params(fn, models)
            for sub in ast.walk(fn):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    for k in sub.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            info["returns"].add(k.value)
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in ("append", "extend", "insert")
                    and isinstance(sub.func.value, ast.Attribute)
                ):
                    info["mutates"].add(sub.func.value.attr)
    for name, fn in defs.items():
        if name in ("build_agent", "main", "create_app", "make_agent", "run_agent"):
            st.entrypoints.append(
                NamedRef(name=name, detail="function", evidence=index.evidence(file, fn.lineno))
            )
        if _HUMAN_APPROVAL_IDENT.search(name):
            st.human_refs.append(index.evidence(file, fn.lineno))
    for node in ast.walk(tree):
        _scan_node(file, node, index, st)
        # WP-P2: LangGraph interrupt_before=[...] (non-empty) or interrupt(...) is a human gate
        if isinstance(node, ast.Call):
            nonempty = any(
                kw.arg == "interrupt_before"
                and isinstance(kw.value, ast.List | ast.Tuple | ast.Set)
                and kw.value.elts
                for kw in node.keywords
            )
            if nonempty or _call_name(node) in ("interrupt", "langgraph.types.interrupt"):
                st.human_refs.append(index.evidence(file, node.lineno))


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}"
    return ""


def _subscript_keys(fn: ast.AST) -> set[str]:
    """``args["x"]`` and ``args.get("x")`` keys inside a tool function."""
    keys: set[str] = set()
    for sub in ast.walk(fn):
        if (
            isinstance(sub, ast.Subscript)
            and isinstance(sub.value, ast.Name)
            and sub.value.id in ("args", "arguments", "params", "kwargs")
            and isinstance(sub.slice, ast.Constant)
            and isinstance(sub.slice.value, str)
        ):
            keys.add(sub.slice.value)
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "get"
            and isinstance(sub.func.value, ast.Name)
            and sub.func.value.id in ("args", "arguments", "params", "kwargs")
            and sub.args
            and isinstance(sub.args[0], ast.Constant)
            and isinstance(sub.args[0].value, str)
        ):
            keys.add(sub.args[0].value)
    return keys


def _str_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("{}")
        return "".join(parts)
    return None


def _scan_node(file: str, node: ast.AST, index: SourceIndex, st: _State) -> None:
    line = getattr(node, "lineno", 1)
    if isinstance(node, ast.Import | ast.ImportFrom):
        mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
        for mod in mods:
            top = mod.split(".")[0]
            if top in ("opentelemetry", "mlflow"):
                st.traces.append(
                    NamedRef(name=top, detail=mod, evidence=index.evidence(file, line))
                )
            if top in ("mcp", "fastmcp", "langchain_mcp_adapters"):
                st.mcp.append(
                    NamedRef(name=mod, detail="import", evidence=index.evidence(file, line))
                )
            if top in ("openai", "anthropic", "litellm", "langchain_openai", "ollama"):
                st.endpoints.append(
                    Endpoint(name=mod, source="code", evidence=index.evidence(file, line))
                )
    elif isinstance(node, ast.Call):
        for kw in node.keywords:
            if kw.arg in ("tracer_provider", "tracer") and file.endswith(".py"):
                st.traces.append(
                    NamedRef(
                        name="otel",
                        detail=f"{kw.arg} passed",
                        evidence=index.evidence(file, kw.value.lineno),
                    )
                )
            value = _str_value(kw.value) if kw.value is not None else None
            if value is None:
                continue
            if kw.arg in ("prompt", "system_prompt", "instructions", "system", "system_message"):
                kind = "task" if kw.arg == "prompt" else "system"
                st.prompts.append(
                    PromptInfo(
                        kind=kind,  # type: ignore[arg-type]
                        excerpt=value[:240],
                        sha256=_sha(value),
                        evidence=index.evidence(file, kw.value.lineno),
                    )
                )
            if kw.arg in ("model", "model_id", "endpoint", "endpoint_name", "base_url"):
                st.endpoints.append(
                    Endpoint(name=value[:120], source="code", evidence=index.evidence(file, line))
                )
        name = _call_name(node)
        if name.endswith((".table", ".read_table")) and node.args:
            v = _str_value(node.args[0])
            if v:
                st.tables.append(
                    TableRef(
                        name=v, direction="read", source="code", evidence=index.evidence(file, line)
                    )
                )
        if name.endswith((".saveAsTable", ".insertInto", ".write_table")) and node.args:
            v = _str_value(node.args[0])
            if v:
                st.tables.append(
                    TableRef(
                        name=v,
                        direction="write",
                        source="code",
                        evidence=index.evidence(file, line),
                    )
                )
    elif isinstance(node, ast.Assign):
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            return
        tname = targets[0]
        if isinstance(node.value, ast.Tuple | ast.List) and tname.isupper():
            vals = [
                e.value
                for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            if vals and len(vals) == len(node.value.elts):
                st.constants[tname] = vals
        value = _str_value(node.value)
        if value and re.search(r"(?i)prompt|instruction|system_message", tname):
            st.prompts.append(
                PromptInfo(
                    kind="system",
                    excerpt=value[:240],
                    sha256=_sha(value),
                    evidence=index.evidence(file, line),
                )
            )
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        v = node.value
        if _MODEL_RE.match(v.strip()) and len(v) < 120:
            st.endpoints.append(
                Endpoint(name=v.strip(), source="code", evidence=index.evidence(file, line))
            )
        if _SQL_HINT.search(v):
            for m in _SQL_READ.finditer(v):
                st.tables.append(
                    TableRef(
                        name=m.group(1).strip("`"),
                        direction="read",
                        source="code",
                        evidence=index.evidence(file, line),
                    )
                )
            for m in _SQL_WRITE.finditer(v):
                st.tables.append(
                    TableRef(
                        name=m.group(1).strip("`"),
                        direction="write",
                        source="code",
                        evidence=index.evidence(file, line),
                    )
                )
        if v.lower().startswith("you are ") and len(v) > 20:
            st.prompts.append(
                PromptInfo(
                    kind="template",
                    excerpt=v[:240],
                    sha256=_sha(v),
                    evidence=index.evidence(file, line),
                )
            )


def _scan_config(file: str, index: SourceIndex, st: _State) -> None:
    for i, line in enumerate(index.lines[file], start=1):
        if re.search(r"(?i)\"?mcpServers\"?\s*[:=]|^\s*mcp_servers\s*:", line):
            st.mcp.append(NamedRef(name=file, detail="config", evidence=index.evidence(file, i)))


def _scan_notes(file: str, index: SourceIndex, st: _State) -> None:
    for i, line in enumerate(index.lines[file], start=1):
        for kind, pattern in _NOTE_RULES:
            if re.search(pattern, line):
                st.notes.append(
                    Note(text=line.strip()[:240], kind=kind, evidence=index.evidence(file, i))  # type: ignore[arg-type]
                )
                break


# --------------------------------------------------------------------------- workspace


def _scan_workspace(
    ws: WorkspaceReader, agent_id: str, scrubber: Scrubber, st: _State, model_id: str
) -> None:
    for e in ws.list_serving_endpoints():
        name = scrubber.scrub(str(e.get("name", "")), source="workspace")
        if not name:
            continue
        linked = agent_id in name or (model_id and model_id.split(":")[0] in str(e))
        st.endpoints.append(
            Endpoint(
                name=name[:120],
                family=str(e.get("family")) if e.get("family") else None,
                source="workspace",
            )
        )
        if linked:
            st.traces.append(
                NamedRef(name="serving", detail=f"endpoint {name[:80]}", source="workspace")
            )
    apps = getattr(ws, "list_apps", None)
    if callable(apps):
        st.apps = sorted(scrubber.scrub(str(a.get("name", "")), source="workspace") for a in apps())
    lineage = getattr(ws, "lineage", None)
    if callable(lineage):
        for row in lineage():
            if row.get("agent") != agent_id:
                continue
            d = "write" if row.get("direction") == "write" else "read"
            st.tables.append(
                TableRef(
                    name=scrubber.scrub(str(row.get("table", "")), source="workspace")[:200],
                    direction=d,  # type: ignore[arg-type]
                    source="workspace",
                )
            )
    traces = getattr(ws, "traces", None)
    if callable(traces):
        for row in traces():
            if row.get("agent") == agent_id:
                st.traces.append(
                    NamedRef(
                        name=str(row.get("source", "workspace"))[:40],
                        detail=f"{int(row.get('count', 0))} existing traces",
                        source="workspace",
                    )
                )


# --------------------------------------------------------------------------- features


def features_of(inv: Inventory) -> list[str]:
    """Catalogue features (``supervisor.catalogue.model.FEATURES``) the agent has."""
    f: set[str] = set()
    tools = inv.tools
    action = [t for t in tools if t.risk_class in ("money", "credit")]
    if any(t.amount_arg for t in action):
        f.add("amount_arg")
    if any(lim.period == "per_call" and lim.tool for lim in inv.limits):
        f.add("declared_limit")
    if any(lim.period == "daily" and lim.tool for lim in inv.limits):
        f.add("declared_daily_limit")
    if any(t.destination_arg for t in tools if t.risk_class == "money"):
        f.add("destination_arg")
    if any(t.key_args for t in action):
        f.add("customer_key")
    reads = [t for t in tools if t.risk_class in ("read_only", "pii_export")]
    if any(_record_flag(t) for t in reads):
        f.add("record_fact")
    decisions = [t for t in tools if t.risk_class == "credit" and "decision" in t.args]
    if decisions:
        f.add("decision_tool")
    for d in decisions:
        ids = {a for a in d.args if a.endswith("_id")}
        if any(ids & set(r.args) for r in reads):
            f.add("prior_read")
    if any(t.risk_class == "pii_export" for t in tools):
        f.add("pii_tool")
    if any(a in ("text", "message", "body", "reply") for t in tools for a in t.args):
        f.add("free_text_output")
    if inv.model_endpoints:
        f.add("llm")
    if any(t.name in ("opentelemetry", "otel", "mlflow", "capture") for t in inv.traces):
        f.add("otel_spans")
    return sorted(f)


def _record_flag(t: ToolInfo) -> str | None:
    return next(
        (r for r in t.returns_fields if r.endswith(("_complete", "_verified", "_ok"))), None
    )


def record_flag(t: ToolInfo) -> str | None:
    """Field of a read tool's result that says a record is complete (for fact rules)."""
    return _record_flag(t)
