"""Fakes for the Databricks REST 1.2 Command Execution API and the Files API."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any


class NotFound(Exception):  # same class name as databricks.sdk.errors.NotFound
    error_code = "NOT_FOUND"


class AlreadyExists(Exception):
    error_code = "ALREADY_EXISTS"


class PermissionDenied(Exception):
    error_code = "PERMISSION_DENIED"


@dataclass
class FakeCommandApi:
    """``api_client.do`` stand-in. Commands are answered by the first rule whose key is in
    the code: ``rules[key] = [status dict, ...]`` (the last one repeats)."""

    cluster_state: str = "RUNNING"
    clusters: list[dict[str, Any]] = field(default_factory=list)
    context_statuses: list[str] = field(default_factory=lambda: ["Pending", "Running"])
    rules: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    fail_destroy: bool = False
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    destroyed: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    _commands: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    executed: list[str] = field(default_factory=list)

    def do(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, dict(query or body or {})))
        if path == "/api/2.1/clusters/list":
            page = (query or {}).get("page_token")
            if not page and len(self.clusters) > 1:
                return {"clusters": self.clusters[:1], "next_page_token": "p2"}
            return {"clusters": self.clusters[1:] if page else self.clusters}
        if path == "/api/2.1/clusters/get":
            return {"cluster_id": (query or {})["cluster_id"], "state": self.cluster_state}
        if path == "/api/1.2/contexts/create":
            assert body and body["language"] == "python"
            return {"id": "ctx-1"}
        if path == "/api/1.2/contexts/status":
            st = (
                self.context_statuses.pop(0)
                if len(self.context_statuses) > 1
                else self.context_statuses[0]
            )
            return {"id": "ctx-1", "status": st}
        if path == "/api/1.2/contexts/destroy":
            if self.fail_destroy:
                raise RuntimeError("destroy failed")
            self.destroyed.append(body["contextId"])  # type: ignore[index]
            return {}
        if path == "/api/1.2/commands/execute":
            code = body["command"]  # type: ignore[index]
            self.executed.append(code)
            cid = f"cmd-{len(self.executed)}"
            for key, statuses in self.rules.items():
                if key in code:
                    self._commands[cid] = list(statuses)
                    break
            else:
                self._commands[cid] = [finished("")]
            return {"id": cid}
        if path == "/api/1.2/commands/status":
            q = self._commands[(query or {})["commandId"]]
            return q.pop(0) if len(q) > 1 else q[0]
        if path == "/api/1.2/commands/cancel":
            self.cancelled.append(body["commandId"])  # type: ignore[index]
            return {}
        raise AssertionError(f"unexpected call {method} {path}")


def finished(text: str) -> dict[str, Any]:
    return {"status": "Finished", "results": {"resultType": "text", "data": text}}


def running() -> dict[str, Any]:
    return {"status": "Running"}


def error(summary: str, cause: str = "") -> dict[str, Any]:
    return {
        "status": "Finished",
        "results": {"resultType": "error", "summary": summary, "cause": cause},
    }


@dataclass
class Entry:
    path: str
    name: str
    is_directory: bool = False


@dataclass
class Download:
    contents: Any


class FakeFiles:
    """``WorkspaceClient().files`` stand-in (in-memory)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.deny: set[str] = set()

    def _check(self, path: str) -> None:
        if any(path.startswith(d) for d in self.deny):
            raise PermissionDenied(f"403 PERMISSION_DENIED on {path}")

    def upload(self, file_path: str, contents: Any, *, overwrite: bool | None = None) -> None:
        self._check(file_path)
        if file_path in self.store and not overwrite:
            raise AlreadyExists(f"{file_path} exists")
        self.store[file_path] = contents.read()

    def get_metadata(self, file_path: str) -> dict[str, int]:
        self._check(file_path)
        if file_path not in self.store:
            raise NotFound(file_path)
        return {"content_length": len(self.store[file_path])}

    def download(self, file_path: str) -> Download:
        self._check(file_path)
        if file_path not in self.store:
            raise NotFound(file_path)
        return Download(io.BytesIO(self.store[file_path]))

    def list_directory_contents(self, directory_path: str) -> list[Entry]:
        self._check(directory_path)
        prefix = directory_path.rstrip("/") + "/"
        names = [p for p in self.store if p.startswith(prefix) and "/" not in p[len(prefix) :]]
        if not names:
            raise NotFound(directory_path)
        return [Entry(p, p[len(prefix) :]) for p in sorted(names)]

    def delete(self, file_path: str) -> None:
        self._check(file_path)
        if file_path not in self.store:
            raise NotFound(file_path)
        del self.store[file_path]

    def create_directory(self, directory_path: str) -> None:
        return None
