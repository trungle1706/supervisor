"""WP17 dependency / supply-chain packs: parsers, version compare and the six runners."""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.assurance import depfiles, versions
from supervisor.assurance.model import EvalPack, ModelDependency, RunnerOutput
from supervisor.assurance.runners import deps as R
from tests.assurance.fakes import FakeAgent, FakeJudge, FakeTraces, ctx
from tests.conftest import REPO_ROOT

PACK_IDS = [
    "sbom_cyclonedx",
    "osv_offline",
    "licence_allowlist",
    "pin_hash_check",
    "model_dependency_inventory",
    "mcp_tool_manifest_drift",
]
FIX = REPO_ROOT / "tests" / "assurance" / "fixtures"
SYN = REPO_ROOT / "data" / "assurance" / "synthetic"
NOW = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
RUNNERS = {
    "sbom_cyclonedx": R.SbomRunner,
    "osv_offline": R.OsvRunner,
    "licence_allowlist": R.LicenceRunner,
    "pin_hash_check": R.PinHashRunner,
    "model_dependency_inventory": R.ModelInventoryRunner,
    "mcp_tool_manifest_drift": R.McpDriftRunner,
}


def pack(pack_id: str) -> EvalPack:
    path = REPO_ROOT / "src" / "supervisor" / "assurance" / "packs" / f"{pack_id}.yaml"
    return EvalPack.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def run(pack_id: str, target: Any, **kw: Any) -> RunnerOutput:
    kw.setdefault("now", NOW)
    return RUNNERS[pack_id]().run(pack(pack_id), ctx(target, **kw))


def verdicts(pack_id: str, out: RunnerOutput) -> dict[str, str]:
    """pass / warn / fail per thresholded metric (the engine does this in production)."""
    p = pack(pack_id)
    res: dict[str, str] = {}
    for t in p.thresholds:
        v = out.metrics.get(t.metric)
        if v is None:
            res[t.metric] = "na"
            continue
        if p.metric(t.metric).direction == "higher_better":
            res[t.metric] = "pass" if v >= t.go else "fail" if v < t.no_go else "warn"
        else:
            res[t.metric] = "pass" if v <= t.go else "fail" if v > t.no_go else "warn"
    return res


def agent_with(files: list[Path], **kw: Any) -> FakeAgent:
    return FakeAgent(deps=files, **kw)


# --------------------------------------------------------------------------- manifests


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_manifest_validates(pack_id: str) -> None:
    p = pack(pack_id)
    assert p.dimension == "dependency"
    assert p.runner.endswith(f":{RUNNERS[pack_id].__name__}")
    assert "ASI04" in p.maps_to.owasp_agentic


def test_launch_gates() -> None:
    gates = {i: pack(i).launch_gate for i in PACK_IDS}
    assert gates == {
        "sbom_cyclonedx": "advisory",
        "osv_offline": "advisory",
        "licence_allowlist": "required",
        "pin_hash_check": "required",
        "model_dependency_inventory": "advisory",
        "mcp_tool_manifest_drift": "required",
    }


# --------------------------------------------------------------------------- versions


def test_version_order() -> None:
    order = ["1.0.dev1", "1.0a1", "1.0b2", "1.0rc1", "1.0", "1.0.post1", "1.0.1", "1!0.1"]
    keys = [versions.parse(v) for v in order]
    assert all(k is not None for k in keys)
    assert keys == sorted(keys)
    assert versions.equal("1.0", "1.0.0")
    assert versions.parse("not a version") is None
    assert versions.compare("2.0", "x") is None


def test_range_events() -> None:
    ev = [{"introduced": "1.0"}, {"fixed": "1.5"}, {"introduced": "2.0"}, {"last_affected": "2.2"}]
    assert not versions.in_ecosystem_range("0.9", ev)
    assert versions.in_ecosystem_range("1.0", ev)
    assert not versions.in_ecosystem_range("1.5", ev)
    assert versions.in_ecosystem_range("2.2", ev)
    assert not versions.in_ecosystem_range("2.2.1", ev)
    assert versions.in_ecosystem_range("0.0.1", [{"introduced": "0"}])
    assert not versions.in_ecosystem_range("garbage", [{"introduced": "0"}])


# --------------------------------------------------------------------------- parsers


def test_real_uv_lock_is_pinned_and_hashed() -> None:
    ds = depfiles.load_depset([REPO_ROOT / "uv.lock"])
    assert ds.lock_present and not ds.errors
    assert len(ds.components) > 50
    assert all(c.pinned for c in ds.components)
    assert [c.name for c in ds.components if not c.hashed] == []
    assert "supervisor" not in {c.name for c in ds.components}  # the project itself
    direct = {c.name for c in ds.components if c.is_direct}
    assert {"fastapi", "pydantic", "pyyaml"} <= direct


def test_requirements_parser() -> None:
    bad = depfiles.parse_requirements((FIX / "pin_hash_check" / "requirements_bad.txt").read_text())
    names = {c.name: c for c in bad}
    assert set(names) == {"fastapi", "httpx", "pydantic", "requests", "syn-lib"}
    assert not any(c.pinned or c.hashed for c in bad)
    assert names["syn-lib"].source == "git"
    good = depfiles.parse_requirements(
        (FIX / "pin_hash_check" / "requirements_good.txt").read_text()
    )
    by = {c.name: c for c in good}
    assert by["fastapi"].version == "0.115.0" and len(by["fastapi"].hashes) == 2
    assert by["pydantic"].version == "2.7.1" and by["pydantic"].hashed
    assert "my-lib-name" in by  # PEP 503 normalisation


def test_poetry_pipfile_and_pyproject(tmp_path: Path) -> None:
    poetry = depfiles.parse_poetry_lock((FIX / "sbom_cyclonedx" / "poetry.lock").read_text())
    assert {c.name for c in poetry} == {"syn-poetry-lib", "syn-git-lib"}
    assert [c.name for c in poetry if c.hashed] == ["syn-poetry-lib"]
    pipf = depfiles.parse_pipfile_lock((FIX / "sbom_cyclonedx" / "Pipfile.lock").read_text())
    by = {c.name: c for c in pipf}
    assert by["syn-pipenv-lib"].version == "3.1.0" and len(by["syn-pipenv-lib"].hashes) == 2
    assert not by["syn-loose-lib"].pinned
    pp = tmp_path / "pyproject.toml"
    pp.write_text(
        '[project]\nname="x"\nversion="1"\ndependencies=["a-b>=1","c==2.0"]\n'
        '[dependency-groups]\ndev=["d>=3", {include-group="other"}]\n',
        encoding="utf-8",
    )
    ds = depfiles.load_depset([pp])
    assert ds.declared_only and not ds.lock_present
    assert {c.name: c.pinned for c in ds.components} == {"a-b": False, "c": True, "d": False}
    assert not any(c.hashed for c in ds.components)


def test_bad_file_does_not_raise(tmp_path: Path) -> None:
    broken = tmp_path / "uv.lock"
    broken.write_text("this is = = not toml", encoding="utf-8")
    ds = depfiles.load_depset([broken, tmp_path / "missing.lock", tmp_path / "notes.md"])
    assert not ds.components and len(ds.errors) == 3


# --------------------------------------------------------------------------- pin_hash_check


def test_pin_hash_good_real_repo() -> None:
    out = run("pin_hash_check", FakeAgent())
    assert out.status == "ok"
    assert out.metrics == {"unpinned_bp": 0, "unhashed_bp": 0, "lock_present": 1}
    assert set(verdicts("pin_hash_check", out).values()) == {"pass"}


def test_pin_hash_bad_requirements() -> None:
    out = run("pin_hash_check", agent_with([FIX / "pin_hash_check" / "requirements_bad.txt"]))
    assert out.metrics["unpinned_bp"] == 10000 and out.metrics["unhashed_bp"] == 10000
    assert out.metrics["lock_present"] == 0
    assert set(verdicts("pin_hash_check", out).values()) == {"fail"}
    assert "requests" in out.details["unpinned"]


def test_pin_hash_repo_like_requirements_target() -> None:
    """A RepoAgentTarget-like fake: onboarded agent with requirements.txt + pyproject."""
    good = agent_with([FIX / "pin_hash_check" / "requirements_good.txt"], target_id="repo:agent_x")
    out = run("pin_hash_check", good)
    assert out.metrics == {"unpinned_bp": 0, "unhashed_bp": 0, "lock_present": 1}
    assert out.dataset_id == "deps:repo:agent_x" and out.is_mock


def test_pin_hash_pyproject_only_is_declared(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname="x"\nversion="1"\ndependencies=["a>=1"]\n', encoding="utf-8")
    out = run("pin_hash_check", agent_with([pp]))
    assert out.metrics["unpinned_bp"] == 10000 and out.metrics["lock_present"] == 0
    assert out.details["declared_only"] is True


def test_pin_hash_synthetic_known_answer() -> None:
    out = run("pin_hash_check", FakeAgent(), data_mode="synthetic")
    assert out.data_mode == "synthetic" and out.n_items == 7
    assert out.metrics["unpinned_bp"] == 0 and out.metrics["unhashed_bp"] == 1428
    assert out.details["unhashed"] == ["syn-theta"]


def test_dep_packs_skip_paths() -> None:
    nofiles = agent_with([])
    for pid in ("pin_hash_check", "sbom_cyclonedx", "licence_allowlist"):
        assert run(pid, nofiles).status == "skip"
        assert run(pid, FakeTraces()).status == "skip"
        assert run(pid, FakeAgent(), data_mode="vendored").status == "skip"
        lacking = FakeAgent(capabilities=frozenset({"chat"}))
        assert "capability" in run(pid, lacking).skip_reason


# --------------------------------------------------------------------------- sbom


def test_sbom_structure_and_determinism(tmp_path: Path) -> None:
    out = run("sbom_cyclonedx", FakeAgent(target_id="agent:demo"), extras={"out_dir": tmp_path})
    assert out.status == "ok"
    assert out.metrics["components_with_purl_bp"] == 10000
    assert out.metrics["components_with_hash_bp"] == 10000
    assert out.metrics["components_count"] > 50
    assert set(verdicts("sbom_cyclonedx", out).values()) == {"pass"}
    f = tmp_path / "sbom-agent_demo.cdx.json"
    assert out.details["sbom_file"] == f.name
    doc = json.loads(f.read_text(encoding="utf-8"))
    assert R.validate_sbom(doc) == []
    assert {"bomFormat", "specVersion", "serialNumber", "version", "metadata", "components"} <= set(
        doc
    )
    assert doc["metadata"]["timestamp"] == "2026-10-15T08:00:00Z"
    c0 = doc["components"][0]
    assert c0["type"] == "library" and c0["purl"] == f"pkg:pypi/{c0['name']}@{c0['version']}"
    assert all(len(h["content"]) == 64 for h in c0["hashes"])
    again = run("sbom_cyclonedx", FakeAgent(target_id="agent:demo"))
    assert again.details["serial_number"] == doc["serialNumber"]  # content-derived
    assert again.details["sbom_file"] == ""  # no out_dir -> nothing written


def test_sbom_validator_catches_problems() -> None:
    assert "bomFormat" in R.validate_sbom({})
    doc = R.build_sbom(depfiles.parse_requirements("a==1 --hash=sha256:" + "a" * 64), "t", NOW)
    assert R.validate_sbom(doc) == []
    doc["components"][0]["hashes"][0]["content"] = "zz"
    assert "components[0].hashes" in R.validate_sbom(doc)


def test_sbom_unpinned_lowers_purl_metric() -> None:
    out = run("sbom_cyclonedx", agent_with([FIX / "pin_hash_check" / "requirements_bad.txt"]))
    assert out.metrics["components_with_purl_bp"] == 0
    assert set(verdicts("sbom_cyclonedx", out).values()) == {"fail"}


def test_sbom_poetry_and_pipenv_fixtures() -> None:
    files = [FIX / "sbom_cyclonedx" / "poetry.lock", FIX / "sbom_cyclonedx" / "Pipfile.lock"]
    out = run("sbom_cyclonedx", agent_with(files))
    assert out.metrics["components_count"] == 5
    assert out.metrics["components_with_hash_bp"] == 6000  # 3 of 5 carry hashes


# --------------------------------------------------------------------------- osv


def test_osv_skip_without_snapshot() -> None:
    for mode in ("auto", "bank"):
        out = run("osv_offline", FakeAgent(), data_mode=mode)
        assert out.status == "skip"
        assert out.skip_reason == "no offline OSV snapshot: set OSV_DB_PATH"
    assert run("osv_offline", FakeAgent(), osv_db_path=Path("/nonexistent/x")).status == "skip"


def test_osv_synthetic_known_answers() -> None:
    out = run("osv_offline", FakeAgent(), data_mode="synthetic")
    assert out.status == "ok" and out.data_mode == "synthetic"
    assert out.metrics == {
        "vulnerable_components": 3,
        "critical_high_count": 2,
        "advisories_matched": 3,  # alpha: two aliased advisories count once
    }
    hit = {m["component"]: m for m in out.details["matches"]}
    assert set(hit) == {"syn-alpha", "syn-eps", "syn-gamma"}
    assert hit["syn-alpha"]["advisories"] == ["SYN-2026-0001"]
    assert hit["syn-eps"]["severity"] == "CRITICAL" and hit["syn-gamma"]["severity"] == "LOW"
    assert out.details["snapshot_withdrawn_ignored"] == 1
    assert "proves the matcher" in out.details["note"]
    assert set(verdicts("osv_offline", out).values()) == {"fail"}


def test_osv_good_real_repo_against_synthetic_snapshot() -> None:
    out = run("osv_offline", FakeAgent(), osv_db_path=SYN / "osv")
    assert out.status == "ok" and out.data_mode == "bank_supplied_path"
    assert out.metrics == {
        "vulnerable_components": 0,
        "critical_high_count": 0,
        "advisories_matched": 0,
    }
    assert set(verdicts("osv_offline", out).values()) == {"pass"}


def test_osv_bad_target_hits_and_zip(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text(
        "syn_alpha==1.2.0 --hash=sha256:" + "a" * 64 + "\n"
        "syn-beta==2.0.0 --hash=sha256:" + "b" * 64 + "\n"
        "syn-unpinned>=1\n",
        encoding="utf-8",
    )
    target = agent_with([req])
    as_dir = run("osv_offline", target, osv_db_path=SYN / "osv")
    assert as_dir.metrics["vulnerable_components"] == 1
    assert as_dir.metrics["critical_high_count"] == 1
    assert as_dir.details["unpinned_not_matched"] == 1  # unpinned cannot be matched
    z = tmp_path / "all.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in sorted((SYN / "osv").glob("*.json")):
            zf.write(p, f"PyPI/{p.name}")
    as_zip = run("osv_offline", target, osv_db_path=z)
    assert as_zip.metrics == as_dir.metrics
    assert as_zip.dataset_sha256 == as_dir.dataset_sha256 != ""
    assert set(verdicts("osv_offline", as_zip).values()) == {"fail"}


def test_osv_empty_snapshot_skips(tmp_path: Path) -> None:
    (tmp_path / "junk.json").write_text("{not json", encoding="utf-8")
    assert run("osv_offline", FakeAgent(), osv_db_path=tmp_path).status == "skip"


# --------------------------------------------------------------------------- licences


def test_licence_expression_eval() -> None:
    allow = {"mit", "apache-2.0"}
    ev = R.eval_expression
    assert ev("MIT", allow) is True
    assert ev("GPL-3.0-only", allow) is False
    assert ev("MIT OR GPL-3.0-only", allow) is True
    assert ev("MIT AND GPL-3.0-only", allow) is False
    assert ev("(MIT OR GPL-2.0-only) AND Apache-2.0", allow) is True
    assert ev("LicenseRef-Proprietary", allow) is None
    assert ev("GPL-2.0-only WITH Classpath-exception-2.0", allow) is False
    assert ev("UNKNOWN", allow) is None


def test_licence_metadata_mapping() -> None:
    class Meta:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

        def get(self, k: str, default: Any = None) -> Any:
            return self.kw.get(k, default)

        def get_all(self, k: str) -> Any:
            return self.kw.get(k + "s") or None

    assert R.licence_expression(Meta(**{"License-Expression": "MIT"})) == "MIT"
    cls = [
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
    ]
    assert R.licence_expression(Meta(Classifiers=cls)) == "MIT OR Apache-2.0"
    assert R.licence_expression(Meta(License="GNU Lesser General Public License v3")) == (
        "LGPL-3.0-only"
    )
    assert R.licence_expression(Meta(License="BSD 2-Clause")) == "BSD-2-Clause"
    assert R.licence_expression(Meta()) == "UNKNOWN"


def test_licence_good_real_repo_and_gpl_override(tmp_path: Path) -> None:
    good = run("licence_allowlist", FakeAgent())
    assert good.status == "ok" and good.metrics["checked_count"] > 50
    assert good.metrics["unknown_licence_bp"] is not None
    bank = tmp_path / "licence_allowlist"
    bank.mkdir()
    shutil.copy(FIX / "licence_allowlist" / "licences_gpl.json", bank / "licences.json")
    bad = run("licence_allowlist", FakeAgent(), data_root=tmp_path)
    assert bad.metrics["disallowed_count"] == good.metrics["disallowed_count"] + 1
    assert {"name": "pydantic", "licence": "GPL-3.0-only"} in bad.details["disallowed"]
    assert "jinja2" in bad.details["unknown_licence"]
    assert verdicts("licence_allowlist", bad)["disallowed_count"] == "fail"
    assert all(set(d) == {"name", "licence"} for d in bad.details["disallowed"])


def test_licence_allow_list_is_configurable() -> None:
    strict = run("licence_allowlist", FakeAgent(), licence_allow=("Nothing-Allowed",))
    assert strict.metrics["disallowed_count"] > 0
    assert strict.details["allow_list"] == ["Nothing-Allowed"]


def test_licence_synthetic_known_answer() -> None:
    out = run("licence_allowlist", FakeAgent(), data_mode="synthetic")
    assert out.metrics["disallowed_count"] == 1  # syn-gamma GPL-3.0-only
    assert out.metrics["checked_count"] == 7
    assert out.metrics["unknown_licence_bp"] == 1428  # syn-theta has no entry
    assert out.details["disallowed"] == [{"name": "syn-gamma", "licence": "GPL-3.0-only"}]


# --------------------------------------------------------------------------- models


def md(**kw: Any) -> ModelDependency:
    base: dict[str, Any] = {
        "role": "agent",
        "vendor": "VendorA",
        "family": "fam-a",
        "model_id": "a-1",
        "version_pinned": True,
        "hosting_region": "VN",
        "is_mock": False,
    }
    return ModelDependency(**{**base, **kw})


def test_models_good_and_bad() -> None:
    good = FakeAgent(
        models=[
            md(),
            md(role="judge_t1", vendor="VendorB", family="fam-b", model_id="b-1"),
        ]
    )
    out = run("model_dependency_inventory", good)
    assert out.metrics == {
        "models_count": 2,
        "unpinned_models": 0,
        "unknown_region_count": 0,
        "max_vendor_share_bp": 5000,
        "mock_models": 0,
    }
    assert set(verdicts("model_dependency_inventory", out).values()) == {"pass"}
    bad = FakeAgent(
        models=[
            md(version_pinned=False),
            md(model_id="a-2", hosting_region=None, is_mock=True),
            md(model_id="a-3", hosting_region="unknown"),
            md(vendor="vendora", model_id="a-4"),
        ]
    )
    out = run("model_dependency_inventory", bad)
    assert out.metrics["unpinned_models"] == 1 and out.metrics["unknown_region_count"] == 2
    assert out.metrics["max_vendor_share_bp"] == 10000  # vendor names compare case-insensitively
    assert out.metrics["mock_models"] == 1
    v = verdicts("model_dependency_inventory", out)
    assert v["unpinned_models"] == "fail" and v["unknown_region_count"] == "fail"


def test_models_judge_target_and_skips() -> None:
    judge = FakeJudge(score_fn=lambda e: {}, models=[md(role="judge_t1")])
    assert run("model_dependency_inventory", judge).metrics["models_count"] == 1
    assert run("model_dependency_inventory", FakeAgent()).status == "skip"  # empty inventory
    assert run("model_dependency_inventory", FakeTraces()).status == "skip"
    lacking = FakeAgent(capabilities=frozenset({"chat"}), models=[md()])
    assert run("model_dependency_inventory", lacking).status == "skip"
    syn = run("model_dependency_inventory", FakeAgent(), data_mode="synthetic")
    assert syn.metrics["unpinned_models"] == 1 and syn.metrics["unknown_region_count"] == 1


# --------------------------------------------------------------------------- mcp drift


def load_manifest(name: str) -> dict[str, Any]:
    return json.loads((FIX / "mcp_tool_manifest_drift" / name).read_text(encoding="utf-8"))


def test_mcp_good_manifest() -> None:
    m = load_manifest("manifest_good.json")
    m["declared_hash"] = R.set_hash(R._flatten_tools(m))
    out = run("mcp_tool_manifest_drift", FakeAgent(tools=m))
    assert out.metrics == {"drift_count": 0, "undeclared_tools": 0, "poisoned_descriptions": 0}
    assert set(verdicts("mcp_tool_manifest_drift", out).values()) == {"pass"}
    assert out.n_items == 3 and out.details["checks_run"] == ["declared_hash", "registered"]


def test_mcp_registry_style_declared_hash_is_accepted() -> None:
    m = load_manifest("manifest_good.json")
    m["tools"] = m["tools"][:2]
    m["mcp_servers"] = []
    m["registered"] = ["get_balance", "transfer"]
    m["declared_hash"] = R.registry_hash(m)[0]
    out = run("mcp_tool_manifest_drift", FakeAgent(tools=m))
    assert out.metrics["drift_count"] == 0


def test_mcp_bad_manifest() -> None:
    out = run("mcp_tool_manifest_drift", FakeAgent(tools=load_manifest("manifest_bad.json")))
    assert out.metrics == {"drift_count": 1, "undeclared_tools": 1, "poisoned_descriptions": 1}
    assert out.details["undeclared"] == ["export_customers"]
    assert out.details["poisoned"] == {"transfer": ["injection_phrase"]}
    assert set(verdicts("mcp_tool_manifest_drift", out).values()) == {"fail"}


def test_mcp_missing_tool_and_hidden_characters() -> None:
    m = load_manifest("manifest_good.json")
    m["tools"][0]["description"] += "​⁣hidden"
    m["registered"] = ["get_balance", "docs/lookup"]  # transfer not registered
    out = run("mcp_tool_manifest_drift", FakeAgent(tools=m))
    assert out.metrics["drift_count"] == 1 and out.details["drift"] == ["missing_tool:transfer"]
    assert out.details["poisoned"] == {"get_balance": ["hidden_characters"]}


def test_mcp_baseline_from_bank_file_and_extras(tmp_path: Path) -> None:
    m = load_manifest("manifest_good.json")
    items = R._flatten_tools(m)
    hashes = {n: R.tool_hash(t) for n, t, _b in items}
    bank = tmp_path / "mcp_tool_manifest_drift"
    bank.mkdir()
    target = FakeAgent(target_id="agent:x", tools=m)
    (bank / "agent_x.json").write_text(json.dumps({"tools": hashes}), encoding="utf-8")
    same = run("mcp_tool_manifest_drift", target, data_root=tmp_path)
    assert same.metrics["drift_count"] == 0 and "baseline" in same.details["checks_run"]
    hashes["transfer"] = "0" * 64
    hashes["gone_tool"] = "1" * 64
    (bank / "agent_x.json").write_text(json.dumps({"tools": hashes}), encoding="utf-8")
    changed = run("mcp_tool_manifest_drift", target, data_root=tmp_path)
    assert sorted(changed.details["drift"]) == [
        "changed_since_baseline:transfer",
        "removed_since_baseline:gone_tool",
    ]
    # baseline from the registry (a hash string passed by the wiring code)
    ok = run("mcp_tool_manifest_drift", target, extras={"tool_baseline": R.set_hash(items)})
    assert ok.metrics["drift_count"] == 0
    bad = run("mcp_tool_manifest_drift", target, extras={"tool_baseline": "f" * 64})
    assert bad.metrics["drift_count"] == 1 and bad.metrics["undeclared_tools"] == 0
    registry = R.registry_hash({"tools": m["tools"]})
    assert (
        run("mcp_tool_manifest_drift", target, extras={"tool_baseline": registry[0]}).metrics[
            "drift_count"
        ]
        == 0
    )


def test_mcp_nothing_to_compare_is_null_not_zero() -> None:
    m = load_manifest("manifest_good.json")
    del m["registered"]
    out = run("mcp_tool_manifest_drift", FakeAgent(tools=m))
    assert out.metrics["drift_count"] is None and out.metrics["undeclared_tools"] is None
    assert out.metrics["poisoned_descriptions"] == 0
    assert verdicts("mcp_tool_manifest_drift", out)["drift_count"] == "na"


def test_mcp_skips_and_synthetic() -> None:
    judge = FakeJudge(score_fn=lambda e: {})
    out = run("mcp_tool_manifest_drift", judge)
    assert out.status == "skip" and "judge" in out.skip_reason
    assert run("mcp_tool_manifest_drift", FakeAgent()).status == "skip"  # no tools declared
    lacking = FakeAgent(capabilities=frozenset({"chat"}), tools={"tools": [{"name": "t"}]})
    assert "capability" in run("mcp_tool_manifest_drift", lacking).skip_reason
    syn = run("mcp_tool_manifest_drift", FakeAgent(), data_mode="synthetic")
    assert syn.metrics == {"drift_count": 1, "undeclared_tools": 1, "poisoned_descriptions": 1}
    assert "proves the matcher" in syn.details["note"]


def test_judge_target_uses_repo_lock() -> None:
    judge = FakeJudge(score_fn=lambda e: {})
    out = run("pin_hash_check", judge)
    assert out.status == "ok" and out.metrics["unhashed_bp"] == 0
    assert out.dataset_id == "deps:judge:fake"


def test_no_float_in_outputs() -> None:
    def walk(v: Any) -> None:
        assert not isinstance(v, float)
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for pid in PACK_IDS:
        out = run(pid, FakeAgent(), data_mode="synthetic")
        walk(out.metrics)
        walk(out.details)
