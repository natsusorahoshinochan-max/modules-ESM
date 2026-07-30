"""Repository-owned v2 example and fixture acceptance for Ticket 33.

The pre-agreed seams are the immutable production Catalog, the public v2
Workflow document/compiler contract, the Module Package/Contract Test Kit
registration seam, and the built artifact inventory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import (
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    compile_workflow,
    discover_module_packages,
    parse_workflow_document,
    relock_workflow,
)
from core.workflow_v2 import WorkflowDocumentError
from examples.v2_suite import (
    CAPABILITY_INVENTORY_PATH,
    PRODUCTION_WORKFLOW_PATHS,
    verify_repository_examples,
)
from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
from modules.structure_comparison.package import (
    MODULE_PACKAGE as STRUCTURE_COMPARISON_PACKAGE,
)
from scripts.verify_backend import TIERS
from tests.fixtures.multi_objective_selection_sources.package import (
    FIXED_PARTITION,
    PAIRED_PARTITION,
    MODULE_PACKAGE as SELECTION_SOURCE_PACKAGE,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SELECTION_FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "v2_workflows"
    / "exact_multi_objective_selection.workflow.json"
)
UNSUPPORTED_WORKFLOW_FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "v2_workflows"
    / "unsupported_schema_version.workflow.json"
)
EXPECTED_PACKAGES = {
    "collection_ops",
    "esm3",
    "folding",
    "prompt_authoring",
    "protein_io",
    "proteinmpnn",
    "selection",
    "solubility",
    "structure_annotation",
    "structure_comparison",
    "structure_transform",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _selection_catalog():
    return build_frozen_catalog(
        (
            SELECTION_PACKAGE,
            STRUCTURE_COMPARISON_PACKAGE,
            SELECTION_SOURCE_PACKAGE,
        )
    )


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_repository_examples_are_exact_locked_compilable_v2_workflows() -> None:
    catalog = build_discovered_frozen_catalog()

    assert PRODUCTION_WORKFLOW_PATHS
    for path in PRODUCTION_WORKFLOW_PATHS:
        payload = _load(path)
        workflow = parse_workflow_document(payload)
        assert workflow.schema_version == "2.0.0"
        assert workflow.contract_lock
        assert relock_workflow(workflow, catalog) == workflow
        assert compile_workflow(
            workflow,
            workflow_revision=1,
            catalog=catalog,
        ).receipt["accepted"] is True
        for node in workflow.nodes:
            assert node.node_type_version == "2.0.0"
            assert node.binding_version == "2.0.0"
            assert node.binding_parameters is not node.node_parameters


def test_examples_never_select_methods_or_environment_implicitly() -> None:
    payloads = [_load(path) for path in PRODUCTION_WORKFLOW_PATHS]
    payloads.append(_load(SELECTION_FIXTURE))

    forbidden_keys = {
        "credential",
        "credential_file",
        "directory",
        "fallback",
        "model_name",
        "path",
        "provider",
        "runtime_path",
    }
    forbidden_values = {"latest", "fallback", "auto"}
    for payload in payloads:
        for node in payload["nodes"]:
            assert node["binding_id"]
            assert set(node) == {
                "node_id",
                "node_type_id",
                "node_type_version",
                "binding_id",
                "binding_version",
                "node_parameters",
                "binding_parameters",
            }
            assert forbidden_keys.isdisjoint(node["node_parameters"])
            assert forbidden_keys.isdisjoint(node["binding_parameters"])
        assert not any(
            isinstance(value, str) and value.lower() in forbidden_values
            for value in _walk(payload)
        )


def test_capability_inventory_locks_the_11_package_node_surface() -> None:
    catalog = build_discovered_frozen_catalog()
    inventory = _load(CAPABILITY_INVENTORY_PATH)
    expected_references = {
        (
            contract.contract_id,
            contract.contract_version,
            contract.contract_digest,
        )
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
    }

    assert inventory["schema_version"] == (
        "protein-workbench-capability-inventory/v2"
    )
    assert set(inventory["package_ids"]) == EXPECTED_PACKAGES
    assert {
        (
            reference["contract_id"],
            reference["contract_version"],
            reference["contract_digest"],
        )
        for reference in inventory["node_types"]
    } == expected_references
    assert {
        package.package_id for package in discover_module_packages()
    } == EXPECTED_PACKAGES
    covered_packages = {
        node["node_type_id"].split(".", 1)[0]
        for path in PRODUCTION_WORKFLOW_PATHS
        for node in _load(path)["nodes"]
    }
    covered_packages.update(
        node["node_type_id"].split(".", 1)[0]
        for node in _load(SELECTION_FIXTURE)["nodes"]
        if not node["node_type_id"].startswith("contract_test.")
    )
    assert covered_packages == EXPECTED_PACKAGES


def test_scoring_fixture_uses_exact_scopes_contexts_and_utilities() -> None:
    catalog = _selection_catalog()
    workflow = parse_workflow_document(_load(SELECTION_FIXTURE))

    assert relock_workflow(workflow, catalog) == workflow
    assert compile_workflow(
        workflow,
        workflow_revision=1,
        catalog=catalog,
    ).receipt["accepted"] is True
    assert {
        objective.source_partition for objective in workflow.selection_objectives
    } == {
        FIXED_PARTITION,
        PAIRED_PARTITION,
    }
    assert {
        objective.context_selector.pairing_mode
        for objective in workflow.selection_objectives
    } == {"fixed_reference", "per_subject_counterpart"}
    assert all(
        objective.metric.contract_id == "structure_comparison.tm_score"
        and objective.metric.contract_version == "2.0.0"
        and objective.method.contract_id
        == "contract_test.multi_objective_selection_source.method"
        and objective.method.contract_version == "2.0.0"
        and objective.utility_transform.contract_version == "2.0.0"
        and objective.match_cardinality == "exactly_one"
        and objective.missing_policy == "error"
        for objective in workflow.selection_objectives
    )
    serialized = json.dumps(workflow.to_public(), sort_keys=True)
    assert "score_id" not in serialized


def test_production_catalog_advertises_only_cohesive_v2_capabilities() -> None:
    catalog = build_discovered_frozen_catalog()
    node_ids = {
        contract.contract_id
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
    }

    assert "stub.echo" not in node_ids
    assert "scoring.aggregate_confidence" not in node_ids
    assert {
        "esm3.generate",
        "esmfold2.fold",
        "structure.pairwise_align",
        "structure.batch_tm_score",
        "scoring.merge",
    }.isdisjoint(node_ids)


def test_legacy_sample_exists_only_as_an_explicit_unsupported_fixture() -> None:
    payload = _load(UNSUPPORTED_WORKFLOW_FIXTURE)

    assert payload == {
        "schema_version": "1.0.0",
        "workflow_id": "unsupported-v1-fixture",
        "nodes": [],
        "edges": [],
        "contract_lock": [],
    }
    with pytest.raises(
        WorkflowDocumentError,
        match="Workflow document is invalid",
    ) as caught:
        parse_workflow_document(payload)
    assert caught.value.code == "unsupported_schema_version"


def test_routine_example_verification_is_pure_and_provider_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_roots = {
        name: tmp_path / name.lower()
        for name in ("PROJECT", "CACHE", "OUTPUT", "RUN")
    }
    for name, root in isolated_roots.items():
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))

    first = verify_repository_examples()
    second = verify_repository_examples()

    assert first == second
    assert first == {
        "catalog_contract_digest": (
            build_discovered_frozen_catalog().contract_digest
        ),
        "package_count": 11,
        "node_type_count": 44,
        "workflow_count": len(PRODUCTION_WORKFLOW_PATHS),
    }
    assert all(not any(root.iterdir()) for root in isolated_roots.values())


def test_example_verification_has_one_isolated_provider_free_tier() -> None:
    tier = TIERS["examples-v2"]

    assert tier.pytest_args == ("tests/test_repository_examples_v2.py",)
    assert tier.requires_provider_evidence is False
    assert tier.requires_biohub_credential is False
    assert tier.requires_local_model_environment is False
    assert tier.requires_simplefold_environment is False
