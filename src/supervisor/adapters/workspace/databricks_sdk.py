"""``WorkspaceReader`` over a Databricks workspace through ``databricks-sdk``. Read-only.

Lists Databricks Apps, Model Serving endpoints, MLflow registered models (Unity Catalog, else
the workspace registry) and Unity Catalog tables. OAuth only:
the client comes from ``supervisor.adapters.sql.databricks_rest.make_workspace_client``
(retry budget capped in ``Config``, PAT refused). No create, update or delete call is
made here. Unit tests pass a fake client; the live test runs with ``RUN_DATABRICKS=1``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.config import Settings

MAX_ITEMS = 2000


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
            out.append(
                {
                    "name": e.name,
                    "task": getattr(e, "task", None),
                    "state": _name(getattr(getattr(e, "state", None), "ready", None)),
                    "served": served,
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
