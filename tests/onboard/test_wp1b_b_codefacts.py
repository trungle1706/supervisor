"""WP1b-B (D08): routes are entrypoints, deepagents is a framework, model family from names.

Regression for the credit-memo benchmark defect: onboarding counted FastAPI route handlers as
agent tools (precision 50 percent), missed `deepagents` and left the model family unknown.
"""

from __future__ import annotations

import json

import pytest

from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.judge.router import FAMILY_ALIASES, normalize_family
from supervisor.onboard import codefacts
from supervisor.onboard.discover import discover
from supervisor.onboard.eval.runner import EvalResult, run_eval
from supervisor.onboard.models import Inventory
from tests.conftest import REPO_ROOT

CORPUS = REPO_ROOT / "data" / "corpus" / "repos"
LABELS = REPO_ROOT / "data" / "corpus" / "labels.yaml"
BASELINE = REPO_ROOT / "data" / "corpus" / "reports" / "wp1b_b_baseline.json"
TOY = CORPUS / "fastapi_deepagents_credit_toy"

REAL_TOOLS = {
    "read_facility",
    "fetch_financials",
    "compute_dscr",
    "search_policy",
    "draft_section",
    "save_memo_draft",
}


@pytest.fixture(scope="module")
def toy() -> Inventory:
    return discover(LocalGitRepoReader(TOY)).inventory


def test_routes_are_entrypoints_not_tools(toy: Inventory) -> None:
    assert {t.name for t in toy.tools} == REAL_TOOLS
    routes = [e for e in toy.entrypoints if e.detail.startswith("route:")]
    assert len(routes) == 5
    assert {e.name for e in routes} == {
        "GET /health",
        "POST /memos",
        "GET /memos/{customer_id}",
        "POST /memos/{customer_id}/review",
        "GET /cases",
    }
    assert all(e.evidence and e.evidence.file == "main.py" for e in routes)


def test_framework_and_model_family(toy: Inventory) -> None:
    assert toy.framework == "deepagents"
    # the endpoint name is only in app.yaml; the code default is a Llama endpoint
    assert toy.model_family == "anthropic"
    assert toy.model_id == "databricks-claude-sonnet-4"
    assert toy.model_family_source == "code"
    assert [c.family for c in toy.llm_calls] == ["anthropic"]


def test_tool_server_routes_stay_tools() -> None:
    """A route under /tools/ is how the model calls a tool server: still a tool, and also listed."""
    inv = discover(LocalGitRepoReader(CORPUS / "fastapi_toolserver_remit")).inventory
    assert {t.name for t in inv.tools} == {"quote_fee", "check_watchlist", "send_remittance"}
    assert len([e for e in inv.entrypoints if e.detail.startswith("route:")]) == 3


@pytest.mark.parametrize(
    ("model", "family"),
    [
        ("databricks-claude-sonnet-4", "anthropic"),
        ("databricks-claude-opus-4-1", "anthropic"),
        ("databricks-meta-llama-3-3-70b-instruct", "meta"),
        ("databricks-llama-4-maverick", "meta"),
        ("databricks-gpt-oss-120b", "openai"),
        ("gpt-4o-mini", "openai"),
        ("o3-mini", "openai"),
        ("us.anthropic.claude-3-5-sonnet-20241022-v2:0", "anthropic"),
        ("anthropic/claude-sonnet-4", "anthropic"),
        ("qwen3.8-27b-int4", "qwen"),
        ("qwen2.5-14b-instruct", "qwen"),
        ("databricks-gemma-3-12b", "google"),
        ("mistral-large", "mistral"),
        ("my-custom-endpoint", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_model_family_names(model: str | None, family: str) -> None:
    assert codefacts.model_family(model) == family


def test_family_uses_the_router_alias_table() -> None:
    """One vocabulary: the family of any aliased token equals the router's normalised family."""
    for token in FAMILY_ALIASES:
        assert codefacts.model_family(f"{token}-x") == normalize_family(token)


def test_env_value_resolves_endpoint_name() -> None:
    src = (
        "import os\nfrom databricks_langchain import ChatDatabricks\n"
        'llm = ChatDatabricks(endpoint=os.environ["EP"])\n'
    )
    facts = codefacts.analyse(
        {
            "a.py": src.splitlines(),
            "app.yaml": ["env:", "  - name: EP", "    value: databricks-gpt-oss-20b"],
        }
    )
    assert [(c.model, c.family) for c in facts.llm_calls] == [("databricks-gpt-oss-20b", "openai")]


def test_env_files_never_yield_credential_values() -> None:
    """Review fix: only non-secret names (endpoint, model) are read from env files. A short
    or odd secret the scrubber misses must still never reach the facts."""
    src = (
        "import os\nfrom langgraph.prebuilt import create_react_agent\n"
        'API_KEY = os.environ["OPENAI_API_KEY"]\nTOK = os.getenv("HF_TOKEN")\n'
        'agent = create_react_agent(os.getenv("MODEL_NAME"), [])\n'
    )
    files = {
        "a.py": src.splitlines(),
        ".env.example": [
            "OPENAI_API_KEY=abc12",
            "HF_TOKEN=hfshort",
            "DB_PASSWORD=x9",
            "MODEL_NAME=databricks-gpt-oss-120b",
        ],
        "app.yaml": ["env:", "  - name: SERVICE_SECRET", "    value: s3cr3t-value"],
    }
    env = codefacts._env_values(files)
    assert env == {"MODEL_NAME": "databricks-gpt-oss-120b"}
    facts = codefacts.analyse(files)
    blob = repr(facts.llm_calls) + repr([vars(f) for f in facts.data_access])
    for secret in ("abc12", "hfshort", "x9", "s3cr3t-value"):
        assert secret not in blob
    assert [(c.provider, c.model) for c in facts.llm_calls] == [
        ("databricks", "databricks-gpt-oss-120b")
    ]


def test_agent_factories_tools_and_dynamic_mcp() -> None:
    src = """
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool

@tool
def a(x: str) -> str:
    return x

@tool
def b(x: str) -> str:
    return x

agent = create_react_agent("anthropic:claude-sonnet-4", tools=[a, b])

async def load(session):
    return await session.list_tools()
"""
    facts = codefacts.analyse({"m.py": src.splitlines()})
    assert {t.name for t in facts.tools} == {"a", "b"}
    assert [(c.provider, c.family, c.model) for c in facts.llm_calls] == [
        ("anthropic", "anthropic", "claude-sonnet-4")
    ]
    assert len(facts.dynamic_tools) == 1


def test_deepagents_subagent_tools() -> None:
    src = """
from deepagents import create_deep_agent
from langchain_core.tools import tool

@tool
def lookup(q: str) -> str:
    return q

sub = {"name": "researcher", "description": "d", "prompt": "p", "tools": [lookup]}
agent = create_deep_agent(model="gpt-4o", tools=[], subagents=[sub])
"""
    facts = codefacts.analyse({"m.py": src.splitlines()})
    assert facts.framework == "deepagents"
    assert {t.name for t in facts.tools} == {"lookup"}
    assert facts.llm_calls[0].family == "openai"


def test_demo_agents_keep_their_manifest_family() -> None:
    inv = discover(
        LocalGitRepoReader(REPO_ROOT / "src" / "supervisor_agents" / "payments")
    ).inventory
    assert inv.model_family_source == "manifest"


# ----------------------------------------------------------------------- eval regression


@pytest.fixture(scope="module")
def result() -> EvalResult:
    return run_eval(CORPUS, LABELS)


def test_eval_does_not_drop_below_the_recorded_baseline(result: EvalResult) -> None:
    base = json.loads(BASELINE.read_text(encoding="utf-8"))["after"]
    for metric, floor in base["min"].items():
        assert result.metrics[metric] >= floor, f"{metric}: {result.metrics[metric]} < {floor}"
    f = result.fields
    assert f["tools"]["precision_ci_bp"][0] >= base["min_ci_low_bp"]["tools_precision"]
    assert f["entrypoints"]["recall_ci_bp"][0] >= base["min_ci_low_bp"]["entrypoints_recall"]
    assert f["model_family"]["accuracy_ci_bp"][0] >= base["min_ci_low_bp"]["model_family_accuracy"]


def test_eval_reports_precision_with_wilson_intervals(result: EvalResult) -> None:
    for name in ("tools", "entrypoints", "llm_calls", "data_access"):
        row = result.fields[name]
        lo, hi = row["precision_ci_bp"]
        assert lo <= row["precision_bp"] <= hi
        lo, hi = row["recall_ci_bp"]
        assert lo <= row["recall_bp"] <= hi
