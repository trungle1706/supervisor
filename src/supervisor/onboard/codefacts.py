"""Code facts for Discover (WP16): framework, LLM call sites, data access, tracing, tool
registrations that the base scan misses, and personal-data identifiers.

Static only: Python files are parsed with ``ast`` (never imported or run). The rules follow
the label conventions in ``data/corpus/README.md`` and were tuned on that corpus.

    facts = analyse(index.lines)          # {file: scrubbed lines}
    facts.framework, facts.llm_calls, facts.data_access, facts.tracing, facts.tools
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import yaml

# The judge router owns the family alias table (claude -> anthropic, ...). Import it so the
# onboarding family and the judge family can never disagree on a name (WP1b-B, D08).
from supervisor.judge.router import FAMILY_ALIASES

PII_VOCAB = frozenset(
    """customer_id full_name customer_name payee_name national_id cccd cmnd id_number phone
    phone_number email address dob date_of_birth account_number account_id card_number income
    monthly_income salary tax_code ho_ten so_cccd so_dien_thoai sdt dia_chi ngay_sinh
    so_tai_khoan thu_nhap ma_so_thue""".split()
)

# Framework by import prefix; first rule that matches any import wins.
_FRAMEWORKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("deepagents", ("deepagents",)),  # built on LangGraph, so it must come first
    ("langgraph", ("langgraph",)),
    ("crewai", ("crewai",)),
    ("llamaindex", ("llama_index",)),
    ("databricks_agents", ("mlflow.pyfunc", "mlflow.types.agent", "databricks.agents")),
    ("langchain", ("langchain", "databricks_langchain")),
    ("fastmcp", ("fastmcp", "mcp.server")),
    ("fastapi", ("fastapi",)),
    ("anthropic_sdk", ("anthropic",)),
    ("openai_sdk", ("openai",)),
)

# Chat-model constructors (the call site for framework LLMs): class -> provider.
_CHAT_CTORS: dict[str, str] = {
    "ChatOpenAI": "openai",
    "AzureChatOpenAI": "azure_openai",
    "ChatAnthropic": "anthropic",
    "ChatDatabricks": "databricks",
    "ChatOllama": "ollama",
    "init_chat_model": "unknown",
}
_LLAMA_LLMS: dict[str, str] = {
    "OpenAI": "openai",
    "AzureOpenAI": "azure_openai",
    "Anthropic": "anthropic",
    "Databricks": "databricks",
    "Ollama": "ollama",
}
_SDK_CLIENTS: dict[str, str] = {
    "openai.OpenAI": "openai",
    "openai.AsyncOpenAI": "openai",
    "openai.AzureOpenAI": "azure_openai",
    "openai.AsyncAzureOpenAI": "azure_openai",
    "anthropic.Anthropic": "anthropic",
    "anthropic.AsyncAnthropic": "anthropic",
    "anthropic.AnthropicBedrock": "anthropic",
    "databricks.sdk.WorkspaceClient": "databricks",
    "mlflow.deployments.get_deploy_client": "databricks",
}
_SDK_CALL_SUFFIXES = (
    "chat.completions.create",
    "chat.completions.parse",
    "completions.create",
    "responses.create",
    "messages.create",
    "messages.stream",
)
_MODEL_KW = (
    "model",
    "model_name",
    "model_id",
    "endpoint",
    "endpoint_name",
    "deployment_name",
    "azure_deployment",
    "deployment_id",
)
_LLM_URL = re.compile(
    r"/chat/completions|/invocations\b|api\.anthropic\.com|/api/chat\b|/api/generate\b|"
    r"/v1/completions\b"
)
_HTTP_METHODS = {"get": "read", "head": "read", "post": "write", "put": "write", "patch": "write"}
_HTTP_METHODS["delete"] = "write"
_SQL_WRITE = re.compile(r"(?i)^\s*(insert|update|delete|merge|create|replace|upsert|drop|alter)\b")
_SQL_HINT = re.compile(r"(?i)\b(select|insert|update|delete|merge)\b")
_SQL_TABLE = re.compile(r"(?i)\b(?:from|into|update|join|table)\s+([A-Za-z_][\w.`]*)")
_FILE_READ = ("read_text", "read_bytes")
_FILE_WRITE = ("write_text", "write_bytes")
_PD_READ = ("read_csv", "read_excel", "read_parquet", "read_json")
_PD_WRITE = ("to_csv", "to_excel", "to_parquet", "to_json")
_TOOL_LIST_KW = ("tools", "functions")
_TOOL_LIST_CALLS = (
    "bind_tools",
    "ToolNode",
    "create_react_agent",
    "create_deep_agent",
    "create_agent",
    "bind_functions",
)
# Agent factories that take the model as a string (``"provider:model"`` or a bare id).
_AGENT_FACTORIES = {
    "create_deep_agent": "deepagents",
    "create_react_agent": "langgraph",
    "create_agent": "langchain",
}
_TOOL_CTORS = {
    "Tool": ("func", "name"),
    "StructuredTool.from_function": ("func", "name"),
    "Tool.from_function": ("func", "name"),
    "FunctionTool.from_defaults": ("fn", "name"),
    "FunctionTool": ("fn", "name"),
}
_TOOL_BASES = ("BaseTool",)
_ROUTE_METHODS = ("get", "post", "put", "patch", "delete")
# A route under one of these path roots is a tool server endpoint (the model calls it as a
# tool); every other route is an entrypoint of the agent app (WP1b-B, D08).
_TOOL_PATH = re.compile(r"^/(tools?|functions?|actions?|mcp)(/|$)", re.IGNORECASE)
_NOT_TOOL_DECOS = ("resource", "prompt", "on_event", "middleware", "exception_handler")


@dataclass
class Fact:
    file: str
    line: int


@dataclass
class LlmCallFact(Fact):
    provider: str
    family: str
    model: str | None
    via: str


@dataclass
class DataFact(Fact):
    kind: str
    direction: str
    target: str | None


@dataclass
class ToolFact(Fact):
    name: str
    func: str | None  # implementing function name (any file)
    how: str


@dataclass
class EntrypointFact(Fact):
    """An HTTP route of the agent app (not a tool the model can call)."""

    method: str
    path: str
    func: str

    @property
    def name(self) -> str:
        return f"{self.method} {self.path}"


@dataclass
class CodeFacts:
    framework: str = "custom"
    framework_evidence: Fact | None = None
    llm_calls: list[LlmCallFact] = field(default_factory=list)
    data_access: list[DataFact] = field(default_factory=list)
    tracing: dict[str, Fact] = field(default_factory=dict)
    tools: list[ToolFact] = field(default_factory=list)
    entrypoints: list[EntrypointFact] = field(default_factory=list)
    dynamic_tools: list[Fact] = field(default_factory=list)  # MCP ``tools/list`` at runtime
    pii: dict[str, Fact] = field(default_factory=dict)
    trees: dict[str, ast.Module] = field(default_factory=dict)


_ID_PREFIXES = (
    "us.anthropic.",
    "eu.anthropic.",
    "global.anthropic.",
    "anthropic.",
    "anthropic/",
    "openai/",
    "databricks/",
    "databricks-",
    "meta-",
    "meta/",
)
_FAMILY_TOKEN = re.compile(r"[a-z]+\d*")
# Families that the router alias table does not list: model-id token -> family.
_EXTRA_TOKENS: dict[str, str] = {
    "o3": "openai",
    "o4": "openai",
    "deepseek": "deepseek",
    "mistral": "mistral",
    "mixtral": "mistral",
    "dbrx": "databricks",
    "qwen": "qwen",
}


def model_family(model: str | None) -> str:
    """Family of a model id or serving endpoint name (``databricks-claude-*`` -> anthropic,
    ``databricks-meta-llama-*`` -> meta, ``databricks-gpt-oss-*`` -> openai, ``qwen3.8-*`` ->
    qwen). Vendor prefixes are cut first; the leading word is then looked up in the judge
    router alias table (``judge.router.FAMILY_ALIASES``), so both sides use one vocabulary."""
    if not model:
        return "unknown"
    name = model.strip().lower().rsplit("/", 1)[-1] if "/" in model else model.strip().lower()
    changed = True
    while changed:
        changed = False
        for p in _ID_PREFIXES:
            if name.startswith(p):
                name, changed = name[len(p) :], True
    m = _FAMILY_TOKEN.match(name)
    if not m:
        return "unknown"
    tok = m.group(0)
    base = tok.rstrip("0123456789")
    for key in (tok, base):
        if key in FAMILY_ALIASES:
            return FAMILY_ALIASES[key]
    for key in (tok, base):
        if key in _EXTRA_TOKENS:
            return _EXTRA_TOKENS[key]
    return "unknown"


# --------------------------------------------------------------------------- per file


@dataclass
class _File:
    path: str
    tree: ast.Module
    imports: dict[str, str] = field(default_factory=dict)  # local name -> dotted origin
    modules: set[str] = field(default_factory=set)
    consts: dict[str, str] = field(default_factory=dict)  # module-level string constants
    binds: dict[str, str] = field(default_factory=dict)  # var -> qualified callee
    bind_kws: dict[str, ast.Call] = field(default_factory=dict)
    defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)  # env values from app.yaml / .env files

    def qual(self, node: ast.AST) -> str:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Call):
            parts.append(self.qual(node.func) + "()")
        elif isinstance(node, ast.Name):
            parts.append(self.imports.get(node.id, node.id))
        else:
            return ""
        return ".".join(reversed(parts))

    def text(self, node: ast.AST | None) -> str | None:
        """Static string value; unknown parts become ``{}``."""
        if node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self.consts.get(node.id)
        if isinstance(node, ast.JoinedStr):
            out = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    out.append(str(v.value))
                elif isinstance(v, ast.FormattedValue):
                    out.append(self.text(v.value) or "{}")
            return "".join(out)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            a, b = self.text(node.left), self.text(node.right)
            if a is None and b is None:
                return None
            return (a or "{}") + (b or "{}")
        if isinstance(node, ast.Call) and self.qual(node.func) in ("os.getenv", "os.environ.get"):
            key = self.text(node.args[0]) if node.args else None
            if key and key in self.env:
                return self.env[key]
            default = node.args[1] if len(node.args) > 1 else _kw(node, "default")
            return self.text(default)
        if (
            isinstance(node, ast.Subscript)
            and self.qual(node.value) == "os.environ"
            and isinstance(node.slice, ast.Constant)
        ):
            return self.env.get(str(node.slice.value))
        if isinstance(node, ast.Call) and self.qual(node.func).endswith(("text", "format")):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                return self.text(node.func.value)
            return self.text(node.args[0]) if node.args else None
        return None


def _load(path: str, tree: ast.Module, env: Mapping[str, str] | None = None) -> _File:
    f = _File(path, tree, env=env or {})
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                f.imports[(a.asname or a.name).split(".")[0]] = (
                    a.name if a.asname else a.name.split(".")[0]
                )
                f.modules.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            f.modules.add(node.module)
            for a in node.names:
                f.imports[a.asname or a.name] = f"{node.module}.{a.name}"
                f.modules.add(f"{node.module}.{a.name}")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            f.defs.setdefault(node.name, node)
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            val = node.value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                for t in targets:
                    if isinstance(t, ast.Name):
                        f.consts[t.id] = val.value
    for node in tree.body:  # second pass: f-string constants built from constants
        if isinstance(node, ast.Assign) and isinstance(
            node.value, ast.JoinedStr | ast.BinOp | ast.Call | ast.Subscript
        ):
            v = f.text(node.value)
            for t in node.targets:
                if isinstance(t, ast.Name) and v is not None:
                    f.consts.setdefault(t.id, v)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(node.value, ast.Call):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                key = ast.unparse(t) if isinstance(t, ast.Name | ast.Attribute) else None
                if key:
                    f.binds[key] = f.qual(node.value.func)
                    f.bind_kws[key] = node.value
    return f


def _kw(call: ast.Call, *names: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg in names:
            return kw.value
    return None


def _root(node: ast.AST) -> ast.AST:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node


def _receiver(call: ast.Call) -> str:
    """Source text of the object a method is called on (``client`` in client.x.y())."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return ""
    node: ast.AST = func.value
    while isinstance(node, ast.Attribute) and node.attr in (
        "chat",
        "completions",
        "messages",
        "responses",
        "beta",
        "serving_endpoints",
    ):
        node = node.value
    return ast.unparse(node) if isinstance(node, ast.Name | ast.Attribute | ast.Call) else ""


# --------------------------------------------------------------------------- analyse


def analyse(lines: Mapping[str, Sequence[str]]) -> CodeFacts:
    facts = CodeFacts()
    files: list[_File] = []
    env = _env_values(lines)
    for path in sorted(lines):
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse("\n".join(lines[path]), filename=path)
        except SyntaxError:
            continue
        facts.trees[path] = tree
        files.append(_load(path, tree, env))
    all_defs = {name: (f, fn) for f in files for name, fn in f.defs.items()}
    facts.framework, facts.framework_evidence = _framework(files)
    for f in files:
        _llm_and_data(f, facts)
        _tracing(f, facts)
        _pii(f, facts)
    facts.tools = _tools(files, all_defs, _yaml_lists(lines))
    facts.entrypoints = _routes(files)
    facts.dynamic_tools = _dynamic_tools(files)
    facts.llm_calls.sort(key=lambda x: (x.file, x.line))
    facts.data_access.sort(key=lambda x: (x.file, x.line, x.kind))
    return facts


def _framework(files: Sequence[_File]) -> tuple[str, Fact | None]:
    for name, prefixes in _FRAMEWORKS:
        for f in files:
            for node in ast.walk(f.tree):
                mods: list[str] = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    mods = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
                if any(_under(m, p) for m in mods for p in prefixes):
                    return name, Fact(f.path, node.lineno)
    return "custom", None


def _under(module: str, prefix: str) -> bool:
    """``langchain_core.tools`` is under ``langchain``; ``mcp.server.fastmcp`` under
    ``mcp.server``."""
    top = module.split(".")[0]
    return module == prefix or module.startswith(prefix + ".") or top.startswith(prefix + "_")


def _client_provider(f: _File, call: ast.Call) -> str:
    recv = _receiver(call)
    bound = f.binds.get(recv, "")
    if bound.endswith("()"):
        bound = bound[:-2]
    for key, prov in _SDK_CLIENTS.items():
        if bound == key or bound.endswith("." + key.rsplit(".", 1)[-1]) and key in bound:
            return prov
    if bound in ("OpenAI", "AsyncOpenAI"):
        return "openai"
    mods = {m.split(".")[0] for m in f.modules}
    if "anthropic" in mods and "openai" not in mods:
        return "anthropic"
    if "openai" in mods:
        return "openai"
    if "databricks" in mods or "mlflow" in mods:
        return "databricks"
    return "unknown"


def _model_of(f: _File, call: ast.Call, extra: Iterable[str] = ()) -> str | None:
    node = _kw(call, *_MODEL_KW, *extra)
    if node is None:
        return None
    v = f.text(node)
    return v if v and "{}" not in v else None


def _http_kind(url: str | None) -> str:
    return "bank_api" if url and ".nganhang.internal" in url else "http"


def _llm_and_data(f: _File, facts: CodeFacts) -> None:
    for node in ast.walk(f.tree):
        if not isinstance(node, ast.Call):
            continue
        q = f.qual(node.func)
        last = q.rsplit(".", 1)[-1]
        line = node.lineno
        # ---- LLM: SDK request calls
        if any(q.endswith(s) for s in _SDK_CALL_SUFFIXES) and not q.startswith(
            ("openai.", "anthropic.")
        ):
            prov = _client_provider(f, node)
            model = _model_of(f, node)
            facts.llm_calls.append(
                LlmCallFact(f.path, line, prov, model_family(model), model, "sdk")
            )
            continue
        if q.endswith("serving_endpoints.query"):
            model = _model_of(f, node, ("name",))
            facts.llm_calls.append(
                LlmCallFact(f.path, line, "databricks", model_family(model), model, "serving")
            )
            continue
        if last == "predict" and (
            "get_deploy_client" in q
            or "get_deploy_client" in f.binds.get(_receiver(node), "")
            or _kw(node, "endpoint") is not None
        ):
            model = _model_of(f, node)
            facts.llm_calls.append(
                LlmCallFact(f.path, line, "databricks", model_family(model), model, "deploy")
            )
            continue
        if q in ("litellm.completion", "litellm.acompletion", "ollama.chat", "ollama.generate"):
            model = _model_of(f, node)
            prov = q.split(".")[0]
            facts.llm_calls.append(LlmCallFact(f.path, line, prov, model_family(model), model, q))
            continue
        # ---- LLM: framework chat-model constructors
        ctor = q.rsplit(".", 1)[-1] if "." in q else q
        origin = f.imports.get(ctor, q)
        if ctor in _CHAT_CTORS and (origin.startswith(("langchain", "databricks_langchain"))):
            model = _model_of(f, node)
            prov = _CHAT_CTORS[ctor]
            if ctor == "init_chat_model":
                model = model or f.text(node.args[0]) if node.args else model
                prov = (f.text(_kw(node, "model_provider")) or "unknown").replace(
                    "azure_openai", "azure_openai"
                )
            facts.llm_calls.append(
                LlmCallFact(f.path, line, prov, model_family(model), model, ctor)
            )
            continue
        if ctor in _LLAMA_LLMS and origin.startswith("llama_index.llms"):
            model = _model_of(f, node)
            facts.llm_calls.append(
                LlmCallFact(f.path, line, _LLAMA_LLMS[ctor], model_family(model), model, ctor)
            )
            continue
        if ctor in _AGENT_FACTORIES and origin.startswith(_AGENT_FACTORIES[ctor]):
            # create_deep_agent(model="..."), create_react_agent("provider:model", tools)
            node_m = _kw(node, "model", "llm")
            if node_m is None and ctor != "create_deep_agent" and node.args:
                node_m = node.args[0]
            model = f.text(node_m) if node_m is not None else None
            if model and "{}" not in model:
                prov, _, rest = model.partition(":")
                if rest and prov.isalpha():
                    model = rest
                else:
                    prov = _prefix_provider(model)
                facts.llm_calls.append(
                    LlmCallFact(f.path, line, prov, model_family(model), model, ctor)
                )
            continue
        if origin.startswith("crewai") and ctor == "LLM":
            model = _model_of(f, node) or (f.text(node.args[0]) if node.args else None)
            prov = _prefix_provider(model)
            facts.llm_calls.append(
                LlmCallFact(f.path, line, prov, model_family(model), model, ctor)
            )
            continue
        if origin.startswith("crewai") and ctor == "Agent":
            llm = _kw(node, "llm")
            model = f.text(llm) if llm is not None else None
            if model:
                facts.llm_calls.append(
                    LlmCallFact(
                        f.path, line, _prefix_provider(model), model_family(model), model, "Agent"
                    )
                )
            continue
        # ---- HTTP (LLM endpoint or data)
        method = _http_method(f, node, q)
        if method:
            url = _resolve(f, node.args[0]) if node.args else _resolve(f, _kw(node, "url"))
            if method == "request" and node.args:
                verb = (f.text(node.args[0]) or "get").lower()
                url = f.text(node.args[1]) if len(node.args) > 1 else f.text(_kw(node, "url"))
                method = verb
            base = _client_base(f, node)
            full = (base or "") + (url or "") if base else url
            if full and _LLM_URL.search(full):
                model = _json_model(f, node)
                facts.llm_calls.append(
                    LlmCallFact(f.path, line, "unknown", model_family(model), model, "http")
                )
                continue
            facts.data_access.append(
                DataFact(
                    f.path,
                    line,
                    _http_kind(full),
                    _HTTP_METHODS.get(method, "read"),
                    full,
                )
            )
            continue
        if q in ("urllib.request.urlopen", "urlopen"):
            url = f.text(node.args[0]) if node.args else None
            facts.data_access.append(DataFact(f.path, line, _http_kind(url), "read", url))
            continue
        # ---- DB
        if last in ("execute", "executemany", "executescript") and isinstance(
            node.func, ast.Attribute
        ):
            sql = f.text(node.args[0]) if node.args else None
            if sql is None and node.args and isinstance(node.args[0], ast.Name):
                sql = _local_sql(f, node.args[0].id)
            facts.data_access.append(_db(f.path, line, sql))
            continue
        if last == "sql" and isinstance(node.func, ast.Attribute) and node.args:
            facts.data_access.append(_db(f.path, line, f.text(node.args[0])))
            continue
        if last in ("table", "read_table") and isinstance(node.func, ast.Attribute):
            recv = ast.unparse(node.func.value)
            if "spark" in recv or recv.endswith("read"):
                facts.data_access.append(
                    DataFact(
                        f.path, line, "db", "read", f.text(node.args[0]) if node.args else None
                    )
                )
                continue
        if last in ("saveAsTable", "insertInto", "to_sql"):
            tgt = f.text(node.args[0]) if node.args else None
            facts.data_access.append(DataFact(f.path, line, "db", "write", tgt))
            continue
        if last in ("read_sql", "read_sql_query", "read_sql_table"):
            facts.data_access.append(_db(f.path, line, f.text(node.args[0]) if node.args else None))
            continue
        if last == "query" and "session" in ast.unparse(node.func).lower():
            facts.data_access.append(DataFact(f.path, line, "db", "read", None))
            continue
        # ---- files
        if q == "open" and node.args:
            mode = f.text(node.args[1]) if len(node.args) > 1 else f.text(_kw(node, "mode"))
            write = bool(mode and any(c in mode for c in "wax+"))
            facts.data_access.append(
                DataFact(f.path, line, "file", "write" if write else "read", f.text(node.args[0]))
            )
            continue
        if last in _FILE_READ + _FILE_WRITE and isinstance(node.func, ast.Attribute):
            facts.data_access.append(
                DataFact(
                    f.path,
                    line,
                    "file",
                    "write" if last in _FILE_WRITE else "read",
                    _path_target(f, node.func.value),
                )
            )
            continue
        if last in _PD_READ and (q.startswith(("pandas.", "pd.")) or q == last):
            facts.data_access.append(
                DataFact(f.path, line, "file", "read", f.text(node.args[0]) if node.args else None)
            )
            continue
        if last in _PD_WRITE and isinstance(node.func, ast.Attribute):
            facts.data_access.append(
                DataFact(f.path, line, "file", "write", f.text(node.args[0]) if node.args else None)
            )
            continue
        if ctor == "SimpleDirectoryReader" and origin.startswith("llama_index"):
            tgt = f.text(node.args[0]) if node.args else f.text(_kw(node, "input_dir"))
            facts.data_access.append(DataFact(f.path, line, "file", "read", tgt))


def _prefix_provider(model: str | None) -> str:
    if not model:
        return "unknown"
    head = model.split("/", 1)[0].lower() if "/" in model else ""
    if head in ("anthropic", "openai", "azure", "databricks", "ollama"):
        return "azure_openai" if head == "azure" else head
    fam = model_family(model)
    return {"anthropic": "anthropic", "openai": "openai"}.get(fam, "unknown")


def _http_method(f: _File, call: ast.Call, q: str) -> str | None:
    head, _, method = q.rpartition(".")
    if method not in _HTTP_METHODS and method != "request" and method != "stream":
        return None
    if head in ("requests", "httpx"):
        return method
    recv = _receiver(call)
    bound = f.binds.get(recv, "").removesuffix("()")
    if bound in (
        "requests.Session",
        "requests.session",
        "httpx.Client",
        "httpx.AsyncClient",
    ):
        return method
    return None


def _client_base(f: _File, call: ast.Call) -> str | None:
    recv = _receiver(call)
    ctor = f.bind_kws.get(recv)
    return f.text(_kw(ctor, "base_url")) if ctor is not None else None


def _json_model(f: _File, call: ast.Call) -> str | None:
    payload = _kw(call, "json", "data")
    if isinstance(payload, ast.Name):
        payload = _local_value(f, payload.id)
    if isinstance(payload, ast.Dict):
        for k, v in zip(payload.keys, payload.values, strict=False):
            if isinstance(k, ast.Constant) and k.value == "model":
                val = f.text(v)
                return val if val and "{}" not in val else None
    return None


def _resolve(f: _File, node: ast.AST | None) -> str | None:
    """Static text of ``node``; a local variable is followed to its assignment."""
    v = f.text(node)
    if v is None and isinstance(node, ast.Name):
        local = _local_value(f, node.id)
        v = f.text(local) if local is not None else None
    return v


def _local_value(f: _File, name: str) -> ast.AST | None:
    for node in ast.walk(f.tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node.value
    return None


def _local_sql(f: _File, name: str) -> str | None:
    v = _local_value(f, name)
    return f.text(v) if v is not None else None


def _path_target(f: _File, node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and node.args:
        return f.text(node.args[0])
    return f.text(node)


def _db(file: str, line: int, sql: str | None) -> DataFact:
    if not sql:
        return DataFact(file, line, "db", "read", None)
    direction = "write" if _SQL_WRITE.match(sql) else "read"
    m = _SQL_TABLE.search(sql)
    return DataFact(file, line, "db", direction, m.group(1).strip("`") if m else None)


def _tracing(f: _File, facts: CodeFacts) -> None:
    for node in ast.walk(f.tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            mods = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            if any(m.split(".")[0] == "opentelemetry" for m in mods):
                facts.tracing.setdefault("otel", Fact(f.path, node.lineno))
            if any(m.startswith("mlflow.tracing") for m in mods):
                facts.tracing.setdefault("mlflow", Fact(f.path, node.lineno))
        elif isinstance(node, ast.Call | ast.Attribute):
            q = f.qual(node.func if isinstance(node, ast.Call) else node)
            if q.startswith("mlflow") and (
                q.endswith(("autolog", ".trace", "start_span", "update_current_trace"))
                or ".tracing." in q
            ):
                facts.tracing.setdefault("mlflow", Fact(f.path, node.lineno))


def _pii(f: _File, facts: CodeFacts) -> None:
    def hit(name: str, line: int) -> None:
        if name in PII_VOCAB and name not in facts.pii:
            facts.pii[name] = Fact(f.path, line)

    for node in ast.walk(f.tree):
        if isinstance(node, ast.arg):
            hit(node.arg, node.lineno)
        elif isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    hit(k.value, k.lineno)
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                hit(node.slice.value, node.lineno)
        elif isinstance(node, ast.keyword) and node.arg:
            hit(node.arg, getattr(node, "lineno", 1))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    hit(node.args[0].value, node.lineno)
        elif isinstance(node, ast.ClassDef):
            for st in node.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    hit(st.target.id, st.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _SQL_HINT.search(node.value):
                for w in re.findall(r"[A-Za-z_]+", node.value):
                    hit(w, node.lineno)


# --------------------------------------------------------------------------- tools


def _yaml_lists(lines: Mapping[str, Sequence[str]]) -> set[str]:
    """String items of tool lists in YAML config (``enabled_tools``, ``tools``)."""
    names: set[str] = set()
    for path, rows in lines.items():
        if not path.endswith((".yaml", ".yml")):
            continue
        try:
            data = yaml.safe_load("\n".join(rows))
        except yaml.YAMLError:
            continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                for k, v in cur.items():
                    if isinstance(v, list) and "tool" in str(k).lower():
                        names |= {x for x in v if isinstance(x, str)}
                    stack.append(v)
            elif isinstance(cur, list):
                stack.extend(cur)
    return names


def _deco_tool(f: _File, dec: ast.AST) -> tuple[bool, str | None]:
    """(is a tool decorator, explicit name)."""
    q = f.qual(dec.func if isinstance(dec, ast.Call) else dec)
    last = q.rsplit(".", 1)[-1]
    if last in _NOT_TOOL_DECOS:
        return False, None
    is_tool = last in ("tool", "function_tool", "register_tool", "supervised_tool", "ai_tool")
    is_tool = is_tool or (last.endswith("_tool") and last.startswith(("register", "add")))
    if not is_tool:
        return False, None
    name = None
    if isinstance(dec, ast.Call):
        name = f.text(dec.args[0]) if dec.args else None
        name = f.text(_kw(dec, "name", "name_or_callable")) or name
    return True, name


def _is_route(f: _File, dec: ast.AST) -> bool:
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return False
    if dec.func.attr not in _ROUTE_METHODS:
        return False
    owner = f.binds.get(ast.unparse(dec.func.value), "").removesuffix("()")
    return owner.endswith(("FastAPI", "APIRouter"))


def _tools(
    files: Sequence[_File],
    all_defs: Mapping[str, tuple[_File, ast.FunctionDef | ast.AsyncFunctionDef]],
    yaml_names: set[str],
) -> list[ToolFact]:
    found: dict[str, ToolFact] = {}

    def add(name: str | None, func: str | None, file: str, line: int, how: str) -> None:
        if not name:
            return
        if func and func in all_defs:
            df, fn = all_defs[func]
            file, line = df.path, fn.lineno
        found.setdefault(name, ToolFact(file, line, name, func, how))

    explicit: dict[str, str] = {}  # function name -> explicit tool name (decorators)
    schema_names: dict[str, tuple[str, int]] = {}
    dispatch: dict[str, str] = {}
    for f in files:
        for node in ast.walk(f.tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for dec in node.decorator_list:
                    ok, name = _deco_tool(f, dec)
                    if ok:
                        explicit[node.name] = name or node.name
                        add(name or node.name, node.name, f.path, node.lineno, "decorator")
                    elif _is_route(f, dec):
                        # A route is a tool only on a tool server (path root /tools/...).
                        if _TOOL_PATH.match(_route_path(f, dec)):
                            add(node.name, node.name, f.path, node.lineno, "route")
            elif isinstance(node, ast.ClassDef):
                bases = {ast.unparse(b).rsplit(".", 1)[-1] for b in node.bases}
                if bases & set(_TOOL_BASES):
                    name = None
                    for st in node.body:
                        tgt = st.target if isinstance(st, ast.AnnAssign) else None
                        if isinstance(st, ast.Assign) and len(st.targets) == 1:
                            tgt = st.targets[0]
                        if isinstance(tgt, ast.Name) and tgt.id == "name":
                            name = f.text(st.value)
                    add(name or node.name, None, f.path, node.lineno, "class")
            elif isinstance(node, ast.Dict):
                keys = {
                    k.value: v
                    for k, v in zip(node.keys, node.values, strict=False)
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
                sub_tools = keys.get("tools")
                if isinstance(sub_tools, ast.List | ast.Tuple) and "name" in keys:
                    # deepagents sub-agent spec: {"name": ..., "tools": [fn, ...]}
                    for elt in sub_tools.elts:
                        if isinstance(elt, ast.Name) and elt.id in all_defs:
                            add(explicit.get(elt.id, elt.id), elt.id, f.path, elt.lineno, "list")
                if "name" in keys and ("input_schema" in keys or "parameters" in keys):
                    n = f.text(keys["name"])
                    if n:
                        schema_names.setdefault(n, (f.path, keys["name"].lineno))
                for k, v in zip(node.keys, node.values, strict=False):
                    if (
                        isinstance(k, ast.Constant)
                        and isinstance(k.value, str)
                        and isinstance(v, ast.Name)
                        and v.id in all_defs
                    ):
                        dispatch.setdefault(k.value, v.id)
            elif isinstance(node, ast.Call):
                q = f.qual(node.func)
                short = ".".join(q.rsplit(".", 2)[-2:]) if "." in q else q
                for key in (short, q.rsplit(".", 1)[-1]):
                    if key in _TOOL_CTORS:
                        fn_kw, name_kw = _TOOL_CTORS[key]
                        fn = _kw(node, fn_kw) or (node.args[0] if node.args else None)
                        func = fn.id if isinstance(fn, ast.Name) else None
                        name = f.text(_kw(node, name_kw)) or func
                        add(name, func, f.path, node.lineno, "ctor")
                        break
                if q.rsplit(".", 1)[-1] in ("QueryEngineTool", "from_defaults") and (
                    "QueryEngineTool" in q
                ):
                    meta = _kw(node, "metadata")
                    name = f.text(_kw(node, "name"))
                    if isinstance(meta, ast.Call):
                        name = f.text(_kw(meta, "name")) or name
                    add(name, None, f.path, node.lineno, "query_engine_tool")
    # lists of tool functions: bind_tools([...]), tools=[...], TOOLS = [...]
    for f in files:
        for node in ast.walk(f.tree):
            seqs: list[ast.AST] = []
            if isinstance(node, ast.Call):
                last = f.qual(node.func).rsplit(".", 1)[-1]
                if last in _TOOL_LIST_CALLS:
                    seqs += node.args[:2]
                seqs += [kw.value for kw in node.keywords if kw.arg in _TOOL_LIST_KW]
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and re.search(r"(?i)tool|cong_cu", t.id):
                        seqs.append(node.value)
            for seq in seqs:
                if isinstance(seq, ast.Name):
                    seq = _local_value(f, seq.id) or seq
                if isinstance(seq, ast.List | ast.Tuple):
                    for elt in seq.elts:
                        if isinstance(elt, ast.Name) and elt.id in all_defs:
                            add(explicit.get(elt.id, elt.id), elt.id, f.path, elt.lineno, "list")
    for name, func in dispatch.items():
        if name in schema_names or name in explicit.values() or name in found:
            add(name, func, "", 0, "dispatch")
        elif re.search(r"(?i)tool|handler|registry|cong_cu", _dict_owner(files, name)):
            add(name, func, "", 0, "registry")
    for name, (path, line) in schema_names.items():
        add(name, name if name in all_defs else dispatch.get(name), path, line, "schema")
    for name in sorted(yaml_names):
        if name in all_defs and name not in found:
            add(name, name, "", 0, "config")
    return sorted(found.values(), key=lambda t: (t.file, t.line, t.name))


def _route_path(f: _File, dec: ast.AST) -> str:
    """Full path of a FastAPI route decorator (router prefix + path), '' if not static."""
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return ""
    raw = f.text(dec.args[0]) if dec.args else f.text(_kw(dec, "path"))
    if raw is None:
        return ""
    owner = ast.unparse(dec.func.value)
    ctor = f.bind_kws.get(owner)
    prefix = f.text(_kw(ctor, "prefix")) if ctor is not None else None
    return (prefix or "") + raw


def _routes(files: Sequence[_File]) -> list[EntrypointFact]:
    """HTTP routes of FastAPI apps and routers, with file:line of the handler ``def``."""
    out: list[EntrypointFact] = []
    for f in files:
        for node in ast.walk(f.tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                if _is_route(f, dec) and isinstance(dec, ast.Call):
                    if not isinstance(dec.func, ast.Attribute):
                        continue
                    out.append(
                        EntrypointFact(
                            f.path,
                            node.lineno,
                            dec.func.attr.upper(),
                            _route_path(f, dec) or "{}",
                            node.name,
                        )
                    )
    return sorted(out, key=lambda e: (e.file, e.line, e.method))


def _dynamic_tools(files: Sequence[_File]) -> list[Fact]:
    """Places where the tool list comes from an MCP server at run time (``tools/list``,
    ``session.list_tools()``). Those tools cannot be named from code."""
    out: list[Fact] = []
    for f in files:
        decorators = {
            id(d)
            for n in ast.walk(f.tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            for d in n.decorator_list
        }
        for node in ast.walk(f.tree):
            if isinstance(node, ast.Call) and id(node) not in decorators:
                if f.qual(node.func).rsplit(".", 1)[-1] == "list_tools" and isinstance(
                    node.func, ast.Attribute
                ):
                    out.append(Fact(f.path, node.lineno))
            elif isinstance(node, ast.Constant) and node.value == "tools/list":
                out.append(Fact(f.path, node.lineno))
    return sorted(out, key=lambda x: (x.file, x.line))


_ENV_LINE = re.compile(
    r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*['\"]?([^'\"#\s]+)['\"]?\s*(?:#.*)?$"
)


def _env_values(lines: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """Non-secret env values a deployment file sets: ``env:`` lists in app.yaml / YAML
    configs (``- name: X`` + ``value: Y``) and ``KEY=value`` lines of ``.env*`` files. Used
    to resolve ``os.environ.get("X")`` to a serving endpoint name."""
    env: dict[str, str] = {}
    for path in sorted(lines):
        base = path.rsplit("/", 1)[-1]
        if path.endswith((".yaml", ".yml")):
            try:
                data = yaml.safe_load("\n".join(lines[path]))
            except yaml.YAMLError:
                continue
            stack = [data]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    for k, v in cur.items():
                        if str(k).lower() in ("env", "environment") and isinstance(v, list):
                            for item in v:
                                if isinstance(item, dict) and isinstance(item.get("name"), str):
                                    val = item.get("value")
                                    if isinstance(val, str):
                                        env.setdefault(item["name"], val)
                        elif str(k).lower() in ("env", "environment") and isinstance(v, dict):
                            for ek, ev in v.items():
                                if isinstance(ev, str):
                                    env.setdefault(str(ek), ev)
                        stack.append(v)
                elif isinstance(cur, list):
                    stack.extend(cur)
        elif base.startswith(".env") or base.endswith(".env"):
            for row in lines[path]:
                m = _ENV_LINE.match(row)
                if m and "[REDACTED" not in m.group(2):
                    env.setdefault(m.group(1), m.group(2))
    return env


def _dict_owner(files: Sequence[_File], key: str) -> str:
    """Name of the variable a dict literal holding ``key`` is assigned to ('' if none)."""
    for f in files:
        for node in ast.walk(f.tree):
            if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(node.value, ast.Dict):
                keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
                if key in keys:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    return " ".join(ast.unparse(t) for t in targets)
    return ""
