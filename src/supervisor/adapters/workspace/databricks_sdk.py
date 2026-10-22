"""``WorkspaceReader`` over a Databricks workspace through ``databricks-sdk``. Read-only.

Lists Databricks Apps, Model Serving endpoints (with their served entities), MLflow registered
models and model versions (Unity Catalog, else the workspace registry), Unity Catalog tables,
functions and connections, Genie spaces, jobs (parameters only) and Vector Search indexes
(WP-G3). OAuth only:
the client comes from ``supervisor.adapters.sql.databricks_rest.make_workspace_client``
(retry budget capped in ``Config``, PAT refused). No create, update or delete call is
made here. Unit tests pass a fake client; the live test runs with ``RUN_DATABRICKS=1``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.config import Settings

MAX_ITEMS = 2000


def _entity(ent: Any, fm: Any, ext: Any) -> dict[str, str]:
    """One served entity: foundation model, external model (with its provider) or custom
    (a registered model and version)."""
    if ext is not None:
        return {
            "kind": "external_model",
            "name": str(getattr(ext, "name", "") or ""),
            "provider": str(_name(getattr(ext, "provider", None)) or ""),
        }
    if fm is not None:
        return {"kind": "foundation_model", "name": str(getattr(fm, "name", "") or "")}
    return {
        "kind": "custom_model",
        "name": str(getattr(ent, "entity_name", None) or getattr(ent, "name", "") or ""),
        "version": str(getattr(ent, "entity_version", "") or ""),
    }


def _is_agent_endpoint(endpoint: Any, task: Any) -> bool:
    """An agent endpoint: task ``agent/...`` (Mosaic AI Agent Framework deploy) or a tag whose
    key says so. Unconfirmed on a live workspace: see docs/live-test-kit.md, check WP-G3."""
    if str(task or "").lower().startswith("agent/"):
        return True
    for tag in getattr(endpoint, "tags", None) or []:
        if str(getattr(tag, "key", "")).lower() in ("agent", "agent_endpoint"):
            return True
    return False


def _strings(value: Any, limit: int = 50, width: int = 200) -> list[str]:
    """Flat list of short strings from a parameter object (dict, list or text)."""
    out: list[str] = []

    def walk(v: Any) -> None:
        if len(out) >= limit or v is None:
            return
        if isinstance(v, Mapping):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, (str, int)) and not isinstance(v, bool):
            out.append(str(v)[:width])

    walk(value)
    return out


def _name(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", None) or getattr(value, "name", None) or value)


class DatabricksWorkspaceReader:
    """Implements ``core.ports.WorkspaceReader`` (plus ``list_apps``)."""

    def __init__(self, client: Any, max_items: int = MAX_ITEMS) -> None:
        self.client = client
        self.max_items = max_items

    @classmethod
    def from_settings(cls, settings: Settings) -> DatabricksWorkspaceReader:
        from supervisor.adapters.sql.databricks_rest import make_workspace_client

        return cls(make_workspace_client(settings))

    def _take(self, items: Any) -> list[Any]:
        out = []
        for i, item in enumerate(items):
            if i >= self.max_items:
                break
            out.append(item)
        return out

    def list_apps(self) -> Sequence[Mapping[str, Any]]:
        apps = self._take(self.client.apps.list())
        return [
            {
                "name": a.name,
                "url": getattr(a, "url", None),
                "description": getattr(a, "description", None),
                "service_principal": getattr(a, "service_principal_name", None),
            }
            for a in apps
        ]

    def list_serving_endpoints(self) -> Sequence[Mapping[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in self._take(self.client.serving_endpoints.list()):
            served: list[str] = []
            entities: list[dict[str, str]] = []
            cfg = getattr(e, "config", None)
            for ent in getattr(cfg, "served_entities", None) or []:
                fm = getattr(ent, "foundation_model", None)
                ext = getattr(ent, "external_model", None)
                served.append(
                    str(
                        getattr(fm, "name", None)
                        or getattr(ext, "name", None)
                        or getattr(ent, "entity_name", None)
                        or getattr(ent, "name", "")
                    )
                )
                entities.append(_entity(ent, fm, ext))
            task = getattr(e, "task", None)
            out.append(
                {
                    "name": e.name,
                    "task": task,
                    "state": _name(getattr(getattr(e, "state", None), "ready", None)),
                    "served": served,
                    # WP-G3: served entities (kind, name, provider, version) and the agent flag.
                    # Names only: no workspace id, URL or creator is copied.
                    "entities": entities,
                    "agent": _is_agent_endpoint(e, task),
                }
            )
        return out

    def list_tables(self, catalog: str, schema: str) -> Sequence[str]:
        tables = self._take(self.client.tables.list(catalog_name=catalog, schema_name=schema))
        return sorted(str(t.full_name or f"{catalog}.{schema}.{t.name}") for t in tables)

    def list_registered_models(self) -> Sequence[Mapping[str, Any]]:
        """MLflow registered models from Unity Catalog and from the workspace (legacy) registry
        (WP24). A workspace can hold both, so both are read; one listing that is refused (no UC
        permission, or the legacy registry is disabled) is skipped. Both refused: the error of
        the UC call is raised, so the caller does not mark known models as gone."""
        out: dict[str, dict[str, Any]] = {}
        errors: list[Exception] = []
        try:
            for m in self._take(self.client.registered_models.list()):
                name = str(m.full_name or m.name)
                out[name] = {"name": name, "registry": "uc"}
        except Exception as exc:  # noqa: BLE001 - e.g. no UC permission: try the legacy registry
            errors.append(exc)
        try:
            for m in self._take(self.client.model_registry.list_models()):
                out.setdefault(str(m.name), {"name": str(m.name), "registry": "workspace"})
        except Exception as exc:  # noqa: BLE001 - legacy registry disabled in a UC-only workspace
            errors.append(exc)
        if len(errors) == 2:
            raise errors[0]
        return [out[k] for k in sorted(out)]

    # ------------------------------------------------------------------ WP-G3 scan sources v2
    # Read only. Each method returns names and short facts: no workspace id, URL, creator or
    # option value is copied. A listing the caller may not read raises; the inventory reports
    # it (exception class only) and does not mark known objects as gone.

    def list_model_versions(
        self, max_models: int = 200, max_versions: int = 20
    ) -> list[dict[str, Any]]:
        """Newest ``max_versions`` versions of each registered model: model name, version,
        aliases (Unity Catalog) or stage (workspace registry). No run id, no storage path."""
        out: list[dict[str, Any]] = []
        try:
            uc = sorted(
                str(m.full_name or m.name) for m in self._take(self.client.registered_models.list())
            )
        except Exception:  # noqa: BLE001 - no UC permission: the legacy registry may still work
            uc = []
        for name in uc[:max_models]:
            versions = sorted(
                self._take(self.client.model_versions.list(full_name=name)),
                key=lambda v: int(getattr(v, "version", 0) or 0),
                reverse=True,
            )[:max_versions]
            for v in versions:
                aliases = [
                    str(getattr(a, "alias_name", a)) for a in getattr(v, "aliases", None) or []
                ]
                out.append(
                    {
                        "model": name,
                        "version": str(getattr(v, "version", "")),
                        "aliases": sorted(aliases),
                        "registry": "uc",
                    }
                )
        try:
            legacy = sorted(
                {str(m.name) for m in self._take(self.client.model_registry.list_models())}
                - set(uc)
            )
        except Exception:  # noqa: BLE001 - legacy registry disabled
            legacy = []
        for name in legacy[:max_models]:
            esc = name.replace("\\", "\\\\").replace("'", "\\'")
            found = self._take(
                self.client.model_registry.search_model_versions(filter=f"name='{esc}'")
            )
            found.sort(key=lambda v: int(getattr(v, "version", 0) or 0), reverse=True)
            for v in found[:max_versions]:
                out.append(
                    {
                        "model": name,
                        "version": str(getattr(v, "version", "")),
                        "stage": str(getattr(v, "current_stage", "") or ""),
                        "registry": "workspace",
                    }
                )
        return out

    def list_genie_spaces(self) -> list[dict[str, Any]]:
        """Genie spaces: title, and the tables the space is attached to when the API says."""
        resp = self.client.genie.list_spaces()
        items = getattr(resp, "spaces", None)
        out = []
        for sp in self._take(items if items is not None else resp):
            title = str(getattr(sp, "title", None) or getattr(sp, "name", None) or "").strip()
            if title:
                tables = [str(t) for t in getattr(sp, "table_identifiers", None) or []]
                out.append({"name": title, "tables": sorted(tables)})
        return out

    def list_jobs(self) -> list[dict[str, Any]]:
        """Jobs with the strings of their parameters and task parameters, so the caller can look
        for an LLM endpoint name. The caller keeps only the endpoint name it matched."""
        out = []
        for j in self._take(self.client.jobs.list(expand_tasks=True)):
            st = getattr(j, "settings", None)
            name = str(getattr(st, "name", None) or "").strip()
            if not name:
                continue
            tasks = []
            for t in getattr(st, "tasks", None) or []:
                nb = getattr(t, "notebook_task", None)
                py = getattr(t, "spark_python_task", None)
                wheel = getattr(t, "python_wheel_task", None)
                if nb is not None:
                    kind, values = "notebook", _strings(getattr(nb, "base_parameters", None))
                elif py is not None:
                    kind, values = "python", _strings(getattr(py, "parameters", None))
                elif wheel is not None:
                    kind = "python_wheel"
                    values = _strings(getattr(wheel, "parameters", None)) + _strings(
                        getattr(wheel, "named_parameters", None)
                    )
                else:
                    kind, values = "other", []
                key = str(getattr(t, "task_key", "") or "")
                tasks.append({"key": key, "kind": kind, "values": values})
            defaults = [
                str(getattr(p, "default", ""))[:200] for p in getattr(st, "parameters", None) or []
            ]
            out.append({"name": name, "tasks": tasks, "parameters": defaults[:50]})
        return out

    def list_vector_indexes(self) -> list[dict[str, Any]]:
        """Vector Search indexes: name, type and the source table of a delta-sync index."""
        out = []
        for ep in self._take(self.client.vector_search_endpoints.list_endpoints()):
            ep_name = str(getattr(ep, "name", "") or "")
            if not ep_name:
                continue
            listing = self.client.vector_search_indexes.list_indexes(endpoint_name=ep_name)
            for ix in self._take(listing):
                name = str(getattr(ix, "name", "") or "")
                if not name:
                    continue
                source = ""
                try:
                    full = self.client.vector_search_indexes.get_index(index_name=name)
                    spec = getattr(full, "delta_sync_index_spec", None)
                    source = str(getattr(spec, "source_table", "") or "")
                except Exception:  # noqa: BLE001 - one unreadable index must not hide the rest
                    source = ""
                out.append(
                    {
                        "name": name,
                        "type": str(_name(getattr(ix, "index_type", None)) or ""),
                        "source_table": source,
                    }
                )
        return out

    def list_functions(self, catalog: str, schema: str) -> list[str]:
        """Unity Catalog functions of one schema (full names). They are agent tools."""
        fns = self._take(self.client.functions.list(catalog_name=catalog, schema_name=schema))
        return sorted(str(f.full_name or f"{catalog}.{schema}.{f.name}") for f in fns)

    def list_connections(self) -> list[dict[str, Any]]:
        """Unity Catalog connections: name, type, and whether it is an MCP connection. Options
        (host, credentials) are read to decide ``mcp`` and are never returned."""
        out = []
        for c in self._take(self.client.connections.list()):
            name = str(getattr(c, "name", "") or "").strip()
            if not name:
                continue
            options = getattr(c, "options", None)
            flag = str(options.get("is_mcp_connection", "")).lower() if options else ""
            out.append(
                {
                    "name": name,
                    "type": str(_name(getattr(c, "connection_type", None)) or ""),
                    "mcp": flag in ("true", "1", "yes"),
                }
            )
        return out
