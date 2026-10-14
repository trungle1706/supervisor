"""WP8: Principal adapters (dev_header, databricks_app) and the current_principal dependency."""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from supervisor.adapters.auth import (
    AuthError,
    AuthPrincipal,
    build_principal_provider,
    current_principal,
    request_user_token,
    set_provider,
)
from supervisor.adapters.auth.base import UserToken
from supervisor.adapters.auth.databricks_app import DatabricksAppPrincipal
from supervisor.adapters.auth.dev_header import DevHeaderPrincipal
from supervisor.config import REPO_ROOT, load_settings
from supervisor.core.errors import ConfigError

_ME = Depends(current_principal)
SECRET = "dapi-NOT-A-REAL-TOKEN-0123456789"


def _auth_file(tmp_path: Path, lookup: str = "none") -> Path:
    p = tmp_path / "auth.yaml"
    p.write_text(
        f"""
service_principal_id: sp-1234
group_lookup: {lookup}
roles:
  reviewer: {{users: [Rev.One@bank.example], groups: [g-reviewers]}}
  approver: {{users: [FILL-ME-approver@bank.example], groups: [g-approvers]}}
  owner: {{users: [owner@bank.example]}}
  auditor: {{users: []}}
  admin: {{users: []}}
""",
        encoding="utf-8",
    )
    return p


def test_dev_users_file_default_and_header() -> None:
    p = DevHeaderPrincipal.from_file(REPO_ROOT / "config" / "users.yaml")
    me, token = p.resolve({}, {})
    assert me.user_id == "reviewer.an" and me.roles == {"reviewer"} and token is None
    assert me.auth_method == "dev_header" and me.kind == "user"
    binh, _ = p.resolve({"x-dev-user": "reviewer.binh"}, {"sv_dev_user": "admin.chi"})
    assert binh.has("approver")
    chi, _ = p.resolve({}, {"sv_dev_user": "admin.chi"})
    assert chi.has("admin")
    with pytest.raises(AuthError):
        p.resolve({"x-dev-user": "mallory"}, {})
    assert p.background().kind == "system"
    owners = {u.user_id for u in p.known_users() if u.has("owner")}
    assert "payops-lead@example.invalid" in owners


def test_dev_header_refused_on_databricks_app() -> None:
    with pytest.raises(ConfigError):
        load_settings(supervisor_mode="databricks_app", auth_kind="dev_header")
    s = load_settings(supervisor_mode="databricks_app", sql_backend="sqlite")
    assert s.effective_auth_kind == "databricks_app"
    assert isinstance(build_principal_provider(s), DatabricksAppPrincipal)
    assert load_settings().effective_auth_kind == "dev_header"


def test_databricks_roles_from_map_and_placeholders_never_match(tmp_path: Path) -> None:
    p = DatabricksAppPrincipal.from_file(_auth_file(tmp_path))
    rev, token = p.resolve(
        {"x-forwarded-email": "rev.one@bank.example", "x-forwarded-access-token": SECRET}, {}
    )
    assert rev.roles == {"reviewer"} and rev.auth_method == "databricks_sso"
    assert isinstance(token, UserToken) and token.reveal() == SECRET
    assert SECRET not in repr(rev) and SECRET not in repr(token) and SECRET not in str(token)
    with pytest.raises(TypeError):
        pickle.dumps(token)
    nobody, _ = p.resolve({"x-forwarded-user": "FILL-ME-approver@bank.example"}, {})
    assert nobody.roles == frozenset()


def test_databricks_service_principal_fallback(tmp_path: Path) -> None:
    p = DatabricksAppPrincipal.from_file(_auth_file(tmp_path))
    sp, token = p.resolve({}, {})
    assert sp.user_id == "sp-1234" and sp.kind == "service_principal" and token is None
    assert sp.auth_method == "databricks_app_sp" and sp.roles == frozenset()
    assert p.background() == sp
    committed = DatabricksAppPrincipal.from_file(REPO_ROOT / "config" / "auth.yaml")
    assert committed.background().user_id == "app-service-principal"  # FILL-ME -> default


def test_group_lookup_uses_token_in_request_only_and_never_logs_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    seen: list[str] = []

    def resolver(host: str, token: UserToken) -> list[str]:
        seen.append(token.reveal())
        return ["g-approvers"]

    p = DatabricksAppPrincipal.from_file(
        _auth_file(tmp_path, "scim_me"), host="https://example.invalid", group_resolver=resolver
    )
    me, _ = p.resolve(
        {"x-forwarded-user": "x@bank.example", "x-forwarded-access-token": SECRET}, {}
    )
    assert me.roles == {"approver"} and seen == [SECRET]

    def broken(host: str, token: UserToken) -> list[str]:
        raise RuntimeError(f"401 for token {token.reveal()}")

    p.group_resolver = broken
    with caplog.at_level(logging.DEBUG):
        me, _ = p.resolve(
            {"x-forwarded-user": "x@bank.example", "x-forwarded-access-token": SECRET}, {}
        )
    assert me.roles == frozenset()
    assert SECRET not in caplog.text and "RuntimeError" in caplog.text


def test_current_principal_dependency(tmp_path: Path) -> None:
    app = FastAPI()

    @app.get("/me")
    def me(principal: AuthPrincipal = _ME) -> dict[str, object]:
        return {"user": principal.user_id, "roles": sorted(principal.roles)}

    set_provider(DatabricksAppPrincipal.from_file(_auth_file(tmp_path)))
    try:
        client = TestClient(app)
        r = client.get(
            "/me",
            headers={
                "X-Forwarded-Email": "rev.one@bank.example",
                "X-Forwarded-Access-Token": SECRET,
            },
        )
        assert r.json() == {"user": "rev.one@bank.example", "roles": ["reviewer"]}
        assert client.get("/me").json()["user"] == "sp-1234"
    finally:
        set_provider(None)
    assert request_user_token  # exported accessor
