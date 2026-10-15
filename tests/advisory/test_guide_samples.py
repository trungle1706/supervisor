"""docs/INTEGRATION_GUIDE.md: every python sample parses and registers tools the way its
cited corpus file does; the gate wiring matches the demo agents."""

from __future__ import annotations

import ast
import inspect
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "INTEGRATION_GUIDE.md"
CORPUS = ROOT / "data" / "corpus" / "repos"
AGENTS = ROOT / "src" / "supervisor_agents"

SAMPLE_RE = re.compile(
    r"<!-- sample: (?P<cite>\S+) -->\n"
    r"(?:<!-- registers: (?P<reg>.*?) -->\n)?"
    r"```python\n(?P<code>.*?)```",
    re.S,
)


@dataclass(frozen=True)
class Sample:
    cite: str
    registers: tuple[str, ...]
    code: str

    @property
    def corpus_file(self) -> Path:
        return CORPUS / self.cite


def load_samples() -> list[Sample]:
    text = GUIDE.read_text(encoding="utf-8")
    out = []
    for m in SAMPLE_RE.finditer(text):
        reg = tuple(x.strip() for x in (m.group("reg") or "").split(",") if x.strip())
        out.append(Sample(m.group("cite"), reg, m.group("code")))
    return out


SAMPLES = load_samples()


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return dotted(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def decorator_names(tree: ast.AST) -> set[str]:
    return {n for f in functions(tree) for d in f.decorator_list if (n := dotted(d))}


def call_names(tree: ast.AST) -> set[str]:
    return {n for c in ast.walk(tree) if isinstance(c, ast.Call) and (n := dotted(c.func))}


def def_names(tree: ast.AST) -> set[str]:
    return {f.name for f in functions(tree)}


def dict_keys(tree: ast.AST, name: str) -> set[str] | None:
    for n in ast.walk(tree):
        value = None
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in n.targets
        ):
            value = n.value
        elif (
            isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name
        ):
            value = n.value
        if isinstance(value, ast.Dict):
            return {k.value for k in value.keys if isinstance(k, ast.Constant)}
    return None


def test_guide_has_all_framework_samples() -> None:
    cited = {s.cite for s in SAMPLES}
    for needed in (
        "langgraph_loan_triage/tools.py",
        "langchain_card_support/tools.py",
        "llamaindex_policy_qa/agent.py",
        "openai_fx_quotes/agent.py",
        "anthropic_dispute_helper/agent.py",
        "mlflow_chatagent_savings/tools.py",
        "fastmcp_account_tools/server.py",
        "fastapi_toolserver_remit/server.py",
    ):
        assert needed in cited, needed


@pytest.mark.parametrize("s", SAMPLES, ids=[f"{s.cite}#{i}" for i, s in enumerate(SAMPLES)])
def test_sample_matches_corpus_registration(s: Sample) -> None:
    assert s.corpus_file.is_file(), f"cited corpus file missing: {s.cite}"
    sample = ast.parse(s.code)  # parses
    corpus = ast.parse(s.corpus_file.read_text(encoding="utf-8"))

    # 1. every framework decorator in the sample exists in the corpus file
    sample_decos = decorator_names(sample) - {"supervised_tool"}
    for d in sample_decos:
        if s.cite == "fastapi_toolserver_remit/server.py" and d == "app.exception_handler":
            continue  # the handler is new; the route decorators are checked below
        assert d in decorator_names(corpus), f"{d} is not used as a decorator in {s.cite}"

    # 2. placement: supervised_tool is the decorator closest to def, below any framework one
    for f in functions(sample):
        names = [dotted(d) for d in f.decorator_list]
        if "supervised_tool" in names:
            assert names[-1] == "supervised_tool", f"{f.name}: supervised_tool must be last"
            deco = f.decorator_list[-1]
            assert isinstance(deco, ast.Call)
            assert len(deco.args) == 4, f"{f.name}: (agent_id, version, tool_name, risk_class)"
            assert [k.arg for k in deco.keywords] == ["gate"]
            assert ast.unparse(deco.keywords[0].value) == "supervisor_onboard.default_gate()"
            risk = deco.args[3]
            assert isinstance(risk, ast.Constant)
            assert risk.value in {"read_only", "money", "credit", "pii_export"}

    # 3. explicit registration tokens
    for token in s.registers:
        kind, _, name = token.partition(":")
        if kind == "decorator":
            assert name in decorator_names(sample), f"sample lacks decorator {name}"
            assert name in decorator_names(corpus), f"corpus lacks decorator {name}"
        elif kind == "call":
            assert name in call_names(sample), f"sample lacks call {name}"
            assert name in call_names(corpus), f"corpus lacks call {name}"
        elif kind == "def":
            assert name in def_names(sample), f"sample lacks def {name}"
            assert name in def_names(corpus), f"corpus lacks def {name}"
        elif kind == "dict":
            mine, theirs = dict_keys(sample, name), dict_keys(corpus, name)
            assert mine is not None and theirs is not None, f"dict {name} missing"
            assert mine <= theirs, f"{name}: sample keys {mine - theirs} not in corpus"
        else:  # pragma: no cover
            raise AssertionError(f"unknown token {token}")


def test_gated_function_is_the_registered_one() -> None:
    """Dispatch-style samples gate the function the dict points to."""
    by_cite = {s.cite: s for s in SAMPLES}
    # openai: DISPATCH value thuc_hien_chuyen_tien is the decorated def
    corpus = ast.parse((CORPUS / "openai_fx_quotes/agent.py").read_text(encoding="utf-8"))
    values = [
        v.id
        for n in ast.walk(corpus)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "DISPATCH" for t in n.targets)
        and isinstance(n.value, ast.Dict)
        for v in n.value.values
        if isinstance(v, ast.Name)
    ]
    assert "thuc_hien_chuyen_tien" in values
    assert "thuc_hien_chuyen_tien" in def_names(
        ast.parse(by_cite["openai_fx_quotes/tools.py"].code)
    )
    # anthropic: HANDLERS value mo_khieu_nai
    corpus = ast.parse((CORPUS / "anthropic_dispute_helper/agent.py").read_text(encoding="utf-8"))
    assert "mo_khieu_nai" in ast.unparse(corpus)
    assert "mo_khieu_nai" in def_names(
        ast.parse(by_cite["anthropic_dispute_helper/actions.py"].code)
    )
    # llamaindex: the gated function is the one passed as fn=
    text = (CORPUS / "llamaindex_policy_qa/agent.py").read_text(encoding="utf-8")
    assert "fn=tra_cuu_bieu_phi" in text
    assert "fn=tra_cuu_bieu_phi" in by_cite["llamaindex_policy_qa/agent.py"].code
    # mlflow: "fn" entry points at the gated function
    assert '"fn": mo_tiet_kiem' in by_cite["mlflow_chatagent_savings/tools.py"].code
    assert '"fn": mo_tiet_kiem' in (CORPUS / "mlflow_chatagent_savings/tools.py").read_text(
        encoding="utf-8"
    )


def test_renamed_tool_names_follow_the_registered_name() -> None:
    """@tool("x") and dispatch keys: the gate tool name is the registered name."""
    by_cite = {s.cite: s for s in SAMPLES}
    assert '@tool("khoa_the_tam_thoi")' in by_cite["langchain_card_support/tools.py"].code
    assert '"khoa_the_tam_thoi",' in by_cite["langchain_card_support/tools.py"].code
    assert '"chuyen_tien_ngoai_te",' in by_cite["openai_fx_quotes/tools.py"].code
    assert '"tra_cuu_phi_the",' in by_cite["llamaindex_policy_qa/tools.py"].code


def test_guide_wiring_matches_demo_agents() -> None:
    from supervisor.core.ports import GateHook
    from supervisor.gateway.sdk import HttpGate, InProcessGate, SupervisorBlocked, SupervisorPaused

    text = GUIDE.read_text(encoding="utf-8")
    # builder shape of all three demo agents: gate and tracer_provider keyword parameters
    for agent in ("payments", "customer_service", "credit_prequal"):
        tree = ast.parse((AGENTS / agent / "agent.py").read_text(encoding="utf-8"))
        builder = next(f for f in functions(tree) if f.name == "build_agent")
        params = {a.arg for a in [*builder.args.args, *builder.args.kwonlyargs]}
        assert {"gate", "tracer_provider", "env"} <= params, agent
    # the guide states that same signature for payments
    assert 'build_agent(chat, world, *, gate=None, tracer_provider=None, env="dev")' in text
    # runtime calls the hook with (agent id, version, tool, args, ctx), like supervised_tool
    runtime = (AGENTS / "common" / "runtime.py").read_text(encoding="utf-8")
    assert "self.gate, self.manifest.id, self.manifest.version, tool, args, gate_ctx" in runtime
    # GateHook.check parameters are what the guide lists, and both gates implement them
    want = ["agent_id", "agent_version", "tool_name", "args", "context"]
    for cls in (GateHook, HttpGate, InProcessGate):
        got = [p for p in inspect.signature(cls.check).parameters if p != "self"]
        assert got == want, cls
    for name in want:
        assert f"`{name}`" in text
    # exceptions named in the guide
    assert issubclass(SupervisorPaused, SupervisorBlocked)
    # codemod lines quoted in the guide are what instrument.py inserts
    instrument = (ROOT / "src/supervisor/onboard/instrument.py").read_text(encoding="utf-8")
    assert "# supervisor-onboard: hook" in text and "# supervisor-onboard: hook" in instrument
    assert "gate = gate if gate is not None else supervisor_onboard.default_gate()" in text
    assert "{HOOK_MODULE}.default_gate()" in instrument
    # payments tools named in the baseline policy use the argument names the guide cites
    baseline = (ROOT / "policies" / "baseline.yaml").read_text(encoding="utf-8")
    for arg in ("amount_minor", "from_account_id", "payee_id", "customer_id", "account_id"):
        assert arg in baseline and f"`{arg}`" in text


def test_rubric_table_is_published_exactly() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    for area, weight in (
        ("tracing", 20),
        ("gate_coverage", 30),
        ("tool_inventory", 15),
        ("money_args", 10),
        ("model_identity", 10),
        ("manifest", 10),
        ("hygiene", 5),
    ):
        assert re.search(rf"^\| {area} \| {weight} \|", text, re.M), area
    assert 20 + 30 + 15 + 10 + 10 + 10 + 5 == 100


def test_guide_lists_every_semconv_attribute() -> None:
    from supervisor.recorder import semconv

    text = GUIDE.read_text(encoding="utf-8")
    assert "TODO(lead)" not in text
    assert semconv.spec_version in text
    wanted = {a for attrs in semconv.EMIT.values() for a in attrs} | set(semconv.SUPERVISOR_ATTRS)
    wanted |= {r.semconv for r in semconv.MAPPING}
    missing = sorted(a for a in wanted if f"`{a}`" not in text)
    assert not missing, missing
