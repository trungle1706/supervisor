"""config/factory_tools.yaml and config/factory_groups.yaml: strict loaders and the checks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from supervisor.config import REPO_ROOT
from supervisor.factory import caps, registry
from supervisor.factory.schemas import AgentDefinitionV1


def test_shipped_registries_load() -> None:
    tools = registry.load_tools()
    groups = registry.load_groups()
    assert {t.kind for t in tools.tools} == set(caps.TOOL_KINDS)
    assert {g.group_id for g in groups.groups} == set(caps.GROUPS)


def test_every_dimension_has_exactly_one_owner_group() -> None:
    groups = registry.load_groups()
    for dim in caps.DIMENSIONS:
        assert groups.owner_of(dim) is not None, dim


def test_group_roles_exist_in_users_yaml() -> None:
    users = yaml.safe_load((REPO_ROOT / "config" / "users.yaml").read_text(encoding="utf-8"))
    roles_in_use = {r for u in users["users"].values() for r in u["roles"]}
    for g in registry.load_groups().groups:
        for role in g.roles:
            assert role in caps.ROLES
            assert role in roles_in_use, (g.group_id, role)


def test_no_tool_has_a_mode_beyond_read_or_propose() -> None:
    for t in registry.load_tools().tools:
        assert set(t.modes) <= {"read", "propose"}


def _write(tmp_path: Path, doc: object, name: str = "x.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


def _tools_doc() -> dict:
    return yaml.safe_load((REPO_ROOT / "config" / "factory_tools.yaml").read_text(encoding="utf-8"))


def test_tools_unknown_key_is_refused(tmp_path: Path) -> None:
    doc = _tools_doc()
    doc["tools"][0]["command"] = "rm -rf /"
    with pytest.raises(registry.RegistryError, match=r"tools\[0\].*unknown key: command"):
        registry.load_tools(_write(tmp_path, doc))


def test_tools_missing_key_is_refused(tmp_path: Path) -> None:
    doc = _tools_doc()
    del doc["tools"][1]["modes"]
    with pytest.raises(registry.RegistryError, match=r"tools\[1\].*missing key: modes"):
        registry.load_tools(_write(tmp_path, doc))


@pytest.mark.parametrize(
    ("key", "value", "field"),
    [
        ("kind", "run_shell", "kind"),
        ("modes", ["read", "act"], "modes"),
        ("data_class", "secret", "data_class"),
        ("allowed_groups", ["everyone"], "allowed_groups"),
        ("scope", ["internet"], "scope"),
        ("tool_id", "Bad Id", "tool_id"),
    ],
)
def test_tools_vocabulary(tmp_path: Path, key: str, value: object, field: str) -> None:
    doc = _tools_doc()
    doc["tools"][0][key] = value
    with pytest.raises(registry.RegistryError, match=field):
        registry.load_tools(_write(tmp_path, doc))


def test_tools_duplicate_id(tmp_path: Path) -> None:
    doc = _tools_doc()
    doc["tools"][1]["tool_id"] = doc["tools"][0]["tool_id"]
    with pytest.raises(registry.RegistryError, match="defined twice"):
        registry.load_tools(_write(tmp_path, doc))


def test_tools_top_level_strict(tmp_path: Path) -> None:
    doc = _tools_doc()
    doc["extra"] = 1
    with pytest.raises(registry.RegistryError, match="unknown key: extra"):
        registry.load_tools(_write(tmp_path, doc))


def test_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(registry.RegistryError, match="cannot read"):
        registry.load_tools(tmp_path / "missing.yaml")


def _groups_doc() -> dict:
    return yaml.safe_load((REPO_ROOT / "config" / "factory_groups.yaml").read_text("utf-8"))


def test_groups_strict(tmp_path: Path) -> None:
    doc = _groups_doc()
    doc["groups"]["legal"]["tools"] = ["x"]
    with pytest.raises(registry.RegistryError, match=r"groups\.legal.*unknown key: tools"):
        registry.load_groups(_write(tmp_path, doc))


def test_groups_unknown_group_role_and_double_owner(tmp_path: Path) -> None:
    doc = _groups_doc()
    doc["groups"]["sales"] = doc["groups"]["legal"]
    with pytest.raises(registry.RegistryError, match="not a platform group"):
        registry.load_groups(_write(tmp_path, doc))
    doc = _groups_doc()
    doc["groups"]["legal"]["roles"] = ["superuser"]
    with pytest.raises(registry.RegistryError, match="roles"):
        registry.load_groups(_write(tmp_path, doc))
    doc = _groups_doc()
    doc["groups"]["legal"]["dimensions"] = ["model"]
    with pytest.raises(registry.RegistryError, match="already owned"):
        registry.load_groups(_write(tmp_path, doc))


# ------------------------------------------------------------------ check_definition


def checks(agent: dict) -> list[tuple[str, str]]:
    return registry.check_definition(
        AgentDefinitionV1.model_validate(agent), registry.load_tools(), registry.load_groups()
    )


def test_valid_examples_pass_the_registry(agent: dict, loop_agent: dict) -> None:
    assert checks(agent) == []
    assert checks(loop_agent) == []


def test_unknown_tool_id(agent: dict) -> None:
    agent["tools"][0]["tool_id"] = "run_python"
    assert [f for f, _ in checks(agent)] == ["tools[0].tool_id"]


def test_group_may_not_use_the_tool(loop_agent: dict) -> None:
    loop_agent["tools"].append({"tool_id": "search_documents"})
    assert ("tools[2].tool_id", "group cyber may not use search_documents") in checks(loop_agent)


def test_mode_not_allowed_by_the_tool(agent: dict) -> None:
    agent["tools"][0]["mode"] = "propose"
    assert [f for f, _ in checks(agent)] == ["tools[0].mode"]


def test_scope_kind_not_allowed(agent: dict) -> None:
    agent["tools"][0]["scope"] = "documents:space-x"
    assert [f for f, _ in checks(agent)] == ["tools[0].scope"]


def test_group_must_own_the_dimension(agent: dict) -> None:
    agent["dimension_id"] = "ethics"
    assert [f for f, _ in checks(agent)] == ["dimension_id"]
