"""Command Execution API runner for the shared interactive cluster (bank guide section 4.3).

``jobs/runs/submit`` is refused on the bank's shared cluster ("does not support jobs
workload"), so heavy work runs through execution contexts (REST API 1.2):

* one execution context per run (``POST /api/1.2/contexts/create``);
* one command per cell, so state carries over between cells;
* stop at the first error (``resultType == "error"`` or status ``Error``/``Cancelled``);
* the context is always destroyed in ``finally``;
* one overall deadline across all cells; a running command is cancelled on expiry;
* no widgets, no ``dbutils.notebook.exit``: parameters are inlined into the code
  (:func:`params_cell`) and the result comes back as a sentinel line on the live stdout
  (``SUPERVISOR-EXIT-JSON: {...}``), parsed by :func:`parse_sentinel`.

Code runs as the signed-in user with their Unity Catalog permissions (the security
boundary the bank accepts). The HTTP call is injected (``WorkspaceClient().api_client.do``),
so this module never imports ``databricks``; tests use a fake.
"""

from __future__ import annotations

import ast
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from supervisor.core.errors import ConfigError, SupervisorError

SENTINEL = "SUPERVISOR-EXIT-JSON:"
Do = Callable[..., Any]
_TAG = re.compile(r"<[^>]+>")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DONE = {"Finished", "Error", "Cancelled"}


class CommandExecError(SupervisorError):
    """The runner could not start (bad input, cluster not usable, context failed)."""


@dataclass
class CellResult:
    index: int
    status: str  # Finished | Error | Cancelled | Timeout
    result_type: str  # text | table | error | ...
    output: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "Finished" and self.result_type != "error"


@dataclass
class RunResult:
    cluster_id: str
    cells: list[CellResult] = field(default_factory=list)
    exit: Any = None  # parsed sentinel payload, or None
    error: str = ""  # first failure, self-diagnosing
    context_destroyed: bool = False

    @property
    def ok(self) -> bool:
        return not self.error and all(c.ok for c in self.cells)

    @property
    def failed_cell(self) -> int | None:
        for c in self.cells:
            if not c.ok:
                return c.index
        return None


# --------------------------------------------------------------------------- code helpers


def params_cell(params: Mapping[str, Any]) -> str:
    """Python code that defines ``PARAMS`` and one variable per key (inline parameters)."""
    for key in params:
        if not _IDENT.match(key):
            raise CommandExecError(f"parameter name must be a Python identifier: {key!r}")
    blob = json.dumps(dict(params), sort_keys=True, ensure_ascii=True)
    lines = ["import json as _supervisor_json", f"PARAMS = _supervisor_json.loads({blob!r})"]
    lines += [f"{k} = PARAMS[{k!r}]" for k in sorted(params)]
    return "\n".join(lines) + "\n"


def sentinel_code(expr: str = "result") -> str:
    """Python code that prints ``expr`` as the sentinel line on the live ``sys.stdout``."""
    return (
        "import json as _supervisor_json, sys as _supervisor_sys\n"
        f"print({SENTINEL!r} + ' ' + _supervisor_json.dumps({expr}, default=str, "
        "sort_keys=True), file=_supervisor_sys.stdout, flush=True)\n"
    )


def parse_sentinel(text: str) -> Any:
    """Payload of the LAST sentinel line in ``text``; None when there is none."""
    found = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(SENTINEL):
            found = line[len(SENTINEL) :].strip()
    if found is None:
        return None
    try:
        return json.loads(found)
    except ValueError as exc:
        raise CommandExecError(f"sentinel line is not valid JSON: {found[:200]}") from exc


def check_cells(cells: Sequence[str]) -> None:
    """Syntax-check Python cells before any remote call (``ast.parse``, never run)."""
    if not cells:
        raise CommandExecError("no cells to run")
    for i, code in enumerate(cells):
        if code.lstrip().startswith("%"):
            raise CommandExecError(f"cell {i}: magic commands (%sql, %pip, ...) are not supported")
        try:
            ast.parse(code, filename=f"<cell {i}>")
        except SyntaxError as exc:
            raise CommandExecError(f"cell {i}: syntax error line {exc.lineno}: {exc.msg}") from exc


def _clean(text: Any, limit: int = 4000) -> str:
    out = _TAG.sub("", str(text or ""))
    out = out.encode("ascii", "backslashreplace").decode("ascii")
    return out if len(out) <= limit else "..." + out[-limit:]


# --------------------------------------------------------------------------- cluster


def resolve_cluster_id(do: Do, *, cluster_id: str | None, cluster_name: str | None) -> str:
    """Cluster id from settings: the id as given, or the name looked up as this identity."""
    from supervisor.config import is_placeholder

    if not is_placeholder(cluster_id):
        return str(cluster_id)
    if is_placeholder(cluster_name):
        raise ConfigError("set DATABRICKS_CLUSTER_NAME (or DATABRICKS_CLUSTER_ID) in .env")
    token: str | None = None
    while True:
        query: dict[str, Any] = {"page_size": 100}
        if token:
            query["page_token"] = token
        resp = do("GET", "/api/2.1/clusters/list", query=query) or {}
        for c in resp.get("clusters", []) or []:
            if c.get("cluster_name") == cluster_name:
                return str(c["cluster_id"])
        token = resp.get("next_page_token")
        if not token:
            break
    raise ConfigError(
        f"cluster named {cluster_name!r} not found or not visible to this identity "
        "(check the workspace host and your cluster permissions)"
    )


# --------------------------------------------------------------------------- runner


class CommandRunner:
    """Run Python cells in one execution context on an interactive cluster."""

    def __init__(
        self,
        do: Do,
        cluster_id: str,
        *,
        deadline_s: float = 1800.0,
        poll_s: float = 1.0,
        host: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._do = do
        self.cluster_id = cluster_id
        self.deadline_s = float(deadline_s)
        self.poll_s = poll_s
        self.host = host
        self._sleep = sleep
        self._monotonic = monotonic

    def _where(self) -> str:
        return f"cluster {self.cluster_id} on {self.host or '(configured host)'}"

    def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            return self._do(method, path, **kw) or {}
        except Exception as exc:  # noqa: BLE001 - SDK errors are not imported here
            msg = _clean(f"{type(exc).__name__}: {exc}", 500)
            if "does not support jobs workload" in msg.lower():
                msg += " -- this runner uses execution contexts, not Jobs; report this"
            raise CommandExecError(f"{method} {path} failed on {self._where()}: {msg}") from exc

    def _left(self, start: float) -> float:
        return self.deadline_s - (self._monotonic() - start)

    def _check_cluster(self) -> None:
        info = self._call("GET", "/api/2.1/clusters/get", query={"cluster_id": self.cluster_id})
        state = str(info.get("state") or "UNKNOWN")
        if state != "RUNNING":
            raise CommandExecError(
                f"{self._where()} is {state}, not RUNNING. Start it in the workspace UI "
                "(Compute) and retry; the shared cluster is interactive-only"
            )

    def _create_context(self, start: float) -> str:
        resp = self._call(
            "POST",
            "/api/1.2/contexts/create",
            body={"clusterId": self.cluster_id, "language": "python"},
        )
        ctx = str(resp.get("id") or "")
        if not ctx:
            raise CommandExecError(f"no execution context id from {self._where()}")
        while True:
            st = self._call(
                "GET",
                "/api/1.2/contexts/status",
                query={"clusterId": self.cluster_id, "contextId": ctx},
            )
            status = str(st.get("status") or "")
            if status == "Running":
                return ctx
            if status == "Error":
                self._destroy(ctx)
                raise CommandExecError(f"execution context failed to start on {self._where()}")
            if self._left(start) <= 0:
                self._destroy(ctx)
                raise CommandExecError(
                    f"execution context not ready before the deadline on {self._where()}"
                )
            self._sleep(self.poll_s)

    def _destroy(self, ctx: str) -> bool:
        try:
            self._do(
                "POST",
                "/api/1.2/contexts/destroy",
                body={"clusterId": self.cluster_id, "contextId": ctx},
            )
        except Exception:  # noqa: BLE001 - best effort; the run result matters more
            return False
        return True

    def _run_cell(self, ctx: str, index: int, code: str, start: float) -> CellResult:
        resp = self._call(
            "POST",
            "/api/1.2/commands/execute",
            body={
                "clusterId": self.cluster_id,
                "contextId": ctx,
                "language": "python",
                "command": code,
            },
        )
        cmd = str(resp.get("id") or "")
        query = {"clusterId": self.cluster_id, "contextId": ctx, "commandId": cmd}
        while True:
            st = self._call("GET", "/api/1.2/commands/status", query=query)
            status = str(st.get("status") or "")
            if status in _DONE:
                break
            if self._left(start) <= 0:
                try:
                    self._do(
                        "POST",
                        "/api/1.2/commands/cancel",
                        body={"clusterId": self.cluster_id, "contextId": ctx, "commandId": cmd},
                    )
                except Exception:  # noqa: BLE001,S110 - best effort
                    pass
                return CellResult(
                    index,
                    "Timeout",
                    "error",
                    error=f"overall deadline of {self.deadline_s:.0f} s passed in cell {index}; "
                    "command cancelled (raise DATABRICKS_COMMAND_DEADLINE_S)",
                )
            self._sleep(self.poll_s)
        results = st.get("results") or {}
        rtype = str(results.get("resultType") or ("error" if status != "Finished" else "text"))
        if rtype == "error" or status != "Finished":
            detail = results.get("summary") or results.get("cause") or status
            cause = results.get("cause") or ""
            text = _clean(detail, 800) + (("\n" + _clean(cause, 3000)) if cause else "")
            return CellResult(index, status, "error", error=text)
        data = results.get("data")
        output = data if isinstance(data, str) else json.dumps(data, default=str)
        return CellResult(index, status, rtype, output=_clean(output, 200_000))

    def run(self, cells: Sequence[str]) -> RunResult:
        """Run ``cells`` in order in one context. Never leaves a context behind."""
        check_cells(cells)
        start = self._monotonic()
        result = RunResult(self.cluster_id)
        ctx: str | None = None
        try:
            self._check_cluster()
            ctx = self._create_context(start)
            for i, code in enumerate(cells):
                cell = self._run_cell(ctx, i, code, start)
                result.cells.append(cell)
                if not cell.ok:
                    result.error = f"cell {i} failed on {self._where()}: {cell.error}"
                    break
            text = "\n".join(c.output for c in result.cells if c.output)
            result.exit = parse_sentinel(text)
        except CommandExecError as exc:
            result.error = str(exc)
        finally:
            if ctx is not None:
                result.context_destroyed = self._destroy(ctx)
        return result

    @classmethod
    def from_settings(cls, settings: Any, client: Any = None) -> CommandRunner:
        if client is None:
            from supervisor.adapters.sql.databricks_rest import make_workspace_client

            client = make_workspace_client(settings)
        do = client.api_client.do
        cluster_id = resolve_cluster_id(
            do,
            cluster_id=settings.databricks_cluster_id,
            cluster_name=settings.databricks_cluster_name,
        )
        host = getattr(getattr(client, "config", None), "host", None) or settings.databricks_host
        return cls(do, cluster_id, deadline_s=settings.databricks_command_deadline_s, host=host)
