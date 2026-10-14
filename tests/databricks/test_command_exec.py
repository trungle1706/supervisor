"""Command Execution API runner (guide section 4.3), against a fake REST 1.2 API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from supervisor.config import load_settings
from supervisor.core.errors import ConfigError
from supervisor.databricks.command_exec import (
    SENTINEL,
    CommandExecError,
    CommandRunner,
    check_cells,
    params_cell,
    parse_sentinel,
    resolve_cluster_id,
    sentinel_code,
)
from supervisor.databricks.notebook import (
    SMOKE_NOTEBOOK,
    ddl_block,
    render,
    split_cells,
    with_params,
)
from supervisor.databricks.notebook import (
    main as notebook_main,
)
from supervisor.jobs import cluster_run
from tests.databricks.fakes import FakeCommandApi, error, finished, running


class Clock:
    def __init__(self, step: float = 1.0) -> None:
        self.t = 0.0
        self.step = step

    def monotonic(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += self.step


def runner(api: FakeCommandApi, deadline: float = 100.0, step: float = 1.0) -> CommandRunner:
    c = Clock(step)
    return CommandRunner(
        api.do, "c-1", deadline_s=deadline, poll_s=1.0, sleep=c.sleep, monotonic=c.monotonic
    )


def test_one_context_cells_in_order_sentinel_and_destroy() -> None:
    api = FakeCommandApi(
        rules={
            "x = 1": [running(), finished("")],
            "result =": [finished(f'noise\n{SENTINEL} {{"n": 2}}\n')],
        }
    )
    res = runner(api).run(["x = 1\n", "result = {'n': x + 1}\n" + sentinel_code()])
    assert res.ok and res.exit == {"n": 2}
    assert res.context_destroyed and api.destroyed == ["ctx-1"]
    creates = [c for c in api.calls if c[1] == "/api/1.2/contexts/create"]
    assert len(creates) == 1  # one execution context for all cells
    assert api.executed[0] == "x = 1\n"


def test_stops_at_first_error_and_destroys() -> None:
    api = FakeCommandApi(
        rules={
            "boom": [error("<span>NameError: name 'y' is not defined</span>", "Traceback ...")],
        }
    )
    res = runner(api).run(["a = 1\n", "boom = y\n", "never = 1\n"])
    assert not res.ok and res.failed_cell == 1
    assert "NameError" in res.error and "<span>" not in res.error and "c-1" in res.error
    assert len(api.executed) == 2  # third cell not sent
    assert api.destroyed == ["ctx-1"]


def test_status_error_counts_as_failure() -> None:
    api = FakeCommandApi(rules={"a": [{"status": "Cancelled", "results": None}]})
    res = runner(api).run(["a = 1\n"])
    assert not res.ok and res.cells[0].status == "Cancelled"


def test_overall_deadline_cancels_and_destroys() -> None:
    api = FakeCommandApi(rules={"slow": [running()]})
    res = runner(api, deadline=5).run(["fast = 1\n", "slow = 1\n"])
    assert not res.ok and res.cells[-1].status == "Timeout"
    assert "deadline" in res.error and api.cancelled == ["cmd-2"]
    assert api.destroyed == ["ctx-1"]


def test_cluster_not_running_no_context() -> None:
    api = FakeCommandApi(cluster_state="TERMINATED")
    res = runner(api).run(["a = 1\n"])
    assert not res.ok and "TERMINATED" in res.error and "interactive-only" in res.error
    assert not any(c[1] == "/api/1.2/contexts/create" for c in api.calls)


def test_context_error_status() -> None:
    api = FakeCommandApi(context_statuses=["Error"])
    res = runner(api).run(["a = 1\n"])
    assert not res.ok and "failed to start" in res.error and api.destroyed == ["ctx-1"]


def test_destroy_failure_is_reported_not_raised() -> None:
    api = FakeCommandApi(fail_destroy=True)
    res = runner(api).run(["a = 1\n"])
    assert res.ok and not res.context_destroyed


def test_transport_exception_still_destroys() -> None:
    api = FakeCommandApi()

    def broken(method: str, path: str, **kw: Any) -> Any:
        if path == "/api/1.2/commands/execute":
            raise RuntimeError("Connection aborted")
        return api.do(method, path, **kw)

    r = CommandRunner(broken, "c-1", sleep=lambda s: None)
    res = r.run(["a = 1\n"])
    assert not res.ok and "Connection aborted" in res.error and api.destroyed == ["ctx-1"]


def test_syntax_checked_before_any_call() -> None:
    api = FakeCommandApi()
    with pytest.raises(CommandExecError, match="cell 1: syntax error"):
        runner(api).run(["a = 1\n", "def (:\n"])
    with pytest.raises(CommandExecError, match="magic"):
        check_cells(["%sql SELECT 1"])
    with pytest.raises(CommandExecError, match="no cells"):
        check_cells([])
    assert api.calls == []


def test_params_cell_inlines_values_safely() -> None:
    code = params_cell({"CATALOG": "c'; DROP", "N": 3, "FLAG": True})
    ns: dict[str, Any] = {}
    import ast

    tree = ast.parse(code)  # valid Python
    assert isinstance(tree, ast.Module)
    assert "PARAMS = _supervisor_json.loads(" in code and "CATALOG = PARAMS['CATALOG']" in code
    with pytest.raises(CommandExecError):
        params_cell({"bad-name": 1})
    assert ns == {}


def test_parse_sentinel_last_line_wins() -> None:
    assert parse_sentinel(f'{SENTINEL} 1\nx\n{SENTINEL} {{"a": 1}}') == {"a": 1}
    assert parse_sentinel("nothing") is None
    with pytest.raises(CommandExecError):
        parse_sentinel(f"{SENTINEL} {{broken")


def test_resolve_cluster_by_name_with_paging() -> None:
    api = FakeCommandApi(
        clusters=[
            {"cluster_id": "a1", "cluster_name": "other"},
            {"cluster_id": "b2", "cluster_name": "shared-interactive"},
        ]
    )
    assert resolve_cluster_id(api.do, cluster_id=None, cluster_name="shared-interactive") == "b2"
    assert resolve_cluster_id(api.do, cluster_id="x9", cluster_name=None) == "x9"
    with pytest.raises(ConfigError, match="not found"):
        resolve_cluster_id(api.do, cluster_id="FILL-ME-cluster", cluster_name="nope")
    with pytest.raises(ConfigError, match="DATABRICKS_CLUSTER_NAME"):
        resolve_cluster_id(api.do, cluster_id=None, cluster_name="FILL-ME-x")


# ------------------------------------------------------------------ notebooks + job


def test_split_cells_drops_markdown_and_header() -> None:
    src = (
        "# Databricks notebook source\n# MAGIC %md\n# MAGIC hi\n\n# COMMAND ----------\n"
        "\na = 1\n\n# COMMAND ----------\n\nb = a\n"
    )
    assert split_cells(src) == ["a = 1\n", "b = a\n"]
    with pytest.raises(CommandExecError):
        split_cells("a = 1\n")
    with pytest.raises(CommandExecError, match="magic"):
        split_cells("# Databricks notebook source\n# MAGIC %sql\n# MAGIC SELECT 1\n")


def test_smoke_notebook_is_valid_and_current() -> None:
    text = SMOKE_NOTEBOOK.read_text(encoding="utf-8")
    assert text.startswith("# Databricks notebook source\n")
    assert render(text) == text, "run: uv run python -m supervisor.databricks.notebook"
    assert notebook_main(["--check"]) == 0
    cells = split_cells(text)
    check_cells(cells)  # every code cell parses
    assert "FILL-ME-catalog" in text and "SUPERVISOR-EXIT-JSON: " in text
    replaced = with_params(cells, {"CATALOG": "c", "SCHEMA": "s"})
    assert "FILL-ME-catalog" not in replaced[0] and "CATALOG = PARAMS['CATALOG']" in replaced[0]
    assert ddl_block().count("CREATE TABLE IF NOT EXISTS") == text.count(
        "CREATE TABLE IF NOT EXISTS"
    )


def test_notebook_check_detects_stale(tmp_path: Path) -> None:
    p = tmp_path / "nb.py"
    p.write_text(
        "# Databricks notebook source\n# GENERATED DDL BEGIN\nDDL = []\n# GENERATED DDL END\n",
        encoding="utf-8",
    )
    assert notebook_main(["--check", str(p)]) == 1
    assert notebook_main([str(p)]) == 0 and notebook_main(["--check", str(p)]) == 0


def test_cluster_run_job_with_fake(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    api = FakeCommandApi(rules={"SUPERVISOR-EXIT-JSON": [finished(f'{SENTINEL} {{"failed": 0}}')]})
    nb = tmp_path / "nb.py"
    nb.write_text(
        "# Databricks notebook source\n# SUPERVISOR-PARAMS\nN = 0\n# COMMAND ----------\n"
        "result = {'failed': 0}\nprint('SUPERVISOR-EXIT-JSON: ' + str(N))\n",
        encoding="utf-8",
    )
    res = cluster_run.run(load_settings(), nb, {"N": 5}, runner=runner(api))
    assert res.ok and res.exit == {"failed": 0}
    assert (
        api.executed[0].startswith("import json as _supervisor_json")
        and "N = PARAMS" in api.executed[0]
    )
    assert cluster_run.parse_param("A=1") == ("A", 1)
    assert cluster_run.parse_param("B=true") == ("B", True)
    assert cluster_run.parse_param("C=x=y") == ("C", "x=y")


def test_cluster_run_main_needs_cluster(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    nb = tmp_path / "nb.py"
    nb.write_text("# Databricks notebook source\na = 1\n", encoding="utf-8")

    class Client:
        class api_client:  # noqa: N801
            do = FakeCommandApi().do

        class config:  # noqa: N801
            host = "https://ws.example.invalid"

    s = load_settings()
    with pytest.raises(ConfigError, match="DATABRICKS_CLUSTER_NAME"):
        CommandRunner.from_settings(s, client=Client())
