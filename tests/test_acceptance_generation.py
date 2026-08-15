"""Contract tests for the serial frozen acceptance-generation controller."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

from core import build_discovered_frozen_catalog, parse_workflow_document
from protein_workbench_public import bundle_digest

from scripts.acceptance_generation import (
    ACCEPTANCE_TIER_ORDER,
    INPUT_DIGESTS,
    SOURCE_BOUND_CONTRACTS,
    generation_definition,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_source_bound_generation_contracts_are_current_and_source_exact() -> None:
    catalog = build_discovered_frozen_catalog()
    for tier_name, contract in SOURCE_BOUND_CONTRACTS.items():
        input_path = PROJECT_ROOT / contract.input_path
        workflow_path = PROJECT_ROOT / contract.workflow_path
        assert hashlib.sha256(input_path.read_bytes()).hexdigest() == (
            INPUT_DIGESTS[tier_name]
        )
        workflow = parse_workflow_document(
            json.loads(workflow_path.read_text(encoding="utf-8"))
        )
        assert workflow.contract_lock
        assert all(
            catalog.require_contract(
                reference.contract_kind,
                reference.contract_id,
                reference.contract_version,
            ).contract_digest
            == reference.contract_digest
            for reference in workflow.contract_lock
        )


def test_generation_definition_binds_one_complete_order_and_public_generation() -> None:
    definition = generation_definition()

    assert definition["schema_namespace"] == (
        "protein-workbench-acceptance-generation/v1"
    )
    assert definition["tier_order"] == list(ACCEPTANCE_TIER_ORDER)
    assert definition["protocol_digest"] == bundle_digest()
    assert definition["catalog_contract_digest"] == (
        build_discovered_frozen_catalog().contract_digest
    )
    assert definition["execution"] == {
        "child_processes": "one_at_a_time",
        "pytest_xdist": False,
        "concurrent_tiers": False,
        "nested_local_model_processes": False,
        "resident_model_instances_per_local_model": 1,
    }
    assert definition["source_bound_inputs"] == INPUT_DIGESTS
    assert set(definition["provider_configuration_contracts"]) == set(
        ACCEPTANCE_TIER_ORDER
    )
    assert list(definition["tier_contracts"]) == list(ACCEPTANCE_TIER_ORDER)
    assert all(
        contract["zero_skip"]
        and contract["clean_source"]
        and contract["retain_evidence_bundle"]
        and "-n" not in contract["pytest_arguments"]
        for contract in definition["tier_contracts"].values()
    )


def test_documented_script_boundary_builds_the_exact_generation_definition(
    tmp_path: Path,
) -> None:
    generation_root = tmp_path / "generation"
    result_path = tmp_path / "result.json"
    launcher = textwrap.dedent(
        """
        import importlib.util
        import json
        from pathlib import Path
        import sys

        project_root = Path(sys.argv[1]).resolve()
        script_path = project_root / "scripts" / "acceptance_generation.py"
        sys.path = [
            entry
            for entry in sys.path
            if Path(entry or ".").resolve() != project_root
        ]
        spec = importlib.util.spec_from_file_location(
            "acceptance_generation_documented_script",
            script_path,
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module._git_authority = lambda: ("d" * 40, False)
        module._configuration_identities = lambda: {"frozen": "configuration"}
        module._provider_asset_identities = lambda: {"frozen": "assets"}
        generation_root = Path(sys.argv[2])
        result_path = Path(sys.argv[3])
        sys.argv = [str(script_path), "start", str(generation_root)]
        assert module.main() == 0
        manifest = json.loads(
            (generation_root / "generation.json").read_text()
        )
        result_path.write_text(json.dumps({
            "installed_order": list(module.INSTALLED_PROVIDER_TIER_ORDER),
            "tier_order": manifest["tier_order"],
            "artifact_kinds": [
                artifact["kind"]
                for artifact in manifest["installed_artifacts"]
            ],
            "repo_root_on_sys_path": any(
                Path(entry or ".").resolve() == project_root
                for entry in sys.path
            ),
        }))
        """
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            launcher,
            str(PROJECT_ROOT),
            str(generation_root),
            str(result_path),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result == {
        "installed_order": list(ACCEPTANCE_TIER_ORDER[:11]),
        "tier_order": list(ACCEPTANCE_TIER_ORDER),
        "artifact_kinds": ["wheel", "sdist"],
        "repo_root_on_sys_path": False,
    }
    assert (generation_root / "generation.json").is_file()


def test_all_source_bound_tiers_collect_exactly_one_zero_skip_journey() -> None:
    from scripts.verify_backend import TIERS

    selectors = tuple(
        TIERS[tier_name].pytest_arguments[0]
        for tier_name in ACCEPTANCE_TIER_ORDER[-4:]
    )
    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "--collect-only",
            "-q",
            *selectors,
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert "4 tests collected" in collected.stdout
    assert all(selector in collected.stdout for selector in selectors)


def test_configuration_identity_binds_only_effective_explicit_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import scripts.acceptance_generation as generation
    from modules.provider_contract import LOCAL_ESM3_SNAPSHOT_REVISION

    configured_path = tmp_path / "configured"
    configured_path.write_text("configured", encoding="utf-8")
    for variables in generation.PROVIDER_CONFIGURATION_CONTRACTS.values():
        for variable in variables:
            if variable not in {"HF_HUB_CACHE", "HF_HOME"}:
                monkeypatch.setenv(variable, str(configured_path))
    hub_cache = tmp_path / "hub"
    snapshot = (
        hub_cache
        / "models--biohub--esm3-sm-open-v1"
        / "snapshots"
        / LOCAL_ESM3_SNAPSHOT_REVISION
    )
    snapshot.mkdir(parents=True)
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "shadowed-hf-home"))

    identities = generation._configuration_identities()

    assert set(identities["installed-local-esm3"]) == {"HF_HUB_CACHE"}
    assert all(identities[tier] for tier in ACCEPTANCE_TIER_ORDER)


def test_controller_records_only_one_strictly_serial_contiguous_prefix(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import scripts.acceptance_generation as generation

    root = tmp_path / "generation"
    artifact_root = root / "artifacts"
    artifact_root.mkdir(parents=True)
    (artifact_root / "protein_workbench.whl").write_bytes(b"wheel")
    (artifact_root / "protein_workbench.tar.gz").write_bytes(b"sdist")
    manifest = {
        **generation.generation_definition(),
        "source_revision": "a" * 40,
        "source_dirty": False,
        "installed_artifacts": generation._artifact_records(artifact_root),
        "provider_configuration_identities": {"frozen": "configuration"},
        "provider_asset_identities": {"frozen": "assets"},
        "results": [],
    }
    frozen_definition = {
        key: value
        for key, value in manifest.items()
        if key
        not in {
            "source_revision",
            "source_dirty",
            "installed_artifacts",
            "provider_configuration_identities",
            "provider_asset_identities",
            "results",
        }
    }
    (root / "generation.json").write_bytes(
        generation._canonical_bytes(manifest)
    )
    monkeypatch.setattr(
        generation,
        "_git_authority",
        lambda: ("a" * 40, False),
    )
    monkeypatch.setattr(
        generation,
        "generation_definition",
        lambda: frozen_definition,
    )
    monkeypatch.setattr(
        generation,
        "_provider_asset_identities",
        lambda: {"frozen": "assets"},
    )
    monkeypatch.setattr(
        generation,
        "_configuration_identities",
        lambda: {"frozen": "configuration"},
    )
    authority_checks = 0

    def assert_authority(_root, _manifest):
        nonlocal authority_checks
        authority_checks += 1

    monkeypatch.setattr(generation, "_assert_authority", assert_authority)
    observed: list[str] = []
    active_children = 0

    def run_child(command, **_kwargs):
        nonlocal active_children
        tier_name = command[-1]
        active_children += 1
        assert active_children == 1
        result_dir = root / "tier-results" / tier_name / "result"
        result_dir.mkdir(parents=True)
        (result_dir / "evidence.json").write_text(tier_name)
        observed.append(tier_name)
        active_children -= 1
        return SimpleNamespace(
            returncode=0,
            stdout=f"RETAINED VERIFICATION RESULT: {result_dir}\n",
        )

    monkeypatch.setattr(generation.subprocess, "run", run_child)
    completed = generation.run_through(
        root,
        generation.INSTALLED_PROVIDER_TIER_ORDER[1],
    )

    assert observed == list(generation.INSTALLED_PROVIDER_TIER_ORDER[:2])
    assert [item["tier"] for item in completed["results"]] == observed
    assert all(item["outcome"] == "passed" for item in completed["results"])
    assert authority_checks == 5


def test_start_freezes_clean_head_without_self_referential_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import scripts.acceptance_generation as generation

    revision = "b" * 40
    root = tmp_path / "generation"
    definition = generation.generation_definition()
    monkeypatch.setattr(generation, "_git_authority", lambda: (revision, False))
    monkeypatch.setattr(
        generation,
        "generation_definition",
        lambda: definition,
    )
    monkeypatch.setattr(
        generation,
        "_provider_asset_identities",
        lambda: {"frozen": "assets"},
    )
    monkeypatch.setattr(
        generation,
        "_configuration_identities",
        lambda: {"frozen": "configuration"},
    )

    def build(command, **_kwargs):
        artifact_root = Path(command[-1])
        artifact_root.mkdir(parents=True)
        (artifact_root / "protein_workbench.whl").write_bytes(b"wheel")
        (artifact_root / "protein_workbench.tar.gz").write_bytes(b"sdist")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(generation.subprocess, "run", build)
    manifest = generation.start_generation(root)

    assert manifest["source_revision"] == revision
    assert manifest["source_dirty"] is False
    assert manifest["provider_asset_identities"] == {"frozen": "assets"}
    assert manifest["results"] == []
    assert "manifest_digest" not in manifest
    assert json.loads((root / "generation.json").read_bytes()) == manifest


def test_failed_tier_is_retained_and_terminates_without_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import pytest
    import scripts.acceptance_generation as generation

    root = tmp_path / "generation"
    artifact_root = root / "artifacts"
    artifact_root.mkdir(parents=True)
    (artifact_root / "protein_workbench.whl").write_bytes(b"wheel")
    (artifact_root / "protein_workbench.tar.gz").write_bytes(b"sdist")
    manifest = {
        **generation.generation_definition(),
        "source_revision": "c" * 40,
        "source_dirty": False,
        "installed_artifacts": generation._artifact_records(artifact_root),
        "provider_configuration_identities": {"frozen": "configuration"},
        "provider_asset_identities": {"frozen": "assets"},
        "results": [],
    }
    (root / "generation.json").write_bytes(
        generation._canonical_bytes(manifest)
    )
    monkeypatch.setattr(generation, "_assert_authority", lambda *_args: None)
    calls = 0

    def fail_child(command, **_kwargs):
        nonlocal calls
        calls += 1
        tier_name = command[-1]
        result_dir = root / "tier-results" / tier_name / "failed"
        result_dir.mkdir(parents=True)
        (result_dir / "evidence.json").write_text(tier_name)
        return SimpleNamespace(
            returncode=1,
            stdout=f"RETAINED VERIFICATION RESULT: {result_dir}\n",
        )

    monkeypatch.setattr(generation.subprocess, "run", fail_child)
    first_tier = generation.ACCEPTANCE_TIER_ORDER[0]

    with pytest.raises(RuntimeError, match="acceptance tier failed"):
        generation.run_through(root, first_tier)
    retained = json.loads((root / "generation.json").read_bytes())
    assert [(item["tier"], item["outcome"]) for item in retained["results"]] == [
        (first_tier, "failed")
    ]
    with pytest.raises(RuntimeError, match="generation is terminated"):
        generation.run_through(root, first_tier)
    assert calls == 1
