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
    WorkflowDocumentError,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    compile_workflow,
    discover_module_packages,
    parse_workflow_document,
    relock_workflow,
)
from examples.v2_suite import (
    CAPABILITY_INVENTORY_PATH,
    PRODUCTION_WORKFLOW_PATHS,
    verify_repository_examples,
)
from modules.prompt_authoring.package import (
    MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
)
from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
from modules.structure_comparison.package import (
    MODULE_PACKAGE as STRUCTURE_COMPARISON_PACKAGE,
)
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
from tests.fixtures.multi_objective_selection_sources.package import (
    FIXED_PARTITION,
    PAIRED_PARTITION,
    MODULE_PACKAGE as SELECTION_SOURCE_PACKAGE,
)
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as PROMPT_AUTHORING_SOURCE_PACKAGE,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SELECTION_FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "v2_workflows"
    / "exact_multi_objective_selection.workflow.json"
)
PROMPT_TRACK_FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "v2_workflows"
    / "exact_prompt_tracks.workflow.json"
)
CTK_WORKFLOW_PATHS = (PROMPT_TRACK_FIXTURE, SELECTION_FIXTURE)
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
    "structure_prediction",
    "structure_transform",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _selection_catalog():
    return build_frozen_catalog(
        (
            SELECTION_PACKAGE,
            STRUCTURE_COMPARISON_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
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
        assert workflow.schema_version == "2.1.0"
        assert workflow.contract_lock
        assert relock_workflow(workflow, catalog) == workflow
        compiled = compile_workflow(
            workflow,
            workflow_commit_revision=1,
            catalog=catalog,
        )
        assert compiled.execution_plan.workflow_commit_revision == 1
        assert compiled.execution_plan.workflow_digest == workflow.digest
        for node in workflow.nodes:
            node_type = catalog.require_contract(
                "node_type",
                node.node_type_id,
                node.node_type_version,
            )
            binding = catalog.require_contract(
                "binding",
                node.binding_id,
                node.binding_version,
            )
            assert binding.descriptor["node_type"] == node_type.reference()


def test_examples_never_select_methods_or_environment_implicitly() -> None:
    payloads = [_load(path) for path in PRODUCTION_WORKFLOW_PATHS]
    payloads.extend(_load(path) for path in CTK_WORKFLOW_PATHS)

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


def test_capability_inventory_names_exactly_12_module_packages() -> None:
    inventory = _load(CAPABILITY_INVENTORY_PATH)

    assert inventory["schema_version"] == (
        "protein-workbench-capability-inventory/v2"
    )
    assert set(inventory["package_ids"]) == EXPECTED_PACKAGES
    assert {
        package.package_id for package in discover_module_packages()
    } == EXPECTED_PACKAGES


def test_capability_inventory_locks_every_canonical_contract_identity() -> None:
    catalog = build_discovered_frozen_catalog()
    inventory = _load(CAPABILITY_INVENTORY_PATH)

    assert inventory["contracts"] == [
        contract.reference()
        for contract in sorted(
            catalog.contracts,
            key=lambda item: (
                item.contract_kind,
                item.contract_id,
                item.contract_version,
            ),
        )
    ]


def test_examples_and_ctk_fixtures_cover_every_node_and_binding() -> None:
    catalog = build_discovered_frozen_catalog()
    payloads = [
        *(_load(path) for path in PRODUCTION_WORKFLOW_PATHS),
        *(_load(path) for path in CTK_WORKFLOW_PATHS),
    ]
    production_bindings = {
        contract.contract_id
        for contract in catalog.contracts
        if contract.contract_kind == "binding"
    }
    production_node_types = {
        contract.contract_id
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
    }
    covered_bindings = {
        node["binding_id"]
        for payload in payloads
        for node in payload["nodes"]
        if node["binding_id"] in production_bindings
    }
    covered_node_types = {
        node["node_type_id"]
        for payload in payloads
        for node in payload["nodes"]
        if node["node_type_id"] in production_node_types
    }
    covered_owners = {
        owner
        for key, owners in catalog.owners.items()
        if (
            key[0] == "binding" and key[1] in covered_bindings
            or key[0] == "node_type" and key[1] in covered_node_types
        )
        for owner in owners
    }

    assert covered_bindings == production_bindings
    assert covered_node_types == production_node_types
    assert covered_owners == EXPECTED_PACKAGES


def test_prediction_confidence_is_materialized_by_explicit_nodes() -> None:
    """Required prediction facts cross the canonical materialization seam."""
    catalog = build_discovered_frozen_catalog()
    producer_candidate_ports = {
        "esm3.generate_paired": "structure_candidates",
        "esm3.generate_structure": "structure_candidates",
        "folding.fold": "structure_candidates",
    }

    for path in PRODUCTION_WORKFLOW_PATHS:
        payload = _load(path)
        nodes = {node["node_id"]: node for node in payload["nodes"]}
        edges = {
            (
                edge["source_node_id"],
                edge["source_port"],
                edge["target_node_id"],
                edge["target_port"],
            )
            for edge in payload["edges"]
        }
        for producer in nodes.values():
            candidate_port = producer_candidate_ports.get(
                producer["node_type_id"]
            )
            if candidate_port is None:
                continue
            node_type = catalog.require_contract(
                "node_type",
                producer["node_type_id"],
                producer["node_type_version"],
            )
            required_outputs = {
                output["name"]
                for output in node_type.descriptor["outputs"]
                if output["required"]
            }
            assert {candidate_port, "confidence_facts"} <= required_outputs
            materializers = [
                node
                for node in nodes.values()
                if node["node_type_id"]
                == "structure_prediction.materialize_confidence"
                and (
                    producer["node_id"],
                    candidate_port,
                    node["node_id"],
                    "structure_candidates",
                )
                in edges
                and (
                    producer["node_id"],
                    "confidence_facts",
                    node["node_id"],
                    "confidence_facts",
                )
                in edges
            ]
            assert len(materializers) == 1, (
                f"{path.name}:{producer['node_id']} must explicitly "
                "materialize its required confidence facts"
            )


def test_scoring_fixture_uses_exact_scopes_contexts_and_utilities() -> None:
    catalog = _selection_catalog()
    workflow = parse_workflow_document(_load(SELECTION_FIXTURE))

    assert relock_workflow(workflow, catalog) == workflow
    compiled = compile_workflow(
        workflow,
        workflow_commit_revision=1,
        catalog=catalog,
    )
    assert compiled.execution_plan.workflow_commit_revision == 1
    assert compiled.execution_plan.workflow_digest == workflow.digest
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
        objective.metric.contract_id
        == "contract_test.multi_objective_selection_score"
        and objective.metric.contract_version == "3.0.0"
        and objective.method.contract_id
        == "contract_test.multi_objective_selection_source.method"
        and objective.method.contract_version == "2.1.0"
        and objective.utility_transform.contract_version == "3.0.0"
        and objective.context_selector.normalization
        == "literal-unit-interval"
        and objective.match_cardinality == "exactly_one"
        and objective.missing_policy == "error"
        for objective in workflow.selection_objectives
    )
    serialized = json.dumps(workflow.to_public(), sort_keys=True)
    assert "score_id" not in serialized


def test_prompt_track_fixture_uses_only_the_ctk_registration_seam() -> None:
    catalog = build_frozen_catalog(
        (
            PROMPT_AUTHORING_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
            PROMPT_AUTHORING_SOURCE_PACKAGE,
        )
    )
    workflow = parse_workflow_document(_load(PROMPT_TRACK_FIXTURE))

    assert relock_workflow(workflow, catalog) == workflow
    compiled = compile_workflow(
        workflow,
        workflow_commit_revision=1,
        catalog=catalog,
    )
    assert compiled.execution_plan.workflow_commit_revision == 1
    assert compiled.execution_plan.workflow_digest == workflow.digest
    assert {
        node.binding_id
        for node in workflow.nodes
        if node.binding_id.startswith("prompt_authoring.")
    } == {
        "prompt_authoring.map_residue_track.direct",
        "prompt_authoring.override_residue_track.direct",
    }


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

    comparison_nodes = {
        (contract.contract_id, contract.contract_version)
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
        and contract.contract_id.startswith("structure_comparison.")
    }
    assert comparison_nodes == {
        ("structure_comparison.align_counterparts", "4.0.0"),
        ("structure_comparison.align_fixed_reference", "4.0.0"),
        ("structure_comparison.align_single", "4.0.0"),
        (
            "structure_comparison.classify_three_way_consistency",
            "1.0.0",
        ),
        ("structure_comparison.rmsd_counterparts", "5.0.0"),
        ("structure_comparison.rmsd_fixed_reference", "5.0.0"),
        ("structure_comparison.tm_score_counterparts", "5.0.0"),
        ("structure_comparison.tm_score_fixed_reference", "5.0.0"),
    }
    comparison_bindings = {
        (contract.contract_id, contract.contract_version)
        for contract in catalog.contracts
        if contract.contract_kind == "binding"
        and contract.contract_id.startswith("structure_comparison.")
    }
    assert comparison_bindings == {
        (
            "structure_comparison.align_counterparts."
            "sequence_primary_affine",
            "4.0.0",
        ),
        (
            "structure_comparison.align_fixed_reference."
            "sequence_primary_affine",
            "4.0.0",
        ),
        (
            "structure_comparison.align_single.sequence_primary_affine",
            "4.0.0",
        ),
        (
            "structure_comparison.align_single.structure_first_tm_align",
            "4.0.0",
        ),
        (
            "structure_comparison.classify_three_way_consistency.direct",
            "1.0.0",
        ),
        (
            "structure_comparison.rmsd_counterparts.from_alignment_evidence",
            "5.0.0",
        ),
        (
            "structure_comparison.rmsd_fixed_reference.from_alignment_evidence",
            "5.0.0",
        ),
        (
            "structure_comparison.tm_score_counterparts."
            "from_alignment_evidence",
            "5.0.0",
        ),
        (
            "structure_comparison.tm_score_fixed_reference."
            "from_alignment_evidence",
            "5.0.0",
        ),
    }
    comparison_scientific_contracts = {
        (contract.contract_kind, contract.contract_id, contract.contract_version)
        for contract in catalog.contracts
        if contract.contract_kind in {
            "method",
            "metric",
            "utility_transform",
        }
        and contract.contract_id.startswith("structure_comparison.")
    }
    assert comparison_scientific_contracts
    assert {version for _, _, version in comparison_scientific_contracts} == {
        "1.0.0",
        "3.0.0",
    }


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

    assert verify_repository_examples() == {
        "catalog_contract_digest": (
            build_discovered_frozen_catalog().contract_digest
        ),
        "package_count": 12,
        "node_type_count": 63,
        "workflow_count": len(PRODUCTION_WORKFLOW_PATHS),
    }
    assert all(not any(root.iterdir()) for root in isolated_roots.values())


def test_example_verification_is_deterministic() -> None:
    first = verify_repository_examples()
    second = verify_repository_examples()

    assert first == second
