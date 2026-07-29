"""Public contracts for the cohesive structure-transform Module Package."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import (
    ModulePackageContractCase,
    ModulePackagePortCase,
    WorkflowCompileError,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    compile_workflow,
    discover_module_packages,
    relock_workflow,
    verify_module_package_contract,
)
from core.workflow_v2 import WorkflowEdge
from datatypes import ProteinStructure
from modules.structure_transform.package import MODULE_PACKAGE
from tests.fixtures.structure_transform_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)


VERSION = "2.0.0"
_SOURCE = WorkflowNodeInstance(
    node_id="source",
    node_type_id="contract_test.structure_transform_source",
    node_type_version=VERSION,
    binding_id="contract_test.structure_transform_source.direct",
    binding_version=VERSION,
    node_parameters={"fixture": "canonical"},
    binding_parameters={},
)
_SOURCE_EDGE = WorkflowEdge(
    "source",
    "structure",
    "contract-test-node",
    "structure",
)
_BACKBONE = ProteinStructure(
    pdb_string=(
        "ATOM      1  N   ALA A   1       1.000   2.000   3.000"
        "  1.00 20.00           N\n"
        "ATOM      2  CA  ALA A   1       2.000   2.000   3.000"
        "  1.00 20.00           C\n"
        "ATOM      3  C   ALA A   1       3.000   2.000   3.000"
        "  1.00 20.00           C\n"
        "ATOM      4  O   ALA A   1       4.000   2.000   3.000"
        "  1.00 20.00           O\n"
        "TER\nEND\n"
    ),
    source="structure_transform.extract_backbone",
)
_MID_RESIDUE_BREAK = ProteinStructure(
    pdb_string=_BACKBONE.pdb_string.replace(
        "\nATOM      2  CA",
        "\nTER\nATOM      2  CA",
    ),
    source="structure_transform.extract_backbone",
)
_MISSING_CHAIN_BREAK = ProteinStructure(
    pdb_string=(
        _BACKBONE.pdb_string.removesuffix("TER\nEND\n")
        + "ATOM      5  N   GLY B   1       5.000   2.000   3.000"
        "  1.00 20.00           N\n"
        "ATOM      6  CA  GLY B   1       6.000   2.000   3.000"
        "  1.00 20.00           C\n"
        "ATOM      7  C   GLY B   1       7.000   2.000   3.000"
        "  1.00 20.00           C\n"
        "ATOM      8  O   GLY B   1       8.000   2.000   3.000"
        "  1.00 20.00           O\n"
        "TER\nEND\n"
    ),
    source="structure_transform.extract_backbone",
)


def test_structure_transform_has_three_scientific_transforms_and_one_bridge() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["structure_transform"]
    assert registration.package_module == "modules.structure_transform"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/select_chains.yaml",
        "definitions/extract_backbone.yaml",
        "definitions/extract_sequence.yaml",
        "definitions/backbone_to_structure.yaml",
    }
    catalog = build_discovered_frozen_catalog()
    assert {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "structure_transform"
        in catalog.owners[(kind, contract_id, version)]
    } == {
        ("structure_transform.select_chains", VERSION),
        ("structure_transform.extract_backbone", VERSION),
        ("structure_transform.extract_sequence", VERSION),
        ("structure_transform.backbone_to_structure", VERSION),
    }


def test_transform_ports_are_exact_and_backbone_is_nominal() -> None:
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    selection = catalog.require_contract(
        "node_type",
        "structure_transform.select_chains",
        VERSION,
    ).descriptor
    backbone = catalog.require_contract(
        "node_type",
        "structure_transform.extract_backbone",
        VERSION,
    ).descriptor
    sequence = catalog.require_contract(
        "node_type",
        "structure_transform.extract_sequence",
        VERSION,
    ).descriptor
    backbone_bridge = catalog.require_contract(
        "node_type",
        "structure_transform.backbone_to_structure",
        VERSION,
    ).descriptor

    assert selection["inputs"][0]["port_type"]["contract_id"] == (
        "protein.structure"
    )
    assert selection["outputs"][0]["port_type"]["contract_id"] == (
        "protein.structure"
    )
    assert backbone["inputs"][0]["port_type"]["contract_id"] == (
        "protein.structure"
    )
    assert backbone["outputs"][0]["port_type"]["contract_id"] == (
        "structure_transform.backbone_structure"
    )
    assert sequence["inputs"][0]["port_type"]["contract_id"] == (
        "protein.structure"
    )
    assert sequence["outputs"][0]["port_type"]["contract_id"] == (
        "protein.sequence"
    )
    assert backbone_bridge["inputs"][0]["port_type"]["contract_id"] == (
        "structure_transform.backbone_structure"
    )
    assert backbone_bridge["outputs"][0]["port_type"]["contract_id"] == (
        "protein.structure"
    )


def test_full_atom_structure_cannot_enter_a_backbone_port_implicitly() -> None:
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="no-implicit-backbone-conversion",
        nodes=(
            _SOURCE,
            WorkflowNodeInstance(
                node_id="sink",
                node_type_id="contract_test.backbone_sink",
                node_type_version=VERSION,
                binding_id="contract_test.backbone_sink.direct",
                binding_version=VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source", "structure", "sink", "backbone"),
        ),
        contract_lock=(),
    )

    with pytest.raises(WorkflowCompileError) as rejected:
        compile_workflow(
            relock_workflow(workflow, catalog),
            workflow_revision=1,
            catalog=catalog,
        )

    assert rejected.value.code == "port_type_mismatch"


def test_all_nodes_pass_the_shared_contract_test_kit(
    tmp_path: Path,
) -> None:
    direct_cases = tuple(
        ModulePackageContractCase(
            case_id=f"structure-transform-{operation}",
            node_type_id=f"structure_transform.{operation}",
            node_type_version=VERSION,
            binding_id=f"structure_transform.{operation}.direct",
            binding_version=VERSION,
            node_parameters=(
                {"chain_ids": ["A"]}
                if operation == "select_chains"
                else {}
            ),
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token=f"structure-transform-{operation}-v1",
            workflow_nodes=(_SOURCE,),
            workflow_edges=(_SOURCE_EDGE,),
        )
        for operation in (
            "select_chains",
            "extract_backbone",
            "extract_sequence",
        )
    )
    backbone_node = WorkflowNodeInstance(
        node_id="extract-backbone",
        node_type_id="structure_transform.extract_backbone",
        node_type_version=VERSION,
        binding_id="structure_transform.extract_backbone.direct",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
    )
    bridge_case = ModulePackageContractCase(
        case_id="structure-transform-backbone-to-structure",
        node_type_id="structure_transform.backbone_to_structure",
        node_type_version=VERSION,
        binding_id="structure_transform.backbone_to_structure.direct",
        binding_version=VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="provider-free",
        invalidation_token="structure-transform-backbone-to-structure-v1",
        workflow_nodes=(_SOURCE, backbone_node),
        workflow_edges=(
            WorkflowEdge(
                "source",
                "structure",
                "extract-backbone",
                "structure",
            ),
            WorkflowEdge(
                "extract-backbone",
                "backbone",
                "contract-test-node",
                "backbone",
            ),
        ),
    )
    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=(*direct_cases, bridge_case),
        port_cases=(
            ModulePackagePortCase(
                "structure_transform.backbone_structure",
                VERSION,
                _BACKBONE,
                (
                    ProteinStructure(
                        pdb_string=_BACKBONE.pdb_string.replace(
                            "TER\n",
                            (
                                "ATOM      5  CB  ALA A   1       5.000"
                                "   2.000   3.000  1.00 20.00"
                                "           C\nTER\n"
                            ),
                        ),
                        source=_BACKBONE.source,
                    ),
                    ProteinStructure("END\n"),
                    _MID_RESIDUE_BREAK,
                    _MISSING_CHAIN_BREAK,
                ),
            ),
        ),
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert report.verified_port_types == (
        "structure_transform.backbone_structure@2.0.0",
    )
